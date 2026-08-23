from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio

from choque.audit import AuditService
from choque.config import Branding
from choque.database import Database
from choque.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from choque.recruitment import DEFAULT_QUESTIONS, GROUPS, RecruitmentService
from choque.web_outbox import WebActionWorker
from tests.conftest import MutableClock

GUILD_ID = 331
ADMIN_ID = 901
CANDIDATE_ID = 1001


@pytest_asyncio.fixture
async def recruitment_bundle(tmp_path):
    database = Database(tmp_path / "recruitment.db")
    await database.open()
    audit = AuditService(database, None, Branding())
    clock = MutableClock()
    service = RecruitmentService(
        database,
        audit,
        token_secret="recruitment-test-secret-with-strong-entropy",
        clock=clock,
    )
    rank_id = await database.execute(
        """
        INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
        VALUES (?, 'Recruta', 'RCT', 1, 'MEMBRO', ?)
        """,
        (GUILD_ID, clock()),
    )
    defaults = await service.ensure_defaults(GUILD_ID, ADMIN_ID)
    campaign = await service.current_campaign(GUILD_ID)
    assert campaign
    await service.update_campaign(
        GUILD_ID,
        int(campaign["id"]),
        ADMIN_ID,
        {
            "name": campaign["name"],
            "status": "OPEN",
            "opens_at": None,
            "closes_at": None,
            "cooldown_days": 30,
            "minimum_age": 16,
            "maximum_applications": None,
            "initial_rank_id": rank_id,
            "candidate_role_id": None,
            "interview_channel_id": None,
        },
    )
    yield {
        "database": database,
        "audit": audit,
        "clock": clock,
        "service": service,
        "defaults": defaults,
        "rank_id": rank_id,
    }
    await database.close()


async def _start(
    service: RecruitmentService,
    discord_id: int = CANDIDATE_ID,
    *,
    bgr_id: str = "1842",
    key: str | None = None,
):
    return await service.start_application(
        GUILD_ID,
        discord_id,
        discord_username=f"candidate-{discord_id}",
        discord_global_name="Candidato Teste",
        discord_avatar=None,
        candidate_nick=f"Candidato_{discord_id}",
        bgr_id=bgr_id,
        age=19,
        idempotency_key=key or f"application-{discord_id}-key",
        consent_accepted=True,
        guild_membership_verified=True,
    )


@pytest.mark.asyncio
async def test_defaults_seed_short_roleplay_form(recruitment_bundle) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    assert len(DEFAULT_QUESTIONS) == 10
    assert sum(group[3] for group in GROUPS) == 10
    questions = await database.fetchone(
        "SELECT COUNT(*) AS total FROM recruitment_questions WHERE guild_id=?",
        (GUILD_ID,),
    )
    application = await _start(service)
    assigned = await database.fetchone(
        "SELECT COUNT(*) AS total FROM recruitment_application_questions WHERE application_id=?",
        (application["id"],),
    )
    assert int(questions["total"]) == 10
    assert int(assigned["total"]) == 10
    assert all(
        question["min_length"] in {None, 10}
        for question in DEFAULT_QUESTIONS
    )
    assert application["protocol"].startswith("AL-")
    assert application["guild_membership_verified_at"]
    assert application["consent_accepted_at"]


@pytest.mark.asyncio
async def test_question_is_hidden_until_idempotent_server_start(recruitment_bundle) -> None:
    service = recruitment_bundle["service"]
    application = await _start(service)
    ready = await service.next_question(GUILD_ID, CANDIDATE_ID, int(application["id"]))
    assert ready["status"] == "NOT_STARTED"
    assert "question" not in ready
    started = await service.start_question(
        GUILD_ID, CANDIDATE_ID, int(application["id"]), int(ready["id"])
    )
    started_again = await service.start_question(
        GUILD_ID, CANDIDATE_ID, int(application["id"]), int(ready["id"])
    )
    assert started_again["started_at"] == started["started_at"]
    assert started_again["expires_at"] == started["expires_at"]
    assert started_again["question_token"] == started["question_token"]
    assert started["question"]["title"]


@pytest.mark.asyncio
async def test_autosave_does_not_reset_timer_and_tampered_token_is_rejected(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    clock = recruitment_bundle["clock"]
    application = await _start(service)
    ready = await service.next_question(GUILD_ID, CANDIDATE_ID, int(application["id"]))
    assigned = await database.fetchone(
        "SELECT question_snapshot_json FROM recruitment_application_questions WHERE id=?",
        (ready["id"],),
    )
    snapshot = json.loads(assigned["question_snapshot_json"])
    snapshot.update(timer_enabled=1, expected_max_length=100)
    await database.execute(
        "UPDATE recruitment_application_questions SET question_snapshot_json=? WHERE id=?",
        (json.dumps(snapshot), ready["id"]),
    )
    started = await service.start_question(
        GUILD_ID, CANDIDATE_ID, int(application["id"]), int(ready["id"])
    )
    expires_at = started["expires_at"]
    clock.advance(3_000)
    saved = await service.save_answer(
        GUILD_ID,
        CANDIDATE_ID,
        int(application["id"]),
        int(ready["id"]),
        answer="Resposta em elaboração",
        question_token=str(started["question_token"]),
        submit=False,
    )
    resumed = await service.next_question(GUILD_ID, CANDIDATE_ID, int(application["id"]))
    assert saved["saved"] is True
    assert resumed["expires_at"] == expires_at
    assert resumed["draft"] == "Resposta em elaboração"
    with pytest.raises(ConflictError):
        await service.save_answer(
            GUILD_ID,
            CANDIDATE_ID,
            int(application["id"]),
            int(ready["id"]),
            answer="Tentativa adulterada",
            question_token=str(started["question_token"]) + "x",
            submit=True,
        )


@pytest.mark.asyncio
async def test_expiry_preserves_draft_and_integrity_is_only_evidence(recruitment_bundle) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    clock = recruitment_bundle["clock"]
    application = await _start(service)
    ready = await service.next_question(GUILD_ID, CANDIDATE_ID, int(application["id"]))
    assigned = await database.fetchone(
        "SELECT question_snapshot_json FROM recruitment_application_questions WHERE id=?",
        (ready["id"],),
    )
    snapshot = json.loads(assigned["question_snapshot_json"])
    snapshot.update(timer_enabled=1, expected_max_length=100)
    await database.execute(
        "UPDATE recruitment_application_questions SET question_snapshot_json=? WHERE id=?",
        (json.dumps(snapshot), ready["id"]),
    )
    started = await service.start_question(
        GUILD_ID, CANDIDATE_ID, int(application["id"]), int(ready["id"])
    )
    await service.record_integrity_event(
        GUILD_ID,
        CANDIDATE_ID,
        int(application["id"]),
        int(ready["id"]),
        "PASTE_BLOCKED",
    )
    clock.value = int(started["expires_at"]) + 5_001
    result = await service.save_answer(
        GUILD_ID,
        CANDIDATE_ID,
        int(application["id"]),
        int(ready["id"]),
        answer="Rascunho preservado no encerramento",
        question_token=str(started["question_token"]),
        submit=True,
    )
    row = await database.fetchone(
        "SELECT status, final_answer_json FROM recruitment_application_questions WHERE id=?",
        (ready["id"],),
    )
    candidate = await database.fetchone(
        "SELECT status FROM recruitment_applications WHERE id=?", (application["id"],)
    )
    assert result["status"] == "TIME_EXPIRED"
    assert json.loads(row["final_answer_json"]) == "Rascunho preservado no encerramento"
    assert candidate["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_candidate_cannot_access_another_application(recruitment_bundle) -> None:
    service = recruitment_bundle["service"]
    application = await _start(service)
    with pytest.raises(NotFoundError):
        await service.next_question(GUILD_ID, CANDIDATE_ID + 1, int(application["id"]))


@pytest.mark.asyncio
async def test_double_question_submit_is_idempotent(recruitment_bundle) -> None:
    service = recruitment_bundle["service"]
    application = await _start(service)
    ready = await service.next_question(GUILD_ID, CANDIDATE_ID, int(application["id"]))
    started = await service.start_question(
        GUILD_ID, CANDIDATE_ID, int(application["id"]), int(ready["id"])
    )
    first = await service.save_answer(
        GUILD_ID,
        CANDIDATE_ID,
        int(application["id"]),
        int(ready["id"]),
        answer="Quero atuar com disciplina na CHOQUE.",
        question_token=str(started["question_token"]),
        submit=True,
    )
    second = await service.save_answer(
        GUILD_ID,
        CANDIDATE_ID,
        int(application["id"]),
        int(ready["id"]),
        answer="Quero atuar com disciplina na CHOQUE.",
        question_token=str(started["question_token"]),
        submit=True,
    )
    assert first == second


@pytest.mark.asyncio
async def test_concurrent_start_returns_one_active_application(recruitment_bundle) -> None:
    service = recruitment_bundle["service"]
    first, second = await asyncio.gather(
        _start(service, key="concurrent-start-key-a"),
        _start(service, key="concurrent-start-key-b"),
    )
    assert first["id"] == second["id"]


@pytest.mark.asyncio
async def test_campaign_capacity_is_enforced_inside_concurrent_transaction(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    campaign = await service.current_campaign(GUILD_ID)
    assert campaign
    await service.update_campaign(
        GUILD_ID,
        int(campaign["id"]),
        ADMIN_ID,
        {
            "name": campaign["name"],
            "status": "OPEN",
            "opens_at": None,
            "closes_at": None,
            "cooldown_days": 30,
            "minimum_age": 16,
            "maximum_applications": 1,
            "initial_rank_id": recruitment_bundle["rank_id"],
            "candidate_role_id": None,
            "interview_channel_id": None,
        },
    )
    results = await asyncio.gather(
        _start(service, CANDIDATE_ID, bgr_id="7001", key="capacity-candidate-one"),
        _start(service, CANDIDATE_ID + 1, bgr_id="7002", key="capacity-candidate-two"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1


@pytest.mark.asyncio
async def test_duplicate_bgr_and_missing_consent_are_blocked(recruitment_bundle) -> None:
    service = recruitment_bundle["service"]
    await _start(service, bgr_id="9001")
    with pytest.raises(ConflictError):
        await _start(service, CANDIDATE_ID + 1, bgr_id="9001")
    with pytest.raises(ValidationError):
        await service.start_application(
            GUILD_ID,
            CANDIDATE_ID + 2,
            discord_username="candidate",
            discord_global_name=None,
            discord_avatar=None,
            candidate_nick="Candidate",
            bgr_id="9002",
            age=19,
            idempotency_key="missing-consent-key",
            consent_accepted=False,
            guild_membership_verified=True,
        )


@pytest.mark.asyncio
async def test_submission_assignment_and_human_approval_are_atomic_and_idempotent(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await _start(service)
    await database.execute(
        """
        UPDATE recruitment_application_questions
        SET status='SUBMITTED', final_answer_json='"Resposta de teste"', submitted_at=?
        WHERE application_id=?
        """,
        (recruitment_bundle["clock"](), application["id"]),
    )
    submitted = await service.submit_application(
        GUILD_ID, CANDIDATE_ID, int(application["id"]), 1
    )
    submitted_retry = await service.submit_application(
        GUILD_ID, CANDIDATE_ID, int(application["id"]), 1
    )
    assert submitted_retry["id"] == submitted["id"]
    assigned = await service.assign(GUILD_ID, int(application["id"]), ADMIN_ID, 2)
    approved = await service.decide(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        int(assigned["version"]),
        approved=True,
        internal_reason="Requisitos e avaliação conferidos",
        candidate_message="Candidatura aprovada pelo comando.",
    )
    approved_retry = await service.decide(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        int(assigned["version"]),
        approved=True,
        internal_reason="Requisitos e avaliação conferidos",
        candidate_message="Candidatura aprovada pelo comando.",
    )
    assert approved_retry["id"] == approved["id"]
    assert approved["status"] == "APPROVED"
    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, CANDIDATE_ID),
    )
    followups = await database.fetchone(
        "SELECT COUNT(*) AS total FROM recruit_followups WHERE origin_application_id=?",
        (application["id"],),
    )
    syncs = await database.fetchall(
        "SELECT payload_json FROM web_action_outbox WHERE target_discord_id=?",
        (CANDIDATE_ID,),
    )
    registration = await database.fetchone(
        "SELECT * FROM registration_gate_records WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, CANDIDATE_ID),
    )
    onboarding = await database.fetchone(
        "SELECT * FROM recruit_onboarding_checklists WHERE guild_id=? AND member_id=?",
        (GUILD_ID, member["id"]),
    )
    assert member["origin_recruitment_application_id"] == application["id"]
    assert int(followups["total"]) == 1
    assert len(syncs) == 1
    sync_payload = json.loads(syncs[0]["payload_json"])
    assert sync_payload["source"] == "REGISTRATION"
    assert sync_payload["flow"] == "RECRUITMENT_APPROVAL"
    assert sync_payload["origin_application_id"] == application["id"]
    assert registration["status"] == "REGISTERED"
    assert registration["access_tier"] == "RECRUIT"
    assert registration["sync_status"] == "PENDING"
    assert onboarding["registration_status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_candidate_cannot_review_own_application(recruitment_bundle) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await _start(service)
    await database.execute(
        "UPDATE recruitment_applications SET status='SUBMITTED', version=2 WHERE id=?",
        (application["id"],),
    )
    with pytest.raises(PermissionDenied, match="própria candidatura"):
        await service.assign(GUILD_ID, int(application["id"]), CANDIDATE_ID, 2)


@pytest.mark.asyncio
async def test_rejection_creates_cooldown_and_blocks_reapplication(recruitment_bundle) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await _start(service)
    await database.execute(
        "UPDATE recruitment_applications SET status='UNDER_REVIEW' WHERE id=?",
        (application["id"],),
    )
    rejected = await service.decide(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        1,
        approved=False,
        internal_reason="Requisitos insuficientes",
        candidate_message="Revise os requisitos antes de tentar novamente.",
    )
    assert rejected["status"] == "REJECTED"
    eligibility = await service.eligibility(GUILD_ID, CANDIDATE_ID)
    assert "COOLDOWN_ACTIVE" in eligibility["reasons"]


@pytest.mark.asyncio
async def test_form_publication_keeps_existing_application_snapshot_immutable(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await _start(service)
    assigned = await database.fetchone(
        """
        SELECT * FROM recruitment_application_questions
        WHERE application_id=? ORDER BY ordinal LIMIT 1
        """,
        (application["id"],),
    )
    before = assigned["question_snapshot_json"]
    source = await database.fetchone(
        "SELECT * FROM recruitment_questions WHERE id=?", (assigned["question_id"],)
    )
    values = dict(source)
    values.update(
        title="Texto administrativo alterado",
        options=json.loads(source["options_json"]),
    )
    await service.update_question(
        GUILD_ID, int(source["id"]), ADMIN_ID, values
    )
    await service.publish_form(GUILD_ID, ADMIN_ID)
    after = await database.fetchone(
        "SELECT question_snapshot_json FROM recruitment_application_questions WHERE id=?",
        (assigned["id"],),
    )
    assert after["question_snapshot_json"] == before


@pytest.mark.asyncio
async def test_group_distribution_is_versioned_and_new_form_changes_only_new_applications(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    first = await _start(service)
    roleplay = await database.fetchone(
        "SELECT * FROM recruitment_question_groups WHERE guild_id=? AND code='ROLEPLAY'",
        (GUILD_ID,),
    )
    await service.update_group(
        GUILD_ID,
        int(roleplay["id"]),
        ADMIN_ID,
        {
            "name": roleplay["name"],
            "position": roleplay["position"],
            "questions_per_application": 1,
            "active": True,
        },
    )
    await service.publish_form(GUILD_ID, ADMIN_ID)
    second = await _start(
        service,
        CANDIDATE_ID + 1,
        bgr_id="1843",
        key="application-versioned-group-key",
    )
    first_total = await database.fetchone(
        "SELECT COUNT(*) AS total FROM recruitment_application_questions WHERE application_id=?",
        (first["id"],),
    )
    second_total = await database.fetchone(
        "SELECT COUNT(*) AS total FROM recruitment_application_questions WHERE application_id=?",
        (second["id"],),
    )
    assert int(first_total["total"]) == 10
    assert int(second_total["total"]) == 9


@pytest.mark.asyncio
async def test_withdraw_block_revoke_and_accessibility_adaptation_are_audited(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await _start(service)
    first_question = await database.fetchone(
        """
        SELECT * FROM recruitment_application_questions
        WHERE application_id=? ORDER BY ordinal LIMIT 1
        """,
        (application["id"],),
    )
    snapshot = json.loads(first_question["question_snapshot_json"])
    snapshot.update(timer_enabled=1, expected_max_length=100, security_level="CONTROLLED")
    await database.execute(
        "UPDATE recruitment_application_questions SET question_snapshot_json=? WHERE id=?",
        (json.dumps(snapshot), first_question["id"]),
    )
    adaptation_id = await service.add_adaptation(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        extra_time_percent=25,
        clipboard_adapted=True,
        alternative_format="Compatível com leitor de tela",
        reason="Necessidade de tecnologia assistiva validada",
    )
    ready = await service.next_question(GUILD_ID, CANDIDATE_ID, int(application["id"]))
    started = await service.start_question(
        GUILD_ID, CANDIDATE_ID, int(application["id"]), int(ready["id"])
    )
    assert adaptation_id > 0
    assert ready["time_seconds"] > 0
    assert started["question"]["clipboard_adapted"] is True
    assert started["question"]["alternative_format"] == "Compatível com leitor de tela"

    withdrawn = await service.withdraw_application(
        GUILD_ID, CANDIDATE_ID, int(application["id"]), 1
    )
    assert withdrawn["status"] == "WITHDRAWN"
    block_id = await service.block_candidate(
        GUILD_ID,
        ADMIN_ID,
        discord_id=CANDIDATE_ID,
        bgr_id=None,
        reason="Impedimento administrativo de validação",
    )
    assert "ADMINISTRATIVE_BLOCK" in (
        await service.eligibility(GUILD_ID, CANDIDATE_ID)
    )["reasons"]
    assert (await service.list_blocks(GUILD_ID, active_only=True))[0]["id"] == block_id
    await service.revoke_block(GUILD_ID, block_id, ADMIN_ID)
    assert await service.list_blocks(GUILD_ID, active_only=True) == []
    audits = await database.fetchall(
        """
        SELECT action FROM audit_logs WHERE guild_id=? AND action IN (
          'RECRUITMENT_ADAPTATION_CREATED',
          'RECRUITMENT_APPLICATION_WITHDRAWN',
          'RECRUITMENT_CANDIDATE_BLOCKED',
          'RECRUITMENT_CANDIDATE_BLOCK_REVOKED'
        )
        """,
        (GUILD_ID,),
    )
    assert {row["action"] for row in audits} == {
        "RECRUITMENT_ADAPTATION_CREATED",
        "RECRUITMENT_APPLICATION_WITHDRAWN",
        "RECRUITMENT_CANDIDATE_BLOCKED",
        "RECRUITMENT_CANDIDATE_BLOCK_REVOKED",
    }


@pytest.mark.asyncio
async def test_similar_response_creates_review_evidence_without_auto_decision(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    first = await _start(service)
    second = await _start(
        service,
        CANDIDATE_ID + 1,
        bgr_id="1888",
        key="similar-response-second-candidate",
    )
    shared = (
        "Durante uma ocorrência eu manteria a disciplina, comunicaria a equipe e "
        "registraria os fatos seguindo o procedimento oficial antes de qualquer decisão. "
    )
    for application in (first, second):
        await database.execute(
            """
            UPDATE recruitment_application_questions
            SET status='SUBMITTED', final_answer_json='"ok"', submitted_at=?
            WHERE application_id=?
            """,
            (recruitment_bundle["clock"](), application["id"]),
        )
    common = await database.fetchone(
        """
        SELECT first.id AS first_id, second.id AS second_id
        FROM recruitment_application_questions first
        JOIN recruitment_application_questions second
          ON second.question_id=first.question_id
        WHERE first.application_id=? AND second.application_id=?
          AND json_extract(first.question_snapshot_json, '$.question_type')='LONG_TEXT'
        ORDER BY first.ordinal LIMIT 1
        """,
        (first["id"], second["id"]),
    )
    for question_id in (common["first_id"], common["second_id"]):
        await database.execute(
            "UPDATE recruitment_application_questions SET final_answer_json=? WHERE id=?",
            (json.dumps(shared), question_id),
        )
    await service.submit_application(GUILD_ID, CANDIDATE_ID, int(first["id"]), 1)
    submitted = await service.submit_application(
        GUILD_ID, CANDIDATE_ID + 1, int(second["id"]), 1
    )
    signal = await database.fetchone(
        """
        SELECT * FROM recruitment_integrity_events
        WHERE application_id=? AND event_type='POSSIBLE_SIMILAR_RESPONSE'
        """,
        (second["id"],),
    )
    assert submitted["status"] == "SUBMITTED"
    assert signal is not None
    assert json.loads(signal["metadata_json"])["similarity_percent"] >= 92


@pytest.mark.asyncio
async def test_legacy_candidacy_ticket_is_imported_once_without_losing_source(tmp_path) -> None:
    database = Database(tmp_path / "legacy-recruitment.db")
    await database.open()
    try:
        clock = MutableClock()
        await database.execute(
            """
            INSERT INTO service_tickets(
                guild_id, discord_id, ticket_type, status, payload_json,
                submitted_at, updated_at
            ) VALUES (?, ?, 'CANDIDACY', 'PENDING', ?, ?, ?)
            """,
            (
                GUILD_ID,
                CANDIDATE_ID,
                json.dumps({"mta_nick": "Legado_Test", "motivation": "Histórico"}),
                clock(),
                clock(),
            ),
        )
        audit = AuditService(database, None, Branding())
        service = RecruitmentService(
            database,
            audit,
            token_secret="legacy-recruitment-secret-with-entropy",
            clock=clock,
        )
        first = await service.ensure_defaults(GUILD_ID, ADMIN_ID)
        second = await service.ensure_defaults(GUILD_ID, ADMIN_ID)
        imported = await database.fetchone(
            "SELECT * FROM recruitment_applications WHERE legacy_ticket_id=1"
        )
        source = await database.fetchone("SELECT * FROM service_tickets WHERE id=1")
        assert first["legacy_applications_imported"] == 1
        assert second["legacy_applications_imported"] == 0
        assert imported["status"] == "SUBMITTED"
        assert imported["legacy_incomplete"] == 1
        assert imported["protocol"] == "LEG-00001"
        assert source["status"] == "PENDING"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_recruitment_notification_outbox_retries_without_new_event(
    recruitment_bundle, monkeypatch
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await _start(service)
    await database.execute(
        """
        UPDATE recruitment_application_questions
        SET status='SUBMITTED', final_answer_json='"ok"', submitted_at=?
        WHERE application_id=?
        """,
        (recruitment_bundle["clock"](), application["id"]),
    )
    await service.submit_application(GUILD_ID, CANDIDATE_ID, int(application["id"]), 1)
    worker = WebActionWorker(database, None, recruitment_bundle["audit"], object())  # type: ignore[arg-type]
    calls = 0

    async def dispatch_failure(_row):
        nonlocal calls
        calls += 1
        raise RuntimeError("temporary Discord failure")

    monkeypatch.setattr(worker, "_dispatch_recruitment", dispatch_failure)
    assert await worker.process_recruitment_pending() == 0
    failed = await database.fetchone("SELECT * FROM recruitment_notification_outbox")
    assert failed["status"] == "FAILED"
    assert failed["attempts"] == 1
    await database.execute(
        "UPDATE recruitment_notification_outbox SET available_at=?",
        (recruitment_bundle["clock"](),),
    )

    async def dispatch_success(_row):
        nonlocal calls
        calls += 1
        return 77, 88

    monkeypatch.setattr(worker, "_dispatch_recruitment", dispatch_success)
    assert await worker.process_recruitment_pending() == 2
    completed = await database.fetchone(
        """
        SELECT * FROM recruitment_notification_outbox
        WHERE event_type='RECRUITMENT_APPLICATION_SUBMITTED'
        """
    )
    total = await database.fetchone(
        "SELECT COUNT(*) AS total FROM recruitment_notification_outbox"
    )
    assert completed["status"] == "COMPLETED"
    assert completed["attempts"] == 2
    assert (completed["delivery_channel_id"], completed["delivery_message_id"]) == (77, 88)
    assert int(total["total"]) == 2
    assert calls == 4


@pytest.mark.asyncio
async def test_recruitment_notification_embed_uses_central_branding(
    recruitment_bundle,
) -> None:
    worker = WebActionWorker(
        recruitment_bundle["database"],
        None,
        recruitment_bundle["audit"],
        object(),  # type: ignore[arg-type]
    )
    embed = worker._recruitment_embed(
        "Nova candidatura recebida",
        {
            "protocol": "AL-00001",
            "candidate_nick": "Candidato QA",
            "bgr_id": "QA-001",
        },
        "Conteúdo disponível no Centro de Comando.",
    )

    assert embed.footer.text == Branding().footer


@pytest.mark.asyncio
async def test_public_recruitment_embed_exposes_only_protocol_and_status(
    recruitment_bundle,
) -> None:
    worker = WebActionWorker(
        recruitment_bundle["database"],
        None,
        recruitment_bundle["audit"],
        object(),  # type: ignore[arg-type]
    )
    embed = worker._recruitment_public_embed(
        {
            "id": 7,
            "protocol": "AL-00007",
            "status": "UNDER_REVIEW",
            "candidate_nick": "NÃO DEVE APARECER",
            "discord_username": "privado",
            "bgr_id": "123456",
        },
        72,
    )

    rendered = str(embed.to_dict())
    assert "AL-00007" in rendered
    assert "Em análise" in rendered
    assert "NÃO DEVE APARECER" not in rendered
    assert "privado" not in rendered
    assert "123456" not in rendered


@pytest.mark.asyncio
async def test_stale_recruitment_notification_is_enqueued_once(recruitment_bundle) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    clock = recruitment_bundle["clock"]
    application = await _start(service)
    await database.execute(
        """
        UPDATE recruitment_applications
        SET status='SUBMITTED', submitted_at=? WHERE id=?
        """,
        (clock() - 25 * 3_600_000, application["id"]),
    )
    worker = WebActionWorker(database, None, recruitment_bundle["audit"], object())  # type: ignore[arg-type]
    first = await worker._enqueue_stale_recruitment(clock())
    second = await worker._enqueue_stale_recruitment(clock())
    events = await database.fetchone(
        """
        SELECT COUNT(*) AS total FROM recruitment_notification_outbox
        WHERE application_id=? AND event_type='RECRUITMENT_APPLICATION_STALE'
        """,
        (application["id"],),
    )
    assert first == 1
    assert second == 0
    assert int(events["total"]) == 1
