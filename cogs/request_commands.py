from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from choque.embeds import branded_embed
from choque.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from choque.models import AdministrativeRequestType
from choque.requests import REQUEST_LABELS
from choque.time_utils import discord_timestamp, format_duration
from cogs.config_ui import respond_error
from cogs.member_sync import sync_member_identity, sync_member_status_roles

LOGGER = logging.getLogger(__name__)


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_member(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "REQUESTS")
    if not await bot.services.permissions.has(interaction.user, "request.submit"):
        raise PermissionDenied("Você não possui permissão de membro para abrir solicitações.")
    return interaction.user


async def require_request_admin(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "REQUESTS")
    if not await bot.services.permissions.has(interaction.user, "request.review"):
        raise PermissionDenied("Você não possui permissão para analisar solicitações.")
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
            await require_request_admin(interaction)
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True


class ErrorModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await respond_error(interaction, error)


def build_request_landing_embed(bot: ChoqueBot) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title="📥 Central de Solicitações • CHOQUE - BGR",
        description=(
            "Abra e acompanhe solicitações administrativas pelos botões abaixo. "
            "As decisões do Comando são auditadas e aplicadas automaticamente ao cadastro."
        ),
    ).add_field(
        name="Disponível neste painel",
        value=(
            "📅 Ausência e retorno antecipado\n"
            "🪖 Entrada ou retorno da reserva\n"
            "⏱️ Correção de horas\n"
            "🪪 Alteração de dados\n"
            "🚪 Desligamento voluntário"
        ),
        inline=False,
    )


async def build_admin_requests_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    pending = await bot.services.requests.pending_count(guild.id)
    return branded_embed(
        bot.config.branding,
        title="📥 Solicitações Administrativas",
        description=(
            f"Pendentes: **{pending}**\n\n"
            "Analise cada item individualmente. Aprovações alteram o cadastro, encerram "
            "serviço quando necessário e geram auditoria na mesma transação."
        ),
    )


def parse_total_minutes(value: str) -> int:
    normalized = value.strip()
    if ":" not in normalized:
        raise ValidationError("Use o total correto no formato HH:MM, por exemplo 02:30.")
    hours_raw, minutes_raw = normalized.split(":", 1)
    if not hours_raw.isdigit() or not minutes_raw.isdigit():
        raise ValidationError("Use o total correto no formato HH:MM, por exemplo 02:30.")
    hours, minutes = int(hours_raw), int(minutes_raw)
    if minutes > 59 or hours > 168:
        raise ValidationError("O total informado está fora do intervalo permitido.")
    return hours * 60 + minutes


class AbsenceRequestModal(ErrorModal, title="Solicitar ausência"):
    start_date = discord.ui.TextInput(label="Data inicial (DD/MM/AAAA)", placeholder="25/08/2026")
    end_date = discord.ui.TextInput(label="Último dia (DD/MM/AAAA)", placeholder="31/08/2026")
    reason = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=500)
    observation = discord.ui.TextInput(
        label="Observação", style=discord.TextStyle.paragraph, required=False, max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_member(interaction)
        bot = get_bot(interaction)
        timezone_name = await bot.services.settings.get(member.guild.id, "timezone")
        zone = ZoneInfo(timezone_name)
        try:
            starts = datetime.strptime(str(self.start_date), "%d/%m/%Y").replace(
                tzinfo=zone, hour=0, minute=0, second=0
            )
            ends = datetime.combine(
                datetime.strptime(str(self.end_date), "%d/%m/%Y").date(), time.max, tzinfo=zone
            )
        except ValueError as exc:
            raise ValidationError("Use datas válidas no formato DD/MM/AAAA.") from exc
        await interaction.response.defer(ephemeral=True, thinking=True)
        request_id = await bot.services.personnel.submit_absence(
            member.guild.id,
            member.id,
            int(starts.timestamp() * 1000),
            int(ends.timestamp() * 1000),
            str(self.reason),
            str(self.observation),
        )
        await notify_command(bot, member.guild, "ABSENCE", request_id, member.id)
        await interaction.followup.send(
            f"✅ Solicitação de ausência **#{request_id}** enviada para análise.", ephemeral=True
        )


class HoursCorrectionModal(ErrorModal, title="Solicitar correção de horas"):
    shift_id = discord.ui.TextInput(label="Número da sessão", placeholder="Ex.: 152", max_length=12)
    correct_total = discord.ui.TextInput(
        label="Total correto (HH:MM)", placeholder="Ex.: 02:30", max_length=6
    )
    problem = discord.ui.TextInput(
        label="Problema encontrado", style=discord.TextStyle.paragraph, max_length=500
    )
    reason = discord.ui.TextInput(
        label="Motivo da correção", style=discord.TextStyle.paragraph, max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_member(interaction)
        if not str(self.shift_id).strip().isdigit():
            raise ValidationError("O número da sessão deve conter somente dígitos.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        request_id = await get_bot(interaction).services.requests.submit(
            member.guild.id,
            member.id,
            AdministrativeRequestType.HOURS_CORRECTION,
            {
                "shift_id": int(str(self.shift_id)),
                "requested_total_minutes": parse_total_minutes(str(self.correct_total)),
                "problem": str(self.problem).strip(),
                "reason": str(self.reason).strip(),
            },
        )
        await notify_command(get_bot(interaction), member.guild, "ADMIN", request_id, member.id)
        await interaction.followup.send(
            f"✅ Correção de horas **#{request_id}** enviada para análise.", ephemeral=True
        )


class DataChangeModal(ErrorModal, title="Solicitar alteração de dados"):
    mta_nick = discord.ui.TextInput(label="Novo nome utilizado", required=False, max_length=50)
    character_id = discord.ui.TextInput(
        label="Nova identificação interna", required=False, max_length=50
    )
    unit = discord.ui.TextInput(label="Nova unidade", required=False, max_length=50)
    reason = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=500)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_member(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        request_id = await get_bot(interaction).services.requests.submit(
            member.guild.id,
            member.id,
            AdministrativeRequestType.DATA_CHANGE,
            {
                "mta_nick": str(self.mta_nick),
                "character_id": str(self.character_id),
                "unit": str(self.unit),
                "reason": str(self.reason),
            },
        )
        await notify_command(get_bot(interaction), member.guild, "ADMIN", request_id, member.id)
        await interaction.followup.send(
            f"✅ Alteração cadastral **#{request_id}** enviada para análise.", ephemeral=True
        )


class DismissalModal(ErrorModal, title="Solicitar desligamento"):
    reason = discord.ui.TextInput(
        label="Motivo do desligamento", style=discord.TextStyle.paragraph, max_length=500
    )
    confirmation = discord.ui.TextInput(
        label="Digite CONFIRMAR", placeholder="CONFIRMAR", max_length=9
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_member(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        request_id = await get_bot(interaction).services.requests.submit(
            member.guild.id,
            member.id,
            AdministrativeRequestType.DISMISSAL,
            {"reason": str(self.reason), "confirmation": str(self.confirmation)},
        )
        await notify_command(get_bot(interaction), member.guild, "ADMIN", request_id, member.id)
        await interaction.followup.send(
            f"✅ Pedido de desligamento **#{request_id}** enviado para análise.", ephemeral=True
        )


class EarlyReturnConfirmView(MemberView):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Este controle pertence a outro membro.", ephemeral=True
            )
            return False
        return await super().interaction_check(interaction)

    @discord.ui.button(
        label="Solicitar retorno antecipado", emoji="🔄", style=discord.ButtonStyle.success
    )
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        request_id = await get_bot(interaction).services.requests.submit(
            member.guild.id,
            member.id,
            AdministrativeRequestType.EARLY_RETURN,
            {"reason": "Retorno antecipado solicitado pelo membro"},
        )
        await notify_command(get_bot(interaction), member.guild, "ADMIN", request_id, member.id)
        await interaction.followup.send(
            f"✅ Retorno antecipado **#{request_id}** enviado para análise.", ephemeral=True
        )


class ReserveChoiceView(MemberView):
    def __init__(self, owner_id: int, status: str) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.status = status
        if status == "RESERVE":
            self.entry.disabled = True
        else:
            self.exit.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Este controle pertence a outro membro.", ephemeral=True
            )
            return False
        return await super().interaction_check(interaction)

    async def submit(
        self, interaction: discord.Interaction, request_type: AdministrativeRequestType
    ) -> None:
        member = await require_member(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        label = REQUEST_LABELS[request_type.value]
        request_id = await get_bot(interaction).services.requests.submit(
            member.guild.id,
            member.id,
            request_type,
            {"reason": f"{label} solicitada pelo membro"},
        )
        await notify_command(get_bot(interaction), member.guild, "ADMIN", request_id, member.id)
        await interaction.followup.send(
            f"✅ {label} **#{request_id}** enviada para análise.", ephemeral=True
        )

    @discord.ui.button(label="Entrar na reserva", emoji="🟡", style=discord.ButtonStyle.primary)
    async def entry(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.submit(interaction, AdministrativeRequestType.RESERVE_ENTRY)

    @discord.ui.button(label="Retornar ao efetivo", emoji="🟢", style=discord.ButtonStyle.success)
    async def exit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.submit(interaction, AdministrativeRequestType.RESERVE_EXIT)


class RequestPanelView(MemberView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ausência",
        emoji="📅",
        style=discord.ButtonStyle.primary,
        custom_id="choque:requests:absence:v1",
        row=0,
    )
    async def absence(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(AbsenceRequestModal())

    @discord.ui.button(
        label="Retorno",
        emoji="🔄",
        style=discord.ButtonStyle.success,
        custom_id="choque:requests:return:v1",
        row=0,
    )
    async def early_return(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        row = await get_bot(interaction).services.database.fetchone(
            """
            SELECT ends_at FROM absence_requests WHERE guild_id=? AND discord_id=?
              AND status='APPROVED' AND starts_at <= ? AND ends_at > ?
            ORDER BY starts_at DESC LIMIT 1
            """,
            (
                member.guild.id,
                member.id,
                int(discord.utils.utcnow().timestamp() * 1000),
                int(discord.utils.utcnow().timestamp() * 1000),
            ),
        )
        if not row:
            raise ConflictError("Você não possui ausência ativa.")
        await interaction.response.send_message(
            f"Sua ausência está ativa até {discord_timestamp(row['ends_at'], 'd')}.",
            view=EarlyReturnConfirmView(member.id),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Reserva",
        emoji="🪖",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:requests:reserve:v1",
        row=0,
    )
    async def reserve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        row = await get_bot(interaction).services.members.get(member.guild.id, member.id)
        if not row:
            raise NotFoundError("Cadastro aprovado não encontrado.")
        await interaction.response.send_message(
            f"Seu status atual é `{row['status']}`. Escolha a ação disponível:",
            view=ReserveChoiceView(member.id, str(row["status"])),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Corrigir horas",
        emoji="⏱️",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:requests:hours:v1",
        row=0,
    )
    async def hours(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(HoursCorrectionModal())

    @discord.ui.button(
        label="Alterar dados",
        emoji="🪪",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:requests:data:v1",
        row=0,
    )
    async def data(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(DataChangeModal())

    @discord.ui.button(
        label="Desligamento",
        emoji="🚪",
        style=discord.ButtonStyle.danger,
        custom_id="choque:requests:dismissal:v1",
        row=1,
    )
    async def dismissal(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(DismissalModal())

    @discord.ui.button(
        label="Minhas solicitações",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:requests:mine:v1",
        row=1,
    )
    async def mine(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        bot = get_bot(interaction)
        generic, absences = await asyncio.gather(
            bot.services.requests.for_member(member.guild.id, member.id, limit=10),
            bot.services.personnel.absences_for_member(member.guild.id, member.id, limit=10),
        )
        rows = [
            {
                "id": row["id"],
                "type": REQUEST_LABELS[row["request_type"]],
                "status": row["status"],
                "submitted_at": row["submitted_at"],
            }
            for row in generic
        ]
        rows.extend(
            {
                "id": row["id"],
                "type": "Ausência",
                "status": row["status"],
                "submitted_at": row["submitted_at"],
            }
            for row in absences
        )
        rows.sort(key=lambda item: int(item["submitted_at"]), reverse=True)
        lines = [
            f"**#{row['id']}** • {row['type']} • `{row['status']}` • {discord_timestamp(row['submitted_at'], 'R')}"
            for row in rows[:10]
        ]
        await interaction.response.send_message(
            "\n".join(lines) or "Você ainda não possui solicitações.", ephemeral=True
        )

    @discord.ui.button(
        label="Troca de atividade",
        emoji="🔁",
        style=discord.ButtonStyle.primary,
        custom_id="choque:requests:activity-swap:v1",
        row=1,
    )
    async def activity_swap(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        cog = get_bot(interaction).get_cog("OperationsCommands")
        if cog is None:
            raise NotFoundError("O sistema de trocas não está disponível.")
        await cog.open_swap(interaction)


class AdministrativeRequestsView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="Ver pendentes", emoji="📥", style=discord.ButtonStyle.primary)
    async def pending(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await get_bot(interaction).services.requests.pending_queue(interaction.guild.id)
        if not rows:
            await interaction.response.edit_message(
                content="✅ Nenhuma solicitação pendente.", embed=None, view=None
            )
            return
        await interaction.response.edit_message(
            content="Selecione uma solicitação para analisar:",
            embed=None,
            view=RequestQueueView(rows),
        )

    @discord.ui.button(label="Histórico", emoji="📚", style=discord.ButtonStyle.secondary)
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await get_bot(interaction).services.requests.recent_queue(interaction.guild.id)
        lines = [
            f"**{REQUEST_LABELS[row['request_type']]} #{row['id']}** • <@{row['discord_id']}> • "
            f"`{row['status']}` • {discord_timestamp(row['submitted_at'], 'R')}"
            for row in rows
        ]
        await interaction.response.edit_message(
            content="\n".join(lines)[:1900] or "Nenhuma solicitação registrada.",
            embed=None,
            view=None,
        )


class RequestQueueSelect(discord.ui.Select):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        super().__init__(
            placeholder="Escolha uma solicitação pendente",
            options=[
                discord.SelectOption(
                    label=f"{REQUEST_LABELS[row['request_type']]} #{row['id']}"[:100],
                    value=f"{row['source']}:{row['id']}",
                    description=f"{row['mta_nick']} • {str(row['payload'].get('reason') or '')}"[
                        :100
                    ],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        source, raw_id = self.values[0].split(":", 1)
        request_id = int(raw_id)
        row = next(
            (
                item
                for item in self.rows
                if item["source"] == source and int(item["id"]) == request_id
            ),
            None,
        )
        if not row:
            raise NotFoundError("Solicitação não encontrada nesta fila.")
        payload = row["payload"]
        details = [
            f"**Membro:** <@{row['discord_id']}> (`{row['mta_nick']}`)",
            f"**Tipo:** {REQUEST_LABELS[row['request_type']]}",
            f"**Motivo:** {payload.get('reason') or '—'}",
        ]
        if row["request_type"] == "ABSENCE":
            details.extend(
                (
                    f"**Início:** {discord_timestamp(payload['starts_at'], 'd')}",
                    f"**Fim:** {discord_timestamp(payload['ends_at'], 'd')}",
                    f"**Observação:** {payload.get('observation') or '—'}",
                )
            )
        elif row["request_type"] == "HOURS_CORRECTION":
            details.extend(
                (
                    f"**Sessão:** #{payload['shift_id']}",
                    f"**Total solicitado:** {format_duration(payload['requested_total_minutes'] * 60_000)}",
                    f"**Problema:** {payload.get('problem') or '—'}",
                )
            )
        elif row["request_type"] == "DATA_CHANGE":
            details.append(
                "**Alterações:** "
                + ", ".join(f"{key} → `{value}`" for key, value in payload["changes"].items())
            )
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title=f"Solicitação #{request_id}",
            description="\n".join(details),
        )
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=RequestDecisionView(source, request_id, int(row["discord_id"])),
        )


class RequestQueueView(AdminView):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(timeout=300)
        self.add_item(RequestQueueSelect(rows))


class RequestDecisionView(AdminView):
    def __init__(self, source: str, request_id: int, discord_id: int) -> None:
        super().__init__(timeout=300)
        self.source = source
        self.request_id = request_id
        self.discord_id = discord_id

    @discord.ui.button(label="Aprovar", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            RequestDecisionModal(self.source, self.request_id, self.discord_id, True)
        )

    @discord.ui.button(label="Negar", emoji="❌", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            RequestDecisionModal(self.source, self.request_id, self.discord_id, False)
        )

    @discord.ui.button(label="Ver perfil", emoji="👤", style=discord.ButtonStyle.secondary)
    async def profile(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await get_bot(interaction).services.members.get(interaction.guild.id, self.discord_id)
        if not row:
            raise NotFoundError("Cadastro do membro não encontrado.")
        await interaction.response.send_message(
            f"<@{self.discord_id}>\n**Nome:** {row['mta_nick']}\n**Patente:** "
            f"{row['rank_name'] or '—'}\n**Status:** `{row['status']}`\n"
            f"**ID interno:** {row['character_id'] or '—'}\n**Unidade:** {row['unit'] or '—'}",
            ephemeral=True,
        )


class RequestDecisionModal(ErrorModal, title="Analisar solicitação"):
    reason = discord.ui.TextInput(
        label="Motivo da decisão",
        style=discord.TextStyle.paragraph,
        default="Análise administrativa",
        max_length=500,
    )

    def __init__(self, source: str, request_id: int, discord_id: int, approved: bool) -> None:
        super().__init__()
        self.source = source
        self.request_id = request_id
        self.discord_id = discord_id
        self.approved = approved

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_request_admin(interaction)
        bot = get_bot(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        if self.source == "ABSENCE":
            result = await bot.services.personnel.review_absence(
                actor.guild.id, self.request_id, self.approved, actor.id, str(self.reason)
            )
            if result["member_status"] == "AWAY":
                await bot.services.shifts.finalize_role_loss(
                    actor.guild.id, self.discord_id, reason="ABSENCE_APPROVED"
                )
        else:
            result = await bot.services.requests.review(
                actor.guild.id, self.request_id, self.approved, actor.id, str(self.reason)
            )
        warning = await apply_discord_result(
            bot, actor.guild, self.discord_id, result, actor.id
        )
        target = actor.guild.get_member(self.discord_id)
        if target:
            try:
                decision = "aprovada" if self.approved else "negada"
                await target.send(
                    f"Sua solicitação #{self.request_id} foi **{decision}**. Motivo: {self.reason}"
                )
            except discord.Forbidden:
                pass
        suffix = f"\n⚠️ {warning}" if warning else ""
        await interaction.followup.send(
            f"✅ Solicitação **#{self.request_id}** definida como `{result['status']}`.{suffix}",
            ephemeral=True,
        )


async def apply_discord_result(
    bot: ChoqueBot,
    guild: discord.Guild,
    discord_id: int,
    result: dict[str, Any],
    actor_id: int | None = None,
) -> str | None:
    target = guild.get_member(discord_id)
    if not target:
        return "O membro não está mais no servidor; a decisão foi preservada no banco."
    warnings = []
    member_status = result.get("member_status")
    if member_status:
        warning = await sync_member_status_roles(bot, guild, target, str(member_status))
        if warning:
            warnings.append(warning)
    if result.get("member_changes"):
        warning = await sync_member_identity(bot, guild, target, actor_id)
        if warning:
            warnings.append(warning)
    return " ".join(warnings) or None


async def notify_command(
    bot: ChoqueBot, guild: discord.Guild, source: str, request_id: int, discord_id: int
) -> None:
    channel_id = await bot.services.settings.get(guild.id, "personnel_admin_channel_id")
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return
    title = "Ausência" if source == "ABSENCE" else "Solicitação administrativa"
    await channel.send(
        embed=branded_embed(
            bot.config.branding,
            title=f"📥 Nova {title.lower()} pendente #{request_id}",
            description=(
                f"**Membro:** <@{discord_id}>\n"
                "Use o botão **Solicitações** na Central Administrativa para analisar."
            ),
        )
    )


class RequestCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self._panel_lock = asyncio.Lock()
        self.bot.add_view(RequestPanelView())

    async def open_admin(self, interaction: discord.Interaction) -> None:
        await require_request_admin(interaction)
        await interaction.response.send_message(
            embed=await build_admin_requests_embed(self.bot, interaction.guild),
            view=AdministrativeRequestsView(),
            ephemeral=True,
        )

    async def publish_or_refresh(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        async with self._panel_lock:
            panel = await self.bot.services.settings.get_panel(guild.id, "REQUESTS")
            if not panel:
                panel = await self.bot.services.settings.get_panel(guild.id, "ABSENCE")
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                    await message.edit(
                        embed=build_request_landing_embed(self.bot), view=RequestPanelView()
                    )
                    await self.bot.services.settings.upsert_panel(
                        guild.id, "REQUESTS", channel.id, message.id
                    )
                    return message
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            message = await channel.send(
                embed=build_request_landing_embed(self.bot), view=RequestPanelView()
            )
            await self.bot.services.settings.upsert_panel(
                guild.id, "REQUESTS", channel.id, message.id
            )
            return message

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            channel_id = await self.bot.services.settings.get(guild.id, "requests_panel_channel_id")
            if not channel_id:
                channel_id = await self.bot.services.settings.get(
                    guild.id, "absence_panel_channel_id"
                )
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                await self.publish_or_refresh(guild, channel)
            except discord.DiscordException:
                LOGGER.exception("Falha ao restaurar a Central de Solicitações")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RequestCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
