from __future__ import annotations

import pytest

from choque.errors import ConflictError, ValidationError
from choque.rbac import PROFILE_PERMISSIONS
from cogs.operations_commands import (
    MemberOperationsView,
    PatrolCentralView,
    PatrolManagementView,
    PatrolReportView,
)

from .conftest import DISCORD_ID, GUILD_ID

WAITING = 2_001
ACTIVE_A = 2_002
ACTIVE_B = 2_003
RANK_ROLE = 8_001
MEMBER_ROLE = 8_002


async def prepare_ranked_member(
    bundle,
    discord_id: int,
    *,
    name: str | None = None,
    rank_level: int = 10,
    rank_role: int = RANK_ROLE,
    rank_name: str = "SOLDADO",
) -> int:
    database = bundle["database"]
    rank = await database.fetchone(
        "SELECT id FROM ranks WHERE guild_id=? AND discord_role_id=?",
        (GUILD_ID, rank_role),
    )
    if not rank:
        rank_id = await database.execute(
            """
            INSERT INTO ranks(
                guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
            ) VALUES (?, ?, ?, ?, ?, 'MEMBRO', ?)
            """,
            (
                GUILD_ID,
                rank_name,
                rank_name[:3],
                rank_level,
                rank_role,
                bundle["clock"](),
            ),
        )
    else:
        rank_id = int(rank["id"])
    existing = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, discord_id),
    )
    if existing:
        await database.execute(
            """
            UPDATE members SET rank_id=?, status='ACTIVE', rank_sync_status='SYNCED'
            WHERE guild_id=? AND discord_id=?
            """,
            (rank_id, GUILD_ID, discord_id),
        )
        return int(existing["id"])
    await bundle["members"].create_or_update(
        GUILD_ID,
        discord_id,
        discord_nick=name or f"Discord {discord_id}",
        mta_nick=name or f"Militar_{discord_id}",
        character_id=str(discord_id)[-3:],
        unit="CHOQUE",
        rank_id=rank_id,
        actor_id=DISCORD_ID,
    )
    row = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, discord_id),
    )
    return int(row["id"])


async def prepare_patrol(bundle) -> None:
    operations = bundle["operations"]
    await operations.configure_patrol_channel(
        GUILD_ID, WAITING, "WAITING", "Aguardando", 0, DISCORD_ID
    )
    await operations.configure_patrol_channel(
        GUILD_ID, ACTIVE_A, "ACTIVE", "Alfa", 1, DISCORD_ID
    )
    await operations.configure_patrol_channel(
        GUILD_ID, ACTIVE_B, "ACTIVE", "Bravo", 2, DISCORD_ID
    )
    await bundle["settings"].set(GUILD_ID, "minimum_patrol_members", 2, DISCORD_ID)


@pytest.mark.asyncio
async def test_patrol_fifo_minimum_and_multiple_formations(service_bundle):
    operations = service_bundle["operations"]
    await prepare_patrol(service_bundle)
    for discord_id in (DISCORD_ID, 457, 458, 459):
        await prepare_ranked_member(service_bundle, discord_id)

    await operations.join_queue(
        GUILD_ID, DISCORD_ID, WAITING, source="VOICE", has_member_role=True
    )
    assert await operations.reserve_formations(
        GUILD_ID, [DISCORD_ID], [ACTIVE_A, ACTIVE_B]
    ) == []

    service_bundle["clock"].advance(1)
    await operations.join_queue(GUILD_ID, 457, WAITING, source="VOICE", has_member_role=True)
    first = await operations.reserve_formations(
        GUILD_ID, [DISCORD_ID, 457], [ACTIVE_A, ACTIVE_B]
    )
    assert len(first) == 1
    assert first[0]["member_discord_ids"] == [DISCORD_ID, 457]
    assert first[0]["channel_id"] == ACTIVE_A
    await operations.activate_formation(GUILD_ID, int(first[0]["patrol_id"]))

    await operations.join_queue(GUILD_ID, 458, WAITING, source="VOICE", has_member_role=True)
    assert await operations.reserve_formations(GUILD_ID, [458], [ACTIVE_B]) == []
    service_bundle["clock"].advance(1)
    await operations.join_queue(GUILD_ID, 459, WAITING, source="VOICE", has_member_role=True)
    second = await operations.reserve_formations(GUILD_ID, [458, 459], [ACTIVE_B])
    assert len(second) == 1
    assert second[0]["member_discord_ids"] == [458, 459]
    assert second[0]["channel_id"] == ACTIVE_B

    queued = await operations.queue(GUILD_ID)
    assert all(row["status"] == "FORMING" for row in queued)


@pytest.mark.asyncio
async def test_patrol_rollback_restores_fifo_and_prevents_duplicate_member(service_bundle):
    operations = service_bundle["operations"]
    await prepare_patrol(service_bundle)
    await prepare_ranked_member(service_bundle, DISCORD_ID)
    await prepare_ranked_member(service_bundle, 457)
    await operations.join_queue(
        GUILD_ID, DISCORD_ID, WAITING, source="PANEL", has_member_role=True
    )
    with pytest.raises(ConflictError, match="fila"):
        await operations.join_queue(
            GUILD_ID, DISCORD_ID, WAITING, source="PANEL", has_member_role=True
        )
    await operations.join_queue(GUILD_ID, 457, WAITING, source="PANEL", has_member_role=True)
    plan = (await operations.reserve_formations(GUILD_ID, [DISCORD_ID, 457], [ACTIVE_A]))[0]
    await operations.rollback_formation(GUILD_ID, int(plan["patrol_id"]), "Move Members negado")
    queue = await operations.queue(GUILD_ID)
    assert [int(row["discord_id"]) for row in queue] == [DISCORD_ID, 457]
    patrol = await service_bundle["database"].fetchone(
        "SELECT * FROM patrols WHERE id=?", (plan["patrol_id"],)
    )
    assert patrol["status"] == "CANCELLED"
    assert patrol["movement_error"] == "Move Members negado"


@pytest.mark.asyncio
async def test_patrol_lifecycle_history_and_private_feedback(service_bundle):
    operations = service_bundle["operations"]
    await prepare_patrol(service_bundle)
    await prepare_ranked_member(service_bundle, DISCORD_ID)
    await prepare_ranked_member(service_bundle, 457)
    await operations.join_queue(
        GUILD_ID, DISCORD_ID, WAITING, source="VOICE", has_member_role=True
    )
    await operations.join_queue(GUILD_ID, 457, WAITING, source="VOICE", has_member_role=True)
    plan = (await operations.reserve_formations(GUILD_ID, [DISCORD_ID, 457], [ACTIVE_A]))[0]
    patrol_id = int(plan["patrol_id"])
    await operations.activate_formation(GUILD_ID, patrol_id)
    service_bundle["clock"].advance(25 * 60_000)
    assert (await operations.mark_patrol_member_left(GUILD_ID, DISCORD_ID, ACTIVE_A))["closed"] is False
    assert (await operations.mark_patrol_member_left(GUILD_ID, 457, ACTIVE_A))["closed"] is True
    history = await operations.patrol_history(GUILD_ID, DISCORD_ID)
    assert history[0]["id"] == patrol_id
    assert history[0]["duration_ms"] == 25 * 60_000

    feedback_id = await operations.add_patrol_feedback(
        GUILD_ID, patrol_id, 457, DISCORD_ID, "POSITIVE", "Boa comunicação."
    )
    assert feedback_id > 0
    own = await operations.patrol_feedback_for_member(GUILD_ID, 457)
    assert own[0]["observation"] == "Boa comunicação."
    with pytest.raises(ConflictError, match="já foi registrado"):
        await operations.add_patrol_feedback(
            GUILD_ID, patrol_id, 457, DISCORD_ID, "POSITIVE", "Duplicado"
        )


@pytest.mark.asyncio
async def test_live_voice_presence_does_not_create_false_patrol_history(service_bundle):
    operations = service_bundle["operations"]
    await prepare_patrol(service_bundle)
    await prepare_ranked_member(service_bundle, DISCORD_ID, name="Paiva")
    await prepare_ranked_member(service_bundle, 457, name="Lopes")

    count = await operations.sync_patrol_voice_presence(
        GUILD_ID,
        {ACTIVE_A: [(DISCORD_ID, "Paiva"), (457, "Lopes")], ACTIVE_B: []},
    )
    assert count == 2
    overview = await operations.active_patrol_overview(GUILD_ID)
    assert len(overview) == 1
    assert overview[0]["origin"] == "DISCORD_LIVE"
    assert overview[0]["member_count"] == 2
    assert overview[0]["member_names"] == "Choque_User | Lopes"
    assert await service_bundle["database"].fetchone("SELECT id FROM patrols") is None

    service_bundle["clock"].advance(5_000)
    await operations.sync_patrol_voice_presence(GUILD_ID, {ACTIVE_A: [], ACTIVE_B: []})
    assert await operations.active_patrol_overview(GUILD_ID) == []


@pytest.mark.asyncio
async def test_patrol_commander_prefers_higher_rank_deterministically(service_bundle):
    operations = service_bundle["operations"]
    await prepare_patrol(service_bundle)
    await prepare_ranked_member(service_bundle, DISCORD_ID, rank_level=10)
    await prepare_ranked_member(
        service_bundle,
        457,
        rank_level=20,
        rank_role=RANK_ROLE + 1,
        rank_name="CABO",
    )
    await operations.join_queue(
        GUILD_ID, DISCORD_ID, WAITING, source="VOICE", has_member_role=True
    )
    service_bundle["clock"].advance(1)
    await operations.join_queue(GUILD_ID, 457, WAITING, source="VOICE", has_member_role=True)
    plan = (await operations.reserve_formations(GUILD_ID, [DISCORD_ID, 457], [ACTIVE_A]))[0]
    result = await operations.activate_formation(
        GUILD_ID, int(plan["patrol_id"]), [DISCORD_ID, 457]
    )
    assert result["commander_discord_id"] == 457
    patrol = await service_bundle["database"].fetchone(
        "SELECT * FROM patrols WHERE id=?", (plan["patrol_id"],)
    )
    assert patrol["commander_assignment_source"] == "AUTOMATIC"
    history = await operations.patrol_commander_history(GUILD_ID, int(plan["patrol_id"]))
    assert [row["discord_id"] for row in history] == [457]


@pytest.mark.asyncio
async def test_required_qualification_can_outweigh_rank(service_bundle):
    operations = service_bundle["operations"]
    await prepare_patrol(service_bundle)
    soldier_id = await prepare_ranked_member(service_bundle, DISCORD_ID, rank_level=10)
    await prepare_ranked_member(
        service_bundle,
        457,
        rank_level=20,
        rank_role=RANK_ROLE + 1,
        rank_name="CABO",
    )
    course_id = await service_bundle["database"].execute(
        """
        INSERT INTO course_catalog(
            guild_id, internal_code, name, description, course_role_id,
            course_role_name, passing_score, source_channel_id, source_message_id,
            source_content_sha256, created_at, updated_at
        ) VALUES (?, 'patrol-command', 'Comando de Patrulha', 'Qualificação operacional',
                  9901, 'Comando de Patrulha', 70, 10, 11, 'hash', ?, ?)
        """,
        (GUILD_ID, service_bundle["clock"](), service_bundle["clock"]()),
    )
    await service_bundle["database"].execute(
        """
        INSERT INTO member_qualifications(
            guild_id, member_id, discord_id, course_name, result,
            responsible_id, recorded_at
        ) VALUES (?, ?, ?, 'Comando de Patrulha', 'APPROVED', ?, ?)
        """,
        (GUILD_ID, soldier_id, DISCORD_ID, DISCORD_ID, service_bundle["clock"]()),
    )
    await operations.configure_patrol_commander(
        GUILD_ID,
        DISCORD_ID,
        enabled=True,
        require_qualification=True,
        required_qualification_id=course_id,
        minimum_rank_level=0,
        reassign_when_higher_rank_joins=False,
    )
    await operations.join_queue(
        GUILD_ID, DISCORD_ID, WAITING, source="VOICE", has_member_role=True
    )
    await operations.join_queue(GUILD_ID, 457, WAITING, source="VOICE", has_member_role=True)
    plan = (await operations.reserve_formations(GUILD_ID, [DISCORD_ID, 457], [ACTIVE_A]))[0]
    result = await operations.activate_formation(
        GUILD_ID, int(plan["patrol_id"]), [DISCORD_ID, 457]
    )
    assert result["commander_discord_id"] == DISCORD_ID


@pytest.mark.asyncio
async def test_equal_ranks_use_join_order_and_later_higher_rank_does_not_replace(service_bundle):
    operations = service_bundle["operations"]
    await prepare_patrol(service_bundle)
    first_member_id = await prepare_ranked_member(service_bundle, DISCORD_ID, rank_level=10)
    await prepare_ranked_member(service_bundle, 457, rank_level=10)
    higher_member_id = await prepare_ranked_member(
        service_bundle,
        458,
        rank_level=30,
        rank_role=RANK_ROLE + 2,
        rank_name="SARGENTO",
    )
    await operations.join_queue(
        GUILD_ID, DISCORD_ID, WAITING, source="VOICE", has_member_role=True
    )
    service_bundle["clock"].advance(1)
    await operations.join_queue(GUILD_ID, 457, WAITING, source="VOICE", has_member_role=True)
    plan = (await operations.reserve_formations(GUILD_ID, [DISCORD_ID, 457], [ACTIVE_A]))[0]
    patrol_id = int(plan["patrol_id"])
    initial = await operations.activate_formation(
        GUILD_ID, patrol_id, [DISCORD_ID, 457]
    )
    assert initial["commander_discord_id"] == DISCORD_ID
    assert first_member_id != higher_member_id

    service_bundle["clock"].advance(1)
    await service_bundle["database"].execute(
        """
        INSERT INTO patrol_members(
            guild_id, patrol_id, member_id, discord_id, member_role,
            status, reserved_at, joined_at
        ) VALUES (?, ?, ?, ?, 'MEMBER', 'ACTIVE', ?, ?)
        """,
        (
            GUILD_ID,
            patrol_id,
            higher_member_id,
            458,
            service_bundle["clock"](),
            service_bundle["clock"](),
        ),
    )
    unchanged = await operations.select_patrol_commander(
        GUILD_ID, patrol_id, [DISCORD_ID, 457, 458], reason="HIGHER_RANK_JOINED"
    )
    assert unchanged["changed"] is False
    assert unchanged["commander_discord_id"] == DISCORD_ID


@pytest.mark.asyncio
async def test_commander_reassignment_manual_lock_and_no_eligible_flag(service_bundle):
    operations = service_bundle["operations"]
    await prepare_patrol(service_bundle)
    await prepare_ranked_member(service_bundle, DISCORD_ID, rank_level=10)
    await prepare_ranked_member(
        service_bundle,
        457,
        rank_level=20,
        rank_role=RANK_ROLE + 1,
        rank_name="CABO",
    )
    await operations.join_queue(
        GUILD_ID, DISCORD_ID, WAITING, source="VOICE", has_member_role=True
    )
    await operations.join_queue(GUILD_ID, 457, WAITING, source="VOICE", has_member_role=True)
    plan = (await operations.reserve_formations(GUILD_ID, [DISCORD_ID, 457], [ACTIVE_A]))[0]
    patrol_id = int(plan["patrol_id"])
    await operations.activate_formation(GUILD_ID, patrol_id, [DISCORD_ID, 457])
    override = await operations.override_patrol_commander(
        GUILD_ID,
        patrol_id,
        DISCORD_ID,
        DISCORD_ID,
        "Decisão operacional",
        [DISCORD_ID, 457],
    )
    assert override["manual_lock"] is True
    await operations.configure_patrol_commander(
        GUILD_ID,
        DISCORD_ID,
        enabled=True,
        require_qualification=False,
        required_qualification_id=None,
        minimum_rank_level=0,
        reassign_when_higher_rank_joins=True,
    )
    unchanged = await operations.select_patrol_commander(
        GUILD_ID, patrol_id, [DISCORD_ID, 457], reason="HIGHER_RANK_JOINED"
    )
    assert unchanged["changed"] is False
    assert unchanged["commander_discord_id"] == DISCORD_ID

    left = await operations.mark_patrol_member_left(GUILD_ID, DISCORD_ID, ACTIVE_A)
    assert left and left["commander"]["commander_discord_id"] == 457
    history = await operations.patrol_commander_history(GUILD_ID, patrol_id)
    assert [row["source"] for row in history] == [
        "AUTOMATIC",
        "MANUAL_OVERRIDE",
        "REASSIGNMENT",
    ]
    assert history[-1]["ended_at"] is None

    await service_bundle["database"].execute(
        "UPDATE members SET status='SUSPENDED' WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, 457),
    )
    cleared = await operations.select_patrol_commander(
        GUILD_ID, patrol_id, [457], reason="MEMBER_STATUS_CHANGED"
    )
    assert cleared["commander_discord_id"] is None
    flag = await service_bundle["database"].fetchone(
        """
        SELECT * FROM patrol_operational_flags
        WHERE patrol_id=? AND flag_type='PATROL_WITHOUT_ELIGIBLE_COMMANDER'
          AND status='OPEN'
        """,
        (patrol_id,),
    )
    assert flag is not None
    repeated = await operations.select_patrol_commander(
        GUILD_ID, patrol_id, [457], reason="RESTART_RECONCILIATION"
    )
    assert repeated["changed"] is False
    audits = await service_bundle["database"].fetchall(
        "SELECT * FROM audit_logs WHERE action LIKE 'PATROL_COMMANDER_%'"
    )
    assert [row["action"] for row in audits].count("PATROL_COMMANDER_CLEARED") == 1


@pytest.mark.asyncio
async def test_maintenance_blocks_new_patrol_actions_without_destroying_state(service_bundle):
    operations = service_bundle["operations"]
    await prepare_patrol(service_bundle)
    await prepare_ranked_member(service_bundle, DISCORD_ID)
    await operations.set_maintenance(
        GUILD_ID, "PATROLS", True, DISCORD_ID, reason="Atualização controlada"
    )
    with pytest.raises(ValidationError, match="manutenção"):
        await operations.join_queue(
            GUILD_ID, DISCORD_ID, WAITING, source="PANEL", has_member_role=True
        )
    await operations.set_maintenance(
        GUILD_ID, "PATROLS", False, DISCORD_ID, reason="Concluída"
    )
    queue_id = await operations.join_queue(
        GUILD_ID, DISCORD_ID, WAITING, source="PANEL", has_member_role=True
    )
    assert queue_id > 0


@pytest.mark.asyncio
async def test_integrity_scan_classifies_safe_and_review_findings(service_bundle):
    operations = service_bundle["operations"]
    await prepare_ranked_member(service_bundle, DISCORD_ID)
    created = await operations.scan_integrity(
        GUILD_ID,
        [
            {"discord_id": DISCORD_ID, "role_ids": [], "display_name": "Sem cargos"},
            {"discord_id": 999, "role_ids": [MEMBER_ROLE], "display_name": "Sem cadastro"},
        ],
        member_role_id=MEMBER_ROLE,
    )
    assert len(created) >= 3
    findings = await operations.integrity_findings(GUILD_ID)
    classes = {row["finding_type"]: row["fix_class"] for row in findings}
    assert classes["MISSING_MEMBER_ROLE"] == "AUTO_FIX_SAFE"
    assert classes["MISSING_RANK_ROLE"] == "AUTO_FIX_SAFE"
    assert classes["DISCORD_MEMBER_WITHOUT_RECORD"] == "REQUIRES_REVIEW"


@pytest.mark.asyncio
async def test_course_extended_requirements_are_enforced(service_bundle):
    await prepare_ranked_member(service_bundle, DISCORD_ID)
    training = service_bundle["training"]
    imported = await training.import_catalog_course(
        GUILD_ID,
        DISCORD_ID,
        internal_code="operacoes",
        name="Operações",
        description="Formação operacional",
        course_role_id=9_001,
        course_role_name="Curso Operações",
        passing_score=70,
        cooldown_days=7,
        enrollment_status="OPEN",
        notes=None,
        source_channel_id=10,
        source_message_id=11,
        source_content_sha256="abc",
        requirements=[],
    )
    course_id = int(imported["course_id"])
    await service_bundle["operations"].configure_course_requirements(
        GUILD_ID,
        course_id,
        DISCORD_ID,
        minimum_rank_level=10,
        minimum_valid_hours=1,
        minimum_tenure_days=1,
        require_no_active_suspension=True,
        prerequisite_course_name="Básico",
    )
    denied = await training.course_eligibility(GUILD_ID, DISCORD_ID, "operacoes", [])
    assert denied["eligible"] is False
    assert "tempo mínimo de serviço válido não atendido" in denied["reasons"]
    assert "tempo mínimo de corporação não atendido" in denied["reasons"]
    assert "pré-requisito Básico não concluído" in denied["reasons"]
    await service_bundle["operations"].configure_course_requirements(
        GUILD_ID,
        course_id,
        DISCORD_ID,
        minimum_rank_level=10,
        minimum_valid_hours=0,
        minimum_tenure_days=0,
        require_no_active_suspension=True,
        prerequisite_course_name=None,
    )
    allowed = await training.course_eligibility(GUILD_ID, DISCORD_ID, "operacoes", [])
    assert allowed["eligible"] is True


@pytest.mark.asyncio
async def test_recruit_promotion_dossier_and_nonautomatic_decision(service_bundle):
    member_id = await prepare_ranked_member(service_bundle, DISCORD_ID)
    await service_bundle["database"].execute(
        "UPDATE ranks SET name='RECRUTA' WHERE guild_id=? AND discord_role_id=?",
        (GUILD_ID, RANK_ROLE),
    )
    await service_bundle["database"].execute(
        """
        INSERT INTO ranks(guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at)
        VALUES (?, 'SOLDADO', 'SD', 20, 8003, 'MEMBRO', ?)
        """,
        (GUILD_ID, service_bundle["clock"]()),
    )
    profile = await service_bundle["operations"].recruit_profile(GUILD_ID, DISCORD_ID)
    assert profile["member"]["id"] == member_id
    evaluation_id = await service_bundle["operations"].add_recruit_evaluation(
        GUILD_ID, DISCORD_ID, 900, "POSITIVE", "Boa evolução"
    )
    assert evaluation_id > 0
    promotion = await service_bundle["operations"].promotion_eligibility(
        GUILD_ID, DISCORD_ID
    )
    assert promotion["next_rank"]["name"] == "SOLDADO"
    assert promotion["automatic_promotion"] is False
    current = await service_bundle["database"].fetchone(
        "SELECT rank_id FROM members WHERE id=?", (member_id,)
    )
    assert current["rank_id"] == profile["member"]["rank_id"]
    dossier = await service_bundle["operations"].dossier(GUILD_ID, DISCORD_ID)
    assert dossier["member"]["discord_id"] == DISCORD_ID
    assert len(dossier["recruit_evaluations"]) == 1


@pytest.mark.asyncio
async def test_activity_swap_requires_consent_then_command_decision(service_bundle):
    await prepare_ranked_member(service_bundle, DISCORD_ID)
    await prepare_ranked_member(service_bundle, 457)
    operations = service_bundle["operations"]
    swap_id = await operations.create_activity_swap(
        GUILD_ID, DISCORD_ID, 457, "Patrulha Alfa", "Conflito de horário"
    )
    with pytest.raises(ValidationError, match="convidado"):
        await operations.respond_activity_swap(GUILD_ID, swap_id, DISCORD_ID, True)
    assert await operations.respond_activity_swap(GUILD_ID, swap_id, 457, True) == "WAITING_COMMAND"
    assert await operations.decide_activity_swap(
        GUILD_ID, swap_id, 900, True, "Ambos confirmaram disponibilidade"
    ) == "APPROVED"
    row = await service_bundle["database"].fetchone(
        "SELECT * FROM activity_swap_requests WHERE id=?", (swap_id,)
    )
    assert row["status"] == "APPROVED"
    assert row["member_decided_at"] is not None
    assert row["command_decided_at"] is not None


@pytest.mark.asyncio
async def test_intelligent_flags_are_nonpunitive_and_feed_admin_inbox(service_bundle):
    member_id = await prepare_ranked_member(service_bundle, DISCORD_ID)
    await service_bundle["settings"].set(
        GUILD_ID, "invalid_shift_flag_threshold", 1, DISCORD_ID
    )
    await service_bundle["database"].execute(
        """
        INSERT INTO shifts(
            guild_id, member_id, status, started_at, ended_at, closed_at,
            end_reason, created_by, created_at, validation_status,
            automatic_validation_status, invalid_reason
        ) VALUES (?, ?, 'CLOSED', ?, ?, ?, 'MEMBER_STOPPED', ?, ?,
                  'INVALIDATED', 'INVALIDATED', 'Tempo mínimo não atingido')
        """,
        (
            GUILD_ID,
            member_id,
            service_bundle["clock"]() - 60_000,
            service_bundle["clock"](),
            service_bundle["clock"](),
            DISCORD_ID,
            service_bundle["clock"]() - 60_000,
        ),
    )
    created = await service_bundle["operations"].scan_shift_flags(GUILD_ID)
    assert created
    member = await service_bundle["database"].fetchone(
        "SELECT status FROM members WHERE id=?", (member_id,)
    )
    assert member["status"] == "ACTIVE"
    inbox = await service_bundle["operations"].administrative_inbox(GUILD_ID)
    assert "OPERATIONAL_FLAG" in {item["type"] for item in inbox}


@pytest.mark.asyncio
async def test_phase_fifteen_public_views_are_persistent_and_stable():
    views = [PatrolCentralView(), PatrolReportView(), MemberOperationsView()]
    for view in views:
        assert view.timeout is None
        custom_ids = [item.custom_id for item in view.children if item.custom_id]
        assert custom_ids
        assert len(custom_ids) == len(set(custom_ids))
        assert all(value.startswith("choque:operations:") for value in custom_ids)


@pytest.mark.asyncio
async def test_commander_management_is_available_only_to_command_profile():
    assert "patrol.commander.override" in PROFILE_PERMISSIONS["COMANDO"]
    assert "patrol.commander.override" not in PROFILE_PERMISSIONS["MEMBRO"]
    view = PatrolManagementView()
    assert {item.label for item in view.children} == {
        "Encerrar patrulha",
        "Alterar comandante",
        "Regra de comando",
        "Prioridade",
        "Histórico",
    }
