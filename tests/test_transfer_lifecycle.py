from __future__ import annotations

import asyncio
import json

import pytest

from choque.errors import ConflictError, ValidationError

from .conftest import GUILD_ID

REQUESTER_ID = 7_002
REVIEWER_ID = 9_001


def transfer_payload() -> dict[str, object]:
    return {
        "mta_nick": "Policial_Transferido",
        "character_id": "99",
        "origin_organization": "Polícia Militar",
        "origin_rank": "Cabo",
        "motivation": "Mudança de unidade.",
    }


async def seed_ranks(database) -> tuple[int, int, int]:
    rank_ids: list[int] = []
    for level, name, prefix in (
        (1, "Recruta", "REC"),
        (2, "Soldado", "SD"),
        (3, "Cabo", "CB"),
    ):
        rank_id = await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
            VALUES (?, ?, ?, ?, 'MEMBRO', 1)
            """,
            (GUILD_ID, name, prefix, level),
        )
        rank_ids.append(rank_id)
    return rank_ids[0], rank_ids[1], rank_ids[2]


@pytest.mark.asyncio
async def test_transfer_submission_creates_stable_protocol_and_append_only_timeline(
    service_bundle,
):
    tickets = service_bundle["tickets"]
    database = service_bundle["database"]

    ticket_id = await tickets.create(
        GUILD_ID,
        REQUESTER_ID,
        "TRANSFER",
        transfer_payload(),
    )

    case = await tickets.transfer_case_for_ticket(GUILD_ID, ticket_id)
    history = await tickets.transfer_history(GUILD_ID, ticket_id)
    mine = await tickets.mine(GUILD_ID, REQUESTER_ID)

    assert case["protocol"] == f"TRF-{GUILD_ID}-{ticket_id:06d}"
    assert case["status"] == "PENDING"
    assert case["requester_id"] == REQUESTER_ID
    assert json.loads(case["request_snapshot_json"]) == transfer_payload()
    assert [row["event_type"] for row in history] == ["SUBMITTED"]
    assert mine[0]["transfer_protocol"] == case["protocol"]

    audit = await database.fetchone(
        """
        SELECT action, after_json FROM audit_logs
        WHERE guild_id=? AND action='TRANSFER_SUBMITTED'
        """,
        (GUILD_ID,),
    )
    assert audit["action"] == "TRANSFER_SUBMITTED"
    assert json.loads(audit["after_json"])["protocol"] == case["protocol"]


@pytest.mark.asyncio
async def test_transfer_rank_cap_is_configurable_and_rejects_escalation(service_bundle):
    tickets = service_bundle["tickets"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    recruit_rank_id, soldier_rank_id, corporal_rank_id = await seed_ranks(database)
    await settings.set(GUILD_ID, "transfer_max_rank_level", 2, REVIEWER_ID)
    ticket_id = await tickets.create(
        GUILD_ID,
        REQUESTER_ID,
        "TRANSFER",
        transfer_payload(),
    )

    options = await tickets.transfer_rank_options(GUILD_ID)
    assert [(row["id"], row["level"]) for row in options] == [
        (recruit_rank_id, 1),
        (soldier_rank_id, 2),
    ]

    with pytest.raises(ValidationError, match="limite de patente"):
        await tickets.decide_transfer(
            GUILD_ID,
            ticket_id,
            REVIEWER_ID,
            approved=True,
            reason="Experiência validada.",
            approved_rank_id=corporal_rank_id,
        )

    ticket = await tickets.get(GUILD_ID, ticket_id)
    case = await tickets.transfer_case_for_ticket(GUILD_ID, ticket_id)
    assert ticket["status"] == "PENDING"
    assert case["status"] == "PENDING"
    assert case["member_application_id"] is None


@pytest.mark.asyncio
async def test_transfer_approval_never_changes_membership_and_pins_approved_rank(
    service_bundle,
):
    tickets = service_bundle["tickets"]
    settings = service_bundle["settings"]
    members = service_bundle["members"]
    database = service_bundle["database"]
    _, soldier_rank_id, corporal_rank_id = await seed_ranks(database)
    await settings.set(GUILD_ID, "transfer_max_rank_level", 2, REVIEWER_ID)
    ticket_id = await tickets.create(
        GUILD_ID,
        REQUESTER_ID,
        "TRANSFER",
        transfer_payload(),
    )

    with pytest.raises(ValidationError, match="fluxo próprio"):
        await tickets.decide(
            GUILD_ID,
            ticket_id,
            REVIEWER_ID,
            approved=True,
            reason="Não pode contornar o protocolo.",
        )

    ticket = await tickets.decide_transfer(
        GUILD_ID,
        ticket_id,
        REVIEWER_ID,
        approved=True,
        reason="Experiência validada.",
        approved_rank_id=soldier_rank_id,
    )
    case = await tickets.transfer_case_for_ticket(GUILD_ID, ticket_id)
    application = await members.get_application(int(case["member_application_id"]))

    assert ticket["status"] == "APPROVED"
    assert case["status"] == "APPROVED"
    assert case["approved_rank_id"] == soldier_rank_id
    assert case["max_rank_level_snapshot"] == 2
    assert application["status"] == "PENDING"
    assert await members.get(GUILD_ID, REQUESTER_ID) is None

    member = await members.review_application(
        int(application["id"]),
        REVIEWER_ID + 1,
        True,
        "Ingresso confirmado após conferência final.",
        "Policial Transferido",
        corporal_rank_id,
        enqueue_discord_sync=True,
    )
    applied_case = await tickets.transfer_case_for_ticket(GUILD_ID, ticket_id)
    history = await tickets.transfer_history(GUILD_ID, ticket_id)

    assert member["rank_id"] == soldier_rank_id
    assert applied_case["status"] == "APPLIED"
    assert applied_case["applied_by"] == REVIEWER_ID + 1
    assert [row["event_type"] for row in history] == [
        "SUBMITTED",
        "APPROVED",
        "APPLIED",
    ]
    outbox = await database.fetchone(
        """
        SELECT action_type, target_discord_id FROM web_action_outbox
        WHERE guild_id=? AND target_discord_id=?
        """,
        (GUILD_ID, REQUESTER_ID),
    )
    assert dict(outbox) == {
        "action_type": "MEMBER_SYNC",
        "target_discord_id": REQUESTER_ID,
    }


@pytest.mark.asyncio
async def test_concurrent_transfer_decisions_create_only_one_application(service_bundle):
    tickets = service_bundle["tickets"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    _, soldier_rank_id, _ = await seed_ranks(database)
    await settings.set(GUILD_ID, "transfer_max_rank_level", 2, REVIEWER_ID)
    ticket_id = await tickets.create(
        GUILD_ID,
        REQUESTER_ID,
        "TRANSFER",
        transfer_payload(),
    )

    results = await asyncio.gather(
        tickets.decide_transfer(
            GUILD_ID,
            ticket_id,
            REVIEWER_ID,
            approved=True,
            reason="Aprovado pelo primeiro revisor.",
            approved_rank_id=soldier_rank_id,
        ),
        tickets.decide_transfer(
            GUILD_ID,
            ticket_id,
            REVIEWER_ID + 1,
            approved=True,
            reason="Aprovado pelo segundo revisor.",
            approved_rank_id=soldier_rank_id,
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1
    applications = await database.fetchone(
        "SELECT COUNT(*) AS total FROM member_applications WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, REQUESTER_ID),
    )
    assert applications["total"] == 1


@pytest.mark.asyncio
async def test_transfer_close_and_reopen_keep_protocol_state_consistent(service_bundle):
    tickets = service_bundle["tickets"]
    ticket_id = await tickets.create(
        GUILD_ID,
        REQUESTER_ID,
        "TRANSFER",
        transfer_payload(),
    )
    await tickets.bind_room(GUILD_ID, ticket_id, 81_200)

    await tickets.close_by_request(
        GUILD_ID,
        ticket_id,
        REQUESTER_ID,
        "Solicitante desistiu.",
    )
    cancelled = await tickets.transfer_case_for_ticket(GUILD_ID, ticket_id)
    assert cancelled["status"] == "CANCELLED"

    await tickets.mark_room_archived(GUILD_ID, ticket_id, REVIEWER_ID)
    reopened_ticket = await tickets.reopen(
        GUILD_ID,
        ticket_id,
        REVIEWER_ID,
        "Solicitante apresentou nova documentação.",
    )
    reopened = await tickets.transfer_case_for_ticket(GUILD_ID, ticket_id)
    history = await tickets.transfer_history(GUILD_ID, ticket_id)

    assert reopened_ticket["status"] == "IN_REVIEW"
    assert reopened["status"] == "PENDING"
    assert [row["event_type"] for row in history] == [
        "SUBMITTED",
        "CANCELLED",
        "REOPENED",
    ]


@pytest.mark.asyncio
async def test_transfer_application_stops_if_approved_rank_was_deactivated(service_bundle):
    tickets = service_bundle["tickets"]
    settings = service_bundle["settings"]
    members = service_bundle["members"]
    database = service_bundle["database"]
    _, soldier_rank_id, _ = await seed_ranks(database)
    await settings.set(GUILD_ID, "transfer_max_rank_level", 2, REVIEWER_ID)
    ticket_id = await tickets.create(
        GUILD_ID,
        REQUESTER_ID,
        "TRANSFER",
        transfer_payload(),
    )
    await tickets.decide_transfer(
        GUILD_ID,
        ticket_id,
        REVIEWER_ID,
        approved=True,
        reason="Experiência validada.",
        approved_rank_id=soldier_rank_id,
    )
    transfer = await tickets.transfer_case_for_ticket(GUILD_ID, ticket_id)
    application_id = int(transfer["member_application_id"])
    await database.execute(
        "UPDATE ranks SET active=0 WHERE guild_id=? AND id=?",
        (GUILD_ID, soldier_rank_id),
    )

    with pytest.raises(ConflictError, match="patente aprovada"):
        await members.review_application(
            application_id,
            REVIEWER_ID + 1,
            True,
            "Conferência final.",
            "Policial Transferido",
            None,
        )

    assert await members.get(GUILD_ID, REQUESTER_ID) is None
    assert (await members.get_application(application_id))["status"] == "PENDING"
    assert (await tickets.transfer_case_for_ticket(GUILD_ID, ticket_id))["status"] == "APPROVED"
