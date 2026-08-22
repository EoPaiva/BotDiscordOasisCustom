from __future__ import annotations

import json
import sqlite3
import sys

from choque.config import AppConfig
from scripts.validate_live_phase5 import discord_get

PHASE15_TABLES = {
    "member_operational_status",
    "patrol_channels",
    "patrols",
    "patrol_members",
    "patrol_queue_entries",
    "patrol_feedback",
    "operational_flags",
    "integrity_findings",
    "training_evaluations",
    "recruit_evaluations",
    "activity_swap_requests",
    "module_maintenance",
    "domain_events",
}


def message_custom_ids(channel_id: int, message_id: int, token: str) -> set[str]:
    message = discord_get(f"/channels/{channel_id}/messages/{message_id}", token)
    return {
        str(component["custom_id"])
        for row in message.get("components", [])
        for component in row.get("components", [])
        if component.get("custom_id")
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
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        registry_row = connection.execute(
            """
            SELECT value_json FROM guild_settings
            WHERE guild_id=? AND setting_key='discord_layout_registry_v2'
            """,
            (config.default_guild_id,),
        ).fetchone()
        registry = json.loads(registry_row["value_json"]) if registry_row else {}
        channel_registry = registry.get("channels", {}) if isinstance(registry, dict) else {}
        patrol_channels = connection.execute(
            """
            SELECT pc.*, av.service_allowed, av.counts_toward_patrol_minimum
            FROM patrol_channels pc
            LEFT JOIN authorized_voice_channels av
              ON av.guild_id=pc.guild_id AND av.channel_id=pc.channel_id
            WHERE pc.guild_id=? AND pc.enabled=1 ORDER BY pc.channel_type, pc.sort_order
            """,
            (config.default_guild_id,),
        ).fetchall()
        panels = {
            row["panel_type"]: row
            for row in connection.execute(
                """
                SELECT * FROM panels WHERE guild_id=?
                  AND panel_type IN ('PATROL_CENTRAL','PATROL_REPORT','MEMBER_CENTRAL')
                """,
                (config.default_guild_id,),
            ).fetchall()
        }
    finally:
        connection.close()

    failures: list[str] = []
    if migration < 15:
        failures.append(f"migration={migration}")
    missing_tables = PHASE15_TABLES - tables
    if missing_tables:
        failures.append(f"tables-missing={sorted(missing_tables)}")
    waiting = [row for row in patrol_channels if row["channel_type"] == "WAITING"]
    active = [row for row in patrol_channels if row["channel_type"] == "ACTIVE"]
    if len(waiting) != 1:
        failures.append(f"waiting-calls={len(waiting)}")
    if len(active) < 1:
        failures.append("active-calls=0")
    if waiting and (
        waiting[0]["service_allowed"] != 1
        or waiting[0]["counts_toward_patrol_minimum"] != 0
    ):
        failures.append("waiting-policy")
    if any(
        row["service_allowed"] != 1 or row["counts_toward_patrol_minimum"] != 1
        for row in active
    ):
        failures.append("active-policy")

    expected_channels = {
        "PATROL_CENTRAL": channel_registry.get("patrol.availability"),
        "PATROL_REPORT": channel_registry.get("patrol.report"),
        "MEMBER_CENTRAL": channel_registry.get("member.central"),
    }
    expected_buttons = {
        "PATROL_CENTRAL": {
            "choque:operations:available:v1",
            "choque:operations:unavailable:v1",
            "choque:operations:queue:join:v1",
            "choque:operations:queue:leave:v1",
            "choque:operations:patrol:mine:v1",
            "choque:operations:patrol:active:v1",
            "choque:operations:patrol:history:v1",
            "choque:operations:status:mine:v1",
        },
        "PATROL_REPORT": {
            "choque:operations:report:last:v1",
            "choque:operations:report:feedback:v1",
            "choque:operations:report:feedback-mine:v1",
        },
        "MEMBER_CENTRAL": {
            "choque:operations:member:patrol:v1",
            "choque:operations:member:qualifications:v1",
            "choque:operations:member:identity:v1",
            "choque:operations:member:swap:v1",
            "choque:operations:member:swap-response:v1",
        },
    }
    panel_button_counts: dict[str, int] = {}
    for panel_type, channel_id in expected_channels.items():
        panel = panels.get(panel_type)
        if not panel or not channel_id or int(panel["channel_id"]) != int(channel_id):
            failures.append(f"panel={panel_type}")
            continue
        custom_ids = message_custom_ids(
            int(panel["channel_id"]), int(panel["message_id"]), config.token
        )
        panel_button_counts[panel_type] = len(custom_ids)
        if not expected_buttons[panel_type] <= custom_ids:
            failures.append(f"buttons={panel_type}")

    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )
    if commands:
        failures.append(f"commands={len(commands)}")

    print(
        "INTELLIGENT_OPERATIONS_LIVE_PASS"
        if not failures
        else "INTELLIGENT_OPERATIONS_LIVE_INVALID"
    )
    print(
        f"migration={migration} tables={len(PHASE15_TABLES & tables)}/{len(PHASE15_TABLES)} "
        f"waiting={len(waiting)} active={len(active)} panels={len(panels)}/3 "
        f"buttons={json.dumps(panel_button_counts, sort_keys=True)} commands={len(commands)}"
    )
    if failures:
        print(f"failures={json.dumps(failures, ensure_ascii=False)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
