from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from discord.ext import commands, tasks

from choque.backups import create_consistent_backup
from choque.time_utils import utc_now_ms

LOGGER = logging.getLogger(__name__)


class SecuritySystem(commands.Cog):
    """Read-only drift audit. Findings are recorded; delicate permissions are never auto-fixed."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        if not self.bot.check_mode:
            self.periodic_audit.start()
            self.daily_backup.start()

    def cog_unload(self) -> None:
        self.periodic_audit.cancel()
        self.daily_backup.cancel()

    @tasks.loop(hours=6)
    async def periodic_audit(self) -> None:
        for guild in self.bot.guilds:
            try:
                findings = await self.bot.services.security.audit_discord_guild(guild)
            except Exception:
                LOGGER.exception("Falha na auditoria de segurança Discord da guild %s", guild.id)
            else:
                LOGGER.info(
                    "Auditoria de segurança Discord concluída na guild %s: %s achado(s)",
                    guild.id,
                    len(findings),
                )

    @periodic_audit.before_loop
    async def before_periodic_audit(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def daily_backup(self) -> None:
        guild_id = int(self.bot.guild_id or 0)
        try:
            if guild_id:
                await self.bot.services.security.apply_retention(guild_id)
            evidence = await asyncio.to_thread(
                create_consistent_backup,
                Path(self.bot.config.database_path),
                Path("data/security_backups"),
            )
            await self.bot.services.settings.set(
                guild_id,
                "security_last_backup",
                {
                    "created_at": utc_now_ms(),
                    "filename": evidence.path.name,
                    "sha256": evidence.sha256,
                    "migration": evidence.migration,
                    "size": evidence.size,
                },
                None,
            )
            await self.bot.services.security.record(
                guild_id,
                "SECURITY_BACKUP_COMPLETED",
                severity="INFO",
                result="RESOLVED",
                source="BOT",
                target_type="DATABASE",
                metadata={"filename": evidence.path.name, "migration": evidence.migration},
            )
        except Exception:
            LOGGER.exception("Falha no backup diário de segurança")
            if guild_id:
                await self.bot.services.security.record(
                    guild_id,
                    "SECURITY_BACKUP_FAILED",
                    severity="CRITICAL",
                    result="FAILED",
                    source="BOT",
                    target_type="DATABASE",
                )

    @daily_backup.before_loop
    async def before_daily_backup(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SecuritySystem(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
