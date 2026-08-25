from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.channel_names import format_category_name, format_channel_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from scripts.migrate_rec_choque import (  # noqa: E402
    CHANNELS,
    DEFAULT_TARGET_GUILD_ID,
    DiscordRest,
    _permission_overwrites,
    _role_key,
)

MEMBER_ROLE = "Membro Choque"
STAFF_ROLES = (
    "Comando REC",
    "Responsável Recrutamento",
    "Auxiliar Recrutamento",
    "Instrutor de Cursos",
)
STABLE_CHANNEL_FIELDS = ("name", "type", "parent_id", "topic", "nsfw", "rate_limit_per_user")


def _find_unique(
    items: list[dict[str, Any]], *, name: str, item_type: int | None = None
) -> dict[str, Any]:
    matches = [
        item
        for item in items
        if (item_type is None or int(item.get("type", -1)) == item_type)
        and _role_key(str(item.get("name", ""))) == _role_key(name)
    ]
    if len(matches) != 1:
        raise RuntimeError(f"{name!r} precisa existir uma única vez; encontrados: {len(matches)}.")
    return matches[0]


def _normalize_overwrites(items: list[dict[str, Any]]) -> list[tuple[str, int, str, str]]:
    return sorted(
        (
            str(item["id"]),
            int(item["type"]),
            str(item.get("allow", "0")),
            str(item.get("deny", "0")),
        )
        for item in items
    )


def build_course_access_plan(
    guild_id: int,
    roles: list[dict[str, Any]],
    channels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    member_role = _find_unique(roles, name=MEMBER_ROLE)
    staff_role_ids = [
        int(_find_unique(roles, name=name)["id"]) for name in STAFF_ROLES
    ]
    category = _find_unique(
        channels, name=format_category_name(3, "Cursos"), item_type=4
    )
    member_role_id = int(member_role["id"])
    category_id = int(category["id"])
    plan = [
        {
            "channel": category,
            "permission_overwrites": _permission_overwrites(
                guild_id,
                staff_role_ids=staff_role_ids,
                viewer_role_ids=[member_role_id],
                private=True,
                writable=False,
            ),
        }
    ]
    for spec in (item for item in CHANNELS if item.category == "courses"):
        channel = _find_unique(
            [item for item in channels if int(item.get("parent_id") or 0) == category_id],
            name=format_channel_name(spec.label, spec.emoji),
            item_type=2 if spec.voice else 0,
        )
        member_visible = not spec.private
        plan.append(
            {
                "channel": channel,
                "permission_overwrites": _permission_overwrites(
                    guild_id,
                    staff_role_ids=staff_role_ids,
                    viewer_role_ids=[member_role_id] if member_visible else [],
                    private=True,
                    writable=spec.key in {"courses.chat", "courses.instructors"}
                    or spec.voice,
                    viewer_writable=member_visible
                    and (spec.key == "courses.chat" or spec.voice),
                ),
            }
        )
    return plan


def _snapshot_channels(plan: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        int(item["channel"]["id"]): {
            field: item["channel"].get(field) for field in STABLE_CHANNEL_FIELDS
        }
        for item in plan
    }


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token:
        raise RuntimeError("DISCORD_TOKEN não configurado.")
    guild_id = int(args.guild)
    api = DiscordRest(config.token)
    try:
        guild, roles, channels = await asyncio.gather(
            api.request("GET", f"/guilds/{guild_id}"),
            api.request("GET", f"/guilds/{guild_id}/roles"),
            api.request("GET", f"/guilds/{guild_id}/channels"),
        )
        if guild_id != DEFAULT_TARGET_GUILD_ID and str(guild["name"]).casefold() != "rec choque":
            raise RuntimeError("O servidor de destino não corresponde ao REC CHOQUE.")
        plan = build_course_access_plan(guild_id, roles, channels)
        before = _snapshot_channels(plan)
        changed = [
            item
            for item in plan
            if _normalize_overwrites(item["channel"].get("permission_overwrites", []))
            != _normalize_overwrites(item["permission_overwrites"])
        ]
        if args.apply:
            for item in changed:
                await api.request(
                    "PATCH",
                    f"/channels/{item['channel']['id']}",
                    payload={"permission_overwrites": item["permission_overwrites"]},
                )
            refreshed = await api.request("GET", f"/guilds/{guild_id}/channels")
            verified_plan = build_course_access_plan(guild_id, roles, refreshed)
            after = _snapshot_channels(verified_plan)
            if after != before:
                raise RuntimeError("Atributos de canais mudaram durante a restrição de acesso.")
            remaining = [
                item
                for item in verified_plan
                if _normalize_overwrites(item["channel"].get("permission_overwrites", []))
                != _normalize_overwrites(item["permission_overwrites"])
            ]
            if remaining:
                raise RuntimeError("Discord não aplicou todas as permissões de Cursos.")
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "guild": guild["name"],
                    "resources": len(plan),
                    "changes": len(changed),
                    "verified": bool(args.apply),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        await api.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restringe a categoria Cursos do REC CHOQUE aos membros e equipe responsável."
    )
    parser.add_argument("--guild", type=int, default=DEFAULT_TARGET_GUILD_ID)
    parser.add_argument("--apply", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(build_parser().parse_args())))
