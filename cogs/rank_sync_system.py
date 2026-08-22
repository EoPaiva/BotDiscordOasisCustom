from __future__ import annotations

import asyncio
import logging
import time
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
        self._last_periodic_reconciliation: dict[int, float] = {}

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

    def cog_unload(self) -> None:
        for task in tuple(self._pending.values()):
            task.cancel()
        self._pending.clear()
        if self._periodic_task:
            self._periodic_task.cancel()
            self._periodic_task = None

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
            result = await self.services.rank_sync.sync_from_member(
                member,
                source=source,
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

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        async with self._reconcile_lock:
            for guild in self.bot.guilds:
                if guild.id in self._reconciled_guilds:
                    continue
                try:
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
