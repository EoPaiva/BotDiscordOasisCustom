from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import aiosqlite
import discord

from .config import Branding
from .database import Database
from .settings import SettingsService
from .time_utils import discord_timestamp, utc_now_ms

LOGGER = logging.getLogger(__name__)


class AuditService:
    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        branding: Branding,
        bot: discord.Client | None = None,
    ):
        self.database = database
        self.settings = settings
        self.branding = branding
        self.bot = bot

    async def record(
        self,
        guild_id: int,
        action: str,
        *,
        actor_id: int | None = None,
        target_id: int | None = None,
        before: Any = None,
        after: Any = None,
        reason: str | None = None,
        connection: aiosqlite.Connection | None = None,
        correlation_id: str | None = None,
        deliver_immediately: bool = True,
    ) -> int:
        params = (
            correlation_id or str(uuid.uuid4()),
            guild_id,
            action,
            actor_id,
            target_id,
            json.dumps(before, ensure_ascii=False) if before is not None else None,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
            reason,
            utc_now_ms(),
        )
        sql = """
            INSERT INTO audit_logs(
                correlation_id, guild_id, action, actor_id, target_id,
                before_json, after_json, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if connection:
            cursor = await connection.execute(sql, params)
            if deliver_immediately:
                self.database.after_commit(self._deliver_if_ready)
            return int(cursor.lastrowid)
        audit_id = await self.database.execute(sql, params)
        if deliver_immediately:
            await self._deliver_if_ready()
        return audit_id

    async def _deliver_if_ready(self) -> None:
        if self.bot and hasattr(self.bot, "is_ready") and self.bot.is_ready():
            await self.deliver_pending()

    async def deliver_pending(self, limit: int = 20) -> int:
        if not self.bot:
            return 0
        rows = await self.database.fetchall(
            """
            SELECT * FROM audit_logs
            WHERE delivery_status IN ('PENDING', 'FAILED') AND delivery_attempts < 10
            ORDER BY id LIMIT ?
            """,
            (limit,),
        )
        delivered = 0
        for row in rows:
            guild_id = int(row["guild_id"])
            if hasattr(self.bot, "get_guild") and self.bot.get_guild(guild_id) is None:
                LOGGER.debug(
                    "Auditoria %s preservada para guild não conectada %s",
                    row["id"],
                    guild_id,
                )
                continue
            channel_id = await self.settings.get(guild_id, "audit_channel_id")
            if not channel_id:
                LOGGER.debug(
                    "Auditoria %s preservada até o canal de auditoria ser configurado",
                    row["id"],
                )
                continue
            channel = self.bot.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                except (discord.DiscordException, ValueError) as exc:
                    await self._mark_failure(int(row["id"]), str(exc))
                    continue
            embed = discord.Embed(
                title="Auditoria • CHOQUE - BGR",
                color=self.branding.embed_color,
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Ação", value=str(row["action"]), inline=False)
            embed.add_field(
                name="Responsável",
                value=f"<@{row['actor_id']}>" if row["actor_id"] else "Sistema",
                inline=True,
            )
            embed.add_field(
                name="Alvo",
                value=f"<@{row['target_id']}>" if row["target_id"] else "—",
                inline=True,
            )
            if row["reason"]:
                embed.add_field(name="Motivo", value=str(row["reason"])[:1024], inline=False)
            embed.add_field(
                name="Data", value=discord_timestamp(int(row["created_at"])), inline=False
            )
            embed.set_footer(text=f"ID #{row['id']} • {self.branding.footer}")
            try:
                await channel.send(embed=embed)
            except discord.DiscordException as exc:
                await self._mark_failure(int(row["id"]), str(exc))
            else:
                await self.database.execute(
                    """
                    UPDATE audit_logs SET delivery_status='DELIVERED', delivered_at=?,
                        delivery_attempts=delivery_attempts+1, last_error=NULL WHERE id=?
                    """,
                    (utc_now_ms(), int(row["id"])),
                )
                delivered += 1
        return delivered

    async def _mark_failure(self, audit_id: int, error: str) -> None:
        LOGGER.warning("Falha ao entregar auditoria %s: %s", audit_id, error)
        await self.database.execute(
            """
            UPDATE audit_logs SET delivery_status='FAILED',
                delivery_attempts=delivery_attempts+1, last_error=? WHERE id=?
            """,
            (error[:500], audit_id),
        )
