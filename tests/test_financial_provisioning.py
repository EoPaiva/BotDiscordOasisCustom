from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from scripts.provision_financial_aid import (
    ADMIN_CHANNEL_NAME,
    HIGHLIGHTS_CHANNEL_NAME,
    PUBLIC_CHANNEL_NAME,
    _ensure_standard_channel_name,
    _public_highlights_overwrites,
    admin_channel_is_private,
    highlights_channel_is_read_only,
    normalized_channel_name,
    select_parent_category,
)


def test_normalized_channel_name_handles_small_caps_and_accents() -> None:
    assert normalized_channel_name("05・ɪɴꜰᴏʀᴍᴀçõᴇꜱ") == "05informacoes"
    assert normalized_channel_name("08・ᴀᴅᴍɪɴɪꜱᴛʀᴀçãᴏ") == "08administracao"
    assert normalized_channel_name("𝟶𝟾・𝙸𝙽𝙵𝙾𝚁𝙼𝙰𝙲𝙾𝙴𝚂") == "08informacoes"
    assert normalized_channel_name("𝟶𝟻・𝙰𝙳𝙼𝙸𝙽𝙸𝚂𝚃𝚁𝙰𝙲𝙰𝙾") == "05administracao"


@pytest.mark.asyncio
async def test_configured_channel_is_renamed_by_id_without_duplicate_creation() -> None:
    updated = SimpleNamespace(name=HIGHLIGHTS_CHANNEL_NAME)
    channel = SimpleNamespace(
        name="🏅・destaques-financeiros",
        edit=AsyncMock(return_value=updated),
    )

    result = await _ensure_standard_channel_name(channel, HIGHLIGHTS_CHANNEL_NAME)

    assert result is updated
    channel.edit.assert_awaited_once_with(
        name=HIGHLIGHTS_CHANNEL_NAME,
        reason="Padronização visual Small Caps da Central Financeira",
    )


def test_category_selection_fails_closed_when_no_approved_parent_exists(monkeypatch) -> None:
    import scripts.provision_financial_aid as provisioner

    monkeypatch.setattr(provisioner.discord, "CategoryChannel", type("Category", (), {}))
    categories = [SimpleNamespace(name="Patrulhas")]
    assert select_parent_category(categories, purpose="PUBLIC") is None
    assert select_parent_category(categories, purpose="ADMIN") is None


def test_category_selection_accepts_the_numbered_small_caps_layout(monkeypatch) -> None:
    import scripts.provision_financial_aid as provisioner

    category_type = type("Category", (), {})
    monkeypatch.setattr(provisioner.discord, "CategoryChannel", category_type)
    public = category_type()
    public.name = "05・ɪɴꜰᴏʀᴍᴀçõᴇꜱ"
    admin = category_type()
    admin.name = "08・ᴀᴅᴍɪɴɪꜱᴛʀᴀçãᴏ"

    assert select_parent_category([public, admin], purpose="PUBLIC") is public
    assert select_parent_category([public, admin], purpose="ADMIN") is admin


def test_admin_channel_requires_the_admin_parent_and_explicit_everyone_deny() -> None:
    default_role = object()
    guild = SimpleNamespace(default_role=default_role)
    parent = SimpleNamespace(id=80)

    def channel(*, category_id: int, view_channel: bool | None):
        return SimpleNamespace(
            category_id=category_id,
            guild=guild,
            overwrites_for=lambda role: SimpleNamespace(view_channel=view_channel),
        )

    assert admin_channel_is_private(channel(category_id=80, view_channel=False), parent)
    assert not admin_channel_is_private(channel(category_id=81, view_channel=False), parent)
    assert not admin_channel_is_private(channel(category_id=80, view_channel=None), parent)


def test_highlights_channel_is_public_read_only_and_bot_can_publish() -> None:
    default_role = object()
    bot_member = object()
    guild = SimpleNamespace(default_role=default_role)
    parent = SimpleNamespace(id=50, overwrites={})
    overwrites = _public_highlights_overwrites(guild, parent, bot_member)

    everyone = overwrites[default_role]
    bot_access = overwrites[bot_member]

    assert PUBLIC_CHANNEL_NAME == "💰・ᴀᴜxɪʟɪᴏ-ꜰɪɴᴀɴᴄᴇɪʀᴏ"
    assert ADMIN_CHANNEL_NAME == "🛡️・ᴀᴅᴍɪɴɪꜱᴛʀᴀᴄᴀᴏ-ꜰɪɴᴀɴᴄᴇɪʀᴀ"
    assert HIGHLIGHTS_CHANNEL_NAME == "🏅・ᴅᴇꜱᴛᴀꞯᴜᴇꜱ-ꜰɪɴᴀɴᴄᴇɪʀᴏꜱ"
    assert isinstance(everyone, discord.PermissionOverwrite)
    assert everyone.view_channel is True
    assert everyone.read_message_history is True
    assert everyone.send_messages is False
    assert everyone.send_messages_in_threads is False
    assert everyone.create_public_threads is False
    assert everyone.create_private_threads is False
    assert everyone.add_reactions is False
    assert bot_access.view_channel is True
    assert bot_access.read_message_history is True
    assert bot_access.send_messages is True
    assert bot_access.embed_links is True
    assert bot_access.manage_messages is True

    channel = SimpleNamespace(
        category_id=parent.id,
        guild=guild,
        overwrites_for=lambda role: overwrites[role],
    )
    assert highlights_channel_is_read_only(channel, parent)


def test_highlights_channel_validation_fails_closed_for_chat_or_wrong_parent() -> None:
    default_role = object()
    guild = SimpleNamespace(default_role=default_role)
    parent = SimpleNamespace(id=50)

    def channel(*, category_id: int, send_messages: bool | None):
        return SimpleNamespace(
            category_id=category_id,
            guild=guild,
            overwrites_for=lambda role: SimpleNamespace(
                view_channel=True,
                read_message_history=True,
                send_messages=send_messages,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False,
            ),
        )

    assert not highlights_channel_is_read_only(
        channel(category_id=parent.id, send_messages=True), parent
    )
    assert not highlights_channel_is_read_only(
        channel(category_id=parent.id + 1, send_messages=False), parent
    )
    assert not highlights_channel_is_read_only(
        channel(category_id=parent.id, send_messages=None), parent
    )
