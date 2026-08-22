from __future__ import annotations

import asyncio
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from choque.config import AppConfig
from choque.rank_sync import format_member_nickname

API_BASE = "https://discord.com/api/v10"
COUNT_PATTERN = re.compile(r"<@&(\d+)>.*?•\s*(\d+)\s+membro", re.DOTALL)


async def api_get(
    session: aiohttp.ClientSession, path: str, params: dict[str, str] | None = None
) -> Any:
    async with session.get(f"{API_BASE}{path}", params=params) as response:
        if response.status != 200:
            body = await response.text()
            raise RuntimeError(f"Discord API {response.status} em {path}: {body[:300]}")
        return await response.json()


async def fetch_all_members(session: aiohttp.ClientSession, guild_id: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    after = "0"
    while True:
        page = await api_get(
            session,
            f"/guilds/{guild_id}/members",
            {"limit": "1000", "after": after},
        )
        result.extend(page)
        if len(page) < 1000:
            return result
        after = str(page[-1]["user"]["id"])


def database_state(path: Path, guild_id: int) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        version = int(
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        )
        ranks = [
            dict(row)
            for row in connection.execute(
                """
                SELECT id, level, name, prefix, discord_role_id
                FROM ranks
                WHERE guild_id=? AND active=1 AND discord_role_id IS NOT NULL
                ORDER BY level DESC
                """,
                (guild_id,),
            )
        ]
        members = [
            dict(row)
            for row in connection.execute(
                """
                SELECT m.discord_id, m.mta_nick, m.character_id, m.rank_id, m.status,
                       m.rank_sync_status, r.prefix, r.discord_role_id
                FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
                WHERE m.guild_id=?
                ORDER BY m.id
                """,
                (guild_id,),
            )
        ]
        panel = connection.execute(
            """
            SELECT channel_id, message_id FROM panels
            WHERE guild_id=? AND panel_type='HIERARCHY'
            """,
            (guild_id,),
        ).fetchone()
        nickname_errors = {
            int(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT target_id FROM audit_logs
                WHERE guild_id=? AND action='NICKNAME_PERMISSION_ERROR'
                  AND target_id IS NOT NULL
                """,
                (guild_id,),
            )
        }
        event_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM rank_sync_events WHERE guild_id=?", (guild_id,)
            ).fetchone()[0]
        )
        companion_row = connection.execute(
            """
            SELECT value_json FROM guild_settings
            WHERE guild_id=? AND setting_key='companion_role_id'
            """,
            (guild_id,),
        ).fetchone()
        companion_role_id = int(str(companion_row[0]).strip('"')) if companion_row else None
    finally:
        connection.close()
    return {
        "version": version,
        "ranks": ranks,
        "members": members,
        "panel": dict(panel) if panel else None,
        "nickname_errors": nickname_errors,
        "event_count": event_count,
        "companion_role_id": companion_role_id,
    }


async def main() -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    guild_id = config.default_guild_id
    state = database_state(config.database_path, guild_id)
    headers = {"Authorization": f"Bot {config.token}", "User-Agent": "CHOQUE-BGR-RankSync/1.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        discord_members = await fetch_all_members(session, guild_id)
        panel_message = None
        if state["panel"]:
            panel_message = await api_get(
                session,
                f"/channels/{state['panel']['channel_id']}/messages/{state['panel']['message_id']}",
            )

    member_by_id = {int(item["user"]["id"]): item for item in discord_members}
    rank_by_role = {int(row["discord_role_id"]): row for row in state["ranks"]}
    failures: list[str] = []
    warnings: list[str] = []
    for record in state["members"]:
        discord_id = int(record["discord_id"])
        live = member_by_id.get(discord_id)
        if not live:
            warnings.append(f"membro {discord_id} não retornou na listagem da guild")
            continue
        if str(record["status"]) == "DISMISSED":
            continue
        live_role_ids = {int(role_id) for role_id in live["roles"]}
        live_ranks = sorted(
            (
                rank_by_role[int(role_id)]
                for role_id in live["roles"]
                if int(role_id) in rank_by_role
            ),
            key=lambda row: int(row["level"]),
            reverse=True,
        )
        expected_rank_id = int(live_ranks[0]["id"]) if live_ranks else None
        # KEEP_LAST intentionally preserves the historical rank when the
        # current Discord role is absent; only a present live rank must win.
        if expected_rank_id is not None and expected_rank_id != record["rank_id"]:
            failures.append(f"membro {discord_id}: banco não corresponde ao maior cargo Discord")
        nickname_prefix = str(record["prefix"] or "")
        if state["companion_role_id"] in live_role_ids:
            nickname_prefix = "COMP.F"
        expected_nick = format_member_nickname(
            nickname_prefix,
            str(record["mta_nick"]),
            str(record["character_id"] or ""),
        )
        if live.get("nick") != expected_nick:
            message = f"membro {discord_id}: apelido esperado não pôde ser aplicado"
            if discord_id in state["nickname_errors"]:
                warnings.append(message + "; falha de hierarquia auditada")
            else:
                failures.append(message + "; sem auditoria correspondente")

    if panel_message and panel_message.get("embeds"):
        fields = panel_message["embeds"][0].get("fields", [])
        rendered_counts: dict[int, int] = {}
        for field in fields:
            match = COUNT_PATTERN.search(str(field.get("value", "")))
            if match:
                rendered_counts[int(match.group(1))] = int(match.group(2))
        for role_id in rank_by_role:
            live_count = sum(
                role_id in {int(value) for value in member["roles"]}
                and not bool(member["user"].get("bot"))
                for member in discord_members
            )
            if rendered_counts.get(role_id) != live_count:
                failures.append(
                    f"painel da hierarquia: cargo {role_id} mostra "
                    f"{rendered_counts.get(role_id)}, esperado {live_count}"
                )
    else:
        warnings.append("mensagem persistida da hierarquia não localizada")

    print("RANK_SYNC_LIVE_PASS" if not failures else "RANK_SYNC_LIVE_FAIL")
    print(f"migration={state['version']}")
    print(f"registered_members={len(state['members'])}")
    print(f"rank_sync_events={state['event_count']}")
    print(f"hierarchy_ranks={len(state['ranks'])}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for failure in failures:
        print(f"FAIL: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
