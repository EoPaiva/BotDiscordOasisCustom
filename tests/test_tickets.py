from __future__ import annotations

import asyncio

import pytest

from choque.errors import ConflictError, ValidationError
from choque.tickets import build_minimized_transcript

from .conftest import GUILD_ID

CANDIDATE_ID = 7001
TRANSFER_ID = 7002
REPORTER_ID = 7003
SUBJECT_ID = 7004
OTHER_ID = 7005
REVIEWER_ID = 9001


def candidacy_payload() -> dict[str, object]:
    return {
        "mta_nick": "Novo_Recruta",
        "character_id": "152",
        "age": 20,
        "availability": "Noites e finais de semana",
        "motivation": "Quero integrar a equipe.",
    }


def transfer_payload() -> dict[str, object]:
    return {
        "mta_nick": "Policial_Transferido",
        "character_id": "99",
        "origin_organization": "Polícia Militar",
        "origin_rank": "Cabo",
        "motivation": "Mudança de unidade.",
    }


@pytest.mark.asyncio
async def test_candidacy_approval_creates_existing_member_application_atomically(service_bundle):
    tickets = service_bundle["tickets"]
    database = service_bundle["database"]

    ticket_id = await tickets.create(GUILD_ID, CANDIDATE_ID, "CANDIDACY", candidacy_payload())
    ticket = await tickets.decide(
        GUILD_ID,
        ticket_id,
        REVIEWER_ID,
        approved=True,
        reason="Aprovado na entrevista.",
    )

    assert ticket["status"] == "APPROVED"
    assert ticket["member_application_id"] is not None
    application = await database.fetchone(
        "SELECT * FROM member_applications WHERE id=?",
        (ticket["member_application_id"],),
    )
    assert application["discord_id"] == CANDIDATE_ID
    assert application["status"] == "PENDING"
    assert application["mta_nick"] == "Novo_Recruta"
    audits = await database.fetchall(
        "SELECT action FROM audit_logs WHERE target_id=? ORDER BY id",
        (CANDIDATE_ID,),
    )
    assert [row["action"] for row in audits] == [
        "SERVICE_TICKET_SUBMITTED",
        "MEMBER_APPLICATION_SUBMITTED",
        "SERVICE_TICKET_APPROVED",
    ]


@pytest.mark.asyncio
async def test_duplicate_open_ticket_is_rejected_and_history_is_preserved(service_bundle):
    tickets = service_bundle["tickets"]
    database = service_bundle["database"]

    first = await tickets.create(GUILD_ID, TRANSFER_ID, "TRANSFER", transfer_payload())
    with pytest.raises(ConflictError, match="transferência pendente"):
        await tickets.create(GUILD_ID, TRANSFER_ID, "TRANSFER", transfer_payload())
    await tickets.decide(
        GUILD_ID, first, REVIEWER_ID, approved=False, reason="Documentação insuficiente."
    )
    second = await tickets.create(GUILD_ID, TRANSFER_ID, "TRANSFER", transfer_payload())

    assert second != first
    rows = await database.fetchall(
        "SELECT status FROM service_tickets WHERE guild_id=? AND discord_id=? ORDER BY id",
        (GUILD_ID, TRANSFER_ID),
    )
    assert [row["status"] for row in rows] == ["REJECTED", "PENDING"]


@pytest.mark.asyncio
async def test_concurrent_decisions_only_process_ticket_once(service_bundle):
    tickets = service_bundle["tickets"]
    database = service_bundle["database"]
    ticket_id = await tickets.create(GUILD_ID, TRANSFER_ID, "TRANSFER", transfer_payload())

    results = await asyncio.gather(
        tickets.decide(GUILD_ID, ticket_id, REVIEWER_ID, approved=True, reason="Aprovado."),
        tickets.decide(GUILD_ID, ticket_id, REVIEWER_ID + 1, approved=False, reason="Negado."),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1
    audits = await database.fetchone(
        """
        SELECT COUNT(*) AS total FROM audit_logs
        WHERE action IN ('SERVICE_TICKET_APPROVED','SERVICE_TICKET_REJECTED')
          AND after_json LIKE ?
        """,
        (f'%"ticket_id": {ticket_id}%',),
    )
    assert audits["total"] == 1


@pytest.mark.asyncio
async def test_report_is_private_structured_and_cannot_target_requester(service_bundle):
    tickets = service_bundle["tickets"]

    with pytest.raises(ValidationError, match="outra pessoa"):
        await tickets.create(
            GUILD_ID,
            REPORTER_ID,
            "REPORT",
            {"details": "Relato"},
            subject_discord_id=REPORTER_ID,
        )
    ticket_id = await tickets.create(
        GUILD_ID,
        REPORTER_ID,
        "REPORT",
        {"details": "Relato completo", "evidence": "https://example.com/evidence"},
        subject_discord_id=SUBJECT_ID,
    )
    mine = await tickets.mine(GUILD_ID, REPORTER_ID)
    counts = await tickets.pending_counts(GUILD_ID)
    queue = await tickets.pending(GUILD_ID, ("REPORT",))

    assert [row["id"] for row in mine] == [ticket_id]
    assert counts["REPORT"] == 1
    assert [row["subject_discord_id"] for row in queue] == [SUBJECT_ID]


@pytest.mark.asyncio
async def test_other_subject_is_private_validated_and_available_in_admin_queue(service_bundle):
    tickets = service_bundle["tickets"]

    with pytest.raises(ValidationError, match="campos obrigatórios"):
        await tickets.create(
            GUILD_ID,
            OTHER_ID,
            "OTHER",
            {"subject": "", "details": "Preciso de ajuda."},
        )

    ticket_id = await tickets.create(
        GUILD_ID,
        OTHER_ID,
        "OTHER",
        {
            "subject": "Dúvida sobre o serviço",
            "details": "Gostaria de orientação da equipe administrativa.",
            "evidence": "",
        },
    )
    mine = await tickets.mine(GUILD_ID, OTHER_ID)
    counts = await tickets.pending_counts(GUILD_ID)
    queue = await tickets.pending(GUILD_ID, ("OTHER",))

    assert [row["id"] for row in mine] == [ticket_id]
    assert counts["OTHER"] == 1
    assert [row["id"] for row in queue] == [ticket_id]
    assert queue[0]["subject_discord_id"] is None


@pytest.mark.asyncio
async def test_ticket_room_is_bound_once_and_recoverable(service_bundle):
    tickets = service_bundle["tickets"]
    database = service_bundle["database"]
    ticket_id = await tickets.create(
        GUILD_ID,
        OTHER_ID,
        "OTHER",
        {"subject": "Acesso", "details": "Preciso de atendimento privado."},
    )

    requiring_room = await tickets.tickets_requiring_rooms(GUILD_ID)
    assert [row["id"] for row in requiring_room] == [ticket_id]

    room = await tickets.bind_room(GUILD_ID, ticket_id, 80001)
    await tickets.set_room_message(GUILD_ID, ticket_id, 81001)
    stored = await tickets.room_by_channel(GUILD_ID, 80001)
    requiring_room = await tickets.tickets_requiring_rooms(GUILD_ID)

    assert room["requester_id"] == OTHER_ID
    assert stored["ticket_id"] == ticket_id
    assert (await tickets.room_for_ticket(GUILD_ID, ticket_id))["control_message_id"] == 81001
    assert [row["id"] for row in requiring_room] == [ticket_id]
    audit = await database.fetchone(
        "SELECT action FROM audit_logs WHERE action='TICKET_ROOM_BOUND' AND guild_id=?",
        (GUILD_ID,),
    )
    assert audit["action"] == "TICKET_ROOM_BOUND"


@pytest.mark.asyncio
async def test_requester_close_is_atomic_and_archival_is_idempotent(service_bundle):
    tickets = service_bundle["tickets"]
    database = service_bundle["database"]
    ticket_id = await tickets.create(
        GUILD_ID,
        OTHER_ID,
        "OTHER",
        {"subject": "Encerrar", "details": "Atendimento resolvido."},
    )
    await tickets.bind_room(GUILD_ID, ticket_id, 80002)

    ticket = await tickets.close_by_request(
        GUILD_ID,
        ticket_id,
        OTHER_ID,
        "Dúvida resolvida.",
    )
    assert ticket["status"] == "CLOSED"
    assert (await tickets.room_for_ticket(GUILD_ID, ticket_id))["status"] == "CLOSED"
    with pytest.raises(ConflictError, match="já foi encerrado"):
        await tickets.close_by_request(
            GUILD_ID,
            ticket_id,
            OTHER_ID,
            "Segunda tentativa.",
        )

    await tickets.mark_room_archived(GUILD_ID, ticket_id, OTHER_ID)
    await tickets.mark_room_archived(GUILD_ID, ticket_id, OTHER_ID)
    assert (await tickets.room_for_ticket(GUILD_ID, ticket_id))["status"] == "ARCHIVED"
    audit = await database.fetchone(
        """
        SELECT COUNT(*) AS total FROM audit_logs
        WHERE guild_id=? AND action='TICKET_ROOM_ARCHIVED'
        """,
        (GUILD_ID,),
    )
    assert audit["total"] == 1


@pytest.mark.asyncio
async def test_decision_room_closure_preserves_final_ticket_status(service_bundle):
    tickets = service_bundle["tickets"]
    ticket_id = await tickets.create(GUILD_ID, TRANSFER_ID, "TRANSFER", transfer_payload())
    await tickets.bind_room(GUILD_ID, ticket_id, 80003)
    decided = await tickets.decide(
        GUILD_ID,
        ticket_id,
        REVIEWER_ID,
        approved=False,
        reason="Documentação insuficiente.",
    )

    await tickets.mark_room_closed(
        GUILD_ID,
        ticket_id,
        REVIEWER_ID,
        "Documentação insuficiente.",
    )

    assert (await tickets.get(GUILD_ID, ticket_id))["status"] == "REJECTED"
    assert decided["status"] == "REJECTED"
    assert (await tickets.room_for_ticket(GUILD_ID, ticket_id))["status"] == "CLOSED"


@pytest.mark.asyncio
async def test_ticket_claim_is_concurrency_safe_and_release_is_owned(service_bundle):
    tickets = service_bundle["tickets"]
    ticket_id = await tickets.create(
        GUILD_ID, OTHER_ID, "OTHER", {"subject": "Acesso", "details": "Ajuda."}
    )

    results = await asyncio.gather(
        tickets.claim(GUILD_ID, ticket_id, REVIEWER_ID),
        tickets.claim(GUILD_ID, ticket_id, REVIEWER_ID + 1),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, Exception)]
    conflicts = [result for result in results if isinstance(result, ConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    winner = int(successes[0]["claimed_by"])
    with pytest.raises(ConflictError, match="Somente quem assumiu"):
        await tickets.release(GUILD_ID, ticket_id, REVIEWER_ID + 9)
    released = await tickets.release(GUILD_ID, ticket_id, winner)
    assert released["claimed_by"] is None


@pytest.mark.asyncio
async def test_priority_and_participant_changes_are_append_only(service_bundle):
    tickets = service_bundle["tickets"]
    database = service_bundle["database"]
    ticket_id = await tickets.create(
        GUILD_ID, OTHER_ID, "OTHER", {"subject": "Prioridade", "details": "Ajuda."}
    )
    updated = await tickets.set_priority(GUILD_ID, ticket_id, REVIEWER_ID, "urgent")
    assert updated["priority"] == "URGENT"

    await tickets.add_participant(GUILD_ID, ticket_id, SUBJECT_ID, REVIEWER_ID)
    with pytest.raises(ConflictError, match="já participa"):
        await tickets.add_participant(GUILD_ID, ticket_id, SUBJECT_ID, REVIEWER_ID)
    assert [row["discord_id"] for row in await tickets.participants(GUILD_ID, ticket_id)] == [
        SUBJECT_ID
    ]
    await tickets.remove_participant(GUILD_ID, ticket_id, SUBJECT_ID, REVIEWER_ID)
    assert await tickets.participants(GUILD_ID, ticket_id) == []
    history = await tickets.operation_history(GUILD_ID, ticket_id)
    assert {row["event_type"] for row in history} >= {
        "PRIORITY_CHANGED",
        "PARTICIPANT_ADDED",
        "PARTICIPANT_REMOVED",
    }
    rows = await database.fetchall(
        "SELECT removed_at FROM ticket_participants WHERE guild_id=? AND ticket_id=?",
        (GUILD_ID, ticket_id),
    )
    assert len(rows) == 1 and rows[0]["removed_at"] is not None


@pytest.mark.asyncio
async def test_requester_notification_is_rate_limited(service_bundle):
    tickets = service_bundle["tickets"]
    ticket_id = await tickets.create(
        GUILD_ID, OTHER_ID, "OTHER", {"subject": "Aviso", "details": "Ajuda."}
    )
    await tickets.mark_requester_notified(GUILD_ID, ticket_id, REVIEWER_ID, cooldown_seconds=60)
    with pytest.raises(ConflictError, match="avisado recentemente"):
        await tickets.mark_requester_notified(GUILD_ID, ticket_id, REVIEWER_ID, cooldown_seconds=60)


@pytest.mark.asyncio
async def test_transcript_is_minimized_redacted_and_hash_only_is_persisted(service_bundle):
    tickets = service_bundle["tickets"]
    database = service_bundle["database"]
    ticket_id = await tickets.create(
        GUILD_ID, OTHER_ID, "OTHER", {"subject": "Transcrição", "details": "Ajuda."}
    )
    content = build_minimized_transcript(
        ticket_id,
        [
            {
                "created_at": 100,
                "author_id": OTHER_ID,
                "content": "token=segredo-super-sensivel",
                "attachment_count": 1,
            },
            {"created_at": 101, "author_id": REVIEWER_ID, "content": "Recebido."},
        ],
    )
    assert "segredo-super-sensivel" not in content
    assert "[SEGREDO REDIGIDO]" in content
    metadata = await tickets.record_transcript(
        GUILD_ID, ticket_id, REVIEWER_ID, content, 2, "Encerramento"
    )
    assert metadata["message_count"] == 2
    columns = await database.fetchall("PRAGMA table_info(ticket_transcripts)")
    assert "content_text" not in {row["name"] for row in columns}


@pytest.mark.asyncio
async def test_ticket_reopens_same_room_and_preserves_close_history(service_bundle):
    tickets = service_bundle["tickets"]
    ticket_id = await tickets.create(
        GUILD_ID, OTHER_ID, "OTHER", {"subject": "Reabrir", "details": "Ajuda."}
    )
    await tickets.bind_room(
        GUILD_ID,
        ticket_id,
        81000,
        active_category_id=82000,
        archive_category_id=83000,
        responsible_role_id=84000,
    )
    await tickets.close_by_request(GUILD_ID, ticket_id, OTHER_ID, "Resolvido.")
    await tickets.mark_room_archived(GUILD_ID, ticket_id, REVIEWER_ID)
    reopened = await tickets.reopen(GUILD_ID, ticket_id, REVIEWER_ID, "Nova evidência.")
    room = await tickets.room_for_ticket(GUILD_ID, ticket_id)
    assert reopened["status"] == "IN_REVIEW"
    assert room["status"] == "OPEN"
    assert room["channel_id"] == 81000
    assert room["active_category_id"] == 82000
    assert room["archive_category_id"] == 83000
    assert room["responsible_role_id"] == 84000
    history = await tickets.operation_history(GUILD_ID, ticket_id)
    assert {row["event_type"] for row in history} >= {"CLOSED", "ARCHIVED", "REOPENED"}
