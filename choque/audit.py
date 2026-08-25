from __future__ import annotations

import asyncio
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

DELIVERY_CLAIM_TTL_MS = 5 * 60 * 1000

# O banco é o registro completo de auditoria. Este conjunto define somente o
# que não precisa gerar uma mensagem no canal humano de Auditoria do Bot.
# A lista é intencionalmente fechada: um evento novo ou administrativo continua
# chegando ao canal até que seja avaliado, em vez de ser silenciado por engano.
ROUTINE_CHANNEL_ACTIONS = frozenset(
    {
        "AI_ANALYSIS_ENQUEUED",
        "AI_ANALYSIS_RETRIED",
        "AI_ANALYSIS_STARTED",
        "AUTHORIZED_VOICE_LABEL_RECONCILED",
        "AVAILABILITY_CHANGED",
        "DISCORD_SYNC_COMPLETED",
        "IDENTITY_RECONCILIATION_JOB_COMPLETED",
        "MEMBER_IDENTITY_RECONCILED",
        "MEMBER_ORIGINAL_NICKNAME_CAPTURED",
        "MEMBER_NICKNAME_RESTORED",
        "PATROL_AUTO_CREATED",
        "PATROL_AUTO_FINISHED",
        "PATROL_COMMANDER_ASSIGNED",
        "PATROL_QUEUE_JOINED",
        "PATROL_QUEUE_LEFT",
        "RANK_REGISTRATION_COMPLIANCE_CANCELLED",
        "RANK_REGISTRATION_COMPLIANCE_COMPLETED",
        "RANK_SYNCED_FROM_DISCORD",
        "RECRUIT_CREATED",
        "RECRUITMENT_APPLICATION_ASSIGNED",
        "RECRUITMENT_APPLICATION_STARTED",
        "RECRUITMENT_APPLICATION_SUBMITTED",
        "REGISTRATION_ACCESS_GRANTED",
        "REGISTRATION_ACCESS_REVOKED",
        "REGISTRATION_COMPLETED",
        "REGISTRATION_RECONCILED",
        "REGISTRATION_REVIEW_RESULT_DELIVERED",
        "SHIFT_GRACE_RESUMED",
        "SHIFT_GRACE_STARTED",
        "SHIFT_MINIMUM_PATROL_REACHED",
        "SHIFT_RECOVERED",
        "SHIFT_STARTED",
        "SHIFT_VOICE_MOVED",
        "TICKET_CLAIMED",
        "TICKET_ROOM_ARCHIVED",
        "TICKET_ROOM_BOUND",
        "TICKET_TRANSCRIPT_GENERATED",
    }
)


def should_deliver_to_audit_channel(action: str) -> bool:
    """Return whether an auditable event also merits a human channel alert.

    Errors, security signals and unknown actions intentionally default to
    delivery. This makes the channel quieter without concealing a new or
    sensitive administrative event that has not yet been classified.
    """
    return action not in ROUTINE_CHANNEL_ACTIONS


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
        self._delivery_lock = asyncio.Lock()
        self._delivery_task: asyncio.Task[None] | None = None
        self._coalesced_registration_backlog = False

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
            # Audit delivery must never extend the critical transaction or the
            # web-action worker by up to a Discord batch.  The durable row is
            # already committed; schedule a single background flush instead.
            if self._delivery_task is None or self._delivery_task.done():
                self._delivery_task = asyncio.create_task(
                    self._deliver_safely(), name="audit-delivery"
                )

    async def _deliver_safely(self) -> None:
        try:
            await self.deliver_pending()
        except Exception:
            LOGGER.exception("Falha inesperada no worker de entrega de auditoria")

    async def deliver_pending(self, limit: int = 20) -> int:
        if not self.bot:
            return 0
        async with self._delivery_lock:
            await self._coalesce_registration_backlog()
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
                if not should_deliver_to_audit_channel(str(row["action"])):
                    await self._mark_suppressed(int(row["id"]))
                    continue
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
                claim_token = await self._claim_delivery(int(row["id"]))
                if claim_token is None:
                    continue
                channel = self.bot.get_channel(int(channel_id))
                if not isinstance(channel, discord.TextChannel):
                    try:
                        channel = await self.bot.fetch_channel(int(channel_id))
                    except (discord.DiscordException, ValueError) as exc:
                        await self._mark_failure(int(row["id"]), claim_token, str(exc))
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
                    await self._mark_failure(int(row["id"]), claim_token, str(exc))
                else:
                    if await self._mark_delivered(int(row["id"]), claim_token):
                        delivered += 1
            return delivered

    async def _mark_suppressed(self, audit_id: int) -> None:
        """Finish a routine delivery without deleting its durable audit row."""
        await self.database.execute(
            """
            UPDATE audit_logs
            SET delivery_status='DELIVERED', delivered_at=?,
                last_error='Suprimida no canal: sucesso operacional rotineiro'
            WHERE id=? AND delivery_status IN ('PENDING','FAILED')
            """,
            (utc_now_ms(), audit_id),
        )

    async def _coalesce_registration_backlog(self) -> None:
        """Keep the newest pending grant per member; retain older rows locally.

        A historical bug emitted a grant on every successful reconciliation.
        Those rows remain auditable, but delivering every stale copy would
        recreate the incident after this deploy.
        """
        if self._coalesced_registration_backlog:
            return
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                UPDATE audit_logs
                SET delivery_status='DELIVERED', delivered_at=?,
                    last_error='Coalescida sem envio: duplicata histórica de acesso concedido'
                WHERE action='REGISTRATION_ACCESS_GRANTED'
                  AND delivery_status IN ('PENDING','FAILED')
                  AND EXISTS (
                    SELECT 1 FROM audit_logs newer
                    WHERE newer.action='REGISTRATION_ACCESS_GRANTED'
                      AND newer.guild_id=audit_logs.guild_id
                      AND newer.target_id=audit_logs.target_id
                      AND newer.delivery_status IN ('PENDING','FAILED')
                      AND newer.id > audit_logs.id
                  )
                """,
                (now,),
            )
        self._coalesced_registration_backlog = True

    async def _claim_delivery(self, audit_id: int) -> str | None:
        now = utc_now_ms()
        token = str(uuid.uuid4())
        async with self.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM audit_delivery_claims WHERE audit_id=? AND claimed_at<?",
                (audit_id, now - DELIVERY_CLAIM_TTL_MS),
            )
            cursor = await connection.execute(
                """
                INSERT OR IGNORE INTO audit_delivery_claims(audit_id, claim_token, claimed_at)
                SELECT ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM audit_logs
                    WHERE id=? AND delivery_status IN ('PENDING','FAILED')
                      AND delivery_attempts < 10
                )
                """,
                (audit_id, token, now, audit_id),
            )
            return token if cursor.rowcount == 1 else None

    async def _mark_delivered(self, audit_id: int, claim_token: str) -> bool:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE audit_logs
                SET delivery_status='DELIVERED', delivered_at=?,
                    delivery_attempts=delivery_attempts+1, last_error=NULL
                WHERE id=? AND EXISTS (
                    SELECT 1 FROM audit_delivery_claims
                    WHERE audit_id=? AND claim_token=?
                )
                """,
                (utc_now_ms(), audit_id, audit_id, claim_token),
            )
            await connection.execute(
                "DELETE FROM audit_delivery_claims WHERE audit_id=? AND claim_token=?",
                (audit_id, claim_token),
            )
            return cursor.rowcount == 1

    async def _mark_failure(self, audit_id: int, claim_token: str, error: str) -> None:
        LOGGER.warning("Falha ao entregar auditoria %s: %s", audit_id, error)
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                UPDATE audit_logs SET delivery_status='FAILED',
                    delivery_attempts=delivery_attempts+1, last_error=?
                WHERE id=? AND EXISTS (
                    SELECT 1 FROM audit_delivery_claims
                    WHERE audit_id=? AND claim_token=?
                )
                """,
                (error[:500], audit_id, audit_id, claim_token),
            )
            await connection.execute(
                "DELETE FROM audit_delivery_claims WHERE audit_id=? AND claim_token=?",
                (audit_id, claim_token),
            )
