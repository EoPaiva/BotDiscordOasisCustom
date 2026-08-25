from __future__ import annotations

import asyncio

import pytest

import choque.audit as audit_module
from choque.audit import AuditService, should_deliver_to_audit_channel
from choque.config import Branding
from choque.database import Database
from choque.settings import SettingsService
from cogs.shift_commands import ShiftCommands

from .conftest import DISCORD_ID, GUILD_ID


class FakeChannel:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent = 0
        self.payloads: list[dict] = []
        self.fail = fail

    async def send(self, **kwargs):
        if self.fail:
            raise audit_module.discord.DiscordException("temporary delivery failure")
        self.sent += 1
        self.payloads.append(kwargs)


class FakeBot:
    def __init__(self, channel: FakeChannel) -> None:
        self.channel = channel

    def get_channel(self, channel_id: int):
        return self.channel


class FakeMessage:
    def __init__(self, channel) -> None:
        self.channel = channel
        self.id = 20
        self.edits = 0

    async def edit(self, **kwargs):
        self.edits += 1


class FakePanelChannel:
    def __init__(self) -> None:
        self.id = 10
        self.message = FakeMessage(self)
        self.sends = 0

    async def fetch_message(self, message_id: int):
        assert message_id == 20
        return self.message

    async def send(self, **kwargs):
        self.sends += 1
        return self.message


class FakePanelBot:
    def __init__(self, channel: FakePanelChannel) -> None:
        self.channel = channel

    def get_channel(self, channel_id: int):
        return self.channel if channel_id == self.channel.id else None


class DisconnectedBot:
    def is_ready(self) -> bool:
        return True

    def get_guild(self, guild_id: int):
        return None


class ConnectedBotWithoutAuditChannel:
    def is_ready(self) -> bool:
        return True

    def get_guild(self, guild_id: int):
        return object()


@pytest.mark.asyncio
async def test_audit_outbox_failure_then_retry(service_bundle, monkeypatch):
    database = service_bundle["database"]
    settings = service_bundle["settings"]
    channel = FakeChannel(fail=True)
    audit = AuditService(database, settings, Branding(), bot=FakeBot(channel))
    monkeypatch.setattr(audit_module.discord, "TextChannel", FakeChannel)
    await settings.set(GUILD_ID, "audit_channel_id", 777, DISCORD_ID)
    audit_id = await audit.record(GUILD_ID, "TEST_EVENT", actor_id=DISCORD_ID)
    assert await audit.deliver_pending() == 0
    failed = await database.fetchone("SELECT * FROM audit_logs WHERE id=?", (audit_id,))
    assert failed["delivery_status"] == "FAILED"
    assert failed["delivery_attempts"] == 1

    channel.fail = False
    assert await audit.deliver_pending() >= 1
    delivered = await database.fetchone("SELECT * FROM audit_logs WHERE id=?", (audit_id,))
    assert delivered["delivery_status"] == "DELIVERED"
    assert channel.sent >= 1


@pytest.mark.asyncio
async def test_audit_outbox_preserves_rows_for_disconnected_guild(service_bundle):
    database = service_bundle["database"]
    settings = service_bundle["settings"]
    audit = AuditService(database, settings, Branding(), bot=DisconnectedBot())
    audit_id = await audit.record(GUILD_ID, "DISCONNECTED_GUILD_EVENT")
    row = await database.fetchone("SELECT * FROM audit_logs WHERE id=?", (audit_id,))
    assert row["delivery_status"] == "PENDING"
    assert row["delivery_attempts"] == 0


@pytest.mark.asyncio
async def test_audit_outbox_waits_for_channel_configuration(service_bundle):
    database = service_bundle["database"]
    settings = service_bundle["settings"]
    audit = AuditService(
        database,
        settings,
        Branding(),
        bot=ConnectedBotWithoutAuditChannel(),
    )
    audit_id = await audit.record(GUILD_ID, "WAITING_FOR_AUDIT_CHANNEL")
    row = await database.fetchone("SELECT * FROM audit_logs WHERE id=?", (audit_id,))
    assert row["delivery_status"] == "PENDING"
    assert row["delivery_attempts"] == 0


@pytest.mark.asyncio
async def test_audit_delivery_is_claimed_once_across_two_runtime_connections(tmp_path, monkeypatch):
    """Bot callbacks and the retry loop cannot publish the same audit twice."""
    path = tmp_path / "shared-audit.db"
    first_database = Database(path)
    second_database = Database(path)
    await first_database.open()
    await second_database.open()
    try:
        first_settings = SettingsService(first_database)
        second_settings = SettingsService(second_database)
        channel = FakeChannel()
        monkeypatch.setattr(audit_module.discord, "TextChannel", FakeChannel)
        first_audit = AuditService(first_database, first_settings, Branding(), bot=FakeBot(channel))
        second_audit = AuditService(second_database, second_settings, Branding(), bot=FakeBot(channel))
        await first_settings.set(GUILD_ID, "audit_channel_id", 777, DISCORD_ID)
        audit_id = await first_audit.record(GUILD_ID, "CONCURRENT_AUDIT")

        delivered = await asyncio.gather(
            first_audit.deliver_pending(), second_audit.deliver_pending()
        )

        row = await first_database.fetchone("SELECT * FROM audit_logs WHERE id=?", (audit_id,))
        assert sum(delivered) == 1
        assert channel.sent == 1
        assert row["delivery_status"] == "DELIVERED"
        assert row["delivery_attempts"] == 1
    finally:
        await second_database.close()
        await first_database.close()


@pytest.mark.asyncio
async def test_audit_coalesces_only_historical_repeated_access_grants(service_bundle, monkeypatch):
    database = service_bundle["database"]
    settings = service_bundle["settings"]
    channel = FakeChannel()
    monkeypatch.setattr(audit_module.discord, "TextChannel", FakeChannel)
    audit = AuditService(database, settings, Branding(), bot=FakeBot(channel))
    await settings.set(GUILD_ID, "audit_channel_id", 777, DISCORD_ID)
    await database.execute("UPDATE audit_logs SET delivery_status='DELIVERED'")
    for _ in range(3):
        await audit.record(GUILD_ID, "REGISTRATION_ACCESS_GRANTED", target_id=8001)
    await audit.record(GUILD_ID, "REGISTRATION_ACCESS_GRANTED", target_id=8002)

    # The historical duplicate compaction remains useful, but routine access
    # grants must no longer repopulate the human channel after a restart.
    assert await audit.deliver_pending(limit=20) == 0
    rows = await database.fetchall(
        """
        SELECT target_id, delivery_status, last_error FROM audit_logs
        WHERE action='REGISTRATION_ACCESS_GRANTED' ORDER BY id
        """
    )
    assert channel.sent == 0
    assert [str(row["delivery_status"]) for row in rows] == [
        "DELIVERED",
        "DELIVERED",
        "DELIVERED",
        "DELIVERED",
    ]
    assert "Coalescida" in str(rows[0]["last_error"])
    assert "Coalescida" in str(rows[1]["last_error"])
    assert "Suprimida" in str(rows[2]["last_error"])
    assert "Suprimida" in str(rows[3]["last_error"])


@pytest.mark.asyncio
async def test_audit_keeps_essential_alerts_and_suppresses_routine_successes(
    service_bundle, monkeypatch
):
    """The Discord channel is concise while the durable audit trail stays complete."""
    database = service_bundle["database"]
    settings = service_bundle["settings"]
    channel = FakeChannel()
    monkeypatch.setattr(audit_module.discord, "TextChannel", FakeChannel)
    audit = AuditService(database, settings, Branding(), bot=FakeBot(channel))
    await settings.set(GUILD_ID, "audit_channel_id", 777, DISCORD_ID)
    await database.execute("UPDATE audit_logs SET delivery_status='DELIVERED'")

    routine_id = await audit.record(GUILD_ID, "REGISTRATION_ACCESS_GRANTED", target_id=8001)
    critical_id = await audit.record(
        GUILD_ID,
        "PUNISHMENT_APPLIED",
        actor_id=DISCORD_ID,
        target_id=8001,
        reason="teste de política",
    )

    assert should_deliver_to_audit_channel("REGISTRATION_ACCESS_GRANTED") is False
    assert should_deliver_to_audit_channel("PUNISHMENT_APPLIED") is True
    assert should_deliver_to_audit_channel("DISCORD_SYNC_FAILED") is True
    assert await audit.deliver_pending(limit=20) == 1

    routine = await database.fetchone("SELECT * FROM audit_logs WHERE id=?", (routine_id,))
    critical = await database.fetchone("SELECT * FROM audit_logs WHERE id=?", (critical_id,))
    assert routine["delivery_status"] == "DELIVERED"
    assert routine["delivery_attempts"] == 0
    assert "Suprimida" in str(routine["last_error"])
    assert critical["delivery_status"] == "DELIVERED"
    assert critical["delivery_attempts"] == 1
    assert critical["last_error"] is None
    assert channel.sent == 1


@pytest.mark.asyncio
async def test_panel_upsert_reuses_single_identity(service_bundle):
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    await settings.upsert_panel(GUILD_ID, "SERVICE", 10, 20)
    await settings.upsert_panel(GUILD_ID, "SERVICE", 10, 21)
    rows = await database.fetchall(
        "SELECT * FROM panels WHERE guild_id=? AND panel_type='SERVICE'", (GUILD_ID,)
    )
    assert len(rows) == 1
    assert rows[0]["message_id"] == 21


@pytest.mark.asyncio
async def test_service_panel_edits_stored_message_instead_of_sending_new(service_bundle):
    settings = service_bundle["settings"]
    await settings.upsert_panel(GUILD_ID, "SERVICE", 10, 20)
    channel = FakePanelChannel()
    cog = object.__new__(ShiftCommands)
    cog.bot = FakePanelBot(channel)
    cog.services = type(
        "FakeServices",
        (),
        {
            "settings": settings,
            "shifts": service_bundle["shifts"],
            "duty_patrols": service_bundle["duty_patrols"],
        },
    )()
    cog.branding = Branding()
    await cog.update_service_panel(GUILD_ID)
    assert channel.message.edits == 1
    assert channel.sends == 0
