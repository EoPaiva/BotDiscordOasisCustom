from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from choque.config import AppConfig

API_BASE = "https://discord.com/api/v10"


def discord_get(path: str, token: str) -> object:
    request = Request(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bot {token}", "User-Agent": "CHOQUE-BGR-QA/1.0"},
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed Discord API base
        return json.load(response)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    database_path = Path(config.database_path)
    connection = sqlite3.connect(database_path)
    try:
        settings = dict(
            connection.execute(
                """
                SELECT setting_key, value_json FROM guild_settings
                WHERE guild_id=? AND setting_key IN (
                    'requests_panel_channel_id','away_role_id',
                    'reserve_role_id','suspended_role_id'
                )
                """,
                (config.default_guild_id,),
            )
        )
        panel = connection.execute(
            """
            SELECT channel_id, message_id FROM panels
            WHERE guild_id=? AND panel_type='REQUESTS'
            """,
            (config.default_guild_id,),
        ).fetchone()
        migration = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    finally:
        connection.close()
    if not panel:
        raise RuntimeError("Painel REQUESTS não registrado.")

    channel_id, message_id = map(int, panel)
    channel = discord_get(f"/channels/{channel_id}", config.token)
    message = discord_get(f"/channels/{channel_id}/messages/{message_id}", config.token)
    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )
    roles = discord_get(f"/guilds/{config.default_guild_id}/roles", config.token)

    components = [
        component for row in message.get("components", []) for component in row["components"]
    ]
    custom_ids = {component.get("custom_id") for component in components}
    expected = {
        "choque:requests:absence:v1",
        "choque:requests:return:v1",
        "choque:requests:reserve:v1",
        "choque:requests:hours:v1",
        "choque:requests:data:v1",
        "choque:requests:dismissal:v1",
        "choque:requests:mine:v1",
    }
    missing = expected - custom_ids
    role_names = {str(role["id"]): role["name"] for role in roles}
    configured_roles = {
        key: role_names.get(str(json.loads(raw_value)))
        for key, raw_value in settings.items()
        if key.endswith("role_id")
    }

    print("LIVE_PHASE5_OK" if not missing and not commands else "LIVE_PHASE5_INVALID")
    print(f"migration={migration}")
    print(f"channel={channel['id']}:{channel['name']}")
    print(f"message={message['id']} components={len(components)} missing={sorted(missing)}")
    print(f"commands={len(commands)}")
    print(f"roles={configured_roles}")
    return 0 if not missing and not commands else 1


if __name__ == "__main__":
    raise SystemExit(main())
