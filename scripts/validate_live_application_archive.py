from __future__ import annotations

import json
import sqlite3
import sys

from choque.config import AppConfig
from scripts.validate_live_phase5 import discord_get
from scripts.validate_live_phase6 import components, panel

VIEW_CHANNEL = 1 << 10
EXPECTED_COLUMNS = {
    "review_channel_id",
    "review_message_id",
    "result_channel_id",
    "result_message_id",
    "delivery_status",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")

    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    try:
        migration = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(member_applications)").fetchall()
        }
        settings = {
            row["setting_key"]: json.loads(row["value_json"])
            for row in connection.execute(
                """
                SELECT setting_key, value_json FROM guild_settings
                WHERE guild_id=? AND setting_key IN (
                    'registration_history_channel_id','discord_layout_registry_v2'
                )
                """,
                (config.default_guild_id,),
            ).fetchall()
        }
        legacy_reviews = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM member_applications
                WHERE guild_id=? AND status IN ('APPROVED','REJECTED')
                  AND delivery_status='LEGACY'
                """,
                (config.default_guild_id,),
            ).fetchone()[0]
        )
        undelivered = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM member_applications
                WHERE guild_id=? AND status IN ('APPROVED','REJECTED')
                  AND delivery_status='PENDING'
                """,
                (config.default_guild_id,),
            ).fetchone()[0]
        )
        admin_channel_id, admin_message_id = panel(
            connection,
            config.default_guild_id,
            "PERSONNEL_ADMIN",
        )
    finally:
        connection.close()

    registry = settings.get("discord_layout_registry_v2", {})
    history_id = int(settings.get("registration_history_channel_id") or 0)
    expected_history_id = int(registry.get("channels", {}).get("archive.members") or 0)
    archive_category_id = int(registry.get("categories", {}).get("archive") or 0)
    history_channel = discord_get(f"/channels/{history_id}", config.token)
    admin_message = discord_get(
        f"/channels/{admin_channel_id}/messages/{admin_message_id}",
        config.token,
    )
    default_overwrite = next(
        (
            item
            for item in history_channel.get("permission_overwrites", [])
            if int(item["type"]) == 0 and int(item["id"]) == config.default_guild_id
        ),
        None,
    )
    custom_ids = {
        item.get("custom_id") for item in components(admin_message) if item.get("custom_id")
    }

    failures: list[str] = []
    if migration < 14:
        failures.append(f"migration={migration}")
    if not EXPECTED_COLUMNS <= columns:
        failures.append(f"columns-missing={sorted(EXPECTED_COLUMNS - columns)}")
    if not history_id or history_id != expected_history_id:
        failures.append("history-setting-mismatch")
    if int(history_channel.get("parent_id") or 0) != archive_category_id:
        failures.append("history-outside-archive")
    if default_overwrite is None or not (int(default_overwrite["deny"]) & VIEW_CHANNEL):
        failures.append("history-visible-to-everyone")
    if undelivered:
        failures.append(f"undelivered={undelivered}")
    if "choque:personnel:applications:v1" not in custom_ids:
        failures.append("applications-button-missing")

    print("APPLICATION_ARCHIVE_LIVE_PASS" if not failures else "APPLICATION_ARCHIVE_LIVE_INVALID")
    print(f"migration={migration} columns={len(EXPECTED_COLUMNS & columns)}/{len(EXPECTED_COLUMNS)}")
    print(f"history_registry_match={history_id == expected_history_id}")
    print(
        "history_private="
        f"{default_overwrite is not None and bool(int(default_overwrite['deny']) & VIEW_CHANNEL)}"
    )
    print(f"legacy_reviews={legacy_reviews} undelivered={undelivered}")
    print(f"applications_button={'true' if 'choque:personnel:applications:v1' in custom_ids else 'false'}")
    if failures:
        print(f"failures={failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
