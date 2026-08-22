from __future__ import annotations

import sqlite3
import sys

from choque.config import AppConfig
from scripts.validate_live_phase5 import discord_get


def panel(connection: sqlite3.Connection, guild_id: int, panel_type: str) -> tuple[int, int]:
    row = connection.execute(
        "SELECT channel_id, message_id FROM panels WHERE guild_id=? AND panel_type=?",
        (guild_id, panel_type),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Painel {panel_type} não registrado.")
    return int(row[0]), int(row[1])


def components(message: dict) -> list[dict]:
    return [component for row in message.get("components", []) for component in row["components"]]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    connection = sqlite3.connect(config.database_path)
    try:
        career = panel(connection, config.default_guild_id, "CAREER")
        admin = panel(connection, config.default_guild_id, "PERSONNEL_ADMIN")
        member_central = panel(connection, config.default_guild_id, "MEMBER_CENTRAL")
    finally:
        connection.close()

    career_channel = discord_get(f"/channels/{career[0]}", config.token)
    career_message = discord_get(f"/channels/{career[0]}/messages/{career[1]}", config.token)
    admin_message = discord_get(f"/channels/{admin[0]}/messages/{admin[1]}", config.token)
    central_message = discord_get(
        f"/channels/{member_central[0]}/messages/{member_central[1]}", config.token
    )
    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )

    career_ids = {component.get("custom_id") for component in components(career_message)}
    expected = {
        "choque:career:profile:v1",
        "choque:career:history:v1",
        "choque:career:hierarchy:v1",
    }
    admin_ids = {component.get("custom_id") for component in components(admin_message)}
    central_labels = {component.get("label") for component in components(central_message)}
    failures = []
    if expected - career_ids:
        failures.append(f"career_missing={sorted(expected - career_ids)}")
    if "choque:personnel:career:v1" not in admin_ids:
        failures.append("admin_career_button_missing")
    if "Carreira" not in central_labels:
        failures.append("member_central_link_missing")
    if commands:
        failures.append(f"commands={len(commands)}")

    print("LIVE_PHASE6_OK" if not failures else "LIVE_PHASE6_INVALID")
    print(f"channel={career_channel['id']}:{career_channel['name']}")
    print(f"message={career_message['id']} components={len(components(career_message))}")
    print(f"admin_button={'choque:personnel:career:v1' in admin_ids}")
    print(f"member_link={'Carreira' in central_labels}")
    print(f"commands={len(commands)}")
    if failures:
        print(f"failures={failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
