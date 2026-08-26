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

from choque.channel_names import format_channel_name  # noqa: E402
from choque.config import AppConfig, Branding  # noqa: E402

API_BASE = "https://discord.com/api/v10"
INFORMATION_CATEGORY_ID = 1161833335618801687
CHANNEL_NAME = format_channel_name("Atualizacoes do bot", "🆕")
CHANNEL_TOPIC = (
    "Atualizações oficiais do sistema CHOQUE - BGR. "
    "Publicação automática e histórico das melhorias."
)
MESSAGE_TITLE = "Atualizações do sistema"
MESSAGE_FOOTER = "CHOQUE - BGR • Sistema de Gestão • Atualizações oficiais"
AUDIT_REASON = "CHOQUE - BGR • criação do canal oficial de atualizações"


def build_update_embed(branding: Branding) -> dict[str, Any]:
    fields = [
        {
            "name": "✅ Portaria e cadastro",
            "value": (
                "O fluxo de cadastro voltou a abrir corretamente para quem precisa se identificar. "
                "Envio, revisão e aprovação foram validados com vínculo único, histórico preservado "
                "e retirada da ficha temporária após a decisão."
            ),
            "inline": False,
        },
        {
            "name": "✅ Central Financeira",
            "value": (
                "O botão Doar, a resposta privada, o QR Code PIX e o Pix Copia e Cola foram "
                "validados. Contribuições confirmadas recebem uma publicação única no mural de "
                "Destaques Financeiros e uma honraria visual sem permissões; identidade e valor "
                "só aparecem com consentimento. A confirmação continua exclusivamente humana."
            ),
            "inline": False,
        },
        {
            "name": "✅ Central de Tags",
            "value": (
                "Cada pedido agora permanece em uma única ficha com status e responsável visíveis. "
                "Os botões mudam conforme a etapa, ações raras ficam em Mais ações e a conclusão "
                "mantém o histórico sem controles. Todas as pendências anteriores foram convertidas "
                "para o novo formato, sem cartões ausentes ou duplicados após reinício."
            ),
            "inline": False,
        },
        {
            "name": "✅ Status do Bot",
            "value": (
                "Painel público com situação da API, site, cadastro, recrutamento, filas, "
                "auditoria, patrulhas e tags, incluindo manutenção e instabilidade."
            ),
            "inline": False,
        },
        {
            "name": "✅ Bate-ponto, patrulhas e viaturas",
            "value": (
                "Ponto automático por call, troca sem duplicar horas, viaturas duráveis, "
                "comandante por hierarquia e relatórios PTR auditados."
            ),
            "inline": False,
        },
        {
            "name": "✅ Carreira, mérito e oficialato",
            "value": (
                "Progressão segura até Cadete, mérito com decisão humana e candidatura a "
                "Oficial com questionário, entrevista e histórico."
            ),
            "inline": False,
        },
        {
            "name": "✅ Robô Analista local",
            "value": (
                "Resumo e organização de evidências sem provedor externo. A ferramenta apenas "
                "auxilia; aprovação e reprovação continuam obrigatoriamente humanas."
            ),
            "inline": False,
        },
        {
            "name": "✅ Qualidade e produção",
            "value": (
                "Testes automatizados e validações em produção concluídos. API e site saudáveis, "
                "com uma única instância do bot conectada."
            ),
            "inline": False,
        },
        {
            "name": "✅ Hierarquia detalhada",
            "value": (
                "Cada patente agora exibe próxima graduação, horas cumulativas, permanência "
                "mínima e tipo de progressão. De Subcomandante para cima não há requisito "
                "público comum; Comandante-Geral é exclusivo do proprietário."
            ),
            "inline": False,
        },
        {
            "name": "✅ Retorno do login corrigido",
            "value": (
                "Candidatura de Oficial e Central de Upamentos agora preservam a página escolhida "
                "durante o login pelo Discord, sem liberar redirecionamentos externos."
            ),
            "inline": False,
        },
        {
            "name": "✅ ADV e disciplina",
            "value": (
                "ADVs agora registram gravidade e prazo, mantêm histórico completo e podem expirar "
                "com segurança. O painel global mostra somente casos ativos e nenhuma punição é "
                "decidida automaticamente."
            ),
            "inline": False,
        },
        {
            "name": "✅ Cursos por canal",
            "value": (
                "Cada curso possui painel próprio com requisitos de patente, cargos, horas, tempo "
                "de corporação, curso anterior, suspensão e ADV. Após aprovação humana, a "
                "qualificação e o cargo são sincronizados sem duplicidade."
            ),
            "inline": False,
        },
        {
            "name": "✅ Transferências auditáveis",
            "value": (
                "O atendimento gera protocolo e histórico estáveis. A patente respeita o teto "
                "configurado e o vínculo só é aplicado depois de duas decisões humanas, sem "
                "concessão retroativa a pedidos antigos."
            ),
            "inline": False,
        },
        {
            "name": "✅ Registro de desligamentos",
            "value": (
                "Desligamentos oficiais agora geram um boletim durável e recuperável, sem apagar "
                "o histórico. Motivos internos permanecem privados e nenhuma saída é decidida "
                "automaticamente pelo sistema."
            ),
            "inline": False,
        },
        {
            "name": "✅ Aguardando configuração da tag",
            "value": (
                "O bot identifica quem ainda precisa configurar a tag, envia a confirmação "
                "privada uma única vez e encaminha impedimentos para atendimento humano. A "
                "conclusão mantém banco, cargos e painel sincronizados."
            ),
            "inline": False,
        },
        {
            "name": "🛡️ Informativo da Central de Tags",
            "value": (
                "A mensagem privada informativa e sua fila segura estão preparadas. O envio geral "
                "continua desligado até autorização específica; nenhum lote coletivo foi iniciado."
            ),
            "inline": False,
        },
    ]
    embed: dict[str, Any] = {
        "title": MESSAGE_TITLE,
        "description": (
            "Resumo das melhorias publicadas até **26/08/2026**. "
            "As próximas entregas oficiais também serão registradas neste canal."
        ),
        "color": branding.embed_color,
        "timestamp": datetime.now(UTC).isoformat(),
        "fields": fields,
        "footer": {"text": MESSAGE_FOOTER},
    }
    if branding.logo_url:
        embed["thumbnail"] = {"url": branding.logo_url}
    return embed


class DiscordRest:
    def __init__(self, token: str) -> None:
        self.session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": "DiscordBot (CHOQUE-BGR, 1.0)",
            }
        )

    async def close(self) -> None:
        await self.session.close()

    async def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | list[dict[str, Any]] | None = None,
        audit_reason: str | None = None,
    ) -> Any:
        headers = {}
        if audit_reason:
            headers["X-Audit-Log-Reason"] = quote(audit_reason, safe="")
        for _ in range(5):
            async with self.session.request(
                method,
                f"{API_BASE}{path}",
                json=payload,
                headers=headers,
            ) as response:
                if response.status == 429:
                    body = await response.json()
                    await asyncio.sleep(float(body.get("retry_after", 1)))
                    continue
                if response.status >= 400:
                    raise RuntimeError(
                        f"Discord recusou {method} {path}: HTTP {response.status}."
                    )
                if response.status == 204:
                    return None
                return await response.json()
        raise RuntimeError("Discord manteve rate limit após cinco tentativas.")


def _channel_snapshot(channels: list[dict[str, Any]]) -> dict[str, Any]:
    category = next(
        (item for item in channels if int(item["id"]) == INFORMATION_CATEGORY_ID), None
    )
    owned = next(
        (
            item
            for item in channels
            if item.get("type") == 0
            and item.get("parent_id") == str(INFORMATION_CATEGORY_ID)
            and item.get("name") == CHANNEL_NAME
        ),
        None,
    )
    return {"captured_at": datetime.now(UTC).isoformat(), "category": category, "channel": owned}


def _save_snapshot(guild_id: int, channels: list[dict[str, Any]]) -> Path:
    destination = PROJECT_ROOT / "data" / "server_layout_backups"
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = destination / f"updates_channel_{guild_id}_{stamp}.json"
    path.write_text(
        json.dumps(_channel_snapshot(channels), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _normalized_overwrites(items: list[dict[str, Any]]) -> list[tuple[str, int, str, str]]:
    return sorted(
        (
            str(item.get("id", "")),
            int(item.get("type", 0)),
            str(item.get("allow", "0")),
            str(item.get("deny", "0")),
        )
        for item in items
    )


async def publish(*, apply: bool) -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID precisam estar configurados.")

    api = DiscordRest(config.token)
    try:
        me = await api.request("GET", "/users/@me")
        channels = await api.request("GET", f"/guilds/{config.default_guild_id}/channels")
        category = next(
            (
                item
                for item in channels
                if int(item["id"]) == INFORMATION_CATEGORY_ID and item.get("type") == 4
            ),
            None,
        )
        if category is None:
            raise RuntimeError("A categoria Informações configurada não foi encontrada.")
        channel = next(
            (
                item
                for item in channels
                if item.get("type") == 0
                and item.get("parent_id") == str(INFORMATION_CATEGORY_ID)
                and item.get("name") == CHANNEL_NAME
            ),
            None,
        )
        if not apply:
            print(
                "UPDATES_CHECK_OK "
                f"category=true channel={str(channel is not None).lower()}"
            )
            return 0

        snapshot = _save_snapshot(config.default_guild_id, channels)
        channel_payload = {
            "name": CHANNEL_NAME,
            "type": 0,
            "topic": CHANNEL_TOPIC,
            "parent_id": str(INFORMATION_CATEGORY_ID),
            "permission_overwrites": category.get("permission_overwrites", []),
        }
        if channel is None:
            channel = await api.request(
                "POST",
                f"/guilds/{config.default_guild_id}/channels",
                payload=channel_payload,
                audit_reason=AUDIT_REASON,
            )
            created = True
        else:
            channel = await api.request(
                "PATCH",
                f"/channels/{channel['id']}",
                payload=channel_payload,
                audit_reason=AUDIT_REASON,
            )
            created = False

        messages = await api.request("GET", f"/channels/{channel['id']}/messages?limit=100")
        summary = next(
            (
                message
                for message in messages
                if message.get("author", {}).get("id") == me.get("id")
                and any(
                    embed.get("footer", {}).get("text") == MESSAGE_FOOTER
                    for embed in message.get("embeds", [])
                )
            ),
            None,
        )
        expected_embed = build_update_embed(config.branding)
        message_payload = {
            "embeds": [expected_embed],
            "allowed_mentions": {"parse": []},
        }
        if summary is None:
            summary = await api.request(
                "POST", f"/channels/{channel['id']}/messages", payload=message_payload
            )
        else:
            summary = await api.request(
                "PATCH",
                f"/channels/{channel['id']}/messages/{summary['id']}",
                payload=message_payload,
            )
        if not summary.get("pinned"):
            await api.request(
                "PUT",
                f"/channels/{channel['id']}/pins/{summary['id']}",
                audit_reason=AUDIT_REASON,
            )

        fresh_channel = await api.request("GET", f"/channels/{channel['id']}")
        pinned = await api.request("GET", f"/channels/{channel['id']}/pins")
        valid_message = any(item.get("id") == summary.get("id") for item in pinned)
        valid_content = any(
            embed.get("title") == MESSAGE_TITLE
            and embed.get("description") == expected_embed["description"]
            and embed.get("footer", {}).get("text") == MESSAGE_FOOTER
            and len(embed.get("fields", [])) == len(expected_embed["fields"])
            for embed in summary.get("embeds", [])
        )
        synced = _normalized_overwrites(
            fresh_channel.get("permission_overwrites", [])
        ) == _normalized_overwrites(
            category.get("permission_overwrites", [])
        )
        if (
            fresh_channel.get("name") != CHANNEL_NAME
            or fresh_channel.get("parent_id") != str(INFORMATION_CATEGORY_ID)
            or not valid_message
            or not valid_content
            or not synced
        ):
            raise RuntimeError(
                "A validação final do canal de atualizações falhou: "
                f"name={fresh_channel.get('name') == CHANNEL_NAME} "
                f"category={fresh_channel.get('parent_id') == str(INFORMATION_CATEGORY_ID)} "
                f"pinned={valid_message} content={valid_content} permissions={synced}."
            )
        print(
            "UPDATES_PUBLISH_OK "
            f"created={str(created).lower()} pinned=true content=true permissions_synced=true "
            f"channel_id={channel['id']} message_id={summary['id']} snapshot={snapshot}"
        )
        return 0
    finally:
        await api.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Publica o canal oficial de atualizações.")
    parser.add_argument("--apply", action="store_true", help="Cria/atualiza o canal e a mensagem.")
    args = parser.parse_args()
    return asyncio.run(publish(apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
