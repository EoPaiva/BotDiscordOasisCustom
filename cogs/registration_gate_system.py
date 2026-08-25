from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

import discord
from discord.ext import commands, tasks

from choque.embeds import branded_embed
from choque.errors import PermissionDenied, ValidationError
from choque.registration_gate import ACCESS_CLASSES
from choque.time_utils import discord_timestamp
from choque.web_urls import recruitment_portal_url

LOGGER = logging.getLogger(__name__)


def registration_review_embed(bot: ChoqueBot, record) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title=f"🪪 Nova identificação • CAD-{int(record['id']):04d}",
        description=(
            f"**Solicitante:** <@{record['discord_id']}>\n"
            f"**Nick BGR:** {record['mta_nick'] or '—'}\n"
            f"**ID BGR:** {record['bgr_id'] or '—'}\n"
            f"**Situação:** `{record['status']}`\n"
            f"**Conflito:** `{record['conflict_code'] or 'NENHUM'}`\n\n"
            "Use **Abrir fila de cadastros** para analisar pela Central Administrativa."
        ),
    )


def registration_result_embed(bot: ChoqueBot, record) -> discord.Embed:
    approved = str(record["status"]) == "REGISTERED"
    reviewed_at = int(record["reviewed_at"] or record["updated_at"])
    return branded_embed(
        bot.config.branding,
        title=(
            f"{'✅' if approved else '⛔'} CAD-{int(record['id']):04d} • "
            f"{'Aprovado' if approved else 'Negado'}"
        ),
        description=(
            f"**Solicitante:** <@{record['discord_id']}>\n"
            f"**Nick BGR:** {record['mta_nick'] or '—'}\n"
            f"**ID BGR:** {record['bgr_id'] or '—'}\n"
            f"**Responsável:** <@{record['reviewed_by']}>\n"
            f"**Motivo:** {record['review_reason'] or 'Não informado'}\n"
            f"**Decisão:** {discord_timestamp(reviewed_at, 'F')}"
        ),
    )


class RegistrationReviewQueueView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abrir fila de cadastros",
        emoji="📥",
        style=discord.ButtonStyle.danger,
        custom_id="choque:registration:open-review-queue:v1",
    )
    async def open_queue(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            raise ValidationError("Use este painel dentro do servidor.")
        bot = cast("ChoqueBot", interaction.client)
        if not await bot.services.permissions.has(interaction.user, "registration.view"):
            raise PermissionDenied("Você não possui permissão para consultar cadastros.")
        rows = await bot.services.registration_gate.queue(interaction.guild.id)
        if not rows:
            await interaction.response.send_message(
                "✅ Nenhum cadastro aguardando revisão.", ephemeral=True
            )
            return
        from cogs.personnel_commands import GateRegistrationListView

        await interaction.response.send_message(
            "Selecione o cadastro que deseja analisar:",
            view=GateRegistrationListView(rows),
            ephemeral=True,
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        del item
        from cogs.config_ui import respond_error

        await respond_error(interaction, error)


class RegistrationGateSystem(commands.Cog):
    """Adapter Discord da Portaria Digital.

    A fonte de verdade vive em RegistrationGateService. Este cog aplica apenas
    os cargos gerenciados explicitamente e nunca limpa cargos arbitrários.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._review_locks: dict[int, asyncio.Lock] = {}
        self._startup_done: set[int] = set()
        self.bot.add_view(RegistrationReviewQueueView())
        if not self.bot.check_mode:
            self.retry_pending_sync.start()

    async def cog_unload(self) -> None:
        if self.retry_pending_sync.is_running():
            self.retry_pending_sync.cancel()

    async def _protected(self, member: discord.Member) -> bool:
        if member.bot or member.id == member.guild.owner_id:
            return True
        bypass_users = {
            int(value)
            for value in await self.services.settings.get(
                member.guild.id, "registration_bypass_user_ids", []
            )
        }
        if member.id in bypass_users:
            return True
        bypass_roles = {
            int(value)
            for value in await self.services.settings.get(
                member.guild.id, "registration_bypass_role_ids", []
            )
        }
        return any(role.id in bypass_roles for role in member.roles)

    async def _role(self, guild: discord.Guild, setting_key: str) -> discord.Role | None:
        role_id = await self.services.settings.get(guild.id, setting_key)
        return guild.get_role(int(role_id)) if role_id else None

    async def _review_channel(self, guild: discord.Guild) -> discord.TextChannel:
        channel_id = await self.services.settings.get(
            guild.id, "registration_approval_channel_id"
        )
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            raise ValidationError("Canal de aprovação de cadastros não foi configurado.")
        return channel

    async def _history_channel(self, guild: discord.Guild) -> discord.TextChannel:
        channel_id = await self.services.settings.get(
            guild.id, "registration_history_channel_id"
        )
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
        return channel

    async def publish_registration_for_review(self, guild: discord.Guild, record) -> discord.Message:
        channel = await self._review_channel(guild)
        lock = self._review_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            record = await self.services.registration_gate.prepare_pending_review_delivery(
                int(record["id"])
            )
            message = None
            if record["review_channel_id"] and record["review_message_id"]:
                existing_channel = guild.get_channel(int(record["review_channel_id"]))
                if isinstance(existing_channel, discord.TextChannel):
                    try:
                        message = await existing_channel.fetch_message(
                            int(record["review_message_id"])
                        )
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        message = None
            if message is None:
                message = await channel.send(
                    embed=registration_review_embed(self.bot, record),
                    view=RegistrationReviewQueueView(),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                await message.edit(
                    embed=registration_review_embed(self.bot, record),
                    view=RegistrationReviewQueueView(),
                )
            await self.services.registration_gate.record_review_notification(
                int(record["id"]), message.channel.id, message.id
            )
            return message

    async def finalize_registration_review(
        self,
        guild: discord.Guild,
        record,
        *,
        actor_id: int | None,
    ) -> discord.Message | None:
        registration_id = int(record["id"])
        claim_token = await self.services.registration_gate.claim_review_result_delivery(
            registration_id
        )
        if claim_token is None:
            current = await self.services.registration_gate.get(registration_id)
            if current and current["result_channel_id"] and current["result_message_id"]:
                existing_channel = guild.get_channel(int(current["result_channel_id"]))
                if isinstance(existing_channel, discord.TextChannel):
                    try:
                        result = await existing_channel.fetch_message(
                            int(current["result_message_id"])
                        )
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        result = None
                    await self.cleanup_registration_review_card(guild, current, result)
                    return result
            return None
        destination = await self._history_channel(guild)
        lock = self._review_locks.setdefault(guild.id, asyncio.Lock())
        try:
            async with lock:
                result_message = None
                if record["result_channel_id"] and record["result_message_id"]:
                    existing_channel = guild.get_channel(int(record["result_channel_id"]))
                    if isinstance(existing_channel, discord.TextChannel):
                        try:
                            result_message = await existing_channel.fetch_message(
                                int(record["result_message_id"])
                            )
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            result_message = None
                if result_message is None:
                    result_message = await destination.send(
                        embed=registration_result_embed(self.bot, record),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    await result_message.edit(embed=registration_result_embed(self.bot, record))
                await self.services.registration_gate.mark_review_result_delivered(
                    registration_id,
                    actor_id=actor_id,
                    channel_id=result_message.channel.id,
                    message_id=result_message.id,
                    claim_token=claim_token,
                )
        except Exception:
            await self.services.registration_gate.release_delivery_claim(
                registration_id, "RESULT", claim_token
            )
            raise
        await self.cleanup_registration_review_card(guild, record, result_message)
        return result_message

    async def cleanup_registration_review_card(
        self,
        guild: discord.Guild,
        record,
        result_message: discord.Message | None = None,
    ) -> bool:
        """Remove exactly the persisted temporary card, never a panel or purge."""
        if not record["review_channel_id"] or not record["review_message_id"]:
            return False
        registration_id = int(record["id"])
        claim_token = await self.services.registration_gate.claim_review_cleanup(registration_id)
        if claim_token is None:
            return False
        try:
            source_channel = guild.get_channel(int(record["review_channel_id"]))
            if isinstance(source_channel, discord.TextChannel):
                try:
                    source = await source_channel.fetch_message(int(record["review_message_id"]))
                    if result_message is None or source.id != result_message.id:
                        await source.delete()
                except discord.NotFound:
                    pass
                except (discord.Forbidden, discord.HTTPException) as exc:
                    LOGGER.warning(
                        "Falha ao retirar ficha temporária da Portaria %s: %s",
                        registration_id,
                        exc,
                    )
                    await self.services.registration_gate.release_delivery_claim(
                        registration_id, "CLEANUP", claim_token
                    )
                    return False
            await self.services.registration_gate.mark_review_cleanup_completed(
                registration_id, claim_token=claim_token
            )
            return True
        except Exception:
            await self.services.registration_gate.release_delivery_claim(
                registration_id, "CLEANUP", claim_token
            )
            raise

    async def reconcile_review_notifications(self, guild: discord.Guild) -> None:
        for record in await self.services.registration_gate.pending_review_notifications(
            guild.id, limit=100
        ):
            try:
                await self.publish_registration_for_review(guild, record)
            except Exception:
                LOGGER.exception("Falha ao publicar cadastro da Portaria %s", record["id"])
        for record in await self.services.registration_gate.undelivered_review_results(
            guild.id, limit=100
        ):
            try:
                await self.finalize_registration_review(
                    guild, record, actor_id=int(record["reviewed_by"] or 0) or None
                )
            except Exception:
                LOGGER.exception("Falha ao arquivar cadastro da Portaria %s", record["id"])
        for record in await self.services.registration_gate.pending_review_cleanup(
            guild.id, limit=100
        ):
            try:
                await self.cleanup_registration_review_card(guild, record)
            except Exception:
                LOGGER.exception(
                    "Falha ao recuperar limpeza da ficha temporária %s", record["id"]
                )

    async def _expected_role_state(
        self, member: discord.Member, record
    ) -> tuple[set[int], set[int]]:
        unregistered = await self._role(member.guild, "unregistered_role_id")
        candidate = await self._role(member.guild, "candidate_role_id")
        add_ids: set[int] = set()
        remove_ids: set[int] = set()
        if record["status"] == "REGISTERED":
            if unregistered:
                remove_ids.add(unregistered.id)
            if record["access_tier"] == "CANDIDATE" and candidate:
                add_ids.add(candidate.id)
            elif candidate:
                remove_ids.add(candidate.id)
        elif unregistered:
            add_ids.add(unregistered.id)
            if candidate:
                remove_ids.add(candidate.id)
        return add_ids, remove_ids

    async def sync_member_access(
        self,
        member: discord.Member,
        record=None,
        *,
        actor_id: int | None = None,
    ) -> bool:
        if await self._protected(member):
            return True
        if not await self.services.settings.get(
            member.guild.id, "registration_gate_enabled", False
        ):
            return True
        if record is None:
            record = await self.services.registration_gate.status(member.guild.id, member.id)
        if record is None:
            record = await self.services.registration_gate.reconcile_identity(
                member.guild.id, member.id
            )

        key = (member.guild.id, member.id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        success = False
        async with lock:
            try:
                bot_member = member.guild.me
                if not bot_member or not bot_member.guild_permissions.manage_roles:
                    raise PermissionError("O bot não possui Manage Roles.")
                add_ids, remove_ids = await self._expected_role_state(member, record)
                if record["status"] == "REGISTERED" and record["member_id"]:
                    result = await self.services.rank_sync.sync_to_member(
                        member,
                        source="REGISTRATION_GATE",
                        actor_id=actor_id,
                        ensure_member_role=True,
                        explicit_remove_role_ids=remove_ids,
                    )
                    if not result.registered:
                        raise RuntimeError("Perfil de membro não localizado durante o sync.")
                    if result.warning:
                        raise RuntimeError(result.warning)
                else:
                    if record["status"] == "BLOCKED" and record["member_id"]:
                        member_role = await self._role(member.guild, "member_role_id")
                        rank_rows = await self.services.database.fetchall(
                            """
                            SELECT discord_role_id FROM ranks
                            WHERE guild_id=? AND discord_role_id IS NOT NULL
                            """,
                            (member.guild.id,),
                        )
                        if member_role:
                            remove_ids.add(member_role.id)
                        remove_ids.update(int(row["discord_role_id"]) for row in rank_rows)
                    to_remove = [
                        role
                        for role in member.roles
                        if role.id in remove_ids and role.id not in add_ids
                    ]
                    to_add = [
                        role
                        for role_id in add_ids
                        if not member.get_role(role_id)
                        and (role := member.guild.get_role(role_id)) is not None
                    ]
                    if to_remove:
                        await member.remove_roles(
                            *to_remove, reason="Portaria Digital • revogação de acesso"
                        )
                    if to_add:
                        await member.add_roles(*to_add, reason="Portaria Digital • acesso")
                await self.services.registration_gate.mark_sync(
                    int(record["id"]), success=True, actor_id=actor_id
                )
                if record["status"] == "REGISTERED":
                    await self.services.registration_gate.resolve_rank_registration_compliance(
                        member.guild.id,
                        member.id,
                        actor_id=actor_id,
                    )
                success = True
            except (discord.Forbidden, discord.HTTPException, PermissionError, RuntimeError) as exc:
                LOGGER.warning(
                    "Falha ao sincronizar Portaria para %s/%s: %s",
                    member.guild.id,
                    member.id,
                    exc,
                )
                await self.services.registration_gate.mark_sync(
                    int(record["id"]), success=False, actor_id=actor_id, error=str(exc)
                )
                await self.services.registration_gate.record_finding(
                    member.guild.id,
                    "BOT_PERMISSION_ERROR"
                    if isinstance(exc, discord.Forbidden | PermissionError)
                    else "SYNC_FAILURE",
                    fingerprint=f"registration-sync:{member.guild.id}:{member.id}",
                    discord_id=member.id,
                    evidence={"error": str(exc), "registration_id": int(record["id"])},
                )
        self._locks.pop(key, None)
        return success

    async def _alert_compliance_failure(self, guild: discord.Guild, row, error: str) -> None:
        channel_id = await self.services.settings.get(
            guild.id, "registration_approval_channel_id"
        )
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            await self.services.registration_gate.mark_rank_compliance_alert(
                int(row["id"]), success=False, error="Canal administrativo não configurado"
            )
            return
        role_rows = await self.services.database.fetchall(
            """
            SELECT DISTINCT b.role_id
            FROM rbac_bindings b
            WHERE b.guild_id=? AND b.profile='ALTO_COMANDO'
            UNION
            SELECT DISTINCT drm.discord_role_id
            FROM discord_role_mappings drm
            JOIN access_profiles ap ON ap.id=drm.access_profile_id
            WHERE drm.guild_id=? AND drm.enabled=1 AND ap.code='ALTO_COMANDO'
            """,
            (guild.id, guild.id),
        )
        mentions = " ".join(
            role.mention
            for row_role in role_rows
            if (role := guild.get_role(int(row_role["role_id"]))) is not None
        )
        try:
            await channel.send(
                f"{mentions}\n⚠️ **Patente sem cadastro • falha de aviso**\n"
                f"Membro: <@{row['discord_id']}>\n"
                f"Patente: <@&{row['rank_role_id']}>\n"
                f"A cobrança permanece ativa. Erro: `{error[:200]}`",
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=False, roles=True, replied_user=False
                ),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self.services.registration_gate.mark_rank_compliance_alert(
                int(row["id"]), success=False, error=str(exc)
            )
        else:
            await self.services.registration_gate.mark_rank_compliance_alert(
                int(row["id"]), success=True
            )

    async def _notify_rank_compliance(self, guild: discord.Guild, row) -> None:
        member = guild.get_member(int(row["discord_id"]))
        if member is None or member.bot:
            return
        channel_id = await self.services.settings.get(
            guild.id, "registration_panel_channel_id"
        )
        destination = f"<#{int(channel_id)}>" if channel_id else "a Portaria Digital"
        try:
            message = await member.send(
                "🛡️ **CHOQUE - BGR • Regularização obrigatória**\n"
                f"Você recebeu a patente **{row['rank_name'] or 'militar'}**, mas ainda não "
                "possui cadastro aprovado.\n\n"
                f"Conclua o cadastro em {destination} até "
                f"{discord_timestamp(int(row['due_at']), 'F')}.\n"
                "Se o prazo expirar, somente esta patente será removida; seus demais cargos "
                "serão preservados."
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self.services.registration_gate.mark_rank_compliance_dm(
                int(row["id"]), success=False, error=str(exc)
            )
            await self._alert_compliance_failure(guild, row, str(exc))
        else:
            await self.services.registration_gate.mark_rank_compliance_dm(
                int(row["id"]), success=True, message_id=message.id
            )

    async def reconcile_rank_compliance_member(self, member: discord.Member) -> None:
        if member.bot:
            return
        if not await self.services.settings.get(
            member.guild.id, "registration_rank_compliance_enabled", False
        ):
            return
        managed = await self.services.registration_gate.managed_rank_role_ids(member.guild.id)
        current = {role.id for role in member.roles} & managed
        if await self.services.registration_gate.registration_is_approved(
            member.guild.id, member.id
        ):
            await self.services.registration_gate.resolve_rank_registration_compliance(
                member.guild.id, member.id
            )
            return
        for role_id in sorted(current):
            row, created = (
                await self.services.registration_gate.ensure_rank_registration_compliance(
                    member.guild.id, member.id, role_id
                )
            )
            if created and row:
                rank = member.guild.get_role(role_id)
                notification_row = dict(row)
                notification_row["rank_name"] = rank.name if rank else "Patente militar"
                await self._notify_rank_compliance(member.guild, notification_row)
        await self.services.registration_gate.cancel_obsolete_rank_compliance(
            member.guild.id,
            member.id,
            current,
        )

    async def process_rank_compliance(self, guild: discord.Guild) -> dict[str, int]:
        notified = 0
        expired = 0
        failed = 0
        if not await self.services.settings.get(
            guild.id, "registration_rank_compliance_enabled", False
        ):
            return {"notified": 0, "expired": 0, "failed": 0}
        for row in await self.services.registration_gate.pending_rank_compliance_notifications(
            guild.id, limit=25
        ):
            await self._notify_rank_compliance(guild, row)
            notified += 1
        for pending in await self.services.registration_gate.expired_rank_compliance(
            guild.id, limit=25
        ):
            member = guild.get_member(int(pending["discord_id"]))
            role = guild.get_role(int(pending["rank_role_id"]))
            current = {item.id for item in member.roles} if member else set()
            if member is None or role is None or role.id not in current:
                await self.services.registration_gate.cancel_obsolete_rank_compliance(
                    guild.id,
                    int(pending["discord_id"]),
                    current,
                )
                continue
            claimed = await self.services.registration_gate.claim_rank_compliance_expiration(
                int(pending["id"])
            )
            if claimed is None:
                continue
            try:
                await member.remove_roles(
                    role,
                    reason="Prazo de 72 horas para cadastro aprovado expirado",
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                failed += 1
                await self.services.registration_gate.finalize_rank_compliance_expiration(
                    int(pending["id"]),
                    removed=False,
                    reason=str(exc),
                )
                await self._alert_compliance_failure(guild, pending, str(exc))
            else:
                expired += 1
                await self.services.registration_gate.finalize_rank_compliance_expiration(
                    int(pending["id"]),
                    removed=True,
                    reason="Prazo expirado sem cadastro aprovado; somente a patente foi removida.",
                )
        return {"notified": notified, "expired": expired, "failed": failed}

    async def reconcile_member(
        self,
        member: discord.Member,
        *,
        source: str = "SYSTEM_RECONCILIATION",
        actor_id: int | None = None,
    ):
        if await self._protected(member):
            return None
        record = await self.services.registration_gate.reconcile_identity(
            member.guild.id,
            member.id,
            source=source,
            actor_id=actor_id,
        )
        await self.sync_member_access(member, record, actor_id=actor_id)
        return record

    async def validate_access(self, guild: discord.Guild) -> dict[str, object]:
        unregistered = await self._role(guild, "unregistered_role_id")
        if unregistered is None:
            return {"protected": 0, "onboarding": 0, "leaks": [], "unclassified": []}
        classifications = await self.services.registration_gate.classifications(guild.id)
        by_resource = {
            (str(row["resource_type"]), int(row["resource_id"])): str(row["access_class"])
            for row in classifications
        }
        leaks: list[int] = []
        unclassified: list[int] = []
        protected = 0
        onboarding = 0
        for channel in guild.channels:
            resource_type = "CATEGORY" if isinstance(channel, discord.CategoryChannel) else "CHANNEL"
            access_class = by_resource.get((resource_type, channel.id))
            if access_class is None:
                unclassified.append(channel.id)
                access_class = "MEMBER_ONLY"
                await self.services.registration_gate.record_finding(
                    guild.id,
                    "UNCLASSIFIED_RESOURCE",
                    fingerprint=f"unclassified:{guild.id}:{channel.id}",
                    resource_id=channel.id,
                    evidence={"resource_type": resource_type, "default": "MEMBER_ONLY"},
                )
            if access_class not in ACCESS_CLASSES:
                continue
            if access_class in {"ONBOARDING_VISIBLE", "PUBLIC"}:
                onboarding += 1
            else:
                protected += 1
                if channel.permissions_for(unregistered).view_channel:
                    leaks.append(channel.id)
                    await self.services.registration_gate.record_finding(
                        guild.id,
                        "UNREGISTERED_ACCESS_LEAK",
                        fingerprint=f"access-leak:{guild.id}:{channel.id}",
                        resource_id=channel.id,
                        evidence={"role_id": unregistered.id, "access_class": access_class},
                    )
        return {
            "protected": protected,
            "onboarding": onboarding,
            "leaks": leaks,
            "unclassified": unclassified,
        }

    async def _welcome(self, member: discord.Member) -> None:
        if not await self.services.settings.get(member.guild.id, "registration_dm_enabled", True):
            return
        registration_channel_id = await self.services.settings.get(
            member.guild.id, "registration_panel_channel_id"
        )
        recruitment_channel_id = await self.services.settings.get(
            member.guild.id, "recruitment_panel_channel_id"
        )
        public_url = await self.services.settings.get(member.guild.id, "recruitment_public_url")
        registration_channel = (
            member.guild.get_channel(int(registration_channel_id))
            if registration_channel_id
            else None
        )
        recruitment_channel = (
            member.guild.get_channel(int(recruitment_channel_id))
            if recruitment_channel_id
            else None
        )
        registration_destination = (
            registration_channel.mention
            if isinstance(registration_channel, discord.TextChannel)
            else "a Portaria Digital"
        )
        recruitment_destination = (
            recruitment_channel.mention
            if isinstance(recruitment_channel, discord.TextChannel)
            else "o painel de Recrutamento"
        )
        view = discord.ui.View(timeout=900)
        if isinstance(public_url, str) and public_url.startswith("https://"):
            view.add_item(
                discord.ui.Button(
                    label="Candidatar-me agora",
                    emoji="🪖",
                    style=discord.ButtonStyle.link,
                    url=recruitment_portal_url(public_url),
                )
            )
        if isinstance(registration_channel, discord.TextChannel):
            view.add_item(
                discord.ui.Button(
                    label="Já fui aprovado • Portaria",
                    emoji="🪪",
                    style=discord.ButtonStyle.link,
                    url=(
                        f"https://discord.com/channels/{member.guild.id}/"
                        f"{registration_channel.id}"
                    ),
                )
            )
        try:
            await member.send(
                "🪖 **BEM-VINDO À CHOQUE - BGR**\n\n"
                "**Quer entrar para a organização?**\n"
                f"Comece em {recruitment_destination} e selecione **Candidatar-me agora**.\n\n"
                "**Já é membro ou já foi aprovado?**\n"
                f"Conclua sua identificação em {registration_destination}.\n\n"
                "Não use a Portaria para iniciar uma candidatura nova.",
                view=view if view.children else None,
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if self.bot.check_mode or await self._protected(member):
            return
        record = await self.reconcile_member(member, source="REJOIN")
        if record and record["status"] != "REGISTERED":
            await self._welcome(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if self.bot.check_mode or {role.id for role in before.roles} == {
            role.id for role in after.roles
        }:
            return
        if await self._protected(after):
            return
        await self.reconcile_rank_compliance_member(after)
        record = await self.services.registration_gate.status(after.guild.id, after.id)
        if not record:
            return
        add_ids, remove_ids = await self._expected_role_state(after, record)
        current = {role.id for role in after.roles}
        if not add_ids.issubset(current) or bool(remove_ids & current):
            await self.sync_member_access(after, record)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        if self.bot.check_mode:
            return
        resource_type = "CATEGORY" if isinstance(channel, discord.CategoryChannel) else "CHANNEL"
        await self.services.registration_gate.record_finding(
            channel.guild.id,
            "UNCLASSIFIED_RESOURCE",
            fingerprint=f"unclassified:{channel.guild.id}:{channel.id}",
            resource_id=channel.id,
            evidence={"resource_type": resource_type, "default": "MEMBER_ONLY"},
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        for guild in self.bot.guilds:
            if guild.id in self._startup_done:
                continue
            self._startup_done.add(guild.id)
            if not await self.services.settings.get(guild.id, "registration_gate_enabled", False):
                continue
            for member in guild.members:
                if await self._protected(member):
                    continue
                record = await self.services.registration_gate.status(guild.id, member.id)
                if record is None:
                    await self.reconcile_member(member)
                elif record["sync_status"] in {"PENDING", "FAILED"}:
                    await self.sync_member_access(member, record)
                await self.reconcile_rank_compliance_member(member)
            await self.validate_access(guild)
            await self.reconcile_review_notifications(guild)
            await self.process_rank_compliance(guild)

    @tasks.loop(minutes=2)
    async def retry_pending_sync(self) -> None:
        if self.bot.check_mode or not self.bot.is_ready():
            return
        for guild in self.bot.guilds:
            if not await self.services.settings.get(guild.id, "registration_gate_enabled", False):
                continue
            for record in await self.services.registration_gate.pending_sync(guild.id, limit=25):
                member = guild.get_member(int(record["discord_id"]))
                if member:
                    await self.sync_member_access(member, record)
            await self.reconcile_review_notifications(guild)
            await self.process_rank_compliance(guild)

    @retry_pending_sync.before_loop
    async def before_retry_pending_sync(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RegistrationGateSystem(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
