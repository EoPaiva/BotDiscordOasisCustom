from __future__ import annotations

import json
import sqlite3
import sys

from choque.config import AppConfig
from scripts.validate_live_phase5 import discord_get

VIEW_CHANNEL = 1 << 10


def has_permission(overwrite: dict[str, object], field: str, permission: int) -> bool:
    return bool(int(str(overwrite[field])) & permission)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")

    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    try:
        room = connection.execute(
            """
            SELECT room.*, ticket.status AS ticket_status, ticket.ticket_type,
                   ticket.discord_id
            FROM ticket_rooms AS room
            JOIN service_tickets AS ticket ON ticket.id=room.ticket_id
            WHERE room.guild_id=?
            ORDER BY room.id DESC LIMIT 1
            """,
            (config.default_guild_id,),
        ).fetchone()
        settings = {
            row["setting_key"]: json.loads(row["value_json"])
            for row in connection.execute(
                """
                SELECT setting_key, value_json FROM guild_settings
                WHERE guild_id=? AND setting_key IN (
                    'ticket_active_category_id','ticket_archive_category_id',
                    'ticket_responsible_role_id'
                )
                """,
                (config.default_guild_id,),
            ).fetchall()
        }
        command_roles = {
            int(row["role_id"])
            for row in connection.execute(
                """
                SELECT role_id FROM rbac_bindings
                WHERE guild_id=? AND profile IN ('COMANDO','ADMINISTRADOR')
                """,
                (config.default_guild_id,),
            ).fetchall()
        }
        migration = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
        participant_ids = {
            int(row["discord_id"])
            for row in connection.execute(
                """
                SELECT discord_id FROM ticket_participants
                WHERE guild_id=? AND ticket_id=? AND removed_at IS NULL
                """,
                (config.default_guild_id, room["ticket_id"] if room else 0),
            ).fetchall()
        }
    finally:
        connection.close()

    if room is None:
        raise RuntimeError("Sala real não encontrada para validação.")
    channel = discord_get(f"/channels/{room['channel_id']}", config.token)
    message = discord_get(
        f"/channels/{room['channel_id']}/messages/{room['control_message_id']}",
        config.token,
    )
    bot_user = discord_get("/users/@me", config.token)

    overwrites = channel.get("permission_overwrites", [])
    role_overwrites = {int(item["id"]): item for item in overwrites if int(item["type"]) == 0}
    user_overwrites = {int(item["id"]): item for item in overwrites if int(item["type"]) == 1}
    default = role_overwrites.get(config.default_guild_id)
    requester = user_overwrites.get(int(room["discord_id"]))
    bot = user_overwrites.get(int(bot_user["id"]))
    custom_ids = {
        item.get("custom_id")
        for row in message.get("components", [])
        for item in row.get("components", [])
    }

    failures: list[str] = []
    if migration < 22:
        failures.append(f"migration={migration}")
    expected_category = (
        settings.get("ticket_archive_category_id")
        if room["status"] == "ARCHIVED"
        else settings.get("ticket_active_category_id")
    )
    if int(channel.get("parent_id") or 0) != int(expected_category or 0):
        failures.append("wrong-category")
    if default is None or not has_permission(default, "deny", VIEW_CHANNEL):
        failures.append("everyone-not-denied")
    if room["status"] == "ARCHIVED":
        if requester is not None and has_permission(requester, "allow", VIEW_CHANNEL):
            failures.append("archived-requester-allowed")
    elif requester is None or not has_permission(requester, "allow", VIEW_CHANNEL):
        failures.append("requester-not-allowed")
    if bot is None or not has_permission(bot, "allow", VIEW_CHANNEL):
        failures.append("bot-not-allowed")
    missing_command_roles = {
        role_id
        for role_id in command_roles
        if role_id not in role_overwrites
        or not has_permission(role_overwrites[role_id], "allow", VIEW_CHANNEL)
    }
    if missing_command_roles:
        failures.append(f"command-roles-missing={len(missing_command_roles)}")
    responsible_id = settings.get("ticket_responsible_role_id")
    responsible = role_overwrites.get(int(responsible_id)) if responsible_id else None
    if room["status"] == "OPEN":
        if responsible is None or not has_permission(responsible, "allow", VIEW_CHANNEL):
            failures.append("responsible-role-not-allowed")
    elif (
        responsible_id not in command_roles
        and responsible is not None
        and has_permission(responsible, "allow", VIEW_CHANNEL)
    ):
        failures.append("archived-responsible-role-allowed")
    unexpected_users = set(user_overwrites) - {
        int(room["discord_id"]),
        int(bot_user["id"]),
        *participant_ids,
    }
    if unexpected_users:
        failures.append(f"unexpected-user-overwrites={len(unexpected_users)}")
    required_controls = {
        "choque:ticket:room:claim:v1",
        "choque:ticket:room:priority:v1",
        "choque:ticket:room:add:v1",
        "choque:ticket:room:remove:v1",
        "choque:ticket:room:notify:v1",
        "choque:ticket:room:transcript:v1",
        "choque:ticket:room:reopen:v1",
        "choque:ticket:room:close:v1",
    }
    if not required_controls <= custom_ids:
        failures.append("ticket-controls-missing")
    if room["status"] == "OPEN" and room["ticket_status"] not in {"PENDING", "IN_REVIEW"}:
        failures.append(f"ticket-status={room['ticket_status']}")
    if room["status"] == "ARCHIVED" and room["ticket_status"] in {"PENDING", "IN_REVIEW"}:
        failures.append(f"archived-ticket-status={room['ticket_status']}")

    print("TICKET_ROOM_LIVE_PASS" if not failures else "TICKET_ROOM_LIVE_INVALID")
    print(f"migration={migration}")
    print(f"room_status={room['status']} ticket_status={room['ticket_status']}")
    print(
        "privacy="
        f"everyone_denied:{default is not None and has_permission(default, 'deny', VIEW_CHANNEL)},"
        f"requester_allowed:{requester is not None and has_permission(requester, 'allow', VIEW_CHANNEL)},"
        f"requester_denied:{requester is not None and has_permission(requester, 'deny', VIEW_CHANNEL)},"
        f"bot_allowed:{bot is not None and has_permission(bot, 'allow', VIEW_CHANNEL)},"
        f"command_roles:{len(command_roles) - len(missing_command_roles)}/{len(command_roles)}"
    )
    print(f"controls={len(required_controls & custom_ids)}/{len(required_controls)}")
    if failures:
        print(f"failures={failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
