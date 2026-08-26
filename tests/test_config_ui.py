from __future__ import annotations

import json

import pytest

from choque.models import RbacProfile
from choque.rbac import PROFILE_PERMISSIONS
from choque.settings import MODULE_DEFAULTS
from cogs.activity_commands import ActivityPanelView
from cogs.career_commands import CareerPanelView
from cogs.config_ui import (
    CHANNEL_SETTINGS,
    ChannelBrowserView,
    ChannelChoice,
    ChannelSettingsView,
    ConfigurationMenuView,
    ModulesConfigurationView,
    PanelsConfigurationView,
    RanksConfigurationView,
    RankSyncRulesModal,
    RoleBrowserView,
    RoleChoice,
    RolesConfigurationView,
    RulesModal,
    detect_military_rank_roles,
    paginate_items,
    reconcile_military_rank_roles,
    search_channel_choices,
    search_role_choices,
    validate_minimum_patrol_minutes,
)
from cogs.discipline_commands import DisciplineAdminView, DisciplinePanelView, ExonerationModal
from cogs.personnel_commands import (
    PersonnelAdminView,
    PersonnelDisciplineView,
    PersonnelEffectiveView,
    PersonnelProcessesView,
    PersonnelServiceView,
    RankingPeriodView,
    RankRegistrationComplianceView,
    RegistrationAdminView,
    RegistrationDirectoryEditModal,
    RegistrationDirectoryStateModal,
    RegistrationDirectoryView,
)
from cogs.request_commands import RequestPanelView
from cogs.ticket_commands import (
    OtherSubjectModal,
    RecruitmentAdminPanelView,
    RecruitmentPanelView,
    TicketAdminView,
    TicketPanelView,
)
from cogs.training_commands import (
    CourseCatalogView,
    TrainingAdminView,
    TrainingEventView,
    TrainingPanelView,
)


@pytest.mark.asyncio
async def test_configuration_menu_is_persistent_and_has_complete_layout():
    view = ConfigurationMenuView()
    assert view.timeout is None
    assert len(view.children) == 8
    custom_ids = [item.custom_id for item in view.children]
    assert len(custom_ids) == len(set(custom_ids))
    assert all(custom_id and custom_id.startswith("choque:config:") for custom_id in custom_ids)


@pytest.mark.asyncio
async def test_configuration_submenus_fit_discord_component_limits():
    channels = ChannelSettingsView()
    roles = RolesConfigurationView()
    panels = PanelsConfigurationView()
    modules = ModulesConfigurationView(MODULE_DEFAULTS)
    assert len(channels.children) == 25
    assert len(CHANNEL_SETTINGS) == 25
    assert len(roles.children) == 8
    assert len(panels.children) == 15
    assert len(modules.children) == 12
    for view in (channels, roles, panels, modules):
        assert all(0 <= (item.row or 0) <= 4 for item in view.children)


def make_channel_choices(total: int) -> list[ChannelChoice]:
    return [
        ChannelChoice(
            channel_id=1_000 + index,
            name=f"canal-{index:02d}",
            category_name="Categoria",
            category_position=0,
            channel_position=index,
        )
        for index in range(total)
    ]


@pytest.mark.asyncio
async def test_channel_browser_pages_include_all_channels_and_stay_under_discord_limit():
    choices = make_channel_choices(63)
    assert [len(paginate_items(choices, page)[0]) for page in range(3)] == [25, 25, 13]

    first_page = ChannelBrowserView(
        action="SETTING",
        action_key="audit_channel_id",
        label="Canal de auditoria",
        choices=choices,
        selected_id=None,
    )
    last_page = first_page.clone(page=2)
    first_select = next(item for item in first_page.children if hasattr(item, "options"))
    last_select = next(item for item in last_page.children if hasattr(item, "options"))
    assert len(first_select.options) == 25
    assert len(last_select.options) == 13
    assert first_page.page_count == 3


@pytest.mark.asyncio
async def test_role_browser_pages_include_all_roles_and_stay_under_discord_limit():
    choices = [RoleChoice(2_000 + index, f"cargo-{index:02d}", index, False) for index in range(91)]
    assert [len(paginate_items(choices, page)[0]) for page in range(4)] == [25, 25, 25, 16]

    first_page = RoleBrowserView(
        action="SETTING",
        action_key="member_role_id",
        label="Cargo de membro",
        choices=choices,
        selected_id=None,
    )
    last_page = first_page.clone(page=3)
    first_select = next(item for item in first_page.children if hasattr(item, "options"))
    last_select = next(item for item in last_page.children if hasattr(item, "options"))
    assert len(first_select.options) == 25
    assert len(last_select.options) == 16
    assert first_page.page_count == 4


def test_channel_and_role_search_accept_partial_names_categories_and_ids():
    channels = make_channel_choices(3) + [ChannelChoice(9999, "logs-bot", "Administracao", 1, 0)]
    roles = [RoleChoice(8888, "Comando Geral", 10, False)]
    assert [item.channel_id for item in search_channel_choices(channels, "logs")] == [9999]
    assert [item.channel_id for item in search_channel_choices(channels, "administracao")] == [9999]
    assert [item.channel_id for item in search_channel_choices(channels, "1001")] == [1001]
    assert [item.role_id for item in search_role_choices(roles, "comando")] == [8888]
    assert [item.role_id for item in search_role_choices(roles, "8888")] == [8888]


def test_military_rank_detection_ignores_decorative_and_managed_roles():
    roles = [
        RoleChoice(index, name, index, False)
        for index, name in enumerate(
            (
                "RECRUTA",
                "SOLDADO",
                "CABO",
                "PRAÇAS",
                "PRAÇAS GRADUADOS",
                "3º SARGENTO",
                "2º SARGENTO",
                "1º SARGENTO",
                "SUB TENENTE",
                "ᴏғɪᴄɪᴀɪs",
                "CADETE",
                "ASPIRANTE",
                "2º TENENTE",
                "1º TENENTE",
                "CAPITÃO",
                "MAJOR",
                "TENENTE-CORONEL",
                "CORONEL",
                "Xenon",
                "ALTO COMANDO★",
                "SUB COMANDANTE",
                "COMANDANTE",
                "COMANDANTE GERAL",
            ),
            start=1,
        )
    ]
    roles.extend(
        [
            RoleChoice(90, "═══ PATENTES ═══", 90, False),
            RoleChoice(91, "Soldado", 91, True),
        ]
    )
    detected = detect_military_rank_roles(roles)
    assert [(item.name, prefix) for item, prefix in detected] == [
        ("RECRUTA", "[REC]"),
        ("SOLDADO", "[SD]"),
        ("CABO", "[CB]"),
        ("3º SARGENTO", "[3SGT]"),
        ("2º SARGENTO", "[2SGT]"),
        ("1º SARGENTO", "[1SGT]"),
        ("SUB TENENTE", "[ST]"),
        ("CADETE", "[CAD]"),
        ("ASPIRANTE", "[ASP]"),
        ("2º TENENTE", "[2TEN]"),
        ("1º TENENTE", "[1TEN]"),
        ("CAPITÃO", "[CAP]"),
        ("MAJOR", "[MAJ]"),
        ("TENENTE-CORONEL", "[TC]"),
        ("CORONEL", "[CEL]"),
        ("SUB COMANDANTE", "[SCMD]"),
        ("COMANDANTE", "[CMD]"),
        ("COMANDANTE GERAL", "[CMDG]"),
    ]


@pytest.mark.asyncio
async def test_rank_reconciliation_rebuilds_real_order_and_preserves_ignored_rows(
    service_bundle,
):
    database = service_bundle["database"]
    choices = [
        RoleChoice(index, name, index, False)
        for index, name in enumerate(
            (
                "RECRUTA",
                "SOLDADO",
                "CABO",
                "PRAÇAS",
                "PRAÇAS GRADUADOS",
                "3º SARGENTO",
                "2º SARGENTO",
                "1º SARGENTO",
                "SUB TENENTE",
                "ᴏғɪᴄɪᴀɪs",
                "CADETE",
                "ASPIRANTE",
                "2º TENENTE",
                "1º TENENTE",
                "CAPITÃO",
                "MAJOR",
                "TENENTE-CORONEL",
                "CORONEL",
                "Xenon",
                "ALTO COMANDO★",
                "SUB COMANDANTE",
                "COMANDANTE",
                "COMANDANTE GERAL",
            ),
            start=1,
        )
    ]
    old_role_ids = (1, 2, 3, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18)
    for level, role_id in enumerate(old_role_ids, start=1):
        role = next(choice for choice in choices if choice.role_id == role_id)
        await database.execute(
            """
            INSERT INTO ranks(
                guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
            ) VALUES (?, ?, '', ?, ?, 'MEMBRO', 1)
            """,
            (123, role.name, level, role.role_id),
        )
    await database.execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
        ) VALUES (123, 'ALTO COMANDO★', '', 16, 20, 'MEMBRO', 1)
        """
    )

    created, updated, detected = await reconcile_military_rank_roles(
        database,
        service_bundle["audit"],
        guild_id=123,
        choices=choices,
        actor_id=456,
    )

    active = await database.fetchall(
        "SELECT level, name FROM ranks WHERE guild_id=123 AND active=1 ORDER BY level"
    )
    assert created == 3
    assert updated == 15
    assert len(detected) == 18
    assert [row["level"] for row in active] == list(range(1, 19))
    assert [row["name"] for row in active] == [
        choice.name
        for choice in choices
        if choice.name
        not in {"PRAÇAS", "PRAÇAS GRADUADOS", "ᴏғɪᴄɪᴀɪs", "Xenon", "ALTO COMANDO★"}
    ]
    ignored = await database.fetchone(
        "SELECT active, level FROM ranks WHERE guild_id=123 AND discord_role_id=20"
    )
    assert ignored["active"] == 0
    assert ignored["level"] == 19
    audit = await database.fetchone(
        "SELECT after_json FROM audit_logs WHERE action='RANKS_IMPORTED_FROM_DISCORD'"
    )
    payload = json.loads(audit["after_json"])
    assert payload["ignored_role_ids"] == [4, 5, 10, 19, 20]
    assert payload["deactivated"] == 1
    reconciliation = await database.fetchone(
        """
        SELECT j.id, j.mode, j.status, o.action_type, o.payload_json
        FROM identity_reconciliation_jobs j
        JOIN web_action_outbox o ON o.correlation_id=j.correlation_id
        WHERE j.guild_id=123
        """
    )
    assert reconciliation is not None
    assert (reconciliation["mode"], reconciliation["status"]) == ("APPLY", "PENDING")
    assert reconciliation["action_type"] == "IDENTITY_RECONCILE_BULK"
    assert json.loads(reconciliation["payload_json"])["source"] == "RANK_CATALOG_IMPORTED"
    assert payload["reconciliation_job_id"] == reconciliation["id"]

    mappings = await database.fetchall(
        """
        SELECT discord_role_id, enabled
        FROM discord_role_mappings
        WHERE guild_id=123 AND mapping_type='RANK'
        ORDER BY priority
        """
    )
    assert [row["discord_role_id"] for row in mappings if row["enabled"]] == [
        choice.role_id
        for choice in choices
        if choice.name
        not in {"PRAÇAS", "PRAÇAS GRADUADOS", "ᴏғɪᴄɪᴀɪs", "Xenon", "ALTO COMANDO★"}
    ]
    ignored_mapping = await database.fetchone(
        """
        SELECT enabled
        FROM discord_role_mappings
        WHERE guild_id=123 AND discord_role_id=20 AND mapping_type='RANK'
        """
    )
    assert ignored_mapping["enabled"] == 0


@pytest.mark.asyncio
async def test_rank_role_adapter_moves_conflict_and_disables_removed_mapping(service_bundle):
    database = service_bundle["database"]
    settings = service_bundle["settings"]
    first_rank_id = await database.execute(
        """
        INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
        VALUES (123, 'Soldado', '[SD]', 1, 'MEMBRO', 1)
        """
    )
    second_rank_id = await database.execute(
        """
        INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
        VALUES (123, 'Cabo', '[CB]', 2, 'GRADUADO', 1)
        """
    )

    await settings.set_rank_role_mapping(123, first_rank_id, 9_001, 456)
    await settings.set_rank_role_mapping(123, second_rank_id, 9_001, 456)

    ranks = await database.fetchall(
        "SELECT id, discord_role_id FROM ranks WHERE id IN (?, ?) ORDER BY id",
        (first_rank_id, second_rank_id),
    )
    assert [row["discord_role_id"] for row in ranks] == [None, 9_001]
    canonical = await database.fetchone(
        """
        SELECT rank_id, enabled, internal_code
        FROM discord_role_mappings
        WHERE guild_id=123 AND discord_role_id=9001 AND mapping_type='RANK'
        """
    )
    assert dict(canonical) == {
        "rank_id": second_rank_id,
        "enabled": 1,
        "internal_code": f"RANK_{second_rank_id}",
    }

    await settings.set_rank_role_mapping(123, second_rank_id, None, 456)

    removed_rank = await database.fetchone(
        "SELECT discord_role_id FROM ranks WHERE id=?",
        (second_rank_id,),
    )
    removed_mapping = await database.fetchone(
        """
        SELECT enabled
        FROM discord_role_mappings
        WHERE guild_id=123 AND discord_role_id=9001 AND mapping_type='RANK'
        """
    )
    assert removed_rank["discord_role_id"] is None
    assert removed_mapping["enabled"] == 0


@pytest.mark.asyncio
async def test_legacy_rank_import_populates_canonical_mapping(service_bundle, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "GUILD_ID": "987",
                "HIERARQUIA": [
                    {"display_name": "Soldado:", "prefix": "[SD]", "role_id": "7654"}
                ],
            }
        ),
        encoding="utf-8",
    )

    imported_guild_id = await service_bundle["settings"].import_legacy(config_path)

    assert imported_guild_id == 987
    rank = await service_bundle["database"].fetchone(
        "SELECT id, discord_role_id FROM ranks WHERE guild_id=987 AND level=1"
    )
    mapping = await service_bundle["database"].fetchone(
        """
        SELECT rank_id, enabled
        FROM discord_role_mappings
        WHERE guild_id=987 AND discord_role_id=7654 AND mapping_type='RANK'
        """
    )
    assert rank["discord_role_id"] == 7654
    assert dict(mapping) == {"rank_id": rank["id"], "enabled": 1}


@pytest.mark.asyncio
async def test_rules_modal_is_prefilled_from_current_settings():
    modal = RulesModal(
        grace=60,
        minimum_patrol=15,
        goal=360,
        timezone_name="America/Sao_Paulo",
    )
    assert modal.grace.default == "60"
    assert modal.minimum_patrol.default == "15"
    assert modal.goal.default == "360"
    assert modal.timezone_name.default == "America/Sao_Paulo"


def test_minimum_patrol_rule_accepts_only_safe_range() -> None:
    assert validate_minimum_patrol_minutes("5") == 5
    assert validate_minimum_patrol_minutes("120") == 120
    for invalid in ("0", "4", "121", "-1", "quinze"):
        with pytest.raises(Exception, match="5 e 120"):
            validate_minimum_patrol_minutes(invalid)


@pytest.mark.asyncio
async def test_rank_sync_rules_are_available_without_commands() -> None:
    view = RanksConfigurationView()
    modal = RankSyncRulesModal(
        enforce_nickname=True,
        auto_remove=False,
        missing_policy="KEEP_LAST",
    )
    assert {item.label for item in view.children} >= {"Sincronização"}
    assert modal.enforce_nickname.default == "sim"
    assert modal.auto_remove.default == "não"
    assert modal.missing_policy.default == "KEEP_LAST"


@pytest.mark.asyncio
async def test_phase_four_and_five_panels_are_persistent_and_have_stable_custom_ids():
    persistent_views = [
        PersonnelAdminView(),
        ActivityPanelView(),
        RequestPanelView(),
        CareerPanelView(),
        DisciplinePanelView(),
        RankingPeriodView(persistent=True),
        TrainingPanelView(),
        CourseCatalogView(),
        TrainingEventView(42),
        RecruitmentPanelView(),
        TicketPanelView(),
        RecruitmentAdminPanelView(),
    ]
    assert [len(view.children) for view in persistent_views] == [
        6,
        3,
        8,
        4,
        2,
        4,
        4,
        9,
        3,
        4,
        5,
        3,
    ]
    for view in persistent_views:
        assert view.timeout is None
        custom_ids = [item.custom_id for item in view.children]
        assert all(custom_ids)
        assert len(custom_ids) == len(set(custom_ids))
        assert all(custom_id.startswith("choque:") for custom_id in custom_ids)
    admin = TrainingAdminView()
    assert admin.timeout == 300
    assert len(admin.children) == 5
    assert "Painéis por curso" in {item.label for item in admin.children}

    ticket_panel = TicketPanelView()
    assert "choque:ticket:other:v1" in {item.custom_id for item in ticket_panel.children}
    career_panel = CareerPanelView()
    assert "choque:career:officer:v1" in {
        item.custom_id for item in career_panel.children
    }


@pytest.mark.asyncio
async def test_personnel_admin_is_grouped_without_hiding_existing_areas():
    root_labels = {item.label for item in PersonnelAdminView().children}
    assert root_labels == {
        "Efetivo",
        "Disciplina",
        "Processos",
        "Serviço e operações",
        "Tags",
        "Atualizar resumo",
    }
    submenu_labels = {
        item.label
        for view in (
            PersonnelEffectiveView(),
            PersonnelDisciplineView(),
            PersonnelProcessesView(),
            PersonnelServiceView(),
        )
        for item in view.children
    }
    assert submenu_labels >= {
        "Portaria e cadastros",
        "Carreira e patentes",
        "Histórico do membro",
        "Ranking",
        "Atividade",
        "Gestão disciplinar",
        "Exonerar membro",
        "Solicitações",
        "Treinamentos",
        "Atendimentos",
        "Revisões de ponto",
        "Operações e patrulhas",
        "Voltar ao início",
    }
    assert "Exonerar membro" in {item.label for item in DisciplineAdminView().children}
    modal = ExonerationModal(42)
    assert modal.title == "Confirmar exoneração"
    assert [item.label for item in modal.children] == [
        "Motivo obrigatório",
        "Digite EXONERAR para confirmar",
    ]


@pytest.mark.asyncio
async def test_high_command_registration_manager_exposes_safe_complete_controls():
    permission = "registration.directory.manage"
    assert permission in PROFILE_PERMISSIONS[RbacProfile.HIGH_COMMAND.value]
    assert permission not in PROFILE_PERMISSIONS[RbacProfile.COMMAND.value]
    assert "Gerenciar cadastros" in {item.label for item in RegistrationAdminView().children}
    rows = [
        {
            "id": index + 1,
            "mta_nick": f"Membro {index:02d}",
            "discord_nick": None,
            "discord_id": 1_000 + index,
            "status": "REGISTERED",
            "rank_name": "Soldado",
            "bgr_id": str(index),
        }
        for index in range(25)
    ]
    view = RegistrationDirectoryView(
        {
            "rows": rows,
            "query": "",
            "page": 0,
            "page_size": 25,
            "pages": 2,
            "total": 26,
        }
    )
    select = next(item for item in view.children if hasattr(item, "options"))
    assert len(select.options) == 25
    assert {item.label for item in view.children if hasattr(item, "label")} >= {
        "Anterior",
        "Pesquisar",
        "Próxima",
        "Atualizar",
    }
    edit = RegistrationDirectoryEditModal(
        {"id": 1, "mta_nick": "Paiva", "bgr_id": "77", "unit": "CHOQUE"}
    )
    deactivate = RegistrationDirectoryStateModal(1, action="DEACTIVATE")
    reopen = RegistrationDirectoryStateModal(1, action="REOPEN")
    assert [item.label for item in edit.children] == [
        "Nick BGR",
        "ID BGR",
        "Unidade",
        "Motivo obrigatório",
    ]
    assert deactivate.confirmation.placeholder == "DESATIVAR"
    assert reopen.confirmation.placeholder == "REABRIR"


@pytest.mark.asyncio
async def test_rank_without_registration_has_visible_high_command_panel():
    assert "Sem cadastro • 72h" in {item.label for item in RegistrationAdminView().children}
    view = RankRegistrationComplianceView(
        {
            "rows": [],
            "page": 0,
            "page_size": 25,
            "pages": 1,
            "total": 0,
        }
    )
    assert {item.label for item in view.children} == {
        "Anterior",
        "Processar agora",
        "Próxima",
        "Atualizar",
    }


@pytest.mark.asyncio
async def test_other_subject_ticket_has_modal_public_button_and_admin_queue():
    panel = TicketPanelView()
    admin = TicketAdminView()
    modal = OtherSubjectModal()

    assert {item.label for item in panel.children} >= {"Outro assunto"}
    assert {item.label for item in admin.children} >= {"Outros assuntos", "Todos"}
    assert modal.title == "Outro assunto"
    assert len(modal.children) == 3
    assert [item.required for item in modal.children] == [True, True, False]
