from __future__ import annotations

import asyncio

import pytest

from choque.errors import ConflictError, PermissionDenied
from choque.models import AdministrativeRequestType

from .conftest import CALL_A, DISCORD_ID, GUILD_ID


@pytest.mark.asyncio
async def test_reserve_approval_closes_active_shift_once(service_bundle):
    requests = service_bundle["requests"]
    shifts = service_bundle["shifts"]
    database = service_bundle["database"]
    started = await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)
    request_id = await requests.submit(
        GUILD_ID,
        DISCORD_ID,
        AdministrativeRequestType.RESERVE_ENTRY,
        {"reason": "Pausa operacional"},
    )

    result = await requests.review(
        GUILD_ID, request_id, True, actor_id=999, reason="Aprovado pelo Comando"
    )

    assert result["member_status"] == "RESERVE"
    assert result["shift_closed"] is True
    shift = await database.fetchone("SELECT * FROM shifts WHERE id=?", (started.shift_id,))
    assert shift["status"] == "CLOSED"
    member = await service_bundle["members"].get(GUILD_ID, DISCORD_ID)
    assert member["status"] == "RESERVE"


@pytest.mark.asyncio
async def test_concurrent_request_review_has_single_winner(service_bundle):
    requests = service_bundle["requests"]
    request_id = await requests.submit(
        GUILD_ID,
        DISCORD_ID,
        AdministrativeRequestType.RESERVE_ENTRY,
        {"reason": "Solicitação concorrente"},
    )
    results = await asyncio.gather(
        requests.review(GUILD_ID, request_id, True, 901, "Aprovado"),
        requests.review(GUILD_ID, request_id, False, 902, "Negado"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1


@pytest.mark.asyncio
async def test_requester_cannot_review_own_request(service_bundle):
    requests = service_bundle["requests"]
    request_id = await requests.submit(
        GUILD_ID,
        DISCORD_ID,
        AdministrativeRequestType.DATA_CHANGE,
        {"mta_nick": "NovoNick", "reason": "Correção administrativa"},
    )
    with pytest.raises(PermissionDenied, match="própria solicitação"):
        await requests.review(
            GUILD_ID,
            request_id,
            True,
            actor_id=DISCORD_ID,
            reason="Tentativa de autoaprovação",
        )


@pytest.mark.asyncio
async def test_early_return_restores_reserve_status(service_bundle):
    personnel = service_bundle["personnel"]
    requests = service_bundle["requests"]
    database = service_bundle["database"]
    clock = service_bundle["clock"]
    await database.execute(
        "UPDATE members SET status='RESERVE' WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    absence_id = await personnel.submit_absence(
        GUILD_ID,
        DISCORD_ID,
        clock.value,
        clock.value + 7 * 86_400_000,
        "Viagem",
        "Retorno se possível",
    )
    await personnel.review_absence(GUILD_ID, absence_id, True, 999, "Aprovado")
    assert (await service_bundle["members"].get(GUILD_ID, DISCORD_ID))["status"] == "AWAY"
    request_id = await requests.submit(
        GUILD_ID,
        DISCORD_ID,
        AdministrativeRequestType.EARLY_RETURN,
        {"reason": "Retornei antes"},
    )

    result = await requests.review(GUILD_ID, request_id, True, 999, "Retorno autorizado")

    assert result["member_status"] == "RESERVE"
    assert (await personnel.get_absence(GUILD_ID, absence_id))["status"] == "ENDED"


@pytest.mark.asyncio
async def test_hours_correction_is_append_only_and_audited(service_bundle):
    shifts = service_bundle["shifts"]
    requests = service_bundle["requests"]
    database = service_bundle["database"]
    clock = service_bundle["clock"]
    started = await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)
    clock.advance(60 * 60_000)
    await shifts.stop_shift(GUILD_ID, DISCORD_ID)
    segments_before = [
        dict(row)
        for row in await database.fetchall(
            "SELECT * FROM shift_segments WHERE shift_id=?", (started.shift_id,)
        )
    ]
    request_id = await requests.submit(
        GUILD_ID,
        DISCORD_ID,
        AdministrativeRequestType.HOURS_CORRECTION,
        {
            "shift_id": started.shift_id,
            "requested_total_minutes": 90,
            "problem": "Saída registrada cedo",
            "reason": "Correção comprovada",
        },
    )

    result = await requests.review(GUILD_ID, request_id, True, 999, "Comprovante validado")

    assert result["delta_minutes"] == 30
    assert [
        dict(row)
        for row in await database.fetchall(
            "SELECT * FROM shift_segments WHERE shift_id=?", (started.shift_id,)
        )
    ] == segments_before
    adjustment = await database.fetchone(
        "SELECT * FROM shift_adjustments WHERE shift_id=?", (started.shift_id,)
    )
    assert adjustment["delta_ms"] == 30 * 60_000
    audit = await database.fetchone(
        "SELECT * FROM audit_logs WHERE action='SHIFT_TIME_ADJUSTED_FROM_REQUEST'"
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_data_change_updates_only_after_approval(service_bundle):
    requests = service_bundle["requests"]
    members = service_bundle["members"]
    request_id = await requests.submit(
        GUILD_ID,
        DISCORD_ID,
        AdministrativeRequestType.DATA_CHANGE,
        {"mta_nick": "Novo_Nome", "character_id": "88", "reason": "Atualização"},
    )
    assert (await members.get(GUILD_ID, DISCORD_ID))["mta_nick"] == "Choque_User"

    result = await requests.review(GUILD_ID, request_id, True, 999, "Dados conferidos")

    member = await members.get(GUILD_ID, DISCORD_ID)
    assert result["member_changes"] == {"mta_nick": "Novo_Nome", "character_id": "88"}
    assert member["mta_nick"] == "Novo_Nome"
    assert member["character_id"] == "88"


@pytest.mark.asyncio
async def test_dismissal_preserves_member_record(service_bundle):
    requests = service_bundle["requests"]
    database = service_bundle["database"]
    request_id = await requests.submit(
        GUILD_ID,
        DISCORD_ID,
        AdministrativeRequestType.DISMISSAL,
        {"reason": "Decisão pessoal", "confirmation": "CONFIRMAR"},
    )

    await requests.review(GUILD_ID, request_id, True, 999, "Desligamento aceito")

    member = await database.fetchone(
        "SELECT * FROM members WHERE guild_id=? AND discord_id=?", (GUILD_ID, DISCORD_ID)
    )
    assert member is not None
    assert member["status"] == "DISMISSED"
