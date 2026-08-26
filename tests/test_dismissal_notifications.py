from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import choque.database as database_module
from choque.config import Branding
from choque.database import Database
from choque.dismissals import (
    HIGH_COMMAND_DISMISSAL_REASON,
    STANDARD_DISMISSAL_REASON,
)
from choque.models import AdministrativeRequestType, PunishmentType, RbacProfile
from choque.settings import SettingsService
from cogs.career_commands import CareerCommands
from scripts.remodel_discord_layout import CHANNEL_BY_KEY

from .conftest import DISCORD_ID, GUILD_ID


async def grant_high_command(service_bundle: dict[str, object], actor_id: int) -> None:
    settings = service_bundle["settings"]
    members = service_bundle["members"]
    database = service_bundle["database"]
    await settings.bind_role(
        GUILD_ID,
        9_900_001,
        RbacProfile.HIGH_COMMAND,
        DISCORD_ID,
    )
    await members.create_or_update(
        GUILD_ID,
        actor_id,
        discord_nick="Responsável",
        mta_nick="Alto_Comando",
        character_id="999",
        unit="BGR",
        rank_id=None,
        actor_id=DISCORD_ID,
    )
    await database.execute(
        """
        UPDATE members
        SET access_profile_id=(
            SELECT id FROM access_profiles
            WHERE guild_id=? AND code='ALTO_COMANDO'
        )
        WHERE guild_id=? AND discord_id=?
        """,
        (GUILD_ID, GUILD_ID, actor_id),
    )


@pytest.mark.asyncio
async def test_high_command_dismissal_enqueues_automatic_public_reason(
    service_bundle,
) -> None:
    actor_id = 999
    manual_reason = "Texto disciplinar privado que não pode aparecer no boletim."
    await grant_high_command(service_bundle, actor_id)

    result = await service_bundle["personnel"].apply_punishment(
        GUILD_ID,
        DISCORD_ID,
        PunishmentType.DISMISSAL,
        actor_id=actor_id,
        reason=manual_reason,
    )

    notification = await service_bundle["database"].fetchone(
        """
        SELECT * FROM career_notifications
        WHERE notification_type='DISMISSAL' AND subject_id=?
        """,
        (result["punishment_id"],),
    )
    assert notification is not None
    assert notification["status"] == "PENDING"
    assert notification["target_discord_id"] is None
    assert notification["channel_setting_key"] == "dismissal_log_channel_id"
    payload = json.loads(notification["payload_json"])
    assert payload == {
        "discord_id": DISCORD_ID,
        "actor_id": actor_id,
        "occurred_at": service_bundle["clock"](),
        "actor_has_high_command": True,
        "public_reason": HIGH_COMMAND_DISMISSAL_REASON,
        "source": "PUNISHMENT",
    }
    assert manual_reason not in notification["payload_json"]


@pytest.mark.asyncio
async def test_approved_dismissal_request_uses_standard_reason(service_bundle) -> None:
    actor_id = 999
    request_id = await service_bundle["requests"].submit(
        GUILD_ID,
        DISCORD_ID,
        AdministrativeRequestType.DISMISSAL,
        {"reason": "Decisão pessoal privada", "confirmation": "CONFIRMAR"},
    )

    await service_bundle["requests"].review(
        GUILD_ID,
        request_id,
        True,
        actor_id=actor_id,
        reason="Análise administrativa privada",
    )

    notification = await service_bundle["database"].fetchone(
        """
        SELECT * FROM career_notifications
        WHERE notification_type='DISMISSAL' AND subject_id=?
        """,
        (request_id,),
    )
    assert notification is not None
    payload = json.loads(notification["payload_json"])
    assert payload["actor_has_high_command"] is False
    assert payload["public_reason"] == STANDARD_DISMISSAL_REASON
    assert payload["source"] == "ADMINISTRATIVE_REQUEST"
    assert "privada" not in notification["payload_json"]


def test_dismissal_embed_is_formal_and_uses_recorded_timestamp() -> None:
    cog = object.__new__(CareerCommands)
    cog.bot = SimpleNamespace(config=SimpleNamespace(branding=Branding()))

    embed = cog._notification_embed(
        "DISMISSAL",
        {
            "discord_id": 456,
            "actor_id": 999,
            "occurred_at": 1_700_000_000_000,
            "actor_has_high_command": False,
            "public_reason": STANDARD_DISMISSAL_REASON,
            "source": "PUNISHMENT",
        },
    )

    assert embed.title == "⚔️ DESLIGAMENTO DE EFETIVO"
    assert {field.name: field.value for field in embed.fields} == {
        "Militar": "<@456>",
        "Responsável": "<@999>",
        "Situação": "Desligado da Corporação",
        "Data": "<t:1700000000:F>",
        "Motivo": STANDARD_DISMISSAL_REASON,
    }
    assert embed.footer.text == (
        "Registro efetuado para controle, disciplina e organização do efetivo."
    )


def test_dismissal_channel_is_registered_and_configurable() -> None:
    assert SettingsService.DEFAULTS["dismissal_log_channel_id"] is None
    channel = CHANNEL_BY_KEY["superiors.dismissals"]
    assert channel.category == "superiors"
    assert channel.kind == "text"
    assert channel.name == "Desligamentos"


@pytest.mark.asyncio
async def test_migration_preserves_existing_career_notifications_and_accepts_dismissal(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "career-notification-v51.db"
    all_migrations = database_module.MIGRATIONS
    monkeypatch.setattr(
        database_module,
        "MIGRATIONS",
        tuple(item for item in all_migrations if item[0] <= 51),
    )
    legacy = Database(target)
    await legacy.open()
    try:
        await legacy.execute(
            """
            INSERT INTO career_notifications(
                guild_id, notification_type, subject_id, target_discord_id,
                channel_setting_key, payload_json, status, attempts,
                available_at, correlation_id, created_at, updated_at
            ) VALUES (123, 'PROMOTION', 1, 456, 'career_promotion_channel_id',
                      '{}', 'PENDING', 0, 1, 'legacy-promotion', 1, 1)
            """
        )
    finally:
        await legacy.close()

    monkeypatch.setattr(database_module, "MIGRATIONS", all_migrations)
    migrated = Database(target)
    await migrated.open()
    try:
        preserved = await migrated.fetchone(
            "SELECT notification_type, correlation_id FROM career_notifications"
        )
        assert tuple(preserved) == ("PROMOTION", "legacy-promotion")
        await migrated.execute(
            """
            INSERT INTO career_notifications(
                guild_id, notification_type, subject_id, channel_setting_key,
                payload_json, status, attempts, available_at, correlation_id,
                created_at, updated_at
            ) VALUES (123, 'DISMISSAL', 2, 'dismissal_log_channel_id', '{}',
                      'PENDING', 0, 2, 'dismissal-v52', 2, 2)
            """
        )
    finally:
        await migrated.close()
