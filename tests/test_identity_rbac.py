from __future__ import annotations

import json

import pytest

from choque.models import RbacProfile

from .conftest import DISCORD_ID, GUILD_ID


async def _mark_identity_synced(database) -> None:
    await database.execute(
        """
        UPDATE members
        SET identity_sync_status='SYNCED', discord_present=1,
            discord_roles_synced_at=1
        WHERE guild_id=? AND discord_id=?
        """,
        (GUILD_ID, DISCORD_ID),
    )


@pytest.mark.asyncio
async def test_new_access_profile_binding_uses_canonical_mapping(service_bundle):
    database = service_bundle["database"]
    settings = service_bundle["settings"]
    permissions = service_bundle["permissions"]

    await settings.bind_role(GUILD_ID, 987_001, RbacProfile.HIGH_COMMAND, DISCORD_ID)

    legacy = await database.fetchone(
        "SELECT 1 FROM rbac_bindings WHERE guild_id=? AND role_id=?",
        (GUILD_ID, 987_001),
    )
    mapping = await database.fetchone(
        """
        SELECT ap.code, drm.enabled
        FROM discord_role_mappings drm
        JOIN access_profiles ap ON ap.id=drm.access_profile_id
        WHERE drm.guild_id=? AND drm.discord_role_id=? AND drm.mapping_type='ACCESS'
        """,
        (GUILD_ID, 987_001),
    )
    resolved = await permissions.permissions_for(GUILD_ID, [987_001])

    assert legacy is None
    assert mapping["code"] == "ALTO_COMANDO"
    assert mapping["enabled"] == 1
    assert {"identity.configure", "settings.manage", "member.edit"} <= resolved

    await settings.unbind_role(
        GUILD_ID,
        987_001,
        DISCORD_ID,
        "DISCORD_PANEL_RBAC_REMOVED",
    )
    assert not await permissions.permissions_for(GUILD_ID, [987_001])
    jobs = await database.fetchall(
        """
        SELECT payload_json, requested_by FROM web_action_outbox
        WHERE guild_id=? AND action_type='IDENTITY_RECONCILE_BULK'
        ORDER BY id
        """,
        (GUILD_ID,),
    )
    assert len(jobs) == 2
    assert all(int(row["requested_by"]) == DISCORD_ID for row in jobs)
    assert json.loads(jobs[-1]["payload_json"])["source"] == "DISCORD_PANEL_RBAC_REMOVED"


@pytest.mark.asyncio
async def test_existing_upamento_role_gets_only_officer_review_permissions(service_bundle):
    settings = service_bundle["settings"]
    permissions = service_bundle["permissions"]
    role_id = 987_777

    await settings.bind_role(
        GUILD_ID, role_id, RbacProfile.OFFICER_REVIEWER, DISCORD_ID
    )
    resolved = await permissions.permissions_for(GUILD_ID, [role_id])

    assert {
        "officer.review",
        "officer.assign",
        "officer.evaluate",
        "officer.interview",
        "officer.decide",
    } <= resolved
    assert "settings.manage" not in resolved
    assert "career.manage" not in resolved


@pytest.mark.asyncio
async def test_explicit_member_deny_overrides_admin_wildcard(service_bundle):
    database = service_bundle["database"]
    permissions = service_bundle["permissions"]
    await permissions.ensure_defaults(GUILD_ID)
    profile = await database.fetchone(
        "SELECT id FROM access_profiles WHERE guild_id=? AND code='ADMINISTRADOR'",
        (GUILD_ID,),
    )
    member = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert profile is not None and member is not None
    await _mark_identity_synced(database)
    await database.execute(
        "UPDATE members SET access_profile_id=? WHERE id=?",
        (profile["id"], member["id"]),
    )
    await database.execute(
        """
        INSERT INTO member_permission_overrides(
            member_id, permission, effect, reason, created_by, created_at, updated_at
        ) VALUES (?, 'settings.manage', 'DENY', 'Teste de precedência', ?, 1, 1)
        """,
        (member["id"], DISCORD_ID),
    )

    access = await permissions.resolve_member_access(GUILD_ID, DISCORD_ID)

    assert access is not None
    assert "*" in access.permissions
    assert not access.can("settings.manage")
    assert access.can("member.edit")


@pytest.mark.asyncio
async def test_secondary_function_contributes_its_access_profile(service_bundle):
    database = service_bundle["database"]
    permissions = service_bundle["permissions"]
    await permissions.ensure_defaults(GUILD_ID)
    profiles = await database.fetchall(
        """
        SELECT id, code FROM access_profiles
        WHERE guild_id=? AND code IN ('SUPERVISOR','INSTRUTOR')
        """,
        (GUILD_ID,),
    )
    profile_ids = {str(row["code"]): int(row["id"]) for row in profiles}
    member = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert member is not None
    await _mark_identity_synced(database)
    await database.execute(
        "UPDATE members SET access_profile_id=? WHERE id=?",
        (profile_ids["SUPERVISOR"], member["id"]),
    )
    for code, name, profile_code, primary, source_role in (
        ("DUTY_SUPERVISOR", "Supervisor de serviço", "SUPERVISOR", 1, 991),
        ("COURSE_INSTRUCTOR", "Instrutor de cursos", "INSTRUTOR", 0, 992),
    ):
        position_id = await database.execute(
            """
            INSERT INTO functional_positions(
                guild_id, code, name, priority, access_profile_id,
                is_primary_candidate, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, 1, ?, 1, 1, 1, 1)
            """,
            (GUILD_ID, code, name, profile_ids[profile_code]),
        )
        await database.execute(
            """
            INSERT INTO discord_role_mappings(
                guild_id, discord_role_id, mapping_type, internal_code,
                display_name, priority, position_id, access_profile_id,
                is_primary_position_candidate, enabled, created_at, updated_at
            ) VALUES (?, ?, 'POSITION', ?, ?, 1, ?, ?, 1, 1, 1, 1)
            """,
            (
                GUILD_ID,
                source_role,
                code,
                name,
                position_id,
                profile_ids[profile_code],
            ),
        )
        await database.execute(
            """
            INSERT INTO member_positions(
                member_id, position_id, source_role_id, is_primary,
                assigned_at, last_seen_at
            ) VALUES (?, ?, ?, ?, 1, 1)
            """,
            (member["id"], position_id, source_role, primary),
        )

    access = await permissions.resolve_member_access(GUILD_ID, DISCORD_ID)

    assert access is not None
    assert access.profile == "SUPERVISOR"
    assert access.can("shift.view.all")
    assert access.can("training.manage")
    assert {str(item["code"]) for item in access.functions} == {
        "DUTY_SUPERVISOR",
        "COURSE_INSTRUCTOR",
    }


@pytest.mark.asyncio
async def test_pending_registration_cannot_inherit_elevated_identity(service_bundle):
    database = service_bundle["database"]
    permissions = service_bundle["permissions"]
    await permissions.ensure_defaults(GUILD_ID)
    admin = await database.fetchone(
        "SELECT id FROM access_profiles WHERE guild_id=? AND code='ADMINISTRADOR'",
        (GUILD_ID,),
    )
    assert admin is not None
    await database.execute(
        """
        UPDATE members SET status='PENDING', access_profile_id=?
        WHERE guild_id=? AND discord_id=?
        """,
        (admin["id"], GUILD_ID, DISCORD_ID),
    )

    access = await permissions.resolve_member_access(GUILD_ID, DISCORD_ID)

    assert access is not None
    assert access.profile == "CANDIDATO"
    assert access.can("request.submit")
    assert not access.can("settings.manage")


@pytest.mark.asyncio
async def test_active_legacy_command_profile_is_fail_closed_before_first_sync(
    service_bundle,
):
    database = service_bundle["database"]
    permissions = service_bundle["permissions"]
    await permissions.ensure_defaults(GUILD_ID)
    command = await database.fetchone(
        "SELECT id FROM access_profiles WHERE guild_id=? AND code='COMANDO'",
        (GUILD_ID,),
    )
    assert command is not None
    await database.execute(
        """
        UPDATE members
        SET status='ACTIVE', access_profile_id=?, identity_sync_status='PENDING',
            discord_present=1, discord_roles_synced_at=NULL
        WHERE guild_id=? AND discord_id=?
        """,
        (command["id"], GUILD_ID, DISCORD_ID),
    )

    access = await permissions.resolve_member_access(GUILD_ID, DISCORD_ID)

    assert access is not None
    assert access.profile == "MEMBRO"
    assert access.can("shift.start")
    assert not access.can("settings.manage")
    assert not access.can("member.edit")


@pytest.mark.asyncio
async def test_all_projected_access_profiles_compose_and_lower_deny_wins(service_bundle):
    database = service_bundle["database"]
    permissions = service_bundle["permissions"]
    await permissions.ensure_defaults(GUILD_ID)
    member = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert member is not None
    profile_ids: dict[str, int] = {}
    for code, priority in (("ACCESS_ALPHA", 80), ("ACCESS_BETA", 20)):
        profile_ids[code] = await database.execute(
            """
            INSERT INTO access_profiles(
                guild_id, code, name, priority, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, 1, 1)
            """,
            (GUILD_ID, code, code, priority),
        )
    for profile_code, permission, effect in (
        ("ACCESS_ALPHA", "settings.manage", "GRANT"),
        ("ACCESS_ALPHA", "exclusive.alpha", "GRANT"),
        ("ACCESS_BETA", "exclusive.beta", "GRANT"),
        ("ACCESS_BETA", "settings.manage", "DENY"),
    ):
        await database.execute(
            """
            INSERT INTO access_profile_permissions(
                access_profile_id, permission, effect, created_at, updated_at
            ) VALUES (?, ?, ?, 1, 1)
            """,
            (profile_ids[profile_code], permission, effect),
        )
    for index, profile_code in enumerate(("ACCESS_ALPHA", "ACCESS_BETA"), start=1):
        mapping_id = await database.execute(
            """
            INSERT INTO discord_role_mappings(
                guild_id, discord_role_id, mapping_type, internal_code,
                display_name, priority, access_profile_id,
                enabled, created_at, updated_at
            ) VALUES (?, ?, 'ACCESS', ?, ?, ?, ?, 1, 1, 1)
            """,
            (
                GUILD_ID,
                8800 + index,
                profile_code,
                profile_code,
                100 - index,
                profile_ids[profile_code],
            ),
        )
        await database.execute(
            """
            INSERT INTO member_access_profiles(
                member_id, access_profile_id, source_mapping_id,
                source_role_id, assigned_at, last_seen_at
            ) VALUES (?, ?, ?, ?, 1, 1)
            """,
            (member["id"], profile_ids[profile_code], mapping_id, 8800 + index),
        )
    await database.execute(
        "UPDATE members SET access_profile_id=? WHERE id=?",
        (profile_ids["ACCESS_ALPHA"], member["id"]),
    )
    await _mark_identity_synced(database)

    access = await permissions.resolve_member_access(GUILD_ID, DISCORD_ID)

    assert access is not None
    assert access.profile == "ACCESS_ALPHA"
    assert access.can("exclusive.alpha")
    assert access.can("exclusive.beta")
    assert not access.can("settings.manage")


@pytest.mark.asyncio
async def test_wildcard_preserves_custom_permission_while_other_permission_is_denied(
    service_bundle,
):
    database = service_bundle["database"]
    permissions = service_bundle["permissions"]
    await permissions.ensure_defaults(GUILD_ID)
    member = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    admin = await database.fetchone(
        "SELECT id FROM access_profiles WHERE guild_id=? AND code='ADMINISTRADOR'",
        (GUILD_ID,),
    )
    assert member is not None and admin is not None
    deny_profile = await database.execute(
        """
        INSERT INTO access_profiles(
            guild_id, code, name, priority, enabled, created_at, updated_at
        ) VALUES (?, 'LIMITADOR', 'Limitador', 1, 1, 1, 1)
        """,
        (GUILD_ID,),
    )
    await database.execute(
        """
        INSERT INTO access_profile_permissions(
            access_profile_id, permission, effect, created_at, updated_at
        ) VALUES (?, 'settings.manage', 'DENY', 1, 1)
        """,
        (deny_profile,),
    )
    for role_id, profile_id, code in (
        (8891, int(admin["id"]), "ADMIN_ACCESS"),
        (8892, deny_profile, "LIMIT_ACCESS"),
    ):
        mapping_id = await database.execute(
            """
            INSERT INTO discord_role_mappings(
                guild_id, discord_role_id, mapping_type, internal_code,
                display_name, access_profile_id, enabled, created_at, updated_at
            ) VALUES (?, ?, 'ACCESS', ?, ?, ?, 1, 1, 1)
            """,
            (GUILD_ID, role_id, code, code, profile_id),
        )
        await database.execute(
            """
            INSERT INTO member_access_profiles(
                member_id, access_profile_id, source_mapping_id,
                source_role_id, assigned_at, last_seen_at
            ) VALUES (?, ?, ?, ?, 1, 1)
            """,
            (member["id"], profile_id, mapping_id, role_id),
        )
    await database.execute(
        "UPDATE members SET access_profile_id=? WHERE id=?",
        (admin["id"], member["id"]),
    )
    await _mark_identity_synced(database)

    access = await permissions.resolve_member_access(GUILD_ID, DISCORD_ID)

    assert access is not None
    assert access.can("custom.permission.outside.static.catalog")
    assert not access.can("settings.manage")
