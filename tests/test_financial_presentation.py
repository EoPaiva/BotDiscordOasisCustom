from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import cogs.financial_aid_commands as financial_commands
from choque.config import Branding
from choque.errors import ValidationError
from cogs.financial_aid_commands import (
    ContributionAdminView,
    FinancialAdminPanelView,
    FinancialAidPanelView,
    FinancialConfigView,
    FinancialProjectAdminView,
    PixConfigurationModal,
    PixDisclosureView,
    SuggestionCategoryView,
    SuggestionModal,
    financial_contribution_highlight_embed,
    require_private_financial_admin_channel,
)

from .conftest import GUILD_ID


def _labels(view):
    return [item.label for item in view.children]


@pytest.mark.asyncio
async def test_public_financial_panel_is_persistent_and_has_the_five_safe_actions():
    view = FinancialAidPanelView()

    assert view.timeout is None
    assert _labels(view) == [
        "Doar",
        "Metas",
        "Prestação de contas",
        "Sugerir melhoria",
        "Apoiadores",
    ]
    assert all(item.custom_id and item.custom_id.startswith("choque:financial:") for item in view.children)


@pytest.mark.asyncio
async def test_financial_admin_panel_exposes_only_operational_areas_not_member_actions():
    view = FinancialAdminPanelView()

    assert view.timeout is None
    assert _labels(view) == [
        "Metas",
        "Contribuições",
        "Despesa",
        "Relatórios",
        "Honrarias",
        "Sugestões",
        "Configurar",
    ]


@pytest.mark.asyncio
async def test_financial_configuration_can_publish_or_move_panels_without_text_commands():
    assert _labels(FinancialConfigView()) == [
        "Configurar PIX",
        "Cargo de honraria",
        "Criar cargos simbólicos",
        "Canal público",
        "Painel administrativo",
        "Criar central pública",
    ]


@pytest.mark.asyncio
async def test_admin_panel_destination_requires_canonical_private_administration_channel():
    default_role = object()
    settings = SimpleNamespace(
        get=AsyncMock(return_value={"categories": {"admin": "800"}})
    )
    bot = SimpleNamespace(services=SimpleNamespace(settings=settings))
    guild = SimpleNamespace(id=GUILD_ID, default_role=default_role)

    def channel(*, category_id: int, view_channel: bool | None):
        return SimpleNamespace(
            category_id=category_id,
            overwrites_for=lambda role: SimpleNamespace(view_channel=view_channel),
        )

    await require_private_financial_admin_channel(
        bot, guild, channel(category_id=800, view_channel=False)
    )
    with pytest.raises(ValidationError, match="categoria Administração"):
        await require_private_financial_admin_channel(
            bot, guild, channel(category_id=801, view_channel=False)
        )
    with pytest.raises(ValidationError, match="@everyone"):
        await require_private_financial_admin_channel(
            bot, guild, channel(category_id=800, view_channel=None)
        )


@pytest.mark.asyncio
async def test_pix_configuration_keeps_the_secure_key_optional_when_already_configured():
    modal = PixConfigurationModal()
    key_field = next(item for item in modal.children if item.label.startswith("Chave PIX"))

    assert key_field.required is False
    assert "opcional" in key_field.label.lower()


@pytest.mark.asyncio
async def test_pix_disclosure_is_persistent_and_cancel_is_safe_and_idempotent(monkeypatch):
    view = PixDisclosureView(payload_available=False)
    items = {item.label: item for item in view.children}

    assert view.timeout is None
    assert items["Copiar chave PIX"].custom_id == "choque:financial:pix:copy-key:v1"
    assert items["Copiar Pix Copia e Cola"].custom_id == "choque:financial:pix:copy-payload:v1"
    assert items["Já realizei o PIX"].custom_id == "choque:financial:pix:declared:v1"
    assert items["Cancelar"].custom_id == "choque:financial:pix:cancel:v1"
    assert items["Copiar Pix Copia e Cola"].disabled is True
    assert str(items["Cancelar"].emoji) == "❌"

    authorize = AsyncMock()
    monkeypatch.setattr(financial_commands, "require_financial_member", authorize)
    response = SimpleNamespace(defer=AsyncMock())
    interaction = SimpleNamespace(
        response=response,
        delete_original_response=AsyncMock(),
    )

    # Repeated delivery of the persistent callback must remain a no-op from the
    # financial domain's perspective and simply close the ephemeral UI again.
    await items["Cancelar"].callback(interaction)
    await items["Cancelar"].callback(interaction)

    assert response.defer.await_count == 2
    response.defer.assert_awaited_with()
    assert interaction.delete_original_response.await_count == 2
    authorize.assert_not_awaited()


def _highlight_snapshot(**overrides):
    snapshot = {
        "id": 41,
        "status": "CONFIRMADA",
        "visibility": "ANONIMO",
        "public_amount": False,
        "discord_id": None,
        "member_name": "Apoiador anônimo",
        "amount_cents": None,
        "confirmed_at": 1_700_000_000_000,
        "reversed_at": None,
        "reversal_reason": None,
        "project_id": None,
        "project_name": None,
        "project_public_code": None,
        "project_target_cents": None,
        "project_collected_cents": None,
        "honor_titles": ["💎 Apoiador da CHOQUE"],
        "achievement_titles": [],
    }
    snapshot.update(overrides)
    return snapshot


def _embed_fields(embed):
    return {field.name: field.value for field in embed.fields}


def test_financial_highlight_keeps_anonymous_identity_and_amount_private():
    bot = SimpleNamespace(config=SimpleNamespace(branding=Branding()))
    embed = financial_contribution_highlight_embed(
        bot,
        _highlight_snapshot(),
        member=None,
        notification_id=73,
    )
    fields = _embed_fields(embed)

    assert fields["Apoiador"] == "◈ Contribuição anônima"
    assert fields["Valor"] == "Preservado por privacidade"
    assert "Militar" not in fields
    assert embed.thumbnail.url is None
    assert "Destaque financeiro da contribuição #41" in embed.footer.text
    assert "Notificação financeira #73" in embed.footer.text


def test_financial_highlight_shows_public_identity_but_amount_only_with_consent():
    bot = SimpleNamespace(config=SimpleNamespace(branding=Branding()))
    member = SimpleNamespace(display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"))
    public = _highlight_snapshot(
        visibility="PUBLICO",
        discord_id=395061579101503491,
        member_name="Paiva",
    )

    hidden_amount = financial_contribution_highlight_embed(
        bot, public, member=member, notification_id=74
    )
    hidden_fields = _embed_fields(hidden_amount)
    assert hidden_fields["Militar"] == "<@395061579101503491>"
    assert hidden_fields["Identificação"] == "Paiva"
    assert hidden_fields["Valor"] == "Preservado por privacidade"
    assert hidden_amount.thumbnail.url == "https://cdn.example/avatar.png"

    disclosed_amount = financial_contribution_highlight_embed(
        bot,
        {**public, "public_amount": True, "amount_cents": 2500},
        member=member,
        notification_id=75,
    )
    assert _embed_fields(disclosed_amount)["Valor"] == "R$ 25.00"


@pytest.mark.asyncio
async def test_project_admin_view_allows_only_valid_status_transitions():
    planning = FinancialProjectAdminView(1, 1, "EM_PLANEJAMENTO")
    running = FinancialProjectAdminView(1, 1, "EM_ANDAMENTO")
    finished = FinancialProjectAdminView(1, 1, "CONCLUIDA")

    planning_items = {item.label: item for item in planning.children}
    running_items = {item.label: item for item in running.children}
    finished_items = {item.label: item for item in finished.children}

    assert not planning_items["Ativar / retomar"].disabled
    assert planning_items["Suspender"].disabled
    assert not running_items["Suspender"].disabled
    assert finished_items["Ativar / retomar"].disabled
    assert finished_items["Concluir"].disabled
    assert finished_items["Cancelar"].disabled


@pytest.mark.asyncio
async def test_suggestion_flow_keeps_category_choice_and_optional_reference_separate():
    category_view = SuggestionCategoryView()
    category_select = category_view.children[0]
    modal = SuggestionModal("SISTEMA")

    assert len(category_select.options) >= 4
    assert [item.label for item in modal.children] == [
        "Título",
        "Descrição",
        "Valor estimado (opcional)",
        "Motivo",
        "Link de referência (opcional)",
    ]


@pytest.mark.asyncio
async def test_contribution_admin_exposes_cancel_only_while_pending():
    pending = {item.label: item for item in ContributionAdminView(1, 1, "PENDENTE").children}
    confirmed = {item.label: item for item in ContributionAdminView(1, 2, "CONFIRMADA").children}

    assert not pending["Cancelar declaração"].disabled
    assert confirmed["Cancelar declaração"].disabled
