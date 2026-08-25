from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.config import AppConfig  # noqa: E402

API_BASE = "https://discord.com/api/v10"
REASON = "CHOQUE - BGR • compactacao autorizada do Discord"

CATEGORY_IDS = {
    "admin": 1540540581728485597,
    "archive": 1146622065110171669,
    "audit": 1146622066527850585,
    "away": 1540589599577866240,
    "events": 1540589586609082478,
    "management": 1540589592263139388,
    "meeting": 1540589600903274546,
    "partnerships": 1540589594691772477,
    "patrol": 1146622065647046776,
    "point": 1540589584679833680,
    "superiors": 1540589576140357712,
    "ticket": 1540589574667898920,
    "info": 1161833335618801687,
}

CHANNEL_IDS = {
    "archive.members": 1147292121234161783,
    "info.eagle": 1161835204642603128,
    "info.rocam": 1161833937232990330,
    "management.config": 1166681424154333277,
    "point.active": 1540546967938011186,
    "point.panel": 1540546965362974731,
    "superiors.manual": 1540590740105724015,
    "superiors.qa": 1540590750813913088,
    "ticket.room.2": 1540590728911261750,
    "ticket.room.3": 1540590731159412848,
}

DELETE_EXPLICIT = {
    "ticket.room.2": "ticket",
    "ticket.room.3": "ticket",
    "superiors.manual": "superiors",
    "superiors.qa": "superiors",
    "info.rocam": "info",
    "info.eagle": "info",
}
DELETE_CATEGORY_KEYS = ("events", "away", "meeting", "archive")
MOVE_TARGETS = {
    "point.panel": "patrol",
    "point.active": "patrol",
    "management.config": "admin",
    "archive.members": "audit",
}
TEXT_CHANNEL_TYPES = {0, 5}


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    delete_channel_ids: tuple[int, ...]
    delete_category_ids: tuple[int, ...]
    move_parent_by_channel_id: dict[int, int]
    preserve_channel_ids: tuple[int, ...]


class DiscordRest:
    def __init__(self, token: str) -> None:
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bot {token}", "User-Agent": "CHOQUE-BGR/1.0"}
        )

    async def close(self) -> None:
        await self.session.close()

    async def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> Any:
        for _ in range(10):
            async with self.session.request(
                method,
                API_BASE + path,
                json=payload,
                headers={"X-Audit-Log-Reason": quote(REASON)},
            ) as response:
                if response.status == 429:
                    data = await response.json()
                    await asyncio.sleep(min(float(data.get("retry_after", 1)), 30.0))
                    continue
                if response.status == 204:
                    return None
                data = await response.json()
                if response.status >= 400:
                    message = data.get("message") if isinstance(data, dict) else str(data)
                    raise RuntimeError(f"Discord API {response.status}: {message}")
                return data
        raise RuntimeError("Discord API permaneceu limitada apos as tentativas seguras.")


def _by_id(channels: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(channel["id"]): channel for channel in channels}


def _expect_channel(
    channels_by_id: dict[int, dict[str, Any]],
    *,
    resource_id: int,
    resource_name: str,
    expected_parent_id: int | None = None,
    expected_type: int | None = None,
) -> dict[str, Any]:
    channel = channels_by_id.get(resource_id)
    if channel is None:
        raise RuntimeError(f"Recurso obrigatorio ausente: {resource_name}:{resource_id}")
    if expected_parent_id is not None and int(channel.get("parent_id") or 0) != expected_parent_id:
        raise RuntimeError(f"Categoria inesperada para {resource_name}:{resource_id}")
    if expected_type is not None and int(channel.get("type", -1)) != expected_type:
        raise RuntimeError(f"Tipo inesperado para {resource_name}:{resource_id}")
    return channel


def build_plan(channels: list[dict[str, Any]]) -> CompactionPlan:
    channels_by_id = _by_id(channels)
    for key, category_id in CATEGORY_IDS.items():
        _expect_channel(
            channels_by_id,
            resource_id=category_id,
            resource_name=f"category.{key}",
            expected_type=4,
        )

    delete_ids: set[int] = set()
    for channel_key, parent_key in DELETE_EXPLICIT.items():
        channel_id = CHANNEL_IDS[channel_key]
        _expect_channel(
            channels_by_id,
            resource_id=channel_id,
            resource_name=channel_key,
            expected_parent_id=CATEGORY_IDS[parent_key],
        )
        delete_ids.add(channel_id)

    preserved_id = CHANNEL_IDS["archive.members"]
    preserved_channel = _expect_channel(
        channels_by_id,
        resource_id=preserved_id,
        resource_name="archive.members",
        expected_type=0,
    )
    if int(preserved_channel.get("parent_id") or 0) not in {
        CATEGORY_IDS["archive"],
        CATEGORY_IDS["audit"],
    }:
        raise RuntimeError(f"Categoria inesperada para archive.members:{preserved_id}")
    for category_key in DELETE_CATEGORY_KEYS:
        category_id = CATEGORY_IDS[category_key]
        delete_ids.update(
            int(channel["id"])
            for channel in channels
            if int(channel.get("parent_id") or 0) == category_id
            and int(channel["id"]) != preserved_id
        )

    move_parent_by_channel_id: dict[int, int] = {}
    for channel_key, destination_key in MOVE_TARGETS.items():
        source_key = "archive" if channel_key == "archive.members" else (
            "management" if channel_key == "management.config" else "point"
        )
        channel_id = CHANNEL_IDS[channel_key]
        channel = _expect_channel(
            channels_by_id,
            resource_id=channel_id,
            resource_name=channel_key,
        )
        current_parent_id = int(channel.get("parent_id") or 0)
        destination_id = CATEGORY_IDS[destination_key]
        if current_parent_id not in {CATEGORY_IDS[source_key], destination_id}:
            raise RuntimeError(f"Categoria inesperada para {channel_key}:{channel_id}")
        move_parent_by_channel_id[channel_id] = destination_id

    overlap = delete_ids.intersection(move_parent_by_channel_id)
    if overlap:
        raise RuntimeError(f"Plano ambiguo: recursos em exclusao e movimento: {sorted(overlap)}")
    return CompactionPlan(
        delete_channel_ids=tuple(sorted(delete_ids)),
        delete_category_ids=tuple(sorted(CATEGORY_IDS[key] for key in DELETE_CATEGORY_KEYS)),
        move_parent_by_channel_id=move_parent_by_channel_id,
        preserve_channel_ids=(preserved_id,),
    )


def snapshot_channel(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(channel["id"]),
        "name": str(channel["name"]),
        "type": int(channel["type"]),
        "parent_id": int(channel["parent_id"]) if channel.get("parent_id") else None,
        "position": int(channel.get("position", 0)),
        "topic": channel.get("topic"),
        "bitrate": channel.get("bitrate"),
        "user_limit": channel.get("user_limit"),
        "rate_limit_per_user": channel.get("rate_limit_per_user"),
        "nsfw": channel.get("nsfw"),
        "permission_overwrites": channel.get("permission_overwrites", []),
    }


def normalize_overwrites(value: Any) -> list[tuple[str, int, str, str]]:
    if not isinstance(value, list):
        return []
    return sorted(
        (
            str(item.get("id", "")),
            int(item.get("type", 0)),
            str(item.get("allow", "0")),
            str(item.get("deny", "0")),
        )
        for item in value
        if isinstance(item, dict)
    )


def fields_equal(before: dict[str, Any], after: dict[str, Any], key: str) -> bool:
    if key == "permission_overwrites":
        return normalize_overwrites(before.get(key)) == normalize_overwrites(after.get(key))
    if key in {"parent_id", "type"}:
        before_value = int(before[key]) if before.get(key) is not None else None
        after_value = int(after[key]) if after.get(key) is not None else None
        return before_value == after_value
    return before.get(key) == after.get(key)


async def fetch_all_messages(api: DiscordRest, channel_id: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    before: str | None = None
    while True:
        suffix = f"?limit=100&before={before}" if before else "?limit=100"
        page = await api.request("GET", f"/channels/{channel_id}/messages{suffix}")
        if not isinstance(page, list):
            raise RuntimeError(f"Historico inesperado no canal {channel_id}")
        result.extend(page)
        if len(page) < 100:
            return result
        before = str(page[-1]["id"])


async def write_snapshot(
    api: DiscordRest,
    *,
    guild_id: int,
    channels: list[dict[str, Any]],
    plan: CompactionPlan,
    destination: Path,
) -> tuple[Path, int]:
    destination.mkdir(parents=True, exist_ok=True)
    channels_by_id = _by_id(channels)
    message_exports: dict[str, list[dict[str, Any]]] = {}
    message_count = 0
    for channel_id in plan.delete_channel_ids:
        channel = channels_by_id[channel_id]
        if int(channel.get("type", -1)) not in TEXT_CHANNEL_TYPES:
            continue
        messages = await fetch_all_messages(api, channel_id)
        message_exports[str(channel_id)] = messages
        message_count += len(messages)

    active_threads = await api.request("GET", f"/guilds/{guild_id}/threads/active")
    payload = {
        "captured_at": datetime.now(UTC).isoformat(),
        "guild_id": guild_id,
        "reason": REASON,
        "warning": (
            "Este arquivo preserva metadados e conteudo textual. A API do Discord nao restaura "
            "IDs nem o historico original de canais excluidos."
        ),
        "plan": asdict(plan),
        "channels": [snapshot_channel(channel) for channel in channels],
        "deleted_channel_messages": message_exports,
        "active_threads": active_threads,
    }
    snapshot_path = destination / "discord_compaction_snapshot.json"
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot_path, message_count


def validate_after(
    before: list[dict[str, Any]], after: list[dict[str, Any]], plan: CompactionPlan
) -> list[str]:
    failures: list[str] = []
    before_by_id = _by_id(before)
    after_by_id = _by_id(after)
    for resource_id in (*plan.delete_channel_ids, *plan.delete_category_ids):
        if resource_id in after_by_id:
            failures.append(f"not_deleted:{resource_id}")
    for channel_id, parent_id in plan.move_parent_by_channel_id.items():
        channel = after_by_id.get(channel_id)
        if channel is None:
            failures.append(f"missing_moved:{channel_id}")
            continue
        if int(channel.get("parent_id") or 0) != parent_id:
            failures.append(f"wrong_parent:{channel_id}")
        before_channel = before_by_id[channel_id]
        for key in ("name", "type", "permission_overwrites"):
            if not fields_equal(before_channel, channel, key):
                failures.append(f"changed_{key}:{channel_id}")
    for channel_id in plan.preserve_channel_ids:
        if channel_id not in after_by_id:
            failures.append(f"missing_preserved:{channel_id}")

    ignored = set(plan.delete_channel_ids) | set(plan.delete_category_ids)
    ignored.update(plan.move_parent_by_channel_id)
    ignored.add(CATEGORY_IDS["partnerships"])
    for resource_id, before_channel in before_by_id.items():
        if resource_id in ignored:
            continue
        after_channel = after_by_id.get(resource_id)
        if after_channel is None:
            failures.append(f"unrelated_missing:{resource_id}")
            continue
        for key in ("name", "type", "parent_id", "permission_overwrites"):
            if not fields_equal(before_channel, after_channel, key):
                failures.append(f"unrelated_changed_{key}:{resource_id}")

    partnership = after_by_id.get(CATEGORY_IDS["partnerships"])
    category_positions = [
        int(channel.get("position", 0))
        for channel in after
        if int(channel.get("type", -1)) == 4
    ]
    if not partnership or int(partnership.get("position", 0)) != max(category_positions):
        failures.append("partnerships_not_last")
    return failures


async def execute(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID sao obrigatorios.")
    guild_id = int(config.default_guild_id)
    api = DiscordRest(config.token)
    try:
        if args.verify_snapshot:
            snapshot = json.loads(args.verify_snapshot.read_text(encoding="utf-8"))
            raw_plan = snapshot["plan"]
            plan = CompactionPlan(
                delete_channel_ids=tuple(int(item) for item in raw_plan["delete_channel_ids"]),
                delete_category_ids=tuple(int(item) for item in raw_plan["delete_category_ids"]),
                move_parent_by_channel_id={
                    int(channel_id): int(parent_id)
                    for channel_id, parent_id in raw_plan["move_parent_by_channel_id"].items()
                },
                preserve_channel_ids=tuple(int(item) for item in raw_plan["preserve_channel_ids"]),
            )
            after = await api.request("GET", f"/guilds/{guild_id}/channels")
            failures = validate_after(snapshot["channels"], after, plan)
            if failures:
                raise RuntimeError(f"Validacao final falhou: {failures}")
            print(
                "DISCORD_COMPACTION_VERIFY_PASS "
                f"snapshot={args.verify_snapshot} channels={len(after)}"
            )
            return 0
        before = await api.request("GET", f"/guilds/{guild_id}/channels")
        if not isinstance(before, list):
            raise RuntimeError("Inventario do Discord invalido.")
        plan = build_plan(before)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = config.database_path.parent / "server_layout_backups" / (
            f"discord_compaction_{guild_id}_{stamp}"
        )
        snapshot_path, message_count = await write_snapshot(
            api,
            guild_id=guild_id,
            channels=before,
            plan=plan,
            destination=destination,
        )
        print(
            "DISCORD_COMPACTION_PREVIEW_PASS "
            f"delete_channels={len(plan.delete_channel_ids)} "
            f"delete_categories={len(plan.delete_category_ids)} "
            f"move_channels={len(plan.move_parent_by_channel_id)} "
            f"messages={message_count} snapshot={snapshot_path}"
        )
        if not args.apply:
            return 0

        manifest: list[dict[str, Any]] = []
        for channel_id, parent_id in plan.move_parent_by_channel_id.items():
            await api.request(
                "PATCH", f"/channels/{channel_id}", payload={"parent_id": str(parent_id)}
            )
            manifest.append({"action": "move", "id": channel_id, "parent_id": parent_id})
        for channel_id in plan.delete_channel_ids:
            await api.request("DELETE", f"/channels/{channel_id}")
            manifest.append({"action": "delete_channel", "id": channel_id})
        for category_id in plan.delete_category_ids:
            await api.request("DELETE", f"/channels/{category_id}")
            manifest.append({"action": "delete_category", "id": category_id})

        interim = await api.request("GET", f"/guilds/{guild_id}/channels")
        categories = sorted(
            (channel for channel in interim if int(channel.get("type", -1)) == 4),
            key=lambda channel: int(channel.get("position", 0)),
        )
        ordered_ids = [
            int(channel["id"])
            for channel in categories
            if int(channel["id"]) != CATEGORY_IDS["partnerships"]
        ] + [CATEGORY_IDS["partnerships"]]
        await api.request(
            "PATCH",
            f"/guilds/{guild_id}/channels",
            payload=[
                {"id": str(category_id), "position": position}
                for position, category_id in enumerate(ordered_ids)
            ],
        )
        manifest.append({"action": "move_category_last", "id": CATEGORY_IDS["partnerships"]})

        after = await api.request("GET", f"/guilds/{guild_id}/channels")
        failures = validate_after(before, after, plan)
        manifest_path = destination / "discord_compaction_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "completed_at": datetime.now(UTC).isoformat(),
                    "actions": manifest,
                    "validation_failures": failures,
                    "after_channels": [snapshot_channel(channel) for channel in after],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if failures:
            raise RuntimeError(f"Validacao final falhou: {failures}")
        print(
            "DISCORD_COMPACTION_APPLY_PASS "
            f"deleted_channels={len(plan.delete_channel_ids)} "
            f"deleted_categories={len(plan.delete_category_ids)} "
            f"moved_channels={len(plan.move_parent_by_channel_id)} manifest={manifest_path}"
        )
        return 0
    finally:
        await api.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compacta o Discord CHOQUE - BGR com snapshot.")
    parser.add_argument("--apply", action="store_true", help="Aplica o plano autorizado.")
    parser.add_argument(
        "--verify-snapshot",
        type=Path,
        help="Valida o estado atual contra um snapshot de compactacao ja aplicado.",
    )
    return parser.parse_args()


def main() -> int:
    return asyncio.run(execute(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
