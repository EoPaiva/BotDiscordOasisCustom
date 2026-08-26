from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiosqlite

from .audit import AuditService
from .database import Database
from .dismissals import enqueue_dismissal_notification
from .errors import ConflictError, NotFoundError, ValidationError
from .models import MemberStatus, PunishmentType
from .settings import SettingsService
from .shift_validation import countable_shift_clause
from .shifts import ShiftService
from .time_utils import utc_now_ms

DAY_MS = 86_400_000


def period_bounds_at(period: str, timezone_name: str, now_ms: int) -> tuple[int, int]:
    zone = ZoneInfo(timezone_name)
    now = datetime.fromtimestamp(now_ms / 1000, zone)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Período inválido: {period}")
    return int(start.timestamp() * 1000), now_ms


def next_week_boundary(week_start_ms: int, timezone_name: str) -> int:
    zone = ZoneInfo(timezone_name)
    start = datetime.fromtimestamp(week_start_ms / 1000, zone)
    return int((start + timedelta(days=7)).timestamp() * 1000)


class ActivityService:
    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
        shifts: ShiftService,
        *,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit
        self.shifts = shifts
        self.clock = clock

    async def _rules(self, guild_id: int) -> dict[str, int | str]:
        return {
            "goal_minutes": int(await self.settings.get(guild_id, "weekly_goal_minutes")),
            "near_percent": int(await self.settings.get(guild_id, "weekly_near_threshold_percent")),
            "low_days": int(await self.settings.get(guild_id, "low_activity_days")),
            "no_days": int(await self.settings.get(guild_id, "no_activity_days")),
            "timezone": str(await self.settings.get(guild_id, "timezone")),
        }

    @staticmethod
    def _activity_status(
        total_ms: int, goal_minutes: int, near_percent: int, exemption_reason: str | None
    ) -> str:
        if exemption_reason:
            return "EXEMPT"
        goal_ms = goal_minutes * 60_000
        if total_ms >= goal_ms:
            return "FULFILLED"
        if total_ms * 100 >= goal_ms * near_percent:
            return "NEAR"
        return "NOT_MET"

    async def _exemption_reason(
        self,
        guild_id: int,
        member_id: int,
        member_status: str,
        start_ms: int,
        end_ms: int,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> str | None:
        if member_status == "RESERVE":
            return "RESERVE"
        if member_status == "AWAY":
            return "AWAY"
        sql = """
            SELECT 1 FROM absence_requests
            WHERE guild_id=? AND member_id=? AND status IN ('APPROVED','ENDED')
              AND starts_at < ? AND ends_at > ? LIMIT 1
        """
        if connection:
            cursor = await connection.execute(sql, (guild_id, member_id, end_ms, start_ms))
            row = await cursor.fetchone()
        else:
            row = await self.database.fetchone(sql, (guild_id, member_id, end_ms, start_ms))
        return "ABSENCE" if row else None

    async def current_dashboard(self, guild_id: int) -> list[dict[str, object]]:
        rules = await self._rules(guild_id)
        now = self.clock()
        start, end = period_bounds_at("week", str(rules["timezone"]), now)
        members = await self.database.fetchall(
            """
            SELECT m.id, m.discord_id, m.mta_nick, m.status, m.joined_at,
                   m.last_activity_at, r.name AS rank_name
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.status NOT IN ('PENDING','DISMISSED')
            ORDER BY COALESCE(r.level, 0) DESC, m.mta_nick COLLATE NOCASE
            """,
            (guild_id,),
        )
        result: list[dict[str, object]] = []
        for member in members:
            total_ms = await self.shifts.total_for_member(
                guild_id, int(member["discord_id"]), start, end
            )
            exemption = await self._exemption_reason(
                guild_id,
                int(member["id"]),
                str(member["status"]),
                start,
                end,
            )
            item = dict(member)
            item.update(
                {
                    "total_ms": total_ms,
                    "goal_minutes": int(rules["goal_minutes"]),
                    "activity_status": self._activity_status(
                        total_ms,
                        int(rules["goal_minutes"]),
                        int(rules["near_percent"]),
                        exemption,
                    ),
                    "exemption_reason": exemption,
                    "week_start_at": start,
                    "week_end_at": end,
                }
            )
            result.append(item)
        return result

    async def member_activity(self, guild_id: int, discord_id: int) -> dict[str, object]:
        rows = await self.current_dashboard(guild_id)
        for row in rows:
            if int(row["discord_id"]) == discord_id:
                return row
        member = await self.database.fetchone(
            "SELECT status FROM members WHERE guild_id=? AND discord_id=?",
            (guild_id, discord_id),
        )
        if not member:
            raise NotFoundError("Membro não cadastrado.")
        raise ValidationError("Seu status atual não participa do quadro semanal.")

    async def snapshot_history(self, guild_id: int, discord_id: int, *, limit: int = 12):
        return await self.database.fetchall(
            """
            SELECT * FROM weekly_activity_snapshots
            WHERE guild_id=? AND discord_id=?
            ORDER BY week_start_at DESC, id DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )

    async def _total_in_tx(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        member_id: int,
        start_ms: int,
        end_ms: int,
        now: int,
    ) -> int:
        countable = countable_shift_clause()
        cursor = await connection.execute(
            f"""
            SELECT COALESCE(SUM(
                MAX(0, MIN(COALESCE(ss.ended_at, ?), ?) - MAX(ss.started_at, ?))
            ), 0) AS segment_ms
            FROM shift_segments ss JOIN shifts s ON s.id=ss.shift_id
            WHERE s.guild_id=? AND s.member_id=? AND {countable}
              AND ss.started_at < ? AND COALESCE(ss.ended_at, ?) > ?
            """,
            (now, end_ms, start_ms, guild_id, member_id, now, end_ms, now, start_ms),
        )
        segment_ms = int((await cursor.fetchone())["segment_ms"])
        cursor = await connection.execute(
            f"""
            SELECT COALESCE(SUM(sa.delta_ms), 0) AS adjustment_ms
            FROM shift_adjustments sa JOIN shifts s ON s.id=sa.shift_id
            WHERE s.guild_id=? AND s.member_id=? AND {countable}
              AND s.started_at >= ? AND s.started_at < ?
            """,
            (guild_id, member_id, now, start_ms, end_ms),
        )
        adjustment_ms = int((await cursor.fetchone())["adjustment_ms"])
        return max(0, segment_ms + adjustment_ms)

    async def close_completed_weeks(
        self, guild_id: int, *, actor_id: int | None = None
    ) -> list[dict[str, int]]:
        rules = await self._rules(guild_id)
        timezone_name = str(rules["timezone"])
        now = self.clock()
        current_start, _ = period_bounds_at("week", timezone_name, now)
        row = await self.database.fetchone(
            "SELECT MAX(week_start_at) AS latest FROM weekly_activity_snapshots WHERE guild_id=?",
            (guild_id,),
        )
        if row and row["latest"] is not None:
            week_start = int(row["latest"])
        else:
            zone = ZoneInfo(timezone_name)
            current_local = datetime.fromtimestamp(current_start / 1000, zone)
            week_start = int((current_local - timedelta(days=7)).timestamp() * 1000)
        closed: list[dict[str, int]] = []
        while week_start < current_start:
            week_end = next_week_boundary(week_start, timezone_name)
            inserted = await self._close_week(
                guild_id,
                week_start,
                week_end,
                int(rules["goal_minutes"]),
                int(rules["near_percent"]),
                actor_id,
            )
            if inserted:
                closed.append(
                    {"week_start_at": week_start, "week_end_at": week_end, "members": inserted}
                )
            week_start = week_end
        return closed

    async def _close_week(
        self,
        guild_id: int,
        week_start: int,
        week_end: int,
        goal_minutes: int,
        near_percent: int,
        actor_id: int | None,
    ) -> int:
        now = self.clock()
        inserted = 0
        counts = {"FULFILLED": 0, "NEAR": 0, "NOT_MET": 0, "EXEMPT": 0}
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT id, discord_id, status FROM members
                WHERE guild_id=? AND joined_at < ? AND status NOT IN ('PENDING','DISMISSED')
                ORDER BY id
                """,
                (guild_id, week_end),
            )
            members = await cursor.fetchall()
            for member in members:
                total_ms = await self._total_in_tx(
                    connection,
                    guild_id,
                    int(member["id"]),
                    week_start,
                    week_end,
                    now,
                )
                exemption = await self._exemption_reason(
                    guild_id,
                    int(member["id"]),
                    str(member["status"]),
                    week_start,
                    week_end,
                    connection=connection,
                )
                status = self._activity_status(total_ms, goal_minutes, near_percent, exemption)
                cursor = await connection.execute(
                    """
                    INSERT OR IGNORE INTO weekly_activity_snapshots(
                        guild_id, member_id, discord_id, week_start_at, week_end_at,
                        total_ms, goal_minutes, status, exemption_reason,
                        member_status_at_close, closed_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        member["id"],
                        member["discord_id"],
                        week_start,
                        week_end,
                        total_ms,
                        goal_minutes,
                        status,
                        exemption,
                        member["status"],
                        actor_id,
                        now,
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                    counts[status] += 1
            if inserted:
                await self.audit.record(
                    guild_id,
                    "WEEKLY_ACTIVITY_CLOSED",
                    actor_id=actor_id,
                    after={
                        "week_start_at": week_start,
                        "week_end_at": week_end,
                        "members": inserted,
                        "counts": counts,
                    },
                    connection=connection,
                )
        return inserted

    async def inactivity(self, guild_id: int, bucket: str) -> list[dict[str, object]]:
        rules = await self._rules(guild_id)
        low_days = int(rules["low_days"])
        no_days = int(rules["no_days"])
        now = self.clock()
        members = await self.database.fetchall(
            """
            SELECT m.discord_id, m.mta_nick, m.status, m.joined_at, m.last_activity_at,
                   r.name AS rank_name
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.status NOT IN ('PENDING','DISMISSED')
            ORDER BY COALESCE(m.last_activity_at, m.joined_at), m.mta_nick COLLATE NOCASE
            """,
            (guild_id,),
        )
        result: list[dict[str, object]] = []
        for member in members:
            last_activity = int(member["last_activity_at"] or member["joined_at"])
            days = max(0, (now - last_activity) // DAY_MS)
            member_bucket = "NORMAL"
            if days >= no_days:
                member_bucket = "NONE"
            elif days >= low_days:
                member_bucket = "LOW"
            if member_bucket == bucket:
                item = dict(member)
                item.update({"days_inactive": days, "activity_bucket": member_bucket})
                result.append(item)
        return result

    async def scan_absence_alerts(self, guild_id: int) -> list[dict[str, object]]:
        """Create each 3/7/10-day alert once and return pending deliveries.

        The cycle key is the member's last real activity timestamp. A later
        activity naturally starts a new cycle without deleting history.
        """
        now = self.clock()
        identity_source_guild_id = await self.settings.get(guild_id, "identity_source_guild_id")
        if identity_source_guild_id and int(identity_source_guild_id) != guild_id:
            # Linked recruitment/training guilds mirror identities, but they are
            # not an independent personnel authority.  Suppress any alert that
            # may have been staged there before this guard was deployed.
            await self.database.execute(
                """
                UPDATE activity_absence_alerts
                SET status='DISABLED', updated_at=?
                WHERE guild_id=? AND status='PENDING'
                """,
                (now, guild_id),
            )
            return []
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT m.id AS member_id, m.discord_id, m.mta_nick,
                       COALESCE(m.last_activity_at, m.joined_at) AS cycle_started_at,
                       COALESCE(su.unit_code, NULLIF(m.unit, 'BGR')) AS unit_code,
                       COALESCE(ac.disabled, 0) AS alerts_disabled
                FROM members m
                LEFT JOIN special_unit_memberships su
                  ON su.canonical_guild_id=m.guild_id AND su.member_id=m.id
                 AND su.status='ACTIVE'
                LEFT JOIN activity_absence_controls ac
                  ON ac.guild_id=m.guild_id AND ac.member_id=m.id
                WHERE m.guild_id=? AND m.status='ACTIVE'
                ORDER BY m.id
                """,
                (guild_id,),
            )
            members = await cursor.fetchall()
            for member in members:
                member_id = int(member["member_id"])
                cycle_started_at = int(member["cycle_started_at"])
                cursor = await connection.execute(
                    """
                    SELECT 1 FROM absence_requests
                    WHERE guild_id=? AND member_id=? AND status='APPROVED'
                      AND starts_at<=? AND ends_at>?
                    LIMIT 1
                    """,
                    (guild_id, member_id, now, now),
                )
                justified = await cursor.fetchone() is not None
                if justified or bool(member["alerts_disabled"]):
                    terminal = "JUSTIFIED" if justified else "DISABLED"
                    await connection.execute(
                        """
                        UPDATE activity_absence_alerts
                        SET status=?, updated_at=?
                        WHERE guild_id=? AND member_id=? AND status='PENDING'
                        """,
                        (terminal, now, guild_id, member_id),
                    )
                    continue
                days = max(0, (now - cycle_started_at) // DAY_MS)
                for threshold in (3, 7, 10):
                    if days < threshold:
                        continue
                    await connection.execute(
                        """
                        INSERT OR IGNORE INTO activity_absence_alerts(
                            guild_id, member_id, discord_id, unit_code,
                            cycle_started_at, threshold_days, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            guild_id,
                            member_id,
                            int(member["discord_id"]),
                            member["unit_code"],
                            cycle_started_at,
                            threshold,
                            now,
                            now,
                        ),
                    )
            cursor = await connection.execute(
                """
                SELECT aa.*, m.mta_nick, r.name AS rank_name
                FROM activity_absence_alerts aa
                JOIN members m ON m.id=aa.member_id
                LEFT JOIN ranks r ON r.id=m.rank_id
                WHERE aa.guild_id=? AND aa.status='PENDING'
                ORDER BY aa.created_at, aa.threshold_days, aa.id
                """,
                (guild_id,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def mark_absence_alert_delivered(
        self, guild_id: int, alert_id: int, channel_id: int, message_id: int
    ) -> None:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE activity_absence_alerts
                SET status='DELIVERED', channel_id=?, message_id=?,
                    delivered_at=?, updated_at=?
                WHERE guild_id=? AND id=? AND status='PENDING'
                """,
                (channel_id, message_id, now, now, guild_id, alert_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Este alerta já foi entregue ou encerrado.")

    async def get_absence_alert(self, guild_id: int, alert_id: int):
        return await self.database.fetchone(
            "SELECT * FROM activity_absence_alerts WHERE guild_id=? AND id=?",
            (guild_id, alert_id),
        )

    async def disable_member_absence_alerts(
        self,
        guild_id: int,
        alert_id: int,
        actor_id: int,
        reason: str | None = None,
    ) -> dict[str, object]:
        now = self.clock()
        normalized_reason = (reason or "").strip() or None
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM activity_absence_alerts WHERE guild_id=? AND id=?",
                (guild_id, alert_id),
            )
            alert = await cursor.fetchone()
            if alert is None:
                raise NotFoundError("Alerta de ausência não encontrado.")
            await connection.execute(
                """
                INSERT INTO activity_absence_controls(
                    guild_id, member_id, disabled, disabled_by,
                    disabled_at, reason, updated_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(guild_id, member_id) DO UPDATE SET
                    disabled=1, disabled_by=excluded.disabled_by,
                    disabled_at=excluded.disabled_at, reason=excluded.reason,
                    updated_at=excluded.updated_at
                """,
                (
                    guild_id,
                    int(alert["member_id"]),
                    actor_id,
                    now,
                    normalized_reason,
                    now,
                ),
            )
            await connection.execute(
                """
                UPDATE activity_absence_alerts SET status='DISABLED', updated_at=?
                WHERE guild_id=? AND member_id=? AND status='PENDING'
                """,
                (now, guild_id, int(alert["member_id"])),
            )
            await self.audit.record(
                guild_id,
                "ACTIVITY_ABSENCE_ALERTS_DISABLED",
                actor_id=actor_id,
                target_id=int(alert["discord_id"]),
                after={
                    "alert_id": alert_id,
                    "member_id": int(alert["member_id"]),
                    "unit": alert["unit_code"],
                },
                reason=normalized_reason,
                connection=connection,
            )
        return {
            "alert_id": alert_id,
            "member_id": int(alert["member_id"]),
            "discord_id": int(alert["discord_id"]),
            "unit_code": alert["unit_code"],
            "disabled_by": actor_id,
            "disabled_at": now,
        }

    async def dismiss_member_for_absence_alert(
        self,
        source_guild_id: int,
        interaction_guild_id: int,
        alert_id: int,
        actor_id: int,
        reason: str,
    ) -> dict[str, object]:
        """Dismiss the canonical member and its REC mirror exactly once."""
        normalized_reason = reason.strip()
        if len(normalized_reason) < 3:
            raise ValidationError("Informe um motivo com pelo menos 3 caracteres.")
        if interaction_guild_id != source_guild_id:
            configured_source = await self.settings.get(
                interaction_guild_id, "identity_source_guild_id"
            )
            if not configured_source or int(configured_source) != source_guild_id:
                raise ValidationError(
                    "Este servidor não está vinculado à autoridade de pessoal informada."
                )

        # Recover a decision that committed before its shift cleanup without
        # holding the database transaction while ShiftService acquires its own
        # member lock.  Keeping the cleanup inside the transaction creates an
        # ABBA deadlock when two button clicks race: one task owns the shift
        # lock and waits for the database while the other owns the database and
        # waits for the shift lock.
        completed = await self.database.fetchone(
            """
            SELECT * FROM activity_absence_dismissals
            WHERE alert_id=? AND source_guild_id=?
            """,
            (alert_id, source_guild_id),
        )
        if completed is not None:
            await self.shifts.finalize_role_loss(
                source_guild_id,
                int(completed["discord_id"]),
                reason="INACTIVITY_DISMISSAL_RECOVERY",
            )
            if interaction_guild_id != source_guild_id:
                await self.shifts.finalize_role_loss(
                    interaction_guild_id,
                    int(completed["discord_id"]),
                    reason="INACTIVITY_DISMISSAL_MIRROR_RECOVERY",
                )
            return {
                "alert_id": alert_id,
                "member_id": int(completed["member_id"]),
                "discord_id": int(completed["discord_id"]),
                "punishment_id": int(completed["punishment_id"]),
                "source_guild_id": source_guild_id,
                "interaction_guild_id": int(completed["interaction_guild_id"]),
                "already_completed": True,
            }

        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM activity_absence_dismissals
                WHERE alert_id=? AND source_guild_id=?
                """,
                (alert_id, source_guild_id),
            )
            completed = await cursor.fetchone()
            if completed is not None:
                # A competing click committed while this task waited for the
                # database.  The winning task owns post-commit cleanup, so this
                # path must return without acquiring ShiftService locks.
                return {
                    "alert_id": alert_id,
                    "member_id": int(completed["member_id"]),
                    "discord_id": int(completed["discord_id"]),
                    "punishment_id": int(completed["punishment_id"]),
                    "source_guild_id": source_guild_id,
                    "interaction_guild_id": int(completed["interaction_guild_id"]),
                    "already_completed": True,
                }

            cursor = await connection.execute(
                """
                SELECT aa.*, m.status AS member_status
                FROM activity_absence_alerts aa
                JOIN members m ON m.id=aa.member_id AND m.guild_id=aa.guild_id
                WHERE aa.guild_id=? AND aa.id=?
                """,
                (source_guild_id, alert_id),
            )
            alert = await cursor.fetchone()
            if alert is None:
                raise NotFoundError("Alerta de inatividade não encontrado.")
            if str(alert["member_status"]) == MemberStatus.DISMISSED.value:
                raise ConflictError("O membro já está desligado do efetivo.")

            cursor = await connection.execute(
                """
                SELECT id FROM punishments
                WHERE guild_id=? AND member_id=? AND punishment_type='DISMISSAL'
                  AND status IN ('SCHEDULED','ACTIVE')
                """,
                (source_guild_id, int(alert["member_id"])),
            )
            if await cursor.fetchone() is not None:
                raise ConflictError("O membro já possui um desligamento ativo.")

            cursor = await connection.execute(
                """
                INSERT INTO punishments(
                    guild_id, member_id, discord_id, punishment_type, reason,
                    previous_member_status, starts_at, ends_at, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    source_guild_id,
                    int(alert["member_id"]),
                    int(alert["discord_id"]),
                    PunishmentType.DISMISSAL.value,
                    normalized_reason,
                    str(alert["member_status"]),
                    now,
                    actor_id,
                    now,
                ),
            )
            punishment_id = int(cursor.lastrowid)
            await connection.execute(
                "UPDATE members SET status='DISMISSED', updated_at=? WHERE id=?",
                (now, int(alert["member_id"])),
            )

            mirrored = False
            if interaction_guild_id != source_guild_id:
                cursor = await connection.execute(
                    "SELECT id, status FROM members WHERE guild_id=? AND discord_id=?",
                    (interaction_guild_id, int(alert["discord_id"])),
                )
                mirror = await cursor.fetchone()
                if mirror is not None and str(mirror["status"]) != MemberStatus.DISMISSED.value:
                    await connection.execute(
                        "UPDATE members SET status='DISMISSED', updated_at=? WHERE id=?",
                        (now, int(mirror["id"])),
                    )
                    mirrored = True
                    await self.audit.record(
                        interaction_guild_id,
                        "MEMBER_STATUS_CHANGED",
                        actor_id=actor_id,
                        target_id=int(alert["discord_id"]),
                        before={"status": str(mirror["status"])},
                        after={
                            "status": MemberStatus.DISMISSED.value,
                            "source_guild_id": source_guild_id,
                            "source_alert_id": alert_id,
                        },
                        reason=normalized_reason,
                        connection=connection,
                    )

            await connection.execute(
                """
                UPDATE activity_absence_alerts
                SET status='DISABLED', updated_at=?
                WHERE guild_id=? AND member_id=? AND status='PENDING'
                """,
                (now, source_guild_id, int(alert["member_id"])),
            )
            await connection.execute(
                """
                INSERT INTO activity_absence_dismissals(
                    alert_id, source_guild_id, interaction_guild_id, member_id,
                    discord_id, punishment_id, actor_id, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    source_guild_id,
                    interaction_guild_id,
                    int(alert["member_id"]),
                    int(alert["discord_id"]),
                    punishment_id,
                    actor_id,
                    normalized_reason,
                    now,
                ),
            )
            await self.audit.record(
                source_guild_id,
                "ACTIVITY_ABSENCE_MEMBER_DISMISSED",
                actor_id=actor_id,
                target_id=int(alert["discord_id"]),
                before={"status": str(alert["member_status"])},
                after={
                    "status": MemberStatus.DISMISSED.value,
                    "alert_id": alert_id,
                    "punishment_id": punishment_id,
                    "interaction_guild_id": interaction_guild_id,
                    "mirror_updated": mirrored,
                },
                reason=normalized_reason,
                connection=connection,
            )
            await enqueue_dismissal_notification(
                connection,
                guild_id=source_guild_id,
                subject_id=punishment_id,
                discord_id=int(alert["discord_id"]),
                actor_id=actor_id,
                occurred_at=now,
                source="INACTIVITY_ALERT",
                correlation_id=f"dismissal-notification-inactivity-{punishment_id}",
            )

        await self.shifts.finalize_role_loss(
            source_guild_id,
            int(alert["discord_id"]),
            reason="INACTIVITY_DISMISSAL",
        )
        if interaction_guild_id != source_guild_id:
            await self.shifts.finalize_role_loss(
                interaction_guild_id,
                int(alert["discord_id"]),
                reason="INACTIVITY_DISMISSAL_MIRROR",
            )
        return {
            "alert_id": alert_id,
            "member_id": int(alert["member_id"]),
            "discord_id": int(alert["discord_id"]),
            "punishment_id": punishment_id,
            "source_guild_id": source_guild_id,
            "interaction_guild_id": interaction_guild_id,
            "already_completed": False,
        }

    async def set_rules(
        self,
        guild_id: int,
        actor_id: int,
        *,
        goal_minutes: int,
        near_percent: int,
        low_days: int,
        no_days: int,
    ) -> dict[str, int]:
        if not 1 <= goal_minutes <= 10_080:
            raise ValidationError("A meta deve ficar entre 1 e 10.080 minutos.")
        if not 1 <= near_percent <= 99:
            raise ValidationError("O limite de proximidade deve ficar entre 1% e 99%.")
        if not 1 <= low_days < no_days <= 365:
            raise ValidationError(
                "Os dias de baixa atividade devem ser menores que os dias sem atividade."
            )
        before = await self._rules(guild_id)
        after = {
            "weekly_goal_minutes": goal_minutes,
            "weekly_near_threshold_percent": near_percent,
            "low_activity_days": low_days,
            "no_activity_days": no_days,
        }
        async with self.database.transaction() as connection:
            for key, value in after.items():
                await self.settings.set(guild_id, key, value, actor_id, connection)
            await self.audit.record(
                guild_id,
                "ACTIVITY_RULES_CHANGED",
                actor_id=actor_id,
                before=before,
                after=after,
                connection=connection,
            )
        return after

    async def _period_summary(self, guild_id: int, period: str) -> dict[str, object]:
        rules = await self._rules(guild_id)
        now = self.clock()
        start, end = period_bounds_at(period, str(rules["timezone"]), now)
        members = await self.database.fetchall(
            """
            SELECT discord_id FROM members
            WHERE guild_id=? AND status NOT IN ('PENDING','DISMISSED')
            """,
            (guild_id,),
        )
        totals = await asyncio.gather(
            *(
                self.shifts.total_for_member(guild_id, int(row["discord_id"]), start, end)
                for row in members
            )
        )
        open_points = await self.database.fetchone(
            "SELECT COUNT(*) AS total FROM shifts WHERE guild_id=? AND status IN ('ACTIVE','GRACE')",
            (guild_id,),
        )
        absences = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM absence_requests
            WHERE guild_id=? AND status='APPROVED' AND starts_at <= ? AND ends_at > ?
            """,
            (guild_id, now, now),
        )
        trainings = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM training_events
            WHERE guild_id=? AND scheduled_at >= ? AND scheduled_at < ?
            """,
            (guild_id, start, end),
        )
        return {
            "period": period,
            "start_at": start,
            "end_at": end,
            "members_worked": sum(total > 0 for total in totals),
            "total_ms": sum(totals),
            "open_points": int(open_points["total"]),
            "active_absences": int(absences["total"]),
            "trainings": int(trainings["total"]),
        }

    async def daily_report(self, guild_id: int) -> dict[str, object]:
        return await self._period_summary(guild_id, "today")

    async def monthly_report(self, guild_id: int) -> dict[str, object]:
        return await self._period_summary(guild_id, "month")

    async def weekly_report(self, guild_id: int) -> dict[str, object]:
        dashboard = await self.current_dashboard(guild_id)
        rules = await self._rules(guild_id)
        now = self.clock()
        start, end = period_bounds_at("week", str(rules["timezone"]), now)
        statuses = {"FULFILLED": 0, "NEAR": 0, "NOT_MET": 0, "EXEMPT": 0}
        for row in dashboard:
            statuses[str(row["activity_status"])] += 1
        total_ms = sum(int(row["total_ms"]) for row in dashboard)
        new_members = await self.database.fetchone(
            "SELECT COUNT(*) AS total FROM members WHERE guild_id=? AND joined_at>=? AND joined_at<?",
            (guild_id, start, end),
        )
        promotions = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM personnel_actions
            WHERE guild_id=? AND action_type='PROMOTION' AND created_at>=? AND created_at<?
            """,
            (guild_id, start, end),
        )
        warnings = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM punishments
            WHERE guild_id=? AND punishment_type='WARNING' AND created_at>=? AND created_at<?
            """,
            (guild_id, start, end),
        )
        trainings = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM training_events
            WHERE guild_id=? AND scheduled_at>=? AND scheduled_at<?
            """,
            (guild_id, start, end),
        )
        return {
            "start_at": start,
            "end_at": end,
            "total_ms": total_ms,
            "average_ms": total_ms // len(dashboard) if dashboard else 0,
            "goal_minutes": int(rules["goal_minutes"]),
            "statuses": statuses,
            "new_members": int(new_members["total"]),
            "promotions": int(promotions["total"]),
            "warnings": int(warnings["total"]),
            "trainings": int(trainings["total"]),
        }

    async def member_report(self, guild_id: int, discord_id: int) -> dict[str, object]:
        rules = await self._rules(guild_id)
        now = self.clock()
        week = period_bounds_at("week", str(rules["timezone"]), now)
        month = period_bounds_at("month", str(rules["timezone"]), now)
        member = await self.database.fetchone(
            """
            SELECT m.*, r.name AS rank_name FROM members m
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        if not member:
            raise NotFoundError("Membro não cadastrado.")
        week_ms, month_ms, total_ms = await asyncio.gather(
            self.shifts.total_for_member(guild_id, discord_id, *week),
            self.shifts.total_for_member(guild_id, discord_id, *month),
            self.shifts.total_for_member(guild_id, discord_id),
        )
        shifts = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total, MAX(started_at) AS last_service
            FROM shifts WHERE guild_id=? AND member_id=?
            """,
            (guild_id, member["id"]),
        )
        warnings = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM punishments
            WHERE guild_id=? AND member_id=? AND punishment_type='WARNING' AND status='ACTIVE'
            """,
            (guild_id, member["id"]),
        )
        trainings = await self.database.fetchone(
            "SELECT COUNT(*) AS total FROM member_qualifications WHERE guild_id=? AND member_id=?",
            (guild_id, member["id"]),
        )
        return {
            "member": member,
            "week_ms": week_ms,
            "month_ms": month_ms,
            "total_ms": total_ms,
            "shifts": int(shifts["total"]),
            "last_service": shifts["last_service"],
            "active_warnings": int(warnings["total"]),
            "trainings_completed": int(trainings["total"]),
        }

    async def points_report(self, guild_id: int) -> dict[str, int]:
        row = await self.database.fetchone(
            """
            SELECT
                COUNT(CASE WHEN status='ACTIVE' THEN 1 END) AS active,
                COUNT(CASE WHEN status='GRACE' THEN 1 END) AS grace,
                COUNT(CASE WHEN status='REVIEW_REQUIRED' THEN 1 END) AS review,
                COUNT(CASE WHEN status='CLOSED' THEN 1 END) AS closed,
                COUNT(CASE WHEN status='CLOSED' AND validation_status='VALID' THEN 1 END)
                    AS valid,
                COUNT(CASE WHEN status='CLOSED' AND validation_status='INVALIDATED' THEN 1 END)
                    AS invalidated
            FROM shifts WHERE guild_id=?
            """,
            (guild_id,),
        )
        return {
            key: int(row[key])
            for key in ("active", "grace", "review", "closed", "valid", "invalidated")
        }

    async def absences_report(self, guild_id: int):
        return await self.database.fetchall(
            """
            SELECT a.*, m.mta_nick FROM absence_requests a
            JOIN members m ON m.id=a.member_id
            WHERE a.guild_id=? AND a.status IN ('PENDING','APPROVED')
            ORDER BY CASE a.status WHEN 'PENDING' THEN 1 ELSE 2 END, a.starts_at
            LIMIT 25
            """,
            (guild_id,),
        )

    async def trainings_report(self, guild_id: int):
        return await self.database.fetchall(
            """
            SELECT t.*,
                COUNT(CASE WHEN e.enrollment_status='ENROLLED' THEN 1 END) AS participants
            FROM training_events t LEFT JOIN training_enrollments e ON e.training_id=t.id
            WHERE t.guild_id=?
            GROUP BY t.id ORDER BY t.scheduled_at DESC, t.id DESC LIMIT 25
            """,
            (guild_id,),
        )
