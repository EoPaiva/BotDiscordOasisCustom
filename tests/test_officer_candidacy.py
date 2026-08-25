from __future__ import annotations

import asyncio
import json

import pytest

from choque.career import HOUR_MS
from choque.errors import ConflictError, PermissionDenied, ValidationError

from .conftest import DISCORD_ID, GUILD_ID

REVIEWER_ID = 900_001


async def _rank(bundle, name: str, level: int) -> int:
    return await bundle["database"].execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
        ) VALUES (?, ?, ?, ?, ?, 'MEMBRO', ?)
        """,
        (GUILD_ID, name, name[:3], level, 920_000 + level, bundle["clock"]()),
    )


async def _prepare_eligible_member(bundle) -> None:
    await _rank(bundle, "RECRUTA", 10)
    soldier_id = await _rank(bundle, "SOLDADO", 20)
    await _rank(bundle, "CADETE", 80)
    await bundle["database"].execute(
        """
        UPDATE members
        SET rank_id=?, status='ACTIVE', identity_sync_status='SYNCED',
            discord_present=1, discord_roles_synced_at=?, rank_sync_status='SYNCED',
            updated_at=?
        WHERE guild_id=? AND discord_id=?
        """,
        (
            soldier_id,
            bundle["clock"](),
            bundle["clock"](),
            GUILD_ID,
            DISCORD_ID,
        ),
    )
    member = await bundle["database"].fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    started_at = bundle["clock"]() - 6 * HOUR_MS
    await bundle["database"].execute(
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
            bundle["clock"](),
            bundle["clock"](),
            DISCORD_ID,
            started_at,
            6 * HOUR_MS,
            6 * HOUR_MS,
            bundle["clock"](),
        ),
    )


async def _answer_all(bundle, application_id: int) -> None:
    questions = await bundle["career"].officer_questionnaire(GUILD_ID)
    for question in questions["questions"]:
        await bundle["career"].save_officer_answer(
            GUILD_ID,
            application_id,
            DISCORD_ID,
            int(question["id"]),
            (
                "Eu preservaria a segurança, comunicaria a equipe com clareza, "
                "registraria os fatos e justificaria a decisão com ética e responsabilidade."
            ),
        )


@pytest.mark.asyncio
async def test_officer_questionnaire_is_exactly_thirty_and_idempotent(service_bundle) -> None:
    first, second = await asyncio.gather(
        service_bundle["career"].ensure_officer_questionnaire(
            GUILD_ID, actor_id=REVIEWER_ID
        ),
        service_bundle["career"].ensure_officer_questionnaire(
            GUILD_ID, actor_id=REVIEWER_ID
        ),
    )
    third = await service_bundle["career"].ensure_officer_questionnaire(
        GUILD_ID, actor_id=REVIEWER_ID
    )
    questionnaire = await service_bundle["career"].officer_questionnaire(GUILD_ID)

    assert first == second == third
    assert len(questionnaire["questions"]) == 30
    assert [item["question_number"] for item in questionnaire["questions"]] == list(
        range(1, 31)
    )
    assert len({item["prompt"] for item in questionnaire["questions"]}) == 30
    assert sum(questionnaire["weights"].values()) == 100


@pytest.mark.asyncio
async def test_officer_application_requires_rank_hours_and_respects_cooldown(
    service_bundle,
) -> None:
    await service_bundle["career"].ensure_officer_questionnaire(
        GUILD_ID, actor_id=REVIEWER_ID
    )
    ineligible = await service_bundle["career"].officer_eligibility(
        GUILD_ID, DISCORD_ID
    )
    assert ineligible["eligible"] is False
    assert "PATENTE" in ineligible["missing"]

    await _prepare_eligible_member(service_bundle)
    eligible = await service_bundle["career"].officer_eligibility(GUILD_ID, DISCORD_ID)
    assert eligible["eligible"] is True
    assert eligible["valid_hours_ms"] == 6 * HOUR_MS

    application = await service_bundle["career"].start_officer_application(
        GUILD_ID, DISCORD_ID
    )
    same = await service_bundle["career"].start_officer_application(GUILD_ID, DISCORD_ID)
    assert same["id"] == application["id"]

    await _answer_all(service_bundle, int(application["id"]))
    await service_bundle["career"].submit_officer_application(
        GUILD_ID, int(application["id"]), DISCORD_ID
    )
    await service_bundle["career"].claim_officer_application(
        GUILD_ID, int(application["id"]), REVIEWER_ID
    )
    decided = await service_bundle["career"].decide_officer_application(
        GUILD_ID,
        int(application["id"]),
        REVIEWER_ID,
        decision="REJECTED",
        reason="Ainda precisa demonstrar maturidade de comando em situações reais.",
    )
    assert decided["status"] == "REJECTED"
    assert decided["resubmit_after"] == service_bundle["clock"]() + 30 * 24 * HOUR_MS

    cooldown = await service_bundle["career"].officer_eligibility(GUILD_ID, DISCORD_ID)
    assert cooldown["eligible"] is False
    assert "COOLDOWN" in cooldown["missing"]
    with pytest.raises(ConflictError, match="aguardar"):
        await service_bundle["career"].start_officer_application(GUILD_ID, DISCORD_ID)


@pytest.mark.asyncio
async def test_officer_submission_generates_advisory_analysis_but_human_decides(
    service_bundle,
) -> None:
    await _prepare_eligible_member(service_bundle)
    await service_bundle["career"].ensure_officer_questionnaire(
        GUILD_ID, actor_id=REVIEWER_ID
    )
    application = await service_bundle["career"].start_officer_application(
        GUILD_ID, DISCORD_ID
    )
    with pytest.raises(ValidationError, match="30"):
        await service_bundle["career"].submit_officer_application(
            GUILD_ID, int(application["id"]), DISCORD_ID
        )

    await _answer_all(service_bundle, int(application["id"]))
    submitted = await service_bundle["career"].submit_officer_application(
        GUILD_ID, int(application["id"]), DISCORD_ID
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["analysis"]["advisory_only"] is True
    assert 1 <= submitted["analysis"]["overall_score"] <= 10
    assert len(submitted["analysis"]["competencies"]) == 10

    row = await service_bundle["database"].fetchone(
        "SELECT analysis_report_json, reviewed_by FROM officer_applications WHERE id=?",
        (application["id"],),
    )
    report = json.loads(row["analysis_report_json"])
    assert report["advisory_only"] is True
    assert row["reviewed_by"] is None
    notification = await service_bundle["database"].fetchone(
        """
        SELECT notification_type, status FROM career_notifications
        WHERE subject_id=? AND notification_type='OFFICER_SUBMITTED'
        """,
        (application["id"],),
    )
    assert tuple(notification) == ("OFFICER_SUBMITTED", "PENDING")

    with pytest.raises(ConflictError, match="assumida"):
        await service_bundle["career"].decide_officer_application(
            GUILD_ID,
            int(application["id"]),
            REVIEWER_ID,
            decision="APPROVED",
            reason="Boa capacidade técnica e postura compatível.",
        )


@pytest.mark.asyncio
async def test_officer_review_is_versioned_private_and_human_only(service_bundle) -> None:
    await _prepare_eligible_member(service_bundle)
    await service_bundle["career"].ensure_officer_questionnaire(
        GUILD_ID, actor_id=REVIEWER_ID
    )
    application = await service_bundle["career"].start_officer_application(
        GUILD_ID, DISCORD_ID
    )
    await _answer_all(service_bundle, int(application["id"]))
    await service_bundle["career"].submit_officer_application(
        GUILD_ID, int(application["id"]), DISCORD_ID
    )

    claimed = await service_bundle["career"].claim_officer_application(
        GUILD_ID, int(application["id"]), REVIEWER_ID
    )
    assert claimed["status"] == "IN_REVIEW"
    assert claimed["assigned_to"] == REVIEWER_ID
    same = await service_bundle["career"].claim_officer_application(
        GUILD_ID, int(application["id"]), REVIEWER_ID
    )
    assert same["version"] == claimed["version"]
    with pytest.raises(ConflictError, match="responsável"):
        await service_bundle["career"].claim_officer_application(
            GUILD_ID, int(application["id"]), REVIEWER_ID + 1
        )
    with pytest.raises(PermissionDenied, match="própria"):
        await service_bundle["career"].decide_officer_application(
            GUILD_ID,
            int(application["id"]),
            DISCORD_ID,
            decision="APPROVED",
            reason="Não pode decidir a própria candidatura.",
        )

    review_before_decision = await service_bundle[
        "career"
    ].officer_application_detail(
        GUILD_ID, int(application["id"]), viewer_id=REVIEWER_ID, reviewer=True
    )
    question_id = int(review_before_decision["answers"][0]["question_id"])
    score = await service_bundle["career"].record_officer_score(
        GUILD_ID,
        int(application["id"]),
        REVIEWER_ID,
        question_id=question_id,
        score=8,
        rationale="Resposta coerente e responsável.",
    )
    interview = await service_bundle["career"].record_officer_interview(
        GUILD_ID,
        int(application["id"]),
        REVIEWER_ID,
        scheduled_at=service_bundle["clock"]() + HOUR_MS,
        result="POSITIVE",
        observations="Demonstrou postura adequada na entrevista.",
    )
    assert score["source"] == "HUMAN"
    assert interview["status"] == "INTERVIEW_REQUIRED"

    final = await service_bundle["career"].decide_officer_application(
        GUILD_ID,
        int(application["id"]),
        REVIEWER_ID,
        decision="APPROVED_CONDITIONAL",
        reason="Apto com acompanhamento inicial obrigatório.",
        condition_text="Concluir duas operações supervisionadas.",
        condition_due_at=service_bundle["clock"]() + 7 * 24 * HOUR_MS,
    )
    assert final["status"] == "APPROVED_CONDITIONAL"
    detail_for_member = await service_bundle["career"].officer_application_detail(
        GUILD_ID, int(application["id"]), viewer_id=DISCORD_ID, reviewer=False
    )
    assert "analysis_report" not in detail_for_member
    assert "interviewer_id" not in detail_for_member["interviews"][0]
    assert "observations" not in detail_for_member["interviews"][0]
    assert all("actor_id" not in event for event in detail_for_member["events"])
    detail_for_reviewer = await service_bundle["career"].officer_application_detail(
        GUILD_ID, int(application["id"]), viewer_id=REVIEWER_ID, reviewer=True
    )
    assert detail_for_reviewer["analysis_report"]["advisory_only"] is True
    assert detail_for_reviewer["scores"][0]["source"] == "HUMAN"
    assert detail_for_reviewer["interviews"][0]["observations"].startswith("Demonstrou")
    assert detail_for_reviewer["conditions"][0]["condition_text"].startswith("Concluir")
    assert detail_for_reviewer["events"][-1]["next_status"] == "APPROVED_CONDITIONAL"
    notification = await service_bundle["database"].fetchone(
        """
        SELECT notification_type, status FROM career_notifications
        WHERE subject_id=? AND notification_type='OFFICER_DECISION'
        """,
        (application["id"],),
    )
    assert tuple(notification) == ("OFFICER_DECISION", "PENDING")
