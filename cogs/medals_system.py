from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import discord
from discord.ext import commands

from choque.embeds import branded_embed

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MedalDefinition:
    key: str
    emoji: str
    name: str
    role_id: int
    summary: str
    criteria: str


MEDALS = (
    MedalDefinition(
        "BRAVERY",
        "🛡️",
        "Medalha da Bravura",
        1165945601733697616,
        "Reconhece atos de bravura ou feitos excepcionais em situação de combate.",
        "Ato comprovado, impacto excepcional e conduta compatível com os valores da corporação.",
    ),
    MedalDefinition(
        "PEACEKEEPER",
        "🕊️",
        "Medalha do Pacificador",
        1165947125067173929,
        "Destinada a militares e civis que prestaram serviço relevante à Força.",
        "Serviço específico que fortaleceu a instituição ou elevou seu prestígio.",
    ),
    MedalDefinition(
        "WAR",
        "⚔️",
        "Medalha de Guerra",
        1165948043686858783,
        "Distingue alta performance durante ação operacional ou defesa da corporação.",
        "Desempenho operacional acima do esperado, confirmado pela cadeia de comando.",
    ),
    MedalDefinition(
        "SERGEANT",
        "🎖️",
        "Medalha Sargento",
        1165952845904871537,
        "Premia sargentos e subtenentes que se destacam no serviço.",
        (
            "Atitude e liderança militar; qualidade do trabalho; capacidade técnico-profissional; "
            "confiabilidade; camaradagem; resistência física e mental."
        ),
    ),
    MedalDefinition(
        "HONOR",
        "⭐",
        "Medalha de Honra",
        1165955707108077619,
        "Reconhece membros com destaque consistente perante o Alto Comando.",
        "Histórico de conduta, entrega e contribuição institucional reconhecido pelo Comando.",
    ),
    MedalDefinition(
        "SHERIFF",
        "🤠",
        "Medalha Sheriff",
        1165960367080484904,
        "Reconhece destaque, empenho e interesse demonstrados durante o recrutamento.",
        "Participação relevante e conduta exemplar nas atividades de recrutamento.",
    ),
    MedalDefinition(
        "DISTINCTION",
        "🏅",
        "Medalha de Distinção",
        1165964069887541268,
        "Destinada a quem se destacou diretamente perante o 01 do CHOQUE.",
        "Concessão excepcional, fundamentada e registrada pela autoridade competente.",
    ),
)
MEDALS_BY_KEY = {medal.key: medal for medal in MEDALS}


def build_medals_embed(bot: ChoqueBot) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="🏅 QUADRO DE CONDECORAÇÕES • CHOQUE - BGR",
        description=(
            "**HONRA • MÉRITO • SERVIÇO**\n\n"
            "As condecorações registram feitos excepcionais e contribuições relevantes. Elas não "
            "substituem patente, função ou avaliação disciplinar e exigem decisão humana fundamentada."
        ),
    )
    for medal in MEDALS:
        embed.add_field(
            name=f"{medal.emoji} {medal.name}",
            value=f"<@&{medal.role_id}>\n{medal.summary}",
            inline=False,
        )
    embed.add_field(
        name="📜 Protocolo de concessão",
        value=(
            "A indicação deve apresentar fato, evidência e justificativa. A competência registrada "
            "no regulamento legado é do **01 do CHOQUE**; qualquer mudança deve ser formalizada antes "
            "de alterar esta publicação."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔎 Consulta detalhada",
        value="Use o seletor abaixo para consultar finalidade e critérios de cada medalha.",
        inline=False,
    )
    return embed


class MedalSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Consultar uma condecoração",
            custom_id="choque:medals:select:v1",
            options=[
                discord.SelectOption(
                    label=medal.name,
                    value=medal.key,
                    emoji=medal.emoji,
                    description=medal.summary[:100],
                )
                for medal in MEDALS
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        medal = MEDALS_BY_KEY[self.values[0]]
        bot = cast("ChoqueBot", interaction.client)
        embed = branded_embed(
            bot.config.branding,
            title=f"{medal.emoji} {medal.name}",
            description=f"**Identificação no Discord:** <@&{medal.role_id}>\n\n{medal.summary}",
        )
        embed.add_field(name="Critérios registrados", value=medal.criteria, inline=False)
        embed.add_field(
            name="Autoridade e auditoria",
            value=(
                "A concessão é humana, deve conter justificativa e precisa permanecer registrada "
                "na auditoria administrativa."
            ),
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class MedalsPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(MedalSelect())


class MedalsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._panel_lock = asyncio.Lock()
        self.bot.add_view(MedalsPanelView())

    async def publish_or_refresh(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
    ) -> discord.Message:
        async with self._panel_lock:
            panel = await self.services.settings.get_panel(guild.id, "MEDALS")
            message = None
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None
            if message is None:
                message = await channel.send(
                    embed=build_medals_embed(self.bot),
                    view=MedalsPanelView(),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                await message.edit(embed=build_medals_embed(self.bot), view=MedalsPanelView())
            await self.services.settings.upsert_panel(
                guild.id,
                "MEDALS",
                message.channel.id,
                message.id,
            )
            return message

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            registry = await self.services.settings.get(
                guild.id,
                "discord_layout_registry_v2",
                {},
            )
            channel_id = (
                registry.get("channels", {}).get("info.medals")
                if isinstance(registry, dict)
                else None
            )
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if not isinstance(channel, discord.TextChannel):
                LOGGER.error("Canal de medalhas não encontrado na guild %s", guild.id)
                continue
            try:
                await self.publish_or_refresh(guild, channel)
            except discord.DiscordException:
                LOGGER.exception("Falha ao publicar o quadro de medalhas da guild %s", guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MedalsCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot

