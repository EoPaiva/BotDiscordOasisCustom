from __future__ import annotations

import json
from types import SimpleNamespace

import discord
import pytest

import cogs.financial_aid_commands as financial_commands
from choque.config import Branding
from cogs.financial_aid_commands import (
    PUBLIC_PANEL_MARKER,
    FinancialAidCommands,
)

from .conftest import GUILD_ID


class FakeMessage:
    def __init__(self, message_id: int, channel, author_id: int, embeds: list[discord.Embed]):
        self.id = message_id
        self.channel = channel
        self.author = SimpleNamespace(id=author_id)
        self.embeds = embeds
        self.content = ""
        self.edits = 0

    async def edit(self, **kwargs):
        self.edits += 1
        if kwargs.get("embed") is not None:
            self.embeds = [kwargs["embed"]]
        return self


class FakeChannel:
    def __init__(self, channel_id: int, bot_user_id: int):
        self.id = channel_id
        self.bot_user_id = bot_user_id
        self.messages: list[FakeMessage] = []
        self.send_count = 0

    def history(self, *, limit: int):
        async def iterate():
            for message in list(reversed(self.messages))[:limit]:
                yield message

        return iterate()

    async def fetch_message(self, message_id: int):
        match = next((message for message in self.messages if message.id == message_id), None)
        if match is None:
            raise discord.NotFound(SimpleNamespace(status=404, reason="not found"), "not found")
        return match

    async def send(self, *, embed, nonce=None, allowed_mentions=None):
        # Keep the signature intentionally strict. A regression that restores
        # ``enforce_nonce`` must fail this test exactly as it failed in Discord.
        assert isinstance(nonce, int)
        assert allowed_mentions is not None
        self.send_count += 1
        message = FakeMessage(10_000 + self.send_count, self, self.bot_user_id, [embed])
        self.messages.append(message)
        return message


def _cog(service_bundle, channel: FakeChannel):
    guild = SimpleNamespace(id=GUILD_ID, get_channel=lambda channel_id: channel if channel_id == channel.id else None)
    bot = SimpleNamespace(
        user=SimpleNamespace(id=999),
        config=SimpleNamespace(branding=Branding()),
        services=SimpleNamespace(
            financial_aid=service_bundle["financial_aid"],
            database=service_bundle["database"],
            settings=service_bundle["settings"],
        ),
        get_guild=lambda guild_id: guild if guild_id == GUILD_ID else None,
    )
    cog = object.__new__(FinancialAidCommands)
    cog.bot = bot
    cog.services = bot.services
    cog._panel_locks = {}
    return cog


@pytest.mark.asyncio
async def test_panel_sent_before_registry_commit_is_adopted_after_restart(service_bundle):
    await service_bundle["financial_aid"].ensure_defaults(GUILD_ID)
    channel = FakeChannel(777, 999)
    previous_embed = discord.Embed(title="Painel já enviado")
    previous_embed.set_footer(text=f"CHOQUE - BGR • {PUBLIC_PANEL_MARKER}")
    existing = FakeMessage(4321, channel, 999, [previous_embed])
    channel.messages.append(existing)
    cog = _cog(service_bundle, channel)

    adopted = await cog._publish_or_refresh_public_panel_unlocked(
        SimpleNamespace(id=GUILD_ID), channel
    )
    panel = await service_bundle["settings"].get_panel(GUILD_ID, "FINANCIAL_AID")

    assert adopted is existing
    assert channel.send_count == 0
    assert panel is not None and int(panel["message_id"]) == existing.id
    assert existing.edits == 1


@pytest.mark.asyncio
async def test_notification_sent_before_id_commit_is_not_sent_twice(
    service_bundle, monkeypatch
):
    database = service_bundle["database"]
    clock = service_bundle["clock"]
    channel = FakeChannel(777, 999)
    cog = _cog(service_bundle, channel)
    monkeypatch.setattr(financial_commands.discord, "TextChannel", FakeChannel)
    await service_bundle["settings"].set(GUILD_ID, "financial_panel_channel_id", channel.id, 900)
    notification_id = await database.execute(
        """
        INSERT INTO financial_notifications(
            guild_id, notification_type, subject_type, subject_id,
            target_discord_id, channel_setting_key, payload_json, event_key,
            status, attempts, available_at, correlation_id, created_at, updated_at
        ) VALUES (?, 'PROJECT_COMPLETED', 'PROJECT', 1, NULL, ?, ?, ?,
                  'PROCESSING', 1, ?, ?, ?, ?)
        """,
        (
            GUILD_ID,
            "financial_panel_channel_id",
            json.dumps({"name": "Meta segura", "public_code": "META-1"}),
            "crash-boundary-notification",
            clock(),
            "crash-boundary-correlation",
            clock(),
            clock(),
        ),
    )
    row = await database.fetchone("SELECT * FROM financial_notifications WHERE id=?", (notification_id,))
    assert row is not None

    original_execute = database.execute
    fail_once = True

    async def execute_with_crash(sql: str, params: tuple = ()):
        nonlocal fail_once
        if fail_once and "SET channel_message_id" in sql:
            fail_once = False
            raise RuntimeError("queda simulada após Discord aceitar a mensagem")
        return await original_execute(sql, params)

    monkeypatch.setattr(database, "execute", execute_with_crash)
    await cog._deliver_financial_notification(dict(row))
    assert channel.send_count == 1

    await original_execute(
        "UPDATE financial_notifications SET status='PROCESSING', updated_at=? WHERE id=?",
        (clock(), notification_id),
    )
    retry = await database.fetchone("SELECT * FROM financial_notifications WHERE id=?", (notification_id,))
    assert retry is not None
    await cog._deliver_financial_notification(dict(retry))
    delivered = await database.fetchone(
        "SELECT status, channel_message_id FROM financial_notifications WHERE id=?",
        (notification_id,),
    )

    assert channel.send_count == 1
    assert delivered is not None and delivered["status"] == "DELIVERED"
    assert int(delivered["channel_message_id"]) == channel.messages[0].id


@pytest.mark.asyncio
async def test_notification_revision_cas_preserves_newer_intent_and_retry_reuses_marker(
    service_bundle, monkeypatch
):
    database = service_bundle["database"]
    clock = service_bundle["clock"]
    channel = FakeChannel(778, 999)
    cog = _cog(service_bundle, channel)
    monkeypatch.setattr(financial_commands.discord, "TextChannel", FakeChannel)
    await service_bundle["settings"].set(
        GUILD_ID, "financial_panel_channel_id", channel.id, 900
    )
    notification_id = await database.execute(
        """
        INSERT INTO financial_notifications(
            guild_id, notification_type, subject_type, subject_id,
            target_discord_id, channel_setting_key, payload_json, event_key,
            status, attempts, available_at, correlation_id, created_at, updated_at
        ) VALUES (?, 'PROJECT_COMPLETED', 'PROJECT', 2, NULL, ?, ?, ?,
                  'PROCESSING', 1, ?, ?, ?, ?)
        """,
        (
            GUILD_ID,
            "financial_panel_channel_id",
            json.dumps({"name": "Meta revisada", "public_code": "META-2"}),
            "revision-cas-notification",
            clock(),
            "revision-cas-correlation",
            clock(),
            clock(),
        ),
    )
    initial = await database.fetchone(
        "SELECT * FROM financial_notifications WHERE id=?", (notification_id,)
    )
    assert initial is not None and int(initial["revision"]) == 1

    original_execute = database.execute
    inject_new_revision = True

    async def execute_with_concurrent_refresh(sql: str, params: tuple = ()):
        nonlocal inject_new_revision
        if inject_new_revision and "SET channel_message_id" in sql:
            inject_new_revision = False
            await original_execute(
                """
                UPDATE financial_notifications
                SET status='PENDING', revision=revision+1, updated_at=?
                WHERE id=?
                """,
                (clock(), notification_id),
            )
        return await original_execute(sql, params)

    monkeypatch.setattr(database, "execute", execute_with_concurrent_refresh)
    await cog._deliver_financial_notification(dict(initial))
    after_stale_delivery = await database.fetchone(
        "SELECT * FROM financial_notifications WHERE id=?", (notification_id,)
    )

    assert channel.send_count == 1
    assert after_stale_delivery is not None
    assert after_stale_delivery["status"] == "PENDING"
    assert int(after_stale_delivery["revision"]) == 2
    assert after_stale_delivery["channel_message_id"] is None

    monkeypatch.setattr(database, "execute", original_execute)
    claimed = await cog._claim_financial_notification()
    assert claimed is not None and int(claimed["revision"]) == 2
    await cog._deliver_financial_notification(claimed)
    delivered = await database.fetchone(
        "SELECT status, revision, channel_message_id FROM financial_notifications WHERE id=?",
        (notification_id,),
    )

    assert channel.send_count == 1
    assert channel.messages[0].edits == 1
    assert delivered is not None and delivered["status"] == "DELIVERED"
    assert int(delivered["revision"]) == 2
    assert int(delivered["channel_message_id"]) == channel.messages[0].id
