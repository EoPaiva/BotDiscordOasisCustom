from __future__ import annotations

import argparse
import asyncio
import json
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402

API_BASE = "https://discord.com/api/v10"
PATROL_CATEGORY_ID = 1146622065647046776
GENERAL_CHAT_ID = 1201450207917899786
MEDIA_CHAT_ID = 1161829510627459172
HIERARCHY_CHANNEL_ID = 1146622065110171666
REASON = "CHOQUE - BGR • acesso do cargo Companheiro de Farda"

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
READ_MESSAGE_HISTORY = 1 << 16
ADD_REACTIONS = 1 << 6
CONNECT = 1 << 20
SPEAK = 1 << 21
CREATE_PUBLIC_THREADS = 1 << 35
CREATE_PRIVATE_THREADS = 1 << 36
SEND_MESSAGES_IN_THREADS = 1 << 38

SMALL_CAPS = str.maketrans(
    {
        "ᴀ": "a",
        "ʙ": "b",
        "ᴄ": "c",
        "ᴅ": "d",
        "ᴇ": "e",
        "ꜰ": "f",
        "ғ": "f",
        "ɢ": "g",
        "ʜ": "h",
        "ɪ": "i",
        "ᴊ": "j",
        "ᴋ": "k",
        "ʟ": "l",
        "ᴍ": "m",
        "ɴ": "n",
        "ᴏ": "o",
        "ᴘ": "p",
        "ʀ": "r",
        "ꜱ": "s",
        "ᴛ": "t",
        "ᴜ": "u",
        "ᴠ": "v",
        "ᴡ": "w",
        "ʏ": "y",
        "ᴢ": "z",
    }
)


def normalize_name(value: str) -> str:
    translated = value.translate(SMALL_CAPS).casefold()
    normalized = unicodedata.normalize("NFKD", translated)
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    for separator in ("・", "·", "•", "-", "_", "ㅤ"):
        plain = plain.replace(separator, " ")
    return " ".join(plain.split())


def permission_snapshot(channel: dict[str, Any], role_id: int) -> dict[str, Any] | None:
    return next(
        (
            dict(overwrite)
            for overwrite in channel.get("permission_overwrites", [])
            if str(overwrite.get("id")) == str(role_id)
            and int(overwrite.get("type", 0)) == 0
        ),
        None,
    )


class DiscordRest:
    def __init__(self, token: str) -> None:
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bot {token}", "User-Agent": "CHOQUE-BGR/1.0"}
        )

    async def close(self) -> None:
        await self.session.close()

    async def request(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None
    ) -> Any:
        for _ in range(6):
            async with self.session.request(
                method,
                API_BASE + path,
                json=payload,
                headers={"X-Audit-Log-Reason": quote(REASON)},
            ) as response:
                if response.status == 429:
                    data = await response.json()
                    await asyncio.sleep(min(float(data.get("retry_after", 1)), 10.0))
                    continue
                if response.status == 204:
                    return None
                data = await response.json()
                if response.status >= 400:
                    raise RuntimeError(f"Discord API {response.status}: {data.get('message')}")
                return data
        raise RuntimeError("Discord API permaneceu limitada após as tentativas seguras.")


def find_companion_role(roles: list[dict[str, Any]]) -> dict[str, Any]:
    matches = []
    for role in roles:
        normalized = normalize_name(str(role["name"]))
        if (
            ("companheiro" in normalized and "farda" in normalized)
            or normalized.startswith(".f ")
            or "comp.f" in normalized.replace(" ", "")
        ):
            matches.append(role)
    if len(matches) != 1:
        names = [str(role["name"]) for role in matches]
        raise RuntimeError(f"Esperado um cargo Companheiro de Farda; encontrados: {names}")
    return matches[0]


def target_policy(channel: dict[str, Any]) -> tuple[int, int, str] | None:
    channel_id = int(channel["id"])
    if channel_id == HIERARCHY_CHANNEL_ID:
        allow = VIEW_CHANNEL | READ_MESSAGE_HISTORY
        deny = (
            SEND_MESSAGES
            | CREATE_PUBLIC_THREADS
            | CREATE_PRIVATE_THREADS
            | SEND_MESSAGES_IN_THREADS
        )
        return allow, deny, "HIERARCHY_READ_ONLY"
    if channel_id in {GENERAL_CHAT_ID, MEDIA_CHAT_ID}:
        allow = VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES | ADD_REACTIONS
        return allow, 0, "COMMUNITY_CHAT"
    if channel_id == PATROL_CATEGORY_ID or int(channel.get("parent_id") or 0) == PATROL_CATEGORY_ID:
        allow = VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES | CONNECT | SPEAK
        return allow, 0, "PATROL_FULL_ACCESS"
    return None


async def write_overwrite(
    api: DiscordRest, channel_id: int, role_id: int, allow: int, deny: int
) -> None:
    await api.request(
        "PUT",
        f"/channels/{channel_id}/permissions/{role_id}",
        payload={"allow": str(allow), "deny": str(deny), "type": 0},
    )


async def restore_snapshot(api: DiscordRest, snapshot: dict[str, Any]) -> None:
    role_id = int(snapshot["role_id"])
    for item in snapshot["targets"]:
        channel_id = int(item["channel_id"])
        previous = item["before"]
        if previous is None:
            await api.request("DELETE", f"/channels/{channel_id}/permissions/{role_id}")
        else:
            await write_overwrite(
                api,
                channel_id,
                role_id,
                int(previous["allow"]),
                int(previous["deny"]),
            )


async def run() -> int:
    parser = argparse.ArgumentParser(description="Configura o acesso do Companheiro de Farda.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--list-roles", action="store_true")
    args = parser.parse_args()
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        print("COMPANION_ACCESS_FAILED type=MissingConfiguration")
        return 1
    api = DiscordRest(config.token)
    try:
        if args.rollback:
            snapshot = json.loads(args.rollback.read_text(encoding="utf-8"))
            await restore_snapshot(api, snapshot)
            print(f"COMPANION_ACCESS_ROLLBACK_PASS restored={len(snapshot['targets'])}")
            return 0
        guild_id = int(config.default_guild_id)
        roles, channels = await asyncio.gather(
            api.request("GET", f"/guilds/{guild_id}/roles"),
            api.request("GET", f"/guilds/{guild_id}/channels"),
        )
        if args.list_roles:
            for candidate in roles:
                print(
                    f"ROLE id={candidate['id']} name={ascii(candidate['name'])} "
                    f"normalized={ascii(normalize_name(str(candidate['name'])))}"
                )
            return 0
        role = find_companion_role(roles)
        policies = [
            (channel, policy)
            for channel in channels
            if (policy := target_policy(channel)) is not None
        ]
        if not policies:
            raise RuntimeError("Nenhum canal-alvo foi localizado pelos IDs oficiais.")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = PROJECT_ROOT / "data" / "server_layout_backups"
        destination.mkdir(parents=True, exist_ok=True)
        snapshot_path = destination / f"companion_access_{guild_id}_{stamp}.json"
        snapshot = {
            "guild_id": guild_id,
            "captured_at": stamp,
            "role_id": int(role["id"]),
            "role_name": str(role["name"]),
            "targets": [
                {
                    "channel_id": int(channel["id"]),
                    "channel_name": str(channel["name"]),
                    "policy": policy[2],
                    "before": permission_snapshot(channel, int(role["id"])),
                }
                for channel, policy in policies
            ],
        }
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not args.apply:
            print(
                "COMPANION_ACCESS_PREVIEW_PASS "
                f"role={ascii(role['name'])} targets={len(policies)} snapshot={snapshot_path.name}"
            )
            return 0
        for channel, (allow, deny, _) in policies:
            await write_overwrite(api, int(channel["id"]), int(role["id"]), allow, deny)
        refreshed = await api.request("GET", f"/guilds/{guild_id}/channels")
        refreshed_by_id = {int(channel["id"]): channel for channel in refreshed}
        failures = []
        for channel, (allow, deny, policy_name) in policies:
            actual = permission_snapshot(refreshed_by_id[int(channel["id"])], int(role["id"]))
            if actual is None or int(actual["allow"]) != allow or int(actual["deny"]) != deny:
                failures.append(f"{policy_name}:{channel['id']}")
        if failures:
            await restore_snapshot(api, snapshot)
            raise RuntimeError(f"Validação falhou e rollback foi executado: {failures}")
        database = Database(config.database_path)
        await database.open()
        try:
            settings = SettingsService(database)
            await settings.set(
                guild_id,
                "companion_role_id",
                int(role["id"]),
                actor_id=None,
            )
        finally:
            await database.close()
        print(
            "COMPANION_ACCESS_APPLY_PASS "
            f"role={ascii(role['name'])} targets={len(policies)} snapshot={snapshot_path.name}"
        )
        return 0
    except Exception as exc:
        print(f"COMPANION_ACCESS_FAILED type={type(exc).__name__} detail={exc}")
        return 1
    finally:
        await api.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
