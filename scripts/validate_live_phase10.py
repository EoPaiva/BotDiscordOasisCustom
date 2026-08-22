from __future__ import annotations

import json
import sqlite3
import sys

from choque.config import AppConfig
from choque.settings import MODULE_DEFAULTS
from scripts.validate_live_phase5 import discord_get
from scripts.validate_live_phase6 import components, panel


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    connection = sqlite3.connect(config.database_path)
    try:
        config_panel = panel(connection, config.default_guild_id, "CONFIG")
        row = connection.execute(
            """
            SELECT value_json FROM guild_settings
            WHERE guild_id=? AND setting_key='module_flags'
            """,
            (config.default_guild_id,),
        ).fetchone()
        states = dict(MODULE_DEFAULTS)
        if row:
            states.update(
                {
                    key: bool(value)
                    for key, value in json.loads(row[0]).items()
                    if key in MODULE_DEFAULTS
                }
            )
        migration = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
    finally:
        connection.close()

    message = discord_get(
        f"/channels/{config_panel[0]}/messages/{config_panel[1]}", config.token
    )
    custom_ids = {component.get("custom_id") for component in components(message)}
    description = (message.get("embeds") or [{}])[0].get("description", "")
    fields = (message.get("embeds") or [{}])[0].get("fields", [])
    module_field = next((field for field in fields if field.get("name") == "Módulos"), None)
    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )

    failures: list[str] = []
    if "choque:config:modules:v1" not in custom_ids:
        failures.append("modules_button_missing")
    if "22/22" not in description:
        failures.append("configuration_progress_invalid")
    if not module_field:
        failures.append("module_status_field_missing")
    if set(states) != set(MODULE_DEFAULTS):
        failures.append("module_registry_invalid")
    if int(migration) != 7:
        failures.append(f"migration={migration}")
    if commands:
        failures.append(f"commands={len(commands)}")

    print("LIVE_PHASE10_OK" if not failures else "LIVE_PHASE10_INVALID")
    print(f"config_message={message['id']} components={len(components(message))}")
    print(f"modules_button={'choque:config:modules:v1' in custom_ids}")
    print(f"modules={states}")
    print(f"migration={migration}")
    print(f"commands={len(commands)}")
    if failures:
        print(f"failures={failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
