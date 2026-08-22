from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import aiosqlite

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .models import MemberStatus, ShiftResult, ShiftStatus
from .settings import SettingsService
from .shift_validation import (
    calculate_patrol_progress_in_tx,
    closed_validation_values,
    countable_shift_clause,
)
from .time_utils import utc_now_ms

LOGGER = logging.getLogger(__name__)


class KeyedLockPool:
    def __init__(self) -> None:
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._refs: defaultdict[tuple[int, int], int] = defaultdict(int)
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def hold(self, key: tuple[int, int]) -> AsyncIterator[None]:
        async with self._guard:
            lock = self._locks.setdefault(key, asyncio.Lock())
            self._refs[key] += 1
        try:
            async with lock:
                yield
        finally:
            async with self._guard:
                self._refs[key] -= 1
                if self._refs[key] <= 0 and not lock.locked():
                    self._refs.pop(key, None)
                    self._locks.pop(key, None)


class ShiftService:
    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit
        self.clock = clock
        self._locks = KeyedLockPool()
        self._grace_tasks: dict[tuple[int, int], asyncio.Task[None]] = {}
        self._state_change_callback: Callable[[int, int, ShiftStatus], Awaitable[None]] | None = (
            None
        )

    def set_state_change_callback(
        self, callback: Callable[[int, int, ShiftStatus], Awaitable[None]]
    ) -> None:
        self._state_change_callback = callback

    async def start_shift(
        self,
        guild_id: int,
        discord_id: int,
        voice_channel_id: int | None,
        *,
        has_authorized_role: bool,
        actor_id: int | None = None,
    ) -> ShiftResult:
        if not has_authorized_role:
            raise ValidationError("Você não possui um cargo autorizado para o serviço.")
        if not await self.settings.is_authorized_voice(guild_id, voice_channel_id):
            raise ValidationError("Entre em uma call autorizada antes de iniciar o serviço.")
        assert voice_channel_id is not None
        counts_toward_patrol = await self.settings.counts_toward_patrol_minimum(
            guild_id, voice_channel_id
        )
        minimum_patrol_ms = await self._minimum_patrol_ms(guild_id)
        now = self.clock()
        key = (guild_id, discord_id)
        async with self._locks.hold(key):
            async with self.database.transaction() as connection:
                member = await self._member_in_tx(connection, guild_id, discord_id)
                if member["status"] != MemberStatus.ACTIVE.value:
                    raise ValidationError("Seu cadastro não está com status Ativo.")
                cursor = await connection.execute(
                    """
                    SELECT id FROM shifts
                    WHERE guild_id=? AND member_id=? AND status IN ('ACTIVE','GRACE')
                    """,
                    (guild_id, member["id"]),
                )
                if await cursor.fetchone():
                    raise ConflictError("Você já possui um ponto ativo.")
                try:
                    shift_cursor = await connection.execute(
                        """
                        INSERT INTO shifts(
                            guild_id, member_id, status, started_at, created_by, created_at,
                            minimum_patrol_ms, validation_status,
                            automatic_validation_status, validation_source
                        ) VALUES (?, ?, 'ACTIVE', ?, ?, ?, ?, 'PENDING', 'PENDING', 'AUTO')
                        """,
                        (
                            guild_id,
                            member["id"],
                            now,
                            actor_id or discord_id,
                            now,
                            minimum_patrol_ms,
                        ),
                    )
                except aiosqlite.IntegrityError as exc:
                    raise ConflictError("Você já possui um ponto ativo.") from exc
                shift_id = int(shift_cursor.lastrowid)
                await connection.execute(
                    """
                    INSERT INTO shift_segments(
                        guild_id, shift_id, voice_channel_id, started_at,
                        counts_toward_patrol_minimum
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (guild_id, shift_id, voice_channel_id, now, int(counts_toward_patrol)),
                )
                await connection.execute(
                    "UPDATE members SET last_activity_at=?, updated_at=? WHERE id=?",
                    (now, now, member["id"]),
                )
                await self.audit.record(
                    guild_id,
                    "SHIFT_STARTED",
                    actor_id=actor_id or discord_id,
                    target_id=discord_id,
                    after={
                        "shift_id": shift_id,
                        "voice_channel_id": voice_channel_id,
                        "minimum_patrol_ms": minimum_patrol_ms,
                        "counts_toward_patrol_minimum": counts_toward_patrol,
                    },
                    connection=connection,
                )
        await self._notify(guild_id, discord_id, ShiftStatus.ACTIVE)
        return ShiftResult(
            shift_id,
            ShiftStatus.ACTIVE,
            now,
            voice_channel_id,
            validation_status="PENDING",
            minimum_patrol_ms=minimum_patrol_ms,
        )

    async def stop_shift(
        self,
        guild_id: int,
        discord_id: int,
        *,
        actor_id: int | None = None,
        reason: str = "MANUAL",
        confirm_short: bool = False,
        expected_shift_id: int | None = None,
    ) -> ShiftResult:
        now = self.clock()
        key = (guild_id, discord_id)
        async with self._locks.hold(key):
            async with self.database.transaction() as connection:
                member = await self._member_in_tx(connection, guild_id, discord_id)
                shift = await self._active_shift_in_tx(connection, guild_id, int(member["id"]))
                if not shift:
                    raise NotFoundError("Você não possui um ponto ativo.")
                if expected_shift_id is not None and int(shift["id"]) != expected_shift_id:
                    raise ConflictError(
                        "A sessão ativa mudou desde a confirmação. Consulte o ponto novamente."
                    )
                valid_end = now
                if shift["status"] == ShiftStatus.GRACE.value:
                    valid_end = int(shift["grace_started_at"] or now)
                progress = await self._patrol_progress_in_tx(
                    connection, int(shift["id"]), valid_end
                )
                if (
                    reason == "MANUAL"
                    and not confirm_short
                    and not bool(progress["requirement_met"])
                ):
                    raise ConflictError(
                        "Confirme a finalização antecipada; esta sessão será invalidada."
                    )
                validation = await self._close_in_tx(
                    connection,
                    shift,
                    guild_id,
                    discord_id,
                    valid_end,
                    reason,
                    actor_id or discord_id,
                    closed_at=now,
                )
            self._cancel_grace(key)
        await self._notify(guild_id, discord_id, ShiftStatus.CLOSED)
        return ShiftResult(
            int(shift["id"]),
            ShiftStatus.CLOSED,
            int(shift["started_at"]),
            None,
            validation_status=str(validation["validation_status"]),
            patrol_duration_ms=int(validation["patrol_duration_ms"]),
            minimum_patrol_ms=int(shift["minimum_patrol_ms"]),
        )

    async def handle_voice_transition(
        self,
        guild_id: int,
        discord_id: int,
        before_channel_id: int | None,
        after_channel_id: int | None,
        *,
        has_authorized_role: bool,
    ) -> ShiftStatus | None:
        member = await self.database.fetchone(
            "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
            (guild_id, discord_id),
        )
        if not member:
            return None
        before_allowed = await self.settings.is_authorized_voice(guild_id, before_channel_id)
        after_allowed = await self.settings.is_authorized_voice(guild_id, after_channel_id)
        now = self.clock()
        key = (guild_id, discord_id)
        schedule: tuple[int, int] | None = None
        status: ShiftStatus | None = None

        async with self._locks.hold(key):
            async with self.database.transaction() as connection:
                shift = await self._active_shift_in_tx(connection, guild_id, int(member["id"]))
                await connection.execute(
                    """
                    INSERT INTO voice_events(
                        guild_id, member_id, shift_id, discord_id, before_channel_id,
                        after_channel_id, event_type, occurred_at, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        member["id"],
                        shift["id"] if shift else None,
                        discord_id,
                        before_channel_id,
                        after_channel_id,
                        "VOICE_STATE_UPDATE",
                        now,
                        json.dumps(
                            {"before_allowed": before_allowed, "after_allowed": after_allowed}
                        ),
                    ),
                )
                if not shift:
                    return None

                if not has_authorized_role:
                    await self._close_in_tx(
                        connection, shift, guild_id, discord_id, now, "ROLE_LOST", discord_id
                    )
                    status = ShiftStatus.CLOSED
                elif shift["status"] == ShiftStatus.ACTIVE.value:
                    if after_allowed and after_channel_id is not None:
                        if after_channel_id != before_channel_id:
                            counts_toward_patrol = await self._channel_counts_patrol_in_tx(
                                connection, guild_id, after_channel_id
                            )
                            await connection.execute(
                                """
                                UPDATE shift_segments SET ended_at=?, end_reason='VOICE_MOVE'
                                WHERE shift_id=? AND ended_at IS NULL
                                """,
                                (now, shift["id"]),
                            )
                            await connection.execute(
                                """
                                INSERT INTO shift_segments(
                                    guild_id, shift_id, voice_channel_id, started_at,
                                    counts_toward_patrol_minimum
                                ) VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    guild_id,
                                    shift["id"],
                                    after_channel_id,
                                    now,
                                    int(counts_toward_patrol),
                                ),
                            )
                            await self.audit.record(
                                guild_id,
                                "SHIFT_VOICE_MOVED",
                                target_id=discord_id,
                                before={"channel_id": before_channel_id},
                                after={"channel_id": after_channel_id},
                                connection=connection,
                            )
                        status = ShiftStatus.ACTIVE
                    else:
                        grace_seconds = int(
                            await self.settings.get(guild_id, "grace_period_seconds", 60)
                        )
                        deadline = now + grace_seconds * 1000
                        await connection.execute(
                            """
                            UPDATE shift_segments SET ended_at=?, end_reason='VOICE_LEFT'
                            WHERE shift_id=? AND ended_at IS NULL
                            """,
                            (now, shift["id"]),
                        )
                        await connection.execute(
                            """
                            UPDATE shifts SET status='GRACE', grace_started_at=?, grace_deadline=?
                            WHERE id=? AND status='ACTIVE'
                            """,
                            (now, deadline, shift["id"]),
                        )
                        await self.audit.record(
                            guild_id,
                            "SHIFT_GRACE_STARTED",
                            target_id=discord_id,
                            after={"shift_id": shift["id"], "deadline": deadline},
                            reason="Saída de call autorizada",
                            connection=connection,
                        )
                        schedule = (int(shift["id"]), deadline)
                        status = ShiftStatus.GRACE
                elif shift["status"] == ShiftStatus.GRACE.value:
                    deadline = int(shift["grace_deadline"] or 0)
                    if after_allowed and after_channel_id is not None and now <= deadline:
                        counts_toward_patrol = await self._channel_counts_patrol_in_tx(
                            connection, guild_id, after_channel_id
                        )
                        await connection.execute(
                            """
                            UPDATE shifts SET status='ACTIVE', grace_started_at=NULL, grace_deadline=NULL
                            WHERE id=? AND status='GRACE'
                            """,
                            (shift["id"],),
                        )
                        await connection.execute(
                            """
                            INSERT INTO shift_segments(
                                guild_id, shift_id, voice_channel_id, started_at,
                                counts_toward_patrol_minimum
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                guild_id,
                                shift["id"],
                                after_channel_id,
                                now,
                                int(counts_toward_patrol),
                            ),
                        )
                        await self.audit.record(
                            guild_id,
                            "SHIFT_GRACE_RESUMED",
                            target_id=discord_id,
                            after={"shift_id": shift["id"], "channel_id": after_channel_id},
                            connection=connection,
                        )
                        status = ShiftStatus.ACTIVE
                    elif now > deadline:
                        await self._close_in_tx(
                            connection,
                            shift,
                            guild_id,
                            discord_id,
                            int(shift["grace_started_at"] or now),
                            "GRACE_EXPIRED",
                            None,
                            closed_at=now,
                        )
                        status = ShiftStatus.CLOSED
                    else:
                        status = ShiftStatus.GRACE

                if status in {ShiftStatus.ACTIVE, ShiftStatus.GRACE}:
                    progress_now = now
                    if status is ShiftStatus.GRACE:
                        progress_now = int(shift["grace_started_at"] or now)
                    await self._refresh_requirement_in_tx(
                        connection,
                        int(shift["id"]),
                        guild_id,
                        discord_id,
                        progress_now,
                    )

            if status != ShiftStatus.GRACE:
                self._cancel_grace(key)
            if schedule:
                self._schedule_grace(key, schedule[0], schedule[1])
        if status:
            await self._notify(guild_id, discord_id, status)
        return status

    async def finalize_role_loss(
        self, guild_id: int, discord_id: int, *, reason: str = "ROLE_LOST"
    ) -> bool:
        try:
            await self.stop_shift(guild_id, discord_id, reason=reason)
        except NotFoundError:
            return False
        return True

    async def expire_grace(
        self, guild_id: int, discord_id: int, shift_id: int, expected_deadline: int
    ) -> bool:
        key = (guild_id, discord_id)
        expired = False
        async with self._locks.hold(key):
            async with self.database.transaction() as connection:
                cursor = await connection.execute(
                    "SELECT * FROM shifts WHERE id=? AND guild_id=?",
                    (shift_id, guild_id),
                )
                shift = await cursor.fetchone()
                if (
                    not shift
                    or shift["status"] != ShiftStatus.GRACE.value
                    or int(shift["grace_deadline"] or 0) != expected_deadline
                ):
                    return False
                member_cursor = await connection.execute(
                    "SELECT discord_id FROM members WHERE id=?", (shift["member_id"],)
                )
                member = await member_cursor.fetchone()
                valid_end = int(shift["grace_started_at"] or self.clock())
                await self._close_in_tx(
                    connection,
                    shift,
                    guild_id,
                    int(member["discord_id"]),
                    valid_end,
                    "GRACE_EXPIRED",
                    None,
                    closed_at=self.clock(),
                )
                expired = True
        if expired:
            await self._notify(guild_id, discord_id, ShiftStatus.CLOSED)
        return expired

    async def patrol_progress(self, guild_id: int, discord_id: int) -> dict[str, object]:
        key = (guild_id, discord_id)
        async with self._locks.hold(key):
            async with self.database.transaction() as connection:
                member = await self._member_in_tx(connection, guild_id, discord_id)
                shift = await self._active_shift_in_tx(connection, guild_id, int(member["id"]))
                if not shift:
                    raise NotFoundError("Você não possui um ponto ativo.")
                effective_now = self.clock()
                if shift["status"] == ShiftStatus.GRACE.value:
                    effective_now = int(shift["grace_started_at"] or effective_now)
                progress = await self._refresh_requirement_in_tx(
                    connection,
                    int(shift["id"]),
                    guild_id,
                    discord_id,
                    effective_now,
                )
        return {
            **progress,
            "shift_id": int(shift["id"]),
            "shift_status": str(shift["status"]),
        }

    async def invalidated_shifts(self, guild_id: int, *, limit: int = 25):
        return await self.database.fetchall(
            """
            SELECT s.*, m.discord_id, m.mta_nick, r.name AS rank_name
            FROM shifts s
            JOIN members m ON m.id=s.member_id
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE s.guild_id=? AND s.status='CLOSED'
              AND s.validation_status='INVALIDATED'
            ORDER BY s.closed_at DESC, s.id DESC LIMIT ?
            """,
            (guild_id, limit),
        )

    async def validate_manually(
        self,
        guild_id: int,
        shift_id: int,
        actor_id: int,
        reason: str,
    ) -> dict[str, object]:
        reason = reason.strip()
        if not reason:
            raise ValidationError("Informe o motivo da validação excepcional.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT s.*, m.discord_id FROM shifts s
                JOIN members m ON m.id=s.member_id
                WHERE s.guild_id=? AND s.id=?
                """,
                (guild_id, shift_id),
            )
            shift = await cursor.fetchone()
            if not shift:
                raise NotFoundError("Sessão não encontrada.")
            if shift["status"] != "CLOSED" or shift["validation_status"] != "INVALIDATED":
                raise ConflictError("Somente uma sessão encerrada e invalidada pode ser validada.")
            cursor = await connection.execute(
                """
                UPDATE shifts
                SET validation_status='VALID', validation_source='ADMIN_OVERRIDE',
                    validated_by=?, validated_at=?, validation_reason=?
                WHERE guild_id=? AND id=? AND validation_status='INVALIDATED'
                """,
                (actor_id, now, reason, guild_id, shift_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A sessão foi revisada simultaneamente.")
            await connection.execute(
                """
                INSERT INTO shift_validation_overrides(
                    guild_id, shift_id, actor_id, previous_validation_status,
                    resulting_validation_status, reason, created_at
                ) VALUES (?, ?, ?, 'INVALIDATED', 'VALID', ?, ?)
                """,
                (guild_id, shift_id, actor_id, reason, now),
            )
            await self.audit.record(
                guild_id,
                "SHIFT_VALIDATED_MANUALLY",
                actor_id=actor_id,
                target_id=int(shift["discord_id"]),
                before={
                    "validation_status": "INVALIDATED",
                    "automatic_validation_status": shift["automatic_validation_status"],
                    "patrol_duration_ms": int(shift["patrol_duration_ms"]),
                    "minimum_patrol_ms": int(shift["minimum_patrol_ms"]),
                },
                after={
                    "validation_status": "VALID",
                    "validation_source": "ADMIN_OVERRIDE",
                    "shift_id": shift_id,
                },
                reason=reason,
                connection=connection,
            )
        return {
            "shift_id": shift_id,
            "discord_id": int(shift["discord_id"]),
            "validation_status": "VALID",
            "validation_source": "ADMIN_OVERRIDE",
            "reason": reason,
        }

    async def adjust_shift(
        self,
        guild_id: int,
        shift_id: int,
        minutes: int,
        actor_id: int,
        reason: str,
    ) -> None:
        if minutes == 0:
            raise ValidationError("O ajuste não pode ser zero.")
        if not reason.strip():
            raise ValidationError("Informe o motivo do ajuste.")
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT s.*, m.discord_id FROM shifts s
                JOIN members m ON m.id=s.member_id
                WHERE s.id=? AND s.guild_id=?
                """,
                (shift_id, guild_id),
            )
            shift = await cursor.fetchone()
            if not shift:
                raise NotFoundError("Sessão não encontrada.")
            await connection.execute(
                """
                INSERT INTO shift_adjustments(
                    guild_id, shift_id, delta_ms, reason, actor_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (guild_id, shift_id, minutes * 60_000, reason, actor_id, self.clock()),
            )
            await self.audit.record(
                guild_id,
                "SHIFT_TIME_ADJUSTED",
                actor_id=actor_id,
                target_id=int(shift["discord_id"]),
                after={"shift_id": shift_id, "delta_minutes": minutes},
                reason=reason,
                connection=connection,
            )

    async def review_shift(
        self,
        guild_id: int,
        shift_id: int,
        action: str,
        actor_id: int,
        reason: str,
        voice_channel_id: int | None = None,
    ) -> ShiftStatus:
        action = action.upper()
        if action not in {"CONFIRMAR", "CONTINUAR"}:
            raise ValidationError("A ação deve ser confirmar ou continuar.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT s.*, m.discord_id FROM shifts s JOIN members m ON m.id=s.member_id
                WHERE s.id=? AND s.guild_id=?
                """,
                (shift_id, guild_id),
            )
            shift = await cursor.fetchone()
            if not shift:
                raise NotFoundError("Sessão não encontrada.")
            if shift["status"] != ShiftStatus.REVIEW_REQUIRED.value:
                raise ConflictError("Essa sessão não está aguardando revisão.")
            if action == "CONTINUAR":
                if not await self.settings.is_authorized_voice(guild_id, voice_channel_id):
                    raise ValidationError("O membro precisa estar em uma call autorizada.")
                assert voice_channel_id is not None
                counts_toward_patrol = await self._channel_counts_patrol_in_tx(
                    connection, guild_id, voice_channel_id
                )
                await connection.execute(
                    """
                    UPDATE shifts SET status='ACTIVE', ended_at=NULL, closed_at=NULL,
                        end_reason=NULL, validation_status='PENDING',
                        automatic_validation_status='PENDING', invalid_reason=NULL
                    WHERE id=?
                    """,
                    (shift_id,),
                )
                await connection.execute(
                    """
                    INSERT INTO shift_segments(
                        guild_id, shift_id, voice_channel_id, started_at,
                        counts_toward_patrol_minimum
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        shift_id,
                        voice_channel_id,
                        now,
                        int(counts_toward_patrol),
                    ),
                )
                await self._refresh_requirement_in_tx(
                    connection, shift_id, guild_id, int(shift["discord_id"]), now
                )
                status = ShiftStatus.ACTIVE
            else:
                effective_end = int(shift["ended_at"] or now)
                progress = await self._patrol_progress_in_tx(
                    connection, shift_id, effective_end
                )
                requirement_met = bool(progress["requirement_met"])
                validation_status = "VALID" if requirement_met else "INVALIDATED"
                await connection.execute(
                    """
                    UPDATE shifts SET status='CLOSED', closed_at=?,
                        end_reason='RECOVERY_CONFIRMED',
                        gross_duration_ms=?, patrol_duration_ms=?,
                        patrol_requirement_met_at=?, validation_status=?,
                        automatic_validation_status=?, invalid_reason=?,
                        validation_source='AUTO', validated_at=?
                    WHERE id=? AND status='REVIEW_REQUIRED'
                    """,
                    (
                        now,
                        max(0, effective_end - int(shift["started_at"])),
                        int(progress["patrol_duration_ms"]),
                        progress["requirement_met_at"],
                        validation_status,
                        validation_status,
                        None
                        if requirement_met
                        else "MINIMUM_PATROL_TIME_NOT_REACHED",
                        now,
                        shift_id,
                    ),
                )
                status = ShiftStatus.CLOSED
            await self.audit.record(
                guild_id,
                "SHIFT_REVIEWED",
                actor_id=actor_id,
                target_id=int(shift["discord_id"]),
                before={"status": ShiftStatus.REVIEW_REQUIRED.value},
                after={
                    "status": status.value,
                    "action": action,
                    "validation_status": (
                        validation_status if action == "CONFIRMAR" else "PENDING"
                    ),
                },
                reason=reason,
                connection=connection,
            )
        await self._notify(
            guild_id,
            int(shift["discord_id"]),
            status,
        )
        return status

    async def get_active(self, guild_id: int, discord_id: int):
        return await self.database.fetchone(
            """
            SELECT s.*, m.discord_id,
                   (SELECT voice_channel_id FROM shift_segments ss
                    WHERE ss.shift_id=s.id AND ss.ended_at IS NULL LIMIT 1) AS voice_channel_id
            FROM shifts s JOIN members m ON m.id=s.member_id
            WHERE s.guild_id=? AND m.discord_id=? AND s.status IN ('ACTIVE','GRACE')
            """,
            (guild_id, discord_id),
        )

    async def list_active(self, guild_id: int):
        return await self.database.fetchall(
            """
            SELECT s.*, m.discord_id, m.mta_nick, r.name AS rank_name,
                   (SELECT voice_channel_id FROM shift_segments ss
                    WHERE ss.shift_id=s.id AND ss.ended_at IS NULL LIMIT 1) AS voice_channel_id,
                   COALESCE((SELECT SUM(COALESCE(ss2.ended_at, ?) - ss2.started_at)
                             FROM shift_segments ss2 WHERE ss2.shift_id=s.id), 0)
                   + COALESCE((SELECT SUM(sa.delta_ms) FROM shift_adjustments sa
                               WHERE sa.shift_id=s.id), 0) AS total_ms
            FROM shifts s JOIN members m ON m.id=s.member_id
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE s.guild_id=? AND s.status IN ('ACTIVE','GRACE')
            ORDER BY s.started_at
            """,
            (self.clock(), guild_id),
        )

    async def history(self, guild_id: int, discord_id: int, limit: int = 10, offset: int = 0):
        return await self.database.fetchall(
            """
            SELECT s.*,
                COALESCE((SELECT SUM(COALESCE(ss.ended_at, ?) - ss.started_at)
                          FROM shift_segments ss WHERE ss.shift_id=s.id), 0)
                + COALESCE((SELECT SUM(sa.delta_ms) FROM shift_adjustments sa
                            WHERE sa.shift_id=s.id), 0) AS total_ms
            FROM shifts s JOIN members m ON m.id=s.member_id
            WHERE s.guild_id=? AND m.discord_id=?
            ORDER BY s.id DESC LIMIT ? OFFSET ?
            """,
            (self.clock(), guild_id, discord_id, limit, offset),
        )

    async def total_for_member(
        self,
        guild_id: int,
        discord_id: int,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> int:
        now = self.clock()
        lower = start_ms if start_ms is not None else 0
        upper = end_ms if end_ms is not None else now
        countable = countable_shift_clause()
        row = await self.database.fetchone(
            f"""
            SELECT
              COALESCE(SUM(
                MAX(0, MIN(COALESCE(ss.ended_at, ?), ?) - MAX(ss.started_at, ?))
              ), 0) AS segment_ms
            FROM shift_segments ss
            JOIN shifts s ON s.id=ss.shift_id
            JOIN members m ON m.id=s.member_id
            WHERE s.guild_id=? AND m.discord_id=? AND {countable}
              AND ss.started_at < ? AND COALESCE(ss.ended_at, ?) > ?
            """,
            (now, upper, lower, guild_id, discord_id, now, upper, now, lower),
        )
        adjustment = await self.database.fetchone(
            f"""
            SELECT COALESCE(SUM(sa.delta_ms), 0) AS adjustment_ms
            FROM shift_adjustments sa
            JOIN shifts s ON s.id=sa.shift_id
            JOIN members m ON m.id=s.member_id
            WHERE s.guild_id=? AND m.discord_id=? AND {countable}
              AND s.started_at >= ? AND s.started_at < ?
            """,
            (guild_id, discord_id, now, lower, upper),
        )
        return max(0, int(row["segment_ms"]) + int(adjustment["adjustment_ms"]))

    async def recover_shift(
        self,
        guild_id: int,
        discord_id: int,
        current_channel_id: int | None,
        last_heartbeat_at: int,
    ) -> ShiftStatus | None:
        shift = await self.get_active(guild_id, discord_id)
        if not shift:
            return None
        now = self.clock()
        current_allowed = await self.settings.is_authorized_voice(guild_id, current_channel_id)
        key = (guild_id, discord_id)
        schedule: tuple[int, int] | None = None
        async with self._locks.hold(key):
            async with self.database.transaction() as connection:
                cursor = await connection.execute("SELECT * FROM shifts WHERE id=?", (shift["id"],))
                current = await cursor.fetchone()
                if not current or current["status"] not in {"ACTIVE", "GRACE"}:
                    return None
                if current["status"] == "GRACE":
                    deadline = int(current["grace_deadline"] or 0)
                    if current_allowed and current_channel_id is not None and now <= deadline:
                        counts_toward_patrol = await self._channel_counts_patrol_in_tx(
                            connection, guild_id, current_channel_id
                        )
                        await connection.execute(
                            "UPDATE shifts SET status='ACTIVE', grace_started_at=NULL, grace_deadline=NULL WHERE id=?",
                            (current["id"],),
                        )
                        await connection.execute(
                            """
                            INSERT INTO shift_segments(
                                guild_id, shift_id, voice_channel_id, started_at,
                                counts_toward_patrol_minimum
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                guild_id,
                                current["id"],
                                current_channel_id,
                                now,
                                int(counts_toward_patrol),
                            ),
                        )
                        status = ShiftStatus.ACTIVE
                    elif now <= deadline:
                        schedule = (int(current["id"]), deadline)
                        status = ShiftStatus.GRACE
                    else:
                        await self._close_in_tx(
                            connection,
                            current,
                            guild_id,
                            discord_id,
                            int(current["grace_started_at"] or last_heartbeat_at),
                            "GRACE_EXPIRED_DURING_RESTART",
                            None,
                            closed_at=now,
                        )
                        status = ShiftStatus.CLOSED
                else:
                    open_cursor = await connection.execute(
                        "SELECT * FROM shift_segments WHERE shift_id=? AND ended_at IS NULL",
                        (current["id"],),
                    )
                    segment = await open_cursor.fetchone()
                    if (
                        current_allowed
                        and current_channel_id is not None
                        and segment
                        and int(segment["voice_channel_id"]) == current_channel_id
                    ):
                        status = ShiftStatus.ACTIVE
                    elif current_allowed and current_channel_id is not None:
                        counts_toward_patrol = await self._channel_counts_patrol_in_tx(
                            connection, guild_id, current_channel_id
                        )
                        await connection.execute(
                            "UPDATE shift_segments SET ended_at=?, end_reason='RESTART_CHANNEL_CHANGED' WHERE shift_id=? AND ended_at IS NULL",
                            (last_heartbeat_at, current["id"]),
                        )
                        await connection.execute(
                            """
                            INSERT INTO shift_segments(
                                guild_id, shift_id, voice_channel_id, started_at,
                                counts_toward_patrol_minimum
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                guild_id,
                                current["id"],
                                current_channel_id,
                                now,
                                int(counts_toward_patrol),
                            ),
                        )
                        status = ShiftStatus.ACTIVE
                    else:
                        await connection.execute(
                            "UPDATE shift_segments SET ended_at=?, end_reason='RESTART_UNKNOWN' WHERE shift_id=? AND ended_at IS NULL",
                            (last_heartbeat_at, current["id"]),
                        )
                        await connection.execute(
                            """
                            UPDATE shifts SET status='REVIEW_REQUIRED', ended_at=?, closed_at=?,
                                end_reason='RESTART_UNKNOWN',
                                validation_status='REVIEW_REQUIRED',
                                automatic_validation_status='REVIEW_REQUIRED'
                            WHERE id=? AND status='ACTIVE'
                            """,
                            (last_heartbeat_at, now, current["id"]),
                        )
                        status = ShiftStatus.REVIEW_REQUIRED
                if status in {ShiftStatus.ACTIVE, ShiftStatus.GRACE}:
                    progress_now = now
                    if status is ShiftStatus.GRACE:
                        progress_now = int(current["grace_started_at"] or now)
                    await self._refresh_requirement_in_tx(
                        connection,
                        int(current["id"]),
                        guild_id,
                        discord_id,
                        progress_now,
                    )
                await self.audit.record(
                    guild_id,
                    "SHIFT_RECOVERED",
                    target_id=discord_id,
                    before={"status": current["status"]},
                    after={"status": status.value, "current_channel_id": current_channel_id},
                    connection=connection,
                )
            if schedule:
                self._schedule_grace(key, schedule[0], schedule[1])
        await self._notify(guild_id, discord_id, status)
        return status

    async def get_previous_heartbeat(self, guild_id: int) -> int:
        row = await self.database.fetchone(
            "SELECT last_heartbeat_at FROM bot_runtime WHERE guild_id=?", (guild_id,)
        )
        return int(row["last_heartbeat_at"]) if row else self.clock()

    async def heartbeat(self, guild_id: int, started_at: int) -> None:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT s.id, s.status, s.grace_started_at, m.discord_id
                FROM shifts s JOIN members m ON m.id=s.member_id
                WHERE s.guild_id=? AND s.status IN ('ACTIVE','GRACE')
                  AND s.validation_status='PENDING'
                """,
                (guild_id,),
            )
            for shift in await cursor.fetchall():
                effective_now = (
                    int(shift["grace_started_at"] or now)
                    if shift["status"] == ShiftStatus.GRACE.value
                    else now
                )
                await self._refresh_requirement_in_tx(
                    connection,
                    int(shift["id"]),
                    guild_id,
                    int(shift["discord_id"]),
                    effective_now,
                )
            await connection.execute(
                """
                INSERT INTO bot_runtime(guild_id, last_heartbeat_at, started_at, clean_shutdown)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(guild_id) DO UPDATE SET
                    last_heartbeat_at=excluded.last_heartbeat_at,
                    started_at=excluded.started_at,
                    clean_shutdown=0
                """,
                (guild_id, now, started_at),
            )

    async def close(self) -> None:
        tasks = list(self._grace_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._grace_tasks.clear()

    async def _member_in_tx(self, connection: aiosqlite.Connection, guild_id: int, discord_id: int):
        cursor = await connection.execute(
            "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
            (guild_id, discord_id),
        )
        member = await cursor.fetchone()
        if not member:
            raise NotFoundError("Você ainda não está cadastrado na corporação.")
        return member

    async def _active_shift_in_tx(
        self, connection: aiosqlite.Connection, guild_id: int, member_id: int
    ):
        cursor = await connection.execute(
            """
            SELECT * FROM shifts
            WHERE guild_id=? AND member_id=? AND status IN ('ACTIVE','GRACE')
            ORDER BY id DESC LIMIT 1
            """,
            (guild_id, member_id),
        )
        return await cursor.fetchone()

    async def _minimum_patrol_ms(self, guild_id: int) -> int:
        value = int(await self.settings.get(guild_id, "minimum_patrol_minutes", 15))
        if value == 0:
            return 0
        if not 5 <= value <= 120:
            LOGGER.warning(
                "Tempo mínimo de patrulha inválido na guild %s: %s; usando 15",
                guild_id,
                value,
            )
            value = 15
        return value * 60_000

    async def _channel_counts_patrol_in_tx(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        channel_id: int,
    ) -> bool:
        cursor = await connection.execute(
            """
            SELECT counts_toward_patrol_minimum
            FROM authorized_voice_channels
            WHERE guild_id=? AND channel_id=? AND service_allowed=1
            """,
            (guild_id, channel_id),
        )
        row = await cursor.fetchone()
        return bool(row and int(row["counts_toward_patrol_minimum"]))

    async def _patrol_progress_in_tx(
        self,
        connection: aiosqlite.Connection,
        shift_id: int,
        effective_now: int,
    ) -> dict[str, int | bool | None]:
        return await calculate_patrol_progress_in_tx(connection, shift_id, effective_now)

    async def _refresh_requirement_in_tx(
        self,
        connection: aiosqlite.Connection,
        shift_id: int,
        guild_id: int,
        discord_id: int,
        effective_now: int,
    ) -> dict[str, int | bool | None]:
        progress = await self._patrol_progress_in_tx(connection, shift_id, effective_now)
        cursor = await connection.execute(
            """
            UPDATE shifts
            SET patrol_duration_ms=?, patrol_requirement_met_at=?,
                validation_status='VALID', automatic_validation_status='VALID',
                validation_source='AUTO', validated_at=?
            WHERE id=? AND validation_status='PENDING' AND ?=1
            """,
            (
                int(progress["patrol_duration_ms"]),
                progress["requirement_met_at"],
                progress["requirement_met_at"] or effective_now,
                shift_id,
                int(bool(progress["requirement_met"])),
            ),
        )
        if cursor.rowcount == 1:
            await self.audit.record(
                guild_id,
                "SHIFT_MINIMUM_PATROL_REACHED",
                target_id=discord_id,
                after={
                    "shift_id": shift_id,
                    "patrol_duration_ms": int(progress["patrol_duration_ms"]),
                    "minimum_patrol_ms": int(progress["minimum_patrol_ms"]),
                    "requirement_met_at": progress["requirement_met_at"],
                },
                connection=connection,
            )
        elif not progress["requirement_met"]:
            await connection.execute(
                "UPDATE shifts SET patrol_duration_ms=? WHERE id=?",
                (int(progress["patrol_duration_ms"]), shift_id),
            )
        return progress

    async def _close_in_tx(
        self,
        connection: aiosqlite.Connection,
        shift,
        guild_id: int,
        discord_id: int,
        valid_end: int,
        reason: str,
        actor_id: int | None,
        *,
        closed_at: int | None = None,
    ) -> dict[str, int | str | None]:
        await connection.execute(
            """
            UPDATE shift_segments SET ended_at=?, end_reason=?
            WHERE shift_id=? AND ended_at IS NULL
            """,
            (valid_end, reason, shift["id"]),
        )
        validation = await closed_validation_values(connection, shift, valid_end)
        patrol_duration_ms = int(validation["patrol_duration_ms"])
        minimum_patrol_ms = int(validation["minimum_patrol_ms"])
        validation_status = str(validation["validation_status"])
        invalid_reason = validation["invalid_reason"]
        finalized_at = closed_at or self.clock()
        cursor = await connection.execute(
            """
            UPDATE shifts SET status='CLOSED', ended_at=?, closed_at=?, end_reason=?,
                grace_started_at=NULL, grace_deadline=NULL,
                gross_duration_ms=?, patrol_duration_ms=?, patrol_requirement_met_at=?,
                validation_status=?, automatic_validation_status=?, invalid_reason=?,
                validation_source='AUTO', validated_at=?
            WHERE id=? AND status IN ('ACTIVE','GRACE')
            """,
            (
                valid_end,
                finalized_at,
                reason,
                validation["gross_duration_ms"],
                patrol_duration_ms,
                validation["patrol_requirement_met_at"],
                validation_status,
                validation_status,
                invalid_reason,
                finalized_at,
                shift["id"],
            ),
        )
        if cursor.rowcount != 1:
            raise ConflictError("O ponto já foi finalizado por outro evento.")
        await self.audit.record(
            guild_id,
            "SHIFT_CLOSED",
            actor_id=actor_id,
            target_id=discord_id,
            before={"status": shift["status"]},
            after={
                "status": "CLOSED",
                "shift_id": shift["id"],
                "ended_at": valid_end,
                "validation_status": validation_status,
                "patrol_duration_ms": patrol_duration_ms,
                "minimum_patrol_ms": minimum_patrol_ms,
                "invalid_reason": invalid_reason,
            },
            reason=reason,
            connection=connection,
        )
        return {
            "validation_status": validation_status,
            "patrol_duration_ms": patrol_duration_ms,
            "minimum_patrol_ms": minimum_patrol_ms,
            "patrol_requirement_met_at": validation["patrol_requirement_met_at"],
            "invalid_reason": invalid_reason,
        }

    def _schedule_grace(self, key: tuple[int, int], shift_id: int, deadline: int) -> None:
        self._cancel_grace(key)

        async def runner() -> None:
            try:
                delay = max(0, (deadline - self.clock()) / 1000)
                await asyncio.sleep(delay)
                await self.expire_grace(key[0], key[1], shift_id, deadline)
            except asyncio.CancelledError:
                raise
            finally:
                current = self._grace_tasks.get(key)
                if current is asyncio.current_task():
                    self._grace_tasks.pop(key, None)

        self._grace_tasks[key] = asyncio.create_task(
            runner(), name=f"shift-grace-{key[0]}-{key[1]}"
        )

    def _cancel_grace(self, key: tuple[int, int]) -> None:
        task = self._grace_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

    async def _notify(self, guild_id: int, discord_id: int, status: ShiftStatus) -> None:
        if not self._state_change_callback:
            return
        try:
            await self._state_change_callback(guild_id, discord_id, status)
        except Exception:
            LOGGER.exception("Falha no callback de mudança do ponto")
