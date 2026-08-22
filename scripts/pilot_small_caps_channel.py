from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.channel_names import format_small_caps_channel_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402
from scripts.remodel_discord_layout import (  # noqa: E402
    CHANNEL_BY_KEY,
    REGISTRY_SETTING,
)

API_BASE = "https://discord.com/api/v10"
TARGET_KEY = "superiors.notices"
PILOT_SETTING = "channel_name_small_caps_pilot_v1"
REASON = "Piloto visual Small Caps CHOQUE - BGR"


def _overwrites(channel: dict[str, Any]) -> list[dict[str, str | int]]:
    return sorted(
        (
            {
                "id": str(item["id"]),
                "type": int(item["type"]),
                "allow": str(item.get("allow", "0")),
                "deny": str(item.get("deny", "0")),
            }
            for item in channel.get("permission_overwrites", [])
        ),
        key=lambda item: (item["type"], item["id"]),
    )


async def _request(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    for attempt in range(2):
        async with session.request(method, f"{API_BASE}{path}", json=payload) as response:
            body = await response.json(content_type=None) if response.content_length != 0 else {}
            if response.status == 429 and attempt == 0:
                await asyncio.sleep(min(float(body.get("retry_after", 1.0)), 15.0))
                continue
            if response.status not in {200, 204}:
                raise RuntimeError(f"Discord API {response.status} em {path}")
            return body
    raise RuntimeError("Discord manteve o rate limit após a repetição controlada")


def _write_snapshot(
    *,
    guild_id: int,
    channel: dict[str, Any],
    desired_name: str,
) -> Path:
    destination = PROJECT_ROOT / "data" / "server_layout_backups"
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = destination / f"small_caps_pilot_{guild_id}_{channel['id']}_{timestamp}.json"
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "guild_id": guild_id,
        "internal_key": TARGET_KEY,
        "channel_id": int(channel["id"]),
        "before_name": str(channel["name"]),
        "desired_name": desired_name,
        "parent_id": int(channel["parent_id"]) if channel.get("parent_id") else None,
        "position": int(channel["position"]),
        "permission_overwrites": _overwrites(channel),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def _record(
    config: AppConfig,
    *,
    action: str,
    channel_id: int,
    before_name: str,
    after_name: str,
    snapshot: Path,
) -> None:
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        payload = {
            "channel_id": channel_id,
            "internal_key": TARGET_KEY,
            "name": after_name,
            "snapshot": str(snapshot.resolve()),
        }
        await settings.set(
            int(config.default_guild_id or 0),
            PILOT_SETTING,
            payload,
            None,
        )
        await audit.record(
            int(config.default_guild_id or 0),
            action,
            target_id=channel_id,
            before={"name": before_name},
            after=payload,
        )
    finally:
        await database.close()


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        registry = await SettingsService(database).get(
            config.default_guild_id,
            REGISTRY_SETTING,
            {},
        )
    finally:
        await database.close()
    channel_id = int(registry["channels"][TARGET_KEY])
    spec = CHANNEL_BY_KEY[TARGET_KEY]
    desired_name = format_small_caps_channel_name(spec.name, spec.emoji)
    headers = {
        "Authorization": f"Bot {config.token}",
        "User-Agent": "CHOQUE-BGR-SmallCapsPilot/1.0",
        "X-Audit-Log-Reason": quote(REASON),
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        before = await _request(session, "GET", f"/channels/{channel_id}")
        if int(before["guild_id"]) != config.default_guild_id:
            raise RuntimeError("O canal do registry não pertence à guild configurada.")
        snapshot = _write_snapshot(
            guild_id=config.default_guild_id,
            channel=before,
            desired_name=desired_name,
        )
        if not args.apply:
            print(
                f"SMALL_CAPS_PILOT_DRY_RUN channel_id={channel_id} "
                f"before={before['name']!r} after={desired_name!r} snapshot={snapshot.resolve()}"
            )
            return 0
        await _request(
            session,
            "PATCH",
            f"/channels/{channel_id}",
            {"name": desired_name},
        )
        after = await _request(session, "GET", f"/channels/{channel_id}")
        unchanged_structure = (
            after.get("parent_id") == before.get("parent_id")
            and int(after["position"]) == int(before["position"])
            and _overwrites(after) == _overwrites(before)
        )
        if str(after["name"]) != desired_name or not unchanged_structure:
            await _request(
                session,
                "PATCH",
                f"/channels/{channel_id}",
                {"name": str(before["name"])},
            )
            restored = await _request(session, "GET", f"/channels/{channel_id}")
            if str(restored["name"]) != str(before["name"]):
                raise RuntimeError("O piloto falhou e o rollback automático também falhou.")
            raise RuntimeError("O Discord alterou o nome ou a estrutura; rollback aplicado.")
    await _record(
        config,
        action="CHANNEL_SMALL_CAPS_PILOT_APPLIED",
        channel_id=channel_id,
        before_name=str(before["name"]),
        after_name=desired_name,
        snapshot=snapshot,
    )
    print(
        f"SMALL_CAPS_PILOT_APPLIED channel_id={channel_id} name={desired_name!r} "
        f"snapshot={snapshot.resolve()} structure_preserved=true mention_preserved=true"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aplica o piloto Small Caps em um único canal.")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(run(parse_args())))
