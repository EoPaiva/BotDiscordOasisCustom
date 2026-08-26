from __future__ import annotations

from types import SimpleNamespace

import pytest

from choque.audit import AuditService
from choque.config import Branding
from choque.database import Database
from choque.errors import ConflictError, ValidationError
from choque.members import MemberService
from choque.settings import SettingsService
from choque.special_units import SpecialUnitService
from choque.web_outbox import WebActionWorker

PRIMARY = 1146622062895579186
REC = 1541908574463070311
MEMBER = 655211515766505502
ACTOR = 326006642799804417


async def _bundle(tmp_path, *, rank_level: int = 1):
    database = Database(tmp_path / "special-units.db")
    await database.open()
    settings = SettingsService(database)
    audit = AuditService(database, settings, Branding())
    members = MemberService(database, audit)
    now = 1_700_000_000_000
    for level, name in ((1, "Recruta"), (2, "Soldado"), (3, "Cabo"), (5, "2º Sargento")):
        await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, active, created_at)
            VALUES (?, ?, '', ?, 1, ?)
            """,
            (PRIMARY, name, level, now),
        )
    rank = await database.fetchone(
        "SELECT id FROM ranks WHERE guild_id=? AND level=?", (PRIMARY, rank_level)
    )
    await members.create_or_update(
        PRIMARY,
        MEMBER,
        discord_nick=".gaspar33",
        mta_nick="Mecklove",
        character_id="4742",
        unit=None,
        rank_id=int(rank["id"]),
        actor_id=ACTOR,
    )
    await settings.set(REC, "identity_source_guild_id", PRIMARY, ACTOR)
    service = SpecialUnitService(database, settings, audit, clock=lambda: now)
    return database, settings, service


@pytest.mark.asyncio
async def test_approval_creates_membership_promotes_floor_and_queues_both_guilds(tmp_path):
    database, _, service = await _bundle(tmp_path, rank_level=1)
    for guild_id, base in ((PRIMARY, 100), (REC, 200)):
        await database.execute(
            """
            INSERT INTO special_unit_guild_resources(
                unit_code, guild_id, member_role_id, assistant_role_id,
                command_role_id, updated_at
            ) VALUES ('ROCAM', ?, ?, ?, ?, ?)
            """,
            (guild_id, base + 1, base + 2, base + 3, 1_700_000_000_000),
        )
    application = await service.submit_application(REC, MEMBER, "rocam")
    await service.assign(int(application["id"]), ACTOR, expected_version=1)
    decided = await service.decide(
        int(application["id"]),
        ACTOR,
        approved=True,
        reason="Aprovado pelo comando da unidade.",
        expected_version=2,
    )
    assert decided["status"] == "APPROVED"
    member = await database.fetchone(
        """
        SELECT m.unit, r.level FROM members m JOIN ranks r ON r.id=m.rank_id
        WHERE m.guild_id=? AND m.discord_id=?
        """,
        (PRIMARY, MEMBER),
    )
    assert dict(member) == {"unit": "ROCAM", "level": 3}
    membership = await database.fetchone(
        "SELECT * FROM special_unit_memberships WHERE member_id=? AND status='ACTIVE'",
        (application["member_id"],),
    )
    assert membership["unit_code"] == "ROCAM"
    assert membership["role_level"] == "MEMBER"
    actions = await database.fetchall(
        "SELECT guild_id, action_type, status FROM web_action_outbox ORDER BY id"
    )
    assert [(row["guild_id"], row["action_type"]) for row in actions] == [
        (PRIMARY, "RANK_SYNC"),
        (PRIMARY, "SPECIAL_UNIT_ROLE_SYNC"),
        (REC, "SPECIAL_UNIT_ROLE_SYNC"),
    ]
    notification = await database.fetchone(
        "SELECT notification_type, status FROM career_notifications WHERE target_discord_id=?",
        (MEMBER,),
    )
    assert dict(notification) == {"notification_type": "PROMOTION", "status": "PENDING"}
    await database.close()


@pytest.mark.asyncio
async def test_approval_never_demotes_higher_rank(tmp_path):
    database, _, service = await _bundle(tmp_path, rank_level=5)
    application = await service.submit_application(REC, MEMBER, "ELITE")
    await service.decide(
        int(application["id"]),
        ACTOR,
        approved=True,
        reason="Aprovado pelo comando da unidade.",
        expected_version=1,
    )
    row = await database.fetchone(
        """
        SELECT r.level FROM members m JOIN ranks r ON r.id=m.rank_id
        WHERE m.guild_id=? AND m.discord_id=?
        """,
        (PRIMARY, MEMBER),
    )
    assert row["level"] == 5
    assert await database.fetchone(
        "SELECT id FROM personnel_actions WHERE correlation_id LIKE 'special-unit-rank:%'"
    ) is None
    await database.close()


@pytest.mark.asyncio
async def test_only_active_canonical_member_can_apply_and_open_application_is_unique(tmp_path):
    database, _, service = await _bundle(tmp_path)
    await service.submit_application(REC, MEMBER, "TATICO")
    with pytest.raises(ConflictError, match="pendente"):
        await service.submit_application(REC, MEMBER, "ROCAM")
    with pytest.raises(ValidationError, match="membro ativo"):
        await service.submit_application(REC, 999, "ROCAM")
    await database.close()


@pytest.mark.asyncio
async def test_concurrent_decision_is_compare_and_set_and_self_review_is_blocked(tmp_path):
    database, _, service = await _bundle(tmp_path)
    application = await service.submit_application(REC, MEMBER, "CORREGEDORIA")
    with pytest.raises(ConflictError, match="própria"):
        await service.decide(
            int(application["id"]),
            MEMBER,
            approved=True,
            reason="Não permitido.",
            expected_version=1,
        )
    await service.decide(
        int(application["id"]),
        ACTOR,
        approved=False,
        reason="Requisitos ainda não atendidos.",
        expected_version=1,
    )
    with pytest.raises(ConflictError, match="já decidida"):
        await service.decide(
            int(application["id"]),
            ACTOR,
            approved=True,
            reason="Tentativa repetida.",
            expected_version=1,
        )
    assert not await database.fetchall("SELECT * FROM special_unit_memberships")
    await database.close()


@pytest.mark.asyncio
async def test_desired_roles_are_scoped_to_current_unit_and_level(tmp_path):
    database, _, service = await _bundle(tmp_path, rank_level=5)
    await database.execute(
        """
        INSERT INTO special_unit_guild_resources(
            unit_code, guild_id, member_role_id, assistant_role_id,
            command_role_id, updated_at
        ) VALUES
            ('ROCAM', ?, 101, 102, 103, 1),
            ('ELITE', ?, 201, 202, 203, 1)
        """,
        (PRIMARY, PRIMARY),
    )
    application = await service.submit_application(REC, MEMBER, "ELITE")
    await service.decide(
        int(application["id"]),
        ACTOR,
        approved=True,
        reason="Aprovado.",
        expected_version=1,
    )
    managed, desired = await service.desired_role_ids(PRIMARY, PRIMARY, MEMBER)
    assert managed == {101, 102, 103, 201, 202, 203}
    assert desired == {201}
    await database.close()


@pytest.mark.asyncio
async def test_command_level_is_hierarchical_and_leave_revokes_every_managed_role(tmp_path):
    database, _, service = await _bundle(tmp_path, rank_level=5)
    await service.upsert_guild_resource(
        "ROCAM",
        PRIMARY,
        category_id=10,
        central_channel_id=11,
        member_role_id=101,
        assistant_role_id=102,
        command_role_id=103,
    )
    application = await service.submit_application(REC, MEMBER, "ROCAM")
    await service.decide(
        int(application["id"]),
        ACTOR,
        approved=True,
        reason="Aprovado.",
        expected_version=1,
    )
    membership = await service.set_role_level(
        PRIMARY,
        "ROCAM",
        MEMBER,
        "COMMAND",
        actor_id=ACTOR,
        reason="Designação do comando.",
    )
    assert membership["role_level"] == "COMMAND"
    managed, desired = await service.desired_role_ids(PRIMARY, PRIMARY, MEMBER)
    assert managed == {101, 102, 103}
    assert desired == {101, 102, 103}

    await service.leave(
        PRIMARY,
        "ROCAM",
        MEMBER,
        actor_id=ACTOR,
        reason="Desligamento formal.",
    )
    _, desired_after = await service.desired_role_ids(PRIMARY, PRIMARY, MEMBER)
    assert desired_after == set()
    row = await database.fetchone(
        "SELECT status FROM special_unit_memberships WHERE member_id=?", (application["member_id"],)
    )
    assert row["status"] == "LEFT"
    await database.close()


@pytest.mark.asyncio
async def test_worker_converges_roles_without_touching_unmanaged_roles(tmp_path):
    database, settings, service = await _bundle(tmp_path, rank_level=5)
    await service.upsert_guild_resource(
        "ELITE",
        PRIMARY,
        category_id=10,
        central_channel_id=11,
        member_role_id=201,
        assistant_role_id=202,
        command_role_id=203,
    )
    application = await service.submit_application(REC, MEMBER, "ELITE")
    await service.decide(
        int(application["id"]),
        ACTOR,
        approved=True,
        reason="Aprovado.",
        expected_version=1,
    )

    class Role:
        def __init__(self, role_id: int) -> None:
            self.id = role_id

    class Guild:
        id = PRIMARY

        def __init__(self) -> None:
            self.roles = {role_id: Role(role_id) for role_id in (201, 202, 203, 999)}

        def get_role(self, role_id: int):
            return self.roles.get(role_id)

    class Member:
        id = MEMBER

        def __init__(self, guild: Guild) -> None:
            self.roles = [guild.roles[202], guild.roles[999]]

        async def remove_roles(self, *roles, reason: str, atomic: bool) -> None:
            removed = {role.id for role in roles}
            self.roles = [role for role in self.roles if role.id not in removed]

        async def add_roles(self, *roles, reason: str, atomic: bool) -> None:
            self.roles.extend(role for role in roles if role not in self.roles)

    guild = Guild()
    member = Member(guild)
    audit = AuditService(database, settings, Branding())
    worker = WebActionWorker(
        database,
        SimpleNamespace(),
        audit,
        SimpleNamespace(),
        special_units=service,
    )
    await worker._sync_special_unit_roles(  # noqa: SLF001
        {
            "id": 700,
            "guild_id": PRIMARY,
            "requested_by": ACTOR,
            "correlation_id": "test-special-unit-sync",
        },
        {"canonical_guild_id": PRIMARY},
        guild,
        member,
    )
    assert {role.id for role in member.roles} == {201, 999}
    await database.close()
