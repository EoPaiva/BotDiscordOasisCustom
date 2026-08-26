from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import TYPE_CHECKING, cast

import discord
from discord.ext import commands, tasks

from choque.dismissals import dismissal_public_reason
from choque.embeds import branded_embed
from choque.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from choque.models import PersonnelActionType
from choque.time_utils import discord_timestamp, format_duration, period_bounds
from cogs.config_ui import respond_error
from cogs.member_sync import sync_rank_to_discord

LOGGER = logging.getLogger(__name__)
HISTORY_PAGE_SIZE = 10


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_member(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "CAREER")
    if not await bot.services.permissions.has(interaction.user, "career.view.self"):
        raise PermissionDenied("Você não possui permissão para consultar a carreira.")
    return interaction.user


async def require_career_admin(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "CAREER")
    if not await bot.services.permissions.has(interaction.user, "career.manage"):
        raise PermissionDenied("Você não possui permissão para administrar carreiras.")
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
            await require_career_admin(interaction)
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True


class ErrorModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await respond_error(interaction, error)


def build_career_landing_embed(bot: ChoqueBot) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title="📈 Carreira • CHOQUE - BGR",
        description=(
            "Consulte sua patente, horas válidas, próximo objetivo, méritos e histórico. "
            "A progressão por horas vai somente de Recruta a Cadete; depois disso, "
            "méritos e movimentações continuam sob decisão humana."
        ),
    )


async def build_career_profile_embed(
    bot: ChoqueBot, guild: discord.Guild, discord_id: int
) -> discord.Embed:
    summary = await bot.services.career.career_summary(guild.id, discord_id)
    profile = summary["profile"]
    timezone_name = await bot.services.settings.get(guild.id, "timezone")
    month_start, month_end = period_bounds("month", timezone_name)
    month_ms = await bot.services.shifts.total_for_member(
        guild.id, discord_id, month_start, month_end
    )
    embed = branded_embed(
        bot.config.branding,
        title=f"📈 Carreira • {profile['mta_nick']}",
        description=f"<@{discord_id}> • status `{profile['status']}`",
    )
    embed.add_field(name="Patente atual", value=profile["rank_name"] or "Não definida")
    embed.add_field(
        name="Tempo na patente",
        value=discord_timestamp(int(profile["rank_since"]), "R"),
    )
    embed.add_field(name="Ingresso", value=discord_timestamp(int(profile["joined_at"]), "d"))
    embed.add_field(name="Horas no mês", value=format_duration(month_ms))
    embed.add_field(name="Advertências ativas", value=str(profile["active_warnings"]))
    embed.add_field(name="Unidade", value=profile["unit"] or "—")
    progression = summary["next_progression"]
    if progression:
        remaining = max(0, int(progression["target_total_ms"]) - int(summary["valid_hours_ms"]))
        embed.add_field(
            name="Próximo objetivo automático",
            value=(
                f"**{progression['next_rank_name']}** • "
                f"{format_duration(summary['valid_hours_ms'])}/"
                f"{format_duration(progression['target_total_ms'])}\n"
                f"Faltam {format_duration(remaining)} e a permanência mínima da etapa."
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name="Progressão automática",
            value="Ciclo concluído em Cadete ou carreira sujeita somente à decisão humana.",
            inline=False,
        )
    merit = summary["merit"]
    embed.add_field(
        name="Méritos após Cadete",
        value=(
            f"{merit['total']} registro(s) • +{merit['positive_weight']} / "
            f"-{merit['negative_weight']} pontos de peso"
        ),
    )
    officer = summary["officer_eligibility"]
    embed.add_field(
        name="Oficialato",
        value=(
            "Elegível para iniciar no site."
            if officer["eligible"]
            else "Pendente: " + ", ".join(officer["missing"])
        ),
    )
    embed.add_field(
        name="Limite da automação",
        value=(
            "O sistema nunca ultrapassa Cadete sozinho, nunca transforma mérito em patente "
            "e nunca decide uma candidatura ao oficialato."
        ),
        inline=False,
    )
    return embed


async def build_history_embed(
    bot: ChoqueBot,
    guild: discord.Guild,
    discord_id: int,
    page: int,
) -> tuple[discord.Embed, int]:
    total = await bot.services.personnel.career_history_count(guild.id, discord_id)
    page_count = max(1, math.ceil(total / HISTORY_PAGE_SIZE))
    safe_page = min(max(page, 0), page_count - 1)
    rows = await bot.services.personnel.career_history(
        guild.id,
        discord_id,
        limit=HISTORY_PAGE_SIZE,
        offset=safe_page * HISTORY_PAGE_SIZE,
    )
    lines = [
        (
            f"**#{row['id']} • {row['action_type']}**\n"
            f"{row['from_rank_name'] or 'Sem patente'} → "
            f"**{row['to_rank_name'] or 'Sem patente'}**\n"
            f"Responsável: "
            f"{'<@' + str(row['actor_id']) + '>' if row['actor_id'] else 'Sistema/Discord'} • "
            f"{discord_timestamp(row['created_at'], 'R')}\n"
            f"Origem: `{row['source']}` • Motivo: {row['reason']}"
        )
        for row in rows
    ]
    embed = branded_embed(
        bot.config.branding,
        title="📋 Histórico de carreira",
        description="\n\n".join(lines) or "Nenhuma movimentação de carreira registrada.",
    )
    embed.set_footer(
        text=f"Página {safe_page + 1}/{page_count} • {total} movimentação(ões) • {bot.config.branding.footer}"
    )
    return embed, page_count


class CareerPanelView(MemberView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Minha carreira",
        emoji="👤",
        style=discord.ButtonStyle.primary,
        custom_id="choque:career:profile:v1",
    )
    async def profile(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        await interaction.response.send_message(
            embed=await build_career_profile_embed(get_bot(interaction), member.guild, member.id),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Meu histórico",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:career:history:v1",
    )
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        embed, page_count = await build_history_embed(
            get_bot(interaction), member.guild, member.id, 0
        )
        await interaction.response.send_message(
            embed=embed,
            view=CareerHistoryView(member.id, member.id, 0, page_count, admin=False),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Hierarquia",
        emoji="🎖️",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:career:hierarchy:v1",
    )
    async def hierarchy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        cog = get_bot(interaction).get_cog("HierarchyCommands")
        if not cog:
            raise NotFoundError("O painel de hierarquia não está disponível.")
        await interaction.response.send_message(
            embed=await cog.build_embed(member.guild.id), ephemeral=True
        )

    @discord.ui.button(
        label="Candidatura oficial",
        emoji="🛡️",
        style=discord.ButtonStyle.success,
        custom_id="choque:career:officer:v1",
    )
    async def officer(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        bot = get_bot(interaction)
        eligibility = await bot.services.career.officer_eligibility(member.guild.id, member.id)
        url = str(
            await bot.services.settings.get(
                member.guild.id,
                "officer_public_url",
                "https://choquebgr.online/candidatura-oficial",
            )
        )
        embed = branded_embed(
            bot.config.branding,
            title="🛡️ Candidatura ao Oficialato",
            description=(
                "Você atende aos requisitos mínimos. A candidatura completa é feita "
                "somente no site; o Discord não coleta respostas."
                if eligibility["eligible"]
                else "Requisitos pendentes: " + ", ".join(eligibility["missing"])
            ),
        )
        view = discord.ui.View(timeout=180)
        view.add_item(discord.ui.Button(label="Abrir candidatura no site", url=url))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CareerAdminView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    async def choose_member(
        self, interaction: discord.Interaction, action: PersonnelActionType | None
    ) -> None:
        await interaction.response.edit_message(
            content=(
                "Selecione o membro que será promovido."
                if action is PersonnelActionType.PROMOTION
                else "Selecione o membro que será rebaixado."
                if action is PersonnelActionType.DEMOTION
                else "Selecione o membro para consultar o histórico."
            ),
            embed=None,
            view=CareerMemberSelectView(action),
        )

    @discord.ui.button(label="Promover", emoji="⬆️", style=discord.ButtonStyle.success)
    async def promote(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_member(interaction, PersonnelActionType.PROMOTION)

    @discord.ui.button(label="Rebaixar", emoji="⬇️", style=discord.ButtonStyle.danger)
    async def demote(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_member(interaction, PersonnelActionType.DEMOTION)

    @discord.ui.button(label="Histórico", emoji="📋", style=discord.ButtonStyle.secondary)
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_member(interaction, None)

    @discord.ui.button(label="Elegibilidade", emoji="🧭", style=discord.ButtonStyle.secondary)
    async def eligibility(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("OperationsCommands")
        if cog is None:
            raise NotFoundError("O diagnóstico de elegibilidade não está disponível.")
        await cog.open_promotion_eligibility(interaction)


class CareerMemberSelect(discord.ui.UserSelect):
    def __init__(self, action: PersonnelActionType | None) -> None:
        self.action = action
        super().__init__(placeholder="Escolha um membro", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_career_admin(interaction)
        target = actor.guild.get_member(self.values[0].id)
        if not target:
            raise NotFoundError("O membro selecionado não está mais no servidor.")
        bot = get_bot(interaction)
        profile = await bot.services.personnel.career_profile(actor.guild.id, target.id)
        if self.action is None:
            embed, page_count = await build_history_embed(bot, actor.guild, target.id, 0)
            await interaction.response.edit_message(
                content=None,
                embed=embed,
                view=CareerHistoryView(actor.id, target.id, 0, page_count, admin=True),
            )
            return
        targets = await bot.services.personnel.rank_targets(actor.guild.id, target.id, self.action)
        if not targets:
            boundary = "mais alta" if self.action is PersonnelActionType.PROMOTION else "mais baixa"
            raise ConflictError(f"O membro já está na patente {boundary}.")
        await interaction.response.edit_message(
            content=(
                f"Membro: {target.mention}\n"
                f"Patente atual: **{profile['rank_name'] or 'Não definida'}**\n"
                "Agora selecione a nova patente."
            ),
            embed=None,
            view=RankTargetView(actor.id, target.id, self.action, targets),
        )


class CareerMemberSelectView(AdminView):
    def __init__(self, action: PersonnelActionType | None) -> None:
        super().__init__(timeout=300)
        self.add_item(CareerMemberSelect(action))


class RankTargetSelect(discord.ui.Select):
    def __init__(
        self,
        owner_id: int,
        target_id: int,
        action: PersonnelActionType,
        targets: list,
    ) -> None:
        self.owner_id = owner_id
        self.target_id = target_id
        self.action = action
        super().__init__(
            placeholder="Escolha a nova patente",
            options=[
                discord.SelectOption(
                    label=f"Nível {row['level']} • {row['name']}"[:100],
                    value=str(row["id"]),
                    description=f"Prefixo {row['prefix'] or '—'}",
                )
                for row in targets[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            raise PermissionDenied("Este fluxo pertence a outro responsável.")
        await interaction.response.send_modal(
            CareerReasonModal(self.owner_id, self.target_id, int(self.values[0]), self.action)
        )


class RankTargetView(AdminView):
    def __init__(
        self,
        owner_id: int,
        target_id: int,
        action: PersonnelActionType,
        targets: list,
    ) -> None:
        super().__init__(timeout=300)
        self.add_item(RankTargetSelect(owner_id, target_id, action, targets))


class CareerReasonModal(ErrorModal, title="Motivo da movimentação"):
    reason = discord.ui.TextInput(
        label="Motivo",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(
        self,
        owner_id: int,
        target_id: int,
        target_rank_id: int,
        action: PersonnelActionType,
    ) -> None:
        super().__init__()
        self.owner_id = owner_id
        self.target_id = target_id
        self.target_rank_id = target_rank_id
        self.action = action

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_career_admin(interaction)
        if actor.id != self.owner_id:
            raise PermissionDenied("Este fluxo pertence a outro responsável.")
        target = actor.guild.get_member(self.target_id)
        if not target:
            raise NotFoundError("O membro não está mais no servidor.")
        bot = get_bot(interaction)
        profile = await bot.services.personnel.career_profile(actor.guild.id, target.id)
        rank = await bot.services.database.fetchone(
            "SELECT * FROM ranks WHERE guild_id=? AND id=? AND active=1",
            (actor.guild.id, self.target_rank_id),
        )
        if not rank:
            raise NotFoundError("A patente selecionada não está mais ativa.")
        timezone_name = await bot.services.settings.get(actor.guild.id, "timezone")
        month_ms = await bot.services.shifts.total_for_member(
            actor.guild.id, target.id, *period_bounds("month", timezone_name)
        )
        action_label = (
            "PROMOÇÃO" if self.action is PersonnelActionType.PROMOTION else "REBAIXAMENTO"
        )
        embed = branded_embed(
            bot.config.branding,
            title=f"⚠️ Confirmar {action_label}",
            description=(
                f"**Membro:** {target.mention}\n"
                f"**Patente atual:** {profile['rank_name'] or 'Não definida'}\n"
                f"**Nova patente:** {rank['name']}\n"
                f"**Motivo:** {self.reason}\n\n"
                f"Tempo na patente: {discord_timestamp(profile['rank_since'], 'R')}\n"
                f"Horas no mês: **{format_duration(month_ms)}**\n"
                f"Advertências ativas: **{profile['active_warnings']}**\n\n"
                "A decisão é humana e só será gravada ao confirmar."
            ),
        )
        await interaction.response.send_message(
            embed=embed,
            view=CareerConfirmationView(
                actor.id,
                target.id,
                self.target_rank_id,
                self.action,
                str(self.reason),
            ),
            ephemeral=True,
        )


class CareerConfirmationView(AdminView):
    def __init__(
        self,
        owner_id: int,
        target_id: int,
        target_rank_id: int,
        action: PersonnelActionType,
        reason: str,
    ) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.target_id = target_id
        self.target_rank_id = target_rank_id
        self.action = action
        self.reason = reason

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Esta confirmação pertence a outro responsável.", ephemeral=True
            )
            return False
        return await super().interaction_check(interaction)

    @discord.ui.button(label="Confirmar", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_career_admin(interaction)
        target = actor.guild.get_member(self.target_id)
        if not target:
            raise NotFoundError("O membro não está mais no servidor.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        bot = get_bot(interaction)
        result = await bot.services.personnel.change_rank_to(
            actor.guild.id,
            target.id,
            self.target_rank_id,
            self.action,
            actor.id,
            self.reason,
        )
        warning = await sync_rank_to_discord(bot, actor.guild, target, result, actor.id)
        suffix = f"\n⚠️ {warning}" if warning else ""
        await interaction.edit_original_response(
            content=(
                f"✅ Movimentação **#{result['action_id']}** confirmada: {target.mention} → "
                f"**{result['to_rank_name']}**.{suffix}"
            ),
            embed=None,
            view=None,
        )

    @discord.ui.button(label="Cancelar", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content="Movimentação cancelada. Nenhuma alteração foi gravada.", embed=None, view=None
        )


class CareerHistoryView(ErrorView):
    def __init__(
        self,
        owner_id: int,
        target_id: int,
        page: int,
        page_count: int,
        *,
        admin: bool,
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
            if self.admin:
                await require_career_admin(interaction)
            else:
                await require_member(interaction)
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True

    async def move(self, interaction: discord.Interaction, page: int) -> None:
        embed, page_count = await build_history_embed(
            get_bot(interaction), interaction.guild, self.target_id, page
        )
        await interaction.response.edit_message(
            embed=embed,
            view=CareerHistoryView(
                self.owner_id, self.target_id, page, page_count, admin=self.admin
            ),
        )

    @discord.ui.button(label="Anterior", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.move(interaction, self.page - 1)

    @discord.ui.button(label="Próxima", emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.move(interaction, self.page + 1)


class CareerCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self._panel_lock = asyncio.Lock()
        self._initialized_guilds: set[int] = set()
        self.bot.add_view(CareerPanelView())
        if not self.bot.check_mode:
            self.progression_loop.start()
            self.notification_loop.start()

    def cog_unload(self) -> None:
        self.progression_loop.cancel()
        self.notification_loop.cancel()

    async def _initialize_guild(self, guild: discord.Guild) -> None:
        if guild.id in self._initialized_guilds:
            return
        await self.bot.services.career.ensure_default_progression(guild.id, actor_id=None)
        await self.bot.services.career.ensure_officer_questionnaire(guild.id, actor_id=None)
        await self.bot.services.career.process_all(guild.id, source="RECOVERY")
        self._initialized_guilds.add(guild.id)

    @tasks.loop(seconds=60)
    async def progression_loop(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self._initialize_guild(guild)
                enabled = await self.bot.services.settings.get(
                    guild.id, "career_progression_enabled", True
                )
                if enabled:
                    await self.bot.services.career.process_all(guild.id, source="AUTOMATIC_HOURS")
            except Exception:
                LOGGER.exception("Falha no ciclo durável de progressão de carreira")

    @progression_loop.before_loop
    async def before_progression_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=5)
    async def notification_loop(self) -> None:
        for _ in range(10):
            notification = await self._claim_notification()
            if notification is None:
                break
            await self._deliver_notification(notification)

    @notification_loop.before_loop
    async def before_notification_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _claim_notification(self) -> dict[str, object] | None:
        now = self.bot.services.career.clock()
        async with self.bot.services.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM career_notifications
                WHERE attempts<6 AND (
                    (status IN ('PENDING','FAILED') AND available_at<=?)
                    OR (status='PROCESSING' AND updated_at<=?)
                )
                ORDER BY id LIMIT 1
                """,
                (now, now - 120_000),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            update = await connection.execute(
                """
                UPDATE career_notifications
                SET status='PROCESSING', attempts=attempts+1, updated_at=?
                WHERE id=? AND status=? AND updated_at=?
                """,
                (now, row["id"], row["status"], row["updated_at"]),
            )
            if update.rowcount != 1:
                return None
        return dict(row)

    def _notification_embed(
        self, notification_type: str, payload: dict[str, object]
    ) -> discord.Embed:
        if notification_type == "DISMISSAL":
            embed = branded_embed(
                self.bot.config.branding,
                title="⚔️ DESLIGAMENTO DE EFETIVO",
            )
            embed.add_field(name="Militar", value=f"<@{int(payload['discord_id'])}>", inline=False)
            embed.add_field(
                name="Responsável",
                value=f"<@{int(payload['actor_id'])}>",
                inline=False,
            )
            embed.add_field(name="Situação", value="Desligado da Corporação", inline=False)
            embed.add_field(
                name="Data",
                value=discord_timestamp(int(payload["occurred_at"]), "F"),
                inline=False,
            )
            embed.add_field(
                name="Motivo",
                value=dismissal_public_reason(payload.get("actor_has_high_command") is True),
                inline=False,
            )
            embed.set_footer(
                text="Registro efetuado para controle, disciplina e organização do efetivo."
            )
            return embed

        titles = {
            "PROMOTION": "⬆️ Promoção registrada",
            "DEMOTION": "⬇️ Rebaixamento registrado",
            "MERIT": "🏅 Registro de mérito",
            "OFFICER_SUBMITTED": "🛡️ Nova candidatura ao Oficialato",
            "OFFICER_DECISION": "🛡️ Decisão da candidatura ao Oficialato",
        }
        if notification_type in {"PROMOTION", "DEMOTION"}:
            actor_id = payload.get("actor_id")
            responsible = f"<@{actor_id}>" if actor_id else "Comando da CHOQUE"
            description = (
                f"<@{payload['discord_id']}> • **{payload.get('from_rank_name') or 'Sem patente'}** "
                f"→ **{payload.get('to_rank_name') or 'Sem patente'}**\n"
                f"**Responsável:** {responsible}\n"
                f"**Motivo:** {payload.get('reason') or 'Progressão automática por critérios válidos.'}"
            )
        elif notification_type == "MERIT":
            description = (
                f"**{payload.get('merit_type')} • {payload.get('category')}** "
                f"(peso {payload.get('weight')})\n{payload.get('reason')}"
            )
        elif notification_type == "OFFICER_SUBMITTED":
            description = (
                f"<@{payload['discord_id']}> enviou a candidatura **OF-"
                f"{int(payload['application_id']):05d}**.\n"
                "O relatório local é apenas consultivo; um responsável precisa assumir."
            )
        else:
            description = (
                f"Candidatura **OF-{int(payload['application_id']):05d}** • "
                f"**{payload.get('status')}**\n{payload.get('reason')}"
            )
            if payload.get("condition"):
                description += f"\nCondição: {payload['condition']}"
        embed = branded_embed(
            self.bot.config.branding,
            title=titles.get(notification_type, "Atualização de carreira"),
            description=description,
        )
        embed.set_footer(
            text=f"Entrega idempotente • decisão de oficialato sempre humana • {self.bot.config.branding.footer}"
        )
        return embed

    async def _deliver_notification(self, row: dict[str, object]) -> None:
        now = self.bot.services.career.clock()
        notification_id = int(row["id"])
        try:
            payload = json.loads(str(row["payload_json"]))
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None:
                raise NotFoundError("Servidor da notificação não está disponível.")
            embed = self._notification_embed(str(row["notification_type"]), payload)
            channel_message_id = row["channel_message_id"]
            channel_key = row["channel_setting_key"]
            if channel_key and channel_message_id is None:
                channel_id = await self.bot.services.settings.get(guild.id, str(channel_key))
                channel = guild.get_channel(int(channel_id)) if channel_id else None
                if not isinstance(channel, discord.TextChannel):
                    raise NotFoundError("Canal configurado para a notificação não foi encontrado.")
                content = None
                if row["notification_type"] == "OFFICER_SUBMITTED":
                    role_id = await self.bot.services.settings.get(
                        guild.id, "officer_upamento_role_id"
                    )
                    content = f"<@&{int(role_id)}>" if role_id else None
                message = await channel.send(
                    content=content,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False, users=True, roles=True
                    ),
                )
                channel_message_id = message.id
                await self.bot.services.database.execute(
                    """
                    UPDATE career_notifications
                    SET channel_message_id=?, updated_at=? WHERE id=?
                    """,
                    (message.id, now, notification_id),
                )

            dm_message_id = row["dm_message_id"]
            dm_error = None
            target_id = row["target_discord_id"]
            if target_id is not None and dm_message_id is None:
                target = guild.get_member(int(target_id)) or self.bot.get_user(int(target_id))
                if target is None:
                    try:
                        target = await self.bot.fetch_user(int(target_id))
                    except discord.DiscordException:
                        target = None
                if target is not None:
                    try:
                        dm = await target.send(embed=embed)
                        dm_message_id = dm.id
                        await self.bot.services.database.execute(
                            """
                            UPDATE career_notifications
                            SET dm_message_id=?, updated_at=? WHERE id=?
                            """,
                            (dm.id, now, notification_id),
                        )
                    except (discord.Forbidden, discord.NotFound):
                        dm_error = "DM indisponível para o destinatário."
                else:
                    dm_error = "Destinatário não localizado."

            await self.bot.services.database.execute(
                """
                UPDATE career_notifications
                SET status='DELIVERED', delivered_at=?, last_error=?, updated_at=?
                WHERE id=? AND status='PROCESSING'
                """,
                (now, dm_error, now, notification_id),
            )
            if row["notification_type"] == "PROMOTION":
                await self.bot.services.database.execute(
                    """
                    UPDATE career_progression_events SET published_at=?
                    WHERE personnel_action_id=?
                    """,
                    (now, row["subject_id"]),
                )
        except Exception as exc:
            attempts = int(row["attempts"] or 0) + 1
            delay = min(300_000, 5_000 * 2 ** min(attempts, 6))
            await self.bot.services.database.execute(
                """
                UPDATE career_notifications
                SET status='FAILED', available_at=?, last_error=?, updated_at=?
                WHERE id=?
                """,
                (now + delay, str(exc)[:1000], now, notification_id),
            )
            LOGGER.exception("Falha ao entregar notificação durável de carreira")

    async def open_admin(self, interaction: discord.Interaction) -> None:
        await require_career_admin(interaction)
        await interaction.response.send_message(
            embed=branded_embed(
                self.bot.config.branding,
                title="📈 Gestão de Carreira",
                description=(
                    "Selecione a operação. Toda promoção ou rebaixamento exige patente de destino, "
                    "motivo e confirmação explícita."
                ),
            ),
            view=CareerAdminView(),
            ephemeral=True,
        )

    async def publish_or_refresh(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        async with self._panel_lock:
            panel = await self.bot.services.settings.get_panel(guild.id, "CAREER")
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                    await message.edit(
                        embed=build_career_landing_embed(self.bot), view=CareerPanelView()
                    )
                    return message
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            message = await channel.send(
                embed=build_career_landing_embed(self.bot), view=CareerPanelView()
            )
            await self.bot.services.settings.upsert_panel(
                guild.id, "CAREER", channel.id, message.id
            )
            return message

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            try:
                await self._initialize_guild(guild)
            except Exception:
                LOGGER.exception("Falha ao restaurar o núcleo de carreira e oficialato")
            channel_id = await self.bot.services.settings.get(guild.id, "career_panel_channel_id")
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                await self.publish_or_refresh(guild, channel)
            except discord.DiscordException:
                LOGGER.exception("Falha ao restaurar o painel de carreira")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CareerCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
