from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.dismissals import enqueue_dismissal_notification  # noqa: E402


async def run(*, guild_id: int, apply: bool) -> int:
    config = AppConfig.load()
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        dismissed = await database.fetchall(
            """
            SELECT
                member.guild_id,
                member.discord_id,
                member.character_id,
                punishment.id AS punishment_id,
                punishment.created_by AS actor_id,
                punishment.created_at AS occurred_at
            FROM members AS member
            JOIN punishments AS punishment
              ON punishment.id=(
                  SELECT latest.id
                  FROM punishments AS latest
                  WHERE latest.guild_id=member.guild_id
                    AND latest.member_id=member.id
                    AND latest.punishment_type='DISMISSAL'
                  ORDER BY latest.created_at DESC, latest.id DESC
                  LIMIT 1
              )
            WHERE member.guild_id=? AND member.status='DISMISSED'
            ORDER BY member.id
            """,
            (guild_id,),
        )
        notifications = await database.fetchall(
            """
            SELECT payload_json FROM career_notifications
            WHERE guild_id=? AND notification_type='DISMISSAL'
            """,
            (guild_id,),
        )
        already_recorded: set[int] = set()
        for notification in notifications:
            try:
                payload = json.loads(str(notification["payload_json"]))
                already_recorded.add(int(payload["discord_id"]))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue

        missing = [row for row in dismissed if int(row["discord_id"]) not in already_recorded]
        print(
            "DISMISSAL_BACKFILL_PLAN "
            f"guild={guild_id} dismissed={len(dismissed)} existing={len(already_recorded)} "
            f"missing={len(missing)} mode={'APPLY' if apply else 'DRY_RUN'}"
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
            for row in missing:
                punishment_id = int(row["punishment_id"])
                await enqueue_dismissal_notification(
                    connection,
                    guild_id=guild_id,
                    subject_id=punishment_id,
                    discord_id=int(row["discord_id"]),
                    actor_id=int(row["actor_id"]),
                    occurred_at=int(row["occurred_at"]),
                    source="PUNISHMENT",
                    correlation_id=(
                        f"dismissal-retroactive-punishment-{guild_id}-{punishment_id}"
                    ),
                )
        print(f"DISMISSAL_BACKFILL_APPLIED guild={guild_id} inserted={len(missing)}")
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
