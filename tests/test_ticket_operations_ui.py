from __future__ import annotations

import pytest

from cogs.ticket_commands import (
    CloseTicketModal,
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
    assert len(view.children) == 4
    assert [item.placeholder for item in view.children] == [
        "Categoria de tickets ativos",
        "Categoria de tickets arquivados",
        "Cargo responsável por tickets",
        "Canal privado para transcrições",
    ]
