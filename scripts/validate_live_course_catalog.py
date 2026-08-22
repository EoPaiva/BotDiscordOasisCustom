from __future__ import annotations

import hashlib
import json
import sqlite3
import sys

from choque.config import AppConfig
from choque.course_catalog_seed import HISTORICAL_COURSE_CHANNEL_ID, HISTORICAL_COURSES
from scripts.validate_live_phase5 import discord_get


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
        courses = connection.execute(
            "SELECT * FROM course_catalog WHERE guild_id=? AND active=1 ORDER BY id",
            (config.default_guild_id,),
        ).fetchall()
        requirements = connection.execute(
            """
            SELECT * FROM course_requirements
            WHERE guild_id=? AND active=1 ORDER BY course_id, sort_order
            """,
            (config.default_guild_id,),
        ).fetchall()
        panel = connection.execute(
            "SELECT * FROM panels WHERE guild_id=? AND panel_type='COURSE_CATALOG'",
            (config.default_guild_id,),
        ).fetchone()
    finally:
        connection.close()

    failures: list[str] = []
    if migration < 14:
        failures.append(f"migration={migration}")
    if len(courses) != 9:
        failures.append(f"courses={len(courses)}")
    if len(requirements) != 10:
        failures.append(f"requirements={len(requirements)}")
    if panel is None or int(panel["channel_id"]) != HISTORICAL_COURSE_CHANNEL_ID:
        failures.append("catalog-panel-missing-or-wrong-channel")

    live_roles = {
        int(role["id"])
        for role in discord_get(f"/guilds/{config.default_guild_id}/roles", config.token)
    }
    missing_role_ids = {
        *(int(course["course_role_id"]) for course in courses),
        *(int(requirement["required_role_id"]) for requirement in requirements),
    } - live_roles
    if missing_role_ids:
        failures.append(f"roles-missing={len(missing_role_ids)}")

    live_messages = discord_get(
        f"/channels/{HISTORICAL_COURSE_CHANNEL_ID}/messages?limit=100", config.token
    )
    by_id = {int(message["id"]): message for message in live_messages}
    for course in courses:
        source = by_id.get(int(course["source_message_id"]))
        if source is None:
            failures.append(f"source-missing:{course['source_message_id']}")
            continue
        digest = hashlib.sha256(str(source.get("content") or "").encode("utf-8")).hexdigest()
        if digest != course["source_content_sha256"]:
            failures.append(f"source-changed:{course['source_message_id']}")

    panel_message = None
    if panel is not None:
        panel_message = discord_get(
            f"/channels/{panel['channel_id']}/messages/{panel['message_id']}", config.token
        )
    custom_ids = {
        component.get("custom_id")
        for row in (panel_message or {}).get("components", [])
        for component in row.get("components", [])
    }
    expected_custom_ids = {
        f"choque:course:apply:{seed.internal_code}:v1" for seed in HISTORICAL_COURSES
    }
    if custom_ids != expected_custom_ids:
        failures.append(f"buttons={len(custom_ids)}/{len(expected_custom_ids)}")
    fields = (panel_message or {}).get("embeds", [{}])[0].get("fields", [])
    if len(fields) != 9:
        failures.append(f"embed-fields={len(fields)}")

    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )
    if commands:
        failures.append(f"commands={len(commands)}")

    print("COURSE_CATALOG_LIVE_PASS" if not failures else "COURSE_CATALOG_LIVE_INVALID")
    print(
        f"migration={migration} courses={len(courses)} requirements={len(requirements)} "
        f"historical_sources={sum(seed.source_message_id in by_id for seed in HISTORICAL_COURSES)}/9"
    )
    print(
        f"panel_fields={len(fields)} buttons={len(custom_ids)} "
        f"roles_missing={len(missing_role_ids)} commands={len(commands)}"
    )
    if failures:
        print(f"failures={json.dumps(failures, ensure_ascii=False)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
