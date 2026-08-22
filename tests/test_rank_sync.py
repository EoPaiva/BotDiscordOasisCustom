from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import discord
import pytest

from choque.rank_sync import format_member_nickname
from cogs.member_sync import sync_member_status_roles
from cogs.rank_sync_system import RankSyncSystem

from .conftest import DISCORD_ID, GUILD_ID


@dataclass
class FakeRole:
    id: int
    name: str


class FakeGuild:
    def __init__(self, roles: list[FakeRole]) -> None:
        self.id = GUILD_ID
        self._roles = {role.id: role for role in roles}
        self._members: dict[int, FakeMember] = {}

    def get_role(self, role_id: int):
        return self._roles.get(role_id)

    def get_member(self, discord_id: int):
        return self._members.get(discord_id)

    async def fetch_member(self, discord_id: int):
        member = self.get_member(discord_id)
        if member is None:
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
        forbid_nickname: bool = False,
        ignored_nickname_edits: int = 0,
    ) -> None:
        self.guild = guild
        self.id = discord_id
        self.roles = list(roles)
        self.nick = nick
        self.bot = False
        self.forbid_nickname = forbid_nickname
        self.ignored_nickname_edits = ignored_nickname_edits
        self.nickname_edits = 0
        guild._members[discord_id] = self

    async def add_roles(self, *roles: FakeRole, reason: str) -> None:
        existing = {role.id for role in self.roles}
        self.roles.extend(role for role in roles if role.id not in existing)

    async def remove_roles(self, *roles: FakeRole, reason: str) -> None:
        removed = {role.id for role in roles}
        self.roles = [role for role in self.roles if role.id not in removed]

    async def edit(self, *, nick: str | None, reason: str) -> None:
        self.nickname_edits += 1
        if self.forbid_nickname:
            response = SimpleNamespace(status=403, reason="Forbidden")
            raise discord.Forbidden(response, "Sem permissão para apelido")
        if self.nickname_edits <= self.ignored_nickname_edits:
            return
        self.nick = nick

    def get_role(self, role_id: int):
        return next((role for role in self.roles if role.id == role_id), None)


class FakeBot:
    def __init__(self, services) -> None:
        self.services = services
        self.check_mode = False
        self.guilds: list[FakeGuild] = []

    def get_cog(self, name: str):
        return None


async def seed_ranks(service_bundle, *, current_level: int = 1):
    database = service_bundle["database"]
    ranks: dict[int, FakeRole] = {}
    rank_ids: dict[int, int] = {}
    for level, (name, prefix) in enumerate(
        (("Recruta", "[REC]"), ("Soldado", "[SD]"), ("Cabo", "[CB]")), start=1
    ):
        role = FakeRole(9_000 + level, name)
        ranks[level] = role
        await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, discord_role_id, created_at)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (GUILD_ID, name, prefix, level, role.id),
        )
        row = await database.fetchone(
            "SELECT id FROM ranks WHERE guild_id=? AND level=?", (GUILD_ID, level)
        )
        rank_ids[level] = int(row["id"])
    await database.execute(
        """
        UPDATE members SET rank_id=?, rank_sync_status='SYNCED'
        WHERE guild_id=? AND discord_id=?
        """,
        (rank_ids[current_level], GUILD_ID, DISCORD_ID),
    )
    return ranks, rank_ids


async def rank_level(service_bundle) -> int | None:
    row = await service_bundle["database"].fetchone(
        """
        SELECT r.level FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
        WHERE m.guild_id=? AND m.discord_id=?
        """,
        (GUILD_ID, DISCORD_ID),
    )
    return int(row["level"]) if row["level"] is not None else None


@pytest.mark.asyncio
async def test_dismissal_restores_nickname_captured_before_first_managed_sync(service_bundle):
    ranks, _ = await seed_ranks(service_bundle)
    dismissed_role = FakeRole(9_100, "Exonerado")
    guild = FakeGuild([*ranks.values(), dismissed_role])
    member = FakeMember(
        guild,
        DISCORD_ID,
        [ranks[1]],
        nick="Apelido anterior",
    )

    synced = await service_bundle["rank_sync"].sync_to_member(
        member,
        source="REGISTRATION_APPROVED",
        actor_id=999,
    )
    assert synced.warning is None
    assert member.nick == "[REC] Choque_User [77]"
    stored = await service_bundle["database"].fetchone(
        """
        SELECT original_discord_nickname, original_nickname_captured
        FROM members WHERE guild_id=? AND discord_id=?
        """,
        (GUILD_ID, DISCORD_ID),
    )
    assert bool(stored["original_nickname_captured"])
    assert stored["original_discord_nickname"] == "Apelido anterior"

    await service_bundle["database"].execute(
        "UPDATE members SET status='DISMISSED' WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    await service_bundle["settings"].set(
        GUILD_ID,
        "dismissed_role_id",
        dismissed_role.id,
        999,
    )
    bot = SimpleNamespace(services=SimpleNamespace(**service_bundle))
    warning = await sync_member_status_roles(bot, guild, member, "DISMISSED")
    assert warning is None
    assert member.nick == "Apelido anterior"
    assert member.get_role(dismissed_role.id) is dismissed_role
    assert member.get_role(ranks[1].id) is None
    audit = await service_bundle["database"].fetchone(
        """
        SELECT id FROM audit_logs
        WHERE guild_id=? AND target_id=? AND action='MEMBER_NICKNAME_RESTORED'
        """,
        (GUILD_ID, DISCORD_ID),
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_dismissal_strips_rank_and_id_when_legacy_original_is_managed(service_bundle):
    ranks, _ = await seed_ranks(service_bundle)
    dismissed_role = FakeRole(9_100, "Exonerado")
    guild = FakeGuild([*ranks.values(), dismissed_role])
    member = FakeMember(
        guild,
        DISCORD_ID,
        [ranks[1]],
        nick="[REC] Choque_User [77]",
    )
    await service_bundle["database"].execute(
        """
        UPDATE members
        SET status='DISMISSED', original_discord_nickname=?, original_nickname_captured=1
        WHERE guild_id=? AND discord_id=?
        """,
        ("[REC] Choque_User [77]", GUILD_ID, DISCORD_ID),
    )
    await service_bundle["settings"].set(
        GUILD_ID,
        "dismissed_role_id",
        dismissed_role.id,
        999,
    )
    bot = SimpleNamespace(services=SimpleNamespace(**service_bundle))

    warning = await sync_member_status_roles(bot, guild, member, "DISMISSED")

    assert warning is None
    assert member.nick == "Choque_User"
    edits_after_restoration = member.nickname_edits
    await service_bundle["rank_sync"].sync_from_member(
        member,
        source="DISCORD_ROLE_CHANGE",
    )
    assert member.nick == "Choque_User"
    assert member.nickname_edits == edits_after_restoration
    stored = await service_bundle["database"].fetchone(
        """
        SELECT original_discord_nickname FROM members
        WHERE guild_id=? AND discord_id=?
        """,
        (GUILD_ID, DISCORD_ID),
    )
    assert stored["original_discord_nickname"] == "Choque_User"
    audit = await service_bundle["database"].fetchone(
        """
        SELECT after_json FROM audit_logs
        WHERE guild_id=? AND target_id=? AND action='MEMBER_NICKNAME_RESTORED'
        ORDER BY id DESC LIMIT 1
        """,
        (GUILD_ID, DISCORD_ID),
    )
    assert "LEGACY_MANAGED_NICKNAME_FALLBACK" in audit["after_json"]


@pytest.mark.asyncio
async def test_dismissal_retries_when_discord_does_not_persist_first_nickname_edit(service_bundle):
    ranks, _ = await seed_ranks(service_bundle)
    dismissed_role = FakeRole(9_100, "Exonerado")
    guild = FakeGuild([*ranks.values(), dismissed_role])
    member = FakeMember(
        guild,
        DISCORD_ID,
        [ranks[1]],
        nick="[REC] Choque_User [77]",
        ignored_nickname_edits=1,
    )
    await service_bundle["database"].execute(
        """
        UPDATE members
        SET status='DISMISSED', original_discord_nickname=?, original_nickname_captured=1
        WHERE guild_id=? AND discord_id=?
        """,
        ("[REC] Choque_User [77]", GUILD_ID, DISCORD_ID),
    )
    await service_bundle["settings"].set(
        GUILD_ID,
        "dismissed_role_id",
        dismissed_role.id,
        999,
    )
    bot = SimpleNamespace(services=SimpleNamespace(**service_bundle))

    warning = await sync_member_status_roles(bot, guild, member, "DISMISSED")

    assert warning is None
    assert member.nick == "Choque_User"
    assert member.nickname_edits == 2


def test_official_nickname_formatter_uses_brackets_and_preserves_id() -> None:
    assert format_member_nickname("[SD]", "Choque_User", "77") == "[SD] Choque_User [77]"
    long_nickname = format_member_nickname(
        "[ABREVIACAO-MUITO-LONGA]", "Nome Muito Longo Para Discord", "12345678901234567890"
    )
    assert len(long_nickname) <= 32
    assert long_nickname.startswith("[") and long_nickname.endswith("]")


@pytest.mark.asyncio
async def test_companion_role_uses_comp_f_nickname_without_becoming_rank(service_bundle):
    service = service_bundle["rank_sync"]
    settings = service_bundle["settings"]
    ranks, _ = await seed_ranks(service_bundle, current_level=2)
    companion = FakeRole(77_777, "Companheiro de Farda")
    guild = FakeGuild([*ranks.values(), companion])
    member = FakeMember(guild, DISCORD_ID, [ranks[2], companion], nick="manual")
    await settings.set(GUILD_ID, "companion_role_id", companion.id, DISCORD_ID)

    result = await service.sync_from_member(member, source="DISCORD_ROLE_CHANGE")

    assert result.rank_name == "Soldado"
    assert result.expected_nickname == "[COMP.F] Choque_User [77]"
    assert member.nick == "[COMP.F] Choque_User [77]"
    assert companion.id in await service.relevant_role_ids(GUILD_ID)


@pytest.mark.asyncio
async def test_01_recruit_to_soldier_updates_database_nickname_and_history(service_bundle):
    ranks, _ = await seed_ranks(service_bundle, current_level=1)
    service = service_bundle["rank_sync"]
    result = await service.sync_from_discord(
        GUILD_ID,
        DISCORD_ID,
        {ranks[2].id},
        "apelido antigo",
        source="DISCORD_MEMBER_UPDATE",
    )
    assert await rank_level(service_bundle) == 2
    assert result.expected_nickname == "[SD] Choque_User [77]"
    event = await service_bundle["database"].fetchone(
        "SELECT event_type, actor_id FROM rank_sync_events ORDER BY id DESC"
    )
    assert (event["event_type"], event["actor_id"]) == ("PROMOTION", None)
    history = await service_bundle["personnel"].career_history(GUILD_ID, DISCORD_ID)
    assert history[0]["source"] == "DISCORD_MEMBER_UPDATE"
    assert history[0]["to_rank_name"] == "Soldado"


@pytest.mark.asyncio
async def test_02_soldier_to_corporal_is_a_promotion(service_bundle):
    ranks, _ = await seed_ranks(service_bundle, current_level=2)
    await service_bundle["rank_sync"].sync_from_discord(
        GUILD_ID, DISCORD_ID, {ranks[3].id}, None, source="DISCORD_MEMBER_UPDATE"
    )
    assert await rank_level(service_bundle) == 3
    event = await service_bundle["database"].fetchone(
        "SELECT event_type FROM rank_sync_events ORDER BY id DESC"
    )
    assert event["event_type"] == "PROMOTION"


@pytest.mark.asyncio
async def test_03_corporal_to_soldier_is_a_demotion(service_bundle):
    ranks, _ = await seed_ranks(service_bundle, current_level=3)
    await service_bundle["rank_sync"].sync_from_discord(
        GUILD_ID, DISCORD_ID, {ranks[2].id}, None, source="DISCORD_MEMBER_UPDATE"
    )
    assert await rank_level(service_bundle) == 2
    event = await service_bundle["database"].fetchone(
        "SELECT event_type FROM rank_sync_events ORDER BY id DESC"
    )
    assert event["event_type"] == "DEMOTION"


@pytest.mark.asyncio
async def test_04_unrelated_role_change_is_ignored(service_bundle):
    ranks, _ = await seed_ranks(service_bundle)
    service = service_bundle["rank_sync"]
    assert not await service.role_change_is_relevant(GUILD_ID, {ranks[1].id, 51}, {ranks[1].id, 52})
    assert await service_bundle["database"].fetchone("SELECT 1 FROM rank_sync_events") is None


@pytest.mark.asyncio
async def test_05_multiple_rank_roles_choose_highest_audit_and_optional_cleanup(service_bundle):
    ranks, _ = await seed_ranks(service_bundle, current_level=1)
    await service_bundle["settings"].set(GUILD_ID, "auto_remove_old_rank_roles", True, DISCORD_ID)
    guild = FakeGuild(list(ranks.values()))
    member = FakeMember(guild, DISCORD_ID, [ranks[1], ranks[3]], nick="manual")
    result = await service_bundle["rank_sync"].sync_from_member(
        member, source="DISCORD_MEMBER_UPDATE"
    )
    assert await rank_level(service_bundle) == 3
    assert result.sync_status == "MULTIPLE_RANKS"
    assert {role.id for role in member.roles} == {ranks[3].id}
    audit = await service_bundle["database"].fetchone(
        "SELECT action FROM audit_logs WHERE action='RANK_ROLE_INCONSISTENCY'"
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_06_missing_rank_role_keeps_last_rank_and_does_not_duplicate_history(service_bundle):
    _, _ = await seed_ranks(service_bundle, current_level=2)
    service = service_bundle["rank_sync"]
    await service.sync_from_discord(
        GUILD_ID, DISCORD_ID, set(), None, source="DISCORD_MEMBER_UPDATE"
    )
    await service.sync_from_discord(
        GUILD_ID, DISCORD_ID, set(), None, source="DISCORD_MEMBER_UPDATE"
    )
    assert await rank_level(service_bundle) == 2
    member = await service_bundle["database"].fetchone(
        "SELECT rank_sync_status FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    count = await service_bundle["database"].fetchone(
        "SELECT COUNT(*) AS total FROM rank_sync_events"
    )
    assert member["rank_sync_status"] == "MISSING_ROLE"
    assert count["total"] == 1


@pytest.mark.asyncio
async def test_07_manual_nickname_is_restored_when_enforcement_is_enabled(service_bundle):
    ranks, _ = await seed_ranks(service_bundle, current_level=2)
    guild = FakeGuild(list(ranks.values()))
    member = FakeMember(guild, DISCORD_ID, [ranks[2]], nick="apelido manual")
    await service_bundle["rank_sync"].sync_from_member(member, source="DISCORD_MEMBER_UPDATE")
    assert member.nick == "[SD] Choque_User [77]"
    assert member.nickname_edits == 1


@pytest.mark.asyncio
async def test_08_startup_reconciliation_uses_discord_as_truth(service_bundle):
    ranks, _ = await seed_ranks(service_bundle, current_level=1)
    guild = FakeGuild(list(ranks.values()))
    FakeMember(guild, DISCORD_ID, [ranks[3]], nick="antigo")
    bot = FakeBot(SimpleNamespace(**service_bundle))
    cog = RankSyncSystem(bot)
    checked, changed = await cog.reconcile_guild(guild)
    assert (checked, changed) == (1, 1)
    assert await rank_level(service_bundle) == 3


@pytest.mark.asyncio
async def test_09_bot_generated_role_update_is_idempotent_without_duplicate_history(service_bundle):
    ranks, _ = await seed_ranks(service_bundle, current_level=1)
    guild = FakeGuild(list(ranks.values()))
    member = FakeMember(guild, DISCORD_ID, [ranks[2]], nick="manual")
    service = service_bundle["rank_sync"]
    await service.sync_from_member(member, source="DISCORD_MEMBER_UPDATE")
    await service.sync_from_member(member, source="DISCORD_MEMBER_UPDATE")
    count = await service_bundle["database"].fetchone(
        "SELECT COUNT(*) AS total FROM rank_sync_events"
    )
    assert count["total"] == 1
    assert service.active_lock_count == 0


@pytest.mark.asyncio
async def test_10_rapid_role_updates_are_debounced_to_one_final_history(service_bundle):
    ranks, _ = await seed_ranks(service_bundle, current_level=1)
    await service_bundle["settings"].set(GUILD_ID, "rank_sync_debounce_seconds", 0.03, DISCORD_ID)
    guild = FakeGuild(list(ranks.values()))
    member = FakeMember(guild, DISCORD_ID, [ranks[2]], nick="manual")
    bot = FakeBot(SimpleNamespace(**service_bundle))
    cog = RankSyncSystem(bot)
    await cog._schedule(member)
    member.roles = [ranks[3]]
    await cog._schedule(member)
    await asyncio.sleep(0.1)
    count = await service_bundle["database"].fetchone(
        "SELECT COUNT(*) AS total FROM rank_sync_events"
    )
    assert count["total"] == 1
    assert await rank_level(service_bundle) == 3
    assert cog.pending_count == 0


@pytest.mark.asyncio
async def test_11_nickname_permission_failure_is_audited_without_rolling_back_database(
    service_bundle,
):
    ranks, _ = await seed_ranks(service_bundle, current_level=1)
    guild = FakeGuild(list(ranks.values()))
    member = FakeMember(
        guild,
        DISCORD_ID,
        [ranks[2]],
        nick="manual",
        forbid_nickname=True,
    )
    result = await service_bundle["rank_sync"].sync_from_member(
        member, source="DISCORD_MEMBER_UPDATE"
    )
    assert await rank_level(service_bundle) == 2
    assert result.warning and "apelido" in result.warning
    audit = await service_bundle["database"].fetchone(
        "SELECT action FROM audit_logs WHERE action='NICKNAME_PERMISSION_ERROR'"
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_12_unregistered_discord_member_is_ignored(service_bundle):
    ranks, _ = await seed_ranks(service_bundle)
    guild = FakeGuild(list(ranks.values()))
    member = FakeMember(guild, 999_999, [ranks[3]], nick="livre")
    result = await service_bundle["rank_sync"].sync_from_member(
        member, source="DISCORD_MEMBER_UPDATE"
    )
    assert not result.registered
    assert member.nick == "livre"
    assert member.nickname_edits == 0


@pytest.mark.asyncio
async def test_registration_initial_rank_prefers_existing_discord_rank(service_bundle):
    ranks, rank_ids = await seed_ranks(service_bundle)
    selected = await service_bundle["rank_sync"].initial_rank_id(
        GUILD_ID, {ranks[2].id, ranks[3].id}
    )
    assert selected == rank_ids[3]
