from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import discord
from discord.ext import commands, tasks

from choque.embeds import branded_embed
from choque.errors import NotFoundError, PermissionDenied, ValidationError
from choque.tags import TagService
from choque.time_utils import discord_timestamp

from .config_ui import respond_error

LOGGER = logging.getLogger(__name__)


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_member(interaction: discord.Interaction, permission: str) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use a Central de Tags dentro do servidor.")
    member = interaction.user
    if not await get_bot(interaction).services.permissions.has(member, permission):
        raise PermissionDenied("Você não possui permissão para esta ação da Central de Tags.")
    return member


async def require_request_member(
    interaction: discord.Interaction,
    request_id: int,
    permission: str,
) -> discord.Member:
    """Resolve the request owner safely both in-guild and from a Discord DM."""
    if interaction.guild and isinstance(interaction.user, discord.Member):
        return await require_member(interaction, permission)

    bot = get_bot(interaction)
    request = await bot.services.tags.get_request(request_id)
    if not request:
        raise NotFoundError("Solicitação de tag não encontrada.")
    if int(request["discord_id"]) != int(interaction.user.id):
        raise PermissionDenied("Somente o titular pode confirmar esta solicitação de tag.")
    guild = bot.get_guild(int(request["guild_id"]))
    if guild is None:
        raise ValidationError("A Central de Tags está temporariamente indisponível.")
    try:
        member = guild.get_member(int(interaction.user.id))
        if member is None:
            member = await guild.fetch_member(int(interaction.user.id))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
        raise PermissionDenied("Seu vínculo com o servidor não pôde ser confirmado.") from exc
    if not await bot.services.permissions.has(member, permission):
        raise PermissionDenied("Você não possui permissão para esta ação da Central de Tags.")
    return member


async def require_responsible(interaction: discord.Interaction) -> discord.Member:
    member = await require_member(interaction, "tag.view.self")
    bot = get_bot(interaction)
    if await bot.services.permissions.has(member, "tag.set"):
        return member
    role_id = await bot.services.settings.get(member.guild.id, "tag_responsible_role_id")
    if role_id and any(int(role.id) == int(role_id) for role in member.roles):
        return member
    raise PermissionDenied("Somente Responsável por Tag ou Comando pode atender solicitações.")


async def require_admin(interaction: discord.Interaction, permission: str) -> discord.Member:
    member = await require_member(interaction, "tag.view.self")
    if not await get_bot(interaction).services.permissions.has(member, permission):
        raise PermissionDenied("Esta ação exige Administração da Central de Tags.")
    return member


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


def request_embed(bot: ChoqueBot, request: dict[str, object]) -> discord.Embed:
    status = str(request["status"])
    labels = {
        "AGUARDANDO_SET": "🟠 Aguardando set",
        "ATENDIMENTO_ASSUMIDO": "🟡 Atendimento assumido",
        "AGUARDANDO_CONFIRMACAO": "🟦 Aguardando sua confirmação",
        "PENDENCIA": "🔴 Pendência em atendimento",
        "CONCLUIDO": "✅ Tag concluída",
        "RECUSADO": "❌ Solicitação recusada",
        "CANCELADO": "⚪ Solicitação cancelada",
        "EXPIRADO": "⌛ Solicitação expirada",
    }
    colors = {
        "AGUARDANDO_SET": discord.Color.orange(),
        "ATENDIMENTO_ASSUMIDO": discord.Color.gold(),
        "AGUARDANDO_CONFIRMACAO": discord.Color.blurple(),
        "PENDENCIA": discord.Color.red(),
        "CONCLUIDO": discord.Color.green(),
        "RECUSADO": discord.Color.dark_grey(),
        "CANCELADO": discord.Color.dark_grey(),
        "EXPIRADO": discord.Color.dark_grey(),
    }
    terminal = status in {"CONCLUIDO", "RECUSADO", "CANCELADO", "EXPIRADO"}
    embed = branded_embed(
        bot.config.branding,
        title=f"🏷️ Solicitação de Tag • #{request['id']}",
        description=(
            f"{labels.get(status, status)}\nFicha encerrada; o histórico foi preservado."
            if terminal
            else labels.get(status, status)
        ),
        color=colors.get(status),
    )
    embed.add_field(name="Membro", value=f"<@{request['discord_id']}>", inline=True)
    embed.add_field(name="ID MTA", value=f"`{request['character_id_snapshot']}`", inline=True)
    embed.add_field(name="Status", value=labels.get(status, status), inline=True)
    if str(request.get("request_origin") or "SET_REQUEST") == "EXISTING_DECLARATION":
        embed.add_field(
            name="Origem",
            value="Membro informou que a tag já está setada; validação responsável pendente.",
            inline=False,
        )
    if request.get("queue_position") is not None:
        embed.add_field(
            name="Posição na fila", value=f"`#{request['queue_position']}`", inline=True
        )
    embed.add_field(
        name="Solicitada em",
        value=discord_timestamp(int(request["requested_at"]), "F"),
        inline=False,
    )
    if request.get("claimed_by"):
        embed.add_field(name="Responsável", value=f"<@{request['claimed_by']}>", inline=True)
    if terminal:
        ended_at = request.get("confirmed_at") or request.get("terminal_at")
        if ended_at:
            embed.add_field(
                name="Encerrada em",
                value=discord_timestamp(int(ended_at), "F"),
                inline=False,
            )
    if request.get("terminal_reason"):
        embed.add_field(name="Motivo", value=str(request["terminal_reason"])[:1000], inline=False)
    if (
        status == "PENDENCIA"
        and str(request.get("request_origin") or "") == "EXISTING_DECLARATION"
    ):
        embed.add_field(
            name="Próxima etapa",
            value="Aguarde um responsável validar a tag já existente no MTA.",
            inline=False,
        )
    elif status in {"AGUARDANDO_SET", "ATENDIMENTO_ASSUMIDO", "PENDENCIA"}:
        embed.add_field(
            name="Próxima etapa",
            value="Compareça à **DP de Los Santos** e aguarde o atendimento.",
            inline=False,
        )
    return embed


async def build_member_panel_embed(bot: ChoqueBot, guild_id: int) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title="🏷️ Central de Tags • CHOQUE - BGR",
        description=(
            "Solicite sua tag de forma simples e acompanhe o atendimento em um só lugar.\n\n"
            "1. Confirme seu ID MTA.\n"
            "2. Compareça à **DP de Los Santos**.\n"
            "3. Aguarde o set e confirme quando ele aparecer no personagem.\n\n"
            "Se a tag já estiver no personagem, use **Minha tag já foi setada** para "
            "pedir a validação de um responsável.\n\n"
            "As informações são validadas no servidor e o atendimento permanece auditável."
        ),
    )


async def build_admin_panel_embed(bot: ChoqueBot, guild_id: int) -> discord.Embed:
    summary = await bot.services.tags.summary(guild_id)
    overview = await bot.services.tags.queue_overview(guild_id)
    embed = branded_embed(
        bot.config.branding,
        title="🛡️ Central Administrativa de Tags",
        description=(
            "Resumo fixo da fila. O atendimento acontece diretamente nas fichas abaixo; "
            "esta mensagem não cria solicitações nem possui botões."
        ),
    )
    embed.add_field(name="Ativas", value=str(summary["open"]), inline=True)
    embed.add_field(name="Aguardando set", value=str(summary["AGUARDANDO_SET"]), inline=True)
    embed.add_field(name="Em atendimento", value=str(summary["ATENDIMENTO_ASSUMIDO"]), inline=True)
    embed.add_field(
        name="Aguardando confirmação",
        value=str(summary["AGUARDANDO_CONFIRMACAO"]),
        inline=True,
    )
    embed.add_field(name="Pendências", value=str(summary["PENDENCIA"]), inline=True)
    embed.add_field(name="Concluídas hoje", value=str(summary["completed_today"]), inline=True)
    oldest = overview.get("oldest")
    embed.add_field(
        name="Pedido ativo mais antigo",
        value=(
            f"`#{oldest['id']}` • <@{oldest['discord_id']}> • "
            f"{discord_timestamp(int(oldest['requested_at']), 'R')}"
            if isinstance(oldest, dict)
            else "Nenhum pedido ativo."
        ),
        inline=False,
    )
    handlers = overview.get("handlers") or []
    embed.add_field(
        name="Responsáveis atendendo agora",
        value=(
            " • ".join(
                f"<@{row['claimed_by']}> (`{row['total']}`)"
                for row in handlers
                if isinstance(row, dict)
            )
            or "Nenhum atendimento assumido."
        ),
        inline=False,
    )
    return embed


class TagIdModal(ErrorModal):
    character_id = discord.ui.TextInput(
        label="ID do jogador no MTA",
        min_length=1,
        max_length=32,
        placeholder="Ex.: 183",
    )

    def __init__(self, *, existing_tag: bool = False) -> None:
        super().__init__(title="Confirmar ID MTA")
        self.existing_tag = existing_tag

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_member(interaction, "tag.request")
        bot = get_bot(interaction)
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands):
            await cog.require_member_request_configuration(member.guild)
        result = await bot.services.tags.request_tag(
            member.guild.id,
            member.id,
            character_id=str(self.character_id),
            existing_tag=self.existing_tag,
        )
        if isinstance(cog, TagCommands):
            await cog.refresh_admin_panel(member.guild)
            await cog.flush_responsible_notifications(member.guild)
        await interaction.response.send_message(embed=request_embed(bot, result), ephemeral=True)


class TagSearchModal(ErrorModal):
    query = discord.ui.TextInput(
        label="Nome MTA, ID MTA ou ID Discord",
        min_length=1,
        max_length=100,
    )

    def __init__(self) -> None:
        super().__init__(title="Buscar solicitação de tag")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        responsible = await require_responsible(interaction)
        bot = get_bot(interaction)
        rows = await bot.services.tags.search_requests(
            responsible.guild.id, str(self.query)
        )
        await interaction.response.send_message(
            embed=build_queue_embed(bot, rows, title="🔎 Resultado da busca de tags"),
            view=TagRequestSelectView(rows),
            ephemeral=True,
        )


class TagIssueModal(ErrorModal):
    reason = discord.ui.TextInput(
        label="O que aconteceu?",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(self, request_id: int, version: int) -> None:
        super().__init__(title="Informar pendência da tag")
        self.request_id = request_id
        self.version = version

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_request_member(
            interaction, self.request_id, "tag.report_missing"
        )
        bot = get_bot(interaction)
        result = await bot.services.tags.report_tag_not_received(
            self.request_id,
            discord_id=member.id,
            expected_version=self.version,
            reason=str(self.reason),
        )
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands):
            await cog.refresh_admin_panel(member.guild)
            await cog.refresh_request_card(member.guild, result)
            await cog.flush_responsible_notifications(member.guild)
        await interaction.response.send_message(
            embed=request_embed(bot, result), ephemeral=interaction.guild is not None
        )


class TagOperationalPendencyModal(ErrorModal):
    reason = discord.ui.TextInput(
        label="Motivo da pendência",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(self, request_id: int, version: int) -> None:
        super().__init__(title="Registrar pendência de tag")
        self.request_id = request_id
        self.version = version

    async def on_submit(self, interaction: discord.Interaction) -> None:
        responsible = await require_responsible(interaction)
        bot = get_bot(interaction)
        result = await bot.services.tags.report_operational_pendency(
            self.request_id,
            actor_id=responsible.id,
            expected_version=self.version,
            reason=str(self.reason),
        )
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands):
            await cog.refresh_admin_panel(responsible.guild)
            await cog.refresh_request_card(responsible.guild, result)
            await cog.flush_responsible_notifications(responsible.guild)
        await interaction.response.send_message(embed=request_embed(bot, result), ephemeral=True)


class TagMemberRequestView(ErrorView):
    def __init__(self, request_id: int, version: int, status: str) -> None:
        super().__init__(timeout=None)
        self.request_id = request_id
        self.version = version
        self.status = status
        self.confirm.custom_id = f"choque:tag:confirm:{request_id}:v1"
        self.not_received.custom_id = f"choque:tag:not-received:{request_id}:v1"
        self.confirm.disabled = status != "AGUARDANDO_CONFIRMACAO"
        self.not_received.disabled = status != "AGUARDANDO_CONFIRMACAO"

    @discord.ui.button(label="Confirmar tag setada", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_request_member(
            interaction, self.request_id, "tag.confirm.self"
        )
        bot = get_bot(interaction)
        result = await bot.services.tags.confirm_tag(
            self.request_id, discord_id=member.id, expected_version=self.version
        )
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands):
            await cog.refresh_admin_panel(member.guild)
            await cog.refresh_request_card(member.guild, result)
        await interaction.response.edit_message(
            embed=request_embed(bot, result), view=TagMemberRequestView(
                self.request_id, int(result["version"]), str(result["status"])
            )
        )

    @discord.ui.button(label="Não recebi a tag", emoji="❌", style=discord.ButtonStyle.danger)
    async def not_received(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_request_member(interaction, self.request_id, "tag.report_missing")
        await interaction.response.send_modal(TagIssueModal(self.request_id, self.version))


class TagMemberPanelView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Solicitar tag",
        emoji="🏷️",
        style=discord.ButtonStyle.success,
        custom_id="choque:tag:request:v1",
    )
    async def request(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "tag.request")
        bot = get_bot(interaction)
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands):
            await cog.require_member_request_configuration(member.guild)
        try:
            result = await bot.services.tags.request_tag(member.guild.id, member.id)
        except ValidationError as exc:
            if "ID MTA" not in str(exc):
                raise
            await interaction.response.send_modal(TagIdModal())
            return
        if isinstance(cog, TagCommands):
            await cog.refresh_admin_panel(member.guild)
            await cog.flush_responsible_notifications(member.guild)
        await interaction.response.send_message(embed=request_embed(bot, result), ephemeral=True)

    @discord.ui.button(
        label="Minha tag já foi setada",
        emoji="✅",
        style=discord.ButtonStyle.primary,
        custom_id="choque:tag:already-set:v1",
    )
    async def already_set(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "tag.request")
        bot = get_bot(interaction)
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands):
            await cog.require_member_request_configuration(member.guild)
        try:
            result = await bot.services.tags.request_tag(
                member.guild.id, member.id, existing_tag=True
            )
        except ValidationError as exc:
            if "ID MTA" not in str(exc):
                raise
            await interaction.response.send_modal(TagIdModal(existing_tag=True))
            return
        if isinstance(cog, TagCommands):
            await cog.refresh_admin_panel(member.guild)
            await cog.flush_responsible_notifications(member.guild)
        await interaction.response.send_message(
            "Sua informação foi enviada para validação. O cargo TAG SETADA só será "
            "aplicado depois da conferência de um responsável.",
            embed=request_embed(bot, result),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Minha tag",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:tag:mine:v1",
    )
    async def mine(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        member = await require_member(interaction, "tag.view.self")
        bot = get_bot(interaction)
        request = await bot.services.tags.member_request(member.guild.id, member.id)
        if not request:
            await interaction.response.send_message(
                "Você ainda não possui uma solicitação de tag.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=request_embed(bot, request),
            view=TagMemberRequestView(
                int(request["id"]), int(request["version"]), str(request["status"])
            ),
            ephemeral=True,
        )


async def show_tag_requests(
    interaction: discord.Interaction,
    *,
    title: str,
    statuses: tuple[str, ...] | None = None,
    history: bool = False,
) -> None:
    """Render a short, private operational list from the durable state."""
    bot = get_bot(interaction)
    if not interaction.guild:
        raise ValidationError("Este painel só pode ser usado dentro do servidor.")
    values, total = await bot.services.tags.request_page(
        interaction.guild.id, statuses=statuses, history=history
    )
    await interaction.response.send_message(
        embed=build_queue_embed(bot, values, title=title, page=0, total=total),
        view=TagRequestPagerView(
            values,
            title=title,
            statuses=statuses,
            history=history,
            page=0,
            total=total,
            admin_only=history,
        ),
        ephemeral=True,
    )


class TagAdminPanelView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Todos",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        custom_id="choque:tag:admin:all:v1",
    )
    async def all_requests(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_responsible(interaction)
        await show_tag_requests(interaction, title="📋 Solicitações de tag")

    @discord.ui.button(
        label="Faltam setar",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        custom_id="choque:tag:admin:waiting:v1",
    )
    async def waiting_queue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_responsible(interaction)
        await show_tag_requests(
            interaction,
            title="👥 Todos que faltam setar",
            statuses=("AGUARDANDO_SET",),
        )

    @discord.ui.button(
        label="Em atendimento",
        emoji="🟡",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:tag:admin:assigned:v1",
    )
    async def assigned(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_responsible(interaction)
        await show_tag_requests(
            interaction,
            title="🟡 Tags em atendimento",
            statuses=("ATENDIMENTO_ASSUMIDO",),
        )

    @discord.ui.button(
        label="Aguardando confirmação",
        emoji="🟦",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:tag:admin:confirmation:v1",
    )
    async def confirmation_queue(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await require_responsible(interaction)
        await show_tag_requests(
            interaction,
            title="🟦 Tags aguardando confirmação",
            statuses=("AGUARDANDO_CONFIRMACAO",),
        )

    @discord.ui.button(
        label="Pendências",
        emoji="🔴",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:tag:admin:pending:v1",
    )
    async def pending(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_responsible(interaction)
        await show_tag_requests(
            interaction,
            title="🔴 Pendências de tag",
            statuses=("PENDENCIA",),
        )

    @discord.ui.button(
        label="Histórico",
        emoji="📚",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:tag:admin:history:v1",
    )
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "tag.history.view")
        await show_tag_requests(interaction, title="📚 Histórico de tags", history=True)

    @discord.ui.button(
        label="Configurar",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:tag:admin:settings:v1",
    )
    async def configure(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "tag.settings")
        bot = get_bot(interaction)
        await interaction.response.send_message(
            embed=await build_tag_configuration_embed(bot, interaction.guild),
            view=TagConfigurationView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Buscar",
        emoji="🔎",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:tag:admin:search:v1",
        row=1,
    )
    async def search(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_responsible(interaction)
        await interaction.response.send_modal(TagSearchModal())


TAG_CONFIGURATION_KEYS = (
    ("tag_member_panel_channel_id", "Canal do painel do membro", "CHANNEL"),
    ("tag_admin_panel_channel_id", "Canal do painel administrativo", "CHANNEL"),
    ("tag_waiting_role_id", "Cargo AGUARDANDO SET", "ROLE"),
    ("tag_set_role_id", "Cargo TAG SETADA", "ROLE"),
    ("tag_responsible_role_id", "Cargo RESPONSÁVEL POR TAG", "ROLE"),
    ("tag_expiration_hours", "Prazo de expiração (horas)", "NUMBER"),
    ("tag_call_cooldown_seconds", "Cooldown de chamada (segundos)", "NUMBER"),
)

TAG_NUMBER_SETTING_BOUNDS = {
    "tag_expiration_hours": (1, 24 * 30),
    "tag_call_cooldown_seconds": (60, 24 * 60 * 60),
}


async def build_tag_configuration_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    values = {
        key: await bot.services.settings.get(guild.id, key)
        for key, _, _ in TAG_CONFIGURATION_KEYS
    }
    lines = []
    for key, label, kind in TAG_CONFIGURATION_KEYS:
        value = values[key]
        if kind == "CHANNEL":
            rendered = f"<#{value}>" if value else "❌"
        elif kind == "ROLE":
            rendered = f"<@&{value}>" if value else "❌"
        elif key == "tag_expiration_hours":
            rendered = f"`{value} horas`"
        else:
            rendered = f"`{value} segundos`"
        lines.append(f"**{label}:** {rendered}")
    return branded_embed(
        bot.config.branding,
        title="⚙️ Configuração da Central de Tags",
        description=(
            "Defina os dois canais e os três cargos usados pela Central. "
            "Todas as alterações são auditadas; cargos de espera e tag setada devem ser diferentes.\n\n"
            + "\n".join(lines)
        ),
    )


async def save_tag_setting(
    interaction: discord.Interaction, *, key: str, value: int
) -> None:
    actor = await require_admin(interaction, "tag.settings")
    bot = get_bot(interaction)
    before = await bot.services.settings.get(actor.guild.id, key)
    async with bot.services.database.transaction() as connection:
        await bot.services.settings.set(actor.guild.id, key, value, actor.id, connection)
        await bot.services.audit.record(
            actor.guild.id,
            "TAG_SETTING_CHANGED",
            actor_id=actor.id,
            before={key: before},
            after={key: value},
            connection=connection,
        )


class TagNumberSettingModal(ErrorModal):
    value = discord.ui.TextInput(label="Novo valor", min_length=1, max_length=6)

    def __init__(self, key: str, label: str) -> None:
        super().__init__(title=label[:45])
        self.key = key
        self.setting_label = label

    async def on_submit(self, interaction: discord.Interaction) -> None:
        minimum, maximum = TAG_NUMBER_SETTING_BOUNDS[self.key]
        try:
            value = int(str(self.value).strip())
        except ValueError as exc:
            raise ValidationError("Informe um número inteiro.") from exc
        if not minimum <= value <= maximum:
            raise ValidationError(
                f"Informe um valor entre {minimum} e {maximum}."
            )
        await save_tag_setting(interaction, key=self.key, value=value)
        await interaction.response.send_message(
            f"**{self.setting_label}** atualizado para `{value}`.", ephemeral=True
        )


class TagRoleSelect(discord.ui.RoleSelect):
    def __init__(self, key: str, label: str) -> None:
        super().__init__(
            placeholder=f"Escolha {label}"[:150],
            min_values=1,
            max_values=1,
        )
        self.key = key
        self.label = label

    async def callback(self, interaction: discord.Interaction) -> None:
        role = self.values[0]
        if role.is_default():
            raise ValidationError("O cargo @everyone não pode ser usado na Central de Tags.")
        await save_tag_setting(interaction, key=self.key, value=int(role.id))
        bot = get_bot(interaction)
        await interaction.response.edit_message(
            embed=await build_tag_configuration_embed(bot, interaction.guild),
            view=TagConfigurationView(),
        )


class TagChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, key: str, label: str) -> None:
        super().__init__(
            placeholder=f"Escolha {label}"[:150],
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        channel = self.values[0]
        if not isinstance(channel, discord.TextChannel):
            raise ValidationError("Escolha um canal de texto para o painel.")
        await save_tag_setting(interaction, key=self.key, value=int(channel.id))
        bot = get_bot(interaction)
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands) and interaction.guild:
            if self.key == "tag_member_panel_channel_id":
                await cog.publish_or_refresh_member_panel(interaction.guild, channel)
            else:
                await cog.publish_or_refresh_admin_panel(interaction.guild, channel)
        await interaction.response.edit_message(
            embed=await build_tag_configuration_embed(bot, interaction.guild),
            view=TagConfigurationView(),
        )


class TagRoleSelectView(ErrorView):
    def __init__(self, key: str, label: str) -> None:
        super().__init__(timeout=600)
        self.add_item(TagRoleSelect(key, label))


class TagChannelSelectView(ErrorView):
    def __init__(self, key: str, label: str) -> None:
        super().__init__(timeout=600)
        self.add_item(TagChannelSelect(key, label))


class TagConfigurationButton(discord.ui.Button):
    def __init__(self, key: str, label: str, kind: str, *, row: int) -> None:
        super().__init__(label=label[:80], style=discord.ButtonStyle.secondary, row=row)
        self.key = key
        self.setting_label = label
        self.kind = kind

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_admin(interaction, "tag.settings")
        view: discord.ui.View
        if self.kind == "ROLE":
            view = TagRoleSelectView(self.key, self.setting_label)
        elif self.kind == "CHANNEL":
            view = TagChannelSelectView(self.key, self.setting_label)
        else:
            await interaction.response.send_modal(
                TagNumberSettingModal(self.key, self.setting_label)
            )
            return
        await interaction.response.edit_message(
            content=None,
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title="⚙️ Configuração da Central de Tags",
                description=f"Selecione **{self.setting_label}**.",
            ),
            view=view,
        )


class TagConfigurationView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=600)
        for index, (key, label, kind) in enumerate(TAG_CONFIGURATION_KEYS):
            self.add_item(TagConfigurationButton(key, label, kind, row=index // 3))


def build_queue_embed(
    bot: ChoqueBot,
    rows: list[dict[str, object]],
    *,
    title: str,
    page: int | None = None,
    total: int | None = None,
) -> discord.Embed:
    lines = []
    for index, row in enumerate(rows, start=1):
        responsible = f" • <@{row['claimed_by']}>" if row.get("claimed_by") else ""
        lines.append(
            f"**{index:02d}.** <@{row['discord_id']}> • ID `{row['character_id_snapshot']}`\n"
            f"└ `#{row['id']}` • `{row['status']}`{responsible}"
        )
    description = "\n\n".join(lines) if lines else "Nenhuma solicitação neste estado."
    if page is not None and total is not None:
        page_count = max(1, (total + 24) // 25)
        description = f"{description}\n\nPágina `{page + 1}/{page_count}` • Total: `{total}`"
    return branded_embed(
        bot.config.branding,
        title=title,
        description=description,
    )


class TagRequestSelect(discord.ui.Select):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__(
            placeholder="Escolha uma solicitação para atender",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['mta_nick_snapshot']}"[:100],
                    value=str(row["id"]),
                    description=f"{row['status']} • ID MTA {row['character_id_snapshot']}"[:100],
                )
                for row in rows[:25]
            ],
            disabled=not rows,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_responsible(interaction)
        bot = get_bot(interaction)
        request = await bot.services.tags.get_request(int(self.values[0]))
        if not request:
            raise NotFoundError("Solicitação de tag não encontrada.")
        await interaction.response.edit_message(
            embed=request_embed(bot, request),
            view=TagRequestAdminView(
                int(request["id"]),
                int(request["version"]),
                str(request["status"]),
                str(request.get("request_origin") or "SET_REQUEST"),
            ),
        )


class TagRequestSelectView(ErrorView):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__(timeout=600)
        if rows:
            self.add_item(TagRequestSelect(rows))


class TagRequestPagerView(ErrorView):
    """Keep long queue navigation in the same ephemeral response."""

    PAGE_SIZE = 25

    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        title: str,
        statuses: tuple[str, ...] | None,
        history: bool,
        page: int,
        total: int,
        admin_only: bool,
    ) -> None:
        super().__init__(timeout=600)
        self.title = title
        self.statuses = statuses
        self.history = history
        self.page = page
        self.total = total
        self.admin_only = admin_only
        if rows:
            self.add_item(TagRequestSelect(rows))
        self.previous.disabled = page <= 0
        self.next.disabled = (page + 1) * self.PAGE_SIZE >= total

    async def _render_page(self, interaction: discord.Interaction, page: int) -> None:
        if self.admin_only:
            await require_admin(interaction, "tag.history.view")
        else:
            await require_responsible(interaction)
        bot = get_bot(interaction)
        if not interaction.guild:
            raise ValidationError("Este painel só pode ser usado dentro do servidor.")
        rows, total = await bot.services.tags.request_page(
            interaction.guild.id,
            statuses=self.statuses,
            history=self.history,
            page=page,
            page_size=self.PAGE_SIZE,
        )
        await interaction.response.edit_message(
            embed=build_queue_embed(bot, rows, title=self.title, page=page, total=total),
            view=TagRequestPagerView(
                rows,
                title=self.title,
                statuses=self.statuses,
                history=self.history,
                page=page,
                total=total,
                admin_only=self.admin_only,
            ),
        )

    @discord.ui.button(label="Anterior", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._render_page(interaction, max(0, self.page - 1))

    @discord.ui.button(label="Próxima", emoji="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        max_page = max(0, (self.total - 1) // self.PAGE_SIZE)
        await self._render_page(interaction, min(max_page, self.page + 1))


class TagSetModal(ErrorModal):
    character_id = discord.ui.TextInput(label="ID MTA utilizado no set", min_length=1, max_length=32)

    def __init__(
        self, request_id: int, version: int, *, existing_tag: bool = False
    ) -> None:
        super().__init__(
            title="Validar tag existente" if existing_tag else "Confirmar set realizado"
        )
        self.request_id = request_id
        self.version = version
        self.existing_tag = existing_tag

    async def on_submit(self, interaction: discord.Interaction) -> None:
        responsible = await require_responsible(interaction)
        bot = get_bot(interaction)
        result = await bot.services.tags.mark_set_performed(
            self.request_id,
            responsible_id=responsible.id,
            expected_version=self.version,
            set_character_id=str(self.character_id),
        )
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands):
            await cog.refresh_admin_panel(responsible.guild)
            await cog.refresh_request_card(responsible.guild, result)
            await cog.deliver_confirmation_notification(responsible.guild, result)
        await interaction.response.send_message(
            (
                "Tag existente validada. O membro foi notificado para a confirmação final."
                if self.existing_tag
                else "Set registrado. O membro foi notificado e também pode confirmar pelo painel **Minha tag**."
            ),
            embed=request_embed(bot, result),
            ephemeral=True,
        )


class TagDecisionModal(ErrorModal):
    reason = discord.ui.TextInput(
        label="Motivo", style=discord.TextStyle.paragraph, min_length=3, max_length=500
    )

    def __init__(self, request_id: int, version: int, *, decision: str) -> None:
        titles = {
            "RECUSAR": "Recusar solicitação",
            "CANCELAR": "Cancelar solicitação",
            "LIBERAR": "Liberar solicitação",
        }
        super().__init__(title=titles[decision])
        self.request_id = request_id
        self.version = version
        self.decision = decision

    async def on_submit(self, interaction: discord.Interaction) -> None:
        responsible = await require_responsible(interaction)
        bot = get_bot(interaction)
        if self.decision == "RECUSAR":
            await require_admin(interaction, "tag.reject")
            result = await bot.services.tags.reject_request(
                self.request_id,
                actor_id=responsible.id,
                expected_version=self.version,
                reason=str(self.reason),
            )
        elif self.decision == "CANCELAR":
            await require_admin(interaction, "tag.cancel")
            result = await bot.services.tags.cancel_request(
                self.request_id,
                actor_id=responsible.id,
                expected_version=self.version,
                reason=str(self.reason),
            )
        else:
            result = await bot.services.tags.release_request(
                self.request_id,
                responsible_id=responsible.id,
                expected_version=self.version,
                reason=str(self.reason),
            )
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands):
            await cog.refresh_admin_panel(responsible.guild)
            await cog.refresh_request_card(responsible.guild, result)
            if str(result["status"]) in {"RECUSADO", "CANCELADO", "EXPIRADO"}:
                await cog.deliver_terminal_notification(responsible.guild, result)
        await interaction.response.send_message(embed=request_embed(bot, result), ephemeral=True)


class TagCorrectIdModal(ErrorModal):
    character_id = discord.ui.TextInput(label="Novo ID MTA", min_length=1, max_length=32)
    reason = discord.ui.TextInput(
        label="Motivo da correção",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )

    def __init__(self, request_id: int, version: int) -> None:
        super().__init__(title="Corrigir ID MTA")
        self.request_id = request_id
        self.version = version

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_admin(interaction, "tag.identity.correct")
        bot = get_bot(interaction)
        result = await bot.services.tags.correct_character_id(
            self.request_id,
            actor_id=admin.id,
            expected_version=self.version,
            character_id=str(self.character_id),
            reason=str(self.reason),
        )
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands):
            await cog.refresh_admin_panel(admin.guild)
            await cog.refresh_request_card(admin.guild, result)
        await interaction.response.send_message(embed=request_embed(bot, result), ephemeral=True)


async def call_tag_member_to_dp(
    interaction: discord.Interaction,
    *,
    request_id: int,
    expected_version: int,
) -> None:
    """Deliver the repeatable, cooldown-protected DP call."""
    responsible = await require_responsible(interaction)
    bot = get_bot(interaction)
    cooldown_seconds = await bot.services.settings.get(
        responsible.guild.id, "tag_call_cooldown_seconds"
    )
    reserved = await bot.services.tags.reserve_member_call(
        request_id,
        responsible_id=responsible.id,
        expected_version=expected_version,
        cooldown_ms=max(1, int(cooldown_seconds)) * 1_000,
    )
    try:
        member = responsible.guild.get_member(int(reserved["discord_id"]))
        if member is None:
            member = await responsible.guild.fetch_member(int(reserved["discord_id"]))
        await member.send(
            "📍 **Seu atendimento de tag está disponível.** Dirija-se à "
            "**DP de Los Santos** para realizar o set."
        )
    except discord.DiscordException as exc:
        await bot.services.tags.release_member_call(
            request_id, responsible_id=responsible.id, error=str(exc)
        )
        raise ValidationError(
            "Não foi possível entregar a chamada no privado do membro."
        ) from exc
    await bot.services.tags.record_member_called(
        request_id, responsible_id=responsible.id
    )
    await interaction.response.send_message(
        "Chamada enviada ao membro com orientação para a **DP de Los Santos**.",
        ephemeral=True,
    )


class TagRequestAdminView(ErrorView):
    def __init__(
        self,
        request_id: int,
        version: int,
        status: str,
        request_origin: str = "SET_REQUEST",
    ) -> None:
        super().__init__(timeout=600)
        self.request_id = request_id
        self.version = version
        self.status = status
        self.request_origin = request_origin
        if request_origin == "EXISTING_DECLARATION":
            self.set_done.label = "Validar tag existente"
        self.claim.disabled = status not in {"AGUARDANDO_SET", "PENDENCIA"}
        self.release.disabled = status != "ATENDIMENTO_ASSUMIDO"
        self.set_done.disabled = status != "ATENDIMENTO_ASSUMIDO"
        self.call_member.disabled = status != "ATENDIMENTO_ASSUMIDO"
        self.operational_pendency.disabled = status not in {
            "AGUARDANDO_SET",
            "ATENDIMENTO_ASSUMIDO",
            "AGUARDANDO_CONFIRMACAO",
        }
        self.reject.disabled = status not in {
            "AGUARDANDO_SET",
            "ATENDIMENTO_ASSUMIDO",
            "AGUARDANDO_CONFIRMACAO",
            "PENDENCIA",
        }
        self.cancel.disabled = status not in TagService.ACTIVE_STATUSES
        self.correct_id.disabled = status not in TagService.ACTIVE_STATUSES

    @discord.ui.button(label="Assumir", emoji="🙋", style=discord.ButtonStyle.primary)
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        responsible = await require_responsible(interaction)
        bot = get_bot(interaction)
        result = await bot.services.tags.claim_request(
            self.request_id, responsible_id=responsible.id, expected_version=self.version
        )
        cog = bot.get_cog("TagCommands")
        if isinstance(cog, TagCommands):
            await cog.refresh_admin_panel(responsible.guild)
            await cog.refresh_request_card(responsible.guild, result)
        await interaction.response.edit_message(
            embed=request_embed(bot, result),
            view=TagRequestAdminView(
                self.request_id,
                int(result["version"]),
                str(result["status"]),
                self.request_origin,
            ),
        )

    @discord.ui.button(label="Liberar", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def release(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_responsible(interaction)
        await interaction.response.send_modal(TagDecisionModal(self.request_id, self.version, decision="LIBERAR"))

    @discord.ui.button(label="Set realizado", emoji="✅", style=discord.ButtonStyle.success)
    async def set_done(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_responsible(interaction)
        await interaction.response.send_modal(
            TagSetModal(
                self.request_id,
                self.version,
                existing_tag=self.request_origin == "EXISTING_DECLARATION",
            )
        )

    @discord.ui.button(label="Chamar para DP", emoji="📍", style=discord.ButtonStyle.secondary, row=1)
    async def call_member(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await call_tag_member_to_dp(
            interaction,
            request_id=self.request_id,
            expected_version=self.version,
        )

    @discord.ui.button(label="Pendência", emoji="⚠️", style=discord.ButtonStyle.secondary, row=1)
    async def operational_pendency(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await require_responsible(interaction)
        await interaction.response.send_modal(
            TagOperationalPendencyModal(self.request_id, self.version)
        )

    @discord.ui.button(label="Recusar", emoji="❌", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "tag.reject")
        await interaction.response.send_modal(TagDecisionModal(self.request_id, self.version, decision="RECUSAR"))

    @discord.ui.button(label="Cancelar", emoji="⛔", style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "tag.cancel")
        await interaction.response.send_modal(TagDecisionModal(self.request_id, self.version, decision="CANCELAR"))

    @discord.ui.button(label="Corrigir ID", emoji="✏️", style=discord.ButtonStyle.secondary, row=1)
    async def correct_id(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_admin(interaction, "tag.identity.correct")
        await interaction.response.send_modal(TagCorrectIdModal(self.request_id, self.version))


class TagRequestCardButton(discord.ui.Button["TagRequestCardView"]):
    def __init__(
        self,
        owner: TagRequestCardView,
        *,
        action: str,
        label: str,
        emoji: str,
        style: discord.ButtonStyle,
    ) -> None:
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            custom_id=f"choque:tag:card:{action}:{owner.request_id}:v1",
        )
        self.owner = owner
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner.handle_action(interaction, self.action)


class TagRequestCardView(ErrorView):
    """Persistent, request-scoped controls shown on the channel card."""

    def __init__(self, request: dict[str, object]) -> None:
        super().__init__(timeout=None)
        self.request_id = int(request["id"])
        self.status = str(request["status"])
        self.request_origin = str(request.get("request_origin") or "SET_REQUEST")
        if self.status in {"AGUARDANDO_SET", "PENDENCIA"}:
            self._add(
                "claim", "Assumir", "🙋", discord.ButtonStyle.primary
            )
            self._add(
                "details", "Ver detalhes", "🔎", discord.ButtonStyle.secondary
            )
        elif self.status == "ATENDIMENTO_ASSUMIDO":
            self._add(
                "call", "Chamar para DP", "📍", discord.ButtonStyle.primary
            )
            self._add(
                "set",
                (
                    "Validar tag existente"
                    if self.request_origin == "EXISTING_DECLARATION"
                    else "Tag aplicada"
                ),
                "✅",
                discord.ButtonStyle.success,
            )
            self._add(
                "more", "Mais ações", "⚙️", discord.ButtonStyle.secondary
            )
        elif self.status in TagService.ACTIVE_STATUSES:
            self._add(
                "details", "Ver detalhes", "🔎", discord.ButtonStyle.secondary
            )
            self._add(
                "more", "Mais ações", "⚙️", discord.ButtonStyle.secondary
            )

    def _add(
        self,
        action: str,
        label: str,
        emoji: str,
        style: discord.ButtonStyle,
    ) -> None:
        self.add_item(
            TagRequestCardButton(
                self,
                action=action,
                label=label,
                emoji=emoji,
                style=style,
            )
        )

    async def _current(self, interaction: discord.Interaction) -> dict[str, object]:
        request = await get_bot(interaction).services.tags.get_request(self.request_id)
        if not request:
            raise NotFoundError("Solicitação de tag não encontrada.")
        return request

    async def handle_action(self, interaction: discord.Interaction, action: str) -> None:
        responsible = await require_responsible(interaction)
        bot = get_bot(interaction)
        request = await self._current(interaction)
        if action in {"details", "more"}:
            await interaction.response.send_message(
                content=("Ações administrativas da ficha." if action == "more" else None),
                embed=request_embed(bot, request),
                view=TagRequestAdminView(
                    self.request_id,
                    int(request["version"]),
                    str(request["status"]),
                    str(request.get("request_origin") or "SET_REQUEST"),
                ),
                ephemeral=True,
            )
            return
        if action == "claim":
            result = await bot.services.tags.claim_request(
                self.request_id,
                responsible_id=responsible.id,
                expected_version=int(request["version"]),
            )
            await interaction.response.edit_message(
                content=None,
                embed=request_embed(bot, result),
                view=TagRequestCardView(result),
            )
            cog = bot.get_cog("TagCommands")
            if isinstance(cog, TagCommands):
                message_id = result.get("responsible_notification_message_id")
                if message_id:
                    await bot.services.tags.mark_request_card_rendered(
                        self.request_id,
                        message_id=int(message_id),
                        rendered_version=int(result["version"]),
                    )
                await cog.register_request_card_view(result)
                await cog.refresh_admin_panel(responsible.guild)
            return
        if action == "call":
            await call_tag_member_to_dp(
                interaction,
                request_id=self.request_id,
                expected_version=int(request["version"]),
            )
            return
        if action == "set":
            await interaction.response.send_modal(
                TagSetModal(
                    self.request_id,
                    int(request["version"]),
                    existing_tag=(
                        str(request.get("request_origin") or "SET_REQUEST")
                        == "EXISTING_DECLARATION"
                    ),
                )
            )
            return
        raise ValidationError("Esta ação da ficha não está disponível.")


class TagCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._registered_confirmation_views: set[tuple[int, int]] = set()
        self._registered_request_card_views: set[tuple[int, int, str]] = set()
        self.bot.add_view(TagMemberPanelView())
        self.bot.add_view(TagAdminPanelView())
        if not self.bot.check_mode:
            self.confirmation_retry.start()

    def cog_unload(self) -> None:
        self.confirmation_retry.cancel()

    async def require_member_request_configuration(self, guild: discord.Guild) -> None:
        """Reject a request before it could enter an unsynchronizable queue."""
        waiting_role_id = await self.services.settings.get(guild.id, "tag_waiting_role_id")
        set_role_id = await self.services.settings.get(guild.id, "tag_set_role_id")
        missing = []
        if not waiting_role_id:
            missing.append("cargo AGUARDANDO SET")
        if not set_role_id:
            missing.append("cargo TAG SETADA")
        if missing:
            raise ValidationError(
                "A Central de Tags ainda precisa configurar " + " e ".join(missing) + "."
            )
        if int(waiting_role_id) == int(set_role_id):
            raise ValidationError(
                "Os cargos AGUARDANDO SET e TAG SETADA precisam ser diferentes."
            )

    def register_confirmation_view(self, request: dict[str, object]) -> None:
        """Register the request-scoped persistent controls before the DM is usable.

        Sending a persistent Discord view does not itself make a newly started
        process route its custom IDs.  Registering at delivery time closes the
        interval until the next recovery loop, while the `(request, version)`
        key keeps a retry or restart from registering duplicate handlers.
        """
        key = (int(request["id"]), int(request["version"]))
        if key in self._registered_confirmation_views:
            return
        self.bot.add_view(
            TagMemberRequestView(
                int(request["id"]), int(request["version"]), str(request["status"])
            )
        )
        self._registered_confirmation_views.add(key)

    async def restore_confirmation_views(self, guild: discord.Guild) -> None:
        for request in await self.services.tags.awaiting_confirmations(guild.id):
            self.register_confirmation_view(request)

    async def register_request_card_view(self, request: dict[str, object]) -> None:
        message_id = request.get("responsible_notification_message_id")
        status = str(request["status"])
        if not message_id or status not in TagService.ACTIVE_STATUSES:
            return
        key = (int(request["id"]), int(message_id), status)
        if key in self._registered_request_card_views:
            return
        self.bot.add_view(
            TagRequestCardView(request), message_id=int(message_id)
        )
        self._registered_request_card_views.add(key)

    async def restore_request_card_views(self, guild: discord.Guild) -> None:
        for request in await self.services.tags.request_cards(guild.id):
            await self.register_request_card_view(request)

    async def refresh_request_card(
        self, guild: discord.Guild, request: dict[str, object]
    ) -> bool:
        """Edit the original request card and never append a status message."""
        message_id = request.get("responsible_notification_message_id")
        if not message_id:
            return False
        channel_id = await self.services.settings.get(
            guild.id, "tag_admin_panel_channel_id"
        )
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return False
        try:
            message = await channel.fetch_message(int(message_id))
            view = (
                TagRequestCardView(request)
                if str(request["status"]) in TagService.ACTIVE_STATUSES
                else None
            )
            await message.edit(
                content=None,
                embed=request_embed(self.bot, request),
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.NotFound:
            rearmed = await self.services.tags.rearm_missing_request_card(
                int(request["id"]), missing_message_id=int(message_id)
            )
            if rearmed:
                current = await self.services.tags.get_request(int(request["id"]))
                if current:
                    await self.deliver_responsible_notification(guild, current)
            return False
        except discord.DiscordException as exc:
            LOGGER.warning(
                "Não foi possível atualizar a ficha única da tag %s: %s",
                request["id"],
                exc,
            )
            return False
        rendered = await self.services.tags.mark_request_card_rendered(
            int(request["id"]),
            message_id=int(message_id),
            rendered_version=int(request["version"]),
        )
        if view is not None:
            await self.register_request_card_view(request)
        return rendered

    async def flush_request_card_refreshes(self, guild: discord.Guild) -> int:
        refreshed = 0
        for request in await self.services.tags.pending_request_card_refreshes(
            guild.id
        ):
            refreshed += int(await self.refresh_request_card(guild, request))
        return refreshed

    async def deliver_confirmation_notification(
        self, guild: discord.Guild, request: dict[str, object]
    ) -> bool:
        """Deliver one durable confirmation notice without changing the tag state."""
        claimed = await self.services.tags.claim_confirmation_notification(int(request["id"]))
        if not claimed:
            return False
        if not await self.services.settings.get(guild.id, "tag_dm_enabled"):
            await self.services.tags.mark_confirmation_notification_delivered(
                int(claimed["id"]), delivery_message_id=None
            )
            return False
        try:
            member = guild.get_member(int(claimed["discord_id"]))
            if member is None:
                member = await guild.fetch_member(int(claimed["discord_id"]))
            self.register_confirmation_view(claimed)
            message = await member.send(
                "🏷️ **Sua tag foi marcada como realizada.** Confira seu personagem no MTA "
                "e confirme abaixo quando estiver correta.",
                embed=request_embed(self.bot, claimed),
                view=TagMemberRequestView(
                    int(claimed["id"]),
                    int(claimed["version"]),
                    str(claimed["status"]),
                ),
            )
        except discord.DiscordException as exc:
            await self.services.tags.mark_confirmation_notification_failed(
                int(claimed["id"]), error=str(exc)
            )
            LOGGER.warning("Não foi possível notificar confirmação da tag %s: %s", claimed["id"], exc)
            return False
        delivered = await self.services.tags.mark_confirmation_notification_delivered(
            int(claimed["id"]), delivery_message_id=message.id
        )
        if delivered:
            await self.services.audit.record(
                guild.id,
                "TAG_CONFIRMATION_NOTIFICATION_DELIVERED",
                actor_id=int(claimed["set_by"] or 0) or None,
                target_id=int(claimed["discord_id"]),
                after={"tag_request_id": int(claimed["id"]), "message_id": message.id},
            )
        return delivered

    async def deliver_responsible_notification(
        self, guild: discord.Guild, request: dict[str, object]
    ) -> bool:
        """Alert the configured tag role once from a durable request claim."""
        channel_id = await self.services.settings.get(guild.id, "tag_admin_panel_channel_id")
        role_id = await self.services.settings.get(guild.id, "tag_responsible_role_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        role = guild.get_role(int(role_id)) if role_id else None
        if not isinstance(channel, discord.TextChannel) or role is None:
            # Leave the notification PENDING: completing configuration later
            # must deliver the alert without creating a second tag request.
            return False

        claimed = await self.services.tags.claim_responsible_notification(int(request["id"]))
        if not claimed:
            return False
        try:
            existing_declaration = (
                str(claimed.get("request_origin") or "SET_REQUEST")
                == "EXISTING_DECLARATION"
            )
            message = await channel.send(
                content=(
                    f"<@&{role.id}> "
                    + (
                        "nova declaração de tag existente aguardando validação."
                        if existing_declaration
                        else "nova solicitação de tag aguardando atendimento."
                    )
                ),
                embed=request_embed(self.bot, claimed),
                view=TagRequestCardView(claimed),
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=False, roles=[role]
                ),
            )
        except discord.DiscordException as exc:
            await self.services.tags.mark_responsible_notification_failed(
                int(claimed["id"]), error=str(exc)
            )
            LOGGER.warning(
                "Não foi possível notificar responsáveis da tag %s: %s", claimed["id"], exc
            )
            return False
        delivered = await self.services.tags.mark_responsible_notification_delivered(
            int(claimed["id"]), delivery_message_id=message.id
        )
        if delivered:
            delivered_request = dict(claimed)
            delivered_request["responsible_notification_message_id"] = message.id
            delivered_request["request_card_rendered_version"] = int(claimed["version"])
            await self.register_request_card_view(delivered_request)
            await self.services.audit.record(
                guild.id,
                "TAG_RESPONSIBLE_NOTIFICATION_DELIVERED",
                actor_id=int(claimed["requested_by"]),
                target_id=int(claimed["discord_id"]),
                after={"tag_request_id": int(claimed["id"]), "message_id": message.id},
            )
        return delivered

    async def flush_responsible_notifications(self, guild: discord.Guild) -> int:
        delivered = 0
        for request in await self.services.tags.pending_responsible_notifications(guild.id):
            delivered += int(await self.deliver_responsible_notification(guild, request))
        return delivered

    async def deliver_terminal_notification(
        self, guild: discord.Guild, request: dict[str, object]
    ) -> bool:
        """Deliver a rejection/cancellation/expiration outcome exactly once per claim."""
        claimed = await self.services.tags.claim_terminal_notification(int(request["id"]))
        if not claimed:
            return False
        if not await self.services.settings.get(guild.id, "tag_dm_enabled"):
            await self.services.tags.mark_terminal_notification_delivered(
                int(claimed["id"]), delivery_message_id=None
            )
            return False
        labels = {
            "RECUSADO": "recusada",
            "CANCELADO": "cancelada",
            "EXPIRADO": "encerrada por expiração",
        }
        try:
            member = guild.get_member(int(claimed["discord_id"]))
            if member is None:
                member = await guild.fetch_member(int(claimed["discord_id"]))
            message = await member.send(
                "🏷️ **Atualização da sua solicitação de tag**\n"
                f"Sua solicitação foi **{labels[str(claimed['status'])]}**.\n"
                f"Motivo: {str(claimed['terminal_reason'])}",
                embed=request_embed(self.bot, claimed),
            )
        except discord.DiscordException as exc:
            await self.services.tags.mark_terminal_notification_failed(
                int(claimed["id"]), error=str(exc)
            )
            LOGGER.warning("Não foi possível entregar decisão da tag %s: %s", claimed["id"], exc)
            return False
        delivered = await self.services.tags.mark_terminal_notification_delivered(
            int(claimed["id"]), delivery_message_id=message.id
        )
        if delivered:
            await self.services.audit.record(
                guild.id,
                "TAG_TERMINAL_NOTIFICATION_DELIVERED",
                actor_id=int(claimed["terminal_by"] or 0) or None,
                target_id=int(claimed["discord_id"]),
                after={"tag_request_id": int(claimed["id"]), "message_id": message.id},
            )
        return delivered

    async def flush_terminal_notifications(self, guild: discord.Guild) -> int:
        delivered = 0
        for request in await self.services.tags.pending_terminal_notifications(guild.id):
            await self.refresh_request_card(guild, request)
            delivered += int(await self.deliver_terminal_notification(guild, request))
        return delivered

    async def flush_confirmation_notifications(self, guild: discord.Guild) -> int:
        delivered = 0
        for request in await self.services.tags.pending_confirmation_notifications(guild.id):
            delivered += int(await self.deliver_confirmation_notification(guild, request))
        return delivered

    async def expire_due_requests(self, guild: discord.Guild) -> list[int]:
        """Apply the guild's durable waiting limit during normal recovery.

        Only unassigned requests can expire in the domain service.  That keeps
        a restart from silently closing an appointment already owned by a
        responsible member.
        """
        configured_hours = await self.services.settings.get(guild.id, "tag_expiration_hours")
        max_wait_ms = max(1, int(configured_hours)) * 60 * 60 * 1_000
        expired_ids = await self.services.tags.expire_overdue(
            guild.id, max_wait_ms=max_wait_ms, actor_id=0
        )
        if expired_ids:
            await self.refresh_admin_panel(guild)
            for request_id in expired_ids:
                request = await self.services.tags.get_request(request_id)
                if request:
                    await self.refresh_request_card(guild, request)
        return expired_ids

    @tasks.loop(seconds=60)
    async def confirmation_retry(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            try:
                await self.services.tags.recover_confirmation_notification_claims()
                await self.services.tags.recover_responsible_notification_claims()
                await self.services.tags.recover_terminal_notification_claims()
                await self.restore_confirmation_views(guild)
                await self.restore_request_card_views(guild)
                await self.flush_responsible_notifications(guild)
                await self.flush_request_card_refreshes(guild)
                await self.flush_confirmation_notifications(guild)
                await self.expire_due_requests(guild)
                await self.flush_terminal_notifications(guild)
            except Exception:
                LOGGER.exception("Falha ao recuperar notificações de tag em %s", guild.id)

    @confirmation_retry.before_loop
    async def before_confirmation_retry(self) -> None:
        await self.bot.wait_until_ready()

    async def publish_or_refresh_member_panel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        panel = await self.services.settings.get_panel(guild.id, "TAG_MEMBER")
        embed = await build_member_panel_embed(self.bot, guild.id)
        if panel and int(panel["channel_id"]) == channel.id:
            try:
                message = await channel.fetch_message(int(panel["message_id"]))
                await message.edit(embed=embed, view=TagMemberPanelView())
                return message
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        retired = await self._retire_previous_panel(guild, panel, channel)
        try:
            message = await channel.send(embed=embed, view=TagMemberPanelView())
            await self.services.settings.upsert_panel(
                guild.id, "TAG_MEMBER", channel.id, message.id
            )
        except Exception:
            await self._restore_retired_panel(retired, TagMemberPanelView)
            raise
        return message

    async def publish_or_refresh_admin_panel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        panel = await self.services.settings.get_panel(guild.id, "TAG_ADMIN")
        embed = await build_admin_panel_embed(self.bot, guild.id)
        if panel and int(panel["channel_id"]) == channel.id:
            try:
                message = await channel.fetch_message(int(panel["message_id"]))
                await message.edit(embed=embed, view=None)
                return message
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        retired = await self._retire_previous_panel(guild, panel, channel)
        try:
            message = await channel.send(embed=embed)
            await self.services.settings.upsert_panel(
                guild.id, "TAG_ADMIN", channel.id, message.id
            )
        except Exception:
            await self._restore_retired_panel(retired, None)
            raise
        return message

    async def _retire_previous_panel(
        self,
        guild: discord.Guild,
        panel: Any,
        destination: discord.TextChannel,
    ) -> discord.Message | None:
        """Disable the old interactive message before moving a configured panel.

        A panel is a single control surface.  If Discord refuses to edit its
        prior message, the move fails closed rather than creating two live
        copies of the same persistent buttons in different channels.
        """
        if not panel or int(panel["channel_id"]) == destination.id:
            return None
        old_channel = guild.get_channel(int(panel["channel_id"]))
        if not isinstance(old_channel, discord.TextChannel):
            return None
        try:
            message = await old_channel.fetch_message(int(panel["message_id"]))
        except discord.NotFound:
            return None
        except discord.DiscordException as exc:
            raise ValidationError(
                "Não foi possível verificar o painel anterior. A configuração não foi alterada."
            ) from exc
        try:
            await message.edit(view=None)
        except discord.DiscordException as exc:
            raise ValidationError(
                "Não foi possível retirar os botões do painel anterior. A configuração não foi alterada."
            ) from exc
        return message

    async def _restore_retired_panel(
        self,
        message: discord.Message | None,
        view_type: type[discord.ui.View] | None,
    ) -> None:
        """Best-effort compensation when creating the replacement did not finish."""
        if message is None:
            return
        try:
            await message.edit(view=view_type() if view_type else None)
        except discord.DiscordException:
            LOGGER.exception("Falha ao restaurar painel de tags após mover configuração")

    async def refresh_admin_panel(self, guild: discord.Guild) -> None:
        channel_id = await self.services.settings.get(guild.id, "tag_admin_panel_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            await self.publish_or_refresh_admin_panel(guild, channel)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            await self.services.tags.recover_confirmation_notification_claims()
            await self.services.tags.recover_responsible_notification_claims()
            await self.services.tags.recover_terminal_notification_claims()
            await self.restore_confirmation_views(guild)
            await self.restore_request_card_views(guild)
            await self.flush_responsible_notifications(guild)
            await self.flush_request_card_refreshes(guild)
            await self.flush_confirmation_notifications(guild)
            await self.expire_due_requests(guild)
            await self.flush_terminal_notifications(guild)
            for setting_key, panel_type in (
                ("tag_member_panel_channel_id", "TAG_MEMBER"),
                ("tag_admin_panel_channel_id", "TAG_ADMIN"),
            ):
                channel_id = await self.services.settings.get(guild.id, setting_key)
                channel = guild.get_channel(int(channel_id)) if channel_id else None
                if not isinstance(channel, discord.TextChannel):
                    continue
                try:
                    if panel_type == "TAG_MEMBER":
                        await self.publish_or_refresh_member_panel(guild, channel)
                    else:
                        await self.publish_or_refresh_admin_panel(guild, channel)
                except discord.DiscordException:
                    LOGGER.exception("Falha ao restaurar painel de tags em %s", guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TagCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
