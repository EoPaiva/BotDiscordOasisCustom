from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

import discord
from discord import app_commands
from discord.ext import commands

from choque.embeds import branded_embed
from choque.errors import PermissionDenied, ValidationError
from choque.time_utils import format_duration

LOGGER = logging.getLogger(__name__)


def promotion_requirement_text(row: object) -> str:
    target_total_ms = row["target_total_ms"]
    if target_total_ms is not None:
        tenure_ms = int(row["minimum_tenure_ms"] or 0)
        tenure = (
            "sem permanência adicional"
            if tenure_ms == 0
            else f"{format_duration(tenure_ms)} na patente atual"
        )
        return (
            f"**Próxima:** {row['next_rank_name']}\n"
            f"**Requisito:** {format_duration(int(target_total_ms))} totais • {tenure}\n"
            "**Tipo:** progressão automática, após validações de cadastro, vínculo, "
            "punições e sincronização"
        )
    if int(row["level"]) == 8:
        return (
            "**Próxima:** Aspirante\n"
            "**Requisito:** mérito, candidatura ao Oficialato, avaliação e entrevista\n"
            "**Tipo:** decisão humana do Comando; horas isoladamente não promovem"
        )
    if int(row["level"]) == 18:
        return (
            "**Requisito:** não se aplica\n"
            "**Tipo:** cargo exclusivo do proprietário do servidor; não é promoção nem upamento"
        )
    if int(row["level"]) >= 16:
        return (
            "**Requisito:** não há requisito público de horas ou mérito\n"
            "**Tipo:** cargo estratégico por nomeação interna e critérios específicos do Comando"
        )
    if int(row["level"]) > 8:
        return (
            "**Requisito:** mérito, desempenho, necessidade institucional e histórico\n"
            "**Tipo:** promoção manual e auditada pelo Comando"
        )
    return "**Tipo:** promoção manual; nenhuma regra automática ativa"


class HierarchyCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._panel_lock = asyncio.Lock()

    async def build_embed(self, guild_id: int) -> discord.Embed:
        rows = await self.services.database.fetchall(
            """
            SELECT r.level, r.name, r.prefix, r.discord_role_id, r.rbac_profile,
                   COUNT(m.id) AS member_count,
                   cpr.target_total_ms, cpr.minimum_tenure_ms,
                   nr.name AS next_rank_name
            FROM ranks r LEFT JOIN members m ON m.rank_id=r.id AND m.status='ACTIVE'
            LEFT JOIN career_progression_rules cpr
              ON cpr.guild_id=r.guild_id AND cpr.from_rank_id=r.id AND cpr.enabled=1
            LEFT JOIN ranks nr ON nr.id=cpr.to_rank_id
            WHERE r.guild_id=? AND r.active=1
            GROUP BY r.id ORDER BY r.level DESC
            """,
            (guild_id,),
        )
        embed = branded_embed(
            self.bot.config.branding,
            title="CHOQUE - BGR • Hierarquia",
            description=(
                "Patentes e requisitos oficiais da carreira. As horas são cumulativas e contam "
                "somente pontos encerrados e validados. Até Cadete, o sistema pode promover "
                "automaticamente; acima disso, toda decisão é humana."
            ),
        )
        if not rows:
            embed.description = "Nenhuma patente ativa configurada."
            return embed
        guild = self.bot.get_guild(guild_id)
        strategic_role_ids = await self.services.settings.get(
            guild_id, "hierarchy_strategic_role_ids", []
        )
        if guild and isinstance(strategic_role_ids, list):
            strategic_lines = []
            for raw_role_id in strategic_role_ids:
                try:
                    role_id = int(raw_role_id)
                except (TypeError, ValueError):
                    continue
                discord_role = guild.get_role(role_id)
                if discord_role is None:
                    continue
                member_count = sum(not member.bot for member in discord_role.members)
                strategic_lines.append(
                    f"{discord_role.mention} • **{member_count}** membro(s) no cargo"
                )
            if strategic_lines:
                embed.add_field(
                    name="🛡️ Estrutura estratégica",
                    value="\n".join(strategic_lines),
                    inline=False,
                )
        for row in rows:
            role = f"<@&{row['discord_role_id']}>" if row["discord_role_id"] else "Sem cargo"
            member_count = int(row["member_count"])
            if guild and row["discord_role_id"]:
                discord_role = guild.get_role(int(row["discord_role_id"]))
                if discord_role:
                    # O cargo Discord é a verdade operacional; o banco permanece
                    # como fallback no modo de verificação sem conexão.
                    member_count = sum(not member.bot for member in discord_role.members)
            embed.add_field(
                name=f"{row['prefix']} {row['name']}".strip(),
                value=(
                    f"Nível `{row['level']}` • {role}\n"
                    f"{promotion_requirement_text(row)}\n"
                    f"Efetivo atual: **{member_count}** membro(s)"
                ),
                inline=False,
            )
        return embed

    async def publish_or_refresh(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        """Atualiza a mensagem registrada e evita painéis duplicados."""
        async with self._panel_lock:
            embed = await self.build_embed(guild.id)
            panel = await self.services.settings.get_panel(guild.id, "HIERARCHY")
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                    await message.edit(embed=embed)
                    return message
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            message = await channel.send(embed=embed)
            await self.services.settings.upsert_panel(guild.id, "HIERARCHY", channel.id, message.id)
            return message

    async def refresh_configured_panel(self, guild: discord.Guild) -> None:
        channel_id = await self.services.settings.get(guild.id, "hierarchy_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            await self.publish_or_refresh(guild, channel)

    @app_commands.command(name="hierarquia", description="Mostra a hierarquia CHOQUE - BGR.")
    @app_commands.describe(publicar="Publica e armazena o painel neste canal")
    async def hierarchy(self, interaction: discord.Interaction, publicar: bool = False) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            raise ValidationError("Este comando só pode ser usado no servidor.")
        if not publicar:
            await interaction.response.send_message(
                embed=await self.build_embed(interaction.guild.id), ephemeral=True
            )
            return
        if not await self.services.permissions.has(interaction.user, "panel.manage"):
            raise PermissionDenied("Você não possui permissão para publicar painéis.")
        if not isinstance(interaction.channel, discord.TextChannel):
            raise ValidationError("Use o comando em um canal de texto.")
        message = await self.publish_or_refresh(interaction.guild, interaction.channel)
        await self.services.settings.set(
            interaction.guild.id,
            "hierarchy_channel_id",
            interaction.channel.id,
            interaction.user.id,
        )
        await interaction.response.send_message(
            f"Painel de hierarquia atualizado em {message.channel.mention}.", ephemeral=True
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            try:
                await self.refresh_configured_panel(guild)
            except Exception:
                LOGGER.exception("Falha ao restaurar painel de hierarquia da guild %s", guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HierarchyCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
