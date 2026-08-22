from __future__ import annotations

import json
import sqlite3

import pytest

import choque.database as database_module
from choque.audit import AuditService
from choque.config import Branding
from choque.database import Database
from choque.errors import ConflictError
from choque.members import MemberService
from choque.models import RbacProfile
from choque.rbac import PermissionService
from choque.settings import SettingsService
from choque.time_utils import period_bounds

from .conftest import DISCORD_ID, GUILD_ID


@pytest.mark.asyncio
async def test_migration_copies_legacy_and_creates_pre_migration_backup(tmp_path):
    legacy = tmp_path / "oasis_custom_data.db"
    connection = sqlite3.connect(legacy)
    connection.execute("CREATE TABLE legacy_value (id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO legacy_value(value) VALUES ('preserved')")
    connection.commit()
    connection.close()

    target = tmp_path / "data" / "choque_bgr.db"
    database = Database(target, legacy)
    await database.open()
    try:
        row = await database.fetchone("SELECT value FROM legacy_value")
        version = await database.fetchone("SELECT MAX(version) AS version FROM schema_migrations")
        assert row["value"] == "preserved"
        assert version["version"] == 24
        assert target.with_suffix(".db.migration-backup").exists()
        assert legacy.exists()
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_only_one_enabled_discord_role_mapping_per_rank(tmp_path):
    database = Database(tmp_path / "rank-mapping.db")
    await database.open()
    try:
        rank_id = await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
            VALUES (?, 'Soldado', 'SD', 1, 'MEMBRO', 1)
            """,
            (GUILD_ID,),
        )
        await database.execute(
            """
            INSERT INTO discord_role_mappings(
                guild_id, discord_role_id, mapping_type, internal_code,
                display_name, rank_id, enabled, created_at, updated_at
            ) VALUES (?, 1001, 'RANK', 'RANK_SOLDADO_A', 'Soldado A', ?, 1, 1, 1)
            """,
            (GUILD_ID, rank_id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            await database.execute(
                """
                INSERT INTO discord_role_mappings(
                    guild_id, discord_role_id, mapping_type, internal_code,
                    display_name, rank_id, enabled, created_at, updated_at
                ) VALUES (?, 1002, 'RANK', 'RANK_SOLDADO_B', 'Soldado B', ?, 1, 1, 1)
                """,
                (GUILD_ID, rank_id),
            )
        await database.execute(
            """
            UPDATE discord_role_mappings SET enabled=0
            WHERE guild_id=? AND discord_role_id=1001 AND mapping_type='RANK'
            """,
            (GUILD_ID,),
        )
        await database.execute(
            """
            INSERT INTO discord_role_mappings(
                guild_id, discord_role_id, mapping_type, internal_code,
                display_name, rank_id, enabled, created_at, updated_at
            ) VALUES (?, 1002, 'RANK', 'RANK_SOLDADO_B', 'Soldado B', ?, 1, 1, 1)
            """,
            (GUILD_ID, rank_id),
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_identity_migration_starts_presence_unconfirmed_and_has_normalized_projection(
    tmp_path,
):
    database = Database(tmp_path / "identity-schema.db")
    await database.open()
    try:
        member_columns = await database.fetchall("PRAGMA table_info(members)")
        defaults = {str(row["name"]): str(row["dflt_value"]) for row in member_columns}
        projection = await database.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='member_access_profiles'"
        )
        job_columns = {
            str(row["name"])
            for row in await database.fetchall(
                "PRAGMA table_info(identity_reconciliation_jobs)"
            )
        }
        item_columns = {
            str(row["name"])
            for row in await database.fetchall(
                "PRAGMA table_info(identity_reconciliation_job_items)"
            )
        }

        assert defaults["discord_present"] == "0"
        assert defaults["identity_sync_status"] == "'PENDING'"
        assert projection is not None
        assert "catalog_hash" in job_columns
        assert {
            "role_ids_json",
            "roles_hash",
            "discord_present_snapshot",
        } <= item_columns
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_identity_migration_seeds_access_catalog_for_guild_without_members(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "empty-guild-v22.db"
    all_migrations = database_module.MIGRATIONS
    monkeypatch.setattr(
        database_module,
        "MIGRATIONS",
        tuple(item for item in all_migrations if item[0] <= 22),
    )
    database = Database(target)
    await database.open()
    try:
        await database.execute(
            """
            INSERT INTO guild_settings(
                guild_id, setting_key, value_json, updated_at, updated_by
            ) VALUES (?, 'timezone', '"America/Sao_Paulo"', 1, 1)
            """,
            (GUILD_ID,),
        )
        await database.execute(
            """
            INSERT INTO rbac_bindings(guild_id, role_id, profile, created_at, created_by)
            VALUES (?, 901, 'MEMBRO', 1, 1)
            """,
            (GUILD_ID,),
        )
    finally:
        await database.close()

    monkeypatch.setattr(database_module, "MIGRATIONS", all_migrations)
    migrated = Database(target)
    await migrated.open()
    try:
        profile_count = await migrated.fetchone(
            "SELECT COUNT(*) AS total FROM access_profiles WHERE guild_id=?",
            (GUILD_ID,),
        )
        mapping = await migrated.fetchone(
            """
            SELECT drm.mapping_type, ap.code
            FROM discord_role_mappings drm
            JOIN access_profiles ap ON ap.id=drm.access_profile_id
            WHERE drm.guild_id=? AND drm.discord_role_id=901
            """,
            (GUILD_ID,),
        )
        assert profile_count["total"] == 9
        assert dict(mapping) == {"mapping_type": "ACCESS", "code": "MEMBRO"}
    finally:
        await migrated.close()


@pytest.mark.asyncio
async def test_identity_schema_rejects_cross_guild_projections(tmp_path):
    database = Database(tmp_path / "cross-guild-identity.db")
    await database.open()
    try:
        guild_a = GUILD_ID
        guild_b = GUILD_ID + 1
        member_a = await database.execute(
            """
            INSERT INTO members(
                guild_id, discord_id, mta_nick, status,
                joined_at, created_at, updated_at
            ) VALUES (?, 501, 'Membro_A', 'ACTIVE', 1, 1, 1)
            """,
            (guild_a,),
        )
        profile_a = await database.execute(
            """
            INSERT INTO access_profiles(
                guild_id, code, name, priority, created_at, updated_at
            ) VALUES (?, 'TEST_A', 'Teste A', 1, 1, 1)
            """,
            (guild_a,),
        )
        profile_b = await database.execute(
            """
            INSERT INTO access_profiles(
                guild_id, code, name, priority, created_at, updated_at
            ) VALUES (?, 'TEST_B', 'Teste B', 1, 1, 1)
            """,
            (guild_b,),
        )
        mapping_a = await database.execute(
            """
            INSERT INTO discord_role_mappings(
                guild_id, discord_role_id, mapping_type, internal_code,
                display_name, access_profile_id, enabled, created_at, updated_at
            ) VALUES (?, 601, 'ACCESS', 'TEST_A', 'Teste A', ?, 1, 1, 1)
            """,
            (guild_a, profile_a),
        )

        with pytest.raises(sqlite3.IntegrityError, match="cross-guild"):
            await database.execute(
                """
                INSERT INTO discord_role_mappings(
                    guild_id, discord_role_id, mapping_type, internal_code,
                    display_name, access_profile_id, enabled, created_at, updated_at
                ) VALUES (?, 602, 'ACCESS', 'INVALID', 'Inválido', ?, 1, 1, 1)
                """,
                (guild_a, profile_b),
            )
        with pytest.raises(sqlite3.IntegrityError, match="invalid member access"):
            await database.execute(
                """
                INSERT INTO member_access_profiles(
                    member_id, access_profile_id, source_mapping_id,
                    source_role_id, assigned_at, last_seen_at
                ) VALUES (?, ?, ?, 601, 1, 1)
                """,
                (member_a, profile_b, mapping_a),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cross-guild member"):
            await database.execute(
                "UPDATE members SET access_profile_id=? WHERE id=?",
                (profile_b, member_a),
            )
        await database.execute(
            """
            INSERT INTO member_access_profiles(
                member_id, access_profile_id, source_mapping_id,
                source_role_id, assigned_at, last_seen_at
            ) VALUES (?, ?, ?, 601, 1, 1)
            """,
            (member_a, profile_a, mapping_a),
        )
        violations = await database.fetchall("PRAGMA foreign_key_check")
        assert violations == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_migration_nine_preserves_existing_tickets_and_allows_other_subject(tmp_path):
    target = tmp_path / "choque_bgr.db"
    connection = sqlite3.connect(target)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at INTEGER NOT NULL
        );
        INSERT INTO schema_migrations(version, applied_at) VALUES (8, 1);

        CREATE TABLE guild_settings (
            guild_id INTEGER NOT NULL,
            setting_key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            updated_by INTEGER,
            PRIMARY KEY(guild_id, setting_key)
        );

        CREATE TABLE member_applications (
            id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'PENDING',
            submitted_at INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE rbac_bindings (
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            profile TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            created_by INTEGER,
            PRIMARY KEY(guild_id, role_id)
        );
        CREATE TABLE ranks (
            id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL DEFAULT 'Patente',
            prefix TEXT NOT NULL DEFAULT '',
            level INTEGER NOT NULL DEFAULT 1,
            discord_role_id INTEGER,
            rbac_profile TEXT NOT NULL DEFAULT 'MEMBRO',
            active INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL DEFAULT 1
        );
                CREATE TABLE members (
                    id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    discord_id INTEGER NOT NULL,
                    discord_nick TEXT,
                    character_id TEXT,
                    rank_id INTEGER REFERENCES ranks(id)
                );
        CREATE TABLE authorized_voice_channels (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            created_by INTEGER NOT NULL,
            PRIMARY KEY(guild_id, channel_id)
        );
        CREATE TABLE shifts (
            id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            ended_at INTEGER
        );
        CREATE TABLE shift_segments (
            id INTEGER PRIMARY KEY,
            shift_id INTEGER NOT NULL,
            started_at INTEGER NOT NULL,
            ended_at INTEGER
        );
        CREATE TABLE service_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            discord_id INTEGER NOT NULL,
            ticket_type TEXT NOT NULL CHECK (
                ticket_type IN ('CANDIDACY','TRANSFER','REPORT')
            ),
            status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
                status IN ('PENDING','IN_REVIEW','APPROVED','REJECTED','CANCELLED','CLOSED')
            ),
            subject_discord_id INTEGER,
            payload_json TEXT NOT NULL,
            submitted_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            claimed_by INTEGER,
            claimed_at INTEGER,
            reviewed_by INTEGER,
            reviewed_at INTEGER,
            review_reason TEXT,
            member_application_id INTEGER REFERENCES member_applications(id) ON DELETE RESTRICT
        );
        CREATE UNIQUE INDEX ux_open_service_ticket
        ON service_tickets(guild_id, discord_id, ticket_type)
        WHERE status IN ('PENDING','IN_REVIEW');
        CREATE INDEX ix_service_tickets_queue
        ON service_tickets(guild_id, ticket_type, status, submitted_at);
        CREATE INDEX ix_service_tickets_requester
        ON service_tickets(guild_id, discord_id, submitted_at DESC);
        INSERT INTO service_tickets(
            guild_id, discord_id, ticket_type, payload_json, submitted_at, updated_at
        ) VALUES (1, 2, 'REPORT', '{"details":"legado"}', 3, 3);
        """
    )
    connection.commit()
    connection.close()

    database = Database(target)
    await database.open()
    try:
        version = await database.fetchone("SELECT MAX(version) AS version FROM schema_migrations")
        preserved = await database.fetchone("SELECT * FROM service_tickets WHERE id=1")
        new_id = await database.execute(
            """
            INSERT INTO service_tickets(
                guild_id, discord_id, ticket_type, payload_json, submitted_at, updated_at
            ) VALUES (?, ?, 'OTHER', ?, ?, ?)
            """,
            (1, 3, '{"subject":"Dúvida","details":"Preciso de ajuda"}', 4, 4),
        )
        assert version["version"] == 24
        assert preserved["ticket_type"] == "REPORT"
        assert json.loads(preserved["payload_json"])["details"] == "legado"
        assert new_id > int(preserved["id"])
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_legacy_config_imports_once_and_converts_ids(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "GUILD_ID": str(GUILD_ID),
                "STAFF_ROLE_ID": "9001",
                "REGISTERED_ROLE_ID_1": "9002",
                "HIERARQUIA": [{"display_name": ": Soldado", "prefix": "[SD]", "role_id": "9003"}],
            }
        ),
        encoding="utf-8",
    )
    database = Database(tmp_path / "db.sqlite")
    await database.open()
    settings = SettingsService(database)
    try:
        assert await settings.import_legacy(config) == GUILD_ID
        assert await settings.import_legacy(config) == GUILD_ID
        assert await settings.get(GUILD_ID, "member_role_id") == 9002
        rank_count = await database.fetchone("SELECT COUNT(*) AS total FROM ranks")
        assert rank_count["total"] == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_rbac_profiles_and_bootstrap(service_bundle):
    settings = service_bundle["settings"]
    permissions = PermissionService(settings)
    await settings.bind_role(GUILD_ID, 81, RbacProfile.COMMAND, DISCORD_ID)
    command_permissions = await permissions.permissions_for(GUILD_ID, [81])
    assert {
        "shift.adjust",
        "member.edit",
        "panel.manage",
        "personnel.manage",
        "punishment.manage",
        "ticket.review",
        "recruitment.review",
    } <= command_permissions
    assert await permissions.permissions_for(GUILD_ID, [], is_owner=True) == {"*"}
    assert await permissions.permissions_for(GUILD_ID, [], is_discord_admin=True) == {"*"}


@pytest.mark.asyncio
async def test_application_approval_creates_active_member(tmp_path):
    database = Database(tmp_path / "db.sqlite")
    await database.open()
    settings = SettingsService(database)
    audit = AuditService(database, settings, Branding())
    members = MemberService(database, audit)
    try:
        await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, created_at)
            VALUES (?, 'Soldado', '[SD]', 1, 1)
            """,
            (GUILD_ID,),
        )
        application_id = await members.submit_application(
            GUILD_ID, DISCORD_ID, "MTA_Name", "88", "BGR", "Recrutador"
        )
        member = await members.review_application(
            application_id,
            999,
            True,
            "Aprovado no recrutamento",
            "Discord Name",
            enqueue_discord_sync=True,
        )
        assert member["status"] == "ACTIVE"
        assert member["rank_name"] == "Soldado"
        application = await members.get_application(application_id)
        queued_sync = await database.fetchone(
            """
            SELECT payload_json FROM web_action_outbox
            WHERE target_discord_id=? AND action_type='MEMBER_SYNC'
            """,
            (DISCORD_ID,),
        )
        assert application["status"] == "APPROVED"
        sync_payload = json.loads(queued_sync["payload_json"])
        assert sync_payload["source"] == "REGISTRATION"
        assert sync_payload["flow"] == "MEMBER_APPLICATION"
        assert sync_payload["member_application_id"] == application_id
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_application_decision_is_concurrency_safe_and_result_delivery_is_idempotent(
    service_bundle,
):
    import asyncio

    members = service_bundle["members"]
    database = service_bundle["database"]
    application_id = await members.submit_application(
        GUILD_ID,
        8001,
        "MTA_Concorrente",
        "801",
        "BGR",
        "Recrutador",
    )
    await members.record_application_review_message(application_id, 9101, 9201)

    results = await asyncio.gather(
        members.review_application(
            application_id,
            999,
            False,
            "Primeira decisão",
            "Discord Name",
        ),
        members.review_application(
            application_id,
            1000,
            True,
            "Segunda decisão",
            "Discord Name",
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1

    reviewed = await members.get_application(application_id)
    await members.mark_application_delivered(
        application_id,
        int(reviewed["reviewed_by"]),
        9301,
        9401,
    )
    await members.mark_application_delivered(
        application_id,
        int(reviewed["reviewed_by"]),
        9301,
        9401,
    )
    delivered = await members.get_application(application_id)
    audits = await database.fetchone(
        """
        SELECT COUNT(*) AS total FROM audit_logs
        WHERE action='MEMBER_APPLICATION_RESULT_DELIVERED' AND target_id=?
        """,
        (8001,),
    )
    assert delivered["delivery_status"] == "DELIVERED"
    assert delivered["review_channel_id"] == 9101
    assert delivered["review_message_id"] == 9201
    assert delivered["result_channel_id"] == 9301
    assert delivered["result_message_id"] == 9401
    assert audits["total"] == 1


def test_timezone_week_starts_on_monday():
    start, end = period_bounds("week", "America/Sao_Paulo")
    from datetime import datetime
    from zoneinfo import ZoneInfo

    local_start = datetime.fromtimestamp(start / 1000, ZoneInfo("America/Sao_Paulo"))
    assert local_start.weekday() == 0
    assert (local_start.hour, local_start.minute, local_start.second) == (0, 0, 0)
    assert end >= start
