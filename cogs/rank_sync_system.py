from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import discord
from discord.ext import commands

from choque.rank_sync import ReconciliationSummary

LOGGER = logging.getLogger(__name__)


class RankSyncSystem(commands.Cog):
    """Gateway adapter for the central Discord identity pipeline."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._pending: dict[tuple[int, int], asyncio.Task[None]] = {}
        self._reconciled_guilds: set[int] = set()
        self._reconcile_lock = asyncio.Lock()
        self._periodic_task: asyncio.Task[None] | None = None
        self._audit_recovery_task: asyncio.Task[None] | None = None
        self._last_periodic_reconciliation: dict[int, float] = {}
        self._seen_member_audit_ids: dict[int, set[int]] = {}
        self._audit_recovery_disabled_guilds: set[int] = set()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def cog_load(self) -> None:
        if self.bot.check_mode or self._periodic_task is not None:
            return
        self._periodic_task = asyncio.create_task(
            self._periodic_reconciliation_loop(),
            name="identity-periodic-reconciliation",
        )
        self._audit_recovery_task = asyncio.create_task(
            self._audit_recovery_loop(),
            name="identity-audit-recovery",
        )

    def cog_unload(self) -> None:
        for task in tuple(self._pending.values()):
            task.cancel()
        self._pending.clear()
        if self._periodic_task:
            self._periodic_task.cancel()
            self._periodic_task = None
        if self._audit_recovery_task:
            self._audit_recovery_task.cancel()
            self._audit_recovery_task = None

    async def _refresh_hierarchy(self, guild: discord.Guild) -> None:
        cog = self.bot.get_cog("HierarchyCommands")
        refresh = getattr(cog, "refresh_configured_panel", None)
        if refresh:
            try:
                await refresh(guild)
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.exception("Falha ao atualizar painel de hierarquia da guild %s", guild.id)

    async def _run_debounced(
        self, member: discord.Member, delay: float, source: str
    ) -> None:
        try:
            await asyncio.sleep(delay)
            actor_id = (
                await self._role_change_actor(member)
                if source == "DISCORD_ROLE_CHANGE"
                else None
            )
            result = await self.services.rank_sync.sync_from_member(
                member,
                source=source,
                actor_id=actor_id,
            )
            if result.db_changed:
                await self._refresh_hierarchy(member.guild)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception(
                "Falha na sincronização de identidade da guild %s, membro %s",
                member.guild.id,
                member.id,
            )
        finally:
            key = (member.guild.id, member.id)
            if self._pending.get(key) is asyncio.current_task():
                self._pending.pop(key, None)

    async def _role_change_actor(self, member: discord.Member) -> int | None:
        """Best-effort attribution for a recent manual rank-role change."""
        cutoff = datetime.now(UTC) - timedelta(seconds=30)
        audit_logs = getattr(member.guild, "audit_logs", None)
        if not callable(audit_logs):
            return None
        try:
            async for entry in audit_logs(
                limit=12,
                action=discord.AuditLogAction.member_role_update,
            ):
                target_id = getattr(entry.target, "id", None)
                if target_id != member.id or entry.created_at < cutoff:
                    continue
                user_id = getattr(entry.user, "id", None)
                return int(user_id) if user_id is not None else None
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.warning(
                "Não foi possível atribuir a alteração recente de patente da guild %s.",
                member.guild.id,
            )
        return None

    async def _recover_recent_member_audits(self, guild: discord.Guild) -> int:
        """Recover role/nickname updates missed by the local member cache.

        Discord audit entries are only a recovery signal.  The final member state is
        always fetched from Discord and reconciled through RankSync, so online and
        offline members follow the same canonical path.
        """
        if guild.id in self._audit_recovery_disabled_guilds:
            return 0
        audit_logs = getattr(guild, "audit_logs", None)
        if not callable(audit_logs):
            return 0

        cutoff = datetime.now(UTC) - timedelta(minutes=15)
        entries: list[tuple[int, str, object]] = []
        try:
            for action, source in (
                (discord.AuditLogAction.member_role_update, "DISCORD_ROLE_CHANGE"),
                (discord.AuditLogAction.member_update, "DISCORD_NICKNAME_CHANGE"),
            ):
                async for entry in audit_logs(limit=50, action=action):
                    if entry.created_at < cutoff:
                        break
                    entries.append((int(entry.id), source, entry))
        except discord.Forbidden:
            self._audit_recovery_disabled_guilds.add(guild.id)
            LOGGER.warning(
                "Recuperação de identidade por auditoria indisponível na guild %s.",
                guild.id,
            )
            return 0
        except discord.HTTPException:
            LOGGER.exception(
                "Falha temporária ao consultar auditoria de identidade da guild %s.",
                guild.id,
            )
            return 0

        seen = self._seen_member_audit_ids.setdefault(guild.id, set())
        changed = 0
        for entry_id, source, entry in sorted(entries, key=lambda item: item[0]):
            if entry_id in seen:
                continue
            target_id = getattr(getattr(entry, "target", None), "id", None)
            if target_id is None:
                seen.add(entry_id)
                continue
            member = guild.get_member(int(target_id))
            if member is None:
                try:
                    member = await guild.fetch_member(int(target_id))
                except discord.NotFound:
                    seen.add(entry_id)
                    continue
                except (discord.Forbidden, discord.HTTPException):
                    LOGGER.exception(
                        "Falha ao buscar membro %s para recuperação de identidade.",
                        target_id,
                    )
                    continue
            if member.bot:
                seen.add(entry_id)
                continue
            actor_id = getattr(getattr(entry, "user", None), "id", None)
            try:
                result = await self.services.rank_sync.sync_from_member(
                    member,
                    source=source,
                    actor_id=int(actor_id) if actor_id is not None else None,
                    correlation_id=f"discord-member-audit-{entry_id}",
                )
            except Exception:
                LOGGER.exception(
                    "Falha ao recuperar identidade do membro %s na guild %s.",
                    target_id,
                    guild.id,
                )
                continue
            seen.add(entry_id)
            changed += int(result.db_changed)

        if len(seen) > 200:
            self._seen_member_audit_ids[guild.id] = set(sorted(seen)[-200:])
        if changed:
            await self._refresh_hierarchy(guild)
        return changed

    async def _schedule(
        self, member: discord.Member, *, source: str = "DISCORD_ROLE_CHANGE"
    ) -> None:
        key = (member.guild.id, member.id)
        previous = self._pending.get(key)
        if previous:
            previous.cancel()
        delay = float(
            await self.services.settings.get(
                member.guild.id, "rank_sync_debounce_seconds", 1.0
            )
        )
        task = asyncio.create_task(
            self._run_debounced(member, max(0.0, min(delay, 10.0)), source),
            name=f"identity-sync:{member.guild.id}:{member.id}",
        )
        self._pending[key] = task

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.bot:
            return
        before_ids = {int(role.id) for role in before.roles}
        after_ids = {int(role.id) for role in after.roles}
        relevant_roles = await self.services.rank_sync.role_change_is_relevant(
            after.guild.id, before_ids, after_ids
        )
        nickname_changed = before.nick != after.nick and bool(
            await self.services.settings.get(
                after.guild.id, "enforce_member_nickname", True
            )
        )
        if relevant_roles or nickname_changed:
            await self._schedule(
                after,
                source=(
                    "DISCORD_ROLE_CHANGE" if relevant_roles else "DISCORD_NICKNAME_CHANGE"
                ),
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        key = (member.guild.id, member.id)
        pending = self._pending.pop(key, None)
        if pending:
            pending.cancel()
        try:
            result = await self.services.rank_sync.mark_discord_absent(
                member.guild.id,
                member.id,
                source="DISCORD_MEMBER_REMOVE",
            )
        except Exception:
            LOGGER.exception(
                "Falha ao revogar identidade do membro ausente %s na guild %s",
                member.id,
                member.guild.id,
            )
            return
        if result.db_changed:
            await self._refresh_hierarchy(member.guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        registered = await self.services.database.fetchone(
            "SELECT 1 FROM members WHERE guild_id=? AND discord_id=?",
            (member.guild.id, member.id),
        )
        if registered:
            await self._schedule(member, source="DISCORD_MEMBER_JOIN")

    async def reconcile_guild(
        self,
        guild: discord.Guild,
        *,
        source: str = "STARTUP_RECONCILIATION",
    ) -> tuple[int, int]:
        summary = await self.services.rank_sync.reconcile_guild(
            guild,
            source=source,
            batch_delay_seconds=0.05 if source == "PERIODIC_RECONCILIATION" else 0.0,
        )
        if summary.changed:
            await self._refresh_hierarchy(guild)
        return summary.checked, summary.changed

    async def run_reconciliation_job(
        self,
        job_id: int,
        guild: discord.Guild,
        *,
        source: str = "PANEL_ACTION",
    ) -> ReconciliationSummary:
        """Thin UI adapter; workers call the service directly."""
        summary = await self.services.rank_sync.process_reconciliation_job(
            job_id,
            guild,
            source=source,
        )
        if summary.changed:
            await self._refresh_hierarchy(guild)
        return summary

    async def _periodic_reconciliation_loop(self) -> None:
        try:
            await self.bot.wait_until_ready()
            while not self.bot.is_closed():
                await asyncio.sleep(300)
                now = time.monotonic()
                for guild in tuple(self.bot.guilds):
                    interval_hours = float(
                        await self.services.settings.get(
                            guild.id, "identity_reconciliation_interval_hours", 6
                        )
                    )
                    interval_seconds = max(3600.0, min(interval_hours * 3600.0, 604800.0))
                    last_run = self._last_periodic_reconciliation.get(guild.id, now)
                    if now - last_run < interval_seconds:
                        self._last_periodic_reconciliation.setdefault(guild.id, now)
                        continue
                    async with self._reconcile_lock:
                        try:
                            summary = await self.services.rank_sync.reconcile_guild(
                                guild,
                                source="PERIODIC_RECONCILIATION",
                                batch_delay_seconds=0.05,
                            )
                        except Exception:
                            LOGGER.exception(
                                "Falha na reconciliação periódica da guild %s", guild.id
                            )
                        else:
                            self._last_periodic_reconciliation[guild.id] = (
                                time.monotonic()
                                if summary.failed == 0
                                else time.monotonic() - interval_seconds
                            )
                            if summary.changed:
                                await self._refresh_hierarchy(guild)
                            LOGGER.info(
                                "Reconciliação periódica da guild %s: "
                                "%s verificados, %s alterados, %s ausentes, %s falhas",
                                guild.id,
                                summary.checked,
                                summary.changed,
                                summary.absent,
                                summary.failed,
                            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Loop periódico de reconciliação de identidade interrompido")

    async def _audit_recovery_loop(self) -> None:
        try:
            await self.bot.wait_until_ready()
            while not self.bot.is_closed():
                intervals: list[float] = []
                for guild in tuple(self.bot.guilds):
                    configured = float(
                        await self.services.settings.get(
                            guild.id, "rank_audit_recovery_interval_seconds", 20
                        )
                    )
                    intervals.append(max(10.0, min(configured, 300.0)))
                    async with self._reconcile_lock:
                        try:
                            await self._recover_recent_member_audits(guild)
                        except Exception:
                            LOGGER.exception(
                                "Falha inesperada na recuperação de identidade da guild %s.",
                                guild.id,
                            )
                await asyncio.sleep(min(intervals, default=20.0))
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Loop de recuperação de identidade por auditoria interrompido")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        async with self._reconcile_lock:
            for guild in self.bot.guilds:
                if guild.id in self._reconciled_guilds:
                    continue
                try:
                    await self._recover_recent_member_audits(guild)
                    summary = await self.services.rank_sync.reconcile_guild(
                        guild,
                        source="STARTUP_RECONCILIATION",
                    )
                except Exception:
                    LOGGER.exception(
                        "Falha na reconciliação de identidade da guild %s", guild.id
                    )
                    continue
                self._reconciled_guilds.add(guild.id)
                interval_hours = float(
                    await self.services.settings.get(
                        guild.id, "identity_reconciliation_interval_hours", 6
                    )
                )
                interval_seconds = max(3600.0, min(interval_hours * 3600.0, 604800.0))
                self._last_periodic_reconciliation[guild.id] = (
                    time.monotonic()
                    if summary.failed == 0
                    else time.monotonic() - interval_seconds
                )
                if summary.changed:
                    await self._refresh_hierarchy(guild)
                LOGGER.info(
                    "Reconciliação de identidade concluída na guild %s: "
                    "%s verificados, %s alterados, %s ausentes, %s falhas",
                    guild.id,
                    summary.checked,
                    summary.changed,
                    summary.absent,
                    summary.failed,
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RankSyncSystem(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
