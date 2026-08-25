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

from choque.channel_names import format_category_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from scripts.migrate_rec_choque import (  # noqa: E402
    DEFAULT_TARGET_GUILD_ID,
    DiscordRest,
    _permission_overwrites,
    _role_key,
)

RECRUITMENT_CATEGORY = format_category_name(1, "Recrutamento")
ADMIN_CATEGORY = format_category_name(2, "Administração do Recrutamento")
OLD_COURSES_CATEGORY = format_category_name(2, "Cursos")
COURSES_CATEGORY = format_category_name(3, "Cursos")
ADMIN_KEYS = frozenset(
    {"recruitment.review", "recruitment.approved", "recruitment.rejected"}
)
STAFF_ROLES = (
    "Comando REC",
    "Responsável Recrutamento",
    "Auxiliar Recrutamento",
)


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


def _admin_overwrites(guild_id: int, staff_role_ids: list[int]) -> list[dict[str, str | int]]:
    return _permission_overwrites(
        guild_id,
        staff_role_ids=staff_role_ids,
        private=True,
        writable=True,
    )


def build_admin_channel_plan(
    guild_id: int,
    channels: list[dict[str, Any]],
    admin_category_id: int,
    staff_role_ids: list[int],
) -> list[dict[str, Any]]:
    by_topic = {
        str(channel.get("topic") or ""): channel
        for channel in channels
        if int(channel.get("type", -1)) == 0
    }
    overwrites = _admin_overwrites(guild_id, staff_role_ids)
    plan = []
    for key in sorted(ADMIN_KEYS):
        topic = f"CHOQUE-BGR rec-migration:{key}"
        channel = by_topic.get(topic)
        if channel is None:
            raise RuntimeError(f"Canal administrativo ausente: {key}.")
        plan.append(
            {
                "id": int(channel["id"]),
                "key": key,
                "actual_parent_id": int(channel.get("parent_id") or 0),
                "parent_id": admin_category_id,
                "permission_overwrites": overwrites,
            }
        )
    return plan


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
        recruitment = _find_unique(channels, name=RECRUITMENT_CATEGORY, item_type=4)
        course_matches = [
            item
            for item in channels
            if int(item.get("type", -1)) == 4
            and str(item.get("name")) in {OLD_COURSES_CATEGORY, COURSES_CATEGORY}
        ]
        if len(course_matches) != 1:
            raise RuntimeError("Categoria Cursos ausente ou duplicada.")
        courses = course_matches[0]
        staff_role_ids = [
            int(_find_unique(roles, name=name)["id"]) for name in STAFF_ROLES
        ]
        admin_overwrites = _admin_overwrites(guild_id, staff_role_ids)
        admin_matches = [
            item
            for item in channels
            if int(item.get("type", -1)) == 4 and str(item.get("name")) == ADMIN_CATEGORY
        ]
        if len(admin_matches) > 1:
            raise RuntimeError("Categoria administrativa duplicada.")
        if admin_matches:
            admin = await api.request(
                "PATCH",
                f"/channels/{admin_matches[0]['id']}",
                payload={"name": ADMIN_CATEGORY, "permission_overwrites": admin_overwrites},
            )
            created = False
        else:
            admin = await api.request(
                "POST",
                f"/guilds/{guild_id}/channels",
                payload={
                    "name": ADMIN_CATEGORY,
                    "type": 4,
                    "permission_overwrites": admin_overwrites,
                },
            )
            created = True
        courses = await api.request(
            "PATCH", f"/channels/{courses['id']}", payload={"name": COURSES_CATEGORY}
        )
        plan = build_admin_channel_plan(
            guild_id, channels, int(admin["id"]), staff_role_ids
        )
        for item in plan:
            await api.request(
                "PATCH",
                f"/channels/{item['id']}",
                payload={
                    "parent_id": str(item["parent_id"]),
                    "permission_overwrites": item["permission_overwrites"],
                },
            )
        await api.request(
            "PATCH",
            f"/guilds/{guild_id}/channels",
            payload=[
                {"id": str(recruitment["id"]), "position": 0},
                {"id": str(admin["id"]), "position": 1},
                {"id": str(courses["id"]), "position": 2},
            ],
        )

        refreshed = await api.request("GET", f"/guilds/{guild_id}/channels")
        refreshed_admin = _find_unique(refreshed, name=ADMIN_CATEGORY, item_type=4)
        refreshed_courses = _find_unique(refreshed, name=COURSES_CATEGORY, item_type=4)
        refreshed_recruitment = _find_unique(
            refreshed, name=RECRUITMENT_CATEGORY, item_type=4
        )
        verified = build_admin_channel_plan(
            guild_id, refreshed, int(refreshed_admin["id"]), staff_role_ids
        )
        if any(
            item["actual_parent_id"] != int(refreshed_admin["id"])
            for item in verified
        ):
            raise RuntimeError("Canal administrativo ficou fora da categoria correta.")
        category_order = [
            item["name"]
            for item in sorted(
                [refreshed_recruitment, refreshed_admin, refreshed_courses],
                key=lambda item: int(item["position"]),
            )
        ]
        if category_order != [RECRUITMENT_CATEGORY, ADMIN_CATEGORY, COURSES_CATEGORY]:
            raise RuntimeError("Categorias não ficaram na ordem planejada.")
        print(
            json.dumps(
                {
                    "guild": guild["name"],
                    "admin_category_id": int(refreshed_admin["id"]),
                    "created": created,
                    "admin_channels": [item["key"] for item in verified],
                    "category_order": category_order,
                    "verified": True,
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
        description="Separa a administração do recrutamento no servidor de instrução."
    )
    parser.add_argument("--guild", type=int, default=DEFAULT_TARGET_GUILD_ID)
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(build_parser().parse_args())))
