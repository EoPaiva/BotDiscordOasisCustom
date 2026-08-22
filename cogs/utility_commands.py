from __future__ import annotations

from typing import TYPE_CHECKING, cast

import discord
from discord import app_commands
from discord.ext import commands

from choque.embeds import branded_embed
from choque.time_utils import discord_timestamp


class UtilityCommands(commands.Cog):
    info_group = app_commands.Group(name="bot", description="Informações do bot")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)

    @app_commands.command(name="ajuda", description="Lista os recursos desta entrega.")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = branded_embed(
            self.bot.config.branding,
            title="CHOQUE - BGR • Central de comandos",
            description=(
                "**Ponto:** `/ponto iniciar`, `/ponto finalizar`, `/ponto status`, `/ponto painel`\n"
                "**Horas:** `/horas hoje`, `/horas semana`, `/horas mes`, `/horas total`\n"
                "**Efetivo:** `/servico ativos`, `/servico painel`\n"
                "**Membros:** `/membro cadastrar`, `/membro perfil`, `/membro painel`\n"
                "**Configuração:** `/configurar status` e grupos administrativos\n\n"
                "Farm, Caixa, Resgate e Ausência legados estão preservados, mas desativados."
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @info_group.command(name="status", description="Mostra a saúde do processo e do banco.")
    async def status(self, interaction: discord.Interaction) -> None:
        migration = await self.bot.services.database.fetchone(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        )
        pending = await self.bot.services.database.fetchone(
            "SELECT COUNT(*) AS total FROM audit_logs WHERE delivery_status!='DELIVERED'"
        )
        embed = branded_embed(self.bot.config.branding, title="Status operacional")
        embed.add_field(name="Latência", value=f"{self.bot.latency * 1000:.0f} ms")
        embed.add_field(name="Migration", value=f"v{migration['version']}")
        embed.add_field(name="Outbox pendente", value=str(pending["total"]))
        embed.add_field(
            name="Processo iniciado",
            value=discord_timestamp(self.bot.started_at, "R"),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @info_group.command(name="sobre", description="Mostra a versão e arquitetura.")
    async def about(self, interaction: discord.Interaction) -> None:
        from choque import __version__

        embed = branded_embed(
            self.bot.config.branding,
            title="CHOQUE - BGR",
            description=(
                f"Versão `{__version__}`\n"
                "Monólito modular em Python, discord.py e SQLite transacional."
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
