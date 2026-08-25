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

from choque.config import AppConfig  # noqa: E402
from scripts.migrate_rec_choque import (  # noqa: E402
    DEFAULT_SOURCE_GUILD_ID,
    DEFAULT_TARGET_GUILD_ID,
    DiscordRest,
    _role_key,
)

TARGET_SOURCE_ROLE_NAMES = {
    "Membro Choque": "ᴍᴇᴍʙʀᴏ ᴄʜᴏǫᴜᴇ",
    "Candidato": "Candidato",
    "Responsável Recrutamento": "ʀᴇsᴘᴏɴsᴀᴠᴇʟ ʀᴇᴄʀᴜᴛᴀᴍᴇɴᴛᴏ",
    "Auxiliar Recrutamento": "ᴀᴜxɪʟɪᴀʀ ʀᴇᴄʀᴜᴛᴀᴍᴇɴᴛᴏ",
    "Instrutor de Cursos": "ɪɴsᴛʀᴜᴛᴏʀ ᴅᴇ ᴄᴜʀsᴏs",
}
TARGET_ONLY_TOP_ROLES = ("Comando REC",)
STABLE_ROLE_FIELDS = (
    "name",
    "permissions",
    "color",
    "hoist",
    "mentionable",
    "managed",
    "icon",
    "unicode_emoji",
)


def _position(role: dict[str, Any]) -> int:
    return int(role["position"])


def _find_unique_role(
    roles: list[dict[str, Any]], name: str, *, guild_label: str
) -> dict[str, Any]:
    matches = [role for role in roles if _role_key(str(role["name"])) == _role_key(name)]
    if len(matches) != 1:
        raise RuntimeError(
            f"Cargo {name!r} precisa existir uma única vez em {guild_label}; encontrados: {len(matches)}."
        )
    return matches[0]


def build_role_order_plan(
    source_roles: list[dict[str, Any]],
    target_roles: list[dict[str, Any]],
    bot_role_ids: set[int],
) -> dict[str, Any]:
    bot_roles = [role for role in target_roles if int(role["id"]) in bot_role_ids]
    if not bot_roles:
        raise RuntimeError("Cargo do bot não encontrado no REC CHOQUE.")
    bot_top_position = max(_position(role) for role in bot_roles)

    movable = [
        role
        for role in target_roles
        if str(role["name"]) != "@everyone" and not bool(role.get("managed"))
    ]
    unreachable = [role for role in movable if _position(role) >= bot_top_position]
    if unreachable:
        names = ", ".join(str(role["name"]) for role in unreachable)
        raise RuntimeError(f"Cargos fora do alcance do bot: {names}.")

    target_only: list[dict[str, Any]] = []
    source_backed: list[tuple[int, int, dict[str, Any]]] = []
    for target_role in movable:
        target_name = str(target_role["name"])
        if target_name in TARGET_ONLY_TOP_ROLES:
            target_only.append(target_role)
            continue
        source_name = TARGET_SOURCE_ROLE_NAMES.get(target_name, target_name)
        source_role = _find_unique_role(source_roles, source_name, guild_label="servidor principal")
        source_backed.append(
            (_position(source_role), int(source_role["id"]), target_role)
        )

    for name in TARGET_ONLY_TOP_ROLES:
        _find_unique_role(target_only, name, guild_label="REC CHOQUE")

    desired_bottom_to_top = [
        item[2] for item in sorted(source_backed, key=lambda item: (item[0], item[1]))
    ]
    desired_bottom_to_top.extend(
        _find_unique_role(target_only, name, guild_label="REC CHOQUE")
        for name in reversed(TARGET_ONLY_TOP_ROLES)
    )

    available_positions = sorted(_position(role) for role in movable)
    if len(desired_bottom_to_top) != len(available_positions):
        raise RuntimeError("Plano de hierarquia perdeu ou duplicou cargos.")

    assignments = [
        {
            "id": int(role["id"]),
            "name": str(role["name"]),
            "from": _position(role),
            "position": position,
        }
        for role, position in zip(desired_bottom_to_top, available_positions, strict=True)
    ]
    changes = [item for item in assignments if item["from"] != item["position"]]
    return {
        "bot_role_position": bot_top_position,
        "assignments": assignments,
        "changes": changes,
        "order_top_to_bottom": [
            str(role["name"]) for role in reversed(desired_bottom_to_top)
        ],
    }


def snapshot_role_attributes(roles: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        int(role["id"]): {field: role.get(field) for field in STABLE_ROLE_FIELDS}
        for role in roles
    }


def validate_role_attributes_unchanged(
    before: dict[int, dict[str, Any]], after_roles: list[dict[str, Any]]
) -> None:
    after = snapshot_role_attributes(after_roles)
    changed = [role_id for role_id, fields in before.items() if after.get(role_id) != fields]
    if changed:
        raise RuntimeError(f"Atributos de cargos mudaram durante a ordenação: {changed}.")


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token:
        raise RuntimeError("DISCORD_TOKEN não configurado.")
    source_guild_id = int(args.source_guild)
    target_guild_id = int(args.target_guild)
    api = DiscordRest(config.token)
    try:
        bot = await api.request("GET", "/users/@me")
        source_guild, target_guild, source_roles, target_roles, bot_member = await asyncio.gather(
            api.request("GET", f"/guilds/{source_guild_id}"),
            api.request("GET", f"/guilds/{target_guild_id}"),
            api.request("GET", f"/guilds/{source_guild_id}/roles"),
            api.request("GET", f"/guilds/{target_guild_id}/roles"),
            api.request("GET", f"/guilds/{target_guild_id}/members/{bot['id']}"),
        )
        if (
            target_guild_id != DEFAULT_TARGET_GUILD_ID
            and str(target_guild["name"]).casefold() != "rec choque"
        ):
            raise RuntimeError("O servidor de destino não corresponde ao REC CHOQUE.")

        bot_role_ids = {int(role_id) for role_id in bot_member.get("roles", [])}
        before = snapshot_role_attributes(target_roles)
        plan = build_role_order_plan(source_roles, target_roles, bot_role_ids)
        if args.apply and plan["changes"]:
            await api.request(
                "PATCH",
                f"/guilds/{target_guild_id}/roles",
                payload=[
                    {"id": str(item["id"]), "position": item["position"]}
                    for item in plan["assignments"]
                ],
            )
            after_roles = await api.request("GET", f"/guilds/{target_guild_id}/roles")
            validate_role_attributes_unchanged(before, after_roles)
            verification = build_role_order_plan(source_roles, after_roles, bot_role_ids)
            if verification["changes"]:
                raise RuntimeError("Discord não convergiu para a hierarquia planejada.")

        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "source_guild": source_guild["name"],
                    "target_guild": target_guild["name"],
                    "roles": len(plan["assignments"]),
                    "changes": len(plan["changes"]),
                    "bot_role_position": plan["bot_role_position"],
                    "order_top_to_bottom": plan["order_top_to_bottom"],
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
        description="Espelha no REC CHOQUE a ordem relativa dos cargos do servidor principal."
    )
    parser.add_argument("--source-guild", type=int, default=DEFAULT_SOURCE_GUILD_ID)
    parser.add_argument("--target-guild", type=int, default=DEFAULT_TARGET_GUILD_ID)
    parser.add_argument("--apply", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(build_parser().parse_args())))
