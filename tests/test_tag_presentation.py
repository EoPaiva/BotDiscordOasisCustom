from __future__ import annotations

import pytest

from cogs.tag_commands import (
    TagAdminPanelView,
    TagConfigurationView,
    TagMemberPanelView,
    TagMemberRequestView,
    TagRequestAdminView,
    TagRequestCardView,
    TagRequestPagerView,
)


@pytest.mark.asyncio
async def test_tag_member_panel_exposes_the_three_simple_member_actions() -> None:
    view = TagMemberPanelView()

    assert [item.label for item in view.children] == [
        "Solicitar tag",
        "Minha tag já foi setada",
        "Minha tag",
    ]
    assert [item.custom_id for item in view.children] == [
        "choque:tag:request:v1",
        "choque:tag:already-set:v1",
        "choque:tag:mine:v1",
    ]
    assert view.is_persistent()


@pytest.mark.asyncio
async def test_tag_admin_panel_exposes_the_operational_views_and_configuration() -> None:
    view = TagAdminPanelView()

    assert [item.label for item in view.children] == [
        "Todos",
        "Faltam setar",
        "Em atendimento",
        "Aguardando confirmação",
        "Pendências",
        "Histórico",
        "Configurar",
        "Buscar",
    ]
    assert view.is_persistent()


@pytest.mark.asyncio
async def test_tag_confirmation_view_has_request_scoped_persistent_controls() -> None:
    view = TagMemberRequestView(42, 3, "AGUARDANDO_CONFIRMACAO")

    assert [item.custom_id for item in view.children] == [
        "choque:tag:confirm:42:v1",
        "choque:tag:not-received:42:v1",
    ]
    assert view.is_persistent()


@pytest.mark.asyncio
async def test_tag_configuration_exposes_role_channel_and_operational_time_settings() -> None:
    view = TagConfigurationView()

    assert [item.label for item in view.children] == [
        "Canal do painel do membro",
        "Canal do painel administrativo",
        "Cargo AGUARDANDO SET",
        "Cargo TAG SETADA",
        "Cargo RESPONSÁVEL POR TAG",
        "Prazo de expiração (horas)",
        "Cooldown de chamada (segundos)",
    ]


@pytest.mark.asyncio
async def test_tag_request_pager_exposes_next_page_without_extra_channel_messages() -> None:
    view = TagRequestPagerView(
        [],
        title="Fila",
        statuses=("AGUARDANDO_SET",),
        history=False,
        page=0,
        total=26,
        admin_only=False,
    )

    assert [item.label for item in view.children] == ["Anterior", "Próxima"]
    assert view.children[0].disabled is True
    assert view.children[1].disabled is False


@pytest.mark.asyncio
async def test_tag_responsible_card_can_register_an_operational_pendency() -> None:
    view = TagRequestAdminView(42, 3, "ATENDIMENTO_ASSUMIDO")

    pending_button = next(item for item in view.children if item.label == "Pendência")
    assert pending_button.disabled is False


@pytest.mark.asyncio
async def test_new_request_card_exposes_only_claim_and_details() -> None:
    view = TagRequestCardView(
        {"id": 42, "status": "AGUARDANDO_SET", "request_origin": "SET_REQUEST"}
    )

    assert [item.label for item in view.children] == ["Assumir", "Ver detalhes"]
    assert [item.custom_id for item in view.children] == [
        "choque:tag:card:claim:42:v1",
        "choque:tag:card:details:42:v1",
    ]
    assert view.is_persistent()


@pytest.mark.asyncio
async def test_claimed_request_card_exposes_dp_set_and_more_actions() -> None:
    view = TagRequestCardView(
        {
            "id": 42,
            "status": "ATENDIMENTO_ASSUMIDO",
            "request_origin": "SET_REQUEST",
        }
    )

    assert [item.label for item in view.children] == [
        "Chamar para DP",
        "Tag aplicada",
        "Mais ações",
    ]
    assert view.is_persistent()


@pytest.mark.asyncio
async def test_existing_tag_card_uses_validation_wording() -> None:
    view = TagRequestCardView(
        {
            "id": 42,
            "status": "ATENDIMENTO_ASSUMIDO",
            "request_origin": "EXISTING_DECLARATION",
        }
    )

    assert [item.label for item in view.children] == [
        "Chamar para DP",
        "Validar tag existente",
        "Mais ações",
    ]


@pytest.mark.asyncio
async def test_terminal_request_card_has_no_live_controls() -> None:
    view = TagRequestCardView(
        {"id": 42, "status": "CONCLUIDO", "request_origin": "SET_REQUEST"}
    )

    assert view.children == []
    assert view.is_persistent()
