from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

import aiosqlite
import discord

from .audit import AuditService
from .database import Database
from .settings import SettingsService
from .time_utils import utc_now_ms

SECURITY_EVENT_TYPES = frozenset(
    {
        "SECURITY_AUTH_FAILED",
        "SECURITY_PERMISSION_DENIED",
        "SECURITY_RATE_LIMIT",
        "SECURITY_ROLE_CHANGED",
        "SECURITY_BULK_ACTION",
        "SECURITY_CONFIG_CHANGED",
        "SECURITY_SESSION_REVOKED",
        "SECURITY_REPLAY_BLOCKED",
        "SECURITY_LOCKDOWN_CHANGED",
        "SECURITY_DISCORD_DRIFT",
        "SECURITY_REQUEST_REJECTED",
        "SECURITY_BACKUP_COMPLETED",
        "SECURITY_BACKUP_FAILED",
    }
)
SEVERITIES = frozenset({"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"})
RESULTS = frozenset({"ALLOWED", "DENIED", "BLOCKED", "FAILED", "DETECTED", "RESOLVED"})


class SecurityService:
    """Append-only security controls shared by the API and Discord runtime."""

    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit

    async def record(
        self,
        guild_id: int,
        event_type: str,
        *,
        severity: str,
        result: str,
        source: str,
        actor_id: int | None = None,
        target_type: str | None = None,
        target_id: str | int | None = None,
        route: str | None = None,
        request_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> int:
        normalized_type = event_type.strip().upper()
        normalized_severity = severity.strip().upper()
        normalized_result = result.strip().upper()
        if normalized_type not in SECURITY_EVENT_TYPES:
            raise ValueError("Tipo de evento de segurança inválido.")
        if normalized_severity not in SEVERITIES or normalized_result not in RESULTS:
            raise ValueError("Classificação de evento de segurança inválida.")
        payload = json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True)[:4000]
        params = (
            guild_id,
            normalized_type,
            normalized_severity,
            actor_id,
            target_type,
            str(target_id) if target_id is not None else None,
            source[:40],
            route[:300] if route else None,
            (request_id or str(uuid.uuid4()))[:100],
            normalized_result,
            payload,
            utc_now_ms(),
        )
        sql = """
            INSERT INTO security_events(
                guild_id, event_type, severity, actor_discord_id, target_type,
                target_id, source, route, request_id, result, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if connection:
            cursor = await connection.execute(sql, params)
            return int(cursor.lastrowid)
        return await self.database.execute(sql, params)

    async def session_allowed(self, guild_id: int, discord_id: int, issued_at: int) -> bool:
        row = await self.database.fetchone(
            """
            SELECT MAX(revoked_at) AS revoked_at FROM security_session_revocations
            WHERE guild_id=? AND discord_id IN (0, ?)
            """,
            (guild_id, discord_id),
        )
        revoked_at = int(row["revoked_at"] or 0) if row else 0
        return issued_at * 1000 > revoked_at

    async def revoke_sessions(
        self,
        guild_id: int,
        *,
        actor_id: int,
        reason: str,
        discord_id: int | None = None,
        request_id: str | None = None,
    ) -> None:
        now = utc_now_ms()
        target = int(discord_id or 0)
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO security_session_revocations(
                    guild_id, discord_id, revoked_at, reason, revoked_by
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                    revoked_at=excluded.revoked_at,
                    reason=excluded.reason,
                    revoked_by=excluded.revoked_by
                """,
                (guild_id, target, now, reason[:500], actor_id),
            )
            await self.record(
                guild_id,
                "SECURITY_SESSION_REVOKED",
                severity="HIGH" if target == 0 else "MEDIUM",
                result="RESOLVED",
                source="WEB",
                actor_id=actor_id,
                target_type="ALL_SESSIONS" if target == 0 else "DISCORD_USER",
                target_id=target or None,
                request_id=request_id,
                metadata={"scope": "GLOBAL" if target == 0 else "USER"},
                connection=connection,
            )
            await self.audit.record(
                guild_id,
                "SECURITY_SESSIONS_REVOKED",
                actor_id=actor_id,
                target_id=discord_id,
                reason=reason[:500],
                after={"scope": "GLOBAL" if target == 0 else "USER", "revoked_at": now},
                correlation_id=request_id,
                connection=connection,
            )

    async def lockdown(self, guild_id: int) -> dict[str, Any]:
        return {
            "active": bool(await self.settings.get(guild_id, "security_lockdown", False)),
            "reason": await self.settings.get(guild_id, "security_lockdown_reason", None),
            "changed_at": await self.settings.get(guild_id, "security_lockdown_changed_at", None),
            "changed_by": await self.settings.get(guild_id, "security_lockdown_changed_by", None),
        }

    async def set_lockdown(
        self,
        guild_id: int,
        *,
        active: bool,
        reason: str,
        actor_id: int,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        before = await self.lockdown(guild_id)
        now = utc_now_ms()
        after = {
            "active": active,
            "reason": reason[:500],
            "changed_at": now,
            "changed_by": actor_id,
        }
        async with self.database.transaction() as connection:
            for key, value in (
                ("security_lockdown", active),
                ("security_lockdown_reason", reason[:500]),
                ("security_lockdown_changed_at", now),
                ("security_lockdown_changed_by", actor_id),
            ):
                await self.settings.set(guild_id, key, value, actor_id, connection)
            await self.record(
                guild_id,
                "SECURITY_LOCKDOWN_CHANGED",
                severity="CRITICAL" if active else "HIGH",
                result="DETECTED" if active else "RESOLVED",
                source="WEB",
                actor_id=actor_id,
                target_type="GUILD",
                target_id=guild_id,
                request_id=request_id,
                metadata={"active": active},
                connection=connection,
            )
            await self.audit.record(
                guild_id,
                "SECURITY_LOCKDOWN_CHANGED",
                actor_id=actor_id,
                before=before,
                after=after,
                reason=reason[:500],
                correlation_id=request_id,
                connection=connection,
            )
        return after

    async def dashboard(self, guild_id: int, *, limit: int = 40) -> dict[str, Any]:
        now = utc_now_ms()
        since = now - 86_400_000
        rows = await self.database.fetchall(
            """
            SELECT event_type, severity, result, COUNT(*) AS total
            FROM security_events WHERE guild_id=? AND created_at>=?
            GROUP BY event_type, severity, result ORDER BY total DESC
            """,
            (guild_id, since),
        )
        events = await self.database.fetchall(
            """
            SELECT id, event_type, severity, actor_discord_id, target_type, target_id,
                   source, route, request_id, result, created_at
            FROM security_events WHERE guild_id=?
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (guild_id, max(1, min(limit, 100))),
        )
        failed_jobs = await self.database.fetchone(
            """
            SELECT
              (SELECT COUNT(*) FROM web_action_outbox WHERE status='FAILED') +
              (SELECT COUNT(*) FROM recruitment_analysis_jobs WHERE status='FAILED') AS total
            """
        )
        migration = await self.database.fetchone(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        )
        return {
            "generated_at": now,
            "lockdown": await self.lockdown(guild_id),
            "last_24_hours": [dict(row) for row in rows],
            "events": [dict(row) for row in events],
            "health": {
                "api": "OPERATIONAL",
                "database": "OPERATIONAL",
                "migration": int(migration["version"]),
                "failed_jobs": int(failed_jobs["total"] or 0),
                "last_backup": await self.settings.get(
                    guild_id, "security_last_backup", None
                ),
            },
        }

    async def apply_retention(self, guild_id: int) -> dict[str, int]:
        days = int(await self.settings.get(guild_id, "security_log_retention_days", 365))
        days = max(30, min(days, 3650))
        now = utc_now_ms()
        cutoff = now - days * 86_400_000
        async with self.database.transaction() as connection:
            security_cursor = await connection.execute(
                "DELETE FROM security_events WHERE guild_id=? AND created_at<?",
                (guild_id, cutoff),
            )
            nonce_cursor = await connection.execute(
                "DELETE FROM internal_request_nonces WHERE expires_at<?", (now,)
            )
            return {
                "security_events": int(security_cursor.rowcount or 0),
                "request_nonces": int(nonce_cursor.rowcount or 0),
            }

    async def audit_discord_guild(self, guild: discord.Guild) -> list[dict[str, str]]:
        findings: list[dict[str, str]] = []
        me = guild.me
        if me is None:
            return [{"code": "BOT_MEMBER_MISSING", "severity": "CRITICAL"}]
        if me.guild_permissions.administrator:
            findings.append({"code": "BOT_HAS_ADMINISTRATOR", "severity": "CRITICAL"})
        excessive = (
            "ban_members",
            "kick_members",
            "manage_guild",
            "manage_channels",
            "manage_webhooks",
        )
        for permission in excessive:
            if getattr(me.guild_permissions, permission, False):
                findings.append(
                    {"code": f"BOT_EXCESS_PERMISSION_{permission.upper()}", "severity": "HIGH"}
                )
        sensitive_keys = (
            "audit_channel_id",
            "registration_approval_channel_id",
            "registration_history_channel_id",
            "personnel_admin_channel_id",
            "dismissal_log_channel_id",
            "recruitment_queue_channel_id",
            "recruitment_notification_channel_id",
        )
        for key in sensitive_keys:
            channel_id = await self.settings.get(guild.id, key)
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if channel is not None and hasattr(channel, "permissions_for"):
                if channel.permissions_for(guild.default_role).view_channel:
                    findings.append(
                        {"code": f"SENSITIVE_CHANNEL_PUBLIC:{key}", "severity": "CRITICAL"}
                    )
        canonical = json.dumps(findings, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        previous = await self.database.fetchone(
            """
            SELECT findings_hash FROM security_discord_audit_snapshots
            WHERE guild_id=? ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (guild.id,),
        )
        if previous and str(previous["findings_hash"]) == digest:
            return findings
        try:
            await self.database.execute(
                """
                INSERT INTO security_discord_audit_snapshots(
                    guild_id, findings_hash, findings_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (guild.id, digest, canonical, utc_now_ms()),
            )
        except Exception:
            return findings
        severity = "INFO" if not findings else max(
            (item["severity"] for item in findings),
            key=("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL").index,
        )
        await self.record(
            guild.id,
            "SECURITY_DISCORD_DRIFT",
            severity=severity,
            result="RESOLVED" if not findings else "DETECTED",
            source="DISCORD_AUDIT",
            target_type="GUILD",
            target_id=guild.id,
            metadata={"finding_codes": [item["code"] for item in findings]},
        )
        await self.audit.record(
            guild.id,
            "SECURITY_DISCORD_AUDIT",
            after={"findings": findings},
            reason="Mudança detectada pela auditoria periódica de permissões.",
        )
        return findings
