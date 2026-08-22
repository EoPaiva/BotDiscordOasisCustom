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
        activity = panel(connection, config.default_guild_id, "ACTIVITY")
        admin = panel(connection, config.default_guild_id, "PERSONNEL_ADMIN")
        member_central = panel(connection, config.default_guild_id, "MEMBER_CENTRAL")
        migration = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
        configured = connection.execute(
            """
            SELECT value_json FROM guild_settings
            WHERE guild_id=? AND setting_key='activity_panel_channel_id'
            """,
            (config.default_guild_id,),
        ).fetchone()
    finally:
        connection.close()

    activity_channel = discord_get(f"/channels/{activity[0]}", config.token)
    activity_message = discord_get(
        f"/channels/{activity[0]}/messages/{activity[1]}", config.token
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

    activity_ids = {component.get("custom_id") for component in components(activity_message)}
    expected = {
        "choque:activity:mine:v1",
        "choque:activity:board:v1",
        "choque:activity:history:v1",
    }
    admin_ids = {component.get("custom_id") for component in components(admin_message)}
    central_labels = {component.get("label") for component in components(central_message)}
    failures: list[str] = []
    if expected - activity_ids:
        failures.append(f"activity_missing={sorted(expected - activity_ids)}")
    if "choque:personnel:activity:v1" not in admin_ids:
        failures.append("admin_activity_button_missing")
    if "Atividade" not in central_labels:
        failures.append("member_central_link_missing")
    if int(migration) != 7:
        failures.append(f"migration={migration}")
    if not configured or int(configured[0]) != activity[0]:
        failures.append("activity_channel_setting_invalid")
    if commands:
        failures.append(f"commands={len(commands)}")

    print("LIVE_PHASE9_OK" if not failures else "LIVE_PHASE9_INVALID")
    print(f"channel={activity_channel['id']}:{activity_channel['name']}")
    print(f"message={activity_message['id']} components={len(components(activity_message))}")
    print(f"admin_button={'choque:personnel:activity:v1' in admin_ids}")
    print(f"member_link={'Atividade' in central_labels}")
    print(f"migration={migration}")
    print(f"commands={len(commands)}")
    if failures:
        print(f"failures={failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
