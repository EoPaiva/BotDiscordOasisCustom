from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from choque.channel_names import normalize_stylized_label  # noqa: E402
from choque.config import AppConfig  # noqa: E402

API_BASE = "https://discord.com/api/v10"
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
READ_MESSAGE_HISTORY = 1 << 16
ELITE_CHANNEL_ALLOW = VIEW_CHANNEL | SEND_MESSAGES | READ_MESSAGE_HISTORY


@dataclass(frozen=True, slots=True)
class RoleSpec:
    name: str
    normalized_name: str
    color: int
    hoist: bool = False


ROLE_SPECS = (
    RoleSpec("ʀᴇsᴘᴏɴsᴀᴠᴇʟ ᴇʟɪᴛᴇ", "responsavel elite", 0xC59A2E),
    RoleSpec("ᴀᴜxɪʟɪᴀʀ ᴇʟɪᴛᴇ", "auxiliar elite", 0x8C6A3A),
    RoleSpec("ᴇʟɪᴛᴇ", "elite", 0x7C1D1D, hoist=True),
)
CHANNEL_NAME = "🛡️・ᴄʜᴀᴛ-ᴇʟɪᴛᴇ"
CHANNEL_NORMALIZED_NAME = "chat elite"


def discord_request(
    path: str,
    token: str,
    *,
    method: str = "GET",
    payload: object | None = None,
) -> object:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{API_BASE}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "CHOQUE-BGR-Elite-Provisioner/1.0",
            "X-Audit-Log-Reason": "Configuração autorizada das Forças Especiais ELITE",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed Discord API base
            if response.status == 204:
                return {}
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"Discord recusou {method} {path}: HTTP {exc.code} {detail}") from exc


def normalized_name(item: dict[str, object]) -> str:
    return normalize_stylized_label(str(item.get("name") or ""))


def permission_overwrites(
    guild_id: int,
    bot_user_id: int,
    role_ids: list[int],
) -> list[dict[str, object]]:
    overwrites: list[dict[str, object]] = [
        {"id": str(guild_id), "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)},
        {
            "id": str(bot_user_id),
            "type": 1,
            "allow": str(ELITE_CHANNEL_ALLOW),
            "deny": "0",
        },
    ]
    overwrites.extend(
        {
            "id": str(role_id),
            "type": 0,
            "allow": str(ELITE_CHANNEL_ALLOW),
            "deny": "0",
        }
        for role_id in role_ids
    )
    return overwrites


def plan(config: AppConfig) -> dict[str, object]:
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    guild_id = int(config.default_guild_id)
    roles = discord_request(f"/guilds/{guild_id}/roles", config.token)
    channels = discord_request(f"/guilds/{guild_id}/channels", config.token)
    by_role_name = {normalized_name(item): item for item in roles}
    by_channel_name = {normalized_name(item): item for item in channels}
    chat_choque = by_channel_name.get("chat choque")
    if not chat_choque or not chat_choque.get("parent_id"):
        raise RuntimeError("O canal Chat Choque e sua categoria não foram localizados.")
    return {
        "guild_id": guild_id,
        "roles": [
            {
                "name": spec.name,
                "exists": spec.normalized_name in by_role_name,
            }
            for spec in ROLE_SPECS
        ],
        "channel": {
            "name": CHANNEL_NAME,
            "exists": CHANNEL_NORMALIZED_NAME in by_channel_name,
            "category_id": int(chat_choque["parent_id"]),
            "position": int(chat_choque.get("position") or 0) + 1,
        },
    }


def apply(config: AppConfig) -> dict[str, object]:
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    token = config.token
    guild_id = int(config.default_guild_id)
    bot_user = discord_request("/users/@me", token)
    roles = discord_request(f"/guilds/{guild_id}/roles", token)
    channels = discord_request(f"/guilds/{guild_id}/channels", token)
    by_role_name = {normalized_name(item): item for item in roles}
    by_channel_name = {normalized_name(item): item for item in channels}

    resolved_roles: list[dict[str, object]] = []
    created_roles = 0
    for spec in ROLE_SPECS:
        role = by_role_name.get(spec.normalized_name)
        payload = {
            "name": spec.name,
            "permissions": "0",
            "color": spec.color,
            "hoist": spec.hoist,
            "mentionable": False,
        }
        if role is None:
            role = discord_request(
                f"/guilds/{guild_id}/roles",
                token,
                method="POST",
                payload=payload,
            )
            created_roles += 1
        else:
            role = discord_request(
                f"/guilds/{guild_id}/roles/{role['id']}",
                token,
                method="PATCH",
                payload=payload,
            )
        resolved_roles.append(role)

    roles = discord_request(f"/guilds/{guild_id}/roles", token)
    responsibility_separator = next(
        (
            role
            for role in roles
            if normalized_name(role) == "responsabilidades"
        ),
        None,
    )
    if responsibility_separator:
        top = max(3, int(responsibility_separator["position"]) - 1)
        discord_request(
            f"/guilds/{guild_id}/roles",
            token,
            method="PATCH",
            payload=[
                {"id": str(role["id"]), "position": max(1, top - index)}
                for index, role in enumerate(resolved_roles)
            ],
        )

    chat_choque = by_channel_name.get("chat choque")
    if not chat_choque or not chat_choque.get("parent_id"):
        raise RuntimeError("O canal Chat Choque e sua categoria não foram localizados.")
    channel_payload = {
        "name": CHANNEL_NAME,
        "type": 0,
        "topic": "Canal reservado às Forças Especiais da CHOQUE.",
        "parent_id": str(chat_choque["parent_id"]),
        "position": int(chat_choque.get("position") or 0) + 1,
        "permission_overwrites": permission_overwrites(
            guild_id,
            int(bot_user["id"]),
            [int(role["id"]) for role in resolved_roles],
        ),
    }
    channel = by_channel_name.get(CHANNEL_NORMALIZED_NAME)
    created_channel = channel is None
    if channel is None:
        channel = discord_request(
            f"/guilds/{guild_id}/channels",
            token,
            method="POST",
            payload=channel_payload,
        )
    else:
        channel = discord_request(
            f"/channels/{channel['id']}",
            token,
            method="PATCH",
            payload=channel_payload,
        )

    actual_roles = discord_request(f"/guilds/{guild_id}/roles", token)
    actual_channels = discord_request(f"/guilds/{guild_id}/channels", token)
    actual_role_names = {normalized_name(item) for item in actual_roles}
    actual_channel = next(
        (item for item in actual_channels if normalized_name(item) == CHANNEL_NORMALIZED_NAME),
        None,
    )
    expected_overwrite_ids = {
        str(guild_id),
        str(bot_user["id"]),
        *(str(role["id"]) for role in resolved_roles),
    }
    actual_overwrite_ids = {
        str(item["id"]) for item in (actual_channel or {}).get("permission_overwrites", [])
    }
    missing_roles = [
        spec.normalized_name
        for spec in ROLE_SPECS
        if spec.normalized_name not in actual_role_names
    ]
    if missing_roles or actual_channel is None or expected_overwrite_ids - actual_overwrite_ids:
        raise RuntimeError("A validação final dos cargos ou do canal ELITE falhou.")
    return {
        "created_roles": created_roles,
        "roles_ready": len(resolved_roles),
        "created_channel": created_channel,
        "channel_ready": True,
        "restricted_overwrites": len(actual_overwrite_ids),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Provisiona a unidade ELITE sem Gateway extra.")
    parser.add_argument("--apply", action="store_true", help="Cria ou reconcilia no Discord.")
    args = parser.parse_args()
    config = AppConfig.load()
    result = apply(config) if args.apply else plan(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
