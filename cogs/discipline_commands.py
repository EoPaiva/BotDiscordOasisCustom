from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from choque.discipline import WARNING_TYPES
from choque.embeds import branded_embed
from choque.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from choque.models import PunishmentType
from choque.time_utils import discord_timestamp
from cogs.config_ui import respond_error
from cogs.member_sync import sync_member_status_roles

HISTORY_PAGE_SIZE = 10
ADV_PAGE_SIZE = 5
ADV_SEVERITY_LABELS = {
    "LEVE": ("🟢", "Leve"),
    "MODERADA": ("🟡", "Moderada"),
    "GRAVE": ("🟠", "Grave"),
    "GRAVISSIMA": ("🔴", "Gravíssima"),
}
LOGGER = logging.getLogger(__name__)


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_member(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "DISCIPLINE")
    if not await bot.services.permissions.has(interaction.user, "discipline.view.self"):
        raise PermissionDenied("Você não possui permissão para consultar sua situação disciplinar.")
    return interaction.user


async def require_admin(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "DISCIPLINE")
    if not await bot.services.permissions.has(interaction.user, "discipline.manage"):
        raise PermissionDenied("Você não possui permissão para administrar a disciplina.")
    return interaction.user


class ErrorView(discord.ui.View):
    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await respond_error(interaction, error)


class MemberView(ErrorView):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            await require_member(interaction)
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True


class AdminView(ErrorView):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            await require_admin(interaction)
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True


class ErrorModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await respond_error(interaction, error)


def build_discipline_landing_embed(bot: ChoqueBot) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title="⚖️ Disciplina • CHOQUE - BGR",
        description=(
            "Consulte sua situação e seu histórico disciplinar. Ocorrências não representam "
            "punição automática; advertências e suspensões dependem de decisão humana do Comando."
        ),
    )


async def build_adv_dashboard_embeds(bot: ChoqueBot, guild_id: int) -> list[discord.Embed]:
    rows = await bot.services.discipline.active_warning_dashboard(guild_id)
    page_count = max(1, math.ceil(len(rows) / ADV_PAGE_SIZE))
    embeds: list[discord.Embed] = []
    for page in range(page_count):
        page_rows = rows[page * ADV_PAGE_SIZE : (page + 1) * ADV_PAGE_SIZE]
        embed = branded_embed(
            bot.config.branding,
            title="📋 ADVs ativas • CHOQUE - BGR",
            description=(
                "Projeção atual das advertências disciplinares vigentes. "
                "O histórico permanece preservado depois do encerramento."
                if page_rows
                else "Nenhuma ADV está ativa neste momento."
            ),
        )
        for row in page_rows:
            severity = str(row.get("severity") or row.get("warning_type") or "MODERADA")
            icon, label = ADV_SEVERITY_LABELS.get(severity, ("⚪", severity.title()))
            duration = row.get("duration_days")
            ends_at = row.get("ends_at")
            period = (
                f"{duration} dia(s) • expira {discord_timestamp(int(ends_at), 'R')}"
                if duration is not None and ends_at is not None
                else "Sem prazo definido (registro legado)"
            )
            embed.add_field(
                name=f"{icon} ADV #{row['id']} • <@{row['discord_id']}>",
                value=(
                    f"**Gravidade:** {label}\n"
                    f"**Patente:** {row.get('rank_name') or 'Não definida'}\n"
                    f"**Motivo:** {str(row['reason'])[:600]}\n"
                    f"**Aplicada:** {discord_timestamp(int(row['created_at']), 'd')}\n"
                    f"**Duração:** {period}"
                ),
                inline=False,
            )
        embed.set_footer(
            text=(
                f"{bot.config.branding.footer} • Página {page + 1}/{page_count} • "
                f"{len(rows)} ADV(s) ativa(s)"
            )
        )
        embeds.append(embed)
    return embeds


async def build_summary_embed(
    bot: ChoqueBot, guild: discord.Guild, discord_id: int
) -> discord.Embed:
    summary = await bot.services.discipline.member_summary(guild.id, discord_id)
    member = summary["member"]
    embed = branded_embed(
        bot.config.branding,
        title=f"⚖️ Situação disciplinar • {member['mta_nick']}",
        description=f"<@{discord_id}> • status funcional `{member['status']}`",
    )
    embed.add_field(name="Ocorrências abertas", value=str(summary["open_occurrences"]))
    embed.add_field(name="Advertências ativas", value=str(summary["active_warnings"]))
    embed.add_field(name="Suspensões", value=str(summary["suspensions"]))
    embed.add_field(name="Patente", value=member["rank_name"] or "Não definida", inline=False)
    embed.add_field(
        name="Transparência",
        value="Nenhum registro é apagado. Cumprimentos, revogações e encerramentos ficam auditados.",
        inline=False,
    )
    return embed


async def build_history_embed(
    bot: ChoqueBot, guild: discord.Guild, discord_id: int, page: int
) -> tuple[discord.Embed, int, int]:
    total = await bot.services.discipline.history_count(guild.id, discord_id)
    page_count = max(1, math.ceil(total / HISTORY_PAGE_SIZE))
    safe_page = min(max(page, 0), page_count - 1)
    rows = await bot.services.discipline.history(
        guild.id,
        discord_id,
        limit=HISTORY_PAGE_SIZE,
        offset=safe_page * HISTORY_PAGE_SIZE,
    )
    labels = {"OCCURRENCE": "Ocorrência", "WARNING": "Advertência", "SUSPENSION": "Suspensão"}
    icons = {"OCCURRENCE": "📝", "WARNING": "⚠️", "SUSPENSION": "⏸️"}
    lines: list[str] = []
    for row in rows:
        record_type = str(row["record_type"])
        subtype = f" • {row['warning_type']}" if row.get("warning_type") else ""
        period = ""
        if record_type in {"SUSPENSION", "WARNING"} and row.get("ends_at") is not None:
            period = (
                f"\nPeríodo: {discord_timestamp(int(row['starts_at']), 'd')} → "
                f"{discord_timestamp(int(row['ends_at']), 'd')}"
            )
        evidence = f"\n[Evidência]({row['evidence_url']})" if row.get("evidence_url") else ""
        lines.append(
            f"{icons[record_type]} **#{row['id']} • {labels[record_type]}{subtype}** "
            f"`{row['status']}`\n{row['reason']}{period}{evidence}\n"
            f"Registrado {discord_timestamp(int(row['created_at']), 'R')}"
        )
    embed = branded_embed(
        bot.config.branding,
        title="📋 Histórico disciplinar",
        description="\n\n".join(lines) or "Nenhum registro disciplinar localizado.",
    )
    embed.set_footer(
        text=f"{bot.config.branding.footer} • Página {safe_page + 1}/{page_count} • {total} registro(s)"
    )
    return embed, page_count, safe_page


class DisciplinePanelView(MemberView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Minha situação",
        emoji="🔎",
        style=discord.ButtonStyle.primary,
        custom_id="choque:discipline:summary:v1",
    )
    async def summary(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        await interaction.response.send_message(
            embed=await build_summary_embed(get_bot(interaction), member.guild, member.id),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Meu histórico",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:discipline:history:v1",
    )
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        embed, page_count, page = await build_history_embed(
            get_bot(interaction), member.guild, member.id, 0
        )
        await interaction.response.send_message(
            embed=embed,
            view=DisciplineHistoryView(member.id, member.id, page, page_count, admin=False),
            ephemeral=True,
        )


class DisciplineHistoryView(ErrorView):
    def __init__(
        self, owner_id: int, target_id: int, page: int, page_count: int, *, admin: bool
    ) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.target_id = target_id
        self.page = page
        self.page_count = page_count
        self.admin = admin
        self.previous.disabled = page <= 0
        self.next.disabled = page >= page_count - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Este histórico pertence a outro usuário.", ephemeral=True
            )
            return False
        try:
            await (require_admin(interaction) if self.admin else require_member(interaction))
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True

    async def show(self, interaction: discord.Interaction, page: int) -> None:
        bot = get_bot(interaction)
        embed, page_count, safe_page = await build_history_embed(
            bot, interaction.guild, self.target_id, page
        )
        await interaction.response.edit_message(
            embed=embed,
            view=DisciplineHistoryView(
                self.owner_id, self.target_id, safe_page, page_count, admin=self.admin
            ),
        )

    @discord.ui.button(label="Anterior", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, self.page - 1)

    @discord.ui.button(label="Próxima", emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, self.page + 1)


class DisciplineAdminView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    async def select_member(self, interaction: discord.Interaction, mode: str) -> None:
        rows = await discipline_candidates(get_bot(interaction), interaction.guild)
        if not rows:
            raise NotFoundError("Não há membros cadastrados elegíveis para esta ação.")
        await interaction.response.send_message(
            "Pesquise pelo nome e selecione um integrante do efetivo cadastrado:",
            view=DisciplineMemberSelectView(mode),
            ephemeral=True,
        )

    @discord.ui.button(label="Registrar ocorrência", emoji="📝", style=discord.ButtonStyle.primary)
    async def occurrence(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.select_member(interaction, "OCCURRENCE")

    @discord.ui.button(label="Aplicar advertência", emoji="⚠️", style=discord.ButtonStyle.secondary)
    async def warning(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.select_member(interaction, "WARNING")

    @discord.ui.button(label="Suspender membro", emoji="⏸️", style=discord.ButtonStyle.danger)
    async def suspension(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.select_member(interaction, "SUSPENSION")

    @discord.ui.button(label="Exonerar membro", emoji="🚪", style=discord.ButtonStyle.danger)
    async def exoneration(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await exoneration_candidates(get_bot(interaction), interaction.guild)
        if not rows:
            raise NotFoundError("Não há membros cadastrados elegíveis para exoneração.")
        await interaction.response.send_message(
            "Pesquise pelo nome e selecione somente um integrante do efetivo cadastrado:",
            view=ExonerationMemberSelectView(),
            ephemeral=True,
        )

    @discord.ui.button(label="Consultar histórico", emoji="📋", style=discord.ButtonStyle.secondary)
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.select_member(interaction, "HISTORY")

    @discord.ui.button(label="Ocorrências abertas", emoji="📂", style=discord.ButtonStyle.primary)
    async def occurrences(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await get_bot(interaction).services.discipline.open_occurrences(interaction.guild.id)
        if not rows:
            raise NotFoundError("Não há ocorrências abertas.")
        await interaction.response.send_message(
            "Selecione a ocorrência:", view=OpenOccurrenceSelectView(rows), ephemeral=True
        )

    @discord.ui.button(label="Gerenciar medidas", emoji="🛡️", style=discord.ButtonStyle.danger)
    async def measures(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.select_member(interaction, "MEASURES")


async def discipline_candidates(bot: ChoqueBot, guild: discord.Guild):
    rows = await bot.services.database.fetchall(
        """
        SELECT m.discord_id, m.mta_nick, m.status, r.name AS rank_name,
               r.level AS rank_level
        FROM members m
        LEFT JOIN ranks r ON r.id=m.rank_id
        WHERE m.guild_id=?
          AND m.status IN ('ACTIVE','AWAY','RESERVE','SUSPENDED')
          AND EXISTS (
              SELECT 1 FROM registration_gate_records g
              WHERE g.guild_id=m.guild_id AND g.discord_id=m.discord_id
                AND g.status='REGISTERED' AND g.member_id=m.id
          )
        ORDER BY COALESCE(r.level, 0) DESC, m.mta_nick COLLATE NOCASE
        """,
        (guild.id,),
    )
    return [
        dict(row)
        for row in rows
        if (member := guild.get_member(int(row["discord_id"]))) is not None and not member.bot
    ]


class DisciplineMemberSelect(discord.ui.UserSelect):
    def __init__(self, mode: str) -> None:
        self.mode = mode
        super().__init__(
            placeholder="Digite ou pesquise o nome do membro",
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        target_id = int(self.values[0].id)
        target = actor.guild.get_member(target_id)
        if not target:
            raise NotFoundError("O membro selecionado não está mais no servidor.")
        bot = get_bot(interaction)
        record = await bot.services.members.get(actor.guild.id, target.id)
        gate = await bot.services.registration_gate.status(actor.guild.id, target.id)
        if (
            target.bot
            or not record
            or str(record["status"]) not in {"ACTIVE", "AWAY", "RESERVE", "SUSPENDED"}
            or not gate
            or str(gate["status"]) != "REGISTERED"
            or int(gate["member_id"] or 0) != int(record["id"])
        ):
            raise NotFoundError("O membro não pertence ao efetivo cadastrado elegível.")
        if self.mode == "OCCURRENCE":
            await interaction.response.send_modal(OccurrenceModal(target.id))
        elif self.mode == "WARNING":
            await interaction.response.edit_message(
                content=f"Membro: {target.mention}\nSelecione o tipo da advertência:",
                view=WarningTypeView(target.id),
            )
        elif self.mode == "SUSPENSION":
            await interaction.response.send_modal(SuspensionModal(target.id))
        elif self.mode == "HISTORY":
            embed, pages, page = await build_history_embed(
                get_bot(interaction), actor.guild, target.id, 0
            )
            await interaction.response.edit_message(
                content=None,
                embed=embed,
                view=DisciplineHistoryView(actor.id, target.id, page, pages, admin=True),
            )
        else:
            rows = await get_bot(interaction).services.discipline.active_measures(
                actor.guild.id, target.id
            )
            if not rows:
                raise NotFoundError("Esse membro não possui medidas ativas ou agendadas.")
            await interaction.response.edit_message(
                content=f"Medidas de {target.mention}:", view=MeasureSelectView(rows)
            )


class DisciplineMemberSelectView(AdminView):
    def __init__(self, mode: str) -> None:
        super().__init__(timeout=300)
        self.add_item(DisciplineMemberSelect(mode))


async def exoneration_candidates(bot: ChoqueBot, guild: discord.Guild):
    rows = await bot.services.database.fetchall(
        """
        SELECT m.discord_id, m.mta_nick, m.status, r.name AS rank_name,
               r.level AS rank_level
        FROM members m
        LEFT JOIN ranks r ON r.id=m.rank_id
        WHERE m.guild_id=?
          AND m.status IN ('ACTIVE','AWAY','RESERVE','SUSPENDED')
          AND EXISTS (
              SELECT 1 FROM registration_gate_records g
              WHERE g.guild_id=m.guild_id AND g.discord_id=m.discord_id
                AND g.status='REGISTERED' AND g.member_id=m.id
          )
        ORDER BY COALESCE(r.level, 0) DESC, m.mta_nick COLLATE NOCASE
        """,
        (guild.id,),
    )
    return [
        row
        for row in rows
        if (member := guild.get_member(int(row["discord_id"]))) is not None and not member.bot
    ]


class ExonerationMemberSelect(discord.ui.UserSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Digite ou pesquise o nome do membro",
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        target_id = int(self.values[0].id)
        target = actor.guild.get_member(target_id)
        bot = get_bot(interaction)
        record = await bot.services.members.get(actor.guild.id, target_id)
        gate = await bot.services.registration_gate.status(actor.guild.id, target_id)
        if (
            not target
            or target.bot
            or not record
            or not gate
            or str(gate["status"]) != "REGISTERED"
            or int(gate["member_id"] or 0) != int(record["id"])
        ):
            raise NotFoundError("O membro selecionado não pertence ao efetivo cadastrado.")
        if str(record["status"]) not in {"ACTIVE", "AWAY", "RESERVE", "SUSPENDED"}:
            raise ConflictError("Este membro não está elegível para exoneração.")
        await interaction.response.edit_message(
            content=(
                f"**Confirmar exoneração de {target.mention}?**\n"
                "A pessoa permanecerá no servidor, perderá os cargos operacionais e receberá "
                "o cargo **Exonerado**. Esta ação exige motivo e confirmação literal."
            ),
            embed=None,
            view=ExonerationConfirmView(target.id),
        )


class ExonerationMemberSelectView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(ExonerationMemberSelect())


class ExonerationConfirmView(AdminView):
    def __init__(self, target_id: int) -> None:
        super().__init__(timeout=300)
        self.target_id = target_id

    @discord.ui.button(label="Confirmar exoneração", emoji="🚪", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ExonerationModal(self.target_id))

    @discord.ui.button(label="Cancelar", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content="Exoneração cancelada. Nenhuma alteração foi realizada.",
            embed=None,
            view=None,
        )


class ExonerationModal(ErrorModal, title="Confirmar exoneração"):
    reason = discord.ui.TextInput(
        label="Motivo obrigatório",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )
    confirmation = discord.ui.TextInput(
        label="Digite EXONERAR para confirmar",
        placeholder="EXONERAR",
        min_length=8,
        max_length=8,
    )

    def __init__(self, target_id: int) -> None:
        super().__init__()
        self.target_id = target_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        if str(self.confirmation).strip().upper() != "EXONERAR":
            raise ValidationError("Digite EXONERAR exatamente para confirmar.")
        bot = get_bot(interaction)
        target = actor.guild.get_member(self.target_id)
        record = await bot.services.members.get(actor.guild.id, self.target_id)
        if not target or target.bot or not record:
            raise NotFoundError("O membro selecionado não pertence ao efetivo cadastrado.")
        if str(record["status"]) not in {"ACTIVE", "AWAY", "RESERVE", "SUSPENDED"}:
            raise ConflictError("Este membro não está elegível para exoneração.")
        dismissed_role_id = await bot.services.settings.get(actor.guild.id, "dismissed_role_id")
        if not dismissed_role_id or not actor.guild.get_role(int(dismissed_role_id)):
            raise ValidationError("O cargo Exonerado ainda não foi configurado pela Administração.")

        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await bot.services.personnel.apply_punishment(
            actor.guild.id,
            target.id,
            PunishmentType.DISMISSAL,
            actor.id,
            str(self.reason),
        )
        await bot.services.shifts.finalize_role_loss(
            actor.guild.id,
            target.id,
            reason="EXONERATION_APPROVED",
        )
        warning = await sync_member_status_roles(
            bot,
            actor.guild,
            target,
            str(result["status"]),
        )
        suffix = f"\n⚠️ {warning}" if warning else ""
        await interaction.followup.send(
            f"✅ {target.mention} foi exonerado e permanece no servidor.{suffix}",
            ephemeral=True,
        )


class OccurrenceModal(ErrorModal, title="Registrar ocorrência"):
    description = discord.ui.TextInput(
        label="Descrição", style=discord.TextStyle.paragraph, min_length=3, max_length=1000
    )
    evidence = discord.ui.TextInput(label="Link da evidência", required=False, max_length=500)
    observation = discord.ui.TextInput(
        label="Observação", style=discord.TextStyle.paragraph, required=False, max_length=500
    )

    def __init__(self, target_id: int) -> None:
        super().__init__()
        self.target_id = target_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        result = await get_bot(interaction).services.discipline.create_occurrence(
            actor.guild.id,
            self.target_id,
            actor.id,
            str(self.description),
            evidence_url=str(self.evidence),
            observation=str(self.observation),
        )
        await interaction.response.send_message(
            f"✅ Ocorrência **#{result['occurrence_id']}** registrada sem punição automática.",
            ephemeral=True,
        )


class WarningTypeSelect(discord.ui.Select):
    def __init__(self, target_id: int, occurrence_id: int | None = None) -> None:
        self.target_id = target_id
        self.occurrence_id = occurrence_id
        super().__init__(
            placeholder="Tipo da advertência",
            options=[
                discord.SelectOption(label=value.title(), value=value) for value in WARNING_TYPES
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            WarningModal(self.target_id, self.values[0], self.occurrence_id)
        )


class WarningTypeView(AdminView):
    def __init__(self, target_id: int, occurrence_id: int | None = None) -> None:
        super().__init__(timeout=300)
        self.add_item(WarningTypeSelect(target_id, occurrence_id))


class WarningModal(ErrorModal, title="Dados da advertência"):
    duration = discord.ui.TextInput(
        label="Duração em dias", placeholder="30", min_length=1, max_length=4
    )
    reason = discord.ui.TextInput(
        label="Motivo", style=discord.TextStyle.paragraph, min_length=3, max_length=1000
    )
    evidence = discord.ui.TextInput(label="Link da evidência", required=False, max_length=500)
    observation = discord.ui.TextInput(
        label="Observação", style=discord.TextStyle.paragraph, required=False, max_length=500
    )

    def __init__(self, target_id: int, warning_type: str, occurrence_id: int | None) -> None:
        super().__init__()
        self.target_id = target_id
        self.warning_type = warning_type
        self.occurrence_id = occurrence_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        duration_text = str(self.duration).strip()
        if not duration_text.isdigit() or not 1 <= int(duration_text) <= 3650:
            raise ValidationError("A duração da ADV deve ficar entre 1 e 3650 dias.")
        duration_days = int(duration_text)
        target = actor.guild.get_member(self.target_id)
        if not target:
            raise NotFoundError("O membro não está mais no servidor.")
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title="⚠️ Confirmar advertência",
            description=(
                f"**Membro:** {target.mention}\n**Gravidade:** {self.warning_type}\n"
                f"**Duração:** {duration_days} dia(s)\n"
                f"**Motivo:** {self.reason}\n**Evidência:** {self.evidence or '—'}\n\n"
                "A medida só será gravada após a confirmação."
            ),
        )
        await interaction.response.send_message(
            embed=embed,
            view=WarningConfirmationView(
                actor.id,
                target.id,
                self.warning_type,
                duration_days,
                str(self.reason),
                str(self.evidence),
                str(self.observation),
                self.occurrence_id,
            ),
            ephemeral=True,
        )


class WarningConfirmationView(AdminView):
    def __init__(
        self,
        owner_id: int,
        target_id: int,
        warning_type: str,
        duration_days: int,
        reason: str,
        evidence: str,
        observation: str,
        occurrence_id: int | None,
    ) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.target_id = target_id
        self.warning_type = warning_type
        self.duration_days = duration_days
        self.reason = reason
        self.evidence = evidence
        self.observation = observation
        self.occurrence_id = occurrence_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Esta confirmação pertence a outro responsável.", ephemeral=True
            )
            return False
        return await super().interaction_check(interaction)

    @discord.ui.button(label="Confirmar advertência", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_admin(interaction)
        result = await get_bot(interaction).services.discipline.apply_warning(
            actor.guild.id,
            self.target_id,
            actor.id,
            self.warning_type,
            self.reason,
            duration_days=self.duration_days,
            evidence_url=self.evidence,
            observation=self.observation,
            occurrence_id=self.occurrence_id,
        )
        target = actor.guild.get_member(self.target_id)
        if target:
            try:
                await target.send(
                    f"Você recebeu uma ADV **{self.warning_type}** com duração de "
                    f"**{self.duration_days} dia(s)** no CHOQUE - BGR. Motivo: {self.reason}"
                )
            except discord.Forbidden:
                pass
        await interaction.response.edit_message(
            content=f"✅ Advertência **#{result['punishment_id']}** aplicada.",
            embed=None,
            view=None,
        )
        cog = get_bot(interaction).get_cog("DisciplineCommands")
        if isinstance(cog, DisciplineCommands):
            await cog.refresh_adv_dashboard(actor.guild)

    @discord.ui.button(label="Cancelar", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Ação cancelada.", embed=None, view=None)


class SuspensionModal(ErrorModal, title="Dados da suspensão"):
    start_date = discord.ui.TextInput(
        label="Início (DD/MM/AAAA)", placeholder="22/08/2026", max_length=10
    )
    duration = discord.ui.TextInput(label="Duração em dias", placeholder="7", max_length=3)
    reason = discord.ui.TextInput(
        label="Motivo", style=discord.TextStyle.paragraph, min_length=3, max_length=1000
    )
    observation = discord.ui.TextInput(
        label="Observação", style=discord.TextStyle.paragraph, required=False, max_length=500
    )
    evidence = discord.ui.TextInput(label="Link da evidência", required=False, max_length=500)

    def __init__(self, target_id: int) -> None:
        super().__init__()
        self.target_id = target_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        if not str(self.duration).strip().isdigit():
            raise ValidationError("Informe a duração numérica em dias.")
        timezone_name = await get_bot(interaction).services.settings.get(actor.guild.id, "timezone")
        try:
            starts = datetime.strptime(str(self.start_date).strip(), "%d/%m/%Y").replace(
                tzinfo=ZoneInfo(timezone_name)
            )
        except ValueError as exc:
            raise ValidationError("Use uma data válida no formato DD/MM/AAAA.") from exc
        target = actor.guild.get_member(self.target_id)
        if not target:
            raise NotFoundError("O membro não está mais no servidor.")
        starts_at = int(starts.timestamp() * 1000)
        duration_days = int(str(self.duration))
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title="⏸️ Confirmar suspensão",
            description=(
                f"**Membro:** {target.mention}\n**Início:** {discord_timestamp(starts_at, 'F')}\n"
                f"**Duração:** {duration_days} dia(s)\n**Motivo:** {self.reason}\n\n"
                "Ao entrar em vigor, o ponto será fechado, novos pontos serão bloqueados e "
                "o cargo de suspensão será sincronizado."
            ),
        )
        await interaction.response.send_message(
            embed=embed,
            view=SuspensionConfirmationView(
                actor.id,
                target.id,
                starts_at,
                duration_days,
                str(self.reason),
                str(self.observation),
                str(self.evidence),
            ),
            ephemeral=True,
        )


class SuspensionConfirmationView(AdminView):
    def __init__(
        self,
        owner_id: int,
        target_id: int,
        starts_at: int,
        duration_days: int,
        reason: str,
        observation: str,
        evidence: str,
    ) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.target_id = target_id
        self.starts_at = starts_at
        self.duration_days = duration_days
        self.reason = reason
        self.observation = observation
        self.evidence = evidence

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Esta confirmação pertence a outro responsável.", ephemeral=True
            )
            return False
        return await super().interaction_check(interaction)

    @discord.ui.button(label="Confirmar suspensão", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_admin(interaction)
        bot = get_bot(interaction)
        result = await bot.services.discipline.apply_suspension(
            actor.guild.id,
            self.target_id,
            actor.id,
            self.reason,
            starts_at=self.starts_at,
            duration_days=self.duration_days,
            observation=self.observation,
            evidence_url=self.evidence,
        )
        target = actor.guild.get_member(self.target_id)
        warning = None
        if target and result["status"] == "ACTIVE":
            warning = await sync_member_status_roles(
                bot, actor.guild, target, str(result["member_status"])
            )
        if target:
            try:
                await target.send(
                    f"Uma suspensão **#{result['punishment_id']}** foi "
                    f"{('aplicada' if result['status'] == 'ACTIVE' else 'agendada')} no "
                    f"CHOQUE - BGR. Motivo: {self.reason}"
                )
            except discord.Forbidden:
                pass
        suffix = f"\n⚠️ {warning}" if warning else ""
        await interaction.response.edit_message(
            content=(
                f"✅ Suspensão **#{result['punishment_id']}** registrada como "
                f"`{result['status']}`.{suffix}"
            ),
            embed=None,
            view=None,
        )

    @discord.ui.button(label="Cancelar", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Ação cancelada.", embed=None, view=None)


class OpenOccurrenceSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Escolha uma ocorrência aberta",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['mta_nick']}"[:100],
                    value=str(row["id"]),
                    description=str(row["description"])[:100],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        occurrence = await get_bot(interaction).services.discipline.get_occurrence(
            interaction.guild.id, int(self.values[0])
        )
        if not occurrence or occurrence["status"] != "OPEN":
            raise ConflictError("A ocorrência não está mais aberta.")
        evidence = (
            f"\n**Evidência:** [abrir link]({occurrence['evidence_url']})"
            if occurrence["evidence_url"]
            else ""
        )
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title=f"📝 Ocorrência #{occurrence['id']}",
            description=(
                f"**Membro:** <@{occurrence['discord_id']}>\n"
                f"**Descrição:** {occurrence['description']}\n"
                f"**Observação:** {occurrence['observation'] or '—'}{evidence}"
            ),
        )
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=OccurrenceDecisionView(int(occurrence["id"]), int(occurrence["discord_id"])),
        )


class OpenOccurrenceSelectView(AdminView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(OpenOccurrenceSelect(rows))


class OccurrenceDecisionView(AdminView):
    def __init__(self, occurrence_id: int, target_id: int) -> None:
        super().__init__(timeout=300)
        self.occurrence_id = occurrence_id
        self.target_id = target_id

    @discord.ui.button(label="Arquivar", emoji="📦", style=discord.ButtonStyle.secondary)
    async def archive(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ArchiveOccurrenceModal(self.occurrence_id))

    @discord.ui.button(
        label="Converter em advertência", emoji="⚠️", style=discord.ButtonStyle.danger
    )
    async def convert(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content="Selecione o tipo da advertência:",
            embed=None,
            view=WarningTypeView(self.target_id, self.occurrence_id),
        )


class ArchiveOccurrenceModal(ErrorModal, title="Arquivar ocorrência"):
    reason = discord.ui.TextInput(
        label="Motivo do arquivamento",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(self, occurrence_id: int) -> None:
        super().__init__()
        self.occurrence_id = occurrence_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        await get_bot(interaction).services.discipline.archive_occurrence(
            actor.guild.id, self.occurrence_id, actor.id, str(self.reason)
        )
        await interaction.response.send_message(
            f"✅ Ocorrência **#{self.occurrence_id}** arquivada.", ephemeral=True
        )


class MeasureSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Escolha a medida",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['punishment_type']} • {row['status']}"[:100],
                    value=str(row["id"]),
                    description=str(row["reason"])[:100],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        measure = await get_bot(interaction).services.discipline.get_measure(
            interaction.guild.id, int(self.values[0])
        )
        if not measure or measure["status"] not in {"SCHEDULED", "ACTIVE"}:
            raise ConflictError("A medida não está mais ativa.")
        await interaction.response.edit_message(
            content=(
                f"Medida **#{measure['id']} • {measure['punishment_type']}** "
                f"`{measure['status']}`\nMotivo: {measure['reason']}"
            ),
            view=MeasureActionView(int(measure["id"]), str(measure["punishment_type"])),
        )


class MeasureSelectView(AdminView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(MeasureSelect(rows))


class MeasureActionView(AdminView):
    def __init__(self, punishment_id: int, punishment_type: str) -> None:
        super().__init__(timeout=300)
        self.punishment_id = punishment_id
        self.punishment_type = punishment_type
        if punishment_type != "WARNING":
            self.remove_item(self.fulfill)

    @discord.ui.button(label="Marcar cumprida", emoji="✅", style=discord.ButtonStyle.success)
    async def fulfill(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(MeasureDecisionModal(self.punishment_id, "FULFILL"))

    @discord.ui.button(label="Revogar", emoji="↩️", style=discord.ButtonStyle.danger)
    async def revoke(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(MeasureDecisionModal(self.punishment_id, "REVOKE"))


class MeasureDecisionModal(ErrorModal, title="Decidir medida disciplinar"):
    reason = discord.ui.TextInput(
        label="Motivo da decisão",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(self, punishment_id: int, action: str) -> None:
        super().__init__()
        self.punishment_id = punishment_id
        self.action = action

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        bot = get_bot(interaction)
        if self.action == "FULFILL":
            result = await bot.services.discipline.fulfill_warning(
                actor.guild.id, self.punishment_id, actor.id, str(self.reason)
            )
            label = "cumprida"
        else:
            result = await bot.services.personnel.revoke_punishment(
                actor.guild.id, self.punishment_id, actor.id, str(self.reason)
            )
            label = "revogada"
            target = actor.guild.get_member(int(result["discord_id"]))
            if target:
                await sync_member_status_roles(
                    bot, actor.guild, target, str(result["member_status"])
                )
        await interaction.response.send_message(
            f"✅ Medida **#{self.punishment_id}** marcada como {label}.", ephemeral=True
        )
        cog = bot.get_cog("DisciplineCommands")
        if isinstance(cog, DisciplineCommands):
            await cog.refresh_adv_dashboard(actor.guild)


class DisciplineCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._panel_lock = asyncio.Lock()
        self._adv_panel_lock = asyncio.Lock()
        self._dismissed_reconciled: set[int] = set()
        self.bot.add_view(DisciplinePanelView())
        if not self.bot.check_mode:
            self.expire_adv_warnings.start()

    def cog_unload(self) -> None:
        self.expire_adv_warnings.cancel()

    async def publish_adv_dashboard(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        embeds = await build_adv_dashboard_embeds(self.bot, guild.id)
        async with self._adv_panel_lock:
            stored = await self.services.database.fetchall(
                """
                SELECT page_number, channel_id, message_id
                FROM discipline_adv_panel_pages WHERE guild_id=? ORDER BY page_number
                """,
                (guild.id,),
            )
            by_page = {int(row["page_number"]): row for row in stored}
            messages: list[discord.Message] = []
            for page_number, embed in enumerate(embeds, start=1):
                row = by_page.get(page_number)
                message = None
                if row and int(row["channel_id"]) == channel.id:
                    try:
                        message = await channel.fetch_message(int(row["message_id"]))
                        await message.edit(embed=embed, view=None)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        message = None
                elif row:
                    old_channel = guild.get_channel(int(row["channel_id"]))
                    if isinstance(old_channel, discord.TextChannel):
                        try:
                            old_message = await old_channel.fetch_message(int(row["message_id"]))
                            await old_message.edit(
                                embed=branded_embed(
                                    self.bot.config.branding,
                                    title="📋 Painel de ADVs transferido",
                                    description=f"Consulte o painel atual em {channel.mention}.",
                                ),
                                view=None,
                            )
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            pass
                if message is None:
                    message = await channel.send(embed=embed)
                messages.append(message)
                await self.services.database.execute(
                    """
                    INSERT INTO discipline_adv_panel_pages(
                        guild_id, page_number, channel_id, message_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, page_number) DO UPDATE SET
                        channel_id=excluded.channel_id,
                        message_id=excluded.message_id,
                        updated_at=excluded.updated_at
                    """,
                    (guild.id, page_number, channel.id, message.id, self.services.discipline.clock()),
                )
            for row in stored[len(embeds) :]:
                old_channel = guild.get_channel(int(row["channel_id"]))
                if isinstance(old_channel, discord.TextChannel):
                    try:
                        old_message = await old_channel.fetch_message(int(row["message_id"]))
                        await old_message.edit(
                            embed=branded_embed(
                                self.bot.config.branding,
                                title="📋 Página de ADV encerrada",
                                description="Esta página não é mais necessária. Consulte o painel ativo.",
                            ),
                            view=None,
                        )
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass
                await self.services.database.execute(
                    "DELETE FROM discipline_adv_panel_pages WHERE guild_id=? AND page_number=?",
                    (guild.id, int(row["page_number"])),
                )
            await self.services.settings.upsert_panel(
                guild.id, "ADV", channel.id, messages[0].id
            )
            if not messages[0].pinned:
                try:
                    await messages[0].pin(reason="Painel global de ADVs ativas")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            return messages[0]

    async def refresh_adv_dashboard(self, guild: discord.Guild) -> discord.Message | None:
        channel_id = await self.services.settings.get(guild.id, "discipline_adv_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return None
        return await self.publish_adv_dashboard(guild, channel)

    @tasks.loop(seconds=60)
    async def expire_adv_warnings(self) -> None:
        for guild in self.bot.guilds:
            try:
                expired = await self.services.discipline.expire_due_warnings(guild.id)
                if expired:
                    await self.refresh_adv_dashboard(guild)
            except Exception:
                LOGGER.exception("Falha ao expirar ADVs da guild %s", guild.id)

    @expire_adv_warnings.before_loop
    async def before_expire_adv_warnings(self) -> None:
        await self.bot.wait_until_ready()

    async def _reconcile_dismissed_members(self, guild: discord.Guild) -> None:
        if guild.id in self._dismissed_reconciled:
            return
        rows = await self.services.database.fetchall(
            "SELECT discord_id FROM members WHERE guild_id=? AND status='DISMISSED' ORDER BY id",
            (guild.id,),
        )
        for row in rows:
            discord_id = int(row["discord_id"])
            target = guild.get_member(discord_id)
            if target is None:
                try:
                    target = await guild.fetch_member(discord_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue
            if target.bot:
                continue
            warning = await sync_member_status_roles(
                self.bot,
                guild,
                target,
                "DISMISSED",
            )
            if warning:
                LOGGER.warning(
                    "Reconciliação da exoneração do membro %s na guild %s: %s",
                    discord_id,
                    guild.id,
                    warning,
                )
        self._dismissed_reconciled.add(guild.id)

    async def open_admin(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction)
        embed = branded_embed(
            self.bot.config.branding,
            title="⚖️ Gestão disciplinar",
            description=(
                "Registre fatos sem punição automática, aplique medidas com confirmação e "
                "consulte o histórico imutável do efetivo."
            ),
        )
        await interaction.response.send_message(
            embed=embed, view=DisciplineAdminView(), ephemeral=True
        )

    async def open_exoneration(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        rows = await exoneration_candidates(self.bot, actor.guild)
        if not rows:
            raise NotFoundError("Não há membros cadastrados elegíveis para exoneração.")
        await interaction.response.send_message(
            "Pesquise pelo nome e selecione somente um integrante do efetivo cadastrado:",
            view=ExonerationMemberSelectView(),
            ephemeral=True,
        )

    async def publish_or_refresh(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        embed = build_discipline_landing_embed(self.bot)
        view = DisciplinePanelView()
        async with self._panel_lock:
            panel = await self.services.settings.get_panel(guild.id, "DISCIPLINE")
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                    await message.edit(embed=embed, view=view)
                    return message
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            message = await channel.send(embed=embed, view=view)
            await self.services.settings.upsert_panel(
                guild.id, "DISCIPLINE", channel.id, message.id
            )
            return message

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            try:
                await self._reconcile_dismissed_members(guild)
            except Exception:
                LOGGER.exception(
                    "Falha ao reconciliar exonerações da guild %s",
                    guild.id,
                )
            channel_id = await self.services.settings.get(guild.id, "discipline_panel_channel_id")
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if isinstance(channel, discord.TextChannel):
                try:
                    await self.publish_or_refresh(guild, channel)
                except discord.DiscordException:
                    pass
            try:
                await self.refresh_adv_dashboard(guild)
            except Exception:
                LOGGER.exception("Falha ao restaurar o painel global de ADVs da guild %s", guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DisciplineCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
