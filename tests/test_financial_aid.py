from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from choque.audit import AuditService
from choque.config import Branding
from choque.database import Database
from choque.errors import ConflictError, ValidationError
from choque.financial_aid import FinancialAidService
from choque.settings import SettingsService
from cogs.financial_aid_commands import FinancialAidCommands

from .conftest import DISCORD_ID, GUILD_ID


@pytest.mark.asyncio
async def test_admin_pix_configuration_is_atomic_masked_audited_and_survives_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("FINANCIAL_PIX_KEY", raising=False)
    monkeypatch.delenv("PIX_KEY", raising=False)
    database_path = tmp_path / "financial-pix.db"
    database = Database(database_path)
    await database.open()
    settings = SettingsService(database)
    audit = AuditService(database, settings, Branding())
    finance = FinancialAidService(database, settings, audit, clock=lambda: 1_700_000_123_000)
    key = "pix-key-testing-123456789"

    with pytest.raises(ValidationError):
        await finance.configure_pix_configuration(
            GUILD_ID,
            actor_id=900,
            key=key,
            recipient_name="A",
            recipient_city="SAO PAULO",
        )
    assert await settings.get(GUILD_ID, "financial_pix_key") is None

    configured = await finance.configure_pix_configuration(
        GUILD_ID,
        actor_id=900,
        key=key,
        recipient_name="Choque BGR",
        recipient_city="Sao Paulo",
    )
    assert configured["configured"] is True
    assert configured["source"] == "ADMINISTRATIVE_SETTING"
    assert configured["masked_key"] != key
    assert configured["recipient_name"] == "CHOQUE BGR"
    assert configured["recipient_city"] == "SAO PAULO"
    audit_row = await database.fetchone(
        """
        SELECT actor_id, before_json, after_json, reason, occurred_at
        FROM financial_audit_events
        WHERE guild_id=? AND event_type='FINANCIAL_PIX_CONFIGURATION_UPDATED'
        """,
        (GUILD_ID,),
    )
    assert audit_row is not None
    audit_text = " ".join(str(audit_row[column] or "") for column in audit_row.keys())
    assert key not in audit_text
    assert "fingerprint" not in audit_text.lower()
    assert audit_row["actor_id"] == 900
    assert audit_row["occurred_at"] == 1_700_000_123_000

    await database.close()
    restarted_database = Database(database_path)
    await restarted_database.open()
    restarted_settings = SettingsService(restarted_database)
    restarted_finance = FinancialAidService(
        restarted_database,
        restarted_settings,
        AuditService(restarted_database, restarted_settings, Branding()),
    )
    restarted = await restarted_finance.pix_configuration_status(GUILD_ID)
    assert restarted["masked_key"] == configured["masked_key"]
    assert restarted["recipient_name"] == "CHOQUE BGR"
    assert await restarted_finance.pix_key(GUILD_ID) == key
    await restarted_database.close()


@pytest.mark.asyncio
async def test_pix_administrative_setting_wins_over_optional_environment_compatibility(service_bundle, monkeypatch):
    monkeypatch.delenv("FINANCIAL_PIX_KEY", raising=False)
    monkeypatch.delenv("PIX_KEY", raising=False)
    finance = service_bundle["financial_aid"]
    configured_key = "persisted-pix-key-123456"
    await finance.configure_pix_configuration(
        GUILD_ID,
        actor_id=900,
        key=configured_key,
        recipient_name="Choque BGR",
        recipient_city="Sao Paulo",
    )
    monkeypatch.setenv("FINANCIAL_PIX_KEY", "environment-pix-key-987654")

    status = await finance.pix_configuration_status(GUILD_ID)
    assert status["source"] == "ADMINISTRATIVE_SETTING"
    assert status["masked_key"] == finance.mask_pix_key(configured_key)
    assert await finance.pix_key(GUILD_ID) == configured_key
    assert await service_bundle["settings"].get(GUILD_ID, "financial_pix_key") == configured_key


@pytest.mark.asyncio
async def test_pix_environment_is_only_a_fallback_when_no_administrative_key_exists(service_bundle, monkeypatch):
    monkeypatch.setenv("FINANCIAL_PIX_KEY", "environment-pix-key-987654")
    finance = service_bundle["financial_aid"]

    status = await finance.pix_configuration_status(GUILD_ID)

    assert status["source"] == "ENVIRONMENT"
    assert await finance.pix_key(GUILD_ID) == "environment-pix-key-987654"


@pytest.mark.asyncio
async def test_panel_pair_configuration_is_atomic_and_audited(service_bundle):
    finance = service_bundle["financial_aid"]

    result = await finance.configure_panel_channels(
        GUILD_ID,
        actor_id=900,
        public_channel_id=111,
        admin_channel_id=222,
    )
    event = await service_bundle["database"].fetchone(
        "SELECT after_json FROM financial_audit_events WHERE event_type='FINANCIAL_PANEL_PAIR_CONFIGURED'"
    )

    assert result == {"public_channel_id": 111, "admin_channel_id": 222}
    assert await service_bundle["settings"].get(GUILD_ID, "financial_panel_channel_id") == 111
    assert await service_bundle["settings"].get(GUILD_ID, "financial_admin_channel_id") == 222
    assert event is not None and json.loads(event["after_json"])["admin_channel_id"] == 222


@pytest.mark.asyncio
async def test_pix_recipient_can_be_configured_without_replacing_secure_environment_key(service_bundle, monkeypatch):
    monkeypatch.setenv("FINANCIAL_PIX_KEY", "environment-pix-key-987654")
    finance = service_bundle["financial_aid"]

    updated = await finance.configure_pix_recipient(
        GUILD_ID,
        actor_id=900,
        recipient_name="Choque BGR",
        recipient_city="Sao Paulo",
    )
    status = await finance.pix_configuration_status(GUILD_ID)

    assert updated == {"recipient_name": "CHOQUE BGR", "recipient_city": "SAO PAULO"}
    assert status["source"] == "ENVIRONMENT"
    assert status["recipient_name"] == "CHOQUE BGR"
    assert status["recipient_city"] == "SAO PAULO"
    assert await service_bundle["settings"].get(GUILD_ID, "financial_pix_key") is None


def test_static_pix_payload_has_br_code_shape_crc_and_local_qr():
    payload = FinancialAidService.build_static_pix_payload(
        pix_key="pix-key-testing-123456789",
        recipient_name="Choque BGR",
        recipient_city="Sao Paulo",
    )

    assert payload.startswith("000201")
    assert "br.gov.bcb.pix" in payload
    assert "5303986" in payload
    assert "5802BR" in payload
    assert "540" not in payload
    assert payload[-8:-4] == "6304"
    assert payload[-4:] == FinancialAidService._crc16_ccitt(payload[:-4])

    qrcode = pytest.importorskip("qrcode")
    assert qrcode is not None
    image = FinancialAidService.pix_qr_png(payload)
    assert image.startswith(b"\x89PNG\r\n\x1a\n")


def test_static_pix_payload_accepts_only_positive_fixed_amounts():
    payload = FinancialAidService.build_static_pix_payload(
        pix_key="pix-key-testing-123456789",
        recipient_name="Choque BGR",
        recipient_city="Sao Paulo",
        amount_cents=1234,
    )
    assert "540512.34" in payload
    with pytest.raises(ValidationError, match="positivo"):
        FinancialAidService.build_static_pix_payload(
            pix_key="pix-key-testing-123456789",
            recipient_name="Choque BGR",
            recipient_city="Sao Paulo",
            amount_cents=0,
        )


@pytest.mark.asyncio
async def test_declared_contribution_is_exact_pending_and_idempotent(service_bundle):
    finance = FinancialAidService(
        service_bundle["database"],
        service_bundle["settings"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    project = await finance.create_project(
        GUILD_ID,
        actor_id=900,
        name="Nova Viatura ROCAM",
        description="Aquisição e configuração da viatura.",
        category="VIATURA",
        target_amount="800,00",
    )

    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="50,25",
        destination_kind="PROJETO",
        project_id=int(project["id"]),
        visibility="ANONIMO",
        observation="Apoio voluntário.",
        idempotency_key="discord:interaction:1",
    )
    duplicate = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="50,25",
        destination_kind="PROJETO",
        project_id=int(project["id"]),
        visibility="ANONIMO",
        observation="Apoio voluntário.",
        idempotency_key="discord:interaction:1",
    )

    assert contribution["id"] == duplicate["id"]
    assert contribution["amount_cents"] == 5025
    assert contribution["status"] == "PENDENTE"
    assert (await finance.project_snapshot(GUILD_ID, int(project["id"])))["collected_cents"] == 0
    with pytest.raises(ValidationError, match="positivo"):
        await finance.declare_contribution(
            GUILD_ID,
            DISCORD_ID,
            amount="0,00",
            destination_kind="FUNDO_GERAL",
            visibility="PUBLICO",
            idempotency_key="discord:interaction:zero",
        )


@pytest.mark.asyncio
async def test_confirmation_updates_project_once_and_closes_completed_target(service_bundle):
    finance = FinancialAidService(
        service_bundle["database"],
        service_bundle["settings"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    project = await finance.create_project(
        GUILD_ID,
        actor_id=900,
        name="Nova Plotagem",
        description="Projeto comunitário de plotagem.",
        category="PLOTAGEM",
        target_amount="100,00",
        start=True,
    )
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="100,00",
        destination_kind="PROJETO",
        project_id=int(project["id"]),
        visibility="PUBLICO",
        idempotency_key="discord:interaction:2",
    )

    confirmed = await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Recebimento conferido no extrato institucional.",
    )
    repeated = await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Recebimento conferido no extrato institucional.",
    )
    snapshot = await finance.project_snapshot(GUILD_ID, int(project["id"]))

    assert confirmed["status"] == "CONFIRMADA"
    assert repeated["id"] == confirmed["id"]
    assert snapshot["collected_cents"] == 10000
    assert snapshot["status"] == "CONCLUIDA"
    assert snapshot["remaining_cents"] == 0
    with pytest.raises(ConflictError, match="não aceita"):
        await finance.declare_contribution(
            GUILD_ID,
            DISCORD_ID,
            amount="1,00",
            destination_kind="PROJETO",
            project_id=int(project["id"]),
            visibility="PUBLICO",
            idempotency_key="discord:interaction:3",
        )


@pytest.mark.asyncio
async def test_ledger_is_append_only_and_reversal_never_deletes_history(service_bundle):
    finance = FinancialAidService(
        service_bundle["database"],
        service_bundle["settings"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="30.00",
        destination_kind="FUNDO_GERAL",
        visibility="ANONIMO",
        idempotency_key="discord:interaction:fund",
    )
    confirmed = await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Conferido.",
    )
    ledger = await finance.ledger_entries(GUILD_ID)
    original = next(entry for entry in ledger if entry["contribution_id"] == confirmed["id"])

    reversal = await finance.reverse_contribution(
        GUILD_ID,
        int(confirmed["id"]),
        actor_id=900,
        reason="Estorno administrativo documentado.",
    )
    ledger_after = await finance.ledger_entries(GUILD_ID)
    transparency = await finance.transparency_snapshot(GUILD_ID)

    assert reversal["amount_cents"] == -3000
    assert len(ledger_after) == 2
    assert {entry["entry_type"] for entry in ledger_after} == {
        "CONTRIBUICAO_CONFIRMADA",
        "ESTORNO_CONTRIBUICAO",
    }
    assert any(entry["id"] == original["id"] for entry in ledger_after)
    assert transparency["general_fund"]["collected_cents"] == 0


@pytest.mark.asyncio
async def test_public_supporters_hide_anonymous_values_and_honors_remain_symbolic(service_bundle):
    finance = FinancialAidService(
        service_bundle["database"],
        service_bundle["settings"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    public = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="12,00",
        destination_kind="FUNDO_GERAL",
        visibility="PUBLICO",
        idempotency_key="discord:interaction:public",
    )
    await finance.confirm_contribution(
        GUILD_ID,
        int(public["id"]),
        actor_id=900,
        expected_version=int(public["version"]),
        reason="Conferido.",
    )
    supporters = await finance.public_supporters(GUILD_ID)
    honor = await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID)

    assert supporters == [{"discord_id": DISCORD_ID, "label": "Apoiador da CHOQUE"}]
    assert honor["honors"][0]["honor_key"] == "APOIADOR"
    assert honor["honors"][0]["symbolic_only"] is True
    assert "amount_cents" not in supporters[0]


@pytest.mark.asyncio
async def test_expense_honor_and_certificate_keep_auditable_symbolic_history(service_bundle):
    finance = FinancialAidService(
        service_bundle["database"],
        service_bundle["settings"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="40,00",
        destination_kind="FUNDO_GERAL",
        visibility="ANONIMO",
        idempotency_key="discord:interaction:expense-source",
    )
    await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Conferido.",
    )
    expense = await finance.record_expense(
        GUILD_ID,
        actor_id=900,
        amount="15,00",
        category="SISTEMA",
        description="Renovação documentada de infraestrutura.",
    )
    honor = await finance.grant_honor(
        GUILD_ID,
        DISCORD_ID,
        actor_id=900,
        honor_key="PATRONO",
        justification="Decisão humana fundamentada por participação excepcional em projetos.",
    )
    certificate = await finance.issue_certificate(
        GUILD_ID,
        DISCORD_ID,
        actor_id=900,
        honor_id=int(honor["id"]),
    )
    transparency = await finance.transparency_snapshot(GUILD_ID)

    assert expense["ledger_entry_id"] is not None
    assert transparency["general_fund"] == {
        "collected_cents": 4000,
        "used_cents": 1500,
        "balance_cents": 2500,
        "movement_count": 2,
    }
    assert certificate["validation_code"].startswith("CHOQUE-")
    with pytest.raises(ValidationError, match="Justificativa"):
        await finance.grant_honor(
            GUILD_ID,
            DISCORD_ID,
            actor_id=900,
            honor_key="COLABORADOR",
            justification="",
        )


@pytest.mark.asyncio
async def test_manual_project_completion_awards_existing_supporters_once(service_bundle):
    finance = service_bundle["financial_aid"]
    project = await finance.create_project(
        GUILD_ID,
        actor_id=900,
        name="Projeto de Identidade",
        description="Nova identidade visual institucional.",
        category="IDENTIDADE_VISUAL",
        target_amount="200,00",
    )
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="10,00",
        destination_kind="PROJETO",
        project_id=int(project["id"]),
        visibility="ANONIMO",
        idempotency_key="manual-project-completion",
    )
    await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Recebimento conferido.",
    )
    current = await finance.project_snapshot(GUILD_ID, int(project["id"]))
    completed = await finance.update_project(
        GUILD_ID,
        int(project["id"]),
        actor_id=900,
        expected_version=int(current["version"]),
        status="CONCLUIDA",
        reason="Meta concluída por decisão administrativa documentada.",
    )
    repeated = await finance.update_project(
        GUILD_ID,
        int(project["id"]),
        actor_id=900,
        expected_version=int(completed["version"]),
        status="CONCLUIDA",
        reason="Confirmação sem reabrir a meta.",
    )
    profile = await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID)

    assert repeated["status"] == "CONCLUIDA"
    assert [item["achievement_key"] for item in profile["achievements"]].count("PROJETO_CONCLUIDO") == 1
    assert [item["achievement_key"] for item in profile["achievements"]].count("FUNDADOR_DE_PROJETO") == 1


@pytest.mark.asyncio
async def test_expired_symbolic_honor_is_hidden_then_closed_without_erasing_history(service_bundle):
    finance = service_bundle["financial_aid"]
    clock = service_bundle["clock"]
    honor = await finance.grant_honor(
        GUILD_ID,
        DISCORD_ID,
        actor_id=900,
        honor_key="COLABORADOR",
        justification="Reconhecimento temporário, estritamente simbólico.",
        expires_at=clock() + 1,
    )
    assert (await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID))["honors"]

    clock.advance(1)
    expired = await finance.expire_due_honors(GUILD_ID)
    profile = await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID)
    historical = await service_bundle["database"].fetchone(
        "SELECT removed_at, removal_reason FROM financial_member_honors WHERE id=?", (int(honor["id"]),)
    )
    notices = await service_bundle["database"].fetchall(
        "SELECT notification_type FROM financial_notifications WHERE subject_id=? ORDER BY id",
        (int(honor["id"]),),
    )

    assert [item["id"] for item in expired] == [honor["id"]]
    assert profile["honors"] == []
    assert historical["removed_at"] == clock()
    assert "Prazo" in historical["removal_reason"]
    assert [row["notification_type"] for row in notices] == ["HONOR_GRANTED", "HONOR_REMOVED"]


@pytest.mark.asyncio
async def test_concurrent_confirmation_has_one_ledger_entry_and_one_final_state(service_bundle):
    finance = service_bundle["financial_aid"]
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="15,00",
        destination_kind="FUNDO_GERAL",
        visibility="ANONIMO",
        idempotency_key="concurrent-confirmation",
    )

    results = await asyncio.gather(
        finance.confirm_contribution(
            GUILD_ID, int(contribution["id"]), actor_id=900, expected_version=int(contribution["version"]), reason="Conferido."
        ),
        finance.confirm_contribution(
            GUILD_ID, int(contribution["id"]), actor_id=901, expected_version=int(contribution["version"]), reason="Conferido."
        ),
    )
    entries = await finance.ledger_entries(GUILD_ID)

    assert {item["status"] for item in results} == {"CONFIRMADA"}
    assert len([item for item in entries if item["contribution_id"] == contribution["id"]]) == 1


@pytest.mark.asyncio
async def test_financial_notification_intents_commit_with_decisions_without_money_or_pix(service_bundle):
    finance = service_bundle["financial_aid"]
    project = await finance.create_project(
        GUILD_ID,
        actor_id=900,
        name="Projeto comunitário",
        description="Melhoria compartilhada da corporação.",
        category="SISTEMA",
        target_amount="10,00",
    )
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="10,00",
        destination_kind="PROJETO",
        project_id=int(project["id"]),
        visibility="ANONIMO",
        idempotency_key="notification-intent",
    )
    await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Recebimento confirmado fora do bot.",
    )
    rows = await service_bundle["database"].fetchall(
        "SELECT notification_type, payload_json, status FROM financial_notifications ORDER BY id"
    )

    types = {row["notification_type"] for row in rows}
    payloads = " ".join(str(row["payload_json"]) for row in rows).lower()
    assert {"CONTRIBUTION_DECIDED", "PROJECT_COMPLETED", "HONOR_GRANTED"} <= types
    assert all(row["status"] == "PENDING" for row in rows)
    assert "amount" not in payloads
    assert "pix" not in payloads


@pytest.mark.asyncio
async def test_expense_reversal_appends_a_counter_entry_and_restores_public_balance(service_bundle):
    finance = service_bundle["financial_aid"]
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="25,00",
        destination_kind="FUNDO_GERAL",
        visibility="ANONIMO",
        idempotency_key="expense-reversal-source",
    )
    await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Conferido.",
    )
    expense = await finance.record_expense(
        GUILD_ID,
        actor_id=900,
        amount="10,00",
        category="SISTEMA",
        description="Despesa lançada para teste de estorno.",
    )
    reversal = await finance.reverse_expense(
        GUILD_ID,
        int(expense["id"]),
        actor_id=901,
        reason="Correção administrativa documentada.",
    )
    repeated = await finance.reverse_expense(
        GUILD_ID,
        int(expense["id"]),
        actor_id=901,
        reason="Não deve criar uma segunda reversão.",
    )
    snapshot = await finance.transparency_snapshot(GUILD_ID)

    assert reversal["id"] == repeated["id"]
    assert reversal["entry_type"] == "ESTORNO_DESPESA"
    assert reversal["amount_cents"] == 1000
    assert snapshot["general_fund"] == {
        "collected_cents": 2500,
        "used_cents": 0,
        "balance_cents": 2500,
        "movement_count": 3,
    }


@pytest.mark.asyncio
async def test_admin_cancellation_preserves_pending_record_and_project_sponsor_privacy(service_bundle):
    finance = service_bundle["financial_aid"]
    project = await finance.create_project(
        GUILD_ID,
        actor_id=900,
        name="Viatura comunitária",
        description="Projeto voluntário de viatura.",
        category="VIATURA",
        target_amount="300,00",
        start=True,
    )
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="10,00",
        destination_kind="PROJETO",
        project_id=int(project["id"]),
        visibility="ANONIMO",
        idempotency_key="cancelled-declaration",
    )
    cancelled = await finance.cancel_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Declaração cancelada antes da confirmação externa.",
    )
    repeated = await finance.cancel_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Repetição idempotente.",
    )
    await finance.sponsor_project(
        GUILD_ID, DISCORD_ID, project_id=int(project["id"]), visibility="ANONIMO"
    )
    snapshot = await finance.project_snapshot(GUILD_ID, int(project["id"]))
    events = await service_bundle["database"].fetchall(
        "SELECT event_type FROM financial_contribution_events WHERE contribution_id=? ORDER BY id",
        (int(contribution["id"]),),
    )

    assert cancelled["status"] == repeated["status"] == "CANCELADA"
    assert [row["event_type"] for row in events] == ["DECLARED", "CANCELLED"]
    assert snapshot["collected_cents"] == 0
    assert snapshot["supporter_count"] == 1
    assert snapshot["supporters"] == [
        {"visibility": "ANONIMO", "label": "Anônimo", "declared_at": service_bundle["clock"]()}
    ]


@pytest.mark.asyncio
async def test_suggestion_review_queues_one_private_status_without_financial_data(service_bundle):
    finance = service_bundle["financial_aid"]
    suggestion = await finance.create_suggestion(
        GUILD_ID,
        DISCORD_ID,
        title="Revisar quadro de ocorrências",
        category="SISTEMA",
        description="Uma tela simplificada para consulta operacional.",
        motivation="Reduzir passos repetitivos na rotina do efetivo.",
        estimated_amount="0,00",
        reference_url="https://example.invalid/referencia",
    )

    reviewed = await finance.review_suggestion(
        GUILD_ID,
        int(suggestion["id"]),
        actor_id=900,
        expected_version=int(suggestion["version"]),
        status="ACEITA",
        reason="Será planejada sem compromisso financeiro automático.",
    )
    notification = await service_bundle["database"].fetchone(
        "SELECT notification_type, target_discord_id, payload_json, status FROM financial_notifications "
        "WHERE subject_type='SUGGESTION' AND subject_id=?",
        (int(suggestion["id"]),),
    )

    assert reviewed["status"] == "ACEITA"
    assert notification["notification_type"] == "SUGGESTION_REVIEWED"
    assert notification["target_discord_id"] == DISCORD_ID
    assert notification["status"] == "PENDING"
    assert "amount" not in str(notification["payload_json"]).lower()
    assert "pix" not in str(notification["payload_json"]).lower()
    with pytest.raises(ValidationError, match="link"):
        await finance.create_suggestion(
            GUILD_ID,
            DISCORD_ID,
            title="Referência inválida",
            category="SISTEMA",
            description="Este registro deve falhar antes de persistir.",
            motivation="Verificação da validação do campo opcional.",
            reference_url="arquivo-local://nao-permitido",
        )


@pytest.mark.asyncio
async def test_durable_notification_claim_is_atomic_and_recovers_only_after_lease(service_bundle):
    finance = service_bundle["financial_aid"]
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="5,00",
        destination_kind="FUNDO_GERAL",
        visibility="ANONIMO",
        idempotency_key="notification-claim",
    )
    await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Confirmação de teste.",
    )
    # The confirmation can also grant one symbolic honor.  Isolate the
    # contribution notice so both tasks contend for the *same* row.
    await service_bundle["database"].execute(
        "UPDATE financial_notifications SET status='DELIVERED' "
        "WHERE notification_type<>'CONTRIBUTION_DECIDED'"
    )
    cog = object.__new__(FinancialAidCommands)
    cog.services = SimpleNamespace(financial_aid=finance, database=service_bundle["database"])

    first, second = await asyncio.gather(
        cog._claim_financial_notification(), cog._claim_financial_notification()
    )
    claimed = first or second
    assert claimed is not None
    assert (first is None) != (second is None)
    row = await service_bundle["database"].fetchone(
        "SELECT status, attempts FROM financial_notifications WHERE id=?", (int(claimed["id"]),)
    )
    assert row["status"] == "PROCESSING"
    assert row["attempts"] == 1

    # A restart must not immediately duplicate a still-in-flight delivery.  A
    # deliberately expired lease is the only condition that releases it.
    assert await cog._claim_financial_notification() is None
    await service_bundle["database"].execute(
        "UPDATE financial_notifications SET updated_at=? WHERE id=?",
        (service_bundle["clock"]() - 120_001, int(claimed["id"])),
    )
    recovered = await cog._claim_financial_notification()
    assert recovered is not None
    assert recovered["id"] == claimed["id"]
    after_recovery = await service_bundle["database"].fetchone(
        "SELECT attempts FROM financial_notifications WHERE id=?", (int(claimed["id"]),)
    )
    assert after_recovery["attempts"] == 2


@pytest.mark.asyncio
async def test_financial_notification_delivery_is_durable_and_does_not_replay_after_recovery(service_bundle):
    class FakeRecipient:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send(self, **kwargs: object) -> SimpleNamespace:
            self.sent.append(kwargs)
            return SimpleNamespace(id=881)

    class FakeGuild:
        def __init__(self, recipient: FakeRecipient) -> None:
            self.id = GUILD_ID
            self._recipient = recipient

        def get_member(self, member_id: int) -> FakeRecipient | None:
            return self._recipient if member_id == DISCORD_ID else None

        def get_channel(self, _: int) -> None:
            return None

    finance = service_bundle["financial_aid"]
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="5,00",
        destination_kind="FUNDO_GERAL",
        visibility="ANONIMO",
        idempotency_key="durable-discord-delivery",
    )
    await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Confirmação humana de teste.",
    )
    await service_bundle["database"].execute(
        "UPDATE financial_notifications SET status='DELIVERED' WHERE notification_type<>'CONTRIBUTION_DECIDED'"
    )
    recipient = FakeRecipient()
    guild = FakeGuild(recipient)
    services = SimpleNamespace(
        financial_aid=finance,
        database=service_bundle["database"],
        settings=service_bundle["settings"],
    )
    cog = object.__new__(FinancialAidCommands)
    cog.services = services
    cog.bot = SimpleNamespace(
        services=services,
        config=SimpleNamespace(branding=Branding()),
        get_guild=lambda guild_id: guild if guild_id == GUILD_ID else None,
        get_user=lambda _: None,
        fetch_user=AsyncMock(return_value=None),
    )

    claimed = await cog._claim_financial_notification()
    assert claimed is not None
    await cog._deliver_financial_notification(claimed)

    delivered = await service_bundle["database"].fetchone(
        "SELECT status, attempts, dm_message_id, last_error FROM financial_notifications WHERE id=?",
        (int(claimed["id"]),),
    )
    assert delivered["status"] == "DELIVERED"
    assert delivered["attempts"] == 1
    assert delivered["dm_message_id"] == 881
    assert delivered["last_error"] is None
    assert len(recipient.sent) == 1
    assert recipient.sent[0]["nonce"] == int(claimed["id"])
    assert await cog._claim_financial_notification() is None


def test_money_parser_rejects_values_outside_sqlite_signed_integer_range():
    with pytest.raises(ValidationError, match="excede"):
        FinancialAidService.parse_amount_to_cents("92233720368547759,00")


@pytest.mark.asyncio
async def test_certificate_snapshot_has_only_symbolic_profile_data_and_validation_code(service_bundle):
    finance = service_bundle["financial_aid"]
    contribution = await finance.declare_contribution(
        GUILD_ID,
        DISCORD_ID,
        amount="7,00",
        destination_kind="FUNDO_GERAL",
        visibility="ANONIMO",
        idempotency_key="certificate-profile",
    )
    await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Conferido para emissão de certificado de teste.",
    )
    profile = await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID)
    certificate = await finance.issue_certificate(
        GUILD_ID,
        DISCORD_ID,
        actor_id=900,
        honor_id=int(profile["honors"][0]["id"]),
    )
    snapshot = await finance.certificate_snapshot(GUILD_ID, int(certificate["id"]))

    assert snapshot["discord_id"] == DISCORD_ID
    assert snapshot["honor_title"]
    assert snapshot["achievement_titles"]
    assert snapshot["validation_code"] == certificate["validation_code"]
    assert "amount_cents" not in snapshot


@pytest.mark.asyncio
async def test_symbolic_honor_role_reconciliation_grants_then_revokes_from_canonical_history(service_bundle):
    class FakeRole:
        def __init__(self, role_id: int, position: int) -> None:
            self.id = role_id
            self.position = position
            self.permissions = SimpleNamespace(value=0)

        def __ge__(self, other: object) -> bool:
            return isinstance(other, FakeRole) and self.position >= other.position

    class FakeMember:
        def __init__(self, member_id: int) -> None:
            self.id = member_id
            self.roles: list[FakeRole] = []

        async def add_roles(self, role: FakeRole, *, reason: str) -> None:
            del reason
            self.roles.append(role)

        async def remove_roles(self, role: FakeRole, *, reason: str) -> None:
            del reason
            self.roles.remove(role)

    class FakeGuild:
        def __init__(self, member: FakeMember, role: FakeRole) -> None:
            self.id = GUILD_ID
            self.me = SimpleNamespace(top_role=FakeRole(999, 99))
            self._member = member
            self._role = role

        def get_member(self, member_id: int) -> FakeMember | None:
            return self._member if member_id == self._member.id else None

        def get_role(self, role_id: int) -> FakeRole | None:
            return self._role if role_id == self._role.id else None

    finance = service_bundle["financial_aid"]
    await finance.configure_honor_role(
        GUILD_ID, actor_id=900, honor_key="PATRONO", role_id=777
    )
    honor = await finance.grant_honor(
        GUILD_ID,
        DISCORD_ID,
        actor_id=900,
        honor_key="PATRONO",
        justification="Reconhecimento simbólico para testar a sincronização.",
    )
    member = FakeMember(DISCORD_ID)
    role = FakeRole(777, 10)
    cog = object.__new__(FinancialAidCommands)
    audit = SimpleNamespace(record=AsyncMock())
    cog.services = SimpleNamespace(
        financial_aid=finance, database=service_bundle["database"], audit=audit
    )
    guild = FakeGuild(member, role)

    await cog.reconcile_honor_roles(guild, discord_id=DISCORD_ID)
    assert role in member.roles

    await finance.remove_honor(
        GUILD_ID,
        int(honor["id"]),
        actor_id=900,
        expected_version=int(honor["version"]),
        reason="Encerramento simbólico de teste.",
    )
    await cog.reconcile_honor_roles(guild, discord_id=DISCORD_ID)

    assert role not in member.roles
    assert audit.record.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_panel_recovery_creates_only_one_persistent_financial_panel(service_bundle):
    class FakeMessage:
        def __init__(self, message_id: int) -> None:
            self.id = message_id
            self.edits = 0

        async def edit(self, **_: object) -> None:
            self.edits += 1

    class FakeChannel:
        def __init__(self) -> None:
            self.id = 990
            self.messages: dict[int, FakeMessage] = {}
            self.send_count = 0

        async def fetch_message(self, message_id: int) -> FakeMessage:
            return self.messages[message_id]

        async def send(self, **_: object) -> FakeMessage:
            await asyncio.sleep(0)
            self.send_count += 1
            message = FakeMessage(self.send_count)
            self.messages[message.id] = message
            return message

    finance = service_bundle["financial_aid"]
    services = SimpleNamespace(
        financial_aid=finance,
        settings=service_bundle["settings"],
        database=service_bundle["database"],
    )
    cog = object.__new__(FinancialAidCommands)
    cog.services = services
    cog.bot = SimpleNamespace(services=services, config=SimpleNamespace(branding=Branding()))
    cog._panel_locks = {}
    channel = FakeChannel()
    guild = SimpleNamespace(id=GUILD_ID)

    first, second = await asyncio.gather(
        cog.publish_or_refresh_public_panel(guild, channel),
        cog.publish_or_refresh_public_panel(guild, channel),
    )
    panel = await service_bundle["settings"].get_panel(GUILD_ID, "FINANCIAL_AID")

    assert channel.send_count == 1
    assert first is second
    assert int(panel["channel_id"]) == channel.id
    assert int(panel["message_id"]) == first.id
