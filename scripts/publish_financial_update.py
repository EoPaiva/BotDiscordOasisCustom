"""Publish one idempotent Central Financeira release note.

The updates channel must already exist in the canonical Discord layout registry.
This script never creates, moves or changes permissions on that channel and uses
Discord REST only (``login`` without ``connect``), preserving the single Gateway.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import discord

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402

PANEL_TYPE = "SYSTEM_UPDATE_FINANCIAL_AID_V1"
MESSAGE_MARKER = "CHOQUE - BGR • Central Financeira • Entrega v1"
AUDIT_CORRELATION_ID = "system-update-financial-aid-v1"
BOOTSTRAP_ACTOR_ID = 0


def build_financial_update_embed(config: AppConfig) -> discord.Embed:
    embed = discord.Embed(
        title="💰 Central Financeira disponível",
        description=(
            "A Central de Auxílio Financeiro foi concluída e validada. O apoio é sempre "
            "voluntário e não concede cargo funcional, promoção, prioridade, poder ou vantagem."
        ),
        color=config.branding.embed_color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="PIX gerado pelo próprio bot",
        value=(
            "O QR Code e o Pix Copia e Cola são gerados localmente. A confirmação de qualquer "
            "contribuição continua exclusivamente humana."
        ),
        inline=False,
    )
    embed.add_field(
        name="Transparência e privacidade",
        value=(
            "Metas, prestação de contas, sugestões e honrarias simbólicas possuem histórico "
            "auditável, opção de apoio anônimo e recuperação após reinício."
        ),
        inline=False,
    )
    embed.add_field(
        name="Destaques e reconhecimento simbólico",
        value=(
            "Contribuições confirmadas recebem uma publicação única no mural de Destaques "
            "Financeiros e uma honraria visual sem permissões. Identidade e valor só aparecem "
            "quando o apoiador autorizou; apoios anônimos continuam anônimos."
        ),
        inline=False,
    )
    embed.add_field(
        name="Segurança",
        value=(
            "A chave PIX não aparece em logs nem auditorias. Decisões financeiras e estornos "
            "exigem permissão administrativa e ficam registrados."
        ),
        inline=False,
    )
    if config.branding.logo_url:
        embed.set_thumbnail(url=config.branding.logo_url)
    embed.set_footer(text=MESSAGE_MARKER)
    return embed


def resolve_updates_channel_id(registry: object) -> int:
    if not isinstance(registry, dict):
        raise RuntimeError("Registro do layout Discord ausente ou inválido.")
    channels = registry.get("channels")
    raw_channel_id = channels.get("info.updates") if isinstance(channels, dict) else None
    if not str(raw_channel_id or "").isdigit():
        raise RuntimeError("O canal Atualizações do Bot não está no registro canônico.")
    return int(raw_channel_id)


def is_financial_release_message(message: discord.Message, bot_user_id: int) -> bool:
    return (
        message.author.id == bot_user_id
        and any(embed.footer and embed.footer.text == MESSAGE_MARKER for embed in message.embeds)
    )


def snapshot_message(message: discord.Message | None, guild_id: int) -> Path:
    destination = PROJECT_ROOT / "data" / "server_layout_backups"
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = destination / f"financial_update_{guild_id}_{stamp}.json"
    payload = {
        "captured_at": datetime.now(UTC).isoformat(),
        "message": None
        if message is None
        else {
            "id": message.id,
            "channel_id": message.channel.id,
            "content": message.content,
            "embeds": [embed.to_dict() for embed in message.embeds],
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def _find_existing_message(
    channel: discord.TextChannel,
    *,
    settings: SettingsService,
    guild_id: int,
    bot_user_id: int,
) -> discord.Message | None:
    panel = await settings.get_panel(guild_id, PANEL_TYPE)
    if panel is not None and int(panel["channel_id"]) == channel.id:
        try:
            message = await channel.fetch_message(int(panel["message_id"]))
        except discord.NotFound:
            pass
        else:
            if is_financial_release_message(message, bot_user_id):
                return message
    async for message in channel.history(limit=100):
        if is_financial_release_message(message, bot_user_id):
            return message
    return None


async def publish(*, dry_run: bool) -> dict[str, object]:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios para publicar a atualização.")

    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    settings = SettingsService(database)
    audit = AuditService(database, settings, config.branding)
    client = discord.Client(intents=discord.Intents.none())
    try:
        registry = await settings.get(config.default_guild_id, "discord_layout_registry_v2", {})
        channel_id = resolve_updates_channel_id(registry)
        await client.login(config.token)
        channel = await client.fetch_channel(channel_id)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != config.default_guild_id:
            raise RuntimeError("O destino registrado para Atualizações do Bot não é um canal de texto da guild oficial.")
        if client.user is None:
            raise RuntimeError("A identidade do bot não foi carregada para validar a publicação.")
        existing = await _find_existing_message(
            channel,
            settings=settings,
            guild_id=config.default_guild_id,
            bot_user_id=client.user.id,
        )
        result = {
            "channel_id": channel.id,
            "existing": existing is not None,
            "message_id": existing.id if existing else None,
        }
        if dry_run:
            return result

        snapshot = snapshot_message(existing, config.default_guild_id)
        embed = build_financial_update_embed(config)
        if existing is None:
            message = await channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            message = await existing.edit(
                content=None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        await settings.upsert_panel(config.default_guild_id, PANEL_TYPE, channel.id, message.id)
        already_audited = await database.fetchone(
            "SELECT id FROM audit_logs WHERE correlation_id=?",
            (AUDIT_CORRELATION_ID,),
        )
        if already_audited is None:
            await audit.record(
                config.default_guild_id,
                "FINANCIAL_AID_RELEASE_PUBLISHED",
                actor_id=BOOTSTRAP_ACTOR_ID,
                after={"panel_type": PANEL_TYPE, "channel_id": channel.id, "message_id": message.id},
                reason="Entrega validada da Central Financeira publicada sem dados PIX.",
                correlation_id=AUDIT_CORRELATION_ID,
                deliver_immediately=False,
            )
        return {
            **result,
            "message_id": message.id,
            "snapshot": str(snapshot),
            "published": True,
        }
    finally:
        await client.close()
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Publica a atualização idempotente da Central Financeira.")
    parser.add_argument("--apply", action="store_true", help="Cria ou edita a mensagem após validar o destino.")
    args = parser.parse_args()
    result = asyncio.run(publish(dry_run=not args.apply))
    summary = " ".join(f"{key}={value}" for key, value in result.items())
    print(f"FINANCIAL_UPDATE_OK {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
