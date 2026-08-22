from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from .conftest import DISCORD_ID, GUILD_ID


@dataclass
class FakeRole:
    id: int
    name: str


class FakeGuild:
    def __init__(self, roles: list[FakeRole]) -> None:
        self.id = GUILD_ID
        self.owner_id = 0
        self._roles = {role.id: role for role in roles}
        self._members: dict[int, FakeMember] = {}

    def get_role(self, role_id: int):
        return self._roles.get(role_id)

    def get_member(self, discord_id: int):
        return self._members.get(discord_id)

    async def fetch_member(self, discord_id: int):
        member = self.get_member(discord_id)
        if member is None:
            # The service only treats discord.NotFound as a confirmed absence;
            # tests that exercise that path call mark_discord_absent directly.
            raise RuntimeError("membro não encontrado")
        return member


class FakeMember:
    def __init__(
        self,
        guild: FakeGuild,
        discord_id: int,
        roles: list[FakeRole],
        *,
        nick: str | None = None,
    ) -> None:
        self.guild = guild
        self.id = discord_id
        self.roles = list(roles)
        self.nick = nick
        self.bot = False
        self.guild_permissions = SimpleNamespace(administrator=False)
        guild._members[discord_id] = self

    async def add_roles(self, *roles: FakeRole, reason: str) -> None:
        del reason
        existing = {role.id for role in self.roles}
        self.roles.extend(role for role in roles if role.id not in existing)

    async def remove_roles(self, *roles: FakeRole, reason: str) -> None:
        del reason
        removed = {role.id for role in roles}
        self.roles = [role for role in self.roles if role.id not in removed]

    async def edit(self, *, nick: str | None, reason: str) -> None:
        del reason
        self.nick = nick


async def _profile_id(service_bundle, code: str) -> int:
    await service_bundle["permissions"].ensure_defaults(GUILD_ID)
    row = await service_bundle["database"].fetchone(
        "SELECT id FROM access_profiles WHERE guild_id=? AND code=?",
        (GUILD_ID, code),
    )
    assert row is not None
    return int(row["id"])


async def _seed_identity_catalog(service_bundle):
    database = service_bundle["database"]
    member_profile = await _profile_id(service_bundle, "MEMBRO")
    instructor_profile = await _profile_id(service_bundle, "INSTRUTOR")
    command_profile = await _profile_id(service_bundle, "COMANDO")
    high_command_profile = await _profile_id(service_bundle, "ALTO_COMANDO")

    rank_member = FakeRole(71_001, "Soldado")
    rank_command = FakeRole(71_002, "Coronel")
    member_role = FakeRole(72_001, "Membro CHOQUE")
    instructor_role = FakeRole(72_002, "Instrutor")
    commander_role = FakeRole(72_003, "Comandante Geral")
    cosmetic_role = FakeRole(72_004, "Cor vermelha")

    await database.execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id,
            rbac_profile, created_at
        ) VALUES (?, 'Soldado', '[SD]', 1, ?, 'MEMBRO', 1)
        """,
        (GUILD_ID, rank_member.id),
    )
    await database.execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id,
            rbac_profile, created_at
        ) VALUES (?, 'Coronel', '[CEL]', 2, ?, 'COMANDO', 1)
        """,
        (GUILD_ID, rank_command.id),
    )
    rank_row = await database.fetchone(
        "SELECT id FROM ranks WHERE guild_id=? AND discord_role_id=?",
        (GUILD_ID, rank_member.id),
    )
    assert rank_row is not None
    await database.execute(
        """
        UPDATE members SET rank_id=?, rank_sync_status='SYNCED'
        WHERE guild_id=? AND discord_id=?
        """,
        (int(rank_row["id"]), GUILD_ID, DISCORD_ID),
    )

    positions = (
        ("MEMBER", "Membro CHOQUE", 100, member_profile, member_role.id),
        ("INSTRUCTOR", "Instrutor", 500, instructor_profile, instructor_role.id),
        (
            "COMMANDER_GENERAL",
            "Comandante Geral",
            1000,
            high_command_profile,
            commander_role.id,
        ),
    )
    position_ids: dict[str, int] = {}
    for code, name, priority, profile_id, role_id in positions:
        position_id = await database.execute(
            """
            INSERT INTO functional_positions(
                guild_id, code, name, priority, access_profile_id,
                is_primary_candidate, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, 1, 1, 1)
            """,
            (GUILD_ID, code, name, priority, profile_id),
        )
        position_ids[code] = position_id
        await database.execute(
            """
            INSERT INTO discord_role_mappings(
                guild_id, discord_role_id, mapping_type, internal_code,
                display_name, priority, position_id, access_profile_id,
                is_primary_position_candidate, enabled, created_at, updated_at
            ) VALUES (?, ?, 'POSITION', ?, ?, ?, ?, ?, 1, 1, 1, 1)
            """,
            (GUILD_ID, role_id, code, name, priority, position_id, profile_id),
        )
    await database.execute(
        """
        INSERT INTO discord_role_mappings(
            guild_id, discord_role_id, mapping_type, internal_code,
            display_name, priority, enabled, created_at, updated_at
        ) VALUES (?, ?, 'COSMETIC', 'COLOR_RED', 'Cor vermelha', 9999, 1, 1, 1)
        """,
        (GUILD_ID, cosmetic_role.id),
    )
    return {
        "rank_member": rank_member,
        "rank_command": rank_command,
        "member": member_role,
        "instructor": instructor_role,
        "commander": commander_role,
        "cosmetic": cosmetic_role,
        "position_ids": position_ids,
        "profiles": {
            "MEMBRO": member_profile,
            "INSTRUTOR": instructor_profile,
            "COMANDO": command_profile,
            "ALTO_COMANDO": high_command_profile,
        },
    }


@pytest.mark.asyncio
async def test_member_role_projects_member_profile(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    result = await service_bundle["rank_sync"].sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {catalog["rank_member"].id, catalog["member"].id},
        None,
        source="DISCORD_ROLE_CHANGE",
    )

    assert result.primary_position_code == "MEMBER"
    assert result.access_profile == "MEMBRO"
    assert result.identity_sync_status == "SYNCED"
    assert result.authorization_version == 2


@pytest.mark.asyncio
async def test_commander_role_projects_primary_and_high_command(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    service = service_bundle["rank_sync"]
    base_roles = {catalog["rank_member"].id, catalog["member"].id}
    base = await service.sync_from_discord(
        GUILD_ID, DISCORD_ID, base_roles, None, source="DISCORD_ROLE_CHANGE"
    )
    elevated = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        base_roles | {catalog["commander"].id},
        None,
        source="DISCORD_ROLE_CHANGE",
    )

    assert elevated.primary_position_code == "COMMANDER_GENERAL"
    assert elevated.access_profile == "ALTO_COMANDO"
    assert elevated.authorization_version == base.authorization_version + 1
    state = await service.identity_state(GUILD_ID, DISCORD_ID)
    assert state and state["primary_position_code"] == "COMMANDER_GENERAL"


@pytest.mark.asyncio
async def test_primary_position_keeps_all_secondary_functions(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    result = await service_bundle["rank_sync"].sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {
            catalog["rank_member"].id,
            catalog["member"].id,
            catalog["instructor"].id,
            catalog["commander"].id,
        },
        None,
        source="DISCORD_ROLE_CHANGE",
    )

    assert result.primary_position_code == "COMMANDER_GENERAL"
    assert set(result.functions) == {"INSTRUCTOR", "MEMBER"}
    assert set(result.position_codes) == {"COMMANDER_GENERAL", "INSTRUCTOR", "MEMBER"}


@pytest.mark.asyncio
async def test_removing_commander_revokes_access_and_increments_version(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    service = service_bundle["rank_sync"]
    base_roles = {catalog["rank_member"].id, catalog["member"].id}
    elevated = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        base_roles | {catalog["commander"].id},
        None,
        source="DISCORD_ROLE_CHANGE",
    )
    downgraded = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        base_roles,
        None,
        source="DISCORD_ROLE_CHANGE",
    )

    assert downgraded.primary_position_code == "MEMBER"
    assert downgraded.access_profile == "MEMBRO"
    assert downgraded.authorization_version == elevated.authorization_version + 1
    removed = await service_bundle["database"].fetchone(
        """
        SELECT 1 FROM member_identity_events
        WHERE event_type='FUNCTION_REMOVED'
          AND before_json LIKE '%COMMANDER_GENERAL%'
        """
    )
    assert removed is not None


@pytest.mark.asyncio
async def test_cosmetic_role_is_ignored_by_hash_version_and_listener_filter(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    service = service_bundle["rank_sync"]
    base_roles = {catalog["rank_member"].id, catalog["member"].id}
    base = await service.sync_from_discord(
        GUILD_ID, DISCORD_ID, base_roles, None, source="DISCORD_ROLE_CHANGE"
    )
    event_count = await service_bundle["database"].fetchone(
        "SELECT COUNT(*) AS total FROM member_identity_events"
    )
    cosmetic = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        base_roles | {catalog["cosmetic"].id},
        None,
        source="DISCORD_ROLE_CHANGE",
    )

    assert not cosmetic.db_changed
    assert cosmetic.authorization_version == base.authorization_version
    assert cosmetic.relevant_role_ids == base.relevant_role_ids
    assert not await service.role_change_is_relevant(
        GUILD_ID, base_roles, base_roles | {catalog["cosmetic"].id}
    )
    final_count = await service_bundle["database"].fetchone(
        "SELECT COUNT(*) AS total FROM member_identity_events"
    )
    assert final_count["total"] == event_count["total"]


@pytest.mark.asyncio
async def test_rank_change_reuses_rank_sync_and_nickname(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    result = await service_bundle["rank_sync"].sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {catalog["rank_command"].id, catalog["member"].id},
        "antigo",
        source="DISCORD_ROLE_CHANGE",
    )

    assert result.rank_name == "Coronel"
    assert result.expected_nickname == "[CEL] Choque_User [77]"
    event = await service_bundle["database"].fetchone(
        "SELECT event_type FROM rank_sync_events ORDER BY id DESC"
    )
    assert event["event_type"] == "PROMOTION"


@pytest.mark.asyncio
async def test_rank_mapping_is_canonical_over_legacy_rank_role_field(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    database = service_bundle["database"]
    service = service_bundle["rank_sync"]
    canonical_role = FakeRole(71_099, "Soldado canônico")
    rank = await database.fetchone(
        "SELECT id FROM ranks WHERE guild_id=? AND discord_role_id=?",
        (GUILD_ID, catalog["rank_member"].id),
    )
    assert rank is not None
    await database.execute(
        """
        INSERT INTO discord_role_mappings(
            guild_id, discord_role_id, mapping_type, internal_code,
            display_name, priority, rank_id, enabled, created_at, updated_at
        ) VALUES (?, ?, 'RANK', 'RANK_SOLDIER', 'Soldado canônico',
                  100, ?, 1, 1, 1)
        """,
        (GUILD_ID, canonical_role.id, rank["id"]),
    )

    assert await service.rank_role_ids(GUILD_ID) >= {canonical_role.id}
    assert catalog["rank_member"].id not in await service.rank_role_ids(GUILD_ID)
    legacy_only = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {catalog["rank_member"].id, catalog["member"].id},
        None,
        source="DISCORD_ROLE_CHANGE",
    )
    assert legacy_only.sync_status == "MISSING_ROLE"

    guild = FakeGuild([catalog["rank_member"], canonical_role, catalog["member"]])
    member = FakeMember(
        guild,
        DISCORD_ID,
        [catalog["rank_member"], catalog["member"]],
    )
    applied = await service.sync_to_member(member, source="FORMAL_CAREER_ACTION")
    assert canonical_role.id in {role.id for role in member.roles}
    assert applied.rank_role_id == canonical_role.id
    assert applied.sync_status == "SYNCED"


@pytest.mark.asyncio
async def test_missing_command_rank_role_keeps_label_but_revokes_command_profile(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    service = service_bundle["rank_sync"]
    elevated = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {catalog["rank_command"].id, catalog["member"].id},
        None,
        source="DISCORD_ROLE_CHANGE",
    )
    assert elevated.access_profile == "COMANDO"

    downgraded = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {catalog["member"].id},
        None,
        source="DISCORD_ROLE_CHANGE",
    )
    assert downgraded.rank_name == "Coronel"  # KEEP_LAST is presentation/history only
    assert downgraded.sync_status == "MISSING_ROLE"
    assert downgraded.access_profile == "MEMBRO"
    assert downgraded.authorization_version == elevated.authorization_version + 1


@pytest.mark.asyncio
async def test_member_absence_revokes_positions_and_is_idempotent(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    service = service_bundle["rank_sync"]
    elevated = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {
            catalog["rank_member"].id,
            catalog["member"].id,
            catalog["commander"].id,
        },
        None,
        source="DISCORD_ROLE_CHANGE",
    )
    absent = await service.mark_discord_absent(
        GUILD_ID, DISCORD_ID, source="DISCORD_MEMBER_REMOVE"
    )
    repeated = await service.mark_discord_absent(
        GUILD_ID, DISCORD_ID, source="STARTUP_RECONCILIATION"
    )

    assert absent.identity_sync_status == "DISCORD_ABSENT"
    assert not absent.discord_present
    assert absent.primary_position_id is None
    assert absent.access_profile == "MEMBRO"
    assert absent.authorization_version == elevated.authorization_version + 1
    assert not repeated.db_changed
    assert repeated.authorization_version == absent.authorization_version
    state = await service.identity_state(GUILD_ID, DISCORD_ID)
    assert state and state["positions"] == [] and not state["discord_present"]


@pytest.mark.asyncio
async def test_startup_reconciliation_recovers_missed_functional_role_event(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    guild = FakeGuild(
        [
            catalog["rank_member"],
            catalog["member"],
            catalog["commander"],
        ]
    )
    FakeMember(
        guild,
        DISCORD_ID,
        [catalog["rank_member"], catalog["member"], catalog["commander"]],
    )

    summary = await service_bundle["rank_sync"].reconcile_guild(
        guild, source="STARTUP_RECONCILIATION"
    )
    state = await service_bundle["rank_sync"].identity_state(GUILD_ID, DISCORD_ID)

    assert summary.checked == 1 and summary.changed == 1 and summary.failed == 0
    assert state and state["primary_position_code"] == "COMMANDER_GENERAL"
    assert state["access_profile"] == "ALTO_COMANDO"


@pytest.mark.asyncio
async def test_preview_then_apply_bulk_job_persists_evidence(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    service = service_bundle["rank_sync"]
    await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {catalog["rank_member"].id, catalog["member"].id},
        None,
        source="STARTUP_RECONCILIATION",
    )
    guild = FakeGuild(
        [catalog["rank_member"], catalog["member"], catalog["commander"]]
    )
    FakeMember(
        guild,
        DISCORD_ID,
        [catalog["rank_member"], catalog["member"], catalog["commander"]],
    )
    now = service_bundle["clock"]()
    preview_job_id = await service_bundle["database"].execute(
        """
        INSERT INTO identity_reconciliation_jobs(
            guild_id, mode, status, requested_by, correlation_id, created_at
        ) VALUES (?, 'PREVIEW', 'PENDING', ?, 'preview-identity-test', ?)
        """,
        (GUILD_ID, DISCORD_ID, now),
    )
    preview_summary = await service.process_reconciliation_job(preview_job_id, guild)
    state_before_apply = await service.identity_state(GUILD_ID, DISCORD_ID)
    assert preview_summary.changed == 1
    assert state_before_apply and state_before_apply["primary_position_code"] == "MEMBER"

    apply_job_id = await service_bundle["database"].execute(
        """
        INSERT INTO identity_reconciliation_jobs(
            guild_id, mode, status, requested_by, source_job_id,
            correlation_id, created_at
        ) VALUES (?, 'APPLY', 'PENDING', ?, ?, 'apply-identity-test', ?)
        """,
        (GUILD_ID, DISCORD_ID, preview_job_id, now),
    )
    apply_summary = await service.process_reconciliation_job(apply_job_id, guild)
    state = await service.identity_state(GUILD_ID, DISCORD_ID)
    item = await service_bundle["database"].fetchone(
        "SELECT result FROM identity_reconciliation_job_items WHERE job_id=?",
        (apply_job_id,),
    )

    assert apply_summary.changed == 1
    assert state and state["primary_position_code"] == "COMMANDER_GENERAL"
    assert item and item["result"] == "APPLIED"


@pytest.mark.asyncio
async def test_rank_sync_persists_every_access_mapping_and_composes_denies(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    database = service_bundle["database"]
    profile_ids: dict[str, int] = {}
    for code, priority in (("ROLE_ALPHA", 80), ("ROLE_BETA", 10)):
        profile_ids[code] = await database.execute(
            """
            INSERT INTO access_profiles(
                guild_id, code, name, priority, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, 1, 1)
            """,
            (GUILD_ID, code, code, priority),
        )
    for code, permission, effect in (
        ("ROLE_ALPHA", "exclusive.alpha", "GRANT"),
        ("ROLE_ALPHA", "settings.manage", "GRANT"),
        ("ROLE_BETA", "exclusive.beta", "GRANT"),
        ("ROLE_BETA", "settings.manage", "DENY"),
    ):
        await database.execute(
            """
            INSERT INTO access_profile_permissions(
                access_profile_id, permission, effect, created_at, updated_at
            ) VALUES (?, ?, ?, 1, 1)
            """,
            (profile_ids[code], permission, effect),
        )
    access_roles = [FakeRole(73_001, "Acesso A"), FakeRole(73_002, "Acesso B")]
    for role, code in zip(access_roles, ("ROLE_ALPHA", "ROLE_BETA"), strict=True):
        await database.execute(
            """
            INSERT INTO discord_role_mappings(
                guild_id, discord_role_id, mapping_type, internal_code,
                display_name, priority, access_profile_id,
                enabled, created_at, updated_at
            ) VALUES (?, ?, 'ACCESS', ?, ?, ?, ?, 1, 1, 1)
            """,
            (
                GUILD_ID,
                role.id,
                code,
                role.name,
                profile_ids[code],
                profile_ids[code],
            ),
        )

    result = await service_bundle["rank_sync"].sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {
            catalog["rank_member"].id,
            catalog["member"].id,
            *(role.id for role in access_roles),
        },
        None,
        source="DISCORD_ROLE_CHANGE",
    )
    projected = await database.fetchall(
        """
        SELECT ap.code, map.source_role_id
        FROM member_access_profiles map
        JOIN access_profiles ap ON ap.id=map.access_profile_id
        JOIN members m ON m.id=map.member_id
        WHERE m.guild_id=? AND m.discord_id=?
        ORDER BY ap.code
        """,
        (GUILD_ID, DISCORD_ID),
    )
    access = await service_bundle["permissions"].resolve_member_access(
        GUILD_ID, DISCORD_ID
    )

    assert result.access_profile == "ROLE_ALPHA"
    assert [(row["code"], row["source_role_id"]) for row in projected] == [
        ("ROLE_ALPHA", access_roles[0].id),
        ("ROLE_BETA", access_roles[1].id),
    ]
    assert access is not None
    assert access.can("exclusive.alpha") and access.can("exclusive.beta")
    assert not access.can("settings.manage")


@pytest.mark.asyncio
async def test_live_role_check_keeps_member_grant_and_member_deny(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    guild = FakeGuild([catalog["rank_member"], catalog["member"]])
    member = FakeMember(
        guild,
        DISCORD_ID,
        [catalog["rank_member"], catalog["member"]],
    )
    await service_bundle["rank_sync"].sync_from_member(
        member, source="STARTUP_RECONCILIATION"
    )
    row = await service_bundle["database"].fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert row is not None
    for permission, effect in (
        ("custom.bot.action", "GRANT"),
        ("shift.start", "DENY"),
    ):
        await service_bundle["database"].execute(
            """
            INSERT INTO member_permission_overrides(
                member_id, permission, effect, reason, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, 'Teste live', ?, 1, 1)
            """,
            (row["id"], permission, effect, DISCORD_ID),
        )

    assert await service_bundle["permissions"].has(member, "custom.bot.action")
    assert not await service_bundle["permissions"].has(member, "shift.start")


@pytest.mark.asyncio
async def test_reconciliation_failure_is_per_item_and_retry_preserves_success(
    service_bundle, monkeypatch
):
    catalog = await _seed_identity_catalog(service_bundle)
    second_id = DISCORD_ID + 1
    await service_bundle["members"].create_or_update(
        GUILD_ID,
        second_id,
        discord_nick="Segundo",
        mta_nick="Segundo_User",
        character_id="78",
        unit="BGR",
        rank_id=None,
        actor_id=DISCORD_ID,
    )
    guild = FakeGuild([catalog["rank_member"], catalog["member"]])
    for discord_id in (DISCORD_ID, second_id):
        FakeMember(
            guild,
            discord_id,
            [catalog["rank_member"], catalog["member"]],
        )
    service = service_bundle["rank_sync"]
    original_preview = service.preview_from_member
    first_calls: list[int] = []

    async def fail_first(target, *, source):
        first_calls.append(target.id)
        if target.id == DISCORD_ID:
            raise RuntimeError("falha determinística")
        return await original_preview(target, source=source)

    monkeypatch.setattr(service, "preview_from_member", fail_first)
    now = service_bundle["clock"]()
    job_id = await service_bundle["database"].execute(
        """
        INSERT INTO identity_reconciliation_jobs(
            guild_id, mode, status, requested_by, correlation_id, created_at
        ) VALUES (?, 'PREVIEW', 'PENDING', ?, 'preview-retry-items', ?)
        """,
        (GUILD_ID, DISCORD_ID, now),
    )

    first = await service.process_reconciliation_job(job_id, guild)
    rows = await service_bundle["database"].fetchall(
        """
        SELECT discord_id, result FROM identity_reconciliation_job_items
        WHERE job_id=? ORDER BY discord_id
        """,
        (job_id,),
    )
    assert first.failed == 1
    assert [row["result"] for row in rows] == ["FAILED", "DIVERGENT"]
    assert first_calls == [DISCORD_ID, second_id]

    retry_calls: list[int] = []

    async def recovered(target, *, source):
        retry_calls.append(target.id)
        return await original_preview(target, source=source)

    monkeypatch.setattr(service, "preview_from_member", recovered)
    retry = await service.process_reconciliation_job(job_id, guild)
    job = await service_bundle["database"].fetchone(
        "SELECT status, failed_members FROM identity_reconciliation_jobs WHERE id=?",
        (job_id,),
    )

    assert retry.failed == 0
    assert retry_calls == [DISCORD_ID]
    assert job and job["status"] == "COMPLETED" and job["failed_members"] == 0


@pytest.mark.asyncio
async def test_apply_rejects_preview_when_mapping_catalog_changed(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    service = service_bundle["rank_sync"]
    await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {catalog["rank_member"].id, catalog["member"].id},
        None,
        source="STARTUP_RECONCILIATION",
    )
    guild = FakeGuild(
        [catalog["rank_member"], catalog["member"], catalog["commander"]]
    )
    FakeMember(
        guild,
        DISCORD_ID,
        [catalog["rank_member"], catalog["member"], catalog["commander"]],
    )
    now = service_bundle["clock"]()
    preview_job = await service_bundle["database"].execute(
        """
        INSERT INTO identity_reconciliation_jobs(
            guild_id, mode, status, requested_by, correlation_id, created_at
        ) VALUES (?, 'PREVIEW', 'PENDING', ?, 'preview-stale-catalog', ?)
        """,
        (GUILD_ID, DISCORD_ID, now),
    )
    await service.process_reconciliation_job(preview_job, guild)
    state_before = await service.identity_state(GUILD_ID, DISCORD_ID)
    await service_bundle["database"].execute(
        """
        UPDATE discord_role_mappings SET priority=priority+1, updated_at=updated_at+1
        WHERE guild_id=? AND discord_role_id=? AND mapping_type='POSITION'
        """,
        (GUILD_ID, catalog["commander"].id),
    )
    apply_job = await service_bundle["database"].execute(
        """
        INSERT INTO identity_reconciliation_jobs(
            guild_id, mode, status, requested_by, source_job_id,
            correlation_id, created_at
        ) VALUES (?, 'APPLY', 'PENDING', ?, ?, 'apply-stale-catalog', ?)
        """,
        (GUILD_ID, DISCORD_ID, preview_job, now),
    )

    summary = await service.process_reconciliation_job(apply_job, guild)
    state_after = await service.identity_state(GUILD_ID, DISCORD_ID)
    item = await service_bundle["database"].fetchone(
        "SELECT result, error FROM identity_reconciliation_job_items WHERE job_id=?",
        (apply_job,),
    )

    assert summary.failed == 1
    assert state_after == state_before
    assert item and item["result"] == "FAILED" and "catálogo" in item["error"]


@pytest.mark.asyncio
async def test_apply_rejects_member_when_roles_changed_after_preview(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    service = service_bundle["rank_sync"]
    await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {catalog["rank_member"].id, catalog["member"].id},
        None,
        source="STARTUP_RECONCILIATION",
    )
    guild = FakeGuild(
        [catalog["rank_member"], catalog["member"], catalog["commander"]]
    )
    member = FakeMember(
        guild,
        DISCORD_ID,
        [catalog["rank_member"], catalog["member"]],
    )
    now = service_bundle["clock"]()
    preview_job = await service_bundle["database"].execute(
        """
        INSERT INTO identity_reconciliation_jobs(
            guild_id, mode, status, requested_by, correlation_id, created_at
        ) VALUES (?, 'PREVIEW', 'PENDING', ?, 'preview-stale-roles', ?)
        """,
        (GUILD_ID, DISCORD_ID, now),
    )
    await service.process_reconciliation_job(preview_job, guild)
    state_before = await service.identity_state(GUILD_ID, DISCORD_ID)
    member.roles.append(catalog["commander"])
    apply_job = await service_bundle["database"].execute(
        """
        INSERT INTO identity_reconciliation_jobs(
            guild_id, mode, status, requested_by, source_job_id,
            correlation_id, created_at
        ) VALUES (?, 'APPLY', 'PENDING', ?, ?, 'apply-stale-roles', ?)
        """,
        (GUILD_ID, DISCORD_ID, preview_job, now),
    )

    summary = await service.process_reconciliation_job(apply_job, guild)
    state_after = await service.identity_state(GUILD_ID, DISCORD_ID)
    item = await service_bundle["database"].fetchone(
        "SELECT result, error FROM identity_reconciliation_job_items WHERE job_id=?",
        (apply_job,),
    )

    assert summary.failed == 1
    assert state_after == state_before
    assert item and item["result"] == "FAILED" and "cargos Discord" in item["error"]


@pytest.mark.asyncio
async def test_duplicate_concurrent_role_reconciliations_are_idempotent(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    service = service_bundle["rank_sync"]
    role_ids = {catalog["rank_member"].id, catalog["member"].id}

    results = await asyncio.gather(
        *(
            service.sync_from_discord(
                GUILD_ID,
                DISCORD_ID,
                role_ids,
                None,
                source="DISCORD_ROLE_CHANGE",
            )
            for _ in range(2)
        )
    )
    events = await service_bundle["database"].fetchall(
        """
        SELECT event_type, COUNT(*) AS total
        FROM member_identity_events
        WHERE guild_id=? AND discord_id=?
        GROUP BY event_type
        ORDER BY event_type
        """,
        (GUILD_ID, DISCORD_ID),
    )

    assert sorted(result.db_changed for result in results) == [False, True]
    assert {result.authorization_version for result in results} == {2}
    assert events
    assert all(int(row["total"]) == 1 for row in events)


@pytest.mark.asyncio
async def test_identity_projection_rolls_back_when_event_insert_fails(
    service_bundle, monkeypatch
):
    catalog = await _seed_identity_catalog(service_bundle)
    service = service_bundle["rank_sync"]
    database = service_bundle["database"]
    before = await service.identity_state(GUILD_ID, DISCORD_ID)
    audit_before = await database.fetchone(
        "SELECT COUNT(*) AS total FROM audit_logs WHERE guild_id=?", (GUILD_ID,)
    )

    async def fail_identity_event(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("falha de persistência do evento")

    monkeypatch.setattr(service, "_insert_identity_event", fail_identity_event)
    with pytest.raises(RuntimeError, match="falha de persistência do evento"):
        await service.sync_from_discord(
            GUILD_ID,
            DISCORD_ID,
            {catalog["rank_member"].id, catalog["member"].id},
            None,
            source="DISCORD_ROLE_CHANGE",
        )

    after = await service.identity_state(GUILD_ID, DISCORD_ID)
    positions = await database.fetchone(
        """
        SELECT COUNT(*) AS total
        FROM member_positions mp
        JOIN members m ON m.id=mp.member_id
        WHERE m.guild_id=? AND m.discord_id=?
        """,
        (GUILD_ID, DISCORD_ID),
    )
    identity_events = await database.fetchone(
        """
        SELECT COUNT(*) AS total FROM member_identity_events
        WHERE guild_id=? AND discord_id=?
        """,
        (GUILD_ID, DISCORD_ID),
    )
    audit_after = await database.fetchone(
        "SELECT COUNT(*) AS total FROM audit_logs WHERE guild_id=?", (GUILD_ID,)
    )

    assert after == before
    assert int(positions["total"]) == 0
    assert int(identity_events["total"]) == 0
    assert int(audit_after["total"]) == int(audit_before["total"])


@pytest.mark.asyncio
async def test_gateway_reconciliation_keeps_unknown_actor_null(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    await service_bundle["rank_sync"].sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {catalog["rank_member"].id, catalog["member"].id},
        None,
        source="DISCORD_ROLE_CHANGE",
    )

    identity_actors = await service_bundle["database"].fetchall(
        """
        SELECT actor_id FROM member_identity_events
        WHERE guild_id=? AND discord_id=?
        """,
        (GUILD_ID, DISCORD_ID),
    )
    audit_actor = await service_bundle["database"].fetchone(
        """
        SELECT actor_id FROM audit_logs
        WHERE guild_id=? AND target_id=? AND action='MEMBER_IDENTITY_RECONCILED'
        ORDER BY id DESC LIMIT 1
        """,
        (GUILD_ID, DISCORD_ID),
    )

    assert identity_actors
    assert all(row["actor_id"] is None for row in identity_actors)
    assert audit_actor is not None and audit_actor["actor_id"] is None


@pytest.mark.asyncio
async def test_role_rename_uses_id_and_disabled_mapping_revokes_function(service_bundle):
    catalog = await _seed_identity_catalog(service_bundle)
    database = service_bundle["database"]
    service = service_bundle["rank_sync"]
    catalog["instructor"].name = "Nome visual alterado no Discord"
    role_ids = {
        catalog["rank_member"].id,
        catalog["member"].id,
        catalog["instructor"].id,
    }

    renamed = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        role_ids,
        None,
        source="DISCORD_ROLE_CHANGE",
    )
    await database.execute(
        """
        UPDATE discord_role_mappings
        SET enabled=0, updated_at=updated_at+1
        WHERE guild_id=? AND discord_role_id=? AND mapping_type='POSITION'
        """,
        (GUILD_ID, catalog["instructor"].id),
    )
    revoked = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        role_ids,
        None,
        source="MANUAL_RECONCILIATION",
    )

    assert "INSTRUCTOR" in renamed.position_codes
    assert renamed.access_profile == "INSTRUTOR"
    assert "INSTRUCTOR" not in revoked.position_codes
    assert revoked.access_profile == "MEMBRO"
    assert revoked.authorization_version == renamed.authorization_version + 1
