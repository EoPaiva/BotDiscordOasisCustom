from __future__ import annotations

from types import SimpleNamespace

import pytest

from choque.career import HOUR_MS, CareerService
from choque.config import Branding
from choque.errors import ConflictError, ValidationError
from cogs.career_commands import CareerCommands

from .conftest import DISCORD_ID, GUILD_ID


async def seed_rank(bundle, name: str, level: int, role_id: int) -> int:
    return await bundle["database"].execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
        ) VALUES (?, ?, ?, ?, ?, 'MEMBRO', ?)
        """,
        (GUILD_ID, name, name[:3], level, role_id, bundle["clock"]()),
    )


def test_rank_movement_announcement_identifies_responsible_and_reason() -> None:
    cog = object.__new__(CareerCommands)
    cog.bot = SimpleNamespace(config=SimpleNamespace(branding=Branding()))

    embed = cog._notification_embed(
        "PROMOTION",
        {
            "discord_id": 456,
            "from_rank_name": "Tenente-Coronel",
            "to_rank_name": "Coronel",
            "actor_id": 999,
            "reason": (
                "Promoção determinada pelo Comando, em conformidade com a "
                "organização do efetivo."
            ),
        },
    )

    assert embed.title == "⬆️ Promoção registrada"
    assert "<@456>" in embed.description
    assert "**Responsável:** <@999>" in embed.description
    assert "**Motivo:** Promoção determinada pelo Comando" in embed.description


async def seed_valid_hours(bundle, hours: int) -> None:
    database = bundle["database"]
    clock = bundle["clock"]
    member = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    started_at = clock() - hours * HOUR_MS
    await database.execute(
        """
        INSERT INTO shifts(
            guild_id, member_id, status, started_at, ended_at, closed_at,
            end_reason, created_by, created_at, gross_duration_ms,
            patrol_duration_ms, validation_status, automatic_validation_status,
            validation_source, validated_at
        ) VALUES (?, ?, 'CLOSED', ?, ?, ?, 'TEST', ?, ?, ?, ?, 'VALID',
                  'VALID', 'AUTO', ?)
        """,
        (
            GUILD_ID,
            member["id"],
            started_at,
            clock(),
            clock(),
            DISCORD_ID,
            started_at,
            hours * HOUR_MS,
            hours * HOUR_MS,
            clock(),
        ),
    )


async def prepare_progression(bundle) -> CareerService:
    recruit = await seed_rank(bundle, "RECRUTA", 10, 91_001)
    await seed_rank(bundle, "SOLDADO", 20, 91_002)
    await seed_rank(bundle, "CABO", 30, 91_003)
    await seed_rank(bundle, "3º SARGENTO", 40, 91_004)
    await seed_rank(bundle, "2º SARGENTO", 50, 91_005)
    await seed_rank(bundle, "1º SARGENTO", 60, 91_006)
    await seed_rank(bundle, "SUBTENENTE", 70, 91_007)
    await seed_rank(bundle, "CADETE", 80, 91_008)
    await bundle["database"].execute(
        "UPDATE members SET rank_id=?, status='ACTIVE', updated_at=? WHERE guild_id=? AND discord_id=?",
        (recruit, bundle["clock"](), GUILD_ID, DISCORD_ID),
    )
    career = CareerService(
        bundle["database"],
        bundle["settings"],
        bundle["audit"],
        bundle["personnel"],
        bundle["shifts"],
        clock=bundle["clock"],
    )
    await career.ensure_default_progression(GUILD_ID, actor_id=DISCORD_ID)
    return career


async def test_progression_matches_stylized_sub_tenente_with_space(service_bundle) -> None:
    database = service_bundle["database"]
    career = service_bundle["career"]
    now = service_bundle["clock"]()
    ranks = (
        ("1º sᴀʀɢᴇɴᴛᴏ", "[1SGT]", 6),
        ("sᴜʙ ᴛᴇɴᴇɴᴛᴇ", "[ST]", 7),
        ("ᴄᴀᴅᴇᴛᴇ", "[CAD]", 8),
    )
    for name, prefix, level in ranks:
        await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, active, created_at)
            VALUES (?, ?, ?, ?, 'MEMBRO', 1, ?)
            """,
            (GUILD_ID, name, prefix, level, now),
        )

    configured = await career.ensure_default_progression(GUILD_ID, actor_id=DISCORD_ID)
    rules = await career.progression_rules(GUILD_ID)

    assert configured == 2
    assert [(row["from_rank_name"], row["to_rank_name"]) for row in rules] == [
        ("1º sᴀʀɢᴇɴᴛᴏ", "sᴜʙ ᴛᴇɴᴇɴᴛᴇ"),
        ("sᴜʙ ᴛᴇɴᴇɴᴛᴇ", "ᴄᴀᴅᴇᴛᴇ"),
    ]


@pytest.mark.asyncio
async def test_automatic_progression_uses_existing_valid_hours_and_is_idempotent(
    service_bundle,
) -> None:
    career = await prepare_progression(service_bundle)
    await seed_valid_hours(service_bundle, 4)

    first = await career.process_member(GUILD_ID, DISCORD_ID)
    second = await career.process_member(GUILD_ID, DISCORD_ID)

    assert first["status"] == "PROMOTED"
    assert first["from_rank_name"] == "RECRUTA"
    assert first["to_rank_name"] == "SOLDADO"
    assert second["status"] == "WAITING_HOURS"
    member = await service_bundle["database"].fetchone(
        """
        SELECT r.name AS rank_name FROM members m JOIN ranks r ON r.id=m.rank_id
        WHERE m.guild_id=? AND m.discord_id=?
        """,
        (GUILD_ID, DISCORD_ID),
    )
    assert member["rank_name"] == "SOLDADO"
    assert (
        await service_bundle["database"].fetchone(
            "SELECT COUNT(*) AS total FROM career_progression_events WHERE guild_id=?",
            (GUILD_ID,),
        )
    )["total"] == 1
    assert (
        await service_bundle["database"].fetchone(
            "SELECT COUNT(*) AS total FROM web_action_outbox WHERE action_type='RANK_SYNC'",
        )
    )["total"] == 1
    notification = await service_bundle["database"].fetchone(
        """
        SELECT notification_type, status, channel_setting_key
        FROM career_notifications WHERE subject_id=?
        """,
        (first["action_id"],),
    )
    assert tuple(notification) == (
        "PROMOTION",
        "PENDING",
        "career_promotion_channel_id",
    )


@pytest.mark.asyncio
async def test_manual_higher_rank_is_never_reduced_by_automatic_hours(
    service_bundle,
) -> None:
    career = await prepare_progression(service_bundle)
    await seed_valid_hours(service_bundle, 4)
    cabo = await service_bundle["database"].fetchone(
        "SELECT id FROM ranks WHERE guild_id=? AND name='CABO'",
        (GUILD_ID,),
    )
    await service_bundle["database"].execute(
        """
        UPDATE members SET rank_id=?, rank_sync_status='SYNCED', updated_at=?
        WHERE guild_id=? AND discord_id=?
        """,
        (cabo["id"], service_bundle["clock"](), GUILD_ID, DISCORD_ID),
    )

    result = await career.process_member(GUILD_ID, DISCORD_ID)

    assert result["status"] == "WAITING_HOURS"
    assert result["valid_hours_ms"] == 4 * HOUR_MS
    assert result["target_total_ms"] == 13 * HOUR_MS
    member = await service_bundle["database"].fetchone(
        """
        SELECT r.name AS rank_name FROM members m JOIN ranks r ON r.id=m.rank_id
        WHERE m.guild_id=? AND m.discord_id=?
        """,
        (GUILD_ID, DISCORD_ID),
    )
    assert member["rank_name"] == "CABO"
    assert (
        await service_bundle["database"].fetchone(
            "SELECT COUNT(*) AS total FROM personnel_actions"
        )
    )["total"] == 0


@pytest.mark.asyncio
async def test_progression_requires_tenure_and_stops_at_cadet(service_bundle) -> None:
    career = await prepare_progression(service_bundle)
    await seed_valid_hours(service_bundle, 40)

    assert (await career.process_member(GUILD_ID, DISCORD_ID))["to_rank_name"] == "SOLDADO"
    waiting = await career.process_member(GUILD_ID, DISCORD_ID)
    assert waiting["status"] == "WAITING_TENURE"
    service_bundle["clock"].advance(2 * HOUR_MS)
    assert (await career.process_member(GUILD_ID, DISCORD_ID))["to_rank_name"] == "CABO"

    for minimum_hours, expected in (
        (3, "3º SARGENTO"),
        (4, "2º SARGENTO"),
        (5, "1º SARGENTO"),
        (5, "SUBTENENTE"),
        (6, "CADETE"),
    ):
        service_bundle["clock"].advance(minimum_hours * HOUR_MS)
        assert (await career.process_member(GUILD_ID, DISCORD_ID))["to_rank_name"] == expected

    stopped = await career.process_member(GUILD_ID, DISCORD_ID)
    assert stopped["status"] == "COMPLETE"
    assert stopped["rank_name"] == "CADETE"


@pytest.mark.asyncio
async def test_merit_is_audited_configured_and_only_available_from_cadet(
    service_bundle,
) -> None:
    career = await prepare_progression(service_bundle)

    with pytest.raises(ConflictError, match="Cadete"):
        await career.create_merit(
            GUILD_ID,
            DISCORD_ID,
            900,
            merit_type="POSITIVE",
            category="LIDERANÇA",
            weight=4,
            reason="Conduziu a equipe com clareza.",
        )

    cadet = await service_bundle["database"].fetchone(
        "SELECT id FROM ranks WHERE guild_id=? AND name='CADETE'", (GUILD_ID,)
    )
    await service_bundle["database"].execute(
        "UPDATE members SET rank_id=? WHERE guild_id=? AND discord_id=?",
        (cadet["id"], GUILD_ID, DISCORD_ID),
    )
    merit_id = await career.create_merit(
        GUILD_ID,
        DISCORD_ID,
        900,
        merit_type="POSITIVE",
        category="LIDERANÇA",
        weight=4,
        reason="Conduziu a equipe com clareza.",
        evidence_locator="https://example.test/evidencia",
    )
    assert merit_id > 0
    history = await career.merit_history(GUILD_ID, DISCORD_ID)
    assert history[0]["category"] == "LIDERANÇA"
    assert history[0]["weight"] == 4
    audit = await service_bundle["database"].fetchone(
        "SELECT action FROM audit_logs WHERE target_id=? ORDER BY id DESC LIMIT 1",
        (DISCORD_ID,),
    )
    assert audit["action"] == "MERIT_CREATED"
    notification = await service_bundle["database"].fetchone(
        """
        SELECT notification_type, status, target_discord_id
        FROM career_notifications WHERE subject_id=?
        """,
        (merit_id,),
    )
    assert tuple(notification) == ("MERIT", "PENDING", DISCORD_ID)

    with pytest.raises(ValidationError, match="categoria"):
        await career.create_merit(
            GUILD_ID,
            DISCORD_ID,
            900,
            merit_type="NEGATIVE",
            category="INVENTADA",
            weight=2,
            reason="Categoria fora da configuração.",
        )
