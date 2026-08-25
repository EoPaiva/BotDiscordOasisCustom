from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from choque.errors import ConflictError, PermissionDenied, ValidationError
from choque.models import RbacProfile
from choque.rbac import PROFILE_PERMISSIONS
from choque.services import Services
from choque.settings import SettingsService
from choque.tags import TagService
from choque.web_outbox import WebActionWorker
from cogs.tag_commands import TagCommands, require_request_member
from command_center.services import CommandCenterServices

from .conftest import DISCORD_ID, GUILD_ID


class _TagRole:
    def __init__(self, role_id: int) -> None:
        self.id = role_id
        self.name = f"Role {role_id}"


class _TagMember:
    def __init__(self, discord_id: int) -> None:
        self.id = discord_id
        self.roles: list[_TagRole] = []

    async def add_roles(self, role: _TagRole, *, reason: str) -> None:
        del reason
        if not any(item.id == role.id for item in self.roles):
            self.roles.append(role)

    async def remove_roles(self, role: _TagRole, *, reason: str) -> None:
        del reason
        self.roles = [item for item in self.roles if item.id != role.id]


class _TagGuild:
    def __init__(self, member: _TagMember, roles: list[_TagRole]) -> None:
        self.id = GUILD_ID
        self._member = member
        self._roles = roles

    def get_member(self, discord_id: int) -> _TagMember | None:
        return self._member if discord_id == self._member.id else None

    async def fetch_member(self, discord_id: int) -> _TagMember:
        assert discord_id == self._member.id
        return self._member

    def get_role(self, role_id: int) -> _TagRole | None:
        return next((role for role in self._roles if role.id == role_id), None)

    async def fetch_roles(self) -> list[_TagRole]:
        return self._roles


class _TagBot:
    def __init__(self, guild: _TagGuild) -> None:
        self.guild = guild

    def get_guild(self, guild_id: int) -> _TagGuild | None:
        return self.guild if guild_id == self.guild.id else None


class _PanelMessage:
    def __init__(self, message_id: int) -> None:
        self.id = message_id
        self.edits: list[dict[str, object]] = []

    async def edit(self, **kwargs: object) -> None:
        self.edits.append(kwargs)


class _PanelChannel:
    def __init__(self, channel_id: int, *, existing: _PanelMessage | None = None) -> None:
        self.id = channel_id
        self.existing = existing
        self.sent: list[_PanelMessage] = []

    async def fetch_message(self, message_id: int) -> _PanelMessage:
        assert self.existing is not None and message_id == self.existing.id
        return self.existing

    async def send(self, **_: object) -> _PanelMessage:
        message = _PanelMessage(900 + len(self.sent))
        self.sent.append(message)
        return message


class _PanelGuild:
    def __init__(self, *channels: _PanelChannel) -> None:
        self.id = GUILD_ID
        self._channels = {channel.id: channel for channel in channels}

    def get_channel(self, channel_id: int) -> _PanelChannel | None:
        return self._channels.get(channel_id)


def test_runtime_service_bundles_expose_the_single_tag_service() -> None:
    assert "tags" in Services.__annotations__
    assert "tags" in CommandCenterServices.__annotations__


def test_tag_permissions_follow_existing_profile_rbac_not_button_visibility() -> None:
    member_permissions = PROFILE_PERMISSIONS[RbacProfile.MEMBER.value]
    command_permissions = PROFILE_PERMISSIONS[RbacProfile.COMMAND.value]
    high_command_permissions = PROFILE_PERMISSIONS[RbacProfile.HIGH_COMMAND.value]

    assert {"tag.request", "tag.view.self", "tag.confirm.self", "tag.report_missing"} <= member_permissions
    assert {"tag.queue.view", "tag.claim", "tag.release", "tag.set", "tag.call"} <= command_permissions
    assert {"tag.identity.correct", "tag.reject", "tag.cancel", "tag.history.view", "tag.settings"} <= high_command_permissions


def test_tag_role_and_panel_settings_have_safe_unconfigured_defaults() -> None:
    assert SettingsService.DEFAULTS["tag_member_panel_channel_id"] is None
    assert SettingsService.DEFAULTS["tag_admin_panel_channel_id"] is None
    assert SettingsService.DEFAULTS["tag_waiting_role_id"] is None
    assert SettingsService.DEFAULTS["tag_set_role_id"] is None
    assert SettingsService.DEFAULTS["tag_responsible_role_id"] is None
    assert SettingsService.DEFAULTS["tag_expiration_hours"] == 72


@pytest.mark.asyncio
async def test_member_tag_request_requires_both_role_ids_to_be_configured(service_bundle):
    cog = object.__new__(TagCommands)
    cog.services = SimpleNamespace(settings=service_bundle["settings"])
    guild = SimpleNamespace(id=GUILD_ID)

    with pytest.raises(ValidationError, match="AGUARDANDO SET"):
        await cog.require_member_request_configuration(guild)

    await service_bundle["settings"].set(GUILD_ID, "tag_waiting_role_id", 101, DISCORD_ID)
    await service_bundle["settings"].set(GUILD_ID, "tag_set_role_id", 202, DISCORD_ID)

    await cog.require_member_request_configuration(guild)


@pytest.mark.asyncio
async def test_moving_member_panel_retires_the_previous_interactive_message(monkeypatch) -> None:
    """Changing the configured channel must not leave two functional panels."""
    import cogs.tag_commands as tag_commands

    old_message = _PanelMessage(41)
    old_channel = _PanelChannel(11, existing=old_message)
    new_channel = _PanelChannel(22)
    guild = _PanelGuild(old_channel, new_channel)
    cog = object.__new__(TagCommands)
    cog.bot = SimpleNamespace(config=SimpleNamespace(branding=SimpleNamespace()))
    cog.services = SimpleNamespace(
        settings=SimpleNamespace(
            get_panel=AsyncMock(return_value={"channel_id": 11, "message_id": 41}),
            upsert_panel=AsyncMock(),
        )
    )
    monkeypatch.setattr(tag_commands.discord, "TextChannel", _PanelChannel)
    monkeypatch.setattr(tag_commands, "build_member_panel_embed", AsyncMock(return_value=object()))

    await cog.publish_or_refresh_member_panel(guild, new_channel)

    assert old_message.edits == [{"view": None}]
    assert len(new_channel.sent) == 1
    cog.services.settings.upsert_panel.assert_awaited_once_with(
        GUILD_ID, "TAG_MEMBER", 22, new_channel.sent[0].id
    )


@pytest.mark.asyncio
async def test_confirmation_view_is_registered_immediately_and_only_once_per_request_version() -> None:
    """A freshly sent confirmation DM must work before the retry loop runs."""
    cog = object.__new__(TagCommands)
    cog.bot = SimpleNamespace(add_view=Mock())
    cog._registered_confirmation_views = set()
    request = {"id": 42, "version": 3, "status": "AGUARDANDO_CONFIRMACAO"}

    cog.register_confirmation_view(request)
    cog.register_confirmation_view(request)

    cog.bot.add_view.assert_called_once()
    view = cog.bot.add_view.call_args.args[0]
    assert view.request_id == 42
    assert view.version == 3


@pytest.mark.asyncio
async def test_request_tag_snapshots_registered_identity_and_is_idempotent(service_bundle):
    """One active tag request must represent the member, not each button click."""
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )

    first = await service.request_tag(GUILD_ID, DISCORD_ID)
    repeated = await service.request_tag(GUILD_ID, DISCORD_ID)

    assert repeated["id"] == first["id"]
    assert first["status"] == "AGUARDANDO_SET"
    assert first["mta_nick_snapshot"] == "Choque_User"
    assert first["character_id_snapshot"] == "77"
    assert repeated["queue_position"] == 1

    row = await service_bundle["database"].fetchone(
        "SELECT COUNT(*) AS total FROM tag_requests WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    events = await service_bundle["database"].fetchone(
        """
        SELECT COUNT(*) AS total FROM tag_request_events
        WHERE tag_request_id=? AND event_type='TAG_REQUEST_CREATED'
        """,
        (first["id"],),
    )
    assert int(row["total"]) == 1
    assert int(events["total"]) == 1


@pytest.mark.asyncio
async def test_existing_tag_declaration_requires_responsible_validation(service_bundle):
    """A member claim is queued for review and must never self-grant TAG SETADA."""
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )

    created = await service.request_tag(GUILD_ID, DISCORD_ID, existing_tag=True)
    repeated = await service.request_tag(GUILD_ID, DISCORD_ID, existing_tag=True)

    assert repeated["id"] == created["id"]
    assert created["status"] == "PENDENCIA"
    assert created["request_origin"] == "EXISTING_DECLARATION"
    assert created["responsible_notification_status"] == "PENDING"

    member = await service_bundle["database"].fetchone(
        "SELECT tag_status, tag_completed_at FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert tuple(member) == ("PENDENCIA", None)

    event = await service_bundle["database"].fetchone(
        """
        SELECT event_type, next_status FROM tag_request_events
        WHERE tag_request_id=? ORDER BY id LIMIT 1
        """,
        (created["id"],),
    )
    assert tuple(event) == ("TAG_EXISTING_DECLARED", "PENDENCIA")


@pytest.mark.asyncio
async def test_existing_tag_declaration_does_not_grant_the_waiting_or_set_role(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    await service_bundle["settings"].set(GUILD_ID, "tag_waiting_role_id", 101, DISCORD_ID)
    await service_bundle["settings"].set(GUILD_ID, "tag_set_role_id", 202, DISCORD_ID)
    member = _TagMember(DISCORD_ID)
    worker = WebActionWorker(
        service_bundle["database"],
        SimpleNamespace(),
        service_bundle["audit"],
        _TagBot(_TagGuild(member, [_TagRole(101), _TagRole(202)])),
        tags=service,
    )

    await service.request_tag(GUILD_ID, DISCORD_ID, existing_tag=True)

    assert await worker.process_pending() == 1
    assert member.roles == []


@pytest.mark.asyncio
async def test_releasing_existing_tag_validation_returns_to_the_validation_queue(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID, existing_tag=True)
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )

    released = await service.release_request(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        reason="Troca de responsável.",
    )

    assert released["status"] == "PENDENCIA"


@pytest.mark.asyncio
async def test_dm_confirmation_resolves_the_request_owner_from_the_guild() -> None:
    """Persistent confirmation controls must remain usable inside a member DM."""
    member = _TagMember(DISCORD_ID)
    guild = _TagGuild(member, [])
    member.guild = guild
    permissions = SimpleNamespace(has=AsyncMock(return_value=True))
    bot = SimpleNamespace(
        services=SimpleNamespace(
            tags=SimpleNamespace(
                get_request=AsyncMock(
                    return_value={"id": 42, "guild_id": GUILD_ID, "discord_id": DISCORD_ID}
                )
            ),
            permissions=permissions,
        ),
        get_guild=Mock(return_value=guild),
    )
    interaction = SimpleNamespace(
        guild=None,
        user=SimpleNamespace(id=DISCORD_ID),
        client=bot,
    )

    resolved = await require_request_member(interaction, 42, "tag.confirm.self")

    assert resolved is member
    permissions.has.assert_awaited_once_with(member, "tag.confirm.self")


@pytest.mark.asyncio
async def test_dm_confirmation_rejects_a_different_request_owner() -> None:
    bot = SimpleNamespace(
        services=SimpleNamespace(
            tags=SimpleNamespace(
                get_request=AsyncMock(
                    return_value={"id": 42, "guild_id": GUILD_ID, "discord_id": DISCORD_ID}
                )
            ),
            permissions=SimpleNamespace(has=AsyncMock()),
        ),
        get_guild=Mock(),
    )
    interaction = SimpleNamespace(
        guild=None,
        user=SimpleNamespace(id=999),
        client=bot,
    )

    with pytest.raises(PermissionDenied):
        await require_request_member(interaction, 42, "tag.confirm.self")

    bot.get_guild.assert_not_called()


@pytest.mark.asyncio
async def test_only_one_responsible_can_claim_the_same_tag_request(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)

    first, second = await asyncio.gather(
        service.claim_request(int(request["id"]), responsible_id=701, expected_version=1),
        service.claim_request(int(request["id"]), responsible_id=702, expected_version=1),
        return_exceptions=True,
    )

    successful = next(result for result in (first, second) if not isinstance(result, Exception))
    rejected = next(result for result in (first, second) if isinstance(result, Exception))
    assert successful["status"] == "ATENDIMENTO_ASSUMIDO"
    assert successful["claimed_by"] in {701, 702}
    assert successful["version"] == 2
    assert isinstance(rejected, ConflictError)
    assert "alterada" in str(rejected)

    events = await service_bundle["database"].fetchone(
        """
        SELECT COUNT(*) AS total FROM tag_request_events
        WHERE tag_request_id=? AND event_type='TAG_REQUEST_CLAIMED'
        """,
        (request["id"],),
    )
    assert int(events["total"]) == 1


@pytest.mark.asyncio
async def test_set_then_member_confirmation_completes_once_and_preserves_timeline(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )

    awaiting_confirmation = await service.mark_set_performed(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        set_character_id="77",
    )
    completed = await service.confirm_tag(
        int(request["id"]),
        discord_id=DISCORD_ID,
        expected_version=int(awaiting_confirmation["version"]),
    )
    repeated = await service.confirm_tag(
        int(request["id"]),
        discord_id=DISCORD_ID,
        expected_version=int(awaiting_confirmation["version"]),
    )

    assert awaiting_confirmation["status"] == "AGUARDANDO_CONFIRMACAO"
    assert awaiting_confirmation["set_by"] == 701
    assert completed["status"] == "CONCLUIDO"
    assert completed["confirmed_by"] == DISCORD_ID
    assert repeated["id"] == completed["id"]
    assert repeated["version"] == completed["version"]

    member_projection = await service_bundle["database"].fetchone(
        """
        SELECT tag_status, tag_completed_at, tag_set_by, tag_last_confirmed_at
        FROM members WHERE guild_id=? AND discord_id=?
        """,
        (GUILD_ID, DISCORD_ID),
    )
    assert tuple(member_projection) == ("CONCLUIDO", completed["confirmed_at"], 701, completed["confirmed_at"])

    events = await service_bundle["database"].fetchall(
        """
        SELECT event_type FROM tag_request_events
        WHERE tag_request_id=? ORDER BY id
        """,
        (request["id"],),
    )
    assert [str(event["event_type"]) for event in events] == [
        "TAG_REQUEST_CREATED",
        "TAG_REQUEST_CLAIMED",
        "TAG_SET_PERFORMED",
        "TAG_CONFIRMED",
    ]


@pytest.mark.asyncio
async def test_only_request_owner_can_report_missing_tag_and_it_returns_to_pendency(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    assert await service.claim_responsible_notification(int(request["id"])) is not None
    await service.mark_responsible_notification_delivered(
        int(request["id"]), delivery_message_id=7001
    )
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )
    awaiting_confirmation = await service.mark_set_performed(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        set_character_id="77",
    )

    with pytest.raises(PermissionDenied):
        await service.report_tag_not_received(
            int(request["id"]),
            discord_id=999,
            expected_version=int(awaiting_confirmation["version"]),
            reason="Não localizei a tag no personagem.",
        )
    pending = await service.report_tag_not_received(
        int(request["id"]),
        discord_id=DISCORD_ID,
        expected_version=int(awaiting_confirmation["version"]),
        reason="Não localizei a tag no personagem.",
    )

    assert pending["status"] == "PENDENCIA"
    assert pending["terminal_at"] is None
    assert pending["responsible_notification_status"] == "DELIVERED"
    assert pending["responsible_notification_message_id"] == 7001
    queued_alerts = await service.pending_responsible_notifications(GUILD_ID)
    assert queued_alerts == []
    event = await service_bundle["database"].fetchone(
        """
        SELECT reason, previous_status, next_status FROM tag_request_events
        WHERE tag_request_id=? AND event_type='TAG_NOT_RECEIVED'
        """,
        (request["id"],),
    )
    assert event["reason"] == "Não localizei a tag no personagem."
    assert (event["previous_status"], event["next_status"]) == (
        "AGUARDANDO_CONFIRMACAO",
        "PENDENCIA",
    )


@pytest.mark.asyncio
async def test_tag_transition_enqueues_versioned_role_sync_without_waiting_for_discord(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )

    request = await service.request_tag(GUILD_ID, DISCORD_ID)

    queued = await service_bundle["database"].fetchone(
        """
        SELECT action_type, target_discord_id, payload_json, requested_by, status
        FROM web_action_outbox
        WHERE action_type='TAG_ROLE_SYNC'
        """
    )
    assert queued is not None
    assert queued["target_discord_id"] == DISCORD_ID
    assert queued["requested_by"] == DISCORD_ID
    assert queued["status"] == "PENDING"
    assert json.loads(queued["payload_json"]) == {
        "request_id": request["id"],
        "request_version": request["version"],
    }


@pytest.mark.asyncio
async def test_responsible_can_release_request_without_erasing_assignment_history(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )

    released = await service.release_request(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        reason="Fim do turno; outro responsável continuará.",
    )
    reclaimed = await service.claim_request(
        int(request["id"]), responsible_id=702, expected_version=int(released["version"])
    )

    assert released["status"] == "AGUARDANDO_SET"
    assert released["claimed_by"] is None
    assert reclaimed["claimed_by"] == 702
    history = await service_bundle["database"].fetchone(
        """
        SELECT actor_id, reason, previous_status, next_status
        FROM tag_request_events
        WHERE tag_request_id=? AND event_type='TAG_REQUEST_RELEASED'
        """,
        (request["id"],),
    )
    assert history["actor_id"] == 701
    assert history["reason"] == "Fim do turno; outro responsável continuará."
    assert (history["previous_status"], history["next_status"]) == (
        "ATENDIMENTO_ASSUMIDO",
        "AGUARDANDO_SET",
    )


@pytest.mark.asyncio
async def test_waiting_queue_is_oldest_first_and_excludes_claimed_requests(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    members = service_bundle["members"]
    await members.create_or_update(
        GUILD_ID,
        457,
        discord_nick="Second User",
        mta_nick="Second_User",
        character_id="78",
        unit="BGR",
        rank_id=None,
        actor_id=457,
    )
    first = await service.request_tag(GUILD_ID, DISCORD_ID)
    service_bundle["clock"].advance(1_000)
    second = await service.request_tag(GUILD_ID, 457)
    await service.claim_request(
        int(first["id"]), responsible_id=701, expected_version=int(first["version"])
    )

    queue = await service.waiting_queue(GUILD_ID)

    assert len(queue) == 1
    assert queue[0]["id"] == second["id"]
    assert queue[0]["queue_position"] == 1
    assert queue[0]["waiting_ms"] == 0


@pytest.mark.asyncio
async def test_tag_request_pages_keep_oldest_queue_entries_and_total_count(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    members = service_bundle["members"]
    for discord_id, nick, character_id in (
        (457, "Second User", "78"),
        (458, "Third User", "79"),
    ):
        await members.create_or_update(
            GUILD_ID,
            discord_id,
            discord_nick=nick,
            mta_nick=nick.replace(" ", "_"),
            character_id=character_id,
            unit="BGR",
            rank_id=None,
            actor_id=discord_id,
        )

    first = await service.request_tag(GUILD_ID, DISCORD_ID)
    service_bundle["clock"].advance(1)
    second = await service.request_tag(GUILD_ID, 457)
    service_bundle["clock"].advance(1)
    third = await service.request_tag(GUILD_ID, 458)

    first_page, total = await service.request_page(
        GUILD_ID, statuses=("AGUARDANDO_SET",), page=0, page_size=2
    )
    second_page, repeated_total = await service.request_page(
        GUILD_ID, statuses=("AGUARDANDO_SET",), page=1, page_size=2
    )

    assert total == repeated_total == 3
    assert [row["id"] for row in first_page] == [first["id"], second["id"]]
    assert [row["id"] for row in second_page] == [third["id"]]


@pytest.mark.asyncio
async def test_role_worker_converges_waiting_and_set_roles_from_request_state(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    await service_bundle["settings"].set(GUILD_ID, "tag_waiting_role_id", 101, DISCORD_ID)
    await service_bundle["settings"].set(GUILD_ID, "tag_set_role_id", 202, DISCORD_ID)
    member = _TagMember(DISCORD_ID)
    waiting_role = _TagRole(101)
    set_role = _TagRole(202)
    worker = WebActionWorker(
        service_bundle["database"],
        SimpleNamespace(),
        service_bundle["audit"],
        _TagBot(_TagGuild(member, [waiting_role, set_role])),
        tags=service,
    )

    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    assert await worker.process_pending() == 1
    assert [role.id for role in member.roles] == [101]

    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )
    awaiting_confirmation = await service.mark_set_performed(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        set_character_id="77",
    )
    await service.confirm_tag(
        int(request["id"]),
        discord_id=DISCORD_ID,
        expected_version=int(awaiting_confirmation["version"]),
    )

    assert await worker.process_pending() == 1
    assert [role.id for role in member.roles] == [202]


@pytest.mark.asyncio
async def test_role_reconciliation_repairs_manual_discord_divergence(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    await service_bundle["settings"].set(GUILD_ID, "tag_waiting_role_id", 101, DISCORD_ID)
    await service_bundle["settings"].set(GUILD_ID, "tag_set_role_id", 202, DISCORD_ID)
    member = _TagMember(DISCORD_ID)
    waiting_role = _TagRole(101)
    set_role = _TagRole(202)
    worker = WebActionWorker(
        service_bundle["database"],
        SimpleNamespace(),
        service_bundle["audit"],
        _TagBot(_TagGuild(member, [waiting_role, set_role])),
        tags=service,
    )
    await service.request_tag(GUILD_ID, DISCORD_ID)
    assert await worker.process_pending() == 1
    assert [role.id for role in member.roles] == [101]


@pytest.mark.asyncio
async def test_delayed_old_terminal_role_sync_cannot_remove_newer_waiting_role(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    await service_bundle["settings"].set(GUILD_ID, "tag_waiting_role_id", 101, DISCORD_ID)
    await service_bundle["settings"].set(GUILD_ID, "tag_set_role_id", 202, DISCORD_ID)
    member = _TagMember(DISCORD_ID)
    worker = WebActionWorker(
        service_bundle["database"],
        SimpleNamespace(),
        service_bundle["audit"],
        _TagBot(_TagGuild(member, [_TagRole(101), _TagRole(202)])),
        tags=service,
    )
    old_request = await service.request_tag(GUILD_ID, DISCORD_ID)
    assert await worker.process_pending() == 1
    assert [role.id for role in member.roles] == [101]
    await service.reject_request(
        int(old_request["id"]),
        actor_id=900,
        expected_version=int(old_request["version"]),
        reason="Dados precisam ser atualizados.",
    )
    newer_request = await service.request_tag(GUILD_ID, DISCORD_ID)
    rows = await service_bundle["database"].fetchall(
        """
        SELECT * FROM web_action_outbox
        WHERE action_type='TAG_ROLE_SYNC' AND status='PENDING' ORDER BY id
        """
    )
    old_row = next(
        row
        for row in rows
        if json.loads(str(row["payload_json"]))["request_id"] == old_request["id"]
    )
    newer_row = next(
        row
        for row in rows
        if json.loads(str(row["payload_json"]))["request_id"] == newer_request["id"]
    )

    # Force the problematic order: a newer cycle is synchronized first, then
    # a delayed terminal operation from the older cycle finally arrives.
    for row in (newer_row, old_row):
        assert await worker._claim(int(row["id"]))
        result = await worker._dispatch(row)
        await worker._complete_action(row, result)

    assert newer_request["status"] == "AGUARDANDO_SET"
    assert [role.id for role in member.roles] == [101]

    member.roles.clear()
    scheduled = await worker.reconcile_tag_roles()

    assert scheduled == 1
    assert await worker.process_pending() == 1
    assert [role.id for role in member.roles] == [101]


@pytest.mark.asyncio
async def test_rejection_is_terminal_audited_and_allows_a_future_request(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)

    rejected = await service.reject_request(
        int(request["id"]),
        actor_id=900,
        expected_version=int(request["version"]),
        reason="Dados de identidade precisam ser revisados.",
    )
    reopened = await service.request_tag(GUILD_ID, DISCORD_ID)

    assert rejected["status"] == "RECUSADO"
    assert rejected["terminal_by"] == 900
    assert rejected["terminal_reason"] == "Dados de identidade precisam ser revisados."
    assert reopened["id"] != rejected["id"]
    assert reopened["status"] == "AGUARDANDO_SET"
    audit = await service_bundle["database"].fetchone(
        """
        SELECT reason FROM audit_logs
        WHERE action='TAG_REQUEST_REJECTED' AND target_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (DISCORD_ID,),
    )
    assert audit["reason"] == "Dados de identidade precisam ser revisados."


@pytest.mark.asyncio
async def test_cancellation_is_terminal_audited_and_preserves_history(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)

    cancelled = await service.cancel_request(
        int(request["id"]),
        actor_id=900,
        expected_version=int(request["version"]),
        reason="Solicitação cancelada administrativamente para correção do fluxo.",
    )
    reopened = await service.request_tag(GUILD_ID, DISCORD_ID)
    timeline = await service.timeline(int(request["id"]))
    audit = await service_bundle["database"].fetchone(
        """
        SELECT reason FROM audit_logs
        WHERE action='TAG_REQUEST_CANCELLED' AND target_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (DISCORD_ID,),
    )

    assert cancelled["status"] == "CANCELADO"
    assert cancelled["terminal_by"] == 900
    assert cancelled["terminal_reason"] == (
        "Solicitação cancelada administrativamente para correção do fluxo."
    )
    assert reopened["id"] != cancelled["id"]
    assert reopened["status"] == "AGUARDANDO_SET"
    assert timeline[-1]["event_type"] == "TAG_REQUEST_CANCELLED"
    assert audit["reason"] == cancelled["terminal_reason"]


@pytest.mark.asyncio
async def test_member_can_confirm_missing_mta_id_once_before_creating_tag_request(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    await service_bundle["members"].create_or_update(
        GUILD_ID,
        458,
        discord_nick="No ID",
        mta_nick="No_ID",
        character_id=None,
        unit="BGR",
        rank_id=None,
        actor_id=458,
    )

    with pytest.raises(ValidationError):
        await service.request_tag(GUILD_ID, 458)
    request = await service.request_tag(GUILD_ID, 458, character_id=" 99 ")
    member = await service_bundle["database"].fetchone(
        "SELECT character_id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, 458),
    )

    assert request["character_id_snapshot"] == "99"
    assert member["character_id"] == "99"
    audit = await service_bundle["database"].fetchone(
        """
        SELECT action FROM audit_logs
        WHERE action='TAG_ID_SELF_CONFIRMED' AND target_id=458
        """
    )
    assert audit["action"] == "TAG_ID_SELF_CONFIRMED"


@pytest.mark.asyncio
async def test_invalid_mta_id_is_rejected_before_identity_or_request_mutation(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    await service_bundle["members"].create_or_update(
        GUILD_ID,
        460,
        discord_nick="Invalid ID",
        mta_nick="Invalid_ID",
        character_id=None,
        unit="BGR",
        rank_id=None,
        actor_id=460,
    )

    with pytest.raises(ValidationError, match="ID BGR"):
        await service.request_tag(GUILD_ID, 460, character_id="bad id!")

    member = await service_bundle["database"].fetchone(
        "SELECT character_id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, 460),
    )
    request_count = await service_bundle["database"].fetchone(
        "SELECT COUNT(*) AS total FROM tag_requests WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, 460),
    )
    assert member["character_id"] is None
    assert request_count["total"] == 0


@pytest.mark.asyncio
async def test_conflicting_mta_id_requires_controlled_administrative_correction(service_bundle):
    """An ID already owned by an active identity gets a clear controlled error."""
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    members = service_bundle["members"]
    await members.create_or_update(
        GUILD_ID,
        459,
        discord_nick="Third User",
        mta_nick="Third_User",
        character_id="99",
        unit="BGR",
        rank_id=None,
        actor_id=459,
    )
    request = await service.request_tag(GUILD_ID, 459)
    with pytest.raises(ValidationError, match="já está vinculado a outro membro ativo"):
        await service.correct_character_id(
            int(request["id"]),
            actor_id=900,
            expected_version=int(request["version"]),
            character_id="77",
            reason="Cadastro MTA revisado pelo Alto Comando.",
        )


@pytest.mark.asyncio
async def test_member_status_and_admin_summary_read_the_same_durable_tag_request(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    created = await service.request_tag(GUILD_ID, DISCORD_ID)

    mine = await service.member_request(GUILD_ID, DISCORD_ID)
    summary = await service.summary(GUILD_ID)

    assert mine is not None
    assert mine["id"] == created["id"]
    assert summary["open"] == 1
    assert summary["AGUARDANDO_SET"] == 1
    assert summary["CONCLUIDO"] == 0


@pytest.mark.asyncio
async def test_admin_summary_counts_completed_requests_for_the_current_day(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )
    awaiting = await service.mark_set_performed(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        set_character_id="77",
    )
    await service.confirm_tag(
        int(request["id"]),
        discord_id=DISCORD_ID,
        expected_version=int(awaiting["version"]),
    )

    summary = await service.summary(GUILD_ID)

    assert summary["completed_today"] == 1
    assert summary["EXPIRADO"] == 0


@pytest.mark.asyncio
async def test_tag_request_detail_and_timeline_are_read_only_projections(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )

    detail = await service.get_request(int(request["id"]))
    timeline = await service.timeline(int(request["id"]))

    assert detail is not None
    assert detail["claimed_by"] == 701
    assert [item["event_type"] for item in timeline] == [
        "TAG_REQUEST_CREATED",
        "TAG_REQUEST_CLAIMED",
    ]


@pytest.mark.asyncio
async def test_tag_request_metrics_calculate_wait_service_confirmation_and_total_time(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    service_bundle["clock"].advance(10_000)
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )
    service_bundle["clock"].advance(20_000)
    awaiting = await service.mark_set_performed(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        set_character_id="77",
    )
    service_bundle["clock"].advance(30_000)
    await service.confirm_tag(
        int(request["id"]),
        discord_id=DISCORD_ID,
        expected_version=int(awaiting["version"]),
    )

    metrics = await service.request_metrics(int(request["id"]))

    assert metrics == {
        "waiting_ms": 10_000,
        "service_ms": 20_000,
        "confirmation_ms": 30_000,
        "total_ms": 60_000,
    }


@pytest.mark.asyncio
async def test_expiration_only_closes_unattended_waiting_requests(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    service_bundle["clock"].advance(3_601_000)

    expired_ids = await service.expire_overdue(
        GUILD_ID, max_wait_ms=3_600_000, actor_id=0
    )
    expired = await service.get_request(int(request["id"]))

    assert expired_ids == [request["id"]]
    assert expired is not None
    assert expired["status"] == "EXPIRADO"
    assert expired["terminal_reason"] == "Prazo máximo de espera expirado."


@pytest.mark.asyncio
async def test_tag_cog_expires_only_due_waiting_requests_using_configured_hours(service_bundle):
    """Restart recovery must apply the configured expiration rule, not a hard-coded timeout."""
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    await service_bundle["settings"].set(
        GUILD_ID, "tag_expiration_hours", 1, DISCORD_ID
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    service_bundle["clock"].advance(3_601_000)

    cog = object.__new__(TagCommands)
    cog.services = SimpleNamespace(tags=service, settings=service_bundle["settings"])
    cog.refresh_admin_panel = AsyncMock()

    expired_ids = await cog.expire_due_requests(SimpleNamespace(id=GUILD_ID))
    current = await service.get_request(int(request["id"]))

    assert expired_ids == [request["id"]]
    assert current is not None
    assert current["status"] == "EXPIRADO"
    cog.refresh_admin_panel.assert_awaited_once()


@pytest.mark.asyncio
async def test_responsible_can_reclaim_a_member_reported_pendency(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )
    waiting_confirmation = await service.mark_set_performed(
        int(claimed["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        set_character_id="77",
    )
    pending = await service.report_tag_not_received(
        int(waiting_confirmation["id"]),
        discord_id=DISCORD_ID,
        expected_version=int(waiting_confirmation["version"]),
        reason="Ainda não apareceu no personagem.",
    )

    reclaimed = await service.claim_request(
        int(pending["id"]), responsible_id=702, expected_version=int(pending["version"])
    )

    assert reclaimed["status"] == "ATENDIMENTO_ASSUMIDO"
    assert reclaimed["claimed_by"] == 702


@pytest.mark.asyncio
async def test_responsible_can_record_operational_pendency_without_erasing_claim_history(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )

    pending = await service.report_operational_pendency(
        int(request["id"]),
        actor_id=701,
        expected_version=int(claimed["version"]),
        reason="Membro indisponível na DP de Los Santos.",
    )
    events = await service.timeline(int(request["id"]))

    assert pending["status"] == "PENDENCIA"
    assert pending["claimed_by"] is None
    assert [event["event_type"] for event in events] == [
        "TAG_REQUEST_CREATED",
        "TAG_REQUEST_CLAIMED",
        "TAG_OPERATIONAL_PENDENCY",
    ]


@pytest.mark.asyncio
async def test_administrator_can_correct_mta_id_without_erasing_tag_history(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)

    corrected = await service.correct_character_id(
        int(request["id"]),
        actor_id=900,
        expected_version=int(request["version"]),
        character_id="291",
        reason="ID informado incorretamente no cadastro.",
    )
    member = await service_bundle["database"].fetchone(
        "SELECT character_id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    timeline = await service.timeline(int(request["id"]))

    assert corrected["status"] == "AGUARDANDO_SET"
    assert corrected["character_id_snapshot"] == "291"
    assert member["character_id"] == "291"
    assert [entry["event_type"] for entry in timeline][-1] == "TAG_ID_CHANGED"
    assert json.loads(str(timeline[-1]["metadata_json"])) == {
        "new_character_id": "291",
        "previous_character_id": "77",
    }


@pytest.mark.asyncio
async def test_confirmation_notification_is_claimed_once_and_survives_restart_recovery(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )
    waiting_confirmation = await service.mark_set_performed(
        int(claimed["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        set_character_id="77",
    )

    delivery = await service.claim_confirmation_notification(
        int(waiting_confirmation["id"])
    )
    repeated_claim = await service.claim_confirmation_notification(
        int(waiting_confirmation["id"])
    )
    await service.mark_confirmation_notification_delivered(
        int(waiting_confirmation["id"]), delivery_message_id=1234
    )
    pending = await service.pending_confirmation_notifications(GUILD_ID)

    assert delivery is not None
    assert repeated_claim is None
    assert pending == []


@pytest.mark.asyncio
async def test_stale_confirmation_notification_claim_is_recoverable_without_changing_tag_state(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )
    await service.mark_set_performed(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        set_character_id="77",
    )
    assert await service.claim_confirmation_notification(int(request["id"])) is not None
    service_bundle["clock"].advance(300_001)

    recovered = await service.recover_confirmation_notification_claims()
    pending = await service.pending_confirmation_notifications(GUILD_ID)
    current = await service.get_request(int(request["id"]))

    assert recovered == 1
    assert [row["id"] for row in pending] == [request["id"]]
    assert current is not None
    assert current["status"] == "AGUARDANDO_CONFIRMACAO"
    assert current["confirmation_delivery_status"] == "FAILED"


@pytest.mark.asyncio
async def test_responsible_notification_is_claimed_once_and_survives_retry_recovery(service_bundle):
    """A new queue entry must alert the responsible role once, not per retry/restart."""
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)

    claimed = await service.claim_responsible_notification(int(request["id"]))
    repeated_claim = await service.claim_responsible_notification(int(request["id"]))
    await service.mark_responsible_notification_delivered(
        int(request["id"]), delivery_message_id=9876
    )
    pending = await service.pending_responsible_notifications(GUILD_ID)

    assert request["responsible_notification_status"] == "PENDING"
    assert claimed is not None
    assert repeated_claim is None
    assert pending == []


@pytest.mark.asyncio
async def test_request_card_projection_tracks_versions_without_new_messages(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    assert await service.claim_responsible_notification(int(request["id"])) is not None
    assert await service.mark_responsible_notification_delivered(
        int(request["id"]), delivery_message_id=9876
    )

    claimed = await service.claim_request(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(request["version"]),
    )
    stale_cards = await service.pending_request_card_refreshes(GUILD_ID)

    assert [row["id"] for row in stale_cards] == [request["id"]]
    assert claimed["responsible_notification_message_id"] == 9876
    assert await service.mark_request_card_rendered(
        int(request["id"]),
        message_id=9876,
        rendered_version=int(claimed["version"]),
    )
    assert await service.pending_request_card_refreshes(GUILD_ID) == []


@pytest.mark.asyncio
async def test_missing_request_card_is_rearmed_only_after_exact_message_match(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    assert await service.claim_responsible_notification(int(request["id"])) is not None
    assert await service.mark_responsible_notification_delivered(
        int(request["id"]), delivery_message_id=9876
    )

    assert not await service.rearm_missing_request_card(
        int(request["id"]), missing_message_id=1111
    )
    assert await service.rearm_missing_request_card(
        int(request["id"]), missing_message_id=9876
    )
    current = await service.get_request(int(request["id"]))

    assert current is not None
    assert current["responsible_notification_status"] == "PENDING"
    assert current["responsible_notification_message_id"] is None
    assert [row["id"] for row in await service.pending_responsible_notifications(GUILD_ID)] == [
        request["id"]
    ]


@pytest.mark.asyncio
async def test_only_current_responsible_can_call_claimed_request_to_dp(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    claimed = await service.claim_request(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(request["version"]),
    )

    with pytest.raises(PermissionDenied):
        await service.reserve_member_call(
            int(request["id"]),
            responsible_id=702,
            expected_version=int(claimed["version"]),
            cooldown_ms=60_000,
        )
    reserved = await service.reserve_member_call(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        cooldown_ms=60_000,
    )

    assert reserved["last_call_by"] == 701


@pytest.mark.asyncio
async def test_terminal_tag_decision_queues_one_member_notification(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    rejected = await service.reject_request(
        int(request["id"]),
        actor_id=900,
        expected_version=int(request["version"]),
        reason="Dados do personagem precisam ser corrigidos.",
    )

    claimed = await service.claim_terminal_notification(int(request["id"]))
    repeated_claim = await service.claim_terminal_notification(int(request["id"]))
    await service.mark_terminal_notification_delivered(
        int(request["id"]), delivery_message_id=7654
    )
    pending = await service.pending_terminal_notifications(GUILD_ID)

    assert rejected["terminal_notification_status"] == "PENDING"
    assert claimed is not None
    assert repeated_claim is None
    assert pending == []


@pytest.mark.asyncio
async def test_tag_cog_flushes_each_durable_responsible_notification_once(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    guild = SimpleNamespace(id=GUILD_ID)
    cog = object.__new__(TagCommands)
    cog.services = SimpleNamespace(tags=service)
    cog.deliver_responsible_notification = AsyncMock(return_value=True)

    delivered = await cog.flush_responsible_notifications(guild)

    assert delivered == 1
    cog.deliver_responsible_notification.assert_awaited_once()
    sent_request = cog.deliver_responsible_notification.await_args.args[1]
    assert sent_request["id"] == request["id"]


@pytest.mark.asyncio
async def test_tag_cog_flushes_terminal_member_notifications_from_durable_state(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    await service.cancel_request(
        int(request["id"]),
        actor_id=900,
        expected_version=int(request["version"]),
        reason="Solicitação duplicada de teste.",
    )
    guild = SimpleNamespace(id=GUILD_ID)
    cog = object.__new__(TagCommands)
    cog.services = SimpleNamespace(tags=service)
    cog.deliver_terminal_notification = AsyncMock(return_value=True)

    delivered = await cog.flush_terminal_notifications(guild)

    assert delivered == 1
    cog.deliver_terminal_notification.assert_awaited_once()


@pytest.mark.asyncio
async def test_member_with_completed_tag_cannot_open_another_request(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)
    claimed = await service.claim_request(
        int(request["id"]), responsible_id=701, expected_version=int(request["version"])
    )
    waiting_confirmation = await service.mark_set_performed(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(claimed["version"]),
        set_character_id="77",
    )
    await service.confirm_tag(
        int(request["id"]),
        discord_id=DISCORD_ID,
        expected_version=int(waiting_confirmation["version"]),
    )

    with pytest.raises(ConflictError, match="já possui TAG SETADA"):
        await service.request_tag(GUILD_ID, DISCORD_ID)


@pytest.mark.asyncio
async def test_member_call_reservation_is_audited_and_respects_configurable_cooldown(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)

    reserved = await service.reserve_member_call(
        int(request["id"]),
        responsible_id=701,
        expected_version=int(request["version"]),
        cooldown_ms=300_000,
    )
    with pytest.raises(ConflictError, match="aguarde"):
        await service.reserve_member_call(
            int(request["id"]),
            responsible_id=701,
            expected_version=int(request["version"]),
            cooldown_ms=300_000,
        )
    await service.record_member_called(int(request["id"]), responsible_id=701)
    events = await service.timeline(int(request["id"]))

    assert reserved["last_call_by"] == 701
    assert [event["event_type"] for event in events][-1] == "TAG_MEMBER_CALLED"


@pytest.mark.asyncio
async def test_queue_search_accepts_mta_nick_mta_id_and_discord_id(service_bundle):
    service = TagService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    request = await service.request_tag(GUILD_ID, DISCORD_ID)

    by_nick = await service.search_requests(GUILD_ID, "choque_user")
    by_mta_id = await service.search_requests(GUILD_ID, "77")
    by_discord_id = await service.search_requests(GUILD_ID, str(DISCORD_ID))

    assert [row["id"] for row in by_nick] == [request["id"]]
    assert [row["id"] for row in by_mta_id] == [request["id"]]
    assert [row["id"] for row in by_discord_id] == [request["id"]]
