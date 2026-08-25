from __future__ import annotations

import pytest

from choque.errors import ConflictError
from choque.models import RbacProfile
from choque.rbac import PROFILE_PERMISSIONS
from choque.settings import SettingsService
from choque.status import STATUS_COMPONENTS, StatusService
from cogs.status_commands import (
    StatusAdminView,
    StatusComponentSelectView,
    StatusPublicView,
)

from .conftest import DISCORD_ID, GUILD_ID


@pytest.mark.asyncio
async def test_status_snapshot_starts_with_all_public_components(service_bundle) -> None:
    service = StatusService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )

    snapshot = await service.snapshot(GUILD_ID)

    assert snapshot["global_state"] == "OPERACIONAL"
    assert [item["component_key"] for item in snapshot["components"]] == [
        key for key, _ in STATUS_COMPONENTS
    ]
    assert all(item["state"] == "OPERACIONAL" for item in snapshot["components"])


@pytest.mark.asyncio
async def test_automatic_status_uses_hysteresis_before_incident_and_recovery(service_bundle) -> None:
    service = StatusService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )

    first, changed_first = await service.record_observation(
        GUILD_ID, "API_SITE", "INDISPONIVEL", "API sem resposta"
    )
    second, changed_second = await service.record_observation(
        GUILD_ID, "API_SITE", "INDISPONIVEL", "API sem resposta"
    )
    recovering, changed_recovering = await service.record_observation(
        GUILD_ID, "API_SITE", "OPERACIONAL", "API respondeu"
    )
    recovered, changed_recovered = await service.record_observation(
        GUILD_ID, "API_SITE", "OPERACIONAL", "API respondeu"
    )

    assert (first["state"], changed_first) == ("OPERACIONAL", False)
    assert (second["state"], changed_second) == ("INDISPONIVEL", True)
    assert (recovering["state"], changed_recovering) == ("INDISPONIVEL", False)
    assert (recovered["state"], changed_recovered) == ("OPERACIONAL", True)

    events = await service.recent_events(GUILD_ID)
    assert [event["next_state"] for event in reversed(events)] == [
        "INDISPONIVEL",
        "OPERACIONAL",
    ]


@pytest.mark.asyncio
async def test_manual_override_masks_detection_until_normalized_with_cas(service_bundle) -> None:
    service = StatusService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    initial = await service.component(GUILD_ID, "CENTRAL_TAGS")
    maintenance = await service.set_override(
        GUILD_ID,
        "CENTRAL_TAGS",
        "EM_MANUTENCAO",
        actor_id=DISCORD_ID,
        reason="Atualização planejada dos painéis.",
        expected_version=int(initial["version"]),
    )

    await service.record_observation(
        GUILD_ID,
        "CENTRAL_TAGS",
        "INDISPONIVEL",
        "Configuração obrigatória ausente",
        failure_threshold=1,
    )
    masked = await service.component(GUILD_ID, "CENTRAL_TAGS")

    assert maintenance["state"] == "EM_MANUTENCAO"
    assert masked["state"] == "EM_MANUTENCAO"
    assert masked["detected_state"] == "INDISPONIVEL"

    with pytest.raises(ConflictError):
        await service.clear_override(
            GUILD_ID,
            "CENTRAL_TAGS",
            actor_id=DISCORD_ID,
            reason="Teste com versão antiga.",
            expected_version=int(initial["version"]),
        )

    normalized = await service.clear_override(
        GUILD_ID,
        "CENTRAL_TAGS",
        actor_id=DISCORD_ID,
        reason="Manutenção encerrada; monitor automático retomado.",
        expected_version=int(masked["version"]),
    )
    assert normalized["state"] == "INDISPONIVEL"
    assert normalized["is_override"] is False


@pytest.mark.asyncio
async def test_override_expiration_restores_detected_state_and_survives_restart_data(service_bundle) -> None:
    service = StatusService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    now = service_bundle["clock"]()
    await service.set_override(
        GUILD_ID,
        "RECRUTAMENTO_MESA",
        "ATUALIZANDO",
        actor_id=DISCORD_ID,
        reason="Publicação controlada.",
        expires_at=now + 60_000,
    )
    service_bundle["clock"].advance(60_001)

    expired = await service.expire_overrides(GUILD_ID)
    current = await service.component(GUILD_ID, "RECRUTAMENTO_MESA")

    assert expired == 1
    assert current["state"] == "OPERACIONAL"
    assert current["override_state"] is None


@pytest.mark.asyncio
async def test_status_notification_claim_is_durable_and_respects_cooldown(service_bundle) -> None:
    service = StatusService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    await service.set_override(
        GUILD_ID,
        "API_SITE",
        "EM_MANUTENCAO",
        actor_id=DISCORD_ID,
        reason="Atualização do portal.",
    )
    event = (await service.pending_notifications(GUILD_ID))[0]
    claimed = await service.claim_notification(int(event["id"]), cooldown_ms=900_000)
    repeated = await service.claim_notification(int(event["id"]), cooldown_ms=900_000)
    assert claimed is not None
    assert repeated is None
    assert await service.mark_notification_delivered(int(event["id"]), message_id=9001)

    current = await service.component(GUILD_ID, "API_SITE")
    await service.set_override(
        GUILD_ID,
        "API_SITE",
        "INSTAVEL_DEGRADADO",
        actor_id=DISCORD_ID,
        reason="Latência elevada após a atualização.",
        expected_version=int(current["version"]),
    )
    second = (await service.pending_notifications(GUILD_ID))[0]
    assert await service.claim_notification(int(second["id"]), cooldown_ms=900_000) is None
    stored = await service_bundle["database"].fetchone(
        "SELECT notification_status FROM system_status_events WHERE id=?", (second["id"],)
    )
    assert stored["notification_status"] == "SUPPRESSED"


@pytest.mark.asyncio
async def test_delivery_health_ignores_terminal_historical_failures(service_bundle) -> None:
    service = StatusService(
        service_bundle["database"],
        service_bundle["audit"],
        clock=service_bundle["clock"],
    )
    baseline = await service.delivery_health_metrics()
    old = service_bundle["clock"]() - 3_600_001
    await service_bundle["database"].execute(
        """
        INSERT INTO web_action_outbox(
            guild_id, action_type, payload_json, requested_by, correlation_id,
            status, attempts, available_at, created_at, last_error
        ) VALUES (?, 'RANK_SYNC', '{}', ?, 'old-terminal-status-test',
                  'FAILED', 10, ?, ?, 'falha histórica')
        """,
        (GUILD_ID, DISCORD_ID, old, old),
    )
    await service_bundle["database"].execute(
        """
        INSERT INTO audit_logs(
            correlation_id, guild_id, action, delivery_status,
            delivery_attempts, created_at, last_error
        ) VALUES ('old-audit-status-test', ?, 'OLD_EVENT', 'FAILED', 2, ?, 'canal antigo')
        """,
        (GUILD_ID, old),
    )

    metrics = await service.delivery_health_metrics()

    assert metrics == baseline


def test_status_settings_and_backend_permission_are_explicit() -> None:
    assert SettingsService.DEFAULTS["status_public_channel_id"] is None
    assert SettingsService.DEFAULTS["status_admin_channel_id"] is None
    assert SettingsService.DEFAULTS["status_notification_channel_id"] is None
    assert "status.manage" in PROFILE_PERMISSIONS[RbacProfile.COMMAND.value]


@pytest.mark.asyncio
async def test_public_status_panel_exposes_only_refresh_and_details() -> None:
    view = StatusPublicView()

    assert [item.label for item in view.children] == ["Atualizar", "Detalhes"]
    assert [item.custom_id for item in view.children] == [
        "choque:status:refresh:v1",
        "choque:status:details:v1",
    ]
    assert view.is_persistent()


@pytest.mark.asyncio
async def test_status_administration_has_explicit_safe_state_actions() -> None:
    view = StatusAdminView()

    assert [item.label for item in view.children] == [
        "Atualizando",
        "Manutenção",
        "Instável",
        "Desativado",
        "Indisponível",
        "Normalizar",
    ]
    assert view.is_persistent()

    component_view = StatusComponentSelectView("EM_MANUTENCAO")
    select = component_view.children[0]
    assert [option.value for option in select.options] == [
        key for key, _ in STATUS_COMPONENTS
    ]
