from __future__ import annotations

import asyncio
import io
import json
import logging
from typing import TYPE_CHECKING, Any, cast

import discord
from discord.ext import commands

from choque.channel_names import format_channel_name
from choque.embeds import branded_embed
from choque.errors import PermissionDenied, ValidationError
from choque.tickets import (
    TICKET_LABELS,
    TICKET_PRIORITY_LABELS,
    build_minimized_transcript,
)
from choque.time_utils import discord_timestamp
from choque.web_urls import recruitment_portal_url, recruitment_status_url
from cogs.config_ui import respond_error

STATUS_LABELS = {
    "PENDING": "🟡 Pendente",
    "IN_REVIEW": "🔎 Em análise",
    "APPROVED": "✅ Aprovado",
    "REJECTED": "❌ Negado",
    "CANCELLED": "⚪ Cancelado",
    "CLOSED": "🔒 Encerrado",
}
LOGGER = logging.getLogger(__name__)


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_guild_user(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    return interaction.user


async def require_reviewer(
    interaction: discord.Interaction, permission: str, module: str
) -> discord.Member:
    actor = await require_guild_user(interaction)
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(actor.guild.id, module)
    if not await bot.services.permissions.has(actor, permission):
        raise PermissionDenied("Você não possui permissão para analisar esta fila.")
    return actor


class ErrorView(discord.ui.View):
    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await respond_error(interaction, error)


class ErrorModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await respond_error(interaction, error)


async def build_recruitment_landing_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    requirements_id = await bot.services.settings.get(
        guild.id, "recruitment_requirements_channel_id"
    )
    registration_id = await bot.services.settings.get(
        guild.id, "registration_panel_channel_id"
    )
    embed = branded_embed(
        bot.config.branding,
        title="🪖 QUERO ENTRAR PARA A CHOQUE - BGR",
        description=(
            "**Este é o ponto de partida para quem ainda não faz parte da organização.**\n"
            "Você não precisa procurar outro canal: selecione **Candidatar-me agora** abaixo "
            "e o portal oficial abrirá diretamente."
        ),
    )
    embed.add_field(
        name="✅ Como fazer sua candidatura",
        value=(
            "`01` Clique em **Candidatar-me agora**.\n"
            "`02` Informe seus dados e responda a avaliação com atenção.\n"
            "`03` Revise as respostas e envie a candidatura.\n"
            "`04` Use **Acompanhar candidatura** para consultar cada atualização."
        ),
        inline=False,
    )
    embed.add_field(
        name="📌 Antes de enviar",
        value=(
            f"Confira os critérios em <#{requirements_id}>. "
            if requirements_id
            else "Confira os requisitos publicados nesta categoria. "
        )
        + "O portal não exige login pelo Discord, mas os dados informados precisam ser verdadeiros.",
        inline=False,
    )
    embed.add_field(
        name="📨 Depois do envio",
        value=(
            "Sua candidatura recebe um protocolo e segue para análise da equipe responsável. "
            "A classificação auxilia a triagem, mas a decisão final sempre é humana."
        ),
        inline=False,
    )
    embed.add_field(
        name="🪪 Já é membro ou já foi aprovado?",
        value=(
            f"Não abra uma nova candidatura. Conclua sua identificação na Portaria em "
            f"<#{registration_id}>."
            if registration_id
            else "Não abra uma nova candidatura. Use a Portaria Digital para concluir seu cadastro."
        ),
        inline=False,
    )
    return embed


def build_ticket_landing_embed(bot: ChoqueBot) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title="🎫 Central de Atendimento • CHOQUE - BGR",
        description=(
            "Abra uma candidatura, transferência, denúncia ou atendimento de outro assunto "
            "pelos botões. "
            "Os dados são privados e cada decisão fica registrada na auditoria."
        ),
    )


async def build_admin_queue_embed(bot: ChoqueBot, guild_id: int) -> discord.Embed:
    counts = await bot.services.tickets.pending_counts(guild_id)
    return branded_embed(
        bot.config.branding,
        title="📥 Fila de Recrutamento e Atendimento",
        description=(
            f"📝 Candidaturas: **{counts['CANDIDACY']}**\n"
            f"🔄 Transferências: **{counts['TRANSFER']}**\n"
            f"⚠️ Denúncias: **{counts['REPORT']}**\n"
            f"💬 Outros assuntos: **{counts['OTHER']}**\n\n"
            "Selecione uma fila. Duas decisões concorrentes nunca processam o mesmo item."
        ),
    )


def ticket_detail_embed(bot: ChoqueBot, ticket) -> discord.Embed:
    payload = json.loads(ticket["payload_json"])
    labels = {
        "mta_nick": "Nick MTA",
        "character_id": "ID do personagem",
        "age": "Idade",
        "availability": "Disponibilidade",
        "motivation": "Motivação",
        "origin_organization": "Organização de origem",
        "origin_rank": "Patente de origem",
        "details": "Relato",
        "evidence": "Evidência",
        "subject": "Assunto",
        "organization": "Organização",
        "representative": "Representante",
        "contact": "Contato",
        "profile": "Perfil institucional",
    }
    lines = [
        f"**{labels.get(key, key)}:** {str(value)[:700]}" for key, value in payload.items() if value
    ]
    embed = branded_embed(
        bot.config.branding,
        title=f"🎫 #{ticket['id']} • {TICKET_LABELS[ticket['ticket_type']]}",
        description=(
            f"**Solicitante:** <@{ticket['discord_id']}>\n"
            f"**Situação:** {STATUS_LABELS[ticket['status']]}\n"
            f"**Prioridade:** {TICKET_PRIORITY_LABELS.get(ticket['priority'], ticket['priority'])}\n"
            + (
                f"**Responsável:** <@{ticket['claimed_by']}>\n"
                if ticket["claimed_by"]
                else "**Responsável:** aguardando equipe\n"
            )
            + f"**Criado:** {discord_timestamp(ticket['submitted_at'], 'R')}\n"
            + (
                f"**Pessoa citada:** <@{ticket['subject_discord_id']}>\n"
                if ticket["subject_discord_id"]
                else ""
            )
            + "\n"
            + "\n".join(lines)
        ),
    )
    if ticket["review_reason"]:
        embed.add_field(name="Decisão", value=str(ticket["review_reason"])[:1024], inline=False)
    return embed


class CandidacyModal(ErrorModal, title="Candidatura CHOQUE - BGR"):
    mta_nick = discord.ui.TextInput(label="Nick no MTA", max_length=40)
    character_id = discord.ui.TextInput(label="ID do personagem", max_length=30, required=False)
    age = discord.ui.TextInput(label="Idade", max_length=3)
    availability = discord.ui.TextInput(label="Disponibilidade de horários", max_length=120)
    motivation = discord.ui.TextInput(
        label="Por que deseja entrar?", style=discord.TextStyle.paragraph, max_length=800
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_guild_user(interaction)
        bot = get_bot(interaction)
        await bot.services.modules.require_enabled(actor.guild.id, "RECRUITMENT")
        if not str(self.age).strip().isdigit():
            raise ValidationError("Informe uma idade válida.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket_id = await bot.services.tickets.create(
            actor.guild.id,
            actor.id,
            "CANDIDACY",
            {
                "mta_nick": str(self.mta_nick).strip(),
                "character_id": str(self.character_id).strip(),
                "age": int(str(self.age).strip()),
                "availability": str(self.availability).strip(),
                "motivation": str(self.motivation).strip(),
            },
        )
        cog = bot.get_cog("TicketCommands")
        room_mention = ""
        if isinstance(cog, TicketCommands):
            room = await cog.ensure_ticket_room(actor.guild, ticket_id)
            room_mention = f" Acompanhe em {room.mention}."
            await cog.refresh_admin_panel(actor.guild)
        await interaction.followup.send(
            f"✅ Candidatura **#{ticket_id}** enviada para a equipe de recrutamento.{room_mention}",
            ephemeral=True,
        )


class TransferModal(ErrorModal, title="Pedido de transferência"):
    mta_nick = discord.ui.TextInput(label="Nick no MTA", max_length=40)
    character_id = discord.ui.TextInput(label="ID do personagem", max_length=30, required=False)
    origin_organization = discord.ui.TextInput(label="Polícia/organização de origem", max_length=80)
    origin_rank = discord.ui.TextInput(label="Patente/cargo de origem", max_length=80)
    motivation = discord.ui.TextInput(
        label="Motivo da transferência", style=discord.TextStyle.paragraph, max_length=800
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_guild_user(interaction)
        bot = get_bot(interaction)
        await bot.services.modules.require_enabled(actor.guild.id, "RECRUITMENT")
        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket_id = await bot.services.tickets.create(
            actor.guild.id,
            actor.id,
            "TRANSFER",
            {
                "mta_nick": str(self.mta_nick).strip(),
                "character_id": str(self.character_id).strip(),
                "origin_organization": str(self.origin_organization).strip(),
                "origin_rank": str(self.origin_rank).strip(),
                "motivation": str(self.motivation).strip(),
            },
        )
        cog = bot.get_cog("TicketCommands")
        room_mention = ""
        if isinstance(cog, TicketCommands):
            room = await cog.ensure_ticket_room(actor.guild, ticket_id)
            room_mention = f" Acompanhe em {room.mention}."
            await cog.refresh_admin_panel(actor.guild)
        await interaction.followup.send(
            f"✅ Transferência **#{ticket_id}** enviada para análise.{room_mention}",
            ephemeral=True,
        )


class ReportModal(ErrorModal, title="Denúncia privada"):
    details = discord.ui.TextInput(
        label="Descreva o ocorrido", style=discord.TextStyle.paragraph, max_length=1200
    )
    evidence = discord.ui.TextInput(label="Link de evidência", max_length=300, required=False)

    def __init__(self, subject_id: int) -> None:
        super().__init__()
        self.subject_id = subject_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_guild_user(interaction)
        bot = get_bot(interaction)
        await bot.services.modules.require_enabled(actor.guild.id, "TICKETS")
        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket_id = await bot.services.tickets.create(
            actor.guild.id,
            actor.id,
            "REPORT",
            {"details": str(self.details).strip(), "evidence": str(self.evidence).strip()},
            subject_discord_id=self.subject_id,
        )
        cog = bot.get_cog("TicketCommands")
        room_mention = ""
        if isinstance(cog, TicketCommands):
            room = await cog.ensure_ticket_room(actor.guild, ticket_id)
            room_mention = f" Acompanhe em {room.mention}."
            await cog.refresh_admin_panel(actor.guild)
        await interaction.followup.send(
            f"✅ Denúncia **#{ticket_id}** registrada de forma privada.{room_mention}",
            ephemeral=True,
        )


class ReportTargetSelect(discord.ui.UserSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Selecione a pessoa citada", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ReportModal(self.values[0].id))


class ReportTargetView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(ReportTargetSelect())


class OtherSubjectModal(ErrorModal, title="Outro assunto"):
    subject = discord.ui.TextInput(label="Assunto", max_length=100)
    details = discord.ui.TextInput(
        label="Descreva como podemos ajudar",
        style=discord.TextStyle.paragraph,
        max_length=1200,
    )
    evidence = discord.ui.TextInput(
        label="Link ou referência adicional", max_length=300, required=False
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_guild_user(interaction)
        bot = get_bot(interaction)
        await bot.services.modules.require_enabled(actor.guild.id, "TICKETS")
        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket_id = await bot.services.tickets.create(
            actor.guild.id,
            actor.id,
            "OTHER",
            {
                "subject": str(self.subject).strip(),
                "details": str(self.details).strip(),
                "evidence": str(self.evidence).strip(),
            },
        )
        cog = bot.get_cog("TicketCommands")
        room_mention = ""
        if isinstance(cog, TicketCommands):
            room = await cog.ensure_ticket_room(actor.guild, ticket_id)
            room_mention = f" Acompanhe em {room.mention}."
            await cog.refresh_admin_panel(actor.guild)
        await interaction.followup.send(
            f"✅ Atendimento **#{ticket_id}** aberto em **Outro assunto**.{room_mention}",
            ephemeral=True,
        )


class PartnershipModal(ErrorModal, title="Solicitação de parceria"):
    organization = discord.ui.TextInput(label="Organização/servidor", max_length=100)
    representative = discord.ui.TextInput(label="Representante responsável", max_length=80)
    contact = discord.ui.TextInput(label="Contato ou convite", max_length=200)
    profile = discord.ui.TextInput(
        label="Atuação e público da organização",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )
    proposal = discord.ui.TextInput(
        label="Proposta de parceria",
        style=discord.TextStyle.paragraph,
        max_length=900,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_guild_user(interaction)
        bot = get_bot(interaction)
        await bot.services.modules.require_enabled(actor.guild.id, "TICKETS")
        await interaction.response.defer(ephemeral=True, thinking=True)
        organization = str(self.organization).strip()
        ticket_id = await bot.services.tickets.create(
            actor.guild.id,
            actor.id,
            "OTHER",
            {
                "subject": f"Parceria institucional • {organization}"[:100],
                "details": str(self.proposal).strip(),
                "organization": organization,
                "representative": str(self.representative).strip(),
                "contact": str(self.contact).strip(),
                "profile": str(self.profile).strip(),
            },
        )
        cog = bot.get_cog("TicketCommands")
        room_mention = ""
        if isinstance(cog, TicketCommands):
            room = await cog.ensure_ticket_room(actor.guild, ticket_id)
            room_mention = f" Acompanhe em {room.mention}."
            await cog.refresh_admin_panel(actor.guild)
        await interaction.followup.send(
            f"✅ Proposta institucional **#{ticket_id}** registrada.{room_mention}",
            ephemeral=True,
        )


async def send_my_tickets(interaction: discord.Interaction) -> None:
    actor = await require_guild_user(interaction)
    rows = await get_bot(interaction).services.tickets.mine(actor.guild.id, actor.id)
    lines = [
        f"**#{row['id']} • {TICKET_LABELS[row['ticket_type']]}**\n"
        f"└ {STATUS_LABELS[row['status']]} • {discord_timestamp(row['submitted_at'], 'R')}"
        for row in rows
    ]
    await interaction.response.send_message(
        embed=branded_embed(
            get_bot(interaction).config.branding,
            title="🎫 Meus atendimentos",
            description="\n\n".join(lines) or "Você ainda não possui atendimentos.",
        ),
        ephemeral=True,
    )


class RecruitmentPanelView(ErrorView):
    def __init__(self, public_url: str | None = None) -> None:
        super().__init__(timeout=None)
        if isinstance(public_url, str) and public_url.startswith("https://"):
            for item in tuple(self.children):
                if item.custom_id in {
                    "choque:recruitment:apply:v1",
                    "choque:recruitment:mine:v1",
                }:
                    self.remove_item(item)
            self.add_item(
                discord.ui.Button(
                    label="Candidatar-me agora",
                    emoji="🪖",
                    style=discord.ButtonStyle.link,
                    url=recruitment_portal_url(public_url),
                    row=0,
                )
            )
            self.add_item(
                discord.ui.Button(
                    label="Acompanhar candidatura",
                    emoji="📋",
                    style=discord.ButtonStyle.link,
                    url=recruitment_status_url(public_url),
                    row=0,
                )
            )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            actor = await require_guild_user(interaction)
            await get_bot(interaction).services.modules.require_enabled(
                actor.guild.id, "RECRUITMENT"
            )
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True

    @discord.ui.button(
        label="Candidatar-me",
        emoji="📝",
        style=discord.ButtonStyle.primary,
        custom_id="choque:recruitment:apply:v1",
        row=0,
    )
    async def apply(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        public_url = await get_bot(interaction).services.settings.get(
            interaction.guild.id, "recruitment_public_url"
        )
        if not isinstance(public_url, str) or not public_url.startswith("https://"):
            raise ValidationError("O portal de recrutamento ainda não foi publicado.")
        view = discord.ui.View(timeout=300)
        view.add_item(
            discord.ui.Button(
                label="Abrir alistamento",
                emoji="📝",
                url=recruitment_portal_url(public_url),
            )
        )
        await interaction.response.send_message(
            "Abra o portal oficial para iniciar ou continuar sua candidatura.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Minha candidatura",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:recruitment:mine:v1",
        row=0,
    )
    async def mine(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        public_url = await get_bot(interaction).services.settings.get(
            interaction.guild.id, "recruitment_public_url"
        )
        if not isinstance(public_url, str) or not public_url.startswith("https://"):
            raise ValidationError("O portal de recrutamento ainda não foi publicado.")
        view = discord.ui.View(timeout=300)
        view.add_item(
            discord.ui.Button(
                label="Consultar candidatura",
                emoji="📋",
                url=recruitment_status_url(public_url),
            )
        )
        await interaction.response.send_message(
            "Consulte seu protocolo, progresso e situação atual no portal.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Requisitos",
        emoji="📚",
        style=discord.ButtonStyle.success,
        custom_id="choque:recruitment:requirements:v1",
        row=1,
    )
    async def requirements(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel_id = await get_bot(interaction).services.settings.get(
            interaction.guild.id, "recruitment_requirements_channel_id"
        )
        await interaction.response.send_message(
            f"Consulte os requisitos em <#{channel_id}>."
            if channel_id
            else "O canal de requisitos ainda não foi configurado.",
            ephemeral=True,
        )


class TicketPanelView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Candidatura",
        emoji="📝",
        style=discord.ButtonStyle.primary,
        custom_id="choque:ticket:candidacy:v1",
    )
    async def candidacy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_guild_user(interaction)
        await get_bot(interaction).services.modules.require_enabled(actor.guild.id, "RECRUITMENT")
        await interaction.response.send_modal(CandidacyModal())

    @discord.ui.button(
        label="Transferência",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:ticket:transfer:v1",
    )
    async def transfer(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_guild_user(interaction)
        await get_bot(interaction).services.modules.require_enabled(actor.guild.id, "RECRUITMENT")
        await interaction.response.send_modal(TransferModal())

    @discord.ui.button(
        label="Denúncia",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        custom_id="choque:ticket:report:v1",
    )
    async def report(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_guild_user(interaction)
        await get_bot(interaction).services.modules.require_enabled(actor.guild.id, "TICKETS")
        await interaction.response.send_message(
            "Selecione a pessoa citada:", view=ReportTargetView(), ephemeral=True
        )

    @discord.ui.button(
        label="Outro assunto",
        emoji="💬",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:ticket:other:v1",
    )
    async def other(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_guild_user(interaction)
        await get_bot(interaction).services.modules.require_enabled(actor.guild.id, "TICKETS")
        await interaction.response.send_modal(OtherSubjectModal())

    @discord.ui.button(
        label="Meus atendimentos",
        emoji="📚",
        style=discord.ButtonStyle.success,
        custom_id="choque:ticket:mine:v1",
    )
    async def mine(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await send_my_tickets(interaction)


class TransferLandingView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Solicitar transferência",
        emoji="🔄",
        style=discord.ButtonStyle.primary,
        custom_id="choque:partnerships:transfer:v1",
    )
    async def transfer(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_guild_user(interaction)
        await get_bot(interaction).services.modules.require_enabled(actor.guild.id, "RECRUITMENT")
        await interaction.response.send_modal(TransferModal())

    @discord.ui.button(
        label="Meus pedidos",
        emoji="📚",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:partnerships:transfer:mine:v1",
    )
    async def mine(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await send_my_tickets(interaction)


class PartnershipLandingView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Propor parceria",
        emoji="🤝",
        style=discord.ButtonStyle.primary,
        custom_id="choque:partnerships:proposal:v1",
    )
    async def propose(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(PartnershipModal())

    @discord.ui.button(
        label="Meus atendimentos",
        emoji="📚",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:partnerships:proposal:mine:v1",
    )
    async def mine(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await send_my_tickets(interaction)


def build_transfer_landing_embed(bot: ChoqueBot) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="🔄 TRANSFERÊNCIA INSTITUCIONAL • CHOQUE - BGR",
        description=(
            "Canal oficial para integrantes de outras corporações que desejam solicitar ingresso "
            "por transferência. Cada pedido abre uma sala privada com a equipe responsável."
        ),
    )
    embed.add_field(
        name="📑 Documentação informada",
        value="Nick MTA • ID • organização de origem • patente atual • justificativa",
        inline=False,
    )
    embed.add_field(
        name="🧭 Fluxo de análise",
        value=(
            "`01` Envio da solicitação\n`02` Conferência de procedência\n"
            "`03` Entrevista, quando necessária\n`04` Decisão humana e registro"
        ),
        inline=False,
    )
    embed.add_field(
        name="⚠️ Importante",
        value="O envio não garante equivalência de patente nem aprovação automática.",
        inline=False,
    )
    return embed


def build_partnership_landing_embed(bot: ChoqueBot) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="🤝 RELAÇÕES INSTITUCIONAIS • CHOQUE - BGR",
        description=(
            "Espaço oficial para propostas de parceria, cooperação, divulgação ou ação conjunta. "
            "A conversa ocorre em uma sala privada após o envio do formulário."
        ),
    )
    embed.add_field(
        name="✅ Propostas bem-vindas",
        value="Projetos compatíveis • ações conjuntas • cooperação institucional • divulgação mútua",
        inline=False,
    )
    embed.add_field(
        name="🚫 Não avançam",
        value="Propostas sem responsável, sem escopo claro ou incompatíveis com as regras do servidor.",
        inline=False,
    )
    return embed


def build_terms_landing_embed(bot: ChoqueBot) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="📜 TERMOS INSTITUCIONAIS • CHOQUE - BGR",
        description=(
            "Toda transferência ou parceria deve respeitar a hierarquia, a confidencialidade, as "
            "regras internas e a autonomia de decisão da CHOQUE - BGR."
        ),
    )
    embed.add_field(
        name="🛡️ Princípios obrigatórios",
        value=(
            "Boa-fé • respeito institucional • proteção de dados • ausência de promessa de cargo • "
            "decisão final humana • registro auditável"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔒 Privacidade",
        value="Dados e documentos enviados são tratados apenas nas áreas privadas do atendimento.",
        inline=False,
    )
    return embed


def build_partnership_links(
    guild_id: int,
    transfer_channel_id: int,
    partners_channel_id: int,
    ticket_channel_id: int,
) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Transferências",
            emoji="🔄",
            url=f"https://discord.com/channels/{guild_id}/{transfer_channel_id}",
        )
    )
    view.add_item(
        discord.ui.Button(
            label="Parcerias",
            emoji="🤝",
            url=f"https://discord.com/channels/{guild_id}/{partners_channel_id}",
        )
    )
    view.add_item(
        discord.ui.Button(
            label="Outro assunto",
            emoji="🎫",
            url=f"https://discord.com/channels/{guild_id}/{ticket_channel_id}",
        )
    )
    return view


class TicketQueueSelect(discord.ui.Select):
    def __init__(
        self,
        rows,
        *,
        permission: str,
        module: str,
    ) -> None:
        self.permission = permission
        self.module = module
        options = [
            discord.SelectOption(
                label=f"#{row['id']} • {TICKET_LABELS[row['ticket_type']]}",
                description=f"Usuário {row['discord_id']}",
                value=str(row["id"]),
                emoji={
                    "CANDIDACY": "📝",
                    "TRANSFER": "🔄",
                    "REPORT": "⚠️",
                    "OTHER": "💬",
                }[row["ticket_type"]],
            )
            for row in rows[:25]
        ]
        super().__init__(placeholder="Selecione um atendimento", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_reviewer(interaction, self.permission, self.module)
        ticket = await get_bot(interaction).services.tickets.get(
            actor.guild.id, int(self.values[0])
        )
        await interaction.response.edit_message(
            content=None,
            embed=ticket_detail_embed(get_bot(interaction), ticket),
            view=TicketDecisionView(
                int(ticket["id"]), permission=self.permission, module=self.module
            ),
        )


class TicketQueueView(ErrorView):
    def __init__(self, rows, *, permission: str, module: str) -> None:
        super().__init__(timeout=300)
        self.permission = permission
        self.module = module
        self.add_item(TicketQueueSelect(rows, permission=permission, module=module))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            await require_reviewer(interaction, self.permission, self.module)
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True


async def open_queue(
    interaction: discord.Interaction,
    ticket_types: tuple[str, ...],
    *,
    permission: str,
    module: str,
) -> None:
    actor = await require_reviewer(interaction, permission, module)
    rows = await get_bot(interaction).services.tickets.pending(actor.guild.id, ticket_types)
    if not rows:
        await interaction.response.send_message("✅ Esta fila está vazia.", ephemeral=True)
        return
    await interaction.response.send_message(
        "Selecione um atendimento:",
        view=TicketQueueView(rows, permission=permission, module=module),
        ephemeral=True,
    )


class TicketDecisionModal(ErrorModal, title="Decisão do atendimento"):
    reason = discord.ui.TextInput(
        label="Motivo da decisão", style=discord.TextStyle.paragraph, max_length=800
    )

    def __init__(
        self,
        ticket_id: int,
        approved: bool,
        *,
        permission: str,
        module: str,
    ) -> None:
        super().__init__()
        self.ticket_id = ticket_id
        self.approved = approved
        self.permission = permission
        self.module = module

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_reviewer(interaction, self.permission, self.module)
        bot = get_bot(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket = await bot.services.tickets.decide(
            actor.guild.id,
            self.ticket_id,
            actor.id,
            approved=self.approved,
            reason=str(self.reason),
        )
        cog = bot.get_cog("TicketCommands")
        if isinstance(cog, TicketCommands):
            await cog.after_decision(actor.guild, ticket)
        await interaction.followup.send(
            f"✅ Atendimento **#{self.ticket_id}** marcado como "
            f"**{STATUS_LABELS[ticket['status']]}**.",
            ephemeral=True,
        )


class TicketDecisionView(ErrorView):
    def __init__(self, ticket_id: int, *, permission: str, module: str) -> None:
        super().__init__(timeout=300)
        self.ticket_id = ticket_id
        self.permission = permission
        self.module = module

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            await require_reviewer(interaction, self.permission, self.module)
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True

    @discord.ui.button(label="Aprovar", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            TicketDecisionModal(
                self.ticket_id,
                True,
                permission=self.permission,
                module=self.module,
            )
        )

    @discord.ui.button(label="Negar", emoji="❌", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            TicketDecisionModal(
                self.ticket_id,
                False,
                permission=self.permission,
                module=self.module,
            )
        )


class RecruitmentAdminPanelView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            await require_reviewer(interaction, "recruitment.review", "RECRUITMENT")
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True

    @discord.ui.button(
        label="Candidaturas",
        emoji="📝",
        style=discord.ButtonStyle.primary,
        custom_id="choque:recruitment:admin:candidacies:v1",
    )
    async def candidacies(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await open_queue(
            interaction,
            ("CANDIDACY",),
            permission="recruitment.review",
            module="RECRUITMENT",
        )

    @discord.ui.button(
        label="Transferências",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:recruitment:admin:transfers:v1",
    )
    async def transfers(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await open_queue(
            interaction,
            ("TRANSFER",),
            permission="recruitment.review",
            module="RECRUITMENT",
        )

    @discord.ui.button(
        label="Atualizar",
        emoji="🔄",
        style=discord.ButtonStyle.success,
        custom_id="choque:recruitment:admin:refresh:v1",
    )
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=await build_admin_queue_embed(get_bot(interaction), interaction.guild.id),
            view=self,
        )


class TicketAdminView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            await require_reviewer(interaction, "ticket.review", "TICKETS")
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True

    @discord.ui.button(label="Denúncias", emoji="⚠️", style=discord.ButtonStyle.danger)
    async def reports(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await open_queue(interaction, ("REPORT",), permission="ticket.review", module="TICKETS")

    @discord.ui.button(label="Outros assuntos", emoji="💬", style=discord.ButtonStyle.primary)
    async def others(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await open_queue(interaction, ("OTHER",), permission="ticket.review", module="TICKETS")

    @discord.ui.button(label="Todos", emoji="📥", style=discord.ButtonStyle.secondary)
    async def all(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await open_queue(
            interaction,
            ("CANDIDACY", "TRANSFER", "REPORT", "OTHER"),
            permission="ticket.review",
            module="TICKETS",
        )

    @discord.ui.button(label="Configuração", emoji="⚙️", style=discord.ButtonStyle.success)
    async def configuration(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_reviewer(interaction, "ticket.manage", "TICKETS")
        await interaction.response.send_message(
            embed=await build_ticket_configuration_embed(get_bot(interaction), actor.guild),
            view=TicketConfigurationView(),
            ephemeral=True,
        )


async def ticket_room_context(interaction: discord.Interaction):
    actor = await require_guild_user(interaction)
    if not interaction.channel_id:
        raise ValidationError("Canal de atendimento inválido.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(actor.guild.id, "TICKETS")
    room = await bot.services.tickets.room_by_channel(actor.guild.id, interaction.channel_id)
    if not room:
        raise ValidationError("Este canal não está vinculado a um atendimento.")
    ticket = await bot.services.tickets.get(actor.guild.id, int(room["ticket_id"]))
    return actor, bot, room, ticket


async def require_ticket_operator(
    interaction: discord.Interaction,
    permission: str = "ticket.manage",
):
    actor, bot, room, ticket = await ticket_room_context(interaction)
    if await bot.services.permissions.has(actor, permission):
        return actor, bot, room, ticket
    responsible_role_id = await bot.services.settings.get(
        actor.guild.id, "ticket_responsible_role_id"
    )
    if responsible_role_id and any(role.id == int(responsible_role_id) for role in actor.roles):
        return actor, bot, room, ticket
    raise PermissionDenied("Somente a equipe responsável por tickets pode executar esta ação.")


async def build_ticket_configuration_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    active = await bot.services.settings.get(guild.id, "ticket_active_category_id")
    archive = await bot.services.settings.get(guild.id, "ticket_archive_category_id")
    responsible = await bot.services.settings.get(guild.id, "ticket_responsible_role_id")
    transcript = await bot.services.settings.get(guild.id, "ticket_transcript_channel_id")
    bot_member = guild.me
    role = guild.get_role(int(responsible)) if responsible else None
    hierarchy_ok = bool(bot_member and role and bot_member.top_role > role)
    return branded_embed(
        bot.config.branding,
        title="⚙️ Configuração operacional de tickets",
        description=(
            f"**Categoria ativa:** {f'<#{active}>' if active else 'não configurada'}\n"
            f"**Categoria de arquivo:** {f'<#{archive}>' if archive else 'não configurada'}\n"
            f"**Cargo responsável:** {f'<@&{responsible}>' if responsible else 'não configurado'}\n"
            f"**Canal de transcrições:** {f'<#{transcript}>' if transcript else 'somente na sala'}\n"
            f"**Hierarquia do bot:** {'✅ válida' if hierarchy_ok else '⚠️ revisar'}\n\n"
            "As categorias são persistidas por ID. O painel público e os históricos não são recriados."
        ),
    )


class TicketCategorySelect(discord.ui.ChannelSelect):
    def __init__(self, setting_key: str, placeholder: str) -> None:
        self.setting_key = setting_key
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.category],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_reviewer(interaction, "ticket.manage", "TICKETS")
        category = self.values[0]
        await get_bot(interaction).services.settings.set(
            actor.guild.id, self.setting_key, category.id, actor.id
        )
        await get_bot(interaction).services.audit.record(
            actor.guild.id,
            "TICKET_CONFIGURATION_CHANGED",
            actor_id=actor.id,
            after={"setting": self.setting_key, "resource_id": category.id},
        )
        await interaction.response.edit_message(
            embed=await build_ticket_configuration_embed(get_bot(interaction), actor.guild),
            view=TicketConfigurationView(),
        )


class TicketResponsibleRoleSelect(discord.ui.RoleSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Cargo responsável por tickets", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_reviewer(interaction, "ticket.manage", "TICKETS")
        role = self.values[0]
        if role.is_default() or role.managed:
            raise ValidationError("Selecione um cargo editável e dedicado à equipe de tickets.")
        await get_bot(interaction).services.settings.set(
            actor.guild.id, "ticket_responsible_role_id", role.id, actor.id
        )
        await get_bot(interaction).services.audit.record(
            actor.guild.id,
            "TICKET_CONFIGURATION_CHANGED",
            actor_id=actor.id,
            after={"setting": "ticket_responsible_role_id", "resource_id": role.id},
        )
        await interaction.response.edit_message(
            embed=await build_ticket_configuration_embed(get_bot(interaction), actor.guild),
            view=TicketConfigurationView(),
        )


class TicketTranscriptChannelSelect(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Canal privado para transcrições",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_reviewer(interaction, "ticket.manage", "TICKETS")
        channel = self.values[0]
        await get_bot(interaction).services.settings.set(
            actor.guild.id, "ticket_transcript_channel_id", channel.id, actor.id
        )
        await get_bot(interaction).services.audit.record(
            actor.guild.id,
            "TICKET_CONFIGURATION_CHANGED",
            actor_id=actor.id,
            after={"setting": "ticket_transcript_channel_id", "resource_id": channel.id},
        )
        await interaction.response.edit_message(
            embed=await build_ticket_configuration_embed(get_bot(interaction), actor.guild),
            view=TicketConfigurationView(),
        )


class TicketConfigurationView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(
            TicketCategorySelect("ticket_active_category_id", "Categoria de tickets ativos")
        )
        self.add_item(
            TicketCategorySelect("ticket_archive_category_id", "Categoria de tickets arquivados")
        )
        self.add_item(TicketResponsibleRoleSelect())
        self.add_item(TicketTranscriptChannelSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            await require_reviewer(interaction, "ticket.manage", "TICKETS")
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True


class CloseTicketModal(ErrorModal, title="Encerrar atendimento"):
    reason = discord.ui.TextInput(
        label="Motivo do encerramento",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )
    confirmation = discord.ui.TextInput(
        label="Digite ENCERRAR para confirmar",
        min_length=8,
        max_length=8,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor, bot, _, ticket = await ticket_room_context(interaction)
        is_operator = await bot.services.permissions.has(actor, "ticket.manage")
        responsible_role_id = await bot.services.settings.get(
            actor.guild.id, "ticket_responsible_role_id"
        )
        is_responsible = bool(
            responsible_role_id and any(role.id == int(responsible_role_id) for role in actor.roles)
        )
        if actor.id != int(ticket["discord_id"]) and not (is_operator or is_responsible):
            raise PermissionDenied("Somente o solicitante ou a equipe responsável pode encerrar.")
        if str(self.confirmation).strip().upper() != "ENCERRAR":
            raise ValidationError("Confirmação inválida. Digite ENCERRAR.")

        await interaction.response.defer(ephemeral=True, thinking=True)
        closed = await bot.services.tickets.close_by_request(
            actor.guild.id,
            int(ticket["id"]),
            actor.id,
            str(self.reason),
        )
        await interaction.followup.send(
            f"🔒 Atendimento **#{ticket['id']}** encerrado. O canal será arquivado.",
            ephemeral=True,
        )
        cog = bot.get_cog("TicketCommands")
        if isinstance(cog, TicketCommands):
            await cog.archive_ticket_room(
                actor.guild,
                closed,
                actor.id,
                transcript_reason=f"Encerramento: {str(self.reason).strip()}",
            )
            await cog.refresh_admin_panel(actor.guild)


class ReopenTicketModal(ErrorModal, title="Reabrir atendimento"):
    reason = discord.ui.TextInput(
        label="Motivo da reabertura",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor, bot, room, _ = await require_ticket_operator(interaction, "ticket.reopen")
        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket = await bot.services.tickets.reopen(
            actor.guild.id, int(room["ticket_id"]), actor.id, str(self.reason)
        )
        cog = bot.get_cog("TicketCommands")
        if not isinstance(cog, TicketCommands):
            raise ValidationError("Módulo de tickets indisponível.")
        channel = await cog.restore_ticket_room(actor.guild, ticket, actor.id)
        await interaction.followup.send(
            f"🔓 Atendimento **#{ticket['id']}** reaberto na mesma sala: {channel.mention}.",
            ephemeral=True,
        )


class TranscriptReasonModal(ErrorModal, title="Gerar transcrição"):
    reason = discord.ui.TextInput(
        label="Finalidade da transcrição",
        min_length=3,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor, bot, _, ticket = await require_ticket_operator(interaction, "ticket.transcript")
        await interaction.response.defer(ephemeral=True, thinking=True)
        cog = bot.get_cog("TicketCommands")
        if not isinstance(cog, TicketCommands):
            raise ValidationError("Módulo de tickets indisponível.")
        transcript, metadata = await cog.generate_transcript(
            actor.guild, ticket, actor.id, str(self.reason)
        )
        await interaction.followup.send(
            f"✅ Transcrição #{metadata['id']} gerada e auditada.",
            file=discord.File(
                io.BytesIO(transcript.encode("utf-8")),
                filename=f"ticket-{int(ticket['id']):04d}.txt",
            ),
            ephemeral=True,
        )


class TicketPrioritySelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Defina a prioridade operacional",
            options=[
                discord.SelectOption(label="Baixa", value="LOW", emoji="🟢"),
                discord.SelectOption(label="Normal", value="NORMAL", emoji="🔵"),
                discord.SelectOption(label="Alta", value="HIGH", emoji="🟠"),
                discord.SelectOption(label="Urgente", value="URGENT", emoji="🔴"),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        actor, bot, room, _ = await require_ticket_operator(interaction, "ticket.priority.manage")
        ticket = await bot.services.tickets.set_priority(
            actor.guild.id, int(room["ticket_id"]), actor.id, self.values[0]
        )
        cog = bot.get_cog("TicketCommands")
        if isinstance(cog, TicketCommands):
            await cog.refresh_room_control(actor.guild, int(ticket["id"]))
        await interaction.response.edit_message(
            content=f"✅ Prioridade alterada para **{TICKET_PRIORITY_LABELS[ticket['priority']]}**.",
            view=None,
        )


class TicketPriorityView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=180)
        self.add_item(TicketPrioritySelect())


class TicketParticipantSelect(discord.ui.UserSelect):
    def __init__(self, *, remove: bool) -> None:
        self.remove = remove
        super().__init__(
            placeholder="Remover participante" if remove else "Adicionar participante",
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        actor, bot, room, _ = await require_ticket_operator(
            interaction, "ticket.participants.manage"
        )
        member = self.values[0]
        if member.bot:
            raise ValidationError("Bots não podem ser participantes do atendimento.")
        if self.remove:
            await bot.services.tickets.remove_participant(
                actor.guild.id, int(room["ticket_id"]), member.id, actor.id
            )
            allow = False
            message = f"✅ {member.mention} removido do atendimento."
        else:
            await bot.services.tickets.add_participant(
                actor.guild.id, int(room["ticket_id"]), member.id, actor.id
            )
            allow = True
            message = f"✅ {member.mention} adicionado ao atendimento."
        channel = interaction.channel
        if isinstance(channel, discord.TextChannel):
            await channel.set_permissions(
                member,
                view_channel=allow,
                read_message_history=allow,
                send_messages=allow,
                attach_files=allow,
                embed_links=allow,
                reason=f"Participante do ticket #{room['ticket_id']}",
            )
        await interaction.response.edit_message(content=message, view=None)


class TicketParticipantView(ErrorView):
    def __init__(self, *, remove: bool) -> None:
        super().__init__(timeout=180)
        self.add_item(TicketParticipantSelect(remove=remove))


class TicketRoomView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Assumir / liberar",
        emoji="🛡️",
        style=discord.ButtonStyle.primary,
        custom_id="choque:ticket:room:claim:v1",
        row=0,
    )
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor, bot, room, ticket = await require_ticket_operator(interaction, "ticket.claim")
        if ticket["claimed_by"] is None:
            updated = await bot.services.tickets.claim(
                actor.guild.id, int(room["ticket_id"]), actor.id
            )
            message = "✅ Você assumiu este atendimento."
        elif int(ticket["claimed_by"]) == actor.id:
            updated = await bot.services.tickets.release(
                actor.guild.id, int(room["ticket_id"]), actor.id
            )
            message = "✅ Atendimento devolvido à fila."
        else:
            raise ValidationError("O atendimento já possui outro responsável.")
        cog = bot.get_cog("TicketCommands")
        if isinstance(cog, TicketCommands):
            await cog.refresh_room_control(actor.guild, int(updated["id"]))
        await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(
        label="Prioridade",
        emoji="🚨",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:ticket:room:priority:v1",
        row=0,
    )
    async def priority(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_ticket_operator(interaction, "ticket.priority.manage")
        await interaction.response.send_message(
            "Selecione a prioridade:", view=TicketPriorityView(), ephemeral=True
        )

    @discord.ui.button(
        label="Adicionar pessoa",
        emoji="➕",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:ticket:room:add:v1",
        row=0,
    )
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_ticket_operator(interaction, "ticket.participants.manage")
        await interaction.response.send_message(
            "Selecione quem poderá acessar a sala:",
            view=TicketParticipantView(remove=False),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Remover pessoa",
        emoji="➖",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:ticket:room:remove:v1",
        row=0,
    )
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_ticket_operator(interaction, "ticket.participants.manage")
        await interaction.response.send_message(
            "Selecione quem perderá o acesso:",
            view=TicketParticipantView(remove=True),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Avisar solicitante",
        emoji="🔔",
        style=discord.ButtonStyle.success,
        custom_id="choque:ticket:room:notify:v1",
        row=1,
    )
    async def notify(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor, bot, room, ticket = await require_ticket_operator(interaction, "ticket.notify")
        cooldown = int(
            await bot.services.settings.get(
                actor.guild.id, "ticket_requester_notify_cooldown_seconds", 60
            )
        )
        await bot.services.tickets.mark_requester_notified(
            actor.guild.id, int(room["ticket_id"]), actor.id, cooldown_seconds=cooldown
        )
        await interaction.response.send_message(
            f"<@{ticket['discord_id']}> a equipe precisa da sua atenção neste atendimento.",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    @discord.ui.button(
        label="Transcrição",
        emoji="📄",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:ticket:room:transcript:v1",
        row=1,
    )
    async def transcript(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_ticket_operator(interaction, "ticket.transcript")
        await interaction.response.send_modal(TranscriptReasonModal())

    @discord.ui.button(
        label="Reabrir",
        emoji="🔓",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:ticket:room:reopen:v1",
        row=1,
    )
    async def reopen(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_ticket_operator(interaction, "ticket.reopen")
        await interaction.response.send_modal(ReopenTicketModal())

    @discord.ui.button(
        label="Encerrar",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="choque:ticket:room:close:v1",
        row=1,
    )
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CloseTicketModal())


class TicketCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._panel_lock = asyncio.Lock()
        self._room_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self.bot.add_view(RecruitmentPanelView())
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(RecruitmentAdminPanelView())
        self.bot.add_view(TicketRoomView())
        self.bot.add_view(TransferLandingView())
        self.bot.add_view(PartnershipLandingView())

    async def _layout_category(
        self,
        guild: discord.Guild,
        key: str,
    ) -> discord.CategoryChannel:
        setting_key = {
            "ticket": "ticket_active_category_id",
            "archive": "ticket_archive_category_id",
        }.get(key)
        configured_id = (
            await self.services.settings.get(guild.id, setting_key) if setting_key else None
        )
        configured = guild.get_channel(int(configured_id)) if configured_id else None
        if isinstance(configured, discord.CategoryChannel):
            return configured
        registry = await self.services.settings.get(guild.id, "discord_layout_registry_v2", {})
        category_id = (
            registry.get("categories", {}).get(key) if isinstance(registry, dict) else None
        )
        category = guild.get_channel(int(category_id)) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            raise ValidationError(f"Categoria registrada para {key} não foi encontrada.")
        return category

    async def _ticket_overwrites(
        self,
        guild: discord.Guild,
        requester: discord.Member,
        ticket_id: int | None = None,
        *,
        include_requester: bool = True,
        include_operational: bool = True,
    ) -> dict[Any, discord.PermissionOverwrite]:
        overwrites: dict[Any, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        if include_requester:
            overwrites[requester] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
            )
        responsible_role_id = (
            await self.services.settings.get(guild.id, "ticket_responsible_role_id")
            if include_operational
            else None
        )
        responsible_role = guild.get_role(int(responsible_role_id)) if responsible_role_id else None
        if responsible_role is not None:
            overwrites[responsible_role] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                manage_messages=True,
            )
        rows = await self.services.database.fetchall(
            """
            SELECT role_id FROM rbac_bindings
            WHERE guild_id=? AND profile IN ('COMANDO','ADMINISTRADOR')
            """,
            (guild.id,),
        )
        for row in rows:
            role = guild.get_role(int(row["role_id"]))
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    read_message_history=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    manage_messages=True,
                )
        bot_member = guild.me
        if bot_member is not None:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                manage_messages=True,
                manage_channels=True,
            )
        if ticket_id is not None and include_operational:
            for participant in await self.services.tickets.participants(guild.id, ticket_id):
                member = guild.get_member(int(participant["discord_id"]))
                if member is not None:
                    overwrites[member] = discord.PermissionOverwrite(
                        view_channel=True,
                        read_message_history=True,
                        send_messages=True,
                        attach_files=True,
                        embed_links=True,
                    )
        return overwrites

    async def ensure_ticket_room(
        self,
        guild: discord.Guild,
        ticket_id: int,
    ) -> discord.TextChannel:
        key = (guild.id, ticket_id)
        lock = self._room_locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                ticket = await self.services.tickets.get(guild.id, ticket_id)
                existing = await self.services.tickets.room_for_ticket(guild.id, ticket_id)
                if existing and existing["status"] == "OPEN":
                    channel = guild.get_channel(int(existing["channel_id"]))
                    if isinstance(channel, discord.TextChannel):
                        requester = guild.get_member(int(ticket["discord_id"]))
                        if requester is not None:
                            active_category = await self._layout_category(guild, "ticket")
                            archive_category = await self._layout_category(guild, "archive")
                            responsible_role_id = await self.services.settings.get(
                                guild.id, "ticket_responsible_role_id"
                            )
                            responsible_role = (
                                guild.get_role(int(responsible_role_id))
                                if responsible_role_id
                                else None
                            )
                            await self.services.tickets.set_room_resources(
                                guild.id,
                                ticket_id,
                                active_category_id=active_category.id,
                                archive_category_id=archive_category.id,
                                responsible_role_id=(
                                    responsible_role.id if responsible_role else None
                                ),
                            )
                            await channel.edit(
                                category=active_category,
                                overwrites=await self._ticket_overwrites(
                                    guild, requester, ticket_id
                                ),
                                sync_permissions=False,
                                reason=f"Reconciliação do ticket #{ticket_id}",
                            )
                            await self.refresh_room_control(guild, ticket_id)
                            if (
                                responsible_role is not None
                                and existing["responsible_role_mentioned_at"] is None
                            ):
                                await channel.send(
                                    content=(
                                        f"{responsible_role.mention} novo atendimento privado "
                                        f"aguardando equipe • protocolo **#{ticket_id}**."
                                    ),
                                    allowed_mentions=discord.AllowedMentions(
                                        users=False, roles=True, everyone=False
                                    ),
                                )
                                await self.services.tickets.mark_responsible_role_mentioned(
                                    guild.id,
                                    ticket_id,
                                    self.bot.user.id if self.bot.user else None,
                                )
                        return channel

                requester = guild.get_member(int(ticket["discord_id"]))
                if requester is None:
                    try:
                        requester = await guild.fetch_member(int(ticket["discord_id"]))
                    except discord.DiscordException as exc:
                        raise ValidationError(
                            "O solicitante não está mais disponível no servidor."
                        ) from exc
                category = await self._layout_category(guild, "ticket")
                archive = await self._layout_category(guild, "archive")
                responsible_role_id = await self.services.settings.get(
                    guild.id, "ticket_responsible_role_id"
                )
                responsible_role = (
                    guild.get_role(int(responsible_role_id)) if responsible_role_id else None
                )
                channel = await guild.create_text_channel(
                    format_channel_name(f"Ticket{ticket_id:04d}", "🎫"),
                    category=category,
                    overwrites=await self._ticket_overwrites(guild, requester, ticket_id),
                    topic=f"CHOQUE-BGR ticket_id={ticket_id}",
                    reason=f"Atendimento privado #{ticket_id}",
                )
                try:
                    await self.services.tickets.bind_room(
                        guild.id,
                        ticket_id,
                        channel.id,
                        active_category_id=category.id,
                        archive_category_id=archive.id,
                        responsible_role_id=responsible_role.id if responsible_role else None,
                    )
                    content = requester.mention
                    if responsible_role is not None:
                        content += f" • {responsible_role.mention}"
                    message = await channel.send(
                        content=content,
                        embed=ticket_detail_embed(self.bot, ticket),
                        view=TicketRoomView(),
                        allowed_mentions=discord.AllowedMentions(
                            users=True, roles=responsible_role is not None, everyone=False
                        ),
                    )
                    await self.services.tickets.set_room_message(
                        guild.id,
                        ticket_id,
                        message.id,
                    )
                    if responsible_role is not None:
                        await self.services.tickets.mark_responsible_role_mentioned(
                            guild.id, ticket_id, self.bot.user.id if self.bot.user else None
                        )
                except Exception:
                    try:
                        await channel.delete(reason=f"Rollback do atendimento #{ticket_id}")
                    except discord.DiscordException:
                        LOGGER.exception("Falha ao remover canal órfão do ticket %s", ticket_id)
                    raise
                return channel
        finally:
            if self._room_locks.get(key) is lock and not lock.locked():
                self._room_locks.pop(key, None)

    async def refresh_room_control(self, guild: discord.Guild, ticket_id: int) -> None:
        room = await self.services.tickets.room_for_ticket(guild.id, ticket_id)
        if not room or not room["control_message_id"]:
            return
        channel = guild.get_channel(int(room["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(int(room["control_message_id"]))
            ticket = await self.services.tickets.get(guild.id, ticket_id)
            await message.edit(embed=ticket_detail_embed(self.bot, ticket), view=TicketRoomView())
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            LOGGER.exception("Falha ao atualizar painel da sala do ticket %s", ticket_id)

    async def _transcript_payload(self, channel: discord.TextChannel) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = []
        async for message in channel.history(limit=1000, oldest_first=True):
            messages.append(
                {
                    "created_at": int(message.created_at.timestamp()),
                    "author_id": message.author.id,
                    "content": message.content,
                    "attachment_count": len(message.attachments),
                }
            )
        return messages

    async def generate_transcript(
        self,
        guild: discord.Guild,
        ticket,
        actor_id: int,
        reason: str,
    ):
        room = await self.services.tickets.room_for_ticket(guild.id, int(ticket["id"]))
        if not room:
            raise ValidationError("Sala do atendimento não encontrada.")
        channel = guild.get_channel(int(room["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            raise ValidationError("A sala do atendimento não está disponível.")
        payload = await self._transcript_payload(channel)
        content = build_minimized_transcript(int(ticket["id"]), payload)
        metadata = await self.services.tickets.record_transcript(
            guild.id,
            int(ticket["id"]),
            actor_id,
            content,
            len(payload),
            reason,
        )
        transcript_channel_id = await self.services.settings.get(
            guild.id, "ticket_transcript_channel_id"
        )
        transcript_channel = (
            guild.get_channel(int(transcript_channel_id)) if transcript_channel_id else None
        )
        if isinstance(transcript_channel, discord.TextChannel):
            await transcript_channel.send(
                content=(
                    f"Transcrição auditada do ticket **#{ticket['id']}** • "
                    f"SHA-256 `{metadata['content_sha256']}`"
                ),
                file=discord.File(
                    io.BytesIO(content.encode("utf-8")),
                    filename=f"ticket-{int(ticket['id']):04d}.txt",
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        return content, metadata

    async def restore_ticket_room(
        self,
        guild: discord.Guild,
        ticket,
        actor_id: int,
    ) -> discord.TextChannel:
        room = await self.services.tickets.room_for_ticket(guild.id, int(ticket["id"]))
        if not room:
            return await self.ensure_ticket_room(guild, int(ticket["id"]))
        channel = guild.get_channel(int(room["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return await self.ensure_ticket_room(guild, int(ticket["id"]))
        requester = guild.get_member(int(ticket["discord_id"]))
        if requester is None:
            requester = await guild.fetch_member(int(ticket["discord_id"]))
        active = await self._layout_category(guild, "ticket")
        await channel.edit(
            name=format_channel_name(f"Ticket{int(ticket['id']):04d}", "🎫"),
            category=active,
            overwrites=await self._ticket_overwrites(
                guild, requester, int(ticket["id"]), include_requester=True
            ),
            sync_permissions=False,
            reason=f"Reabertura do ticket #{ticket['id']} por {actor_id}",
        )
        await channel.send(
            embed=branded_embed(
                self.bot.config.branding,
                title=f"🔓 Atendimento #{ticket['id']} reaberto",
                description="A mesma sala e todo o histórico foram restaurados para continuidade.",
            )
        )
        await self.refresh_room_control(guild, int(ticket["id"]))
        return channel

    async def archive_ticket_room(
        self,
        guild: discord.Guild,
        ticket,
        actor_id: int,
        *,
        transcript_reason: str | None = None,
    ) -> None:
        room = await self.services.tickets.room_for_ticket(guild.id, int(ticket["id"]))
        if not room or room["status"] == "ARCHIVED":
            return
        channel = guild.get_channel(int(room["channel_id"]))
        await self.services.tickets.mark_room_closed(
            guild.id,
            int(ticket["id"]),
            actor_id,
            str(ticket["review_reason"] or "Atendimento encerrado."),
        )
        if isinstance(channel, discord.TextChannel):
            requester = guild.get_member(int(ticket["discord_id"]))
            try:
                if transcript_reason:
                    content, metadata = await self.generate_transcript(
                        guild, ticket, actor_id, transcript_reason
                    )
                    await channel.send(
                        content=f"📄 Transcrição final registrada • `{metadata['content_sha256']}`",
                        file=discord.File(
                            io.BytesIO(content.encode("utf-8")),
                            filename=f"ticket-{int(ticket['id']):04d}.txt",
                        ),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                await channel.send(
                    embed=branded_embed(
                        self.bot.config.branding,
                        title=f"🔒 Atendimento #{ticket['id']} encerrado",
                        description=(
                            f"**Situação final:** {STATUS_LABELS[ticket['status']]}\n"
                            f"**Motivo:** {ticket['review_reason'] or 'Atendimento encerrado.'}\n\n"
                            "O registro foi preservado no arquivo administrativo."
                        ),
                    )
                )
                archive = await self._layout_category(guild, "archive")
                if requester is None:
                    requester = await guild.fetch_member(int(ticket["discord_id"]))
                await channel.edit(
                    name=format_channel_name(f"Arquivo{int(ticket['id']):04d}", "📁"),
                    category=archive,
                    overwrites=await self._ticket_overwrites(
                        guild,
                        requester,
                        int(ticket["id"]),
                        include_requester=False,
                        include_operational=False,
                    ),
                    sync_permissions=False,
                    reason=f"Arquivamento do ticket #{ticket['id']}",
                )
            except discord.DiscordException:
                LOGGER.exception("Falha ao arquivar canal do ticket %s", ticket["id"])
                return
        await self.services.tickets.mark_room_archived(guild.id, int(ticket["id"]), actor_id)

    async def open_admin(self, interaction: discord.Interaction) -> None:
        actor = await require_reviewer(interaction, "ticket.review", "TICKETS")
        await interaction.response.send_message(
            embed=await build_admin_queue_embed(self.bot, actor.guild.id),
            view=TicketAdminView(),
            ephemeral=True,
        )

    async def publish_or_refresh(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        panel_type: str,
    ) -> discord.Message:
        if panel_type == "RECRUITMENT":
            embed = await build_recruitment_landing_embed(self.bot, guild)
            public_url = await self.services.settings.get(guild.id, "recruitment_public_url")
            view: discord.ui.View = RecruitmentPanelView(
                public_url if isinstance(public_url, str) else None
            )
        elif panel_type == "TICKET":
            embed = build_ticket_landing_embed(self.bot)
            view = TicketPanelView()
        elif panel_type == "RECRUITMENT_ADMIN":
            embed = await build_admin_queue_embed(self.bot, guild.id)
            view = RecruitmentAdminPanelView()
        elif panel_type == "TRANSFER":
            embed = build_transfer_landing_embed(self.bot)
            view = TransferLandingView()
        elif panel_type == "PARTNERSHIP":
            embed = build_partnership_landing_embed(self.bot)
            view = PartnershipLandingView()
        elif panel_type == "PARTNERSHIP_TERMS":
            embed = build_terms_landing_embed(self.bot)
            registry = await self.services.settings.get(
                guild.id,
                "discord_layout_registry_v2",
                {},
            )
            channels = registry.get("channels", {}) if isinstance(registry, dict) else {}
            required = {
                "transfer": channels.get("partnerships.transfers"),
                "partners": channels.get("partnerships.partners"),
                "ticket": channels.get("ticket.panel"),
            }
            if not all(required.values()):
                raise ValidationError("Registry de Transferências e Parcerias incompleto.")
            view = build_partnership_links(
                guild.id,
                int(required["transfer"]),
                int(required["partners"]),
                int(required["ticket"]),
            )
        else:
            raise ValidationError("Tipo de painel de atendimento inválido.")
        async with self._panel_lock:
            panel = await self.services.settings.get_panel(guild.id, panel_type)
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                    await message.edit(embed=embed, view=view)
                    return message
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            message = await channel.send(embed=embed, view=view)
            await self.services.settings.upsert_panel(guild.id, panel_type, channel.id, message.id)
            return message

    async def publish_partnership_panels(self, guild: discord.Guild) -> None:
        registry = await self.services.settings.get(
            guild.id,
            "discord_layout_registry_v2",
            {},
        )
        channels = registry.get("channels", {}) if isinstance(registry, dict) else {}
        targets = {
            "TRANSFER": channels.get("partnerships.transfers"),
            "PARTNERSHIP": channels.get("partnerships.partners"),
            "PARTNERSHIP_TERMS": channels.get("partnerships.terms"),
        }
        for panel_type, channel_id in targets.items():
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if not isinstance(channel, discord.TextChannel):
                raise ValidationError(f"Canal registrado ausente para {panel_type}.")
            await self.publish_or_refresh(guild, channel, panel_type)

    async def refresh_admin_panel(self, guild: discord.Guild) -> None:
        channel_id = await self.services.settings.get(guild.id, "recruitment_queue_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                await self.publish_or_refresh(guild, channel, "RECRUITMENT_ADMIN")
            except discord.DiscordException:
                LOGGER.exception("Falha ao atualizar fila de atendimento da guild %s", guild.id)

    async def after_decision(self, guild: discord.Guild, ticket) -> None:
        await self.refresh_admin_panel(guild)
        if ticket["ticket_type"] == "CANDIDACY" and ticket["member_application_id"]:
            member_cog = self.bot.get_cog("MemberCommands")
            if member_cog is not None:
                await member_cog.publish_application_for_review(
                    guild,
                    int(ticket["member_application_id"]),
                )
        requester = guild.get_member(int(ticket["discord_id"]))
        if requester:
            try:
                await requester.send(
                    f"Seu atendimento **#{ticket['id']} • "
                    f"{TICKET_LABELS[ticket['ticket_type']]}** foi atualizado para "
                    f"**{STATUS_LABELS[ticket['status']]}**.\n"
                    f"Motivo: {ticket['review_reason']}"
                )
            except discord.DiscordException:
                pass
        channel_key = None
        if ticket["ticket_type"] == "CANDIDACY":
            channel_key = (
                "recruitment_approved_channel_id"
                if ticket["status"] == "APPROVED"
                else "recruitment_rejected_channel_id"
            )
        elif ticket["ticket_type"] == "TRANSFER":
            channel_key = "transfer_results_channel_id"
        channel_id = (
            await self.services.settings.get(guild.id, channel_key) if channel_key else None
        )
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=ticket_detail_embed(self.bot, ticket))
            except discord.DiscordException:
                LOGGER.exception("Falha ao publicar resultado do atendimento %s", ticket["id"])
        await self.archive_ticket_room(
            guild,
            ticket,
            int(ticket["reviewed_by"] or 0),
            transcript_reason="Decisão administrativa final",
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        targets = {
            "RECRUITMENT": "recruitment_panel_channel_id",
            "TICKET": "ticket_panel_channel_id",
            "RECRUITMENT_ADMIN": "recruitment_queue_channel_id",
        }
        for guild in self.bot.guilds:
            if guild.me is not None:
                await self.services.settings.set(
                    guild.id,
                    "ticket_bot_role_id",
                    guild.me.top_role.id,
                    self.bot.user.id if self.bot.user else None,
                )
            for panel_type, setting_key in targets.items():
                channel_id = await self.services.settings.get(guild.id, setting_key)
                channel = guild.get_channel(int(channel_id)) if channel_id else None
                if isinstance(channel, discord.TextChannel):
                    try:
                        await self.publish_or_refresh(guild, channel, panel_type)
                    except Exception:
                        LOGGER.exception(
                            "Falha ao restaurar painel %s da guild %s", panel_type, guild.id
                        )
            try:
                await self.publish_partnership_panels(guild)
            except Exception:
                LOGGER.exception(
                    "Falha ao restaurar Transferências e Parcerias da guild %s", guild.id
                )
            for ticket in await self.services.tickets.tickets_requiring_rooms(guild.id):
                try:
                    await self.ensure_ticket_room(guild, int(ticket["id"]))
                except Exception:
                    LOGGER.exception("Falha ao restaurar canal privado do ticket %s", ticket["id"])
            rooms = await self.services.database.fetchall(
                "SELECT ticket_id FROM ticket_rooms WHERE guild_id=?",
                (guild.id,),
            )
            for room in rooms:
                await self.refresh_room_control(guild, int(room["ticket_id"]))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
