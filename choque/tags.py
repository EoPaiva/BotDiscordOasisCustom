from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from .identity import normalize_bgr_id
from .time_utils import utc_now_ms


class TagService:
    """Durable state machine for the Central de Tags.

    The service owns tag-request state only.  It deliberately snapshots the
    existing member identity instead of creating a second identity store.
    Discord roles are reconciled asynchronously from a request version.
    """

    ACTIVE_STATUSES = frozenset(
        {
            "SOLICITADO",
            "AGUARDANDO_SET",
            "ATENDIMENTO_ASSUMIDO",
            "SET_REALIZADO",
            "AGUARDANDO_CONFIRMACAO",
            "PENDENCIA",
        }
    )

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

    async def _active_character_id_conflict(
        self,
        connection: Any,
        *,
        guild_id: int,
        member_id: int,
        character_id: str,
    ) -> Any | None:
        """Return another active identity that owns this MTA ID, if any.

        The canonical `members` table also enforces this invariant with a
        unique index.  Checking first turns a low-level SQLite constraint into
        an actionable administrative message and protects legacy snapshots
        before a request can be created.
        """
        cursor = await connection.execute(
            """
            SELECT id, discord_id, mta_nick
            FROM members
            WHERE guild_id=? AND character_id=? AND id<>? AND status='ACTIVE'
            LIMIT 1
            """,
            (guild_id, character_id, member_id),
        )
        return await cursor.fetchone()

    async def _enqueue_role_sync(
        self,
        connection: Any,
        request: Any,
        *,
        requested_by: int,
        now: int,
    ) -> None:
        """Persist a versioned role intent; Discord I/O runs after commit."""
        request_id = int(request["id"])
        version = int(request["version"])
        await connection.execute(
            """
            INSERT OR IGNORE INTO web_action_outbox(
                guild_id, action_type, target_discord_id, payload_json,
                requested_by, correlation_id, status, attempts, available_at, created_at
            ) VALUES (?, 'TAG_ROLE_SYNC', ?, ?, ?, ?, 'PENDING', 0, ?, ?)
            """,
            (
                int(request["guild_id"]),
                int(request["discord_id"]),
                json.dumps(
                    {"request_id": request_id, "request_version": version},
                    sort_keys=True,
                ),
                requested_by,
                f"tag-role-sync:{request_id}:v{version}",
                now,
                now,
            ),
        )

    async def _queue_projection(self, connection: Any, request: Any) -> dict[str, object]:
        """Attach non-persistent queue information to a member-facing response."""
        item = self._row(request)
        if str(request["status"]) != "AGUARDANDO_SET":
            return item
        cursor = await connection.execute(
            """
            SELECT COUNT(*) AS position FROM tag_requests
            WHERE guild_id=? AND status='AGUARDANDO_SET'
              AND (requested_at<? OR (requested_at=? AND id<=?))
            """,
            (
                int(request["guild_id"]),
                int(request["requested_at"]),
                int(request["requested_at"]),
                int(request["id"]),
            ),
        )
        position = await cursor.fetchone()
        item["queue_position"] = int(position["position"] if position else 0)
        item["waiting_ms"] = max(0, self.clock() - int(request["requested_at"]))
        return item

    async def request_tag(
        self,
        guild_id: int,
        discord_id: int,
        *,
        character_id: str | None = None,
        existing_tag: bool = False,
    ) -> dict[str, object]:
        """Create one active request, or return the existing one unchanged.

        A double-click, reconnect or concurrent API callback cannot append a
        second event because the partial unique index and `INSERT OR IGNORE`
        agree on the same active member identity.
        """
        now = self.clock()
        request_origin = "EXISTING_DECLARATION" if existing_tag else "SET_REQUEST"
        initial_status = "PENDENCIA" if existing_tag else "AGUARDANDO_SET"
        event_type = "TAG_EXISTING_DECLARED" if existing_tag else "TAG_REQUEST_CREATED"
        active_statuses = tuple(sorted(self.ACTIVE_STATUSES))
        placeholders = ",".join("?" for _ in active_statuses)
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT id, mta_nick, character_id, status, tag_status
                FROM members
                WHERE guild_id=? AND discord_id=?
                """,
                (guild_id, discord_id),
            )
            member = await cursor.fetchone()
            if not member:
                raise NotFoundError("Você ainda não possui cadastro aprovado.")
            if str(member["status"]) != "ACTIVE":
                raise ValidationError("Somente membros ativos podem solicitar a tag.")
            if str(member["tag_status"] or "") == "CONCLUIDO":
                raise ConflictError("Você já possui TAG SETADA registrada.")
            stored_character_id = str(member["character_id"] or "").strip()
            if stored_character_id:
                stored_character_id = normalize_bgr_id(stored_character_id)
            submitted_character_id = str(character_id or "").strip()
            if submitted_character_id:
                submitted_character_id = normalize_bgr_id(submitted_character_id)
            if stored_character_id and submitted_character_id and submitted_character_id != stored_character_id:
                raise ValidationError(
                    "O ID informado diverge do cadastro. Solicite uma correção administrativa."
                )
            if stored_character_id:
                character_id = stored_character_id
            elif submitted_character_id:
                character_id = submitted_character_id
                identity_correlation_id = str(uuid.uuid4())
                await connection.execute(
                    """
                    UPDATE members SET character_id=?, updated_at=?
                    WHERE id=? AND character_id IS NULL
                    """,
                    (character_id, now, int(member["id"])),
                )
                await self.audit.record(
                    guild_id,
                    "TAG_ID_SELF_CONFIRMED",
                    actor_id=discord_id,
                    target_id=discord_id,
                    after={"character_id": character_id, "source": "TAG_REQUEST"},
                    connection=connection,
                    correlation_id=identity_correlation_id,
                )
            else:
                raise ValidationError("Seu ID MTA precisa ser confirmado antes de solicitar a tag.")

            conflict = await self._active_character_id_conflict(
                connection,
                guild_id=guild_id,
                member_id=int(member["id"]),
                character_id=str(character_id),
            )
            if conflict:
                raise ValidationError(
                    "O ID MTA informado já está vinculado a outro membro ativo. "
                    "Solicite uma revisão administrativa da identidade."
                )

            cursor = await connection.execute(
                f"""
                SELECT * FROM tag_requests
                WHERE guild_id=? AND member_id=? AND status IN ({placeholders})
                ORDER BY requested_at DESC, id DESC LIMIT 1
                """,
                (guild_id, int(member["id"]), *active_statuses),
            )
            existing = await cursor.fetchone()
            if existing:
                return await self._queue_projection(connection, existing)

            cursor = await connection.execute(
                """
                INSERT OR IGNORE INTO tag_requests(
                    guild_id, member_id, discord_id, mta_nick_snapshot,
                    character_id_snapshot, status, request_origin,
                    responsible_notification_status,
                    requested_at, requested_by,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    int(member["id"]),
                    discord_id,
                    str(member["mta_nick"]),
                    character_id,
                    initial_status,
                    request_origin,
                    now,
                    discord_id,
                    now,
                    now,
                ),
            )
            if cursor.rowcount == 0:
                cursor = await connection.execute(
                    f"""
                    SELECT * FROM tag_requests
                    WHERE guild_id=? AND member_id=? AND status IN ({placeholders})
                    ORDER BY requested_at DESC, id DESC LIMIT 1
                    """,
                    (guild_id, int(member["id"]), *active_statuses),
                )
                existing = await cursor.fetchone()
                if existing:
                    return await self._queue_projection(connection, existing)
                raise RuntimeError("A solicitação de tag não pôde ser criada.")

            request_id = int(cursor.lastrowid)
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    guild_id,
                    event_type,
                    initial_status,
                    discord_id,
                    json.dumps(
                        {
                            "character_id": character_id,
                            "mta_nick": str(member["mta_nick"]),
                            "request_origin": request_origin,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                """
                INSERT INTO tag_role_sync_state(
                    tag_request_id, requested_version, updated_at
                ) VALUES (?, 1, ?)
                """,
                (request_id, now),
            )
            await connection.execute(
                "UPDATE members SET tag_status=?, updated_at=? WHERE id=?",
                (initial_status, now, int(member["id"])),
            )
            await self.audit.record(
                guild_id,
                event_type,
                actor_id=discord_id,
                target_id=discord_id,
                after={
                    "tag_request_id": request_id,
                    "status": initial_status,
                    "character_id": character_id,
                    "request_origin": request_origin,
                },
                connection=connection,
                correlation_id=correlation_id,
            )
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            created = await cursor.fetchone()
            assert created is not None
            await self._enqueue_role_sync(
                connection, created, requested_by=discord_id, now=now
            )
            return await self._queue_projection(connection, created)

    async def request_tag_from_waiting_role(
        self, guild_id: int, discord_id: int
    ) -> dict[str, object]:
        """Open one recoverable private check after observing AGUARDANDO SET.

        The Discord listener supplies the role observation, while this method
        owns deduplication and persistence. Existing active requests always win
        so a role event cannot create a parallel queue entry.
        """
        now = self.clock()
        active_statuses = tuple(sorted(self.ACTIVE_STATUSES))
        placeholders = ",".join("?" for _ in active_statuses)
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT id, mta_nick, character_id, status
                FROM members WHERE guild_id=? AND discord_id=?
                """,
                (guild_id, discord_id),
            )
            member = await cursor.fetchone()
            if not member:
                raise NotFoundError("O membro com AGUARDANDO SET não possui cadastro aprovado.")
            if str(member["status"]) != "ACTIVE":
                raise ValidationError("Somente membros ativos podem entrar na Central de Tags.")

            cursor = await connection.execute(
                f"""
                SELECT * FROM tag_requests
                WHERE guild_id=? AND member_id=? AND status IN ({placeholders})
                ORDER BY requested_at DESC, id DESC LIMIT 1
                """,
                (guild_id, int(member["id"]), *active_statuses),
            )
            existing = await cursor.fetchone()
            if existing:
                return await self._queue_projection(connection, existing)

            character_id = str(member["character_id"] or "SEM_ID_REGISTRADO").strip()
            cursor = await connection.execute(
                """
                INSERT OR IGNORE INTO tag_requests(
                    guild_id, member_id, discord_id, mta_nick_snapshot,
                    character_id_snapshot, status, request_origin, intake_source,
                    responsible_notification_status, confirmation_requested_at,
                    confirmation_delivery_status, set_by, set_at,
                    set_character_id, requested_at, requested_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'AGUARDANDO_CONFIRMACAO', 'SET_REQUEST',
                          'WAITING_ROLE_SCAN', 'NOT_REQUESTED', ?, 'PENDING', ?, ?, ?,
                          ?, 0, ?, ?)
                """,
                (
                    guild_id,
                    int(member["id"]),
                    discord_id,
                    str(member["mta_nick"]),
                    character_id,
                    now,
                    discord_id,
                    now,
                    character_id,
                    now,
                    now,
                    now,
                ),
            )
            if cursor.rowcount == 0:
                cursor = await connection.execute(
                    f"""
                    SELECT * FROM tag_requests
                    WHERE guild_id=? AND member_id=? AND status IN ({placeholders})
                    ORDER BY requested_at DESC, id DESC LIMIT 1
                    """,
                    (guild_id, int(member["id"]), *active_statuses),
                )
                existing = await cursor.fetchone()
                if existing:
                    return await self._queue_projection(connection, existing)
                raise RuntimeError("A verificação automática de tag não pôde ser criada.")

            request_id = int(cursor.lastrowid)
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_WAITING_ROLE_DETECTED', NULL,
                          'AGUARDANDO_CONFIRMACAO', NULL, ?, ?, ?)
                """,
                (
                    request_id,
                    guild_id,
                    json.dumps(
                        {"source": "DISCORD_ROLE", "role_state": "AGUARDANDO_SET"},
                        sort_keys=True,
                    ),
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                """
                INSERT INTO tag_role_sync_state(tag_request_id, requested_version, updated_at)
                VALUES (?, 1, ?)
                """,
                (request_id, now),
            )
            await connection.execute(
                """
                UPDATE members SET tag_status='AGUARDANDO_CONFIRMACAO', updated_at=?
                WHERE id=?
                """,
                (now, int(member["id"])),
            )
            await self.audit.record(
                guild_id,
                "TAG_WAITING_ROLE_DETECTED",
                target_id=discord_id,
                after={
                    "tag_request_id": request_id,
                    "status": "AGUARDANDO_CONFIRMACAO",
                    "source": "DISCORD_ROLE",
                },
                connection=connection,
                correlation_id=correlation_id,
            )
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            created = await cursor.fetchone()
            assert created is not None
            await self._enqueue_role_sync(connection, created, requested_by=0, now=now)
            return self._row(created)

    async def report_waiting_role_missing(
        self,
        request_id: int,
        *,
        discord_id: int,
        expected_version: int,
    ) -> dict[str, object]:
        """Move a role-detected private check into the command queue once."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            if int(request["discord_id"]) != discord_id:
                raise PermissionDenied("Somente o titular pode responder sobre a própria tag.")
            if str(request["intake_source"]) != "WAITING_ROLE_SCAN":
                raise ConflictError("Esta solicitação não veio da verificação de AGUARDANDO SET.")
            if str(request["status"]) == "AGUARDANDO_SET":
                return await self._queue_projection(connection, request)
            if str(request["status"]) != "AGUARDANDO_CONFIRMACAO":
                raise ConflictError("Esta solicitação já foi alterada.")
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET status='AGUARDANDO_SET', responsible_notification_status='PENDING',
                    responsible_notification_attempts=0,
                    responsible_notification_claimed_at=NULL,
                    responsible_notification_message_id=NULL,
                    responsible_notification_error=NULL,
                    version=version+1, updated_at=?
                WHERE id=? AND status='AGUARDANDO_CONFIRMACAO'
                  AND discord_id=? AND version=? AND intake_source='WAITING_ROLE_SCAN'
                """,
                (now, request_id, discord_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi alterada. Atualize o painel.")
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            updated = await cursor.fetchone()
            assert updated is not None
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_WAITING_ROLE_REQUIRES_SET',
                          'AGUARDANDO_CONFIRMACAO', 'AGUARDANDO_SET', ?, '{}', ?, ?)
                """,
                (request_id, int(request["guild_id"]), discord_id, correlation_id, now),
            )
            await connection.execute(
                """
                UPDATE tag_role_sync_state SET requested_version=?, updated_at=?
                WHERE tag_request_id=?
                """,
                (int(updated["version"]), now, request_id),
            )
            await connection.execute(
                "UPDATE members SET tag_status='AGUARDANDO_SET', updated_at=? WHERE id=?",
                (now, int(request["member_id"])),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_WAITING_ROLE_REQUIRES_SET",
                actor_id=discord_id,
                target_id=discord_id,
                before={"status": "AGUARDANDO_CONFIRMACAO"},
                after={"tag_request_id": request_id, "status": "AGUARDANDO_SET"},
                connection=connection,
                correlation_id=correlation_id,
            )
            await self._enqueue_role_sync(
                connection, updated, requested_by=discord_id, now=now
            )
            return await self._queue_projection(connection, updated)

    async def escalate_waiting_role_dm_failure(
        self, request_id: int, *, error: str
    ) -> dict[str, object]:
        """Expose a blocked proactive DM in the Central for manual contact."""
        normalized_error = error.strip()[:500] or "Mensagem privada indisponível"
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            if str(request["intake_source"]) != "WAITING_ROLE_SCAN":
                raise ConflictError("Esta notificação não pertence à varredura de cargos.")
            if str(request["status"]) == "AGUARDANDO_SET":
                return await self._queue_projection(connection, request)
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET status='AGUARDANDO_SET',
                    confirmation_delivery_status='FAILED',
                    confirmation_delivery_claimed_at=NULL,
                    confirmation_delivery_error=?,
                    responsible_notification_status='PENDING',
                    responsible_notification_attempts=0,
                    responsible_notification_claimed_at=NULL,
                    responsible_notification_message_id=NULL,
                    responsible_notification_error=NULL,
                    version=version+1, updated_at=?
                WHERE id=? AND status='AGUARDANDO_CONFIRMACAO'
                  AND intake_source='WAITING_ROLE_SCAN'
                  AND confirmation_delivery_status='PROCESSING'
                """,
                (normalized_error, now, request_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A entrega privada já foi alterada.")
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            updated = await cursor.fetchone()
            assert updated is not None
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, reason, metadata_json,
                    correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_WAITING_ROLE_DM_UNAVAILABLE',
                          'AGUARDANDO_CONFIRMACAO', 'AGUARDANDO_SET', NULL, ?, '{}', ?, ?)
                """,
                (
                    request_id,
                    int(request["guild_id"]),
                    normalized_error,
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                """
                UPDATE tag_role_sync_state SET requested_version=?, updated_at=?
                WHERE tag_request_id=?
                """,
                (int(updated["version"]), now, request_id),
            )
            await connection.execute(
                "UPDATE members SET tag_status='AGUARDANDO_SET', updated_at=? WHERE id=?",
                (now, int(request["member_id"])),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_WAITING_ROLE_DM_UNAVAILABLE",
                target_id=int(request["discord_id"]),
                before={"status": "AGUARDANDO_CONFIRMACAO"},
                after={
                    "tag_request_id": request_id,
                    "status": "AGUARDANDO_SET",
                    "manual_contact_required": True,
                },
                reason=normalized_error,
                connection=connection,
                correlation_id=correlation_id,
            )
            await self._enqueue_role_sync(connection, updated, requested_by=0, now=now)
            return await self._queue_projection(connection, updated)

    async def waiting_queue(self, guild_id: int, *, limit: int = 100) -> list[dict[str, object]]:
        """Return the operational queue oldest first, with no assigned cards."""
        safe_limit = max(1, min(int(limit), 100))
        rows = await self.database.fetchall(
            """
            SELECT * FROM tag_requests
            WHERE guild_id=? AND status='AGUARDANDO_SET'
            ORDER BY requested_at, id LIMIT ?
            """,
            (guild_id, safe_limit),
        )
        now = self.clock()
        queue: list[dict[str, object]] = []
        for position, row in enumerate(rows, start=1):
            item = self._row(row)
            item["queue_position"] = position
            item["waiting_ms"] = max(0, now - int(row["requested_at"]))
            queue.append(item)
        return queue

    async def search_requests(
        self, guild_id: int, query: str, *, limit: int = 25
    ) -> list[dict[str, object]]:
        """Find requests by MTA name/ID or Discord ID without exposing other guilds."""
        normalized = query.strip().lower()
        if not normalized:
            raise ValidationError("Informe nome, ID MTA ou ID Discord para pesquisar.")
        safe_limit = max(1, min(int(limit), 100))
        needle = f"%{normalized}%"
        rows = await self.database.fetchall(
            """
            SELECT * FROM tag_requests
            WHERE guild_id=? AND (
                LOWER(mta_nick_snapshot) LIKE ?
                OR LOWER(character_id_snapshot) LIKE ?
                OR CAST(discord_id AS TEXT) LIKE ?
            )
            ORDER BY requested_at DESC, id DESC LIMIT ?
            """,
            (guild_id, needle, needle, needle, safe_limit),
        )
        return [self._row(row) for row in rows]

    async def request_page(
        self,
        guild_id: int,
        *,
        statuses: tuple[str, ...] | None = None,
        history: bool = False,
        page: int = 0,
        page_size: int = 25,
    ) -> tuple[list[dict[str, object]], int]:
        """Read one deterministic Discord-sized page from the durable queue."""
        safe_page = max(0, int(page))
        safe_page_size = max(1, min(int(page_size), 25))
        clauses = ["guild_id=?"]
        params: list[object] = [guild_id]
        if statuses:
            clauses.append("status IN (" + ",".join("?" for _ in statuses) + ")")
            params.extend(statuses)
        where = " AND ".join(clauses)
        total_row = await self.database.fetchone(
            f"SELECT COUNT(*) AS total FROM tag_requests WHERE {where}", tuple(params)
        )
        order_by = "requested_at DESC, id DESC" if history else "requested_at, id"
        rows = await self.database.fetchall(
            f"SELECT * FROM tag_requests WHERE {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            (*params, safe_page_size, safe_page * safe_page_size),
        )
        return [self._row(row) for row in rows], int(total_row["total"] if total_row else 0)

    async def member_request(
        self, guild_id: int, discord_id: int
    ) -> dict[str, object] | None:
        """Return the active request, or the latest terminal one for status UX."""
        row = await self.database.fetchone(
            """
            SELECT * FROM tag_requests
            WHERE guild_id=? AND discord_id=?
            ORDER BY CASE WHEN status IN (
                'SOLICITADO','AGUARDANDO_SET','ATENDIMENTO_ASSUMIDO','SET_REALIZADO',
                'AGUARDANDO_CONFIRMACAO','PENDENCIA'
            ) THEN 0 ELSE 1 END,
            requested_at DESC, id DESC LIMIT 1
            """,
            (guild_id, discord_id),
        )
        return self._row(row) if row else None

    async def get_request(self, request_id: int) -> dict[str, object] | None:
        row = await self.database.fetchone(
            "SELECT * FROM tag_requests WHERE id=?", (request_id,)
        )
        return self._row(row) if row else None

    async def request_cards(
        self, guild_id: int, *, limit: int = 200
    ) -> list[dict[str, object]]:
        """Return active durable Discord request cards for view recovery."""
        safe_limit = max(1, min(int(limit), 500))
        rows = await self.database.fetchall(
            """
            SELECT * FROM tag_requests
            WHERE guild_id=? AND responsible_notification_message_id IS NOT NULL
              AND status IN (
                'SOLICITADO','AGUARDANDO_SET','ATENDIMENTO_ASSUMIDO',
                'SET_REALIZADO','AGUARDANDO_CONFIRMACAO','PENDENCIA'
              )
            ORDER BY requested_at, id LIMIT ?
            """,
            (guild_id, safe_limit),
        )
        return [self._row(row) for row in rows]

    async def pending_request_card_refreshes(
        self, guild_id: int, *, limit: int = 25
    ) -> list[dict[str, object]]:
        """Return stale cards without generating a second Discord message."""
        safe_limit = max(1, min(int(limit), 100))
        rows = await self.database.fetchall(
            """
            SELECT * FROM tag_requests
            WHERE guild_id=? AND responsible_notification_message_id IS NOT NULL
              AND (
                request_card_rendered_version IS NULL
                OR request_card_rendered_version<version
              )
            ORDER BY updated_at, id LIMIT ?
            """,
            (guild_id, safe_limit),
        )
        return [self._row(row) for row in rows]

    async def mark_request_card_rendered(
        self,
        request_id: int,
        *,
        message_id: int,
        rendered_version: int,
    ) -> bool:
        """Acknowledge one exact card render using message and request CAS."""
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests SET request_card_rendered_version=?
                WHERE id=? AND responsible_notification_message_id=? AND version=?
                """,
                (
                    rendered_version,
                    request_id,
                    message_id,
                    rendered_version,
                ),
            )
            return cursor.rowcount == 1

    async def rearm_missing_request_card(
        self, request_id: int, *, missing_message_id: int
    ) -> bool:
        """Recreate a card only after Discord confirmed its old message is gone."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET responsible_notification_status='PENDING',
                    responsible_notification_claimed_at=NULL,
                    responsible_notification_message_id=NULL,
                    responsible_notification_error=NULL,
                    request_card_rendered_version=NULL,
                    updated_at=?
                WHERE id=? AND responsible_notification_message_id=?
                  AND status IN (
                    'SOLICITADO','AGUARDANDO_SET','ATENDIMENTO_ASSUMIDO',
                    'SET_REALIZADO','AGUARDANDO_CONFIRMACAO','PENDENCIA'
                  )
                """,
                (now, request_id, missing_message_id),
            )
            return cursor.rowcount == 1

    async def queue_overview(self, guild_id: int) -> dict[str, object]:
        """Return the compact facts shown on the fixed summary panel."""
        oldest = await self.database.fetchone(
            """
            SELECT id, discord_id, requested_at FROM tag_requests
            WHERE guild_id=? AND status IN (
                'SOLICITADO','AGUARDANDO_SET','ATENDIMENTO_ASSUMIDO',
                'SET_REALIZADO','AGUARDANDO_CONFIRMACAO','PENDENCIA'
            )
            ORDER BY requested_at, id LIMIT 1
            """,
            (guild_id,),
        )
        handlers = await self.database.fetchall(
            """
            SELECT claimed_by, COUNT(*) AS total FROM tag_requests
            WHERE guild_id=? AND status='ATENDIMENTO_ASSUMIDO'
              AND claimed_by IS NOT NULL
            GROUP BY claimed_by ORDER BY MIN(claimed_at), claimed_by LIMIT 10
            """,
            (guild_id,),
        )
        return {
            "oldest": self._row(oldest) if oldest else None,
            "handlers": [self._row(row) for row in handlers],
        }

    async def request_metrics(self, request_id: int) -> dict[str, int]:
        """Return explainable elapsed times for reports without mutating the request."""
        request = await self.get_request(request_id)
        if not request:
            raise NotFoundError("Solicitação de tag não encontrada.")
        now = self.clock()
        requested_at = int(request["requested_at"])
        claimed_at = int(request["claimed_at"] or request["terminal_at"] or now)
        set_at = int(request["set_at"] or claimed_at)
        ended_at = int(request["confirmed_at"] or request["terminal_at"] or now)
        return {
            "waiting_ms": max(0, claimed_at - requested_at),
            "service_ms": max(0, set_at - claimed_at) if request["set_at"] else 0,
            "confirmation_ms": (
                max(0, ended_at - set_at) if request["set_at"] else 0
            ),
            "total_ms": max(0, ended_at - requested_at),
        }

    async def timeline(self, request_id: int) -> list[dict[str, object]]:
        rows = await self.database.fetchall(
            """
            SELECT * FROM tag_request_events
            WHERE tag_request_id=? ORDER BY occurred_at, id
            """,
            (request_id,),
        )
        return [self._row(row) for row in rows]

    async def summary(self, guild_id: int) -> dict[str, int]:
        """Counts for the fixed administrative panel, derived directly from state."""
        rows = await self.database.fetchall(
            """
            SELECT status, COUNT(*) AS total FROM tag_requests
            WHERE guild_id=? GROUP BY status
            """,
            (guild_id,),
        )
        result = {
            "SOLICITADO": 0,
            "AGUARDANDO_SET": 0,
            "ATENDIMENTO_ASSUMIDO": 0,
            "SET_REALIZADO": 0,
            "AGUARDANDO_CONFIRMACAO": 0,
            "CONCLUIDO": 0,
            "PENDENCIA": 0,
            "RECUSADO": 0,
            "CANCELADO": 0,
            "EXPIRADO": 0,
        }
        for row in rows:
            result[str(row["status"])] = int(row["total"])
        result["open"] = sum(result[status] for status in self.ACTIVE_STATUSES)
        now = self.clock()
        day_start = now - (now % (24 * 60 * 60 * 1_000))
        completed_today = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM tag_requests
            WHERE guild_id=? AND status='CONCLUIDO' AND confirmed_at>=?
            """,
            (guild_id, day_start),
        )
        result["completed_today"] = int(completed_today["total"]) if completed_today else 0
        return result

    async def claim_request(
        self, request_id: int, *, responsible_id: int, expected_version: int
    ) -> dict[str, object]:
        """Assign a waiting request to exactly one responsible user.

        `expected_version` is supplied by the Discord message/panel.  The
        compare-and-set update is the authority; the view is never trusted to
        decide whether a stale click is still valid.
        """
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            if (
                str(request["status"]) == "ATENDIMENTO_ASSUMIDO"
                and int(request["claimed_by"] or 0) == responsible_id
            ):
                return self._row(request)
            previous_status = str(request["status"])
            if previous_status not in {"AGUARDANDO_SET", "PENDENCIA"}:
                raise ConflictError("Esta solicitação já foi alterada por outro atendimento.")

            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET status='ATENDIMENTO_ASSUMIDO', claimed_by=?, claimed_at=?,
                    assignment_delivery_status='PENDING',
                    assignment_delivery_attempts=0,
                    assignment_delivery_claimed_at=NULL,
                    assignment_delivery_message_id=NULL,
                    assignment_delivery_error=NULL,
                    version=version+1, updated_at=?
                WHERE id=? AND status IN ('AGUARDANDO_SET', 'PENDENCIA') AND version=?
                """,
                (responsible_id, now, now, request_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi alterada por outro atendimento.")
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_REQUEST_CLAIMED', ?,
                          'ATENDIMENTO_ASSUMIDO', ?, '{}', ?, ?)
                """,
                (
                    request_id,
                    int(request["guild_id"]),
                    previous_status,
                    responsible_id,
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                "UPDATE members SET tag_status='ATENDIMENTO_ASSUMIDO', updated_at=? WHERE id=?",
                (now, int(request["member_id"])),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_REQUEST_CLAIMED",
                actor_id=responsible_id,
                target_id=int(request["discord_id"]),
                before={"status": previous_status},
                after={"tag_request_id": request_id, "status": "ATENDIMENTO_ASSUMIDO"},
                connection=connection,
                correlation_id=correlation_id,
            )
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            claimed = await cursor.fetchone()
            assert claimed is not None
            return self._row(claimed)

    async def mark_set_performed(
        self,
        request_id: int,
        *,
        responsible_id: int,
        expected_version: int,
        set_character_id: str,
    ) -> dict[str, object]:
        """Record the set, but wait for the member's own confirmation."""
        character_id = normalize_bgr_id(set_character_id)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            if (
                str(request["status"]) == "AGUARDANDO_CONFIRMACAO"
                and int(request["set_by"] or 0) == responsible_id
            ):
                return self._row(request)
            if str(request["status"]) != "ATENDIMENTO_ASSUMIDO":
                raise ConflictError("Esta solicitação não está disponível para registrar o set.")
            if int(request["claimed_by"] or 0) != responsible_id:
                raise ConflictError("Somente o responsável que assumiu pode registrar o set.")
            if character_id != str(request["character_id_snapshot"]):
                raise ValidationError(
                    "O ID informado diverge do cadastro. Solicite uma correção administrativa."
                )
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET status='AGUARDANDO_CONFIRMACAO', set_by=?, set_at=?,
                    set_character_id=?, confirmation_requested_at=?,
                    confirmation_delivery_status='PENDING',
                    confirmation_delivery_attempts=0,
                    confirmation_delivery_claimed_at=NULL,
                    confirmation_delivery_message_id=NULL,
                    confirmation_delivery_error=NULL,
                    version=version+1, updated_at=?
                WHERE id=? AND status='ATENDIMENTO_ASSUMIDO' AND claimed_by=? AND version=?
                """,
                (
                    responsible_id,
                    now,
                    character_id,
                    now,
                    now,
                    request_id,
                    responsible_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi alterada por outro atendimento.")
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_SET_PERFORMED', 'ATENDIMENTO_ASSUMIDO',
                          'AGUARDANDO_CONFIRMACAO', ?, ?, ?, ?)
                """,
                (
                    request_id,
                    int(request["guild_id"]),
                    responsible_id,
                    json.dumps({"set_character_id": character_id}, sort_keys=True),
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                """
                UPDATE members
                SET tag_status='AGUARDANDO_CONFIRMACAO', tag_set_by=?, updated_at=?
                WHERE id=?
                """,
                (responsible_id, now, int(request["member_id"])),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_SET_PERFORMED",
                actor_id=responsible_id,
                target_id=int(request["discord_id"]),
                before={"status": "ATENDIMENTO_ASSUMIDO"},
                after={
                    "tag_request_id": request_id,
                    "status": "AGUARDANDO_CONFIRMACAO",
                    "set_character_id": character_id,
                },
                connection=connection,
                correlation_id=correlation_id,
            )
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            updated = await cursor.fetchone()
            assert updated is not None
            return self._row(updated)

    async def complete_waiting_role_set(
        self,
        request_id: int,
        *,
        responsible_id: int,
        expected_version: int,
    ) -> dict[str, object]:
        """Finish a role-detected request directly by its assigned responsible."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            if str(request["intake_source"]) != "WAITING_ROLE_SCAN":
                raise ConflictError("Use o fluxo normal de confirmação para esta solicitação.")
            if str(request["status"]) == "CONCLUIDO":
                return self._row(request)
            if str(request["status"]) != "ATENDIMENTO_ASSUMIDO":
                raise ConflictError("Esta solicitação não está em atendimento.")
            if int(request["claimed_by"] or 0) != responsible_id:
                raise ConflictError("Somente o responsável que assumiu pode finalizar o set.")
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET status='CONCLUIDO', set_by=?, set_at=?,
                    set_character_id=character_id_snapshot,
                    confirmed_by=?, confirmed_at=?, version=version+1, updated_at=?
                WHERE id=? AND status='ATENDIMENTO_ASSUMIDO' AND claimed_by=?
                  AND version=? AND intake_source='WAITING_ROLE_SCAN'
                """,
                (
                    responsible_id,
                    now,
                    responsible_id,
                    now,
                    now,
                    request_id,
                    responsible_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi alterada. Atualize o painel.")
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            completed = await cursor.fetchone()
            assert completed is not None
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_WAITING_ROLE_SET_COMPLETED',
                          'ATENDIMENTO_ASSUMIDO', 'CONCLUIDO', ?, '{}', ?, ?)
                """,
                (request_id, int(request["guild_id"]), responsible_id, correlation_id, now),
            )
            await connection.execute(
                """
                UPDATE tag_role_sync_state SET requested_version=?, updated_at=?
                WHERE tag_request_id=?
                """,
                (int(completed["version"]), now, request_id),
            )
            await connection.execute(
                """
                UPDATE members
                SET tag_status='CONCLUIDO', tag_completed_at=?, tag_set_by=?,
                    tag_last_confirmed_at=?, updated_at=?
                WHERE id=?
                """,
                (now, responsible_id, now, now, int(request["member_id"])),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_WAITING_ROLE_SET_COMPLETED",
                actor_id=responsible_id,
                target_id=int(request["discord_id"]),
                before={"status": "ATENDIMENTO_ASSUMIDO"},
                after={
                    "tag_request_id": request_id,
                    "status": "CONCLUIDO",
                    "set_by": responsible_id,
                },
                connection=connection,
                correlation_id=correlation_id,
            )
            await self._enqueue_role_sync(
                connection, completed, requested_by=responsible_id, now=now
            )
            return self._row(completed)

    async def complete_from_set_role_observation(
        self, guild_id: int, discord_id: int
    ) -> dict[str, object] | None:
        """Close a waiting-role case when Discord already shows TAG SETADA.

        A manual Discord role change has no reliable actor identity. The
        transition preserves any claimed responsibility, clears unknown set
        and confirmation actors, records the observation as a system event,
        and makes the durable aggregate converge before the listener removes
        AGUARDANDO SET.
        """
        now = self.clock()
        active_statuses = tuple(sorted(self.ACTIVE_STATUSES))
        placeholders = ",".join("?" for _ in active_statuses)
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                f"""
                SELECT * FROM tag_requests
                WHERE guild_id=? AND discord_id=?
                  AND intake_source='WAITING_ROLE_SCAN'
                  AND status IN ({placeholders})
                ORDER BY requested_at DESC, id DESC LIMIT 1
                """,
                (guild_id, discord_id, *active_statuses),
            )
            request = await cursor.fetchone()
            if request is None:
                return None

            previous_status = str(request["status"])
            cursor = await connection.execute(
                f"""
                UPDATE tag_requests
                SET status='CONCLUIDO', set_by=NULL, set_at=?,
                    set_character_id=character_id_snapshot,
                    confirmed_by=NULL, confirmed_at=?,
                    version=version+1, updated_at=?
                WHERE id=? AND version=? AND intake_source='WAITING_ROLE_SCAN'
                  AND status IN ({placeholders})
                """,
                (
                    now,
                    now,
                    now,
                    int(request["id"]),
                    int(request["version"]),
                    *active_statuses,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A solicitação de tag mudou durante a reconciliação.")

            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (int(request["id"]),)
            )
            completed = await cursor.fetchone()
            assert completed is not None
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_SET_ROLE_OBSERVED', ?, 'CONCLUIDO', NULL, ?, ?, ?)
                """,
                (
                    int(request["id"]),
                    guild_id,
                    previous_status,
                    json.dumps(
                        {"source": "DISCORD_ROLE", "role_state": "TAG_SETADA"},
                        sort_keys=True,
                    ),
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                """
                UPDATE tag_role_sync_state SET requested_version=?, updated_at=?
                WHERE tag_request_id=?
                """,
                (int(completed["version"]), now, int(request["id"])),
            )
            await connection.execute(
                """
                UPDATE members
                SET tag_status='CONCLUIDO', tag_completed_at=?,
                    tag_set_by=?, tag_last_confirmed_at=?, updated_at=?
                WHERE id=?
                """,
                (
                    now,
                    completed["set_by"],
                    now,
                    now,
                    int(request["member_id"]),
                ),
            )
            await self.audit.record(
                guild_id,
                "TAG_SET_ROLE_OBSERVED",
                target_id=discord_id,
                before={"status": previous_status},
                after={
                    "tag_request_id": int(request["id"]),
                    "status": "CONCLUIDO",
                    "source": "DISCORD_ROLE",
                },
                connection=connection,
                correlation_id=correlation_id,
            )
            await self._enqueue_role_sync(connection, completed, requested_by=0, now=now)
            return self._row(completed)

    async def pending_confirmation_notifications(
        self, guild_id: int, *, limit: int = 50
    ) -> list[dict[str, object]]:
        """Return undelivered confirmation notices in deterministic order."""
        safe_limit = max(1, min(int(limit), 100))
        rows = await self.database.fetchall(
            """
            SELECT * FROM tag_requests
            WHERE guild_id=? AND status='AGUARDANDO_CONFIRMACAO'
              AND confirmation_delivery_status IN ('PENDING', 'FAILED')
            ORDER BY confirmation_requested_at, id LIMIT ?
            """,
            (guild_id, safe_limit),
        )
        return [self._row(row) for row in rows]

    async def pending_responsible_notifications(
        self, guild_id: int, *, limit: int = 50
    ) -> list[dict[str, object]]:
        """Return new/renewed queue entries awaiting the responsible role alert."""
        safe_limit = max(1, min(int(limit), 100))
        rows = await self.database.fetchall(
            """
            SELECT * FROM tag_requests
            WHERE guild_id=? AND status IN ('AGUARDANDO_SET', 'PENDENCIA')
              AND responsible_notification_status IN ('PENDING', 'FAILED')
            ORDER BY requested_at, id LIMIT ?
            """,
            (guild_id, safe_limit),
        )
        return [self._row(row) for row in rows]

    async def pending_assignment_notifications(
        self, guild_id: int, *, limit: int = 50
    ) -> list[dict[str, object]]:
        """Return durable notices that identify who assumed each request."""
        safe_limit = max(1, min(int(limit), 100))
        rows = await self.database.fetchall(
            """
            SELECT * FROM tag_requests
            WHERE guild_id=? AND status='ATENDIMENTO_ASSUMIDO'
              AND assignment_delivery_status IN ('PENDING', 'FAILED')
            ORDER BY claimed_at, id LIMIT ?
            """,
            (guild_id, safe_limit),
        )
        return [self._row(row) for row in rows]

    async def recover_assignment_notification_claims(
        self, *, stale_after_ms: int = 300_000
    ) -> int:
        if stale_after_ms <= 0:
            raise ValidationError("O tempo de recuperação precisa ser positivo.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET assignment_delivery_status='FAILED',
                    assignment_delivery_claimed_at=NULL,
                    assignment_delivery_error='Recuperado após reinício do bot',
                    updated_at=?
                WHERE status='ATENDIMENTO_ASSUMIDO'
                  AND assignment_delivery_status='PROCESSING'
                  AND assignment_delivery_claimed_at IS NOT NULL
                  AND assignment_delivery_claimed_at<=?
                """,
                (now, now - int(stale_after_ms)),
            )
            return cursor.rowcount

    async def claim_assignment_notification(
        self, request_id: int
    ) -> dict[str, object] | None:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET assignment_delivery_status='PROCESSING',
                    assignment_delivery_attempts=assignment_delivery_attempts+1,
                    assignment_delivery_claimed_at=?,
                    assignment_delivery_error=NULL, updated_at=?
                WHERE id=? AND status='ATENDIMENTO_ASSUMIDO'
                  AND assignment_delivery_status IN ('PENDING', 'FAILED')
                """,
                (now, now, request_id),
            )
            if cursor.rowcount != 1:
                return None
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            assert request is not None
            return self._row(request)

    async def mark_assignment_notification_delivered(
        self, request_id: int, *, delivery_message_id: int | None
    ) -> bool:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET assignment_delivery_status='DELIVERED',
                    assignment_delivery_claimed_at=NULL,
                    assignment_delivery_message_id=?,
                    assignment_delivery_error=NULL, updated_at=?
                WHERE id=? AND assignment_delivery_status='PROCESSING'
                """,
                (delivery_message_id, now, request_id),
            )
            return cursor.rowcount == 1

    async def mark_assignment_notification_failed(
        self, request_id: int, *, error: str
    ) -> bool:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET assignment_delivery_status='FAILED',
                    assignment_delivery_claimed_at=NULL,
                    assignment_delivery_error=?, updated_at=?
                WHERE id=? AND assignment_delivery_status='PROCESSING'
                """,
                (error[:500], now, request_id),
            )
            return cursor.rowcount == 1

    async def recover_responsible_notification_claims(
        self, *, stale_after_ms: int = 300_000
    ) -> int:
        """Return abandoned role alerts to the durable queue after a restart."""
        if stale_after_ms <= 0:
            raise ValidationError("O tempo de recuperação precisa ser positivo.")
        now = self.clock()
        cutoff = now - int(stale_after_ms)
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET responsible_notification_status='FAILED',
                    responsible_notification_claimed_at=NULL,
                    responsible_notification_error='Recuperado após reinício do bot',
                    updated_at=?
                WHERE status IN ('AGUARDANDO_SET', 'PENDENCIA')
                  AND responsible_notification_status='PROCESSING'
                  AND responsible_notification_claimed_at IS NOT NULL
                  AND responsible_notification_claimed_at<=?
                """,
                (now, cutoff),
            )
            return cursor.rowcount

    async def claim_responsible_notification(
        self, request_id: int
    ) -> dict[str, object] | None:
        """Claim exactly one role alert before the Discord send begins."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET responsible_notification_status='PROCESSING',
                    responsible_notification_attempts=responsible_notification_attempts+1,
                    responsible_notification_claimed_at=?,
                    responsible_notification_error=NULL, updated_at=?
                WHERE id=? AND status IN ('AGUARDANDO_SET', 'PENDENCIA')
                  AND responsible_notification_status IN ('PENDING', 'FAILED')
                """,
                (now, now, request_id),
            )
            if cursor.rowcount != 1:
                return None
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            assert request is not None
            return self._row(request)

    async def mark_responsible_notification_delivered(
        self, request_id: int, *, delivery_message_id: int | None
    ) -> bool:
        """Close a role-alert claim without changing the request state."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET responsible_notification_status='DELIVERED',
                    responsible_notification_claimed_at=NULL,
                    responsible_notification_message_id=?,
                    request_card_rendered_version=version,
                    responsible_notification_error=NULL, updated_at=?
                WHERE id=? AND responsible_notification_status='PROCESSING'
                """,
                (delivery_message_id, now, request_id),
            )
            return cursor.rowcount == 1

    async def mark_responsible_notification_failed(self, request_id: int, *, error: str) -> bool:
        """Make a transient Discord failure retryable without recreating the request."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET responsible_notification_status='FAILED',
                    responsible_notification_claimed_at=NULL,
                    responsible_notification_error=?, updated_at=?
                WHERE id=? AND responsible_notification_status='PROCESSING'
                """,
                (error[:500], now, request_id),
            )
            return cursor.rowcount == 1

    async def pending_terminal_notifications(
        self, guild_id: int, *, limit: int = 50
    ) -> list[dict[str, object]]:
        """Return final outcomes whose member notice has not reached Discord."""
        safe_limit = max(1, min(int(limit), 100))
        rows = await self.database.fetchall(
            """
            SELECT * FROM tag_requests
            WHERE guild_id=? AND status IN ('RECUSADO', 'CANCELADO', 'EXPIRADO')
              AND terminal_notification_status IN ('PENDING', 'FAILED')
            ORDER BY terminal_at, id LIMIT ?
            """,
            (guild_id, safe_limit),
        )
        return [self._row(row) for row in rows]

    async def recover_terminal_notification_claims(
        self, *, stale_after_ms: int = 300_000
    ) -> int:
        """Recover a final member notice abandoned during a process restart."""
        if stale_after_ms <= 0:
            raise ValidationError("O tempo de recuperação precisa ser positivo.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET terminal_notification_status='FAILED',
                    terminal_notification_claimed_at=NULL,
                    terminal_notification_error='Recuperado após reinício do bot',
                    updated_at=?
                WHERE status IN ('RECUSADO', 'CANCELADO', 'EXPIRADO')
                  AND terminal_notification_status='PROCESSING'
                  AND terminal_notification_claimed_at IS NOT NULL
                  AND terminal_notification_claimed_at<=?
                """,
                (now, now - int(stale_after_ms)),
            )
            return cursor.rowcount

    async def claim_terminal_notification(self, request_id: int) -> dict[str, object] | None:
        """Claim a terminal member notification exactly once before I/O."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET terminal_notification_status='PROCESSING',
                    terminal_notification_attempts=terminal_notification_attempts+1,
                    terminal_notification_claimed_at=?, terminal_notification_error=NULL,
                    updated_at=?
                WHERE id=? AND status IN ('RECUSADO', 'CANCELADO', 'EXPIRADO')
                  AND terminal_notification_status IN ('PENDING', 'FAILED')
                """,
                (now, now, request_id),
            )
            if cursor.rowcount != 1:
                return None
            cursor = await connection.execute("SELECT * FROM tag_requests WHERE id=?", (request_id,))
            request = await cursor.fetchone()
            assert request is not None
            return self._row(request)

    async def mark_terminal_notification_delivered(
        self, request_id: int, *, delivery_message_id: int | None
    ) -> bool:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET terminal_notification_status='DELIVERED',
                    terminal_notification_claimed_at=NULL,
                    terminal_notification_message_id=?, terminal_notification_error=NULL,
                    updated_at=?
                WHERE id=? AND terminal_notification_status='PROCESSING'
                """,
                (delivery_message_id, now, request_id),
            )
            return cursor.rowcount == 1

    async def mark_terminal_notification_failed(self, request_id: int, *, error: str) -> bool:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET terminal_notification_status='FAILED',
                    terminal_notification_claimed_at=NULL,
                    terminal_notification_error=?, updated_at=?
                WHERE id=? AND terminal_notification_status='PROCESSING'
                """,
                (error[:500], now, request_id),
            )
            return cursor.rowcount == 1

    async def awaiting_confirmations(
        self, guild_id: int, *, limit: int = 100
    ) -> list[dict[str, object]]:
        """All live confirmation cards, including notices already delivered."""
        safe_limit = max(1, min(int(limit), 100))
        rows = await self.database.fetchall(
            """
            SELECT * FROM tag_requests
            WHERE guild_id=? AND status='AGUARDANDO_CONFIRMACAO'
            ORDER BY confirmation_requested_at, id LIMIT ?
            """,
            (guild_id, safe_limit),
        )
        return [self._row(row) for row in rows]

    async def reserve_member_call(
        self,
        request_id: int,
        *,
        responsible_id: int,
        expected_version: int,
        cooldown_ms: int,
    ) -> dict[str, object]:
        """Reserve one non-spam call to the DP before attempting a DM."""
        if cooldown_ms <= 0:
            raise ValidationError("O cooldown de chamada precisa ser positivo.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            status = str(request["status"])
            if status not in {"AGUARDANDO_SET", "ATENDIMENTO_ASSUMIDO", "PENDENCIA"}:
                raise ConflictError("Esta solicitação não pode ser chamada para a DP agora.")
            if (
                status == "ATENDIMENTO_ASSUMIDO"
                and int(request["claimed_by"] or 0) != responsible_id
            ):
                raise PermissionDenied(
                    "Somente o responsável atual pode chamar o membro para a DP."
                )
            last_call_at = request["last_call_at"]
            if last_call_at is not None and now - int(last_call_at) < cooldown_ms:
                remaining_ms = cooldown_ms - (now - int(last_call_at))
                raise ConflictError(
                    f"Por favor, aguarde {max(1, (remaining_ms + 59_999) // 60_000)} min antes de chamar novamente."
                )
            cursor = await connection.execute(
                """
                UPDATE tag_requests SET last_call_at=?, last_call_by=?, updated_at=?
                WHERE id=? AND version=? AND (
                    last_call_at IS NULL OR last_call_at<=?
                )
                """,
                (now, responsible_id, now, request_id, expected_version, now - cooldown_ms),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A chamada já foi reservada por outro responsável.")
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            reserved = await cursor.fetchone()
            assert reserved is not None
            return self._row(reserved)

    async def release_member_call(
        self, request_id: int, *, responsible_id: int, error: str
    ) -> bool:
        """Free a reservation only when delivery failed before a real call."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request or int(request["last_call_by"] or 0) != responsible_id:
                return False
            cursor = await connection.execute(
                """
                UPDATE tag_requests SET last_call_at=NULL, last_call_by=NULL, updated_at=?
                WHERE id=? AND last_call_by=?
                """,
                (now, request_id, responsible_id),
            )
            if cursor.rowcount != 1:
                return False
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status, next_status,
                    actor_id, reason, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_MEMBER_CALL_FAILED', ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    request_id,
                    int(request["guild_id"]),
                    str(request["status"]),
                    str(request["status"]),
                    responsible_id,
                    error[:500],
                    correlation_id,
                    now,
                ),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_MEMBER_CALL_FAILED",
                actor_id=responsible_id,
                target_id=int(request["discord_id"]),
                after={"tag_request_id": request_id},
                reason=error[:500],
                connection=connection,
                correlation_id=correlation_id,
            )
            return True

    async def record_member_called(
        self, request_id: int, *, responsible_id: int
    ) -> dict[str, object]:
        """Append exactly one successful DP-call event for the reservation."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            if int(request["last_call_by"] or 0) != responsible_id or request["last_call_at"] is None:
                raise ConflictError("A chamada não possui uma reserva válida.")
            correlation_id = f"tag-member-call:{request_id}:{int(request['last_call_at'])}"
            cursor = await connection.execute(
                "SELECT id FROM tag_request_events WHERE correlation_id=?", (correlation_id,)
            )
            if await cursor.fetchone():
                return self._row(request)
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status, next_status,
                    actor_id, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_MEMBER_CALLED', ?, ?, ?, '{}', ?, ?)
                """,
                (
                    request_id,
                    int(request["guild_id"]),
                    str(request["status"]),
                    str(request["status"]),
                    responsible_id,
                    correlation_id,
                    now,
                ),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_MEMBER_CALLED",
                actor_id=responsible_id,
                target_id=int(request["discord_id"]),
                after={"tag_request_id": request_id, "status": str(request["status"])},
                connection=connection,
                correlation_id=correlation_id,
            )
            return self._row(request)

    async def recover_confirmation_notification_claims(
        self, *, stale_after_ms: int = 300_000
    ) -> int:
        """Make a notification abandoned by a terminated worker retryable."""
        if stale_after_ms <= 0:
            raise ValidationError("O tempo de recuperação precisa ser positivo.")
        cutoff = self.clock() - int(stale_after_ms)
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET confirmation_delivery_status='FAILED',
                    confirmation_delivery_claimed_at=NULL,
                    confirmation_delivery_error='Recuperado após reinício do bot',
                    updated_at=?
                WHERE status='AGUARDANDO_CONFIRMACAO'
                  AND confirmation_delivery_status='PROCESSING'
                  AND confirmation_delivery_claimed_at IS NOT NULL
                  AND confirmation_delivery_claimed_at<=?
                """,
                (self.clock(), cutoff),
            )
            return cursor.rowcount

    async def claim_confirmation_notification(
        self, request_id: int
    ) -> dict[str, object] | None:
        """Claim one member notice atomically before Discord I/O begins."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET confirmation_delivery_status='PROCESSING',
                    confirmation_delivery_attempts=confirmation_delivery_attempts+1,
                    confirmation_delivery_claimed_at=?, confirmation_delivery_error=NULL,
                    updated_at=?
                WHERE id=? AND status='AGUARDANDO_CONFIRMACAO'
                  AND confirmation_delivery_status IN ('PENDING', 'FAILED')
                """,
                (now, now, request_id),
            )
            if cursor.rowcount != 1:
                return None
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            assert request is not None
            return self._row(request)

    async def mark_confirmation_notification_delivered(
        self, request_id: int, *, delivery_message_id: int | None
    ) -> bool:
        """Finish a claimed notice without altering the tag state itself."""
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET confirmation_delivery_status='DELIVERED',
                    confirmation_delivery_message_id=?,
                    confirmation_delivery_claimed_at=NULL,
                    confirmation_delivery_error=NULL, updated_at=?
                WHERE id=? AND status='AGUARDANDO_CONFIRMACAO'
                  AND confirmation_delivery_status='PROCESSING'
                """,
                (delivery_message_id, self.clock(), request_id),
            )
            return cursor.rowcount == 1

    async def mark_confirmation_notification_failed(
        self, request_id: int, *, error: str
    ) -> bool:
        """Release a failed delivery for retry while preserving its attempts."""
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET confirmation_delivery_status='FAILED',
                    confirmation_delivery_claimed_at=NULL,
                    confirmation_delivery_error=?, updated_at=?
                WHERE id=? AND status='AGUARDANDO_CONFIRMACAO'
                  AND confirmation_delivery_status='PROCESSING'
                """,
                (error[:500], self.clock(), request_id),
            )
            return cursor.rowcount == 1

    async def release_request(
        self,
        request_id: int,
        *,
        responsible_id: int,
        expected_version: int,
        reason: str,
    ) -> dict[str, object]:
        """Return an assigned request to the queue without losing its timeline."""
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Informe o motivo para liberar a solicitação.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            if str(request["status"]) != "ATENDIMENTO_ASSUMIDO":
                raise ConflictError("Esta solicitação não está em atendimento.")
            if int(request["claimed_by"] or 0) != responsible_id:
                raise PermissionDenied("Somente o responsável atual pode liberar a solicitação.")
            released_status = (
                "PENDENCIA"
                if str(request["request_origin"] or "SET_REQUEST")
                == "EXISTING_DECLARATION"
                else "AGUARDANDO_SET"
            )
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET status=?, claimed_by=NULL, claimed_at=NULL,
                    version=version+1, updated_at=?
                WHERE id=? AND status='ATENDIMENTO_ASSUMIDO'
                  AND claimed_by=? AND version=?
                """,
                (released_status, now, request_id, responsible_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi alterada. Atualize o painel.")
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, reason, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_REQUEST_RELEASED', 'ATENDIMENTO_ASSUMIDO',
                          ?, ?, ?, '{}', ?, ?)
                """,
                (
                    request_id,
                    int(request["guild_id"]),
                    released_status,
                    responsible_id,
                    normalized_reason,
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                "UPDATE members SET tag_status=?, updated_at=? WHERE id=?",
                (released_status, now, int(request["member_id"])),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_REQUEST_RELEASED",
                actor_id=responsible_id,
                target_id=int(request["discord_id"]),
                before={"status": "ATENDIMENTO_ASSUMIDO"},
                after={"tag_request_id": request_id, "status": released_status},
                reason=normalized_reason,
                connection=connection,
                correlation_id=correlation_id,
            )
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            released = await cursor.fetchone()
            assert released is not None
            return self._row(released)

    async def correct_character_id(
        self,
        request_id: int,
        *,
        actor_id: int,
        expected_version: int,
        character_id: str,
        reason: str,
    ) -> dict[str, object]:
        """Apply an explicitly audited MTA-ID correction to identity and request.

        A correction after someone started the set cannot silently keep the
        former service state: it becomes a pendency and drops the stale
        assignment/set data so a responsible person must review it again.
        """
        normalized_id = normalize_bgr_id(character_id)
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Informe o motivo da correção do ID.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            previous_status = str(request["status"])
            if previous_status not in self.ACTIVE_STATUSES:
                raise ConflictError("Não é possível corrigir uma solicitação já encerrada.")
            previous_id = str(request["character_id_snapshot"])
            if previous_id == normalized_id:
                return self._row(request)

            conflict = await self._active_character_id_conflict(
                connection,
                guild_id=int(request["guild_id"]),
                member_id=int(request["member_id"]),
                character_id=normalized_id,
            )
            if conflict:
                raise ValidationError(
                    "O ID MTA informado já está vinculado a outro membro ativo. "
                    "Revise a identidade existente antes de concluir a correção."
                )

            needs_review = previous_status not in {"AGUARDANDO_SET", "PENDENCIA"}
            next_status = "PENDENCIA" if needs_review else previous_status
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET character_id_snapshot=?, status=?,
                    claimed_by=CASE WHEN ? THEN NULL ELSE claimed_by END,
                    claimed_at=CASE WHEN ? THEN NULL ELSE claimed_at END,
                    set_by=CASE WHEN ? THEN NULL ELSE set_by END,
                    set_at=CASE WHEN ? THEN NULL ELSE set_at END,
                    set_character_id=CASE WHEN ? THEN NULL ELSE set_character_id END,
                    confirmation_requested_at=CASE WHEN ? THEN NULL ELSE confirmation_requested_at END,
                    identity_conflict_json=?, version=version+1, updated_at=?
                WHERE id=? AND version=?
                """,
                (
                    normalized_id,
                    next_status,
                    int(needs_review),
                    int(needs_review),
                    int(needs_review),
                    int(needs_review),
                    int(needs_review),
                    int(needs_review),
                    json.dumps(
                        {
                            "previous_character_id": previous_id,
                            "new_character_id": normalized_id,
                            "corrected_by": actor_id,
                            "reason": normalized_reason,
                            "corrected_at": now,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                    request_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi alterada. Atualize o painel.")
            await connection.execute(
                "UPDATE members SET character_id=?, updated_at=? WHERE id=?",
                (normalized_id, now, int(request["member_id"])),
            )
            await connection.execute(
                "UPDATE members SET tag_status=?, updated_at=? WHERE id=?",
                (next_status, now, int(request["member_id"])),
            )
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            updated = await cursor.fetchone()
            assert updated is not None
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, reason, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_ID_CHANGED', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    int(request["guild_id"]),
                    previous_status,
                    next_status,
                    actor_id,
                    normalized_reason,
                    json.dumps(
                        {
                            "previous_character_id": previous_id,
                            "new_character_id": normalized_id,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                """
                UPDATE tag_role_sync_state SET requested_version=?, updated_at=?
                WHERE tag_request_id=?
                """,
                (int(updated["version"]), now, request_id),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_ID_CHANGED",
                actor_id=actor_id,
                target_id=int(request["discord_id"]),
                before={"character_id": previous_id, "status": previous_status},
                after={
                    "tag_request_id": request_id,
                    "character_id": normalized_id,
                    "status": next_status,
                },
                reason=normalized_reason,
                connection=connection,
                correlation_id=correlation_id,
            )
            await self._enqueue_role_sync(
                connection, updated, requested_by=actor_id, now=now
            )
            return self._row(updated)

    async def reject_request(
        self,
        request_id: int,
        *,
        actor_id: int,
        expected_version: int,
        reason: str,
    ) -> dict[str, object]:
        return await self._terminalize(
            request_id,
            actor_id=actor_id,
            expected_version=expected_version,
            reason=reason,
            status="RECUSADO",
            event_type="TAG_REQUEST_REJECTED",
        )

    async def archive_departed_member(
        self, guild_id: int, discord_id: int
    ) -> dict[str, object] | None:
        """Archive the member's active request after a Discord departure."""
        active_statuses = tuple(sorted(self.ACTIVE_STATUSES))
        placeholders = ",".join("?" for _ in active_statuses)
        request = await self.database.fetchone(
            f"""
            SELECT * FROM tag_requests
            WHERE guild_id=? AND discord_id=? AND status IN ({placeholders})
            ORDER BY requested_at DESC, id DESC LIMIT 1
            """,
            (guild_id, discord_id, *active_statuses),
        )
        if not request:
            return None
        return await self._terminalize(
            int(request["id"]),
            actor_id=0,
            expected_version=int(request["version"]),
            reason="Membro saiu do servidor.",
            status="CANCELADO",
            event_type="TAG_REQUEST_MEMBER_LEFT",
            notify_member=False,
            enqueue_role_sync=False,
        )

    async def cancel_request(
        self,
        request_id: int,
        *,
        actor_id: int,
        expected_version: int,
        reason: str,
    ) -> dict[str, object]:
        return await self._terminalize(
            request_id,
            actor_id=actor_id,
            expected_version=expected_version,
            reason=reason,
            status="CANCELADO",
            event_type="TAG_REQUEST_CANCELLED",
        )

    async def expire_overdue(
        self,
        guild_id: int,
        *,
        max_wait_ms: int,
        actor_id: int = 0,
    ) -> list[int]:
        """Expire only requests that have never been picked up.

        A claim is an explicit human promise to handle a request, so a worker
        must never expire a card already assigned to someone.  Each terminal
        transition still goes through the same compare-and-set path used by
        manual decisions, making a race with a late claim harmless.
        """
        if max_wait_ms <= 0:
            raise ValidationError("O prazo de expiração precisa ser positivo.")
        cutoff = self.clock() - int(max_wait_ms)
        rows = await self.database.fetchall(
            """
            SELECT id, version FROM tag_requests
            WHERE guild_id=? AND status='AGUARDANDO_SET' AND requested_at<=?
            ORDER BY requested_at, id
            """,
            (guild_id, cutoff),
        )
        expired_ids: list[int] = []
        for row in rows:
            request_id = int(row["id"])
            try:
                expired = await self._terminalize(
                    request_id,
                    actor_id=actor_id,
                    expected_version=int(row["version"]),
                    reason="Prazo máximo de espera expirado.",
                    status="EXPIRADO",
                    event_type="TAG_REQUEST_EXPIRED",
                )
            except ConflictError:
                # A responsible user claimed or changed it after this worker
                # took its snapshot.  The newer state is authoritative.
                continue
            if str(expired["status"]) == "EXPIRADO":
                expired_ids.append(request_id)
        return expired_ids

    async def _terminalize(
        self,
        request_id: int,
        *,
        actor_id: int,
        expected_version: int,
        reason: str,
        status: str,
        event_type: str,
        notify_member: bool = True,
        enqueue_role_sync: bool = True,
    ) -> dict[str, object]:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Informe o motivo da decisão.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            if str(request["status"]) == status:
                return self._row(request)
            if str(request["status"]) not in self.ACTIVE_STATUSES:
                raise ConflictError("Esta solicitação já possui uma decisão final.")
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET status=?, terminal_by=?, terminal_at=?, terminal_reason=?,
                    terminal_notification_status=?,
                    terminal_notification_attempts=0,
                    terminal_notification_claimed_at=NULL,
                    terminal_notification_message_id=NULL,
                    terminal_notification_error=NULL,
                    claimed_by=NULL, claimed_at=NULL, version=version+1, updated_at=?
                WHERE id=? AND version=?
                """,
                (
                    status,
                    actor_id,
                    now,
                    normalized_reason,
                    "PENDING" if notify_member else "DELIVERED",
                    now,
                    request_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi alterada. Atualize o painel.")
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            terminal = await cursor.fetchone()
            assert terminal is not None
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, reason, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    request_id,
                    int(request["guild_id"]),
                    event_type,
                    str(request["status"]),
                    status,
                    actor_id,
                    normalized_reason,
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                """
                UPDATE tag_role_sync_state
                SET requested_version=?, updated_at=?
                WHERE tag_request_id=?
                """,
                (int(terminal["version"]), now, request_id),
            )
            await connection.execute(
                "UPDATE members SET tag_status=?, updated_at=? WHERE id=?",
                (status, now, int(request["member_id"])),
            )
            await self.audit.record(
                int(request["guild_id"]),
                event_type,
                actor_id=actor_id,
                target_id=int(request["discord_id"]),
                before={"status": str(request["status"])},
                after={"tag_request_id": request_id, "status": status},
                reason=normalized_reason,
                connection=connection,
                correlation_id=correlation_id,
            )
            if enqueue_role_sync:
                await self._enqueue_role_sync(
                    connection, terminal, requested_by=actor_id, now=now
                )
            return self._row(terminal)

    async def confirm_tag(
        self, request_id: int, *, discord_id: int, expected_version: int
    ) -> dict[str, object]:
        """Let only the request owner complete the tag after checking it in MTA."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            if int(request["discord_id"]) != discord_id:
                raise ConflictError("Somente o membro da solicitação pode confirmar a tag.")
            if str(request["status"]) == "CONCLUIDO":
                return self._row(request)
            if str(request["status"]) != "AGUARDANDO_CONFIRMACAO":
                raise ConflictError("A tag ainda não está aguardando sua confirmação.")
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET status='CONCLUIDO', confirmed_by=?, confirmed_at=?,
                    version=version+1, updated_at=?
                WHERE id=? AND status='AGUARDANDO_CONFIRMACAO'
                  AND discord_id=? AND version=?
                """,
                (discord_id, now, now, request_id, discord_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi alterada. Atualize o painel.")
            cursor = await connection.execute(
                "SELECT version FROM tag_requests WHERE id=?", (request_id,)
            )
            current = await cursor.fetchone()
            assert current is not None
            new_version = int(current["version"])
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_CONFIRMED', 'AGUARDANDO_CONFIRMACAO',
                          'CONCLUIDO', ?, '{}', ?, ?)
                """,
                (request_id, int(request["guild_id"]), discord_id, correlation_id, now),
            )
            await connection.execute(
                """
                UPDATE tag_role_sync_state
                SET requested_version=?, updated_at=?
                WHERE tag_request_id=?
                """,
                (new_version, now, request_id),
            )
            await connection.execute(
                """
                UPDATE members
                SET tag_status='CONCLUIDO', tag_completed_at=?, tag_set_by=?,
                    tag_last_confirmed_at=?, updated_at=?
                WHERE id=?
                """,
                (
                    now,
                    int(request["set_by"]),
                    now,
                    now,
                    int(request["member_id"]),
                ),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_CONFIRMED",
                actor_id=discord_id,
                target_id=discord_id,
                before={"status": "AGUARDANDO_CONFIRMACAO"},
                after={"tag_request_id": request_id, "status": "CONCLUIDO"},
                connection=connection,
                correlation_id=correlation_id,
            )
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            completed = await cursor.fetchone()
            assert completed is not None
            await self._enqueue_role_sync(
                connection, completed, requested_by=discord_id, now=now
            )
            return self._row(completed)

    async def report_tag_not_received(
        self,
        request_id: int,
        *,
        discord_id: int,
        expected_version: int,
        reason: str,
    ) -> dict[str, object]:
        """Return a set to the queue when its owner reports a real problem."""
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Explique o problema encontrado com a tag.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            if int(request["discord_id"]) != discord_id:
                raise PermissionDenied("Somente o membro da solicitação pode informar esta pendência.")
            if str(request["status"]) == "PENDENCIA":
                return self._row(request)
            if str(request["status"]) != "AGUARDANDO_CONFIRMACAO":
                raise ConflictError("Esta solicitação não está aguardando confirmação.")
            previous_responsible = request["claimed_by"]
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET status='PENDENCIA', claimed_by=NULL, claimed_at=NULL,
                    responsible_notification_status=CASE
                        WHEN responsible_notification_message_id IS NULL
                        THEN 'PENDING' ELSE 'DELIVERED' END,
                    responsible_notification_attempts=CASE
                        WHEN responsible_notification_message_id IS NULL
                        THEN 0 ELSE responsible_notification_attempts END,
                    responsible_notification_claimed_at=NULL,
                    responsible_notification_error=NULL,
                    version=version+1, updated_at=?
                WHERE id=? AND status='AGUARDANDO_CONFIRMACAO'
                  AND discord_id=? AND version=?
                """,
                (now, request_id, discord_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi alterada. Atualize o painel.")
            cursor = await connection.execute(
                "SELECT version FROM tag_requests WHERE id=?", (request_id,)
            )
            current = await cursor.fetchone()
            assert current is not None
            new_version = int(current["version"])
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, reason, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_NOT_RECEIVED', 'AGUARDANDO_CONFIRMACAO',
                          'PENDENCIA', ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    int(request["guild_id"]),
                    discord_id,
                    normalized_reason,
                    json.dumps(
                        {"previous_responsible_id": previous_responsible},
                        sort_keys=True,
                    ),
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                """
                UPDATE tag_role_sync_state
                SET requested_version=?, updated_at=?
                WHERE tag_request_id=?
                """,
                (new_version, now, request_id),
            )
            await connection.execute(
                "UPDATE members SET tag_status='PENDENCIA', updated_at=? WHERE id=?",
                (now, int(request["member_id"])),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_NOT_RECEIVED",
                actor_id=discord_id,
                target_id=discord_id,
                before={"status": "AGUARDANDO_CONFIRMACAO"},
                after={"tag_request_id": request_id, "status": "PENDENCIA"},
                reason=normalized_reason,
                connection=connection,
                correlation_id=correlation_id,
            )
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            pending = await cursor.fetchone()
            assert pending is not None
            return self._row(pending)

    async def report_operational_pendency(
        self,
        request_id: int,
        *,
        actor_id: int,
        expected_version: int,
        reason: str,
    ) -> dict[str, object]:
        """Return an operationally blocked request to the durable pending queue."""
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Informe o motivo da pendência.")
        now = self.clock()
        allowed_statuses = {"AGUARDANDO_SET", "ATENDIMENTO_ASSUMIDO", "AGUARDANDO_CONFIRMACAO"}
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tag_requests WHERE id=?", (request_id,)
            )
            request = await cursor.fetchone()
            if not request:
                raise NotFoundError("Solicitação de tag não encontrada.")
            previous_status = str(request["status"])
            if previous_status == "PENDENCIA":
                return self._row(request)
            if previous_status not in allowed_statuses:
                raise ConflictError("Esta solicitação não pode receber uma pendência agora.")
            previous_responsible = request["claimed_by"]
            cursor = await connection.execute(
                """
                UPDATE tag_requests
                SET status='PENDENCIA', claimed_by=NULL, claimed_at=NULL,
                    responsible_notification_status=CASE
                        WHEN responsible_notification_message_id IS NULL
                        THEN 'PENDING' ELSE 'DELIVERED' END,
                    responsible_notification_attempts=CASE
                        WHEN responsible_notification_message_id IS NULL
                        THEN 0 ELSE responsible_notification_attempts END,
                    responsible_notification_claimed_at=NULL,
                    responsible_notification_error=NULL,
                    version=version+1, updated_at=?
                WHERE id=? AND version=? AND status IN (
                    'AGUARDANDO_SET','ATENDIMENTO_ASSUMIDO','AGUARDANDO_CONFIRMACAO'
                )
                """,
                (now, request_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi alterada. Atualize o painel.")
            cursor = await connection.execute("SELECT * FROM tag_requests WHERE id=?", (request_id,))
            pending = await cursor.fetchone()
            assert pending is not None
            correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO tag_request_events(
                    tag_request_id, guild_id, event_type, previous_status,
                    next_status, actor_id, reason, metadata_json, correlation_id, occurred_at
                ) VALUES (?, ?, 'TAG_OPERATIONAL_PENDENCY', ?, 'PENDENCIA', ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    int(request["guild_id"]),
                    previous_status,
                    actor_id,
                    normalized_reason,
                    json.dumps({"previous_responsible_id": previous_responsible}, sort_keys=True),
                    correlation_id,
                    now,
                ),
            )
            await connection.execute(
                "UPDATE tag_role_sync_state SET requested_version=?, updated_at=? WHERE tag_request_id=?",
                (int(pending["version"]), now, request_id),
            )
            await connection.execute(
                "UPDATE members SET tag_status='PENDENCIA', updated_at=? WHERE id=?",
                (now, int(request["member_id"])),
            )
            await self.audit.record(
                int(request["guild_id"]),
                "TAG_OPERATIONAL_PENDENCY",
                actor_id=actor_id,
                target_id=int(request["discord_id"]),
                before={"status": previous_status},
                after={"tag_request_id": request_id, "status": "PENDENCIA"},
                reason=normalized_reason,
                connection=connection,
                correlation_id=correlation_id,
            )
            await self._enqueue_role_sync(connection, pending, requested_by=actor_id, now=now)
            return self._row(pending)
