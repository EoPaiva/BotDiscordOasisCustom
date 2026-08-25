from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.channel_names import format_channel_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from scripts.publish_system_updates import DiscordRest  # noqa: E402

CHANNEL_NAME = format_channel_name("Atualizacoes do bot", "🆕")
MESSAGE_MARKER = "CHOQUE - BGR • Atualização • REC CHOQUE"


def build_embed(config: AppConfig) -> dict[str, Any]:
    embed: dict[str, Any] = {
        "title": "✅ Recrutamento e Cursos no REC CHOQUE",
        "description": (
            "A estrutura paralela de **Recrutamento** e **Cursos** foi publicada no "
            "servidor REC CHOQUE sem retirar os painéis do servidor principal."
        ),
        "color": config.branding.embed_color,
        "timestamp": datetime.now(UTC).isoformat(),
        "fields": [
            {
                "name": "Estrutura entregue",
                "value": (
                    "Canais, cargos, permissões, mensagens fixadas, Mesa de Análise, "
                    "painel de Recrutamento e catálogo de Cursos foram provisionados."
                ),
                "inline": False,
            },
            {
                "name": "Dados e identidade",
                "value": (
                    "As identidades e qualificações usam o histórico canônico do servidor "
                    "principal, com separação por servidor e proteção contra duplicação."
                ),
                "inline": False,
            },
            {
                "name": "Validação",
                "value": (
                    "Portal oficial, recuperação após reinício, banco, painéis e reconciliação "
                    "foram verificados. A fase permanece paralela até o teste humano final."
                ),
                "inline": False,
            },
        ],
        "footer": {"text": MESSAGE_MARKER},
    }
    if config.branding.logo_url:
        embed["thumbnail"] = {"url": config.branding.logo_url}
    return embed


async def publish() -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("Configuração do Discord ausente.")

    api = DiscordRest(config.token)
    try:
        channels = await api.request("GET", f"/guilds/{config.default_guild_id}/channels")
        channel = next(
            (
                item
                for item in channels
                if item.get("type") == 0 and item.get("name") == CHANNEL_NAME
            ),
            None,
        )
        if channel is None:
            raise RuntimeError("O canal Atualizações do Bot não foi encontrado.")

        messages = await api.request("GET", f"/channels/{channel['id']}/messages?limit=100")
        if any(
            embed.get("footer", {}).get("text") == MESSAGE_MARKER
            for message in messages
            for embed in message.get("embeds", [])
        ):
            print("REC_MIGRATION_UPDATE_ALREADY_PUBLISHED")
            return 0

        message = await api.request(
            "POST",
            f"/channels/{channel['id']}/messages",
            payload={"embeds": [build_embed(config)], "allowed_mentions": {"parse": []}},
        )
        print(f"REC_MIGRATION_UPDATE_PUBLISHED message_id={message['id']}")
        return 0
    finally:
        await api.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(publish()))
