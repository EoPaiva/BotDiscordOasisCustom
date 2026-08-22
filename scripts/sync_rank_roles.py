from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService
from choque.config import AppConfig
from choque.database import Database
from choque.settings import SettingsService
from cogs.config_ui import (
    IGNORED_RANK_ROLE_NAMES,
    RoleChoice,
    detect_military_rank_roles,
    normalize_rank_name,
    reconcile_military_rank_roles,
)
from scripts.validate_live_phase5 import discord_get


def fetch_role_choices(config: AppConfig) -> list[RoleChoice]:
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    payload = discord_get(f"/guilds/{config.default_guild_id}/roles", config.token)
    if not isinstance(payload, list):
        raise RuntimeError("A API do Discord não retornou a lista de cargos esperada.")
    return [
        RoleChoice(
            role_id=int(role["id"]),
            name=str(role["name"]),
            position=int(role["position"]),
            managed=bool(role["managed"]),
        )
        for role in payload
        if str(role["name"]) != "@everyone"
    ]


async def apply_sync(config: AppConfig, choices: list[RoleChoice]) -> None:
    database = Database(Path(config.database_path))
    await database.open()
    try:
        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        created, updated, detected = await reconcile_military_rank_roles(
            database,
            audit,
            guild_id=int(config.default_guild_id),
            choices=choices,
            actor_id=None,
        )
        print(f"SYNC_APPLIED created={created} updated={updated} active={len(detected)}")
    finally:
        await database.close()


def validate_sync(config: AppConfig, choices: list[RoleChoice]) -> bool:
    detected = detect_military_rank_roles(choices)
    expected_role_ids = [choice.role_id for choice, _ in detected]
    ignored = [
        choice
        for choice in choices
        if normalize_rank_name(choice.name) in IGNORED_RANK_ROLE_NAMES
    ]
    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    try:
        active = connection.execute(
            """
            SELECT level, name, discord_role_id FROM ranks
            WHERE guild_id=? AND active=1 ORDER BY level
            """,
            (config.default_guild_id,),
        ).fetchall()
        panel = connection.execute(
            """
            SELECT channel_id, message_id FROM panels
            WHERE guild_id=? AND panel_type='HIERARCHY'
            """,
            (config.default_guild_id,),
        ).fetchone()
    finally:
        connection.close()

    active_role_ids = [int(row["discord_role_id"]) for row in active]
    sequential_levels = [int(row["level"]) for row in active] == list(
        range(1, len(active) + 1)
    )
    panel_fields = -1
    panel_has_all_roles = False
    if panel and config.token:
        message = discord_get(
            f"/channels/{panel['channel_id']}/messages/{panel['message_id']}", config.token
        )
        embeds = message.get("embeds", []) if isinstance(message, dict) else []
        fields = embeds[0].get("fields", []) if embeds else []
        panel_fields = len(fields)
        rendered = "\n".join(str(field.get("value", "")) for field in fields)
        panel_has_all_roles = all(f"<@&{role_id}>" in rendered for role_id in expected_role_ids)

    valid = (
        active_role_ids == expected_role_ids
        and sequential_levels
        and panel_fields == len(expected_role_ids)
        and panel_has_all_roles
    )
    print("LIVE_RANKS_OK" if valid else "LIVE_RANKS_INVALID")
    print(f"recognized={len(expected_role_ids)} active_database={len(active_role_ids)}")
    print(f"ignored={[choice.name for choice in ignored]}")
    print(f"panel_fields={panel_fields} sequential_levels={sequential_levels}")
    for row in active:
        print(f"{int(row['level']):02d} {row['name']} role_id={row['discord_role_id']}")
    return valid


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Sincroniza as patentes com a posição real dos cargos do Discord."
    )
    parser.add_argument("--apply", action="store_true", help="Aplica a sincronização no banco.")
    args = parser.parse_args()
    config = AppConfig.load()
    choices = fetch_role_choices(config)
    if args.apply:
        asyncio.run(apply_sync(config, choices))
        return 0
    return 0 if validate_sync(config, choices) else 1


if __name__ == "__main__":
    raise SystemExit(main())
