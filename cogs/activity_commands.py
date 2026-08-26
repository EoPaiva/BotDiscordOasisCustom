from __future__ import annotations

import asyncio
import logging
import math
from typing import TYPE_CHECKING, cast

import discord
from discord.ext import commands, tasks

from choque.embeds import branded_embed
from choque.errors import NotFoundError, PermissionDenied, ValidationError
from choque.time_utils import discord_timestamp, format_duration
from cogs.config_ui import respond_error
from cogs.member_sync import sync_member_status_roles

DASHBOARD_PAGE_SIZE = 15
LOGGER = logging.getLogger(__name__)
STATUS_LABELS = {
    "FULFILLED": "✅ Cumprida",
    "NEAR": "⚠️ Próxima",
    "NOT_MET": "❌ Não cumprida",
    "EXEMPT": "🛡️ Isento",
}


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_member(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "ACTIVITY")
    if not await bot.services.permissions.has(interaction.user, "activity.view.self"):
        raise PermissionDenied("Você não possui permissão para consultar atividade.")
    return interaction.user


async def require_activity_admin(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "ACTIVITY")
    if not await bot.services.permissions.has(interaction.user, "activity.manage"):
        raise PermissionDenied("Você não possui permissão para gerenciar atividade.")
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
            await require_activity_admin(interaction)
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True


class ErrorModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await respond_error(interaction, error)


async def build_activity_landing_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    dashboard = await bot.services.activity.current_dashboard(guild.id)
    goal = int(await bot.services.settings.get(guild.id, "weekly_goal_minutes"))
    fulfilled = sum(row["activity_status"] == "FULFILLED" for row in dashboard)
    exempt = sum(row["activity_status"] == "EXEMPT" for row in dashboard)
    embed = branded_embed(
        bot.config.branding,
        title="📊 Atividade Semanal • CHOQUE - BGR",
        description=(
            "Acompanhe a meta e o histórico semanal. Os indicadores são informativos; "
            "nenhuma punição ou desligamento é aplicado automaticamente."
        ),
    )
    embed.add_field(name="Meta atual", value=f"**{format_duration(goal * 60_000)}**")
    embed.add_field(name="Cumpriram", value=f"**{fulfilled}**")
    embed.add_field(name="Isentos", value=f"**{exempt}**")
    return embed


async def build_member_activity_embed(
    bot: ChoqueBot, guild: discord.Guild, discord_id: int
) -> discord.Embed:
    row = await bot.services.activity.member_activity(guild.id, discord_id)
    goal_ms = int(row["goal_minutes"]) * 60_000
    progress = min(100, int(row["total_ms"]) * 100 // goal_ms) if goal_ms else 100
    embed = branded_embed(
        bot.config.branding,
        title=f"📊 Minha atividade • {row['mta_nick']}",
        description=f"<@{discord_id}> • {STATUS_LABELS[str(row['activity_status'])]}",
    )
    embed.add_field(name="Horas na semana", value=format_duration(int(row["total_ms"])))
    embed.add_field(name="Meta", value=format_duration(goal_ms))
    embed.add_field(name="Progresso", value=f"**{progress}%**")
    embed.add_field(
        name="Período",
        value=(
            f"{discord_timestamp(int(row['week_start_at']), 'd')} até "
            f"{discord_timestamp(int(row['week_end_at']), 'R')}"
        ),
        inline=False,
    )
    if row["exemption_reason"]:
        embed.add_field(
            name="Isenção",
            value=f"Motivo registrado: **{row['exemption_reason']}**",
            inline=False,
        )
    return embed


async def build_dashboard_embed(
    bot: ChoqueBot, guild: discord.Guild, page: int
) -> tuple[discord.Embed, int, int]:
    rows = await bot.services.activity.current_dashboard(guild.id)
    page_count = max(1, math.ceil(len(rows) / DASHBOARD_PAGE_SIZE))
    safe_page = min(max(page, 0), page_count - 1)
    visible = rows[safe_page * DASHBOARD_PAGE_SIZE : (safe_page + 1) * DASHBOARD_PAGE_SIZE]
    lines = [
        f"{STATUS_LABELS[str(row['activity_status'])].split()[0]} <@{row['discord_id']}> • "
        f"**{format_duration(int(row['total_ms']))}** / "
        f"{format_duration(int(row['goal_minutes']) * 60_000)}"
        + (f" • **{row['exemption_reason']}**" if row["exemption_reason"] else "")
        for row in visible
    ]
    embed = branded_embed(
        bot.config.branding,
        title="📊 Quadro de Atividade Semanal",
        description="\n".join(lines) or "Nenhum membro elegível encontrado.",
    )
    embed.set_footer(
        text=(
            f"{bot.config.branding.footer} • Página {safe_page + 1}/{page_count} • "
            "Indicadores não geram punição automática"
        )
    )
    return embed, page_count, safe_page


class ActivityPanelView(MemberView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Minha atividade",
        emoji="📊",
        style=discord.ButtonStyle.primary,
        custom_id="choque:activity:mine:v1",
    )
    async def mine(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        await interaction.response.send_message(
            embed=await build_member_activity_embed(get_bot(interaction), member.guild, member.id),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Quadro semanal",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:activity:board:v1",
    )
    async def board(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        embed, pages, page = await build_dashboard_embed(get_bot(interaction), member.guild, 0)
        await interaction.response.send_message(
            embed=embed,
            view=ActivityDashboardView(member.id, page, pages),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Meu histórico",
        emoji="📚",
        style=discord.ButtonStyle.success,
        custom_id="choque:activity:history:v1",
    )
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        rows = await get_bot(interaction).services.activity.snapshot_history(
            member.guild.id, member.id
        )
        lines = [
            f"{STATUS_LABELS[str(row['status'])].split()[0]} "
            f"{discord_timestamp(row['week_start_at'], 'd')} — "
            f"**{format_duration(row['total_ms'])}** / "
            f"{format_duration(row['goal_minutes'] * 60_000)} • **{row['status']}**"
            + (f" • **{row['exemption_reason']}**" if row["exemption_reason"] else "")
            for row in rows
        ]
        await interaction.response.send_message(
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title="📚 Histórico semanal",
                description="\n\n".join(lines) or "Nenhuma semana foi fechada ainda.",
            ),
            ephemeral=True,
        )


class ActivityDashboardView(MemberView):
    def __init__(self, owner_id: int, page: int, page_count: int) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.page = page
        self.page_count = page_count
        self.previous.disabled = page <= 0
        self.next.disabled = page >= page_count - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Este quadro foi aberto por outro usuário.", ephemeral=True
            )
            return False
        return await super().interaction_check(interaction)

    async def show(self, interaction: discord.Interaction, page: int) -> None:
        embed, pages, safe = await build_dashboard_embed(
            get_bot(interaction), interaction.guild, page
        )
        await interaction.response.edit_message(
            embed=embed, view=ActivityDashboardView(self.owner_id, safe, pages)
        )

    @discord.ui.button(label="Anterior", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, self.page - 1)

    @discord.ui.button(label="Próxima", emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, self.page + 1)


class ActivityAdminView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="Monitoramento", emoji="🔎", style=discord.ButtonStyle.primary)
    async def monitoring(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title="🔎 Monitoramento de Atividade",
                description=(
                    "Consulte as faixas abaixo. O monitoramento não aplica advertência, "
                    "suspensão ou desligamento automaticamente."
                ),
            ),
            view=ActivityMonitoringView(),
            ephemeral=True,
        )

    @discord.ui.button(label="Relatórios", emoji="📑", style=discord.ButtonStyle.secondary)
    async def reports(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title="📑 Relatórios",
                description="Escolha o relatório desejado pelos botões abaixo.",
            ),
            view=ReportsView(),
            ephemeral=True,
        )

    @discord.ui.button(label="Configurar regras", emoji="⚙️", style=discord.ButtonStyle.primary)
    async def rules(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_activity_admin(interaction)
        bot = get_bot(interaction)
        await interaction.response.send_modal(
            ActivityRulesModal(
                goal=int(await bot.services.settings.get(actor.guild.id, "weekly_goal_minutes")),
                near=int(
                    await bot.services.settings.get(actor.guild.id, "weekly_near_threshold_percent")
                ),
                low=int(await bot.services.settings.get(actor.guild.id, "low_activity_days")),
                no=int(await bot.services.settings.get(actor.guild.id, "no_activity_days")),
            )
        )

    @discord.ui.button(
        label="Fechar semanas pendentes", emoji="🗓️", style=discord.ButtonStyle.danger
    )
    async def close_weeks(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_activity_admin(interaction)
        closed = await get_bot(interaction).services.activity.close_completed_weeks(
            actor.guild.id, actor_id=actor.id
        )
        members = sum(row["members"] for row in closed)
        await interaction.response.send_message(
            (
                f"✅ **{len(closed)}** semana(s) fechada(s), com **{members}** snapshot(s)."
                if closed
                else "✅ Não existem semanas pendentes; os snapshots já estão atualizados."
            ),
            ephemeral=True,
        )


class ActivityMonitoringView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    async def show(self, interaction: discord.Interaction, bucket: str) -> None:
        rows = await get_bot(interaction).services.activity.inactivity(interaction.guild.id, bucket)
        labels = {
            "NORMAL": "✅ Atividade normal",
            "LOW": "⚠️ Baixa atividade",
            "NONE": "❌ Sem atividade",
        }
        lines = [
            f"<@{row['discord_id']}> • **{row['days_inactive']} dia(s)** sem atividade • "
            f"**{row['status']}**"
            for row in rows[:25]
        ]
        await interaction.response.send_message(
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title=labels[bucket],
                description="\n".join(lines) or "Nenhum membro nesta faixa.",
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Atividade normal", emoji="✅", style=discord.ButtonStyle.success)
    async def normal(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, "NORMAL")

    @discord.ui.button(label="Baixa atividade", emoji="⚠️", style=discord.ButtonStyle.primary)
    async def low(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, "LOW")

    @discord.ui.button(label="Sem atividade", emoji="❌", style=discord.ButtonStyle.danger)
    async def none(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, "NONE")


class ActivityRulesModal(ErrorModal, title="Regras de atividade"):
    goal = discord.ui.TextInput(label="Meta semanal em minutos", max_length=5)
    near = discord.ui.TextInput(label="Percentual para status Próxima", max_length=2)
    low = discord.ui.TextInput(label="Dias para baixa atividade", max_length=3)
    no = discord.ui.TextInput(label="Dias para sem atividade", max_length=3)

    def __init__(self, *, goal: int, near: int, low: int, no: int) -> None:
        super().__init__()
        self.goal.default = str(goal)
        self.near.default = str(near)
        self.low.default = str(low)
        self.no.default = str(no)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_activity_admin(interaction)
        values = (str(self.goal), str(self.near), str(self.low), str(self.no))
        if not all(value.strip().isdigit() for value in values):
            raise ValidationError("Todos os campos precisam ser números inteiros.")
        result = await get_bot(interaction).services.activity.set_rules(
            actor.guild.id,
            actor.id,
            goal_minutes=int(values[0]),
            near_percent=int(values[1]),
            low_days=int(values[2]),
            no_days=int(values[3]),
        )
        await interaction.response.send_message(
            (
                "✅ Regras atualizadas: meta **{weekly_goal_minutes} min**, próxima em "
                "**{weekly_near_threshold_percent}%**, baixa em **{low_activity_days} dias** "
                "e sem atividade em **{no_activity_days} dias**."
            ).format(**result),
            ephemeral=True,
        )


def period_report_embed(bot: ChoqueBot, title: str, row: dict[str, object]) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title=f"📑 {title}",
        description=(
            f"**Período:** {discord_timestamp(int(row['start_at']), 'd')} até agora\n"
            f"**Membros que trabalharam:** {row['members_worked']}\n"
            f"**Horas realizadas:** {format_duration(int(row['total_ms']))}\n"
            f"**Pontos abertos:** {row['open_points']}\n"
            f"**Ausências ativas:** {row['active_absences']}\n"
            f"**Treinamentos:** {row['trainings']}"
        ),
    )


class ReportsView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="Diário", emoji="📅", style=discord.ButtonStyle.primary)
    async def daily(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await get_bot(interaction).services.activity.daily_report(interaction.guild.id)
        await interaction.response.send_message(
            embed=period_report_embed(get_bot(interaction), "Relatório Diário", row), ephemeral=True
        )

    @discord.ui.button(label="Semanal", emoji="🗓️", style=discord.ButtonStyle.primary)
    async def weekly(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await get_bot(interaction).services.activity.weekly_report(interaction.guild.id)
        statuses = row["statuses"]
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title="📑 Relatório Semanal",
            description=(
                f"**Período:** {discord_timestamp(row['start_at'], 'd')} até agora\n"
                f"**Horas totais:** {format_duration(row['total_ms'])}\n"
                f"**Média por membro:** {format_duration(row['average_ms'])}\n"
                f"**Meta:** {format_duration(row['goal_minutes'] * 60_000)}\n\n"
                f"✅ Cumpriram: **{statuses['FULFILLED']}**\n"
                f"⚠️ Próximos: **{statuses['NEAR']}**\n"
                f"❌ Abaixo: **{statuses['NOT_MET']}**\n"
                f"🛡️ Isentos: **{statuses['EXEMPT']}**\n\n"
                f"Novos membros: **{row['new_members']}** • Promoções: **{row['promotions']}**\n"
                f"Advertências: **{row['warnings']}** • Treinamentos: **{row['trainings']}**"
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Mensal", emoji="📆", style=discord.ButtonStyle.secondary)
    async def monthly(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await get_bot(interaction).services.activity.monthly_report(interaction.guild.id)
        await interaction.response.send_message(
            embed=period_report_embed(get_bot(interaction), "Relatório Mensal", row), ephemeral=True
        )

    @discord.ui.button(label="Membro", emoji="👤", style=discord.ButtonStyle.secondary)
    async def member(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "Selecione o membro:", view=ReportMemberSelectView(), ephemeral=True
        )

    @discord.ui.button(label="Pontos", emoji="⏱️", style=discord.ButtonStyle.secondary)
    async def points(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await get_bot(interaction).services.activity.points_report(interaction.guild.id)
        await interaction.response.send_message(
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title="⏱️ Relatório de Pontos",
                description=(
                    f"🟢 Ativos: **{row['active']}**\n🟡 Em tolerância: **{row['grace']}**\n"
                    f"⚠️ Em revisão: **{row['review']}**\n✅ Encerrados: **{row['closed']}**\n"
                    f"🎯 Válidos: **{row['valid']}**\n❌ Invalidados: **{row['invalidated']}**"
                ),
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Ausências", emoji="💤", style=discord.ButtonStyle.primary)
    async def absences(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await get_bot(interaction).services.activity.absences_report(interaction.guild.id)
        lines = [
            f"<@{row['discord_id']}> • **{row['status']}** • "
            f"{discord_timestamp(row['starts_at'], 'd')} → {discord_timestamp(row['ends_at'], 'd')}"
            for row in rows
        ]
        await interaction.response.send_message(
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title="💤 Relatório de Ausências",
                description="\n".join(lines) or "Nenhuma ausência ativa ou pendente.",
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Treinamentos", emoji="🎓", style=discord.ButtonStyle.success)
    async def trainings(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await get_bot(interaction).services.activity.trainings_report(interaction.guild.id)
        lines = [
            f"**#{row['id']} • {row['name']}** **{row['status']}** • "
            f"{discord_timestamp(row['scheduled_at'], 'f')} • **{row['participants']}** participante(s)"
            for row in rows
        ]
        await interaction.response.send_message(
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title="🎓 Relatório de Treinamentos",
                description="\n\n".join(lines) or "Nenhum treinamento registrado.",
            ),
            ephemeral=True,
        )


class ReportMemberSelect(discord.ui.UserSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Escolha um membro", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        target = interaction.guild.get_member(self.values[0].id)
        if not target:
            raise NotFoundError("O membro não está mais no servidor.")
        row = await get_bot(interaction).services.activity.member_report(
            interaction.guild.id, target.id
        )
        member = row["member"]
        last_service = (
            discord_timestamp(int(row["last_service"]), "d") if row["last_service"] else "Nunca"
        )
        await interaction.response.edit_message(
            content=None,
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title=f"👤 Relatório • {member['mta_nick']}",
                description=(
                    f"{target.mention} • {member['rank_name'] or 'Sem patente'} • "
                    f"**{member['status']}**\n\n"
                    f"**Horas semana:** {format_duration(row['week_ms'])}\n"
                    f"**Horas mês:** {format_duration(row['month_ms'])}\n"
                    f"**Horas total:** {format_duration(row['total_ms'])}\n"
                    f"**Serviços realizados:** {row['shifts']}\n"
                    f"**Último serviço:** {last_service}\n"
                    f"**Advertências ativas:** {row['active_warnings']}\n"
                    f"**Treinamentos concluídos:** {row['trainings_completed']}"
                ),
            ),
            view=None,
        )


class ReportMemberSelectView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(ReportMemberSelect())


async def require_absence_alert_responsible(
    interaction: discord.Interaction,
    alert_id: int,
    source_guild_id: int | None = None,
) -> tuple[discord.Member, object, int]:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este controle dentro do servidor.")
    bot = get_bot(interaction)
    actor = interaction.user
    source_id = int(source_guild_id or actor.guild.id)
    if source_id == actor.guild.id:
        actor = await require_activity_admin(interaction)
    else:
        linked_source = await bot.services.settings.get(
            actor.guild.id, "identity_source_guild_id"
        )
        if not linked_source or int(linked_source) != source_id:
            raise PermissionDenied("Este servidor não administra esse cadastro de pessoal.")
        configured_roles = await bot.services.settings.get(
            actor.guild.id, "activity_absence_alert_manager_role_ids", []
        )
        allowed = {
            int(role_id)
            for role_id in configured_roles
            if str(role_id).isdigit()
        }
        is_owner = actor.id == actor.guild.owner_id
        is_admin = actor.guild_permissions.administrator
        if not (is_owner or is_admin or any(role.id in allowed for role in actor.roles)):
            raise PermissionDenied(
                "Somente a equipe autorizada do REC pode decidir este alerta."
            )
    alert = await bot.services.activity.get_absence_alert(source_id, alert_id)
    if alert is None:
        raise NotFoundError("Alerta de ausência não encontrado.")
    unit_code = str(alert["unit_code"] or "").strip()
    if (
        source_id == actor.guild.id
        and unit_code
        and not await bot.services.permissions.has(actor, "settings.manage")
    ):
        resource = await bot.services.database.fetchone(
            """
            SELECT assistant_role_id, command_role_id
            FROM special_unit_guild_resources
            WHERE guild_id=? AND unit_code=?
            """,
            (actor.guild.id, unit_code),
        )
        allowed = {
            int(value)
            for value in (
                resource["assistant_role_id"] if resource else None,
                resource["command_role_id"] if resource else None,
            )
            if value
        }
        if allowed and not any(role.id in allowed for role in actor.roles):
            raise PermissionDenied("Somente os responsáveis desta unidade podem alterar o alerta.")
    return actor, alert, source_id


class DisableAbsenceAlertModal(ErrorModal, title="Desativar alertas do membro"):
    reason = discord.ui.TextInput(
        label="Motivo (opcional)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, alert_id: int, source_guild_id: int | None = None) -> None:
        super().__init__()
        self.alert_id = alert_id
        self.source_guild_id = source_guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor, _, source_id = await require_absence_alert_responsible(
            interaction, self.alert_id, self.source_guild_id
        )
        result = await get_bot(interaction).services.activity.disable_member_absence_alerts(
            source_id, self.alert_id, actor.id, str(self.reason)
        )
        await interaction.response.send_message(
            f"🔕 Alertas desativados para <@{result['discord_id']}> por <@{actor.id}>.",
            ephemeral=True,
        )
        if interaction.message:
            await interaction.message.edit(view=None)


class JustifiedAbsenceModal(ErrorModal, title="Registrar ausência justificada"):
    days = discord.ui.TextInput(
        label="Duração em dias",
        placeholder="Ex.: 7",
        min_length=1,
        max_length=3,
    )
    reason = discord.ui.TextInput(
        label="Motivo",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(self, alert_id: int, source_guild_id: int | None = None) -> None:
        super().__init__()
        self.alert_id = alert_id
        self.source_guild_id = source_guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor, alert, source_id = await require_absence_alert_responsible(
            interaction, self.alert_id, self.source_guild_id
        )
        raw_days = str(self.days).strip()
        if not raw_days.isdigit() or not 1 <= int(raw_days) <= 366:
            raise ValidationError("A duração deve ficar entre 1 e 366 dias.")
        now = get_bot(interaction).services.activity.clock()
        result = await get_bot(interaction).services.personnel.register_justified_absence(
            source_id,
            int(alert["discord_id"]),
            now,
            now + int(raw_days) * 86_400_000,
            actor.id,
            str(self.reason),
        )
        await interaction.response.send_message(
            f"✅ Ausência justificada **#{result['absence_id']}** registrada para "
            f"<@{result['discord_id']}>.",
            ephemeral=True,
        )
        if interaction.message:
            await interaction.message.edit(view=None)


class DismissInactiveMemberModal(ErrorModal, title="Desligar por inatividade"):
    confirmation = discord.ui.TextInput(
        label="Digite DESLIGAR para confirmar",
        placeholder="DESLIGAR",
        min_length=8,
        max_length=8,
    )
    reason = discord.ui.TextInput(
        label="Motivo do desligamento",
        placeholder="Ex.: desligamento por inatividade prolongada.",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(self, source_guild_id: int, alert_id: int) -> None:
        super().__init__()
        self.source_guild_id = source_guild_id
        self.alert_id = alert_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if str(self.confirmation).strip().upper() != "DESLIGAR":
            raise ValidationError("Confirmação inválida; digite DESLIGAR.")
        actor, _, source_id = await require_absence_alert_responsible(
            interaction, self.alert_id, self.source_guild_id
        )
        await interaction.response.defer(ephemeral=True, thinking=True)
        bot = get_bot(interaction)
        result = await bot.services.activity.dismiss_member_for_absence_alert(
            source_id,
            actor.guild.id,
            self.alert_id,
            actor.id,
            str(self.reason),
        )

        warnings: list[str] = []
        for guild_id in {source_id, actor.guild.id}:
            guild = bot.get_guild(guild_id)
            if guild is None:
                warnings.append(f"servidor `{guild_id}` indisponível para sincronização")
                continue
            target = guild.get_member(int(result["discord_id"]))
            if target is None:
                try:
                    target = await guild.fetch_member(int(result["discord_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    target = None
            if target is None:
                continue
            warning = await sync_member_status_roles(bot, guild, target, "DISMISSED")
            if warning:
                warnings.append(warning)

        if interaction.message:
            embed = discord.Embed(
                title="⚫ DESLIGADO POR INATIVIDADE",
                description=(
                    f"<@{result['discord_id']}> foi desligado do cadastro principal e do "
                    f"espelho REC por <@{actor.id}>.\n\n"
                    f"**Motivo:** {str(self.reason).strip()}"
                ),
                color=0x4F545C,
            )
            await interaction.message.edit(embed=embed, view=None)
        suffix = f"\n⚠️ {' '.join(warnings)}" if warnings else ""
        repeated = " O desligamento já havia sido concluído." if result["already_completed"] else ""
        await interaction.followup.send(
            f"✅ Desligamento por inatividade concluído.{repeated}{suffix}",
            ephemeral=True,
        )


class DisableAbsenceAlertButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"^choque:activity:absence:(?P<alert_id>[0-9]+):disable:v1$",
):
    def __init__(self, alert_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Desativar alertas",
                emoji="🔕",
                style=discord.ButtonStyle.secondary,
                custom_id=f"choque:activity:absence:{alert_id}:disable:v1",
            )
        )
        self.alert_id = alert_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["alert_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(DisableAbsenceAlertModal(self.alert_id))


class JustifiedAbsenceButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"^choque:activity:absence:(?P<alert_id>[0-9]+):justify:v1$",
):
    def __init__(self, alert_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Registrar ausência justificada",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"choque:activity:absence:{alert_id}:justify:v1",
            )
        )
        self.alert_id = alert_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["alert_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(JustifiedAbsenceModal(self.alert_id))


class DisableAbsenceAlertButtonV2(
    discord.ui.DynamicItem[discord.ui.Button],
    template=(
        r"^choque:activity:absence:(?P<source_id>[0-9]+):"
        r"(?P<alert_id>[0-9]+):disable:v2$"
    ),
):
    def __init__(self, source_guild_id: int, alert_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Desativar alertas",
                emoji="🔕",
                style=discord.ButtonStyle.secondary,
                custom_id=(
                    f"choque:activity:absence:{source_guild_id}:{alert_id}:disable:v2"
                ),
            )
        )
        self.source_guild_id = source_guild_id
        self.alert_id = alert_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["source_id"]), int(match["alert_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            DisableAbsenceAlertModal(self.alert_id, self.source_guild_id)
        )


class JustifiedAbsenceButtonV2(
    discord.ui.DynamicItem[discord.ui.Button],
    template=(
        r"^choque:activity:absence:(?P<source_id>[0-9]+):"
        r"(?P<alert_id>[0-9]+):justify:v2$"
    ),
):
    def __init__(self, source_guild_id: int, alert_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Registrar ausência justificada",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=(
                    f"choque:activity:absence:{source_guild_id}:{alert_id}:justify:v2"
                ),
            )
        )
        self.source_guild_id = source_guild_id
        self.alert_id = alert_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["source_id"]), int(match["alert_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            JustifiedAbsenceModal(self.alert_id, self.source_guild_id)
        )


class DismissInactiveMemberButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=(
        r"^choque:activity:absence:(?P<source_id>[0-9]+):"
        r"(?P<alert_id>[0-9]+):dismiss:v1$"
    ),
):
    def __init__(self, source_guild_id: int, alert_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Desligar por inatividade",
                emoji="🚫",
                style=discord.ButtonStyle.danger,
                custom_id=(
                    f"choque:activity:absence:{source_guild_id}:{alert_id}:dismiss:v1"
                ),
            )
        )
        self.source_guild_id = source_guild_id
        self.alert_id = alert_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["source_id"]), int(match["alert_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            DismissInactiveMemberModal(self.source_guild_id, self.alert_id)
        )


class AbsenceAlertView(ErrorView):
    def __init__(self, source_guild_id: int, alert_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(DisableAbsenceAlertButtonV2(source_guild_id, alert_id))
        self.add_item(JustifiedAbsenceButtonV2(source_guild_id, alert_id))
        self.add_item(DismissInactiveMemberButton(source_guild_id, alert_id))


class ActivityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._panel_lock = asyncio.Lock()
        self.bot.add_view(ActivityPanelView())
        self.bot.add_dynamic_items(
            DisableAbsenceAlertButton,
            JustifiedAbsenceButton,
            DisableAbsenceAlertButtonV2,
            JustifiedAbsenceButtonV2,
            DismissInactiveMemberButton,
        )

    async def open_admin(self, interaction: discord.Interaction) -> None:
        await require_activity_admin(interaction)
        await interaction.response.send_message(
            embed=branded_embed(
                self.bot.config.branding,
                title="📊 Gestão de Atividade",
                description=(
                    "Acompanhe metas, inatividade e relatórios. Os dados apoiam decisões humanas; "
                    "o módulo não pune ou desliga membros automaticamente."
                ),
            ),
            view=ActivityAdminView(),
            ephemeral=True,
        )

    async def publish_or_refresh(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        async with self._panel_lock:
            embed = await build_activity_landing_embed(self.bot, guild)
            panel = await self.services.settings.get_panel(guild.id, "ACTIVITY")
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                    await message.edit(embed=embed, view=ActivityPanelView())
                    return message
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            message = await channel.send(embed=embed, view=ActivityPanelView())
            await self.services.settings.upsert_panel(guild.id, "ACTIVITY", channel.id, message.id)
            return message

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            channel_id = await self.services.settings.get(guild.id, "activity_panel_channel_id")
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if isinstance(channel, discord.TextChannel):
                try:
                    await self.publish_or_refresh(guild, channel)
                except Exception:
                    LOGGER.exception("Falha ao restaurar painel de atividade da guild %s", guild.id)
        if not self.weekly_close_loop.is_running():
            self.weekly_close_loop.start()

    @tasks.loop(minutes=30)
    async def weekly_close_loop(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.services.activity.close_completed_weeks(guild.id)
                await self.deliver_absence_alerts(guild)
            except Exception:
                LOGGER.exception("Falha no fechamento semanal da guild %s", guild.id)

    async def deliver_absence_alerts(self, guild: discord.Guild) -> int:
        delivered = 0
        labels = {
            3: ("🟡 BAIXA ATIVIDADE", 0xE0B341),
            7: ("🟠 AUSÊNCIA DETECTADA", 0xE67E22),
            10: ("🔴 AUSÊNCIA PROLONGADA", 0xC0392B),
        }
        for alert in await self.services.activity.scan_absence_alerts(guild.id):
            unit_code = str(alert["unit_code"] or "").strip()
            destination_guild_id = await self.services.settings.get(
                guild.id, "activity_absence_alert_destination_guild_id"
            )
            destination_channel_id = await self.services.settings.get(
                guild.id, "activity_absence_alert_channel_id"
            )
            destination_guild = (
                self.bot.get_guild(int(destination_guild_id))
                if destination_guild_id
                else guild
            )
            if destination_guild is None:
                continue
            resource = (
                await self.services.database.fetchone(
                    """
                    SELECT * FROM special_unit_guild_resources
                    WHERE guild_id=? AND unit_code=?
                    """,
                    (guild.id, unit_code),
                )
                if unit_code
                else None
            )
            channel_id = destination_channel_id or (
                int(resource["central_channel_id"])
                if resource and resource["central_channel_id"]
                else await self.services.settings.get(guild.id, "personnel_admin_channel_id")
            )
            channel = (
                destination_guild.get_channel(int(channel_id)) if channel_id else None
            )
            if not isinstance(channel, discord.TextChannel):
                continue
            threshold = int(alert["threshold_days"])
            title, color = labels[threshold]
            embed = discord.Embed(
                title=title,
                description=(
                    f"O membro <@{alert['discord_id']}> está há **{threshold} dias** "
                    "sem atividade registrada na corporação.\n\n"
                    f"**Última atividade:** {discord_timestamp(int(alert['cycle_started_at']), 'd')}\n"
                    f"**Unidade:** `{unit_code or 'GERAL'}`\n\n"
                    "O aviso não aplica punição automaticamente. A decisão de desligar "
                    "exige confirmação humana e é registrada no cadastro principal."
                ),
                color=color,
            )
            role_mentions: list[str] = []
            if destination_guild.id != guild.id:
                manager_role_ids = await self.services.settings.get(
                    destination_guild.id,
                    "activity_absence_alert_manager_role_ids",
                    [],
                )
                role_mentions.extend(
                    f"<@&{int(role_id)}>"
                    for role_id in manager_role_ids
                    if str(role_id).isdigit()
                )
            elif resource:
                for key in ("command_role_id", "assistant_role_id"):
                    if resource[key]:
                        role_mentions.append(f"<@&{int(resource[key])}>")
            message = await channel.send(
                content=" ".join(role_mentions) or None,
                embed=embed,
                view=AbsenceAlertView(guild.id, int(alert["id"])),
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
            await self.services.activity.mark_absence_alert_delivered(
                guild.id, int(alert["id"]), channel.id, message.id
            )
            delivered += 1
        return delivered

    @weekly_close_loop.before_loop
    async def before_weekly_close_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def cog_unload(self) -> None:
        self.weekly_close_loop.cancel()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ActivityCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
