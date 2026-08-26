from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from choque.config import Branding
from choque.errors import ConflictError
from cogs.training_commands import (
    CoursePanelView,
    build_course_catalog_embed,
    build_course_panel_embed,
)

from .conftest import DISCORD_ID, GUILD_ID

DAY_MS = 86_400_000


async def create_event(service_bundle, *, capacity: int = 20, name: str = "Treinamento de Choque"):
    training = service_bundle["training"]
    clock = service_bundle["clock"]
    return await training.create_training(
        GUILD_ID,
        actor_id=900,
        name=name,
        description="Formação operacional da unidade",
        scheduled_at=clock.value + DAY_MS,
        responsible_id=DISCORD_ID,
        capacity=capacity,
        course_name="Operador de Choque",
    )


async def import_course(service_bundle, *, status: str = "OPEN"):
    return await service_bundle["training"].import_catalog_course(
        GUILD_ID,
        actor_id=900,
        internal_code="abordagem_basica",
        name="Abordagem Básica",
        description="Formação fundamental",
        course_role_id=222,
        course_role_name="Curso Abordagem Básica",
        passing_score=90,
        cooldown_days=14,
        enrollment_status=status,
        notes="Fonte histórica",
        source_channel_id=300,
        source_message_id=301,
        source_content_sha256="a" * 64,
        requirements=[(111, "Praças")],
    )


@pytest.mark.asyncio
async def test_training_creation_enrollment_and_message_recovery(service_bundle):
    training = service_bundle["training"]
    event = await create_event(service_bundle)
    event_id = int(event["training_id"])

    enrolled = await training.enroll(GUILD_ID, event_id, DISCORD_ID)
    assert enrolled["enrolled_count"] == 1
    await training.attach_message(GUILD_ID, event_id, 100, 200)
    persisted = await training.persistent_events()
    assert [(row["id"], row["channel_id"], row["message_id"]) for row in persisted] == [
        (event_id, 100, 200)
    ]


@pytest.mark.asyncio
async def test_enrollment_cancel_and_rejoin_do_not_duplicate(service_bundle):
    training = service_bundle["training"]
    database = service_bundle["database"]
    event_id = int((await create_event(service_bundle))["training_id"])
    await training.enroll(GUILD_ID, event_id, DISCORD_ID)
    cancelled = await training.cancel_enrollment(GUILD_ID, event_id, DISCORD_ID)
    assert cancelled["enrolled_count"] == 0
    rejoined = await training.enroll(GUILD_ID, event_id, DISCORD_ID)
    assert rejoined["enrolled_count"] == 1
    row = await database.fetchone(
        "SELECT COUNT(*) AS total FROM training_enrollments WHERE training_id=?",
        (event_id,),
    )
    assert row["total"] == 1


@pytest.mark.asyncio
async def test_capacity_is_protected_under_concurrent_enrollment(service_bundle):
    training = service_bundle["training"]
    members = service_bundle["members"]
    second_id = 789
    await members.create_or_update(
        GUILD_ID,
        second_id,
        discord_nick="Segundo",
        mta_nick="Segundo_Membro",
        character_id="88",
        unit="BGR",
        rank_id=None,
        actor_id=900,
    )
    event_id = int((await create_event(service_bundle, capacity=1))["training_id"])
    results = await asyncio.gather(
        training.enroll(GUILD_ID, event_id, DISCORD_ID),
        training.enroll(GUILD_ID, event_id, second_id),
        return_exceptions=True,
    )
    assert len([result for result in results if isinstance(result, dict)]) == 1
    assert len([result for result in results if isinstance(result, ConflictError)]) == 1


@pytest.mark.asyncio
async def test_non_active_member_cannot_enroll(service_bundle):
    training = service_bundle["training"]
    database = service_bundle["database"]
    event_id = int((await create_event(service_bundle))["training_id"])
    await database.execute(
        "UPDATE members SET status='SUSPENDED' WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    with pytest.raises(ConflictError, match="Somente membros ativos"):
        await training.enroll(GUILD_ID, event_id, DISCORD_ID)


@pytest.mark.asyncio
async def test_training_completion_requires_decisions_and_records_course(service_bundle):
    training = service_bundle["training"]
    event_id = int((await create_event(service_bundle))["training_id"])
    await training.enroll(GUILD_ID, event_id, DISCORD_ID)
    await training.close_enrollment(GUILD_ID, event_id, actor_id=900)

    with pytest.raises(ConflictError, match="sem presença e resultado"):
        await training.complete_training(GUILD_ID, event_id, actor_id=900)

    await training.decide_participant(
        GUILD_ID,
        event_id,
        DISCORD_ID,
        actor_id=900,
        attendance="PRESENT",
        result="APPROVED",
    )
    completed = await training.complete_training(GUILD_ID, event_id, actor_id=900)
    assert completed == {
        "training_id": event_id,
        "status": "COMPLETED",
        "participants": 1,
        "approved": 1,
        "failed": 0,
    }
    courses = await training.member_courses(GUILD_ID, DISCORD_ID)
    assert courses[0]["course_name"] == "Operador de Choque"
    assert courses[0]["result"] == "APPROVED"
    evaluation = await service_bundle["database"].fetchone(
        "SELECT * FROM training_evaluations WHERE training_id=?", (event_id,)
    )
    assert evaluation["performance"] == "GOOD"
    assert evaluation["attendance"] == "PRESENT"


@pytest.mark.asyncio
async def test_training_completion_queues_exactly_one_course_role_sync(service_bundle):
    training = service_bundle["training"]
    database = service_bundle["database"]
    await training.import_catalog_course(
        GUILD_ID,
        actor_id=900,
        internal_code="operador_choque",
        name="Operador de Choque",
        description="Qualificação operacional",
        course_role_id=9_900,
        course_role_name="Curso Operador de Choque",
        passing_score=80,
        cooldown_days=7,
        enrollment_status="OPEN",
        notes=None,
        source_channel_id=300,
        source_message_id=302,
        source_content_sha256="b" * 64,
        requirements=[],
    )
    event_id = int((await create_event(service_bundle))["training_id"])
    await training.enroll(GUILD_ID, event_id, DISCORD_ID)
    await training.close_enrollment(GUILD_ID, event_id, actor_id=900)
    await training.decide_participant(
        GUILD_ID,
        event_id,
        DISCORD_ID,
        actor_id=900,
        attendance="PRESENT",
        result="APPROVED",
    )

    await training.complete_training(GUILD_ID, event_id, actor_id=900)

    changes = await database.fetchall(
        "SELECT * FROM qualification_changes WHERE source='TRAINING'"
    )
    outbox = await database.fetchall(
        "SELECT * FROM web_action_outbox WHERE action_type='QUALIFICATION_SYNC'"
    )
    assert len(changes) == 1
    assert changes[0]["action"] == "GRANT"
    assert len(outbox) == 1
    assert outbox[0]["status"] == "PENDING"
    assert json.loads(outbox[0]["payload_json"]) == {
        "course_id": changes[0]["course_id"],
        "granted": True,
        "source": "TRAINING",
    }


@pytest.mark.asyncio
async def test_training_cancellation_is_preserved_in_history(service_bundle):
    training = service_bundle["training"]
    event_id = int((await create_event(service_bundle))["training_id"])
    result = await training.cancel_training(
        GUILD_ID, event_id, actor_id=900, reason="Indisponibilidade do instrutor"
    )
    assert result["status"] == "CANCELLED"
    history = await training.history(GUILD_ID)
    assert history[0]["id"] == event_id
    assert history[0]["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_course_catalog_import_is_idempotent_and_preserves_requirements(service_bundle):
    await import_course(service_bundle)
    await import_course(service_bundle)
    rows = await service_bundle["training"].catalog(GUILD_ID)
    assert len(rows) == 1
    assert rows[0]["name"] == "Abordagem Básica"
    assert rows[0]["requirement_count"] == 1
    requirements = await service_bundle["training"].course_requirements(
        GUILD_ID, int(rows[0]["id"])
    )
    assert [(row["required_role_id"], row["required_role_name"]) for row in requirements] == [
        (111, "Praças")
    ]


@pytest.mark.asyncio
async def test_course_panel_channel_is_persistent_audited_and_individual(service_bundle):
    imported = await import_course(service_bundle)
    course_id = int(imported["course_id"])
    training = service_bundle["training"]
    configured = await training.configure_course_panel_channel(
        GUILD_ID, course_id, 7_001, actor_id=900
    )
    assert configured["panel_channel_id"] == 7_001
    row = await training.course_by_id(GUILD_ID, course_id)
    assert row["panel_channel_id"] == 7_001
    audit = await service_bundle["database"].fetchone(
        "SELECT action FROM audit_logs WHERE action='COURSE_PANEL_CHANNEL_UPDATED'"
    )
    assert audit["action"] == "COURSE_PANEL_CHANNEL_UPDATED"

    bot = SimpleNamespace(
        config=SimpleNamespace(branding=Branding()),
        services=SimpleNamespace(training=training, database=service_bundle["database"]),
    )
    index = await build_course_catalog_embed(bot, GUILD_ID)
    panel = await build_course_panel_embed(bot, GUILD_ID, course_id)
    assert not index.fields
    assert "1 curso(s) ativo(s)" in index.description
    assert panel.title == "🎓 Abordagem Básica"
    assert any(field.name == "Requisitos" for field in panel.fields)
    view = CoursePanelView("abordagem_basica", "Abordagem Básica", enrollment_open=True)
    assert len(view.children) == 1
    assert view.children[0].custom_id == "choque:course:apply:abordagem_basica:v1"


@pytest.mark.asyncio
async def test_course_application_checks_roles_and_pending_duplicate(service_bundle):
    training = service_bundle["training"]
    await import_course(service_bundle)
    with pytest.raises(ConflictError, match="requisitos de cargo"):
        await training.apply_to_course(GUILD_ID, DISCORD_ID, "abordagem_basica", [])
    applied = await training.apply_to_course(
        GUILD_ID, DISCORD_ID, "abordagem_basica", [111]
    )
    assert applied["status"] == "PENDING"
    with pytest.raises(ConflictError, match="solicitação pendente"):
        await training.apply_to_course(GUILD_ID, DISCORD_ID, "abordagem_basica", [111])


@pytest.mark.asyncio
async def test_satellite_course_uses_canonical_service_history(service_bundle):
    source_guild_id = GUILD_ID
    target_guild_id = GUILD_ID + 1
    training = service_bundle["training"]
    database = service_bundle["database"]
    settings = service_bundle["settings"]
    training.settings = settings

    source_member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
        (source_guild_id, DISCORD_ID),
    )
    await service_bundle["members"].create_or_update(
        target_guild_id,
        DISCORD_ID,
        discord_nick="Membro REC",
        mta_nick=str(source_member["mta_nick"]),
        character_id=source_member["character_id"],
        unit="BGR",
        rank_id=None,
        actor_id=900,
    )
    now = service_bundle["clock"].value
    await database.execute(
        """
        INSERT INTO shifts(
            guild_id,member_id,status,started_at,ended_at,closed_at,end_reason,
            created_by,created_at,patrol_duration_ms,gross_duration_ms,
            validation_status,automatic_validation_status,validation_source
        ) VALUES(?,?,'CLOSED',?,?,?,?,?,?,?,?,'VALID','VALID','LEGACY')
        """,
        (
            source_guild_id,
            int(source_member["id"]),
            now - 18_000_000,
            now,
            now,
            "TEST_CANONICAL_HISTORY",
            900,
            now,
            18_000_000,
            18_000_000,
        ),
    )
    await settings.set(
        target_guild_id, "identity_source_guild_id", source_guild_id, actor_id=900
    )
    imported = await training.import_catalog_course(
        target_guild_id,
        actor_id=900,
        internal_code="curso_rec",
        name="Curso REC",
        description="Curso com histórico canônico",
        course_role_id=333,
        course_role_name="Curso REC",
        passing_score=90,
        cooldown_days=14,
        enrollment_status="OPEN",
        notes=None,
        source_channel_id=400,
        source_message_id=401,
        source_content_sha256="b" * 64,
        requirements=[(444, "Membro REC")],
    )
    await database.execute(
        "UPDATE course_catalog SET minimum_valid_hours_ms=? WHERE id=?",
        (14_400_000, int(imported["course_id"])),
    )

    applied = await training.apply_to_course(
        target_guild_id, DISCORD_ID, "curso_rec", [444]
    )

    assert applied["status"] == "PENDING"


@pytest.mark.asyncio
async def test_course_application_rejects_closed_and_already_qualified(service_bundle):
    training = service_bundle["training"]
    await import_course(service_bundle, status="CLOSED")
    with pytest.raises(ConflictError, match="inscrições temporariamente encerradas"):
        await training.apply_to_course(GUILD_ID, DISCORD_ID, "abordagem_basica", [111])
    await import_course(service_bundle, status="OPEN")
    with pytest.raises(ConflictError, match="curso já consta nos seus cargos"):
        await training.apply_to_course(GUILD_ID, DISCORD_ID, "abordagem_basica", [111, 222])


@pytest.mark.asyncio
async def test_rejected_course_application_enforces_cooldown(service_bundle):
    training = service_bundle["training"]
    clock = service_bundle["clock"]
    await import_course(service_bundle)
    application = await training.apply_to_course(
        GUILD_ID, DISCORD_ID, "abordagem_basica", [111]
    )
    await training.decide_course_application(
        GUILD_ID,
        int(application["application_id"]),
        900,
        approved=False,
        reason="Nota insuficiente",
    )
    with pytest.raises(ConflictError, match="nova solicitação disponível"):
        await training.apply_to_course(GUILD_ID, DISCORD_ID, "abordagem_basica", [111])
    clock.advance(14 * DAY_MS)
    second = await training.apply_to_course(
        GUILD_ID, DISCORD_ID, "abordagem_basica", [111]
    )
    assert int(second["application_id"]) > int(application["application_id"])


@pytest.mark.asyncio
async def test_course_application_decision_is_concurrency_safe(service_bundle):
    training = service_bundle["training"]
    await import_course(service_bundle)
    application = await training.apply_to_course(
        GUILD_ID, DISCORD_ID, "abordagem_basica", [111]
    )
    results = await asyncio.gather(
        training.decide_course_application(
            GUILD_ID,
            int(application["application_id"]),
            900,
            approved=True,
            reason="Requisitos conferidos",
        ),
        training.decide_course_application(
            GUILD_ID,
            int(application["application_id"]),
            901,
            approved=False,
            reason="Decisão concorrente",
        ),
        return_exceptions=True,
    )
    assert len([result for result in results if isinstance(result, dict)]) == 1
    assert len([result for result in results if isinstance(result, ConflictError)]) == 1
