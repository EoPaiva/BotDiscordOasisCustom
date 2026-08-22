from __future__ import annotations

import asyncio
import json
import sys

from choque.audit import AuditService
from choque.config import AppConfig
from choque.database import Database
from choque.settings import SettingsService


async def run() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.default_guild_id:
        raise RuntimeError("DEFAULT_GUILD_ID é obrigatório.")
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        row = await database.fetchone(
            """
            SELECT value_json FROM guild_settings
            WHERE guild_id=? AND setting_key='minimum_patrol_minutes'
            """,
            (config.default_guild_id,),
        )
        if row:
            value = int(json.loads(row["value_json"]))
            if not 5 <= value <= 120:
                raise RuntimeError(
                    f"minimum_patrol_minutes persistido fora da faixa segura: {value}"
                )
            changed = False
        else:
            value = int(SettingsService.DEFAULTS["minimum_patrol_minutes"])
            async with database.transaction() as connection:
                await settings.set(
                    config.default_guild_id,
                    "minimum_patrol_minutes",
                    value,
                    None,
                    connection,
                )
                await audit.record(
                    config.default_guild_id,
                    "MINIMUM_PATROL_DEFAULT_PERSISTED",
                    after={"minimum_patrol_minutes": value},
                    connection=connection,
                )
            changed = True
        calls = await database.fetchall(
            """
            SELECT channel_id, service_allowed, counts_toward_patrol_minimum
            FROM authorized_voice_channels WHERE guild_id=?
            """,
            (config.default_guild_id,),
        )
        invalid_calls = [
            int(call["channel_id"])
            for call in calls
            if call["service_allowed"] not in (0, 1)
            or call["counts_toward_patrol_minimum"] not in (0, 1)
        ]
        if invalid_calls:
            raise RuntimeError(f"Calls com classificação inválida: {invalid_calls}")
        print("MINIMUM_PATROL_CONFIGURED")
        print(
            f"guild={config.default_guild_id} minimum_minutes={value} "
            f"persisted_now={int(changed)} calls={len(calls)}"
        )
        return 0
    finally:
        await database.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
