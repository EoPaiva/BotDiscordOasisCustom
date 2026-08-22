from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from choque.errors import ConflictError
from cogs.discipline_commands import discipline_candidates, exoneration_candidates

from .conftest import CALL_A, DISCORD_ID, GUILD_ID

DAY_MS = 86_400_000


@pytest.mark.asyncio
async def test_exoneration_candidates_include_only_registered_non_bot_effective_members(
    service_bundle,
):
    members = service_bundle["members"]
    gate = service_bundle["registration_gate"]
    await gate.reconcile_identity(GUILD_ID, DISCORD_ID)
    await members.create_or_update(
        GUILD_ID,
        DISCORD_ID + 1,
        discord_nick="Bot cadastrado",
        mta_nick="Bot cadastrado",
        character_id="78",
        unit="BGR",
        rank_id=None,
        actor_id=900,
    )
    await gate.reconcile_identity(GUILD_ID, DISCORD_ID + 1)
    await members.create_or_update(
        GUILD_ID,
        DISCORD_ID + 2,
        discord_nick="Sem Portaria",
        mta_nick="Sem Portaria",
        character_id="79",
        unit="BGR",
        rank_id=None,
        actor_id=900,
    )
    discord_members = {
        DISCORD_ID: SimpleNamespace(bot=False),
        DISCORD_ID + 1: SimpleNamespace(bot=True),
        DISCORD_ID + 2: SimpleNamespace(bot=False),
    }
    guild = SimpleNamespace(
        id=GUILD_ID,
        get_member=lambda discord_id: discord_members.get(discord_id),
    )
    bot = SimpleNamespace(services=SimpleNamespace(**service_bundle))

    rows = await exoneration_candidates(bot, guild)
    discipline_rows = await discipline_candidates(bot, guild)

    assert [int(row["discord_id"]) for row in rows] == [DISCORD_ID]
    assert [int(row["discord_id"]) for row in discipline_rows] == [DISCORD_ID]


@pytest.mark.asyncio
async def test_occurrence_can_be_archived_without_punishing_member(service_bundle):
    discipline = service_bundle["discipline"]
    database = service_bundle["database"]
    members = service_bundle["members"]

    created = await discipline.create_occurrence(
        GUILD_ID,
        DISCORD_ID,
        actor_id=900,
        description="Relato operacional para apuração",
        evidence_url="https://example.com/evidence",
        observation="Sem decisão disciplinar neste momento",
    )
    assert (await members.get(GUILD_ID, DISCORD_ID))["status"] == "ACTIVE"
    assert await database.fetchone("SELECT 1 FROM punishments") is None

    archived = await discipline.archive_occurrence(
        GUILD_ID, int(created["occurrence_id"]), 901, "Fato esclarecido"
    )
    assert archived["status"] == "ARCHIVED"
    row = await discipline.get_occurrence(GUILD_ID, int(created["occurrence_id"]))
    assert row["status"] == "ARCHIVED"


@pytest.mark.asyncio
async def test_occurrence_conversion_and_warning_fulfilment_are_append_only(service_bundle):
    discipline = service_bundle["discipline"]
    database = service_bundle["database"]
    occurrence = await discipline.create_occurrence(
        GUILD_ID, DISCORD_ID, 900, "Conduta incompatível registrada"
    )

    warning = await discipline.apply_warning(
        GUILD_ID,
        DISCORD_ID,
        901,
        "MODERADA",
        "Decisão do Comando",
        occurrence_id=int(occurrence["occurrence_id"]),
    )
    converted = await discipline.get_occurrence(GUILD_ID, int(occurrence["occurrence_id"]))
    assert converted["status"] == "CONVERTED_TO_WARNING"
    assert int(converted["converted_punishment_id"]) == int(warning["punishment_id"])

    fulfilled = await discipline.fulfill_warning(
        GUILD_ID, int(warning["punishment_id"]), 902, "Medida cumprida"
    )
    assert fulfilled["status"] == "FULFILLED"
    persisted = await database.fetchone(
        "SELECT * FROM punishments WHERE id=?", (warning["punishment_id"],)
    )
    assert persisted["status"] == "FULFILLED"
    assert persisted["fulfilled_reason"] == "Medida cumprida"


@pytest.mark.asyncio
async def test_immediate_suspension_closes_shift_and_blocks_member(service_bundle):
    discipline = service_bundle["discipline"]
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    database = service_bundle["database"]
    members = service_bundle["members"]
    started = await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)

    result = await discipline.apply_suspension(
        GUILD_ID,
        DISCORD_ID,
        900,
        "Suspensão cautelar",
        starts_at=clock.value,
        duration_days=3,
    )
    assert result["status"] == "ACTIVE"
    assert result["shift_closed"] is True
    assert (await members.get(GUILD_ID, DISCORD_ID))["status"] == "SUSPENDED"
    shift = await database.fetchone("SELECT * FROM shifts WHERE id=?", (started.shift_id,))
    assert shift["status"] == "CLOSED"
    assert shift["end_reason"] == "MEMBER_SUSPENDED"


@pytest.mark.asyncio
async def test_scheduled_suspension_survives_restart_clock_and_restores_status(service_bundle):
    discipline = service_bundle["discipline"]
    personnel = service_bundle["personnel"]
    members = service_bundle["members"]
    clock = service_bundle["clock"]
    starts_at = clock.value + DAY_MS

    scheduled = await discipline.apply_suspension(
        GUILD_ID,
        DISCORD_ID,
        900,
        "Suspensão programada",
        starts_at=starts_at,
        duration_days=1,
    )
    assert scheduled["status"] == "SCHEDULED"
    assert (await members.get(GUILD_ID, DISCORD_ID))["status"] == "ACTIVE"

    clock.advance(DAY_MS + 1)
    activated = await personnel.expire_due(GUILD_ID)
    assert activated == [(DISCORD_ID, "SUSPENDED")]
    assert (await members.get(GUILD_ID, DISCORD_ID))["status"] == "SUSPENDED"

    clock.advance(DAY_MS)
    expired = await personnel.expire_due(GUILD_ID)
    assert expired == [(DISCORD_ID, "ACTIVE")]
    assert (await members.get(GUILD_ID, DISCORD_ID))["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_concurrent_warning_completion_has_one_winner(service_bundle):
    discipline = service_bundle["discipline"]
    warning = await discipline.apply_warning(GUILD_ID, DISCORD_ID, 900, "LEVE", "Orientação formal")
    results = await asyncio.gather(
        discipline.fulfill_warning(GUILD_ID, int(warning["punishment_id"]), 901, "Cumprida"),
        discipline.fulfill_warning(
            GUILD_ID, int(warning["punishment_id"]), 902, "Cumprida novamente"
        ),
        return_exceptions=True,
    )
    assert len([result for result in results if isinstance(result, dict)]) == 1
    assert len([result for result in results if isinstance(result, ConflictError)]) == 1
