from __future__ import annotations

import asyncio

import pytest

from choque.errors import ConflictError
from choque.models import ShiftStatus
from choque.shifts import ShiftService

from .conftest import CALL_A, CALL_B, DISCORD_ID, GUILD_ID

MINIMUM_MINUTES = 15
MINIMUM_MS = MINIMUM_MINUTES * 60_000


async def enable_minimum(service_bundle) -> None:
    await service_bundle["settings"].set(
        GUILD_ID,
        "minimum_patrol_minutes",
        MINIMUM_MINUTES,
        DISCORD_ID,
    )


async def start(service_bundle, channel_id: int = CALL_A):
    await enable_minimum(service_bundle)
    return await service_bundle["shifts"].start_shift(
        GUILD_ID,
        DISCORD_ID,
        channel_id,
        has_authorized_role=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("duration_ms", "expected_status"),
    [
        (14 * 60_000 + 59_000, "INVALIDATED"),
        (15 * 60_000, "VALID"),
        (20 * 60_000, "VALID"),
    ],
)
async def test_minimum_boundary_is_exact(service_bundle, duration_ms, expected_status):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    result = await start(service_bundle)
    clock.advance(duration_ms)
    closed = await shifts.stop_shift(
        GUILD_ID,
        DISCORD_ID,
        confirm_short=expected_status == "INVALIDATED",
    )

    row = await service_bundle["database"].fetchone(
        "SELECT * FROM shifts WHERE id=?", (result.shift_id,)
    )
    assert closed.validation_status == expected_status
    assert row["validation_status"] == expected_status
    assert row["patrol_duration_ms"] == duration_ms
    assert row["minimum_patrol_ms"] == MINIMUM_MS
    assert (row["invalid_reason"] is not None) == (expected_status == "INVALIDATED")


@pytest.mark.asyncio
async def test_two_patrol_calls_accumulate_without_reset(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    result = await start(service_bundle)
    clock.advance(10 * 60_000)
    assert (
        await shifts.handle_voice_transition(
            GUILD_ID,
            DISCORD_ID,
            CALL_A,
            CALL_B,
            has_authorized_role=True,
        )
        is ShiftStatus.ACTIVE
    )
    clock.advance(5 * 60_000)
    closed = await shifts.stop_shift(GUILD_ID, DISCORD_ID)
    segments = await service_bundle["database"].fetchall(
        "SELECT * FROM shift_segments WHERE shift_id=? ORDER BY id", (result.shift_id,)
    )

    assert closed.validation_status == "VALID"
    assert closed.patrol_duration_ms == MINIMUM_MS
    assert len(segments) == 2


@pytest.mark.asyncio
async def test_authorized_training_call_keeps_service_but_does_not_validate(service_bundle):
    shifts = service_bundle["shifts"]
    settings = service_bundle["settings"]
    clock = service_bundle["clock"]
    training_call = 9_999
    await settings.add_voice_channel(GUILD_ID, training_call, "Treinamento", DISCORD_ID)
    await settings.set_voice_patrol_classification(GUILD_ID, training_call, False)
    result = await start(service_bundle)
    clock.advance(10 * 60_000)
    await shifts.handle_voice_transition(
        GUILD_ID,
        DISCORD_ID,
        CALL_A,
        training_call,
        has_authorized_role=True,
    )
    clock.advance(20 * 60_000)
    closed = await shifts.stop_shift(GUILD_ID, DISCORD_ID, confirm_short=True)

    segments = await service_bundle["database"].fetchall(
        """
        SELECT voice_channel_id, counts_toward_patrol_minimum
        FROM shift_segments WHERE shift_id=? ORDER BY id
        """,
        (result.shift_id,),
    )
    assert closed.validation_status == "INVALIDATED"
    assert closed.patrol_duration_ms == 10 * 60_000
    assert [row["counts_toward_patrol_minimum"] for row in segments] == [1, 0]


@pytest.mark.asyncio
async def test_grace_gap_is_excluded_from_exact_fifteen_minutes(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    await start(service_bundle)
    clock.advance(14 * 60_000 + 30_000)
    await shifts.handle_voice_transition(
        GUILD_ID, DISCORD_ID, CALL_A, None, has_authorized_role=True
    )
    clock.advance(40_000)
    await shifts.handle_voice_transition(
        GUILD_ID, DISCORD_ID, None, CALL_A, has_authorized_role=True
    )
    clock.advance(30_000)
    closed = await shifts.stop_shift(GUILD_ID, DISCORD_ID)

    assert closed.validation_status == "VALID"
    assert closed.patrol_duration_ms == MINIMUM_MS


@pytest.mark.asyncio
async def test_automatic_grace_close_at_eight_minutes_is_invalidated(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    result = await start(service_bundle)
    clock.advance(8 * 60_000)
    await shifts.handle_voice_transition(
        GUILD_ID, DISCORD_ID, CALL_A, None, has_authorized_role=True
    )
    active = await shifts.get_active(GUILD_ID, DISCORD_ID)
    clock.advance(60_000)
    assert await shifts.expire_grace(
        GUILD_ID,
        DISCORD_ID,
        result.shift_id,
        int(active["grace_deadline"]),
    )

    row = await service_bundle["database"].fetchone(
        "SELECT * FROM shifts WHERE id=?", (result.shift_id,)
    )
    assert row["validation_status"] == "INVALIDATED"
    assert row["end_reason"] == "GRACE_EXPIRED"
    assert row["patrol_duration_ms"] == 8 * 60_000


@pytest.mark.asyncio
async def test_restart_at_ten_minutes_preserves_progress_to_fifteen(service_bundle):
    clock = service_bundle["clock"]
    await start(service_bundle)
    clock.advance(10 * 60_000)
    recovered = ShiftService(
        service_bundle["database"],
        service_bundle["settings"],
        service_bundle["audit"],
        clock=clock,
    )
    assert (
        await recovered.recover_shift(GUILD_ID, DISCORD_ID, CALL_A, clock.value)
        is ShiftStatus.ACTIVE
    )
    clock.advance(5 * 60_000)
    closed = await recovered.stop_shift(GUILD_ID, DISCORD_ID)
    await recovered.close()

    assert closed.validation_status == "VALID"
    assert closed.patrol_duration_ms == MINIMUM_MS


@pytest.mark.asyncio
async def test_short_manual_stop_requires_confirmation_and_preserves_history(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    result = await start(service_bundle)
    clock.advance(4 * 60_000)

    with pytest.raises(ConflictError, match="Confirme"):
        await shifts.stop_shift(GUILD_ID, DISCORD_ID)
    assert await shifts.get_active(GUILD_ID, DISCORD_ID)

    closed = await shifts.stop_shift(
        GUILD_ID,
        DISCORD_ID,
        confirm_short=True,
        expected_shift_id=result.shift_id,
    )
    history = await shifts.history(GUILD_ID, DISCORD_ID)
    assert closed.validation_status == "INVALIDATED"
    assert history[0]["id"] == result.shift_id
    assert history[0]["validation_status"] == "INVALIDATED"


@pytest.mark.asyncio
async def test_invalidated_session_is_zero_in_totals_ranking_goal_and_reports(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    result = await start(service_bundle)
    clock.advance(10 * 60_000)
    await shifts.stop_shift(GUILD_ID, DISCORD_ID, confirm_short=True)
    await shifts.adjust_shift(GUILD_ID, result.shift_id, 30, 999, "Ajuste não valida sessão")

    total = await shifts.total_for_member(GUILD_ID, DISCORD_ID)
    ranking = await service_bundle["personnel"].ranking(
        GUILD_ID, 0, clock.value + 1, limit=20
    )
    activity = await service_bundle["activity"].member_activity(GUILD_ID, DISCORD_ID)
    daily = await service_bundle["activity"].daily_report(GUILD_ID)
    points = await service_bundle["activity"].points_report(GUILD_ID)
    punishments = await service_bundle["database"].fetchone(
        "SELECT COUNT(*) AS total FROM punishments WHERE guild_id=?", (GUILD_ID,)
    )

    assert total == 0
    assert int(ranking[0]["total_ms"]) == 0
    assert activity["total_ms"] == 0
    assert daily["total_ms"] == 0
    assert points["invalidated"] == 1
    assert punishments["total"] == 0


@pytest.mark.asyncio
async def test_call_classification_is_snapshotted_per_segment(service_bundle):
    shifts = service_bundle["shifts"]
    settings = service_bundle["settings"]
    clock = service_bundle["clock"]
    result = await start(service_bundle)
    clock.advance(10 * 60_000)
    await settings.set_voice_patrol_classification(GUILD_ID, CALL_A, False)
    await shifts.handle_voice_transition(
        GUILD_ID, DISCORD_ID, CALL_A, CALL_B, has_authorized_role=True
    )
    await shifts.handle_voice_transition(
        GUILD_ID, DISCORD_ID, CALL_B, CALL_A, has_authorized_role=True
    )
    clock.advance(5 * 60_000)
    closed = await shifts.stop_shift(GUILD_ID, DISCORD_ID, confirm_short=True)
    segments = await service_bundle["database"].fetchall(
        """
        SELECT voice_channel_id, counts_toward_patrol_minimum
        FROM shift_segments WHERE shift_id=? ORDER BY id
        """,
        (result.shift_id,),
    )

    assert closed.validation_status == "INVALIDATED"
    assert closed.patrol_duration_ms == 10 * 60_000
    assert [row["counts_toward_patrol_minimum"] for row in segments] == [1, 1, 0]


@pytest.mark.asyncio
async def test_admin_override_is_append_only_audited_and_concurrency_safe(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    result = await start(service_bundle)
    clock.advance(10 * 60_000)
    await shifts.stop_shift(GUILD_ID, DISCORD_ID, confirm_short=True)

    decisions = await asyncio.gather(
        shifts.validate_manually(GUILD_ID, result.shift_id, 9001, "Queda geral do Discord"),
        shifts.validate_manually(GUILD_ID, result.shift_id, 9002, "Evento operacional confirmado"),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, Exception) for item in decisions) == 1
    assert sum(isinstance(item, ConflictError) for item in decisions) == 1

    row = await service_bundle["database"].fetchone(
        "SELECT * FROM shifts WHERE id=?", (result.shift_id,)
    )
    override = await service_bundle["database"].fetchone(
        "SELECT * FROM shift_validation_overrides WHERE shift_id=?", (result.shift_id,)
    )
    audit = await service_bundle["database"].fetchone(
        "SELECT * FROM audit_logs WHERE action='SHIFT_VALIDATED_MANUALLY' AND target_id=?",
        (DISCORD_ID,),
    )
    assert row["validation_status"] == "VALID"
    assert row["automatic_validation_status"] == "INVALIDATED"
    assert row["validation_source"] == "ADMIN_OVERRIDE"
    assert override and audit
    assert await shifts.total_for_member(GUILD_ID, DISCORD_ID) == 10 * 60_000


@pytest.mark.asyncio
async def test_active_session_becomes_countable_at_exact_threshold_without_tick(service_bundle):
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    await start(service_bundle)
    clock.advance(MINIMUM_MS)

    assert await shifts.total_for_member(GUILD_ID, DISCORD_ID) == MINIMUM_MS
    ranking = await service_bundle["personnel"].ranking(
        GUILD_ID, 0, clock.value + 1, limit=20
    )
    assert int(ranking[0]["total_ms"]) == MINIMUM_MS
