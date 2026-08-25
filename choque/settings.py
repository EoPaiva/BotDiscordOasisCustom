from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from .database import Database
from .identity_queue import enqueue_identity_reconciliation
from .models import RBAC_PROFILE_METADATA, RbacProfile
from .time_utils import utc_now_ms

LOGGER = logging.getLogger(__name__)

MODULE_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("REGISTRATION", "Cadastros", "📝"),
    ("POINT", "Bate-ponto", "⏱️"),
    ("REQUESTS", "Solicitações", "📥"),
    ("CAREER", "Carreira", "📈"),
    ("DISCIPLINE", "Disciplina", "⚖️"),
    ("TRAINING", "Treinamentos", "🎓"),
    ("ACTIVITY", "Atividade", "📊"),
    ("RANKING", "Ranking", "🏆"),
    ("RECRUITMENT", "Recrutamento", "🧑‍💼"),
    ("TICKETS", "Atendimento", "🎫"),
    ("PATROLS", "Patrulhas", "🚔"),
    ("FINANCIAL", "Auxílio Financeiro", "💰"),
)
MODULE_DEFAULTS = {key: True for key, _, _ in MODULE_DEFINITIONS}

class SettingsService:
    DEFAULTS: dict[str, Any] = {
        "timezone": "America/Sao_Paulo",
        "grace_period_seconds": 60,
        "minimum_patrol_minutes": 15,
        "minimum_patrol_members": 2,
        "patrol_continue_until_empty": True,
        "patrol_formation_dm_enabled": True,
        "automatic_patrol_clock_enabled": True,
        "patrol_report_max_evidence": 20,
        "patrol_commander_enabled": True,
        "patrol_commander_require_qualification": False,
        "patrol_commander_required_qualification_id": None,
        "patrol_commander_minimum_rank_level": 0,
        "patrol_commander_selection_priority": [
            "QUALIFICATION",
            "RANK_LEVEL",
            "TIME_IN_RANK",
            "TOTAL_SERVICE_TIME",
            "MEMBERSHIP_TIME",
            "PATROL_JOIN_ORDER",
        ],
        "patrol_commander_reassign_when_higher_rank_joins": True,
        "weekly_goal_minutes": 360,
        "audit_channel_id": None,
        "registration_approval_channel_id": None,
        "registration_history_channel_id": None,
        "registration_panel_channel_id": None,
        "registration_gate_enabled": False,
        "unregistered_role_id": None,
        "candidate_role_id": None,
        "registration_onboarding_category_id": None,
        "registration_support_channel_id": None,
        "registration_onboarding_channel_ids": [],
        "registration_bypass_role_ids": [],
        "registration_bypass_user_ids": [],
        "registration_dm_enabled": True,
        "registration_gate_activated_at": None,
        "point_panel_channel_id": None,
        "service_panel_channel_id": None,
        "hierarchy_channel_id": None,
        "config_panel_channel_id": None,
        "personnel_admin_channel_id": None,
        "absence_panel_channel_id": None,
        "requests_panel_channel_id": None,
        "career_panel_channel_id": None,
        "discipline_panel_channel_id": None,
        "training_panel_channel_id": None,
        "activity_panel_channel_id": None,
        "ranking_panel_channel_id": None,
        "recruitment_requirements_channel_id": None,
        "recruitment_panel_channel_id": None,
        "ticket_panel_channel_id": None,
        "ticket_active_category_id": None,
        "ticket_archive_category_id": None,
        "ticket_responsible_role_id": None,
        "ticket_bot_role_id": None,
        "ticket_transcript_channel_id": None,
        "ticket_requester_notify_cooldown_seconds": 60,
        "tag_member_panel_channel_id": None,
        "tag_admin_panel_channel_id": None,
        "tag_waiting_role_id": None,
        "tag_set_role_id": None,
        "tag_responsible_role_id": None,
        "tag_expiration_hours": 72,
        "tag_call_cooldown_seconds": 300,
        "tag_dm_enabled": True,
        "status_public_channel_id": None,
        "status_admin_channel_id": None,
        "status_notification_channel_id": None,
        "status_monitor_interval_seconds": 30,
        "status_alert_cooldown_seconds": 900,
        "status_api_health_url": "http://127.0.0.1:8080/health",
        "status_site_health_url": "https://choquebgr.online/status",
        "financial_panel_channel_id": None,
        "financial_admin_channel_id": None,
        "financial_suggestions_channel_id": None,
        "financial_honors_channel_id": None,
        "financial_pix_key": None,
        "financial_pix_key_fingerprint": None,
        "financial_pix_recipient_name": None,
        "financial_pix_recipient_city": None,
        "financial_dm_enabled": True,
        "financial_public_supporters_limit": 50,
        "recruitment_queue_channel_id": None,
        "recruitment_review_channel_id": None,
        "recruitment_public_status_channel_id": None,
        "recruitment_notification_channel_id": None,
        "recruitment_public_url": None,
        "transfer_results_channel_id": None,
        "recruitment_approved_channel_id": None,
        "recruitment_rejected_channel_id": None,
        "recruitment_tag_setup_channel_id": None,
        "recruitment_main_server_channel_id": None,
        "service_role_id": None,
        "member_role_id": None,
        "away_role_id": None,
        "reserve_role_id": None,
        "suspended_role_id": None,
        "weekly_near_threshold_percent": 75,
        "low_activity_days": 7,
        "no_activity_days": 14,
        "auto_remove_old_rank_roles": False,
        "enforce_member_nickname": True,
        "missing_rank_role_policy": "KEEP_LAST",
        "rank_sync_debounce_seconds": 1.0,
        "rank_audit_recovery_interval_seconds": 20,
        "identity_reconciliation_interval_hours": 6,
        "identity_stale_hours": 12,
        "patrol_formation_debounce_seconds": 1.0,
        "invalid_shift_flag_threshold": 3,
        "voice_disconnect_flag_threshold": 6,
        "manual_adjustment_flag_threshold": 3,
        "stale_request_hours": 48,
        "promotion_min_rank_days": 30,
        "promotion_min_valid_hours": 30,
        "promotion_required_courses": [],
        "career_progression_enabled": True,
        "career_progression_interval_seconds": 60,
        "promotion_channel_id": None,
        "automatic_progression_channel_id": None,
        "demotion_channel_id": None,
        "officer_candidacy_channel_id": None,
        "officer_upamento_channel_id": None,
        "officer_upamento_role_id": None,
        "officer_minimum_rank_name": "SOLDADO",
        "officer_minimum_valid_hours": 5,
        "officer_reapplication_days": 30,
        "officer_public_url": "https://choquebgr.online/candidatura-oficial",
        "career_positive_merit_categories": [
            "LIDERANÇA",
            "DESEMPENHO",
            "INICIATIVA",
            "PARTICIPAÇÃO",
            "COMPORTAMENTO EXEMPLAR",
            "CONTRIBUIÇÃO INSTITUCIONAL",
        ],
        "career_negative_merit_categories": [
            "FALHA",
            "DESEMPENHO INADEQUADO",
            "COMPORTAMENTO",
            "OCORRÊNCIA RELEVANTE",
        ],
        "recruit_min_days": 7,
        "recruit_min_valid_hours": 10,
        "recruit_min_patrols": 3,
        "recruit_min_evaluations": 2,
        "recruit_required_courses": [],
        "recruit_rank_names": ["RECRUTA"],
        "recruitment_stale_warning_hours": 24,
        "recruitment_review_sla_hours": 72,
        "recruitment_ai_enabled": False,
        "recruitment_ai_auto_analyze": True,
        "recruitment_ai_analyze_integrity": True,
        "recruitment_ai_generate_interview_questions": True,
        "recruitment_ai_generate_summary": True,
        "recruitment_ai_final_assisted_after_interview": True,
        "recruitment_ai_discord_notice": False,
        "recruitment_ai_show_score": True,
        "security_lockdown": False,
        "security_lockdown_reason": None,
        "security_lockdown_changed_at": None,
        "security_lockdown_changed_by": None,
        "security_log_retention_days": 365,
        "module_flags": MODULE_DEFAULTS,
    }

    def __init__(self, database: Database):
        self.database = database

    async def get(self, guild_id: int, key: str, default: Any = None) -> Any:
        row = await self.database.fetchone(
            "SELECT value_json FROM guild_settings WHERE guild_id = ? AND setting_key = ?",
            (guild_id, key),
        )
        if not row:
            return self.DEFAULTS.get(key, default)
        return json.loads(row["value_json"])

    async def set(
        self,
        guild_id: int,
        key: str,
        value: Any,
        actor_id: int | None,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        sql = """
            INSERT INTO guild_settings(guild_id, setting_key, value_json, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, setting_key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
        """
        params = (guild_id, key, json.dumps(value), utc_now_ms(), actor_id)
        if connection:
            await connection.execute(sql, params)
        else:
            await self.database.execute(sql, params)

    async def authorized_voice_ids(self, guild_id: int) -> set[int]:
        rows = await self.database.fetchall(
            """
            SELECT channel_id FROM authorized_voice_channels
            WHERE guild_id = ? AND service_allowed=1
            """,
            (guild_id,),
        )
        return {int(row["channel_id"]) for row in rows}

    async def is_authorized_voice(self, guild_id: int, channel_id: int | None) -> bool:
        if channel_id is None:
            return False
        row = await self.database.fetchone(
            """
            SELECT 1 FROM authorized_voice_channels
            WHERE guild_id = ? AND channel_id = ? AND service_allowed=1
            """,
            (guild_id, channel_id),
        )
        return row is not None

    async def voice_channel_policy(self, guild_id: int, channel_id: int | None):
        if channel_id is None:
            return None
        return await self.database.fetchone(
            """
            SELECT * FROM authorized_voice_channels
            WHERE guild_id=? AND channel_id=?
            """,
            (guild_id, channel_id),
        )

    async def counts_toward_patrol_minimum(self, guild_id: int, channel_id: int | None) -> bool:
        policy = await self.voice_channel_policy(guild_id, channel_id)
        return bool(
            policy
            and int(policy["service_allowed"])
            and int(policy["counts_toward_patrol_minimum"])
        )

    async def add_voice_channel(
        self, guild_id: int, channel_id: int, label: str, actor_id: int
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO authorized_voice_channels(
                guild_id, channel_id, label, created_at, created_by,
                service_allowed, counts_toward_patrol_minimum
            ) VALUES (?, ?, ?, ?, ?, 1, 1)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                label = excluded.label,
                service_allowed=1
            """,
            (guild_id, channel_id, label, utc_now_ms(), actor_id),
        )

    async def set_voice_patrol_classification(
        self,
        guild_id: int,
        channel_id: int,
        counts_toward_patrol_minimum: bool,
    ) -> None:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE authorized_voice_channels
                SET counts_toward_patrol_minimum=?
                WHERE guild_id=? AND channel_id=? AND service_allowed=1
                """,
                (int(counts_toward_patrol_minimum), guild_id, channel_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Call autorizada não encontrada.")

    async def remove_voice_channel(self, guild_id: int, channel_id: int) -> None:
        await self.database.execute(
            "DELETE FROM authorized_voice_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )

    async def bind_role(
        self,
        guild_id: int,
        role_id: int,
        profile: RbacProfile,
        actor_id: int,
        source: str = "ACCESS_ROLE_MAPPING_CHANGED",
        connection: aiosqlite.Connection | None = None,
    ) -> dict[str, object]:
        if connection is None:
            async with self.database.transaction() as transaction:
                return await self.bind_role(
                    guild_id,
                    role_id,
                    profile,
                    actor_id,
                    source,
                    connection=transaction,
                )
        now = utc_now_ms()
        profile_name, priority = RBAC_PROFILE_METADATA[profile]
        legacy_profiles = {
            RbacProfile.MEMBER,
            RbacProfile.GRADUATE,
            RbacProfile.INSTRUCTOR,
            RbacProfile.COMMAND,
            RbacProfile.ADMIN,
        }
        if profile in legacy_profiles:
            await connection.execute(
                """
                INSERT INTO rbac_bindings(
                    guild_id, role_id, profile, created_at, created_by
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, role_id) DO UPDATE SET
                    profile=excluded.profile,
                    created_by=excluded.created_by
                """,
                (guild_id, role_id, profile.value, now, actor_id),
            )
        else:
            # The legacy table has a deliberately narrow CHECK constraint.
            # New profiles live only in the canonical role mapping registry.
            await connection.execute(
                "DELETE FROM rbac_bindings WHERE guild_id=? AND role_id=?",
                (guild_id, role_id),
            )
        await connection.execute(
            """
            INSERT INTO access_profiles(
                guild_id, code, name, priority, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(guild_id, code) DO UPDATE SET
                name=excluded.name,
                priority=excluded.priority,
                enabled=1,
                updated_at=excluded.updated_at
            """,
            (guild_id, profile.value, profile_name, priority, now, now),
        )
        row = await connection.execute(
            "SELECT id FROM access_profiles WHERE guild_id=? AND code=?",
            (guild_id, profile.value),
        )
        access_profile = await row.fetchone()
        assert access_profile is not None
        await connection.execute(
            """
            INSERT INTO discord_role_mappings(
                guild_id, discord_role_id, mapping_type, internal_code,
                display_name, priority, access_profile_id, enabled,
                created_at, updated_at, created_by
            ) VALUES (?, ?, 'ACCESS', ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(guild_id, discord_role_id, mapping_type) DO UPDATE SET
                internal_code=excluded.internal_code,
                display_name=excluded.display_name,
                priority=excluded.priority,
                access_profile_id=excluded.access_profile_id,
                enabled=1,
                updated_at=excluded.updated_at,
                created_by=excluded.created_by
            """,
            (
                guild_id,
                role_id,
                f"ACCESS_ROLE_{role_id}",
                profile_name,
                priority,
                int(access_profile["id"]),
                now,
                now,
                actor_id,
            ),
        )
        return await enqueue_identity_reconciliation(
            connection,
            guild_id=guild_id,
            requested_by=actor_id,
            mode="APPLY",
            source=source,
        )

    async def unbind_role(
        self,
        guild_id: int,
        role_id: int,
        actor_id: int | None = None,
        source: str = "ACCESS_ROLE_MAPPING_REMOVED",
        connection: aiosqlite.Connection | None = None,
    ) -> dict[str, object]:
        if connection is None:
            async with self.database.transaction() as transaction:
                return await self.unbind_role(
                    guild_id,
                    role_id,
                    actor_id,
                    source,
                    connection=transaction,
                )
        await connection.execute(
            "DELETE FROM rbac_bindings WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )
        await connection.execute(
            """
            DELETE FROM discord_role_mappings
            WHERE guild_id=? AND discord_role_id=? AND mapping_type='ACCESS'
            """,
            (guild_id, role_id),
        )
        return await enqueue_identity_reconciliation(
            connection,
            guild_id=guild_id,
            requested_by=int(actor_id or 0),
            mode="APPLY",
            source=source,
        )

    async def set_rank_role_mapping(
        self,
        guild_id: int,
        rank_id: int,
        role_id: int | None,
        actor_id: int | None,
        *,
        enabled: bool | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        """Mantém o vínculo de patente canônico e seu espelho legado consistentes.

        ``discord_role_mappings`` é a fonte canônica. ``ranks.discord_role_id``
        permanece preenchido apenas por compatibilidade com telas e rotinas
        antigas. Toda troca desativa os vínculos anteriores dentro da mesma
        transação, inclusive quando o cargo estava associado a outra patente.
        """
        if connection is None:
            async with self.database.transaction() as transaction:
                await self.set_rank_role_mapping(
                    guild_id,
                    rank_id,
                    role_id,
                    actor_id,
                    enabled=enabled,
                    connection=transaction,
                )
            return

        cursor = await connection.execute(
            """
            SELECT id, name, level, active, discord_role_id
            FROM ranks
            WHERE guild_id=? AND id=?
            """,
            (guild_id, rank_id),
        )
        rank = await cursor.fetchone()
        if rank is None:
            raise ValueError("Patente não encontrada para vincular o cargo.")

        now = utc_now_ms()
        mapping_enabled = bool(rank["active"]) if enabled is None else bool(enabled)

        # Uma patente possui no máximo um cargo hierárquico canônico. O registro
        # antigo fica desabilitado para que a ausência de vínculo nunca reative
        # o fallback de ranks.discord_role_id.
        await connection.execute(
            """
            UPDATE discord_role_mappings
            SET enabled=0, updated_at=?
            WHERE guild_id=? AND mapping_type='RANK' AND rank_id=?
            """,
            (now, guild_id, rank_id),
        )

        if role_id is None:
            await connection.execute(
                "UPDATE ranks SET discord_role_id=NULL WHERE guild_id=? AND id=?",
                (guild_id, rank_id),
            )
            return

        normalized_role_id = int(role_id)
        if normalized_role_id <= 0:
            raise ValueError("O ID do cargo da patente deve ser positivo.")

        # Se o cargo mudou de patente, limpa também o espelho antigo. A linha
        # canônica do próprio cargo será reaproveitada pelo UPSERT abaixo.
        conflict_cursor = await connection.execute(
            """
            SELECT id
            FROM ranks
            WHERE guild_id=? AND discord_role_id=? AND id<>?
            """,
            (guild_id, normalized_role_id, rank_id),
        )
        conflicting_rank_ids = [int(row["id"]) for row in await conflict_cursor.fetchall()]
        if conflicting_rank_ids:
            placeholders = ",".join("?" for _ in conflicting_rank_ids)
            await connection.execute(
                f"""
                UPDATE discord_role_mappings
                SET enabled=0, updated_at=?
                WHERE guild_id=? AND mapping_type='RANK'
                  AND rank_id IN ({placeholders})
                """,
                (now, guild_id, *conflicting_rank_ids),
            )
            await connection.execute(
                """
                UPDATE ranks
                SET discord_role_id=NULL
                WHERE guild_id=? AND discord_role_id=? AND id<>?
                """,
                (guild_id, normalized_role_id, rank_id),
            )

        # Também cobre inconsistências em que o registry aponta para uma
        # patente diferente, mas o espelho legado já não contém o cargo.
        canonical_conflict_cursor = await connection.execute(
            """
            SELECT rank_id
            FROM discord_role_mappings
            WHERE guild_id=? AND discord_role_id=? AND mapping_type='RANK'
              AND rank_id<>?
            """,
            (guild_id, normalized_role_id, rank_id),
        )
        canonical_conflicts = [
            int(row["rank_id"])
            for row in await canonical_conflict_cursor.fetchall()
            if row["rank_id"] is not None
        ]
        if canonical_conflicts:
            placeholders = ",".join("?" for _ in canonical_conflicts)
            await connection.execute(
                f"""
                UPDATE discord_role_mappings
                SET enabled=0, updated_at=?
                WHERE guild_id=? AND mapping_type='RANK'
                  AND rank_id IN ({placeholders})
                """,
                (now, guild_id, *canonical_conflicts),
            )
            await connection.execute(
                f"""
                UPDATE ranks
                SET discord_role_id=NULL
                WHERE guild_id=? AND id IN ({placeholders})
                  AND discord_role_id=?
                """,
                (guild_id, *canonical_conflicts, normalized_role_id),
            )

        await connection.execute(
            "UPDATE ranks SET discord_role_id=? WHERE guild_id=? AND id=?",
            (normalized_role_id, guild_id, rank_id),
        )
        await connection.execute(
            """
            INSERT INTO discord_role_mappings(
                guild_id, discord_role_id, mapping_type, internal_code,
                display_name, priority, rank_id, position_id,
                access_profile_id, is_primary_position_candidate, enabled,
                created_at, updated_at, created_by
            ) VALUES (?, ?, 'RANK', ?, ?, ?, ?, NULL, NULL, 0, ?, ?, ?, ?)
            ON CONFLICT(guild_id, discord_role_id, mapping_type) DO UPDATE SET
                internal_code=excluded.internal_code,
                display_name=excluded.display_name,
                priority=excluded.priority,
                rank_id=excluded.rank_id,
                position_id=NULL,
                access_profile_id=NULL,
                is_primary_position_candidate=0,
                enabled=excluded.enabled,
                updated_at=excluded.updated_at,
                created_by=excluded.created_by
            """,
            (
                guild_id,
                normalized_role_id,
                f"RANK_{rank_id}",
                str(rank["name"]),
                int(rank["level"]),
                rank_id,
                int(mapping_enabled),
                now,
                now,
                actor_id,
            ),
        )
    async def role_profiles(self, guild_id: int, role_ids: set[int]) -> set[str]:
        if not role_ids:
            return set()
        placeholders = ",".join("?" for _ in role_ids)
        rows = await self.database.fetchall(
            f"SELECT profile FROM rbac_bindings WHERE guild_id = ? AND role_id IN ({placeholders})",
            (guild_id, *role_ids),
        )
        return {str(row["profile"]) for row in rows}

    async def upsert_panel(
        self, guild_id: int, panel_type: str, channel_id: int, message_id: int
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO panels(guild_id, panel_type, channel_id, message_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, panel_type) DO UPDATE SET
                channel_id = excluded.channel_id,
                message_id = excluded.message_id,
                updated_at = excluded.updated_at
            """,
            (guild_id, panel_type, channel_id, message_id, utc_now_ms()),
        )

    async def get_panel(self, guild_id: int, panel_type: str):
        return await self.database.fetchone(
            "SELECT channel_id, message_id FROM panels WHERE guild_id = ? AND panel_type = ?",
            (guild_id, panel_type),
        )

    async def import_legacy(self, config_path: Path) -> int | None:
        if not config_path.exists():
            return None
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Config legado nao importado: %s", exc)
            return None

        raw_guild = payload.get("GUILD_ID")
        if not raw_guild or not str(raw_guild).isdigit():
            return None
        guild_id = int(raw_guild)
        if await self.get(guild_id, "legacy_import_complete", False):
            return guild_id

        mappings = {
            "HR_LOGS_CHANNEL_ID": "audit_channel_id",
            "REGISTRATION_APPROVAL_CHANNEL_ID": "registration_approval_channel_id",
            "REGISTERED_ROLE_ID_1": "member_role_id",
            "HIERARCHY_CHANNEL_ID": "hierarchy_channel_id",
        }
        async with self.database.transaction() as connection:
            for old_key, new_key in mappings.items():
                value = payload.get(old_key)
                if value is not None and str(value).isdigit():
                    await self.set(guild_id, new_key, int(value), None, connection)
            for key, value in self.DEFAULTS.items():
                existing = await connection.execute(
                    "SELECT 1 FROM guild_settings WHERE guild_id = ? AND setting_key = ?",
                    (guild_id, key),
                )
                if not await existing.fetchone():
                    await self.set(guild_id, key, value, None, connection)

            for level, rank in enumerate(payload.get("HIERARQUIA", []), start=1):
                role_id = rank.get("role_id")
                if not role_id or not str(role_id).isdigit():
                    continue
                await connection.execute(
                    """
                    INSERT OR IGNORE INTO ranks(
                        guild_id, name, prefix, level, rbac_profile, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        str(rank.get("display_name", f"Patente {level}")).strip(": "),
                        str(rank.get("prefix", "")),
                        level,
                        RbacProfile.MEMBER.value,
                        utc_now_ms(),
                    ),
                )
                cursor = await connection.execute(
                    """
                    SELECT id, discord_role_id, active
                    FROM ranks
                    WHERE guild_id=? AND (level=? OR discord_role_id=?)
                    ORDER BY CASE WHEN level=? THEN 0 ELSE 1 END, id
                    LIMIT 1
                    """,
                    (guild_id, level, int(role_id), level),
                )
                imported_rank = await cursor.fetchone()
                if imported_rank is not None:
                    canonical_role_id = (
                        int(imported_rank["discord_role_id"])
                        if imported_rank["discord_role_id"] is not None
                        else int(role_id)
                    )
                    await self.set_rank_role_mapping(
                        guild_id,
                        int(imported_rank["id"]),
                        canonical_role_id,
                        None,
                        enabled=bool(imported_rank["active"]),
                        connection=connection,
                    )

            staff_role = payload.get("STAFF_ROLE_ID")
            if staff_role and str(staff_role).isdigit():
                await connection.execute(
                    """
                    INSERT OR IGNORE INTO rbac_bindings(guild_id, role_id, profile, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (guild_id, int(staff_role), RbacProfile.COMMAND.value, utc_now_ms()),
                )
            await self.set(guild_id, "legacy_import_complete", True, None, connection)
        LOGGER.info("Configuracao legada importada para a guild %s", guild_id)
        return guild_id
