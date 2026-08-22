from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

import discord
from discord.ext import commands, tasks

from choque.embeds import branded_embed
from choque.errors import (
    ChoqueError,
    ConflictError,
    NotFoundError,
    PermissionDenied,
    ValidationError,
)
from choque.settings import MODULE_DEFINITIONS
from choque.time_utils import discord_timestamp, format_duration
from cogs.config_ui import respond_error

LOGGER = logging.getLogger(__name__)


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_member(interaction: discord.Interaction, permission: str) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "PATROLS")
    if not await bot.services.permissions.has(interaction.user, permission):
        raise PermissionDenied("Você não possui permissão para esta ação.")
    return interaction.user


async def require_admin(interaction: discord.Interaction, permission: str) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    if not await get_bot(interaction).services.permissions.has(interaction.user, permission):
        raise PermissionDenied("Você não possui permissão para esta área operacional.")
    return interaction.user


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


def status_label(value: str) -> str:
    return {
        "ON_PATROL": "🚔 Em patrulha",
        "QUEUED": "⏳ Aguardando formação",
        "AVAILABLE_FOR_PATROL": "🟢 Disponível",
        "IN_TRAINING": "🎓 Em treinamento",
        "AWAY": "📅 Afastado",
        "SUSPENDED": "⛔ Suspenso",
        "UNAVAILABLE": "⚫ Indisponível",
    }.get(value, value)


def commander_mention(discord_id: object, *, lowercase: bool = False) -> str:
    if discord_id:
        return f"<@{int(discord_id)}>"
    return "não definido" if lowercase else "Não definido"


async def patrol_central_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    queue, active, readiness = await asyncio.gather(
        bot.services.operations.queue(guild.id),
        bot.services.operations.active_patrols(guild.id),
        bot.services.operations.readiness(guild.id),
    )
    minimum = int(await bot.services.settings.get(guild.id, "minimum_patrol_members", 2))
    queue_lines = [
        f"`{index:02d}` <@{row['discord_id']}> • {row['rank_name'] or 'Sem patente'}"
        for index, row in enumerate(queue[:10], start=1)
    ]
    patrol_lines = [
        f"🚔 **PTR #{row['sequence_number']:04d}** • <#{row['voice_channel_id']}> • "
        f"{row['member_count']} integrante(s)\n"
        f"└ **Comandante:** "
        f"{commander_mention(row['commander_discord_id'])}"
        for row in active[:10]
    ]
    counts = readiness["counts"]
    embed = branded_embed(
        bot.config.branding,
        title="🚔 CENTRAL DE PATRULHA • CHOQUE - BGR",
        description=(
            "Central operacional para disponibilidade, fila FIFO e formação automática. "
            "Entre primeiro na call **Aguardando Patrulha** e então use o botão da fila.\n\n"
            f"**Formação mínima:** {minimum} militares • **Ponto:** sempre manual no painel próprio"
        ),
    )
    embed.add_field(
        name=f"⏳ Fila de formação • {len(queue)}",
        value="\n".join(queue_lines) or "Nenhum militar aguardando.",
        inline=False,
    )
    embed.add_field(
        name=f"🛡️ Patrulhas ativas • {len(active)}",
        value="\n".join(patrol_lines) or "Nenhuma patrulha em andamento.",
        inline=False,
    )
    embed.add_field(
        name="📡 Prontidão agora",
        value=(
            f"Em patrulha **{counts.get('ON_PATROL', 0)}** • "
            f"Fila **{counts.get('QUEUED', 0)}** • "
            f"Disponíveis **{counts.get('AVAILABLE_FOR_PATROL', 0)}** • "
            f"Treinamento **{counts.get('IN_TRAINING', 0)}**"
        ),
        inline=False,
    )
    return embed


async def patrol_report_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    rows = await bot.services.database.fetchall(
        """
        SELECT p.*, COUNT(pm.id) AS member_count,
               GROUP_CONCAT(pm.discord_id) AS member_ids,
               (
                   SELECT h.discord_id FROM patrol_commander_history h
                   WHERE h.patrol_id=p.id ORDER BY h.started_at DESC, h.id DESC LIMIT 1
               ) AS final_commander_discord_id
        FROM patrols p LEFT JOIN patrol_members pm ON pm.patrol_id=p.id
        WHERE p.guild_id=? AND p.status='CLOSED'
        GROUP BY p.id ORDER BY p.ended_at DESC, p.id DESC LIMIT 5
        """,
        (guild.id,),
    )
    embed = branded_embed(
        bot.config.branding,
        title="📋 RELATÓRIO PÓS-PATRULHA • CHOQUE - BGR",
        description=(
            "Consulte sua última missão, estatísticas e registre uma avaliação privada sobre "
            "um integrante da guarnição. O feedback é visível apenas ao próprio avaliado e ao Comando."
        ),
    )
    for row in rows:
        duration = max(0, int(row["ended_at"] or 0) - int(row["started_at"] or row["reserved_at"]))
        embed.add_field(
            name=f"PTR #{row['sequence_number']:04d} • {row['status']}",
            value=(
                f"Call <#{row['voice_channel_id']}> • {row['member_count']} integrante(s) • "
                f"{format_duration(duration)}\n"
                f"Comandante final: "
                f"{commander_mention(row['final_commander_discord_id'])}\n"
                f"Encerrada {discord_timestamp(int(row['ended_at']), 'R')} • "
                f"motivo `{row['end_reason'] or 'NÃO INFORMADO'}`"
            ),
            inline=False,
        )
    if not rows:
        embed.add_field(
            name="Situação", value="Nenhuma patrulha foi encerrada ainda.", inline=False
        )
    return embed


async def member_center_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title="🏠 CENTRAL DO MEMBRO • CHOQUE - BGR",
        description=(
            "Acesso unificado aos serviços da corporação. Os botões operacionais abaixo respondem "
            "de forma privada; os atalhos levam aos painéis oficiais sem criar fluxos duplicados."
        ),
    )


class PatrolCentralView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Disponível",
        emoji="🟢",
        style=discord.ButtonStyle.success,
        custom_id="choque:operations:available:v1",
        row=0,
    )
    async def available(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.queue")
        status = await get_bot(interaction).services.operations.set_availability(
            member.guild.id, member.id, True, member.id
        )
        await interaction.response.send_message(
            f"✅ Situação operacional atualizada: **{status_label(status)}**.", ephemeral=True
        )

    @discord.ui.button(
        label="Indisponível",
        emoji="⚫",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:operations:unavailable:v1",
        row=0,
    )
    async def unavailable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.queue")
        status = await get_bot(interaction).services.operations.set_availability(
            member.guild.id, member.id, False, member.id
        )
        await interaction.response.send_message(
            f"Situação operacional atualizada: **{status_label(status)}**.", ephemeral=True
        )

    @discord.ui.button(
        label="Entrar na fila",
        emoji="🚔",
        style=discord.ButtonStyle.primary,
        custom_id="choque:operations:queue:join:v1",
        row=0,
    )
    async def join_queue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.queue")
        voice_id = member.voice.channel.id if member.voice and member.voice.channel else None
        has_role = await get_bot(interaction).services.permissions.has_authorized_service_role(
            member
        )
        queue_id = await get_bot(interaction).services.operations.join_queue(
            member.guild.id, member.id, voice_id, source="PANEL", has_member_role=has_role
        )
        cog = get_bot(interaction).get_cog("OperationsCommands")
        await interaction.response.send_message(
            f"✅ Você entrou na fila FIFO. Registro **#{queue_id}**.", ephemeral=True
        )
        if cog:
            await cog.reconcile_patrols(member.guild)

    @discord.ui.button(
        label="Sair da fila",
        emoji="↩️",
        style=discord.ButtonStyle.danger,
        custom_id="choque:operations:queue:leave:v1",
        row=0,
    )
    async def leave_queue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.queue")
        removed = await get_bot(interaction).services.operations.leave_queue(
            member.guild.id, member.id
        )
        if not removed:
            raise ConflictError("Você não está na fila de patrulha.")
        await interaction.response.send_message("✅ Você saiu da fila.", ephemeral=True)

    @discord.ui.button(
        label="Minha patrulha",
        emoji="🛡️",
        style=discord.ButtonStyle.primary,
        custom_id="choque:operations:patrol:mine:v1",
        row=1,
    )
    async def my_patrol(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.view.self")
        row = await get_bot(interaction).services.operations.current_patrol(
            member.guild.id, member.id
        )
        if not row:
            await interaction.response.send_message(
                "Você não integra uma patrulha ativa neste momento.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🚔 **PTR #{row['sequence_number']:04d}** • <#{row['voice_channel_id']}> • "
            f"função `{row['member_role']}` • início {discord_timestamp(row['started_at'], 'R')}\n"
            f"**Comandante:** "
            f"{commander_mention(row['commander_discord_id'])}",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Patrulhas ativas",
        emoji="📡",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:operations:patrol:active:v1",
        row=1,
    )
    async def active(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.view.self")
        rows = await get_bot(interaction).services.operations.active_patrols(member.guild.id)
        lines = [
            f"🚔 **PTR #{row['sequence_number']:04d}** • <#{row['voice_channel_id']}> • "
            f"{row['member_count']} integrante(s) • comandante "
            f"{commander_mention(row['commander_discord_id'], lowercase=True)}"
            for row in rows
        ]
        await interaction.response.send_message(
            "\n".join(lines) or "Nenhuma patrulha ativa.", ephemeral=True
        )

    @discord.ui.button(
        label="Meu histórico",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:operations:patrol:history:v1",
        row=1,
    )
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.view.self")
        bot = get_bot(interaction)
        rows = await bot.services.operations.patrol_history(member.guild.id, member.id)
        stats = await bot.services.operations.patrol_statistics(member.guild.id, member.id)
        lines = [
            f"**PTR #{row['sequence_number']:04d}** • {format_duration(row['duration_ms'])} • "
            f"`{row['shift_validation_status'] or 'SEM PONTO'}` • comandante "
            f"{commander_mention(row['final_commander_discord_id'], lowercase=True)}"
            for row in rows
        ]
        embed = branded_embed(
            bot.config.branding,
            title="📋 Meu histórico de patrulhas",
            description="\n".join(lines) or "Nenhuma patrulha registrada.",
        )
        embed.add_field(
            name="Estatísticas",
            value=(
                f"Patrulhas **{stats['total']}** • Tempo **{format_duration(stats['total_ms'])}** • "
                f"Média **{format_duration(stats['average_ms'])}**"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Minha situação",
        emoji="🪖",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:operations:status:mine:v1",
        row=1,
    )
    async def my_status(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.view.self")
        status = await get_bot(interaction).services.operations.effective_operational_status(
            member.guild.id, member.id
        )
        await interaction.response.send_message(
            f"Sua situação operacional: **{status_label(status)}**.", ephemeral=True
        )


class FeedbackModal(ErrorModal, title="Feedback privado pós-patrulha"):
    rating = discord.ui.TextInput(
        label="Avaliação", placeholder="POSITIVO, NEUTRO ou ATENCAO", max_length=20
    )
    observation = discord.ui.TextInput(
        label="Observação objetiva", style=discord.TextStyle.paragraph, max_length=1000
    )

    def __init__(self, patrol_id: int, subject_id: int) -> None:
        super().__init__()
        self.patrol_id = patrol_id
        self.subject_id = subject_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_member(interaction, "patrol.feedback")
        normalized = str(self.rating).strip().upper()
        normalized = {
            "POSITIVO": "POSITIVE",
            "NEUTRO": "NEUTRAL",
            "ATENCAO": "NEEDS_ATTENTION",
            "ATENÇÃO": "NEEDS_ATTENTION",
        }.get(normalized, normalized)
        feedback_id = await get_bot(interaction).services.operations.add_patrol_feedback(
            member.guild.id,
            self.patrol_id,
            self.subject_id,
            member.id,
            normalized,
            str(self.observation),
        )
        await interaction.response.send_message(
            f"✅ Feedback privado **#{feedback_id}** registrado.", ephemeral=True
        )


class FeedbackSubjectSelect(discord.ui.UserSelect):
    def __init__(self, patrol_id: int) -> None:
        super().__init__(placeholder="Militar avaliado", min_values=1, max_values=1)
        self.patrol_id = patrol_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_member(interaction, "patrol.feedback")
        await interaction.response.send_modal(FeedbackModal(self.patrol_id, self.values[0].id))


class FeedbackSubjectView(ErrorView):
    def __init__(self, patrol_id: int) -> None:
        super().__init__(timeout=300)
        self.add_item(FeedbackSubjectSelect(patrol_id))


class PatrolReportView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Dados da última patrulha",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        custom_id="choque:operations:report:last:v1",
    )
    async def last(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.view.self")
        rows = await get_bot(interaction).services.operations.patrol_history(
            member.guild.id, member.id, limit=1
        )
        if not rows:
            raise NotFoundError("Você ainda não possui patrulhas registradas.")
        row = rows[0]
        commanders = await get_bot(
            interaction
        ).services.operations.patrol_commander_history(member.guild.id, int(row["id"]))
        command_lines = [
            f"{discord_timestamp(entry['started_at'], 't')}–"
            f"{discord_timestamp(entry['ended_at'], 't') if entry['ended_at'] else 'agora'} "
            f"{commander_mention(entry['discord_id'])}"
            for entry in commanders
        ]
        command_history_text = "\n".join(command_lines) or "Não definido"
        await interaction.response.send_message(
            f"🚔 **PTR #{row['sequence_number']:04d}** • <#{row['voice_channel_id']}>\n"
            f"Duração **{format_duration(row['duration_ms'])}** • ponto "
            f"`{row['shift_validation_status'] or 'SEM PONTO'}` • fim "
            f"{discord_timestamp(row['ended_at'], 'R') if row['ended_at'] else 'em andamento'}\n"
            f"**Comandantes**\n"
            f"{command_history_text}",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Avaliar patrulha",
        emoji="🎯",
        style=discord.ButtonStyle.success,
        custom_id="choque:operations:report:feedback:v1",
    )
    async def feedback(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.feedback")
        row = await get_bot(interaction).services.database.fetchone(
            """
            SELECT p.id FROM patrols p JOIN patrol_members pm ON pm.patrol_id=p.id
            WHERE p.guild_id=? AND pm.discord_id=? AND p.status='CLOSED'
            ORDER BY p.ended_at DESC, p.id DESC LIMIT 1
            """,
            (member.guild.id, member.id),
        )
        if not row:
            raise NotFoundError("Nenhuma patrulha encerrada disponível para avaliação.")
        await interaction.response.send_message(
            "Selecione um integrante da sua última patrulha. O vínculo será validado no servidor.",
            view=FeedbackSubjectView(int(row["id"])),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Meus feedbacks",
        emoji="🔒",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:operations:report:feedback-mine:v1",
    )
    async def feedback_mine(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.view.self")
        rows = await get_bot(interaction).services.operations.patrol_feedback_for_member(
            member.guild.id, member.id
        )
        lines = [
            f"**PTR #{row['sequence_number']:04d}** • `{row['rating']}` • "
            f"{row['observation'] or 'Sem observação'}"
            for row in rows
        ]
        await interaction.response.send_message(
            "\n\n".join(lines) or "Nenhum feedback recebido.", ephemeral=True
        )


class ActivitySwapModal(ErrorModal, title="Solicitar troca de atividade"):
    activity = discord.ui.TextInput(
        label="Escala ou atividade", placeholder="Ex.: Patrulha Alfa / treinamento", max_length=100
    )
    reason = discord.ui.TextInput(
        label="Motivo", style=discord.TextStyle.paragraph, max_length=1000
    )

    def __init__(self, target_id: int) -> None:
        super().__init__()
        self.target_id = target_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_member(interaction, "swap.request")
        swap_id = await get_bot(interaction).services.operations.create_activity_swap(
            member.guild.id,
            member.id,
            self.target_id,
            str(self.activity),
            str(self.reason),
        )
        target = member.guild.get_member(self.target_id)
        if target:
            try:
                await target.send(
                    f"Você recebeu a solicitação de troca **#{swap_id}** de {member.mention}. "
                    "Responda pela Central do Membro → Trocas."
                )
            except discord.Forbidden:
                pass
        await interaction.response.send_message(
            f"✅ Troca **#{swap_id}** enviada. Nada será alterado sem consentimento.",
            ephemeral=True,
        )


class ActivitySwapTargetSelect(discord.ui.UserSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Militar convidado para a troca", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_member(interaction, "swap.request")
        await interaction.response.send_modal(ActivitySwapModal(self.values[0].id))


class ActivitySwapTargetView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(ActivitySwapTargetSelect())


class ActivitySwapResponseView(ErrorView):
    def __init__(self, swap_id: int) -> None:
        super().__init__(timeout=300)
        self.swap_id = swap_id

    @discord.ui.button(label="Aceitar", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "swap.respond")
        status = await get_bot(interaction).services.operations.respond_activity_swap(
            member.guild.id, self.swap_id, member.id, True
        )
        await interaction.response.edit_message(
            content=f"✅ Consentimento registrado. Situação: `{status}`.", view=None
        )

    @discord.ui.button(label="Recusar", emoji="❌", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "swap.respond")
        status = await get_bot(interaction).services.operations.respond_activity_swap(
            member.guild.id, self.swap_id, member.id, False
        )
        await interaction.response.edit_message(
            content=f"Solicitação recusada. Situação: `{status}`.", view=None
        )


class PendingSwapSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Troca aguardando sua resposta",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['activity_name']}"[:100],
                    value=str(row["id"]),
                    description=f"Solicitante {row['requester_discord_id']}"[:100],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_member(interaction, "swap.respond")
        await interaction.response.edit_message(
            content="Confirme sua decisão. A aceitação poderá seguir para análise do Comando.",
            view=ActivitySwapResponseView(int(self.values[0])),
        )


class PendingSwapView(ErrorView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(PendingSwapSelect(rows))


class MemberOperationsView(ErrorView):
    def __init__(self, links: list[tuple[str, str, str]] | None = None) -> None:
        super().__init__(timeout=None)
        for label, emoji, url in links or []:
            self.add_item(
                discord.ui.Button(
                    label=label[:80], emoji=emoji, style=discord.ButtonStyle.link, url=url
                )
            )

    @discord.ui.button(
        label="Operações",
        emoji="🚔",
        style=discord.ButtonStyle.primary,
        custom_id="choque:operations:member:patrol:v1",
        row=0,
    )
    async def patrol(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.view.self")
        await interaction.response.send_message(
            embed=await patrol_central_embed(get_bot(interaction), member.guild),
            view=PatrolCentralView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Qualificações",
        emoji="🎖️",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:operations:member:qualifications:v1",
        row=0,
    )
    async def qualifications(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "qualification.view.self")
        matrix = await get_bot(interaction).services.operations.qualification_matrix(
            member.guild.id, discord_ids=[member.id]
        )
        entry = matrix["members"][0] if matrix["members"] else None
        lines = []
        if entry:
            for course in matrix["courses"]:
                qualification = entry["courses"].get(course["internal_code"])
                lines.append(
                    f"{'✅' if qualification and qualification['result'] == 'APPROVED' else '⬜'} "
                    f"**{course['name']}**"
                )
        await interaction.response.send_message(
            "\n".join(lines) or "Nenhuma qualificação configurada.", ephemeral=True
        )

    @discord.ui.button(
        label="Minha identidade",
        emoji="🪪",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:operations:member:identity:v1",
        row=0,
    )
    async def identity(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "patrol.view.self")
        result = await get_bot(interaction).services.rank_sync.sync_from_member(
            member, source="MEMBER_IDENTITY_PANEL", actor_id=member.id
        )
        if not result.registered:
            raise NotFoundError("Cadastro aprovado não encontrado.")
        await interaction.response.send_message(
            f"✅ Identidade conferida • patente **{result.rank_name or 'não identificada'}** • "
            f"situação `{result.sync_status}` • nick esperado `{result.expected_nickname}`.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Solicitar troca",
        emoji="🔁",
        style=discord.ButtonStyle.primary,
        custom_id="choque:operations:member:swap:v1",
        row=0,
    )
    async def swap(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_member(interaction, "swap.request")
        await interaction.response.send_message(
            "Selecione o militar com quem deseja solicitar a troca:",
            view=ActivitySwapTargetView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Responder trocas",
        emoji="📨",
        style=discord.ButtonStyle.success,
        custom_id="choque:operations:member:swap-response:v1",
        row=0,
    )
    async def swap_response(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "swap.respond")
        rows = await get_bot(interaction).services.database.fetchall(
            """
            SELECT * FROM activity_swap_requests
            WHERE guild_id=? AND target_discord_id=? AND status='WAITING_MEMBER'
            ORDER BY submitted_at, id LIMIT 25
            """,
            (member.guild.id, member.id),
        )
        if not rows:
            await interaction.response.send_message(
                "Nenhuma troca aguarda sua resposta.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Selecione uma solicitação:", view=PendingSwapView(rows), ephemeral=True
        )


class AdminMemberSelect(discord.ui.UserSelect):
    def __init__(self, mode: str) -> None:
        super().__init__(placeholder="Selecione um membro", min_values=1, max_values=1)
        self.mode = mode

    async def callback(self, interaction: discord.Interaction) -> None:
        permission = {
            "PROMOTION": "promotion.eligibility.view",
            "DOSSIER": "dossier.view",
            "RECRUIT": "recruit.evaluate",
        }[self.mode]
        await require_admin(interaction, permission)
        bot = get_bot(interaction)
        target = self.values[0]
        if self.mode == "PROMOTION":
            result = await bot.services.operations.promotion_eligibility(
                interaction.guild.id, target.id
            )
            checks = "\n".join(
                f"{'✅' if value else '❌'} {key.replace('_', ' ').title()}"
                for key, value in result["checks"].items()
            )
            next_rank = result["next_rank"]
            await interaction.response.edit_message(
                content=(
                    f"### Elegibilidade de {target.mention}\n"
                    f"Patente atual **{result['member']['rank_name']}** → "
                    f"**{next_rank['name'] if next_rank else 'topo da hierarquia'}**\n"
                    f"Tempo na patente **{result['rank_days']} dias** • "
                    f"Horas válidas **{format_duration(result['valid_hours_ms'])}**\n{checks}\n\n"
                    "Este diagnóstico apenas apoia a decisão humana; nenhuma promoção foi aplicada."
                ),
                view=None,
            )
            return
        if self.mode == "DOSSIER":
            result = await bot.services.operations.dossier(interaction.guild.id, target.id)
            await interaction.response.edit_message(
                content=(
                    f"### Dossiê resumido • {target.mention}\n"
                    f"Patente **{result['member']['rank_name'] or 'Não definida'}** • "
                    f"status `{result['member']['status']}` • "
                    f"horas válidas **{format_duration(result['valid_hours_ms'])}**\n"
                    f"Patrulhas **{result['patrol_statistics']['total']}** • "
                    f"Carreira **{len(result['personnel_actions'])}** • "
                    f"Punições **{len(result['punishments'])}** • "
                    f"Cursos **{len(result['qualifications'])}** • "
                    f"Flags **{len(result['flags'])}**"
                ),
                view=None,
            )
            return
        profile = await bot.services.operations.recruit_profile(interaction.guild.id, target.id)
        checks = "\n".join(
            f"{'✅' if value else '❌'} {key.replace('_', ' ').title()}"
            for key, value in profile["requirements"].items()
        )
        await interaction.response.edit_message(
            content=(
                f"### Acompanhamento de recruta • {target.mention}\n"
                f"Dias **{profile['days_in_corporation']}** • "
                f"Horas **{format_duration(profile['valid_hours_ms'])}** • "
                f"Patrulhas **{profile['patrols']}** • Avaliações **{profile['evaluations']}**\n"
                f"{checks}\n\nElegível para análise de efetivação: "
                f"**{'SIM' if profile['eligible_for_effective_review'] else 'NÃO'}**"
            ),
            view=RecruitEvaluationView(target.id),
        )


class AdminMemberSelectView(ErrorView):
    def __init__(self, mode: str) -> None:
        super().__init__(timeout=300)
        self.add_item(AdminMemberSelect(mode))


class RecruitEvaluationModal(ErrorModal, title="Avaliação de recruta"):
    outcome = discord.ui.TextInput(
        label="Resultado", placeholder="POSITIVO, NEUTRO ou ATENCAO", max_length=20
    )
    observation = discord.ui.TextInput(
        label="Observação", style=discord.TextStyle.paragraph, max_length=1000
    )

    def __init__(self, target_id: int) -> None:
        super().__init__()
        self.target_id = target_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction, "recruit.evaluate")
        normalized = str(self.outcome).strip().upper()
        normalized = {
            "POSITIVO": "POSITIVE",
            "NEUTRO": "NEUTRAL",
            "ATENCAO": "NEEDS_ATTENTION",
            "ATENÇÃO": "NEEDS_ATTENTION",
        }.get(normalized, normalized)
        evaluation_id = await get_bot(interaction).services.operations.add_recruit_evaluation(
            actor.guild.id, self.target_id, actor.id, normalized, str(self.observation)
        )
        await interaction.response.send_message(
            f"✅ Avaliação de acompanhamento **#{evaluation_id}** registrada.", ephemeral=True
        )


class RecruitEvaluationView(ErrorView):
    def __init__(self, target_id: int) -> None:
        super().__init__(timeout=300)
        self.target_id = target_id

    @discord.ui.button(label="Registrar avaliação", emoji="📝", style=discord.ButtonStyle.primary)
    async def evaluate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "recruit.evaluate")
        await interaction.response.send_modal(RecruitEvaluationModal(self.target_id))


class AdminSwapDecisionModal(ErrorModal, title="Decisão do Comando"):
    reason = discord.ui.TextInput(
        label="Justificativa", style=discord.TextStyle.paragraph, max_length=1000
    )

    def __init__(self, swap_id: int, approved: bool) -> None:
        super().__init__()
        self.swap_id = swap_id
        self.approved = approved

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction, "swap.review")
        status = await get_bot(interaction).services.operations.decide_activity_swap(
            actor.guild.id, self.swap_id, actor.id, self.approved, str(self.reason)
        )
        await interaction.response.send_message(
            f"✅ Decisão registrada. Situação final: `{status}`.", ephemeral=True
        )


class AdminSwapDecisionView(ErrorView):
    def __init__(self, swap_id: int) -> None:
        super().__init__(timeout=300)
        self.swap_id = swap_id

    @discord.ui.button(label="Aprovar", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "swap.review")
        await interaction.response.send_modal(AdminSwapDecisionModal(self.swap_id, True))

    @discord.ui.button(label="Negar", emoji="❌", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "swap.review")
        await interaction.response.send_modal(AdminSwapDecisionModal(self.swap_id, False))


class AdminSwapSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Troca aguardando decisão",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['activity_name']}"[:100],
                    value=str(row["id"]),
                    description=(f"{row['requester_discord_id']} ↔ {row['target_discord_id']}")[
                        :100
                    ],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction, "swap.review")
        await interaction.response.edit_message(
            content="A troca possui consentimento do membro. Registre a decisão do Comando:",
            view=AdminSwapDecisionView(int(self.values[0])),
        )


class AdminSwapSelectView(ErrorView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(AdminSwapSelect(rows))


class MaintenanceModal(ErrorModal, title="Ativar manutenção de módulo"):
    reason = discord.ui.TextInput(
        label="Motivo público", style=discord.TextStyle.paragraph, max_length=500
    )
    duration = discord.ui.TextInput(
        label="Previsão em minutos (opcional)", required=False, max_length=6
    )

    def __init__(self, module_key: str) -> None:
        super().__init__()
        self.module_key = module_key

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction, "maintenance.manage")
        duration = str(self.duration).strip()
        expected_end_at = None
        if duration:
            try:
                minutes = int(duration)
            except ValueError as exc:
                raise ValidationError("A previsão deve ser informada em minutos inteiros.") from exc
            if not 1 <= minutes <= 43_200:
                raise ValidationError("A previsão deve ficar entre 1 minuto e 30 dias.")
            expected_end_at = int(discord.utils.utcnow().timestamp() * 1000) + minutes * 60_000
        await get_bot(interaction).services.operations.set_maintenance(
            actor.guild.id,
            self.module_key,
            True,
            actor.id,
            str(self.reason),
            expected_end_at,
        )
        await interaction.response.send_message(
            f"🛠️ Módulo **{self.module_key}** colocado em manutenção.", ephemeral=True
        )


class MaintenanceActionView(ErrorView):
    def __init__(self, module_key: str) -> None:
        super().__init__(timeout=300)
        self.module_key = module_key

    @discord.ui.button(label="Ativar manutenção", emoji="🛠️", style=discord.ButtonStyle.danger)
    async def enable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "maintenance.manage")
        await interaction.response.send_modal(MaintenanceModal(self.module_key))

    @discord.ui.button(label="Encerrar manutenção", emoji="✅", style=discord.ButtonStyle.success)
    async def disable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_admin(interaction, "maintenance.manage")
        await get_bot(interaction).services.operations.set_maintenance(
            actor.guild.id,
            self.module_key,
            False,
            actor.id,
            "Manutenção encerrada pelo Comando",
        )
        await interaction.response.edit_message(
            content=f"✅ Manutenção de **{self.module_key}** encerrada.", view=None
        )


class MaintenanceModuleSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Selecione o módulo",
            options=[
                discord.SelectOption(label=label, value=key, emoji=emoji)
                for key, label, emoji in MODULE_DEFINITIONS
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction, "maintenance.manage")
        module_key = self.values[0]
        row = await get_bot(interaction).services.operations.maintenance_state(
            interaction.guild.id, module_key
        )
        state = "ATIVA" if row and row["active"] else "INATIVA"
        await interaction.response.edit_message(
            content=f"Manutenção do módulo **{module_key}**: `{state}`.",
            view=MaintenanceActionView(module_key),
        )


class MaintenanceModuleView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(MaintenanceModuleSelect())


class ChangesPeriodView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    async def show(self, interaction: discord.Interaction, days: int) -> None:
        await require_admin(interaction, "changes.view")
        data = await get_bot(interaction).services.operations.changes_summary(
            interaction.guild.id, period_days=days
        )
        labels = {
            "PATROL_CREATED": "Patrulhas formadas",
            "PATROL_FINISHED": "Patrulhas encerradas",
            "MEMBER_AVAILABILITY_CHANGED": "Disponibilidades alteradas",
            "ACTIVITY_SWAP_DECIDED": "Trocas decididas",
            "INTEGRITY_FINDINGS_CREATED": "Varreduras com achados",
            "MAINTENANCE_CHANGED": "Manutenções alteradas",
        }
        lines = [f"• **{labels.get(key, key)}:** {count}" for key, count in data["counts"].items()]
        await interaction.response.edit_message(
            content=f"### O que mudou • últimos {days} dia(s)\n"
            + ("\n".join(lines) or "Nenhum evento interno no período."),
            view=None,
        )

    @discord.ui.button(label="24 horas", style=discord.ButtonStyle.secondary)
    async def day(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, 1)

    @discord.ui.button(label="7 dias", style=discord.ButtonStyle.primary)
    async def week(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, 7)

    @discord.ui.button(label="30 dias", style=discord.ButtonStyle.secondary)
    async def month(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, 30)


class FinishPatrolModal(ErrorModal, title="Encerrar patrulha"):
    reason = discord.ui.TextInput(
        label="Motivo operacional", style=discord.TextStyle.paragraph, max_length=500
    )

    def __init__(self, patrol_id: int) -> None:
        super().__init__()
        self.patrol_id = patrol_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction, "patrol.manage")
        await get_bot(interaction).services.operations.finish_patrol(
            actor.guild.id, self.patrol_id, actor.id, str(self.reason)
        )
        cog = get_bot(interaction).get_cog("OperationsCommands")
        if cog:
            await cog.refresh_panels(actor.guild)
        await interaction.response.send_message("✅ Patrulha encerrada e auditada.", ephemeral=True)


class ActivePatrolSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Patrulha ativa para encerrar",
            options=[
                discord.SelectOption(
                    label=f"PTR #{row['sequence_number']:04d}",
                    value=str(row["id"]),
                    description=f"Call {row['voice_channel_id']} • {row['member_count']} membros",
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction, "patrol.manage")
        await interaction.response.send_modal(FinishPatrolModal(int(self.values[0])))


class ActivePatrolSelectView(ErrorView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(ActivePatrolSelect(rows))


class CommanderOverrideModal(ErrorModal, title="Confirmar comandante da patrulha"):
    reason = discord.ui.TextInput(
        label="Motivo operacional",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(self, patrol_id: int, commander_discord_id: int, voice_channel_id: int) -> None:
        super().__init__()
        self.patrol_id = patrol_id
        self.commander_discord_id = commander_discord_id
        self.voice_channel_id = voice_channel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction, "patrol.commander.override")
        channel = actor.guild.get_channel(self.voice_channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            raise NotFoundError("A call desta patrulha não está disponível.")
        present = [member.id for member in channel.members if not member.bot]
        result = await get_bot(interaction).services.operations.override_patrol_commander(
            actor.guild.id,
            self.patrol_id,
            self.commander_discord_id,
            actor.id,
            str(self.reason),
            present,
        )
        cog = get_bot(interaction).get_cog("OperationsCommands")
        if cog:
            await cog.refresh_panels(actor.guild)
        await interaction.response.send_message(
            f"✅ Comando da patrulha transferido para "
            f"{commander_mention(result['commander_discord_id'])}. O override ficou protegido.",
            ephemeral=True,
        )


class CommanderMemberSelect(discord.ui.Select):
    def __init__(self, patrol: dict[str, object], members: list) -> None:
        self.patrol = patrol
        super().__init__(
            placeholder="Militar integrante desta patrulha",
            options=[
                discord.SelectOption(
                    label=f"{row['rank_prefix'] or row['rank_name'] or 'SEM PATENTE'} • {row['mta_nick']}"[
                        :100
                    ],
                    value=str(row["discord_id"]),
                    description=f"Discord {row['discord_id']}"[:100],
                )
                for row in members[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction, "patrol.commander.override")
        await interaction.response.send_modal(
            CommanderOverrideModal(
                int(self.patrol["id"]),
                int(self.values[0]),
                int(self.patrol["voice_channel_id"]),
            )
        )


class CommanderMemberSelectView(ErrorView):
    def __init__(self, patrol: dict[str, object], members: list) -> None:
        super().__init__(timeout=300)
        self.add_item(CommanderMemberSelect(patrol, members))


class CommanderPatrolSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Patrulha para alterar o comandante",
            options=[
                discord.SelectOption(
                    label=f"PTR #{row['sequence_number']:04d}",
                    value=str(row["id"]),
                    description=(
                        f"{row['member_count']} integrantes • comandante "
                        f"{row['commander_mta_nick'] or 'não definido'}"
                    )[:100],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction, "patrol.commander.override")
        bot = get_bot(interaction)
        patrol_id = int(self.values[0])
        patrol = await bot.services.database.fetchone(
            "SELECT * FROM patrols WHERE guild_id=? AND id=? AND status='ACTIVE'",
            (interaction.guild.id, patrol_id),
        )
        if not patrol:
            raise NotFoundError("A patrulha selecionada não está mais ativa.")
        members = await bot.services.operations.active_patrol_members(
            interaction.guild.id, patrol_id
        )
        if not members:
            raise NotFoundError("A patrulha não possui integrantes ativos.")
        await interaction.response.edit_message(
            content=(
                f"### PTR #{patrol['sequence_number']:04d} • alterar comandante\n"
                "Escolha somente um integrante atual. A elegibilidade e a presença na call serão "
                "validadas novamente antes da confirmação."
            ),
            view=CommanderMemberSelectView(dict(patrol), members),
        )


class CommanderPatrolSelectView(ErrorView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(CommanderPatrolSelect(rows))


def parse_panel_bool(value: str, label: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"sim", "s", "true", "1", "ativo", "ativado"}:
        return True
    if normalized in {"nao", "não", "n", "false", "0", "inativo", "desativado"}:
        return False
    raise ValidationError(f"{label}: use SIM ou NÃO.")


class CommanderRulesModal(ErrorModal, title="Regra do comandante automático"):
    enabled = discord.ui.TextInput(label="Módulo ativo? SIM ou NÃO", max_length=10)
    require_qualification = discord.ui.TextInput(
        label="Qualificação obrigatória? SIM ou NÃO", max_length=10
    )
    minimum_rank_level = discord.ui.TextInput(
        label="Nível mínimo da patente", max_length=6
    )
    reassign_higher = discord.ui.TextInput(
        label="Trocar se superior entrar? SIM ou NÃO", max_length=10
    )

    def __init__(self, qualification_id: int | None, config: dict[str, object]) -> None:
        super().__init__()
        self.qualification_id = qualification_id
        self.priority = [str(value) for value in config["selection_priority"]]
        self.enabled.default = "SIM" if config["enabled"] else "NÃO"
        self.require_qualification.default = (
            "SIM" if config["require_qualification"] else "NÃO"
        )
        self.minimum_rank_level.default = str(config["minimum_rank_level"])
        self.reassign_higher.default = (
            "SIM" if config["reassign_when_higher_rank_joins"] else "NÃO"
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction, "patrol.commander.override")
        try:
            minimum_level = int(str(self.minimum_rank_level).strip())
        except ValueError as exc:
            raise ValidationError("O nível mínimo precisa ser um número inteiro.") from exc
        result = await get_bot(interaction).services.operations.configure_patrol_commander(
            actor.guild.id,
            actor.id,
            enabled=parse_panel_bool(str(self.enabled), "Módulo"),
            require_qualification=parse_panel_bool(
                str(self.require_qualification), "Qualificação obrigatória"
            ),
            required_qualification_id=self.qualification_id,
            minimum_rank_level=minimum_level,
            reassign_when_higher_rank_joins=parse_panel_bool(
                str(self.reassign_higher), "Troca por superior"
            ),
            selection_priority=self.priority,
        )
        await interaction.response.send_message(
            "✅ Regra salva e auditada. "
            f"Módulo **{'ativo' if result['enabled'] else 'inativo'}**, nível mínimo "
            f"**{result['minimum_rank_level']}**, qualificação "
            f"**{result['required_qualification_name'] or 'não definida'}**.",
            ephemeral=True,
        )


class CommanderQualificationSelect(discord.ui.Select):
    def __init__(self, courses: list, config: dict[str, object]) -> None:
        self.config = config
        selected = config["required_qualification_id"]
        options = [
            discord.SelectOption(
                label="Sem qualificação vinculada",
                value="none",
                default=selected is None,
            )
        ]
        options.extend(
            discord.SelectOption(
                label=str(row["name"])[:100],
                value=str(row["id"]),
                description=str(row["internal_code"])[:100],
                default=selected is not None and int(selected) == int(row["id"]),
            )
            for row in courses[:24]
        )
        super().__init__(placeholder="Qualificação de comando", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction, "patrol.commander.override")
        qualification_id = None if self.values[0] == "none" else int(self.values[0])
        await interaction.response.send_modal(CommanderRulesModal(qualification_id, self.config))


class CommanderQualificationView(ErrorView):
    def __init__(self, courses: list, config: dict[str, object]) -> None:
        super().__init__(timeout=300)
        self.add_item(CommanderQualificationSelect(courses, config))


COMMANDER_PRIORITY_PRESETS: dict[str, tuple[str, ...]] = {
    "BALANCED": (
        "QUALIFICATION",
        "RANK_LEVEL",
        "TIME_IN_RANK",
        "TOTAL_SERVICE_TIME",
        "MEMBERSHIP_TIME",
        "PATROL_JOIN_ORDER",
    ),
    "HIERARCHY": (
        "RANK_LEVEL",
        "QUALIFICATION",
        "TIME_IN_RANK",
        "TOTAL_SERVICE_TIME",
        "MEMBERSHIP_TIME",
        "PATROL_JOIN_ORDER",
    ),
    "EXPERIENCE": (
        "TOTAL_SERVICE_TIME",
        "RANK_LEVEL",
        "TIME_IN_RANK",
        "QUALIFICATION",
        "MEMBERSHIP_TIME",
        "PATROL_JOIN_ORDER",
    ),
}


class CommanderPrioritySelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Ordem de prioridade determinística",
            options=[
                discord.SelectOption(
                    label="Equilibrada",
                    value="BALANCED",
                    description="Qualificação, patente, antiguidade e serviço",
                ),
                discord.SelectOption(
                    label="Hierarquia primeiro",
                    value="HIERARCHY",
                    description="Patente antes da qualificação e experiência",
                ),
                discord.SelectOption(
                    label="Experiência operacional",
                    value="EXPERIENCE",
                    description="Horas válidas antes da patente e antiguidade",
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction, "patrol.commander.override")
        operations = get_bot(interaction).services.operations
        config = await operations.patrol_commander_config(actor.guild.id)
        result = await operations.configure_patrol_commander(
            actor.guild.id,
            actor.id,
            enabled=bool(config["enabled"]),
            require_qualification=bool(config["require_qualification"]),
            required_qualification_id=config["required_qualification_id"],
            minimum_rank_level=int(config["minimum_rank_level"]),
            reassign_when_higher_rank_joins=bool(
                config["reassign_when_higher_rank_joins"]
            ),
            selection_priority=COMMANDER_PRIORITY_PRESETS[self.values[0]],
        )
        await interaction.response.edit_message(
            content=(
                "✅ Prioridade atualizada e auditada:\n`"
                + " → ".join(result["selection_priority"])
                + "`"
            ),
            view=None,
        )


class CommanderPriorityView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(CommanderPrioritySelect())


class CommanderHistoryPatrolSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Patrulha para consultar o histórico de comando",
            options=[
                discord.SelectOption(
                    label=f"PTR #{row['sequence_number']:04d} • {row['status']}",
                    value=str(row["id"]),
                    description=f"Call {row['voice_channel_id']}"[:100],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction, "patrol.view.all")
        rows = await get_bot(interaction).services.operations.patrol_commander_history(
            interaction.guild.id, int(self.values[0])
        )
        lines = [
            f"{discord_timestamp(row['started_at'], 't')}–"
            f"{discord_timestamp(row['ended_at'], 't') if row['ended_at'] else 'agora'} • "
            f"{commander_mention(row['discord_id'])} • `{row['source']}`\n└ {row['reason']}"
            for row in rows
        ]
        await interaction.response.edit_message(
            content="### Histórico de comando\n" + ("\n\n".join(lines) or "Sem comandante registrado."),
            view=None,
        )


class CommanderHistoryPatrolView(ErrorView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(CommanderHistoryPatrolSelect(rows))


class PatrolManagementView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="Encerrar patrulha", emoji="🛑", style=discord.ButtonStyle.danger)
    async def finish(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "patrol.manage")
        rows = await get_bot(interaction).services.operations.active_patrols(interaction.guild.id)
        if not rows:
            await interaction.response.edit_message(
                content="✅ Nenhuma patrulha ativa para encerrar.", view=self
            )
            return
        await interaction.response.edit_message(
            content="Selecione a patrulha. O encerramento exigirá justificativa:",
            view=ActivePatrolSelectView(rows),
        )

    @discord.ui.button(label="Alterar comandante", emoji="🎖️", style=discord.ButtonStyle.primary)
    async def override(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "patrol.commander.override")
        rows = await get_bot(interaction).services.operations.active_patrols(interaction.guild.id)
        if not rows:
            await interaction.response.edit_message(
                content="Nenhuma patrulha ativa para gerenciar.", view=self
            )
            return
        await interaction.response.edit_message(
            content="Selecione a patrulha cujo comando será alterado:",
            view=CommanderPatrolSelectView(rows),
        )

    @discord.ui.button(label="Regra de comando", emoji="⚙️", style=discord.ButtonStyle.secondary)
    async def configure(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "patrol.commander.override")
        bot = get_bot(interaction)
        config = await bot.services.operations.patrol_commander_config(interaction.guild.id)
        courses = await bot.services.database.fetchall(
            """
            SELECT id, internal_code, name FROM course_catalog
            WHERE guild_id=? AND active=1 ORDER BY name LIMIT 24
            """,
            (interaction.guild.id,),
        )
        await interaction.response.edit_message(
            content=(
                "Selecione a qualificação operacional vinculada. Depois o formulário abrirá "
                "as regras restantes."
            ),
            view=CommanderQualificationView(courses, config),
        )

    @discord.ui.button(label="Prioridade", emoji="📐", style=discord.ButtonStyle.secondary)
    async def priority(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "patrol.commander.override")
        await interaction.response.edit_message(
            content="Escolha a ordem determinística de seleção:",
            view=CommanderPriorityView(),
        )

    @discord.ui.button(label="Histórico", emoji="📜", style=discord.ButtonStyle.secondary)
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "patrol.view.all")
        rows = await get_bot(interaction).services.database.fetchall(
            """
            SELECT id, sequence_number, status, voice_channel_id FROM patrols
            WHERE guild_id=? ORDER BY id DESC LIMIT 25
            """,
            (interaction.guild.id,),
        )
        if not rows:
            await interaction.response.edit_message(
                content="Nenhuma patrulha registrada.", view=self
            )
            return
        await interaction.response.edit_message(
            content="Selecione a patrulha para consultar a cadeia de comando:",
            view=CommanderHistoryPatrolView(rows),
        )


class OperationsAdminView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="Prontidão", emoji="📡", style=discord.ButtonStyle.primary, row=0)
    async def readiness(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "operations.view")
        data = await get_bot(interaction).services.operations.readiness(interaction.guild.id)
        lines = [f"**{status_label(key)}:** {value}" for key, value in data["counts"].items()]
        await interaction.response.edit_message(
            content="### Prontidão do efetivo\n" + "\n".join(lines), view=self
        )

    @discord.ui.button(label="Inbox", emoji="📥", style=discord.ButtonStyle.primary, row=0)
    async def inbox(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "admin.inbox.view")
        rows = await get_bot(interaction).services.operations.administrative_inbox(
            interaction.guild.id
        )
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["type"]] = counts.get(row["type"], 0) + 1
        lines = [f"• **{key}:** {value}" for key, value in counts.items()]
        await interaction.response.edit_message(
            content="### Caixa de entrada administrativa\n"
            + ("\n".join(lines) or "✅ Nenhuma pendência humana."),
            view=self,
        )

    @discord.ui.button(label="Flags de ponto", emoji="🚩", style=discord.ButtonStyle.danger, row=0)
    async def flags(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "operations.flags.review")
        bot = get_bot(interaction)
        await bot.services.operations.scan_shift_flags(interaction.guild.id)
        rows = await bot.services.operations.operational_flags(interaction.guild.id)
        lines = [
            f"**#{row['id']}** • <@{row['discord_id']}> • `{row['flag_type']}`\n└ {row['reason']}"
            for row in rows[:15]
        ]
        await interaction.response.edit_message(
            content="### Sinalizações não punitivas\n"
            + ("\n\n".join(lines) or "✅ Nenhuma sinalização aberta."),
            view=self,
        )

    @discord.ui.button(label="Integridade", emoji="🧩", style=discord.ButtonStyle.danger, row=0)
    async def integrity(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_admin(interaction, "integrity.view")
        bot = get_bot(interaction)
        snapshots = [
            {
                "discord_id": member.id,
                "role_ids": [role.id for role in member.roles],
                "display_name": member.display_name,
            }
            for member in actor.guild.members
            if not member.bot
        ]
        member_role_id = await bot.services.settings.get(actor.guild.id, "member_role_id")
        await bot.services.operations.scan_integrity(
            actor.guild.id,
            snapshots,
            member_role_id=int(member_role_id) if member_role_id else None,
        )
        rows = await bot.services.operations.integrity_findings(actor.guild.id)
        safe = sum(row["fix_class"] == "AUTO_FIX_SAFE" for row in rows)
        review = len(rows) - safe
        lines = [
            f"**#{row['id']}** • <@{row['discord_id']}> • `{row['finding_type']}` • "
            f"`{row['fix_class']}`"
            for row in rows[:15]
        ]
        await interaction.response.edit_message(
            content=(
                f"### Integridade do efetivo\nCorreções seguras **{safe}** • revisão humana "
                f"**{review}**\n\n" + ("\n".join(lines) or "✅ Nenhum achado aberto.")
            ),
            view=self,
        )

    @discord.ui.button(label="Qualificações", emoji="🎖️", style=discord.ButtonStyle.secondary, row=1)
    async def qualifications(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "qualification.view.all")
        matrix = await get_bot(interaction).services.operations.qualification_matrix(
            interaction.guild.id
        )
        lines = []
        for entry in matrix["members"][:20]:
            approved = sum(
                bool(value and value["result"] == "APPROVED") for value in entry["courses"].values()
            )
            lines.append(
                f"<@{entry['member']['discord_id']}> • **{approved}/{len(matrix['courses'])}** cursos"
            )
        await interaction.response.edit_message(
            content="### Matriz de qualificação\n"
            + ("\n".join(lines) or "Nenhum membro/curso disponível."),
            view=self,
        )

    @discord.ui.button(label="Recrutas", emoji="🪖", style=discord.ButtonStyle.secondary, row=1)
    async def recruits(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "recruit.evaluate")
        rows = await get_bot(interaction).services.operations.recruits(interaction.guild.id)
        lines = [
            f"<@{row['member']['discord_id']}> • {row['days_in_corporation']}d • "
            f"{format_duration(row['valid_hours_ms'])} • {row['patrols']} PTR • "
            f"{'✅ apto à análise' if row['eligible_for_effective_review'] else '⏳ em formação'}"
            for row in rows
        ]
        await interaction.response.edit_message(
            content="### Acompanhamento de recrutas\n"
            + ("\n".join(lines) or "Nenhum recruta identificado."),
            view=AdminMemberSelectView("RECRUIT"),
        )

    @discord.ui.button(
        label="Elegibilidade", emoji="📈", style=discord.ButtonStyle.secondary, row=1
    )
    async def promotion(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "promotion.eligibility.view")
        await interaction.response.edit_message(
            content="Selecione um membro para diagnóstico de elegibilidade (sem promoção automática):",
            view=AdminMemberSelectView("PROMOTION"),
        )

    @discord.ui.button(label="Dossiê", emoji="🗂️", style=discord.ButtonStyle.secondary, row=1)
    async def dossier(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "dossier.view")
        await interaction.response.edit_message(
            content="Selecione o membro para gerar o dossiê resumido privado:",
            view=AdminMemberSelectView("DOSSIER"),
        )

    @discord.ui.button(label="Trocas", emoji="🔁", style=discord.ButtonStyle.primary, row=2)
    async def swaps(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "swap.review")
        rows = await get_bot(interaction).services.database.fetchall(
            """
            SELECT * FROM activity_swap_requests
            WHERE guild_id=? AND status='WAITING_COMMAND'
            ORDER BY submitted_at, id LIMIT 25
            """,
            (interaction.guild.id,),
        )
        if not rows:
            await interaction.response.edit_message(
                content="✅ Nenhuma troca aguarda o Comando.", view=self
            )
            return
        await interaction.response.edit_message(
            content="Selecione a troca com consentimento para decidir:",
            view=AdminSwapSelectView(rows),
        )

    @discord.ui.button(label="Decisões", emoji="📚", style=discord.ButtonStyle.secondary, row=2)
    async def decisions(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "decisions.view")
        rows = await get_bot(interaction).services.operations.decision_history(interaction.guild.id)
        lines = [
            f"**#{row['id']}** • `{row['action']}` • <@{row['actor_id']}> • "
            f"{discord_timestamp(row['created_at'], 'R')}"
            for row in rows[:20]
        ]
        await interaction.response.edit_message(
            content="### Histórico de decisões\n"
            + ("\n".join(lines) or "Nenhuma decisão auditada."),
            view=self,
        )

    @discord.ui.button(label="O que mudou?", emoji="🆕", style=discord.ButtonStyle.secondary, row=2)
    async def changes(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "changes.view")
        await interaction.response.edit_message(
            content="Selecione o período do resumo operacional:", view=ChangesPeriodView()
        )

    @discord.ui.button(label="Identidade", emoji="🪪", style=discord.ButtonStyle.primary, row=2)
    async def identity(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_admin(interaction, "identity.manage")
        cog = get_bot(interaction).get_cog("RankSyncSystem")
        if not cog:
            raise NotFoundError("Sincronizador de identidade indisponível.")
        await interaction.response.defer(ephemeral=True)
        checked, changed = await cog.reconcile_guild(actor.guild)
        gate_counts = await get_bot(interaction).services.registration_gate.counts(actor.guild.id)
        await interaction.followup.send(
            f"✅ Sincronização em lote concluída: **{checked}** conferidos, "
            f"**{changed}** atualizados.\n"
            f"🛡️ Portaria: **{gate_counts['UNREGISTERED']}** sem cadastro • "
            f"**{gate_counts['PENDING']}** pendentes • "
            f"**{gate_counts['REQUIRES_REVIEW']}** divergentes • "
            f"**{gate_counts['MEMBERS_WITHOUT_ID']}** membros sem ID.",
            ephemeral=True,
        )

    @discord.ui.button(label="Manutenção", emoji="🛠️", style=discord.ButtonStyle.danger, row=3)
    async def maintenance(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "maintenance.manage")
        await interaction.response.edit_message(
            content="Selecione o módulo a colocar ou retirar de manutenção:",
            view=MaintenanceModuleView(),
        )

    @discord.ui.button(label="Patrulhas", emoji="🚔", style=discord.ButtonStyle.danger, row=3)
    async def patrols(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "patrol.manage")
        await interaction.response.edit_message(
            content=(
                "### Gerenciamento de patrulhas\n"
                "Comando automático, override humano, regras, prioridade, histórico e encerramento."
            ),
            view=PatrolManagementView(),
        )


class OperationsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._panel_lock = asyncio.Lock()
        self._formation_locks: dict[int, asyncio.Lock] = {}
        self._ready_guilds: set[int] = set()
        self.bot.add_view(PatrolCentralView())
        self.bot.add_view(PatrolReportView())
        self.bot.add_view(MemberOperationsView())

    async def open_admin(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction, "operations.view")
        await interaction.response.send_message(
            embed=branded_embed(
                self.bot.config.branding,
                title="🛡️ CENTRAL DE OPERAÇÕES INTELIGENTES",
                description=(
                    "Prontidão, patrulhas, integridade, qualificações e decisões em um submenu "
                    "privado. Indicadores nunca promovem, punem ou corrigem casos ambíguos sozinhos."
                ),
            ),
            view=OperationsAdminView(),
            ephemeral=True,
        )

    async def open_member(self, interaction: discord.Interaction) -> None:
        member = await require_member(interaction, "patrol.view.self")
        await interaction.response.send_message(
            embed=await member_center_embed(self.bot, member.guild),
            view=MemberOperationsView(),
            ephemeral=True,
        )

    async def open_swap(self, interaction: discord.Interaction) -> None:
        await require_member(interaction, "swap.request")
        await interaction.response.send_message(
            "Selecione o militar com quem deseja solicitar uma troca consensual:",
            view=ActivitySwapTargetView(),
            ephemeral=True,
        )

    async def open_qualification_matrix(self, interaction: discord.Interaction) -> None:
        member = await require_member(interaction, "qualification.view.self")
        matrix = await self.services.operations.qualification_matrix(
            member.guild.id, discord_ids=[member.id]
        )
        entry = matrix["members"][0] if matrix["members"] else None
        lines = []
        if entry:
            for course in matrix["courses"]:
                result = entry["courses"].get(course["internal_code"])
                lines.append(
                    f"{'✅' if result and result['result'] == 'APPROVED' else '⬜'} "
                    f"**{course['name']}**"
                )
        await interaction.response.send_message(
            "### Minha matriz de qualificação\n"
            + ("\n".join(lines) or "Nenhum curso configurado."),
            ephemeral=True,
        )

    async def open_promotion_eligibility(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction, "promotion.eligibility.view")
        await interaction.response.send_message(
            "Selecione o membro para diagnóstico, sem executar promoção:",
            view=AdminMemberSelectView("PROMOTION"),
            ephemeral=True,
        )

    async def _registry(self, guild_id: int) -> dict[str, int]:
        registry = await self.services.settings.get(guild_id, "discord_layout_registry_v2", {})
        channels = registry.get("channels", {}) if isinstance(registry, dict) else {}
        return {str(key): int(value) for key, value in channels.items() if str(value).isdigit()}

    async def configure_patrol_channels(self, guild: discord.Guild) -> None:
        channels = await self._registry(guild.id)
        waiting_id = channels.get("patrol.waiting")
        active = [
            (key, channel_id)
            for key, channel_id in channels.items()
            if key.startswith("patrol.")
            and key not in {"patrol.waiting", "patrol.availability", "patrol.report"}
            and isinstance(guild.get_channel(channel_id), discord.VoiceChannel)
        ]
        existing = {
            int(row["channel_id"]): dict(row)
            for row in await self.services.operations.patrol_channels(guild.id)
        }
        actor_id = self.bot.user.id if self.bot.user else None
        waiting_channel = guild.get_channel(waiting_id) if waiting_id else None
        if isinstance(waiting_channel, discord.VoiceChannel):
            row = existing.get(waiting_id)
            if (
                not row
                or row["channel_type"] != "WAITING"
                or not row["enabled"]
                or row["label"] != waiting_channel.name
            ):
                await self.services.operations.configure_patrol_channel(
                    guild.id, waiting_id, "WAITING", waiting_channel.name, 0, actor_id
                )
            policy = await self.services.settings.voice_channel_policy(guild.id, waiting_id)
            if not policy:
                await self.services.settings.add_voice_channel(
                    guild.id, waiting_id, waiting_channel.name, actor_id or 0
                )
            elif policy["label"] != waiting_channel.name:
                await self.services.settings.add_voice_channel(
                    guild.id, waiting_id, waiting_channel.name, actor_id or 0
                )
            await self.services.settings.set_voice_patrol_classification(
                guild.id, waiting_id, False
            )
        for index, (_key, channel_id) in enumerate(sorted(active), start=1):
            voice_channel = guild.get_channel(channel_id)
            assert isinstance(voice_channel, discord.VoiceChannel)
            row = existing.get(channel_id)
            if (
                not row
                or row["channel_type"] != "ACTIVE"
                or not row["enabled"]
                or row["label"] != voice_channel.name
            ):
                await self.services.operations.configure_patrol_channel(
                    guild.id, channel_id, "ACTIVE", voice_channel.name, index, actor_id
                )
            policy = await self.services.settings.voice_channel_policy(guild.id, channel_id)
            if not policy:
                await self.services.settings.add_voice_channel(
                    guild.id, channel_id, voice_channel.name, actor_id or 0
                )
            elif policy["label"] != voice_channel.name:
                await self.services.settings.add_voice_channel(
                    guild.id, channel_id, voice_channel.name, actor_id or 0
                )
            await self.services.settings.set_voice_patrol_classification(guild.id, channel_id, True)

    async def _upsert_panel(
        self,
        guild: discord.Guild,
        panel_type: str,
        channel: discord.TextChannel,
        embed: discord.Embed,
        view: discord.ui.View,
    ) -> discord.Message:
        async with self._panel_lock:
            panel = await self.services.settings.get_panel(guild.id, panel_type)
            if panel:
                current_channel = guild.get_channel(int(panel["channel_id"]))
                if isinstance(current_channel, discord.TextChannel):
                    try:
                        message = await current_channel.fetch_message(int(panel["message_id"]))
                        await message.edit(embed=embed, view=view)
                        return message
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass
            message = await channel.send(embed=embed, view=view)
            await self.services.settings.upsert_panel(guild.id, panel_type, channel.id, message.id)
            return message

    async def _member_links(self, guild: discord.Guild) -> list[tuple[str, str, str]]:
        channels = await self._registry(guild.id)
        definitions = (
            ("Ponto", "⏱️", "point.panel"),
            ("Solicitações", "📥", "member.requests"),
            ("Carreira", "📈", "member.career"),
            ("Disciplina", "⚖️", "member.discipline"),
            ("Atividade", "📊", "member.activity"),
            ("Ranking", "🏆", "member.ranking"),
            ("Treinamentos", "🎓", "courses.panel"),
        )
        return [
            (
                label,
                emoji,
                f"https://discord.com/channels/{guild.id}/{channels[key]}",
            )
            for label, emoji, key in definitions
            if key in channels
        ]

    async def refresh_panels(self, guild: discord.Guild) -> None:
        channels = await self._registry(guild.id)
        availability = guild.get_channel(channels.get("patrol.availability", 0))
        report = guild.get_channel(channels.get("patrol.report", 0))
        central = guild.get_channel(channels.get("member.central", 0))
        if isinstance(availability, discord.TextChannel):
            await self._upsert_panel(
                guild,
                "PATROL_CENTRAL",
                availability,
                await patrol_central_embed(self.bot, guild),
                PatrolCentralView(),
            )
        if isinstance(report, discord.TextChannel):
            await self._upsert_panel(
                guild,
                "PATROL_REPORT",
                report,
                await patrol_report_embed(self.bot, guild),
                PatrolReportView(),
            )
        if isinstance(central, discord.TextChannel):
            await self._upsert_panel(
                guild,
                "MEMBER_CENTRAL",
                central,
                await member_center_embed(self.bot, guild),
                MemberOperationsView(await self._member_links(guild)),
            )

    async def reconcile_patrol_commanders(
        self, guild: discord.Guild, *, reason: str
    ) -> int:
        changed = 0
        for patrol in await self.services.operations.active_patrols(guild.id):
            channel = guild.get_channel(int(patrol["voice_channel_id"]))
            present = (
                [member.id for member in channel.members if not member.bot]
                if isinstance(channel, discord.VoiceChannel)
                else []
            )
            result = await self.services.operations.select_patrol_commander(
                guild.id,
                int(patrol["id"]),
                present,
                reason=reason,
            )
            changed += int(bool(result["changed"]))
        return changed

    async def reconcile_patrols(self, guild: discord.Guild) -> None:
        lock = self._formation_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            waiting_id = await self.services.operations.waiting_channel_id(guild.id)
            waiting = guild.get_channel(waiting_id) if waiting_id else None
            if not isinstance(waiting, discord.VoiceChannel):
                await self.reconcile_patrol_commanders(
                    guild, reason="RESTART_RECONCILIATION"
                )
                return
            active_rows = await self.services.operations.patrol_channels(guild.id, "ACTIVE")
            free_channels = [
                channel
                for row in active_rows
                if row["enabled"]
                and isinstance(
                    (channel := guild.get_channel(int(row["channel_id"]))), discord.VoiceChannel
                )
                and not channel.members
            ]
            plans = await self.services.operations.reserve_formations(
                guild.id,
                [member.id for member in waiting.members if not member.bot],
                [channel.id for channel in free_channels],
            )
            for plan in plans:
                destination = guild.get_channel(int(plan["channel_id"]))
                if not isinstance(destination, discord.VoiceChannel):
                    await self.services.operations.rollback_formation(
                        guild.id, int(plan["patrol_id"]), "Call de destino não encontrada"
                    )
                    continue
                moved: list[discord.Member] = []
                try:
                    for discord_id in plan["member_discord_ids"]:
                        member = guild.get_member(int(discord_id))
                        if not member or not member.voice or member.voice.channel != waiting:
                            raise ValidationError("Um integrante deixou a call durante a formação.")
                        await member.move_to(
                            destination,
                            reason=f"Formação automática PTR #{plan['sequence_number']:04d}",
                        )
                        moved.append(member)
                    await self.services.operations.activate_formation(
                        guild.id,
                        int(plan["patrol_id"]),
                        [member.id for member in destination.members if not member.bot],
                    )
                except (ChoqueError, discord.DiscordException) as exc:
                    for member in moved:
                        try:
                            await member.move_to(waiting, reason="Rollback de formação de patrulha")
                        except discord.DiscordException:
                            LOGGER.warning("Falha no rollback de voz do membro %s", member.id)
                    await self.services.operations.rollback_formation(
                        guild.id, int(plan["patrol_id"]), str(exc)
                    )
                    continue
                if await self.services.settings.get(guild.id, "patrol_formation_dm_enabled", True):
                    for member in moved:
                        try:
                            await member.send(
                                f"🚔 **PTR #{plan['sequence_number']:04d} formada.** "
                                f"Destino: **{destination.name}**. O ponto permanece manual."
                            )
                        except discord.Forbidden:
                            pass
            commander_changes = await self.reconcile_patrol_commanders(
                guild, reason="PATROL_RECONCILIATION"
            )
            if plans or commander_changes:
                await self.refresh_panels(guild)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot or before.channel == after.channel:
            return
        waiting_id = await self.services.operations.waiting_channel_id(member.guild.id)
        try:
            if before.channel and before.channel.id == waiting_id:
                await self.services.operations.leave_queue(
                    member.guild.id, member.id, reason="LEFT_WAITING_VOICE"
                )
            if before.channel:
                await self.services.operations.mark_patrol_member_left(
                    member.guild.id, member.id, before.channel.id
                )
            if after.channel and after.channel.id == waiting_id:
                has_role = await self.services.permissions.has_authorized_service_role(member)
                await self.services.operations.join_queue(
                    member.guild.id,
                    member.id,
                    after.channel.id,
                    source="VOICE",
                    has_member_role=has_role,
                )
        except (NotFoundError, ValidationError, ConflictError):
            pass
        try:
            await self.reconcile_patrols(member.guild)
            await self.refresh_panels(member.guild)
        except Exception:
            LOGGER.exception("Falha ao reconciliar patrulhas da guild %s", member.guild.id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.bot:
            return
        before_roles = {role.id for role in before.roles}
        after_roles = {role.id for role in after.roles}
        if before_roles == after_roles:
            return
        try:
            changed = await self.reconcile_patrol_commanders(
                after.guild, reason="MEMBER_RANK_CHANGED"
            )
            if changed:
                await self.refresh_panels(after.guild)
        except Exception:
            LOGGER.exception(
                "Falha ao reavaliar comando após mudança de cargos na guild %s",
                after.guild.id,
            )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            if guild.id in self._ready_guilds:
                continue
            try:
                await self.configure_patrol_channels(guild)
                await self.reconcile_patrols(guild)
                await self.refresh_panels(guild)
            except Exception:
                LOGGER.exception("Falha ao restaurar Operações na guild %s", guild.id)
                continue
            self._ready_guilds.add(guild.id)
        if not self.panel_refresh_loop.is_running():
            self.panel_refresh_loop.start()
        if not self.intelligence_loop.is_running():
            self.intelligence_loop.start()
        if not self.commander_reconciliation_loop.is_running():
            self.commander_reconciliation_loop.start()

    @tasks.loop(minutes=5)
    async def panel_refresh_loop(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.refresh_panels(guild)
            except Exception:
                LOGGER.exception("Falha no refresh de Operações da guild %s", guild.id)

    @panel_refresh_loop.before_loop
    async def before_panel_refresh(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def commander_reconciliation_loop(self) -> None:
        for guild in self.bot.guilds:
            try:
                changed = await self.reconcile_patrol_commanders(
                    guild, reason="ELIGIBILITY_RECONCILIATION"
                )
                if changed:
                    await self.refresh_panels(guild)
            except Exception:
                LOGGER.exception(
                    "Falha na reconciliação de comandantes da guild %s", guild.id
                )

    @commander_reconciliation_loop.before_loop
    async def before_commander_reconciliation(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def intelligence_loop(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.services.operations.scan_shift_flags(guild.id)
            except Exception:
                LOGGER.exception("Falha na varredura operacional da guild %s", guild.id)

    @intelligence_loop.before_loop
    async def before_intelligence(self) -> None:
        await self.bot.wait_until_ready()

    async def cog_unload(self) -> None:
        self.panel_refresh_loop.cancel()
        self.intelligence_loop.cancel()
        self.commander_reconciliation_loop.cancel()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OperationsCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
