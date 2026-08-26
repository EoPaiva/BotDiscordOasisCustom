from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from choque.bot import COGS
from choque.config import Branding
from choque.web_urls import recruitment_portal_url, recruitment_status_url
from cogs.medals_system import MEDALS, MedalsPanelView, build_medals_embed
from cogs.member_commands import (
    RegistrationModal,
    RegistrationPanelView,
    build_registration_panel_embed,
)
from cogs.shift_commands import PointPanelView, build_point_panel_embed
from cogs.ticket_commands import (
    PartnershipLandingView,
    RecruitmentPanelView,
    TransferLandingView,
    build_partnership_landing_embed,
    build_partnership_links,
    build_recruitment_landing_embed,
    build_terms_landing_embed,
    build_transfer_landing_embed,
)


def bot_stub():
    return SimpleNamespace(config=SimpleNamespace(branding=Branding()))


def custom_ids(view) -> set[str]:
    return {str(item.custom_id) for item in view.children if item.custom_id}


class SettingsStub:
    async def get(self, guild_id: int, key: str):
        assert guild_id == 123
        return {
            "recruitment_requirements_channel_id": 456,
            "registration_panel_channel_id": 789,
        }[key]


@pytest.mark.asyncio
async def test_registration_button_always_opens_two_field_modal_without_querying_status() -> None:
    class ModulesStub:
        async def require_enabled(self, guild_id: int, module: str) -> None:
            assert guild_id == 123
            assert module == "REGISTRATION"

    class RegistrationGateStub:
        async def registration_intent(self, *_args, **_kwargs):
            pytest.fail("o clique não deve consultar intent/status antes de abrir o modal")

    class ResponseStub:
        modal = None

        async def send_modal(self, modal) -> None:
            self.modal = modal

    response = ResponseStub()
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=123),
        user=SimpleNamespace(id=456),
        client=SimpleNamespace(
            services=SimpleNamespace(
                modules=ModulesStub(),
                registration_gate=RegistrationGateStub(),
            )
        ),
        response=response,
    )
    view = RegistrationPanelView()
    register_button = next(
        item
        for item in view.children
        if item.custom_id == "choque:member:register:v3"
    )

    await register_button.callback(interaction)

    assert isinstance(response.modal, RegistrationModal)
    assert [item.label for item in response.modal.children] == [
        "Nick utilizado no BGR",
        "ID no BGR",
    ]


@pytest.mark.asyncio
async def test_registration_and_point_panels_are_detailed_and_keep_persistent_actions() -> None:
    registration = build_registration_panel_embed(bot_stub())
    point = build_point_panel_embed(bot_stub())

    assert registration.title == "🛡️ PORTARIA DIGITAL • CHOQUE - BGR"
    assert len(registration.fields) == 5
    assert "Realizar cadastro" in (registration.description or "")
    assert "Candidatar-me agora" not in (registration.description or "")
    assert "VISITANTE" not in str(registration.to_dict())
    assert custom_ids(RegistrationPanelView()) == {
        "choque:member:identify:v2",
        "choque:member:register:v3",
    }
    assert [item.label for item in RegistrationPanelView().children] == [
        "Identificar vínculo",
        "Realizar cadastro",
    ]
    assert not [item for item in RegistrationPanelView().children if item.url]

    registration_modal = RegistrationModal()
    assert [item.label for item in registration_modal.children] == [
        "Nick utilizado no BGR",
        "ID no BGR",
    ]

    public_recruitment = RecruitmentPanelView("https://example.test")
    assert {item.label for item in public_recruitment.children} == {
        "Candidatar-me agora",
        "Acompanhar candidatura",
        "Entrada por indicação",
        "Requisitos",
    }
    assert {item.url for item in public_recruitment.children if item.url} == {
        "https://example.test/recrutamento",
        "https://example.test/minha-candidatura",
    }
    assert custom_ids(public_recruitment) == {
        "choque:recruitment:direct-indication:v1",
        "choque:recruitment:requirements:v1",
    }

    scoped_recruitment = RecruitmentPanelView("https://example.test/recrutamento")
    assert {item.url for item in scoped_recruitment.children if item.url} == {
        "https://example.test/recrutamento",
        "https://example.test/minha-candidatura",
    }

    assert point.title == "⏱️ CONTROLE OPERACIONAL DE SERVIÇO"
    assert len(point.fields) == 6
    assert any(field.name == "🎯 Validação mínima de patrulha" for field in point.fields)
    assert "fora da call nunca é contabilizado" in point.fields[1].value
    assert "não precisa abrir ou fechar o ponto manualmente" in (point.description or "").lower()
    assert custom_ids(PointPanelView()) == {
        "choque:shift:status:v1",
        "choque:shift:hours:v1",
        "choque:shift:history:v1",
    }


def test_recruitment_urls_accept_root_or_already_scoped_configuration() -> None:
    assert recruitment_portal_url("https://example.test") == (
        "https://example.test/recrutamento"
    )
    assert recruitment_portal_url("https://example.test/recrutamento/") == (
        "https://example.test/recrutamento"
    )
    assert recruitment_status_url("https://example.test") == (
        "https://example.test/minha-candidatura"
    )
    assert recruitment_status_url("https://example.test/recrutamento") == (
        "https://example.test/minha-candidatura"
    )


@pytest.mark.asyncio
async def test_recruitment_landing_gives_visitors_one_unambiguous_starting_point() -> None:
    bot = SimpleNamespace(
        config=SimpleNamespace(branding=Branding()),
        services=SimpleNamespace(settings=SettingsStub()),
    )
    embed = await build_recruitment_landing_embed(bot, SimpleNamespace(id=123))

    assert embed.title == "🪖 QUERO ENTRAR PARA A CHOQUE - BGR"
    assert "não precisa procurar outro canal" in (embed.description or "").lower()
    assert "Candidatar-me agora" in embed.fields[0].value
    assert "<#456>" in embed.fields[1].value
    assert "<#789>" in embed.fields[3].value


@pytest.mark.asyncio
async def test_medals_panel_preserves_all_seven_historical_decorations() -> None:
    embed = build_medals_embed(bot_stub())
    view = MedalsPanelView()

    assert len(MEDALS) == 7
    assert len({medal.role_id for medal in MEDALS}) == 7
    assert len(embed.fields) == 9
    assert len(view.children) == 1
    assert len(view.children[0].options) == 7
    assert view.children[0].custom_id == "choque:medals:select:v1"
    assert "cogs.medals_system" not in COGS


def test_structural_scripts_do_not_recreate_intentionally_removed_medals() -> None:
    root = Path(__file__).parents[1]
    for relative_path in (
        "scripts/provision_discord_layout.py",
        "scripts/remodel_discord_layout.py",
    ):
        content = (root / relative_path).read_text(encoding="utf-8")
        assert "info.medals" not in content
        assert "🏅│medalhas" not in content


@pytest.mark.asyncio
async def test_partnership_category_has_three_distinct_landing_surfaces() -> None:
    transfer = build_transfer_landing_embed(bot_stub())
    partnership = build_partnership_landing_embed(bot_stub())
    terms = build_terms_landing_embed(bot_stub())
    links = build_partnership_links(1, 2, 3, 4)

    assert "TRANSFERÊNCIA" in (transfer.title or "")
    assert "RELAÇÕES INSTITUCIONAIS" in (partnership.title or "")
    assert "TERMOS INSTITUCIONAIS" in (terms.title or "")
    assert custom_ids(TransferLandingView()) == {
        "choque:partnerships:transfer:v1",
        "choque:partnerships:transfer:mine:v1",
    }
    assert custom_ids(PartnershipLandingView()) == {
        "choque:partnerships:proposal:v1",
        "choque:partnerships:proposal:mine:v1",
    }
    assert len(links.children) == 3
    assert all(
        item.url and item.url.startswith("https://discord.com/channels/1/")
        for item in links.children
    )
