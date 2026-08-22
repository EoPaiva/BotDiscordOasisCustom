from __future__ import annotations

from datetime import timedelta

import pytest

from choque.activity import ActivityService, period_bounds_at
from choque.errors import ValidationError

from .conftest import CALL_A, DISCORD_ID, GUILD_ID

MINUTE_MS = 60_000
DAY_MS = 86_400_000


async def seed_closed_shift(
    bundle: dict[str, object], *, started_at: int, duration_minutes: int
) -> int:
    database = bundle["database"]
    member = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    ended_at = started_at + duration_minutes * MINUTE_MS
    async with database.transaction() as connection:
        cursor = await connection.execute(
            """
            INSERT INTO shifts(
                guild_id, member_id, status, started_at, ended_at, closed_at,
                end_reason, created_by, created_at
            ) VALUES (?, ?, 'CLOSED', ?, ?, ?, 'TEST', ?, ?)
            """,
            (
                GUILD_ID,
                member["id"],
                started_at,
                ended_at,
                ended_at,
                DISCORD_ID,
                started_at,
            ),
        )
        shift_id = int(cursor.lastrowid)
        await connection.execute(
            """
            INSERT INTO shift_segments(
                guild_id, shift_id, voice_channel_id, started_at, ended_at, end_reason
            ) VALUES (?, ?, ?, ?, ?, 'TEST')
            """,
            (GUILD_ID, shift_id, CALL_A, started_at, ended_at),
        )
    return shift_id


@pytest.mark.asyncio
async def test_weekly_dashboard_classifies_goal_near_and_exemption(service_bundle):
    activity = service_bundle["activity"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]
    clock = service_bundle["clock"]
    week_start, _ = period_bounds_at("week", "America/Sao_Paulo", clock.value)
    await settings.set(GUILD_ID, "weekly_goal_minutes", 100, DISCORD_ID)
    await settings.set(GUILD_ID, "weekly_near_threshold_percent", 75, DISCORD_ID)
    await seed_closed_shift(service_bundle, started_at=week_start + MINUTE_MS, duration_minutes=80)

    row = await activity.member_activity(GUILD_ID, DISCORD_ID)
    assert row["total_ms"] == 80 * MINUTE_MS
    assert row["activity_status"] == "NEAR"

    await database.execute(
        "UPDATE members SET status='RESERVE' WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    exempt = await activity.member_activity(GUILD_ID, DISCORD_ID)
    assert exempt["activity_status"] == "EXEMPT"
    assert exempt["exemption_reason"] == "RESERVE"


@pytest.mark.asyncio
async def test_weekly_close_is_append_only_idempotent_and_restart_safe(service_bundle):
    activity = service_bundle["activity"]
    database = service_bundle["database"]
    settings = service_bundle["settings"]
    audit = service_bundle["audit"]
    shifts = service_bundle["shifts"]
    clock = service_bundle["clock"]
    current_start, _ = period_bounds_at("week", "America/Sao_Paulo", clock.value)
    previous_start = current_start - int(timedelta(days=7).total_seconds() * 1000)
    await database.execute(
        "UPDATE members SET joined_at=? WHERE guild_id=? AND discord_id=?",
        (previous_start - 1, GUILD_ID, DISCORD_ID),
    )
    await seed_closed_shift(
        service_bundle, started_at=previous_start + MINUTE_MS, duration_minutes=400
    )

    first = await activity.close_completed_weeks(GUILD_ID, actor_id=DISCORD_ID)
    assert first == [
        {
            "week_start_at": previous_start,
            "week_end_at": current_start,
            "members": 1,
        }
    ]
    snapshot = await database.fetchone(
        "SELECT * FROM weekly_activity_snapshots WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    assert snapshot["total_ms"] == 400 * MINUTE_MS
    assert snapshot["status"] == "FULFILLED"
    assert await activity.close_completed_weeks(GUILD_ID, actor_id=DISCORD_ID) == []

    restarted = ActivityService(database, settings, audit, shifts, clock=clock)
    assert await restarted.close_completed_weeks(GUILD_ID) == []
    counts = await database.fetchone(
        "SELECT COUNT(*) AS total FROM weekly_activity_snapshots WHERE guild_id=?",
        (GUILD_ID,),
    )
    audits = await database.fetchone(
        "SELECT COUNT(*) AS total FROM audit_logs WHERE guild_id=? AND action='WEEKLY_ACTIVITY_CLOSED'",
        (GUILD_ID,),
    )
    assert counts["total"] == 1
    assert audits["total"] == 1


@pytest.mark.asyncio
async def test_approved_absence_exempts_closed_week(service_bundle):
    activity = service_bundle["activity"]
    database = service_bundle["database"]
    clock = service_bundle["clock"]
    current_start, _ = period_bounds_at("week", "America/Sao_Paulo", clock.value)
    previous_start = current_start - 7 * DAY_MS
    member = await database.fetchone(
        "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
        (GUILD_ID, DISCORD_ID),
    )
    await database.execute(
        "UPDATE members SET joined_at=? WHERE id=?",
        (previous_start - 1, member["id"]),
    )
    await database.execute(
        """
        INSERT INTO absence_requests(
            guild_id, member_id, discord_id, starts_at, ends_at, reason,
            status, submitted_at, reviewed_by, reviewed_at
        ) VALUES (?, ?, ?, ?, ?, 'Teste', 'APPROVED', ?, ?, ?)
        """,
        (
            GUILD_ID,
            member["id"],
            DISCORD_ID,
            previous_start,
            current_start,
            previous_start,
            DISCORD_ID,
            previous_start,
        ),
    )

    await activity.close_completed_weeks(GUILD_ID)
    snapshot = await database.fetchone(
        "SELECT status, exemption_reason FROM weekly_activity_snapshots WHERE guild_id=?",
        (GUILD_ID,),
    )
    assert dict(snapshot) == {"status": "EXEMPT", "exemption_reason": "ABSENCE"}


@pytest.mark.asyncio
async def test_inactivity_is_only_monitoring_and_never_creates_punishment(service_bundle):
    activity = service_bundle["activity"]
    database = service_bundle["database"]
    clock = service_bundle["clock"]
    await database.execute(
        "UPDATE members SET last_activity_at=? WHERE guild_id=? AND discord_id=?",
        (clock.value - 10 * DAY_MS, GUILD_ID, DISCORD_ID),
    )
    low = await activity.inactivity(GUILD_ID, "LOW")
    assert [row["discord_id"] for row in low] == [DISCORD_ID]

    await database.execute(
        "UPDATE members SET last_activity_at=? WHERE guild_id=? AND discord_id=?",
        (clock.value - 20 * DAY_MS, GUILD_ID, DISCORD_ID),
    )
    none = await activity.inactivity(GUILD_ID, "NONE")
    assert [row["discord_id"] for row in none] == [DISCORD_ID]
    punishments = await database.fetchone("SELECT COUNT(*) AS total FROM punishments")
    assert punishments["total"] == 0


@pytest.mark.asyncio
async def test_activity_rules_validate_and_are_audited(service_bundle):
    activity = service_bundle["activity"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]

    with pytest.raises(ValidationError):
        await activity.set_rules(
            GUILD_ID,
            DISCORD_ID,
            goal_minutes=360,
            near_percent=75,
            low_days=20,
            no_days=10,
        )
    result = await activity.set_rules(
        GUILD_ID,
        DISCORD_ID,
        goal_minutes=420,
        near_percent=80,
        low_days=8,
        no_days=16,
    )
    assert result["weekly_goal_minutes"] == 420
    assert await settings.get(GUILD_ID, "no_activity_days") == 16
    audit = await database.fetchone(
        "SELECT action FROM audit_logs WHERE guild_id=? AND action='ACTIVITY_RULES_CHANGED'",
        (GUILD_ID,),
    )
    assert audit["action"] == "ACTIVITY_RULES_CHANGED"
