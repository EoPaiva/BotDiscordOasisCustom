from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.ticket_commands import (
    CloseTicketModal,
    TicketCommands,
    TicketConfigurationView,
    TicketRoomView,
)


@pytest.mark.asyncio
async def test_ticket_room_persistent_controls_are_complete_and_stable() -> None:
    view = TicketRoomView()
    custom_ids = {item.custom_id for item in view.children}
    assert custom_ids == {
        "choque:ticket:room:claim:v1",
        "choque:ticket:room:priority:v1",
        "choque:ticket:room:add:v1",
        "choque:ticket:room:remove:v1",
        "choque:ticket:room:notify:v1",
        "choque:ticket:room:transcript:v1",
        "choque:ticket:room:reopen:v1",
        "choque:ticket:room:close:v1",
    }
    assert len(view.children) == 8


@pytest.mark.asyncio
async def test_ticket_close_requires_reason_and_literal_confirmation() -> None:
    modal = CloseTicketModal()
    assert {item.label for item in modal.children} == {
        "Motivo do encerramento",
        "Digite ENCERRAR para confirmar",
    }


@pytest.mark.asyncio
async def test_ticket_configuration_uses_category_role_and_channel_selects() -> None:
    view = TicketConfigurationView()
    assert len(view.children) == 5
    assert [item.placeholder for item in view.children if hasattr(item, "placeholder")] == [
        "Categoria de tickets ativos",
        "Categoria de tickets arquivados",
        "Cargo responsável por tickets",
        "Canal privado para transcrições",
    ]
    assert any(item.label == "Teto de transferências" for item in view.children)


@pytest.mark.asyncio
async def test_approved_transfer_is_published_to_the_existing_registration_review() -> None:
    member_cog = SimpleNamespace(publish_application_for_review=AsyncMock())
    bot = SimpleNamespace(get_cog=lambda name: member_cog if name == "MemberCommands" else None)
    command = TicketCommands.__new__(TicketCommands)
    command.bot = bot
    command.services = SimpleNamespace(
        settings=SimpleNamespace(get=AsyncMock(return_value=None))
    )
    command.refresh_admin_panel = AsyncMock()
    command.archive_ticket_room = AsyncMock()
    guild = SimpleNamespace(id=123, get_member=lambda _: None)
    ticket = {
        "id": 41,
        "ticket_type": "TRANSFER",
        "member_application_id": 73,
        "discord_id": 7002,
        "status": "APPROVED",
        "review_reason": "Experiência validada.",
        "reviewed_by": 9001,
    }

    await TicketCommands.after_decision(command, guild, ticket)

    member_cog.publish_application_for_review.assert_awaited_once_with(guild, 73)
