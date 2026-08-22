from __future__ import annotations

import asyncio
from typing import Literal, cast

import discord
from discord import app_commands
from discord.ext import commands, tasks

from choque.embeds import branded_embed
from choque.errors import ChoqueError, NotFoundError, PermissionDenied, ValidationError
from choque.models import ShiftStatus
from choque.time_utils import discord_timestamp, format_duration, period_bounds
from cogs.config_ui import respond_error


def _member_from_interaction(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Este recurso só pode ser usado dentro do servidor.")
    return interaction.user


def build_point_panel_embed(bot: commands.Bot) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="⏱️ CONTROLE OPERACIONAL DE SERVIÇO",
        description=(
            "**SISTEMA OFICIAL DE BATE-PONTO • CHOQUE - BGR**\n\n"
            "Registre somente o período em que estiver efetivamente disponível para o serviço. "
            "O sistema acompanha sua presença nas calls autorizadas, distingue patrulha efetiva "
            "de espera/treinamento e mantém auditoria de cada ação."
        ),
    )
    embed.add_field(
        name="🟢 Entrada em serviço",
        value=(
            "`01` Entre em uma call operacional autorizada.\n"
            "`02` Confirme que possui cargo e cadastro ativos.\n"
            "`03` Pressione **Iniciar Serviço** uma única vez."
        ),
        inline=False,
    )
    embed.add_field(
        name="🎙️ Durante a operação",
        value=(
            "Trocas entre calls autorizadas mantêm a mesma sessão. Saídas fecham o segmento válido "
            "imediatamente; o intervalo fora da call nunca é contabilizado."
        ),
        inline=False,
    )
    embed.add_field(
        name="🎯 Validação mínima de patrulha",
        value=(
            "A sessão só entra nas horas, ranking e meta após atingir o **mínimo configurado** em "
            "calls marcadas como patrulha. Tempo em call apenas autorizada pode manter o serviço "
            "aberto sem avançar a validação."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔴 Encerramento e tolerância",
        value=(
            "Ao sair de uma call válida, existe tolerância configurável para retorno. Se não voltar, "
            "a sessão é encerrada automaticamente. Use **Finalizar Serviço** ao concluir a missão."
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 Situações registradas",
        value=(
            "`ACTIVE` Em serviço • `GRACE` Em tolerância • `REVIEW_REQUIRED` Revisão do Comando • "
            "`CLOSED` Encerrado"
        ),
        inline=False,
    )
    embed.add_field(
        name="🛡️ Integridade do registro",
        value=(
            "Não é permitido manter dois pontos ativos. Ajustes administrativos são append-only, "
            "exigem motivo e permanecem na auditoria."
        ),
        inline=False,
    )
    return embed


class PointPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def _run(self, interaction: discord.Interaction, action: str) -> None:
        cog = interaction.client.get_cog("ShiftCommands")
        if not isinstance(cog, ShiftCommands):
            await interaction.response.send_message(
                "O sistema de ponto está indisponível.", ephemeral=True
            )
            return
        await cog.handle_panel_action(interaction, action)

    @discord.ui.button(
        label="Iniciar Serviço",
        emoji="🟢",
        style=discord.ButtonStyle.success,
        custom_id="choque:shift:start:v1",
    )
    async def start(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "start")

    @discord.ui.button(
        label="Finalizar Serviço",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        custom_id="choque:shift:stop:v1",
    )
    async def stop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "stop")

    @discord.ui.button(
        label="Minhas Horas",
        emoji="⏱",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:shift:hours:v1",
    )
    async def hours(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "hours")

    @discord.ui.button(
        label="Histórico",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:shift:history:v1",
    )
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "history")

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await respond_error(interaction, error)


class ShiftHistoryView(discord.ui.View):
    def __init__(self, cog: ShiftCommands, member: discord.Member, page: int = 0) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.member = member
        self.page = page

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.member.id:
            return True
        await interaction.response.send_message(
            "Este histórico pertence a outro membro.", ephemeral=True
        )
        return False

    async def render(self, interaction: discord.Interaction) -> None:
        embed, has_next = await self.cog._history_embed(self.member, self.page)
        self.previous.disabled = self.page == 0
        self.next.disabled = not has_next
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Anterior", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        await self.render(interaction)

    @discord.ui.button(label="Próxima", emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page += 1
        await self.render(interaction)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await respond_error(interaction, error)


class EarlyStopConfirmationView(discord.ui.View):
    def __init__(self, cog: ShiftCommands, member: discord.Member, shift_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.member = member
        self.shift_id = shift_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.member.id:
            return True
        await interaction.response.send_message(
            "Somente o titular desta sessão pode confirmar o encerramento.", ephemeral=True
        )
        return False

    @discord.ui.button(
        label="Finalizar mesmo assim", emoji="⚠️", style=discord.ButtonStyle.danger
    )
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        text = await self.cog._stop_member(
            self.member,
            confirm_short=True,
            expected_shift_id=self.shift_id,
        )
        self.stop()
        await interaction.edit_original_response(content=text, embed=None, view=None)

    @discord.ui.button(
        label="Continuar em serviço", emoji="🟢", style=discord.ButtonStyle.success
    )
    async def continue_service(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        self.stop()
        await interaction.response.edit_message(
            content="🟢 Sessão mantida. Continue em uma call que conte como patrulha.",
            embed=None,
            view=None,
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await respond_error(interaction, error)


class ManualValidationModal(discord.ui.Modal, title="Validar ponto excepcionalmente"):
    reason = discord.ui.TextInput(
        label="Motivo detalhado", style=discord.TextStyle.paragraph, min_length=10, max_length=800
    )
    confirmation = discord.ui.TextInput(
        label="Digite VALIDAR para confirmar", min_length=7, max_length=7
    )

    def __init__(self, cog: ShiftCommands, shift_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.shift_id = shift_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = _member_from_interaction(interaction)
        await self.cog._require(member, "shift.review")
        if str(self.confirmation).strip().upper() != "VALIDAR":
            raise ValidationError("Confirmação inválida. Digite VALIDAR exatamente.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.cog.services.shifts.validate_manually(
            member.guild.id,
            self.shift_id,
            member.id,
            str(self.reason),
        )
        await interaction.followup.send(
            f"✅ Sessão **#{result['shift_id']}** validada por exceção administrativa. "
            "A decisão automática original permanece preservada na auditoria.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await respond_error(interaction, error)


class ManualValidationDecisionView(discord.ui.View):
    def __init__(self, cog: ShiftCommands, shift_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.shift_id = shift_id

    @discord.ui.button(label="Validar manualmente", emoji="🛡️", style=discord.ButtonStyle.danger)
    async def validate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ManualValidationModal(self.cog, self.shift_id))


class InvalidatedShiftSelect(discord.ui.Select):
    def __init__(self, cog: ShiftCommands, rows) -> None:
        self.cog = cog
        self.rows = {int(row["id"]): row for row in rows}
        super().__init__(
            placeholder="Escolha uma sessão invalidada",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['mta_nick']}"[:100],
                    value=str(row["id"]),
                    description=(
                        f"Patrulha {format_duration(int(row['patrol_duration_ms']))} / "
                        f"{format_duration(int(row['minimum_patrol_ms']))}"
                    )[:100],
                )
                for row in rows
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        row = self.rows[int(self.values[0])]
        embed = branded_embed(
            self.cog.branding,
            title=f"🛡️ Revisão excepcional • Sessão #{row['id']}",
            description=(
                f"**Membro:** <@{row['discord_id']}> • `{row['mta_nick']}`\n"
                f"**Duração bruta:** {format_duration(int(row['gross_duration_ms']))}\n"
                f"**Patrulha válida:** {format_duration(int(row['patrol_duration_ms']))}\n"
                f"**Mínimo exigido:** {format_duration(int(row['minimum_patrol_ms']))}\n"
                f"**Decisão automática:** `{row['automatic_validation_status']}`\n"
                f"**Motivo:** `{row['invalid_reason'] or 'Não informado'}`\n\n"
                "A validação excepcional exige motivo e confirmação e não altera a decisão "
                "automática preservada."
            ),
        )
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=ManualValidationDecisionView(self.cog, int(row["id"])),
        )


class InvalidatedShiftView(discord.ui.View):
    def __init__(self, cog: ShiftCommands, rows) -> None:
        super().__init__(timeout=300)
        self.add_item(InvalidatedShiftSelect(cog, rows))


class ShiftCommands(commands.Cog):
    ponto = app_commands.Group(name="ponto", description="Controle de serviço por call")
    servico = app_commands.Group(name="servico", description="Efetivo em serviço")
    horas = app_commands.Group(name="horas", description="Consultas de horas válidas")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.services = bot.services
        self.branding = bot.config.branding
        self._recovery_lock = asyncio.Lock()
        self._panel_lock = asyncio.Lock()
        self._recovered = False
        self.services.shifts.set_state_change_callback(self.on_shift_state_change)
        self.bot.add_view(PointPanelView())
        if not bot.check_mode:
            self.heartbeat_loop.start()
            self.audit_retry_loop.start()
            self.service_panel_loop.start()

    async def publish_or_refresh_point_panel(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
    ) -> discord.Message:
        async with self._panel_lock:
            panel = await self.services.settings.get_panel(guild.id, "POINT")
            message = None
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None
            if message is None:
                message = await channel.send(
                    embed=build_point_panel_embed(self.bot),
                    view=PointPanelView(),
                )
            else:
                await message.edit(
                    embed=build_point_panel_embed(self.bot),
                    view=PointPanelView(),
                )
            await self.services.settings.upsert_panel(
                guild.id,
                "POINT",
                message.channel.id,
                message.id,
            )
            return message

    def cog_unload(self) -> None:
        for loop in (self.heartbeat_loop, self.audit_retry_loop, self.service_panel_loop):
            loop.cancel()

    async def _require(self, member: discord.Member, permission: str) -> None:
        if not await self.services.permissions.has(member, permission):
            raise PermissionDenied("Você não possui permissão para esta ação.")

    async def handle_panel_action(self, interaction: discord.Interaction, action: str) -> None:
        try:
            member = _member_from_interaction(interaction)
            await self.services.modules.require_enabled(member.guild.id, "POINT")
            if action == "stop":
                await self._require(member, "shift.stop.self")
                progress = await self.services.shifts.patrol_progress(member.guild.id, member.id)
                if not progress["requirement_met"]:
                    embed = branded_embed(
                        self.branding,
                        title="⚠️ Finalização antecipada",
                        description=(
                            f"**Patrulha válida:** {format_duration(int(progress['patrol_duration_ms']))}\n"
                            f"**Mínimo exigido:** {format_duration(int(progress['minimum_patrol_ms']))}\n\n"
                            "Se encerrar agora, a sessão será **INVALIDADA**, continuará no "
                            "histórico e contribuirá com **zero horas**."
                        ),
                    )
                    await interaction.response.send_message(
                        embed=embed,
                        view=EarlyStopConfirmationView(
                            self, member, int(progress["shift_id"])
                        ),
                        ephemeral=True,
                    )
                    return
            await interaction.response.defer(ephemeral=True, thinking=True)
            if action == "start":
                text = await self._start_member(member)
                await interaction.followup.send(text, ephemeral=True)
            elif action == "stop":
                text = await self._stop_member(member)
                await interaction.followup.send(text, ephemeral=True)
            elif action == "hours":
                embed = await self._hours_embed(member)
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                embed, has_next = await self._history_embed(member)
                view = ShiftHistoryView(self, member)
                view.previous.disabled = True
                view.next.disabled = not has_next
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except ChoqueError as exc:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

    async def _start_member(self, member: discord.Member) -> str:
        await self._require(member, "shift.start")
        voice_channel_id = (
            member.voice.channel.id if member.voice and member.voice.channel else None
        )
        authorized_role = await self.services.permissions.has_authorized_service_role(member)
        result = await self.services.shifts.start_shift(
            member.guild.id,
            member.id,
            voice_channel_id,
            has_authorized_role=authorized_role,
        )
        return (
            f"🟢 Serviço iniciado. Sessão **#{result.shift_id}**.\n"
            f"🎯 Acumule **{format_duration(result.minimum_patrol_ms)}** em calls de patrulha. "
            "Uma saída antecipada invalida a sessão e ela não entra nas horas."
        )

    async def _stop_member(
        self,
        member: discord.Member,
        *,
        confirm_short: bool = False,
        expected_shift_id: int | None = None,
    ) -> str:
        await self._require(member, "shift.stop.self")
        result = await self.services.shifts.stop_shift(
            member.guild.id,
            member.id,
            confirm_short=confirm_short,
            expected_shift_id=expected_shift_id,
        )
        if result.validation_status == "INVALIDATED":
            return (
                f"⚠️ Serviço finalizado. Sessão **#{result.shift_id} INVALIDADA**.\n"
                f"Patrulha: **{format_duration(result.patrol_duration_ms)}** de "
                f"**{format_duration(result.minimum_patrol_ms)}**. O registro foi preservado, "
                "mas contribui com zero horas."
            )
        return (
            f"🔴 Serviço finalizado. Sessão **#{result.shift_id}** validada com "
            f"**{format_duration(result.patrol_duration_ms)}** de patrulha."
        )

    async def _hours_embed(self, member: discord.Member) -> discord.Embed:
        timezone_name = await self.services.settings.get(member.guild.id, "timezone")
        today = period_bounds("today", timezone_name)
        week = period_bounds("week", timezone_name)
        month = period_bounds("month", timezone_name)
        today_ms, week_ms, month_ms, total_ms = await asyncio.gather(
            self.services.shifts.total_for_member(member.guild.id, member.id, *today),
            self.services.shifts.total_for_member(member.guild.id, member.id, *week),
            self.services.shifts.total_for_member(member.guild.id, member.id, *month),
            self.services.shifts.total_for_member(member.guild.id, member.id),
        )
        embed = branded_embed(self.branding, title="Minhas horas válidas")
        embed.add_field(name="Hoje", value=format_duration(today_ms), inline=True)
        embed.add_field(name="Semana", value=format_duration(week_ms), inline=True)
        embed.add_field(name="Mês", value=format_duration(month_ms), inline=True)
        embed.add_field(name="Total", value=format_duration(total_ms), inline=True)
        return embed

    async def _history_embed(
        self, member: discord.Member, page: int = 0
    ) -> tuple[discord.Embed, bool]:
        rows = await self.services.shifts.history(member.guild.id, member.id, 11, page * 10)
        has_next = len(rows) > 10
        rows = rows[:10]
        embed = branded_embed(self.branding, title=f"Histórico de serviço • Página {page + 1}")
        if not rows:
            embed.description = "Nenhuma sessão registrada."
            return embed, False
        lines = []
        for row in rows:
            validation = str(row["validation_status"])
            validation_label = {
                "VALID": "✅ Válido",
                "INVALIDATED": "❌ Invalidado",
                "REVIEW_REQUIRED": "⚠️ Revisão",
                "PENDING": "⏳ Em validação",
            }.get(validation, validation)
            lines.append(
                f"**#{row['id']}** • {discord_timestamp(int(row['started_at']), 'd')} • "
                f"{format_duration(int(row['total_ms']))} • **{validation_label}**\n"
                f"└ Patrulha {format_duration(int(row['patrol_duration_ms']))} / "
                f"{format_duration(int(row['minimum_patrol_ms']))}"
            )
        embed.description = "\n".join(lines)
        return embed, has_next

    @ponto.command(name="iniciar", description="Inicia o serviço na call autorizada atual.")
    async def point_start(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        member = _member_from_interaction(interaction)
        await interaction.followup.send(await self._start_member(member), ephemeral=True)

    @ponto.command(name="finalizar", description="Finaliza seu serviço ativo.")
    async def point_stop(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        member = _member_from_interaction(interaction)
        await interaction.followup.send(await self._stop_member(member), ephemeral=True)

    @ponto.command(name="status", description="Mostra o estado do seu ponto.")
    async def point_status(self, interaction: discord.Interaction) -> None:
        member = _member_from_interaction(interaction)
        active = await self.services.shifts.get_active(member.guild.id, member.id)
        if not active:
            await interaction.response.send_message("⚫ Você está fora de serviço.", ephemeral=True)
            return
        progress = await self.services.shifts.patrol_progress(member.guild.id, member.id)
        channel = (
            f"<#{active['voice_channel_id']}>" if active["voice_channel_id"] else "Em tolerância"
        )
        embed = branded_embed(self.branding, title="🟢 EM SERVIÇO")
        embed.add_field(name="Entrada", value=discord_timestamp(int(active["started_at"]), "t"))
        validation = (
            "✅ Requisito mínimo atingido"
            if progress["requirement_met"]
            else (
                f"⏳ {format_duration(int(progress['patrol_duration_ms']))} / "
                f"{format_duration(int(progress['minimum_patrol_ms']))}"
            )
        )
        embed.add_field(name="Validação da sessão", value=validation, inline=False)
        embed.add_field(name="Call atual", value=channel, inline=False)
        embed.add_field(name="Sessão", value=f"#{active['id']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ponto.command(name="painel", description="Publica ou atualiza o painel fixo de ponto.")
    async def point_panel(self, interaction: discord.Interaction) -> None:
        member = _member_from_interaction(interaction)
        await self._require(member, "panel.manage")
        await interaction.response.defer(ephemeral=True)
        message = await self.publish_or_refresh_point_panel(member.guild, interaction.channel)
        await interaction.followup.send(
            f"Painel de ponto atualizado em {message.channel.mention}.", ephemeral=True
        )

    @ponto.command(name="ajustar", description="Adiciona um ajuste auditável a uma sessão.")
    async def point_adjust(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
        minutos: int,
        motivo: str,
    ) -> None:
        actor = _member_from_interaction(interaction)
        await self._require(actor, "shift.adjust")
        latest = await self.services.database.fetchone(
            """
            SELECT s.id FROM shifts s JOIN members m ON m.id=s.member_id
            WHERE s.guild_id=? AND m.discord_id=? ORDER BY s.id DESC LIMIT 1
            """,
            (actor.guild.id, membro.id),
        )
        if not latest:
            raise NotFoundError("O membro não possui sessões.")
        await self.services.shifts.adjust_shift(
            actor.guild.id, int(latest["id"]), minutos, actor.id, motivo
        )
        await interaction.response.send_message(
            f"Ajuste de {minutos:+d} minuto(s) registrado na sessão #{latest['id']}.",
            ephemeral=True,
        )

    @ponto.command(name="revisar", description="Resolve uma sessão inconsistente após reinício.")
    async def point_review(
        self,
        interaction: discord.Interaction,
        sessao: int,
        acao: Literal["confirmar", "continuar"],
        motivo: str,
    ) -> None:
        actor = _member_from_interaction(interaction)
        await self._require(actor, "shift.review")
        row = await self.services.database.fetchone(
            """
            SELECT m.discord_id FROM shifts s JOIN members m ON m.id=s.member_id
            WHERE s.id=? AND s.guild_id=?
            """,
            (sessao, actor.guild.id),
        )
        if not row:
            raise NotFoundError("Sessão não encontrada.")
        target = actor.guild.get_member(int(row["discord_id"]))
        voice_channel_id = (
            target.voice.channel.id if target and target.voice and target.voice.channel else None
        )
        status = await self.services.shifts.review_shift(
            actor.guild.id, sessao, acao, actor.id, motivo, voice_channel_id
        )
        await interaction.response.send_message(
            f"Sessão #{sessao} revisada: `{status.value}`.", ephemeral=True
        )

    @servico.command(name="ativos", description="Lista o efetivo atualmente em serviço.")
    async def service_active(self, interaction: discord.Interaction) -> None:
        actor = _member_from_interaction(interaction)
        await self._require(actor, "shift.view.all")
        await interaction.response.send_message(
            embed=await self.build_service_embed(actor.guild.id), ephemeral=True
        )

    @servico.command(name="painel", description="Publica ou atualiza o painel de efetivo.")
    async def service_panel(self, interaction: discord.Interaction) -> None:
        actor = _member_from_interaction(interaction)
        await self._require(actor, "panel.manage")
        await interaction.response.defer(ephemeral=True)
        await self.update_service_panel(actor.guild.id, preferred_channel=interaction.channel)
        await interaction.followup.send("Painel de efetivo atualizado.", ephemeral=True)

    async def _hours_period(self, interaction: discord.Interaction, period: str) -> None:
        member = _member_from_interaction(interaction)
        timezone_name = await self.services.settings.get(member.guild.id, "timezone")
        total = await self.services.shifts.total_for_member(
            member.guild.id, member.id, *period_bounds(period, timezone_name)
        )
        await interaction.response.send_message(
            f"Tempo válido: **{format_duration(total)}**.", ephemeral=True
        )

    @horas.command(name="hoje", description="Mostra suas horas válidas de hoje.")
    async def hours_today(self, interaction: discord.Interaction) -> None:
        await self._hours_period(interaction, "today")

    @horas.command(name="semana", description="Mostra suas horas válidas da semana.")
    async def hours_week(self, interaction: discord.Interaction) -> None:
        await self._hours_period(interaction, "week")

    @horas.command(name="mes", description="Mostra suas horas válidas do mês.")
    async def hours_month(self, interaction: discord.Interaction) -> None:
        await self._hours_period(interaction, "month")

    @horas.command(name="total", description="Mostra seu total de horas válidas.")
    async def hours_total(self, interaction: discord.Interaction) -> None:
        member = _member_from_interaction(interaction)
        total = await self.services.shifts.total_for_member(member.guild.id, member.id)
        await interaction.response.send_message(
            f"Tempo total válido: **{format_duration(total)}**.", ephemeral=True
        )

    @horas.command(name="membro", description="Consulta as horas de outro membro.")
    async def hours_member(self, interaction: discord.Interaction, membro: discord.Member) -> None:
        actor = _member_from_interaction(interaction)
        await self._require(actor, "hours.view.all")
        total = await self.services.shifts.total_for_member(actor.guild.id, membro.id)
        await interaction.response.send_message(
            f"{membro.mention}: **{format_duration(total)}** válidos.", ephemeral=True
        )

    async def build_service_embed(self, guild_id: int) -> discord.Embed:
        rows = await self.services.shifts.list_active(guild_id)
        embed = branded_embed(self.branding, title="CHOQUE - BGR • EFETIVO EM SERVIÇO")
        if not rows:
            embed.description = "Nenhum membro em serviço."
            return embed
        lines = []
        for index, row in enumerate(rows, start=1):
            channel = f"<#{row['voice_channel_id']}>" if row["voice_channel_id"] else "Tolerância"
            progress = await self.services.shifts.patrol_progress(
                guild_id, int(row["discord_id"])
            )
            validation = (
                "✅ Validado"
                if progress["requirement_met"]
                else (
                    f"⏳ {format_duration(int(progress['patrol_duration_ms']))} / "
                    f"{format_duration(int(progress['minimum_patrol_ms']))}"
                )
            )
            lines.append(
                f"**{index:02d} • {row['mta_nick']}**\n"
                f"{row['rank_name'] or 'Sem patente'} • {channel} • {validation}"
            )
        embed.description = "\n\n".join(lines)
        embed.add_field(name="Total em serviço", value=str(len(rows)), inline=False)
        return embed

    async def open_invalidated_admin(self, interaction: discord.Interaction) -> None:
        member = _member_from_interaction(interaction)
        await self._require(member, "shift.review")
        rows = await self.services.shifts.invalidated_shifts(member.guild.id)
        if not rows:
            await interaction.response.send_message(
                "✅ Nenhuma sessão invalidada aguarda eventual revisão.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=branded_embed(
                self.branding,
                title="🛡️ Sessões invalidadas",
                description=(
                    "Selecione uma sessão para consultar a decisão automática. A validação "
                    "manual é excepcional, exige justificativa e fica auditada."
                ),
            ),
            view=InvalidatedShiftView(self, rows),
            ephemeral=True,
        )

    async def update_service_panel(
        self, guild_id: int, preferred_channel: discord.abc.Messageable | None = None
    ) -> None:
        panel = await self.services.settings.get_panel(guild_id, "SERVICE")
        embed = await self.build_service_embed(guild_id)
        if panel:
            try:
                channel = self.bot.get_channel(
                    int(panel["channel_id"])
                ) or await self.bot.fetch_channel(int(panel["channel_id"]))
                message = await cast(discord.TextChannel, channel).fetch_message(
                    int(panel["message_id"])
                )
                await message.edit(embed=embed)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        channel = preferred_channel
        if channel is None:
            configured = await self.services.settings.get(guild_id, "service_panel_channel_id")
            if configured:
                channel = self.bot.get_channel(int(configured))
        if channel is None:
            return
        message = await channel.send(embed=embed)
        await self.services.settings.upsert_panel(
            guild_id, "SERVICE", message.channel.id, message.id
        )

    async def on_shift_state_change(
        self, guild_id: int, discord_id: int, status: ShiftStatus
    ) -> None:
        guild = self.bot.get_guild(guild_id)
        if guild:
            member = guild.get_member(discord_id)
            role_id = await self.services.settings.get(guild_id, "service_role_id")
            role = guild.get_role(int(role_id)) if role_id else None
            if member and role:
                try:
                    if status in {ShiftStatus.ACTIVE, ShiftStatus.GRACE}:
                        await member.add_roles(role, reason="Ponto CHOQUE ativo")
                    else:
                        await member.remove_roles(role, reason="Ponto CHOQUE encerrado")
                except discord.Forbidden:
                    await self.services.audit.record(
                        guild_id,
                        "SERVICE_ROLE_SYNC_FAILED",
                        target_id=discord_id,
                        reason="Permissão insuficiente para gerenciar o cargo",
                    )
            await self.update_service_panel(guild_id)
        await self.services.audit.deliver_pending()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return
        authorized = await self.services.permissions.has_authorized_service_role(member)
        await self.services.shifts.handle_voice_transition(
            member.guild.id,
            member.id,
            before.channel.id if before.channel else None,
            after.channel.id if after.channel else None,
            has_authorized_role=authorized,
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.roles == after.roles:
            return
        was_authorized = await self.services.permissions.has_authorized_service_role(before)
        is_authorized = await self.services.permissions.has_authorized_service_role(after)
        if was_authorized and not is_authorized:
            await self.services.shifts.finalize_role_loss(after.guild.id, after.id)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode or self._recovered:
            return
        async with self._recovery_lock:
            if self._recovered:
                return
            for guild in self.bot.guilds:
                panel_channel_id = await self.services.settings.get(
                    guild.id,
                    "point_panel_channel_id",
                )
                panel_channel = (
                    guild.get_channel(int(panel_channel_id)) if panel_channel_id else None
                )
                if isinstance(panel_channel, discord.TextChannel):
                    await self.publish_or_refresh_point_panel(guild, panel_channel)
                previous = await self.services.shifts.get_previous_heartbeat(guild.id)
                active = await self.services.shifts.list_active(guild.id)
                for row in active:
                    member = guild.get_member(int(row["discord_id"]))
                    channel_id = (
                        member.voice.channel.id
                        if member and member.voice and member.voice.channel
                        else None
                    )
                    await self.services.shifts.recover_shift(
                        guild.id, int(row["discord_id"]), channel_id, previous
                    )
                await self.services.shifts.heartbeat(guild.id, self.bot.started_at)
                await self.update_service_panel(guild.id)
            await self.services.audit.deliver_pending()
            self._recovered = True

    @tasks.loop(seconds=60)
    async def heartbeat_loop(self) -> None:
        for guild in self.bot.guilds:
            await self.services.shifts.heartbeat(guild.id, self.bot.started_at)

    @heartbeat_loop.before_loop
    async def before_heartbeat(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=60)
    async def audit_retry_loop(self) -> None:
        await self.services.audit.deliver_pending()

    @audit_retry_loop.before_loop
    async def before_audit_retry(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def service_panel_loop(self) -> None:
        for guild in self.bot.guilds:
            await self.update_service_panel(guild.id)

    @service_panel_loop.before_loop
    async def before_service_panel(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShiftCommands(bot))
