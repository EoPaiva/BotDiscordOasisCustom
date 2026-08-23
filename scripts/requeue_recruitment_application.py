from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402
from choque.time_utils import utc_now_ms  # noqa: E402

SUPPORTED_STATUSES = {
    "SUBMITTED",
    "UNDER_REVIEW",
    "INTERVIEW_PENDING",
    "INTERVIEW_SCHEDULED",
    "INTERVIEW_COMPLETED",
    "FINAL_REVIEW",
    "APPROVED",
    "REJECTED",
}


async def _load_application(database: Database, protocol: str):
    return await database.fetchone(
        "SELECT * FROM recruitment_applications WHERE protocol=?",
        (protocol,),
    )


async def _delivery_summary(database: Database, application_id: int) -> list[dict[str, object]]:
    rows = await database.fetchall(
        """
        SELECT event_type, event_key, status, attempts,
               delivery_channel_id, delivery_message_id, last_error
        FROM recruitment_notification_outbox
        WHERE application_id=?
        ORDER BY id
        """,
        (application_id,),
    )
    return [
        {
            "event_type": str(row["event_type"]),
            "event_key": str(row["event_key"]),
            "status": str(row["status"]),
            "attempts": int(row["attempts"]),
            "delivery_channel_id": (
                int(row["delivery_channel_id"])
                if row["delivery_channel_id"] is not None
                else None
            ),
            "delivery_message_id": (
                int(row["delivery_message_id"])
                if row["delivery_message_id"] is not None
                else None
            ),
            "last_error": str(row["last_error"] or "")[:160] or None,
        }
        for row in rows
    ]


async def run() -> int:
    parser = argparse.ArgumentParser(
        description="Reencaminha uma candidatura existente ao fluxo Discord atual."
    )
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    protocol = args.protocol.strip().upper()
    config = AppConfig.load()
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        application = await _load_application(database, protocol)
        if not application:
            raise RuntimeError("Protocolo não encontrado.")
        application_id = int(application["id"])
        application_status = str(application["status"])
        if args.status:
            print(
                json.dumps(
                    {
                        "protocol": protocol,
                        "status": application_status,
                        "deliveries": await _delivery_summary(database, application_id),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if application_status not in SUPPORTED_STATUSES:
            raise RuntimeError(
                "Somente candidaturas ativas e já enviadas podem ser reencaminhadas."
            )
        if not args.apply:
            print(
                "RECRUITMENT_REQUEUE_PREVIEW_PASS "
                f"protocol={protocol} status={application_status}"
            )
            return 0

        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        now = utc_now_ms()
        private_key = f"application-submitted:{application_id}:workflow-v3"
        public_key = (
            f"application-public-status:{application_id}:{application_status}:workflow-v3"
        )
        async with database.transaction() as connection:
            private_cursor = None
            if application_status not in {"APPROVED", "REJECTED"}:
                private_cursor = await connection.execute(
                    """
                    INSERT INTO recruitment_notification_outbox(
                        guild_id, application_id, event_type, event_key,
                        payload_json, available_at, created_at
                    ) VALUES (?, ?, 'RECRUITMENT_APPLICATION_SUBMITTED', ?, ?, ?, ?)
                    ON CONFLICT(guild_id, event_key) DO NOTHING
                    """,
                    (
                        int(application["guild_id"]),
                        application_id,
                        private_key,
                        json.dumps(
                            {
                                "application_id": application_id,
                                "protocol": protocol,
                                "migration": "workflow-v3",
                            },
                            ensure_ascii=False,
                        ),
                        now,
                        now,
                    ),
                )
            public_cursor = await connection.execute(
                """
                INSERT INTO recruitment_notification_outbox(
                    guild_id, application_id, event_type, event_key,
                    payload_json, available_at, created_at
                ) VALUES (?, ?, 'RECRUITMENT_PUBLIC_STATUS', ?, ?, ?, ?)
                ON CONFLICT(guild_id, event_key) DO NOTHING
                """,
                (
                    int(application["guild_id"]),
                    application_id,
                    public_key,
                    json.dumps(
                        {
                            "application_id": application_id,
                            "status": application_status,
                            "migration": "workflow-v3",
                        },
                        ensure_ascii=False,
                    ),
                    now,
                    now,
                ),
            )
            result_cursors = []
            if application_status in {"APPROVED", "REJECTED"}:
                approved = application_status == "APPROVED"
                for suffix, event_type in (
                    (
                        "result-log",
                        (
                            "RECRUITMENT_APPLICATION_APPROVED_LOG"
                            if approved
                            else "RECRUITMENT_APPLICATION_REJECTED_LOG"
                        ),
                    ),
                    (
                        "result-dm",
                        (
                            "RECRUITMENT_APPLICATION_APPROVED"
                            if approved
                            else "RECRUITMENT_APPLICATION_REJECTED"
                        ),
                    ),
                ):
                    result_cursors.append(
                        await connection.execute(
                            """
                            INSERT INTO recruitment_notification_outbox(
                                guild_id, application_id, event_type, event_key,
                                payload_json, available_at, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(guild_id, event_key) DO NOTHING
                            """,
                            (
                                int(application["guild_id"]),
                                application_id,
                                event_type,
                                f"application-{suffix}:{application_id}:workflow-v3",
                                json.dumps(
                                    {
                                        "application_id": application_id,
                                        "protocol": protocol,
                                        "migration": "workflow-v3",
                                    },
                                    ensure_ascii=False,
                                ),
                                now,
                                now,
                            ),
                        )
                    )
            await audit.record(
                int(application["guild_id"]),
                "RECRUITMENT_APPLICATION_WORKFLOW_MIGRATED",
                target_id=int(application["discord_id"]),
                before={"protocol": protocol, "status": application_status},
                after={
                    "workflow": "v3",
                    "private_event_created": bool(
                        private_cursor and private_cursor.rowcount == 1
                    ),
                    "public_event_created": public_cursor.rowcount == 1,
                    "result_events_created": sum(
                        int(cursor.rowcount == 1) for cursor in result_cursors
                    ),
                },
                reason="Reencaminhamento ao quadro público e à mesa privada sem alterar a candidatura.",
                connection=connection,
                deliver_immediately=False,
            )
        print(
            "RECRUITMENT_REQUEUE_APPLY_PASS "
            f"protocol={protocol} "
            f"private_created={int(bool(private_cursor and private_cursor.rowcount == 1))} "
            f"public_created={int(public_cursor.rowcount == 1)} "
            f"result_created={sum(int(cursor.rowcount == 1) for cursor in result_cursors)}"
        )
        return 0
    finally:
        await database.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
