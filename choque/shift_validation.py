from __future__ import annotations

import aiosqlite

from .errors import NotFoundError

INVALID_REASON_MINIMUM = "MINIMUM_PATROL_TIME_NOT_REACHED"


def countable_shift_clause(
    shift_alias: str = "s", segment_alias: str = "validation_segment"
) -> str:
    """SQL predicate for sessions that may contribute to hour aggregates.

    The single placeholder is the effective current timestamp. Closed sessions
    depend on their persisted validation result; active sessions are evaluated
    from their immutable segment classification so the exact threshold does not
    depend on a background tick.
    """
    return f"""
        (
            {shift_alias}.validation_status='VALID'
            OR (
                {shift_alias}.status IN ('ACTIVE','GRACE')
                AND COALESCE((
                    SELECT SUM(MAX(
                        0,
                        COALESCE({segment_alias}.ended_at, ?) - {segment_alias}.started_at
                    ))
                    FROM shift_segments {segment_alias}
                    WHERE {segment_alias}.shift_id={shift_alias}.id
                      AND {segment_alias}.counts_toward_patrol_minimum=1
                ), 0) >= {shift_alias}.minimum_patrol_ms
            )
        )
    """


async def calculate_patrol_progress_in_tx(
    connection: aiosqlite.Connection,
    shift_id: int,
    effective_now: int,
) -> dict[str, int | bool | None]:
    cursor = await connection.execute(
        "SELECT minimum_patrol_ms, patrol_requirement_met_at FROM shifts WHERE id=?",
        (shift_id,),
    )
    shift = await cursor.fetchone()
    if not shift:
        raise NotFoundError("Sessão não encontrada.")
    minimum_ms = int(shift["minimum_patrol_ms"])
    cursor = await connection.execute(
        """
        SELECT started_at, COALESCE(ended_at, ?) AS effective_end
        FROM shift_segments
        WHERE shift_id=? AND counts_toward_patrol_minimum=1
        ORDER BY started_at, id
        """,
        (effective_now, shift_id),
    )
    segments = list(await cursor.fetchall())
    patrol_ms = 0
    met_at = (
        int(shift["patrol_requirement_met_at"])
        if shift["patrol_requirement_met_at"]
        else None
    )
    for segment in segments:
        started_at = int(segment["started_at"])
        ended_at = max(started_at, min(int(segment["effective_end"]), effective_now))
        duration = ended_at - started_at
        if met_at is None and minimum_ms > 0 and patrol_ms + duration >= minimum_ms:
            met_at = started_at + (minimum_ms - patrol_ms)
        patrol_ms += duration
    requirement_met = minimum_ms <= 0 or patrol_ms >= minimum_ms
    return {
        "patrol_duration_ms": patrol_ms,
        "minimum_patrol_ms": minimum_ms,
        "requirement_met": requirement_met,
        "requirement_met_at": met_at,
    }


async def closed_validation_values(
    connection: aiosqlite.Connection,
    shift,
    valid_end: int,
) -> dict[str, int | str | None]:
    progress = await calculate_patrol_progress_in_tx(
        connection,
        int(shift["id"]),
        valid_end,
    )
    requirement_met = bool(progress["requirement_met"])
    return {
        "gross_duration_ms": max(0, valid_end - int(shift["started_at"])),
        "patrol_duration_ms": int(progress["patrol_duration_ms"]),
        "minimum_patrol_ms": int(progress["minimum_patrol_ms"]),
        "patrol_requirement_met_at": progress["requirement_met_at"],
        "validation_status": "VALID" if requirement_met else "INVALIDATED",
        "invalid_reason": None if requirement_met else INVALID_REASON_MINIMUM,
    }
