from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Literal, cast

import discord
from discord import app_commands
from discord.ext import commands

from choque.embeds import branded_embed
from choque.errors import NotFoundError, PermissionDenied, ValidationError
from choque.models import MemberStatus
from choque.time_utils import discord_timestamp, format_duration
from cogs.config_ui import respond_error
from cogs.member_sync import sync_registered_member

LOGGER = logging.getLogger(__name__)


def should_open_registration_form(intent) -> bool:
    """Garante que o botão de cadastro nunca vire uma consulta para quem não se cadastrou."""
    current = intent.get("current")
    current_status = str(current["status"]) if current else None
    return intent.get("mode") == "FORM" or current_status == "UNREGISTERED"


def build_registration_panel_embed(bot: ChoqueBot) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="🛡️ PORTARIA DIGITAL • CHOQUE - BGR",
        description=(
            "**ESCOLHA O CAMINHO CORRETO PARA NÃO PERDER TEMPO**\n\n"
            "Se você **ainda não pertence à CHOQUE - BGR**, comece por "
            "**Candidatar-me agora**. A Portaria é destinada a quem já foi aprovado, já é membro "
            "ou possui vínculo funcional reconhecido."
        ),
    )
    embed.add_field(
        name="🪖 Ainda não é membro?",
        value=(
            "Clique em **Candidatar-me agora**. Você será levado diretamente ao processo seletivo "
            "e poderá acompanhar o andamento pelo mesmo portal."
        ),
        inline=False,
    )
    embed.add_field(
        name="🪪 Já é membro, foi aprovado ou é Companheiro de Farda?",
        value=(
            "`01` Selecione **Realizar cadastro**.\n"
            "`02` Informe somente seu **nick BGR** e **ID BGR**.\n"
            "`03` O sistema procura vínculo de membro ou candidatura já existente.\n"
            "`04` Cargos, patente e nickname são sincronizados após a validação."
        ),
        inline=False,
    )
    embed.add_field(
        name="🎖️ Níveis de acesso",
        value=(
            "`VISITANTE` recepção, tickets, recrutamento e transferências.\n"
            "`CANDIDATO` área do processo seletivo.\n"
            "`RECRUTA / MEMBRO` áreas internas conforme cargo e patente.\n"
            "`COMPANHEIRO DE FARDA` pode realizar o mesmo cadastro pela Portaria e, "
            "após validação, usa o prefixo funcional `[COMP.F]`."
        ),
        inline=False,
    )
    embed.add_field(
        name="⚠️ Segurança de identidade",
        value=(
            "IDs duplicados, perfis antigos e divergências nunca são sobrescritos. O caso é "
            "encaminhado ao Alto Comando para revisão auditada."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔒 Privacidade e suporte",
        value=(
            "Seus dados e sua situação aparecem somente em respostas privadas. Use **Preciso de "
            "ajuda** se não reconhecer o vínculo exibido."
        ),
        inline=False,
    )
    return embed


def interaction_member(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Este comando só pode ser usado dentro do servidor.")
    return interaction.user


def registration_status_embed(bot: ChoqueBot, member: discord.Member, record) -> discord.Embed:
    status = str(record["status"]) if record else "UNREGISTERED"
    labels = {
        "UNREGISTERED": ("NÃO CADASTRADO", "Conclua sua identificação nesta Portaria."),
        "PENDING": ("PENDENTE", "Aguarde a conferência administrativa."),
        "REGISTERED": (
            "CADASTRO CONCLUÍDO",
            "A sincronização de acesso será confirmada pelo Discord.",
        ),
        "REQUIRES_REVIEW": (
            "REVISÃO NECESSÁRIA",
            "Uma divergência de identidade será analisada por um responsável.",
        ),
        "BLOCKED": ("ACESSO BLOQUEADO", "Procure o suporte para orientação."),
    }
    label, next_step = labels[status]
    sync_status = str(record["sync_status"]) if record else "NOT_REQUIRED"
    embed = branded_embed(
        bot.config.branding,
        title="🪪 SITUAÇÃO NA PORTARIA DIGITAL",
        description=f"**Discord:** {member.mention}",
    )
    embed.add_field(name="Situação", value=f"`{label}`", inline=True)
    embed.add_field(
        name="Nível",
        value=f"`{record['access_tier'] if record else 'VISITANTE'}`",
        inline=True,
    )
    embed.add_field(name="Sincronização", value=f"`{sync_status}`", inline=True)
    embed.add_field(name="Próxima etapa", value=next_step, inline=False)
    if record and record["mta_nick"]:
        embed.add_field(name="Nick BGR", value=str(record["mta_nick"]), inline=True)
    if record and record["bgr_id"]:
        embed.add_field(name="ID BGR", value=str(record["bgr_id"]), inline=True)
    return embed


class RegistrationModal(discord.ui.Modal, title="Portaria Digital • Identificação"):
    mta_nick = discord.ui.TextInput(
        label="Nick utilizado no BGR", min_length=2, max_length=32
    )
    character_id = discord.ui.TextInput(label="ID no BGR", min_length=1, max_length=32)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Cadastro disponível somente no servidor.", ephemeral=True
            )
            return
        bot = cast("ChoqueBot", interaction.client)
        try:
            await bot.services.modules.require_enabled(interaction.guild.id, "REGISTRATION")
            record = await bot.services.registration_gate.submit(
                interaction.guild.id,
                interaction.user.id,
                mta_nick=str(self.mta_nick),
                bgr_id=str(self.character_id),
            )
            notification_pending = False
            if record["status"] in {"PENDING", "REQUIRES_REVIEW"}:
                gate_cog = bot.get_cog("RegistrationGateSystem")
                if gate_cog and hasattr(gate_cog, "publish_registration_for_review"):
                    try:
                        await gate_cog.publish_registration_for_review(interaction.guild, record)
                        record = await bot.services.registration_gate.status(
                            interaction.guild.id, interaction.user.id
                        )
                    except Exception:
                        notification_pending = True
                        LOGGER.exception(
                            "Falha ao publicar cadastro da Portaria %s", record["id"]
                        )
                else:
                    notification_pending = True
            if record["status"] == "REGISTERED" and isinstance(
                interaction.user, discord.Member
            ):
                gate_cog = bot.get_cog("RegistrationGateSystem")
                if gate_cog and hasattr(gate_cog, "sync_member_access"):
                    await gate_cog.sync_member_access(interaction.user, record)
                    record = await bot.services.registration_gate.status(
                        interaction.guild.id, interaction.user.id
                    )
            embed = registration_status_embed(bot, interaction.user, record)
            if notification_pending:
                embed.add_field(
                    name="Encaminhamento",
                    value=(
                        "Sua solicitação foi salva. O aviso administrativo será reenviado "
                        "automaticamente pelo sistema."
                    ),
                    inline=False,
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as exc:
            from choque.errors import ChoqueError

            if isinstance(exc, ChoqueError):
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return
            raise

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await respond_error(interaction, error)

def application_review_embed(bot: ChoqueBot, application) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title=f"📝 Nova solicitação de membro #{application['id']}",
        description=(
            f"**Discord:** <@{application['discord_id']}>\n"
            f"**Nick MTA:** {application['mta_nick']}\n"
            f"**ID:** {application['character_id'] or 'Não informado'}\n"
            f"**Unidade:** {application['unit'] or 'Não informada'}\n"
            f"**Recrutador:** {application['recruiter'] or 'Não informado'}\n\n"
            "⏳ **Situação:** aguardando análise\n"
            "Use **Cadastros** na Central Administrativa para decidir."
        ),
    )


def application_result_embed(bot: ChoqueBot, application) -> discord.Embed:
    approved = application["status"] == "APPROVED"
    return branded_embed(
        bot.config.branding,
        title=(
            f"{'✅' if approved else '❌'} Cadastro #{application['id']} "
            f"{'aprovado' if approved else 'negado'}"
        ),
        description=(
            f"**Membro:** <@{application['discord_id']}>\n"
            f"**Nick MTA:** {application['mta_nick']}\n"
            f"**Resultado:** `{'APROVADO' if approved else 'NEGADO'}`\n"
            f"**Responsável:** <@{application['reviewed_by']}>\n"
            f"**Motivo:** {application['review_reason'] or 'Não informado'}\n"
            f"**Analisado:** {discord_timestamp(int(application['reviewed_at']), 'F')}"
        ),
    )


class RegistrationPanelView(discord.ui.View):
    def __init__(self, recruitment_public_url: str | None = None) -> None:
        super().__init__(timeout=None)
        if isinstance(recruitment_public_url, str) and recruitment_public_url.startswith("https://"):
            self.add_item(
                discord.ui.Button(
                    label="Candidatar-me agora",
                    emoji="🪖",
                    style=discord.ButtonStyle.link,
                    url=f"{recruitment_public_url.rstrip('/')}/recrutamento",
                    row=0,
                )
            )

    @discord.ui.button(
        label="Realizar cadastro",
        emoji="🪪",
        style=discord.ButtonStyle.danger,
        custom_id="choque:member:register:v1",
        row=1,
    )
    async def register(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild:
            raise ValidationError("Cadastro disponível somente no servidor.")
        bot = cast("ChoqueBot", interaction.client)
        await bot.services.modules.require_enabled(interaction.guild.id, "REGISTRATION")
        intent = await bot.services.registration_gate.registration_intent(
            interaction.guild.id, interaction.user.id
        )
        if should_open_registration_form(intent):
            await interaction.response.send_modal(RegistrationModal())
            return
        if intent["mode"] == "CONFIRM_EXISTING":
            if intent["kind"] == "MEMBER":
                record = await bot.services.registration_gate.request_existing_member_review(
                    interaction.guild.id, interaction.user.id
                )
                gate_cog = bot.get_cog("RegistrationGateSystem")
                if gate_cog and hasattr(gate_cog, "publish_registration_for_review"):
                    await gate_cog.publish_registration_for_review(interaction.guild, record)
                    record = await bot.services.registration_gate.status(
                        interaction.guild.id, interaction.user.id
                    )
            else:
                record = await bot.services.registration_gate.reconcile_identity(
                    interaction.guild.id,
                    interaction.user.id,
                    source="SYSTEM_RECONCILIATION",
                    actor_id=interaction.user.id,
                )
                if isinstance(interaction.user, discord.Member):
                    gate_cog = bot.get_cog("RegistrationGateSystem")
                    if gate_cog and hasattr(gate_cog, "sync_member_access"):
                        await gate_cog.sync_member_access(interaction.user, record)
                        record = await bot.services.registration_gate.status(
                            interaction.guild.id, interaction.user.id
                        )
            await interaction.response.send_message(
                embed=registration_status_embed(bot, interaction.user, record), ephemeral=True
            )
            return
        if intent["mode"] in {"BLOCKED", "STATUS"}:
            current = intent["current"]
            if current and current["status"] in {"PENDING", "REQUIRES_REVIEW"}:
                gate_cog = bot.get_cog("RegistrationGateSystem")
                if gate_cog and hasattr(gate_cog, "publish_registration_for_review"):
                    await gate_cog.publish_registration_for_review(interaction.guild, current)
                    current = await bot.services.registration_gate.status(
                        interaction.guild.id, interaction.user.id
                    )
            await interaction.response.send_message(
                embed=registration_status_embed(bot, interaction.user, current),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(RegistrationModal())

    @discord.ui.button(
        label="Consultar situação",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:registration:status:v1",
        row=1,
    )
    async def status(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            raise ValidationError("Consulta disponível somente no servidor.")
        bot = cast("ChoqueBot", interaction.client)
        record = await bot.services.registration_gate.status(
            interaction.guild.id, interaction.user.id
        )
        await interaction.response.send_message(
            embed=registration_status_embed(bot, interaction.user, record), ephemeral=True
        )

    @discord.ui.button(
        label="Preciso de ajuda",
        emoji="🆘",
        style=discord.ButtonStyle.primary,
        custom_id="choque:registration:help:v1",
        row=1,
    )
    async def help(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild:
            raise ValidationError("Suporte disponível somente no servidor.")
        bot = cast("ChoqueBot", interaction.client)
        support_id = await bot.services.settings.get(
            interaction.guild.id, "registration_support_channel_id"
        )
        support = interaction.guild.get_channel(int(support_id)) if support_id else None
        destination = (
            support.mention if isinstance(support, discord.TextChannel) else "o painel de Tickets"
        )
        await interaction.response.send_message(
            "🆘 **SUPORTE DA PORTARIA DIGITAL**\n"
            f"Abra um atendimento em {destination} e informe que precisa de ajuda com o cadastro. "
            "Não publique seu ID ou outros dados em canais abertos.",
            ephemeral=True,
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await respond_error(interaction, error)


class MemberCommands(commands.Cog):
    membro = app_commands.Group(name="membro", description="Cadastro e gestão de membros")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._panel_lock = asyncio.Lock()
        self.bot.add_view(RegistrationPanelView())

    async def publish_or_refresh_panel(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
    ) -> discord.Message:
        recruitment_public_url = await self.services.settings.get(
            guild.id, "recruitment_public_url"
        )
        panel_view = RegistrationPanelView(
            recruitment_public_url if isinstance(recruitment_public_url, str) else None
        )
        async with self._panel_lock:
            panel = await self.services.settings.get_panel(guild.id, "MEMBER")
            message = None
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None
            if message is None:
                message = await channel.send(
                    embed=build_registration_panel_embed(self.bot),
                    view=panel_view,
                )
            else:
                await message.edit(
                    embed=build_registration_panel_embed(self.bot),
                    view=panel_view,
                )
            await self.services.settings.upsert_panel(
                guild.id,
                "MEMBER",
                message.channel.id,
                message.id,
            )
            return message

    async def _history_channel(self, guild: discord.Guild) -> discord.TextChannel:
        channel_id = await self.services.settings.get(guild.id, "registration_history_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            return channel
        registry = await self.services.settings.get(guild.id, "discord_layout_registry_v2", {})
        registry_id = (
            registry.get("channels", {}).get("archive.members")
            if isinstance(registry, dict)
            else None
        )
        channel = guild.get_channel(int(registry_id)) if registry_id else None
        if not isinstance(channel, discord.TextChannel):
            audit_id = await self.services.settings.get(guild.id, "audit_channel_id")
            channel = guild.get_channel(int(audit_id)) if audit_id else None
        if not isinstance(channel, discord.TextChannel):
            raise ValidationError("Canal de histórico de cadastros não foi configurado.")
        await self.services.settings.set(
            guild.id,
            "registration_history_channel_id",
            channel.id,
            self.bot.user.id if self.bot.user else None,
        )
        return channel

    async def publish_application_for_review(
        self,
        guild: discord.Guild,
        application_id: int,
    ) -> discord.Message:
        application = await self.services.members.get_application(application_id)
        if not application or int(application["guild_id"]) != guild.id:
            raise NotFoundError("Solicitação não encontrada neste servidor.")
        if application["status"] != "PENDING":
            raise ValidationError("A solicitação já foi analisada.")
        channel_id = await self.services.settings.get(
            guild.id, "registration_approval_channel_id"
        )
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            raise ValidationError("Canal de aprovação de cadastros não foi configurado.")

        message = None
        if application["review_channel_id"] and application["review_message_id"]:
            existing_channel = guild.get_channel(int(application["review_channel_id"]))
            if isinstance(existing_channel, discord.TextChannel):
                try:
                    message = await existing_channel.fetch_message(
                        int(application["review_message_id"])
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None
        if message is None:
            message = await channel.send(
                embed=application_review_embed(self.bot, application),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await message.edit(embed=application_review_embed(self.bot, application))
        await self.services.members.record_application_review_message(
            application_id,
            message.channel.id,
            message.id,
        )
        return message

    async def finalize_application_review(
        self,
        guild: discord.Guild,
        application_id: int,
        actor_id: int,
    ) -> discord.Message:
        application = await self.services.members.get_application(application_id)
        if not application or int(application["guild_id"]) != guild.id:
            raise NotFoundError("Solicitação não encontrada neste servidor.")
        if application["status"] == "PENDING":
            raise ValidationError("A solicitação ainda não foi analisada.")
        destination = await self._history_channel(guild)
        result_message = None
        if application["result_channel_id"] and application["result_message_id"]:
            existing_channel = guild.get_channel(int(application["result_channel_id"]))
            if isinstance(existing_channel, discord.TextChannel):
                try:
                    result_message = await existing_channel.fetch_message(
                        int(application["result_message_id"])
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    result_message = None
        if result_message is None:
            result_message = await destination.send(
                embed=application_result_embed(self.bot, application),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await result_message.edit(embed=application_result_embed(self.bot, application))
        await self.services.members.mark_application_delivered(
            application_id,
            actor_id,
            result_message.channel.id,
            result_message.id,
        )

        if application["review_channel_id"] and application["review_message_id"]:
            source_channel = guild.get_channel(int(application["review_channel_id"]))
            if isinstance(source_channel, discord.TextChannel):
                try:
                    source = await source_channel.fetch_message(int(application["review_message_id"]))
                    if source.id != result_message.id:
                        await source.delete()
                except discord.NotFound:
                    pass
                except (discord.Forbidden, discord.HTTPException):
                    LOGGER.exception(
                        "Falha ao retirar cadastro analisado %s da fila", application_id
                    )
        return result_message

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            panel_channel_id = await self.services.settings.get(
                guild.id,
                "registration_panel_channel_id",
            )
            panel_channel = guild.get_channel(int(panel_channel_id)) if panel_channel_id else None
            if isinstance(panel_channel, discord.TextChannel):
                try:
                    await self.publish_or_refresh_panel(guild, panel_channel)
                except Exception:
                    LOGGER.exception("Falha ao restaurar o painel de cadastro da guild %s", guild.id)
            try:
                await self._history_channel(guild)
            except Exception:
                LOGGER.exception("Falha ao resolver o histórico de cadastros da guild %s", guild.id)
            for application in await self.services.members.pending_applications(guild.id):
                try:
                    await self.publish_application_for_review(guild, int(application["id"]))
                except Exception:
                    LOGGER.exception(
                        "Falha ao restaurar cadastro pendente %s", application["id"]
                    )
            for application in await self.services.members.undelivered_reviews(guild.id):
                try:
                    await self.finalize_application_review(
                        guild,
                        int(application["id"]),
                        int(application["reviewed_by"] or 0),
                    )
                except Exception:
                    LOGGER.exception(
                        "Falha ao entregar resultado do cadastro %s", application["id"]
                    )

    async def _require(self, member: discord.Member, permission: str) -> None:
        if not await self.services.permissions.has(member, permission):
            raise PermissionDenied("Você não possui permissão para esta ação.")

    async def _profile_embed(self, guild_id: int, member: discord.Member) -> discord.Embed:
        row = await self.services.members.get(guild_id, member.id)
        if not row:
            raise NotFoundError("Membro não cadastrado.")
        total = await self.services.shifts.total_for_member(guild_id, member.id)
        embed = branded_embed(
            self.bot.config.branding,
            title=f"Perfil operacional • {row['mta_nick']}",
            description=member.mention,
        )
        embed.add_field(name="Patente", value=row["rank_name"] or "Não definida")
        embed.add_field(name="Unidade", value=row["unit"] or "Não definida")
        embed.add_field(name="Status", value=f"`{row['status']}`")
        embed.add_field(name="ID do personagem", value=row["character_id"] or "—")
        embed.add_field(name="Horas válidas", value=format_duration(total))
        embed.add_field(name="Ingresso", value=discord_timestamp(int(row["joined_at"]), "d"))
        if row["notes"]:
            embed.add_field(name="Observações", value=str(row["notes"])[:1024], inline=False)
        return embed

    @membro.command(name="cadastrar", description="Envia sua solicitação de cadastro.")
    async def member_register(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RegistrationModal())

    @membro.command(name="perfil", description="Mostra o perfil operacional de um membro.")
    async def member_profile(
        self, interaction: discord.Interaction, membro: discord.Member | None = None
    ) -> None:
        actor = interaction_member(interaction)
        target = membro or actor
        if target.id != actor.id:
            await self._require(actor, "member.view")
        await interaction.response.send_message(
            embed=await self._profile_embed(actor.guild.id, target), ephemeral=True
        )

    @membro.command(name="status", description="Altera o status operacional do membro.")
    async def member_status(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
        status: Literal["ATIVO", "AFASTADO", "RESERVA", "SUSPENSO", "DESLIGADO"],
        motivo: str,
    ) -> None:
        actor = interaction_member(interaction)
        await self._require(actor, "member.edit")
        status_map = {
            "ATIVO": MemberStatus.ACTIVE,
            "AFASTADO": MemberStatus.AWAY,
            "RESERVA": MemberStatus.RESERVE,
            "SUSPENSO": MemberStatus.SUSPENDED,
            "DESLIGADO": MemberStatus.DISMISSED,
        }
        new_status = status_map[status]
        await self.services.members.change_status(
            actor.guild.id, membro.id, new_status, actor.id, motivo
        )
        if new_status is not MemberStatus.ACTIVE:
            await self.services.shifts.finalize_role_loss(
                actor.guild.id, membro.id, reason=f"STATUS_{new_status.value}"
            )
        await interaction.response.send_message(
            f"Status de {membro.mention} alterado para `{new_status.value}`.", ephemeral=True
        )

    @membro.command(name="analisar", description="Aprova ou nega uma solicitação pendente.")
    async def member_review(
        self,
        interaction: discord.Interaction,
        solicitacao: int,
        acao: Literal["aprovar", "negar"],
        motivo: str = "Análise administrativa",
    ) -> None:
        actor = interaction_member(interaction)
        await self._require(actor, "member.edit")
        application = await self.services.members.get_application(solicitacao)
        if not application or int(application["guild_id"]) != actor.guild.id:
            raise NotFoundError("Solicitação não encontrada neste servidor.")
        target = actor.guild.get_member(int(application["discord_id"]))
        if not target:
            raise NotFoundError("O solicitante não está mais no servidor.")
        approved = acao == "aprovar"
        initial_rank_id = (
            await self.services.rank_sync.initial_rank_id(
                actor.guild.id, {int(role.id) for role in target.roles}
            )
            if approved
            else None
        )
        row = await self.services.members.review_application(
            solicitacao,
            actor.id,
            approved,
            motivo,
            target.display_name,
            initial_rank_id,
        )
        role_notes: list[str] = []
        if approved and row:
            warning = await sync_registered_member(self.bot, actor.guild, target, actor.id)
            if warning:
                role_notes.append(warning)
        await self.finalize_application_review(actor.guild, solicitacao, actor.id)
        response = "aprovada" if approved else "negada"
        suffix = f" {' '.join(role_notes)}" if role_notes else ""
        await interaction.response.send_message(
            f"Solicitação #{solicitacao} {response}.{suffix}", ephemeral=True
        )

    @membro.command(name="painel", description="Publica o painel persistente de cadastro.")
    async def member_panel(self, interaction: discord.Interaction) -> None:
        actor = interaction_member(interaction)
        await self._require(actor, "panel.manage")
        if not isinstance(interaction.channel, discord.TextChannel):
            raise ValidationError("Use este comando em um canal de texto.")
        message = await self.publish_or_refresh_panel(actor.guild, interaction.channel)
        await interaction.response.send_message(
            f"Painel de cadastro atualizado em {message.channel.mention}.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemberCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
