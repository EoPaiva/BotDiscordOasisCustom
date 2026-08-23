from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402

API_BASE = "https://discord.com/api/v10"
APPROVED_CHANNEL_ID = 1166175384119812166
REJECTED_CHANNEL_ID = 1166176079724154910
REASON = "CHOQUE - BGR • modelos públicos do resultado de recrutamento"


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
        for _ in range(7):
            async with self.session.request(
                method,
                API_BASE + path,
                json=payload,
                headers={"X-Audit-Log-Reason": quote(REASON)},
            ) as response:
                if response.status == 429:
                    data = await response.json()
                    await asyncio.sleep(min(float(data.get("retry_after", 1)), 15.0))
                    continue
                if response.status == 204:
                    return None
                data = await response.json()
                if response.status >= 400:
                    message = data.get("message") if isinstance(data, dict) else str(data)
                    raise RuntimeError(f"Discord API {response.status}: {message}")
                return data
        raise RuntimeError("Discord API permaneceu limitada após as tentativas seguras.")


def payload(*, approved: bool, public_url: str) -> dict[str, Any]:
    parsed = urlsplit(public_url)
    status_url = f"{parsed.scheme}://{parsed.netloc}/minha-candidatura"
    title = (
        "🎖️ MODELO DE APROVAÇÃO • NÃO É RESULTADO REAL"
        if approved
        else "📋 MODELO DE REPROVAÇÃO • NÃO É RESULTADO REAL"
    )
    result = "APROVADA NO FORMULÁRIO" if approved else "NÃO APROVADA NO FORMULÁRIO"
    color = 0x71906D if approved else 0xA94F43
    description = (
        "**MISSÃO CUMPRIDA.** Este modelo apresenta como um protocolo aprovado será "
        "publicado, preservando a identidade do candidato."
        if approved
        else "Este modelo apresenta o encerramento formal de um protocolo sem aprovação, "
        "com discrição e respeito ao candidato."
    )
    next_step = (
        "🏅 Aguarde a convocação oficial para a próxima etapa do alistamento."
        if approved
        else "Consulte o protocolo no portal. Uma nova candidatura dependerá da abertura de outro ciclo."
    )
    return {
        "content": "",
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "author": {"name": "CHOQUE - BGR • COMANDO DE RECRUTAMENTO"},
                "fields": [
                    {"name": "Protocolo", "value": "`AL-EXEMPLO`", "inline": True},
                    {"name": "Resultado", "value": result, "inline": True},
                    {
                        "name": "Ordem do dia" if approved else "Orientação",
                        "value": next_step,
                        "inline": False,
                    },
                    {
                        "name": "Privacidade",
                        "value": (
                            "Os canais públicos exibem somente o protocolo. Nome, Discord, ID BGR, "
                            "respostas e pareceres permanecem restritos à equipe responsável."
                        ),
                        "inline": False,
                    },
                ],
                "footer": {"text": "CHOQUE - BGR • Sistema de Gestão"},
            }
        ],
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": "Acompanhar candidatura",
                        "emoji": {"name": "📨"},
                        "url": status_url,
                    }
                ],
            }
        ],
        "allowed_mentions": {"parse": []},
    }


async def persist_panels(config: AppConfig, approved_id: int, rejected_id: int) -> None:
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        settings = SettingsService(database)
        guild_id = int(config.default_guild_id or 0)
        await settings.upsert_panel(
            guild_id, "RECRUITMENT_APPROVED_EXAMPLE", APPROVED_CHANNEL_ID, approved_id
        )
        await settings.upsert_panel(
            guild_id, "RECRUITMENT_REJECTED_EXAMPLE", REJECTED_CHANNEL_ID, rejected_id
        )
    finally:
        await database.close()


async def publish_or_edit(
    api: DiscordRest, *, channel_id: int, approved: bool, public_url: str
) -> dict[str, Any]:
    messages = await api.request("GET", f"/channels/{channel_id}/messages?limit=100")
    existing = next(
        (
            message
            for message in messages
            if bool(message.get("author", {}).get("bot"))
            and any(
                "NÃO É RESULTADO REAL" in str(embed.get("title") or "")
                for embed in message.get("embeds", [])
            )
        ),
        None,
    )
    body = payload(approved=approved, public_url=public_url)
    if existing:
        return await api.request(
            "PATCH", f"/channels/{channel_id}/messages/{existing['id']}", payload=body
        )
    return await api.request("POST", f"/channels/{channel_id}/messages", payload=body)


async def run() -> int:
    parser = argparse.ArgumentParser(description="Publica exemplos anônimos de resultado.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--public-url")
    parser.add_argument("--settings-only-approved-message-id", type=int)
    parser.add_argument("--settings-only-rejected-message-id", type=int)
    args = parser.parse_args()
    config = AppConfig.load()
    if args.settings_only_approved_message_id and args.settings_only_rejected_message_id:
        await persist_panels(
            config,
            args.settings_only_approved_message_id,
            args.settings_only_rejected_message_id,
        )
        print("RECRUITMENT_RESULT_EXAMPLES_SETTINGS_PASS")
        return 0
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    public_url = (
        args.public_url
        or os.getenv("RECRUITMENT_PUBLIC_URL")
        or "https://web-plum-tau-82.vercel.app/recrutamento"
    ).strip()
    api = DiscordRest(config.token)
    try:
        approved_messages, rejected_messages = await asyncio.gather(
            api.request("GET", f"/channels/{APPROVED_CHANNEL_ID}/messages?limit=100"),
            api.request("GET", f"/channels/{REJECTED_CHANNEL_ID}/messages?limit=100"),
        )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = config.database_path.parent / "server_layout_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = backup_dir / f"recruitment_result_examples_{stamp}.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "captured_at": stamp,
                    "approved_messages": approved_messages,
                    "rejected_messages": rejected_messages,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            "RECRUITMENT_RESULT_EXAMPLES_PREVIEW_PASS "
            f"snapshot={snapshot_path.name}"
        )
        if not args.apply:
            return 0
        approved, rejected = await asyncio.gather(
            publish_or_edit(
                api,
                channel_id=APPROVED_CHANNEL_ID,
                approved=True,
                public_url=public_url,
            ),
            publish_or_edit(
                api,
                channel_id=REJECTED_CHANNEL_ID,
                approved=False,
                public_url=public_url,
            ),
        )
        await persist_panels(config, int(approved["id"]), int(rejected["id"]))
        print(
            "RECRUITMENT_RESULT_EXAMPLES_APPLY_PASS "
            f"approved_message_id={approved['id']} rejected_message_id={rejected['id']}"
        )
        return 0
    finally:
        await api.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
