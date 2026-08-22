from __future__ import annotations

import asyncio

import pytest

from choque.errors import ConflictError, PermissionDenied, ValidationError
from choque.models import PersonnelActionType, PunishmentType

from .conftest import DISCORD_ID, GUILD_ID


async def seed_ranks(service_bundle) -> list[int]:
    database = service_bundle["database"]
    rank_ids = []
    for level, name in enumerate(("Recruta", "Soldado", "Cabo"), start=1):
        await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, discord_role_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (GUILD_ID, name, f"[R{level}]", level, 8_000 + level, 1),
        )
        row = await database.fetchone(
            "SELECT id FROM ranks WHERE guild_id=? AND level=?", (GUILD_ID, level)
        )
        rank_ids.append(int(row["id"]))
    await database.execute(
        "UPDATE members SET rank_id=? WHERE guild_id=? AND discord_id=?",
        (rank_ids[0], GUILD_ID, DISCORD_ID),
    )
    return rank_ids


@pytest.mark.asyncio
async def test_promotion_and_demotion_are_ordered_and_append_only(service_bundle):
    personnel = service_bundle["personnel"]
    database = service_bundle["database"]
    await seed_ranks(service_bundle)

    promoted = await personnel.change_rank(
        GUILD_ID,
        DISCORD_ID,
        PersonnelActionType.PROMOTION,
        actor_id=999,
        reason="Mérito operacional",
    )
    demoted = await personnel.change_rank(
        GUILD_ID,
        DISCORD_ID,
        PersonnelActionType.DEMOTION,
        actor_id=999,
        reason="Revisão administrativa",
    )

    assert promoted["from_rank_name"] == "Recruta"
    assert promoted["to_rank_name"] == "Soldado"
    assert demoted["from_rank_name"] == "Soldado"
    assert demoted["to_rank_name"] == "Recruta"
    actions = await database.fetchall("SELECT action_type FROM personnel_actions ORDER BY id")
    assert [row["action_type"] for row in actions] == ["PROMOTION", "DEMOTION"]


@pytest.mark.asyncio
async def test_member_cannot_change_own_rank(service_bundle):
    personnel = service_bundle["personnel"]
    ranks = await seed_ranks(service_bundle)
    with pytest.raises(PermissionDenied, match="própria patente"):
        await personnel.change_rank_to(
            GUILD_ID,
            DISCORD_ID,
            ranks[1],
            PersonnelActionType.PROMOTION,
            actor_id=DISCORD_ID,
            reason="Tentativa de auto promoção",
        )


@pytest.mark.asyncio
async def test_rank_boundary_rejects_second_demotion(service_bundle):
    personnel = service_bundle["personnel"]
    await seed_ranks(service_bundle)
    with pytest.raises(ConflictError, match="patente mais baixa"):
        await personnel.change_rank(
            GUILD_ID,
            DISCORD_ID,
            PersonnelActionType.DEMOTION,
            actor_id=999,
            reason="Sem nível inferior",
        )


@pytest.mark.asyncio
async def test_career_allows_human_selected_target_rank(service_bundle):
    personnel = service_bundle["personnel"]
    rank_ids = await seed_ranks(service_bundle)

    result = await personnel.change_rank_to(
        GUILD_ID,
        DISCORD_ID,
        rank_ids[2],
        PersonnelActionType.PROMOTION,
        actor_id=999,
        reason="Decisão humana confirmada",
    )

    assert result["from_rank_name"] == "Recruta"
    assert result["to_rank_name"] == "Cabo"
    profile = await personnel.career_profile(GUILD_ID, DISCORD_ID)
    assert profile["rank_name"] == "Cabo"


@pytest.mark.asyncio
async def test_career_rejects_target_in_wrong_direction(service_bundle):
    personnel = service_bundle["personnel"]
    rank_ids = await seed_ranks(service_bundle)

    with pytest.raises(ValidationError, match="acima"):
        await personnel.change_rank_to(
            GUILD_ID,
            DISCORD_ID,
            rank_ids[0],
            PersonnelActionType.PROMOTION,
            actor_id=999,
            reason="Destino inválido",
        )


@pytest.mark.asyncio
async def test_career_history_is_paginated_and_append_only(service_bundle):
    personnel = service_bundle["personnel"]
    rank_ids = await seed_ranks(service_bundle)
    await personnel.change_rank_to(
        GUILD_ID,
        DISCORD_ID,
        rank_ids[2],
        PersonnelActionType.PROMOTION,
        999,
        "Promoção especial",
    )
    await personnel.change_rank_to(
        GUILD_ID,
        DISCORD_ID,
        rank_ids[1],
        PersonnelActionType.DEMOTION,
        999,
        "Revisão confirmada",
    )

    first = await personnel.career_history(GUILD_ID, DISCORD_ID, limit=1, offset=0)
    second = await personnel.career_history(GUILD_ID, DISCORD_ID, limit=1, offset=1)

    assert await personnel.career_history_count(GUILD_ID, DISCORD_ID) == 2
    assert first[0]["action_type"] == "DEMOTION"
    assert second[0]["action_type"] == "PROMOTION"


@pytest.mark.asyncio
async def test_suspension_changes_status_and_expiry_restores_member(service_bundle):
    personnel = service_bundle["personnel"]
    members = service_bundle["members"]
    clock = service_bundle["clock"]

    punishment = await personnel.apply_punishment(
        GUILD_ID,
        DISCORD_ID,
        PunishmentType.SUSPENSION,
        actor_id=999,
        reason="Apuração disciplinar",
        duration_days=1,
    )
    assert punishment["status"] == "SUSPENDED"
    assert (await members.get(GUILD_ID, DISCORD_ID))["status"] == "SUSPENDED"

    clock.advance(86_400_001)
    changes = await personnel.expire_due(GUILD_ID)
    assert changes == [(DISCORD_ID, "ACTIVE")]
    assert (await members.get(GUILD_ID, DISCORD_ID))["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_revoking_dismissal_restores_member(service_bundle):
    personnel = service_bundle["personnel"]
    members = service_bundle["members"]
    punishment = await personnel.apply_punishment(
        GUILD_ID,
        DISCORD_ID,
        PunishmentType.DISMISSAL,
        actor_id=999,
        reason="Desligamento administrativo",
    )
    assert (await members.get(GUILD_ID, DISCORD_ID))["status"] == "DISMISSED"
    revoked = await personnel.revoke_punishment(
        GUILD_ID,
        int(punishment["punishment_id"]),
        actor_id=999,
        reason="Decisão revertida",
    )
    assert revoked["member_status"] == "ACTIVE"
    assert (await members.get(GUILD_ID, DISCORD_ID))["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_concurrent_absence_review_produces_one_decision(service_bundle):
    personnel = service_bundle["personnel"]
    clock = service_bundle["clock"]
    absence_id = await personnel.submit_absence(
        GUILD_ID,
        DISCORD_ID,
        clock.value,
        clock.value + 7 * 86_400_000,
        "Viagem programada",
    )
    results = await asyncio.gather(
        personnel.review_absence(GUILD_ID, absence_id, True, actor_id=901, reason="Aprovado"),
        personnel.review_absence(GUILD_ID, absence_id, False, actor_id=902, reason="Negado"),
        return_exceptions=True,
    )
    successes = [result for result in results if isinstance(result, dict)]
    conflicts = [result for result in results if isinstance(result, ConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    row = await personnel.get_absence(GUILD_ID, absence_id)
    assert row["status"] in {"APPROVED", "REJECTED"}


@pytest.mark.asyncio
async def test_ranking_uses_valid_segments(service_bundle):
    database = service_bundle["database"]
    personnel = service_bundle["personnel"]
    clock = service_bundle["clock"]
    member = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?", (GUILD_ID, DISCORD_ID)
    )
    await database.execute(
        """
        INSERT INTO shifts(
            guild_id, member_id, status, started_at, ended_at, closed_at,
            end_reason, created_by, created_at
        ) VALUES (?, ?, 'CLOSED', ?, ?, ?, 'TEST', ?, ?)
        """,
        (
            GUILD_ID,
            member["id"],
            clock.value - 7_200_000,
            clock.value,
            clock.value,
            DISCORD_ID,
            clock.value - 7_200_000,
        ),
    )
    shift = await database.fetchone("SELECT id FROM shifts ORDER BY id DESC LIMIT 1")
    await database.execute(
        """
        INSERT INTO shift_segments(
            guild_id, shift_id, voice_channel_id, started_at, ended_at, end_reason
        ) VALUES (?, ?, ?, ?, ?, 'TEST')
        """,
        (GUILD_ID, shift["id"], 1001, clock.value - 7_200_000, clock.value),
    )
    rows = await personnel.ranking(GUILD_ID, 0, clock.value)
    assert int(rows[0]["total_ms"]) == 7_200_000
    assert int(rows[0]["discord_id"]) == DISCORD_ID
