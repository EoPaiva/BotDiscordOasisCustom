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
    DEFAULT_TARGET_GUILD_ID,
    MAIN_SERVER_URL,
    DiscordRest,
    _button,
    _embed,
    _permission_overwrites,
    _role_key,
)

CHANNEL_NAME = format_channel_name("Entrar no Servidor Principal", "🚪")
CATEGORY_NAME = format_category_name(1, "Recrutamento")
TOPIC = "CHOQUE-BGR rec-migration:recruitment.main_server"
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


def channel_payload(guild_id: int, category_id: int, staff_role_ids: list[int]) -> dict[str, Any]:
    return {
        "name": CHANNEL_NAME,
        "type": 0,
        "parent_id": str(category_id),
        "topic": TOPIC,
        "permission_overwrites": _permission_overwrites(
            guild_id,
            staff_role_ids=staff_role_ids,
            private=True,
            writable=False,
        ),
    }


def message_payload() -> dict[str, Any]:
    return {
        "embeds": [
            _embed(
                "✅ Candidatura aprovada",
                "Parabéns pela aprovação. Use o botão abaixo para entrar no servidor principal da CHOQUE - BGR e continuar seu ingresso.",
                [
                    {
                        "name": "Próxima etapa",
                        "value": "Entre no servidor principal e siga as orientações da Portaria.",
                        "inline": False,
                    }
                ],
            )
        ],
        "components": [
            {
                "type": 1,
                "components": [
                    _button("Entrar no servidor principal", "🚪", url=MAIN_SERVER_URL)
                ],
            }
        ],
        "allowed_mentions": {"parse": []},
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
        category = _find_unique(channels, name=CATEGORY_NAME, item_type=4)
        staff_role_ids = [
            int(_find_unique(roles, name=name)["id"]) for name in STAFF_ROLES
        ]
        payload = channel_payload(guild_id, int(category["id"]), staff_role_ids)
        matches = [
            channel
            for channel in channels
            if int(channel.get("type", -1)) == 0
            and (str(channel.get("topic") or "") == TOPIC or str(channel["name"]) == CHANNEL_NAME)
        ]
        if len(matches) > 1:
            raise RuntimeError("Canal de ingresso duplicado no servidor de instrução.")
        created = not matches
        if created:
            channel = await api.request(
                "POST", f"/guilds/{guild_id}/channels", payload=payload
            )
        else:
            channel = await api.request(
                "PATCH", f"/channels/{matches[0]['id']}", payload=payload
            )

        messages = await api.request("GET", f"/channels/{channel['id']}/messages?limit=50")
        bot = await api.request("GET", "/users/@me")
        managed = [
            message
            for message in messages
            if int(message["author"]["id"]) == int(bot["id"])
            and any(
                str(embed.get("title")) == "✅ Candidatura aprovada"
                for embed in message.get("embeds", [])
            )
        ]
        if len(managed) > 1:
            raise RuntimeError("Mensagem de ingresso duplicada; correção manual necessária.")
        if managed:
            message = await api.request(
                "PATCH",
                f"/channels/{channel['id']}/messages/{managed[0]['id']}",
                payload=message_payload(),
            )
        else:
            message = await api.request(
                "POST", f"/channels/{channel['id']}/messages", payload=message_payload()
            )
        await api.request("PUT", f"/channels/{channel['id']}/pins/{message['id']}")
        print(
            json.dumps(
                {
                    "guild": guild["name"],
                    "channel_id": int(channel["id"]),
                    "message_id": int(message["id"]),
                    "created": created,
                    "pinned": True,
                    "url": MAIN_SERVER_URL,
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
        description="Cria o canal privado de ingresso no servidor principal."
    )
    parser.add_argument("--guild", type=int, default=DEFAULT_TARGET_GUILD_ID)
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(build_parser().parse_args())))
