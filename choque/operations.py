from __future__ import annotations

import json
from collections.abc import Callable, Iterable

import aiosqlite

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .settings import SettingsService
from .shifts import ShiftService
from .time_utils import utc_now_ms

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
COMMANDER_PRIORITY_DEFAULT = (
    "QUALIFICATION",
    "RANK_LEVEL",
    "TIME_IN_RANK",
    "TOTAL_SERVICE_TIME",
    "MEMBERSHIP_TIME",
    "PATROL_JOIN_ORDER",
)
COMMANDER_PRIORITY_ALLOWED = frozenset(COMMANDER_PRIORITY_DEFAULT)


class OperationsService:
    """Operational intelligence without automatic administrative decisions."""

    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
        shifts: ShiftService,
        *,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit
        self.shifts = shifts
        self.clock = clock

    async def _member_in_tx(self, connection: aiosqlite.Connection, guild_id: int, discord_id: int):
        cursor = await connection.execute(
            """
            SELECT m.*, r.name AS rank_name, r.level AS rank_level,
                   r.discord_role_id AS rank_role_id
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        member = await cursor.fetchone()
        if not member:
            raise NotFoundError("Você ainda não possui cadastro aprovado.")
        return member

    async def _event(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        event_type: str,
        aggregate_type: str,
        aggregate_id: int | None,
        event_key: str,
        payload: dict[str, object],
    ) -> None:
        await connection.execute(
            """
            INSERT OR IGNORE INTO domain_events(
                guild_id, event_type, aggregate_type, aggregate_id,
                event_key, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                event_type,
                aggregate_type,
                aggregate_id,
                event_key,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                self.clock(),
            ),
        )

    async def maintenance_state(self, guild_id: int, module_key: str):
        return await self.database.fetchone(
            """
            SELECT * FROM module_maintenance
            WHERE guild_id=? AND module_key=? AND active=1
            """,
            (guild_id, module_key.upper()),
        )

    async def require_available_module(self, guild_id: int, module_key: str) -> None:
        state = await self.maintenance_state(guild_id, module_key)
        if state:
            reason = state["reason"] or "Ajustes internos"
            raise ValidationError(
                f"O módulo {module_key.upper()} está em manutenção. Motivo: {reason}."
            )

    async def set_maintenance(
        self,
        guild_id: int,
        module_key: str,
        active: bool,
        actor_id: int,
        *,
        reason: str | None = None,
        expected_end_at: int | None = None,
    ) -> dict[str, object]:
        module_key = module_key.strip().upper()
        if not module_key:
            raise ValidationError("Informe o módulo.")
        if active and not (reason or "").strip():
            raise ValidationError("Informe o motivo da manutenção.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM module_maintenance WHERE guild_id=? AND module_key=?",
                (guild_id, module_key),
            )
            before = await cursor.fetchone()
            await connection.execute(
                """
                INSERT INTO module_maintenance(
                    guild_id, module_key, active, reason, expected_end_at,
                    enabled_by, enabled_at, disabled_by, disabled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, module_key) DO UPDATE SET
                    active=excluded.active,
                    reason=excluded.reason,
                    expected_end_at=excluded.expected_end_at,
                    enabled_by=CASE WHEN excluded.active=1 THEN excluded.enabled_by
                                    ELSE module_maintenance.enabled_by END,
                    enabled_at=CASE WHEN excluded.active=1 THEN excluded.enabled_at
                                    ELSE module_maintenance.enabled_at END,
                    disabled_by=CASE WHEN excluded.active=0 THEN excluded.disabled_by
                                     ELSE NULL END,
                    disabled_at=CASE WHEN excluded.active=0 THEN excluded.disabled_at
                                     ELSE NULL END
                """,
                (
                    guild_id,
                    module_key,
                    int(active),
                    (reason or "").strip() or None,
                    expected_end_at,
                    actor_id if active else None,
                    now if active else None,
                    actor_id if not active else None,
                    now if not active else None,
                ),
            )
            await self.audit.record(
                guild_id,
                "MAINTENANCE_ENABLED" if active else "MAINTENANCE_DISABLED",
                actor_id=actor_id,
                before=dict(before) if before else None,
                after={
                    "module": module_key,
                    "active": active,
                    "expected_end_at": expected_end_at,
                },
                reason=(reason or "").strip() or None,
                connection=connection,
            )
            await self._event(
                connection,
                guild_id,
                "MAINTENANCE_CHANGED",
                "MODULE",
                None,
                f"maintenance:{module_key}:{now}",
                {"module": module_key, "active": active},
            )
        return {"module": module_key, "active": active}

    async def maintenance_modules(self, guild_id: int):
        return await self.database.fetchall(
            "SELECT * FROM module_maintenance WHERE guild_id=? ORDER BY module_key",
            (guild_id,),
        )

    async def configure_patrol_channel(
        self,
        guild_id: int,
        channel_id: int,
        channel_type: str,
        label: str,
        sort_order: int,
        actor_id: int | None,
        *,
        enabled: bool = True,
    ) -> None:
        channel_type = channel_type.upper()
        if channel_type not in {"WAITING", "ACTIVE"}:
            raise ValidationError("Tipo de call de patrulha inválido.")
        now = self.clock()
        async with self.database.transaction() as connection:
            if channel_type == "WAITING" and enabled:
                await connection.execute(
                    """
                    UPDATE patrol_channels SET enabled=0, updated_at=?
                    WHERE guild_id=? AND channel_type='WAITING' AND channel_id<>?
                    """,
                    (now, guild_id, channel_id),
                )
            await connection.execute(
                """
                INSERT INTO patrol_channels(
                    guild_id, channel_id, channel_type, enabled, sort_order,
                    label, created_at, created_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                    channel_type=excluded.channel_type,
                    enabled=excluded.enabled,
                    sort_order=excluded.sort_order,
                    label=excluded.label,
                    updated_at=excluded.updated_at
                """,
                (
                    guild_id,
                    channel_id,
                    channel_type,
                    int(enabled),
                    sort_order,
                    label,
                    now,
                    actor_id,
                    now,
                ),
            )
            await self.audit.record(
                guild_id,
                "PATROL_CHANNEL_CONFIGURED",
                actor_id=actor_id,
                target_id=channel_id,
                after={
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "enabled": enabled,
                    "sort_order": sort_order,
                },
                connection=connection,
            )

    async def patrol_channels(self, guild_id: int, channel_type: str | None = None):
        where = "AND channel_type=?" if channel_type else ""
        params: tuple[object, ...] = (
            (guild_id, channel_type.upper()) if channel_type else (guild_id,)
        )
        return await self.database.fetchall(
            f"""
            SELECT * FROM patrol_channels
            WHERE guild_id=? {where}
            ORDER BY channel_type DESC, sort_order, channel_id
            """,
            params,
        )

    async def waiting_channel_id(self, guild_id: int) -> int | None:
        row = await self.database.fetchone(
            """
            SELECT channel_id FROM patrol_channels
            WHERE guild_id=? AND channel_type='WAITING' AND enabled=1
            """,
            (guild_id,),
        )
        return int(row["channel_id"]) if row else None

    async def patrol_commander_config(self, guild_id: int) -> dict[str, object]:
        raw_priority = await self.settings.get(
            guild_id,
            "patrol_commander_selection_priority",
            list(COMMANDER_PRIORITY_DEFAULT),
        )
        priority: list[str] = []
        if isinstance(raw_priority, list):
            for value in raw_priority:
                normalized = str(value).strip().upper()
                if normalized in COMMANDER_PRIORITY_ALLOWED and normalized not in priority:
                    priority.append(normalized)
        priority.extend(value for value in COMMANDER_PRIORITY_DEFAULT if value not in priority)
        qualification_id = await self.settings.get(
            guild_id, "patrol_commander_required_qualification_id"
        )
        qualification = None
        if qualification_id is not None:
            try:
                qualification = await self.database.fetchone(
                    "SELECT id, internal_code, name FROM course_catalog "
                    "WHERE guild_id=? AND id=? AND active=1",
                    (guild_id, int(qualification_id)),
                )
            except (TypeError, ValueError):
                qualification_id = None
        return {
            "enabled": bool(
                await self.settings.get(guild_id, "patrol_commander_enabled", True)
            ),
            "require_qualification": bool(
                await self.settings.get(
                    guild_id, "patrol_commander_require_qualification", False
                )
            ),
            "required_qualification_id": (
                int(qualification["id"]) if qualification is not None else None
            ),
            "required_qualification_name": (
                str(qualification["name"]) if qualification is not None else None
            ),
            "minimum_rank_level": max(
                0,
                int(
                    await self.settings.get(
                        guild_id, "patrol_commander_minimum_rank_level", 0
                    )
                ),
            ),
            "selection_priority": priority,
            "reassign_when_higher_rank_joins": bool(
                await self.settings.get(
                    guild_id,
                    "patrol_commander_reassign_when_higher_rank_joins",
                    False,
                )
            ),
        }

    async def configure_patrol_commander(
        self,
        guild_id: int,
        actor_id: int,
        *,
        enabled: bool,
        require_qualification: bool,
        required_qualification_id: int | None,
        minimum_rank_level: int,
        reassign_when_higher_rank_joins: bool,
        selection_priority: Iterable[str] | None = None,
    ) -> dict[str, object]:
        if minimum_rank_level < 0:
            raise ValidationError("O nível mínimo de patente não pode ser negativo.")
        course = None
        if required_qualification_id is not None:
            course = await self.database.fetchone(
                "SELECT id, name FROM course_catalog WHERE guild_id=? AND id=? AND active=1",
                (guild_id, required_qualification_id),
            )
            if not course:
                raise ValidationError("A qualificação selecionada não existe ou está inativa.")
        if require_qualification and not course:
            raise ValidationError("Selecione uma qualificação antes de torná-la obrigatória.")
        priority: list[str] = []
        for value in selection_priority or COMMANDER_PRIORITY_DEFAULT:
            normalized = str(value).strip().upper()
            if normalized not in COMMANDER_PRIORITY_ALLOWED:
                raise ValidationError(f"Critério de comando inválido: {normalized}.")
            if normalized not in priority:
                priority.append(normalized)
        priority.extend(value for value in COMMANDER_PRIORITY_DEFAULT if value not in priority)
        before = await self.patrol_commander_config(guild_id)
        async with self.database.transaction() as connection:
            values = {
                "patrol_commander_enabled": bool(enabled),
                "patrol_commander_require_qualification": bool(require_qualification),
                "patrol_commander_required_qualification_id": required_qualification_id,
                "patrol_commander_minimum_rank_level": int(minimum_rank_level),
                "patrol_commander_reassign_when_higher_rank_joins": bool(
                    reassign_when_higher_rank_joins
                ),
                "patrol_commander_selection_priority": priority,
            }
            for key, value in values.items():
                await self.settings.set(guild_id, key, value, actor_id, connection)
            after = {
                "enabled": bool(enabled),
                "require_qualification": bool(require_qualification),
                "required_qualification_id": required_qualification_id,
                "required_qualification_name": str(course["name"]) if course else None,
                "minimum_rank_level": int(minimum_rank_level),
                "selection_priority": priority,
                "reassign_when_higher_rank_joins": bool(reassign_when_higher_rank_joins),
            }
            await self.audit.record(
                guild_id,
                "PATROL_COMMANDER_CONFIGURATION_CHANGED",
                actor_id=actor_id,
                before=before,
                after=after,
                connection=connection,
            )
        return after

    async def effective_operational_status(self, guild_id: int, discord_id: int) -> str:
        now = self.clock()
        row = await self.database.fetchone(
            """
            SELECT m.id, m.status, COALESCE(os.manual_status, 'UNAVAILABLE') AS manual_status,
                EXISTS(
                    SELECT 1 FROM patrol_members pm JOIN patrols p ON p.id=pm.patrol_id
                    WHERE pm.guild_id=m.guild_id AND pm.member_id=m.id
                      AND pm.status='ACTIVE' AND p.status='ACTIVE'
                ) AS on_patrol,
                EXISTS(
                    SELECT 1 FROM training_enrollments te
                    JOIN training_events t ON t.id=te.training_id
                    WHERE te.guild_id=m.guild_id AND te.member_id=m.id
                      AND te.enrollment_status='ENROLLED' AND t.status IN ('OPEN','CLOSED')
                      AND t.scheduled_at<=?
                ) AS in_training
            FROM members m
            LEFT JOIN member_operational_status os
              ON os.guild_id=m.guild_id AND os.member_id=m.id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (now, guild_id, discord_id),
        )
        if not row:
            raise NotFoundError("Membro não cadastrado.")
        if row["status"] == "AWAY":
            return "AWAY"
        if row["status"] in {"SUSPENDED", "RESERVE", "DISMISSED", "PENDING"}:
            return "UNAVAILABLE"
        if row["on_patrol"]:
            return "ON_PATROL"
        if row["in_training"]:
            return "IN_TRAINING"
        return str(row["manual_status"])

    async def set_availability(
        self, guild_id: int, discord_id: int, available: bool, actor_id: int
    ) -> str:
        await self.require_available_module(guild_id, "PATROLS")
        now = self.clock()
        async with self.database.transaction() as connection:
            member = await self._member_in_tx(connection, guild_id, discord_id)
            if member["status"] != "ACTIVE":
                raise ValidationError("Somente membros ativos podem alterar a disponibilidade.")
            status = "AVAILABLE_FOR_PATROL" if available else "UNAVAILABLE"
            await connection.execute(
                """
                INSERT INTO member_operational_status(
                    guild_id, member_id, discord_id, manual_status, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, member_id) DO UPDATE SET
                    manual_status=excluded.manual_status,
                    updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by
                """,
                (guild_id, member["id"], discord_id, status, now, actor_id),
            )
            if not available:
                await connection.execute(
                    """
                    UPDATE patrol_queue_entries
                    SET status='REMOVED', updated_at=?, exited_at=?, exit_reason='UNAVAILABLE'
                    WHERE guild_id=? AND member_id=? AND status='QUEUED'
                    """,
                    (now, now, guild_id, member["id"]),
                )
            await self.audit.record(
                guild_id,
                "AVAILABILITY_CHANGED",
                actor_id=actor_id,
                target_id=discord_id,
                after={"manual_status": status},
                connection=connection,
            )
            await self._event(
                connection,
                guild_id,
                "MEMBER_AVAILABILITY_CHANGED",
                "MEMBER",
                int(member["id"]),
                f"availability:{member['id']}:{now}",
                {"discord_id": discord_id, "manual_status": status},
            )
        return status

    async def join_queue(
        self,
        guild_id: int,
        discord_id: int,
        connected_channel_id: int | None,
        *,
        source: str,
        has_member_role: bool,
    ) -> int:
        await self.require_available_module(guild_id, "PATROLS")
        source = source.upper()
        if source not in {"VOICE", "PANEL", "RECOVERY"}:
            raise ValidationError("Origem da fila inválida.")
        waiting_channel = await self.waiting_channel_id(guild_id)
        if waiting_channel is None:
            raise ValidationError("A call Aguardando Patrulha ainda não foi configurada.")
        if connected_channel_id != waiting_channel:
            raise ValidationError("Entre na call Aguardando Patrulha antes de entrar na fila.")
        if not has_member_role:
            raise ValidationError("Seu cargo de membro não está sincronizado.")
        now = self.clock()
        async with self.database.transaction() as connection:
            member = await self._member_in_tx(connection, guild_id, discord_id)
            if member["status"] != "ACTIVE":
                raise ValidationError("Seu status administrativo não permite patrulhar.")
            if member["rank_id"] is None or member["rank_role_id"] is None:
                raise ValidationError("Sua patente ainda não está configurada.")
            if member["rank_sync_status"] != "SYNCED":
                raise ValidationError("Sua patente ou identificação precisa ser sincronizada.")
            cursor = await connection.execute(
                """
                SELECT 1 FROM patrol_members pm JOIN patrols p ON p.id=pm.patrol_id
                WHERE pm.guild_id=? AND pm.member_id=?
                  AND pm.status IN ('RESERVED','ACTIVE')
                  AND p.status IN ('RESERVED','ACTIVE')
                """,
                (guild_id, member["id"]),
            )
            if await cursor.fetchone():
                raise ConflictError("Você já participa de uma patrulha em andamento.")
            cursor = await connection.execute(
                """
                SELECT 1 FROM training_enrollments te
                JOIN training_events t ON t.id=te.training_id
                WHERE te.guild_id=? AND te.member_id=?
                  AND te.enrollment_status='ENROLLED' AND t.status IN ('OPEN','CLOSED')
                  AND t.scheduled_at<=?
                LIMIT 1
                """,
                (guild_id, member["id"], now),
            )
            if await cursor.fetchone():
                raise ValidationError("Você está em um treinamento incompatível com a fila.")
            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO patrol_queue_entries(
                        guild_id, member_id, discord_id, status, source,
                        queue_entered_at, updated_at
                    ) VALUES (?, ?, ?, 'QUEUED', ?, ?, ?)
                    """,
                    (guild_id, member["id"], discord_id, source, now, now),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("Você já está na fila de patrulha.") from exc
            queue_id = int(cursor.lastrowid)
            await connection.execute(
                """
                INSERT INTO member_operational_status(
                    guild_id, member_id, discord_id, manual_status, updated_at, updated_by
                ) VALUES (?, ?, ?, 'AVAILABLE_FOR_PATROL', ?, ?)
                ON CONFLICT(guild_id, member_id) DO UPDATE SET
                    manual_status='AVAILABLE_FOR_PATROL', updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by
                """,
                (guild_id, member["id"], discord_id, now, discord_id),
            )
            await self.audit.record(
                guild_id,
                "PATROL_QUEUE_JOINED",
                actor_id=discord_id,
                target_id=discord_id,
                after={"queue_id": queue_id, "source": source},
                connection=connection,
            )
        return queue_id

    async def leave_queue(
        self, guild_id: int, discord_id: int, *, reason: str = "MEMBER_LEFT"
    ) -> bool:
        now = self.clock()
        async with self.database.transaction() as connection:
            member = await self._member_in_tx(connection, guild_id, discord_id)
            cursor = await connection.execute(
                """
                UPDATE patrol_queue_entries
                SET status='REMOVED', updated_at=?, exited_at=?, exit_reason=?
                WHERE guild_id=? AND member_id=? AND status='QUEUED'
                """,
                (now, now, reason, guild_id, member["id"]),
            )
            if cursor.rowcount != 1:
                return False
            await self.audit.record(
                guild_id,
                "PATROL_QUEUE_LEFT",
                actor_id=discord_id,
                target_id=discord_id,
                after={"reason": reason},
                connection=connection,
            )
        return True

    async def queue(self, guild_id: int):
        return await self.database.fetchall(
            """
            SELECT q.*, m.mta_nick, r.name AS rank_name
            FROM patrol_queue_entries q
            JOIN members m ON m.id=q.member_id
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE q.guild_id=? AND q.status IN ('QUEUED','FORMING')
            ORDER BY q.queue_entered_at, q.id
            """,
            (guild_id,),
        )

    async def reserve_formations(
        self,
        guild_id: int,
        waiting_discord_ids: Iterable[int],
        free_channel_ids: Iterable[int],
    ) -> list[dict[str, object]]:
        await self.require_available_module(guild_id, "PATROLS")
        minimum = int(await self.settings.get(guild_id, "minimum_patrol_members", 2))
        if not 2 <= minimum <= 10:
            raise ValidationError("O mínimo de integrantes deve ficar entre 2 e 10.")
        waiting_ids = {int(value) for value in waiting_discord_ids}
        free_ids = {int(value) for value in free_channel_ids}
        if len(waiting_ids) < minimum or not free_ids:
            return []
        now = self.clock()
        plans: list[dict[str, object]] = []
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT q.*, m.status AS member_status, m.rank_id, m.rank_sync_status
                FROM patrol_queue_entries q JOIN members m ON m.id=q.member_id
                WHERE q.guild_id=? AND q.status='QUEUED'
                ORDER BY q.queue_entered_at, q.id
                """,
                (guild_id,),
            )
            queued = [
                row
                for row in await cursor.fetchall()
                if int(row["discord_id"]) in waiting_ids
                and row["member_status"] == "ACTIVE"
                and row["rank_id"] is not None
                and row["rank_sync_status"] == "SYNCED"
            ]
            placeholders = ",".join("?" for _ in free_ids)
            if not placeholders:
                return []
            cursor = await connection.execute(
                f"""
                SELECT pc.* FROM patrol_channels pc
                WHERE pc.guild_id=? AND pc.channel_type='ACTIVE' AND pc.enabled=1
                  AND pc.channel_id IN ({placeholders})
                  AND NOT EXISTS(
                      SELECT 1 FROM patrols p
                      WHERE p.guild_id=pc.guild_id AND p.voice_channel_id=pc.channel_id
                        AND p.status IN ('RESERVED','ACTIVE')
                  )
                ORDER BY pc.sort_order, pc.channel_id
                """,
                (guild_id, *sorted(free_ids)),
            )
            channels = list(await cursor.fetchall())
            cursor = await connection.execute(
                "SELECT COALESCE(MAX(sequence_number), 0) AS sequence FROM patrols WHERE guild_id=?",
                (guild_id,),
            )
            sequence = int((await cursor.fetchone())["sequence"])
            continue_until_empty = bool(
                await self.settings.get(guild_id, "patrol_continue_until_empty", True)
            )
            while len(queued) >= minimum and channels:
                selected = queued[:minimum]
                queued = queued[minimum:]
                channel = channels.pop(0)
                sequence += 1
                cursor = await connection.execute(
                    """
                    INSERT INTO patrols(
                        guild_id, sequence_number, voice_channel_id, status, origin,
                        minimum_members, continue_until_empty, leader_member_id,
                        reserved_at, created_at, updated_at
                    ) VALUES (?, ?, ?, 'RESERVED', 'AUTO', ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        sequence,
                        channel["channel_id"],
                        minimum,
                        int(continue_until_empty),
                        now,
                        now,
                        now,
                    ),
                )
                patrol_id = int(cursor.lastrowid)
                for row in selected:
                    update = await connection.execute(
                        """
                        UPDATE patrol_queue_entries
                        SET status='FORMING', patrol_id=?, updated_at=?
                        WHERE id=? AND status='QUEUED'
                        """,
                        (patrol_id, now, row["id"]),
                    )
                    if update.rowcount != 1:
                        raise ConflictError("A fila mudou durante a formação.")
                    await connection.execute(
                        """
                        INSERT INTO patrol_members(
                            guild_id, patrol_id, member_id, discord_id, member_role,
                            status, reserved_at
                        ) VALUES (?, ?, ?, ?, ?, 'RESERVED', ?)
                        """,
                        (
                            guild_id,
                            patrol_id,
                            row["member_id"],
                            row["discord_id"],
                            "MEMBER",
                            now,
                        ),
                    )
                member_ids = [int(row["discord_id"]) for row in selected]
                await self._event(
                    connection,
                    guild_id,
                    "PATROL_CREATED",
                    "PATROL",
                    patrol_id,
                    f"patrol:reserved:{patrol_id}",
                    {"channel_id": int(channel["channel_id"]), "members": member_ids},
                )
                plans.append(
                    {
                        "patrol_id": patrol_id,
                        "sequence_number": sequence,
                        "channel_id": int(channel["channel_id"]),
                        "member_discord_ids": member_ids,
                    }
                )
        return plans

    async def activate_formation(
        self,
        guild_id: int,
        patrol_id: int,
        present_discord_ids: Iterable[int] | None = None,
    ) -> dict[str, object]:
        now = self.clock()
        config = await self.patrol_commander_config(guild_id)
        present = (
            {int(value) for value in present_discord_ids}
            if present_discord_ids is not None
            else None
        )
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE patrols SET status='ACTIVE', started_at=?, updated_at=?
                WHERE guild_id=? AND id=? AND status='RESERVED'
                """,
                (now, now, guild_id, patrol_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A reserva da patrulha não está mais disponível.")
            cursor = await connection.execute(
                "SELECT * FROM patrol_members WHERE patrol_id=? AND status='RESERVED' ORDER BY id",
                (patrol_id,),
            )
            members = list(await cursor.fetchall())
            for member in members:
                shift_cursor = await connection.execute(
                    """
                    SELECT s.id FROM shifts s
                    WHERE s.guild_id=? AND s.member_id=? AND s.status IN ('ACTIVE','GRACE')
                    ORDER BY s.id DESC LIMIT 1
                    """,
                    (guild_id, member["member_id"]),
                )
                shift = await shift_cursor.fetchone()
                await connection.execute(
                    """
                    UPDATE patrol_members SET status='ACTIVE', joined_at=?, associated_shift_id=?
                    WHERE id=? AND status='RESERVED'
                    """,
                    (now, int(shift["id"]) if shift else None, member["id"]),
                )
                await connection.execute(
                    """
                    UPDATE patrol_queue_entries
                    SET status='FORMED', updated_at=?, exited_at=?, exit_reason='PATROL_FORMED'
                    WHERE guild_id=? AND member_id=? AND status='FORMING' AND patrol_id=?
                    """,
                    (now, now, guild_id, member["member_id"], patrol_id),
                )
                await connection.execute(
                    """
                    INSERT INTO member_operational_status(
                        guild_id, member_id, discord_id, manual_status, updated_at
                    ) VALUES (?, ?, ?, 'AVAILABLE_FOR_PATROL', ?)
                    ON CONFLICT(guild_id, member_id) DO UPDATE SET updated_at=excluded.updated_at
                    """,
                    (guild_id, member["member_id"], member["discord_id"], now),
                )
            commander = await self._select_patrol_commander_in_tx(
                connection,
                guild_id,
                patrol_id,
                config,
                present,
                reason="PATROL_CREATED",
            )
            await self.audit.record(
                guild_id,
                "PATROL_AUTO_CREATED",
                after={
                    "patrol_id": patrol_id,
                    "members": [int(row["discord_id"]) for row in members],
                    "commander_discord_id": commander.get("commander_discord_id"),
                },
                connection=connection,
            )
            await self._event(
                connection,
                guild_id,
                "PATROL_CREATED",
                "PATROL",
                patrol_id,
                f"patrol:active:{patrol_id}",
                {"member_count": len(members)},
            )
        return {
            "patrol_id": patrol_id,
            "member_count": len(members),
            "commander_discord_id": commander.get("commander_discord_id"),
        }

    async def rollback_formation(self, guild_id: int, patrol_id: int, error: str) -> None:
        now = self.clock()
        message = error.strip()[:1000] or "Falha de movimentação"
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE patrols SET status='CANCELLED', ended_at=?, end_reason='MOVE_FAILED',
                    movement_error=?, updated_at=?
                WHERE guild_id=? AND id=? AND status='RESERVED'
                """,
                (now, message, now, guild_id, patrol_id),
            )
            if cursor.rowcount != 1:
                return
            await connection.execute(
                "UPDATE patrol_members SET status='CANCELLED', left_at=? WHERE patrol_id=?",
                (now, patrol_id),
            )
            await connection.execute(
                """
                UPDATE patrol_queue_entries
                SET status='QUEUED', patrol_id=NULL, updated_at=?, exited_at=NULL, exit_reason=NULL
                WHERE guild_id=? AND patrol_id=? AND status='FORMING'
                """,
                (now, guild_id, patrol_id),
            )
            await self.audit.record(
                guild_id,
                "PATROL_FORMATION_MOVE_FAILED",
                after={"patrol_id": patrol_id},
                reason=message,
                connection=connection,
            )

    async def _commander_candidates_in_tx(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        patrol_id: int,
        config: dict[str, object],
        present_discord_ids: set[int] | None,
    ) -> list[dict[str, object]]:
        now = self.clock()
        qualification_name = config.get("required_qualification_name")
        cursor = await connection.execute(
            """
            SELECT pm.id AS patrol_member_id, pm.member_id, pm.discord_id,
                   COALESCE(pm.joined_at, pm.reserved_at) AS patrol_joined_at,
                   m.mta_nick, m.status AS member_status, m.joined_at AS member_joined_at,
                   m.rank_sync_status, m.rank_id,
                   r.name AS rank_name, r.prefix AS rank_prefix, r.level AS rank_level,
                   COALESCE((
                       SELECT MAX(changed_at) FROM (
                           SELECT pa.created_at AS changed_at
                           FROM personnel_actions pa
                           WHERE pa.guild_id=m.guild_id AND pa.member_id=m.id
                             AND pa.to_rank_id=m.rank_id
                           UNION ALL
                           SELECT rse.created_at AS changed_at
                           FROM rank_sync_events rse
                           WHERE rse.guild_id=m.guild_id AND rse.member_id=m.id
                             AND rse.to_rank_id=m.rank_id
                             AND rse.from_rank_id IS NOT rse.to_rank_id
                       )
                   ), m.joined_at) AS rank_since,
                   COALESCE((
                       SELECT SUM(
                           s.patrol_duration_ms + COALESCE((
                               SELECT SUM(sa.delta_ms)
                               FROM shift_adjustments sa WHERE sa.shift_id=s.id
                           ), 0)
                       )
                       FROM shifts s
                       WHERE s.guild_id=m.guild_id AND s.member_id=m.id
                         AND s.status='CLOSED' AND s.validation_status='VALID'
                   ), 0) AS valid_service_ms,
                   EXISTS(
                       SELECT 1 FROM punishments pu
                       WHERE pu.guild_id=m.guild_id AND pu.member_id=m.id
                         AND pu.punishment_type='SUSPENSION'
                         AND pu.status IN ('SCHEDULED','ACTIVE')
                         AND pu.starts_at<=? AND (pu.ends_at IS NULL OR pu.ends_at>?)
                   ) AS has_active_suspension,
                   EXISTS(
                       SELECT 1 FROM absence_requests ar
                       WHERE ar.guild_id=m.guild_id AND ar.member_id=m.id
                         AND ar.status='APPROVED' AND ar.starts_at<=? AND ar.ends_at>?
                   ) AS has_active_absence,
                   CASE WHEN ? IS NULL THEN 0 ELSE EXISTS(
                       SELECT 1 FROM member_qualifications mq
                       WHERE mq.guild_id=m.guild_id AND mq.member_id=m.id
                         AND mq.result='APPROVED' AND lower(mq.course_name)=lower(?)
                   ) END AS has_required_qualification
            FROM patrol_members pm
            JOIN members m ON m.id=pm.member_id
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE pm.guild_id=? AND pm.patrol_id=? AND pm.status='ACTIVE'
            ORDER BY COALESCE(pm.joined_at, pm.reserved_at), pm.id
            """,
            (
                now,
                now,
                now,
                now,
                qualification_name,
                qualification_name,
                guild_id,
                patrol_id,
            ),
        )
        minimum_rank_level = int(config["minimum_rank_level"])
        require_qualification = bool(config["require_qualification"])
        candidates: list[dict[str, object]] = []
        for raw in await cursor.fetchall():
            row = dict(raw)
            discord_id = int(row["discord_id"])
            eligible = (
                row["member_status"] == "ACTIVE"
                and row["rank_id"] is not None
                and row["rank_sync_status"] == "SYNCED"
                and row["rank_level"] is not None
                and int(row["rank_level"]) >= minimum_rank_level
                and not bool(row["has_active_suspension"])
                and not bool(row["has_active_absence"])
                and (present_discord_ids is None or discord_id in present_discord_ids)
                and (not require_qualification or bool(row["has_required_qualification"]))
            )
            if eligible:
                candidates.append(row)
        return candidates

    @staticmethod
    def _commander_sort_key(
        candidate: dict[str, object], priority: list[str]
    ) -> tuple[int, ...]:
        keys: list[int] = []
        for criterion in priority:
            if criterion == "QUALIFICATION":
                keys.append(-int(bool(candidate["has_required_qualification"])))
            elif criterion == "RANK_LEVEL":
                keys.append(-int(candidate["rank_level"]))
            elif criterion == "TIME_IN_RANK":
                keys.append(int(candidate["rank_since"]))
            elif criterion == "TOTAL_SERVICE_TIME":
                keys.append(-int(candidate["valid_service_ms"]))
            elif criterion == "MEMBERSHIP_TIME":
                keys.append(int(candidate["member_joined_at"]))
            elif criterion == "PATROL_JOIN_ORDER":
                keys.append(int(candidate["patrol_joined_at"]))
        keys.extend(
            (int(candidate["patrol_joined_at"]), int(candidate["patrol_member_id"]))
        )
        return tuple(keys)

    async def _write_commander_change_in_tx(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        patrol_id: int,
        before_member_id: int | None,
        before_discord_id: int | None,
        after: dict[str, object] | None,
        *,
        source: str,
        reason: str,
        actor_id: int | None,
        manual_lock: bool,
    ) -> dict[str, object]:
        now = self.clock()
        after_member_id = int(after["member_id"]) if after else None
        after_discord_id = int(after["discord_id"]) if after else None
        await connection.execute(
            """
            UPDATE patrol_commander_history SET ended_at=?
            WHERE patrol_id=? AND ended_at IS NULL
            """,
            (now, patrol_id),
        )
        await connection.execute(
            "UPDATE patrol_members SET member_role='MEMBER' WHERE patrol_id=?",
            (patrol_id,),
        )
        if after_member_id is not None:
            await connection.execute(
                """
                UPDATE patrol_members SET member_role='LEADER'
                WHERE patrol_id=? AND member_id=? AND status='ACTIVE'
                """,
                (patrol_id, after_member_id),
            )
            await connection.execute(
                """
                INSERT INTO patrol_commander_history(
                    guild_id, patrol_id, member_id, discord_id, started_at,
                    source, reason, assigned_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    patrol_id,
                    after_member_id,
                    after_discord_id,
                    now,
                    source,
                    reason,
                    actor_id,
                ),
            )
        await connection.execute(
            """
            UPDATE patrols SET leader_member_id=?, commander_member_id=?,
                commander_assigned_at=?, commander_assignment_source=?,
                commander_manual_lock=?, updated_at=?
            WHERE guild_id=? AND id=? AND status='ACTIVE'
            """,
            (
                after_member_id,
                after_member_id,
                now if after else None,
                source if after else None,
                int(bool(after and manual_lock)),
                now,
                guild_id,
                patrol_id,
            ),
        )
        if after:
            await connection.execute(
                """
                UPDATE patrol_operational_flags
                SET status='RESOLVED', resolved_at=?, resolution='COMMANDER_ASSIGNED'
                WHERE patrol_id=? AND flag_type='PATROL_WITHOUT_ELIGIBLE_COMMANDER'
                  AND status='OPEN'
                """,
                (now, patrol_id),
            )
        else:
            await connection.execute(
                """
                INSERT OR IGNORE INTO patrol_operational_flags(
                    guild_id, patrol_id, flag_type, evidence_json, created_at
                ) VALUES (?, ?, 'PATROL_WITHOUT_ELIGIBLE_COMMANDER', ?, ?)
                """,
                (
                    guild_id,
                    patrol_id,
                    json.dumps({"reason": reason}, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
        if source == "MANUAL_OVERRIDE":
            action = "PATROL_COMMANDER_OVERRIDDEN"
        elif after is None:
            action = "PATROL_COMMANDER_CLEARED"
        elif before_member_id is None:
            action = "PATROL_COMMANDER_ASSIGNED"
        else:
            action = "PATROL_COMMANDER_REASSIGNED"
        await self.audit.record(
            guild_id,
            action,
            actor_id=actor_id,
            target_id=after_discord_id or before_discord_id,
            before={
                "patrol_id": patrol_id,
                "commander_member_id": before_member_id,
                "commander_discord_id": before_discord_id,
            },
            after={
                "patrol_id": patrol_id,
                "commander_member_id": after_member_id,
                "commander_discord_id": after_discord_id,
                "source": source if after else None,
                "manual_lock": bool(after and manual_lock),
            },
            reason=reason,
            connection=connection,
        )
        await self._event(
            connection,
            guild_id,
            action,
            "PATROL",
            patrol_id,
            f"patrol:commander:{patrol_id}:{before_member_id}:{after_member_id}:{now}",
            {
                "before": before_discord_id,
                "after": after_discord_id,
                "source": source if after else None,
                "reason": reason,
                "actor": actor_id,
            },
        )
        return {
            "changed": True,
            "patrol_id": patrol_id,
            "commander_member_id": after_member_id,
            "commander_discord_id": after_discord_id,
            "source": source if after else None,
            "manual_lock": bool(after and manual_lock),
        }

    async def _select_patrol_commander_in_tx(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        patrol_id: int,
        config: dict[str, object],
        present_discord_ids: set[int] | None,
        *,
        reason: str,
    ) -> dict[str, object]:
        cursor = await connection.execute(
            """
            SELECT p.*, m.discord_id AS commander_discord_id
            FROM patrols p LEFT JOIN members m ON m.id=p.commander_member_id
            WHERE p.guild_id=? AND p.id=? AND p.status='ACTIVE'
            """,
            (guild_id, patrol_id),
        )
        patrol = await cursor.fetchone()
        if not patrol:
            raise NotFoundError("Patrulha ativa não encontrada.")
        before_member_id = (
            int(patrol["commander_member_id"])
            if patrol["commander_member_id"] is not None
            else None
        )
        before_discord_id = (
            int(patrol["commander_discord_id"])
            if patrol["commander_discord_id"] is not None
            else None
        )
        if not bool(config["enabled"]):
            if before_member_id is None:
                return {
                    "changed": False,
                    "patrol_id": patrol_id,
                    "commander_member_id": None,
                    "commander_discord_id": None,
                    "source": None,
                    "manual_lock": False,
                }
            return await self._write_commander_change_in_tx(
                connection,
                guild_id,
                patrol_id,
                before_member_id,
                before_discord_id,
                None,
                source="REASSIGNMENT",
                reason="COMMANDER_MODULE_DISABLED",
                actor_id=None,
                manual_lock=False,
            )
        candidates = await self._commander_candidates_in_tx(
            connection, guild_id, patrol_id, config, present_discord_ids
        )
        eligible_by_id = {int(row["member_id"]): row for row in candidates}
        current = eligible_by_id.get(before_member_id) if before_member_id is not None else None
        preserve_current = bool(
            current
            and (
                bool(patrol["commander_manual_lock"])
                or not bool(config["reassign_when_higher_rank_joins"])
            )
        )
        if preserve_current:
            return {
                "changed": False,
                "patrol_id": patrol_id,
                "commander_member_id": before_member_id,
                "commander_discord_id": before_discord_id,
                "source": patrol["commander_assignment_source"],
                "manual_lock": bool(patrol["commander_manual_lock"]),
            }
        priority = [str(value) for value in config["selection_priority"]]
        selected = min(candidates, key=lambda item: self._commander_sort_key(item, priority)) if candidates else None
        selected_member_id = int(selected["member_id"]) if selected else None
        if selected_member_id == before_member_id:
            if selected_member_id is None:
                now = self.clock()
                cursor = await connection.execute(
                    """
                    INSERT OR IGNORE INTO patrol_operational_flags(
                        guild_id, patrol_id, flag_type, evidence_json, created_at
                    ) VALUES (?, ?, 'PATROL_WITHOUT_ELIGIBLE_COMMANDER', ?, ?)
                    """,
                    (
                        guild_id,
                        patrol_id,
                        json.dumps(
                            {"reason": "NO_ELIGIBLE_COMMANDER"},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now,
                    ),
                )
                if cursor.rowcount == 1:
                    await self.audit.record(
                        guild_id,
                        "PATROL_COMMANDER_CLEARED",
                        after={"patrol_id": patrol_id, "commander_member_id": None},
                        reason="NO_ELIGIBLE_COMMANDER",
                        connection=connection,
                    )
                    await self._event(
                        connection,
                        guild_id,
                        "PATROL_COMMANDER_CLEARED",
                        "PATROL",
                        patrol_id,
                        f"patrol:commander:none:{patrol_id}:{now}",
                        {"before": None, "after": None, "reason": "NO_ELIGIBLE_COMMANDER"},
                    )
            return {
                "changed": False,
                "patrol_id": patrol_id,
                "commander_member_id": before_member_id,
                "commander_discord_id": before_discord_id,
                "source": patrol["commander_assignment_source"],
                "manual_lock": bool(patrol["commander_manual_lock"]),
            }
        source = "AUTOMATIC" if before_member_id is None and reason == "PATROL_CREATED" else "REASSIGNMENT"
        return await self._write_commander_change_in_tx(
            connection,
            guild_id,
            patrol_id,
            before_member_id,
            before_discord_id,
            selected,
            source=source,
            reason=reason if selected else "NO_ELIGIBLE_COMMANDER",
            actor_id=None,
            manual_lock=False,
        )

    async def select_patrol_commander(
        self,
        guild_id: int,
        patrol_id: int,
        present_discord_ids: Iterable[int] | None,
        *,
        reason: str,
    ) -> dict[str, object]:
        config = await self.patrol_commander_config(guild_id)
        present = (
            {int(value) for value in present_discord_ids}
            if present_discord_ids is not None
            else None
        )
        async with self.database.transaction() as connection:
            return await self._select_patrol_commander_in_tx(
                connection, guild_id, patrol_id, config, present, reason=reason
            )

    async def override_patrol_commander(
        self,
        guild_id: int,
        patrol_id: int,
        commander_discord_id: int,
        actor_id: int,
        reason: str,
        present_discord_ids: Iterable[int],
    ) -> dict[str, object]:
        reason = reason.strip()
        if not reason:
            raise ValidationError("Informe o motivo da alteração de comandante.")
        config = await self.patrol_commander_config(guild_id)
        if not bool(config["enabled"]):
            raise ValidationError("O comandante automático está desativado.")
        present = {int(value) for value in present_discord_ids}
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT p.commander_member_id, m.discord_id AS commander_discord_id
                FROM patrols p LEFT JOIN members m ON m.id=p.commander_member_id
                WHERE p.guild_id=? AND p.id=? AND p.status='ACTIVE'
                """,
                (guild_id, patrol_id),
            )
            patrol = await cursor.fetchone()
            if not patrol:
                raise NotFoundError("Patrulha ativa não encontrada.")
            candidates = await self._commander_candidates_in_tx(
                connection, guild_id, patrol_id, config, present
            )
            selected = next(
                (
                    row
                    for row in candidates
                    if int(row["discord_id"]) == int(commander_discord_id)
                ),
                None,
            )
            if not selected:
                raise ValidationError(
                    "O militar precisa integrar a patrulha, estar na call e permanecer elegível."
                )
            before_member_id = (
                int(patrol["commander_member_id"])
                if patrol["commander_member_id"] is not None
                else None
            )
            if before_member_id == int(selected["member_id"]):
                raise ConflictError("O militar selecionado já comanda esta patrulha.")
            return await self._write_commander_change_in_tx(
                connection,
                guild_id,
                patrol_id,
                before_member_id,
                (
                    int(patrol["commander_discord_id"])
                    if patrol["commander_discord_id"] is not None
                    else None
                ),
                selected,
                source="MANUAL_OVERRIDE",
                reason=reason,
                actor_id=actor_id,
                manual_lock=True,
            )

    async def patrol_commander_history(self, guild_id: int, patrol_id: int):
        return await self.database.fetchall(
            """
            SELECT h.*, m.mta_nick, r.name AS rank_name, r.prefix AS rank_prefix
            FROM patrol_commander_history h
            JOIN members m ON m.id=h.member_id
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE h.guild_id=? AND h.patrol_id=?
            ORDER BY h.started_at, h.id
            """,
            (guild_id, patrol_id),
        )

    async def active_patrol_members(self, guild_id: int, patrol_id: int):
        return await self.database.fetchall(
            """
            SELECT pm.*, m.mta_nick, r.name AS rank_name, r.prefix AS rank_prefix,
                   r.level AS rank_level
            FROM patrol_members pm JOIN members m ON m.id=pm.member_id
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE pm.guild_id=? AND pm.patrol_id=? AND pm.status='ACTIVE'
            ORDER BY COALESCE(pm.joined_at, pm.reserved_at), pm.id
            """,
            (guild_id, patrol_id),
        )

    async def active_patrols(self, guild_id: int):
        return await self.database.fetchall(
            """
            SELECT p.*,
                COUNT(CASE WHEN pm.status='ACTIVE' THEN 1 END) AS member_count,
                GROUP_CONCAT(CASE WHEN pm.status='ACTIVE' THEN pm.discord_id END) AS member_ids,
                commander.discord_id AS commander_discord_id,
                commander.mta_nick AS commander_mta_nick,
                commander_rank.name AS commander_rank_name,
                commander_rank.prefix AS commander_rank_prefix
            FROM patrols p LEFT JOIN patrol_members pm ON pm.patrol_id=p.id
            LEFT JOIN members commander ON commander.id=p.commander_member_id
            LEFT JOIN ranks commander_rank ON commander_rank.id=commander.rank_id
            WHERE p.guild_id=? AND p.status='ACTIVE'
            GROUP BY p.id ORDER BY p.started_at, p.id
            """,
            (guild_id,),
        )

    async def current_patrol(self, guild_id: int, discord_id: int):
        return await self.database.fetchone(
            """
            SELECT p.*, pm.member_role, pm.joined_at, pm.associated_shift_id,
                   commander.discord_id AS commander_discord_id,
                   commander.mta_nick AS commander_mta_nick,
                   commander_rank.name AS commander_rank_name,
                   commander_rank.prefix AS commander_rank_prefix
            FROM patrol_members pm JOIN patrols p ON p.id=pm.patrol_id
            LEFT JOIN members commander ON commander.id=p.commander_member_id
            LEFT JOIN ranks commander_rank ON commander_rank.id=commander.rank_id
            WHERE pm.guild_id=? AND pm.discord_id=? AND pm.status='ACTIVE'
              AND p.status='ACTIVE'
            ORDER BY p.id DESC LIMIT 1
            """,
            (guild_id, discord_id),
        )

    async def mark_patrol_member_left(
        self, guild_id: int, discord_id: int, voice_channel_id: int
    ) -> dict[str, object] | None:
        now = self.clock()
        config = await self.patrol_commander_config(guild_id)
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT p.*, pm.id AS patrol_member_id,
                       pm.member_id AS leaving_member_id
                FROM patrols p JOIN patrol_members pm ON pm.patrol_id=p.id
                WHERE p.guild_id=? AND p.voice_channel_id=? AND p.status='ACTIVE'
                  AND pm.discord_id=? AND pm.status='ACTIVE'
                """,
                (guild_id, voice_channel_id, discord_id),
            )
            patrol = await cursor.fetchone()
            if not patrol:
                return None
            await connection.execute(
                "UPDATE patrol_members SET status='LEFT', left_at=? WHERE id=? AND status='ACTIVE'",
                (now, patrol["patrol_member_id"]),
            )
            cursor = await connection.execute(
                "SELECT COUNT(*) AS total FROM patrol_members WHERE patrol_id=? AND status='ACTIVE'",
                (patrol["id"],),
            )
            remaining = int((await cursor.fetchone())["total"])
            should_close = remaining == 0 or (
                not bool(patrol["continue_until_empty"])
                and remaining < int(patrol["minimum_members"])
            )
            if should_close:
                await self._finish_patrol_in_tx(
                    connection,
                    patrol,
                    now,
                    "CALL_EMPTY" if remaining == 0 else "BELOW_MINIMUM",
                    None,
                )
                commander = None
            else:
                commander = await self._select_patrol_commander_in_tx(
                    connection,
                    guild_id,
                    int(patrol["id"]),
                    config,
                    None,
                    reason=(
                        "COMMANDER_LEFT_PATROL"
                        if patrol["commander_member_id"] == patrol["leaving_member_id"]
                        else "PATROL_MEMBER_LEFT"
                    ),
                )
            return {
                "patrol_id": int(patrol["id"]),
                "remaining": remaining,
                "closed": should_close,
                "commander": commander,
            }

    async def _finish_patrol_in_tx(
        self,
        connection: aiosqlite.Connection,
        patrol,
        now: int,
        reason: str,
        actor_id: int | None,
    ) -> None:
        cursor = await connection.execute(
            """
            UPDATE patrols SET status='CLOSED', ended_at=?, end_reason=?, updated_at=?
            WHERE id=? AND status='ACTIVE'
            """,
            (now, reason, now, patrol["id"]),
        )
        if cursor.rowcount != 1:
            raise ConflictError("A patrulha já foi encerrada.")
        await connection.execute(
            """
            UPDATE patrol_members SET status='LEFT', left_at=COALESCE(left_at, ?)
            WHERE patrol_id=? AND status='ACTIVE'
            """,
            (now, patrol["id"]),
        )
        await connection.execute(
            """
            UPDATE patrol_commander_history SET ended_at=?
            WHERE patrol_id=? AND ended_at IS NULL
            """,
            (now, patrol["id"]),
        )
        await connection.execute(
            """
            UPDATE patrol_operational_flags
            SET status='RESOLVED', resolved_at=?, resolution='PATROL_FINISHED'
            WHERE patrol_id=? AND status='OPEN'
            """,
            (now, patrol["id"]),
        )
        await self.audit.record(
            int(patrol["guild_id"]),
            "PATROL_AUTO_FINISHED" if actor_id is None else "PATROL_FINISHED_BY_ADMIN",
            actor_id=actor_id,
            after={"patrol_id": int(patrol["id"]), "reason": reason},
            connection=connection,
        )
        await self._event(
            connection,
            int(patrol["guild_id"]),
            "PATROL_FINISHED",
            "PATROL",
            int(patrol["id"]),
            f"patrol:finished:{patrol['id']}",
            {"reason": reason, "ended_at": now},
        )

    async def finish_patrol(
        self, guild_id: int, patrol_id: int, actor_id: int, reason: str
    ) -> None:
        reason = reason.strip()
        if not reason:
            raise ValidationError("Informe o motivo do encerramento.")
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM patrols WHERE guild_id=? AND id=? AND status='ACTIVE'",
                (guild_id, patrol_id),
            )
            patrol = await cursor.fetchone()
            if not patrol:
                raise NotFoundError("Patrulha ativa não encontrada.")
            await self._finish_patrol_in_tx(connection, patrol, self.clock(), reason, actor_id)

    async def patrol_history(
        self, guild_id: int, discord_id: int, *, limit: int = 10, offset: int = 0
    ):
        return await self.database.fetchall(
            """
            SELECT p.*, pm.member_role, pm.associated_shift_id,
                MAX(0, COALESCE(p.ended_at, ?) - COALESCE(p.started_at, p.reserved_at)) AS duration_ms,
                s.validation_status AS shift_validation_status,
                (
                    SELECT h.discord_id FROM patrol_commander_history h
                    WHERE h.patrol_id=p.id ORDER BY h.started_at DESC, h.id DESC LIMIT 1
                ) AS final_commander_discord_id
            FROM patrol_members pm JOIN patrols p ON p.id=pm.patrol_id
            LEFT JOIN shifts s ON s.id=pm.associated_shift_id
            WHERE pm.guild_id=? AND pm.discord_id=? AND p.status IN ('ACTIVE','CLOSED')
            ORDER BY p.id DESC LIMIT ? OFFSET ?
            """,
            (self.clock(), guild_id, discord_id, limit, offset),
        )

    async def patrol_statistics(self, guild_id: int, discord_id: int) -> dict[str, object]:
        rows = await self.patrol_history(guild_id, discord_id, limit=10_000)
        durations = [int(row["duration_ms"]) for row in rows]
        return {
            "total": len(rows),
            "total_ms": sum(durations),
            "average_ms": sum(durations) // len(durations) if durations else 0,
            "longest_ms": max(durations, default=0),
            "valid_shifts": sum(row["shift_validation_status"] == "VALID" for row in rows),
            "invalid_shifts": sum(row["shift_validation_status"] == "INVALIDATED" for row in rows),
            "last_patrol": rows[0] if rows else None,
        }

    async def add_patrol_feedback(
        self,
        guild_id: int,
        patrol_id: int,
        subject_discord_id: int,
        author_id: int,
        rating: str,
        observation: str | None,
    ) -> int:
        rating = rating.upper()
        if rating not in {"POSITIVE", "NEUTRAL", "NEEDS_ATTENTION"}:
            raise ValidationError("Avaliação de patrulha inválida.")
        note = (observation or "").strip() or None
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT p.id, p.status, subject.member_id AS subject_member_id,
                       author.member_id AS author_member_id,
                       (
                           SELECT h.discord_id FROM patrol_commander_history h
                           WHERE h.patrol_id=p.id
                           ORDER BY h.started_at DESC, h.id DESC LIMIT 1
                       ) AS final_commander_discord_id
                FROM patrols p
                JOIN patrol_members subject ON subject.patrol_id=p.id
                    AND subject.discord_id=?
                JOIN patrol_members author ON author.patrol_id=p.id
                    AND author.discord_id=?
                WHERE p.guild_id=? AND p.id=? AND p.status='CLOSED'
                """,
                (subject_discord_id, author_id, guild_id, patrol_id),
            )
            row = await cursor.fetchone()
            if not row:
                raise ValidationError(
                    "O feedback só pode ser registrado por integrante após o encerramento."
                )
            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO patrol_feedback(
                        guild_id, patrol_id, subject_member_id, subject_discord_id,
                        author_id, rating, observation, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        patrol_id,
                        row["subject_member_id"],
                        subject_discord_id,
                        author_id,
                        rating,
                        note,
                        now,
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("Este feedback já foi registrado.") from exc
            feedback_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "PATROL_FEEDBACK_CREATED",
                actor_id=author_id,
                target_id=subject_discord_id,
                after={
                    "patrol_id": patrol_id,
                    "rating": rating,
                    "final_commander_discord_id": row["final_commander_discord_id"],
                    "feedback_about_final_commander": (
                        row["final_commander_discord_id"] == subject_discord_id
                    ),
                },
                connection=connection,
            )
        return feedback_id

    async def patrol_feedback_for_member(self, guild_id: int, discord_id: int, *, limit: int = 10):
        return await self.database.fetchall(
            """
            SELECT f.*, p.sequence_number FROM patrol_feedback f
            JOIN patrols p ON p.id=f.patrol_id
            WHERE f.guild_id=? AND f.subject_discord_id=?
            ORDER BY f.created_at DESC, f.id DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )

    async def readiness(self, guild_id: int) -> dict[str, object]:
        members = await self.database.fetchall(
            "SELECT discord_id, mta_nick, status FROM members WHERE guild_id=? AND status!='DISMISSED'",
            (guild_id,),
        )
        details: dict[str, list[dict[str, object]]] = {
            "ON_PATROL": [],
            "QUEUED": [],
            "AVAILABLE_FOR_PATROL": [],
            "IN_TRAINING": [],
            "AWAY": [],
            "SUSPENDED": [],
            "UNAVAILABLE": [],
        }
        queued = {
            int(row["discord_id"])
            for row in await self.database.fetchall(
                """
                SELECT discord_id FROM patrol_queue_entries
                WHERE guild_id=? AND status IN ('QUEUED','FORMING')
                """,
                (guild_id,),
            )
        }
        for member in members:
            discord_id = int(member["discord_id"])
            if member["status"] == "SUSPENDED":
                effective = "SUSPENDED"
            elif discord_id in queued:
                effective = "QUEUED"
            else:
                effective = await self.effective_operational_status(guild_id, discord_id)
            details.setdefault(effective, []).append(dict(member))
        return {
            "counts": {key: len(value) for key, value in details.items()},
            "details": details,
        }

    async def scan_shift_flags(self, guild_id: int) -> list[int]:
        now = self.clock()
        window_start = now - 7 * DAY_MS
        invalid_threshold = int(
            await self.settings.get(guild_id, "invalid_shift_flag_threshold", 3)
        )
        disconnect_threshold = int(
            await self.settings.get(guild_id, "voice_disconnect_flag_threshold", 6)
        )
        adjustment_threshold = int(
            await self.settings.get(guild_id, "manual_adjustment_flag_threshold", 3)
        )
        rows = await self.database.fetchall(
            """
            SELECT m.id AS member_id, m.discord_id,
                COUNT(DISTINCT CASE WHEN s.validation_status='INVALIDATED' THEN s.id END)
                    AS invalid_count,
                COUNT(DISTINCT CASE WHEN s.validation_status='INVALIDATED'
                    AND s.patrol_duration_ms < s.minimum_patrol_ms / 2 THEN s.id END)
                    AS very_short_count,
                COUNT(DISTINCT CASE WHEN ve.event_type IN ('LEFT_AUTHORIZED','ENTERED_GRACE')
                    THEN ve.id END) AS disconnect_count,
                COUNT(DISTINCT sa.id) AS adjustment_count,
                COUNT(DISTINCT CASE WHEN s.validation_status='VALID'
                    AND s.gross_duration_ms > s.patrol_duration_ms * 2
                    AND s.gross_duration_ms - s.patrol_duration_ms >= 1800000 THEN s.id END)
                    AS unusual_count
            FROM members m
            LEFT JOIN shifts s ON s.member_id=m.id AND s.started_at>=?
            LEFT JOIN voice_events ve ON ve.member_id=m.id AND ve.occurred_at>=?
            LEFT JOIN shift_adjustments sa ON sa.shift_id=s.id AND sa.created_at>=?
            WHERE m.guild_id=? AND m.status!='DISMISSED'
            GROUP BY m.id
            """,
            (window_start, window_start, window_start, guild_id),
        )
        created: list[int] = []
        async with self.database.transaction() as connection:
            for row in rows:
                candidates: list[tuple[str, int, int, str]] = [
                    (
                        "MANY_INVALID_SHIFTS",
                        int(row["invalid_count"]),
                        invalid_threshold,
                        "sessões invalidadas nos últimos 7 dias",
                    ),
                    (
                        "SHORT_SHIFT_PATTERN",
                        int(row["very_short_count"]),
                        invalid_threshold,
                        "sessões muito abaixo do mínimo nos últimos 7 dias",
                    ),
                    (
                        "FREQUENT_VOICE_DISCONNECTS",
                        int(row["disconnect_count"]),
                        disconnect_threshold,
                        "desconexões/saídas de call nos últimos 7 dias",
                    ),
                    (
                        "MANUAL_ADJUSTMENT_FREQUENCY",
                        int(row["adjustment_count"]),
                        adjustment_threshold,
                        "ajustes manuais nos últimos 7 dias",
                    ),
                    (
                        "UNUSUAL_SESSION_PATTERN",
                        int(row["unusual_count"]),
                        2,
                        "sessões com grande divergência entre tempo bruto e patrulha",
                    ),
                ]
                for flag_type, count, threshold, label in candidates:
                    if count < threshold:
                        continue
                    fingerprint = f"{flag_type}:{row['member_id']}:{window_start // DAY_MS}"
                    evidence = {"count": count, "threshold": threshold, "window_days": 7}
                    cursor = await connection.execute(
                        """
                        INSERT OR IGNORE INTO operational_flags(
                            guild_id, member_id, discord_id, flag_type, evidence_json,
                            reason, fingerprint, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            guild_id,
                            row["member_id"],
                            row["discord_id"],
                            flag_type,
                            json.dumps(evidence, sort_keys=True),
                            f"{count} {label}.",
                            fingerprint,
                            now,
                        ),
                    )
                    if cursor.rowcount == 1:
                        flag_id = int(cursor.lastrowid)
                        created.append(flag_id)
                        await self.audit.record(
                            guild_id,
                            "SHIFT_FLAGGED",
                            target_id=int(row["discord_id"]),
                            after={
                                "flag_id": flag_id,
                                "flag_type": flag_type,
                                "evidence": evidence,
                            },
                            connection=connection,
                        )
        return created

    async def operational_flags(self, guild_id: int, *, status: str = "OPEN"):
        return await self.database.fetchall(
            """
            SELECT f.*, m.mta_nick FROM operational_flags f
            JOIN members m ON m.id=f.member_id
            WHERE f.guild_id=? AND f.status=? ORDER BY f.created_at DESC, f.id DESC
            LIMIT 100
            """,
            (guild_id, status.upper()),
        )

    async def review_operational_flag(
        self,
        guild_id: int,
        flag_id: int,
        actor_id: int,
        decision: str,
        reason: str,
    ) -> None:
        decision = decision.upper()
        if decision not in {"RESOLVED", "DISMISSED"}:
            raise ValidationError("Decisão de flag inválida.")
        reason = reason.strip()
        if not reason:
            raise ValidationError("Informe a justificativa da decisão.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM operational_flags WHERE guild_id=? AND id=? AND status='OPEN'",
                (guild_id, flag_id),
            )
            flag = await cursor.fetchone()
            if not flag:
                raise NotFoundError("Sinalização aberta não encontrada.")
            cursor = await connection.execute(
                """
                UPDATE operational_flags
                SET status=?, reviewed_by=?, reviewed_at=?, review_reason=?
                WHERE guild_id=? AND id=? AND status='OPEN'
                """,
                (decision, actor_id, now, reason, guild_id, flag_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A sinalização já foi analisada.")
            await self.audit.record(
                guild_id,
                "OPERATIONAL_FLAG_REVIEWED",
                actor_id=actor_id,
                target_id=flag["discord_id"],
                before={"status": "OPEN", "flag_type": flag["flag_type"]},
                after={"status": decision, "flag_id": flag_id},
                reason=reason,
                connection=connection,
            )

    async def scan_integrity(
        self,
        guild_id: int,
        discord_members: Iterable[dict[str, object]],
        *,
        member_role_id: int | None,
    ) -> list[int]:
        """Compare a read-only Discord snapshot with persisted membership state."""
        now = self.clock()
        discord_snapshot = {
            int(item["discord_id"]): {
                "role_ids": {int(role_id) for role_id in item.get("role_ids", [])},
                "display_name": str(item.get("display_name") or ""),
            }
            for item in discord_members
        }
        rank_roles = {
            int(row["discord_role_id"]): int(row["id"])
            for row in await self.database.fetchall(
                """
                SELECT id, discord_role_id FROM ranks
                WHERE guild_id=? AND active=1 AND discord_role_id IS NOT NULL
                """,
                (guild_id,),
            )
        }
        members = await self.database.fetchall(
            """
            SELECT m.*, r.discord_role_id AS expected_rank_role_id
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=?
            """,
            (guild_id,),
        )
        findings: list[tuple[int | None, int | None, str, str, dict[str, object], str]] = []
        known_ids = {int(row["discord_id"]) for row in members}
        for member in members:
            discord_id = int(member["discord_id"])
            snapshot = discord_snapshot.get(discord_id)
            if snapshot is None:
                if member["status"] not in {"DISMISSED", "PENDING"}:
                    findings.append(
                        (
                            int(member["id"]),
                            discord_id,
                            "MEMBER_NOT_IN_GUILD",
                            "REQUIRES_REVIEW",
                            {"member_status": member["status"]},
                            f"member-not-guild:{member['id']}:{member['status']}",
                        )
                    )
                continue
            role_ids = snapshot["role_ids"]
            assert isinstance(role_ids, set)
            expected_rank = member["expected_rank_role_id"]
            actual_rank_roles = sorted(role_ids.intersection(rank_roles))
            if member["status"] == "ACTIVE":
                if member_role_id and member_role_id not in role_ids:
                    findings.append(
                        (
                            int(member["id"]),
                            discord_id,
                            "MISSING_MEMBER_ROLE",
                            "AUTO_FIX_SAFE",
                            {"expected_role_id": member_role_id},
                            f"missing-member-role:{member['id']}:{member_role_id}",
                        )
                    )
                if expected_rank and int(expected_rank) not in role_ids:
                    findings.append(
                        (
                            int(member["id"]),
                            discord_id,
                            "MISSING_RANK_ROLE",
                            "AUTO_FIX_SAFE",
                            {"expected_role_id": int(expected_rank)},
                            f"missing-rank-role:{member['id']}:{expected_rank}",
                        )
                    )
                unexpected = [role for role in actual_rank_roles if role != expected_rank]
                if unexpected:
                    findings.append(
                        (
                            int(member["id"]),
                            discord_id,
                            "MULTIPLE_OR_WRONG_RANK_ROLES",
                            "REQUIRES_REVIEW",
                            {
                                "expected_role_id": expected_rank,
                                "actual_role_ids": actual_rank_roles,
                            },
                            f"wrong-ranks:{member['id']}:{','.join(map(str, actual_rank_roles))}",
                        )
                    )
            elif member_role_id and member_role_id in role_ids:
                findings.append(
                    (
                        int(member["id"]),
                        discord_id,
                        "INACTIVE_WITH_MEMBER_ROLE",
                        "REQUIRES_REVIEW",
                        {"member_status": member["status"]},
                        f"inactive-member-role:{member['id']}:{member['status']}",
                    )
                )
        privileged_roles = set(rank_roles)
        if member_role_id:
            privileged_roles.add(member_role_id)
        for discord_id, snapshot in discord_snapshot.items():
            role_ids = snapshot["role_ids"]
            assert isinstance(role_ids, set)
            if discord_id not in known_ids and role_ids.intersection(privileged_roles):
                findings.append(
                    (
                        None,
                        discord_id,
                        "DISCORD_MEMBER_WITHOUT_RECORD",
                        "REQUIRES_REVIEW",
                        {"role_ids": sorted(role_ids.intersection(privileged_roles))},
                        f"discord-no-record:{discord_id}",
                    )
                )
        created: list[int] = []
        async with self.database.transaction() as connection:
            for member_id, discord_id, finding_type, fix_class, evidence, fingerprint in findings:
                cursor = await connection.execute(
                    """
                    INSERT OR IGNORE INTO integrity_findings(
                        guild_id, member_id, discord_id, finding_type, fix_class,
                        evidence_json, fingerprint, detected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        member_id,
                        discord_id,
                        finding_type,
                        fix_class,
                        json.dumps(evidence, sort_keys=True),
                        fingerprint,
                        now,
                    ),
                )
                if cursor.rowcount == 1:
                    created.append(int(cursor.lastrowid))
            if created:
                await self.audit.record(
                    guild_id,
                    "INTEGRITY_SCAN_COMPLETED",
                    after={"created_findings": len(created)},
                    connection=connection,
                )
                await self._event(
                    connection,
                    guild_id,
                    "INTEGRITY_FINDINGS_CREATED",
                    "GUILD",
                    guild_id,
                    f"integrity-scan:{now}",
                    {"created_findings": len(created)},
                )
        return created

    async def integrity_findings(self, guild_id: int, *, status: str = "OPEN"):
        return await self.database.fetchall(
            """
            SELECT f.*, m.mta_nick FROM integrity_findings f
            LEFT JOIN members m ON m.id=f.member_id
            WHERE f.guild_id=? AND f.status=?
            ORDER BY CASE f.fix_class WHEN 'REQUIRES_REVIEW' THEN 0 ELSE 1 END,
                     f.detected_at DESC, f.id DESC
            LIMIT 200
            """,
            (guild_id, status.upper()),
        )

    async def resolve_integrity_finding(
        self,
        guild_id: int,
        finding_id: int,
        actor_id: int,
        resolution: str,
        *,
        dismissed: bool = False,
    ) -> None:
        resolution = resolution.strip()
        if not resolution:
            raise ValidationError("Informe como o achado foi tratado.")
        now = self.clock()
        status = "DISMISSED" if dismissed else "RESOLVED"
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM integrity_findings WHERE guild_id=? AND id=? AND status='OPEN'",
                (guild_id, finding_id),
            )
            finding = await cursor.fetchone()
            if not finding:
                raise NotFoundError("Achado aberto não encontrado.")
            cursor = await connection.execute(
                """
                UPDATE integrity_findings
                SET status=?, resolved_by=?, resolved_at=?, resolution=?
                WHERE guild_id=? AND id=? AND status='OPEN'
                """,
                (status, actor_id, now, resolution, guild_id, finding_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("O achado já foi tratado.")
            await self.audit.record(
                guild_id,
                "INTEGRITY_FINDING_RESOLVED",
                actor_id=actor_id,
                target_id=finding["discord_id"],
                before={"status": "OPEN", "finding_type": finding["finding_type"]},
                after={"status": status, "finding_id": finding_id},
                reason=resolution,
                connection=connection,
            )

    async def _valid_hours_ms(self, guild_id: int, member_id: int) -> int:
        row = await self.database.fetchone(
            """
            SELECT COALESCE(SUM(
                s.patrol_duration_ms + COALESCE((
                    SELECT SUM(sa.delta_ms) FROM shift_adjustments sa WHERE sa.shift_id=s.id
                ), 0)
            ), 0) AS total_ms
            FROM shifts s
            WHERE s.guild_id=? AND s.member_id=? AND s.status='CLOSED'
              AND s.validation_status='VALID'
            """,
            (guild_id, member_id),
        )
        return max(0, int(row["total_ms"] if row else 0))

    async def qualification_matrix(
        self, guild_id: int, *, discord_ids: Iterable[int] | None = None
    ) -> dict[str, object]:
        params: list[object] = [guild_id]
        filter_sql = ""
        selected_ids = sorted({int(value) for value in (discord_ids or [])})
        if selected_ids:
            filter_sql = f" AND m.discord_id IN ({','.join('?' for _ in selected_ids)})"
            params.extend(selected_ids)
        members = await self.database.fetchall(
            f"""
            SELECT m.id, m.discord_id, m.mta_nick, m.status, r.name AS rank_name
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.status!='DISMISSED' {filter_sql}
            ORDER BY COALESCE(r.level, -1) DESC, m.mta_nick
            """,
            tuple(params),
        )
        courses = await self.database.fetchall(
            """
            SELECT internal_code, name FROM course_catalog
            WHERE guild_id=? AND active=1 ORDER BY internal_code
            """,
            (guild_id,),
        )
        qualifications = await self.database.fetchall(
            """
            SELECT member_id, course_name, result, recorded_at
            FROM member_qualifications WHERE guild_id=?
            ORDER BY recorded_at DESC, id DESC
            """,
            (guild_id,),
        )
        by_member: dict[int, dict[str, dict[str, object]]] = {}
        for row in qualifications:
            entries = by_member.setdefault(int(row["member_id"]), {})
            entries.setdefault(str(row["course_name"]).casefold(), dict(row))
        matrix = []
        for member in members:
            approved = by_member.get(int(member["id"]), {})
            matrix.append(
                {
                    "member": dict(member),
                    "courses": {
                        str(course["internal_code"]): approved.get(str(course["name"]).casefold())
                        for course in courses
                    },
                }
            )
        return {"courses": [dict(row) for row in courses], "members": matrix}

    async def course_requirement_status(
        self, guild_id: int, course_id: int, discord_id: int
    ) -> dict[str, object]:
        course = await self.database.fetchone(
            "SELECT * FROM course_catalog WHERE guild_id=? AND id=? AND active=1",
            (guild_id, course_id),
        )
        if not course:
            raise NotFoundError("Curso ativo não encontrado.")
        member = await self.database.fetchone(
            """
            SELECT m.*, COALESCE(r.level, -1) AS rank_level, r.name AS rank_name
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        if not member:
            raise NotFoundError("Membro não cadastrado.")
        now = self.clock()
        total_ms = await self._valid_hours_ms(guild_id, int(member["id"]))
        tenure_days = max(0, (now - int(member["joined_at"])) // DAY_MS)
        suspension = await self.database.fetchone(
            """
            SELECT 1 FROM punishments WHERE guild_id=? AND member_id=?
              AND punishment_type='SUSPENSION' AND status IN ('SCHEDULED','ACTIVE')
              AND starts_at<=? AND (ends_at IS NULL OR ends_at>?) LIMIT 1
            """,
            (guild_id, member["id"], now, now),
        )
        prereq_ok = True
        prereq = course["prerequisite_course_name"]
        if prereq:
            prereq_ok = bool(
                await self.database.fetchone(
                    """
                    SELECT 1 FROM member_qualifications
                    WHERE guild_id=? AND member_id=? AND lower(course_name)=lower(?)
                      AND result='APPROVED' LIMIT 1
                    """,
                    (guild_id, member["id"], prereq),
                )
            )
        checks = {
            "active_member": member["status"] == "ACTIVE",
            "minimum_rank": course["minimum_rank_level"] is None
            or int(member["rank_level"]) >= int(course["minimum_rank_level"]),
            "minimum_hours": total_ms >= int(course["minimum_valid_hours_ms"]),
            "minimum_tenure": tenure_days >= int(course["minimum_tenure_days"]),
            "no_active_suspension": not bool(course["require_no_active_suspension"])
            or suspension is None,
            "prerequisite_course": prereq_ok,
        }
        return {
            "eligible": all(checks.values()),
            "checks": checks,
            "course": dict(course),
            "member": dict(member),
            "valid_hours_ms": total_ms,
            "tenure_days": tenure_days,
        }

    async def configure_course_requirements(
        self,
        guild_id: int,
        course_id: int,
        actor_id: int,
        *,
        minimum_rank_level: int | None,
        minimum_valid_hours: int,
        minimum_tenure_days: int,
        require_no_active_suspension: bool,
        prerequisite_course_name: str | None,
    ) -> None:
        if minimum_valid_hours < 0 or minimum_tenure_days < 0:
            raise ValidationError("Horas e tempo de corporação não podem ser negativos.")
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM course_catalog WHERE guild_id=? AND id=?",
                (guild_id, course_id),
            )
            course = await cursor.fetchone()
            if not course:
                raise NotFoundError("Curso não encontrado.")
            await connection.execute(
                """
                UPDATE course_catalog SET minimum_rank_level=?, minimum_valid_hours_ms=?,
                    minimum_tenure_days=?, require_no_active_suspension=?,
                    prerequisite_course_name=?, updated_at=?
                WHERE guild_id=? AND id=?
                """,
                (
                    minimum_rank_level,
                    minimum_valid_hours * HOUR_MS,
                    minimum_tenure_days,
                    int(require_no_active_suspension),
                    (prerequisite_course_name or "").strip() or None,
                    self.clock(),
                    guild_id,
                    course_id,
                ),
            )
            await self.audit.record(
                guild_id,
                "COURSE_REQUIREMENTS_UPDATED",
                actor_id=actor_id,
                target_id=course_id,
                before={
                    "minimum_rank_level": course["minimum_rank_level"],
                    "minimum_valid_hours_ms": course["minimum_valid_hours_ms"],
                    "minimum_tenure_days": course["minimum_tenure_days"],
                    "prerequisite_course_name": course["prerequisite_course_name"],
                },
                after={
                    "minimum_rank_level": minimum_rank_level,
                    "minimum_valid_hours": minimum_valid_hours,
                    "minimum_tenure_days": minimum_tenure_days,
                    "require_no_active_suspension": require_no_active_suspension,
                    "prerequisite_course_name": prerequisite_course_name,
                },
                connection=connection,
            )

    async def record_training_evaluation(
        self,
        guild_id: int,
        training_id: int,
        enrollment_id: int,
        evaluator_id: int,
        attendance: str,
        result: str,
        performance: str,
        observation: str | None,
    ) -> int:
        attendance, result, performance = (attendance.upper(), result.upper(), performance.upper())
        if attendance not in {"PRESENT", "ABSENT"}:
            raise ValidationError("Presença inválida.")
        if result not in {"APPROVED", "FAILED"}:
            raise ValidationError("Resultado inválido.")
        if performance not in {"EXCELLENT", "GOOD", "REGULAR", "INSUFFICIENT"}:
            raise ValidationError("Desempenho inválido.")
        if attendance == "ABSENT" and result == "APPROVED":
            raise ValidationError("Um ausente não pode ser aprovado.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT e.*, t.course_name FROM training_enrollments e
                JOIN training_events t ON t.id=e.training_id
                WHERE e.guild_id=? AND e.training_id=? AND e.id=?
                  AND e.enrollment_status='ENROLLED'
                """,
                (guild_id, training_id, enrollment_id),
            )
            enrollment = await cursor.fetchone()
            if not enrollment:
                raise NotFoundError("Inscrição ativa não encontrada.")
            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO training_evaluations(
                        guild_id, training_id, enrollment_id, member_id, discord_id,
                        attendance, result, performance, observation, evaluator_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        training_id,
                        enrollment_id,
                        enrollment["member_id"],
                        enrollment["discord_id"],
                        attendance,
                        result,
                        performance,
                        (observation or "").strip() or None,
                        evaluator_id,
                        now,
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("Este participante já foi avaliado.") from exc
            evaluation_id = int(cursor.lastrowid)
            await connection.execute(
                """
                UPDATE training_enrollments SET attendance_status=?, result_status=?,
                    decided_by=?, decided_at=?, decision_notes=? WHERE id=?
                """,
                (
                    attendance,
                    result,
                    evaluator_id,
                    now,
                    (observation or "").strip() or None,
                    enrollment_id,
                ),
            )
            if enrollment["course_name"]:
                await connection.execute(
                    """
                    INSERT INTO member_qualifications(
                        guild_id, member_id, discord_id, training_id, course_name,
                        result, responsible_id, recorded_at, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(training_id, member_id) DO UPDATE SET
                        result=excluded.result, responsible_id=excluded.responsible_id,
                        recorded_at=excluded.recorded_at, notes=excluded.notes
                    """,
                    (
                        guild_id,
                        enrollment["member_id"],
                        enrollment["discord_id"],
                        training_id,
                        enrollment["course_name"],
                        result,
                        evaluator_id,
                        now,
                        (observation or "").strip() or None,
                    ),
                )
            await self.audit.record(
                guild_id,
                "TRAINING_EVALUATION_RECORDED",
                actor_id=evaluator_id,
                target_id=enrollment["discord_id"],
                after={
                    "training_id": training_id,
                    "attendance": attendance,
                    "result": result,
                    "performance": performance,
                },
                connection=connection,
            )
        return evaluation_id

    async def recruit_profile(self, guild_id: int, discord_id: int) -> dict[str, object]:
        member = await self.database.fetchone(
            """
            SELECT m.*, r.name AS rank_name, r.level AS rank_level
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        if not member:
            raise NotFoundError("Membro não cadastrado.")
        now = self.clock()
        valid_hours_ms = await self._valid_hours_ms(guild_id, int(member["id"]))
        patrol_row = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM patrol_members pm JOIN patrols p ON p.id=pm.patrol_id
            WHERE pm.guild_id=? AND pm.member_id=? AND p.status='CLOSED'
            """,
            (guild_id, member["id"]),
        )
        evaluation_row = await self.database.fetchone(
            "SELECT COUNT(*) AS total FROM recruit_evaluations WHERE guild_id=? AND member_id=?",
            (guild_id, member["id"]),
        )
        required_courses = [
            str(value)
            for value in await self.settings.get(guild_id, "recruit_required_courses", [])
        ]
        qualifications = await self.database.fetchall(
            """
            SELECT course_name, result, recorded_at FROM member_qualifications
            WHERE guild_id=? AND member_id=? ORDER BY recorded_at DESC
            """,
            (guild_id, member["id"]),
        )
        approved = {
            str(row["course_name"]).casefold()
            for row in qualifications
            if row["result"] == "APPROVED"
        }
        missing_courses = [
            course for course in required_courses if course.casefold() not in approved
        ]
        requirements = {
            "minimum_days": max(0, (now - int(member["joined_at"])) // DAY_MS)
            >= int(await self.settings.get(guild_id, "recruit_min_days", 7)),
            "minimum_hours": valid_hours_ms
            >= int(await self.settings.get(guild_id, "recruit_min_valid_hours", 10)) * HOUR_MS,
            "minimum_patrols": int(patrol_row["total"] if patrol_row else 0)
            >= int(await self.settings.get(guild_id, "recruit_min_patrols", 3)),
            "minimum_evaluations": int(evaluation_row["total"] if evaluation_row else 0)
            >= int(await self.settings.get(guild_id, "recruit_min_evaluations", 2)),
            "required_courses": not missing_courses,
            "active_status": member["status"] == "ACTIVE",
        }
        return {
            "member": dict(member),
            "days_in_corporation": max(0, (now - int(member["joined_at"])) // DAY_MS),
            "valid_hours_ms": valid_hours_ms,
            "patrols": int(patrol_row["total"] if patrol_row else 0),
            "evaluations": int(evaluation_row["total"] if evaluation_row else 0),
            "qualifications": [dict(row) for row in qualifications],
            "missing_courses": missing_courses,
            "requirements": requirements,
            "eligible_for_effective_review": all(requirements.values()),
        }

    async def recruits(self, guild_id: int) -> list[dict[str, object]]:
        configured = {
            str(value).casefold()
            for value in await self.settings.get(guild_id, "recruit_rank_names", ["RECRUTA"])
        }
        rows = await self.database.fetchall(
            """
            SELECT m.discord_id, r.name AS rank_name FROM members m
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.status!='DISMISSED'
            ORDER BY m.joined_at
            """,
            (guild_id,),
        )
        result: list[dict[str, object]] = []
        for row in rows:
            if str(row["rank_name"] or "").casefold() in configured:
                result.append(await self.recruit_profile(guild_id, int(row["discord_id"])))
        return result

    async def add_recruit_evaluation(
        self,
        guild_id: int,
        discord_id: int,
        evaluator_id: int,
        outcome: str,
        observation: str,
    ) -> int:
        outcome = outcome.upper()
        if outcome not in {"POSITIVE", "NEUTRAL", "NEEDS_ATTENTION"}:
            raise ValidationError("Resultado de acompanhamento inválido.")
        observation = observation.strip()
        if not observation:
            raise ValidationError("Informe a observação da avaliação.")
        async with self.database.transaction() as connection:
            member = await self._member_in_tx(connection, guild_id, discord_id)
            cursor = await connection.execute(
                """
                INSERT INTO recruit_evaluations(
                    guild_id, member_id, discord_id, evaluator_id,
                    outcome, observation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    member["id"],
                    discord_id,
                    evaluator_id,
                    outcome,
                    observation,
                    self.clock(),
                ),
            )
            evaluation_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "RECRUIT_EVALUATION_CREATED",
                actor_id=evaluator_id,
                target_id=discord_id,
                after={"evaluation_id": evaluation_id, "outcome": outcome},
                reason=observation,
                connection=connection,
            )
        return evaluation_id

    async def promotion_eligibility(self, guild_id: int, discord_id: int) -> dict[str, object]:
        member = await self.database.fetchone(
            """
            SELECT m.*, r.name AS rank_name, r.level AS rank_level
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        if not member:
            raise NotFoundError("Membro não cadastrado.")
        next_rank = await self.database.fetchone(
            """
            SELECT * FROM ranks WHERE guild_id=? AND active=1 AND level>?
            ORDER BY level ASC LIMIT 1
            """,
            (guild_id, int(member["rank_level"] or -1)),
        )
        rank_change = await self.database.fetchone(
            """
            SELECT created_at FROM personnel_actions
            WHERE guild_id=? AND member_id=? AND to_rank_id=?
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (guild_id, member["id"], member["rank_id"]),
        )
        rank_since = int(rank_change["created_at"]) if rank_change else int(member["joined_at"])
        rank_days = max(0, (self.clock() - rank_since) // DAY_MS)
        hours_ms = await self._valid_hours_ms(guild_id, int(member["id"]))
        required_courses = [
            str(value)
            for value in await self.settings.get(guild_id, "promotion_required_courses", [])
        ]
        qualifications = await self.database.fetchall(
            """
            SELECT course_name, result FROM member_qualifications
            WHERE guild_id=? AND member_id=?
            """,
            (guild_id, member["id"]),
        )
        approved = {
            str(row["course_name"]).casefold()
            for row in qualifications
            if row["result"] == "APPROVED"
        }
        missing_courses = [
            course for course in required_courses if course.casefold() not in approved
        ]
        active_punishment = await self.database.fetchone(
            """
            SELECT 1 FROM punishments WHERE guild_id=? AND member_id=?
              AND status IN ('SCHEDULED','ACTIVE') LIMIT 1
            """,
            (guild_id, member["id"]),
        )
        checks = {
            "next_rank_available": next_rank is not None,
            "active_status": member["status"] == "ACTIVE",
            "minimum_rank_days": rank_days
            >= int(await self.settings.get(guild_id, "promotion_min_rank_days", 30)),
            "minimum_valid_hours": hours_ms
            >= int(await self.settings.get(guild_id, "promotion_min_valid_hours", 30)) * HOUR_MS,
            "required_courses": not missing_courses,
            "no_active_punishment": active_punishment is None,
        }
        return {
            "member": dict(member),
            "next_rank": dict(next_rank) if next_rank else None,
            "rank_days": rank_days,
            "valid_hours_ms": hours_ms,
            "missing_courses": missing_courses,
            "checks": checks,
            "eligible_for_human_review": all(checks.values()),
            "automatic_promotion": False,
        }

    async def dossier(self, guild_id: int, discord_id: int) -> dict[str, object]:
        member = await self.database.fetchone(
            """
            SELECT m.*, r.name AS rank_name, r.level AS rank_level
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        if not member:
            raise NotFoundError("Membro não cadastrado.")
        member_id = int(member["id"])
        queries = {
            "personnel_actions": (
                "SELECT * FROM personnel_actions WHERE guild_id=? AND member_id=? ORDER BY id DESC LIMIT 10",
                (guild_id, member_id),
            ),
            "punishments": (
                "SELECT * FROM punishments WHERE guild_id=? AND member_id=? ORDER BY id DESC LIMIT 10",
                (guild_id, member_id),
            ),
            "absences": (
                "SELECT * FROM absence_requests WHERE guild_id=? AND member_id=? ORDER BY id DESC LIMIT 10",
                (guild_id, member_id),
            ),
            "qualifications": (
                "SELECT * FROM member_qualifications WHERE guild_id=? AND member_id=? ORDER BY id DESC LIMIT 20",
                (guild_id, member_id),
            ),
            "training_evaluations": (
                "SELECT * FROM training_evaluations WHERE guild_id=? AND member_id=? ORDER BY id DESC LIMIT 10",
                (guild_id, member_id),
            ),
            "recruit_evaluations": (
                "SELECT * FROM recruit_evaluations WHERE guild_id=? AND member_id=? ORDER BY id DESC LIMIT 10",
                (guild_id, member_id),
            ),
            "flags": (
                "SELECT * FROM operational_flags WHERE guild_id=? AND member_id=? ORDER BY id DESC LIMIT 10",
                (guild_id, member_id),
            ),
        }
        result: dict[str, object] = {
            "member": dict(member),
            "valid_hours_ms": await self._valid_hours_ms(guild_id, member_id),
            "patrol_statistics": await self.patrol_statistics(guild_id, discord_id),
        }
        for key, (sql, params) in queries.items():
            result[key] = [dict(row) for row in await self.database.fetchall(sql, params)]
        return result

    async def create_activity_swap(
        self,
        guild_id: int,
        requester_id: int,
        target_id: int,
        activity_name: str,
        reason: str,
        *,
        requires_command: bool = True,
    ) -> int:
        if requester_id == target_id:
            raise ValidationError("Selecione outro membro para a troca.")
        activity_name, reason = activity_name.strip(), reason.strip()
        if not activity_name or not reason:
            raise ValidationError("Informe a atividade e o motivo da troca.")
        now = self.clock()
        async with self.database.transaction() as connection:
            requester = await self._member_in_tx(connection, guild_id, requester_id)
            target = await self._member_in_tx(connection, guild_id, target_id)
            if requester["status"] != "ACTIVE" or target["status"] != "ACTIVE":
                raise ValidationError("A troca exige dois membros ativos.")
            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO activity_swap_requests(
                        guild_id, requester_member_id, requester_discord_id,
                        target_member_id, target_discord_id, activity_name, reason,
                        requires_command, status, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'WAITING_MEMBER', ?)
                    """,
                    (
                        guild_id,
                        requester["id"],
                        requester_id,
                        target["id"],
                        target_id,
                        activity_name,
                        reason,
                        int(requires_command),
                        now,
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("Já existe uma troca aberta entre estes membros.") from exc
            swap_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "ACTIVITY_SWAP_REQUESTED",
                actor_id=requester_id,
                target_id=target_id,
                after={"swap_id": swap_id, "activity_name": activity_name},
                reason=reason,
                connection=connection,
            )
        return swap_id

    async def respond_activity_swap(
        self,
        guild_id: int,
        swap_id: int,
        actor_id: int,
        accepted: bool,
        reason: str | None = None,
    ) -> str:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM activity_swap_requests
                WHERE guild_id=? AND id=? AND status='WAITING_MEMBER'
                """,
                (guild_id, swap_id),
            )
            swap = await cursor.fetchone()
            if not swap:
                raise NotFoundError("Solicitação aguardando membro não encontrada.")
            if int(swap["target_discord_id"]) != actor_id:
                raise ValidationError("Somente o membro convidado pode responder.")
            status = (
                "WAITING_COMMAND"
                if accepted and bool(swap["requires_command"])
                else "APPROVED"
                if accepted
                else "DENIED"
            )
            await connection.execute(
                """
                UPDATE activity_swap_requests SET status=?, member_decided_at=?,
                    member_decision_reason=? WHERE id=? AND status='WAITING_MEMBER'
                """,
                (status, now, (reason or "").strip() or None, swap_id),
            )
            await self.audit.record(
                guild_id,
                "ACTIVITY_SWAP_MEMBER_RESPONDED",
                actor_id=actor_id,
                target_id=swap["requester_discord_id"],
                before={"status": "WAITING_MEMBER"},
                after={"status": status, "swap_id": swap_id},
                reason=(reason or "").strip() or None,
                connection=connection,
            )
        return status

    async def decide_activity_swap(
        self,
        guild_id: int,
        swap_id: int,
        actor_id: int,
        approved: bool,
        reason: str,
    ) -> str:
        reason = reason.strip()
        if not reason:
            raise ValidationError("Informe a justificativa da decisão.")
        status = "APPROVED" if approved else "DENIED"
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM activity_swap_requests
                WHERE guild_id=? AND id=? AND status='WAITING_COMMAND'
                """,
                (guild_id, swap_id),
            )
            swap = await cursor.fetchone()
            if not swap:
                raise NotFoundError("Troca aguardando o Comando não encontrada.")
            await connection.execute(
                """
                UPDATE activity_swap_requests SET status=?, command_decided_at=?,
                    command_decided_by=?, command_decision_reason=?
                WHERE id=? AND status='WAITING_COMMAND'
                """,
                (status, now, actor_id, reason, swap_id),
            )
            await self.audit.record(
                guild_id,
                "ACTIVITY_SWAP_COMMAND_DECIDED",
                actor_id=actor_id,
                target_id=swap["requester_discord_id"],
                before={"status": "WAITING_COMMAND"},
                after={"status": status, "swap_id": swap_id},
                reason=reason,
                connection=connection,
            )
            await self._event(
                connection,
                guild_id,
                "ACTIVITY_SWAP_DECIDED",
                "ACTIVITY_SWAP",
                swap_id,
                f"activity-swap:decided:{swap_id}",
                {"status": status},
            )
        return status

    async def member_activity_swaps(self, guild_id: int, discord_id: int):
        return await self.database.fetchall(
            """
            SELECT * FROM activity_swap_requests
            WHERE guild_id=? AND (requester_discord_id=? OR target_discord_id=?)
            ORDER BY submitted_at DESC, id DESC LIMIT 25
            """,
            (guild_id, discord_id, discord_id),
        )

    async def administrative_inbox(
        self, guild_id: int, *, item_type: str | None = None, limit: int = 100
    ) -> list[dict[str, object]]:
        sources = (
            (
                "REGISTRATION_GATE",
                "registration_gate_records",
                "status IN ('PENDING','REQUIRES_REVIEW')",
                "updated_at",
            ),
            (
                "REGISTRATION_ACCESS",
                "registration_access_findings",
                "status='OPEN'",
                "created_at",
            ),
            ("MEMBER_APPLICATION", "member_applications", "status='PENDING'", "submitted_at"),
            (
                "SERVICE_TICKET",
                "service_tickets",
                """status IN ('PENDING','IN_REVIEW') AND (
                    ticket_type!='CANDIDACY' OR id NOT IN (
                        SELECT legacy_ticket_id FROM recruitment_applications
                        WHERE guild_id=service_tickets.guild_id AND legacy_ticket_id IS NOT NULL
                    )
                )""",
                "submitted_at",
            ),
            (
                "RECRUITMENT_APPLICATION",
                "recruitment_applications",
                """status IN ('SUBMITTED','UNDER_REVIEW','INTERVIEW_PENDING',
                               'INTERVIEW_SCHEDULED','INTERVIEW_COMPLETED','FINAL_REVIEW')""",
                "submitted_at",
            ),
            ("ADMIN_REQUEST", "administrative_requests", "status='PENDING'", "submitted_at"),
            ("ABSENCE", "absence_requests", "status='PENDING'", "submitted_at"),
            ("COURSE_APPLICATION", "course_applications", "status='PENDING'", "submitted_at"),
            ("ACTIVITY_SWAP", "activity_swap_requests", "status='WAITING_COMMAND'", "submitted_at"),
            (
                "SHIFT_REVIEW",
                "shifts",
                "status='REVIEW_REQUIRED' OR validation_status='REVIEW_REQUIRED'",
                "started_at",
            ),
            ("INTEGRITY", "integrity_findings", "status='OPEN'", "detected_at"),
            ("OPERATIONAL_FLAG", "operational_flags", "status='OPEN'", "created_at"),
            (
                "PATROL_COMMANDER_FLAG",
                "patrol_operational_flags",
                "status='OPEN'",
                "created_at",
            ),
        )
        requested_type = item_type.upper() if item_type else None
        items: list[dict[str, object]] = []
        for source_type, table, where, time_column in sources:
            if requested_type and requested_type != source_type:
                continue
            rows = await self.database.fetchall(
                f"SELECT *, {time_column} AS inbox_time FROM {table} WHERE guild_id=? AND ({where})",
                (guild_id,),
            )
            for row in rows:
                items.append({"type": source_type, "id": int(row["id"]), "data": dict(row)})
        items.sort(key=lambda item: int(item["data"]["inbox_time"]), reverse=True)
        return items[:limit]

    async def decision_history(
        self, guild_id: int, *, actor_id: int | None = None, limit: int = 50
    ):
        where = "AND actor_id=?" if actor_id else ""
        params: tuple[object, ...] = (guild_id, actor_id, limit) if actor_id else (guild_id, limit)
        return await self.database.fetchall(
            f"""
            SELECT * FROM audit_logs WHERE guild_id=? {where}
              AND (action LIKE '%APPROV%' OR action LIKE '%REJECT%'
                   OR action LIKE '%DECID%' OR action LIKE '%REVIEW%'
                   OR action LIKE '%RESOLV%' OR action LIKE '%DISMISS%')
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            params,
        )

    async def changes_summary(self, guild_id: int, *, period_days: int = 7) -> dict[str, object]:
        if period_days not in {1, 7, 30}:
            raise ValidationError("Período permitido: 1, 7 ou 30 dias.")
        since = self.clock() - period_days * DAY_MS
        events = await self.database.fetchall(
            """
            SELECT * FROM domain_events WHERE guild_id=? AND created_at>=?
            ORDER BY created_at DESC, id DESC LIMIT 200
            """,
            (guild_id, since),
        )
        counts: dict[str, int] = {}
        for event in events:
            key = str(event["event_type"])
            counts[key] = counts.get(key, 0) + 1
        return {
            "period_days": period_days,
            "since": since,
            "counts": counts,
            "events": [dict(row) for row in events],
        }
