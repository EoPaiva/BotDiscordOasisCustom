from __future__ import annotations

import asyncio
import json
import logging
from io import BytesIO
from typing import TYPE_CHECKING, cast

import discord
from discord.ext import commands, tasks

from choque.channel_names import format_channel_name
from choque.embeds import branded_embed
from choque.errors import NotFoundError, PermissionDenied, ValidationError
from choque.financial_aid import FinancialAidService
from choque.time_utils import discord_timestamp

from .config_ui import respond_error

if TYPE_CHECKING:
    from choque.bot import ChoqueBot


LOGGER = logging.getLogger(__name__)
PUBLIC_PANEL_MARKER = "Central Financeira Pública v1"
ADMIN_PANEL_MARKER = "Central Financeira Administrativa v1"
HIGHLIGHTS_PANEL_MARKER = "Destaques Financeiros v1"
PUBLIC_FINANCIAL_CHANNEL_NAME = format_channel_name("Auxilio financeiro", "💰")

HONOR_ROLE_PRESENTATION: dict[str, tuple[str, int]] = {
    "APOIADOR": ("💎 Apoiador da CHOQUE", 0xD4AF37),
    "COLABORADOR": ("🌟 Colaborador da CHOQUE", 0x3498DB),
    "BENFEITOR": ("🏅 Benfeitor da CHOQUE", 0xE67E22),
    "PATRONO": ("👑 Patrono da CHOQUE", 0x9B59B6),
}


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_financial_member(
    interaction: discord.Interaction, permission: str
) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use a Central de Auxílio Financeiro dentro do servidor.")
    member = interaction.user
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(member.guild.id, "FINANCIAL")
    if not await bot.services.permissions.has(member, permission):
        raise PermissionDenied("Você não possui permissão para esta ação financeira.")
    return member


async def require_private_financial_admin_channel(
    bot: ChoqueBot,
    guild: discord.Guild,
    channel: discord.TextChannel,
) -> None:
    """Fail closed unless the admin panel stays in the canonical private area."""

    registry = await bot.services.settings.get(guild.id, "discord_layout_registry_v2", {})
    categories = registry.get("categories", {}) if isinstance(registry, dict) else {}
    admin_category_id = categories.get("admin") if isinstance(categories, dict) else None
    if not admin_category_id or channel.category_id != int(admin_category_id):
        raise ValidationError(
            "O painel administrativo financeiro deve ficar na categoria Administração."
        )
    everyone = channel.overwrites_for(guild.default_role)
    if everyone.view_channel is not False:
        raise ValidationError(
            "O canal administrativo precisa negar explicitamente a visualização para @everyone."
        )


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


def _status_label(status: str) -> str:
    return {
        "EM_PLANEJAMENTO": "⚪ Em planejamento",
        "EM_ANDAMENTO": "🟠 Em andamento",
        "CONCLUIDA": "✅ Concluída",
        "CANCELADA": "⛔ Cancelada",
        "SUSPENSA": "⚠️ Suspensa",
        "PENDENTE": "🟠 Aguardando confirmação",
        "CONFIRMADA": "✅ Confirmada",
        "NAO_CONFIRMADA": "❌ Não confirmada",
        "EM_ANALISE": "🔎 Em análise",
        "ACEITA": "✅ Aceita",
        "RECUSADA": "❌ Recusada",
        "ARQUIVADA": "📁 Arquivada",
    }.get(status, status)


def project_embed(bot: ChoqueBot, project: dict[str, object]) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title=f"🎯 {project['name']}",
        description=str(project["description"]),
    )
    embed.add_field(name="Código", value=f"`{project['public_code']}`", inline=True)
    embed.add_field(name="Categoria", value=f"`{project['category']}`", inline=True)
    embed.add_field(name="Status", value=_status_label(str(project["status"])), inline=True)
    embed.add_field(
        name="Meta",
        value=FinancialAidService.format_cents(int(project["target_cents"])),
        inline=True,
    )
    embed.add_field(
        name="Arrecadado",
        value=FinancialAidService.format_cents(int(project["collected_cents"])),
        inline=True,
    )
    embed.add_field(
        name="Restante",
        value=FinancialAidService.format_cents(int(project["remaining_cents"])),
        inline=True,
    )
    embed.add_field(name="Progresso", value=f"`{int(project['percent'])}%`", inline=True)
    if project.get("deadline_at"):
        embed.add_field(
            name="Prazo", value=discord_timestamp(int(project["deadline_at"])), inline=True
        )
    supporters = cast(list[dict[str, object]], project.get("supporters") or [])
    if supporters:
        embed.add_field(
            name=f"Apoiadores ({len(supporters)})",
            value="\n".join(f"◈ {str(item['label'])[:120]}" for item in supporters[:12]),
            inline=False,
        )
    embed.add_field(
        name="Princípio institucional",
        value="Todo apoio é voluntário. Nenhuma contribuição gera cargo, promoção, prioridade ou poder.",
        inline=False,
    )
    return embed


async def financial_panel_embed(bot: ChoqueBot, guild_id: int) -> discord.Embed:
    snapshot = await bot.services.financial_aid.transparency_snapshot(guild_id)
    active = await bot.services.financial_aid.active_projects(guild_id)
    fund = cast(dict[str, object], snapshot["general_fund"])
    embed = branded_embed(
        bot.config.branding,
        title="⚡ Auxílio Financeiro • CHOQUE - BGR",
        description=(
            "A CHOQUE é construída com a participação voluntária da comunidade.\n\n"
            "Este espaço registra apoio a projetos e melhorias com transparência, privacidade e "
            "confirmação humana. Não existe valor mínimo, máximo, obrigação ou mensalidade."
        ),
    )
    embed.add_field(name="Metas ativas", value=str(len(active)), inline=True)
    embed.add_field(
        name="Fundo geral", value=FinancialAidService.format_cents(int(fund["balance_cents"])), inline=True
    )
    embed.add_field(name="Movimentações", value=str(fund["movement_count"]), inline=True)
    embed.add_field(
        name="⚠️ Igualdade institucional",
        value=(
            "Contribuições são voluntárias. Honrarias são exclusivamente simbólicas e não concedem "
            "autoridade, promoção, prioridade ou vantagem operacional/administrativa."
        ),
        inline=False,
    )
    embed.add_field(
        name="Encerramento",
        value=(
            "**A CHOQUE é construída por quem participa dela.** Contribuir é opcional; "
            "o reconhecimento existe apenas para agradecer."
        ),
        inline=False,
    )
    embed.set_footer(text=f"{bot.config.branding.footer} • {PUBLIC_PANEL_MARKER}")
    return embed


async def admin_panel_embed(bot: ChoqueBot, guild_id: int) -> discord.Embed:
    pending = await bot.services.financial_aid.contribution_page(
        guild_id, statuses=("PENDENTE",), limit=100
    )
    projects = await bot.services.financial_aid.active_projects(guild_id, limit=100)
    suggestions = await bot.services.database.fetchone(
        "SELECT COUNT(*) AS total FROM financial_suggestions WHERE guild_id=? AND status='PENDENTE'",
        (guild_id,),
    )
    pix = await bot.services.financial_aid.pix_configuration_status(guild_id)
    embed = branded_embed(
        bot.config.branding,
        title="🛡️ Administração Financeira • CHOQUE - BGR",
        description=(
            "Confirmações são humanas e toda alteração fica registrada. Valores individuais e a chave PIX "
            "não são expostos neste painel público."
        ),
    )
    embed.add_field(name="Aguardando confirmação", value=str(len(pending)), inline=True)
    embed.add_field(name="Metas em andamento", value=str(len(projects)), inline=True)
    embed.add_field(name="Sugestões pendentes", value=str(suggestions["total"] if suggestions else 0), inline=True)
    source = "ambiente seguro" if pix["source"] == "ENVIRONMENT" else "configuração administrativa"
    pix_value = str(pix["masked_key"]) if pix["configured"] else "Não configurada"
    pix_lines = [pix_value, f"Fonte: {source if pix['configured'] else '—'}"]
    if pix["configured"] and pix["updated_by"]:
        pix_lines.append(f"Atualizado por <@{pix['updated_by']}>")
    if pix["recipient_name"] and pix["recipient_city"]:
        pix_lines.append(f"Recebedor: {pix['recipient_name']} / {pix['recipient_city']}")
    embed.add_field(name="PIX", value="\n".join(pix_lines), inline=True)
    embed.set_footer(text=f"{bot.config.branding.footer} • {ADMIN_PANEL_MARKER}")
    return embed


def financial_notification_embed(
    bot: ChoqueBot,
    notification_type: str,
    payload: dict[str, object],
    *,
    notification_id: int | None = None,
) -> discord.Embed:
    """Render durable notices without individual amounts, PIX, or private data."""
    if notification_type == "CONTRIBUTION_DECIDED":
        status = _status_label(str(payload.get("status") or "PENDENTE"))
        title = "💰 Atualização do seu apoio voluntário"
        description = f"Situação: **{status}**\n{str(payload.get('reason') or 'Sem observação adicional.')[:1000]}"
    elif notification_type == "PROJECT_COMPLETED":
        title = "✅ Meta comunitária concluída"
        description = (
            f"**{payload.get('public_code') or 'META'} • {payload.get('name') or 'Projeto'}**\n"
            "Projeto desenvolvido com apoio voluntário da comunidade CHOQUE."
        )
    elif notification_type == "HONOR_GRANTED":
        title = "🏅 Honraria simbólica registrada"
        description = (
            f"Honraria: **{str(payload.get('honor_key') or 'RECONHECIMENTO').replace('_', ' ')}**\n"
            "Este reconhecimento é simbólico e não concede autoridade, prioridade ou vantagem."
        )
    elif notification_type == "HONOR_REMOVED":
        title = "↩️ Atualização de honraria"
        description = str(payload.get("reason") or "A honraria foi encerrada com histórico preservado.")[:1000]
    elif notification_type == "CERTIFICATE_ISSUED":
        title = "🧾 Certificado de reconhecimento"
        description = (
            f"Certificamos a participação voluntária de **{payload.get('member_name') or 'membro CHOQUE'}** "
            "no desenvolvimento da corporação, sem incluir valor financeiro.\n"
            f"Código de validação: `{payload.get('validation_code') or '—'}`"
        )
    elif notification_type == "SUGGESTION_REVIEWED":
        title = "💡 Atualização da sua sugestão"
        description = (
            f"**{str(payload.get('title') or 'Sugestão')[:180]}**\n"
            f"Situação: **{_status_label(str(payload.get('status') or 'PENDENTE'))}**"
        )
    else:
        title = "💰 Atualização da Central Financeira"
        description = "Uma atualização institucional foi registrada."
    embed = branded_embed(bot.config.branding, title=title, description=description)
    if notification_type == "CERTIFICATE_ISSUED":
        embed.add_field(name="Honraria", value=str(payload.get("honor_title") or "Reconhecimento institucional")[:1024])
        project = str(payload.get("project_name") or "Reconhecimento institucional")
        code = str(payload.get("project_code") or "—")
        embed.add_field(name="Projeto", value=f"{project[:900]}\n`{code[:100]}`", inline=False)
        achievements = payload.get("achievement_titles") or []
        embed.add_field(
            name="Conquistas registradas",
            value="\n".join(f"✓ {str(item)[:120]}" for item in list(achievements)[:8]) or "Nenhuma conquista adicional.",
            inline=False,
        )
        if payload.get("issued_at"):
            embed.add_field(name="Emissão", value=discord_timestamp(int(payload["issued_at"]), "F"))
    if notification_id is not None:
        embed.set_footer(
            text=f"{bot.config.branding.footer} • Notificação financeira #{notification_id}"
        )
    return embed


def financial_highlights_panel_embed(bot: ChoqueBot) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="🏅 DESTAQUES FINANCEIROS • CHOQUE - BGR",
        description=(
            "Este mural reconhece apoios voluntários confirmados pela Administração. "
            "Honrarias são estritamente simbólicas e nunca concedem autoridade, promoção, "
            "prioridade ou vantagem."
        ),
        color=0xD4AF37,
    )
    embed.add_field(
        name="🔐 Privacidade",
        value=(
            "A identidade só aparece quando o apoiador escolheu o modo público. "
            "O valor individual só aparece quando houver consentimento específico; "
            "contribuições anônimas permanecem anônimas."
        ),
        inline=False,
    )
    embed.add_field(
        name="📜 Integridade",
        value=(
            "Cada confirmação possui uma única publicação vinculada ao registro canônico. "
            "Estornos e correções atualizam a mesma mensagem, sem apagar o histórico."
        ),
        inline=False,
    )
    embed.set_footer(text=f"{bot.config.branding.footer} • {HIGHLIGHTS_PANEL_MARKER}")
    return embed


def financial_contribution_highlight_embed(
    bot: ChoqueBot,
    snapshot: dict[str, object],
    *,
    member: discord.Member | None,
    notification_id: int,
) -> discord.Embed:
    """Render one privacy-aware, durable contribution highlight."""

    reversed_at = snapshot.get("reversed_at")
    is_reversed = reversed_at is not None
    is_public = str(snapshot.get("visibility") or "ANONIMO") == "PUBLICO"
    public_amount = bool(snapshot.get("public_amount"))
    title = "↩️ APOIO VOLUNTÁRIO ESTORNADO" if is_reversed else "🏅 APOIO VOLUNTÁRIO CONFIRMADO"
    description = (
        "Esta publicação foi atualizada para refletir o estorno administrativo, com o histórico preservado."
        if is_reversed
        else "A CHOQUE agradece a quem contribui voluntariamente para fortalecer nossos projetos e estrutura."
    )
    embed = branded_embed(
        bot.config.branding,
        title=title,
        description=description,
        color=0x6B7280 if is_reversed else 0xD4AF37,
    )
    if is_public:
        discord_id = int(snapshot["discord_id"])
        embed.add_field(name="Militar", value=f"<@{discord_id}>", inline=True)
        embed.add_field(
            name="Identificação",
            value=str(snapshot.get("member_name") or "Membro CHOQUE")[:1024],
            inline=True,
        )
        if member is not None:
            embed.set_thumbnail(url=member.display_avatar.url)
    else:
        embed.add_field(name="Apoiador", value="◈ Contribuição anônima", inline=False)

    amount_text = (
        FinancialAidService.format_cents(int(snapshot["amount_cents"]))
        if public_amount
        else "Preservado por privacidade"
    )
    embed.add_field(name="Valor", value=amount_text, inline=True)
    project_name = str(snapshot.get("project_name") or "Fundo Geral da CHOQUE")
    project_code = str(snapshot.get("project_public_code") or "GERAL")
    embed.add_field(name="Destino", value=f"**{project_name[:800]}**\n`{project_code[:80]}`", inline=False)

    target = snapshot.get("project_target_cents")
    collected = snapshot.get("project_collected_cents")
    if target is not None and collected is not None and int(target) > 0:
        percentage = min(100, max(0, round(int(collected) * 100 / int(target))))
        blocks = min(10, percentage // 10)
        progress = "█" * blocks + "░" * (10 - blocks)
        embed.add_field(
            name="Progresso da meta",
            value=(
                f"`{progress}` **{percentage}%**\n"
                f"{FinancialAidService.format_cents(int(collected))} de "
                f"{FinancialAidService.format_cents(int(target))}"
            ),
            inline=False,
        )

    honors = [str(value) for value in snapshot.get("honor_titles") or []]
    achievements = [str(value) for value in snapshot.get("achievement_titles") or []]
    recognition = honors[:1] + achievements[:3]
    embed.add_field(
        name="Reconhecimento simbólico",
        value="\n".join(f"◈ {item[:180]}" for item in recognition) or "Registro institucional de apoio",
        inline=False,
    )
    event_at = int(reversed_at or snapshot.get("confirmed_at") or 0)
    if event_at:
        embed.add_field(
            name="Atualização" if is_reversed else "Confirmação",
            value=discord_timestamp(event_at, "F"),
            inline=True,
        )
    if is_reversed:
        embed.add_field(
            name="Situação",
            value="Estornada administrativamente; nenhuma informação foi apagada.",
            inline=False,
        )
    embed.set_footer(
        text=(
            f"{bot.config.branding.footer} • Destaque financeiro da contribuição "
            f"#{int(snapshot['id'])} • Notificação financeira #{notification_id}"
        )
    )
    return embed


def _message_has_marker(message: discord.Message, *, bot_user_id: int, marker: str) -> bool:
    return (
        message.author.id == bot_user_id
        and any(embed.footer and embed.footer.text and marker in embed.footer.text for embed in message.embeds)
    )


def certificate_embed(bot: ChoqueBot, certificate: dict[str, object]) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="🧾 Certificado de reconhecimento • CHOQUE - BGR",
        description=(
            "A Corporação CHOQUE certifica a participação voluntária no desenvolvimento de "
            "projetos e melhorias comunitárias. Este documento não representa valor financeiro "
            "nem concede autoridade, promoção, prioridade ou vantagem."
        ),
    )
    embed.add_field(name="Membro", value=str(certificate["member_name"])[:1024], inline=True)
    embed.add_field(name="Discord ID", value=f"`{certificate['discord_id']}`", inline=True)
    embed.add_field(name="Honraria", value=str(certificate["honor_title"])[:1024], inline=False)
    project = str(certificate.get("project_name") or "Reconhecimento institucional")
    code = str(certificate.get("project_code") or "—")
    embed.add_field(name="Projeto relacionado", value=f"{project[:900]}\n`{code[:100]}`", inline=False)
    achievements = certificate.get("achievement_titles") or []
    embed.add_field(
        name="Conquistas registradas",
        value="\n".join(f"✓ {str(item)[:120]}" for item in list(achievements)[:8]) or "Nenhuma conquista adicional.",
        inline=False,
    )
    embed.add_field(name="Data de emissão", value=discord_timestamp(int(certificate["issued_at"]), "F"), inline=True)
    embed.add_field(name="Código de validação", value=f"`{certificate['validation_code']}`", inline=True)
    return embed


class ContributionModal(ErrorModal):
    amount = discord.ui.TextInput(
        label="Valor (R$)", min_length=1, max_length=32, placeholder="Ex.: 25,00"
    )
    visibility = discord.ui.TextInput(
        label="Visibilidade", min_length=1, max_length=12, default="ANONIMO", placeholder="PUBLICO ou ANONIMO"
    )
    public_amount = discord.ui.TextInput(
        label="Exibir o valor no destaque?",
        min_length=3,
        max_length=3,
        default="NAO",
        placeholder="SIM ou NAO",
    )
    observation = discord.ui.TextInput(
        label="Observação (opcional)", style=discord.TextStyle.paragraph, required=False, max_length=800
    )

    def __init__(self, destination_kind: str, project_id: int | None) -> None:
        super().__init__(title="Registrar contribuição voluntária")
        self.destination_kind = destination_kind
        self.project_id = project_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_financial_member(interaction, "financial.contribute")
        finance = get_bot(interaction).services.financial_aid
        public_amount_answer = str(self.public_amount).strip().upper()
        if public_amount_answer not in {"SIM", "NAO", "NÃO"}:
            raise ValidationError("Informe `SIM` ou `NAO` para a exibição pública do valor.")
        contribution = await finance.declare_contribution(
            member.guild.id,
            member.id,
            amount=str(self.amount),
            destination_kind=self.destination_kind,
            project_id=self.project_id,
            visibility=str(self.visibility),
            public_amount=public_amount_answer == "SIM",
            observation=str(self.observation),
            idempotency_key=f"discord:financial:declare:{interaction.id}",
        )
        await interaction.response.send_message(
            "✅ Seu registro foi enviado e aguarda confirmação administrativa. "
            "Informar que realizou o PIX não confirma automaticamente o recebimento.",
            embed=contribution_embed(get_bot(interaction), contribution, show_amount=True),
            ephemeral=True,
        )


def contribution_embed(
    bot: ChoqueBot, contribution: dict[str, object], *, show_amount: bool
) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="💰 Registro de contribuição voluntária",
        description=_status_label(str(contribution["status"])),
    )
    embed.add_field(name="Registro", value=f"`#{contribution['id']}`", inline=True)
    embed.add_field(name="Destino", value=str(contribution["destination_kind"]), inline=True)
    embed.add_field(name="Visibilidade", value=str(contribution["visibility"]), inline=True)
    if show_amount:
        embed.add_field(
            name="Valor declarado",
            value=FinancialAidService.format_cents(int(contribution["amount_cents"])),
            inline=True,
        )
    if contribution.get("final_reason"):
        embed.add_field(name="Justificativa", value=str(contribution["final_reason"])[:1024], inline=False)
    return embed


class PixDisclosureView(ErrorView):
    def __init__(self, *, payload_available: bool = True) -> None:
        super().__init__(timeout=None)
        self.copy_payload.disabled = not payload_available

    @discord.ui.button(
        label="Copiar chave PIX",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:financial:pix:copy-key:v1",
    )
    async def copy_key(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_financial_member(interaction, "financial.contribute")
        key = await get_bot(interaction).services.financial_aid.pix_key(member.guild.id)
        await interaction.response.send_message(
            f"Copie a chave PIX exibida abaixo:\n```{key}```", ephemeral=True
        )

    @discord.ui.button(
        label="Copiar Pix Copia e Cola",
        emoji="🔳",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:financial:pix:copy-payload:v1",
    )
    async def copy_payload(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_financial_member(interaction, "financial.contribute")
        payment = await get_bot(interaction).services.financial_aid.pix_payment_payload(member.guild.id)
        await interaction.response.send_message(
            "Pix Copia e Cola (sem valor fixo):\n```" + payment["payload"] + "```",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Já realizei o PIX",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="choque:financial:pix:declared:v1",
    )
    async def declared(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_financial_member(interaction, "financial.contribute")
        projects = await get_bot(interaction).services.financial_aid.active_projects(member.guild.id)
        await interaction.response.edit_message(
            content="Escolha o destino da contribuição. Metas encerradas não aparecem na lista.",
            embed=None,
            attachments=[],
            view=ContributionDestinationView(projects),
        )

    @discord.ui.button(
        label="Cancelar",
        emoji="❌",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:financial:pix:cancel:v1",
    )
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        # Cancelar não executa uma ação financeira. Reconheça o componente antes
        # de qualquer consulta e remova diretamente a resposta efêmera; esse é o
        # caminho suportado pelo Discord para fechar uma mensagem efêmera com
        # anexo, sem deixar o clique expirar nem tentar reeditar o QR Code.
        await interaction.response.defer()
        try:
            await interaction.delete_original_response()
        except discord.NotFound:
            # Repetições entregues pelo Gateway depois que a resposta já sumiu
            # continuam idempotentes e não criam qualquer registro financeiro.
            return


class ContributionDestinationSelect(discord.ui.Select):
    def __init__(self, projects: list[dict[str, object]]) -> None:
        options = [
            discord.SelectOption(
                label="Fundo Geral da CHOQUE",
                value="GENERAL",
                description="Apoio sem finalidade específica.",
                emoji="💰",
            )
        ]
        for project in projects[:24]:
            options.append(
                discord.SelectOption(
                    label=str(project["name"])[:100],
                    value=f"PROJECT:{project['id']}",
                    description=(
                        f"{project['public_code']} • {FinancialAidService.format_cents(int(project['remaining_cents']))} restantes"
                    )[:100],
                    emoji="🎯",
                )
            )
        super().__init__(placeholder="Destino da contribuição", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_financial_member(interaction, "financial.contribute")
        selected = self.values[0]
        if selected == "GENERAL":
            await interaction.response.send_modal(ContributionModal("FUNDO_GERAL", None))
            return
        await interaction.response.send_modal(ContributionModal("PROJETO", int(selected.split(":", 1)[1])))


class ContributionDestinationView(ErrorView):
    def __init__(self, projects: list[dict[str, object]]) -> None:
        super().__init__(timeout=600)
        self.add_item(ContributionDestinationSelect(projects))


class ProjectSponsorView(ErrorView):
    def __init__(self, project_id: int, *, active: bool) -> None:
        super().__init__(timeout=600)
        self.project_id = project_id
        self.sponsor_public.disabled = not active
        self.sponsor_anonymous.disabled = not active

    async def _sponsor(self, interaction: discord.Interaction, visibility: str) -> None:
        member = await require_financial_member(interaction, "financial.sponsor")
        result = await get_bot(interaction).services.financial_aid.sponsor_project(
            member.guild.id, member.id, project_id=self.project_id, visibility=visibility
        )
        await interaction.response.send_message(
            "✅ Interesse registrado. Apadrinhar um projeto não cria obrigação de completar a meta.",
            ephemeral=True,
        )
        del result

    @discord.ui.button(label="Apadrinhar publicamente", emoji="🏷️", style=discord.ButtonStyle.primary)
    async def sponsor_public(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._sponsor(interaction, "PUBLICO")

    @discord.ui.button(label="Apadrinhar anonimamente", emoji="🕶️", style=discord.ButtonStyle.secondary)
    async def sponsor_anonymous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._sponsor(interaction, "ANONIMO")


class ProjectSelect(discord.ui.Select):
    def __init__(self, projects: list[dict[str, object]], *, admin: bool = False) -> None:
        self.admin = admin
        super().__init__(
            placeholder="Escolha uma meta",
            options=[
                discord.SelectOption(
                    label=f"{row['public_code']} • {row['name']}"[:100],
                    value=str(row["id"]),
                    description=f"{row['status']} • {int(row['percent'])}%"[:100],
                )
                for row in projects[:25]
            ],
            disabled=not projects,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        permission = "financial.project.manage" if self.admin else "financial.view.public"
        await require_financial_member(interaction, permission)
        bot = get_bot(interaction)
        project = await bot.services.financial_aid.project_snapshot(
            interaction.guild.id, int(self.values[0])
        )
        view: discord.ui.View
        if self.admin:
            view = FinancialProjectAdminView(
                int(project["id"]), int(project["version"]), str(project["status"])
            )
        else:
            view = ProjectSponsorView(int(project["id"]), active=str(project["status"]) == "EM_ANDAMENTO")
        await interaction.response.edit_message(embed=project_embed(bot, project), view=view)


class ProjectSelectView(ErrorView):
    def __init__(self, projects: list[dict[str, object]], *, admin: bool = False) -> None:
        super().__init__(timeout=600)
        if projects:
            self.add_item(ProjectSelect(projects, admin=admin))


class SuggestionModal(ErrorModal):
    title_input = discord.ui.TextInput(label="Título", min_length=3, max_length=180)
    description_input = discord.ui.TextInput(label="Descrição", style=discord.TextStyle.paragraph, min_length=10, max_length=1500)
    estimated = discord.ui.TextInput(label="Valor estimado (opcional)", required=False, max_length=32)
    motivation = discord.ui.TextInput(
        label="Motivo", style=discord.TextStyle.paragraph, min_length=3, max_length=1000
    )
    reference_url = discord.ui.TextInput(
        label="Link de referência (opcional)", required=False, max_length=400,
        placeholder="https://...",
    )

    def __init__(self, category: str) -> None:
        super().__init__(title="Sugerir melhoria")
        self.category_value = category

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_financial_member(interaction, "financial.suggest")
        await get_bot(interaction).services.financial_aid.create_suggestion(
            member.guild.id,
            member.id,
            title=str(self.title_input),
            category=self.category_value,
            description=str(self.description_input),
            motivation=str(self.motivation),
            estimated_amount=str(self.estimated) or None,
            reference_url=str(self.reference_url) or None,
        )
        await interaction.response.send_message(
            "✅ Sugestão enviada para análise administrativa.", ephemeral=True
        )


class SuggestionCategorySelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Escolha a categoria da sugestão",
            options=[
                discord.SelectOption(label="Viatura", value="VIATURA", emoji="🚓"),
                discord.SelectOption(label="Skin", value="SKIN", emoji="🎨"),
                discord.SelectOption(label="Plotagem", value="PLOTAGEM", emoji="🖌️"),
                discord.SelectOption(label="Uniforme", value="UNIFORME", emoji="🧥"),
                discord.SelectOption(label="Mod", value="MOD", emoji="🧩"),
                discord.SelectOption(label="Sistema", value="SISTEMA", emoji="⚙️"),
                discord.SelectOption(label="Estrutura", value="ESTRUTURA", emoji="🏢"),
                discord.SelectOption(label="Outro", value="OUTRO", emoji="💡"),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_financial_member(interaction, "financial.suggest")
        await interaction.response.send_modal(SuggestionModal(self.values[0]))


class SuggestionCategoryView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=600)
        self.add_item(SuggestionCategorySelect())


class FinancialAidPanelView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Doar", emoji="💰", style=discord.ButtonStyle.success, custom_id="choque:financial:donate:v1")
    async def donate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_financial_member(interaction, "financial.contribute")
        bot = get_bot(interaction)
        key = await bot.services.financial_aid.pix_key(member.guild.id)
        payment: dict[str, str] | None = None
        try:
            payment = await bot.services.financial_aid.pix_payment_payload(member.guild.id)
        except ValidationError:
            # A key alone remains usable while the leadership finishes the public
            # recipient data required by BR Code.  The interaction stays fail-closed
            # for the QR payload instead of inventing name/city fields.
            payment = None
        embed = branded_embed(
            bot.config.branding,
            title="💰 Contribuição voluntária",
            description=(
                "Use a chave PIX abaixo apenas se desejar contribuir. Depois, registre a declaração para "
                "que a administração possa conferir. O clique nunca confirma pagamento automaticamente."
            ),
        )
        embed.add_field(name="Chave PIX", value=f"```{key}```", inline=False)
        if payment is not None:
            embed.add_field(
                name="QR Code e Pix Copia e Cola",
                value="Escaneie o QR abaixo ou use o botão para copiar o BR Code sem valor fixo.",
                inline=False,
            )
            embed.set_image(url="attachment://pix-qr.png")
        else:
            embed.add_field(
                name="QR Code",
                value="A Administração ainda precisa configurar nome e cidade do recebedor para liberar o BR Code.",
                inline=False,
            )
        embed.add_field(
            name="Importante",
            value="Nenhuma contribuição gera promoção, cargo, prioridade ou vantagem.",
            inline=False,
        )
        view = PixDisclosureView(payload_available=payment is not None)
        if payment is None:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return
        file = discord.File(BytesIO(bot.services.financial_aid.pix_qr_png(payment["payload"])), filename="pix-qr.png")
        await interaction.response.send_message(embed=embed, view=view, file=file, ephemeral=True)

    @discord.ui.button(label="Metas", emoji="🎯", style=discord.ButtonStyle.primary, custom_id="choque:financial:goals:v1")
    async def goals(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_financial_member(interaction, "financial.view.public")
        bot = get_bot(interaction)
        projects = await bot.services.financial_aid.active_projects(member.guild.id)
        if not projects:
            await interaction.response.send_message("Não há metas em andamento neste momento.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Escolha uma meta para ver os detalhes e, se desejar, demonstrar apoio.",
            view=ProjectSelectView(projects),
            ephemeral=True,
        )

    @discord.ui.button(label="Prestação de contas", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="choque:financial:transparency:v1")
    async def transparency(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_financial_member(interaction, "financial.view.public")
        bot = get_bot(interaction)
        snapshot = await bot.services.financial_aid.transparency_snapshot(member.guild.id)
        fund = cast(dict[str, object], snapshot["general_fund"])
        embed = branded_embed(bot.config.branding, title="📊 Prestação de contas • CHOQUE - BGR")
        embed.add_field(name="Arrecadado", value=FinancialAidService.format_cents(int(fund["collected_cents"])), inline=True)
        embed.add_field(name="Utilizado", value=FinancialAidService.format_cents(int(fund["used_cents"])), inline=True)
        embed.add_field(name="Saldo", value=FinancialAidService.format_cents(int(fund["balance_cents"])), inline=True)
        completed = cast(list[dict[str, object]], snapshot["completed_projects"])
        embed.add_field(
            name="Projetos concluídos",
            value="\n".join(f"✅ {item['name']}" for item in completed[:10]) or "Nenhum projeto concluído ainda.",
            inline=False,
        )
        embed.add_field(
            name="Privacidade",
            value="Valores individuais e dados privados não são publicados neste quadro.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Sugerir melhoria", emoji="💡", style=discord.ButtonStyle.secondary, custom_id="choque:financial:suggest:v1")
    async def suggest(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.suggest")
        await interaction.response.send_message(
            "Escolha a categoria; em seguida você poderá detalhar a melhoria e, se quiser, incluir uma referência.",
            view=SuggestionCategoryView(),
            ephemeral=True,
        )

    @discord.ui.button(label="Apoiadores", emoji="🤝", style=discord.ButtonStyle.secondary, custom_id="choque:financial:supporters:v1")
    async def supporters(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_financial_member(interaction, "financial.view.public")
        bot = get_bot(interaction)
        limit = await bot.services.settings.get(member.guild.id, "financial_public_supporters_limit")
        supporters = await bot.services.financial_aid.public_supporters(member.guild.id, limit=int(limit))
        profile = await bot.services.financial_aid.member_honor_snapshot(member.guild.id, member.id)
        embed = branded_embed(
            bot.config.branding,
            title="🤝 Apoiadores da CHOQUE",
            description="Reconhecimento institucional, sem valores e sem ranking financeiro.",
        )
        embed.add_field(
            name="Mural",
            value="\n".join(f"◈ <@{row['discord_id']}> — {row['label']}" for row in supporters) or "Ainda não há apoiadores públicos.",
            inline=False,
        )
        honors = cast(list[dict[str, object]], profile["honors"])
        achievements = cast(list[dict[str, object]], profile["achievements"])
        embed.add_field(
            name="Suas honrarias",
            value="\n".join(f"◈ {item['title']}" for item in honors[:5]) or "Nenhuma honraria ativa.",
            inline=False,
        )
        embed.add_field(
            name="Suas conquistas",
            value="\n".join(f"✓ {item['title']}" for item in achievements[:8]) or "Nenhuma conquista ainda.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class ProjectCreateModal(ErrorModal):
    name_input = discord.ui.TextInput(label="Nome da meta", min_length=3, max_length=160)
    category = discord.ui.TextInput(label="Categoria", min_length=3, max_length=80)
    target = discord.ui.TextInput(label="Meta (R$)", min_length=1, max_length=32, placeholder="Ex.: 800,00")
    description_input = discord.ui.TextInput(label="Descrição", style=discord.TextStyle.paragraph, min_length=8, max_length=1600)
    notes = discord.ui.TextInput(label="Observações (opcional)", style=discord.TextStyle.paragraph, required=False, max_length=600)

    def __init__(self) -> None:
        super().__init__(title="Criar meta financeira")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.project.manage")
        project = await get_bot(interaction).services.financial_aid.create_project(
            admin.guild.id,
            actor_id=admin.id,
            name=str(self.name_input),
            description=str(self.description_input),
            category=str(self.category),
            target_amount=str(self.target),
            notes=str(self.notes),
        )
        await interaction.response.send_message(
            "✅ Meta criada.", embed=project_embed(get_bot(interaction), project), ephemeral=True
        )
        await refresh_financial_panels(admin.guild)


class ProjectEditModal(ErrorModal):
    name_input = discord.ui.TextInput(label="Nome", min_length=3, max_length=160)
    category = discord.ui.TextInput(label="Categoria", min_length=3, max_length=80)
    description_input = discord.ui.TextInput(label="Descrição", style=discord.TextStyle.paragraph, min_length=8, max_length=1600)
    notes = discord.ui.TextInput(label="Observações", style=discord.TextStyle.paragraph, required=False, max_length=600)
    reason = discord.ui.TextInput(label="Motivo da alteração", min_length=3, max_length=500)

    def __init__(self, project: dict[str, object]) -> None:
        super().__init__(title="Editar meta financeira")
        self.project_id = int(project["id"])
        self.version = int(project["version"])
        self.name_input.default = str(project["name"])
        self.category.default = str(project["category"])
        self.description_input.default = str(project["description"])
        self.notes.default = str(project.get("notes") or "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.project.manage")
        project = await get_bot(interaction).services.financial_aid.update_project(
            admin.guild.id,
            self.project_id,
            actor_id=admin.id,
            expected_version=self.version,
            name=str(self.name_input),
            category=str(self.category),
            description=str(self.description_input),
            notes=str(self.notes),
            reason=str(self.reason),
        )
        await interaction.response.send_message("✅ Meta atualizada.", embed=project_embed(get_bot(interaction), project), ephemeral=True)
        await refresh_financial_panels(admin.guild)


class ProjectDecisionModal(ErrorModal):
    reason = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, min_length=3, max_length=500)

    def __init__(self, project_id: int, version: int, *, status: str) -> None:
        titles = {
            "CONCLUIDA": "Concluir meta",
            "CANCELADA": "Cancelar meta",
            "SUSPENSA": "Suspender meta",
        }
        super().__init__(title=titles.get(status, "Atualizar meta"))
        self.project_id = project_id
        self.version = version
        self.status = status

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.project.manage")
        project = await get_bot(interaction).services.financial_aid.update_project(
            admin.guild.id,
            self.project_id,
            actor_id=admin.id,
            expected_version=self.version,
            status=self.status,
            reason=str(self.reason),
        )
        await interaction.response.send_message(embed=project_embed(get_bot(interaction), project), ephemeral=True)
        await refresh_financial_panels(admin.guild)


class FinancialProjectAdminView(ErrorView):
    def __init__(self, project_id: int, version: int, status: str) -> None:
        super().__init__(timeout=600)
        self.project_id = project_id
        self.version = version
        self.status = status
        self.start.disabled = status not in {"EM_PLANEJAMENTO", "SUSPENSA"}
        self.suspend.disabled = status != "EM_ANDAMENTO"
        self.complete.disabled = status not in {"EM_ANDAMENTO", "SUSPENSA"}
        self.cancel.disabled = status in {"CONCLUIDA", "CANCELADA"}

    @discord.ui.button(label="Ativar / retomar", emoji="▶️", style=discord.ButtonStyle.success)
    async def start(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        admin = await require_financial_member(interaction, "financial.project.manage")
        project = await get_bot(interaction).services.financial_aid.update_project(
            admin.guild.id, self.project_id, actor_id=admin.id, expected_version=self.version,
            status="EM_ANDAMENTO", reason="Meta liberada para apoio comunitário.",
        )
        await interaction.response.edit_message(
            embed=project_embed(get_bot(interaction), project),
            view=FinancialProjectAdminView(self.project_id, int(project["version"]), str(project["status"])),
        )
        await refresh_financial_panels(admin.guild)

    @discord.ui.button(label="Suspender", emoji="⏸️", style=discord.ButtonStyle.secondary)
    async def suspend(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.project.manage")
        await interaction.response.send_modal(ProjectDecisionModal(self.project_id, self.version, status="SUSPENSA"))

    @discord.ui.button(label="Editar", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        admin = await require_financial_member(interaction, "financial.project.manage")
        project = await get_bot(interaction).services.financial_aid.project_snapshot(admin.guild.id, self.project_id)
        await interaction.response.send_modal(ProjectEditModal(project))

    @discord.ui.button(label="Concluir", emoji="✅", style=discord.ButtonStyle.success)
    async def complete(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.project.manage")
        await interaction.response.send_modal(ProjectDecisionModal(self.project_id, self.version, status="CONCLUIDA"))

    @discord.ui.button(label="Cancelar", emoji="⛔", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.project.manage")
        await interaction.response.send_modal(ProjectDecisionModal(self.project_id, self.version, status="CANCELADA"))


class MetaManagementView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=600)

    @discord.ui.button(label="Criar meta", emoji="➕", style=discord.ButtonStyle.success)
    async def create(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.project.manage")
        await interaction.response.send_modal(ProjectCreateModal())

    @discord.ui.button(label="Gerenciar metas", emoji="🎯", style=discord.ButtonStyle.primary)
    async def manage(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        admin = await require_financial_member(interaction, "financial.project.manage")
        rows = await get_bot(interaction).services.financial_aid.project_page(admin.guild.id)
        await interaction.response.send_message(
            "Escolha uma meta para editar, ativar, suspender, concluir ou cancelar.",
            view=ProjectSelectView(rows, admin=True), ephemeral=True,
        )


class ContributionDecisionModal(ErrorModal):
    reason = discord.ui.TextInput(label="Justificativa", style=discord.TextStyle.paragraph, min_length=3, max_length=500)

    def __init__(self, contribution_id: int, version: int, *, decision: str) -> None:
        titles = {
            "CONFIRM": "Confirmar contribuição",
            "INVALIDATE": "Invalidar contribuição",
            "CANCEL": "Cancelar declaração",
        }
        super().__init__(title=titles[decision])
        self.contribution_id = contribution_id
        self.version = version
        self.decision = decision

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.contribution.review")
        finance = get_bot(interaction).services.financial_aid
        if self.decision == "CANCEL":
            result = await finance.cancel_contribution(
                admin.guild.id,
                self.contribution_id,
                actor_id=admin.id,
                expected_version=self.version,
                reason=str(self.reason),
            )
        else:
            result = await finance.decide_unconfirmed_contribution(
                admin.guild.id, self.contribution_id, actor_id=admin.id, expected_version=self.version,
                confirmed=self.decision == "CONFIRM", reason=str(self.reason),
            )
        await interaction.response.send_message(
            embed=contribution_embed(get_bot(interaction), result, show_amount=True), ephemeral=True
        )
        if str(result["status"]) == "CONFIRMADA":
            cog = get_bot(interaction).get_cog("FinancialAidCommands")
            if isinstance(cog, FinancialAidCommands):
                try:
                    await cog.reconcile_honor_roles(admin.guild, discord_id=int(result["discord_id"]))
                except discord.DiscordException:
                    # The durable database state is already committed.  The
                    # five-minute reconciliation will retry a transient role
                    # failure without rolling back the human confirmation.
                    LOGGER.exception("Falha transitória ao sincronizar honraria financeira")
        await refresh_financial_panels(admin.guild)


class ContributionSelect(discord.ui.Select):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = {int(row["id"]): row for row in rows}
        super().__init__(
            placeholder="Escolha uma contribuição",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['mta_nick']}"[:100],
                    value=str(row["id"]),
                    description=f"{row['status']} • {FinancialAidService.format_cents(int(row['amount_cents']))}"[:100],
                ) for row in rows[:25]
            ],
            disabled=not rows,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_financial_member(interaction, "financial.contribution.review")
        row = self.rows[int(self.values[0])]
        await interaction.response.edit_message(
            embed=contribution_embed(get_bot(interaction), row, show_amount=True),
            view=ContributionAdminView(int(row["id"]), int(row["version"]), str(row["status"])),
        )


class ContributionSelectView(ErrorView):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__(timeout=600)
        if rows:
            self.add_item(ContributionSelect(rows))


class ContributionAdminView(ErrorView):
    def __init__(self, contribution_id: int, version: int, status: str) -> None:
        super().__init__(timeout=600)
        self.contribution_id = contribution_id
        self.version = version
        self.status = status
        self.confirm.disabled = status != "PENDENTE"
        self.invalidate.disabled = status != "PENDENTE"
        self.cancel_declaration.disabled = status != "PENDENTE"
        self.reverse.disabled = status != "CONFIRMADA"

    @discord.ui.button(label="Confirmar", emoji="💳", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.contribution.review")
        await interaction.response.send_modal(ContributionDecisionModal(self.contribution_id, self.version, decision="CONFIRM"))

    @discord.ui.button(label="Invalidar", emoji="🚫", style=discord.ButtonStyle.danger)
    async def invalidate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.contribution.review")
        await interaction.response.send_modal(ContributionDecisionModal(self.contribution_id, self.version, decision="INVALIDATE"))

    @discord.ui.button(label="Cancelar declaração", emoji="⛔", style=discord.ButtonStyle.secondary)
    async def cancel_declaration(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.contribution.review")
        await interaction.response.send_modal(ContributionDecisionModal(self.contribution_id, self.version, decision="CANCEL"))

    @discord.ui.button(label="Estornar", emoji="↩️", style=discord.ButtonStyle.danger)
    async def reverse(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.contribution.reverse")
        await interaction.response.send_modal(ContributionReverseModal(self.contribution_id))


class ContributionReverseModal(ErrorModal):
    reason = discord.ui.TextInput(label="Motivo do estorno", style=discord.TextStyle.paragraph, min_length=3, max_length=500)

    def __init__(self, contribution_id: int) -> None:
        super().__init__(title="Estornar contribuição")
        self.contribution_id = contribution_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.contribution.reverse")
        result = await get_bot(interaction).services.financial_aid.reverse_contribution(
            admin.guild.id, self.contribution_id, actor_id=admin.id, reason=str(self.reason)
        )
        await interaction.response.send_message(
            f"✅ Estorno registrado no livro-caixa como lançamento `{result['id']}`. O lançamento original foi preservado.",
            ephemeral=True,
        )
        await refresh_financial_panels(admin.guild)


class ExpenseModal(ErrorModal):
    amount = discord.ui.TextInput(label="Valor (R$)", min_length=1, max_length=32)
    category = discord.ui.TextInput(label="Categoria", min_length=3, max_length=80)
    description_input = discord.ui.TextInput(label="Descrição", style=discord.TextStyle.paragraph, min_length=5, max_length=1200)
    project_id = discord.ui.TextInput(label="ID da meta (opcional)", required=False, max_length=20)

    def __init__(self) -> None:
        super().__init__(title="Registrar despesa")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.expense.record")
        raw_project_id = str(self.project_id).strip()
        project_id = int(raw_project_id) if raw_project_id else None
        expense = await get_bot(interaction).services.financial_aid.record_expense(
            admin.guild.id, actor_id=admin.id, amount=str(self.amount), category=str(self.category),
            description=str(self.description_input), project_id=project_id,
        )
        await interaction.response.send_message(
            f"✅ Despesa registrada como lançamento imutável `{expense['ledger_entry_id']}`.", ephemeral=True
        )
        await refresh_financial_panels(admin.guild)


class ExpenseReverseModal(ErrorModal):
    expense_id = discord.ui.TextInput(label="ID da despesa", min_length=1, max_length=20)
    reason = discord.ui.TextInput(label="Motivo do estorno", style=discord.TextStyle.paragraph, min_length=3, max_length=500)

    def __init__(self) -> None:
        super().__init__(title="Estornar despesa registrada")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.expense.reverse")
        reversal = await get_bot(interaction).services.financial_aid.reverse_expense(
            admin.guild.id,
            int(str(self.expense_id)),
            actor_id=admin.id,
            reason=str(self.reason),
        )
        await interaction.response.send_message(
            f"✅ Estorno registrado como lançamento imutável `#{reversal['id']}`.", ephemeral=True
        )
        await refresh_financial_panels(admin.guild)


class HonorGrantModal(ErrorModal):
    discord_id = discord.ui.TextInput(label="Discord ID do membro", min_length=5, max_length=32)
    honor_key = discord.ui.TextInput(label="Honraria", min_length=3, max_length=40, placeholder="APOIADOR, COLABORADOR, BENFEITOR ou PATRONO")
    reason = discord.ui.TextInput(label="Justificativa", style=discord.TextStyle.paragraph, min_length=8, max_length=1000)
    expires_at = discord.ui.TextInput(label="Expira em (timestamp ms, opcional)", required=False, max_length=20)

    def __init__(self) -> None:
        super().__init__(title="Conceder honraria simbólica")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.honor.grant")
        expires_raw = str(self.expires_at).strip()
        honor = await get_bot(interaction).services.financial_aid.grant_honor(
            admin.guild.id, int(str(self.discord_id)), actor_id=admin.id, honor_key=str(self.honor_key),
            justification=str(self.reason), expires_at=int(expires_raw) if expires_raw else None,
        )
        await interaction.response.send_message(
            f"✅ Honraria simbólica concedida (`#{honor['id']}`). Nenhuma permissão foi concedida por esta ação.",
            ephemeral=True,
        )
        cog = get_bot(interaction).get_cog("FinancialAidCommands")
        if isinstance(cog, FinancialAidCommands):
            await cog.reconcile_honor_roles(admin.guild, discord_id=int(str(self.discord_id)))


class HonorRemoveModal(ErrorModal):
    honor_id = discord.ui.TextInput(label="ID da honraria", min_length=1, max_length=20)
    version = discord.ui.TextInput(label="Versão exibida", min_length=1, max_length=20)
    reason = discord.ui.TextInput(label="Justificativa", style=discord.TextStyle.paragraph, min_length=8, max_length=1000)

    def __init__(self) -> None:
        super().__init__(title="Remover honraria")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.honor.remove")
        result = await get_bot(interaction).services.financial_aid.remove_honor(
            admin.guild.id, int(str(self.honor_id)), actor_id=admin.id, expected_version=int(str(self.version)), reason=str(self.reason)
        )
        await interaction.response.send_message(
            f"✅ Remoção registrada para a honraria `#{result['id']}`; o histórico foi preservado.", ephemeral=True
        )
        cog = get_bot(interaction).get_cog("FinancialAidCommands")
        if isinstance(cog, FinancialAidCommands):
            await cog.reconcile_honor_roles(admin.guild, discord_id=int(result["discord_id"]))


class CertificateModal(ErrorModal):
    discord_id = discord.ui.TextInput(label="Discord ID do membro", min_length=5, max_length=32)
    honor_id = discord.ui.TextInput(label="ID da honraria (opcional)", required=False, max_length=20)
    project_id = discord.ui.TextInput(label="ID da meta (opcional)", required=False, max_length=20)

    def __init__(self) -> None:
        super().__init__(title="Emitir certificado de reconhecimento")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.certificate.issue")
        honor_raw, project_raw = str(self.honor_id).strip(), str(self.project_id).strip()
        certificate = await get_bot(interaction).services.financial_aid.issue_certificate(
            admin.guild.id, int(str(self.discord_id)), actor_id=admin.id,
            honor_id=int(honor_raw) if honor_raw else None, project_id=int(project_raw) if project_raw else None,
        )
        details = await get_bot(interaction).services.financial_aid.certificate_snapshot(
            admin.guild.id, int(certificate["id"])
        )
        await interaction.response.send_message(
            "✅ Certificado emitido e colocado na entrega persistente do membro.",
            embed=certificate_embed(get_bot(interaction), details),
            ephemeral=True,
        )


class HonorRoleModal(ErrorModal):
    honor_key = discord.ui.TextInput(label="Honraria", min_length=3, max_length=40)
    role_id = discord.ui.TextInput(label="ID do cargo simbólico", min_length=5, max_length=32)

    def __init__(self) -> None:
        super().__init__(title="Configurar cargo de honraria")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.settings")
        role = admin.guild.get_role(int(str(self.role_id)))
        if role is None:
            raise NotFoundError("Cargo Discord não encontrado.")
        if role.permissions.value != 0:
            raise ValidationError(
                "Cargo de honraria precisa ser estritamente simbólico e não pode possuir permissões."
            )
        bot_member = admin.guild.me
        if bot_member is None or role >= bot_member.top_role:
            raise ValidationError(
                "O cargo simbólico precisa ficar abaixo do maior cargo do bot para poder ser sincronizado."
            )
        configured = await get_bot(interaction).services.financial_aid.configure_honor_role(
            admin.guild.id, actor_id=admin.id, honor_key=str(self.honor_key), role_id=role.id
        )
        cog = get_bot(interaction).get_cog("FinancialAidCommands")
        if isinstance(cog, FinancialAidCommands):
            previous = configured.get("previous_discord_role_id")
            await cog.reconcile_honor_roles(
                admin.guild,
                extra_role_ids={int(previous)} if previous is not None else None,
            )
        await interaction.response.send_message(
            f"✅ `{role.name}` foi configurado como cargo simbólico, sem permissões.", ephemeral=True
        )


class FinancialSuggestionSelect(discord.ui.Select):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = {int(row["id"]): row for row in rows}
        super().__init__(
            placeholder="Escolha uma sugestão",
            options=[
                discord.SelectOption(label=f"#{row['id']} • {row['title']}"[:100], value=str(row["id"]), description=str(row["status"]))
                for row in rows[:25]
            ],
            disabled=not rows,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_financial_member(interaction, "financial.suggestion.review")
        row = self.rows[int(self.values[0])]
        embed = branded_embed(get_bot(interaction).config.branding, title=f"💡 Sugestão #{row['id']}", description=str(row["description"]))
        embed.add_field(name="Título", value=str(row["title"]), inline=True)
        embed.add_field(name="Categoria", value=str(row["category"]), inline=True)
        embed.add_field(name="Motivo", value=str(row["motivation"]), inline=False)
        if row.get("reference_url"):
            embed.add_field(name="Referência", value=str(row["reference_url"])[:1024], inline=False)
        await interaction.response.edit_message(embed=embed, view=SuggestionDecisionView(int(row["id"]), int(row["version"])))


class SuggestionDecisionModal(ErrorModal):
    reason = discord.ui.TextInput(label="Justificativa", style=discord.TextStyle.paragraph, min_length=3, max_length=500)

    def __init__(self, suggestion_id: int, version: int, status: str) -> None:
        super().__init__(title=f"Marcar sugestão como {status.lower()}")
        self.suggestion_id = suggestion_id
        self.version = version
        self.status = status

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.suggestion.review")
        result = await get_bot(interaction).services.financial_aid.review_suggestion(
            admin.guild.id, self.suggestion_id, actor_id=admin.id, expected_version=self.version,
            status=self.status, reason=str(self.reason),
        )
        await interaction.response.send_message(f"✅ Sugestão #{result['id']} marcada como {result['status']}.", ephemeral=True)
        await refresh_financial_panels(admin.guild)


class SuggestionDecisionView(ErrorView):
    def __init__(self, suggestion_id: int, version: int) -> None:
        super().__init__(timeout=600)
        self.suggestion_id = suggestion_id
        self.version = version

    @discord.ui.button(label="Em análise", emoji="🔎", style=discord.ButtonStyle.secondary)
    async def in_review(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.suggestion.review")
        await interaction.response.send_modal(SuggestionDecisionModal(self.suggestion_id, self.version, "EM_ANALISE"))

    @discord.ui.button(label="Aceitar", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.suggestion.review")
        await interaction.response.send_modal(SuggestionDecisionModal(self.suggestion_id, self.version, "ACEITA"))

    @discord.ui.button(label="Recusar", emoji="❌", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.suggestion.review")
        await interaction.response.send_modal(SuggestionDecisionModal(self.suggestion_id, self.version, "RECUSADA"))


class PixConfigurationModal(ErrorModal):
    pix_key = discord.ui.TextInput(
        label="Chave PIX (opcional se já configurada)", min_length=5, max_length=77,
        placeholder="Deixe em branco para manter a chave segura vigente",
        required=False,
    )
    recipient_name = discord.ui.TextInput(
        label="Nome do recebedor", min_length=2, max_length=25,
        placeholder="Nome registrado para o recebimento",
    )
    recipient_city = discord.ui.TextInput(
        label="Cidade do recebedor", min_length=2, max_length=15,
        placeholder="Ex.: SAO PAULO",
    )

    def __init__(self) -> None:
        super().__init__(title="Configurar PIX institucional")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.settings")
        finance = get_bot(interaction).services.financial_aid
        raw_key = str(self.pix_key).strip()
        if raw_key:
            status = await finance.configure_pix_configuration(
                admin.guild.id,
                actor_id=admin.id,
                key=raw_key,
                recipient_name=str(self.recipient_name),
                recipient_city=str(self.recipient_city),
            )
        else:
            existing = await finance.pix_configuration_status(admin.guild.id)
            if not existing["configured"]:
                raise ValidationError(
                    "Informe uma chave PIX ou configure FINANCIAL_PIX_KEY no ambiente seguro antes de salvar o recebedor."
                )
            await finance.configure_pix_recipient(
                admin.guild.id,
                actor_id=admin.id,
                recipient_name=str(self.recipient_name),
                recipient_city=str(self.recipient_city),
            )
            status = await finance.pix_configuration_status(admin.guild.id)
        await interaction.response.send_message(
            "✅ Dados PIX configurados com segurança. "
            f"Chave: `{status['masked_key']}` • Recebedor: {status['recipient_name']} / {status['recipient_city']}.\n"
            "A chave não foi publicada em auditoria nem persistida no Discord.",
            ephemeral=True,
        )
        await refresh_financial_panels(admin.guild)


class FinancialConfigView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=600)

    @discord.ui.button(label="Configurar PIX", emoji="🔐", style=discord.ButtonStyle.secondary)
    async def configure_pix(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.settings")
        await interaction.response.send_modal(PixConfigurationModal())

    @discord.ui.button(label="Cargo de honraria", emoji="🎖️", style=discord.ButtonStyle.secondary)
    async def honor_role(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.settings")
        await interaction.response.send_modal(HonorRoleModal())

    @discord.ui.button(label="Criar cargos simbólicos", emoji="🏅", style=discord.ButtonStyle.secondary)
    async def create_honor_roles(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        admin = await require_financial_member(interaction, "financial.settings")
        cog = get_bot(interaction).get_cog("FinancialAidCommands")
        if not isinstance(cog, FinancialAidCommands):
            raise ValidationError("A Central Financeira está indisponível.")
        created_or_reused = await cog.ensure_symbolic_honor_roles(
            admin.guild, actor_id=admin.id
        )
        await interaction.response.send_message(
            "✅ Cargos simbólicos configurados, sem permissões: " + ", ".join(f"`{name}`" for name in created_or_reused),
            ephemeral=True,
        )

    @discord.ui.button(label="Canal público", emoji="💰", style=discord.ButtonStyle.secondary)
    async def public_panel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.settings")
        await interaction.response.edit_message(
            content="Escolha o canal da Central de Auxílio Financeiro.",
            embed=None,
            view=FinancialPanelChannelSelectView("PUBLIC"),
        )

    @discord.ui.button(label="Painel administrativo", emoji="🛡️", style=discord.ButtonStyle.secondary)
    async def admin_panel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.settings")
        await interaction.response.edit_message(
            content="Escolha o canal privado da Administração Financeira.",
            embed=None,
            view=FinancialPanelChannelSelectView("ADMIN"),
        )

    @discord.ui.button(label="Criar central pública", emoji="➕", style=discord.ButtonStyle.primary)
    async def create_public_panel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        admin = await require_financial_member(interaction, "financial.settings")
        guild = admin.guild
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_channels:
            raise ValidationError("O bot precisa de Gerenciar Canais para criar a Central Financeira.")
        channel = discord.utils.get(guild.text_channels, name=PUBLIC_FINANCIAL_CHANNEL_NAME)
        if channel is None:
            category = interaction.channel.category if isinstance(interaction.channel, discord.TextChannel) else None
            channel = await guild.create_text_channel(
                PUBLIC_FINANCIAL_CHANNEL_NAME,
                category=category,
                reason="Central de Auxílio Financeiro da CHOQUE",
            )
        finance = get_bot(interaction).services.financial_aid
        await finance.configure_panel_channel(
            guild.id, actor_id=admin.id, panel_kind="PUBLIC", channel_id=channel.id
        )
        cog = get_bot(interaction).get_cog("FinancialAidCommands")
        if not isinstance(cog, FinancialAidCommands):
            raise ValidationError("O módulo financeiro não está carregado.")
        await cog.publish_or_refresh_public_panel(guild, channel)
        await interaction.response.send_message(
            f"✅ Central Financeira configurada em {channel.mention}.", ephemeral=True
        )


class FinancialPanelChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, panel_kind: str) -> None:
        super().__init__(
            placeholder="Escolha um canal de texto",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.panel_kind = panel_kind

    async def callback(self, interaction: discord.Interaction) -> None:
        admin = await require_financial_member(interaction, "financial.settings")
        channel = self.values[0]
        if not isinstance(channel, discord.TextChannel):
            raise ValidationError("Escolha um canal de texto.")
        bot = get_bot(interaction)
        if self.panel_kind == "ADMIN":
            await require_private_financial_admin_channel(bot, admin.guild, channel)
        finance = bot.services.financial_aid
        await finance.configure_panel_channel(
            admin.guild.id,
            actor_id=admin.id,
            panel_kind=self.panel_kind,
            channel_id=channel.id,
        )
        cog = bot.get_cog("FinancialAidCommands")
        if not isinstance(cog, FinancialAidCommands):
            raise ValidationError("O módulo financeiro não está carregado.")
        if self.panel_kind == "PUBLIC":
            await cog.publish_or_refresh_public_panel(admin.guild, channel)
            label = "Central Financeira"
        else:
            await cog.publish_or_refresh_admin_panel(admin.guild, channel)
            label = "Painel Administrativo Financeiro"
        await interaction.response.edit_message(
            content=f"✅ {label} configurado em {channel.mention}.", embed=None, view=None
        )


class FinancialPanelChannelSelectView(ErrorView):
    def __init__(self, panel_kind: str) -> None:
        super().__init__(timeout=600)
        self.add_item(FinancialPanelChannelSelect(panel_kind))


class HonorsAdminView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=600)

    @discord.ui.button(label="Conceder", emoji="🎖️", style=discord.ButtonStyle.success)
    async def grant(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.honor.grant")
        await interaction.response.send_modal(HonorGrantModal())

    @discord.ui.button(label="Remover", emoji="↩️", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.honor.remove")
        await interaction.response.send_modal(HonorRemoveModal())

    @discord.ui.button(label="Certificado", emoji="🧾", style=discord.ButtonStyle.secondary)
    async def certificate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.certificate.issue")
        await interaction.response.send_modal(CertificateModal())


class FinancialAdminPanelView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Metas", emoji="🎯", style=discord.ButtonStyle.primary, custom_id="choque:financial:admin:projects:v1", row=0)
    async def projects(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.project.manage")
        await interaction.response.send_message("Gerenciamento de metas.", view=MetaManagementView(), ephemeral=True)

    @discord.ui.button(label="Contribuições", emoji="💳", style=discord.ButtonStyle.primary, custom_id="choque:financial:admin:contributions:v1", row=0)
    async def contributions(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        admin = await require_financial_member(interaction, "financial.contribution.review")
        rows = await get_bot(interaction).services.financial_aid.contribution_page(admin.guild.id, statuses=("PENDENTE",))
        await interaction.response.send_message(
            "Selecione uma declaração pendente. Confirme somente depois de conferir o recebimento fora do bot.",
            view=ContributionSelectView(rows), ephemeral=True,
        )

    @discord.ui.button(label="Despesa", emoji="➖", style=discord.ButtonStyle.secondary, custom_id="choque:financial:admin:expense:v1", row=0)
    async def expense(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.expense.record")
        await interaction.response.send_modal(ExpenseModal())

    @discord.ui.button(label="Relatórios", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="choque:financial:admin:reports:v1", row=0)
    async def reports(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        admin = await require_financial_member(interaction, "financial.audit.view")
        snapshot = await get_bot(interaction).services.financial_aid.transparency_snapshot(admin.guild.id)
        await interaction.response.send_message(
            f"Saldo do Fundo Geral: **{FinancialAidService.format_cents(int(snapshot['general_fund']['balance_cents']))}**. "
            "O livro-caixa detalhado permanece auditável e não é apagado.",
            view=FinancialReportsView(), ephemeral=True,
        )

    @discord.ui.button(label="Honrarias", emoji="🏅", style=discord.ButtonStyle.secondary, custom_id="choque:financial:admin:honors:v1", row=0)
    async def honors(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.honor.grant")
        await interaction.response.send_message("Honrarias e certificados simbólicos.", view=HonorsAdminView(), ephemeral=True)

    @discord.ui.button(label="Sugestões", emoji="💡", style=discord.ButtonStyle.secondary, custom_id="choque:financial:admin:suggestions:v1", row=1)
    async def suggestions(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        admin = await require_financial_member(interaction, "financial.suggestion.review")
        rows = await get_bot(interaction).services.database.fetchall(
            "SELECT * FROM financial_suggestions WHERE guild_id=? AND status IN ('PENDENTE','EM_ANALISE') ORDER BY created_at, id LIMIT 25",
            (admin.guild.id,),
        )
        items = [dict(row) for row in rows]
        if not items:
            await interaction.response.send_message("Não há sugestões pendentes.", ephemeral=True)
            return
        view = ErrorView(timeout=600)
        view.add_item(FinancialSuggestionSelect(items))
        await interaction.response.send_message("Escolha uma sugestão para análise.", view=view, ephemeral=True)

    @discord.ui.button(label="Configurar", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="choque:financial:admin:settings:v1", row=1)
    async def configure(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.settings")
        await interaction.response.send_message(
            "Configurações seguras. A chave PIX é exibida somente mascarada e nunca é publicada em auditoria, logs ou mensagens. "
            "Use esta área elevada para configurar os dados necessários ao QR Code.",
            view=FinancialConfigView(), ephemeral=True,
        )


class FinancialReportsView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=600)

    @discord.ui.button(label="Últimos lançamentos", emoji="📚", style=discord.ButtonStyle.secondary)
    async def ledger(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        admin = await require_financial_member(interaction, "financial.audit.view")
        rows = await get_bot(interaction).services.financial_aid.ledger_entries(admin.guild.id)
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title="📚 Livro-caixa financeiro • últimos lançamentos",
            description="Lançamentos são imutáveis; estornos aparecem como novas linhas vinculadas ao original.",
        )
        lines = []
        for row in rows[:20]:
            project = str(row.get("project_name") or "Fundo Geral")[:45]
            lines.append(
                f"`#{row['id']}` {FinancialAidService.format_cents(int(row['amount_cents']))} • "
                f"{row['entry_type']} • {project}"
            )
        embed.add_field(name="Movimentações", value="\n".join(lines) or "Nenhum lançamento ainda.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Estornar despesa", emoji="↩️", style=discord.ButtonStyle.danger)
    async def reverse_expense(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_financial_member(interaction, "financial.expense.reverse")
        await interaction.response.send_modal(ExpenseReverseModal())


async def refresh_financial_panels(guild: discord.Guild) -> None:
    cog = guild._state._get_client().get_cog("FinancialAidCommands")  # type: ignore[attr-defined]
    if isinstance(cog, FinancialAidCommands):
        await cog.refresh_panels(guild)


class FinancialAidCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._panel_locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._runtime_reconciliation_lock = asyncio.Lock()
        self.bot.add_view(FinancialAidPanelView())
        self.bot.add_view(FinancialAdminPanelView())
        self.bot.add_view(PixDisclosureView())
        if not self.bot.check_mode:
            self.honor_reconciliation.start()
            self.notification_delivery_loop.start()

    def cog_unload(self) -> None:
        self.honor_reconciliation.cancel()
        self.notification_delivery_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        guild = self.bot.get_guild(self.bot.guild_id) if self.bot.guild_id else None
        if guild:
            await self.reconcile_financial_runtime(guild)

    async def reconcile_financial_runtime(self, guild: discord.Guild) -> None:
        """Recover durable Finance projections without duplicating roles or messages."""

        async with self._runtime_reconciliation_lock:
            await self.services.financial_aid.ensure_defaults(guild.id)
            await self.services.financial_aid.expire_due_honors(guild.id)
            await self.services.financial_aid.reconcile_confirmed_contributions(guild.id)
            now = self.services.financial_aid.clock()
            active_honors = await self.services.database.fetchall(
                """
                SELECT DISTINCT d.honor_key
                FROM financial_member_honors AS h
                JOIN financial_honor_definitions AS d ON d.id=h.honor_definition_id
                WHERE h.guild_id=? AND h.removed_at IS NULL
                  AND (h.expires_at IS NULL OR h.expires_at>?)
                """,
                (guild.id, now),
            )
            required_keys = {str(row["honor_key"]) for row in active_honors}
            if required_keys:
                bot_actor_id = int(self.bot.user.id) if self.bot.user is not None else None
                await self.ensure_symbolic_honor_roles(
                    guild,
                    actor_id=bot_actor_id,
                    honor_keys=required_keys,
                )
            await self.refresh_panels(guild)
            await self.reconcile_honor_roles(guild)

    def _panel_lock(self, guild_id: int, panel_kind: str) -> asyncio.Lock:
        return self._panel_locks.setdefault((guild_id, panel_kind), asyncio.Lock())

    async def publish_or_refresh_public_panel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        async with self._panel_lock(guild.id, "FINANCIAL_AID"):
            return await self._publish_or_refresh_public_panel_unlocked(guild, channel)

    async def _publish_or_refresh_public_panel_unlocked(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        panel = await self.services.settings.get_panel(guild.id, "FINANCIAL_AID")
        embed = await financial_panel_embed(self.bot, guild.id)
        if panel and int(panel["channel_id"]) == channel.id:
            try:
                message = await channel.fetch_message(int(panel["message_id"]))
            except discord.NotFound:
                pass
            else:
                await message.edit(embed=embed, view=FinancialAidPanelView())
                return message
        await self._retire_panel_if_moved(guild, panel, channel, "Central Financeira")
        adopted = await self._find_panel_message(channel, PUBLIC_PANEL_MARKER)
        if adopted is not None:
            await adopted.edit(embed=embed, view=FinancialAidPanelView())
            await self.services.settings.upsert_panel(
                guild.id, "FINANCIAL_AID", channel.id, adopted.id
            )
            return adopted
        message = await channel.send(embed=embed, view=FinancialAidPanelView())
        await self.services.settings.upsert_panel(guild.id, "FINANCIAL_AID", channel.id, message.id)
        return message

    async def publish_or_refresh_admin_panel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        async with self._panel_lock(guild.id, "FINANCIAL_AID_ADMIN"):
            return await self._publish_or_refresh_admin_panel_unlocked(guild, channel)

    async def _publish_or_refresh_admin_panel_unlocked(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        panel = await self.services.settings.get_panel(guild.id, "FINANCIAL_AID_ADMIN")
        embed = await admin_panel_embed(self.bot, guild.id)
        if panel and int(panel["channel_id"]) == channel.id:
            try:
                message = await channel.fetch_message(int(panel["message_id"]))
            except discord.NotFound:
                pass
            else:
                await message.edit(embed=embed, view=FinancialAdminPanelView())
                return message
        await self._retire_panel_if_moved(guild, panel, channel, "Painel Administrativo Financeiro")
        adopted = await self._find_panel_message(channel, ADMIN_PANEL_MARKER)
        if adopted is not None:
            await adopted.edit(embed=embed, view=FinancialAdminPanelView())
            await self.services.settings.upsert_panel(
                guild.id, "FINANCIAL_AID_ADMIN", channel.id, adopted.id
            )
            return adopted
        message = await channel.send(embed=embed, view=FinancialAdminPanelView())
        await self.services.settings.upsert_panel(guild.id, "FINANCIAL_AID_ADMIN", channel.id, message.id)
        return message

    async def publish_or_refresh_highlights_panel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        async with self._panel_lock(guild.id, "FINANCIAL_AID_HIGHLIGHTS"):
            panel = await self.services.settings.get_panel(guild.id, "FINANCIAL_AID_HIGHLIGHTS")
            embed = financial_highlights_panel_embed(self.bot)
            message: discord.Message | None = None
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                except discord.NotFound:
                    message = None
            if message is None:
                message = await self._find_panel_message(channel, HIGHLIGHTS_PANEL_MARKER)
            if message is None:
                message = await channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                await message.edit(embed=embed, view=None)
            await self.services.settings.upsert_panel(
                guild.id, "FINANCIAL_AID_HIGHLIGHTS", channel.id, message.id
            )
            if not getattr(message, "pinned", False):
                try:
                    await message.pin(reason="Painel persistente de Destaques Financeiros")
                except (discord.Forbidden, discord.HTTPException):
                    LOGGER.warning(
                        "Painel de destaques publicado, mas não pôde ser fixado",
                        extra={"guild_id": guild.id, "channel_id": channel.id},
                    )
            return message

    async def refresh_panels(self, guild: discord.Guild) -> None:
        public_id = await self.services.settings.get(guild.id, "financial_panel_channel_id")
        if public_id:
            channel = guild.get_channel(int(public_id))
            if isinstance(channel, discord.TextChannel):
                await self.publish_or_refresh_public_panel(guild, channel)
        admin_id = await self.services.settings.get(guild.id, "financial_admin_channel_id")
        if admin_id:
            channel = guild.get_channel(int(admin_id))
            if isinstance(channel, discord.TextChannel):
                await self.publish_or_refresh_admin_panel(guild, channel)
        highlights_id = await self.services.settings.get(
            guild.id, "financial_highlights_channel_id"
        )
        if highlights_id:
            channel = guild.get_channel(int(highlights_id))
            if isinstance(channel, discord.TextChannel):
                await self.publish_or_refresh_highlights_panel(guild, channel)

    async def _find_panel_message(
        self, channel: discord.TextChannel, marker: str
    ) -> discord.Message | None:
        bot_user = getattr(self.bot, "user", None)
        if bot_user is None:
            return None
        try:
            async for message in channel.history(limit=100):
                if _message_has_marker(message, bot_user_id=bot_user.id, marker=marker):
                    return message
        except (discord.Forbidden, discord.HTTPException) as exc:
            raise ValidationError(
                "Não foi possível conferir os painéis existentes; nenhuma nova mensagem foi criada."
            ) from exc
        return None

    async def _retire_panel_if_moved(
        self,
        guild: discord.Guild,
        panel: object,
        destination: discord.TextChannel,
        label: str,
    ) -> None:
        if not panel or int(panel["channel_id"]) == destination.id:  # type: ignore[index]
            return
        previous_channel = guild.get_channel(int(panel["channel_id"]))  # type: ignore[index]
        if not isinstance(previous_channel, discord.TextChannel):
            try:
                fetched = await self.bot.fetch_channel(int(panel["channel_id"]))  # type: ignore[index]
            except discord.NotFound:
                return
            except (discord.Forbidden, discord.HTTPException) as exc:
                raise ValidationError(
                    "Não foi possível conferir o painel anterior; a Central não foi movida."
                ) from exc
            if not isinstance(fetched, discord.TextChannel) or fetched.guild.id != guild.id:
                raise ValidationError("O painel anterior registrado não pertence a um canal seguro da guild.")
            previous_channel = fetched
        try:
            message = await previous_channel.fetch_message(int(panel["message_id"]))  # type: ignore[index]
        except discord.NotFound:
            return
        except (discord.Forbidden, discord.HTTPException) as exc:
            raise ValidationError(
                "Não foi possível desativar o painel anterior; a Central não foi movida para evitar controles duplicados."
            ) from exc
        try:
            await message.edit(
                content=f"⚠️ {label} movido para {destination.mention}. Use apenas o painel novo.",
                view=None,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            raise ValidationError(
                "Não foi possível desativar o painel anterior; a Central não foi movida para evitar controles duplicados."
            ) from exc

    async def ensure_symbolic_honor_roles(
        self,
        guild: discord.Guild,
        *,
        actor_id: int | None,
        honor_keys: set[str] | None = None,
    ) -> list[str]:
        """Create or reuse only zero-permission symbolic roles and keep them manageable."""

        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            raise ValidationError("O bot precisa de Gerenciar Cargos para criar as honrarias simbólicas.")
        await self.services.financial_aid.ensure_defaults(guild.id)
        definitions = await self.services.database.fetchall(
            """
            SELECT honor_key, title, discord_role_id
            FROM financial_honor_definitions WHERE guild_id=? AND active=1
            ORDER BY id
            """,
            (guild.id,),
        )
        configured_roles: dict[str, discord.Role] = {}
        requested_keys = {key.strip().upper() for key in honor_keys} if honor_keys else None
        for definition in definitions:
            honor_key = str(definition["honor_key"])
            if requested_keys is not None and honor_key not in requested_keys:
                continue
            presentation = HONOR_ROLE_PRESENTATION.get(honor_key)
            if presentation is None:
                continue
            role_name, role_color = presentation
            role = (
                guild.get_role(int(definition["discord_role_id"]))
                if definition["discord_role_id"]
                else None
            )
            if role is None:
                aliases = {role_name, str(definition["title"]), f"◈ {honor_key.title()} da CHOQUE"}
                role = next((item for item in guild.roles if item.name in aliases), None)
            if role is None:
                role = await guild.create_role(
                    name=role_name,
                    colour=discord.Colour(role_color),
                    hoist=True,
                    mentionable=False,
                    permissions=discord.Permissions.none(),
                    reason="Cargo de honraria estritamente simbólica CHOQUE",
                )
            if role.permissions.value != 0:
                raise ValidationError(
                    f"O cargo `{role.name}` possui permissões e não pode ser associado a honraria."
                )
            if role >= bot_member.top_role:
                raise ValidationError(
                    f"O cargo `{role.name}` precisa ficar abaixo do maior cargo do bot."
                )
            if (
                role.name != role_name
                or role.colour.value != role_color
                or not role.hoist
                or role.mentionable
            ):
                updated = await role.edit(
                    name=role_name,
                    colour=discord.Colour(role_color),
                    hoist=True,
                    mentionable=False,
                    permissions=discord.Permissions.none(),
                    reason="Padronização visual de honraria simbólica CHOQUE",
                )
                if updated is not None:
                    role = updated
            if definition["discord_role_id"] is None or int(definition["discord_role_id"]) != role.id:
                await self.services.financial_aid.configure_honor_role(
                    guild.id,
                    actor_id=int(actor_id or 0),
                    honor_key=honor_key,
                    role_id=role.id,
                )
            configured_roles[honor_key] = role

        protected_tokens = ("admin", "comando", "comandante", "subcomandante", "propriet")
        protected_positions = [
            role.position
            for role in guild.roles
            if role.position < bot_member.top_role.position
            and any(token in role.name.casefold() for token in protected_tokens)
        ]
        ceiling = bot_member.top_role.position - 1
        if protected_positions:
            ceiling = min(ceiling, min(protected_positions) - 1)
        tier_order = ("APOIADOR", "COLABORADOR", "BENFEITOR", "PATRONO")
        movable = [configured_roles[key] for key in tier_order if key in configured_roles]
        if movable and ceiling >= len(movable):
            positions = {
                role: ceiling - (len(movable) - index - 1)
                for index, role in enumerate(movable)
            }
            try:
                await guild.edit_role_positions(
                    positions=positions,
                    reason="Hierarquia visual segura das honrarias simbólicas CHOQUE",
                )
            except discord.HTTPException:
                LOGGER.warning(
                    "Cargos financeiros configurados, mas a posição visual não pôde ser ajustada",
                    extra={"guild_id": guild.id},
                )
        await self.reconcile_honor_roles(guild)
        return [HONOR_ROLE_PRESENTATION[key][0] for key in tier_order if key in configured_roles]

    @tasks.loop(minutes=5)
    async def honor_reconciliation(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.reconcile_financial_runtime(guild)
            except Exception:
                LOGGER.exception("Falha ao reconciliar honrarias financeiras", extra={"guild_id": guild.id})

    @honor_reconciliation.before_loop
    async def before_honor_reconciliation(self) -> None:
        await self.bot.wait_until_ready()

    async def reconcile_honor_roles(
        self,
        guild: discord.Guild,
        *,
        discord_id: int | None = None,
        extra_role_ids: set[int] | None = None,
    ) -> None:
        """Converge only configured zero-permission honor roles after restart.

        The database remains authoritative. The sync is idempotent and avoids
        granting a role whose current Discord permissions are nonzero.
        """
        now = self.services.financial_aid.clock()
        configured = await self.services.database.fetchall(
            """
            SELECT id, discord_role_id FROM financial_honor_definitions
            WHERE guild_id=? AND discord_role_id IS NOT NULL
            """,
            (guild.id,),
        )
        configured_roles = {int(row["discord_role_id"]) for row in configured}
        configured_roles.update(extra_role_ids or set())
        if not configured_roles:
            return
        params: tuple[object, ...] = (guild.id, now)
        where = """
            WHERE h.guild_id=? AND h.removed_at IS NULL
              AND (h.expires_at IS NULL OR h.expires_at>?)
              AND d.active=1 AND d.discord_role_id IS NOT NULL
        """
        if discord_id is not None:
            where += " AND h.discord_id=?"
            params = (guild.id, now, discord_id)
        rows = await self.services.database.fetchall(
            f"""
            SELECT h.discord_id, d.discord_role_id, h.id AS honor_id
            FROM financial_member_honors h
            JOIN financial_honor_definitions d ON d.id=h.honor_definition_id
            {where}
            """,
            params,
        )
        desired: dict[int, set[int]] = {}
        for row in rows:
            desired.setdefault(int(row["discord_id"]), set()).add(int(row["discord_role_id"]))
        history_params: tuple[object, ...] = (guild.id,)
        history_where = """
            WHERE h.guild_id=? AND d.discord_role_id IS NOT NULL
        """
        if discord_id is not None:
            history_where += " AND h.discord_id=?"
            history_params = (guild.id, discord_id)
        history = await self.services.database.fetchall(
            f"""
            SELECT DISTINCT h.discord_id
            FROM financial_member_honors h
            JOIN financial_honor_definitions d ON d.id=h.honor_definition_id
            {history_where}
            """,
            history_params,
        )
        target_ids = set(desired) | {int(row["discord_id"]) for row in history}
        for target_id in target_ids:
            desired_roles = desired.get(target_id, set())
            member = guild.get_member(target_id)
            if member is None:
                try:
                    member = await guild.fetch_member(target_id)
                except discord.DiscordException:
                    continue
            for role_id in configured_roles:
                role = guild.get_role(role_id)
                if role is None:
                    continue
                if role.permissions.value != 0:
                    LOGGER.error("Cargo de honraria %s possui permissões e foi bloqueado", role.id)
                    continue
                bot_member = guild.me
                if bot_member is None or role >= bot_member.top_role:
                    LOGGER.error("Cargo de honraria %s está acima do bot e foi bloqueado", role.id)
                    continue
                should_have = role_id in desired_roles
                if should_have and role not in member.roles:
                    await member.add_roles(role, reason="Sincronização de honraria simbólica CHOQUE")
                    await self.services.audit.record(
                        guild.id, "FINANCIAL_HONOR_ROLE_SYNCED", actor_id=None, target_id=member.id,
                        after={"role_id": role.id, "symbolic_only": True}, reason="Reconciliação de honraria simbólica."
                    )
                elif not should_have and role in member.roles:
                    await member.remove_roles(role, reason="Revogação de honraria simbólica CHOQUE")
                    await self.services.audit.record(
                        guild.id, "FINANCIAL_HONOR_ROLE_REVOKED", actor_id=None, target_id=member.id,
                        after={"role_id": role.id, "symbolic_only": True},
                        reason="Honraria removida, expirada ou desativada."
                    )

    @tasks.loop(seconds=2)
    async def notification_delivery_loop(self) -> None:
        for _ in range(6):
            row = await self._claim_financial_notification()
            if row is None:
                break
            await self._deliver_financial_notification(row)

    @notification_delivery_loop.before_loop
    async def before_notification_delivery_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _claim_financial_notification(self) -> dict[str, object] | None:
        now = self.services.financial_aid.clock()
        async with self.services.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM financial_notifications
                WHERE attempts<8 AND (
                    (status IN ('PENDING','FAILED') AND available_at<=?)
                    OR (status='PROCESSING' AND updated_at<=?)
                )
                ORDER BY id LIMIT 1
                """,
                (now, now - 120_000),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            update = await connection.execute(
                """
                UPDATE financial_notifications
                SET status='PROCESSING', attempts=attempts+1, updated_at=?
                WHERE id=? AND status=? AND updated_at=? AND revision=?
                """,
                (
                    now,
                    int(row["id"]),
                    str(row["status"]),
                    int(row["updated_at"]),
                    int(row["revision"]),
                ),
            )
            if update.rowcount != 1:
                return None
            return dict(row)

    async def _deliver_financial_notification(self, row: dict[str, object]) -> None:
        now = self.services.financial_aid.clock()
        notification_id = int(row["id"])
        claimed_revision = int(row.get("revision") or 1)
        try:
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                raise ValidationError("Payload de notificação financeira inválido.")
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None:
                raise NotFoundError("Servidor da notificação financeira não está disponível.")
            notification_type = str(row["notification_type"])
            if notification_type == "CERTIFICATE_ISSUED":
                certificate = await self.services.financial_aid.certificate_snapshot(
                    guild.id, int(row["subject_id"])
                )
                payload = {
                    **payload,
                    "member_name": certificate["member_name"],
                    "honor_title": certificate["honor_title"],
                    "project_name": certificate.get("project_name"),
                    "project_code": certificate.get("project_code"),
                    "achievement_titles": certificate["achievement_titles"],
                    "issued_at": certificate["issued_at"],
                }
            if notification_type == "CONTRIBUTION_HIGHLIGHT":
                highlight = await self.services.financial_aid.contribution_highlight_snapshot(
                    guild.id, int(row["subject_id"])
                )
                public_member = None
                if str(highlight.get("visibility")) == "PUBLICO":
                    public_member = guild.get_member(int(highlight["discord_id"]))
                embed = financial_contribution_highlight_embed(
                    self.bot,
                    highlight,
                    member=public_member,
                    notification_id=notification_id,
                )
            else:
                embed = financial_notification_embed(
                    self.bot,
                    notification_type,
                    payload,
                    notification_id=notification_id,
                )
            channel_message_id = row.get("channel_message_id")
            dm_message_id = row.get("dm_message_id")
            delivery_error: str | None = None
            channel_key = row.get("channel_setting_key")
            if channel_key:
                channel_id = await self.services.settings.get(guild.id, str(channel_key))
                channel = guild.get_channel(int(channel_id)) if channel_id else None
                if not isinstance(channel, discord.TextChannel):
                    raise NotFoundError("Canal financeiro configurado não foi encontrado.")
                message = None
                if channel_message_id is not None:
                    try:
                        message = await channel.fetch_message(int(channel_message_id))
                    except discord.NotFound:
                        message = None
                if message is None:
                    message = await self._find_notification_message(channel, notification_id)
                if message is None:
                    message = await channel.send(
                        embed=embed,
                        nonce=notification_id,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    await message.edit(embed=embed, view=None)
                channel_message_id = message.id
                await self.services.database.execute(
                    """
                    UPDATE financial_notifications
                    SET channel_message_id=?, updated_at=?
                    WHERE id=? AND status='PROCESSING' AND revision=?
                    """,
                    (message.id, now, notification_id, claimed_revision),
                )
            target_id = row.get("target_discord_id")
            dm_enabled = await self.services.settings.get(guild.id, "financial_dm_enabled", True)
            if target_id is not None and dm_message_id is None and bool(dm_enabled):
                target = guild.get_member(int(target_id)) or self.bot.get_user(int(target_id))
                if target is None:
                    try:
                        target = await self.bot.fetch_user(int(target_id))
                    except discord.DiscordException:
                        target = None
                if target is None:
                    delivery_error = "Destinatário não localizado para DM."
                else:
                    try:
                        dm_channel = getattr(target, "dm_channel", None)
                        if dm_channel is None and hasattr(target, "create_dm"):
                            dm_channel = await target.create_dm()
                        if dm_channel is None:
                            message = await target.send(
                                embed=embed,
                                nonce=notification_id,
                                allowed_mentions=discord.AllowedMentions.none(),
                            )
                        else:
                            message = await self._find_notification_message(
                                dm_channel, notification_id
                            )
                            if message is None:
                                message = await dm_channel.send(
                                    embed=embed,
                                    nonce=notification_id,
                                    allowed_mentions=discord.AllowedMentions.none(),
                                )
                        dm_message_id = message.id
                        await self.services.database.execute(
                            """
                            UPDATE financial_notifications
                            SET dm_message_id=?, updated_at=?
                            WHERE id=? AND status='PROCESSING' AND revision=?
                            """,
                            (message.id, now, notification_id, claimed_revision),
                        )
                    except (discord.Forbidden, discord.NotFound):
                        delivery_error = "DM indisponível para o destinatário."
            elif target_id is not None and not bool(dm_enabled):
                delivery_error = "DM financeiro desativado na configuração."
            await self.services.database.execute(
                """
                UPDATE financial_notifications
                SET status='DELIVERED', delivered_at=?, last_error=?, updated_at=?
                WHERE id=? AND status='PROCESSING' AND revision=?
                """,
                (now, delivery_error, now, notification_id, claimed_revision),
            )
        except Exception as exc:
            attempt = int(row.get("attempts") or 0) + 1
            delay = min(300_000, 5_000 * 2 ** min(attempt, 6))
            await self.services.database.execute(
                """
                UPDATE financial_notifications
                SET status='FAILED', available_at=?, last_error=?, updated_at=?
                WHERE id=? AND status='PROCESSING' AND revision=?
                """,
                (
                    now + delay,
                    str(exc)[:1000],
                    now,
                    notification_id,
                    claimed_revision,
                ),
            )
            LOGGER.exception("Falha ao entregar notificação financeira %s", notification_id)

    async def _find_notification_message(
        self,
        channel: discord.TextChannel | discord.DMChannel,
        notification_id: int,
    ) -> discord.Message | None:
        bot_user = getattr(self.bot, "user", None)
        if bot_user is None:
            return None
        marker = f"Notificação financeira #{notification_id}"
        try:
            async for message in channel.history(limit=100):
                if _message_has_marker(message, bot_user_id=bot_user.id, marker=marker):
                    return message
        except (discord.Forbidden, discord.HTTPException) as exc:
            raise ValidationError(
                "Não foi possível conferir a entrega anterior da notificação financeira."
            ) from exc
        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FinancialAidCommands(bot))
