from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import discord
import pytest
import pytest_asyncio

import choque.web_outbox as web_outbox_module
from choque.audit import AuditService
from choque.config import Branding
from choque.database import Database
from choque.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from choque.recruitment import DEFAULT_QUESTIONS, GROUPS, RecruitmentService
from choque.registration_gate import RegistrationGateService
from choque.settings import SettingsService
from choque.web_outbox import (
    WebActionWorker,
    build_recruitment_review_embed,
    build_recruitment_review_view,
)
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
    assert int(campaign["minimum_age"]) == 15
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


@pytest.mark.asyncio
async def test_migration_27_aligns_existing_campaign_age_and_audits_with_later_version_present(tmp_path) -> None:
    path = tmp_path / "recruitment-v26.db"
    database = Database(path)
    await database.open()
    audit = AuditService(database, None, Branding())
    service = RecruitmentService(
        database,
        audit,
        token_secret="recruitment-test-secret-with-strong-entropy",
    )
    await service.ensure_defaults(GUILD_ID, ADMIN_ID)
    campaign = await service.current_campaign(GUILD_ID)
    assert campaign
    await database.execute(
        "UPDATE recruitment_campaigns SET minimum_age=16 WHERE id=?",
        (int(campaign["id"]),),
    )
    await database.execute("DELETE FROM schema_migrations WHERE version=27")
    later = await database.fetchone("SELECT 1 FROM schema_migrations WHERE version=28")
    assert later is not None
    await database.close()

    migrated = Database(path)
    await migrated.open()
    try:
        updated = await migrated.fetchone(
            "SELECT minimum_age FROM recruitment_campaigns WHERE id=?",
            (int(campaign["id"]),),
        )
        event = await migrated.fetchone(
            """
            SELECT action, before_json, after_json FROM audit_logs
            WHERE correlation_id=?
            """,
            (f"migration-27-recruitment-minimum-age-{int(campaign['id'])}",),
        )
        assert int(updated["minimum_age"]) == 15
        assert event["action"] == "RECRUITMENT_MINIMUM_AGE_ALIGNED"
        assert json.loads(event["before_json"])["minimum_age"] == 16
        assert json.loads(event["after_json"])["minimum_age"] == 15
    finally:
        await migrated.close()


@pytest.mark.asyncio
async def test_direct_indication_skips_form_reuses_approval_and_blocks_duplicate(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await service.submit_direct_indication(
        GUILD_ID,
        CANDIDATE_ID,
        discord_username="candidate",
        candidate_nick="Candidato_Indicado",
        bgr_id="7788",
        indicated_by=2002,
        requested_unit_code="ROCAM",
        notes="Indicação registrada pelo responsável.",
    )
    assert application["status"] == "UNDER_REVIEW"
    assert application["entry_method"] == "INDICATION"
    assert application["protocol"].startswith("IND-")
    questions = await database.fetchone(
        "SELECT COUNT(*) AS total FROM recruitment_application_questions WHERE application_id=?",
        (application["id"],),
    )
    assert questions["total"] == 0

    with pytest.raises(ConflictError, match="já possui uma solicitação"):
        await service.submit_direct_indication(
            GUILD_ID,
            CANDIDATE_ID,
            discord_username="candidate",
            candidate_nick="Candidato_Indicado",
            bgr_id="7788",
            indicated_by=2002,
        )

    decided = await service.decide(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        int(application["version"]),
        approved=True,
        internal_reason="Indicação validada pelo Comando.",
        candidate_message="Entrada aprovada por indicação.",
        origin="DISCORD",
    )
    assert decided["status"] == "APPROVED"
    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, CANDIDATE_ID),
    )
    assert member is not None
    assert member["mta_nick"] == "Candidato_Indicado"
    registration = await database.fetchone(
        "SELECT * FROM registration_gate_records WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, CANDIDATE_ID),
    )
    assert registration["status"] == "REGISTERED"
    audit = await database.fetchone(
        """
        SELECT after_json FROM audit_logs
        WHERE guild_id=? AND action='RECRUITMENT_DIRECT_INDICATION_SUBMITTED'
        """,
        (GUILD_ID,),
    )
    assert json.loads(audit["after_json"])["entry_method"] == "INDICATION"
    decision_audit = await database.fetchone(
        """
        SELECT after_json FROM audit_logs
        WHERE guild_id=? AND action='RECRUITMENT_APPLICATION_APPROVED'
        """,
        (GUILD_ID,),
    )
    decision_after = json.loads(decision_audit["after_json"])
    assert decision_after["entry_method"] == "INDICATION"
    assert decision_after["indicated_by"] == 2002
    assert decision_after["requested_unit_code"] == "ROCAM"


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
async def test_approval_blocks_existing_bgr_identity_without_partial_decision(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    clock = recruitment_bundle["clock"]
    rank_id = recruitment_bundle["rank_id"]
    await database.execute(
        """
        INSERT INTO members(
            guild_id, discord_id, discord_nick, mta_nick, character_id, rank_id,
            unit, status, joined_at, created_at, updated_at
        ) VALUES (?, ?, 'owner', 'Existing_Owner', '1842', ?, 'BGR', 'ACTIVE', ?, ?, ?)
        """,
        (GUILD_ID, CANDIDATE_ID + 99, rank_id, clock(), clock(), clock()),
    )
    application = await _start(service)
    await database.execute(
        """
        UPDATE recruitment_application_questions
        SET status='SUBMITTED', final_answer_json='"Resposta de teste"', submitted_at=?
        WHERE application_id=?
        """,
        (clock(), application["id"]),
    )
    await service.submit_application(GUILD_ID, CANDIDATE_ID, int(application["id"]), 1)
    assigned = await service.assign(GUILD_ID, int(application["id"]), ADMIN_ID, 2)

    with pytest.raises(ConflictError, match="ID in-game informado já está vinculado"):
        await service.decide(
            GUILD_ID,
            int(application["id"]),
            ADMIN_ID,
            int(assigned["version"]),
            approved=True,
            internal_reason="Requisitos conferidos",
            candidate_message="Aprovado.",
        )

    current = await database.fetchone(
        "SELECT status, stage, version, decided_at, decided_by FROM recruitment_applications WHERE id=?",
        (application["id"],),
    )
    created_member = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, CANDIDATE_ID),
    )
    assert dict(current) == {
        "status": "UNDER_REVIEW",
        "stage": "REVIEW",
        "version": int(assigned["version"]),
        "decided_at": None,
        "decided_by": None,
    }
    assert created_member is None


@pytest.mark.asyncio
async def test_approval_does_not_replace_existing_bgr_for_same_discord(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    clock = recruitment_bundle["clock"]
    rank_id = recruitment_bundle["rank_id"]
    application = await _start(service)
    await database.execute(
        """
        INSERT INTO members(
            guild_id, discord_id, discord_nick, mta_nick, character_id, rank_id,
            unit, status, joined_at, created_at, updated_at
        ) VALUES (?, ?, 'candidate', 'Existing_Identity', '9999', ?, 'BGR', 'ACTIVE', ?, ?, ?)
        """,
        (GUILD_ID, CANDIDATE_ID, rank_id, clock(), clock(), clock()),
    )
    await database.execute(
        """
        UPDATE recruitment_application_questions
        SET status='SUBMITTED', final_answer_json='"Resposta de teste"', submitted_at=?
        WHERE application_id=?
        """,
        (clock(), application["id"]),
    )
    await service.submit_application(GUILD_ID, CANDIDATE_ID, int(application["id"]), 1)
    assigned = await service.assign(GUILD_ID, int(application["id"]), ADMIN_ID, 2)

    with pytest.raises(ConflictError, match="Discord já está vinculado a outro ID in-game"):
        await service.decide(
            GUILD_ID,
            int(application["id"]),
            ADMIN_ID,
            int(assigned["version"]),
            approved=True,
            internal_reason="Requisitos conferidos",
            candidate_message="Aprovado.",
        )

    member = await database.fetchone(
        "SELECT character_id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, CANDIDATE_ID),
    )
    current = await database.fetchone(
        "SELECT status, version, decided_at FROM recruitment_applications WHERE id=?",
        (application["id"],),
    )
    assert member["character_id"] == "9999"
    assert dict(current) == {
        "status": "UNDER_REVIEW",
        "version": int(assigned["version"]),
        "decided_at": None,
    }


@pytest.mark.asyncio
async def test_assignment_is_idempotent_for_owner_and_blocks_takeover(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await _start(service)
    await database.execute(
        "UPDATE recruitment_applications SET status='UNDER_REVIEW', version=2 WHERE id=?",
        (application["id"],),
    )
    assigned = await service.assign(GUILD_ID, int(application["id"]), ADMIN_ID, 2)

    repeated = await service.assign(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        int(assigned["version"]),
    )
    with pytest.raises(ConflictError, match="já está atribuída a outro responsável"):
        await service.assign(
            GUILD_ID,
            int(application["id"]),
            ADMIN_ID + 1,
            int(assigned["version"]),
        )

    current = await database.fetchone(
        "SELECT assigned_to, version FROM recruitment_applications WHERE id=?",
        (application["id"],),
    )
    assert repeated["assigned_to"] == ADMIN_ID
    assert int(current["assigned_to"]) == ADMIN_ID
    assert int(current["version"]) == int(assigned["version"])


@pytest.mark.asyncio
async def test_rec_approval_imports_registration_into_canonical_guild(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    settings = SettingsService(database)
    service.audit.settings = settings
    canonical_guild_id = GUILD_ID + 1
    canonical_rank_id = await database.execute(
        """
        INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
        VALUES (?, 'Recruta', 'REC', 1, 'MEMBRO', ?)
        """,
        (canonical_guild_id, recruitment_bundle["clock"]()),
    )
    await settings.set(GUILD_ID, "identity_source_guild_id", canonical_guild_id, ADMIN_ID)

    application = await _start(service)
    await database.execute(
        """
        UPDATE recruitment_application_questions
        SET status='SUBMITTED', final_answer_json='"Resposta de teste"', submitted_at=?
        WHERE application_id=?
        """,
        (recruitment_bundle["clock"](), application["id"]),
    )
    await service.submit_application(GUILD_ID, CANDIDATE_ID, int(application["id"]), 1)
    assigned = await service.assign(GUILD_ID, int(application["id"]), ADMIN_ID, 2)
    await service.decide(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        int(assigned["version"]),
        approved=True,
        internal_reason="Requisitos conferidos",
        candidate_message="Aprovado.",
    )

    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
        (canonical_guild_id, CANDIDATE_ID),
    )
    registration = await database.fetchone(
        "SELECT * FROM registration_gate_records WHERE guild_id=? AND discord_id=?",
        (canonical_guild_id, CANDIDATE_ID),
    )
    syncs = await database.fetchall(
        """
        SELECT guild_id, correlation_id FROM web_action_outbox
        WHERE target_discord_id=? ORDER BY guild_id
        """,
        (CANDIDATE_ID,),
    )
    assert int(member["rank_id"]) == canonical_rank_id
    assert member["mta_nick"] == f"Candidato_{CANDIDATE_ID}"
    assert member["character_id"] == "1842"
    assert member["status"] == "ACTIVE"
    assert registration["status"] == "REGISTERED"
    assert registration["access_tier"] == "RECRUIT"
    assert int(registration["member_id"]) == int(member["id"])
    assert registration["source"] == "ADMIN_APPROVAL"
    assert [int(row["guild_id"]) for row in syncs] == [GUILD_ID, canonical_guild_id]
    assert str(syncs[1]["correlation_id"]) == (
        f"rec-source-member-sync:{GUILD_ID}:{int(application['id'])}"
    )


@pytest.mark.asyncio
async def test_member_join_backfill_imports_previously_approved_rec_identity(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    settings = SettingsService(database)
    service.audit.settings = settings
    canonical_guild_id = GUILD_ID + 1
    await database.execute(
        """
        INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
        VALUES (?, 'Recruta', 'REC', 1, 'MEMBRO', ?)
        """,
        (canonical_guild_id, recruitment_bundle["clock"]()),
    )

    application = await _start(service)
    await database.execute(
        """
        UPDATE recruitment_application_questions
        SET status='SUBMITTED', final_answer_json='"Resposta de teste"', submitted_at=?
        WHERE application_id=?
        """,
        (recruitment_bundle["clock"](), application["id"]),
    )
    await service.submit_application(GUILD_ID, CANDIDATE_ID, int(application["id"]), 1)
    assigned = await service.assign(GUILD_ID, int(application["id"]), ADMIN_ID, 2)
    await service.decide(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        int(assigned["version"]),
        approved=True,
        internal_reason="Requisitos conferidos",
        candidate_message="Aprovado.",
    )
    now = recruitment_bundle["clock"]()
    await database.execute(
        """
        INSERT INTO registration_gate_records(
            guild_id, discord_id, status, access_tier, source, sync_status,
            created_at, updated_at
        ) VALUES (?, ?, 'UNREGISTERED', 'CANDIDATE', 'REJOIN', 'SYNCED', ?, ?)
        """,
        (canonical_guild_id, CANDIDATE_ID, now, now),
    )
    await settings.set(GUILD_ID, "identity_source_guild_id", canonical_guild_id, ADMIN_ID)

    imported = await service.import_approved_identity_to_source(
        canonical_guild_id,
        CANDIDATE_ID,
        actor_id=ADMIN_ID,
    )
    repeated = await service.import_approved_identity_to_source(
        canonical_guild_id,
        CANDIDATE_ID,
        actor_id=ADMIN_ID,
    )

    assert imported is not None
    assert repeated is not None
    assert int(imported["guild_id"]) == canonical_guild_id
    totals = await database.fetchone(
        """
        SELECT
          (SELECT COUNT(*) FROM members WHERE guild_id=? AND discord_id=?) AS members,
          (SELECT COUNT(*) FROM registration_gate_records
           WHERE guild_id=? AND discord_id=?) AS registrations,
          (SELECT COUNT(*) FROM web_action_outbox
           WHERE correlation_id=?) AS syncs
        """,
        (
            canonical_guild_id,
            CANDIDATE_ID,
            canonical_guild_id,
            CANDIDATE_ID,
            f"rec-source-member-sync:{GUILD_ID}:{int(application['id'])}",
        ),
    )
    assert dict(totals) == {"members": 1, "registrations": 1, "syncs": 1}


@pytest.mark.asyncio
async def test_rec_import_routes_existing_bgr_owner_to_review_without_overwrite(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    settings = SettingsService(database)
    service.audit.settings = settings
    canonical_guild_id = GUILD_ID + 1
    canonical_rank_id = await database.execute(
        """
        INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
        VALUES (?, 'Recruta', 'REC', 1, 'MEMBRO', ?)
        """,
        (canonical_guild_id, recruitment_bundle["clock"]()),
    )
    await database.execute(
        """
        INSERT INTO members(
            guild_id, discord_id, discord_nick, mta_nick, character_id, rank_id,
            unit, status, joined_at, created_at, updated_at
        ) VALUES (?, ?, 'owner', 'Dono_ID', '1842', ?, 'BGR', 'ACTIVE', ?, ?, ?)
        """,
        (
            canonical_guild_id,
            CANDIDATE_ID + 99,
            canonical_rank_id,
            recruitment_bundle["clock"](),
            recruitment_bundle["clock"](),
            recruitment_bundle["clock"](),
        ),
    )
    await settings.set(GUILD_ID, "identity_source_guild_id", canonical_guild_id, ADMIN_ID)

    application = await _start(service)
    await database.execute(
        """
        UPDATE recruitment_application_questions
        SET status='SUBMITTED', final_answer_json='"Resposta de teste"', submitted_at=?
        WHERE application_id=?
        """,
        (recruitment_bundle["clock"](), application["id"]),
    )
    await service.submit_application(GUILD_ID, CANDIDATE_ID, int(application["id"]), 1)
    assigned = await service.assign(GUILD_ID, int(application["id"]), ADMIN_ID, 2)
    await service.decide(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        int(assigned["version"]),
        approved=True,
        internal_reason="Requisitos conferidos",
        candidate_message="Aprovado.",
    )

    imported_member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
        (canonical_guild_id, CANDIDATE_ID),
    )
    registration = await database.fetchone(
        "SELECT * FROM registration_gate_records WHERE guild_id=? AND discord_id=?",
        (canonical_guild_id, CANDIDATE_ID),
    )
    assert imported_member is None
    assert registration["status"] == "REQUIRES_REVIEW"
    assert registration["conflict_code"] == "CROSS_GUILD_IDENTITY_CONFLICT"


@pytest.mark.asyncio
async def test_approved_recruit_can_start_one_portaria_registration_without_duplicate_member(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await _start(service)
    await database.execute(
        """
        UPDATE recruitment_application_questions
        SET status='SUBMITTED', final_answer_json='\"Resposta de teste\"', submitted_at=?
        WHERE application_id=?
        """,
        (recruitment_bundle["clock"](), application["id"]),
    )
    await service.submit_application(GUILD_ID, CANDIDATE_ID, int(application["id"]), 1)
    assigned = await service.assign(GUILD_ID, int(application["id"]), ADMIN_ID, 2)
    await service.decide(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        int(assigned["version"]),
        approved=True,
        internal_reason="Aprovado para a identificação da Portaria",
        candidate_message="Candidatura aprovada.",
    )

    settings = SettingsService(database)
    await settings.set(GUILD_ID, "registration_gate_enabled", True, ADMIN_ID)
    gate = RegistrationGateService(database, settings, recruitment_bundle["audit"])

    intent = await gate.registration_intent(GUILD_ID, CANDIDATE_ID)
    assert (intent["mode"], intent["kind"]) == ("FORM", "APPROVED_RECRUITMENT")

    submitted = await gate.submit(
        GUILD_ID,
        CANDIDATE_ID,
        mta_nick=f"Candidato_{CANDIDATE_ID}",
        bgr_id="1842",
    )
    assert submitted["status"] == "REQUIRES_REVIEW"
    assert submitted["member_id"] is not None

    repeated_intent = await gate.registration_intent(GUILD_ID, CANDIDATE_ID)
    assert (repeated_intent["mode"], repeated_intent["kind"]) == (
        "STATUS",
        "REQUIRES_REVIEW",
    )
    count = await database.fetchone(
        "SELECT COUNT(*) AS total FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, CANDIDATE_ID),
    )
    assert int(count["total"]) == 1


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
async def test_discord_decision_preserves_origin_correlation_and_one_review_card_refresh(
    recruitment_bundle,
) -> None:
    """Discord and web share the same decision service and durable state transition."""
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await _start(service)
    await database.execute(
        "UPDATE recruitment_applications SET status='UNDER_REVIEW' WHERE id=?",
        (application["id"],),
    )

    decided = await service.decide(
        GUILD_ID,
        int(application["id"]),
        ADMIN_ID,
        int(application["version"]),
        approved=False,
        internal_reason="Conhecimento operacional ainda insuficiente.",
        candidate_message="Revise os requisitos e tente novamente no próximo período.",
        origin="DISCORD",
        correlation_id="discord-decision-test",
    )
    assert decided["status"] == "REJECTED"
    history = await database.fetchone(
        """
        SELECT metadata_json FROM recruitment_history
        WHERE application_id=? AND event_type='APPLICATION_REJECTED'
        ORDER BY id DESC LIMIT 1
        """,
        (application["id"],),
    )
    assert json.loads(history["metadata_json"]) == {
        "origin": "DISCORD",
        "correlation_id": "discord-decision-test",
    }
    audit = await database.fetchone(
        "SELECT correlation_id, after_json FROM audit_logs WHERE correlation_id=?",
        ("discord-decision-test",),
    )
    assert audit["correlation_id"] == "discord-decision-test"
    assert json.loads(audit["after_json"])["origin"] == "DISCORD"
    refreshes = await database.fetchall(
        """
        SELECT event_key FROM recruitment_notification_outbox
        WHERE application_id=? AND event_type='RECRUITMENT_REVIEW_CARD_REFRESH'
        """,
        (application["id"],),
    )
    assert [row["event_key"] for row in refreshes] == [
        f"application-review-card:{application['id']}:v2"
    ]


@pytest.mark.asyncio
async def test_repeated_same_discord_decision_is_idempotent_and_opposite_is_rejected(
    recruitment_bundle,
) -> None:
    service = recruitment_bundle["service"]
    database = recruitment_bundle["database"]
    application = await _start(service)
    await database.execute(
        "UPDATE recruitment_applications SET status='UNDER_REVIEW' WHERE id=?",
        (application["id"],),
    )
    args = dict(
        approved=False,
        internal_reason="Avaliação insuficiente.",
        candidate_message="Revise o conteúdo e tente novamente.",
        origin="DISCORD",
    )
    first, repeated = await asyncio.gather(
        service.decide(GUILD_ID, int(application["id"]), ADMIN_ID, 1, **args),
        service.decide(GUILD_ID, int(application["id"]), ADMIN_ID, 1, **args),
    )
    assert first["status"] == repeated["status"] == "REJECTED"
    cooldowns = await database.fetchone(
        "SELECT COUNT(*) AS total FROM recruitment_cooldowns WHERE application_id=?",
        (application["id"],),
    )
    assert int(cooldowns["total"]) == 1
    with pytest.raises(ConflictError, match="decisão final diferente"):
        await service.decide(
            GUILD_ID,
            int(application["id"]),
            ADMIN_ID,
            int(repeated["version"]),
            approved=True,
            internal_reason="Tentativa de decisão incompatível.",
            candidate_message="Não deve ser enviada.",
            origin="DISCORD",
        )


@pytest.mark.asyncio
async def test_review_card_refresh_edits_the_original_message_without_sending_another(
    recruitment_bundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Settings:
        async def get(self, guild_id: int, key: str, default=None):
            assert guild_id == GUILD_ID
            return "https://portal.example/recrutamento" if key == "recruitment_public_url" else default

    class Message:
        id = 82

        def __init__(self) -> None:
            self.edits: list[dict[str, object]] = []

        async def edit(self, **kwargs) -> None:
            self.edits.append(kwargs)

    class Channel:
        id = 81

        def __init__(self, message: Message) -> None:
            self.message = message

        async def fetch_message(self, message_id: int) -> Message:
            assert message_id == self.message.id
            return self.message

    class Bot:
        def __init__(self, channel: Channel) -> None:
            self.channel = channel
            self.config = SimpleNamespace(branding=Branding())

        def get_channel(self, channel_id: int):
            return self.channel if channel_id == self.channel.id else None

    application = await _start(recruitment_bundle["service"])
    await recruitment_bundle["database"].execute(
        """
        INSERT INTO recruitment_notification_outbox(
            guild_id, application_id, event_type, event_key, payload_json, status,
            available_at, created_at, processed_at, delivery_channel_id, delivery_message_id
        ) VALUES (?, ?, 'RECRUITMENT_APPLICATION_SUBMITTED', ?, '{}', 'COMPLETED', ?, ?, ?, ?, ?)
        """,
        (
            GUILD_ID,
            application["id"],
            f"application-submitted:{application['id']}",
            recruitment_bundle["clock"](),
            recruitment_bundle["clock"](),
            recruitment_bundle["clock"](),
            81,
            82,
        ),
    )
    message = Message()
    channel = Channel(message)
    monkeypatch.setattr(web_outbox_module.discord, "TextChannel", Channel)
    worker = WebActionWorker(
        recruitment_bundle["database"],
        None,
        SimpleNamespace(settings=Settings()),
        Bot(channel),
    )
    delivery = await worker._refresh_recruitment_review_card(
        {"guild_id": GUILD_ID},
        {**application, "status": "UNDER_REVIEW", "assigned_to": ADMIN_ID},
    )
    assert delivery == (81, 82)
    assert len(message.edits) == 1
    assert message.edits[0]["view"] is not None
    assert "EM ANÁLISE" in message.edits[0]["embed"].title


@pytest.mark.asyncio
async def test_review_card_refresh_without_original_card_finishes_without_duplication(
    recruitment_bundle,
) -> None:
    """A legacy follow-up must not recreate a deleted or never-published card."""
    application = await _start(recruitment_bundle["service"])
    worker = WebActionWorker(
        recruitment_bundle["database"],
        None,
        SimpleNamespace(settings=None),
        None,
    )

    delivery = await worker._refresh_recruitment_review_card(
        {"id": 999, "guild_id": GUILD_ID},
        application,
    )

    assert delivery == (None, None)
    rows = await recruitment_bundle["database"].fetchall(
        "SELECT * FROM recruitment_notification_outbox WHERE application_id=?",
        (application["id"],),
    )
    assert rows == []


@pytest.mark.asyncio
async def test_review_card_refresh_dispatch_converts_database_row_to_mapping(
    recruitment_bundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Durable outbox rows must use the same renderer as direct Discord decisions."""
    class Settings:
        async def get(self, guild_id: int, key: str, default=None):
            assert guild_id == GUILD_ID
            return "https://portal.example/recrutamento" if key == "recruitment_public_url" else default

    class Message:
        id = 82

        def __init__(self) -> None:
            self.edits: list[dict[str, object]] = []

        async def edit(self, **kwargs) -> None:
            self.edits.append(kwargs)

    class Channel:
        id = 81

        def __init__(self, message: Message) -> None:
            self.message = message

        async def fetch_message(self, message_id: int) -> Message:
            assert message_id == self.message.id
            return self.message

    class Bot:
        def __init__(self, channel: Channel) -> None:
            self.channel = channel
            self.config = SimpleNamespace(branding=Branding())

        def get_channel(self, channel_id: int):
            return self.channel if channel_id == self.channel.id else None

        def get_guild(self, guild_id: int):
            return object() if guild_id == GUILD_ID else None

    database = recruitment_bundle["database"]
    clock = recruitment_bundle["clock"]
    application = await _start(recruitment_bundle["service"])
    await database.execute(
        "UPDATE recruitment_applications SET status='UNDER_REVIEW', submitted_at=? WHERE id=?",
        (clock(), application["id"]),
    )
    await database.execute(
        """
        INSERT INTO recruitment_notification_outbox(
            guild_id, application_id, event_type, event_key, payload_json, status,
            available_at, created_at, processed_at, delivery_channel_id, delivery_message_id
        ) VALUES (?, ?, 'RECRUITMENT_APPLICATION_SUBMITTED', ?, '{}', 'COMPLETED', ?, ?, ?, ?, ?)
        """,
        (
            GUILD_ID,
            application["id"],
            f"application-submitted:{application['id']}",
            clock(),
            clock(),
            clock(),
            81,
            82,
        ),
    )
    await database.execute(
        """
        INSERT INTO recruitment_notification_outbox(
            guild_id, application_id, event_type, event_key, payload_json, available_at, created_at
        ) VALUES (?, ?, 'RECRUITMENT_REVIEW_CARD_REFRESH', ?, '{}', ?, ?)
        """,
        (
            GUILD_ID,
            application["id"],
            f"application-review-card:{application['id']}:v1",
            clock(),
            clock(),
        ),
    )
    row = await database.fetchone(
        "SELECT * FROM recruitment_notification_outbox WHERE event_type='RECRUITMENT_REVIEW_CARD_REFRESH'"
    )
    message = Message()
    channel = Channel(message)
    monkeypatch.setattr(web_outbox_module.discord, "TextChannel", Channel)
    worker = WebActionWorker(
        database,
        None,
        SimpleNamespace(settings=Settings()),
        Bot(channel),
    )

    assert await worker._dispatch_recruitment(row) == (81, 82)
    assert len(message.edits) == 1
    assert "EM ANÁLISE" in message.edits[0]["embed"].title


@pytest.mark.asyncio
async def test_review_card_recovery_enqueues_one_in_place_refresh_per_version(
    recruitment_bundle,
) -> None:
    """A restart updates the existing card, never sending a second one."""
    database = recruitment_bundle["database"]
    clock = recruitment_bundle["clock"]
    application = await _start(recruitment_bundle["service"])
    await database.execute(
        """
        UPDATE recruitment_applications
        SET status='UNDER_REVIEW', submitted_at=?
        WHERE id=?
        """,
        (clock(), application["id"]),
    )
    await database.execute(
        """
        INSERT INTO recruitment_notification_outbox(
            guild_id, application_id, event_type, event_key, payload_json, status,
            available_at, created_at, processed_at, delivery_channel_id, delivery_message_id
        ) VALUES (?, ?, 'RECRUITMENT_APPLICATION_SUBMITTED', ?, '{}', 'COMPLETED', ?, ?, ?, ?, ?)
        """,
        (
            GUILD_ID,
            application["id"],
            f"application-submitted:{application['id']}",
            clock(),
            clock(),
            clock(),
            81,
            82,
        ),
    )
    worker = WebActionWorker(database, None, SimpleNamespace(settings=None), object())  # type: ignore[arg-type]

    assert await worker._enqueue_recruitment_review_card_refreshes(clock()) == 1
    assert await worker._enqueue_recruitment_review_card_refreshes(clock()) == 0
    refreshes = await database.fetchall(
        """
        SELECT event_type, event_key, status FROM recruitment_notification_outbox
        WHERE application_id=? AND event_type='RECRUITMENT_REVIEW_CARD_REFRESH'
        """,
        (application["id"],),
    )
    assert [(row["event_type"], row["status"] ) for row in refreshes] == [
        ("RECRUITMENT_REVIEW_CARD_REFRESH", "PENDING")
    ]
    assert refreshes[0]["event_key"] == f"application-review-card:{application['id']}:v1"


@pytest.mark.asyncio
async def test_recovery_review_card_refreshes_are_paced_without_delaying_new_actions(
    recruitment_bundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = recruitment_bundle["database"]
    application = await _start(recruitment_bundle["service"])
    now = [1_000]
    monkeypatch.setattr(web_outbox_module, "utc_now_ms", lambda: now[0])
    insert_refresh = """
        INSERT INTO recruitment_notification_outbox(
            guild_id, application_id, event_type, event_key, payload_json, available_at, created_at
        ) VALUES (?, ?, 'RECRUITMENT_REVIEW_CARD_REFRESH', ?, ?, ?, ?)
        """
    for event_key in (
        "application-review-card:recovery-a",
        "application-review-card:recovery-b",
    ):
        await database.execute(
            insert_refresh,
            (GUILD_ID, application["id"], event_key, '{"recovery": true}', now[0], now[0]),
        )
    worker = WebActionWorker(database, None, SimpleNamespace(settings=None), object())  # type: ignore[arg-type]
    dispatched: list[int] = []

    async def dispatch(row):
        dispatched.append(int(row["id"]))
        return 81, 82

    monkeypatch.setattr(worker, "_dispatch_recruitment", dispatch)
    assert await worker.process_recruitment_pending() == 1
    assert await worker.process_recruitment_pending() == 0
    assert len(dispatched) == 1
    now[0] += web_outbox_module.RECOVERY_REVIEW_CARD_REFRESH_INTERVAL_MS
    assert await worker.process_recruitment_pending() == 1
    assert len(dispatched) == 2


@pytest.mark.asyncio
async def test_review_card_has_direct_controls_and_final_state_disables_them() -> None:
    pending = {"id": 91, "protocol": "AL-00091", "status": "UNDER_REVIEW"}
    view = build_recruitment_review_view(pending, "https://portal.example/recrutamento")
    controls = [item for item in view.children if isinstance(item, discord.ui.Button)]
    assert [item.label for item in controls] == [
        "Abrir dossiê",
        "Adicionar nota",
        "Entrevista",
        "Decidir",
        "Aprovar",
        "Reprovar",
    ]
    assert [item.disabled for item in controls[-2:]] == [False, False]
    final = {**pending, "status": "APPROVED", "decided_by": ADMIN_ID, "decided_at": 1_700_000_000_000}
    final_view = build_recruitment_review_view(final, "https://portal.example/recrutamento")
    final_controls = [item for item in final_view.children if isinstance(item, discord.ui.Button)]
    assert [item.disabled for item in final_controls[:4]] == [False, True, True, True]
    assert [item.disabled for item in final_controls[-2:]] == [True, True]
    embed = build_recruitment_review_embed(Branding(), final)
    assert "APROVADA" in embed.title
    assert any(field.name == "Decidida por" for field in embed.fields)


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
async def test_recruitment_public_status_backlog_delivers_only_latest_card_state(
    recruitment_bundle, monkeypatch
) -> None:
    """A recovered backlog must not PATCH one public Discord card repeatedly."""
    database = recruitment_bundle["database"]
    clock = recruitment_bundle["clock"]
    application = await _start(recruitment_bundle["service"])
    now = clock()
    async with database.transaction() as connection:
        await connection.executemany(
            """
            INSERT INTO recruitment_notification_outbox(
                guild_id, application_id, event_type, event_key, payload_json,
                available_at, created_at
            ) VALUES (?, ?, 'RECRUITMENT_PUBLIC_STATUS', ?, '{}', ?, ?)
            """,
            (
                (GUILD_ID, application["id"], "public-status:submitted", now, now),
                (GUILD_ID, application["id"], "public-status:under-review", now, now),
                (GUILD_ID, application["id"], "public-status:approved", now, now),
            ),
        )
    worker = WebActionWorker(database, None, recruitment_bundle["audit"], object())  # type: ignore[arg-type]
    delivered_ids: list[int] = []

    async def dispatch(row):
        delivered_ids.append(int(row["id"]))
        return 77, 88

    monkeypatch.setattr(worker, "_dispatch_recruitment", dispatch)

    assert await worker.process_recruitment_pending() == 1
    rows = await database.fetchall(
        """
        SELECT id, event_type, status, attempts, last_error FROM recruitment_notification_outbox
        WHERE application_id=? ORDER BY id
        """,
        (application["id"],),
    )
    public_rows = [row for row in rows if row["event_type"] == "RECRUITMENT_PUBLIC_STATUS"]
    assert len(public_rows) == 3
    assert delivered_ids == [int(public_rows[-1]["id"])]
    assert [int(row["attempts"]) for row in public_rows] == [0, 0, 1]
    assert "Coalescida" in str(public_rows[0]["last_error"])
    assert "Coalescida" in str(public_rows[1]["last_error"])
    assert public_rows[-1]["last_error"] is None


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
