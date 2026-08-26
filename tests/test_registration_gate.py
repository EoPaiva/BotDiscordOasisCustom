from __future__ import annotations

import asyncio
import json

import pytest

from choque.errors import ConflictError
from choque.models import MemberStatus
from choque.registration_gate import RANK_COMPLIANCE_WINDOW_MS

from .conftest import DISCORD_ID, GUILD_ID
from .test_identity_sync import FakeGuild, FakeMember, FakeRole


async def open_managed_rank_registration(
    service_bundle, discord_id: int, role_id: int
) -> None:
    database = service_bundle["database"]
    await database.execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
        ) VALUES (?, ?, '[REC]', 1, ?, 'RECRUTA', 1)
        """,
        (GUILD_ID, f"Recruta teste {discord_id}", role_id),
    )
    _, created = await service_bundle[
        "registration_gate"
    ].ensure_rank_registration_compliance(GUILD_ID, discord_id, role_id)
    assert created is True


@pytest.mark.asyncio
async def test_registration_gate_reconciles_active_member(service_bundle):
    gate = service_bundle["registration_gate"]
    record = await gate.reconcile_identity(GUILD_ID, DISCORD_ID, source="REJOIN")
    assert record["status"] == "REGISTERED"
    assert record["access_tier"] == "MEMBER"
    assert record["member_id"] is not None
    assert record["sync_status"] == "PENDING"


@pytest.mark.asyncio
async def test_registration_sync_grant_is_idempotent_after_gateway_retries(service_bundle):
    gate = service_bundle["registration_gate"]
    database = service_bundle["database"]
    record = await gate.reconcile_identity(GUILD_ID, DISCORD_ID, source="REJOIN")

    first, second = await asyncio.gather(
        gate.mark_sync(int(record["id"]), success=True),
        gate.mark_sync(int(record["id"]), success=True),
    )

    grants = await database.fetchone(
        """
        SELECT COUNT(*) AS total FROM audit_logs
        WHERE action='REGISTRATION_ACCESS_GRANTED' AND target_id=?
        """,
        (DISCORD_ID,),
    )
    assert sorted((first, second)) == [False, True]
    assert int(grants["total"]) == 1


@pytest.mark.asyncio
async def test_legacy_active_member_requires_human_review_before_confirmation(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    reconciled = await gate.reconcile_identity(
        GUILD_ID, DISCORD_ID, source="SYSTEM_RECONCILIATION"
    )
    assert reconciled["status"] == "REGISTERED"
    assert reconciled["reviewed_at"] is None

    intent = await gate.registration_intent(GUILD_ID, DISCORD_ID)
    assert (intent["mode"], intent["kind"]) == ("FORM", "MEMBER_REVIEW")
    pending = await gate.request_existing_member_review(GUILD_ID, DISCORD_ID)

    assert pending["status"] == "REQUIRES_REVIEW"
    assert pending["member_id"] == reconciled["member_id"]
    assert pending["conflict_member_id"] == reconciled["member_id"]
    assert pending["conflict_code"] == "LEGACY_MEMBER_REVIEW_REQUIRED"
    assert pending["sync_status"] == "NOT_REQUIRED"
    assert pending["delivery_status"] == "PENDING"
    assert pending["reviewed_at"] is None
    notifications = await gate.pending_review_notifications(GUILD_ID)
    assert [int(row["id"]) for row in notifications] == [int(pending["id"])]

    repeated = await gate.request_existing_member_review(GUILD_ID, DISCORD_ID)
    assert repeated["id"] == pending["id"]
    events = await database.fetchone(
        """
        SELECT COUNT(*) AS total FROM registration_gate_events
        WHERE registration_id=? AND event_type='REGISTRATION_REVIEW_REQUIRED'
        """,
        (pending["id"],),
    )
    assert int(events["total"]) == 1


@pytest.mark.asyncio
async def test_human_review_confirms_existing_member_without_duplicate(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    pending = await gate.request_existing_member_review(GUILD_ID, DISCORD_ID)

    approved = await gate.link_existing_member(
        int(pending["id"]),
        member_id=int(pending["member_id"]),
        reviewer_id=DISCORD_ID + 1,
        reason="Perfil legado conferido pelo Comando",
    )

    assert approved["status"] == "REGISTERED"
    assert approved["reviewed_at"] is not None
    assert approved["reviewed_by"] == DISCORD_ID + 1
    intent = await gate.registration_intent(GUILD_ID, DISCORD_ID)
    assert (intent["mode"], intent["kind"]) == ("STATUS", "REGISTERED")
    total = await database.fetchone(
        "SELECT COUNT(*) AS total FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert int(total["total"]) == 1


@pytest.mark.asyncio
async def test_registration_can_be_reopened_without_deleting_member_or_history(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    pending = await gate.request_existing_member_review(GUILD_ID, DISCORD_ID)
    approved = await gate.link_existing_member(
        int(pending["id"]),
        member_id=int(pending["member_id"]),
        reviewer_id=DISCORD_ID + 1,
        reason="Perfil conferido",
    )

    reopened = await gate.reopen_for_review(
        int(approved["id"]),
        actor_id=DISCORD_ID + 1,
        reason="Simulação autorizada do fluxo de cadastro",
    )

    assert reopened["status"] == "UNREGISTERED"
    assert reopened["member_id"] == approved["member_id"]
    assert reopened["reviewed_at"] is None
    assert reopened["sync_status"] == "NOT_REQUIRED"
    intent = await gate.registration_intent(GUILD_ID, DISCORD_ID)
    assert (intent["mode"], intent["kind"]) == ("FORM", "MEMBER_REVIEW")
    members = await database.fetchone(
        "SELECT COUNT(*) AS total FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert int(members["total"]) == 1
    audit = await database.fetchone(
        """
        SELECT COUNT(*) AS total FROM audit_logs
        WHERE guild_id=? AND action='REGISTRATION_REOPENED_FOR_REVIEW'
        """,
        (GUILD_ID,),
    )
    assert int(audit["total"]) == 1


@pytest.mark.asyncio
async def test_high_command_directory_searches_and_paginates_all_registrations(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    for index in range(27):
        await gate.submit(
            GUILD_ID,
            20_000 + index,
            mta_nick=f"Candidato {index:02d}",
            bgr_id=f"BGR-{index:02d}",
        )

    first = await gate.directory(GUILD_ID)
    second = await gate.directory(GUILD_ID, page=1)
    found = await gate.directory(GUILD_ID, query="Candidato 26")

    assert first["total"] == 27
    assert first["pages"] == 2
    assert len(first["rows"]) == 25
    assert len(second["rows"]) == 2
    assert [row["discord_id"] for row in found["rows"]] == [20_026]


@pytest.mark.asyncio
async def test_high_command_directory_edits_linked_identity_atomically(service_bundle):
    gate = service_bundle["registration_gate"]
    database = service_bundle["database"]
    record = await gate.reconcile_identity(GUILD_ID, DISCORD_ID, source="REJOIN")

    updated = await gate.update_directory_identity(
        int(record["id"]),
        actor_id=DISCORD_ID + 1,
        mta_nick="Identidade Corrigida",
        bgr_id="BGR-7700",
        unit="CHOQUE",
        reason="Correção conferida pelo Alto Comando",
    )

    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert (updated["mta_nick"], updated["bgr_id"]) == (
        "Identidade Corrigida",
        "BGR-7700",
    )
    assert (member["mta_nick"], member["character_id"], member["unit"]) == (
        "Identidade Corrigida",
        "BGR-7700",
        "CHOQUE",
    )
    audit = await database.fetchone(
        """
        SELECT COUNT(*) AS total FROM audit_logs
        WHERE guild_id=? AND action='REGISTRATION_DIRECTORY_IDENTITY_EDITED'
        """,
        (GUILD_ID,),
    )
    assert int(audit["total"]) == 1


@pytest.mark.asyncio
async def test_high_command_directory_deactivation_is_logical_and_recoverable(service_bundle):
    gate = service_bundle["registration_gate"]
    database = service_bundle["database"]
    settings = service_bundle["settings"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    record = await gate.reconcile_identity(GUILD_ID, DISCORD_ID, source="REJOIN")

    blocked = await gate.deactivate_directory_registration(
        int(record["id"]),
        actor_id=DISCORD_ID + 1,
        reason="Cadastro desativado para conferência administrativa",
    )
    assert (blocked["status"], blocked["conflict_code"]) == (
        "BLOCKED",
        "ADMIN_DEACTIVATED",
    )
    intent = await gate.registration_intent(GUILD_ID, DISCORD_ID)
    assert (intent["mode"], intent["kind"]) == ("BLOCKED", "ADMIN_DEACTIVATED")
    with pytest.raises(ConflictError, match="desativado"):
        await gate.submit(
            GUILD_ID,
            DISCORD_ID,
            mta_nick="Tentativa",
            bgr_id="77",
        )

    reopened = await gate.reopen_for_review(
        int(record["id"]),
        actor_id=DISCORD_ID + 1,
        reason="Nova análise autorizada",
    )
    assert reopened["status"] == "UNREGISTERED"
    members = await database.fetchone(
        "SELECT COUNT(*) AS total FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert int(members["total"]) == 1


@pytest.mark.asyncio
async def test_accidental_unlinked_block_with_current_rank_cycle_reopens_registration_form(
    service_bundle,
):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    discord_id = 91_777
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    await open_managed_rank_registration(service_bundle, discord_id, 89_177)
    pending = await gate.submit(
        GUILD_ID,
        discord_id,
        mta_nick="Identidade anterior",
        bgr_id="3270",
    )
    blocked = await gate.deactivate_directory_registration(
        int(pending["id"]),
        actor_id=DISCORD_ID,
        reason="Bloqueio aplicado em teste",
    )
    assert blocked["member_id"] is None
    assert (blocked["status"], blocked["conflict_code"]) == (
        "BLOCKED",
        "ADMIN_DEACTIVATED",
    )

    reopened = await gate.reopen_for_review(
        int(blocked["id"]),
        actor_id=DISCORD_ID,
        reason="bloqueio aplicado por engano",
    )
    intent = await gate.registration_intent(GUILD_ID, discord_id)

    assert reopened["status"] == "UNREGISTERED"
    assert reopened["member_id"] is None
    assert (intent["mode"], intent["kind"]) == ("FORM", "CURRENT_CYCLE")
    resubmitted = await gate.submit(
        GUILD_ID,
        discord_id,
        mta_nick="Sheikh",
        bgr_id="3270",
    )
    assert int(resubmitted["id"]) == int(blocked["id"])
    assert (resubmitted["status"], resubmitted["conflict_code"]) == (
        "PENDING",
        "FUNCTIONAL_ROLE_REVIEW_REQUIRED",
    )
    assert resubmitted["delivery_status"] == "PENDING"
    assert await database.fetchone(
        "SELECT 1 FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, discord_id),
    ) is None
    audit = await database.fetchone(
        """
        SELECT reason FROM audit_logs
        WHERE guild_id=? AND action='REGISTRATION_REOPENED_FOR_REVIEW'
          AND target_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (GUILD_ID, discord_id),
    )
    assert audit["reason"] == "bloqueio aplicado por engano"


@pytest.mark.asyncio
async def test_rank_without_approved_registration_opens_one_persistent_72h_deadline(
    service_bundle,
):
    gate = service_bundle["registration_gate"]
    database = service_bundle["database"]
    role_id = 88_001
    await database.execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
        ) VALUES (?, 'Major', '[MAJ]', 10, ?, 'COMANDO', 1)
        """,
        (GUILD_ID, role_id),
    )
    first, created = await gate.ensure_rank_registration_compliance(
        GUILD_ID, DISCORD_ID, role_id
    )
    second, repeated = await gate.ensure_rank_registration_compliance(
        GUILD_ID, DISCORD_ID, role_id
    )
    assert created is True
    assert repeated is False
    assert first["id"] == second["id"]
    assert first["status"] == "PENDING"
    assert int(first["due_at"]) - int(first["detected_at"]) == RANK_COMPLIANCE_WINDOW_MS
    rows = await gate.rank_compliance_directory(GUILD_ID)
    assert rows["total"] == 1
    assert rows["rows"][0]["rank_name"] == "Major"


@pytest.mark.asyncio
async def test_companion_without_registration_uses_same_72h_compliance(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    companion_role_id = 88_099
    await settings.set(GUILD_ID, "companion_role_id", companion_role_id, DISCORD_ID)

    managed = await gate.managed_rank_role_ids(GUILD_ID)
    pending, created = await gate.ensure_rank_registration_compliance(
        GUILD_ID, DISCORD_ID, companion_role_id
    )

    assert companion_role_id in managed
    assert created is True
    assert pending["status"] == "PENDING"
    rows = await gate.rank_compliance_directory(GUILD_ID)
    assert rows["rows"][0]["rank_name"] == "Companheiro de Farda"


@pytest.mark.asyncio
async def test_rank_registration_compliance_reminders_and_approval_are_recoverable(
    service_bundle,
):
    gate = service_bundle["registration_gate"]
    database = service_bundle["database"]
    role_id = 88_002
    await database.execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
        ) VALUES (?, 'Coronel', '[CEL]', 20, ?, 'COMANDO', 1)
        """,
        (GUILD_ID, role_id),
    )
    pending, _ = await gate.ensure_rank_registration_compliance(
        GUILD_ID, DISCORD_ID, role_id
    )
    notifications = await gate.pending_rank_compliance_notifications(GUILD_ID)
    assert [int(row["id"]) for row in notifications] == [int(pending["id"])]
    await gate.mark_rank_compliance_dm(int(pending["id"]), success=True, message_id=91)
    notified = await database.fetchone(
        "SELECT * FROM rank_registration_compliance WHERE id=?", (pending["id"],)
    )
    assert (notified["dm_status"], notified["dm_message_id"], notified["reminder_count"]) == (
        "SENT",
        91,
        1,
    )
    await gate.reconcile_identity(GUILD_ID, DISCORD_ID, source="REJOIN")
    resolved = await gate.resolve_rank_registration_compliance(GUILD_ID, DISCORD_ID)
    assert resolved == 1
    completed = await database.fetchone(
        "SELECT * FROM rank_registration_compliance WHERE id=?", (pending["id"],)
    )
    assert (completed["status"], completed["completion_reason"]) == (
        "COMPLETED",
        "REGISTRATION_APPROVED",
    )


@pytest.mark.asyncio
async def test_rank_registration_expiration_claim_is_conditional_and_preserves_member(
    service_bundle,
):
    gate = service_bundle["registration_gate"]
    database = service_bundle["database"]
    role_id = 88_003
    await database.execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
        ) VALUES (?, 'Capitão', '[CAP]', 15, ?, 'COMANDO', 1)
        """,
        (GUILD_ID, role_id),
    )
    pending, _ = await gate.ensure_rank_registration_compliance(
        GUILD_ID, DISCORD_ID, role_id
    )
    await database.execute(
        "UPDATE rank_registration_compliance SET due_at=1 WHERE id=?", (pending["id"],)
    )
    claimed = await gate.claim_rank_compliance_expiration(int(pending["id"]))
    duplicate = await gate.claim_rank_compliance_expiration(int(pending["id"]))
    assert claimed is not None
    assert duplicate is None
    await gate.finalize_rank_compliance_expiration(
        int(pending["id"]),
        removed=True,
        reason="Prazo expirado em teste",
    )
    final = await database.fetchone(
        "SELECT * FROM rank_registration_compliance WHERE id=?", (pending["id"],)
    )
    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=?", (GUILD_ID, DISCORD_ID)
    )
    assert final["status"] == "EXPIRED"
    assert member is not None


@pytest.mark.asyncio
async def test_registration_gate_does_not_reactivate_inactive_member(service_bundle):
    gate = service_bundle["registration_gate"]
    members = service_bundle["members"]
    await members.change_status(
        GUILD_ID,
        DISCORD_ID,
        MemberStatus.DISMISSED,
        DISCORD_ID,
        "Teste de ex-membro",
    )
    record = await gate.reconcile_identity(GUILD_ID, DISCORD_ID, source="REJOIN")
    assert record["status"] == "BLOCKED"
    assert record["access_tier"] == "CANDIDATE"


@pytest.mark.asyncio
async def test_registration_gate_new_identity_creates_effective_member(
    service_bundle,
):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    await database.execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id, rbac_profile, created_at
        ) VALUES (?, 'ʀᴇᴄʀᴜᴛᴀ', '[REC]', 1, 90001, 'MEMBRO', 1)
        """,
        (GUILD_ID,),
    )

    first = await gate.submit(
        GUILD_ID,
        9001,
        mta_nick="Visitante",
        bgr_id="9001",
        discord_nick="Discord Visitante",
        idempotency_key="same-submit",
    )
    second = await gate.submit(
        GUILD_ID,
        9001,
        mta_nick="Visitante",
        bgr_id="9001",
        idempotency_key="same-submit",
    )

    assert first["id"] == second["id"]
    assert first["status"] == "REGISTERED"
    assert first["access_tier"] == "RECRUIT"
    assert first["member_id"] is not None
    assert await gate.pending_review_notifications(GUILD_ID) == []
    with pytest.raises(ConflictError):
        await gate.approve_new_member(
            int(first["id"]),
            reviewer_id=DISCORD_ID,
            reason="Tentativa inválida",
            discord_nick="Visitante",
        )
    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=9001",
        (GUILD_ID,),
    )
    assert member is not None
    assert member["status"] == "ACTIVE"
    assert member["discord_nick"] == "Discord Visitante"
    assert member["rank_id"] is not None
    checklist = await database.fetchone(
        "SELECT * FROM recruit_onboarding_checklists WHERE member_id=?",
        (member["id"],),
    )
    assert checklist["registration_status"] == "COMPLETED"
    outbox = await database.fetchone(
        "SELECT * FROM web_action_outbox WHERE target_discord_id=9001"
    )
    assert outbox["action_type"] == "MEMBER_SYNC"
    total = await database.fetchone(
        "SELECT COUNT(*) AS total FROM registration_gate_records WHERE discord_id=9001"
    )
    assert int(total["total"]) == 1


@pytest.mark.asyncio
async def test_registration_gate_concurrent_double_submit_is_idempotent(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    rows = await asyncio.gather(
        *(
            gate.submit(
                GUILD_ID,
                9010,
                mta_nick="Concorrente",
                bgr_id="9010",
                idempotency_key="concurrent-submit",
            )
            for _ in range(2)
        )
    )
    assert rows[0]["id"] == rows[1]["id"]
    total = await database.fetchone(
        "SELECT COUNT(*) AS total FROM registration_gate_records WHERE discord_id=9010"
    )
    assert int(total["total"]) == 1


@pytest.mark.asyncio
async def test_registration_gate_duplicate_bgr_requires_review(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    record = await gate.submit(
        GUILD_ID,
        9002,
        mta_nick="Outro",
        bgr_id="77",
    )
    assert record["status"] == "REQUIRES_REVIEW"
    assert record["conflict_code"] == "BGR_ID_ALREADY_LINKED"
    assert record["conflict_member_id"] is not None


@pytest.mark.asyncio
async def test_registration_gate_completes_identity_for_preinserted_member(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    await database.execute(
        "UPDATE members SET character_id=NULL WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    intent = await gate.registration_intent(GUILD_ID, DISCORD_ID)
    assert intent["mode"] == "FORM"
    record = await gate.submit(
        GUILD_ID,
        DISCORD_ID,
        mta_nick="Identidade Confirmada",
        bgr_id="7007",
    )
    assert record["status"] == "REQUIRES_REVIEW"
    assert record["conflict_code"] == "LEGACY_MEMBER_REVIEW_REQUIRED"
    assert record["conflict_member_id"] == record["member_id"]
    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert member["character_id"] is None

    approved = await gate.link_existing_member(
        int(record["id"]),
        member_id=int(record["member_id"]),
        reviewer_id=DISCORD_ID + 1,
        reason="Identidade conferida pelo Comando",
    )
    assert approved["status"] == "REGISTERED"
    assert approved["mta_nick"] == "Identidade Confirmada"
    assert approved["bgr_id"] == "7007"
    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert member["mta_nick"] == "Identidade Confirmada"
    assert member["character_id"] == "7007"


@pytest.mark.asyncio
async def test_registration_gate_links_existing_profile_only_after_human_decision(
    service_bundle,
):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    pending = await gate.submit(
        GUILD_ID,
        9011,
        mta_nick="Choque User",
        bgr_id="77",
    )
    assert pending["status"] == "REQUIRES_REVIEW"

    linked = await gate.link_existing_member(
        int(pending["id"]),
        member_id=int(pending["conflict_member_id"]),
        reviewer_id=DISCORD_ID,
        reason="Conta Discord substituída após conferência",
    )
    assert linked["status"] == "REGISTERED"
    assert linked["discord_id"] == 9011
    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND id=?",
        (GUILD_ID, pending["conflict_member_id"]),
    )
    assert member["discord_id"] == 9011
    previous_account = await gate.status(GUILD_ID, DISCORD_ID)
    assert previous_account["status"] == "BLOCKED"
    assert previous_account["sync_status"] == "PENDING"


@pytest.mark.asyncio
async def test_registration_gate_approval_is_atomic_and_enqueues_sync(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    await open_managed_rank_registration(service_bundle, 9003, 88_903)
    pending = await gate.submit(
        GUILD_ID,
        9003,
        mta_nick="Novo_Recruta",
        bgr_id="9003",
    )

    approved = await gate.approve_new_member(
        int(pending["id"]),
        reviewer_id=DISCORD_ID,
        reason="Aprovação de teste",
        discord_nick="Novo Recruta",
    )
    assert approved["status"] == "REGISTERED"
    assert approved["sync_status"] == "PENDING"
    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=9003", (GUILD_ID,)
    )
    assert member is not None
    outbox = await database.fetchall(
        "SELECT payload_json FROM web_action_outbox WHERE target_discord_id=9003"
    )
    assert len(outbox) == 1
    payload = json.loads(outbox[0]["payload_json"])
    assert payload == {"source": "REGISTRATION", "flow": "PORTARIA_DIGITAL"}
    checklist = await database.fetchone(
        "SELECT * FROM recruit_onboarding_checklists WHERE member_id=?", (member["id"],)
    )
    assert checklist["registration_status"] == "COMPLETED"

    with pytest.raises(ConflictError):
        await gate.approve_new_member(
            int(pending["id"]),
            reviewer_id=DISCORD_ID,
            reason="Duplicada",
            discord_nick="Novo Recruta",
        )


@pytest.mark.asyncio
async def test_registration_review_notification_and_archive_are_persisted(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    await open_managed_rank_registration(service_bundle, 9_033, 88_933)
    pending = await gate.submit(
        GUILD_ID,
        9_033,
        mta_nick="Fila Portaria",
        bgr_id="9033",
    )

    notifications = await gate.pending_review_notifications(GUILD_ID)
    assert [int(row["id"]) for row in notifications] == [int(pending["id"])]
    await gate.record_review_notification(int(pending["id"]), 71, 72)

    approved = await gate.approve_new_member(
        int(pending["id"]),
        reviewer_id=DISCORD_ID,
        reason="Identidade conferida",
        discord_nick="Nome anterior",
    )
    results = await gate.undelivered_review_results(GUILD_ID)
    assert [int(row["id"]) for row in results] == [int(approved["id"])]
    assert int(results[0]["review_channel_id"]) == 71
    assert int(results[0]["review_message_id"]) == 72

    await gate.mark_review_result_delivered(
        int(approved["id"]),
        actor_id=DISCORD_ID,
        channel_id=81,
        message_id=82,
    )
    delivered = await gate.get(int(approved["id"]))
    assert delivered["delivery_status"] == "DELIVERED"
    assert int(delivered["result_channel_id"]) == 81
    assert int(delivered["result_message_id"]) == 82
    assert await gate.undelivered_review_results(GUILD_ID) == []


@pytest.mark.asyncio
async def test_registration_result_and_temporary_card_cleanup_are_claimed_once(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    await open_managed_rank_registration(service_bundle, 9_123, 89_123)
    pending = await gate.submit(
        GUILD_ID,
        9_123,
        mta_nick="Ficha Temporária",
        bgr_id="9123",
    )
    await gate.record_review_notification(int(pending["id"]), 71, 72)
    approved = await gate.approve_new_member(
        int(pending["id"]),
        reviewer_id=DISCORD_ID,
        reason="Aprovado para teste de entrega",
        discord_nick="Ficha Temporária",
    )

    claims = await asyncio.gather(
        gate.claim_review_result_delivery(int(approved["id"])),
        gate.claim_review_result_delivery(int(approved["id"])),
    )
    claim_token = next(item for item in claims if item is not None)
    assert sum(item is not None for item in claims) == 1
    await gate.mark_review_result_delivered(
        int(approved["id"]),
        actor_id=DISCORD_ID,
        channel_id=81,
        message_id=82,
        claim_token=claim_token,
    )

    # A failed Discord delete releases only the cleanup claim.  It never
    # republishes the final history message and remains recoverable at startup.
    cleanup_claim = await gate.claim_review_cleanup(int(approved["id"]))
    assert cleanup_claim is not None
    await gate.release_delivery_claim(int(approved["id"]), "CLEANUP", cleanup_claim)
    assert [int(row["id"]) for row in await gate.pending_review_cleanup(GUILD_ID)] == [
        int(approved["id"])
    ]

    cleanup_claim = await gate.claim_review_cleanup(int(approved["id"]))
    assert cleanup_claim is not None
    await gate.mark_review_cleanup_completed(
        int(approved["id"]), claim_token=cleanup_claim
    )
    delivered = await gate.get(int(approved["id"]))
    assert delivered["delivery_status"] == "DELIVERED"
    assert delivered["review_channel_id"] is None
    assert delivered["review_message_id"] is None


@pytest.mark.asyncio
async def test_reused_delivered_registration_starts_a_fresh_review_cycle(service_bundle):
    """A prior result delivery must never remove the card of a new review."""
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    await open_managed_rank_registration(service_bundle, 9_124, 89_124)

    first = await gate.submit(
        GUILD_ID,
        9_124,
        mta_nick="Ciclo anterior",
        bgr_id="9124",
    )
    await gate.record_review_notification(int(first["id"]), 71, 72)
    first_decision = await gate.approve_new_member(
        int(first["id"]),
        reviewer_id=DISCORD_ID,
        reason="Primeiro ciclo concluído",
        discord_nick="Ciclo anterior",
    )
    result_claim = await gate.claim_review_result_delivery(int(first_decision["id"]))
    assert result_claim is not None
    await gate.mark_review_result_delivered(
        int(first_decision["id"]),
        actor_id=DISCORD_ID,
        channel_id=81,
        message_id=82,
        claim_token=result_claim,
    )

    # A new self-identification with a divergent ID reuses the durable row,
    # but must begin a distinct pending delivery cycle.
    second = await gate.submit(
        GUILD_ID,
        9_124,
        mta_nick="Ciclo novo",
        bgr_id="9125",
    )
    assert int(second["id"]) == int(first["id"])
    assert second["status"] == "REQUIRES_REVIEW"
    assert second["delivery_status"] == "PENDING"
    assert second["reviewed_at"] is None
    assert second["review_channel_id"] is None
    assert second["review_message_id"] is None
    assert second["result_channel_id"] is None
    assert second["result_message_id"] is None

    # This is the startup/retry path.  It must publish/recover the pending
    # review, never clean it up because the previous cycle was delivered.
    await gate.record_review_notification(int(second["id"]), 171, 172)
    assert [int(row["id"]) for row in await gate.pending_review_notifications(GUILD_ID)] == [
        int(second["id"])
    ]
    assert await gate.pending_review_cleanup(GUILD_ID) == []
    assert await gate.claim_review_cleanup(int(second["id"])) is None

    rejected = await gate.reject(
        int(second["id"]), reviewer_id=DISCORD_ID, reason="Divergência confirmada"
    )
    result_claim = await gate.claim_review_result_delivery(int(rejected["id"]))
    assert result_claim is not None
    await gate.mark_review_result_delivered(
        int(rejected["id"]),
        actor_id=DISCORD_ID,
        channel_id=181,
        message_id=182,
        claim_token=result_claim,
    )
    assert [int(row["id"]) for row in await gate.pending_review_cleanup(GUILD_ID)] == [
        int(second["id"])
    ]
    cleanup_claim = await gate.claim_review_cleanup(int(second["id"]))
    assert cleanup_claim is not None
    await gate.mark_review_cleanup_completed(int(second["id"]), claim_token=cleanup_claim)
    assert await gate.claim_review_cleanup(int(second["id"])) is None
    assert (await gate.get(int(second["id"])))["review_message_id"] is None


@pytest.mark.asyncio
async def test_pending_review_recovery_repairs_stale_result_delivery_without_losing_card(
    service_bundle,
):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    await open_managed_rank_registration(service_bundle, 9_125, 89_125)
    first = await gate.submit(
        GUILD_ID,
        9_125,
        mta_nick="Recuperação de ficha",
        bgr_id="9125",
    )
    await gate.record_review_notification(int(first["id"]), 71, 72)
    approved = await gate.approve_new_member(
        int(first["id"]),
        reviewer_id=DISCORD_ID,
        reason="Ciclo anterior",
        discord_nick="Recuperação de ficha",
    )
    result_claim = await gate.claim_review_result_delivery(int(approved["id"]))
    assert result_claim is not None
    await gate.mark_review_result_delivered(
        int(approved["id"]),
        actor_id=DISCORD_ID,
        channel_id=81,
        message_id=82,
        claim_token=result_claim,
    )

    # A row left by an old deployment may be PENDING while it still carries
    # the previous terminal delivery.  Startup reconciliation must repair it
    # and retain the current temporary-card pointer.
    await database.execute(
        """
        UPDATE registration_gate_records
        SET status='REQUIRES_REVIEW', completed_at=NULL, reviewed_at=NULL,
            reviewed_by=NULL, review_reason=NULL, review_channel_id=171,
            review_message_id=172
        WHERE id=?
        """,
        (int(approved["id"]),),
    )
    recovered = await gate.prepare_pending_review_delivery(int(approved["id"]))
    assert recovered["status"] == "REQUIRES_REVIEW"
    assert recovered["delivery_status"] == "PENDING"
    assert int(recovered["review_channel_id"]) == 171
    assert int(recovered["review_message_id"]) == 172
    assert recovered["result_channel_id"] is None
    assert recovered["result_message_id"] is None
    assert recovered["reviewed_at"] is None
    assert await gate.pending_review_cleanup(GUILD_ID) == []
    assert await gate.claim_review_cleanup(int(approved["id"])) is None


@pytest.mark.asyncio
async def test_approved_registration_projects_existing_functional_role(service_bundle):
    gate = service_bundle["registration_gate"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    rank_sync = service_bundle["rank_sync"]
    await settings.set(GUILD_ID, "registration_gate_enabled", True, DISCORD_ID)
    await service_bundle["permissions"].ensure_defaults(GUILD_ID)
    instructor_profile = await database.fetchone(
        "SELECT id FROM access_profiles WHERE guild_id=? AND code='INSTRUTOR'",
        (GUILD_ID,),
    )
    assert instructor_profile is not None
    rank_role = FakeRole(81_001, "Recruta")
    functional_role = FakeRole(81_002, "Monitor de instrução")
    rank_id = await database.execute(
        """
        INSERT INTO ranks(
            guild_id, name, prefix, level, discord_role_id,
            rbac_profile, created_at
        ) VALUES (?, 'Recruta', '[REC]', 1, ?, 'RECRUTA', 1)
        """,
        (GUILD_ID, rank_role.id),
    )
    position_id = await database.execute(
        """
        INSERT INTO functional_positions(
            guild_id, code, name, priority, access_profile_id,
            is_primary_candidate, enabled, created_at, updated_at
        ) VALUES (?, 'TRAINING_MONITOR', 'Monitor de instrução', 500, ?, 1, 1, 1, 1)
        """,
        (GUILD_ID, instructor_profile["id"]),
    )
    await database.execute(
        """
        INSERT INTO discord_role_mappings(
            guild_id, discord_role_id, mapping_type, internal_code,
            display_name, priority, position_id, access_profile_id,
            is_primary_position_candidate, enabled, created_at, updated_at
        ) VALUES (?, ?, 'POSITION', 'TRAINING_MONITOR', 'Monitor de instrução',
                  500, ?, ?, 1, 1, 1, 1)
        """,
        (GUILD_ID, functional_role.id, position_id, instructor_profile["id"]),
    )
    _, compliance_created = await gate.ensure_rank_registration_compliance(
        GUILD_ID, 9_020, rank_role.id
    )
    assert compliance_created is True
    pending = await gate.submit(
        GUILD_ID,
        9_020,
        mta_nick="Novo_Funcional",
        bgr_id="9020",
    )
    approved = await gate.approve_new_member(
        int(pending["id"]),
        reviewer_id=DISCORD_ID,
        reason="Identidade conferida na Portaria",
        discord_nick="Novo Funcional",
    )
    member_id = int(approved["member_id"])
    await database.execute(
        """
        UPDATE members
        SET unit='CHOQUE', notes='Dado administrativo preservado'
        WHERE id=?
        """,
        (member_id,),
    )
    before = await database.fetchone(
        """
        SELECT mta_nick, character_id, discord_nick, unit, notes, joined_at, status
        FROM members WHERE id=?
        """,
        (member_id,),
    )
    guild = FakeGuild([rank_role, functional_role])
    discord_member = FakeMember(
        guild,
        9_020,
        [functional_role],
        nick="Nome anterior",
    )

    result = await rank_sync.sync_to_member(
        discord_member,
        source="REGISTRATION_APPROVAL",
        actor_id=DISCORD_ID,
    )
    after = await database.fetchone(
        """
        SELECT mta_nick, character_id, discord_nick, unit, notes, joined_at, status
        FROM members WHERE id=?
        """,
        (member_id,),
    )
    projection = await database.fetchone(
        """
        SELECT fp.code, mp.source_role_id
        FROM member_positions mp
        JOIN functional_positions fp ON fp.id=mp.position_id
        WHERE mp.member_id=?
        """,
        (member_id,),
    )

    assert rank_id == result.rank_id
    assert {role.id for role in discord_member.roles} == {
        rank_role.id,
        functional_role.id,
    }
    assert result.primary_position_code == "TRAINING_MONITOR"
    assert result.access_profile == "INSTRUTOR"
    assert projection is not None
    assert (projection["code"], projection["source_role_id"]) == (
        "TRAINING_MONITOR",
        functional_role.id,
    )
    assert dict(after) == dict(before)


@pytest.mark.asyncio
async def test_registration_gate_classification_snapshot_and_counts(service_bundle):
    gate = service_bundle["registration_gate"]
    await gate.classify_resource(
        GUILD_ID,
        resource_type="CHANNEL",
        resource_id=100,
        internal_key="registration.panel",
        access_class="ONBOARDING_VISIBLE",
        actor_id=DISCORD_ID,
    )
    rows = await gate.classifications(GUILD_ID)
    assert [(row["internal_key"], row["access_class"]) for row in rows] == [
        ("registration.panel", "ONBOARDING_VISIBLE")
    ]
    operation_id = await gate.store_permission_snapshot(
        GUILD_ID,
        {"channels": {"100": {"view_channel": True}}},
        actor_id=DISCORD_ID,
    )
    assert operation_id
    counts = await gate.counts(GUILD_ID)
    assert counts["MEMBERS_WITHOUT_ID"] == 0
