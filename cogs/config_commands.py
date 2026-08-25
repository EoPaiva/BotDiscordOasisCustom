from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Literal, cast

import discord
from discord import app_commands
from discord.ext import commands

from choque.errors import PermissionDenied, ValidationError
from choque.identity_queue import enqueue_identity_reconciliation
from choque.models import RbacProfile
from choque.time_utils import utc_now_ms
from cogs.config_ui import ConfigurationMenuView, build_configuration_status

LOGGER = logging.getLogger(__name__)


def interaction_member(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Este comando só pode ser usado dentro do servidor.")
    return interaction.user


class ConfigurationCommands(commands.Cog):
    configurar = app_commands.Group(name="configurar", description="Configuração do sistema")
    call_group = app_commands.Group(name="call", description="Calls autorizadas", parent=configurar)
    role_group = app_commands.Group(
        name="cargo", description="Vínculos de cargos e permissões", parent=configurar
    )
    channel_group = app_commands.Group(
        name="canal", description="Canais do sistema", parent=configurar
    )
    rank_group = app_commands.Group(
        name="patente", description="Patentes ordenadas", parent=configurar
    )
    rule_group = app_commands.Group(
        name="regra", description="Regras operacionais", parent=configurar
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._config_panel_lock = asyncio.Lock()
        self.bot.add_view(ConfigurationMenuView())

    async def publish_or_refresh_config_panel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        async with self._config_panel_lock:
            embed = await build_configuration_status(self.bot, guild)
            panel = await self.services.settings.get_panel(guild.id, "CONFIG")
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                    await message.edit(embed=embed, view=ConfigurationMenuView())
                    return message
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            message = await channel.send(embed=embed, view=ConfigurationMenuView())
            await self.services.settings.upsert_panel(
                guild.id, "CONFIG", message.channel.id, message.id
            )
            return message

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            channel_id = await self.services.settings.get(guild.id, "config_panel_channel_id")
            if not channel_id:
                panel = await self.services.settings.get_panel(guild.id, "CONFIG")
                channel_id = int(panel["channel_id"]) if panel else None
            if not channel_id:
                continue
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                LOGGER.warning("Canal do menu de configuração não encontrado: %s", channel_id)
                continue
            try:
                await self.publish_or_refresh_config_panel(guild, channel)
            except discord.DiscordException:
                LOGGER.exception("Falha ao restaurar menu de configuração na guild %s", guild.id)

    async def _require(self, interaction: discord.Interaction) -> discord.Member:
        actor = interaction_member(interaction)
        if not await self.services.permissions.has(actor, "settings.manage"):
            raise PermissionDenied("Você não possui permissão para alterar configurações.")
        return actor

    @call_group.command(name="adicionar", description="Autoriza uma call para o ponto.")
    async def call_add(self, interaction: discord.Interaction, call: discord.VoiceChannel) -> None:
        actor = await self._require(interaction)
        async with self.services.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO authorized_voice_channels(
                    guild_id, channel_id, label, created_at, created_by,
                    service_allowed, counts_toward_patrol_minimum
                ) VALUES (?, ?, ?, ?, ?, 1, 1)
                ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                    label=excluded.label,
                    service_allowed=1
                """,
                (actor.guild.id, call.id, call.name, utc_now_ms(), actor.id),
            )
            await self.services.audit.record(
                actor.guild.id,
                "AUTHORIZED_CALL_ADDED",
                actor_id=actor.id,
                target_id=call.id,
                after={"channel_id": call.id, "name": call.name},
                connection=connection,
            )
        await interaction.response.send_message(
            f"Call {call.mention} autorizada para o ponto.", ephemeral=True
        )

    @call_group.command(name="remover", description="Remove uma call autorizada.")
    async def call_remove(
        self, interaction: discord.Interaction, call: discord.VoiceChannel
    ) -> None:
        actor = await self._require(interaction)
        async with self.services.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM authorized_voice_channels WHERE guild_id=? AND channel_id=?",
                (actor.guild.id, call.id),
            )
            await self.services.audit.record(
                actor.guild.id,
                "AUTHORIZED_CALL_REMOVED",
                actor_id=actor.id,
                target_id=call.id,
                before={"channel_id": call.id},
                connection=connection,
            )
        await interaction.response.send_message(f"Call {call.mention} removida.", ephemeral=True)

    @call_group.command(name="listar", description="Lista as calls autorizadas.")
    async def call_list(self, interaction: discord.Interaction) -> None:
        actor = await self._require(interaction)
        rows = await self.services.database.fetchall(
            "SELECT channel_id, label FROM authorized_voice_channels WHERE guild_id=? ORDER BY label",
            (actor.guild.id,),
        )
        text = "\n".join(f"• <#{row['channel_id']}> — {row['label']}" for row in rows)
        await interaction.response.send_message(text or "Nenhuma call autorizada.", ephemeral=True)

    @role_group.command(name="vincular", description="Vincula um cargo a um perfil RBAC.")
    async def role_bind(
        self,
        interaction: discord.Interaction,
        cargo: discord.Role,
        perfil: Literal[
            "CANDIDATO",
            "RECRUTA",
            "MEMBRO",
            "GRADUADO",
            "INSTRUTOR",
            "SUPERVISOR",
            "COMANDO",
            "ALTO_COMANDO",
            "RESPONSAVEL_UPAMENTO",
            "ADMINISTRADOR",
        ],
    ) -> None:
        actor = await self._require(interaction)
        profile = RbacProfile(perfil)
        async with self.services.database.transaction() as connection:
            reconciliation = await self.services.settings.bind_role(
                actor.guild.id,
                cargo.id,
                profile,
                actor.id,
                "LEGACY_DISCORD_COMMAND_RBAC_CHANGED",
                connection=connection,
            )
            await self.services.audit.record(
                actor.guild.id,
                "RBAC_ROLE_BOUND",
                actor_id=actor.id,
                target_id=cargo.id,
                after={
                    "role_id": cargo.id,
                    "profile": profile.value,
                    "reconciliation_job_id": reconciliation["job_id"],
                },
                connection=connection,
            )
        await self.services.permissions.invalidate(actor.guild.id)
        await interaction.response.send_message(
            f"{cargo.mention} vinculado a `{profile.value}`.", ephemeral=True
        )

    @role_group.command(name="remover", description="Remove o vínculo RBAC de um cargo.")
    async def role_remove(self, interaction: discord.Interaction, cargo: discord.Role) -> None:
        actor = await self._require(interaction)
        async with self.services.database.transaction() as connection:
            reconciliation = await self.services.settings.unbind_role(
                actor.guild.id,
                cargo.id,
                actor.id,
                "LEGACY_DISCORD_COMMAND_RBAC_REMOVED",
                connection=connection,
            )
            await self.services.audit.record(
                actor.guild.id,
                "RBAC_ROLE_UNBOUND",
                actor_id=actor.id,
                target_id=cargo.id,
                before={"role_id": cargo.id},
                after={"reconciliation_job_id": reconciliation["job_id"]},
                connection=connection,
            )
        await self.services.permissions.invalidate(actor.guild.id)
        await interaction.response.send_message("Vínculo removido.", ephemeral=True)

    @role_group.command(name="listar", description="Lista os vínculos RBAC.")
    async def role_list(self, interaction: discord.Interaction) -> None:
        actor = await self._require(interaction)
        rows = await self.services.database.fetchall(
            """
            SELECT drm.discord_role_id AS role_id, ap.code AS profile
            FROM discord_role_mappings drm
            JOIN access_profiles ap ON ap.id=drm.access_profile_id
            WHERE drm.guild_id=? AND drm.mapping_type='ACCESS' AND drm.enabled=1
            ORDER BY ap.priority, drm.discord_role_id
            """,
            (actor.guild.id,),
        )
        text = "\n".join(f"• <@&{row['role_id']}> → `{row['profile']}`" for row in rows)
        await interaction.response.send_message(
            text or "Nenhum vínculo configurado.", ephemeral=True
        )

    @channel_group.command(name="definir", description="Define um canal operacional.")
    async def channel_set(
        self,
        interaction: discord.Interaction,
        tipo: Literal[
            "auditoria",
            "aprovacao",
            "cadastro",
            "ponto",
            "efetivo",
            "hierarquia",
            "configuracao",
            "administracao",
            "afastamentos",
            "ranking",
        ],
        canal: discord.TextChannel,
    ) -> None:
        actor = await self._require(interaction)
        key = {
            "auditoria": "audit_channel_id",
            "aprovacao": "registration_approval_channel_id",
            "cadastro": "registration_panel_channel_id",
            "ponto": "point_panel_channel_id",
            "efetivo": "service_panel_channel_id",
            "hierarquia": "hierarchy_channel_id",
            "configuracao": "config_panel_channel_id",
            "administracao": "personnel_admin_channel_id",
            "afastamentos": "absence_panel_channel_id",
            "ranking": "ranking_panel_channel_id",
        }[tipo]
        before = await self.services.settings.get(actor.guild.id, key)
        async with self.services.database.transaction() as connection:
            await self.services.settings.set(actor.guild.id, key, canal.id, actor.id, connection)
            await self.services.audit.record(
                actor.guild.id,
                "SETTING_CHANGED",
                actor_id=actor.id,
                before={key: before},
                after={key: canal.id},
                connection=connection,
            )
        await interaction.response.send_message(
            f"Canal de `{tipo}` definido como {canal.mention}.", ephemeral=True
        )

    @rank_group.command(name="definir", description="Cria ou atualiza uma patente ordenada.")
    async def rank_set(
        self,
        interaction: discord.Interaction,
        nivel: app_commands.Range[int, 1, 999],
        nome: str,
        prefixo: str,
        cargo: discord.Role | None = None,
        perfil: Literal["MEMBRO", "GRADUADO", "INSTRUTOR", "COMANDO", "ADMINISTRADOR"] = "MEMBRO",
    ) -> None:
        actor = await self._require(interaction)
        if not nome.strip():
            raise ValidationError("O nome da patente é obrigatório.")
        async with self.services.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM ranks WHERE guild_id=? AND level=?",
                (actor.guild.id, int(nivel)),
            )
            before = await cursor.fetchone()
            await connection.execute(
                """
                INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, level) DO UPDATE SET name=excluded.name,
                    prefix=excluded.prefix, rbac_profile=excluded.rbac_profile, active=1
                """,
                (
                    actor.guild.id,
                    nome.strip(),
                    prefixo.strip(),
                    int(nivel),
                    perfil,
                    utc_now_ms(),
                ),
            )
            saved_cursor = await connection.execute(
                "SELECT id FROM ranks WHERE guild_id=? AND level=?",
                (actor.guild.id, int(nivel)),
            )
            saved_rank = await saved_cursor.fetchone()
            assert saved_rank is not None
            await self.services.settings.set_rank_role_mapping(
                actor.guild.id,
                int(saved_rank["id"]),
                cargo.id if cargo else None,
                actor.id,
                enabled=True,
                connection=connection,
            )
            reconciliation = await enqueue_identity_reconciliation(
                connection,
                guild_id=actor.guild.id,
                requested_by=actor.id,
                mode="APPLY",
                source="RANK_MAPPING_CHANGED",
            )
            await self.services.audit.record(
                actor.guild.id,
                "RANK_UPSERTED",
                actor_id=actor.id,
                target_id=cargo.id if cargo else None,
                before=dict(before) if before else None,
                after={
                    "level": int(nivel),
                    "name": nome,
                    "prefix": prefixo,
                    "profile": perfil,
                    "role_id": cargo.id if cargo else None,
                    "reconciliation_job_id": reconciliation["job_id"],
                },
                connection=connection,
            )
        await interaction.response.send_message(
            f"Patente nível {nivel} definida como **{nome}**.", ephemeral=True
        )

    @rank_group.command(name="remover", description="Desativa uma patente sem apagar histórico.")
    async def rank_remove(
        self, interaction: discord.Interaction, nivel: app_commands.Range[int, 1, 999]
    ) -> None:
        actor = await self._require(interaction)
        async with self.services.database.transaction() as connection:
            rank_cursor = await connection.execute(
                "SELECT id, discord_role_id FROM ranks WHERE guild_id=? AND level=?",
                (actor.guild.id, int(nivel)),
            )
            rank = await rank_cursor.fetchone()
            if rank is None:
                raise ValidationError("Patente não encontrada nesse nível.")
            await connection.execute(
                "UPDATE ranks SET active=0 WHERE guild_id=? AND level=?",
                (actor.guild.id, int(nivel)),
            )
            await self.services.settings.set_rank_role_mapping(
                actor.guild.id,
                int(rank["id"]),
                int(rank["discord_role_id"]) if rank["discord_role_id"] is not None else None,
                actor.id,
                enabled=False,
                connection=connection,
            )
            reconciliation = await enqueue_identity_reconciliation(
                connection,
                guild_id=actor.guild.id,
                requested_by=actor.id,
                mode="APPLY",
                source="RANK_MAPPING_DISABLED",
            )
            await self.services.audit.record(
                actor.guild.id,
                "RANK_DEACTIVATED",
                actor_id=actor.id,
                after={
                    "level": int(nivel),
                    "active": False,
                    "reconciliation_job_id": reconciliation["job_id"],
                },
                connection=connection,
            )
        await interaction.response.send_message("Patente desativada.", ephemeral=True)

    @rank_group.command(name="listar", description="Lista a hierarquia configurada.")
    async def rank_list(self, interaction: discord.Interaction) -> None:
        actor = await self._require(interaction)
        rows = await self.services.database.fetchall(
            """
            SELECT level, name, prefix, discord_role_id, rbac_profile, active
            FROM ranks WHERE guild_id=? ORDER BY level
            """,
            (actor.guild.id,),
        )
        text = "\n".join(
            f"`{row['level']:03d}` {row['prefix']} **{row['name']}** "
            f"{f'<@&{row["discord_role_id"]}>' if row['discord_role_id'] else ''} "
            f"`{row['rbac_profile']}`{' (inativa)' if not row['active'] else ''}"
            for row in rows
        )
        await interaction.response.send_message(text or "Nenhuma patente definida.", ephemeral=True)

    @rule_group.command(name="definir", description="Define uma regra operacional.")
    async def rule_set(
        self,
        interaction: discord.Interaction,
        regra: Literal[
            "tolerancia_segundos",
            "meta_semanal_minutos",
            "timezone",
            "cargo_servico",
            "cargo_membro",
        ],
        valor: str,
    ) -> None:
        actor = await self._require(interaction)
        key = {
            "tolerancia_segundos": "grace_period_seconds",
            "meta_semanal_minutos": "weekly_goal_minutes",
            "timezone": "timezone",
            "cargo_servico": "service_role_id",
            "cargo_membro": "member_role_id",
        }[regra]
        parsed: str | int = valor.strip()
        if regra != "timezone":
            if not parsed.isdigit():
                raise ValidationError("Informe um número inteiro positivo.")
            parsed = int(parsed)
        if regra == "tolerancia_segundos" and not 0 <= int(parsed) <= 600:
            raise ValidationError("A tolerância deve ficar entre 0 e 600 segundos.")
        if regra == "timezone":
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                ZoneInfo(str(parsed))
            except ZoneInfoNotFoundError as exc:
                raise ValidationError("Timezone IANA inválido.") from exc
        before = await self.services.settings.get(actor.guild.id, key)
        async with self.services.database.transaction() as connection:
            await self.services.settings.set(actor.guild.id, key, parsed, actor.id, connection)
            await self.services.audit.record(
                actor.guild.id,
                "RULE_CHANGED",
                actor_id=actor.id,
                before={key: before},
                after={key: parsed},
                connection=connection,
            )
        await interaction.response.send_message(
            f"Regra `{regra}` atualizada para `{parsed}`.", ephemeral=True
        )

    @configurar.command(name="status", description="Mostra a configuração operacional atual.")
    async def configuration_status(self, interaction: discord.Interaction) -> None:
        actor = await self._require(interaction)
        await interaction.response.send_message(
            embed=await build_configuration_status(self.bot, actor.guild), ephemeral=True
        )

    @configurar.command(name="menu", description="Publica o menu visual de configuração.")
    async def configuration_menu(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = await self._require(interaction)
        if not isinstance(interaction.channel, discord.TextChannel):
            raise ValidationError("Use este comando em um canal de texto.")
        message = await self.publish_or_refresh_config_panel(actor.guild, interaction.channel)
        async with self.services.database.transaction() as connection:
            await self.services.settings.set(
                actor.guild.id,
                "config_panel_channel_id",
                message.channel.id,
                actor.id,
                connection,
            )
            await self.services.audit.record(
                actor.guild.id,
                "CONFIG_PANEL_PUBLISHED",
                actor_id=actor.id,
                target_id=message.id,
                after={"channel_id": message.channel.id, "message_id": message.id},
                connection=connection,
            )
        await interaction.followup.send(
            f"✅ Menu de configuração publicado: {message.jump_url}", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ConfigurationCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
