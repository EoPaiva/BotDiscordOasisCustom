from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import aiohttp
import discord
from discord.ext import commands, tasks

from choque.embeds import branded_embed
from choque.errors import PermissionDenied, ValidationError
from choque.status import COMPONENT_LABELS, STATUS_COMPONENTS
from choque.time_utils import discord_timestamp, utc_now_ms

from .config_ui import respond_error

LOGGER = logging.getLogger(__name__)

STATE_LABELS = {
    "OPERACIONAL": "🟢 Operacional",
    "ATUALIZANDO": "🔵 Atualizando",
    "EM_MANUTENCAO": "🟠 Em manutenção",
    "INSTAVEL_DEGRADADO": "🟡 Instável / degradado",
    "TEMPORARIAMENTE_DESATIVADO": "⚪ Temporariamente desativado",
    "INDISPONIVEL": "🔴 Indisponível",
}


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_status_admin(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("A administração de status só funciona dentro do servidor.")
    if not await get_bot(interaction).services.permissions.has(
        interaction.user, "status.manage"
    ):
        raise PermissionDenied("Esta ação exige permissão de administração operacional.")
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


def _component_lines(snapshot: dict[str, object]) -> list[str]:
    lines: list[str] = []
    for component in cast(list[dict[str, object]], snapshot["components"]):
        lines.append(
            f"{STATE_LABELS[str(component['state'])]} **{component['label']}**\n"
            f"└ {str(component['summary'])[:180]}"
        )
    return lines


async def build_public_status_embed(bot: ChoqueBot, guild_id: int) -> discord.Embed:
    snapshot = await bot.services.status.snapshot(guild_id)
    global_state = str(snapshot["global_state"])
    embed = branded_embed(
        bot.config.branding,
        title="📡 Status Operacional • CHOQUE - BGR",
        description=(
            f"**Situação geral:** {STATE_LABELS[global_state]}\n\n"
            + "\n\n".join(_component_lines(snapshot))
        ),
    )
    embed.add_field(
        name="Última atualização",
        value=discord_timestamp(int(snapshot["updated_at"]), "R"),
        inline=True,
    )
    embed.add_field(
        name="Como acompanhar",
        value="Use **Atualizar** para consultar agora e **Detalhes** para ver mudanças recentes.",
        inline=False,
    )
    return embed


async def build_status_details_embed(bot: ChoqueBot, guild_id: int) -> discord.Embed:
    snapshot = await bot.services.status.snapshot(guild_id)
    events = await bot.services.status.recent_events(guild_id, limit=10)
    embed = branded_embed(
        bot.config.branding,
        title="📋 Detalhes do Status Operacional",
        description="Informações públicas, sem dados internos ou mensagens técnicas.",
    )
    for component in cast(list[dict[str, object]], snapshot["components"]):
        detail = [str(component["summary"])[:300]]
        if component.get("override_started_at") and component.get("is_override"):
            detail.append(
                f"Desde {discord_timestamp(int(component['override_started_at']), 'R')}"
            )
        if component.get("override_responsible_id") and component.get("is_override"):
            detail.append(f"Responsável: <@{component['override_responsible_id']}>")
        if component.get("override_expected_at") and component.get("is_override"):
            detail.append(
                f"Previsão: {discord_timestamp(int(component['override_expected_at']), 'F')}"
            )
        embed.add_field(
            name=f"{STATE_LABELS[str(component['state'])]} • {component['label']}",
            value="\n".join(detail),
            inline=False,
        )
    if events:
        recent = []
        for event in events[:5]:
            recent.append(
                f"{discord_timestamp(int(event['occurred_at']), 'R')} • "
                f"**{COMPONENT_LABELS[str(event['component_key'])]}** → "
                f"{STATE_LABELS[str(event['next_state'])]}"
            )
        embed.add_field(name="Mudanças recentes", value="\n".join(recent), inline=False)
    return embed


async def build_admin_status_embed(bot: ChoqueBot, guild_id: int) -> discord.Embed:
    snapshot = await bot.services.status.snapshot(guild_id)
    overrides = sum(
        1
        for item in cast(list[dict[str, object]], snapshot["components"])
        if item["is_override"]
    )
    embed = branded_embed(
        bot.config.branding,
        title="🛠️ Administração • Status do Bot",
        description=(
            "Selecione o estado e depois o componente. Toda alteração exige motivo, "
            "é versionada, auditada e pode ter previsão e expiração."
        ),
    )
    embed.add_field(name="Estado geral", value=STATE_LABELS[str(snapshot["global_state"])] )
    embed.add_field(name="Ajustes manuais ativos", value=str(overrides))
    return embed


class StatusPublicView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Atualizar",
        emoji="🔄",
        style=discord.ButtonStyle.primary,
        custom_id="choque:status:refresh:v1",
    )
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild:
            raise ValidationError("O painel de status pertence ao servidor.")
        await get_bot(interaction).services.status.expire_overrides(interaction.guild.id)
        await interaction.response.edit_message(
            embed=await build_public_status_embed(get_bot(interaction), interaction.guild.id),
            view=StatusPublicView(),
        )

    @discord.ui.button(
        label="Detalhes",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:status:details:v1",
    )
    async def details(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild:
            raise ValidationError("O painel de status pertence ao servidor.")
        await interaction.response.send_message(
            embed=await build_status_details_embed(get_bot(interaction), interaction.guild.id),
            ephemeral=True,
        )


class StatusOverrideModal(ErrorModal):
    reason = discord.ui.TextInput(
        label="Motivo ou resolução",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
    )
    expected_minutes = discord.ui.TextInput(
        label="Previsão em minutos (opcional)",
        required=False,
        max_length=8,
    )
    expires_minutes = discord.ui.TextInput(
        label="Expirar ajuste em minutos (opcional)",
        required=False,
        max_length=8,
    )

    def __init__(
        self,
        component_key: str,
        state: str,
        version: int,
    ) -> None:
        super().__init__(
            title=(
                "Normalizar componente"
                if state == "OPERACIONAL"
                else f"Definir {STATE_LABELS[state].split(' ', 1)[1]}"
            )[:45]
        )
        self.component_key = component_key
        self.state = state
        self.version = version

    @staticmethod
    def _future(value: str, now: int, label: str) -> int | None:
        normalized = value.strip()
        if not normalized:
            return None
        try:
            minutes = int(normalized)
        except ValueError as exc:
            raise ValidationError(f"{label} precisa ser informada em minutos inteiros.") from exc
        if minutes < 1 or minutes > 43_200:
            raise ValidationError(f"{label} precisa ficar entre 1 minuto e 30 dias.")
        return now + minutes * 60_000

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = await require_status_admin(interaction)
        bot = get_bot(interaction)
        now = utc_now_ms()
        if self.state == "OPERACIONAL":
            result = await bot.services.status.clear_override(
                member.guild.id,
                self.component_key,
                actor_id=member.id,
                reason=str(self.reason),
                expected_version=self.version,
            )
        else:
            result = await bot.services.status.set_override(
                member.guild.id,
                self.component_key,
                self.state,
                actor_id=member.id,
                reason=str(self.reason),
                expected_at=self._future(str(self.expected_minutes), now, "A previsão"),
                expires_at=self._future(str(self.expires_minutes), now, "A expiração"),
                expected_version=self.version,
            )
        cog = bot.get_cog("StatusCommands")
        if isinstance(cog, StatusCommands):
            await cog.refresh_panels(member.guild)
            await cog.flush_notifications(member.guild)
        await interaction.response.send_message(
            f"Status de **{result['label']}** atualizado para {STATE_LABELS[str(result['state'])]}.",
            ephemeral=True,
        )


class StatusComponentSelect(discord.ui.Select):
    def __init__(self, state: str) -> None:
        super().__init__(
            placeholder="Selecione o componente",
            options=[
                discord.SelectOption(label=label, value=key)
                for key, label in STATUS_COMPONENTS
            ],
        )
        self.state = state

    async def callback(self, interaction: discord.Interaction) -> None:
        member = await require_status_admin(interaction)
        component = await get_bot(interaction).services.status.component(
            member.guild.id, self.values[0]
        )
        await interaction.response.send_modal(
            StatusOverrideModal(
                str(component["component_key"]), self.state, int(component["version"])
            )
        )


class StatusComponentSelectView(ErrorView):
    def __init__(self, state: str) -> None:
        super().__init__(timeout=300)
        self.add_item(StatusComponentSelect(state))


class StatusAdminView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def _choose(self, interaction: discord.Interaction, state: str) -> None:
        await require_status_admin(interaction)
        await interaction.response.send_message(
            "Escolha o componente que será atualizado:",
            view=StatusComponentSelectView(state),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Atualizando",
        emoji="🔵",
        style=discord.ButtonStyle.primary,
        custom_id="choque:status:admin:updating:v1",
    )
    async def updating(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._choose(interaction, "ATUALIZANDO")

    @discord.ui.button(
        label="Manutenção",
        emoji="🟠",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:status:admin:maintenance:v1",
    )
    async def maintenance(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._choose(interaction, "EM_MANUTENCAO")

    @discord.ui.button(
        label="Instável",
        emoji="🟡",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:status:admin:degraded:v1",
    )
    async def degraded(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._choose(interaction, "INSTAVEL_DEGRADADO")

    @discord.ui.button(
        label="Desativado",
        emoji="⚪",
        style=discord.ButtonStyle.danger,
        custom_id="choque:status:admin:disabled:v1",
    )
    async def disabled(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._choose(interaction, "TEMPORARIAMENTE_DESATIVADO")

    @discord.ui.button(
        label="Indisponível",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        custom_id="choque:status:admin:unavailable:v1",
    )
    async def unavailable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._choose(interaction, "INDISPONIVEL")

    @discord.ui.button(
        label="Normalizar",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="choque:status:admin:normalize:v1",
        row=1,
    )
    async def normalize(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._choose(interaction, "OPERACIONAL")


class StatusCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self.bot.add_view(StatusPublicView())
        self.bot.add_view(StatusAdminView())
        if not self.bot.check_mode:
            self.status_monitor.start()

    def cog_unload(self) -> None:
        self.status_monitor.cancel()

    async def _retire_previous_panel(
        self,
        guild: discord.Guild,
        panel: object,
        channel: discord.TextChannel,
    ) -> None:
        if not panel or int(panel["channel_id"]) == channel.id:  # type: ignore[index]
            return
        old_channel = guild.get_channel(int(panel["channel_id"]))  # type: ignore[index]
        if not isinstance(old_channel, discord.TextChannel):
            return
        try:
            old_message = await old_channel.fetch_message(int(panel["message_id"]))  # type: ignore[index]
            await old_message.edit(view=None)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    @staticmethod
    async def _pin_panel(message: discord.Message) -> None:
        if message.pinned:
            return
        try:
            await message.pin(reason="CHOQUE - BGR • painel persistente de status")
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.warning("Não foi possível fixar o painel persistente de status")

    async def publish_or_refresh_public_panel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        panel = await self.services.settings.get_panel(guild.id, "SYSTEM_STATUS_PUBLIC")
        embed = await build_public_status_embed(self.bot, guild.id)
        if panel and int(panel["channel_id"]) == channel.id:
            try:
                message = await channel.fetch_message(int(panel["message_id"]))
                await message.edit(embed=embed, view=StatusPublicView())
                await self._pin_panel(message)
                return message
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await self._retire_previous_panel(guild, panel, channel)
        message = await channel.send(embed=embed, view=StatusPublicView())
        await self._pin_panel(message)
        await self.services.settings.upsert_panel(
            guild.id, "SYSTEM_STATUS_PUBLIC", channel.id, message.id
        )
        return message

    async def publish_or_refresh_admin_panel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        panel = await self.services.settings.get_panel(guild.id, "SYSTEM_STATUS_ADMIN")
        embed = await build_admin_status_embed(self.bot, guild.id)
        if panel and int(panel["channel_id"]) == channel.id:
            try:
                message = await channel.fetch_message(int(panel["message_id"]))
                await message.edit(embed=embed, view=StatusAdminView())
                await self._pin_panel(message)
                return message
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await self._retire_previous_panel(guild, panel, channel)
        message = await channel.send(embed=embed, view=StatusAdminView())
        await self._pin_panel(message)
        await self.services.settings.upsert_panel(
            guild.id, "SYSTEM_STATUS_ADMIN", channel.id, message.id
        )
        return message

    async def refresh_panels(self, guild: discord.Guild) -> None:
        public_channel_id = await self.services.settings.get(
            guild.id, "status_public_channel_id"
        )
        admin_channel_id = await self.services.settings.get(
            guild.id, "status_admin_channel_id"
        )
        public_channel = guild.get_channel(int(public_channel_id)) if public_channel_id else None
        admin_channel = guild.get_channel(int(admin_channel_id)) if admin_channel_id else None
        if isinstance(public_channel, discord.TextChannel):
            await self.publish_or_refresh_public_panel(guild, public_channel)
        if isinstance(admin_channel, discord.TextChannel):
            await self.publish_or_refresh_admin_panel(guild, admin_channel)

    async def _probe_url(self, url: str) -> tuple[bool, str]:
        timeout = aiohttp.ClientTimeout(total=5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if 200 <= response.status < 400:
                        return True, "respondeu normalmente"
                    return False, "respondeu fora da faixa saudável"
        except (aiohttp.ClientError, TimeoutError):
            return False, "não respondeu dentro do prazo"

    async def _module_state(
        self, guild_id: int, module_keys: tuple[str, ...]
    ) -> tuple[str, str]:
        flags = await self.services.modules.states(guild_id)
        disabled = [key for key in module_keys if not flags.get(key, True)]
        if disabled:
            return "TEMPORARIAMENTE_DESATIVADO", "Módulo desativado pela Administração."
        placeholders = ",".join("?" for _ in module_keys)
        maintenance = await self.services.database.fetchone(
            f"""
            SELECT reason FROM module_maintenance
            WHERE guild_id=? AND module_key IN ({placeholders}) AND active=1
            ORDER BY enabled_at DESC LIMIT 1
            """,
            (guild_id, *module_keys),
        )
        if maintenance:
            return "EM_MANUTENCAO", str(maintenance["reason"] or "Manutenção programada.")
        return "OPERACIONAL", "Fluxo disponível."

    async def collect_observations(
        self, guild: discord.Guild
    ) -> dict[str, tuple[str, str, dict[str, object]]]:
        observations: dict[str, tuple[str, str, dict[str, object]]] = {}
        latency_ms = max(0, round(float(self.bot.latency) * 1_000))
        if not self.bot.is_ready():
            observations["BOT_GATEWAY"] = (
                "INDISPONIVEL",
                "Conexão do bot com o Discord indisponível.",
                {"latency_ms": latency_ms},
            )
        elif latency_ms >= 2_500:
            observations["BOT_GATEWAY"] = (
                "INSTAVEL_DEGRADADO",
                "Conexão com o Discord apresenta latência elevada.",
                {"latency_ms": latency_ms},
            )
        else:
            observations["BOT_GATEWAY"] = (
                "OPERACIONAL",
                "Bot conectado ao Discord.",
                {"latency_ms": latency_ms},
            )

        api_url = str(await self.services.settings.get(guild.id, "status_api_health_url"))
        site_url = str(await self.services.settings.get(guild.id, "status_site_health_url"))
        api_ok, api_detail = await self._probe_url(api_url)
        site_ok, site_detail = await self._probe_url(site_url)
        if not api_ok:
            api_state = "INDISPONIVEL"
            api_summary = "A API não está respondendo normalmente."
        elif not site_ok:
            api_state = "INSTAVEL_DEGRADADO"
            api_summary = "A API está disponível, mas o site apresenta instabilidade."
        else:
            api_state = "OPERACIONAL"
            api_summary = "API e site respondendo normalmente."
        observations["API_SITE"] = (
            api_state,
            api_summary,
            {"api": api_detail, "site": site_detail},
        )

        for component, modules in (
            ("PORTARIA_CADASTRO", ("REGISTRATION",)),
            ("RECRUTAMENTO_MESA", ("RECRUITMENT",)),
            ("BATE_PONTO_PATRULHAS", ("POINT", "PATROLS")),
        ):
            state, summary = await self._module_state(guild.id, modules)
            observations[component] = (state, summary, {"modules": modules})

        delivery_metrics = await self.services.status.delivery_health_metrics()
        queue = delivery_metrics["outbox"]
        queue_total = queue["total"]
        queue_failed = queue["failed"]
        queue_age = queue["oldest_ms"]
        if queue_failed >= 20 or queue_age >= 30 * 60_000:
            queue_state, queue_summary = "INDISPONIVEL", "Filas críticas estão muito atrasadas."
        elif queue_failed > 0 or queue_age >= 5 * 60_000:
            queue_state, queue_summary = (
                "INSTAVEL_DEGRADADO",
                "Algumas notificações estão atrasadas e serão reenviadas.",
            )
        else:
            queue_state, queue_summary = "OPERACIONAL", "Notificações e filas em dia."
        observations["NOTIFICACOES_FILAS"] = (
            queue_state,
            queue_summary,
            {"total": queue_total, "failed": queue_failed, "oldest_ms": queue_age},
        )

        audit = delivery_metrics["audit"]
        audit_total = audit["total"]
        audit_failed = audit["failed"]
        audit_age = audit["oldest_ms"]
        if audit_failed >= 20 or audit_age >= 30 * 60_000:
            audit_state, audit_summary = "INDISPONIVEL", "Histórico crítico com atraso elevado."
        elif audit_failed > 0 or audit_age >= 10 * 60_000:
            audit_state, audit_summary = (
                "INSTAVEL_DEGRADADO",
                "Alguns registros aguardam entrega ao canal de auditoria.",
            )
        else:
            audit_state, audit_summary = "OPERACIONAL", "Auditoria e histórico preservados."
        observations["AUDITORIA_HISTORICO"] = (
            audit_state,
            audit_summary,
            {"total": audit_total, "failed": audit_failed, "oldest_ms": audit_age},
        )

        tag_settings = [
            await self.services.settings.get(guild.id, key)
            for key in (
                "tag_member_panel_channel_id",
                "tag_admin_panel_channel_id",
                "tag_waiting_role_id",
                "tag_set_role_id",
                "tag_responsible_role_id",
            )
        ]
        if all(tag_settings) and self.bot.get_cog("TagCommands"):
            observations["CENTRAL_TAGS"] = (
                "OPERACIONAL",
                "Painéis, fila e validação de tags disponíveis.",
                {},
            )
        else:
            observations["CENTRAL_TAGS"] = (
                "INDISPONIVEL",
                "A Central de Tags ainda não está completamente configurada.",
                {},
            )
        return observations

    async def monitor_guild(self, guild: discord.Guild) -> bool:
        changed = bool(await self.services.status.expire_overrides(guild.id))
        for component, (state, summary, metadata) in (
            await self.collect_observations(guild)
        ).items():
            _, component_changed = await self.services.status.record_observation(
                guild.id, component, state, summary, metadata=metadata
            )
            changed = changed or component_changed
        if changed:
            await self.refresh_panels(guild)
        await self.flush_notifications(guild)
        return changed

    async def deliver_notification(
        self, guild: discord.Guild, event: dict[str, object]
    ) -> bool:
        cooldown_seconds = int(
            await self.services.settings.get(guild.id, "status_alert_cooldown_seconds")
        )
        claimed = await self.services.status.claim_notification(
            int(event["id"]), cooldown_ms=max(0, cooldown_seconds) * 1_000
        )
        if not claimed:
            return False
        channel_id = await self.services.settings.get(
            guild.id, "status_notification_channel_id"
        ) or await self.services.settings.get(guild.id, "status_public_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            await self.services.status.mark_notification_failed(
                int(claimed["id"]), error="Canal de status não configurado"
            )
            return False
        is_resolution = str(claimed["next_state"]) == "OPERACIONAL"
        embed = branded_embed(
            self.bot.config.branding,
            title=("✅ Serviço normalizado" if is_resolution else "📡 Atualização operacional"),
            description=(
                f"**{COMPONENT_LABELS[str(claimed['component_key'])]}** agora está "
                f"{STATE_LABELS[str(claimed['next_state'])]}.\n\n{claimed['summary']}"
            ),
        )
        if claimed.get("expected_at"):
            embed.add_field(
                name="Previsão",
                value=discord_timestamp(int(claimed["expected_at"]), "F"),
            )
        try:
            message = await channel.send(embed=embed)
        except discord.DiscordException as exc:
            await self.services.status.mark_notification_failed(
                int(claimed["id"]), error=str(exc)
            )
            LOGGER.warning("Falha ao publicar atualização do status: %s", exc)
            return False
        return await self.services.status.mark_notification_delivered(
            int(claimed["id"]), message_id=message.id
        )

    async def flush_notifications(self, guild: discord.Guild) -> int:
        delivered = 0
        for event in await self.services.status.pending_notifications(guild.id):
            delivered += int(await self.deliver_notification(guild, event))
        return delivered

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.services.status.ensure_components(guild.id)
                await self.services.status.recover_notification_claims()
                await self.monitor_guild(guild)
                await self.refresh_panels(guild)
            except Exception:
                LOGGER.exception("Falha ao recuperar o Status do Bot na guild %s", guild.id)

    @tasks.loop(seconds=30)
    async def status_monitor(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.monitor_guild(guild)
            except Exception:
                LOGGER.exception("Falha no monitor do Status do Bot na guild %s", guild.id)

    @status_monitor.before_loop
    async def before_status_monitor(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatusCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
