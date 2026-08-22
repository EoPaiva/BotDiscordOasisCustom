from __future__ import annotations

from collections.abc import Callable

import aiosqlite

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .models import MemberStatus
from .shift_validation import closed_validation_values
from .time_utils import utc_now_ms

DAY_MS = 86_400_000
WARNING_TYPES = ("LEVE", "MODERADA", "GRAVE", "ADMINISTRATIVA")


class DisciplineService:
    """Núcleo transacional de ocorrências, advertências e suspensões."""

    def __init__(
        self,
        database: Database,
        audit: AuditService,
        *,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.audit = audit
        self.clock = clock

    @staticmethod
    def _required(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValidationError(f"Informe {label}.")
        return normalized

    @staticmethod
    def _optional(value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    async def _member_in_tx(self, connection: aiosqlite.Connection, guild_id: int, discord_id: int):
        cursor = await connection.execute(
            "SELECT id, status, mta_nick FROM members WHERE guild_id=? AND discord_id=?",
            (guild_id, discord_id),
        )
        member = await cursor.fetchone()
        if not member:
            raise NotFoundError("Membro não cadastrado.")
        return member

    async def create_occurrence(
        self,
        guild_id: int,
        discord_id: int,
        actor_id: int,
        description: str,
        *,
        evidence_url: str | None = None,
        observation: str | None = None,
    ) -> dict[str, object]:
        description = self._required(description, "a descrição da ocorrência")
        evidence_url = self._optional(evidence_url)
        observation = self._optional(observation)
        now = self.clock()
        async with self.database.transaction() as connection:
            member = await self._member_in_tx(connection, guild_id, discord_id)
            cursor = await connection.execute(
                """
                INSERT INTO disciplinary_occurrences(
                    guild_id, member_id, discord_id, description, evidence_url,
                    observation, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    member["id"],
                    discord_id,
                    description,
                    evidence_url,
                    observation,
                    actor_id,
                    now,
                ),
            )
            occurrence_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "DISCIPLINARY_OCCURRENCE_CREATED",
                actor_id=actor_id,
                target_id=discord_id,
                after={
                    "occurrence_id": occurrence_id,
                    "status": "OPEN",
                    "evidence_url": evidence_url,
                },
                reason=description,
                connection=connection,
            )
        return {
            "occurrence_id": occurrence_id,
            "discord_id": discord_id,
            "status": "OPEN",
        }

    async def open_occurrences(self, guild_id: int, *, limit: int = 25):
        return await self.database.fetchall(
            """
            SELECT o.*, m.mta_nick FROM disciplinary_occurrences o
            JOIN members m ON m.id=o.member_id
            WHERE o.guild_id=? AND o.status='OPEN'
            ORDER BY o.created_at ASC, o.id ASC LIMIT ?
            """,
            (guild_id, limit),
        )

    async def get_occurrence(self, guild_id: int, occurrence_id: int):
        return await self.database.fetchone(
            """
            SELECT o.*, m.mta_nick FROM disciplinary_occurrences o
            JOIN members m ON m.id=o.member_id
            WHERE o.guild_id=? AND o.id=?
            """,
            (guild_id, occurrence_id),
        )

    async def archive_occurrence(
        self, guild_id: int, occurrence_id: int, actor_id: int, reason: str
    ) -> dict[str, object]:
        reason = self._required(reason, "o motivo do arquivamento")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM disciplinary_occurrences WHERE guild_id=? AND id=?",
                (guild_id, occurrence_id),
            )
            occurrence = await cursor.fetchone()
            if not occurrence:
                raise NotFoundError("Ocorrência não encontrada.")
            cursor = await connection.execute(
                """
                UPDATE disciplinary_occurrences
                SET status='ARCHIVED', archived_by=?, archived_at=?, archive_reason=?
                WHERE id=? AND status='OPEN'
                """,
                (actor_id, now, reason, occurrence_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Essa ocorrência já foi decidida.")
            await self.audit.record(
                guild_id,
                "DISCIPLINARY_OCCURRENCE_ARCHIVED",
                actor_id=actor_id,
                target_id=int(occurrence["discord_id"]),
                before={"occurrence_id": occurrence_id, "status": "OPEN"},
                after={"status": "ARCHIVED"},
                reason=reason,
                connection=connection,
            )
        return {"occurrence_id": occurrence_id, "status": "ARCHIVED"}

    async def apply_warning(
        self,
        guild_id: int,
        discord_id: int,
        actor_id: int,
        warning_type: str,
        reason: str,
        *,
        evidence_url: str | None = None,
        observation: str | None = None,
        occurrence_id: int | None = None,
    ) -> dict[str, object]:
        warning_type = warning_type.strip().upper()
        if warning_type not in WARNING_TYPES:
            raise ValidationError("Selecione um tipo de advertência válido.")
        reason = self._required(reason, "o motivo da advertência")
        evidence_url = self._optional(evidence_url)
        observation = self._optional(observation)
        now = self.clock()
        async with self.database.transaction() as connection:
            member = await self._member_in_tx(connection, guild_id, discord_id)
            occurrence = None
            if occurrence_id is not None:
                cursor = await connection.execute(
                    "SELECT * FROM disciplinary_occurrences WHERE guild_id=? AND id=?",
                    (guild_id, occurrence_id),
                )
                occurrence = await cursor.fetchone()
                if not occurrence or int(occurrence["discord_id"]) != discord_id:
                    raise NotFoundError("Ocorrência não encontrada para esse membro.")
                if occurrence["status"] != "OPEN":
                    raise ConflictError("Essa ocorrência já foi decidida.")
                evidence_url = evidence_url or occurrence["evidence_url"]
                observation = observation or occurrence["observation"]
            cursor = await connection.execute(
                """
                INSERT INTO punishments(
                    guild_id, member_id, discord_id, punishment_type, warning_type,
                    reason, evidence_url, observation, previous_member_status,
                    starts_at, status, created_by, created_at
                ) VALUES (?, ?, ?, 'WARNING', ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
                """,
                (
                    guild_id,
                    member["id"],
                    discord_id,
                    warning_type,
                    reason,
                    evidence_url,
                    observation,
                    member["status"],
                    now,
                    actor_id,
                    now,
                ),
            )
            punishment_id = int(cursor.lastrowid)
            if occurrence_id is not None:
                cursor = await connection.execute(
                    """
                    UPDATE disciplinary_occurrences
                    SET status='CONVERTED_TO_WARNING', converted_punishment_id=?,
                        converted_by=?, converted_at=?
                    WHERE id=? AND status='OPEN'
                    """,
                    (punishment_id, actor_id, now, occurrence_id),
                )
                if cursor.rowcount != 1:
                    raise ConflictError("A ocorrência foi decidida simultaneamente.")
            await self.audit.record(
                guild_id,
                "WARNING_APPLIED",
                actor_id=actor_id,
                target_id=discord_id,
                after={
                    "punishment_id": punishment_id,
                    "warning_type": warning_type,
                    "status": "ACTIVE",
                    "occurrence_id": occurrence_id,
                    "evidence_url": evidence_url,
                },
                reason=reason,
                connection=connection,
            )
        return {
            "punishment_id": punishment_id,
            "discord_id": discord_id,
            "type": "WARNING",
            "warning_type": warning_type,
            "status": "ACTIVE",
            "occurrence_id": occurrence_id,
        }

    async def apply_suspension(
        self,
        guild_id: int,
        discord_id: int,
        actor_id: int,
        reason: str,
        *,
        starts_at: int,
        duration_days: int,
        observation: str | None = None,
        evidence_url: str | None = None,
    ) -> dict[str, object]:
        reason = self._required(reason, "o motivo da suspensão")
        if not 1 <= duration_days <= 365:
            raise ValidationError("A suspensão deve durar entre 1 e 365 dias.")
        now = self.clock()
        if starts_at < now - DAY_MS:
            raise ValidationError("A data inicial da suspensão não pode estar no passado.")
        if starts_at > now + 365 * DAY_MS:
            raise ValidationError("A suspensão não pode ser agendada com mais de 365 dias.")
        observation = self._optional(observation)
        evidence_url = self._optional(evidence_url)
        effective_now = starts_at <= now
        measure_status = "ACTIVE" if effective_now else "SCHEDULED"
        ends_at = starts_at + duration_days * DAY_MS
        try:
            async with self.database.transaction() as connection:
                member = await self._member_in_tx(connection, guild_id, discord_id)
                if member["status"] == MemberStatus.DISMISSED.value:
                    raise ConflictError("Membro desligado não pode ser suspenso.")
                cursor = await connection.execute(
                    """
                    INSERT INTO punishments(
                        guild_id, member_id, discord_id, punishment_type, reason,
                        evidence_url, observation, previous_member_status, starts_at,
                        ends_at, status, created_by, created_at
                    ) VALUES (?, ?, ?, 'SUSPENSION', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        member["id"],
                        discord_id,
                        reason,
                        evidence_url,
                        observation,
                        member["status"],
                        starts_at,
                        ends_at,
                        measure_status,
                        actor_id,
                        now,
                    ),
                )
                punishment_id = int(cursor.lastrowid)
                shift_closed = False
                if effective_now:
                    await connection.execute(
                        "UPDATE members SET status='SUSPENDED', updated_at=? WHERE id=?",
                        (now, member["id"]),
                    )
                    shift_closed = await self._close_shift_in_tx(
                        connection, guild_id, int(member["id"]), discord_id, now, actor_id
                    )
                await self.audit.record(
                    guild_id,
                    "SUSPENSION_APPLIED" if effective_now else "SUSPENSION_SCHEDULED",
                    actor_id=actor_id,
                    target_id=discord_id,
                    before={"member_status": member["status"]},
                    after={
                        "punishment_id": punishment_id,
                        "measure_status": measure_status,
                        "member_status": (
                            MemberStatus.SUSPENDED.value if effective_now else member["status"]
                        ),
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "shift_closed": shift_closed,
                    },
                    reason=reason,
                    connection=connection,
                )
        except aiosqlite.IntegrityError as exc:
            raise ConflictError(
                "Já existe uma suspensão ativa ou agendada para esse membro."
            ) from exc
        return {
            "punishment_id": punishment_id,
            "discord_id": discord_id,
            "type": "SUSPENSION",
            "status": measure_status,
            "member_status": (
                MemberStatus.SUSPENDED.value if effective_now else str(member["status"])
            ),
            "starts_at": starts_at,
            "ends_at": ends_at,
            "shift_closed": shift_closed,
        }

    async def _close_shift_in_tx(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        member_id: int,
        discord_id: int,
        now: int,
        actor_id: int,
    ) -> bool:
        cursor = await connection.execute(
            """
            SELECT * FROM shifts
            WHERE guild_id=? AND member_id=? AND status IN ('ACTIVE','GRACE')
            ORDER BY id DESC LIMIT 1
            """,
            (guild_id, member_id),
        )
        shift = await cursor.fetchone()
        if not shift:
            return False
        valid_end = int(shift["grace_started_at"] or now)
        await connection.execute(
            """
            UPDATE shift_segments SET ended_at=?, end_reason='MEMBER_SUSPENDED'
            WHERE shift_id=? AND ended_at IS NULL
            """,
            (valid_end, shift["id"]),
        )
        validation = await closed_validation_values(connection, shift, valid_end)
        cursor = await connection.execute(
            """
            UPDATE shifts SET status='CLOSED', ended_at=?, closed_at=?,
                end_reason='MEMBER_SUSPENDED', grace_started_at=NULL, grace_deadline=NULL,
                gross_duration_ms=?, patrol_duration_ms=?, patrol_requirement_met_at=?,
                validation_status=?, automatic_validation_status=?, invalid_reason=?,
                validation_source='AUTO', validated_at=?
            WHERE id=? AND status IN ('ACTIVE','GRACE')
            """,
            (
                valid_end,
                now,
                validation["gross_duration_ms"],
                validation["patrol_duration_ms"],
                validation["patrol_requirement_met_at"],
                validation["validation_status"],
                validation["validation_status"],
                validation["invalid_reason"],
                now,
                shift["id"],
            ),
        )
        if cursor.rowcount != 1:
            return False
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
                "validation_status": validation["validation_status"],
            },
            reason="MEMBER_SUSPENDED",
            connection=connection,
        )
        return True

    async def active_measures(self, guild_id: int, discord_id: int):
        return await self.database.fetchall(
            """
            SELECT * FROM punishments
            WHERE guild_id=? AND discord_id=? AND status IN ('SCHEDULED','ACTIVE')
              AND punishment_type IN ('WARNING','SUSPENSION')
            ORDER BY created_at DESC, id DESC
            """,
            (guild_id, discord_id),
        )

    async def get_measure(self, guild_id: int, punishment_id: int):
        return await self.database.fetchone(
            "SELECT * FROM punishments WHERE guild_id=? AND id=?",
            (guild_id, punishment_id),
        )

    async def fulfill_warning(
        self, guild_id: int, punishment_id: int, actor_id: int, reason: str
    ) -> dict[str, object]:
        reason = self._required(reason, "o motivo da conclusão")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM punishments WHERE guild_id=? AND id=?",
                (guild_id, punishment_id),
            )
            warning = await cursor.fetchone()
            if not warning or warning["punishment_type"] != "WARNING":
                raise NotFoundError("Advertência não encontrada.")
            cursor = await connection.execute(
                """
                UPDATE punishments SET status='FULFILLED', fulfilled_by=?,
                    fulfilled_at=?, fulfilled_reason=?
                WHERE id=? AND status='ACTIVE'
                """,
                (actor_id, now, reason, punishment_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Essa advertência não está mais ativa.")
            await self.audit.record(
                guild_id,
                "WARNING_FULFILLED",
                actor_id=actor_id,
                target_id=int(warning["discord_id"]),
                before={"punishment_id": punishment_id, "status": "ACTIVE"},
                after={"status": "FULFILLED"},
                reason=reason,
                connection=connection,
            )
        return {
            "punishment_id": punishment_id,
            "discord_id": int(warning["discord_id"]),
            "status": "FULFILLED",
        }

    async def member_summary(self, guild_id: int, discord_id: int) -> dict[str, object]:
        member = await self.database.fetchone(
            """
            SELECT m.*, r.name AS rank_name FROM members m
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        if not member:
            raise NotFoundError("Membro não cadastrado.")
        counts = await self.database.fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM disciplinary_occurrences o
                 WHERE o.guild_id=? AND o.discord_id=? AND o.status='OPEN') AS open_occurrences,
                (SELECT COUNT(*) FROM punishments p
                 WHERE p.guild_id=? AND p.discord_id=? AND p.punishment_type='WARNING'
                   AND p.status='ACTIVE') AS active_warnings,
                (SELECT COUNT(*) FROM punishments p
                 WHERE p.guild_id=? AND p.discord_id=? AND p.punishment_type='SUSPENSION'
                   AND p.status IN ('SCHEDULED','ACTIVE')) AS suspensions
            """,
            (guild_id, discord_id, guild_id, discord_id, guild_id, discord_id),
        )
        return {
            "member": member,
            "open_occurrences": int(counts["open_occurrences"]),
            "active_warnings": int(counts["active_warnings"]),
            "suspensions": int(counts["suspensions"]),
        }

    async def history(
        self, guild_id: int, discord_id: int, *, limit: int = 10, offset: int = 0
    ) -> list[dict[str, object]]:
        occurrences = await self.database.fetchall(
            """
            SELECT id, 'OCCURRENCE' AS record_type, status, description AS reason,
                   NULL AS warning_type, evidence_url, observation, created_by, created_at,
                   NULL AS starts_at, NULL AS ends_at
            FROM disciplinary_occurrences WHERE guild_id=? AND discord_id=?
            """,
            (guild_id, discord_id),
        )
        measures = await self.database.fetchall(
            """
            SELECT id, punishment_type AS record_type, status, reason, warning_type,
                   evidence_url, observation, created_by, created_at, starts_at, ends_at
            FROM punishments WHERE guild_id=? AND discord_id=?
              AND punishment_type IN ('WARNING','SUSPENSION')
            """,
            (guild_id, discord_id),
        )
        combined = [dict(row) for row in (*occurrences, *measures)]
        combined.sort(key=lambda row: (int(row["created_at"]), int(row["id"])), reverse=True)
        return combined[offset : offset + limit]

    async def history_count(self, guild_id: int, discord_id: int) -> int:
        row = await self.database.fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM disciplinary_occurrences
                 WHERE guild_id=? AND discord_id=?)
                +
                (SELECT COUNT(*) FROM punishments
                 WHERE guild_id=? AND discord_id=?
                   AND punishment_type IN ('WARNING','SUSPENSION')) AS total
            """,
            (guild_id, discord_id, guild_id, discord_id),
        )
        return int(row["total"])
