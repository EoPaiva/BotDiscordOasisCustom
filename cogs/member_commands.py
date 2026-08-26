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


def build_registration_panel_embed(bot: ChoqueBot) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="🛡️ PORTARIA DIGITAL • CHOQUE - BGR",
        description=(
            "**IDENTIFICAÇÃO E CADASTRO FUNCIONAL**\n\n"
            "Este painel é destinado a quem já possui vínculo com a CHOQUE - BGR ou foi "
            "aprovado no processo seletivo. Escolha **Identificar vínculo** ou "
            "**Realizar cadastro**."
        ),
    )
    embed.add_field(
        name="🪪 Identificar vínculo",
        value=(
            "Use quando já possui um vínculo funcional, precisa localizar um perfil existente ou "
            "acompanhar uma conferência administrativa."
        ),
        inline=False,
    )
    embed.add_field(
        name="📝 Realizar cadastro",
        value=(
            "Use depois da aprovação no alistamento, ou quando a Administração orientar uma "
            "nova identificação.\n"
            "`02` Informe somente seu **nick BGR** e **ID BGR**.\n"
            "`03` O sistema verifica elegibilidade e evita duplicidade.\n"
            "`04` Casos que exigem conferência seguem para a fila do Alto Comando."
        ),
        inline=False,
    )
    embed.add_field(
        name="🎖️ Níveis de acesso",
        value=(
            "`NÃO CADASTRADO` ainda não concluiu a Portaria.\n"
            "`CANDIDATO` área do processo seletivo.\n"
            "`RECRUTA / MEMBRO` áreas internas conforme cargo e patente.\n"
            "`COMPANHEIRO DE FARDA` pode realizar o mesmo cadastro pela Portaria após "
            "a validação do vínculo."
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
        name="🔒 Privacidade e orientação",
        value=(
            "Seus dados e sua situação aparecem somente em respostas privadas. Em caso de dúvida, "
            "procure um responsável pelo atendimento."
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
        value=f"`{record['access_tier'] if record else 'NÃO CADASTRADO'}`",
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
                discord_nick=interaction.user.display_name,
            )
            submission_outcome = (
                str(record.get("submission_outcome") or "")
                if isinstance(record, dict)
                else ""
            )
            if submission_outcome == "ALREADY_REGISTERED":
                embed = registration_status_embed(bot, interaction.user, record)
                embed.add_field(
                    name="Cadastro existente",
                    value=(
                        "Você já possui um cadastro ou vínculo canônico. Nenhum dado foi "
                        "alterado e nenhuma nova solicitação foi criada."
                    ),
                    inline=False,
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
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
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Identificar vínculo",
        emoji="🪪",
        style=discord.ButtonStyle.danger,
        custom_id="choque:member:identify:v2",
        row=0,
    )
    async def identify(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild:
            raise ValidationError("Identificação disponível somente no servidor.")
        bot = cast("ChoqueBot", interaction.client)
        await bot.services.modules.require_enabled(interaction.guild.id, "REGISTRATION")
        intent = await bot.services.registration_gate.registration_intent(
            interaction.guild.id, interaction.user.id
        )
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
        current = intent.get("current")
        if current and current["status"] in {"PENDING", "REQUIRES_REVIEW"}:
            gate_cog = bot.get_cog("RegistrationGateSystem")
            if gate_cog and hasattr(gate_cog, "publish_registration_for_review"):
                await gate_cog.publish_registration_for_review(interaction.guild, current)
                current = await bot.services.registration_gate.status(
                    interaction.guild.id, interaction.user.id
                )
        if current:
            await interaction.response.send_message(
                embed=registration_status_embed(bot, interaction.user, current),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Nenhum vínculo funcional foi localizado. Se você foi aprovado no alistamento, "
            "use **Realizar cadastro**; caso contrário, procure a área de Recrutamento.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Realizar cadastro",
        emoji="📝",
        style=discord.ButtonStyle.success,
        custom_id="choque:member:register:v3",
        row=0,
    )
    async def register(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild:
            raise ValidationError("Cadastro disponível somente no servidor.")
        # O botão é somente a porta de entrada para os dois campos declarados pelo
        # próprio usuário. Toda decisão autoritativa (cadastro existente, bloqueio,
        # conflito ou novo ciclo) acontece no submit, dentro da transação do serviço.
        await interaction.response.send_modal(RegistrationModal())

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
        panel_view = RegistrationPanelView()
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
    ) -> discord.Message | None:
        application = await self.services.members.get_application(application_id)
        if not application or int(application["guild_id"]) != guild.id:
            raise NotFoundError("Solicitação não encontrada neste servidor.")
        if application["status"] == "PENDING":
            raise ValidationError("A solicitação ainda não foi analisada.")
        claim_token = await self.services.members.claim_application_result_delivery(application_id)
        if claim_token is None:
            current = await self.services.members.get_application(application_id)
            if current and current["result_channel_id"] and current["result_message_id"]:
                existing_channel = guild.get_channel(int(current["result_channel_id"]))
                if isinstance(existing_channel, discord.TextChannel):
                    try:
                        result = await existing_channel.fetch_message(
                            int(current["result_message_id"])
                        )
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        result = None
                    await self.cleanup_application_review_card(guild, current, result)
                    return result
            return None
        destination = await self._history_channel(guild)
        try:
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
                claim_token=claim_token,
            )
        except Exception:
            await self.services.members.release_application_delivery_claim(
                application_id, "RESULT", claim_token
            )
            raise
        await self.cleanup_application_review_card(guild, application, result_message)
        return result_message

    async def cleanup_application_review_card(
        self,
        guild: discord.Guild,
        application,
        result_message: discord.Message | None = None,
    ) -> bool:
        if not application["review_channel_id"] or not application["review_message_id"]:
            return False
        application_id = int(application["id"])
        claim_token = await self.services.members.claim_application_cleanup(application_id)
        if claim_token is None:
            return False
        try:
            source_channel = guild.get_channel(int(application["review_channel_id"]))
            if isinstance(source_channel, discord.TextChannel):
                try:
                    source = await source_channel.fetch_message(
                        int(application["review_message_id"])
                    )
                    if result_message is None or source.id != result_message.id:
                        await source.delete()
                except discord.NotFound:
                    pass
                except (discord.Forbidden, discord.HTTPException) as exc:
                    LOGGER.warning(
                        "Falha ao retirar ficha temporária de membro %s: %s",
                        application_id,
                        exc,
                    )
                    await self.services.members.release_application_delivery_claim(
                        application_id, "CLEANUP", claim_token
                    )
                    return False
            await self.services.members.mark_application_cleanup_completed(
                application_id, claim_token=claim_token
            )
            return True
        except Exception:
            await self.services.members.release_application_delivery_claim(
                application_id, "CLEANUP", claim_token
            )
            raise

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            if not await self.services.modules.is_enabled(guild.id, "REGISTRATION"):
                continue
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
            for application in await self.services.members.pending_application_cleanup(guild.id):
                try:
                    await self.cleanup_application_review_card(guild, application)
                except Exception:
                    LOGGER.exception(
                        "Falha ao recuperar limpeza da ficha temporária %s", application["id"]
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
        financial = await self.services.financial_aid.member_honor_snapshot(guild_id, member.id)
        honors = financial["honors"]
        achievements = financial["achievements"]
        embed.add_field(
            name="Honrarias simbólicas",
            value="\n".join(f"◈ {item['title']}" for item in honors[:5]) or "Nenhuma honraria ativa.",
            inline=False,
        )
        embed.add_field(
            name="Conquistas de apoio",
            value="\n".join(f"✓ {item['title']}" for item in achievements[:8]) or "Nenhuma conquista registrada.",
            inline=False,
        )
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
