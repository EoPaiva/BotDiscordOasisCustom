from __future__ import annotations

import sqlite3
import sys

from choque.config import AppConfig
from scripts.validate_live_phase5 import discord_get
from scripts.validate_live_phase6 import components, panel


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    connection = sqlite3.connect(config.database_path)
    try:
        discipline = panel(connection, config.default_guild_id, "DISCIPLINE")
        admin = panel(connection, config.default_guild_id, "PERSONNEL_ADMIN")
        member_central = panel(connection, config.default_guild_id, "MEMBER_CENTRAL")
        migration = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
        configured = connection.execute(
            """
            SELECT value_json FROM guild_settings
            WHERE guild_id=? AND setting_key='discipline_panel_channel_id'
            """,
            (config.default_guild_id,),
        ).fetchone()
    finally:
        connection.close()

    discipline_channel = discord_get(f"/channels/{discipline[0]}", config.token)
    discipline_message = discord_get(
        f"/channels/{discipline[0]}/messages/{discipline[1]}", config.token
    )
    admin_message = discord_get(f"/channels/{admin[0]}/messages/{admin[1]}", config.token)
    central_message = discord_get(
        f"/channels/{member_central[0]}/messages/{member_central[1]}", config.token
    )
    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )

    discipline_ids = {
        component.get("custom_id") for component in components(discipline_message)
    }
    expected = {
        "choque:discipline:summary:v1",
        "choque:discipline:history:v1",
    }
    admin_ids = {component.get("custom_id") for component in components(admin_message)}
    central_labels = {component.get("label") for component in components(central_message)}
    failures: list[str] = []
    if expected - discipline_ids:
        failures.append(f"discipline_missing={sorted(expected - discipline_ids)}")
    if "choque:personnel:discipline:v1" not in admin_ids:
        failures.append("admin_discipline_button_missing")
    if "Disciplina" not in central_labels:
        failures.append("member_central_link_missing")
    if int(migration) != 5:
        failures.append(f"migration={migration}")
    if not configured or int(configured[0]) != discipline[0]:
        failures.append("discipline_channel_setting_invalid")
    if commands:
        failures.append(f"commands={len(commands)}")

    print("LIVE_PHASE7_OK" if not failures else "LIVE_PHASE7_INVALID")
    print(f"channel={discipline_channel['id']}:{discipline_channel['name']}")
    print(f"message={discipline_message['id']} components={len(components(discipline_message))}")
    print(f"admin_button={'choque:personnel:discipline:v1' in admin_ids}")
    print(f"member_link={'Disciplina' in central_labels}")
    print(f"migration={migration}")
    print(f"commands={len(commands)}")
    if failures:
        print(f"failures={failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
