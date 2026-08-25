from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import aiosqlite

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .models import ShiftStatus
from .settings import SettingsService
from .shifts import ShiftService
from .time_utils import utc_now_ms

if TYPE_CHECKING:
    from .operations import OperationsService


DEFAULT_OCCURRENCE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("ABANDONO_PTR", "Abandono de PTR"),
    ("AUSENCIA_INJUSTIFICADA", "Ausência injustificada"),
    ("ATRASO", "Atraso"),
    ("PROCEDIMENTO", "Descumprimento de procedimento"),
    ("CONDUTA", "Conduta inadequada"),
    ("ERRO_OPERACIONAL", "Erro operacional"),
    ("DESLIGAMENTO_CALL", "Desligamento da call"),
    ("PERDA_PATRULHA", "Perda da patrulha"),
    ("OUTRA", "Outra ocorrência"),
)


class DutyPatrolService:
    """Coordinates Discord voice presence, official shifts and durable vehicles.

    Discord is authoritative only for current presence. SQLite remains the
    source of history and all actions are recoverable after a process restart.
    """

    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
        shifts: ShiftService,
        operations: OperationsService,
        *,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit
        self.shifts = shifts
        self.operations = operations
        self.clock = clock
        self._guild_locks: dict[int, asyncio.Lock] = {}

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._guild_locks.setdefault(guild_id, asyncio.Lock())

    async def _active_channel(self, guild_id: int, channel_id: int | None):
        if channel_id is None:
            return None
        return await self.database.fetchone(
            """
            SELECT * FROM patrol_channels
            WHERE guild_id=? AND channel_id=? AND channel_type='ACTIVE' AND enabled=1
            """,
            (guild_id, channel_id),
        )

    async def _modules_allow_new_duty(self, guild_id: int) -> bool:
        if not bool(
            await self.settings.get(guild_id, "automatic_patrol_clock_enabled", True)
        ):
            return False
        flags = await self.settings.get(guild_id, "module_flags", {})
        if isinstance(flags, dict) and (
            flags.get("POINT") is False or flags.get("PATROLS") is False
        ):
            return False
        return not bool(await self.operations.maintenance_state(guild_id, "PATROLS"))

    async def handle_voice_transition(
        self,
        guild_id: int,
        discord_id: int,
        before_channel_id: int | None,
        after_channel_id: int | None,
        *,
        has_authorized_role: bool,
        role_snapshot: str | None = None,
        role_ids: Iterable[int] = (),
    ) -> dict[str, object]:
        """Process one voice transition exactly once for shifts and vehicles."""
        async with self._lock(guild_id):
            before_patrol = await self._active_channel(guild_id, before_channel_id)
            after_patrol = await self._active_channel(guild_id, after_channel_id)
            active_shift = await self.shifts.get_active(guild_id, discord_id)
            shift_status: ShiftStatus | None = None
            opened = False

            if after_patrol and bool(after_patrol["automatic_clock"]):
                if not has_authorized_role or not await self._modules_allow_new_duty(guild_id):
                    if active_shift:
                        shift_status = await self.shifts.handle_voice_transition(
                            guild_id,
                            discord_id,
                            before_channel_id,
                            after_channel_id,
                            has_authorized_role=has_authorized_role,
                            before_allowed_override=bool(before_patrol),
                            after_allowed_override=False,
                        )
                elif not active_shift:
                    result = await self.shifts.start_shift(
                        guild_id,
                        discord_id,
                        after_channel_id,
                        has_authorized_role=True,
                        source="VOICE_AUTO",
                        role_snapshot=role_snapshot,
                    )
                    active_shift = await self.shifts.get_active(guild_id, discord_id)
                    shift_status = result.status
                    opened = True
                else:
                    shift_status = await self.shifts.handle_voice_transition(
                        guild_id,
                        discord_id,
                        before_channel_id,
                        after_channel_id,
                        has_authorized_role=True,
                        before_allowed_override=bool(before_patrol),
                        after_allowed_override=True,
                    )
                    active_shift = await self.shifts.get_active(guild_id, discord_id)
            elif active_shift:
                shift_status = await self.shifts.handle_voice_transition(
                    guild_id,
                    discord_id,
                    before_channel_id,
                    after_channel_id,
                    has_authorized_role=has_authorized_role,
                    before_allowed_override=(True if before_patrol else None),
                    after_allowed_override=(False if before_patrol else None),
                )
                active_shift = await self.shifts.get_active(guild_id, discord_id)

            left: dict[str, object] | None = None
            if before_patrol and before_channel_id != after_channel_id:
                left = await self._leave_vehicle(
                    guild_id, discord_id, int(before_channel_id), reason="VOICE_TRANSITION"
                )

            vehicle: dict[str, object] | None = None
            if after_patrol and active_shift and shift_status is not ShiftStatus.CLOSED:
                vehicle = await self.ensure_voice_vehicle(
                    guild_id,
                    discord_id,
                    int(after_channel_id),
                    int(active_shift["id"]),
                    role_ids=role_ids,
                    source="VOICE_AUTO" if opened else "RECOVERY",
                )

            if left and vehicle and before_patrol and after_patrol:
                member = await self.database.fetchone(
                    "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
                    (guild_id, discord_id),
                )
                async with self.database.transaction() as connection:
                    await self._composition_event(
                        connection,
                        guild_id,
                        int(left["patrol_id"]),
                        "MEMBER_MOVED",
                        event_key=(
                            f"vehicle:{left['patrol_id']}:member:{discord_id}:"
                            f"move:{vehicle['patrol_id']}"
                        ),
                        member_id=int(member["id"]) if member else None,
                        discord_id=discord_id,
                        before_channel_id=int(before_channel_id),
                        after_channel_id=int(after_channel_id),
                        reason="VOICE_PATROL_TRANSFER",
                        metadata={"next_patrol_id": int(vehicle["patrol_id"])},
                    )
                    await self.audit.record(
                        guild_id,
                        "PATROL_VEHICLE_MEMBER_MOVED",
                        target_id=discord_id,
                        before={
                            "patrol_id": int(left["patrol_id"]),
                            "voice_channel_id": int(before_channel_id),
                        },
                        after={
                            "patrol_id": int(vehicle["patrol_id"]),
                            "voice_channel_id": int(after_channel_id),
                        },
                        connection=connection,
                    )

            return {
                "opened": opened,
                "shift_status": shift_status.value if shift_status else None,
                "shift_id": int(active_shift["id"]) if active_shift else None,
                "vehicle": vehicle,
                "left": left,
            }

    async def ensure_voice_vehicle(
        self,
        guild_id: int,
        discord_id: int,
        voice_channel_id: int,
        shift_id: int,
        *,
        role_ids: Iterable[int] = (),
        source: str = "VOICE_AUTO",
    ) -> dict[str, object]:
        source = source.strip().upper()
        if source not in {"VOICE_AUTO", "RECOVERY"}:
            raise ValidationError("Origem automática da viatura inválida.")
        channel = await self._active_channel(guild_id, voice_channel_id)
        if not channel:
            raise ValidationError("A call não está configurada como patrulha ativa.")
        allowed_roles = {
            int(value)
            for value in json.loads(str(channel["allowed_role_ids_json"] or "[]"))
            if str(value).isdigit()
        }
        given_roles = {int(value) for value in role_ids}
        if allowed_roles and not allowed_roles.intersection(given_roles):
            raise ValidationError("Seus cargos não permitem integrar esta viatura.")
        now = self.clock()
        created = False
        joined = False
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT m.*, r.name AS rank_name FROM members m
                LEFT JOIN ranks r ON r.id=m.rank_id
                WHERE m.guild_id=? AND m.discord_id=?
                """,
                (guild_id, discord_id),
            )
            member = await cursor.fetchone()
            if not member or member["status"] != "ACTIVE" or member["rank_id"] is None:
                raise ValidationError("Somente militar ativo e identificado pode integrar viatura.")
            cursor = await connection.execute(
                """
                SELECT * FROM patrols
                WHERE guild_id=? AND voice_channel_id=?
                  AND status IN ('RESERVED','ACTIVE')
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, voice_channel_id),
            )
            patrol = await cursor.fetchone()
            if patrol and patrol["status"] == "RESERVED":
                return {
                    "patrol_id": int(patrol["id"]),
                    "vehicle_number": int(patrol["sequence_number"]),
                    "created": False,
                    "joined": False,
                    "reserved": True,
                }
            if not patrol:
                cursor = await connection.execute(
                    "SELECT COALESCE(MAX(sequence_number), 0) AS value FROM patrols WHERE guild_id=?",
                    (guild_id,),
                )
                sequence = int((await cursor.fetchone())["value"]) + 1
                cursor = await connection.execute(
                    """
                    INSERT INTO patrols(
                        guild_id, sequence_number, voice_channel_id, status, origin,
                        minimum_members, continue_until_empty, reserved_at, started_at,
                        created_at, updated_at, creation_source
                    ) VALUES (?, ?, ?, 'ACTIVE', 'AUTO', 1, 1, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        sequence,
                        voice_channel_id,
                        now,
                        now,
                        now,
                        now,
                        source,
                    ),
                )
                patrol_id = int(cursor.lastrowid)
                cursor = await connection.execute("SELECT * FROM patrols WHERE id=?", (patrol_id,))
                patrol = await cursor.fetchone()
                created = True
                await self._composition_event(
                    connection,
                    guild_id,
                    patrol_id,
                    "VEHICLE_CREATED",
                    event_key=f"vehicle:{patrol_id}:created",
                    after_channel_id=voice_channel_id,
                    reason=source,
                )
            assert patrol is not None
            cursor = await connection.execute(
                """
                SELECT pm.id FROM patrol_members pm JOIN patrols p ON p.id=pm.patrol_id
                WHERE pm.guild_id=? AND pm.member_id=? AND pm.status IN ('RESERVED','ACTIVE')
                  AND p.status IN ('RESERVED','ACTIVE') AND p.id<>?
                LIMIT 1
                """,
                (guild_id, member["id"], patrol["id"]),
            )
            if await cursor.fetchone():
                raise ConflictError("O militar ainda está vinculado a outra viatura ativa.")
            cursor = await connection.execute(
                "SELECT status FROM patrol_members WHERE patrol_id=? AND member_id=?",
                (patrol["id"], member["id"]),
            )
            previous = await cursor.fetchone()
            is_new_presence = not previous or str(previous["status"]) != "ACTIVE"
            if is_new_presence:
                capacity = int(channel["capacity"] or 0)
                if capacity:
                    cursor = await connection.execute(
                        "SELECT COUNT(*) AS total FROM patrol_members WHERE patrol_id=? AND status='ACTIVE'",
                        (patrol["id"],),
                    )
                    if int((await cursor.fetchone())["total"]) >= capacity:
                        raise ConflictError("A viatura atingiu a capacidade configurada.")
                await connection.execute(
                    """
                    INSERT INTO patrol_members(
                        guild_id, patrol_id, member_id, discord_id, member_role,
                        status, reserved_at, joined_at, left_at, associated_shift_id
                    ) VALUES (?, ?, ?, ?, 'MEMBER', 'ACTIVE', ?, ?, NULL, ?)
                    ON CONFLICT(patrol_id, member_id) DO UPDATE SET
                        status='ACTIVE', joined_at=excluded.joined_at, left_at=NULL,
                        associated_shift_id=excluded.associated_shift_id, member_role='MEMBER'
                    """,
                    (
                        guild_id,
                        patrol["id"],
                        member["id"],
                        discord_id,
                        now,
                        now,
                        shift_id,
                    ),
                )
                joined = True
                await self._composition_event(
                    connection,
                    guild_id,
                    int(patrol["id"]),
                    "MEMBER_JOINED",
                    event_key=f"vehicle:{patrol['id']}:member:{member['id']}:join:{now}",
                    member_id=int(member["id"]),
                    discord_id=discord_id,
                    after_channel_id=voice_channel_id,
                    reason=source,
                )
                await self.audit.record(
                    guild_id,
                    "PATROL_VEHICLE_MEMBER_JOINED",
                    target_id=discord_id,
                    after={
                        "patrol_id": int(patrol["id"]),
                        "shift_id": shift_id,
                        "voice_channel_id": voice_channel_id,
                    },
                    connection=connection,
                )
            await connection.execute(
                "UPDATE shifts SET current_patrol_id=?, version=version+1 WHERE id=?",
                (patrol["id"], shift_id),
            )
        commander = await self.operations.select_patrol_commander(
            guild_id,
            int(patrol["id"]),
            None,
            reason="VEHICLE_CREATED" if created else "MEMBER_JOINED",
        )
        return {
            "patrol_id": int(patrol["id"]),
            "vehicle_number": int(patrol["sequence_number"]),
            "created": created,
            "joined": joined,
            "reserved": False,
            "commander_discord_id": commander.get("commander_discord_id"),
        }

    async def _leave_vehicle(
        self, guild_id: int, discord_id: int, voice_channel_id: int, *, reason: str
    ) -> dict[str, object] | None:
        now = self.clock()
        result = await self.operations.mark_patrol_member_left(
            guild_id, discord_id, voice_channel_id
        )
        if not result:
            return None
        member = await self.database.fetchone(
            "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
            (guild_id, discord_id),
        )
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                UPDATE shifts SET current_patrol_id=NULL, version=version+1
                WHERE guild_id=? AND member_id=? AND status IN ('ACTIVE','GRACE')
                """,
                (guild_id, member["id"] if member else -1),
            )
            await self._composition_event(
                connection,
                guild_id,
                int(result["patrol_id"]),
                "MEMBER_LEFT",
                event_key=(
                    f"vehicle:{result['patrol_id']}:member:{member['id'] if member else discord_id}"
                    f":leave:{now}"
                ),
                member_id=int(member["id"]) if member else None,
                discord_id=discord_id,
                before_channel_id=voice_channel_id,
                reason=reason,
            )
            if bool(result["closed"]):
                await self._composition_event(
                    connection,
                    guild_id,
                    int(result["patrol_id"]),
                    "VEHICLE_CLOSED",
                    event_key=f"vehicle:{result['patrol_id']}:closed",
                    before_channel_id=voice_channel_id,
                    reason="CALL_EMPTY",
                )
        if bool(result["closed"]):
            await self.ensure_report_for_patrol(guild_id, int(result["patrol_id"]))
        return result

    async def reconcile_voice_state(
        self,
        guild_id: int,
        occupants: Mapping[int, Iterable[Mapping[str, object]]],
    ) -> dict[str, int]:
        """Rebuild automatic shifts/vehicles from one complete Discord snapshot."""
        async with self._lock(guild_id):
            normalized: dict[int, dict[int, Mapping[str, object]]] = {
                int(channel_id): {
                    int(member["discord_id"]): member for member in members
                }
                for channel_id, members in occupants.items()
            }
            active = await self.operations.active_patrols(guild_id)
            closed = 0
            removed = 0
            for patrol in active:
                channel_members = normalized.get(int(patrol["voice_channel_id"]), {})
                for member in await self.operations.active_patrol_members(
                    guild_id, int(patrol["id"])
                ):
                    if int(member["discord_id"]) not in channel_members:
                        outcome = await self._leave_vehicle(
                            guild_id,
                            int(member["discord_id"]),
                            int(patrol["voice_channel_id"]),
                            reason="RESTART_RECONCILIATION",
                        )
                        removed += int(outcome is not None)
                        closed += int(bool(outcome and outcome["closed"]))
            opened = 0
            joined = 0
            for channel_id, members in normalized.items():
                channel = await self._active_channel(guild_id, channel_id)
                if (
                    not channel
                    or not bool(channel["automatic_clock"])
                    or not await self._modules_allow_new_duty(guild_id)
                ):
                    continue
                for discord_id, snapshot in members.items():
                    active_shift = await self.shifts.get_active(guild_id, discord_id)
                    if active_shift and active_shift["status"] == ShiftStatus.GRACE.value:
                        await self.shifts.handle_voice_transition(
                            guild_id,
                            discord_id,
                            None,
                            channel_id,
                            has_authorized_role=bool(snapshot.get("authorized", False)),
                            after_allowed_override=True,
                        )
                        active_shift = await self.shifts.get_active(guild_id, discord_id)
                    if not active_shift and bool(snapshot.get("authorized", False)):
                        result = await self.shifts.start_shift(
                            guild_id,
                            discord_id,
                            channel_id,
                            has_authorized_role=True,
                            source="RECOVERY",
                            role_snapshot=str(snapshot.get("role_snapshot") or "") or None,
                        )
                        opened += int(result.status is ShiftStatus.ACTIVE)
                        active_shift = await self.shifts.get_active(guild_id, discord_id)
                    if not active_shift:
                        continue
                    vehicle = await self.ensure_voice_vehicle(
                        guild_id,
                        discord_id,
                        channel_id,
                        int(active_shift["id"]),
                        role_ids=snapshot.get("role_ids", ()),
                        source="RECOVERY",
                    )
                    joined += int(bool(vehicle["joined"]))
            await self.ensure_missing_reports(guild_id)
            return {"opened": opened, "joined": joined, "removed": removed, "closed": closed}

    async def ensure_report_catalog(self, guild_id: int, actor_id: int | None = None) -> int:
        now = self.clock()
        inserted = 0
        async with self.database.transaction() as connection:
            for code, title in DEFAULT_OCCURRENCE_CATEGORIES:
                cursor = await connection.execute(
                    """
                    INSERT OR IGNORE INTO patrol_occurrence_categories(
                        guild_id, code, title, active, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, ?, ?, ?)
                    """,
                    (guild_id, code, title, actor_id, now, now),
                )
                inserted += int(cursor.rowcount == 1)
        return inserted

    async def ensure_report_for_patrol(self, guild_id: int, patrol_id: int) -> dict[str, object]:
        await self.ensure_report_catalog(guild_id)
        now = self.clock()
        created = False
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT p.*,
                       COALESCE(p.commander_member_id, (
                           SELECT h.member_id FROM patrol_commander_history h
                           WHERE h.patrol_id=p.id ORDER BY h.started_at DESC, h.id DESC LIMIT 1
                       )) AS final_commander_member_id,
                       (SELECT h.discord_id FROM patrol_commander_history h
                        WHERE h.patrol_id=p.id ORDER BY h.started_at DESC, h.id DESC LIMIT 1
                       ) AS final_commander_discord_id
                FROM patrols p WHERE p.guild_id=? AND p.id=? AND p.status='CLOSED'
                """,
                (guild_id, patrol_id),
            )
            patrol = await cursor.fetchone()
            if not patrol:
                raise ValidationError("O relatório só pode ser gerado para viatura encerrada.")
            started_at = int(patrol["started_at"] or patrol["reserved_at"])
            ended_at = int(patrol["ended_at"] or now)
            cursor = await connection.execute(
                """
                INSERT OR IGNORE INTO patrol_reports(
                    guild_id, patrol_id, status, vehicle_number, voice_channel_id,
                    commander_member_id, commander_discord_id, started_at, ended_at,
                    duration_ms, created_at, updated_at
                ) VALUES (?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    patrol_id,
                    patrol["sequence_number"],
                    patrol["voice_channel_id"],
                    patrol["final_commander_member_id"],
                    patrol["final_commander_discord_id"],
                    started_at,
                    ended_at,
                    max(0, ended_at - started_at),
                    now,
                    now,
                ),
            )
            created = cursor.rowcount == 1
            cursor = await connection.execute(
                "SELECT * FROM patrol_reports WHERE guild_id=? AND patrol_id=?",
                (guild_id, patrol_id),
            )
            report = await cursor.fetchone()
            assert report is not None
            cursor = await connection.execute(
                """
                SELECT pm.member_id, pm.discord_id, pm.member_role, pm.joined_at, pm.left_at,
                       m.mta_nick, r.name AS rank_name
                FROM patrol_members pm JOIN members m ON m.id=pm.member_id
                LEFT JOIN ranks r ON r.id=m.rank_id
                WHERE pm.patrol_id=? ORDER BY COALESCE(pm.joined_at, pm.reserved_at), pm.id
                """,
                (patrol_id,),
            )
            members = list(await cursor.fetchall())
            for member in members:
                await connection.execute(
                    """
                    INSERT OR IGNORE INTO patrol_report_members(
                        guild_id, report_id, member_id, discord_id, display_name,
                        rank_name, member_role, joined_at, left_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        report["id"],
                        member["member_id"],
                        member["discord_id"],
                        member["mta_nick"],
                        member["rank_name"],
                        member["member_role"],
                        member["joined_at"],
                        member["left_at"],
                    ),
                )
            if created:
                await self.audit.record(
                    guild_id,
                    "PATROL_REPORT_DRAFT_CREATED",
                    after={"patrol_id": patrol_id, "report_id": int(report["id"])},
                    connection=connection,
                )
        return {**dict(report), "created": created}

    async def ensure_missing_reports(self, guild_id: int) -> int:
        rows = await self.database.fetchall(
            """
            SELECT p.id FROM patrols p LEFT JOIN patrol_reports r ON r.patrol_id=p.id
            WHERE p.guild_id=? AND p.status='CLOSED' AND r.id IS NULL
            ORDER BY p.id
            """,
            (guild_id,),
        )
        for row in rows:
            await self.ensure_report_for_patrol(guild_id, int(row["id"]))
        return len(rows)

    async def report(self, guild_id: int, report_id: int) -> dict[str, object]:
        row = await self.database.fetchone(
            "SELECT * FROM patrol_reports WHERE guild_id=? AND id=?",
            (guild_id, report_id),
        )
        if not row:
            raise NotFoundError("Relatório de PTR não encontrado.")
        members = await self.database.fetchall(
            "SELECT * FROM patrol_report_members WHERE report_id=? ORDER BY id", (report_id,)
        )
        occurrences = await self.database.fetchall(
            """
            SELECT o.*, c.code AS category_code, c.title AS category_title,
                   a.code AS article_code, a.title AS article_title
            FROM patrol_report_occurrences o
            JOIN patrol_occurrence_categories c ON c.id=o.category_id
            LEFT JOIN patrol_articles a ON a.id=o.article_id
            WHERE o.report_id=? ORDER BY o.occurred_at, o.id
            """,
            (report_id,),
        )
        evidence = await self.database.fetchall(
            "SELECT * FROM patrol_report_evidence WHERE report_id=? ORDER BY created_at, id",
            (report_id,),
        )
        return {
            "report": dict(row),
            "members": [dict(item) for item in members],
            "occurrences": [dict(item) for item in occurrences],
            "evidence": [dict(item) for item in evidence],
        }

    async def latest_report_for_member(
        self, guild_id: int, discord_id: int
    ) -> dict[str, object] | None:
        row = await self.database.fetchone(
            """
            SELECT r.id FROM patrol_reports r JOIN patrol_report_members rm ON rm.report_id=r.id
            WHERE r.guild_id=? AND rm.discord_id=? ORDER BY r.ended_at DESC, r.id DESC LIMIT 1
            """,
            (guild_id, discord_id),
        )
        return await self.report(guild_id, int(row["id"])) if row else None

    async def add_occurrence(
        self,
        guild_id: int,
        report_id: int,
        subject_discord_id: int,
        actor_id: int,
        *,
        category_code: str,
        reason: str,
        description: str,
        article_code: str | None = None,
        occurred_at: int | None = None,
        observations: str | None = None,
    ) -> int:
        category_code = category_code.strip().upper()
        article_code = (article_code or "").strip().upper() or None
        reason = reason.strip()
        description = description.strip()
        if not category_code or not reason or not description:
            raise ValidationError("Categoria, motivo e descrição são obrigatórios.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM patrol_reports WHERE guild_id=? AND id=?",
                (guild_id, report_id),
            )
            report = await cursor.fetchone()
            if not report or report["status"] != "DRAFT":
                raise ConflictError("O relatório não está aberto para novas ocorrências.")
            cursor = await connection.execute(
                """
                SELECT rm.*, m.id AS current_member_id FROM patrol_report_members rm
                JOIN members m ON m.id=rm.member_id
                WHERE rm.report_id=? AND rm.discord_id=?
                """,
                (report_id, subject_discord_id),
            )
            subject = await cursor.fetchone()
            if not subject:
                raise ValidationError("O militar não integra a composição congelada desta PTR.")
            cursor = await connection.execute(
                """
                SELECT * FROM patrol_occurrence_categories
                WHERE guild_id=? AND code=? AND active=1
                """,
                (guild_id, category_code),
            )
            category = await cursor.fetchone()
            if not category:
                raise ValidationError("Categoria de ocorrência não configurada.")
            article = None
            if article_code:
                cursor = await connection.execute(
                    """
                    SELECT * FROM patrol_articles
                    WHERE guild_id=? AND code=? AND active=1
                    """,
                    (guild_id, article_code),
                )
                article = await cursor.fetchone()
                if not article:
                    raise ValidationError("Artigo/enquadramento não configurado.")
            cursor = await connection.execute(
                """
                INSERT INTO patrol_report_occurrences(
                    guild_id, report_id, subject_member_id, subject_discord_id,
                    subject_name, subject_rank, category_id, article_id, occurred_at,
                    reason, description, responsible_id, observations, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    report_id,
                    subject["member_id"],
                    subject_discord_id,
                    subject["display_name"],
                    subject["rank_name"],
                    category["id"],
                    article["id"] if article else None,
                    occurred_at or now,
                    reason,
                    description,
                    actor_id,
                    (observations or "").strip() or None,
                    now,
                ),
            )
            occurrence_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "PATROL_REPORT_OCCURRENCE_CREATED",
                actor_id=actor_id,
                target_id=subject_discord_id,
                after={
                    "report_id": report_id,
                    "occurrence_id": occurrence_id,
                    "category": category_code,
                    "article": article_code,
                },
                reason=reason,
                connection=connection,
            )
        return occurrence_id

    async def add_evidence(
        self,
        guild_id: int,
        report_id: int,
        actor_id: int,
        *,
        evidence_type: str,
        locator: str,
        occurrence_id: int | None = None,
        description: str | None = None,
    ) -> int:
        evidence_type = evidence_type.strip().upper()
        locator = locator.strip()
        if evidence_type not in {"IMAGE", "LINK", "FILE", "NOTE"}:
            raise ValidationError("Tipo de evidência inválido.")
        if not locator or len(locator) > 2000:
            raise ValidationError("Informe uma referência de evidência válida.")
        if evidence_type in {"IMAGE", "LINK", "FILE"}:
            parsed = urlparse(locator)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValidationError("A evidência precisa usar um link HTTP ou HTTPS persistente.")
        maximum = max(
            1,
            int(await self.settings.get(guild_id, "patrol_report_max_evidence", 20)),
        )
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT status FROM patrol_reports WHERE guild_id=? AND id=?",
                (guild_id, report_id),
            )
            report = await cursor.fetchone()
            if not report or report["status"] != "DRAFT":
                raise ConflictError("O relatório não está aberto para novas evidências.")
            cursor = await connection.execute(
                "SELECT COUNT(*) AS total FROM patrol_report_evidence WHERE report_id=?",
                (report_id,),
            )
            if int((await cursor.fetchone())["total"]) >= maximum:
                raise ConflictError(
                    f"O relatório atingiu o limite de {maximum} evidência(s)."
                )
            if occurrence_id is not None:
                cursor = await connection.execute(
                    "SELECT 1 FROM patrol_report_occurrences WHERE report_id=? AND id=?",
                    (report_id, occurrence_id),
                )
                if not await cursor.fetchone():
                    raise ValidationError("A ocorrência não pertence a este relatório.")
            cursor = await connection.execute(
                """
                INSERT INTO patrol_report_evidence(
                    guild_id, report_id, occurrence_id, evidence_type, locator,
                    description, author_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    report_id,
                    occurrence_id,
                    evidence_type,
                    locator,
                    (description or "").strip() or None,
                    actor_id,
                    now,
                ),
            )
            evidence_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "PATROL_REPORT_EVIDENCE_CREATED",
                actor_id=actor_id,
                after={
                    "report_id": report_id,
                    "occurrence_id": occurrence_id,
                    "evidence_id": evidence_id,
                    "type": evidence_type,
                },
                connection=connection,
            )
        return evidence_id

    async def finalize_report(
        self,
        guild_id: int,
        report_id: int,
        actor_id: int,
        *,
        description: str,
        observations: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, object]:
        description = description.strip()
        if not description:
            raise ValidationError("Descreva resumidamente a patrulha.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM patrol_reports WHERE guild_id=? AND id=?",
                (guild_id, report_id),
            )
            report = await cursor.fetchone()
            if not report:
                raise NotFoundError("Relatório de PTR não encontrado.")
            if report["status"] == "FINALIZED":
                return dict(report)
            if report["status"] != "DRAFT":
                raise ConflictError("O relatório não pode ser finalizado neste estado.")
            if expected_version is not None and int(report["version"]) != expected_version:
                raise ConflictError("O relatório mudou; atualize antes de finalizar.")
            cursor = await connection.execute(
                """
                UPDATE patrol_reports
                SET status='FINALIZED', responsible_id=?, description=?, observations=?,
                    finalized_at=?, updated_at=?, version=version+1
                WHERE id=? AND status='DRAFT' AND version=?
                """,
                (
                    actor_id,
                    description,
                    (observations or "").strip() or None,
                    now,
                    now,
                    report_id,
                    report["version"],
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("O relatório foi alterado por outro responsável.")
            await self.audit.record(
                guild_id,
                "PATROL_REPORT_FINALIZED",
                actor_id=actor_id,
                after={"report_id": report_id, "patrol_id": int(report["patrol_id"])},
                connection=connection,
            )
            cursor = await connection.execute("SELECT * FROM patrol_reports WHERE id=?", (report_id,))
            updated = await cursor.fetchone()
        return dict(updated)

    async def configure_article(
        self,
        guild_id: int,
        actor_id: int,
        *,
        code: str,
        title: str,
        description: str | None,
        severity: str,
        category_code: str | None = None,
        active: bool = True,
    ) -> int:
        code = code.strip().upper()
        title = title.strip()
        severity = severity.strip().upper()
        if not code or not title or severity not in {"LOW", "NORMAL", "HIGH", "CRITICAL"}:
            raise ValidationError("Código, título e gravidade válidos são obrigatórios.")
        now = self.clock()
        async with self.database.transaction() as connection:
            category_id = None
            if category_code:
                cursor = await connection.execute(
                    "SELECT id FROM patrol_occurrence_categories WHERE guild_id=? AND code=?",
                    (guild_id, category_code.strip().upper()),
                )
                category = await cursor.fetchone()
                if not category:
                    raise ValidationError("Categoria vinculada não encontrada.")
                category_id = int(category["id"])
            await connection.execute(
                """
                INSERT INTO patrol_articles(
                    guild_id, code, title, description, severity, category_id,
                    active, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, code) DO UPDATE SET
                    title=excluded.title, description=excluded.description,
                    severity=excluded.severity, category_id=excluded.category_id,
                    active=excluded.active, updated_at=excluded.updated_at
                """,
                (
                    guild_id,
                    code,
                    title,
                    (description or "").strip() or None,
                    severity,
                    category_id,
                    int(active),
                    actor_id,
                    now,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT id FROM patrol_articles WHERE guild_id=? AND code=?", (guild_id, code)
            )
            article_id = int((await cursor.fetchone())["id"])
            await self.audit.record(
                guild_id,
                "PATROL_ARTICLE_CONFIGURED",
                actor_id=actor_id,
                after={"article_id": article_id, "code": code, "active": active},
                connection=connection,
            )
        return article_id

    async def configure_occurrence_category(
        self,
        guild_id: int,
        actor_id: int,
        *,
        code: str,
        title: str,
        description: str | None,
        active: bool = True,
    ) -> int:
        code = code.strip().upper()
        title = title.strip()
        if not code or not title:
            raise ValidationError("Código e título da categoria são obrigatórios.")
        now = self.clock()
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO patrol_occurrence_categories(
                    guild_id, code, title, description, active,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, code) DO UPDATE SET
                    title=excluded.title, description=excluded.description,
                    active=excluded.active, updated_at=excluded.updated_at
                """,
                (
                    guild_id,
                    code,
                    title,
                    (description or "").strip() or None,
                    int(active),
                    actor_id,
                    now,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT id FROM patrol_occurrence_categories WHERE guild_id=? AND code=?",
                (guild_id, code),
            )
            category_id = int((await cursor.fetchone())["id"])
            await self.audit.record(
                guild_id,
                "PATROL_OCCURRENCE_CATEGORY_CONFIGURED",
                actor_id=actor_id,
                after={"category_id": category_id, "code": code, "active": active},
                connection=connection,
            )
        return category_id

    async def service_overview(self, guild_id: int) -> dict[str, object]:
        patrols = [dict(row) for row in await self.operations.active_patrols(guild_id)]
        for patrol in patrols:
            patrol["members"] = [
                dict(row)
                for row in await self.database.fetchall(
                    """
                    SELECT pm.*, m.mta_nick, r.name AS rank_name, s.started_at AS shift_started_at
                    FROM patrol_members pm JOIN members m ON m.id=pm.member_id
                    LEFT JOIN ranks r ON r.id=m.rank_id
                    LEFT JOIN shifts s ON s.id=pm.associated_shift_id
                    WHERE pm.patrol_id=? AND pm.status='ACTIVE'
                    ORDER BY COALESCE(pm.joined_at, pm.reserved_at), pm.id
                    """,
                    (patrol["id"],),
                )
            ]
        unassigned = await self.database.fetchall(
            """
            SELECT s.*, m.discord_id, m.mta_nick, r.name AS rank_name,
                   (SELECT voice_channel_id FROM shift_segments ss
                    WHERE ss.shift_id=s.id AND ss.ended_at IS NULL LIMIT 1) AS voice_channel_id
            FROM shifts s JOIN members m ON m.id=s.member_id
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE s.guild_id=? AND s.status IN ('ACTIVE','GRACE')
              AND NOT EXISTS(
                  SELECT 1 FROM patrol_members pm JOIN patrols p ON p.id=pm.patrol_id
                  WHERE pm.guild_id=s.guild_id AND pm.member_id=s.member_id
                    AND pm.status='ACTIVE' AND p.status='ACTIVE'
              )
            ORDER BY s.started_at, s.id
            """,
            (guild_id,),
        )
        return {
            "patrols": patrols,
            "unassigned": [dict(row) for row in unassigned],
            "member_count": sum(len(patrol["members"]) for patrol in patrols)
            + len(unassigned),
        }

    async def composition_timeline(self, guild_id: int, patrol_id: int):
        return await self.database.fetchall(
            """
            SELECT * FROM patrol_composition_events
            WHERE guild_id=? AND patrol_id=? ORDER BY occurred_at, id
            """,
            (guild_id, patrol_id),
        )

    async def _composition_event(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        patrol_id: int,
        event_type: str,
        *,
        event_key: str,
        member_id: int | None = None,
        discord_id: int | None = None,
        before_channel_id: int | None = None,
        after_channel_id: int | None = None,
        previous_commander_id: int | None = None,
        next_commander_id: int | None = None,
        actor_id: int | None = None,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        await connection.execute(
            """
            INSERT OR IGNORE INTO patrol_composition_events(
                guild_id, patrol_id, event_type, member_id, discord_id,
                before_channel_id, after_channel_id, previous_commander_id,
                next_commander_id, actor_id, reason, metadata_json, event_key, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                patrol_id,
                event_type,
                member_id,
                discord_id,
                before_channel_id,
                after_channel_id,
                previous_commander_id,
                next_commander_id,
                actor_id,
                reason,
                json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                event_key,
                self.clock(),
            ),
        )

    async def record_admin_adjustment(
        self,
        guild_id: int,
        action_type: str,
        actor_id: int,
        reason: str,
        *,
        patrol_id: int | None = None,
        shift_id: int | None = None,
        target_discord_id: int | None = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
    ) -> int:
        action_type = action_type.strip().upper()
        reason = reason.strip()
        if not reason:
            raise ValidationError("Toda correção administrativa exige motivo.")
        correlation_id = str(uuid.uuid4())
        async with self.database.transaction() as connection:
            adjustment_id = await self._record_admin_adjustment_in_tx(
                connection,
                guild_id,
                action_type,
                actor_id,
                reason,
                patrol_id=patrol_id,
                shift_id=shift_id,
                target_discord_id=target_discord_id,
                before=before,
                after=after,
                correlation_id=correlation_id,
            )
        return adjustment_id

    async def _record_admin_adjustment_in_tx(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        action_type: str,
        actor_id: int,
        reason: str,
        *,
        patrol_id: int | None = None,
        shift_id: int | None = None,
        target_discord_id: int | None = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> int:
        allowed = {
            "SHIFT_OPENED",
            "SHIFT_CLOSED",
            "SHIFT_CORRECTED",
            "SHIFT_INVALIDATED",
            "MEMBER_ASSIGNED",
            "MEMBER_REMOVED",
            "COMMANDER_OVERRIDDEN",
            "REPORT_VOIDED",
        }
        action_type = action_type.strip().upper()
        reason = reason.strip()
        if action_type not in allowed:
            raise ValidationError("Tipo de correção administrativa inválido.")
        if not reason:
            raise ValidationError("Toda correção administrativa exige motivo.")
        correlation_id = correlation_id or str(uuid.uuid4())
        cursor = await connection.execute(
            """
            INSERT INTO patrol_admin_adjustments(
                guild_id, action_type, patrol_id, shift_id, target_discord_id,
                actor_id, reason, before_json, after_json, correlation_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                action_type,
                patrol_id,
                shift_id,
                target_discord_id,
                actor_id,
                reason,
                json.dumps(dict(before or {}), ensure_ascii=False, sort_keys=True),
                json.dumps(dict(after or {}), ensure_ascii=False, sort_keys=True),
                correlation_id,
                self.clock(),
            ),
        )
        adjustment_id = int(cursor.lastrowid)
        await self.audit.record(
            guild_id,
            f"PATROL_ADMIN_{action_type}",
            actor_id=actor_id,
            target_id=target_discord_id,
            before=dict(before or {}),
            after=dict(after or {}),
            reason=reason,
            correlation_id=correlation_id,
            connection=connection,
        )
        return adjustment_id

    async def admin_assign_member(
        self,
        guild_id: int,
        patrol_id: int,
        target_discord_id: int,
        actor_id: int,
        *,
        reason: str,
        present_discord_ids: Iterable[int],
    ) -> dict[str, object]:
        """Repair a missed voice join without manufacturing a service session."""
        reason = reason.strip()
        present = {int(value) for value in present_discord_ids}
        if target_discord_id not in present:
            raise ValidationError("O militar precisa estar presente na call da viatura.")
        if not reason:
            raise ValidationError("Toda correção administrativa exige motivo.")
        now = self.clock()
        config = await self.operations.patrol_commander_config(guild_id)
        correlation_id = str(uuid.uuid4())
        async with self._lock(guild_id), self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM patrols WHERE guild_id=? AND id=? AND status='ACTIVE'",
                (guild_id, patrol_id),
            )
            patrol = await cursor.fetchone()
            if not patrol:
                raise NotFoundError("Viatura ativa não encontrada.")
            cursor = await connection.execute(
                """
                SELECT m.*, s.id AS shift_id, s.current_patrol_id, s.status AS shift_status
                FROM members m LEFT JOIN shifts s ON s.member_id=m.id AND s.guild_id=m.guild_id
                    AND s.status IN ('ACTIVE','GRACE')
                WHERE m.guild_id=? AND m.discord_id=?
                """,
                (guild_id, target_discord_id),
            )
            member = await cursor.fetchone()
            if not member or member["status"] != "ACTIVE" or member["rank_id"] is None:
                raise ValidationError("Somente militar ativo e identificado pode integrar viatura.")
            if member["shift_id"] is None:
                raise ConflictError("O militar não possui sessão de serviço ativa.")
            if member["current_patrol_id"] not in {None, patrol_id}:
                raise ConflictError("O militar já está vinculado a outra viatura.")
            cursor = await connection.execute(
                """
                SELECT pm.* FROM patrol_members pm JOIN patrols p ON p.id=pm.patrol_id
                WHERE pm.guild_id=? AND pm.member_id=? AND pm.status IN ('RESERVED','ACTIVE')
                  AND p.status IN ('RESERVED','ACTIVE')
                """,
                (guild_id, member["id"]),
            )
            active_membership = await cursor.fetchone()
            if active_membership:
                raise ConflictError("O militar já integra uma viatura ativa.")
            cursor = await connection.execute(
                "SELECT status FROM patrol_members WHERE patrol_id=? AND member_id=?",
                (patrol_id, member["id"]),
            )
            previous = await cursor.fetchone()
            before = {
                "membership_status": previous["status"] if previous else None,
                "current_patrol_id": member["current_patrol_id"],
                "shift_id": int(member["shift_id"]),
            }
            await connection.execute(
                """
                INSERT INTO patrol_members(
                    guild_id, patrol_id, member_id, discord_id, member_role,
                    status, reserved_at, joined_at, left_at, associated_shift_id
                ) VALUES (?, ?, ?, ?, 'MEMBER', 'ACTIVE', ?, ?, NULL, ?)
                ON CONFLICT(patrol_id, member_id) DO UPDATE SET
                    status='ACTIVE', joined_at=excluded.joined_at, left_at=NULL,
                    associated_shift_id=excluded.associated_shift_id, member_role='MEMBER'
                """,
                (
                    guild_id,
                    patrol_id,
                    member["id"],
                    target_discord_id,
                    now,
                    now,
                    member["shift_id"],
                ),
            )
            await connection.execute(
                "UPDATE shifts SET current_patrol_id=?, version=version+1 WHERE id=?",
                (patrol_id, member["shift_id"]),
            )
            await connection.execute(
                "UPDATE patrols SET version=version+1, updated_at=? WHERE id=?",
                (now, patrol_id),
            )
            await self._composition_event(
                connection,
                guild_id,
                patrol_id,
                "ADMIN_ADJUSTED",
                event_key=f"vehicle:{patrol_id}:admin-assign:{correlation_id}",
                member_id=int(member["id"]),
                discord_id=target_discord_id,
                after_channel_id=int(patrol["voice_channel_id"]),
                actor_id=actor_id,
                reason=reason,
                metadata={"action": "MEMBER_ASSIGNED"},
            )
            after = {
                "membership_status": "ACTIVE",
                "current_patrol_id": patrol_id,
                "shift_id": int(member["shift_id"]),
            }
            adjustment_id = await self._record_admin_adjustment_in_tx(
                connection,
                guild_id,
                "MEMBER_ASSIGNED",
                actor_id,
                reason,
                patrol_id=patrol_id,
                shift_id=int(member["shift_id"]),
                target_discord_id=target_discord_id,
                before=before,
                after=after,
                correlation_id=correlation_id,
            )
            commander = await self.operations._select_patrol_commander_in_tx(
                connection,
                guild_id,
                patrol_id,
                config,
                present,
                reason="ADMIN_MEMBER_ASSIGNED",
            )
        return {
            "action": "MEMBER_ASSIGNED",
            "adjustment_id": adjustment_id,
            "patrol_id": patrol_id,
            "target_discord_id": target_discord_id,
            "commander": commander,
        }

    async def admin_remove_member(
        self,
        guild_id: int,
        patrol_id: int,
        target_discord_id: int,
        actor_id: int,
        *,
        reason: str,
        present_discord_ids: Iterable[int],
    ) -> dict[str, object]:
        """Repair a missed voice leave while preserving the official shift history."""
        reason = reason.strip()
        present = {int(value) for value in present_discord_ids}
        if target_discord_id in present:
            raise ValidationError("O militar ainda está presente na call da viatura.")
        if not reason:
            raise ValidationError("Toda correção administrativa exige motivo.")
        now = self.clock()
        config = await self.operations.patrol_commander_config(guild_id)
        correlation_id = str(uuid.uuid4())
        closed = False
        async with self._lock(guild_id), self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT p.*, pm.id AS patrol_member_id, pm.member_id,
                       pm.associated_shift_id, pm.member_role
                FROM patrols p JOIN patrol_members pm ON pm.patrol_id=p.id
                WHERE p.guild_id=? AND p.id=? AND p.status='ACTIVE'
                  AND pm.discord_id=? AND pm.status='ACTIVE'
                """,
                (guild_id, patrol_id, target_discord_id),
            )
            row = await cursor.fetchone()
            if not row:
                raise NotFoundError("O militar não integra esta viatura ativa.")
            before = {
                "membership_status": "ACTIVE",
                "current_patrol_id": patrol_id,
                "shift_id": row["associated_shift_id"],
                "member_role": row["member_role"],
            }
            await connection.execute(
                "UPDATE patrol_members SET status='LEFT', left_at=? WHERE id=?",
                (now, row["patrol_member_id"]),
            )
            await connection.execute(
                """
                UPDATE shifts SET current_patrol_id=NULL, version=version+1
                WHERE id=? AND current_patrol_id=? AND status IN ('ACTIVE','GRACE')
                """,
                (row["associated_shift_id"], patrol_id),
            )
            cursor = await connection.execute(
                "SELECT COUNT(*) AS total FROM patrol_members WHERE patrol_id=? AND status='ACTIVE'",
                (patrol_id,),
            )
            remaining = int((await cursor.fetchone())["total"])
            closed = remaining == 0 or (
                not bool(row["continue_until_empty"])
                and remaining < int(row["minimum_members"])
            )
            await self._composition_event(
                connection,
                guild_id,
                patrol_id,
                "ADMIN_ADJUSTED",
                event_key=f"vehicle:{patrol_id}:admin-remove:{correlation_id}",
                member_id=int(row["member_id"]),
                discord_id=target_discord_id,
                before_channel_id=int(row["voice_channel_id"]),
                actor_id=actor_id,
                reason=reason,
                metadata={"action": "MEMBER_REMOVED"},
            )
            after = {
                "membership_status": "LEFT",
                "current_patrol_id": None,
                "shift_id": row["associated_shift_id"],
                "member_role": row["member_role"],
            }
            adjustment_id = await self._record_admin_adjustment_in_tx(
                connection,
                guild_id,
                "MEMBER_REMOVED",
                actor_id,
                reason,
                patrol_id=patrol_id,
                shift_id=(
                    int(row["associated_shift_id"])
                    if row["associated_shift_id"] is not None
                    else None
                ),
                target_discord_id=target_discord_id,
                before=before,
                after=after,
                correlation_id=correlation_id,
            )
            if closed:
                await self.operations._finish_patrol_in_tx(
                    connection, row, now, "ADMIN_MEMBER_REMOVED", actor_id
                )
                commander = None
            else:
                await connection.execute(
                    "UPDATE patrols SET version=version+1, updated_at=? WHERE id=?",
                    (now, patrol_id),
                )
                commander = await self.operations._select_patrol_commander_in_tx(
                    connection,
                    guild_id,
                    patrol_id,
                    config,
                    present,
                    reason="ADMIN_MEMBER_REMOVED",
                )
        if closed:
            await self.ensure_report_for_patrol(guild_id, patrol_id)
        return {
            "action": "MEMBER_REMOVED",
            "adjustment_id": adjustment_id,
            "patrol_id": patrol_id,
            "target_discord_id": target_discord_id,
            "closed": closed,
            "commander": commander,
        }

    async def admin_open_shift(
        self,
        guild_id: int,
        target_discord_id: int,
        actor_id: int,
        *,
        reason: str,
        voice_channel_id: int,
        target_has_authorized_role: bool,
        role_snapshot: str | None = None,
        role_ids: Iterable[int] = (),
    ) -> dict[str, object]:
        reason = reason.strip()
        if not reason:
            raise ValidationError("Toda correção administrativa exige motivo.")
        result = await self.shifts.start_shift(
            guild_id,
            target_discord_id,
            voice_channel_id,
            has_authorized_role=target_has_authorized_role,
            actor_id=actor_id,
            source="ADMIN",
            role_snapshot=role_snapshot,
        )
        channel = await self._active_channel(guild_id, voice_channel_id)
        vehicle = None
        vehicle_error = None
        if channel:
            try:
                vehicle = await self.ensure_voice_vehicle(
                    guild_id,
                    target_discord_id,
                    voice_channel_id,
                    result.shift_id,
                    role_ids=role_ids,
                    source="RECOVERY",
                )
            except (ConflictError, ValidationError) as exc:
                # An exceptional point correction is still valid when the
                # configured vehicle cannot accept the member. Keep the shift
                # explicitly unassigned and audit the reason instead of
                # leaving an untracked partial action.
                vehicle_error = str(exc)
        after = {
            "status": result.status.value,
            "voice_channel_id": voice_channel_id,
            "start_source": "ADMIN",
            "patrol_id": vehicle["patrol_id"] if vehicle else None,
            "vehicle_error": vehicle_error,
        }
        adjustment_id = await self.record_admin_adjustment(
            guild_id,
            "SHIFT_OPENED",
            actor_id,
            reason,
            patrol_id=int(vehicle["patrol_id"]) if vehicle else None,
            shift_id=result.shift_id,
            target_discord_id=target_discord_id,
            before={"status": None},
            after=after,
        )
        return {
            "action": "SHIFT_OPENED",
            "adjustment_id": adjustment_id,
            "shift_id": result.shift_id,
            "vehicle": vehicle,
            "vehicle_error": vehicle_error,
        }

    async def admin_correct_shift(
        self,
        guild_id: int,
        shift_id: int,
        actor_id: int,
        *,
        minutes: int,
        reason: str,
    ) -> dict[str, object]:
        row = await self.database.fetchone(
            """
            SELECT s.*, m.discord_id,
                   COALESCE((SELECT SUM(delta_ms) FROM shift_adjustments sa
                             WHERE sa.shift_id=s.id), 0) AS adjustment_ms
            FROM shifts s JOIN members m ON m.id=s.member_id
            WHERE s.guild_id=? AND s.id=?
            """,
            (guild_id, shift_id),
        )
        if not row:
            raise NotFoundError("Sessão não encontrada.")
        before = {"adjustment_ms": int(row["adjustment_ms"])}
        await self.shifts.adjust_shift(guild_id, shift_id, minutes, actor_id, reason)
        after = {"adjustment_ms": int(row["adjustment_ms"]) + minutes * 60_000}
        adjustment_id = await self.record_admin_adjustment(
            guild_id,
            "SHIFT_CORRECTED",
            actor_id,
            reason,
            shift_id=shift_id,
            target_discord_id=int(row["discord_id"]),
            before=before,
            after=after,
        )
        return {
            "action": "SHIFT_CORRECTED",
            "adjustment_id": adjustment_id,
            "shift_id": shift_id,
            **after,
        }

    async def admin_close_shift(
        self,
        guild_id: int,
        target_discord_id: int,
        actor_id: int,
        *,
        reason: str,
        invalidate: bool = False,
    ) -> dict[str, object]:
        reason = reason.strip()
        if not reason:
            raise ValidationError("Toda correção administrativa exige motivo.")
        active = await self.shifts.get_active(guild_id, target_discord_id)
        if not active:
            raise NotFoundError("O militar não possui sessão ativa.")
        patrol = None
        if active["current_patrol_id"] is not None:
            patrol = await self.database.fetchone(
                "SELECT * FROM patrols WHERE guild_id=? AND id=? AND status='ACTIVE'",
                (guild_id, active["current_patrol_id"]),
            )
        before = {
            "status": active["status"],
            "validation_status": active["validation_status"],
            "current_patrol_id": active["current_patrol_id"],
        }
        result = await self.shifts.stop_shift(
            guild_id,
            target_discord_id,
            actor_id=actor_id,
            reason="ADMIN_CORRECTION",
            confirm_short=True,
            expected_shift_id=int(active["id"]),
        )
        if patrol:
            await self._leave_vehicle(
                guild_id,
                target_discord_id,
                int(patrol["voice_channel_id"]),
                reason="ADMIN_CORRECTION",
            )
        if invalidate:
            now = self.clock()
            async with self.database.transaction() as connection:
                await connection.execute(
                    """
                    UPDATE shifts SET validation_status='INVALIDATED',
                        automatic_validation_status='INVALIDATED',
                        validation_source='ADMIN_OVERRIDE', invalid_reason=?,
                        validated_by=?, validated_at=?, validation_reason=?
                    WHERE guild_id=? AND id=? AND status='CLOSED'
                    """,
                    (reason, actor_id, now, reason, guild_id, result.shift_id),
                )
                await self.audit.record(
                    guild_id,
                    "SHIFT_INVALIDATED_BY_ADMIN",
                    actor_id=actor_id,
                    target_id=target_discord_id,
                    before={"validation_status": result.validation_status},
                    after={"validation_status": "INVALIDATED"},
                    reason=reason,
                    connection=connection,
                )
        action = "SHIFT_INVALIDATED" if invalidate else "SHIFT_CLOSED"
        after = {
            "status": "CLOSED",
            "validation_status": (
                "INVALIDATED" if invalidate else result.validation_status
            ),
            "current_patrol_id": None,
        }
        adjustment_id = await self.record_admin_adjustment(
            guild_id,
            action,
            actor_id,
            reason,
            patrol_id=int(patrol["id"]) if patrol else None,
            shift_id=result.shift_id,
            target_discord_id=target_discord_id,
            before=before,
            after=after,
        )
        return {
            "action": action,
            "adjustment_id": adjustment_id,
            "shift_id": result.shift_id,
            **after,
        }

    async def admin_override_commander(
        self,
        guild_id: int,
        patrol_id: int,
        commander_discord_id: int,
        actor_id: int,
        *,
        reason: str,
        present_discord_ids: Iterable[int],
    ) -> dict[str, object]:
        before = await self.database.fetchone(
            """
            SELECT p.commander_member_id, m.discord_id AS commander_discord_id
            FROM patrols p LEFT JOIN members m ON m.id=p.commander_member_id
            WHERE p.guild_id=? AND p.id=? AND p.status='ACTIVE'
            """,
            (guild_id, patrol_id),
        )
        if not before:
            raise NotFoundError("Viatura ativa não encontrada.")
        result = await self.operations.override_patrol_commander(
            guild_id,
            patrol_id,
            commander_discord_id,
            actor_id,
            reason,
            present_discord_ids,
        )
        adjustment_id = await self.record_admin_adjustment(
            guild_id,
            "COMMANDER_OVERRIDDEN",
            actor_id,
            reason,
            patrol_id=patrol_id,
            target_discord_id=commander_discord_id,
            before={
                "commander_member_id": before["commander_member_id"],
                "commander_discord_id": before["commander_discord_id"],
            },
            after={
                "commander_member_id": result["commander_member_id"],
                "commander_discord_id": result["commander_discord_id"],
                "manual_lock": result["manual_lock"],
            },
        )
        return {**result, "adjustment_id": adjustment_id}

    async def handle_role_loss(
        self, guild_id: int, target_discord_id: int
    ) -> dict[str, object]:
        """Close every active operational link when service eligibility is lost."""
        async with self._lock(guild_id):
            active = await self.shifts.get_active(guild_id, target_discord_id)
            if not active:
                return {"closed": False, "shift_id": None, "patrol_id": None}
            patrol = None
            if active["current_patrol_id"] is not None:
                patrol = await self.database.fetchone(
                    "SELECT * FROM patrols WHERE guild_id=? AND id=? AND status='ACTIVE'",
                    (guild_id, active["current_patrol_id"]),
                )
            result = await self.shifts.stop_shift(
                guild_id,
                target_discord_id,
                reason="ROLE_LOST",
                confirm_short=True,
                expected_shift_id=int(active["id"]),
            )
            if patrol:
                await self._leave_vehicle(
                    guild_id,
                    target_discord_id,
                    int(patrol["voice_channel_id"]),
                    reason="ROLE_LOST",
                )
            return {
                "closed": True,
                "shift_id": result.shift_id,
                "patrol_id": int(patrol["id"]) if patrol else None,
            }
