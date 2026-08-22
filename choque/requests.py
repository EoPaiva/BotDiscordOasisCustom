from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import aiosqlite

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from .models import AdministrativeRequestStatus, AdministrativeRequestType, MemberStatus
from .shift_validation import closed_validation_values
from .time_utils import utc_now_ms

REQUEST_LABELS = {
    AdministrativeRequestType.EARLY_RETURN.value: "Retorno antecipado",
    AdministrativeRequestType.RESERVE_ENTRY.value: "Entrada na reserva",
    AdministrativeRequestType.RESERVE_EXIT.value: "Retorno da reserva",
    AdministrativeRequestType.HOURS_CORRECTION.value: "Correção de horas",
    AdministrativeRequestType.DATA_CHANGE.value: "Alteração de dados",
    AdministrativeRequestType.DISMISSAL.value: "Desligamento",
    "ABSENCE": "Ausência",
}


class RequestService:
    def __init__(
        self,
        database: Database,
        audit: AuditService,
        *,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.audit = audit
        self.clock = clock

    async def submit(
        self,
        guild_id: int,
        discord_id: int,
        request_type: AdministrativeRequestType,
        payload: dict[str, Any],
    ) -> int:
        now = self.clock()
        normalized = dict(payload)
        reason = str(normalized.get("reason") or "").strip()
        if not reason:
            raise ValidationError("Informe o motivo da solicitação.")
        normalized["reason"] = reason

        try:
            async with self.database.transaction() as connection:
                member = await self._member(connection, guild_id, discord_id)
                await self._validate_submission(
                    connection, guild_id, member, request_type, normalized, now
                )
                cursor = await connection.execute(
                    """
                    INSERT INTO administrative_requests(
                        guild_id, member_id, discord_id, request_type,
                        payload_json, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        member["id"],
                        discord_id,
                        request_type.value,
                        json.dumps(normalized, ensure_ascii=False),
                        now,
                    ),
                )
                request_id = int(cursor.lastrowid)
                await self.audit.record(
                    guild_id,
                    "ADMIN_REQUEST_SUBMITTED",
                    actor_id=discord_id,
                    target_id=discord_id,
                    after={"request_id": request_id, "request_type": request_type.value},
                    reason=reason,
                    connection=connection,
                )
        except aiosqlite.IntegrityError as exc:
            raise ConflictError("Você já possui uma solicitação desse tipo pendente.") from exc
        return request_id

    async def _validate_submission(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        member: aiosqlite.Row,
        request_type: AdministrativeRequestType,
        payload: dict[str, Any],
        now: int,
    ) -> None:
        status = str(member["status"])
        if status == MemberStatus.DISMISSED.value:
            raise ConflictError("Membro desligado não pode abrir novas solicitações.")

        if request_type is AdministrativeRequestType.EARLY_RETURN:
            cursor = await connection.execute(
                """
                SELECT id, ends_at, previous_member_status FROM absence_requests
                WHERE guild_id=? AND member_id=? AND status='APPROVED'
                  AND starts_at <= ? AND ends_at > ?
                ORDER BY starts_at DESC LIMIT 1
                """,
                (guild_id, member["id"], now, now),
            )
            absence = await cursor.fetchone()
            if not absence:
                raise ConflictError("Você não possui ausência ativa para encerrar.")
            payload["absence_id"] = int(absence["id"])
            payload["scheduled_end_at"] = int(absence["ends_at"])
            return

        if request_type is AdministrativeRequestType.RESERVE_ENTRY:
            if status != MemberStatus.ACTIVE.value:
                raise ConflictError("Somente membros ativos podem solicitar entrada na reserva.")
            return

        if request_type is AdministrativeRequestType.RESERVE_EXIT:
            if status != MemberStatus.RESERVE.value:
                raise ConflictError("Você não está na reserva.")
            return

        if request_type is AdministrativeRequestType.HOURS_CORRECTION:
            try:
                shift_id = int(payload.get("shift_id"))
                requested_minutes = int(payload.get("requested_total_minutes"))
            except (TypeError, ValueError) as exc:
                raise ValidationError("Informe uma sessão e um total de horas válidos.") from exc
            if requested_minutes < 0 or requested_minutes > 10_080:
                raise ValidationError("O total correto deve estar entre 0 e 168 horas.")
            cursor = await connection.execute(
                """
                SELECT s.id, s.status,
                    COALESCE((SELECT SUM(COALESCE(ss.ended_at, ?) - ss.started_at)
                              FROM shift_segments ss WHERE ss.shift_id=s.id), 0)
                    + COALESCE((SELECT SUM(sa.delta_ms) FROM shift_adjustments sa
                                WHERE sa.shift_id=s.id), 0) AS total_ms
                FROM shifts s
                WHERE s.id=? AND s.guild_id=? AND s.member_id=?
                """,
                (now, shift_id, guild_id, member["id"]),
            )
            shift = await cursor.fetchone()
            if not shift:
                raise NotFoundError("A sessão informada não pertence ao seu cadastro.")
            if shift["status"] != "CLOSED":
                raise ConflictError("Somente sessões finalizadas podem ser corrigidas.")
            payload["shift_id"] = shift_id
            payload["previous_total_ms"] = int(shift["total_ms"])
            payload["requested_total_minutes"] = requested_minutes
            return

        if request_type is AdministrativeRequestType.DATA_CHANGE:
            changes: dict[str, str] = {}
            for key in ("mta_nick", "character_id", "unit"):
                value = str(payload.get(key) or "").strip()
                if value and value != str(member[key] or ""):
                    changes[key] = value
            if not changes:
                raise ValidationError("Informe ao menos um dado diferente do cadastro atual.")
            payload["changes"] = changes
            for key in ("mta_nick", "character_id", "unit"):
                payload.pop(key, None)
            return

        if request_type is AdministrativeRequestType.DISMISSAL:
            confirmation = str(payload.pop("confirmation", "")).strip().upper()
            if confirmation != "CONFIRMAR":
                raise ValidationError("Digite CONFIRMAR para solicitar o desligamento.")

    async def review(
        self,
        guild_id: int,
        request_id: int,
        approved: bool,
        actor_id: int,
        reason: str,
    ) -> dict[str, Any]:
        decision_reason = reason.strip()
        if not decision_reason:
            raise ValidationError("Informe o motivo da decisão.")
        now = self.clock()
        decision = (
            AdministrativeRequestStatus.APPROVED
            if approved
            else AdministrativeRequestStatus.REJECTED
        )
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM administrative_requests WHERE guild_id=? AND id=?",
                (guild_id, request_id),
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação não encontrada.")
            if request["status"] != AdministrativeRequestStatus.PENDING.value:
                raise ConflictError("Essa solicitação já foi analisada.")
            if int(request["discord_id"]) == actor_id:
                raise PermissionDenied("Você não pode decidir a própria solicitação.")
            payload = json.loads(request["payload_json"])
            result: dict[str, Any] = {
                "request_id": request_id,
                "request_type": request["request_type"],
                "discord_id": int(request["discord_id"]),
                "status": decision.value,
                "member_status": None,
                "shift_closed": False,
            }
            if approved:
                result.update(
                    await self._apply_approved(connection, request, payload, actor_id, now)
                )
            cursor = await connection.execute(
                """
                UPDATE administrative_requests
                SET status=?, reviewed_by=?, reviewed_at=?, review_reason=?, applied_at=?
                WHERE id=? AND guild_id=? AND status='PENDING'
                """,
                (
                    decision.value,
                    actor_id,
                    now,
                    decision_reason,
                    now if approved else None,
                    request_id,
                    guild_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Essa solicitação foi analisada simultaneamente.")
            await self.audit.record(
                guild_id,
                "ADMIN_REQUEST_REVIEWED",
                actor_id=actor_id,
                target_id=int(request["discord_id"]),
                before={"status": AdministrativeRequestStatus.PENDING.value},
                after=result,
                reason=decision_reason,
                connection=connection,
            )
        return result

    async def _apply_approved(
        self,
        connection: aiosqlite.Connection,
        request: aiosqlite.Row,
        payload: dict[str, Any],
        actor_id: int,
        now: int,
    ) -> dict[str, Any]:
        guild_id = int(request["guild_id"])
        member_id = int(request["member_id"])
        discord_id = int(request["discord_id"])
        request_type = AdministrativeRequestType(str(request["request_type"]))
        result: dict[str, Any] = {}

        if request_type is AdministrativeRequestType.EARLY_RETURN:
            absence_id = int(payload["absence_id"])
            cursor = await connection.execute(
                """
                SELECT previous_member_status FROM absence_requests
                WHERE id=? AND guild_id=? AND member_id=? AND status='APPROVED'
                  AND starts_at <= ? AND ends_at > ?
                """,
                (absence_id, guild_id, member_id, now, now),
            )
            absence = await cursor.fetchone()
            if not absence:
                raise ConflictError("A ausência já terminou ou deixou de estar ativa.")
            await connection.execute(
                "UPDATE absence_requests SET status='ENDED', ended_at=? WHERE id=?",
                (now, absence_id),
            )
            restored = await self._effective_status(
                connection,
                guild_id,
                member_id,
                now,
                fallback=str(absence["previous_member_status"] or MemberStatus.ACTIVE.value),
            )
            await self._set_member_status(connection, member_id, restored, now)
            result.update({"member_status": restored, "absence_id": absence_id})

        elif request_type is AdministrativeRequestType.RESERVE_ENTRY:
            await self._require_member_status(connection, member_id, MemberStatus.ACTIVE.value)
            await self._set_member_status(connection, member_id, MemberStatus.RESERVE.value, now)
            closed = await self._close_active_shift(
                connection, guild_id, member_id, discord_id, now, "RESERVE_APPROVED", actor_id
            )
            result.update({"member_status": MemberStatus.RESERVE.value, "shift_closed": closed})

        elif request_type is AdministrativeRequestType.RESERVE_EXIT:
            await self._require_member_status(connection, member_id, MemberStatus.RESERVE.value)
            restored = await self._effective_status(
                connection, guild_id, member_id, now, fallback=MemberStatus.ACTIVE.value
            )
            await self._set_member_status(connection, member_id, restored, now)
            result["member_status"] = restored

        elif request_type is AdministrativeRequestType.HOURS_CORRECTION:
            shift_id = int(payload["shift_id"])
            cursor = await connection.execute(
                """
                SELECT s.status,
                    COALESCE((SELECT SUM(COALESCE(ss.ended_at, ?) - ss.started_at)
                              FROM shift_segments ss WHERE ss.shift_id=s.id), 0)
                    + COALESCE((SELECT SUM(sa.delta_ms) FROM shift_adjustments sa
                                WHERE sa.shift_id=s.id), 0) AS total_ms
                FROM shifts s WHERE s.id=? AND s.guild_id=? AND s.member_id=?
                """,
                (now, shift_id, guild_id, member_id),
            )
            shift = await cursor.fetchone()
            if not shift or shift["status"] != "CLOSED":
                raise ConflictError("A sessão não está mais disponível para correção.")
            previous_ms = int(shift["total_ms"])
            requested_ms = int(payload["requested_total_minutes"]) * 60_000
            delta_minutes = round((requested_ms - previous_ms) / 60_000)
            applied_ms = delta_minutes * 60_000
            if delta_minutes:
                await connection.execute(
                    """
                    INSERT INTO shift_adjustments(
                        guild_id, shift_id, delta_ms, reason, actor_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        shift_id,
                        applied_ms,
                        f"Solicitação #{request['id']}: {payload['reason']}",
                        actor_id,
                        now,
                    ),
                )
            await self.audit.record(
                guild_id,
                "SHIFT_TIME_ADJUSTED_FROM_REQUEST",
                actor_id=actor_id,
                target_id=discord_id,
                before={"shift_id": shift_id, "total_ms": previous_ms},
                after={
                    "shift_id": shift_id,
                    "total_ms": previous_ms + applied_ms,
                    "delta_minutes": delta_minutes,
                    "request_id": int(request["id"]),
                },
                reason=str(payload["reason"]),
                connection=connection,
            )
            result.update(
                {
                    "shift_id": shift_id,
                    "previous_total_ms": previous_ms,
                    "new_total_ms": previous_ms + applied_ms,
                    "delta_minutes": delta_minutes,
                }
            )

        elif request_type is AdministrativeRequestType.DATA_CHANGE:
            changes = dict(payload["changes"])
            cursor = await connection.execute(
                "SELECT mta_nick, character_id, unit FROM members WHERE id=?", (member_id,)
            )
            member = await cursor.fetchone()
            before = {key: member[key] for key in changes}
            assignments = ", ".join(f"{key}=?" for key in changes)
            await connection.execute(
                f"UPDATE members SET {assignments}, updated_at=? WHERE id=?",
                (*changes.values(), now, member_id),
            )
            await self.audit.record(
                guild_id,
                "MEMBER_DATA_CHANGED_FROM_REQUEST",
                actor_id=actor_id,
                target_id=discord_id,
                before=before,
                after=changes,
                reason=str(payload["reason"]),
                connection=connection,
            )
            result["member_changes"] = changes

        elif request_type is AdministrativeRequestType.DISMISSAL:
            await self._set_member_status(connection, member_id, MemberStatus.DISMISSED.value, now)
            closed = await self._close_active_shift(
                connection, guild_id, member_id, discord_id, now, "DISMISSAL_APPROVED", actor_id
            )
            result.update({"member_status": MemberStatus.DISMISSED.value, "shift_closed": closed})
        return result

    async def cancel(self, guild_id: int, discord_id: int, request_id: int) -> None:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE administrative_requests SET status='CANCELLED', cancelled_at=?
                WHERE id=? AND guild_id=? AND discord_id=? AND status='PENDING'
                """,
                (now, request_id, guild_id, discord_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Solicitação pendente não encontrada.")
            await self.audit.record(
                guild_id,
                "ADMIN_REQUEST_CANCELLED",
                actor_id=discord_id,
                target_id=discord_id,
                after={"request_id": request_id, "status": "CANCELLED"},
                connection=connection,
            )

    async def get(self, guild_id: int, request_id: int):
        row = await self.database.fetchone(
            """
            SELECT ar.*, m.mta_nick, m.status AS member_status
            FROM administrative_requests ar JOIN members m ON m.id=ar.member_id
            WHERE ar.guild_id=? AND ar.id=?
            """,
            (guild_id, request_id),
        )
        return self._decode(row) if row else None

    async def for_member(self, guild_id: int, discord_id: int, limit: int = 20):
        rows = await self.database.fetchall(
            """
            SELECT ar.*, m.mta_nick FROM administrative_requests ar
            JOIN members m ON m.id=ar.member_id
            WHERE ar.guild_id=? AND ar.discord_id=?
            ORDER BY ar.submitted_at DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )
        return [self._decode(row) for row in rows]

    async def pending_queue(self, guild_id: int, limit: int = 25, offset: int = 0):
        absences = await self.database.fetchall(
            """
            SELECT ar.*, m.mta_nick FROM absence_requests ar
            JOIN members m ON m.id=ar.member_id
            WHERE ar.guild_id=? AND ar.status='PENDING'
            """,
            (guild_id,),
        )
        requests = await self.database.fetchall(
            """
            SELECT ar.*, m.mta_nick FROM administrative_requests ar
            JOIN members m ON m.id=ar.member_id
            WHERE ar.guild_id=? AND ar.status='PENDING'
            """,
            (guild_id,),
        )
        queue = [
            {
                **dict(row),
                "source": "ABSENCE",
                "request_type": "ABSENCE",
                "payload": {
                    "starts_at": int(row["starts_at"]),
                    "ends_at": int(row["ends_at"]),
                    "reason": row["reason"],
                    "observation": row["observation"],
                },
            }
            for row in absences
        ]
        queue.extend({**self._decode(row), "source": "ADMIN"} for row in requests)
        queue.sort(
            key=lambda item: (int(item["submitted_at"]), str(item["source"]), int(item["id"]))
        )
        return queue[offset : offset + limit]

    async def recent_queue(self, guild_id: int, limit: int = 25):
        absences = await self.database.fetchall(
            """
            SELECT ar.*, m.mta_nick FROM absence_requests ar
            JOIN members m ON m.id=ar.member_id WHERE ar.guild_id=?
            ORDER BY ar.submitted_at DESC LIMIT ?
            """,
            (guild_id, limit),
        )
        requests = await self.database.fetchall(
            """
            SELECT ar.*, m.mta_nick FROM administrative_requests ar
            JOIN members m ON m.id=ar.member_id WHERE ar.guild_id=?
            ORDER BY ar.submitted_at DESC LIMIT ?
            """,
            (guild_id, limit),
        )
        queue = [
            {
                **dict(row),
                "source": "ABSENCE",
                "request_type": "ABSENCE",
                "payload": {"reason": row["reason"]},
            }
            for row in absences
        ]
        queue.extend({**self._decode(row), "source": "ADMIN"} for row in requests)
        queue.sort(key=lambda item: int(item["submitted_at"]), reverse=True)
        return queue[:limit]

    async def pending_count(self, guild_id: int) -> int:
        row = await self.database.fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM absence_requests
                 WHERE guild_id=? AND status='PENDING')
                +
                (SELECT COUNT(*) FROM administrative_requests
                 WHERE guild_id=? AND status='PENDING') AS total
            """,
            (guild_id, guild_id),
        )
        return int(row["total"])

    async def _member(
        self, connection: aiosqlite.Connection, guild_id: int, discord_id: int
    ) -> aiosqlite.Row:
        cursor = await connection.execute(
            "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
            (guild_id, discord_id),
        )
        member = await cursor.fetchone()
        if not member:
            raise NotFoundError("Você ainda não possui cadastro aprovado.")
        return member

    async def _require_member_status(
        self, connection: aiosqlite.Connection, member_id: int, expected: str
    ) -> None:
        cursor = await connection.execute("SELECT status FROM members WHERE id=?", (member_id,))
        member = await cursor.fetchone()
        if not member or member["status"] != expected:
            raise ConflictError("O status do membro mudou desde o envio da solicitação.")

    async def _set_member_status(
        self, connection: aiosqlite.Connection, member_id: int, status: str, now: int
    ) -> None:
        await connection.execute(
            "UPDATE members SET status=?, updated_at=? WHERE id=?", (status, now, member_id)
        )

    async def _effective_status(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        member_id: int,
        now: int,
        *,
        fallback: str,
    ) -> str:
        cursor = await connection.execute(
            """
            SELECT punishment_type FROM punishments
            WHERE guild_id=? AND member_id=? AND status='ACTIVE'
              AND punishment_type IN ('SUSPENSION','DISMISSAL')
              AND (ends_at IS NULL OR ends_at > ?)
            ORDER BY CASE punishment_type WHEN 'DISMISSAL' THEN 1 ELSE 2 END LIMIT 1
            """,
            (guild_id, member_id, now),
        )
        punishment = await cursor.fetchone()
        if punishment:
            return (
                MemberStatus.DISMISSED.value
                if punishment["punishment_type"] == "DISMISSAL"
                else MemberStatus.SUSPENDED.value
            )
        cursor = await connection.execute(
            """
            SELECT 1 FROM absence_requests
            WHERE guild_id=? AND member_id=? AND status='APPROVED'
              AND starts_at <= ? AND ends_at > ? LIMIT 1
            """,
            (guild_id, member_id, now, now),
        )
        if await cursor.fetchone():
            return MemberStatus.AWAY.value
        return fallback if fallback == MemberStatus.RESERVE.value else MemberStatus.ACTIVE.value

    async def _close_active_shift(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        member_id: int,
        discord_id: int,
        now: int,
        reason: str,
        actor_id: int,
    ) -> bool:
        cursor = await connection.execute(
            """
            SELECT * FROM shifts WHERE guild_id=? AND member_id=?
              AND status IN ('ACTIVE','GRACE') LIMIT 1
            """,
            (guild_id, member_id),
        )
        shift = await cursor.fetchone()
        if not shift:
            return False
        valid_end = int(shift["grace_started_at"] or now) if shift["status"] == "GRACE" else now
        await connection.execute(
            """
            UPDATE shift_segments SET ended_at=?, end_reason=?
            WHERE shift_id=? AND ended_at IS NULL
            """,
            (valid_end, reason, shift["id"]),
        )
        validation = await closed_validation_values(connection, shift, valid_end)
        cursor = await connection.execute(
            """
            UPDATE shifts SET status='CLOSED', ended_at=?, closed_at=?, end_reason=?,
                grace_started_at=NULL, grace_deadline=NULL,
                gross_duration_ms=?, patrol_duration_ms=?, patrol_requirement_met_at=?,
                validation_status=?, automatic_validation_status=?, invalid_reason=?,
                validation_source='AUTO', validated_at=?
            WHERE id=? AND status IN ('ACTIVE','GRACE')
            """,
            (
                valid_end,
                now,
                reason,
                validation["gross_duration_ms"],
                validation["patrol_duration_ms"],
                validation["patrol_requirement_met_at"],
                validation["validation_status"],
                validation["validation_status"],
                validation["invalid_reason"],
                now,
                shift["id"],
            ),
        )
        if cursor.rowcount != 1:
            return False
        await self.audit.record(
            guild_id,
            "SHIFT_CLOSED_BY_ADMIN_REQUEST",
            actor_id=actor_id,
            target_id=discord_id,
            before={"shift_id": int(shift["id"]), "status": shift["status"]},
            after={
                "status": "CLOSED",
                "end_reason": reason,
                "validation_status": validation["validation_status"],
            },
            connection=connection,
        )
        return True

    @staticmethod
    def _decode(row: aiosqlite.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result
