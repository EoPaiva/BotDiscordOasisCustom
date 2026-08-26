from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from choque.course_catalog_seed import COURSE_DISPLAY_NAMES, HISTORICAL_COURSES
from choque.embeds import branded_embed
from choque.errors import NotFoundError, PermissionDenied, ValidationError
from choque.time_utils import discord_timestamp
from cogs.config_ui import respond_error


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_member(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "TRAINING")
    if not await bot.services.permissions.has(interaction.user, "training.view.self"):
        raise PermissionDenied("Você não possui permissão para acessar treinamentos.")
    return interaction.user


async def require_training_admin(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    await bot.services.modules.require_enabled(interaction.guild.id, "TRAINING")
    if not await bot.services.permissions.has(interaction.user, "training.manage"):
        raise PermissionDenied("Você não possui permissão para gerenciar treinamentos.")
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
            await require_training_admin(interaction)
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True


class ErrorModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await respond_error(interaction, error)


def build_training_landing_embed(bot: ChoqueBot) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title="🎓 Treinamentos • CHOQUE - BGR",
        description=(
            "Consulte treinamentos abertos, acompanhe suas inscrições e veja seus cursos. "
            "Use os botões abaixo; todas as respostas pessoais são privadas."
        ),
    )


async def build_course_catalog_embed(bot: ChoqueBot, guild_id: int) -> discord.Embed:
    rows = await bot.services.training.catalog(guild_id)
    return branded_embed(
        bot.config.branding,
        title="🎖️ Central de Cursos • CHOQUE - BGR",
        description=(
            f"Existem **{len(rows)} curso(s) ativo(s)**. Cada curso possui uma mensagem própria "
            "no canal correspondente, com requisitos, situação e ação de candidatura.\n\n"
            "**Fluxo:** requisitos → solicitação → análise humana → convocação → "
            "treinamento → qualificação e cargo."
        ),
    )


async def build_course_panel_embed(
    bot: ChoqueBot, guild_id: int, course_id: int
) -> discord.Embed:
    row = await bot.services.training.course_by_id(guild_id, course_id)
    if not row:
        raise NotFoundError("Curso ativo não encontrado.")
    requirements = await bot.services.training.course_requirements(guild_id, course_id)
    requirement_lines = [
        f"• Cargo/curso: <@&{requirement['required_role_id']}>"
        for requirement in requirements
    ]
    if row["minimum_rank_level"] is not None:
        rank = await bot.services.database.fetchone(
            """
            SELECT name FROM ranks WHERE guild_id=? AND level>=?
            ORDER BY level, id LIMIT 1
            """,
            (guild_id, row["minimum_rank_level"]),
        )
        rank_label = str(rank["name"]) if rank else f"nível {row['minimum_rank_level']}"
        requirement_lines.append(f"• Patente mínima: **{rank_label}**")
    minimum_hours = int(row["minimum_valid_hours_ms"]) / 3_600_000
    if minimum_hours:
        requirement_lines.append(f"• Bate-ponto válido: **{minimum_hours:g}h**")
    if int(row["minimum_tenure_days"]):
        requirement_lines.append(
            f"• Tempo de corporação: **{row['minimum_tenure_days']} dia(s)**"
        )
    if row["prerequisite_course_name"]:
        requirement_lines.append(
            f"• Curso anterior: **{row['prerequisite_course_name']}**"
        )
    if bool(row["require_no_active_suspension"]):
        requirement_lines.append("• Não possuir suspensão ativa")
    if bool(row["require_no_active_adv"]):
        requirement_lines.append("• Não possuir ADV ativa")
    if not requirement_lines:
        requirement_lines.append("• Cadastro ativo na CHOQUE")
    status = "🟢 Solicitações abertas" if row["enrollment_status"] == "OPEN" else "🔒 Fechado"
    source_url = (
        f"https://discord.com/channels/{guild_id}/{row['source_channel_id']}/"
        f"{row['source_message_id']}"
    )
    embed = branded_embed(
        bot.config.branding,
        title=f"🎓 {row['name']}",
        description=str(row["description"]),
    )
    embed.add_field(name="Requisitos", value="\n".join(requirement_lines), inline=False)
    embed.add_field(name="Situação", value=status)
    embed.add_field(name="Nota mínima", value=f"**{row['passing_score']}**")
    embed.add_field(name="Nova tentativa", value=f"**{row['cooldown_days']} dia(s)**")
    embed.add_field(
        name="Processo",
        value=(
            "A elegibilidade é validada no servidor. A decisão e o resultado do treinamento "
            "permanecem humanos. A conclusão registra o histórico e sincroniza o cargo."
        ),
        inline=False,
    )
    embed.add_field(name="Edital de origem", value=f"[Consultar mensagem]({source_url})")
    embed.set_footer(text=f"CHOQUE - BGR • Curso {row['internal_code']}")
    return embed


class CourseApplicationButton(discord.ui.Button[discord.ui.View]):
    def __init__(
        self, internal_code: str, label: str, row: int = 0, *, disabled: bool = False
    ) -> None:
        super().__init__(
            label=label,
            emoji="📝",
            style=discord.ButtonStyle.primary,
            custom_id=f"choque:course:apply:{internal_code}:v1",
            row=row,
            disabled=disabled,
        )
        self.internal_code = internal_code

    async def callback(self, interaction: discord.Interaction) -> None:
        member = await require_member(interaction)
        bot = get_bot(interaction)
        result = await bot.services.training.apply_to_course(
            member.guild.id,
            member.id,
            self.internal_code,
            (role.id for role in member.roles),
        )
        await interaction.response.send_message(
            embed=branded_embed(
                bot.config.branding,
                title="✅ Solicitação de curso registrada",
                description=(
                    f"**Curso:** {result['course_name']}\n"
                    f"**Protocolo:** `#{result['application_id']}`\n"
                    "**Situação:** aguardando análise humana do Instrutor/Comando.\n\n"
                    "A aprovação autoriza sua convocação; o cargo do curso somente é concedido "
                    "após conclusão e resultado do treinamento."
                ),
            ),
            ephemeral=True,
        )


class CourseCatalogView(MemberView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        for index, seed in enumerate(HISTORICAL_COURSES):
            self.add_item(
                CourseApplicationButton(
                    seed.internal_code,
                    COURSE_DISPLAY_NAMES[seed.internal_code],
                    index // 5,
                )
            )


class CoursePanelView(MemberView):
    def __init__(self, internal_code: str, label: str, *, enrollment_open: bool) -> None:
        super().__init__(timeout=None)
        self.add_item(
            CourseApplicationButton(
                internal_code,
                label="Candidatar-me" if enrollment_open else "Inscrições fechadas",
                disabled=not enrollment_open,
            )
        )


async def build_event_embed(bot: ChoqueBot, guild_id: int, training_id: int) -> discord.Embed:
    event = await bot.services.training.get_training(guild_id, training_id)
    if not event:
        raise NotFoundError("Treinamento não encontrado.")
    status_labels = {
        "OPEN": "🟢 Inscrições abertas",
        "CLOSED": "🟡 Inscrições encerradas",
        "COMPLETED": "✅ Finalizado",
        "CANCELLED": "❌ Cancelado",
    }
    embed = branded_embed(
        bot.config.branding,
        title=f"🎓 {event['name']}",
        description=str(event["description"]),
    )
    embed.add_field(name="Responsável", value=f"<@{event['responsible_id']}>")
    embed.add_field(name="Data e horário", value=discord_timestamp(event["scheduled_at"], "F"))
    embed.add_field(name="Vagas", value=f"**{event['enrolled_count']} / {event['capacity']}**")
    embed.add_field(name="Situação", value=status_labels[str(event["status"])])
    embed.add_field(name="Curso/qualificação", value=event["course_name"] or event["name"])
    embed.add_field(name="Identificador", value=f"`#{event['id']}`")
    if event["status"] == "CANCELLED":
        embed.add_field(
            name="Cancelamento",
            value=event["cancel_reason"] or "Sem motivo informado",
            inline=False,
        )
    return embed


def event_link(guild_id: int, row: dict | object) -> str | None:
    channel_id = row["channel_id"]
    message_id = row["message_id"]
    if not channel_id or not message_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


class TrainingPanelView(MemberView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Treinamentos abertos",
        emoji="🎓",
        style=discord.ButtonStyle.primary,
        custom_id="choque:training:open:v1",
    )
    async def open_trainings(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        rows = await get_bot(interaction).services.training.open_trainings(member.guild.id)
        if not rows:
            await interaction.response.send_message(
                "Nenhum treinamento possui inscrições abertas no momento.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Selecione um treinamento para consultar ou participar:",
            view=OpenTrainingSelectView(rows),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Meus treinamentos",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:training:mine:v1",
    )
    async def my_trainings(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        rows = await get_bot(interaction).services.training.member_trainings(
            member.guild.id, member.id
        )
        lines: list[str] = []
        for row in rows:
            icon = "✅" if row["enrollment_status"] == "ENROLLED" else "❌"
            result = ""
            if row["training_status"] == "COMPLETED":
                result = (
                    f" • presença `{row['attendance_status']}` • resultado `{row['result_status']}`"
                )
            link = event_link(member.guild.id, row)
            title = f"[{row['name']}]({link})" if link else f"**{row['name']}**"
            lines.append(
                f"{icon} {title} • {discord_timestamp(row['scheduled_at'], 'f')}\n"
                f"└ `{row['training_status']}`{result}"
            )
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title="📋 Meus treinamentos",
            description="\n\n".join(lines) or "Você ainda não possui inscrições.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Meus cursos",
        emoji="🏅",
        style=discord.ButtonStyle.success,
        custom_id="choque:training:courses:v1",
    )
    async def my_courses(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        rows = await get_bot(interaction).services.training.member_courses(
            member.guild.id, member.id
        )
        lines = [
            f"{'✅' if row['result'] == 'APPROVED' else '❌'} **{row['course_name']}** • "
            f"{discord_timestamp(row['recorded_at'], 'd')}\n└ Responsável: <@{row['responsible_id']}>"
            for row in rows
        ]
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title="🏅 Meus cursos e qualificações",
            description="\n\n".join(lines) or "Nenhum curso concluído foi registrado.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Matriz de qualificação",
        emoji="🧭",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:training:matrix:v1",
    )
    async def qualification_matrix(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        cog = get_bot(interaction).get_cog("OperationsCommands")
        if cog is None:
            raise NotFoundError("A matriz de qualificação não está disponível.")
        await cog.open_qualification_matrix(interaction)


class OpenTrainingSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Escolha um treinamento",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['name']}"[:100],
                    value=str(row["id"]),
                    description=(
                        f"Vagas {row['enrolled_count']}/{row['capacity']} • "
                        f"responsável {row['responsible_id']}"
                    )[:100],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        event_id = int(self.values[0])
        await interaction.response.edit_message(
            content=None,
            embed=await build_event_embed(get_bot(interaction), interaction.guild.id, event_id),
            view=TrainingEventView(event_id, persistent=False),
        )


class OpenTrainingSelectView(MemberView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(OpenTrainingSelect(rows))


class TrainingEventView(MemberView):
    def __init__(self, training_id: int, *, persistent: bool = True) -> None:
        super().__init__(timeout=None if persistent else 300)
        self.training_id = training_id
        suffix = f":{training_id}:v1"
        self.join.custom_id = "choque:training:join" + suffix
        self.cancel.custom_id = "choque:training:cancel" + suffix
        self.details.custom_id = "choque:training:details" + suffix

    @discord.ui.button(label="Participar", emoji="✅", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        bot = get_bot(interaction)
        result = await bot.services.training.enroll(member.guild.id, self.training_id, member.id)
        cog = bot.get_cog("TrainingCommands")
        if cog:
            await cog.refresh_event_message(member.guild, self.training_id)
        await interaction.response.send_message(
            f"✅ Inscrição confirmada. Vagas: **{result['enrolled_count']}/{result['capacity']}**.",
            ephemeral=True,
        )

    @discord.ui.button(label="Cancelar participação", emoji="❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction)
        bot = get_bot(interaction)
        result = await bot.services.training.cancel_enrollment(
            member.guild.id, self.training_id, member.id
        )
        cog = bot.get_cog("TrainingCommands")
        if cog:
            await cog.refresh_event_message(member.guild, self.training_id)
        await interaction.response.send_message(
            f"✅ Participação cancelada. Vagas: **{result['enrolled_count']}/{result['capacity']}**.",
            ephemeral=True,
        )

    @discord.ui.button(label="Detalhes", emoji="ℹ️", style=discord.ButtonStyle.secondary)
    async def details(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_member(interaction)
        await interaction.response.send_message(
            embed=await build_event_embed(
                get_bot(interaction), interaction.guild.id, self.training_id
            ),
            ephemeral=True,
        )


def build_course_application_embed(bot: ChoqueBot, row: object) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title=f"📨 Solicitação de curso #{row['id']}",
        description=(
            f"**Membro:** <@{row['discord_id']}>\n"
            f"**Nick MTA:** `{row['mta_nick']}`\n"
            f"**Curso:** {row['course_name']}\n"
            f"**Nota mínima:** {row['passing_score']}\n"
            f"**Recebida:** {discord_timestamp(row['submitted_at'], 'F')}\n\n"
            "A elegibilidade foi validada no envio. A decisão final permanece humana."
        ),
    )
    return embed


class CourseApplicationDecisionModal(ErrorModal):
    reason = discord.ui.TextInput(
        label="Motivo da decisão",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(self, application_id: int, *, approved: bool) -> None:
        super().__init__(title="Aprovar solicitação" if approved else "Rejeitar solicitação")
        self.application_id = application_id
        self.approved = approved

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_training_admin(interaction)
        bot = get_bot(interaction)
        result = await bot.services.training.decide_course_application(
            actor.guild.id,
            self.application_id,
            actor.id,
            approved=self.approved,
            reason=str(self.reason),
        )
        target = actor.guild.get_member(int(result["discord_id"]))
        if target is not None:
            try:
                await target.send(
                    f"Sua solicitação do curso **{result['course_name']}** foi "
                    f"**{result['status']}**. Motivo: {result['reason']}"
                )
            except discord.Forbidden:
                pass
        await interaction.response.edit_message(
            embed=branded_embed(
                bot.config.branding,
                title="✅ Solicitação analisada",
                description=(
                    f"**Protocolo:** `#{self.application_id}`\n"
                    f"**Curso:** {result['course_name']}\n"
                    f"**Resultado:** `{result['status']}`\n"
                    f"**Motivo:** {result['reason']}"
                ),
            ),
            view=None,
        )


class CourseApplicationDecisionView(AdminView):
    def __init__(self, application_id: int) -> None:
        super().__init__(timeout=300)
        self.application_id = application_id

    @discord.ui.button(label="Aprovar", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            CourseApplicationDecisionModal(self.application_id, approved=True)
        )

    @discord.ui.button(label="Rejeitar", emoji="❌", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            CourseApplicationDecisionModal(self.application_id, approved=False)
        )


class CourseApplicationSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Selecione a solicitação",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['course_name']}"[:100],
                    value=str(row["id"]),
                    description=f"{row['mta_nick']} • membro {row['discord_id']}"[:100],
                )
                for row in rows[:25]
            ],
        )
        self.rows = {int(row["id"]): row for row in rows}

    async def callback(self, interaction: discord.Interaction) -> None:
        application_id = int(self.values[0])
        row = self.rows[application_id]
        await interaction.response.edit_message(
            content=None,
            embed=build_course_application_embed(get_bot(interaction), row),
            view=CourseApplicationDecisionView(application_id),
        )


class CourseApplicationQueueView(AdminView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(CourseApplicationSelect(rows))


class CoursePanelChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, course_id: int) -> None:
        self.course_id = course_id
        super().__init__(
            placeholder="Selecione o canal exclusivo deste curso",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_training_admin(interaction)
        selected = actor.guild.get_channel(int(self.values[0].id))
        if not isinstance(selected, discord.TextChannel):
            raise ValidationError("Selecione um canal de texto do servidor.")
        bot = get_bot(interaction)
        result = await bot.services.training.configure_course_panel_channel(
            actor.guild.id, self.course_id, selected.id, actor.id
        )
        cog = bot.get_cog("TrainingCommands")
        if not isinstance(cog, TrainingCommands):
            raise NotFoundError("O módulo de cursos não está disponível.")
        message = await cog.publish_course_panel(actor.guild, self.course_id, selected)
        await interaction.response.edit_message(
            content=(
                f"✅ Painel de **{result['course_name']}** publicado em {selected.mention}: "
                f"{message.jump_url}"
            ),
            view=None,
        )


class CoursePanelChannelView(AdminView):
    def __init__(self, course_id: int) -> None:
        super().__init__(timeout=300)
        self.add_item(CoursePanelChannelSelect(course_id))


class CoursePanelCourseSelect(discord.ui.Select):
    def __init__(self, courses: list) -> None:
        super().__init__(
            placeholder="Selecione o curso que terá painel próprio",
            options=[
                discord.SelectOption(
                    label=str(row["name"])[:100],
                    value=str(row["id"]),
                    description=(
                        f"{row['enrollment_status']} • "
                        f"canal {row['panel_channel_id'] or 'a definir'}"
                    )[:100],
                )
                for row in courses[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_training_admin(interaction)
        await interaction.response.edit_message(
            content="Agora selecione o canal exclusivo do curso:",
            view=CoursePanelChannelView(int(self.values[0])),
        )


class CoursePanelCourseView(AdminView):
    def __init__(self, courses: list) -> None:
        super().__init__(timeout=300)
        self.add_item(CoursePanelCourseSelect(courses))


class TrainingAdminView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="Criar treinamento", emoji="➕", style=discord.ButtonStyle.success)
    async def create(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "Selecione o responsável pelo treinamento:",
            view=TrainingResponsibleView(),
            ephemeral=True,
        )

    @discord.ui.button(label="Treinamentos ativos", emoji="🎓", style=discord.ButtonStyle.primary)
    async def active(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await get_bot(interaction).services.training.active_trainings(interaction.guild.id)
        if not rows:
            raise NotFoundError("Não há treinamentos ativos.")
        await interaction.response.send_message(
            "Selecione um treinamento para gerenciar:",
            view=ActiveTrainingSelectView(rows),
            ephemeral=True,
        )

    @discord.ui.button(label="Histórico", emoji="📚", style=discord.ButtonStyle.secondary)
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await get_bot(interaction).services.training.history(interaction.guild.id)
        lines = [
            (
                f"{'✅' if row['status'] == 'COMPLETED' else '❌'} **#{row['id']} • "
                f"{row['name']}** `{row['status']}`\n"
                f"{discord_timestamp(row['scheduled_at'], 'f')} • participantes "
                f"**{row['participants']}** • aprovados **{row['approved']}** • "
                f"reprovados **{row['failed']}**"
            )
            for row in rows
        ]
        await interaction.response.send_message(
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title="📚 Histórico de treinamentos",
                description="\n\n".join(lines) or "Nenhum treinamento foi encerrado.",
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Solicitações de curso", emoji="📨", style=discord.ButtonStyle.primary)
    async def course_applications(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        rows = await get_bot(interaction).services.training.pending_course_applications(
            interaction.guild.id
        )
        if not rows:
            raise NotFoundError("Não há solicitações de curso aguardando análise.")
        await interaction.response.send_message(
            "Selecione uma solicitação de curso:",
            view=CourseApplicationQueueView(rows),
            ephemeral=True,
        )

    @discord.ui.button(label="Painéis por curso", emoji="🧭", style=discord.ButtonStyle.secondary)
    async def course_panels(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        courses = await get_bot(interaction).services.training.catalog(interaction.guild.id)
        if not courses:
            raise NotFoundError("Não há cursos ativos para configurar.")
        await interaction.response.send_message(
            "Escolha um curso. Cada um manterá sua própria mensagem persistente:",
            view=CoursePanelCourseView(courses),
            ephemeral=True,
        )


class TrainingResponsibleSelect(discord.ui.UserSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Escolha o responsável", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_training_admin(interaction)
        responsible = actor.guild.get_member(self.values[0].id)
        if not responsible:
            raise NotFoundError("O responsável não está mais no servidor.")
        if not await get_bot(interaction).services.members.get(actor.guild.id, responsible.id):
            raise NotFoundError("O responsável precisa possuir cadastro aprovado.")
        await interaction.response.send_modal(CreateTrainingModal(responsible.id))


class TrainingResponsibleView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(TrainingResponsibleSelect())


class CreateTrainingModal(ErrorModal, title="Criar treinamento"):
    name = discord.ui.TextInput(label="Nome", min_length=3, max_length=100)
    date_time = discord.ui.TextInput(
        label="Data e horário (DD/MM/AAAA HH:MM)", placeholder="25/08/2026 21:00", max_length=16
    )
    capacity = discord.ui.TextInput(label="Número de vagas", placeholder="20", max_length=3)
    course_name = discord.ui.TextInput(
        label="Curso/qualificação concedida", required=False, max_length=100
    )
    description = discord.ui.TextInput(
        label="Descrição", style=discord.TextStyle.paragraph, min_length=3, max_length=1000
    )

    def __init__(self, responsible_id: int) -> None:
        super().__init__()
        self.responsible_id = responsible_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_training_admin(interaction)
        if not str(self.capacity).strip().isdigit():
            raise ValidationError("Informe um número de vagas válido.")
        bot = get_bot(interaction)
        timezone_name = await bot.services.settings.get(actor.guild.id, "timezone")
        try:
            scheduled = datetime.strptime(str(self.date_time).strip(), "%d/%m/%Y %H:%M").replace(
                tzinfo=ZoneInfo(timezone_name)
            )
        except ValueError as exc:
            raise ValidationError(
                "Use data e horário válidos no formato DD/MM/AAAA HH:MM."
            ) from exc
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await bot.services.training.create_training(
            actor.guild.id,
            actor.id,
            name=str(self.name),
            description=str(self.description),
            scheduled_at=int(scheduled.timestamp() * 1000),
            responsible_id=self.responsible_id,
            capacity=int(str(self.capacity)),
            course_name=str(self.course_name),
        )
        cog = bot.get_cog("TrainingCommands")
        if cog is None:
            raise NotFoundError("O módulo de treinamentos não está disponível.")
        message = await cog.publish_event(actor.guild, int(result["training_id"]))
        await interaction.followup.send(
            f"✅ Treinamento **#{result['training_id']}** criado e publicado: {message.jump_url}",
            ephemeral=True,
        )


class ActiveTrainingSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Escolha um treinamento ativo",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['name']}"[:100],
                    value=str(row["id"]),
                    description=(
                        f"{row['status']} • {row['enrolled_count']}/{row['capacity']} inscritos • "
                        f"{row['pending_count']} pendentes"
                    )[:100],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        event_id = int(self.values[0])
        await interaction.response.edit_message(
            content=None,
            embed=await build_event_embed(get_bot(interaction), interaction.guild.id, event_id),
            view=TrainingManagementView(event_id),
        )


class ActiveTrainingSelectView(AdminView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(ActiveTrainingSelect(rows))


async def build_roster_embed(bot: ChoqueBot, guild_id: int, training_id: int) -> discord.Embed:
    rows = await bot.services.training.enrollments(guild_id, training_id)
    lines = [
        f"{index}. <@{row['discord_id']}> • `{row['attendance_status']}` • `{row['result_status']}`"
        for index, row in enumerate(rows, start=1)
    ]
    return branded_embed(
        bot.config.branding,
        title=f"👥 Participantes • Treinamento #{training_id}",
        description="\n".join(lines) or "Nenhum membro inscrito.",
    )


class TrainingManagementView(AdminView):
    def __init__(self, training_id: int) -> None:
        super().__init__(timeout=300)
        self.training_id = training_id

    @discord.ui.button(label="Participantes", emoji="👥", style=discord.ButtonStyle.secondary)
    async def participants(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await build_roster_embed(
                get_bot(interaction), interaction.guild.id, self.training_id
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Encerrar inscrições", emoji="🔒", style=discord.ButtonStyle.primary)
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_training_admin(interaction)
        bot = get_bot(interaction)
        await bot.services.training.close_enrollment(actor.guild.id, self.training_id, actor.id)
        cog = bot.get_cog("TrainingCommands")
        if cog:
            await cog.refresh_event_message(actor.guild, self.training_id)
        await interaction.response.send_message("✅ Inscrições encerradas.", ephemeral=True)

    @discord.ui.button(label="Finalizar", emoji="✅", style=discord.ButtonStyle.success)
    async def finalize(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await get_bot(interaction).services.training.enrollments(
            interaction.guild.id, self.training_id
        )
        await interaction.response.send_message(
            embed=await build_roster_embed(
                get_bot(interaction), interaction.guild.id, self.training_id
            ),
            view=FinalizeTrainingView(self.training_id, rows),
            ephemeral=True,
        )

    @discord.ui.button(label="Cancelar treinamento", emoji="❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CancelTrainingModal(self.training_id))


class ParticipantSelect(discord.ui.Select):
    def __init__(self, training_id: int, rows: list) -> None:
        self.training_id = training_id
        super().__init__(
            placeholder="Escolha um participante para avaliar",
            options=[
                discord.SelectOption(
                    label=f"{row['mta_nick']} • {row['discord_id']}"[:100],
                    value=str(row["discord_id"]),
                    description=(
                        f"Presença {row['attendance_status']} • Resultado {row['result_status']}"
                    )[:100],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content=f"Defina a situação de <@{self.values[0]}>:",
            embed=None,
            view=ParticipantDecisionView(self.training_id, int(self.values[0])),
        )


class FinalizeTrainingView(AdminView):
    def __init__(self, training_id: int, rows: list) -> None:
        super().__init__(timeout=600)
        self.training_id = training_id
        if rows:
            self.add_item(ParticipantSelect(training_id, rows))

    @discord.ui.button(label="Concluir treinamento", emoji="🏁", style=discord.ButtonStyle.success)
    async def complete(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_training_admin(interaction)
        bot = get_bot(interaction)
        result = await bot.services.training.complete_training(
            actor.guild.id, self.training_id, actor.id
        )
        cog = bot.get_cog("TrainingCommands")
        if cog:
            await cog.refresh_event_message(actor.guild, self.training_id)
        await interaction.response.edit_message(
            content=(
                f"✅ Treinamento concluído: **{result['participants']}** participante(s), "
                f"**{result['approved']}** aprovado(s) e **{result['failed']}** reprovado(s)."
            ),
            embed=None,
            view=None,
        )


class ParticipantDecisionView(AdminView):
    def __init__(self, training_id: int, discord_id: int) -> None:
        super().__init__(timeout=600)
        self.training_id = training_id
        self.discord_id = discord_id

    @discord.ui.button(label="Presente e aprovado", emoji="✅", style=discord.ButtonStyle.success)
    async def approved(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_training_admin(interaction)
        await interaction.response.send_modal(
            TrainingEvaluationModal(self.training_id, self.discord_id, "PRESENT", "APPROVED")
        )

    @discord.ui.button(label="Presente e reprovado", emoji="⚠️", style=discord.ButtonStyle.primary)
    async def failed(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_training_admin(interaction)
        await interaction.response.send_modal(
            TrainingEvaluationModal(self.training_id, self.discord_id, "PRESENT", "FAILED")
        )

    @discord.ui.button(label="Ausente", emoji="❌", style=discord.ButtonStyle.danger)
    async def absent(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_training_admin(interaction)
        await interaction.response.send_modal(
            TrainingEvaluationModal(self.training_id, self.discord_id, "ABSENT", "FAILED")
        )


class TrainingEvaluationModal(ErrorModal, title="Avaliação pós-treinamento"):
    performance = discord.ui.TextInput(
        label="Desempenho",
        placeholder="EXCELENTE, BOM, REGULAR ou INSUFICIENTE",
        max_length=20,
    )
    observation = discord.ui.TextInput(
        label="Observação técnica",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )

    def __init__(
        self, training_id: int, discord_id: int, attendance: str, result: str
    ) -> None:
        super().__init__()
        self.training_id = training_id
        self.discord_id = discord_id
        self.attendance = attendance
        self.result = result

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_training_admin(interaction)
        performance = str(self.performance).strip().upper()
        performance = {
            "EXCELENTE": "EXCELLENT",
            "BOM": "GOOD",
            "REGULAR": "REGULAR",
            "INSUFICIENTE": "INSUFFICIENT",
        }.get(performance, performance)
        bot = get_bot(interaction)
        await bot.services.training.decide_participant(
            actor.guild.id,
            self.training_id,
            self.discord_id,
            actor.id,
            attendance=self.attendance,
            result=self.result,
            performance=performance,
            notes=str(self.observation),
        )
        rows = await bot.services.training.enrollments(actor.guild.id, self.training_id)
        await interaction.response.send_message(
            content="✅ Avaliação pós-treinamento registrada.",
            embed=await build_roster_embed(bot, actor.guild.id, self.training_id),
            view=FinalizeTrainingView(self.training_id, rows),
            ephemeral=True,
        )


class CancelTrainingModal(ErrorModal, title="Cancelar treinamento"):
    reason = discord.ui.TextInput(
        label="Motivo do cancelamento",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(self, training_id: int) -> None:
        super().__init__()
        self.training_id = training_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_training_admin(interaction)
        bot = get_bot(interaction)
        await bot.services.training.cancel_training(
            actor.guild.id, self.training_id, actor.id, str(self.reason)
        )
        cog = bot.get_cog("TrainingCommands")
        if cog:
            await cog.refresh_event_message(actor.guild, self.training_id)
        rows = await bot.services.training.enrollments(actor.guild.id, self.training_id)
        for row in rows:
            target = actor.guild.get_member(int(row["discord_id"]))
            if target:
                try:
                    await target.send(
                        f"O treinamento #{self.training_id} foi cancelado. Motivo: {self.reason}"
                    )
                except discord.Forbidden:
                    pass
        await interaction.response.send_message(
            f"✅ Treinamento **#{self.training_id}** cancelado.", ephemeral=True
        )


class TrainingCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._panel_lock = asyncio.Lock()
        self._catalog_lock = asyncio.Lock()
        self.bot.add_view(TrainingPanelView())
        self.bot.add_view(CourseCatalogView())

    async def cog_load(self) -> None:
        for row in await self.services.training.persistent_events():
            self.bot.add_view(TrainingEventView(int(row["id"])), message_id=int(row["message_id"]))
        rows = await self.services.database.fetchall(
            """
            SELECT c.internal_code, c.name, c.enrollment_status, p.message_id
            FROM course_panel_messages p
            JOIN course_catalog c ON c.id=p.course_id AND c.guild_id=p.guild_id
            WHERE c.active=1
            """
        )
        for row in rows:
            self.bot.add_view(
                CoursePanelView(
                    str(row["internal_code"]),
                    str(row["name"]),
                    enrollment_open=str(row["enrollment_status"]) == "OPEN",
                ),
                message_id=int(row["message_id"]),
            )

    async def open_admin(self, interaction: discord.Interaction) -> None:
        await require_training_admin(interaction)
        await interaction.response.send_message(
            embed=branded_embed(
                self.bot.config.branding,
                title="🎓 Gestão de Treinamentos",
                description=(
                    "Crie treinamentos, acompanhe inscrições, registre presença e resultado e "
                    "consulte o histórico. Decisões continuam humanas e auditadas."
                ),
            ),
            view=TrainingAdminView(),
            ephemeral=True,
        )

    async def publish_or_refresh(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        async with self._panel_lock:
            panel = await self.services.settings.get_panel(guild.id, "TRAINING")
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                    await message.edit(
                        embed=build_training_landing_embed(self.bot), view=TrainingPanelView()
                    )
                    return message
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            message = await channel.send(
                embed=build_training_landing_embed(self.bot), view=TrainingPanelView()
            )
            await self.services.settings.upsert_panel(guild.id, "TRAINING", channel.id, message.id)
            return message

    async def publish_course_catalog(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        async with self._catalog_lock:
            panel = await self.services.settings.get_panel(guild.id, "COURSE_CATALOG")
            message = None
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None
            embed = await build_course_catalog_embed(self.bot, guild.id)
            if message is not None:
                await message.edit(embed=embed, view=None)
            else:
                if panel:
                    old_channel = guild.get_channel(int(panel["channel_id"]))
                    if isinstance(old_channel, discord.TextChannel):
                        try:
                            old_message = await old_channel.fetch_message(int(panel["message_id"]))
                            await old_message.edit(
                                embed=branded_embed(
                                    self.bot.config.branding,
                                    title="🎖️ Central de Cursos transferida",
                                    description=f"Consulte o índice atual em {channel.mention}.",
                                ),
                                view=None,
                            )
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            pass
                message = await channel.send(embed=embed)
                await self.services.settings.upsert_panel(
                    guild.id,
                    "COURSE_CATALOG",
                    channel.id,
                    message.id,
                )
            return message

    async def publish_course_panel(
        self, guild: discord.Guild, course_id: int, channel: discord.TextChannel
    ) -> discord.Message:
        course = await self.services.training.course_by_id(guild.id, course_id)
        if not course:
            raise NotFoundError("Curso ativo não encontrado.")
        async with self._catalog_lock:
            stored = await self.services.database.fetchone(
                """
                SELECT channel_id, message_id FROM course_panel_messages
                WHERE guild_id=? AND course_id=?
                """,
                (guild.id, course_id),
            )
            message = None
            if stored and int(stored["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(stored["message_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None
            elif stored:
                old_channel = guild.get_channel(int(stored["channel_id"]))
                if isinstance(old_channel, discord.TextChannel):
                    try:
                        old_message = await old_channel.fetch_message(int(stored["message_id"]))
                        await old_message.edit(
                            embed=branded_embed(
                                self.bot.config.branding,
                                title=f"🎓 Painel de {course['name']} transferido",
                                description=f"Consulte o painel atual em {channel.mention}.",
                            ),
                            view=None,
                        )
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass
            embed = await build_course_panel_embed(self.bot, guild.id, course_id)
            view = CoursePanelView(
                str(course["internal_code"]),
                str(course["name"]),
                enrollment_open=str(course["enrollment_status"]) == "OPEN",
            )
            if message is not None:
                await message.edit(embed=embed, view=view)
            else:
                message = await channel.send(embed=embed, view=view)
            await self.services.database.execute(
                """
                INSERT INTO course_panel_messages(
                    guild_id, course_id, channel_id, message_id, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, course_id) DO UPDATE SET
                    channel_id=excluded.channel_id,
                    message_id=excluded.message_id,
                    updated_at=excluded.updated_at
                """,
                (
                    guild.id,
                    course_id,
                    channel.id,
                    message.id,
                    self.services.training.clock(),
                ),
            )
            return message

    async def publish_configured_course_panels(self, guild: discord.Guild) -> list[int]:
        published: list[int] = []
        for course in await self.services.training.catalog(guild.id):
            channel_id = course["panel_channel_id"] or course["source_channel_id"]
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if not isinstance(channel, discord.TextChannel):
                continue
            await self.publish_course_panel(guild, int(course["id"]), channel)
            published.append(int(course["id"]))
        return published

    async def publish_event(self, guild: discord.Guild, training_id: int) -> discord.Message:
        channel_id = await self.services.settings.get(guild.id, "training_panel_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            raise ValidationError("Configure o canal de treinamentos antes de publicar.")
        event = await self.services.training.get_training(guild.id, training_id)
        if not event:
            raise NotFoundError("Treinamento não encontrado.")
        view = TrainingEventView(training_id)
        message = None
        if event["channel_id"] and event["message_id"]:
            old_channel = guild.get_channel(int(event["channel_id"]))
            if isinstance(old_channel, discord.TextChannel):
                try:
                    message = await old_channel.fetch_message(int(event["message_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None
        if message:
            await message.edit(
                embed=await build_event_embed(self.bot, guild.id, training_id), view=view
            )
        else:
            message = await channel.send(
                embed=await build_event_embed(self.bot, guild.id, training_id), view=view
            )
            await self.services.training.attach_message(
                guild.id, training_id, channel.id, message.id
            )
        return message

    async def refresh_event_message(self, guild: discord.Guild, training_id: int) -> None:
        event = await self.services.training.get_training(guild.id, training_id)
        if not event or not event["channel_id"] or not event["message_id"]:
            return
        channel = guild.get_channel(int(event["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(int(event["message_id"]))
            active = event["status"] in {"OPEN", "CLOSED"}
            await message.edit(
                embed=await build_event_embed(self.bot, guild.id, training_id),
                view=TrainingEventView(training_id) if active else None,
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            channel_id = await self.services.settings.get(guild.id, "training_panel_channel_id")
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if isinstance(channel, discord.TextChannel):
                try:
                    await self.publish_or_refresh(guild, channel)
                except discord.DiscordException:
                    pass
            catalog_channel_id = await self.services.settings.get(
                guild.id, "course_catalog_channel_id"
            )
            catalog_channel = (
                guild.get_channel(int(catalog_channel_id)) if catalog_channel_id else None
            )
            if isinstance(catalog_channel, discord.TextChannel):
                try:
                    await self.publish_course_catalog(guild, catalog_channel)
                except discord.DiscordException:
                    pass
            try:
                await self.publish_configured_course_panels(guild)
            except discord.DiscordException:
                pass
            for event in await self.services.training.active_trainings(guild.id):
                if event["message_id"]:
                    await self.refresh_event_message(guild, int(event["id"]))
                elif isinstance(channel, discord.TextChannel):
                    await self.publish_event(guild, int(event["id"]))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrainingCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
