from __future__ import annotations

import asyncio

import pytest

from choque.errors import ConflictError, NotFoundError, ValidationError
from choque.models import ShiftStatus
from choque.shifts import ShiftService

from .conftest import CALL_A, CALL_B, DISCORD_ID, GUILD_ID


@pytest.mark.asyncio
async def test_01_start_outside_authorized_call_is_denied(service_bundle):
    shifts = service_bundle["shifts"]
    with pytest.raises(ValidationError, match="call autorizada"):
        await shifts.start_shift(GUILD_ID, DISCORD_ID, 9999, has_authorized_role=True)


@pytest.mark.asyncio
async def test_02_start_in_authorized_call(service_bundle):
    result = await service_bundle["shifts"].start_shift(
        GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True
    )
    assert result.status is ShiftStatus.ACTIVE
    assert await service_bundle["shifts"].get_active(GUILD_ID, DISCORD_ID)


@pytest.mark.asyncio
async def test_03_concurrent_second_start_is_denied(service_bundle):
    shifts = service_bundle["shifts"]
    results = await asyncio.gather(
        shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True),
        shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1


@pytest.mark.asyncio
async def test_04_authorized_call_move_creates_two_segments(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    started = await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)
    clock.advance(10_000)
    status = await shifts.handle_voice_transition(
        GUILD_ID, DISCORD_ID, CALL_A, CALL_B, has_authorized_role=True
    )
    segments = await service_bundle["database"].fetchall(
        "SELECT * FROM shift_segments WHERE shift_id=? ORDER BY id", (started.shift_id,)
    )
    assert status is ShiftStatus.ACTIVE
    assert len(segments) == 2
    assert segments[0]["ended_at"] == segments[1]["started_at"]
    assert segments[1]["voice_channel_id"] == CALL_B


@pytest.mark.asyncio
async def test_05_leave_enters_grace_and_expiration_closes_once(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    result = await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)
    clock.advance(12_000)
    status = await shifts.handle_voice_transition(
        GUILD_ID, DISCORD_ID, CALL_A, None, has_authorized_role=True
    )
    active = await shifts.get_active(GUILD_ID, DISCORD_ID)
    assert status is ShiftStatus.GRACE
    deadline = int(active["grace_deadline"])
    assert await shifts.expire_grace(GUILD_ID, DISCORD_ID, result.shift_id, deadline)
    assert not await shifts.expire_grace(GUILD_ID, DISCORD_ID, result.shift_id, deadline)
    assert await shifts.total_for_member(GUILD_ID, DISCORD_ID) == 12_000


@pytest.mark.asyncio
async def test_06_return_during_grace_excludes_gap_and_does_not_duplicate(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    result = await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)
    clock.advance(10_000)
    await shifts.handle_voice_transition(
        GUILD_ID, DISCORD_ID, CALL_A, None, has_authorized_role=True
    )
    clock.advance(20_000)
    status = await shifts.handle_voice_transition(
        GUILD_ID, DISCORD_ID, None, CALL_A, has_authorized_role=True
    )
    clock.advance(5_000)
    await shifts.stop_shift(GUILD_ID, DISCORD_ID)
    segments = await service_bundle["database"].fetchall(
        "SELECT * FROM shift_segments WHERE shift_id=? ORDER BY id", (result.shift_id,)
    )
    assert status is ShiftStatus.ACTIVE
    assert len(segments) == 2
    assert await shifts.total_for_member(GUILD_ID, DISCORD_ID) == 15_000


@pytest.mark.asyncio
async def test_07_restart_recovers_same_call_or_marks_unknown_for_review(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)
    clock.advance(30_000)
    same_call = ShiftService(
        service_bundle["database"],
        service_bundle["settings"],
        service_bundle["audit"],
        clock=clock,
    )
    assert (
        await same_call.recover_shift(GUILD_ID, DISCORD_ID, CALL_A, clock.value - 5_000)
        is ShiftStatus.ACTIVE
    )
    clock.advance(10_000)
    assert (
        await same_call.recover_shift(GUILD_ID, DISCORD_ID, None, clock.value - 3_000)
        is ShiftStatus.REVIEW_REQUIRED
    )
    assert await same_call.total_for_member(GUILD_ID, DISCORD_ID) == 0
    await same_call.close()


@pytest.mark.asyncio
async def test_restart_in_different_authorized_call_excludes_ambiguous_gap(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    result = await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)
    clock.advance(30_000)
    last_heartbeat = clock.value
    clock.advance(20_000)
    recovered = ShiftService(
        service_bundle["database"],
        service_bundle["settings"],
        service_bundle["audit"],
        clock=clock,
    )
    status = await recovered.recover_shift(GUILD_ID, DISCORD_ID, CALL_B, last_heartbeat)
    segments = await service_bundle["database"].fetchall(
        "SELECT * FROM shift_segments WHERE shift_id=? ORDER BY id", (result.shift_id,)
    )
    assert status is ShiftStatus.ACTIVE
    assert len(segments) == 2
    assert segments[0]["ended_at"] == last_heartbeat
    assert segments[1]["started_at"] == clock.value
    assert await recovered.total_for_member(GUILD_ID, DISCORD_ID) == 30_000
    await recovered.close()


@pytest.mark.asyncio
async def test_08_two_finalizations_create_only_one_close_audit(service_bundle):
    shifts = service_bundle["shifts"]
    await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)
    results = await asyncio.gather(
        shifts.stop_shift(GUILD_ID, DISCORD_ID),
        shifts.stop_shift(GUILD_ID, DISCORD_ID),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, NotFoundError) for result in results) == 1
    audit_count = await service_bundle["database"].fetchone(
        "SELECT COUNT(*) AS total FROM audit_logs WHERE action='SHIFT_CLOSED'"
    )
    assert audit_count["total"] == 1


@pytest.mark.asyncio
async def test_09_append_only_adjustment_changes_total_and_audits(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    result = await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)
    clock.advance(60_000)
    await shifts.stop_shift(GUILD_ID, DISCORD_ID)
    segment_before = await service_bundle["database"].fetchone(
        "SELECT started_at, ended_at FROM shift_segments WHERE shift_id=?", (result.shift_id,)
    )
    await shifts.adjust_shift(GUILD_ID, result.shift_id, 5, 999, "Correção aprovada")
    segment_after = await service_bundle["database"].fetchone(
        "SELECT started_at, ended_at FROM shift_segments WHERE shift_id=?", (result.shift_id,)
    )
    assert dict(segment_before) == dict(segment_after)
    assert await shifts.total_for_member(GUILD_ID, DISCORD_ID) == 360_000
    audit = await service_bundle["database"].fetchone(
        "SELECT * FROM audit_logs WHERE action='SHIFT_TIME_ADJUSTED'"
    )
    assert audit and audit["reason"] == "Correção aprovada"


@pytest.mark.asyncio
async def test_10_role_loss_finalizes_immediately(service_bundle):
    shifts = service_bundle["shifts"]
    await shifts.start_shift(GUILD_ID, DISCORD_ID, CALL_A, has_authorized_role=True)
    assert await shifts.finalize_role_loss(GUILD_ID, DISCORD_ID)
    assert await shifts.get_active(GUILD_ID, DISCORD_ID) is None
    closed = await service_bundle["database"].fetchone(
        "SELECT end_reason FROM shifts ORDER BY id DESC LIMIT 1"
    )
    assert closed["end_reason"] == "ROLE_LOST"
