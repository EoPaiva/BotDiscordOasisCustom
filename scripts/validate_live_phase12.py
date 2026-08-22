from __future__ import annotations

import sqlite3
import sys

from choque.channel_names import format_channel_name
from choque.config import AppConfig
from scripts.remodel_discord_layout import (
    CATEGORY_SPECS,
    CHANNEL_SPECS,
    REGISTRY_SETTING,
)
from scripts.validate_live_phase5 import discord_get


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")

    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    try:
        registry_row = connection.execute(
            """
            SELECT value_json FROM guild_settings
            WHERE guild_id=? AND setting_key=?
            """,
            (config.default_guild_id, REGISTRY_SETTING),
        ).fetchone()
        if not registry_row:
            raise RuntimeError("Registro interno do layout não foi persistido.")
        import json

        registry = json.loads(registry_row["value_json"])
        authorized = connection.execute(
            """
            SELECT channel_id, label FROM authorized_voice_channels
            WHERE guild_id=? ORDER BY channel_id
            """,
            (config.default_guild_id,),
        ).fetchall()
        migration = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
        ticket_rooms = connection.execute(
            """
            SELECT ticket_id, channel_id, status FROM ticket_rooms
            WHERE guild_id=? ORDER BY ticket_id
            """,
            (config.default_guild_id,),
        ).fetchall()
    finally:
        connection.close()

    live = discord_get(f"/guilds/{config.default_guild_id}/channels", config.token)
    by_id = {int(channel["id"]): channel for channel in live}
    failures: list[str] = []

    category_ids = registry.get("categories", {})
    channel_ids = registry.get("channels", {})
    for spec in CATEGORY_SPECS:
        channel = by_id.get(int(category_ids.get(spec.key, 0)))
        if not channel or channel.get("type") != 4 or channel.get("name") != spec.visual_name:
            failures.append(f"category:{spec.key}")

    for spec in CHANNEL_SPECS:
        channel = by_id.get(int(channel_ids.get(spec.key, 0)))
        expected_type = 0 if spec.kind == "text" else 2
        expected_category = int(category_ids.get(spec.category, 0))
        if (
            not channel
            or channel.get("type") != expected_type
            or channel.get("name") != spec.visual_name
            or int(channel.get("parent_id") or 0) != expected_category
        ):
            failures.append(f"channel:{spec.key}")
            continue
        rendered_name = str(channel["name"]).split("・", 1)[-1]
        if any(
            character in rendered_name
            for character in ("_", "│", " ", "·", "•", chr(0x3164), chr(0x2800))
        ):
            failures.append(f"format:{spec.key}")

    patrol_category_id = int(category_ids.get("patrol", 0))
    for row in authorized:
        channel = by_id.get(int(row["channel_id"]))
        if not channel or int(channel.get("parent_id") or 0) != patrol_category_id:
            failures.append(f"authorized_category:{row['channel_id']}")
        elif row["label"] != channel.get("name"):
            failures.append(f"authorized_label:{row['channel_id']}")

    for row in ticket_rooms:
        ticket_id = int(row["ticket_id"])
        archived = str(row["status"]) == "ARCHIVED"
        label = f"Arquivo{ticket_id:04d}" if archived else f"Ticket{ticket_id:04d}"
        expected_name = format_channel_name(label, "📁" if archived else "🎫")
        channel = by_id.get(int(row["channel_id"]))
        if not channel or channel.get("type") != 0 or channel.get("name") != expected_name:
            failures.append(f"ticket_room:{ticket_id}")

    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )
    if commands:
        failures.append(f"commands={len(commands)}")
    if migration < 14:
        failures.append(f"migration={migration}")
    managed_content_ids = {
        int(value) for value in channel_ids.values()
    } | {int(row["channel_id"]) for row in ticket_rooms}
    live_content_ids = {
        int(channel["id"]) for channel in live if int(channel["type"]) in {0, 2}
    }
    if live_content_ids != managed_content_ids:
        failures.append(
            f"content_inventory=live:{len(live_content_ids)}/managed:{len(managed_content_ids)}"
        )

    print("LIVE_PHASE12_OK" if not failures else "LIVE_PHASE12_INVALID")
    print(f"categories={len(CATEGORY_SPECS)}")
    print(f"channels={len(CHANNEL_SPECS)}")
    print(f"live_items={len(live)}")
    print(f"authorized_patrol_calls={len(authorized)}")
    print(f"ticket_rooms={len(ticket_rooms)}")
    print(f"migration={migration}")
    print(f"commands={len(commands)}")
    if failures:
        print(f"failures={failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
