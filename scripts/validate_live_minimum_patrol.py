from __future__ import annotations

import json
import sqlite3
import sys

from choque.config import AppConfig
from scripts.validate_live_phase5 import discord_get


def _message(config: AppConfig, connection: sqlite3.Connection, panel_type: str):
    panel = connection.execute(
        "SELECT * FROM panels WHERE guild_id=? AND panel_type=?",
        (config.default_guild_id, panel_type),
    ).fetchone()
    if not panel:
        return None
    return discord_get(
        f"/channels/{panel['channel_id']}/messages/{panel['message_id']}",
        config.token,
    )


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
        setting = connection.execute(
            """
            SELECT value_json FROM guild_settings
            WHERE guild_id=? AND setting_key='minimum_patrol_minutes'
            """,
            (config.default_guild_id,),
        ).fetchone()
        calls = connection.execute(
            """
            SELECT channel_id, service_allowed, counts_toward_patrol_minimum
            FROM authorized_voice_channels WHERE guild_id=? ORDER BY channel_id
            """,
            (config.default_guild_id,),
        ).fetchall()
        shift_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(shifts)").fetchall()
        }
        segment_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(shift_segments)").fetchall()
        }
        override_table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='shift_validation_overrides'
            """
        ).fetchone()
        point_message = _message(config, connection, "POINT")
        config_message = _message(config, connection, "CONFIG")
    finally:
        connection.close()

    expected_shift_columns = {
        "minimum_patrol_ms",
        "patrol_duration_ms",
        "gross_duration_ms",
        "validation_status",
        "automatic_validation_status",
        "invalid_reason",
        "validation_source",
    }
    failures: list[str] = []
    minimum = int(json.loads(setting["value_json"])) if setting else 0
    if migration < 14:
        failures.append(f"migration={migration}")
    if not 5 <= minimum <= 120:
        failures.append(f"minimum={minimum}")
    if not expected_shift_columns <= shift_columns:
        failures.append("shift-columns")
    if "counts_toward_patrol_minimum" not in segment_columns:
        failures.append("segment-classification")
    if not override_table:
        failures.append("override-table")
    if any(
        row["service_allowed"] not in (0, 1)
        or row["counts_toward_patrol_minimum"] not in (0, 1)
        for row in calls
    ):
        failures.append("call-classification")

    point_text = " ".join(
        embed.get("description", "")
        + " "
        + " ".join(
            field.get("name", "") + " " + field.get("value", "")
            for field in embed.get("fields", [])
        )
        for embed in (point_message or {}).get("embeds", [])
    ).casefold()
    config_text = " ".join(
        field.get("value", "")
        for embed in (config_message or {}).get("embeds", [])
        for field in embed.get("fields", [])
    ).casefold()
    if "validação mínima" not in point_text:
        failures.append("point-panel-copy")
    if f"patrulha mínima: **{minimum} min**" not in config_text:
        failures.append("config-panel-minimum")

    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )
    if commands:
        failures.append(f"commands={len(commands)}")

    print("MINIMUM_PATROL_LIVE_PASS" if not failures else "MINIMUM_PATROL_LIVE_INVALID")
    print(
        f"migration={migration} minimum={minimum} calls={len(calls)} "
        f"shift_columns={len(expected_shift_columns & shift_columns)}/{len(expected_shift_columns)} "
        f"commands={len(commands)}"
    )
    if failures:
        print(f"failures={json.dumps(failures, ensure_ascii=False)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
