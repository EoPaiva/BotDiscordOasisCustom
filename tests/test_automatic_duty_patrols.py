from __future__ import annotations

import asyncio

import pytest

from choque.errors import ConflictError, ValidationError

from .conftest import DISCORD_ID, GUILD_ID

ACTIVE_A = 7_001
ACTIVE_B = 7_002
RANK_SOLDIER = 77_001
RANK_SERGEANT = 77_002


async def ranked_member(
    bundle,
    discord_id: int,
    *,
    level: int,
    role_id: int,
    rank_name: str,
) -> int:
    database = bundle["database"]
    rank = await database.fetchone(
        "SELECT id FROM ranks WHERE guild_id=? AND discord_role_id=?",
        (GUILD_ID, role_id),
    )
    rank_id = int(rank["id"]) if rank else await database.execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
        ) VALUES (?, ?, ?, ?, ?, 'MEMBRO', ?)
        """,
        (GUILD_ID, rank_name, rank_name[:3], level, role_id, bundle["clock"]()),
    )
    member = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, discord_id),
    )
    if not member:
        await bundle["members"].create_or_update(
            GUILD_ID,
            discord_id,
            discord_nick=f"Discord {discord_id}",
            mta_nick=f"Militar_{discord_id}",
            character_id=str(discord_id),
            unit="CHOQUE",
            rank_id=rank_id,
            actor_id=DISCORD_ID,
        )
        member = await database.fetchone(
            "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
            (GUILD_ID, discord_id),
        )
    await database.execute(
        """
        UPDATE members SET rank_id=?, status='ACTIVE', rank_sync_status='SYNCED'
        WHERE id=?
        """,
        (rank_id, member["id"]),
    )
    return int(member["id"])


async def prepare(bundle) -> None:
    await ranked_member(
        bundle,
        DISCORD_ID,
        level=10,
        role_id=RANK_SOLDIER,
        rank_name="SOLDADO",
    )
    await bundle["settings"].add_voice_channel(
        GUILD_ID, ACTIVE_A, "Patrulha Alfa", DISCORD_ID
    )
    await bundle["settings"].add_voice_channel(
        GUILD_ID, ACTIVE_B, "Patrulha Bravo", DISCORD_ID
    )
    await bundle["settings"].set_voice_patrol_classification(GUILD_ID, ACTIVE_A, True)
    await bundle["settings"].set_voice_patrol_classification(GUILD_ID, ACTIVE_B, True)
    await bundle["operations"].configure_patrol_channel(
        GUILD_ID,
        ACTIVE_A,
        "ACTIVE",
        "Patrulha Alfa",
        1,
        DISCORD_ID,
        logical_key="patrol.alfa",
    )
    await bundle["operations"].configure_patrol_channel(
        GUILD_ID,
        ACTIVE_B,
        "ACTIVE",
        "Patrulha Bravo",
        2,
        DISCORD_ID,
        logical_key="patrol.bravo",
    )


@pytest.mark.asyncio
async def test_voice_entry_opens_one_shift_and_one_durable_vehicle(service_bundle) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]

    first = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_snapshot="SOLDADO",
        role_ids=[RANK_SOLDIER],
    )
    repeated = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        ACTIVE_A,
        ACTIVE_A,
        has_authorized_role=True,
        role_snapshot="SOLDADO",
        role_ids=[RANK_SOLDIER],
    )

    assert first["opened"] is True
    assert first["vehicle"]["created"] is True
    assert repeated["opened"] is False
    assert repeated["vehicle"]["joined"] is False
    shift = await service_bundle["database"].fetchone("SELECT * FROM shifts")
    assert shift["start_source"] == "VOICE_AUTO"
    assert shift["initial_voice_channel_id"] == ACTIVE_A
    assert shift["current_patrol_id"] == first["vehicle"]["patrol_id"]
    assert len(await service_bundle["database"].fetchall("SELECT id FROM shifts")) == 1
    assert len(await service_bundle["database"].fetchall("SELECT id FROM patrols")) == 1
    assert len(
        await service_bundle["database"].fetchall(
            "SELECT id FROM patrol_members WHERE status='ACTIVE'"
        )
    ) == 1
    timeline = await duty.composition_timeline(
        GUILD_ID, int(first["vehicle"]["patrol_id"])
    )
    assert [row["event_type"] for row in timeline].count("MEMBER_JOINED") == 1


@pytest.mark.asyncio
async def test_two_members_share_vehicle_and_higher_rank_takes_command(service_bundle) -> None:
    await prepare(service_bundle)
    await ranked_member(
        service_bundle,
        457,
        level=30,
        role_id=RANK_SERGEANT,
        rank_name="SARGENTO",
    )
    duty = service_bundle["duty_patrols"]
    first = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    second = await duty.handle_voice_transition(
        GUILD_ID,
        457,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SERGEANT],
    )

    assert second["vehicle"]["patrol_id"] == first["vehicle"]["patrol_id"]
    patrol = await service_bundle["database"].fetchone(
        "SELECT * FROM patrols WHERE id=?", (first["vehicle"]["patrol_id"],)
    )
    commander = await service_bundle["database"].fetchone(
        "SELECT discord_id FROM members WHERE id=?", (patrol["commander_member_id"],)
    )
    assert commander["discord_id"] == 457
    assert len(await service_bundle["operations"].active_patrol_members(GUILD_ID, patrol["id"])) == 2


@pytest.mark.asyncio
async def test_patrol_move_keeps_shift_and_moves_vehicle_without_duplicate_time(
    service_bundle,
) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]
    entered = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    service_bundle["clock"].advance(5_000)
    moved = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        ACTIVE_A,
        ACTIVE_B,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )

    assert moved["shift_id"] == entered["shift_id"]
    assert moved["vehicle"]["patrol_id"] != entered["vehicle"]["patrol_id"]
    shifts = await service_bundle["database"].fetchall("SELECT * FROM shifts")
    segments = await service_bundle["database"].fetchall(
        "SELECT * FROM shift_segments ORDER BY id"
    )
    assert len(shifts) == 1
    assert len(segments) == 2
    assert segments[0]["ended_at"] == segments[1]["started_at"]
    old = await service_bundle["database"].fetchone(
        "SELECT status FROM patrols WHERE id=?", (entered["vehicle"]["patrol_id"],)
    )
    assert old["status"] == "CLOSED"
    movement = await service_bundle["database"].fetchone(
        """
        SELECT * FROM patrol_composition_events
        WHERE patrol_id=? AND event_type='MEMBER_MOVED'
        """,
        (entered["vehicle"]["patrol_id"],),
    )
    assert movement["before_channel_id"] == ACTIVE_A
    assert movement["after_channel_id"] == ACTIVE_B


@pytest.mark.asyncio
async def test_voice_exit_closes_vehicle_and_creates_frozen_report(service_bundle) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]
    entered = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    service_bundle["clock"].advance(10 * 60_000)
    left = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        ACTIVE_A,
        None,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )

    assert left["shift_status"] == "GRACE"
    patrol = await service_bundle["database"].fetchone(
        "SELECT * FROM patrols WHERE id=?", (entered["vehicle"]["patrol_id"],)
    )
    assert patrol["status"] == "CLOSED"
    report = await service_bundle["database"].fetchone(
        "SELECT * FROM patrol_reports WHERE patrol_id=?", (patrol["id"],)
    )
    assert report["status"] == "DRAFT"
    assert report["duration_ms"] == 10 * 60_000
    members = await service_bundle["database"].fetchall(
        "SELECT * FROM patrol_report_members WHERE report_id=?", (report["id"],)
    )
    assert [row["discord_id"] for row in members] == [DISCORD_ID]


@pytest.mark.asyncio
async def test_restart_reconciliation_is_idempotent_and_repairs_missing_vehicle(
    service_bundle,
) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]
    snapshot = {
        ACTIVE_A: [
            {
                "discord_id": DISCORD_ID,
                "role_snapshot": "SOLDADO",
                "role_ids": [RANK_SOLDIER],
                "authorized": True,
            }
        ],
        ACTIVE_B: [],
    }

    first = await duty.reconcile_voice_state(GUILD_ID, snapshot)
    second = await duty.reconcile_voice_state(GUILD_ID, snapshot)

    assert first == {"opened": 1, "joined": 1, "removed": 0, "closed": 0}
    assert second == {"opened": 0, "joined": 0, "removed": 0, "closed": 0}
    assert len(await service_bundle["database"].fetchall("SELECT id FROM shifts")) == 1
    assert len(await service_bundle["database"].fetchall("SELECT id FROM patrols")) == 1


@pytest.mark.asyncio
async def test_restart_reconciliation_resumes_grace_shift_without_duplicate_time(
    service_bundle,
) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]
    entered = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    service_bundle["clock"].advance(10_000)
    await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        ACTIVE_A,
        None,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    service_bundle["clock"].advance(5_000)

    result = await duty.reconcile_voice_state(
        GUILD_ID,
        {
            ACTIVE_A: [
                {
                    "discord_id": DISCORD_ID,
                    "role_snapshot": "SOLDADO",
                    "role_ids": [RANK_SOLDIER],
                    "authorized": True,
                }
            ]
        },
    )

    shift = await service_bundle["shifts"].get_active(GUILD_ID, DISCORD_ID)
    assert result["opened"] == 0
    assert shift["id"] == entered["shift_id"]
    assert shift["status"] == "ACTIVE"
    segments = await service_bundle["database"].fetchall(
        "SELECT * FROM shift_segments WHERE shift_id=? ORDER BY id", (shift["id"],)
    )
    assert len(segments) == 2
    assert segments[0]["ended_at"] < segments[1]["started_at"]


@pytest.mark.asyncio
async def test_restart_after_expired_grace_closes_old_and_opens_new_shift(
    service_bundle,
) -> None:
    await prepare(service_bundle)
    await service_bundle["settings"].set(GUILD_ID, "grace_period_seconds", 5, DISCORD_ID)
    duty = service_bundle["duty_patrols"]
    first = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        ACTIVE_A,
        None,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    service_bundle["clock"].advance(6_000)

    result = await duty.reconcile_voice_state(
        GUILD_ID,
        {
            ACTIVE_A: [
                {
                    "discord_id": DISCORD_ID,
                    "role_snapshot": "SOLDADO",
                    "role_ids": [RANK_SOLDIER],
                    "authorized": True,
                }
            ]
        },
    )

    shifts = await service_bundle["database"].fetchall(
        "SELECT * FROM shifts ORDER BY id"
    )
    assert result["opened"] == 1
    assert len(shifts) == 2
    assert shifts[0]["id"] == first["shift_id"]
    assert shifts[0]["status"] == "CLOSED"
    assert shifts[1]["status"] == "ACTIVE"
    assert shifts[1]["start_source"] == "RECOVERY"


@pytest.mark.asyncio
async def test_report_occurrence_evidence_and_finalization_are_audited(service_bundle) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]
    entered = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    service_bundle["clock"].advance(15 * 60_000)
    await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        ACTIVE_A,
        None,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    report = await service_bundle["database"].fetchone(
        "SELECT * FROM patrol_reports WHERE patrol_id=?",
        (entered["vehicle"]["patrol_id"],),
    )
    occurrence_id = await duty.add_occurrence(
        GUILD_ID,
        int(report["id"]),
        DISCORD_ID,
        DISCORD_ID,
        category_code="ABANDONO_PTR",
        reason="Saída antecipada",
        description="O militar deixou a call antes do encerramento operacional.",
    )
    evidence_id = await duty.add_evidence(
        GUILD_ID,
        int(report["id"]),
        DISCORD_ID,
        evidence_type="IMAGE",
        locator="https://cdn.discordapp.com/attachments/evidencia.png",
        occurrence_id=occurrence_id,
    )
    finalized = await duty.finalize_report(
        GUILD_ID,
        int(report["id"]),
        DISCORD_ID,
        description="Patrulhamento preventivo concluído.",
        expected_version=int(report["version"]),
    )

    assert evidence_id > 0
    assert finalized["status"] == "FINALIZED"
    with pytest.raises(ConflictError, match="não está aberto"):
        await duty.add_occurrence(
            GUILD_ID,
            int(report["id"]),
            DISCORD_ID,
            DISCORD_ID,
            category_code="OUTRA",
            reason="Tardio",
            description="Não pode alterar relatório finalizado.",
        )
    actions = {
        row["action"]
        for row in await service_bundle["database"].fetchall(
            "SELECT action FROM audit_logs"
        )
    }
    assert {
        "PATROL_REPORT_DRAFT_CREATED",
        "PATROL_REPORT_OCCURRENCE_CREATED",
        "PATROL_REPORT_EVIDENCE_CREATED",
        "PATROL_REPORT_FINALIZED",
    } <= actions


@pytest.mark.asyncio
async def test_channel_capacity_and_persistent_evidence_validation(service_bundle) -> None:
    await prepare(service_bundle)
    await ranked_member(
        service_bundle,
        457,
        level=30,
        role_id=RANK_SERGEANT,
        rank_name="SARGENTO",
    )
    await service_bundle["operations"].configure_patrol_channel(
        GUILD_ID,
        ACTIVE_A,
        "ACTIVE",
        "Patrulha Alfa",
        1,
        DISCORD_ID,
        logical_key="patrol.alfa",
        capacity=1,
    )
    duty = service_bundle["duty_patrols"]
    await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    with pytest.raises(ConflictError, match="capacidade"):
        await duty.handle_voice_transition(
            GUILD_ID,
            457,
            None,
            ACTIVE_A,
            has_authorized_role=True,
            role_ids=[RANK_SERGEANT],
        )
    assert await service_bundle["shifts"].get_active(GUILD_ID, 457) is not None
    with pytest.raises(ValidationError, match="HTTP"):
        await duty.add_evidence(
            GUILD_ID,
            999,
            DISCORD_ID,
            evidence_type="FILE",
            locator="arquivo-local.png",
        )


@pytest.mark.asyncio
async def test_global_automatic_clock_switch_blocks_new_voice_shift(service_bundle) -> None:
    await prepare(service_bundle)
    await service_bundle["settings"].set(
        GUILD_ID,
        "automatic_patrol_clock_enabled",
        False,
        DISCORD_ID,
    )

    result = await service_bundle["duty_patrols"].handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )

    assert result["opened"] is False
    assert result["vehicle"] is None
    assert await service_bundle["shifts"].get_active(GUILD_ID, DISCORD_ID) is None

    recovered = await service_bundle["duty_patrols"].reconcile_voice_state(
        GUILD_ID,
        {
            ACTIVE_A: [
                {
                    "discord_id": DISCORD_ID,
                    "role_snapshot": "SOLDADO",
                    "role_ids": [RANK_SOLDIER],
                    "authorized": True,
                }
            ]
        },
    )
    assert recovered == {"opened": 0, "joined": 0, "removed": 0, "closed": 0}
    assert await service_bundle["shifts"].get_active(GUILD_ID, DISCORD_ID) is None


@pytest.mark.asyncio
async def test_evidence_limit_is_enforced_per_report(service_bundle) -> None:
    await prepare(service_bundle)
    await service_bundle["settings"].set(
        GUILD_ID,
        "patrol_report_max_evidence",
        1,
        DISCORD_ID,
    )
    duty = service_bundle["duty_patrols"]
    entered = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        ACTIVE_A,
        None,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    report = await service_bundle["database"].fetchone(
        "SELECT id FROM patrol_reports WHERE patrol_id=?",
        (entered["vehicle"]["patrol_id"],),
    )
    await duty.add_evidence(
        GUILD_ID,
        int(report["id"]),
        DISCORD_ID,
        evidence_type="LINK",
        locator="https://example.com/evidence/1",
    )

    with pytest.raises(ConflictError, match="limite"):
        await duty.add_evidence(
            GUILD_ID,
            int(report["id"]),
            DISCORD_ID,
            evidence_type="LINK",
            locator="https://example.com/evidence/2",
        )


@pytest.mark.asyncio
async def test_commander_leaving_promotes_next_eligible_member(service_bundle) -> None:
    await prepare(service_bundle)
    await ranked_member(
        service_bundle,
        457,
        level=30,
        role_id=RANK_SERGEANT,
        rank_name="SARGENTO",
    )
    duty = service_bundle["duty_patrols"]
    await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    entered = await duty.handle_voice_transition(
        GUILD_ID,
        457,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SERGEANT],
    )

    await duty.handle_voice_transition(
        GUILD_ID,
        457,
        ACTIVE_A,
        None,
        has_authorized_role=True,
        role_ids=[RANK_SERGEANT],
    )

    patrol = await service_bundle["database"].fetchone(
        "SELECT commander_member_id FROM patrols WHERE id=?",
        (entered["vehicle"]["patrol_id"],),
    )
    commander = await service_bundle["database"].fetchone(
        "SELECT discord_id FROM members WHERE id=?", (patrol["commander_member_id"],)
    )
    assert commander["discord_id"] == DISCORD_ID


@pytest.mark.asyncio
async def test_duplicate_concurrent_voice_events_are_idempotent(service_bundle) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]

    await asyncio.gather(
        *(
            duty.handle_voice_transition(
                GUILD_ID,
                DISCORD_ID,
                None,
                ACTIVE_A,
                has_authorized_role=True,
                role_ids=[RANK_SOLDIER],
            )
            for _ in range(5)
        )
    )

    assert len(await service_bundle["database"].fetchall("SELECT id FROM shifts")) == 1
    assert len(await service_bundle["database"].fetchall("SELECT id FROM patrols")) == 1
    assert len(
        await service_bundle["database"].fetchall(
            "SELECT id FROM patrol_members WHERE status='ACTIVE'"
        )
    ) == 1


@pytest.mark.asyncio
async def test_admin_can_repair_vehicle_membership_with_full_audit(service_bundle) -> None:
    await prepare(service_bundle)
    target_id = 457
    await ranked_member(
        service_bundle,
        target_id,
        level=30,
        role_id=RANK_SERGEANT,
        rank_name="SARGENTO",
    )
    duty = service_bundle["duty_patrols"]
    entered = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    await service_bundle["shifts"].start_shift(
        GUILD_ID,
        target_id,
        ACTIVE_A,
        has_authorized_role=True,
        source="ADMIN",
    )

    assigned = await duty.admin_assign_member(
        GUILD_ID,
        int(entered["vehicle"]["patrol_id"]),
        target_id,
        DISCORD_ID,
        reason="Reparar evento de voz perdido",
        present_discord_ids=[DISCORD_ID, target_id],
    )
    removed = await duty.admin_remove_member(
        GUILD_ID,
        int(entered["vehicle"]["patrol_id"]),
        target_id,
        DISCORD_ID,
        reason="Reparar saída não processada",
        present_discord_ids=[DISCORD_ID],
    )

    assert assigned["action"] == "MEMBER_ASSIGNED"
    assert removed["action"] == "MEMBER_REMOVED"
    membership = await service_bundle["database"].fetchone(
        "SELECT status FROM patrol_members WHERE patrol_id=? AND discord_id=?",
        (entered["vehicle"]["patrol_id"], target_id),
    )
    assert membership["status"] == "LEFT"
    adjustments = await service_bundle["database"].fetchall(
        "SELECT action_type, before_json, after_json, reason FROM patrol_admin_adjustments "
        "ORDER BY id"
    )
    assert [row["action_type"] for row in adjustments] == [
        "MEMBER_ASSIGNED",
        "MEMBER_REMOVED",
    ]
    assert all(row["before_json"] != row["after_json"] for row in adjustments)
    assert all(row["reason"] for row in adjustments)


@pytest.mark.asyncio
async def test_occurrence_categories_and_articles_are_admin_configurable(service_bundle) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]

    category_id = await duty.configure_occurrence_category(
        GUILD_ID,
        DISCORD_ID,
        code="APOIO_EXTERNO",
        title="Apoio operacional externo",
        description="Ocorrência relacionada a apoio prestado fora da unidade.",
    )
    article_id = await duty.configure_article(
        GUILD_ID,
        DISCORD_ID,
        code="ART-APOIO",
        title="Procedimento de apoio",
        description="Enquadramento operacional configurável.",
        severity="NORMAL",
        category_code="APOIO_EXTERNO",
    )
    await duty.configure_occurrence_category(
        GUILD_ID,
        DISCORD_ID,
        code="APOIO_EXTERNO",
        title="Apoio operacional externo",
        description="Categoria desativada sem exclusão histórica.",
        active=False,
    )

    assert category_id > 0
    assert article_id > 0
    category = await service_bundle["database"].fetchone(
        "SELECT active, description FROM patrol_occurrence_categories WHERE id=?",
        (category_id,),
    )
    assert category["active"] == 0
    assert "desativada" in category["description"]
    actions = {
        row["action"]
        for row in await service_bundle["database"].fetchall(
            "SELECT action FROM audit_logs"
        )
    }
    assert "PATROL_OCCURRENCE_CATEGORY_CONFIGURED" in actions
    assert "PATROL_ARTICLE_CONFIGURED" in actions


@pytest.mark.asyncio
async def test_admin_shift_exceptions_open_close_adjust_and_invalidate(service_bundle) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]

    opened = await duty.admin_open_shift(
        GUILD_ID,
        DISCORD_ID,
        DISCORD_ID,
        reason="Recuperar entrada não recebida pelo Discord",
        voice_channel_id=ACTIVE_A,
        target_has_authorized_role=True,
        role_snapshot="SOLDADO",
        role_ids=[RANK_SOLDIER],
    )
    await duty.admin_correct_shift(
        GUILD_ID,
        int(opened["shift_id"]),
        DISCORD_ID,
        minutes=5,
        reason="Corrigir cinco minutos comprovados",
    )
    closed = await duty.admin_close_shift(
        GUILD_ID,
        DISCORD_ID,
        DISCORD_ID,
        reason="Encerramento excepcional confirmado",
        invalidate=True,
    )

    assert opened["action"] == "SHIFT_OPENED"
    assert closed["action"] == "SHIFT_INVALIDATED"
    shift = await service_bundle["database"].fetchone(
        "SELECT * FROM shifts WHERE id=?", (opened["shift_id"],)
    )
    assert shift["status"] == "CLOSED"
    assert shift["validation_status"] == "INVALIDATED"
    assert shift["start_source"] == "ADMIN"
    adjustments = await service_bundle["database"].fetchall(
        "SELECT action_type FROM patrol_admin_adjustments ORDER BY id"
    )
    assert [row["action_type"] for row in adjustments] == [
        "SHIFT_OPENED",
        "SHIFT_CORRECTED",
        "SHIFT_INVALIDATED",
    ]


@pytest.mark.asyncio
async def test_admin_open_shift_keeps_audited_unassigned_shift_when_vehicle_rejects(
    service_bundle, monkeypatch
) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]

    async def reject_vehicle(*args, **kwargs):
        raise ConflictError("A call atingiu a capacidade configurada.")

    monkeypatch.setattr(duty, "ensure_voice_vehicle", reject_vehicle)
    opened = await duty.admin_open_shift(
        GUILD_ID,
        DISCORD_ID,
        DISCORD_ID,
        reason="Recuperar ponto apesar da call lotada",
        voice_channel_id=ACTIVE_A,
        target_has_authorized_role=True,
        role_snapshot="SOLDADO",
        role_ids=[RANK_SOLDIER],
    )

    assert opened["action"] == "SHIFT_OPENED"
    assert opened["vehicle"] is None
    assert opened["vehicle_error"] == "A call atingiu a capacidade configurada."
    shift = await service_bundle["database"].fetchone(
        "SELECT status, current_patrol_id FROM shifts WHERE id=?", (opened["shift_id"],)
    )
    assert shift["status"] == "ACTIVE"
    assert shift["current_patrol_id"] is None
    adjustment = await service_bundle["database"].fetchone(
        "SELECT action_type, after_json FROM patrol_admin_adjustments ORDER BY id DESC LIMIT 1"
    )
    assert adjustment["action_type"] == "SHIFT_OPENED"
    assert "call atingiu a capacidade" in adjustment["after_json"]


@pytest.mark.asyncio
async def test_admin_commander_override_records_before_and_after(service_bundle) -> None:
    await prepare(service_bundle)
    await ranked_member(
        service_bundle,
        457,
        level=30,
        role_id=RANK_SERGEANT,
        rank_name="SARGENTO",
    )
    duty = service_bundle["duty_patrols"]
    first = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )
    await duty.handle_voice_transition(
        GUILD_ID,
        457,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SERGEANT],
    )

    result = await duty.admin_override_commander(
        GUILD_ID,
        int(first["vehicle"]["patrol_id"]),
        DISCORD_ID,
        DISCORD_ID,
        reason="Decisão excepcional do comando",
        present_discord_ids=[DISCORD_ID, 457],
    )

    assert result["commander_discord_id"] == DISCORD_ID
    adjustment = await service_bundle["database"].fetchone(
        "SELECT * FROM patrol_admin_adjustments WHERE action_type='COMMANDER_OVERRIDDEN'"
    )
    assert adjustment is not None
    assert "457" in adjustment["before_json"]
    assert str(DISCORD_ID) in adjustment["after_json"]


@pytest.mark.asyncio
async def test_role_loss_closes_shift_and_vehicle_immediately(service_bundle) -> None:
    await prepare(service_bundle)
    duty = service_bundle["duty_patrols"]
    entered = await duty.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        None,
        ACTIVE_A,
        has_authorized_role=True,
        role_ids=[RANK_SOLDIER],
    )

    result = await duty.handle_role_loss(GUILD_ID, DISCORD_ID)

    assert result["closed"] is True
    assert await service_bundle["shifts"].get_active(GUILD_ID, DISCORD_ID) is None
    patrol = await service_bundle["database"].fetchone(
        "SELECT status FROM patrols WHERE id=?", (entered["vehicle"]["patrol_id"],)
    )
    assert patrol["status"] == "CLOSED"
    report = await service_bundle["database"].fetchone(
        "SELECT id FROM patrol_reports WHERE patrol_id=?",
        (entered["vehicle"]["patrol_id"],),
    )
    assert report is not None
