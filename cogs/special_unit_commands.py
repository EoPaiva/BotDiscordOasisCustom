from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

import discord
from discord.ext import commands

from choque.embeds import branded_embed
from choque.errors import PermissionDenied, ValidationError
from choque.special_units import UNIT_CODES

from .config_ui import respond_error

LOGGER = logging.getLogger(__name__)
UNIT_DISPLAY = {
    "ROCAM": "ROCAM",
    "TATICO": "TÁTICO",
    "ELITE": "ELITE",
    "CORREGEDORIA": "CORREGEDORIA",
}
UNIT_COLORS = {
    "ROCAM": 0x1F6FEB,
    "TATICO": 0xC0392B,
    "ELITE": 0x8E44AD,
    "CORREGEDORIA": 0xD4AC0D,
}


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


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


async def canonical_guild_id(interaction: discord.Interaction) -> int:
    if interaction.guild is None:
        raise ValidationError("Use este painel dentro do servidor.")
    bot = get_bot(interaction)
    source = await bot.services.settings.get(
        interaction.guild.id, "identity_source_guild_id"
    )
    return int(source or interaction.guild.id)


async def require_unit_staff(
    interaction: discord.Interaction,
    unit_code: str | None = None,
    *,
    command_only: bool = False,
) -> discord.Member:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Use esta ação dentro do servidor.")
    member = interaction.user
    if member.guild_permissions.administrator:
        return member
    bot = get_bot(interaction)
    if await bot.services.permissions.has(member, "recruitment.approve"):
        return member
    codes = [unit_code] if unit_code else sorted(UNIT_CODES)
    for code in codes:
        row = await bot.services.database.fetchone(
            """
            SELECT assistant_role_id, command_role_id
            FROM special_unit_guild_resources WHERE guild_id=? AND unit_code=?
            """,
            (member.guild.id, code),
        )
        if row is None:
            continue
        allowed = {int(row["command_role_id"])}
        if not command_only:
            allowed.add(int(row["assistant_role_id"]))
        if any(role.id in allowed for role in member.roles):
            return member
    raise PermissionDenied("Você não possui autorização para esta ação da unidade.")


def candidate_panel_embed(bot: ChoqueBot) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title="🛡️ Unidades Especiais • Candidaturas",
        description=(
            "Escolha a unidade desejada para enviar sua candidatura.\n\n"
            "A identidade é validada pelo efetivo oficial da CHOQUE. Só é permitida "
            "uma candidatura pendente por membro, e toda decisão permanece auditada."
        ),
    )


def admin_panel_embed(bot: ChoqueBot, pending: int) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="📋 Mesa • Unidades Especiais",
        description=(
            "Fila administrativa persistente. Assuma uma candidatura antes de decidir; "
            "a aprovação sincroniza cargos nos dois servidores sem reduzir patente."
        ),
    )
    embed.add_field(name="Pendentes", value=str(pending), inline=True)
    return embed


def central_embed(bot: ChoqueBot, unit_code: str) -> discord.Embed:
    display = UNIT_DISPLAY[unit_code]
    embed = branded_embed(
        bot.config.branding,
        title=f"🛡️ Central • {display}",
        description=(
            "Ambiente interno da unidade. Os controles exibem somente informações "
            "permitidas ao seu nível funcional."
        ),
        color=discord.Color(UNIT_COLORS[unit_code]),
    )
    embed.add_field(
        name="Controles",
        value="Membros • Tags • Registros • Cursos • Administração",
        inline=False,
    )
    return embed


class UnitApplicationSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Escolha uma unidade especial",
            custom_id="choque:special-unit:apply:v1",
            options=[
                discord.SelectOption(label=UNIT_DISPLAY[code], value=code)
                for code in ("ROCAM", "TATICO", "ELITE", "CORREGEDORIA")
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            raise ValidationError("Use este painel dentro do servidor REC.")
        result = await get_bot(interaction).services.special_units.submit_application(
            interaction.guild.id, interaction.user.id, self.values[0]
        )
        await interaction.response.send_message(
            f"✅ Candidatura `#{result['id']}` para **{UNIT_DISPLAY[self.values[0]]}** enviada.",
            ephemeral=True,
        )
        cog = get_bot(interaction).get_cog("SpecialUnitCommands")
        if isinstance(cog, SpecialUnitCommands):
            await cog.refresh_admin_panel(interaction.guild)


class UnitCandidatePanelView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(UnitApplicationSelect())


class UnitQueueSelect(discord.ui.Select):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = {str(row["id"]): row for row in rows}
        super().__init__(
            placeholder="Escolha uma candidatura",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['mta_nick']}"[:100],
                    value=str(row["id"]),
                    description=f"{UNIT_DISPLAY[str(row['unit_code'])]} • ID {row['character_id']}"[:100],
                )
                for row in rows[:25]
            ],
            disabled=not rows,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_unit_staff(interaction)
        row = self.rows[self.values[0]]
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title=f"Candidatura #{row['id']} • {UNIT_DISPLAY[str(row['unit_code'])]}",
            description=f"<@{row['discord_id']}> • `{row['mta_nick']}` • ID `{row['character_id']}`",
        )
        embed.add_field(name="Patente", value=str(row.get("rank_name") or "—"), inline=True)
        embed.add_field(
            name="Responsável",
            value=f"<@{row['assigned_to']}>" if row.get("assigned_to") else "Não assumida",
            inline=True,
        )
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=UnitApplicationReviewView(
                int(row["id"]), str(row["unit_code"]), int(row["version"])
            ),
        )


class UnitQueueView(ErrorView):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__(timeout=600)
        self.add_item(UnitQueueSelect(rows))


class UnitDecisionModal(ErrorModal):
    reason = discord.ui.TextInput(
        label="Justificativa", style=discord.TextStyle.paragraph, min_length=3, max_length=500
    )

    def __init__(self, application_id: int, unit_code: str, version: int, approved: bool) -> None:
        super().__init__(title="Aprovar candidatura" if approved else "Reprovar candidatura")
        self.application_id = application_id
        self.unit_code = unit_code
        self.version = version
        self.approved = approved

    async def on_submit(self, interaction: discord.Interaction) -> None:
        reviewer = await require_unit_staff(interaction, self.unit_code, command_only=True)
        result = await get_bot(interaction).services.special_units.decide(
            self.application_id,
            reviewer.id,
            approved=self.approved,
            reason=str(self.reason),
            expected_version=self.version,
        )
        await interaction.response.send_message(
            f"✅ Candidatura `#{result['id']}` encerrada como **{result['status']}**.",
            ephemeral=True,
        )
        bot = get_bot(interaction)
        try:
            candidate = bot.get_user(int(result["discord_id"])) or await bot.fetch_user(
                int(result["discord_id"])
            )
            await candidate.send(
                f"Sua candidatura para **{UNIT_DISPLAY[self.unit_code]}** foi "
                f"**{'aprovada' if self.approved else 'reprovada'}**.\n"
                f"Justificativa: {str(self.reason)[:500]}"
            )
        except discord.DiscordException:
            LOGGER.info("DM da candidatura de unidade %s não entregue", result["id"])
        cog = bot.get_cog("SpecialUnitCommands")
        if isinstance(cog, SpecialUnitCommands) and interaction.guild:
            await cog.refresh_admin_panel(interaction.guild)


class UnitApplicationReviewView(ErrorView):
    def __init__(self, application_id: int, unit_code: str, version: int) -> None:
        super().__init__(timeout=600)
        self.application_id = application_id
        self.unit_code = unit_code
        self.version = version

    @discord.ui.button(label="Assumir", emoji="✋", style=discord.ButtonStyle.primary)
    async def assign(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        reviewer = await require_unit_staff(interaction, self.unit_code)
        result = await get_bot(interaction).services.special_units.assign(
            self.application_id, reviewer.id, expected_version=self.version
        )
        self.version = int(result["version"])
        await interaction.response.send_message("✅ Candidatura assumida.", ephemeral=True)

    @discord.ui.button(label="Aprovar", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_unit_staff(interaction, self.unit_code, command_only=True)
        await interaction.response.send_modal(
            UnitDecisionModal(self.application_id, self.unit_code, self.version, True)
        )

    @discord.ui.button(label="Reprovar", emoji="❌", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_unit_staff(interaction, self.unit_code, command_only=True)
        await interaction.response.send_modal(
            UnitDecisionModal(self.application_id, self.unit_code, self.version, False)
        )


class UnitAdminPanelView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abrir fila",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        custom_id="choque:special-unit:queue:v1",
    )
    async def queue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_unit_staff(interaction)
        if interaction.guild is None:
            raise ValidationError("Use o painel dentro do servidor REC.")
        rows = [
            dict(row)
            for row in await get_bot(interaction).services.special_units.queue(
                interaction.guild.id
            )
        ]
        await interaction.response.send_message(
            "Selecione uma candidatura pendente.", view=UnitQueueView(rows), ephemeral=True
        )


class UnitMemberManagementModal(ErrorModal):
    discord_id = discord.ui.TextInput(label="Discord ID do membro", min_length=5, max_length=32)
    reason = discord.ui.TextInput(
        label="Motivo", style=discord.TextStyle.paragraph, min_length=3, max_length=500
    )

    def __init__(self, unit_code: str, action: str) -> None:
        titles = {
            "COMMAND": "Designar comando",
            "ASSISTANT": "Designar auxiliar",
            "MEMBER": "Definir como integrante",
            "LEAVE": "Registrar saída",
        }
        super().__init__(title=titles[action])
        self.unit_code = unit_code
        self.action = action

    async def on_submit(self, interaction: discord.Interaction) -> None:
        admin = await require_unit_staff(interaction, self.unit_code, command_only=True)
        canonical = await canonical_guild_id(interaction)
        target_id = int(str(self.discord_id))
        service = get_bot(interaction).services.special_units
        if self.action == "LEAVE":
            await service.leave(
                canonical,
                self.unit_code,
                target_id,
                actor_id=admin.id,
                reason=str(self.reason),
            )
            result = "saída registrada"
        else:
            await service.set_role_level(
                canonical,
                self.unit_code,
                target_id,
                self.action,
                actor_id=admin.id,
                reason=str(self.reason),
            )
            result = f"nível alterado para {self.action}"
        await interaction.response.send_message(
            f"✅ <@{target_id}>: {result}, com sincronização e auditoria.", ephemeral=True
        )


class UnitMemberManagementView(ErrorView):
    def __init__(self, unit_code: str) -> None:
        super().__init__(timeout=600)
        self.unit_code = unit_code
        for label, emoji, action in (
            ("Comando", "⭐", "COMMAND"),
            ("Auxiliar", "🛡️", "ASSISTANT"),
            ("Integrante", "👤", "MEMBER"),
            ("Registrar saída", "🚪", "LEAVE"),
        ):
            button = discord.ui.Button(
                label=label,
                emoji=emoji,
                style=(
                    discord.ButtonStyle.danger
                    if action == "LEAVE"
                    else discord.ButtonStyle.secondary
                ),
            )

            async def callback(
                interaction: discord.Interaction, selected_action: str = action
            ) -> None:
                await require_unit_staff(interaction, self.unit_code, command_only=True)
                await interaction.response.send_modal(
                    UnitMemberManagementModal(self.unit_code, selected_action)
                )

            button.callback = callback
            self.add_item(button)


class UnitCentralView(ErrorView):
    def __init__(self, unit_code: str) -> None:
        super().__init__(timeout=None)
        self.unit_code = unit_code
        for label, emoji, action in (
            ("Membros", "👥", "members"),
            ("Tags", "🏷️", "tags"),
            ("Registros", "📚", "records"),
            ("Cursos", "🎓", "courses"),
            ("Administração", "🛡️", "admin"),
        ):
            button = discord.ui.Button(
                label=label,
                emoji=emoji,
                custom_id=f"choque:special-unit:{unit_code.lower()}:{action}:v1",
                style=(
                    discord.ButtonStyle.danger
                    if action == "admin"
                    else discord.ButtonStyle.secondary
                ),
            )
            button.callback = self._callback(action)
            self.add_item(button)

    def _callback(self, action: str):
        async def callback(interaction: discord.Interaction) -> None:
            command_only = action == "admin"
            await require_unit_staff(
                interaction, self.unit_code, command_only=command_only
            )
            bot = get_bot(interaction)
            canonical = await canonical_guild_id(interaction)
            if action == "members":
                rows = await bot.services.special_units.memberships(
                    canonical, self.unit_code
                )
                text = "\n".join(
                    f"• <@{row['discord_id']}> • {row['role_level']} • {row['rank_name'] or '—'}"
                    for row in rows[:40]
                ) or "Nenhum membro ativo nesta unidade."
            elif action == "tags":
                text = "A gestão de tags usa a Central de Tags oficial, sem cadastro paralelo."
            elif action == "records":
                events = await bot.services.database.fetchall(
                    """
                    SELECT event_type, actor_id, created_at FROM special_unit_events
                    WHERE canonical_guild_id=? AND unit_code=?
                    ORDER BY id DESC LIMIT 20
                    """,
                    (canonical, self.unit_code),
                )
                text = "\n".join(
                    f"• `{row['event_type']}` • <@{row['actor_id']}>" for row in events
                ) or "Nenhum registro disponível."
            elif action == "courses":
                text = "Os cursos permanecem no sistema oficial de Qualificações."
            else:
                await interaction.response.send_message(
                    "Administração auditada da unidade.",
                    view=UnitMemberManagementView(self.unit_code),
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(text[:1900], ephemeral=True)

        return callback


class SpecialUnitCommands(commands.Cog):
    def __init__(self, bot: ChoqueBot) -> None:
        self.bot = bot
        self.services = bot.services
        self._provision_lock = asyncio.Lock()
        self._provisioned = False
        self.bot.add_view(UnitCandidatePanelView())
        self.bot.add_view(UnitAdminPanelView())
        for code in UNIT_CODES:
            self.bot.add_view(UnitCentralView(code))

    async def _ensure_role(self, guild: discord.Guild, name: str, color: int) -> discord.Role:
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            role = await guild.create_role(
                name=name,
                permissions=discord.Permissions.none(),
                color=discord.Color(color),
                reason="Provisionamento auditável das Unidades Especiais",
            )
        elif role.permissions.value != 0:
            raise ValidationError(f"O cargo `{name}` possui permissões globais indevidas.")
        return role

    async def _ensure_category(
        self, guild: discord.Guild, name: str, overwrites: dict
    ) -> discord.CategoryChannel:
        category = discord.utils.get(guild.categories, name=name)
        if category is None:
            category = await guild.create_category(
                name, overwrites=overwrites, reason="Unidades Especiais"
            )
        else:
            await category.edit(overwrites=overwrites, reason="Permissões das Unidades Especiais")
        return category

    async def _ensure_channel(
        self, category: discord.CategoryChannel, name: str
    ) -> discord.TextChannel:
        channel = discord.utils.get(category.text_channels, name=name)
        if channel is None:
            channel = await category.create_text_channel(name, reason="Unidades Especiais")
        return channel

    async def _ensure_panel(
        self,
        guild: discord.Guild,
        panel_type: str,
        channel: discord.TextChannel,
        embed: discord.Embed,
        view: discord.ui.View,
    ) -> discord.Message:
        existing = await self.services.settings.get_panel(guild.id, panel_type)
        message = None
        if existing and int(existing["channel_id"]) == channel.id:
            try:
                message = await channel.fetch_message(int(existing["message_id"]))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                message = None
        if message is None:
            message = await channel.send(embed=embed, view=view)
            await self.services.settings.upsert_panel(
                guild.id, panel_type, channel.id, message.id
            )
        else:
            await message.edit(embed=embed, view=view)
        try:
            await message.pin(reason="Painel persistente das Unidades Especiais")
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.warning("Não foi possível fixar painel %s em %s", panel_type, guild.id)
        return message

    async def _provision_roles(self, guild: discord.Guild) -> dict[str, tuple[discord.Role, ...]]:
        roles: dict[str, tuple[discord.Role, ...]] = {}
        for code in ("ROCAM", "TATICO", "ELITE", "CORREGEDORIA"):
            display = UNIT_DISPLAY[code]
            color = UNIT_COLORS[code]
            member = await self._ensure_role(guild, display, color)
            assistant = await self._ensure_role(guild, f"AUXILIAR • {display}", color)
            command = await self._ensure_role(guild, f"COMANDO • {display}", color)
            roles[code] = (member, assistant, command)
        if guild.me and guild.me.top_role.position > 1:
            ordered = [
                role
                for code in ("ROCAM", "TATICO", "ELITE", "CORREGEDORIA")
                for role in reversed(roles[code])
            ]
            top = guild.me.top_role.position - 1
            positions = {
                role: max(1, top - index) for index, role in enumerate(ordered)
            }
            try:
                await guild.edit_role_positions(
                    positions=positions,
                    reason="Hierarquia equivalente das Unidades Especiais",
                )
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.warning("Não foi possível ordenar cargos de unidades em %s", guild.id)
        return roles

    async def _provision_primary(self, guild: discord.Guild) -> None:
        roles = await self._provision_roles(guild)
        for code, (member, assistant, command) in roles.items():
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                assistant: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                command: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_messages=True
                ),
            }
            if guild.me:
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_messages=True
                )
            category = await self._ensure_category(
                guild, f"╭─ {UNIT_DISPLAY[code]}", overwrites
            )
            channel = await self._ensure_channel(category, "central")
            await self.services.special_units.upsert_guild_resource(
                code,
                guild.id,
                category_id=category.id,
                central_channel_id=channel.id,
                member_role_id=member.id,
                assistant_role_id=assistant.id,
                command_role_id=command.id,
            )
            await self._ensure_panel(
                guild,
                f"special_unit_central:{code}",
                channel,
                central_embed(self.bot, code),
                UnitCentralView(code),
            )

    async def _provision_rec(self, guild: discord.Guild, primary_id: int) -> None:
        roles = await self._provision_roles(guild)
        member_role_id = await self.services.settings.get(guild.id, "member_role_id")
        member_role = guild.get_role(int(member_role_id)) if member_role_id else None
        if member_role is None:
            member_role = discord.utils.get(guild.roles, name="Membro Choque")
            if member_role is not None:
                await self.services.settings.set(
                    guild.id, "member_role_id", member_role.id, guild.owner_id
                )
        staff_roles = {
            role for group in roles.values() for role in (group[1], group[2])
        }
        staff_roles.update(
            role
            for name in (
                "Comando REC",
                "Responsável Recrutamento",
                "Auxiliar Recrutamento",
                "Instrutor de Cursos",
            )
            if (role := discord.utils.get(guild.roles, name=name)) is not None
        )
        public_overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False)
        }
        if member_role:
            public_overwrites[member_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=False
            )
        for role in staff_roles:
            public_overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True
            )
        if guild.me:
            public_overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True
            )
        category = await self._ensure_category(guild, "╭─ UNIDADES ESPECIAIS", public_overwrites)
        candidate_channel = await self._ensure_channel(category, "candidaturas-unidades")

        admin_overwrites = dict(public_overwrites)
        if member_role:
            admin_overwrites[member_role] = discord.PermissionOverwrite(view_channel=False)
        admin_category = await self._ensure_category(
            guild, "╭─ ADM UNIDADES", admin_overwrites
        )
        admin_channel = await self._ensure_channel(admin_category, "mesa-unidades")
        await self.services.settings.set(
            guild.id, "identity_source_guild_id", primary_id, None
        )
        await self.services.settings.set(
            guild.id, "special_units_recruitment_category_id", category.id, None
        )
        await self.services.settings.set(
            guild.id, "special_units_recruitment_channel_id", candidate_channel.id, None
        )
        for code, (member, assistant, command) in roles.items():
            await self.services.special_units.upsert_guild_resource(
                code,
                guild.id,
                category_id=category.id,
                central_channel_id=candidate_channel.id,
                member_role_id=member.id,
                assistant_role_id=assistant.id,
                command_role_id=command.id,
            )
        await self._ensure_panel(
            guild,
            "special_unit_candidate",
            candidate_channel,
            candidate_panel_embed(self.bot),
            UnitCandidatePanelView(),
        )
        pending = len(await self.services.special_units.queue(guild.id))
        await self._ensure_panel(
            guild,
            "special_unit_admin",
            admin_channel,
            admin_panel_embed(self.bot, pending),
            UnitAdminPanelView(),
        )

    async def refresh_admin_panel(self, guild: discord.Guild) -> None:
        panel = await self.services.settings.get_panel(guild.id, "special_unit_admin")
        if not panel:
            return
        channel = guild.get_channel(int(panel["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(int(panel["message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        pending = len(await self.services.special_units.queue(guild.id))
        await message.edit(embed=admin_panel_embed(self.bot, pending), view=UnitAdminPanelView())

    async def provision(self) -> None:
        async with self._provision_lock:
            if self._provisioned:
                return
            primary_id = int(self.bot.guild_id or 0)
            primary = self.bot.get_guild(primary_id)
            if primary is None:
                return
            linked_guild_ids = (
                await self.services.special_units.linked_recruitment_guild_ids(primary_id)
            )
            rec_guilds = [
                guild
                for guild_id in linked_guild_ids
                if (guild := self.bot.get_guild(guild_id)) is not None
                and guild.id != primary_id
            ]
            if not rec_guilds:
                LOGGER.warning("Servidor REC não localizado; unidades não provisionadas.")
                return
            await self._provision_primary(primary)
            for guild in rec_guilds:
                await self._provision_rec(guild, primary_id)
            self._provisioned = True

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        try:
            await self.provision()
        except Exception:
            LOGGER.exception("Falha ao recuperar/provisionar Unidades Especiais")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        primary_id = int(
            await self.services.settings.get(
                member.guild.id, "identity_source_guild_id", self.bot.guild_id
            )
        )
        managed, desired = await self.services.special_units.desired_role_ids(
            member.guild.id, primary_id, member.id
        )
        if not managed:
            return
        remove = [role for role in member.roles if role.id in managed and role.id not in desired]
        add = [role for role_id in desired if (role := member.guild.get_role(role_id))]
        if remove:
            await member.remove_roles(*remove, reason="Reconciliação de Unidade Especial")
        if add:
            await member.add_roles(*add, reason="Reconciliação de Unidade Especial")


async def setup(bot: ChoqueBot) -> None:
    await bot.add_cog(SpecialUnitCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
