from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.dismissals import (  # noqa: E402
    backfill_historical_dismissals,
    missing_historical_dismissals,
)


async def run(*, guild_id: int, apply: bool) -> int:
    config = AppConfig.load()
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        async with database.transaction() as connection:
            missing = await missing_historical_dismissals(connection, guild_id)
        print(
            "DISMISSAL_BACKFILL_PLAN "
            f"guild={guild_id} missing={len(missing)} mode={'APPLY' if apply else 'DRY_RUN'}"
        )
        for row in missing:
            print(
                "DISMISSAL_BACKFILL_ITEM "
                f"discord_id={int(row['discord_id'])} "
                f"character_id={str(row['character_id'] or 'Não informado')} "
                f"punishment_id={int(row['punishment_id'])}"
            )

        if not apply:
            return 0

        async with database.transaction() as connection:
            inserted = await backfill_historical_dismissals(connection, guild_id)
        print(f"DISMISSAL_BACKFILL_APPLIED guild={guild_id} inserted={inserted}")
        return 0
    finally:
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cria notificações duráveis para desligamentos históricos sem publicação."
    )
    parser.add_argument("--guild-id", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(guild_id=args.guild_id, apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
