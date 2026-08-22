from __future__ import annotations

import json
import sqlite3
import sys

from choque.config import AppConfig
from choque.settings import MODULE_DEFAULTS
from scripts.validate_live_phase5 import discord_get
from scripts.validate_live_phase6 import components, panel

EXPECTED_COMPONENTS = {
    "RECRUITMENT": {
        "choque:recruitment:apply:v1",
        "choque:recruitment:mine:v1",
        "choque:recruitment:requirements:v1",
    },
    "TICKET": {
        "choque:ticket:candidacy:v1",
        "choque:ticket:transfer:v1",
        "choque:ticket:report:v1",
        "choque:ticket:other:v1",
        "choque:ticket:mine:v1",
    },
    "RECRUITMENT_ADMIN": {
        "choque:recruitment:admin:candidacies:v1",
        "choque:recruitment:admin:transfers:v1",
        "choque:recruitment:admin:refresh:v1",
    },
    "PERSONNEL_ADMIN": {"choque:personnel:tickets:v1"},
}

EXPECTED_SETTINGS = {
    "recruitment_requirements_channel_id",
    "recruitment_panel_channel_id",
    "ticket_panel_channel_id",
    "recruitment_queue_channel_id",
    "transfer_results_channel_id",
    "recruitment_approved_channel_id",
    "recruitment_rejected_channel_id",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")

    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    try:
        panel_rows = {
            panel_type: panel(connection, config.default_guild_id, panel_type)
            for panel_type in EXPECTED_COMPONENTS
        }
        settings = {
            row["setting_key"]: json.loads(row["value_json"])
            for row in connection.execute(
                """
                SELECT setting_key, value_json FROM guild_settings
                WHERE guild_id=? AND setting_key IN ({})
                """.format(",".join("?" for _ in EXPECTED_SETTINGS)),
                (config.default_guild_id, *sorted(EXPECTED_SETTINGS)),
            ).fetchall()
        }
        module_row = connection.execute(
            """
            SELECT value_json FROM guild_settings
            WHERE guild_id=? AND setting_key='module_flags'
            """,
            (config.default_guild_id,),
        ).fetchone()
        modules = dict(MODULE_DEFAULTS)
        if module_row:
            modules.update(
                {
                    key: bool(value)
                    for key, value in json.loads(module_row["value_json"]).items()
                    if key in MODULE_DEFAULTS
                }
            )
        migration = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
        real_tickets = int(
            connection.execute("SELECT COUNT(*) FROM service_tickets").fetchone()[0]
        )
    finally:
        connection.close()

    failures: list[str] = []
    found_components: dict[str, set[str]] = {}
    for panel_type, expected in EXPECTED_COMPONENTS.items():
        channel_id, message_id = panel_rows[panel_type]
        message = discord_get(f"/channels/{channel_id}/messages/{message_id}", config.token)
        custom_ids = {
            item.get("custom_id") for item in components(message) if item.get("custom_id")
        }
        found_components[panel_type] = custom_ids
        missing = expected - custom_ids
        if missing:
            failures.append(f"{panel_type.lower()}_missing={sorted(missing)}")

    missing_settings = EXPECTED_SETTINGS - {
        key for key, value in settings.items() if isinstance(value, int) and value > 0
    }
    if missing_settings:
        failures.append(f"settings_missing={sorted(missing_settings)}")
    if not modules.get("RECRUITMENT") or not modules.get("TICKETS"):
        failures.append("modules_disabled")
    if migration < 14:
        failures.append(f"migration={migration}")

    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )
    if commands:
        failures.append(f"commands={len(commands)}")

    print("LIVE_PHASE11_OK" if not failures else "LIVE_PHASE11_INVALID")
    for panel_type, custom_ids in found_components.items():
        print(f"{panel_type.lower()}_components={len(custom_ids)}")
    print(f"settings={len(EXPECTED_SETTINGS) - len(missing_settings)}/{len(EXPECTED_SETTINGS)}")
    print(f"modules=recruitment:{modules.get('RECRUITMENT')},tickets:{modules.get('TICKETS')}")
    print(f"migration={migration}")
    print(f"commands={len(commands)}")
    print(f"real_tickets={real_tickets}")
    if failures:
        print(f"failures={failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
