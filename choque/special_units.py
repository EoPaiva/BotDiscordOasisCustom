from __future__ import annotations

import json
import uuid
from collections.abc import Callable

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .settings import SettingsService
from .time_utils import utc_now_ms

UNIT_CODES = frozenset({"ROCAM", "TATICO", "ELITE", "CORREGEDORIA"})
ROLE_LEVELS = {"MEMBER": 1, "ASSISTANT": 2, "COMMAND": 3}


class SpecialUnitService:
    """Durable unit candidacy and membership over canonical CHOQUE identity."""

    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
        *,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit
        self.clock = clock

    @staticmethod
    def normalize_unit(value: str) -> str:
        code = value.strip().upper().replace("Á", "A")
        if code not in UNIT_CODES:
            raise ValidationError("Unidade especial inválida.")
        return code

    async def list_units(self):
        return await self.database.fetchall(
            "SELECT * FROM special_units WHERE enabled=1 ORDER BY sort_order"
        )

    async def linked_recruitment_guild_ids(self, canonical_guild_id: int) -> list[int]:
        rows = await self.database.fetchall(
            """
            SELECT guild_id FROM guild_settings
            WHERE setting_key='identity_source_guild_id' AND value_json=?
            ORDER BY guild_id
            """,
            (json.dumps(canonical_guild_id),),
        )
        return [int(row["guild_id"]) for row in rows]

    async def canonical_guild_id(self, recruitment_guild_id: int) -> int:
        source = await self.settings.get(recruitment_guild_id, "identity_source_guild_id")
        if source is None:
            raise ValidationError("Servidor de origem da identidade não configurado.")
        return int(source)

    async def submit_application(
        self, recruitment_guild_id: int, discord_id: int, unit_code: str
    ):
        unit_code = self.normalize_unit(unit_code)
        canonical_guild_id = await self.canonical_guild_id(recruitment_guild_id)
        now = self.clock()
        correlation_id = f"special-unit-apply:{canonical_guild_id}:{discord_id}:{uuid.uuid4()}"
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT id, status FROM members
                WHERE guild_id=? AND discord_id=? AND status='ACTIVE'
                """,
                (canonical_guild_id, discord_id),
            )
            member = await cursor.fetchone()
            if member is None:
                raise ValidationError("Somente membro ativo da CHOQUE pode se candidatar.")
            cursor = await connection.execute(
                """
                SELECT unit_code FROM special_unit_memberships
                WHERE canonical_guild_id=? AND member_id=? AND status='ACTIVE'
                """,
                (canonical_guild_id, member["id"]),
            )
            membership = await cursor.fetchone()
            if membership and str(membership["unit_code"]) == unit_code:
                raise ConflictError("Você já pertence a essa unidade.")
            cursor = await connection.execute(
                """
                SELECT id FROM special_unit_applications
                WHERE canonical_guild_id=? AND member_id=? AND status='PENDING'
                """,
                (canonical_guild_id, member["id"]),
            )
            if await cursor.fetchone():
                raise ConflictError("Você já possui uma candidatura de unidade pendente.")
            cursor = await connection.execute(
                """
                INSERT INTO special_unit_applications(
                    recruitment_guild_id, canonical_guild_id, member_id,
                    discord_id, unit_code, submitted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recruitment_guild_id,
                    canonical_guild_id,
                    member["id"],
                    discord_id,
                    unit_code,
                    now,
                    now,
                ),
            )
            application_id = int(cursor.lastrowid)
            await self._event(
                connection,
                canonical_guild_id=canonical_guild_id,
                unit_code=unit_code,
                member_id=int(member["id"]),
                application_id=application_id,
                event_type="APPLICATION_SUBMITTED",
                actor_id=discord_id,
                previous_state=None,
                next_state="PENDING",
                correlation_id=correlation_id,
            )
            await self.audit.record(
                recruitment_guild_id,
                "SPECIAL_UNIT_APPLICATION_SUBMITTED",
                actor_id=discord_id,
                target_id=discord_id,
                after={"application_id": application_id, "unit_code": unit_code},
                correlation_id=f"{correlation_id}:audit",
                connection=connection,
            )
        return await self.get_application(application_id)

    async def get_application(self, application_id: int):
        row = await self.database.fetchone(
            "SELECT * FROM special_unit_applications WHERE id=?", (application_id,)
        )
        if row is None:
            raise NotFoundError("Candidatura de unidade não encontrada.")
        return row

    async def queue(self, recruitment_guild_id: int, *, limit: int = 100):
        return await self.database.fetchall(
            """
            SELECT a.*, m.mta_nick, m.character_id, r.name AS rank_name,
                   r.level AS rank_level
            FROM special_unit_applications a
            JOIN members m ON m.id=a.member_id
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE a.recruitment_guild_id=? AND a.status='PENDING'
            ORDER BY a.submitted_at, a.id LIMIT ?
            """,
            (recruitment_guild_id, limit),
        )

    async def memberships(self, canonical_guild_id: int, unit_code: str):
        return await self.database.fetchall(
            """
            SELECT sm.*, m.mta_nick, m.character_id, r.name AS rank_name
            FROM special_unit_memberships sm
            JOIN members m ON m.id=sm.member_id
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE sm.canonical_guild_id=? AND sm.unit_code=? AND sm.status='ACTIVE'
            ORDER BY CASE sm.role_level WHEN 'COMMAND' THEN 1
                         WHEN 'ASSISTANT' THEN 2 ELSE 3 END,
                     lower(m.mta_nick), sm.id
            """,
            (canonical_guild_id, self.normalize_unit(unit_code)),
        )

    async def upsert_guild_resource(
        self,
        unit_code: str,
        guild_id: int,
        *,
        category_id: int | None,
        central_channel_id: int | None,
        member_role_id: int,
        assistant_role_id: int,
        command_role_id: int,
    ):
        unit_code = self.normalize_unit(unit_code)
        now = self.clock()
        await self.database.execute(
            """
            INSERT INTO special_unit_guild_resources(
                unit_code, guild_id, category_id, central_channel_id,
                member_role_id, assistant_role_id, command_role_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(unit_code, guild_id) DO UPDATE SET
                category_id=excluded.category_id,
                central_channel_id=excluded.central_channel_id,
                member_role_id=excluded.member_role_id,
                assistant_role_id=excluded.assistant_role_id,
                command_role_id=excluded.command_role_id,
                updated_at=excluded.updated_at
            """,
            (
                unit_code,
                guild_id,
                category_id,
                central_channel_id,
                member_role_id,
                assistant_role_id,
                command_role_id,
                now,
            ),
        )
        return await self.database.fetchone(
            "SELECT * FROM special_unit_guild_resources WHERE unit_code=? AND guild_id=?",
            (unit_code, guild_id),
        )

    async def set_role_level(
        self,
        canonical_guild_id: int,
        unit_code: str,
        target_discord_id: int,
        role_level: str,
        *,
        actor_id: int,
        reason: str,
    ):
        unit_code = self.normalize_unit(unit_code)
        role_level = role_level.strip().upper()
        if role_level not in ROLE_LEVELS:
            raise ValidationError("Nível funcional da unidade inválido.")
        reason = reason.strip()
        if not reason:
            raise ValidationError("Informe o motivo da alteração.")
        now = self.clock()
        correlation_id = f"special-unit-level:{canonical_guild_id}:{target_discord_id}:{uuid.uuid4()}"
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM special_unit_memberships
                WHERE canonical_guild_id=? AND discord_id=? AND unit_code=? AND status='ACTIVE'
                """,
                (canonical_guild_id, target_discord_id, unit_code),
            )
            membership = await cursor.fetchone()
            if membership is None:
                raise NotFoundError("Membro ativo da unidade não encontrado.")
            previous = str(membership["role_level"])
            if previous == role_level:
                return membership
            cursor = await connection.execute(
                """
                UPDATE special_unit_memberships
                SET role_level=?, changed_by=?, change_reason=?, version=version+1, updated_at=?
                WHERE id=? AND version=? AND status='ACTIVE'
                """,
                (
                    role_level,
                    actor_id,
                    reason,
                    now,
                    membership["id"],
                    membership["version"],
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Vínculo da unidade foi alterado por outra pessoa.")
            await self._event(
                connection,
                canonical_guild_id=canonical_guild_id,
                unit_code=unit_code,
                member_id=int(membership["member_id"]),
                application_id=None,
                event_type="ROLE_LEVEL_CHANGED",
                actor_id=actor_id,
                previous_state=previous,
                next_state=role_level,
                reason=reason,
                correlation_id=correlation_id,
            )
            await self._enqueue_role_syncs(
                connection,
                canonical_guild_id=canonical_guild_id,
                discord_id=target_discord_id,
                actor_id=actor_id,
                sync_key=f"level:{membership['id']}:{int(membership['version']) + 1}",
                now=now,
            )
            await self.audit.record(
                canonical_guild_id,
                "SPECIAL_UNIT_ROLE_LEVEL_CHANGED",
                actor_id=actor_id,
                target_id=target_discord_id,
                before={"unit_code": unit_code, "role_level": previous},
                after={"unit_code": unit_code, "role_level": role_level},
                reason=reason,
                correlation_id=f"{correlation_id}:audit",
                connection=connection,
            )
        return await self.database.fetchone(
            "SELECT * FROM special_unit_memberships WHERE id=?", (membership["id"],)
        )

    async def leave(
        self,
        canonical_guild_id: int,
        unit_code: str,
        target_discord_id: int,
        *,
        actor_id: int,
        reason: str,
    ) -> None:
        unit_code = self.normalize_unit(unit_code)
        reason = reason.strip()
        if not reason:
            raise ValidationError("Informe o motivo da saída.")
        now = self.clock()
        correlation_id = f"special-unit-leave:{canonical_guild_id}:{target_discord_id}:{uuid.uuid4()}"
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM special_unit_memberships
                WHERE canonical_guild_id=? AND discord_id=? AND unit_code=? AND status='ACTIVE'
                """,
                (canonical_guild_id, target_discord_id, unit_code),
            )
            membership = await cursor.fetchone()
            if membership is None:
                raise NotFoundError("Membro ativo da unidade não encontrado.")
            cursor = await connection.execute(
                """
                UPDATE special_unit_memberships
                SET status='LEFT', left_at=?, changed_by=?, change_reason=?,
                    version=version+1, updated_at=?
                WHERE id=? AND version=? AND status='ACTIVE'
                """,
                (
                    now,
                    actor_id,
                    reason,
                    now,
                    membership["id"],
                    membership["version"],
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Vínculo da unidade foi alterado por outra pessoa.")
            await connection.execute(
                "UPDATE members SET unit=NULL, updated_at=? WHERE id=? AND unit=?",
                (now, membership["member_id"], unit_code),
            )
            await self._event(
                connection,
                canonical_guild_id=canonical_guild_id,
                unit_code=unit_code,
                member_id=int(membership["member_id"]),
                application_id=None,
                event_type="MEMBER_LEFT",
                actor_id=actor_id,
                previous_state="ACTIVE",
                next_state="LEFT",
                reason=reason,
                correlation_id=correlation_id,
            )
            await self._enqueue_role_syncs(
                connection,
                canonical_guild_id=canonical_guild_id,
                discord_id=target_discord_id,
                actor_id=actor_id,
                sync_key=f"leave:{membership['id']}:{int(membership['version']) + 1}",
                now=now,
            )
            await self.audit.record(
                canonical_guild_id,
                "SPECIAL_UNIT_MEMBER_LEFT",
                actor_id=actor_id,
                target_id=target_discord_id,
                before={"unit_code": unit_code, "status": "ACTIVE"},
                after={"unit_code": unit_code, "status": "LEFT"},
                reason=reason,
                correlation_id=f"{correlation_id}:audit",
                connection=connection,
            )

    async def assign(
        self, application_id: int, actor_id: int, *, expected_version: int
    ):
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE special_unit_applications
                SET assigned_to=?, assigned_at=COALESCE(assigned_at, ?),
                    version=version+1, updated_at=?
                WHERE id=? AND status='PENDING' AND version=?
                  AND (assigned_to IS NULL OR assigned_to=?)
                """,
                (actor_id, now, now, application_id, expected_version, actor_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Candidatura assumida ou alterada por outra pessoa.")
        return await self.get_application(application_id)

    async def decide(
        self,
        application_id: int,
        actor_id: int,
        *,
        approved: bool,
        reason: str,
        expected_version: int,
    ):
        reason = reason.strip()
        if not reason:
            raise ValidationError("Informe a justificativa da decisão.")
        now = self.clock()
        correlation_id = f"special-unit-decision:{application_id}:{uuid.uuid4()}"
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM special_unit_applications WHERE id=?",
                (application_id,),
            )
            application = await cursor.fetchone()
            if application is None:
                raise NotFoundError("Candidatura de unidade não encontrada.")
            if int(application["discord_id"]) == actor_id:
                raise ConflictError("Você não pode decidir a própria candidatura.")
            status = "APPROVED" if approved else "REJECTED"
            cursor = await connection.execute(
                """
                UPDATE special_unit_applications
                SET status=?, reviewed_by=?, reviewed_at=?, decision_reason=?,
                    version=version+1, updated_at=?
                WHERE id=? AND status='PENDING' AND version=?
                  AND (assigned_to IS NULL OR assigned_to=?)
                """,
                (
                    status,
                    actor_id,
                    now,
                    reason,
                    now,
                    application_id,
                    expected_version,
                    actor_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Candidatura já decidida ou assumida por outra pessoa.")
            promoted = False
            if approved:
                promoted = await self._approve_membership(
                    connection, application, actor_id=actor_id, reason=reason, now=now
                )
            await self._event(
                connection,
                canonical_guild_id=int(application["canonical_guild_id"]),
                unit_code=str(application["unit_code"]),
                member_id=int(application["member_id"]),
                application_id=application_id,
                event_type="APPLICATION_APPROVED" if approved else "APPLICATION_REJECTED",
                actor_id=actor_id,
                previous_state="PENDING",
                next_state=status,
                reason=reason,
                metadata={"rank_promoted": promoted},
                correlation_id=correlation_id,
            )
            await self.audit.record(
                int(application["recruitment_guild_id"]),
                "SPECIAL_UNIT_APPLICATION_DECIDED",
                actor_id=actor_id,
                target_id=int(application["discord_id"]),
                before={"status": "PENDING"},
                after={
                    "status": status,
                    "unit_code": str(application["unit_code"]),
                    "rank_promoted": promoted,
                },
                reason=reason,
                correlation_id=f"{correlation_id}:audit",
                connection=connection,
            )
        return await self.get_application(application_id)

    async def _approve_membership(
        self, connection, application, *, actor_id: int, reason: str, now: int
    ) -> bool:
        canonical_guild_id = int(application["canonical_guild_id"])
        member_id = int(application["member_id"])
        discord_id = int(application["discord_id"])
        unit_code = str(application["unit_code"])
        await connection.execute(
            """
            UPDATE special_unit_memberships
            SET status='TRANSFERRED', left_at=?, changed_by=?,
                change_reason=?, version=version+1, updated_at=?
            WHERE canonical_guild_id=? AND member_id=? AND status='ACTIVE'
            """,
            (now, actor_id, reason, now, canonical_guild_id, member_id),
        )
        await connection.execute(
            """
            INSERT INTO special_unit_memberships(
                canonical_guild_id, member_id, discord_id, unit_code,
                role_level, status, joined_at, changed_by, change_reason, updated_at
            ) VALUES (?, ?, ?, ?, 'MEMBER', 'ACTIVE', ?, ?, ?, ?)
            """,
            (
                canonical_guild_id,
                member_id,
                discord_id,
                unit_code,
                now,
                actor_id,
                reason,
                now,
            ),
        )
        await connection.execute(
            "UPDATE members SET unit=?, updated_at=? WHERE id=? AND status='ACTIVE'",
            (unit_code, now, member_id),
        )
        promoted = await self._ensure_rank_floor(
            connection,
            canonical_guild_id=canonical_guild_id,
            member_id=member_id,
            discord_id=discord_id,
            actor_id=actor_id,
            sync_key=f"application:{int(application['id'])}",
            now=now,
        )
        await self._enqueue_role_syncs(
            connection,
            canonical_guild_id=canonical_guild_id,
            discord_id=discord_id,
            actor_id=actor_id,
            sync_key=f"application:{int(application['id'])}",
            now=now,
        )
        return promoted

    async def _ensure_rank_floor(
        self,
        connection,
        *,
        canonical_guild_id: int,
        member_id: int,
        discord_id: int,
        actor_id: int,
        sync_key: str,
        now: int,
    ) -> bool:
        minimum_level = int(
            await self.settings.get(canonical_guild_id, "special_unit_minimum_rank_level", 3)
        )
        cursor = await connection.execute(
            """
            SELECT m.rank_id, r.level, r.name
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id WHERE m.id=?
            """,
            (member_id,),
        )
        current = await cursor.fetchone()
        if current is None or current["level"] is None or int(current["level"]) >= minimum_level:
            return False
        cursor = await connection.execute(
            """
            SELECT id, name, level FROM ranks
            WHERE guild_id=? AND active=1 AND level>=?
            ORDER BY level, id LIMIT 1
            """,
            (canonical_guild_id, minimum_level),
        )
        target = await cursor.fetchone()
        if target is None:
            raise ValidationError("Patente mínima das unidades não está configurada.")
        correlation_id = f"special-unit-rank:{sync_key}"
        cursor = await connection.execute(
            """
            UPDATE members SET rank_id=?, updated_at=?
            WHERE id=? AND rank_id=? AND status='ACTIVE'
            """,
            (target["id"], now, member_id, current["rank_id"]),
        )
        if cursor.rowcount != 1:
            raise ConflictError("A patente mudou durante a aprovação da unidade.")
        action_cursor = await connection.execute(
            """
            INSERT OR IGNORE INTO personnel_actions(
                guild_id, member_id, discord_id, action_type, from_rank_id,
                to_rank_id, reason, actor_id, created_at, source, correlation_id
            ) VALUES (?, ?, ?, 'PROMOTION', ?, ?, ?, ?, ?, 'MANUAL', ?)
            """,
            (
                canonical_guild_id,
                member_id,
                discord_id,
                current["rank_id"],
                target["id"],
                "Promoção decorrente de aprovação em Unidade Especial.",
                actor_id,
                now,
                correlation_id,
            ),
        )
        action_id = int(action_cursor.lastrowid or 0)
        if action_id <= 0:
            cursor = await connection.execute(
                "SELECT id FROM personnel_actions WHERE correlation_id=?", (correlation_id,)
            )
            existing_action = await cursor.fetchone()
            if existing_action is None:
                raise ConflictError("Não foi possível registrar a promoção da unidade.")
            action_id = int(existing_action["id"])
        await connection.execute(
            """
            INSERT OR IGNORE INTO career_notifications(
                guild_id, notification_type, subject_id, target_discord_id,
                channel_setting_key, payload_json, status, attempts,
                available_at, correlation_id, created_at, updated_at
            ) VALUES (?, 'PROMOTION', ?, ?, 'career_promotion_channel_id', ?,
                      'PENDING', 0, ?, ?, ?, ?)
            """,
            (
                canonical_guild_id,
                action_id,
                discord_id,
                json.dumps(
                    {
                        "discord_id": discord_id,
                        "from_rank_name": current["name"],
                        "to_rank_name": target["name"],
                        "reason": "Promoção decorrente de aprovação em Unidade Especial.",
                        "source": "SPECIAL_UNIT_APPROVAL",
                        "actor_id": actor_id,
                    },
                    ensure_ascii=False,
                ),
                now,
                f"special-unit-promotion-notification:{sync_key}",
                now,
                now,
            ),
        )
        await connection.execute(
            """
            INSERT INTO web_action_outbox(
                guild_id, action_type, target_discord_id, payload_json,
                requested_by, correlation_id, available_at, created_at
            ) VALUES (?, 'RANK_SYNC', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(correlation_id) DO NOTHING
            """,
            (
                canonical_guild_id,
                discord_id,
                json.dumps(
                    {
                        "action": "PROMOTION",
                        "source": "SPECIAL_UNIT_APPROVAL",
                        "from_rank_id": current["rank_id"],
                        "to_rank_id": target["id"],
                    },
                    ensure_ascii=False,
                ),
                actor_id,
                f"{correlation_id}:sync",
                now,
                now,
            ),
        )
        return True

    async def _enqueue_role_syncs(
        self,
        connection,
        *,
        canonical_guild_id: int,
        discord_id: int,
        actor_id: int,
        sync_key: str,
        now: int,
    ) -> None:
        cursor = await connection.execute(
            """
            SELECT DISTINCT guild_id FROM special_unit_guild_resources
            WHERE unit_code IN (SELECT code FROM special_units WHERE enabled=1)
            """
        )
        guild_rows = await cursor.fetchall()
        guild_ids = {int(row["guild_id"]) for row in guild_rows}
        guild_ids.add(canonical_guild_id)
        for guild_id in sorted(guild_ids):
            correlation_id = f"special-unit-role-sync:{sync_key}:{guild_id}"
            await connection.execute(
                """
                INSERT INTO web_action_outbox(
                    guild_id, action_type, target_discord_id, payload_json,
                    requested_by, correlation_id, available_at, created_at
                ) VALUES (?, 'SPECIAL_UNIT_ROLE_SYNC', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(correlation_id) DO UPDATE SET
                    status='PENDING', attempts=0, available_at=excluded.available_at,
                    processed_at=NULL, last_error=NULL, payload_json=excluded.payload_json
                """,
                (
                    guild_id,
                    discord_id,
                    json.dumps(
                        {"canonical_guild_id": canonical_guild_id}, ensure_ascii=False
                    ),
                    actor_id,
                    correlation_id,
                    now,
                    now,
                ),
            )

    async def desired_role_ids(
        self, guild_id: int, canonical_guild_id: int, discord_id: int
    ) -> tuple[set[int], set[int]]:
        managed_rows = await self.database.fetchall(
            """
            SELECT member_role_id, assistant_role_id, command_role_id
            FROM special_unit_guild_resources WHERE guild_id=?
            """,
            (guild_id,),
        )
        managed = {
            int(value)
            for row in managed_rows
            for value in row
            if value is not None
        }
        membership = await self.database.fetchone(
            """
            SELECT sm.unit_code, sm.role_level, r.member_role_id,
                   r.assistant_role_id, r.command_role_id
            FROM special_unit_memberships sm
            JOIN special_unit_guild_resources r
              ON r.unit_code=sm.unit_code AND r.guild_id=?
            WHERE sm.canonical_guild_id=? AND sm.discord_id=? AND sm.status='ACTIVE'
            """,
            (guild_id, canonical_guild_id, discord_id),
        )
        if membership is None:
            return managed, set()
        desired: set[int] = set()
        level = ROLE_LEVELS[str(membership["role_level"])]
        for required, key in (
            (1, "member_role_id"),
            (2, "assistant_role_id"),
            (3, "command_role_id"),
        ):
            if level >= required and membership[key] is not None:
                desired.add(int(membership[key]))
        return managed, desired

    async def _event(
        self,
        connection,
        *,
        canonical_guild_id: int,
        unit_code: str,
        member_id: int | None,
        application_id: int | None,
        event_type: str,
        actor_id: int | None,
        previous_state: str | None,
        next_state: str | None,
        correlation_id: str,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO special_unit_events(
                canonical_guild_id, unit_code, member_id, application_id,
                event_type, actor_id, previous_state, next_state, reason,
                metadata_json, correlation_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_guild_id,
                unit_code,
                member_id,
                application_id,
                event_type,
                actor_id,
                previous_state,
                next_state,
                reason,
                json.dumps(metadata or {}, ensure_ascii=False),
                correlation_id,
                self.clock(),
            ),
        )
