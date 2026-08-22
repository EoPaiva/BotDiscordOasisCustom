from __future__ import annotations

import sqlite3
import sys

from choque.config import AppConfig
from cogs.operations_commands import PatrolManagementView
from scripts.validate_live_phase5 import discord_get

EXPECTED_TABLES = {
    "patrol_commander_history",
    "patrol_operational_flags",
}
EXPECTED_COLUMNS = {
    "commander_member_id",
    "commander_assigned_at",
    "commander_assignment_source",
    "commander_manual_lock",
}
EXPECTED_CONTROLS = {
    "Encerrar patrulha",
    "Alterar comandante",
    "Regra de comando",
    "Prioridade",
    "Histórico",
}


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
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(patrols)").fetchall()
        }
        invalid_history = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT patrol_id, COUNT(*) AS total
                    FROM patrol_commander_history WHERE ended_at IS NULL
                    GROUP BY patrol_id HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
        )
        active_patrols = int(
            connection.execute(
                "SELECT COUNT(*) FROM patrols WHERE guild_id=? AND status='ACTIVE'",
                (config.default_guild_id,),
            ).fetchone()[0]
        )
    finally:
        connection.close()

    control_labels = {str(item.label) for item in PatrolManagementView().children}
    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )
    failures: list[str] = []
    if migration < 20:
        failures.append(f"migration={migration}")
    if missing := EXPECTED_TABLES - tables:
        failures.append(f"tables={sorted(missing)}")
    if missing := EXPECTED_COLUMNS - columns:
        failures.append(f"columns={sorted(missing)}")
    if control_labels != EXPECTED_CONTROLS:
        failures.append(f"controls={sorted(control_labels)}")
    if invalid_history:
        failures.append(f"multiple-open-history={invalid_history}")
    if commands:
        failures.append(f"commands={len(commands)}")

    print("PATROL_COMMANDER_LIVE_PASS" if not failures else "PATROL_COMMANDER_LIVE_INVALID")
    print(
        f"migration={migration} tables={len(EXPECTED_TABLES & tables)}/2 "
        f"columns={len(EXPECTED_COLUMNS & columns)}/4 controls={len(control_labels)}/5 "
        f"active_patrols={active_patrols} commands={len(commands)}"
    )
    if failures:
        print(f"failures={failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
