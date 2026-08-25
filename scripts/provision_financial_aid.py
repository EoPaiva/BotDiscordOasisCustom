"""Provision the minimum Financial Aid channels without creating a second bot session.

The script is intentionally run inside the combined Discloud application after
the Finance module is deployed.  It uses Discord's REST client only (``login``
without ``connect``), reuses a configured/existing channel when possible and
persists destinations before the normal bot restart publishes the single
registered panel message in each channel.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

import discord

from choque.audit import AuditService
from choque.channel_names import format_channel_name
from choque.config import AppConfig
from choque.database import Database
from choque.financial_aid import FinancialAidService
from choque.settings import SettingsService

PUBLIC_CHANNEL_NAME = format_channel_name("Auxilio financeiro", "💰")
ADMIN_CHANNEL_NAME = format_channel_name("Administracao financeira", "🛡️")
HIGHLIGHTS_CHANNEL_NAME = format_channel_name("Destaques financeiros", "🏅")
BOOTSTRAP_ACTOR_ID = 0

_SMALL_CAPS = str.maketrans(
    {
        "ᴀ": "a",
        "ʙ": "b",
        "ᴄ": "c",
        "ᴅ": "d",
        "ᴇ": "e",
        "ꜰ": "f",
        "ɢ": "g",
        "ʜ": "h",
        "ɪ": "i",
        "ᴊ": "j",
        "ᴋ": "k",
        "ʟ": "l",
        "ᴍ": "m",
        "ɴ": "n",
        "ᴏ": "o",
        "ᴘ": "p",
        "ʀ": "r",
        "ꜱ": "s",
        "ᴛ": "t",
        "ᴜ": "u",
        "ᴠ": "v",
        "ᴡ": "w",
        "ʏ": "y",
        "ᴢ": "z",
    }
)


def normalized_channel_name(value: str) -> str:
    """Normalize regular and Small Caps channel labels for a safe category match."""

    # Mathematical alphabets only become ASCII after NFKD, so lower-case the
    # decomposed value as well as supporting the explicit Small Caps mapping.
    translated = value.translate(_SMALL_CAPS)
    decomposed = unicodedata.normalize("NFKD", translated).lower()
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", without_marks)


def select_parent_category(
    channels: Iterable[discord.abc.GuildChannel], *, purpose: str
) -> discord.CategoryChannel | None:
    categories = [channel for channel in channels if isinstance(channel, discord.CategoryChannel)]
    if purpose == "PUBLIC":
        accepted = ("informacoes", "informacao")
    elif purpose == "ADMIN":
        accepted = ("administracao", "centraladministrativa")
    else:
        raise ValueError(f"Finalidade de canal inválida: {purpose}")
    return next(
        (category for category in categories if any(token in normalized_channel_name(category.name) for token in accepted)),
        None,
    )


def admin_channel_is_private(
    channel: discord.TextChannel, admin_parent: discord.CategoryChannel
) -> bool:
    """Require the admin channel to stay inside Administration and deny @everyone."""
    if channel.category_id != admin_parent.id:
        return False
    everyone = channel.overwrites_for(channel.guild.default_role)
    return everyone.view_channel is False


def highlights_channel_is_read_only(
    channel: discord.TextChannel, public_parent: discord.CategoryChannel
) -> bool:
    """Keep the public recognition mural visible but protected from chat traffic."""

    if channel.category_id != public_parent.id:
        return False
    everyone = channel.overwrites_for(channel.guild.default_role)
    return bool(
        everyone.view_channel is True
        and everyone.read_message_history is True
        and everyone.send_messages is False
        and everyone.send_messages_in_threads is False
        and everyone.create_public_threads is False
        and everyone.create_private_threads is False
    )


def _can_publish(channel: discord.abc.GuildChannel, member: discord.Member) -> bool:
    permissions = channel.permissions_for(member)
    return bool(
        permissions.view_channel
        and permissions.send_messages
        and permissions.read_message_history
        and permissions.embed_links
    )


def _private_admin_overwrites(
    guild: discord.Guild, parent: discord.CategoryChannel
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites = dict(parent.overwrites)
    everyone = overwrites.get(guild.default_role, discord.PermissionOverwrite())
    everyone.view_channel = False
    everyone.send_messages = False
    everyone.read_message_history = False
    overwrites[guild.default_role] = everyone
    return overwrites


def _public_highlights_overwrites(
    guild: discord.Guild,
    parent: discord.CategoryChannel,
    bot_member: discord.Member,
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites = dict(parent.overwrites)
    everyone = overwrites.get(guild.default_role, discord.PermissionOverwrite())
    everyone.view_channel = True
    everyone.read_message_history = True
    everyone.send_messages = False
    everyone.send_messages_in_threads = False
    everyone.create_public_threads = False
    everyone.create_private_threads = False
    everyone.add_reactions = False
    overwrites[guild.default_role] = everyone
    bot_access = overwrites.get(bot_member, discord.PermissionOverwrite())
    bot_access.view_channel = True
    bot_access.read_message_history = True
    bot_access.send_messages = True
    bot_access.embed_links = True
    bot_access.manage_messages = True
    overwrites[bot_member] = bot_access
    return overwrites


async def _configured_or_named_channel(
    *,
    settings: SettingsService,
    guild_id: int,
    channels: list[discord.abc.GuildChannel],
    setting_key: str,
    expected_name: str,
) -> discord.TextChannel | None:
    configured = await settings.get(guild_id, setting_key)
    if configured:
        existing = next((channel for channel in channels if channel.id == int(configured)), None)
        if isinstance(existing, discord.TextChannel):
            return existing
    return next(
        (
            channel
            for channel in channels
            if isinstance(channel, discord.TextChannel) and channel.name == expected_name
        ),
        None,
    )


async def _ensure_standard_channel_name(
    channel: discord.TextChannel,
    expected_name: str,
) -> discord.TextChannel:
    """Rename the configured channel by ID without creating a duplicate."""

    if channel.name == expected_name:
        return channel
    updated = await channel.edit(
        name=expected_name,
        reason="Padronização visual Small Caps da Central Financeira",
    )
    return updated or channel


async def provision(*, dry_run: bool) -> dict[str, object]:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios para provisionar a Central Financeira.")

    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    settings = SettingsService(database)
    audit = AuditService(database, settings, config.branding)
    financial = FinancialAidService(database, settings, audit)
    client = discord.Client(intents=discord.Intents.none())
    try:
        await client.login(config.token)
        guild = await client.fetch_guild(config.default_guild_id)
        channels = list(await guild.fetch_channels())
        public_parent = select_parent_category(channels, purpose="PUBLIC")
        admin_parent = select_parent_category(channels, purpose="ADMIN")
        if public_parent is None:
            raise RuntimeError("Categoria Informações não foi encontrada; a Central pública não será criada fora de categoria.")
        if admin_parent is None:
            raise RuntimeError("Categoria Administração não foi encontrada; o painel privado não será criado fora de categoria.")
        public = await _configured_or_named_channel(
            settings=settings,
            guild_id=guild.id,
            channels=channels,
            setting_key="financial_panel_channel_id",
            expected_name=PUBLIC_CHANNEL_NAME,
        )
        admin = await _configured_or_named_channel(
            settings=settings,
            guild_id=guild.id,
            channels=channels,
            setting_key="financial_admin_channel_id",
            expected_name=ADMIN_CHANNEL_NAME,
        )
        highlights = await _configured_or_named_channel(
            settings=settings,
            guild_id=guild.id,
            channels=channels,
            setting_key="financial_highlights_channel_id",
            expected_name=HIGHLIGHTS_CHANNEL_NAME,
        )
        rejected_unsafe_admin = admin is not None and not admin_channel_is_private(admin, admin_parent)
        if rejected_unsafe_admin:
            admin = None
        if client.user is None:
            raise RuntimeError("A identidade do bot não foi carregada para validar as permissões.")
        bot_member = await guild.fetch_member(client.user.id)
        if (
            public is None
            or admin is None
            or highlights is None
            or not highlights_channel_is_read_only(highlights, public_parent)
        ) and not bot_member.guild_permissions.manage_channels:
            raise RuntimeError("O bot não possui Gerenciar Canais para criar a Central Financeira.")
        if public is not None and not _can_publish(public, bot_member):
            raise RuntimeError("O bot não consegue publicar no canal financeiro público existente.")
        if admin is not None and not _can_publish(admin, bot_member):
            raise RuntimeError("O bot não consegue publicar no painel financeiro administrativo existente.")
        if highlights is not None and not _can_publish(highlights, bot_member):
            raise RuntimeError("O bot não consegue publicar no canal de Destaques Financeiros existente.")
        if public is None and not _can_publish(public_parent, bot_member):
            raise RuntimeError("O bot não consegue publicar dentro da categoria Informações.")
        if admin is None and not _can_publish(admin_parent, bot_member):
            raise RuntimeError("O bot não consegue publicar dentro da categoria Administração.")

        result = {
            "public_existing": public is not None,
            "admin_existing": admin is not None,
            "highlights_existing": highlights is not None,
            "highlights_read_only": bool(
                highlights and highlights_channel_is_read_only(highlights, public_parent)
            ),
            "unsafe_admin_rejected": rejected_unsafe_admin,
            "public_parent": public_parent.name if public_parent else None,
            "admin_parent": admin_parent.name if admin_parent else None,
        }
        if dry_run:
            return result

        created: list[discord.TextChannel] = []
        try:
            if public is None:
                public = await guild.create_text_channel(
                    PUBLIC_CHANNEL_NAME,
                    category=public_parent,
                    reason="Central de Auxílio Financeiro da CHOQUE",
                )
                created.append(public)
            if admin is None:
                admin = await guild.create_text_channel(
                    ADMIN_CHANNEL_NAME,
                    category=admin_parent,
                    overwrites=_private_admin_overwrites(guild, admin_parent),
                    reason="Painel administrativo financeiro da CHOQUE",
                )
                created.append(admin)
            if highlights is None:
                highlights = await guild.create_text_channel(
                    HIGHLIGHTS_CHANNEL_NAME,
                    category=public_parent,
                    overwrites=_public_highlights_overwrites(guild, public_parent, bot_member),
                    reason="Destaques de apoio voluntário da CHOQUE",
                )
                created.append(highlights)
            public = await _ensure_standard_channel_name(public, PUBLIC_CHANNEL_NAME)
            admin = await _ensure_standard_channel_name(admin, ADMIN_CHANNEL_NAME)
            if not highlights_channel_is_read_only(highlights, public_parent):
                await highlights.edit(
                    name=HIGHLIGHTS_CHANNEL_NAME,
                    category=public_parent,
                    overwrites=_public_highlights_overwrites(guild, public_parent, bot_member),
                    reason="Proteção do mural público de Destaques Financeiros",
                )
            else:
                highlights = await _ensure_standard_channel_name(
                    highlights,
                    HIGHLIGHTS_CHANNEL_NAME,
                )
            if not admin_channel_is_private(admin, admin_parent):
                raise RuntimeError("O painel administrativo não ficou privado; provisionamento cancelado.")
            if not highlights_channel_is_read_only(highlights, public_parent):
                raise RuntimeError("O canal de Destaques Financeiros não ficou protegido contra mensagens.")
            if (
                not _can_publish(public, bot_member)
                or not _can_publish(admin, bot_member)
                or not _can_publish(highlights, bot_member)
            ):
                raise RuntimeError("O bot não possui as permissões de publicação nos canais provisionados.")
            await financial.ensure_defaults(guild.id)
            await financial.configure_panel_channels(
                guild.id,
                actor_id=BOOTSTRAP_ACTOR_ID,
                public_channel_id=public.id,
                admin_channel_id=admin.id,
            )
            await financial.configure_highlights_channel(
                guild.id,
                actor_id=BOOTSTRAP_ACTOR_ID,
                channel_id=highlights.id,
            )
        except Exception:
            for channel in reversed(created):
                try:
                    await channel.delete(reason="Rollback de provisionamento financeiro incompleto")
                except discord.DiscordException:
                    pass
            raise
        return {
            **result,
            "public_configured": True,
            "admin_configured": True,
            "highlights_configured": True,
            "highlights_read_only": True,
        }
    finally:
        await client.close()
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Provisiona os canais mínimos da Central Financeira.")
    parser.add_argument("--dry-run", action="store_true", help="Valida categorias e reutilização sem alterar Discord ou banco.")
    args = parser.parse_args()
    result: dict[str, Any] = asyncio.run(provision(dry_run=args.dry_run))
    summary = " ".join(f"{key}={value}" for key, value in result.items())
    print(f"FINANCIAL_PROVISION_OK {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
