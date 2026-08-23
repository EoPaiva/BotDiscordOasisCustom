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
from choque.time_utils import utc_now_ms  # noqa: E402

API_BASE = "https://discord.com/api/v10"
REQUIREMENTS_CHANNEL_ID = 1161840087483564092
LEGACY_REQUIREMENTS_MESSAGE_ID = 1202162594933121035
PANEL_TYPE = "RECRUITMENT_REQUIREMENTS"
REASON = "CHOQUE - BGR • atualização oficial dos requisitos de alistamento"
BRAND_COLOR = 0xB11226


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


def build_payload(public_url: str, logo_url: str | None) -> dict[str, Any]:
    parsed = urlsplit(public_url)
    status_url = f"{parsed.scheme}://{parsed.netloc}/minha-candidatura"
    embed: dict[str, Any] = {
        "title": "🛡️ ALISTAMENTO • CHOQUE - BGR",
        "description": (
            "A entrada no CHOQUE é um compromisso com disciplina, preparo e Roleplay policial "
            "responsável. Nosso processo foi feito para ser direto: você se candidata, recebe "
            "um protocolo e acompanha cada etapa sem exposição dos seus dados."
        ),
        "color": BRAND_COLOR,
        "fields": [
            {
                "name": "📋 REQUISITOS OBRIGATÓRIOS",
                "value": (
                    "• Ter **15 anos ou mais fora do personagem**.\n"
                    "• Possuir microfone funcional e comunicação clara.\n"
                    "• Demonstrar maturidade, respeito e compromisso.\n"
                    "• Ter disponibilidade para participar das atividades da corporação.\n"
                    "• Conhecer as bases do Roleplay e aceitar a hierarquia militar."
                ),
                "inline": False,
            },
            {
                "name": "🎮 ANTES DE INICIAR",
                "value": (
                    "• Estar no nível 10 ou superior.\n"
                    "• Ter em mãos o nick e o ID utilizados no BGR.\n"
                    "• Reservar alguns minutos para responder com calma e com suas próprias palavras."
                ),
                "inline": False,
            },
            {
                "name": "🎯 COMO FUNCIONA",
                "value": (
                    "`01` Clique em **Iniciar candidatura**.\n"
                    "`02` Responda às 10 questões sobre RP policial, comunicação e códigos Q.\n"
                    "`03` Receba seu protocolo e acompanhe o prazo inicial de até 72 horas.\n"
                    "`04` O Comando fará a decisão humana e poderá convocar uma entrevista."
                ),
                "inline": False,
            },
            {
                "name": "⚖️ CONDUTA DURANTE O PROCESSO",
                "value": (
                    "Responda com suas próprias palavras. Informações falsas, desrespeito ou "
                    "tentativa de burlar o processo podem encerrar a candidatura. A avaliação "
                    "considera coerência, postura e disposição para aprender — não respostas decoradas."
                ),
                "inline": False,
            },
            {
                "name": "🔄 TRANSFERÊNCIAS",
                "value": (
                    "Membros de outra corporação devem usar o fluxo específico de **Transferências**. "
                    "Não abra candidatura comum e transferência ao mesmo tempo."
                ),
                "inline": False,
            },
        ],
        "footer": {"text": "CHOQUE - BGR • Disciplina, preparo e responsabilidade"},
    }
    if logo_url:
        embed["thumbnail"] = {"url": logo_url}
    return {
        "content": "",
        "embeds": [embed],
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": "Iniciar candidatura",
                        "emoji": {"name": "📝"},
                        "url": public_url,
                    },
                    {
                        "type": 2,
                        "style": 5,
                        "label": "Acompanhar candidatura",
                        "emoji": {"name": "📨"},
                        "url": status_url,
                    },
                ],
            }
        ],
        "allowed_mentions": {"parse": []},
    }


async def persist_panel(config: AppConfig, message_id: int) -> None:
    guild_id = int(config.default_guild_id or 0)
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        settings = SettingsService(database)
        await settings.upsert_panel(
            guild_id, PANEL_TYPE, REQUIREMENTS_CHANNEL_ID, message_id
        )
        await database.execute(
            """
            INSERT INTO audit_logs(
                correlation_id, guild_id, action, before_json, after_json,
                reason, created_at, delivery_status
            ) VALUES (lower(hex(randomblob(16))), ?, 'RECRUITMENT_REQUIREMENTS_PUBLISHED',
                      NULL, ?, ?, ?, 'PENDING')
            """,
            (
                guild_id,
                json.dumps(
                    {"channel_id": REQUIREMENTS_CHANNEL_ID, "message_id": message_id}
                ),
                REASON,
                utc_now_ms(),
            ),
        )
    finally:
        await database.close()


async def run() -> int:
    parser = argparse.ArgumentParser(description="Publica os requisitos oficiais do recrutamento.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--public-url")
    parser.add_argument("--settings-only-message-id", type=int)
    args = parser.parse_args()
    config = AppConfig.load()
    if args.settings_only_message_id:
        await persist_panel(config, args.settings_only_message_id)
        print("RECRUITMENT_REQUIREMENTS_SETTINGS_PASS")
        return 0
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    public_url = (
        args.public_url
        or os.getenv("RECRUITMENT_PUBLIC_URL")
        or "https://web-plum-tau-82.vercel.app/recrutamento"
    ).strip()
    if not public_url.startswith("https://"):
        raise RuntimeError("A URL pública do recrutamento deve usar HTTPS.")

    api = DiscordRest(config.token)
    try:
        channel, messages = await asyncio.gather(
            api.request("GET", f"/channels/{REQUIREMENTS_CHANNEL_ID}"),
            api.request("GET", f"/channels/{REQUIREMENTS_CHANNEL_ID}/messages?limit=100"),
        )
        if int(channel.get("guild_id") or 0) != int(config.default_guild_id):
            raise RuntimeError("O canal de requisitos não pertence à guild configurada.")
        legacy = next(
            (
                message
                for message in messages
                if int(message["id"]) == LEGACY_REQUIREMENTS_MESSAGE_ID
            ),
            None,
        )
        existing = next(
            (
                message
                for message in messages
                if bool(message.get("author", {}).get("bot"))
                and any(
                    embed.get("title") == "🛡️ ALISTAMENTO • CHOQUE - BGR"
                    for embed in message.get("embeds", [])
                )
            ),
            None,
        )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = config.database_path.parent / "server_layout_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = backup_dir / f"recruitment_requirements_{stamp}.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "captured_at": stamp,
                    "channel": channel,
                    "legacy_message": legacy,
                    "existing_official_message": existing,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            "RECRUITMENT_REQUIREMENTS_PREVIEW_PASS "
            f"legacy_exists={bool(legacy)} official_exists={bool(existing)} "
            f"snapshot={snapshot_path.name}"
        )
        if not args.apply:
            return 0

        payload = build_payload(public_url, config.branding.logo_url)
        if existing:
            official = await api.request(
                "PATCH",
                f"/channels/{REQUIREMENTS_CHANNEL_ID}/messages/{existing['id']}",
                payload=payload,
            )
        else:
            official = await api.request(
                "POST",
                f"/channels/{REQUIREMENTS_CHANNEL_ID}/messages",
                payload=payload,
            )
        fetched = await api.request(
            "GET",
            f"/channels/{REQUIREMENTS_CHANNEL_ID}/messages/{official['id']}",
        )
        titles = [str(embed.get("title")) for embed in fetched.get("embeds", [])]
        if "🛡️ ALISTAMENTO • CHOQUE - BGR" not in titles:
            raise RuntimeError("A mensagem oficial não foi persistida corretamente.")
        if legacy and int(legacy["id"]) != int(official["id"]):
            await api.request(
                "DELETE",
                f"/channels/{REQUIREMENTS_CHANNEL_ID}/messages/{legacy['id']}",
            )
        await persist_panel(config, int(official["id"]))
        print(
            "RECRUITMENT_REQUIREMENTS_APPLY_PASS "
            f"message_id={official['id']} legacy_removed={bool(legacy)}"
        )
        return 0
    finally:
        await api.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
