from __future__ import annotations

import json
import uuid
from typing import Any

from .time_utils import utc_now_ms


async def enqueue_identity_reconciliation(
    connection: Any,
    *,
    guild_id: int,
    requested_by: int,
    mode: str,
    source: str,
    source_job_id: int | None = None,
) -> dict[str, object]:
    """Persiste job e outbox de identidade na transação da mudança de acesso."""
    normalized_mode = mode.strip().upper()
    if normalized_mode not in {"PREVIEW", "APPLY"}:
        raise ValueError("Modo de reconciliação de identidade inválido.")
    now = utc_now_ms()
    correlation_id = str(uuid.uuid4())
    cursor = await connection.execute(
        """
        INSERT INTO identity_reconciliation_jobs(
            guild_id, mode, status, requested_by, source_job_id,
            correlation_id, created_at
        ) VALUES (?, ?, 'PENDING', ?, ?, ?, ?)
        """,
        (
            guild_id,
            normalized_mode,
            requested_by,
            source_job_id,
            correlation_id,
            now,
        ),
    )
    job_id = int(cursor.lastrowid)
    await connection.execute(
        """
        INSERT INTO web_action_outbox(
            guild_id, action_type, payload_json, requested_by,
            correlation_id, status, available_at, created_at
        ) VALUES (?, 'IDENTITY_RECONCILE_BULK', ?, ?, ?, 'PENDING', ?, ?)
        """,
        (
            guild_id,
            json.dumps(
                {
                    "job_id": job_id,
                    "mode": normalized_mode,
                    "source": source,
                    "source_job_id": source_job_id,
                },
                ensure_ascii=False,
            ),
            requested_by,
            correlation_id,
            now,
            now,
        ),
    )
    return {
        "job_id": job_id,
        "mode": normalized_mode,
        "status": "PENDING",
        "correlation_id": correlation_id,
    }
