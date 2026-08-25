from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .time_utils import utc_now_ms

STATUS_STATES = frozenset(
    {
        "OPERACIONAL",
        "ATUALIZANDO",
        "EM_MANUTENCAO",
        "INSTAVEL_DEGRADADO",
        "TEMPORARIAMENTE_DESATIVADO",
        "INDISPONIVEL",
    }
)

STATUS_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("BOT_GATEWAY", "Bot e Gateway"),
    ("API_SITE", "API e Site"),
    ("PORTARIA_CADASTRO", "Portaria e Cadastro"),
    ("RECRUTAMENTO_MESA", "Recrutamento e Mesa"),
    ("NOTIFICACOES_FILAS", "Notificações e Filas"),
    ("AUDITORIA_HISTORICO", "Auditoria e Histórico"),
    ("BATE_PONTO_PATRULHAS", "Bate-ponto e Patrulhas"),
    ("CENTRAL_TAGS", "Central de Tags"),
)

COMPONENT_LABELS = dict(STATUS_COMPONENTS)
STATE_SEVERITY = {
    "OPERACIONAL": 0,
    "ATUALIZANDO": 1,
    "INSTAVEL_DEGRADADO": 2,
    "EM_MANUTENCAO": 3,
    "TEMPORARIAMENTE_DESATIVADO": 4,
    "INDISPONIVEL": 5,
}


class StatusService:
    """Durable operational status with manual overrides and stable detection."""

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

    @staticmethod
    def _row(row: Any) -> dict[str, object]:
        return dict(row)

    @staticmethod
    def _validate_component(component_key: str) -> str:
        normalized = component_key.strip().upper()
        if normalized not in COMPONENT_LABELS:
            raise ValidationError("Componente de status desconhecido.")
        return normalized

    @staticmethod
    def _validate_state(state: str, *, allow_operational: bool = True) -> str:
        normalized = state.strip().upper()
        if normalized not in STATUS_STATES or (
            not allow_operational and normalized == "OPERACIONAL"
        ):
            raise ValidationError("Estado operacional inválido.")
        return normalized

    def _effective_state(self, row: Any, now: int) -> tuple[str, str]:
        override_state = row["override_state"]
        expires_at = row["override_expires_at"]
        if override_state and (expires_at is None or int(expires_at) > now):
            return str(override_state), str(row["override_reason"] or "Ajuste operacional.")
        return str(row["detected_state"]), str(row["detected_summary"])

    def _project(self, row: Any, now: int) -> dict[str, object]:
        item = self._row(row)
        state, summary = self._effective_state(row, now)
        item["state"] = state
        item["summary"] = summary
        item["label"] = COMPONENT_LABELS[str(row["component_key"])]
        item["is_override"] = bool(
            row["override_state"]
            and (row["override_expires_at"] is None or int(row["override_expires_at"]) > now)
        )
        return item

    async def ensure_components(self, guild_id: int) -> None:
        now = self.clock()
        async with self.database.transaction() as connection:
            for component_key, _ in STATUS_COMPONENTS:
                await connection.execute(
                    """
                    INSERT OR IGNORE INTO system_status_components(
                        guild_id, component_key, detected_at, last_signal_at,
                        last_success_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (guild_id, component_key, now, now, now, now, now),
                )

    async def snapshot(self, guild_id: int) -> dict[str, object]:
        await self.ensure_components(guild_id)
        now = self.clock()
        rows = await self.database.fetchall(
            """
            SELECT * FROM system_status_components
            WHERE guild_id=? ORDER BY CASE component_key
                WHEN 'BOT_GATEWAY' THEN 1 WHEN 'API_SITE' THEN 2
                WHEN 'PORTARIA_CADASTRO' THEN 3 WHEN 'RECRUTAMENTO_MESA' THEN 4
                WHEN 'NOTIFICACOES_FILAS' THEN 5 WHEN 'AUDITORIA_HISTORICO' THEN 6
                WHEN 'BATE_PONTO_PATRULHAS' THEN 7 WHEN 'CENTRAL_TAGS' THEN 8
                ELSE 99 END
            """,
            (guild_id,),
        )
        components = [self._project(row, now) for row in rows]
        global_state = max(
            (str(item["state"]) for item in components),
            key=lambda state: STATE_SEVERITY[state],
            default="OPERACIONAL",
        )
        return {
            "guild_id": guild_id,
            "global_state": global_state,
            "components": components,
            "updated_at": max(
                (int(item["updated_at"]) for item in components), default=now
            ),
        }

    async def component(self, guild_id: int, component_key: str) -> dict[str, object]:
        key = self._validate_component(component_key)
        await self.ensure_components(guild_id)
        row = await self.database.fetchone(
            "SELECT * FROM system_status_components WHERE guild_id=? AND component_key=?",
            (guild_id, key),
        )
        if not row:
            raise NotFoundError("Componente de status não encontrado.")
        return self._project(row, self.clock())

    async def _append_event(
        self,
        connection: Any,
        *,
        guild_id: int,
        component_key: str,
        event_type: str,
        previous_state: str | None,
        next_state: str,
        summary: str,
        reason: str | None,
        actor_id: int | None,
        responsible_id: int | None,
        expected_at: int | None,
        metadata: dict[str, object] | None = None,
        notify: bool,
        correlation_id: str,
        now: int,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO system_status_events(
                guild_id, component_key, event_type, previous_state, next_state,
                summary, reason, actor_id, responsible_id, expected_at,
                metadata_json, correlation_id, notification_status, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                component_key,
                event_type,
                previous_state,
                next_state,
                summary,
                reason,
                actor_id,
                responsible_id,
                expected_at,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                correlation_id,
                "PENDING" if notify else "NOT_REQUESTED",
                now,
            ),
        )

    async def set_override(
        self,
        guild_id: int,
        component_key: str,
        state: str,
        *,
        actor_id: int,
        reason: str,
        expected_at: int | None = None,
        expires_at: int | None = None,
        expected_version: int | None = None,
    ) -> dict[str, object]:
        key = self._validate_component(component_key)
        normalized_state = self._validate_state(state, allow_operational=False)
        normalized_reason = reason.strip()
        if len(normalized_reason) < 3:
            raise ValidationError("Informe um motivo claro para alterar o status.")
        now = self.clock()
        if expected_at is not None and expected_at <= now:
            raise ValidationError("A previsão precisa estar no futuro.")
        if expires_at is not None and expires_at <= now:
            raise ValidationError("A expiração precisa estar no futuro.")
        await self.ensure_components(guild_id)
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM system_status_components WHERE guild_id=? AND component_key=?",
                (guild_id, key),
            )
            row = await cursor.fetchone()
            assert row is not None
            previous_state, _ = self._effective_state(row, now)
            if expected_version is not None and int(row["version"]) != expected_version:
                raise ConflictError("O status foi alterado. Atualize o painel e tente novamente.")
            cursor = await connection.execute(
                """
                UPDATE system_status_components
                SET override_state=?, override_reason=?, override_responsible_id=?,
                    override_started_at=?, override_expected_at=?, override_expires_at=?,
                    version=version+1, updated_at=?
                WHERE guild_id=? AND component_key=? AND version=?
                """,
                (
                    normalized_state,
                    normalized_reason,
                    actor_id,
                    now,
                    expected_at,
                    expires_at,
                    now,
                    guild_id,
                    key,
                    int(row["version"]),
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("O status foi alterado por outra pessoa.")
            correlation_id = str(uuid.uuid4())
            await self._append_event(
                connection,
                guild_id=guild_id,
                component_key=key,
                event_type="STATUS_OVERRIDE_SET",
                previous_state=previous_state,
                next_state=normalized_state,
                summary=normalized_reason,
                reason=normalized_reason,
                actor_id=actor_id,
                responsible_id=actor_id,
                expected_at=expected_at,
                metadata={"expires_at": expires_at},
                notify=previous_state != normalized_state,
                correlation_id=correlation_id,
                now=now,
            )
            await self.audit.record(
                guild_id,
                "SYSTEM_STATUS_OVERRIDE_SET",
                actor_id=actor_id,
                before={"component": key, "state": previous_state},
                after={
                    "component": key,
                    "state": normalized_state,
                    "expected_at": expected_at,
                    "expires_at": expires_at,
                },
                reason=normalized_reason,
                connection=connection,
                correlation_id=correlation_id,
            )
            cursor = await connection.execute(
                "SELECT * FROM system_status_components WHERE guild_id=? AND component_key=?",
                (guild_id, key),
            )
            updated = await cursor.fetchone()
            assert updated is not None
            return self._project(updated, now)

    async def clear_override(
        self,
        guild_id: int,
        component_key: str,
        *,
        actor_id: int,
        reason: str,
        expected_version: int | None = None,
        event_type: str = "STATUS_OVERRIDE_CLEARED",
    ) -> dict[str, object]:
        key = self._validate_component(component_key)
        normalized_reason = reason.strip()
        if len(normalized_reason) < 3:
            raise ValidationError("Informe o motivo da normalização.")
        now = self.clock()
        await self.ensure_components(guild_id)
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM system_status_components WHERE guild_id=? AND component_key=?",
                (guild_id, key),
            )
            row = await cursor.fetchone()
            assert row is not None
            previous_state, _ = self._effective_state(row, now)
            if expected_version is not None and int(row["version"]) != expected_version:
                raise ConflictError("O status foi alterado. Atualize o painel e tente novamente.")
            if not row["override_state"]:
                return self._project(row, now)
            next_state = str(row["detected_state"])
            cursor = await connection.execute(
                """
                UPDATE system_status_components
                SET override_state=NULL, override_reason=NULL,
                    override_responsible_id=NULL, override_started_at=NULL,
                    override_expected_at=NULL, override_expires_at=NULL,
                    version=version+1, updated_at=?
                WHERE guild_id=? AND component_key=? AND version=?
                """,
                (now, guild_id, key, int(row["version"])),
            )
            if cursor.rowcount != 1:
                raise ConflictError("O status foi alterado por outra pessoa.")
            correlation_id = str(uuid.uuid4())
            await self._append_event(
                connection,
                guild_id=guild_id,
                component_key=key,
                event_type=event_type,
                previous_state=previous_state,
                next_state=next_state,
                summary=str(row["detected_summary"]),
                reason=normalized_reason,
                actor_id=actor_id,
                responsible_id=actor_id,
                expected_at=None,
                notify=previous_state != next_state,
                correlation_id=correlation_id,
                now=now,
            )
            await self.audit.record(
                guild_id,
                "SYSTEM_STATUS_OVERRIDE_CLEARED",
                actor_id=actor_id,
                before={"component": key, "state": previous_state},
                after={"component": key, "state": next_state},
                reason=normalized_reason,
                connection=connection,
                correlation_id=correlation_id,
            )
            cursor = await connection.execute(
                "SELECT * FROM system_status_components WHERE guild_id=? AND component_key=?",
                (guild_id, key),
            )
            updated = await cursor.fetchone()
            assert updated is not None
            return self._project(updated, now)

    async def expire_overrides(self, guild_id: int) -> int:
        now = self.clock()
        rows = await self.database.fetchall(
            """
            SELECT component_key, version FROM system_status_components
            WHERE guild_id=? AND override_state IS NOT NULL
              AND override_expires_at IS NOT NULL AND override_expires_at<=?
            ORDER BY component_key
            """,
            (guild_id, now),
        )
        expired = 0
        for row in rows:
            await self.clear_override(
                guild_id,
                str(row["component_key"]),
                actor_id=0,
                reason="Expiração automática do estado administrativo.",
                expected_version=int(row["version"]),
                event_type="STATUS_OVERRIDE_EXPIRED",
            )
            expired += 1
        return expired

    async def record_observation(
        self,
        guild_id: int,
        component_key: str,
        state: str,
        summary: str,
        *,
        failure_threshold: int = 2,
        recovery_threshold: int = 2,
        metadata: dict[str, object] | None = None,
    ) -> tuple[dict[str, object], bool]:
        key = self._validate_component(component_key)
        observed_state = self._validate_state(state)
        normalized_summary = summary.strip()[:500] or "Sinal operacional recebido."
        if failure_threshold < 1 or recovery_threshold < 1:
            raise ValidationError("Os limites de confirmação precisam ser positivos.")
        now = self.clock()
        await self.ensure_components(guild_id)
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM system_status_components WHERE guild_id=? AND component_key=?",
                (guild_id, key),
            )
            row = await cursor.fetchone()
            assert row is not None
            current_detected = str(row["detected_state"])
            if observed_state == current_detected:
                await connection.execute(
                    """
                    UPDATE system_status_components
                    SET detected_summary=?, candidate_state=NULL, candidate_summary=NULL,
                        candidate_streak=0, last_signal_at=?,
                        last_success_at=CASE WHEN ?='OPERACIONAL' THEN ? ELSE last_success_at END,
                        updated_at=?
                    WHERE guild_id=? AND component_key=?
                    """,
                    (
                        normalized_summary,
                        now,
                        observed_state,
                        now,
                        now,
                        guild_id,
                        key,
                    ),
                )
                cursor = await connection.execute(
                    "SELECT * FROM system_status_components WHERE guild_id=? AND component_key=?",
                    (guild_id, key),
                )
                stable = await cursor.fetchone()
                assert stable is not None
                return self._project(stable, now), False

            streak = (
                int(row["candidate_streak"]) + 1
                if str(row["candidate_state"] or "") == observed_state
                else 1
            )
            threshold = recovery_threshold if observed_state == "OPERACIONAL" else failure_threshold
            if streak < threshold:
                await connection.execute(
                    """
                    UPDATE system_status_components
                    SET candidate_state=?, candidate_summary=?, candidate_streak=?,
                        last_signal_at=?, updated_at=?
                    WHERE guild_id=? AND component_key=?
                    """,
                    (observed_state, normalized_summary, streak, now, now, guild_id, key),
                )
                cursor = await connection.execute(
                    "SELECT * FROM system_status_components WHERE guild_id=? AND component_key=?",
                    (guild_id, key),
                )
                pending = await cursor.fetchone()
                assert pending is not None
                return self._project(pending, now), False

            previous_effective, _ = self._effective_state(row, now)
            cursor = await connection.execute(
                """
                UPDATE system_status_components
                SET detected_state=?, detected_summary=?, detected_at=?,
                    candidate_state=NULL, candidate_summary=NULL, candidate_streak=0,
                    last_signal_at=?,
                    last_success_at=CASE WHEN ?='OPERACIONAL' THEN ? ELSE last_success_at END,
                    version=version+1, updated_at=?
                WHERE guild_id=? AND component_key=? AND version=?
                """,
                (
                    observed_state,
                    normalized_summary,
                    now,
                    now,
                    observed_state,
                    now,
                    now,
                    guild_id,
                    key,
                    int(row["version"]),
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("O monitor recebeu uma atualização concorrente.")
            override_active = bool(
                row["override_state"]
                and (
                    row["override_expires_at"] is None
                    or int(row["override_expires_at"]) > now
                )
            )
            if not override_active:
                correlation_id = str(uuid.uuid4())
                await self._append_event(
                    connection,
                    guild_id=guild_id,
                    component_key=key,
                    event_type="STATUS_AUTOMATIC_CHANGED",
                    previous_state=previous_effective,
                    next_state=observed_state,
                    summary=normalized_summary,
                    reason=None,
                    actor_id=None,
                    responsible_id=None,
                    expected_at=None,
                    metadata=metadata,
                    notify=previous_effective != observed_state,
                    correlation_id=correlation_id,
                    now=now,
                )
                await self.audit.record(
                    guild_id,
                    "SYSTEM_STATUS_AUTOMATIC_CHANGED",
                    before={"component": key, "state": previous_effective},
                    after={"component": key, "state": observed_state},
                    connection=connection,
                    correlation_id=correlation_id,
                )
            cursor = await connection.execute(
                "SELECT * FROM system_status_components WHERE guild_id=? AND component_key=?",
                (guild_id, key),
            )
            updated = await cursor.fetchone()
            assert updated is not None
            return self._project(updated, now), not override_active

    async def recent_events(
        self, guild_id: int, *, limit: int = 20
    ) -> list[dict[str, object]]:
        safe_limit = max(1, min(int(limit), 50))
        rows = await self.database.fetchall(
            """
            SELECT * FROM system_status_events
            WHERE guild_id=? ORDER BY occurred_at DESC, id DESC LIMIT ?
            """,
            (guild_id, safe_limit),
        )
        return [self._row(row) for row in rows]

    async def delivery_health_metrics(
        self, *, recent_failure_ms: int = 3_600_000
    ) -> dict[str, dict[str, int]]:
        """Return current retryable backlog without reviving historical failures."""
        if recent_failure_ms < 1:
            raise ValidationError("A janela de falhas recentes precisa ser positiva.")
        now = self.clock()
        cutoff = now - recent_failure_ms
        outbox = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) AS failed,
                   MIN(created_at) AS oldest
            FROM web_action_outbox
            WHERE status IN ('PENDING','PROCESSING')
               OR (status='FAILED' AND attempts<10 AND created_at>=?)
            """,
            (cutoff,),
        )
        audit = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN delivery_status='FAILED' THEN 1 ELSE 0 END) AS failed,
                   MIN(created_at) AS oldest
            FROM audit_logs
            WHERE delivery_status IN ('PENDING','PROCESSING')
               OR (delivery_status='FAILED' AND delivery_attempts<10 AND created_at>=?)
            """,
            (cutoff,),
        )

        def project(row: Any) -> dict[str, int]:
            total = int(row["total"] or 0) if row else 0
            oldest = int(row["oldest"] or now) if row and total else now
            return {
                "total": total,
                "failed": int(row["failed"] or 0) if row else 0,
                "oldest_ms": max(0, now - oldest),
            }

        return {"outbox": project(outbox), "audit": project(audit)}

    async def pending_notifications(
        self, guild_id: int, *, limit: int = 20
    ) -> list[dict[str, object]]:
        safe_limit = max(1, min(int(limit), 50))
        rows = await self.database.fetchall(
            """
            SELECT * FROM system_status_events
            WHERE guild_id=? AND notification_status IN ('PENDING','FAILED')
              AND notification_attempts<10
            ORDER BY occurred_at, id LIMIT ?
            """,
            (guild_id, safe_limit),
        )
        return [self._row(row) for row in rows]

    async def claim_notification(
        self, event_id: int, *, cooldown_ms: int
    ) -> dict[str, object] | None:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT e.*, c.last_notification_at
                FROM system_status_events e
                JOIN system_status_components c
                  ON c.guild_id=e.guild_id AND c.component_key=e.component_key
                WHERE e.id=?
                """,
                (event_id,),
            )
            event = await cursor.fetchone()
            if not event or str(event["notification_status"]) not in {"PENDING", "FAILED"}:
                return None
            is_resolution = str(event["next_state"]) == "OPERACIONAL"
            last_notification_at = event["last_notification_at"]
            if (
                not is_resolution
                and last_notification_at is not None
                and int(last_notification_at) + max(0, cooldown_ms) > now
            ):
                await connection.execute(
                    "UPDATE system_status_events SET notification_status='SUPPRESSED' WHERE id=?",
                    (event_id,),
                )
                return None
            cursor = await connection.execute(
                """
                UPDATE system_status_events
                SET notification_status='PROCESSING',
                    notification_attempts=notification_attempts+1,
                    notification_claimed_at=?, notification_error=NULL
                WHERE id=? AND notification_status IN ('PENDING','FAILED')
                """,
                (now, event_id),
            )
            if cursor.rowcount != 1:
                return None
            cursor = await connection.execute(
                "SELECT * FROM system_status_events WHERE id=?", (event_id,)
            )
            claimed = await cursor.fetchone()
            assert claimed is not None
            return self._row(claimed)

    async def mark_notification_delivered(
        self, event_id: int, *, message_id: int
    ) -> bool:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT guild_id, component_key FROM system_status_events WHERE id=?",
                (event_id,),
            )
            event = await cursor.fetchone()
            if not event:
                return False
            cursor = await connection.execute(
                """
                UPDATE system_status_events
                SET notification_status='DELIVERED', notification_message_id=?,
                    notification_claimed_at=NULL, notification_error=NULL
                WHERE id=? AND notification_status='PROCESSING'
                """,
                (message_id, event_id),
            )
            if cursor.rowcount != 1:
                return False
            await connection.execute(
                """
                UPDATE system_status_components SET last_notification_at=?, updated_at=?
                WHERE guild_id=? AND component_key=?
                """,
                (now, now, int(event["guild_id"]), str(event["component_key"])),
            )
            return True

    async def mark_notification_failed(self, event_id: int, *, error: str) -> bool:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE system_status_events
                SET notification_status='FAILED', notification_claimed_at=NULL,
                    notification_error=?
                WHERE id=? AND notification_status='PROCESSING'
                """,
                (error[:500], event_id),
            )
            return cursor.rowcount == 1

    async def recover_notification_claims(self, *, stale_after_ms: int = 300_000) -> int:
        if stale_after_ms < 1:
            raise ValidationError("O tempo de recuperação precisa ser positivo.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE system_status_events
                SET notification_status='FAILED', notification_claimed_at=NULL,
                    notification_error='Recuperado após reinício do bot'
                WHERE notification_status='PROCESSING' AND notification_claimed_at<=?
                """,
                (now - stale_after_ms,),
            )
            return cursor.rowcount
