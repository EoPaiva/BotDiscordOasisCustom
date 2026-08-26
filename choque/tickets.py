from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence

import aiosqlite

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .members import MemberService
from .settings import SettingsService
from .time_utils import utc_now_ms

TICKET_TYPES = {"CANDIDACY", "TRANSFER", "REPORT", "OTHER"}
TICKET_LABELS = {
    "CANDIDACY": "Candidatura",
    "TRANSFER": "Transferência",
    "REPORT": "Denúncia",
    "OTHER": "Outro assunto",
}
TICKET_PRIORITIES = {"LOW", "NORMAL", "HIGH", "URGENT"}
TICKET_PRIORITY_LABELS = {
    "LOW": "Baixa",
    "NORMAL": "Normal",
    "HIGH": "Alta",
    "URGENT": "Urgente",
}

_TRANSCRIPT_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization|token|secret|password|senha|api[_ -]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:mfa\.[\w-]{20,}|[\w-]{20,}\.[\w-]{6,}\.[\w-]{20,})\b"),
    re.compile(r"\b(?:sk|rk|pk)_[A-Za-z0-9_-]{16,}\b"),
)


def sanitize_transcript_content(value: str) -> str:
    """Minimize a transcript and redact common credential formats."""
    normalized = value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    for pattern in _TRANSCRIPT_SECRET_PATTERNS:
        normalized = pattern.sub("[SEGREDO REDIGIDO]", normalized)
    return normalized[:4000]


def build_minimized_transcript(
    ticket_id: int,
    messages: Sequence[Mapping[str, object]],
) -> str:
    lines = [f"CHOQUE - BGR | TRANSCRICAO MINIMIZADA | TICKET #{ticket_id}"]
    for message in messages:
        content = sanitize_transcript_content(str(message.get("content") or "")).strip()
        attachment_count = max(0, int(message.get("attachment_count") or 0))
        if not content and not attachment_count:
            continue
        created_at = int(message.get("created_at") or 0)
        author_id = int(message.get("author_id") or 0)
        suffix = f" [anexos:{attachment_count}]" if attachment_count else ""
        lines.append(f"[{created_at}] user:{author_id} {content}{suffix}".rstrip())
    return "\n".join(lines) + "\n"


class TicketService:
    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
        members: MemberService,
        *,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit
        self.members = members
        self.clock = clock

    async def _event(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        ticket_id: int,
        event_type: str,
        *,
        actor_id: int | None,
        metadata: Mapping[str, object] | None = None,
        created_at: int | None = None,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO ticket_operation_events(
                guild_id, ticket_id, event_type, actor_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                ticket_id,
                event_type,
                actor_id,
                json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                created_at if created_at is not None else self.clock(),
            ),
        )

    async def _transfer_event(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        transfer_case_id: int,
        event_type: str,
        *,
        actor_id: int | None,
        metadata: Mapping[str, object] | None = None,
        created_at: int | None = None,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO transfer_case_events(
                guild_id, transfer_case_id, event_type, actor_id,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                transfer_case_id,
                event_type,
                actor_id,
                json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                created_at if created_at is not None else self.clock(),
            ),
        )

    @staticmethod
    def _validate_payload(ticket_type: str, payload: dict[str, object]) -> None:
        required = {
            "CANDIDACY": ("mta_nick", "motivation"),
            "TRANSFER": ("mta_nick", "origin_organization", "origin_rank", "motivation"),
            "REPORT": ("details",),
            "OTHER": ("subject", "details"),
        }[ticket_type]
        missing = [key for key in required if not str(payload.get(key) or "").strip()]
        if missing:
            raise ValidationError("Preencha todos os campos obrigatórios do atendimento.")

    async def create(
        self,
        guild_id: int,
        discord_id: int,
        ticket_type: str,
        payload: dict[str, object],
        *,
        subject_discord_id: int | None = None,
    ) -> int:
        normalized = ticket_type.upper()
        if normalized not in TICKET_TYPES:
            raise ValidationError("Tipo de atendimento inválido.")
        self._validate_payload(normalized, payload)
        if normalized == "REPORT" and subject_discord_id == discord_id:
            raise ValidationError("Selecione outra pessoa como alvo da denúncia.")
        now = self.clock()
        async with self.database.transaction() as connection:
            if normalized == "CANDIDACY":
                cursor = await connection.execute(
                    "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
                    (guild_id, discord_id),
                )
                if await cursor.fetchone():
                    raise ConflictError("Você já faz parte do efetivo.")
                cursor = await connection.execute(
                    """
                    SELECT id FROM member_applications
                    WHERE guild_id=? AND discord_id=? AND status='PENDING'
                    """,
                    (guild_id, discord_id),
                )
                if await cursor.fetchone():
                    raise ConflictError("Você já possui um cadastro aguardando análise.")
            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO service_tickets(
                        guild_id, discord_id, ticket_type, subject_discord_id,
                        payload_json, submitted_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        discord_id,
                        normalized,
                        subject_discord_id,
                        json.dumps(payload, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError(
                    f"Você já possui {TICKET_LABELS[normalized].lower()} pendente."
                ) from exc
            ticket_id = int(cursor.lastrowid)
            if normalized == "TRANSFER":
                protocol = f"TRF-{guild_id}-{ticket_id:06d}"
                transfer_cursor = await connection.execute(
                    """
                    INSERT INTO transfer_cases(
                        guild_id, ticket_id, protocol, requester_id,
                        request_snapshot_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        ticket_id,
                        protocol,
                        discord_id,
                        json.dumps(payload, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                transfer_case_id = int(transfer_cursor.lastrowid)
                await self._transfer_event(
                    connection,
                    guild_id,
                    transfer_case_id,
                    "SUBMITTED",
                    actor_id=discord_id,
                    metadata={"protocol": protocol, "ticket_id": ticket_id},
                    created_at=now,
                )
                await self.audit.record(
                    guild_id,
                    "TRANSFER_SUBMITTED",
                    actor_id=discord_id,
                    target_id=discord_id,
                    after={
                        "protocol": protocol,
                        "ticket_id": ticket_id,
                        "transfer_case_id": transfer_case_id,
                    },
                    connection=connection,
                )
            await self.audit.record(
                guild_id,
                "SERVICE_TICKET_SUBMITTED",
                actor_id=discord_id,
                target_id=discord_id,
                after={"ticket_id": ticket_id, "ticket_type": normalized},
                connection=connection,
            )
        return ticket_id

    async def get(self, guild_id: int, ticket_id: int):
        row = await self.database.fetchone(
            """
            SELECT ticket.*, transfer.protocol AS transfer_protocol,
                   transfer.status AS transfer_case_status,
                   transfer.approved_rank_id,
                   rank.name AS approved_rank_name
            FROM service_tickets AS ticket
            LEFT JOIN transfer_cases AS transfer
              ON transfer.guild_id=ticket.guild_id AND transfer.ticket_id=ticket.id
            LEFT JOIN ranks AS rank ON rank.id=transfer.approved_rank_id
            WHERE ticket.guild_id=? AND ticket.id=?
            """,
            (guild_id, ticket_id),
        )
        if not row:
            raise NotFoundError("Atendimento não encontrado.")
        return row

    async def room_for_ticket(self, guild_id: int, ticket_id: int):
        return await self.database.fetchone(
            "SELECT * FROM ticket_rooms WHERE guild_id=? AND ticket_id=?",
            (guild_id, ticket_id),
        )

    async def room_by_channel(self, guild_id: int, channel_id: int):
        return await self.database.fetchone(
            "SELECT * FROM ticket_rooms WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )

    async def bind_room(
        self,
        guild_id: int,
        ticket_id: int,
        channel_id: int,
        *,
        control_message_id: int | None = None,
        active_category_id: int | None = None,
        archive_category_id: int | None = None,
        responsible_role_id: int | None = None,
    ):
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT discord_id, status FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            if ticket["status"] not in {"PENDING", "IN_REVIEW"}:
                raise ConflictError("Este atendimento já foi encerrado.")
            try:
                await connection.execute(
                    """
                    INSERT INTO ticket_rooms(
                        guild_id, ticket_id, requester_id, channel_id,
                        control_message_id, status, created_at, active_category_id,
                        archive_category_id, responsible_role_id
                    ) VALUES (?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)
                    ON CONFLICT(guild_id, ticket_id) DO UPDATE SET
                        channel_id=excluded.channel_id,
                        control_message_id=COALESCE(
                            excluded.control_message_id, ticket_rooms.control_message_id
                        ),
                        status='OPEN',
                        closed_by=NULL,
                        closed_at=NULL,
                        close_reason=NULL,
                        archived_at=NULL,
                        active_category_id=COALESCE(
                            excluded.active_category_id, ticket_rooms.active_category_id
                        ),
                        archive_category_id=COALESCE(
                            excluded.archive_category_id, ticket_rooms.archive_category_id
                        ),
                        responsible_role_id=COALESCE(
                            excluded.responsible_role_id, ticket_rooms.responsible_role_id
                        ),
                        version=ticket_rooms.version+1
                    """,
                    (
                        guild_id,
                        ticket_id,
                        int(ticket["discord_id"]),
                        channel_id,
                        control_message_id,
                        now,
                        active_category_id,
                        archive_category_id,
                        responsible_role_id,
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("Este canal já pertence a outro atendimento.") from exc
            await self.audit.record(
                guild_id,
                "TICKET_ROOM_BOUND",
                actor_id=int(ticket["discord_id"]),
                target_id=int(ticket["discord_id"]),
                after={"ticket_id": ticket_id, "channel_id": channel_id},
                connection=connection,
            )
            await self._event(
                connection,
                guild_id,
                ticket_id,
                "ROOM_CREATED",
                actor_id=int(ticket["discord_id"]),
                metadata={
                    "channel_id": channel_id,
                    "active_category_id": active_category_id,
                    "archive_category_id": archive_category_id,
                    "responsible_role_id": responsible_role_id,
                },
                created_at=now,
            )
        return await self.room_for_ticket(guild_id, ticket_id)

    async def set_room_message(
        self,
        guild_id: int,
        ticket_id: int,
        message_id: int,
    ) -> None:
        await self.database.execute(
            """
            UPDATE ticket_rooms SET control_message_id=?
            WHERE guild_id=? AND ticket_id=?
            """,
            (message_id, guild_id, ticket_id),
        )

    async def set_room_resources(
        self,
        guild_id: int,
        ticket_id: int,
        *,
        active_category_id: int,
        archive_category_id: int,
        responsible_role_id: int | None,
    ) -> None:
        await self.database.execute(
            """
            UPDATE ticket_rooms
            SET active_category_id=?, archive_category_id=?, responsible_role_id=?,
                version=CASE
                    WHEN active_category_id IS NOT ? OR archive_category_id IS NOT ?
                      OR responsible_role_id IS NOT ? THEN version+1 ELSE version END
            WHERE guild_id=? AND ticket_id=?
            """,
            (
                active_category_id,
                archive_category_id,
                responsible_role_id,
                active_category_id,
                archive_category_id,
                responsible_role_id,
                guild_id,
                ticket_id,
            ),
        )

    async def mark_responsible_role_mentioned(
        self,
        guild_id: int,
        ticket_id: int,
        actor_id: int | None,
    ) -> bool:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE ticket_rooms
                SET responsible_role_mentioned_at=?, version=version+1
                WHERE guild_id=? AND ticket_id=?
                  AND responsible_role_mentioned_at IS NULL
                """,
                (now, guild_id, ticket_id),
            )
            if cursor.rowcount != 1:
                return False
            await self._event(
                connection,
                guild_id,
                ticket_id,
                "RESPONSIBLE_ROLE_MENTIONED",
                actor_id=actor_id,
                created_at=now,
            )
        return True

    async def claim(self, guild_id: int, ticket_id: int, actor_id: int):
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            if ticket["status"] not in {"PENDING", "IN_REVIEW"}:
                raise ConflictError("Este atendimento não está aberto.")
            if ticket["claimed_by"] is not None:
                if int(ticket["claimed_by"]) == actor_id:
                    return ticket
                raise ConflictError("Este atendimento já foi assumido por outro responsável.")
            cursor = await connection.execute(
                """
                UPDATE service_tickets
                SET claimed_by=?, claimed_at=?, status='IN_REVIEW', updated_at=?, version=version+1
                WHERE guild_id=? AND id=? AND claimed_by IS NULL
                  AND status IN ('PENDING','IN_REVIEW')
                """,
                (actor_id, now, now, guild_id, ticket_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Outro responsável assumiu este atendimento.")
            await self._event(
                connection, guild_id, ticket_id, "CLAIMED", actor_id=actor_id, created_at=now
            )
            await self.audit.record(
                guild_id,
                "TICKET_CLAIMED",
                actor_id=actor_id,
                target_id=int(ticket["discord_id"]),
                after={"ticket_id": ticket_id, "claimed_by": actor_id},
                connection=connection,
            )
        return await self.get(guild_id, ticket_id)

    async def release(
        self,
        guild_id: int,
        ticket_id: int,
        actor_id: int,
        *,
        force: bool = False,
    ):
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            claimed_by = ticket["claimed_by"]
            if claimed_by is None:
                return ticket
            if int(claimed_by) != actor_id and not force:
                raise ConflictError("Somente quem assumiu pode liberar este atendimento.")
            cursor = await connection.execute(
                """
                UPDATE service_tickets
                SET claimed_by=NULL, claimed_at=NULL, updated_at=?, version=version+1
                WHERE guild_id=? AND id=? AND claimed_by=?
                """,
                (now, guild_id, ticket_id, int(claimed_by)),
            )
            if cursor.rowcount != 1:
                raise ConflictError("O responsável foi alterado por outra ação.")
            await self._event(
                connection,
                guild_id,
                ticket_id,
                "RELEASED",
                actor_id=actor_id,
                metadata={"previous_claimed_by": int(claimed_by), "forced": force},
                created_at=now,
            )
            await self.audit.record(
                guild_id,
                "TICKET_RELEASED",
                actor_id=actor_id,
                target_id=int(ticket["discord_id"]),
                before={"claimed_by": int(claimed_by)},
                after={"ticket_id": ticket_id, "claimed_by": None},
                connection=connection,
            )
        return await self.get(guild_id, ticket_id)

    async def set_priority(
        self,
        guild_id: int,
        ticket_id: int,
        actor_id: int,
        priority: str,
    ):
        normalized = priority.upper()
        if normalized not in TICKET_PRIORITIES:
            raise ValidationError("Prioridade inválida.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            if ticket["status"] not in {"PENDING", "IN_REVIEW"}:
                raise ConflictError("Este atendimento não está aberto.")
            if str(ticket["priority"]) == normalized:
                return ticket
            cursor = await connection.execute(
                """
                UPDATE service_tickets SET priority=?, updated_at=?, version=version+1
                WHERE guild_id=? AND id=? AND version=?
                """,
                (normalized, now, guild_id, ticket_id, int(ticket["version"])),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A prioridade foi alterada por outra ação.")
            await self._event(
                connection,
                guild_id,
                ticket_id,
                "PRIORITY_CHANGED",
                actor_id=actor_id,
                metadata={"before": ticket["priority"], "after": normalized},
                created_at=now,
            )
            await self.audit.record(
                guild_id,
                "TICKET_PRIORITY_CHANGED",
                actor_id=actor_id,
                target_id=int(ticket["discord_id"]),
                before={"priority": ticket["priority"]},
                after={"ticket_id": ticket_id, "priority": normalized},
                connection=connection,
            )
        return await self.get(guild_id, ticket_id)

    async def participants(self, guild_id: int, ticket_id: int):
        return await self.database.fetchall(
            """
            SELECT * FROM ticket_participants
            WHERE guild_id=? AND ticket_id=? AND removed_at IS NULL
            ORDER BY added_at, id
            """,
            (guild_id, ticket_id),
        )

    async def add_participant(
        self,
        guild_id: int,
        ticket_id: int,
        discord_id: int,
        actor_id: int,
    ):
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            if ticket["status"] not in {"PENDING", "IN_REVIEW"}:
                raise ConflictError("Este atendimento não está aberto.")
            if int(ticket["discord_id"]) == discord_id:
                raise ValidationError("O solicitante já possui acesso ao atendimento.")
            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO ticket_participants(
                        guild_id, ticket_id, discord_id, added_by, added_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (guild_id, ticket_id, discord_id, actor_id, now),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("Esta pessoa já participa do atendimento.") from exc
            await self._event(
                connection,
                guild_id,
                ticket_id,
                "PARTICIPANT_ADDED",
                actor_id=actor_id,
                metadata={"discord_id": discord_id},
                created_at=now,
            )
            await self.audit.record(
                guild_id,
                "TICKET_PARTICIPANT_ADDED",
                actor_id=actor_id,
                target_id=discord_id,
                after={"ticket_id": ticket_id},
                connection=connection,
            )
        return await self.database.fetchone(
            "SELECT * FROM ticket_participants WHERE id=?", (int(cursor.lastrowid),)
        )

    async def remove_participant(
        self,
        guild_id: int,
        ticket_id: int,
        discord_id: int,
        actor_id: int,
    ) -> bool:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE ticket_participants SET removed_by=?, removed_at=?
                WHERE guild_id=? AND ticket_id=? AND discord_id=? AND removed_at IS NULL
                """,
                (actor_id, now, guild_id, ticket_id, discord_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Esta pessoa não participa do atendimento.")
            await self._event(
                connection,
                guild_id,
                ticket_id,
                "PARTICIPANT_REMOVED",
                actor_id=actor_id,
                metadata={"discord_id": discord_id},
                created_at=now,
            )
            await self.audit.record(
                guild_id,
                "TICKET_PARTICIPANT_REMOVED",
                actor_id=actor_id,
                target_id=discord_id,
                after={"ticket_id": ticket_id},
                connection=connection,
            )
        return True

    async def mark_requester_notified(
        self,
        guild_id: int,
        ticket_id: int,
        actor_id: int,
        *,
        cooldown_seconds: int = 60,
    ):
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            if ticket["status"] not in {"PENDING", "IN_REVIEW"}:
                raise ConflictError("Este atendimento não está aberto.")
            last = ticket["last_requester_notification_at"]
            if last is not None and now - int(last) < max(1, cooldown_seconds) * 1000:
                raise ConflictError("O solicitante já foi avisado recentemente.")
            cursor = await connection.execute(
                """
                UPDATE service_tickets
                SET last_requester_notification_at=?, updated_at=?, version=version+1
                WHERE guild_id=? AND id=? AND version=?
                """,
                (now, now, guild_id, ticket_id, int(ticket["version"])),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Outra notificação foi registrada ao mesmo tempo.")
            await self._event(
                connection,
                guild_id,
                ticket_id,
                "REQUESTER_NOTIFIED",
                actor_id=actor_id,
                created_at=now,
            )
            await self.audit.record(
                guild_id,
                "TICKET_REQUESTER_NOTIFIED",
                actor_id=actor_id,
                target_id=int(ticket["discord_id"]),
                after={"ticket_id": ticket_id},
                connection=connection,
            )
        return await self.get(guild_id, ticket_id)

    async def record_transcript(
        self,
        guild_id: int,
        ticket_id: int,
        actor_id: int,
        content: str,
        message_count: int,
        reason: str,
    ):
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Informe a finalidade da transcrição.")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT discord_id FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            cursor = await connection.execute(
                """
                INSERT INTO ticket_transcripts(
                    guild_id, ticket_id, generated_by, reason, message_count,
                    content_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, ticket_id, actor_id, normalized_reason, message_count, digest, now),
            )
            transcript_id = int(cursor.lastrowid)
            await self._event(
                connection,
                guild_id,
                ticket_id,
                "TRANSCRIPT_GENERATED",
                actor_id=actor_id,
                metadata={
                    "transcript_id": transcript_id,
                    "message_count": message_count,
                    "sha256": digest,
                },
                created_at=now,
            )
            await self.audit.record(
                guild_id,
                "TICKET_TRANSCRIPT_GENERATED",
                actor_id=actor_id,
                target_id=int(ticket["discord_id"]),
                after={"ticket_id": ticket_id, "transcript_id": transcript_id, "sha256": digest},
                reason=normalized_reason,
                connection=connection,
            )
        return await self.database.fetchone(
            "SELECT * FROM ticket_transcripts WHERE id=?", (transcript_id,)
        )

    async def close_by_request(
        self,
        guild_id: int,
        ticket_id: int,
        actor_id: int,
        reason: str,
    ):
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Informe o motivo do encerramento.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            if ticket["status"] not in {"PENDING", "IN_REVIEW"}:
                raise ConflictError("Este atendimento já foi encerrado.")
            cursor = await connection.execute(
                """
                UPDATE service_tickets
                SET status='CLOSED', updated_at=?, review_reason=COALESCE(review_reason, ?),
                    version=version+1
                WHERE guild_id=? AND id=? AND status IN ('PENDING','IN_REVIEW')
                """,
                (now, normalized_reason, guild_id, ticket_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Este atendimento foi encerrado por outra pessoa.")
            if ticket["ticket_type"] == "TRANSFER":
                transfer_cursor = await connection.execute(
                    """
                    SELECT * FROM transfer_cases
                    WHERE guild_id=? AND ticket_id=?
                    """,
                    (guild_id, ticket_id),
                )
                transfer = await transfer_cursor.fetchone()
                if not transfer:
                    raise NotFoundError("Protocolo de transferência não encontrado.")
                transfer_cursor = await connection.execute(
                    """
                    UPDATE transfer_cases
                    SET status='CANCELLED', updated_at=?, version=version+1
                    WHERE id=? AND status='PENDING'
                    """,
                    (now, transfer["id"]),
                )
                if transfer_cursor.rowcount != 1:
                    raise ConflictError("O protocolo de transferência não está pendente.")
                await self._transfer_event(
                    connection,
                    guild_id,
                    int(transfer["id"]),
                    "CANCELLED",
                    actor_id=actor_id,
                    metadata={"reason": normalized_reason, "ticket_id": ticket_id},
                    created_at=now,
                )
                await self.audit.record(
                    guild_id,
                    "TRANSFER_CANCELLED",
                    actor_id=actor_id,
                    target_id=int(ticket["discord_id"]),
                    before={"status": transfer["status"]},
                    after={
                        "status": "CANCELLED",
                        "protocol": str(transfer["protocol"]),
                        "ticket_id": ticket_id,
                    },
                    reason=normalized_reason,
                    connection=connection,
                )
            await connection.execute(
                """
                UPDATE ticket_rooms
                SET status='CLOSED', closed_by=?, closed_at=?, close_reason=?, version=version+1
                WHERE guild_id=? AND ticket_id=? AND status='OPEN'
                """,
                (actor_id, now, normalized_reason, guild_id, ticket_id),
            )
            await self.audit.record(
                guild_id,
                "SERVICE_TICKET_CLOSED",
                actor_id=actor_id,
                target_id=int(ticket["discord_id"]),
                before={"status": ticket["status"]},
                after={"status": "CLOSED", "ticket_id": ticket_id},
                reason=normalized_reason,
                connection=connection,
            )
            await self._event(
                connection,
                guild_id,
                ticket_id,
                "CLOSED",
                actor_id=actor_id,
                metadata={"reason": normalized_reason},
                created_at=now,
            )
        return await self.get(guild_id, ticket_id)

    async def mark_room_closed(
        self,
        guild_id: int,
        ticket_id: int,
        actor_id: int,
        reason: str,
    ) -> None:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE ticket_rooms
                SET status='CLOSED', closed_by=?, closed_at=?, close_reason=?, version=version+1
                WHERE guild_id=? AND ticket_id=? AND status='OPEN'
                """,
                (actor_id, now, reason.strip(), guild_id, ticket_id),
            )
            if cursor.rowcount:
                await self.audit.record(
                    guild_id,
                    "TICKET_ROOM_CLOSED",
                    actor_id=actor_id,
                    after={"ticket_id": ticket_id},
                    reason=reason.strip(),
                    connection=connection,
                )
                await self._event(
                    connection,
                    guild_id,
                    ticket_id,
                    "CLOSED",
                    actor_id=actor_id,
                    metadata={"reason": reason.strip()},
                    created_at=now,
                )

    async def mark_room_archived(
        self,
        guild_id: int,
        ticket_id: int,
        actor_id: int,
    ) -> None:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE ticket_rooms SET status='ARCHIVED', archived_at=?, version=version+1
                WHERE guild_id=? AND ticket_id=? AND status!='ARCHIVED'
                """,
                (now, guild_id, ticket_id),
            )
            if cursor.rowcount:
                await self.audit.record(
                    guild_id,
                    "TICKET_ROOM_ARCHIVED",
                    actor_id=actor_id,
                    after={"ticket_id": ticket_id},
                    connection=connection,
                )
                await self._event(
                    connection,
                    guild_id,
                    ticket_id,
                    "ARCHIVED",
                    actor_id=actor_id,
                    created_at=now,
                )

    async def reopen(
        self,
        guild_id: int,
        ticket_id: int,
        actor_id: int,
        reason: str,
    ):
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Informe o motivo da reabertura.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            cursor = await connection.execute(
                "SELECT * FROM ticket_rooms WHERE guild_id=? AND ticket_id=?",
                (guild_id, ticket_id),
            )
            room = await cursor.fetchone()
            if not room:
                raise NotFoundError("Sala do atendimento não encontrada.")
            if room["status"] == "OPEN":
                return ticket
            transfer = None
            if ticket["ticket_type"] == "TRANSFER":
                transfer_cursor = await connection.execute(
                    """
                    SELECT * FROM transfer_cases
                    WHERE guild_id=? AND ticket_id=?
                    """,
                    (guild_id, ticket_id),
                )
                transfer = await transfer_cursor.fetchone()
                if not transfer:
                    raise NotFoundError("Protocolo de transferência não encontrado.")
                if transfer["status"] not in {"CANCELLED", "REJECTED"}:
                    raise ConflictError(
                        "Somente transferências canceladas ou rejeitadas podem ser reabertas."
                    )
            cursor = await connection.execute(
                """
                UPDATE service_tickets
                SET status='IN_REVIEW', updated_at=?, claimed_by=NULL, claimed_at=NULL,
                    version=version+1
                WHERE guild_id=? AND id=? AND status NOT IN ('PENDING','IN_REVIEW')
                """,
                (now, guild_id, ticket_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("O atendimento já foi reaberto por outra ação.")
            cursor = await connection.execute(
                """
                UPDATE ticket_rooms
                SET status='OPEN', archived_at=NULL, reopened_by=?, reopened_at=?,
                    close_reason=NULL, version=version+1
                WHERE guild_id=? AND ticket_id=? AND status IN ('CLOSED','ARCHIVED')
                """,
                (actor_id, now, guild_id, ticket_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A sala já foi reaberta por outra ação.")
            if transfer:
                transfer_cursor = await connection.execute(
                    """
                    UPDATE transfer_cases
                    SET status='PENDING', approved_rank_id=NULL,
                        max_rank_level_snapshot=NULL, member_application_id=NULL,
                        decided_by=NULL, decided_at=NULL, decision_reason=NULL,
                        applied_by=NULL, applied_at=NULL, updated_at=?, version=version+1
                    WHERE id=? AND status=?
                    """,
                    (now, transfer["id"], transfer["status"]),
                )
                if transfer_cursor.rowcount != 1:
                    raise ConflictError(
                        "O protocolo de transferência foi reaberto por outra pessoa."
                    )
                await self._transfer_event(
                    connection,
                    guild_id,
                    int(transfer["id"]),
                    "REOPENED",
                    actor_id=actor_id,
                    metadata={
                        "previous_status": str(transfer["status"]),
                        "reason": normalized_reason,
                        "ticket_id": ticket_id,
                    },
                    created_at=now,
                )
                await self.audit.record(
                    guild_id,
                    "TRANSFER_REOPENED",
                    actor_id=actor_id,
                    target_id=int(ticket["discord_id"]),
                    before={"status": transfer["status"]},
                    after={
                        "status": "PENDING",
                        "protocol": str(transfer["protocol"]),
                        "ticket_id": ticket_id,
                    },
                    reason=normalized_reason,
                    connection=connection,
                )
            await self._event(
                connection,
                guild_id,
                ticket_id,
                "REOPENED",
                actor_id=actor_id,
                metadata={"previous_status": ticket["status"], "reason": normalized_reason},
                created_at=now,
            )
            await self.audit.record(
                guild_id,
                "TICKET_REOPENED",
                actor_id=actor_id,
                target_id=int(ticket["discord_id"]),
                before={"status": ticket["status"]},
                after={"status": "IN_REVIEW", "ticket_id": ticket_id},
                reason=normalized_reason,
                connection=connection,
            )
        return await self.get(guild_id, ticket_id)

    async def operation_history(self, guild_id: int, ticket_id: int, *, limit: int = 50):
        return await self.database.fetchall(
            """
            SELECT * FROM ticket_operation_events
            WHERE guild_id=? AND ticket_id=? ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (guild_id, ticket_id, limit),
        )

    async def dashboard(self, guild_id: int):
        tickets, rooms, counts = (
            await self.database.fetchall(
                """
            SELECT ticket.*, room.channel_id, room.status AS room_status,
                   room.responsible_role_id, room.control_message_id
            FROM service_tickets AS ticket
            LEFT JOIN ticket_rooms AS room
              ON room.guild_id=ticket.guild_id AND room.ticket_id=ticket.id
            WHERE ticket.guild_id=?
            ORDER BY CASE ticket.priority
                WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'NORMAL' THEN 2 ELSE 3 END,
                ticket.updated_at DESC LIMIT 100
            """,
                (guild_id,),
            ),
            await self.database.fetchall(
                "SELECT * FROM ticket_rooms WHERE guild_id=? ORDER BY created_at DESC LIMIT 100",
                (guild_id,),
            ),
            await self.pending_counts(guild_id),
        )
        return {"tickets": tickets, "rooms": rooms, "counts": counts}

    async def tickets_requiring_rooms(self, guild_id: int, *, limit: int = 100):
        return await self.database.fetchall(
            """
            SELECT ticket.* FROM service_tickets AS ticket
            LEFT JOIN ticket_rooms AS room
              ON room.guild_id=ticket.guild_id AND room.ticket_id=ticket.id
            WHERE ticket.guild_id=? AND ticket.status IN ('PENDING','IN_REVIEW')
              AND (room.id IS NULL OR room.status='OPEN')
            ORDER BY ticket.submitted_at, ticket.id LIMIT ?
            """,
            (guild_id, limit),
        )

    async def mine(self, guild_id: int, discord_id: int, *, limit: int = 10):
        return await self.database.fetchall(
            """
            SELECT * FROM service_tickets
            WHERE guild_id=? AND discord_id=?
            ORDER BY submitted_at DESC, id DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )

    async def pending(
        self,
        guild_id: int,
        ticket_types: Iterable[str] | None = None,
        *,
        limit: int = 25,
    ):
        types = tuple(ticket_type.upper() for ticket_type in (ticket_types or TICKET_TYPES))
        if not types or any(ticket_type not in TICKET_TYPES for ticket_type in types):
            raise ValidationError("Filtro de atendimento inválido.")
        placeholders = ",".join("?" for _ in types)
        return await self.database.fetchall(
            f"""
            SELECT * FROM service_tickets
            WHERE guild_id=? AND status IN ('PENDING','IN_REVIEW')
              AND ticket_type IN ({placeholders})
            ORDER BY submitted_at, id LIMIT ?
            """,
            (guild_id, *types, limit),
        )

    async def pending_counts(self, guild_id: int) -> dict[str, int]:
        rows = await self.database.fetchall(
            """
            SELECT ticket_type, COUNT(*) AS total FROM service_tickets
            WHERE guild_id=? AND status IN ('PENDING','IN_REVIEW')
            GROUP BY ticket_type
            """,
            (guild_id,),
        )
        result = {ticket_type: 0 for ticket_type in TICKET_TYPES}
        result.update({str(row["ticket_type"]): int(row["total"]) for row in rows})
        return result

    async def transfer_case_for_ticket(self, guild_id: int, ticket_id: int):
        row = await self.database.fetchone(
            """
            SELECT transfer.*, rank.name AS approved_rank_name,
                   rank.level AS approved_rank_level
            FROM transfer_cases AS transfer
            LEFT JOIN ranks AS rank ON rank.id=transfer.approved_rank_id
            WHERE transfer.guild_id=? AND transfer.ticket_id=?
            """,
            (guild_id, ticket_id),
        )
        if not row:
            raise NotFoundError("Protocolo de transferência não encontrado.")
        return row

    async def transfer_history(self, guild_id: int, ticket_id: int, *, limit: int = 100):
        transfer = await self.transfer_case_for_ticket(guild_id, ticket_id)
        return await self.database.fetchall(
            """
            SELECT * FROM transfer_case_events
            WHERE guild_id=? AND transfer_case_id=?
            ORDER BY created_at, id LIMIT ?
            """,
            (guild_id, int(transfer["id"]), limit),
        )

    async def _transfer_max_rank_level(self, guild_id: int) -> int:
        configured = await self.settings.get(guild_id, "transfer_max_rank_level")
        if isinstance(configured, bool):
            raise ValidationError("Configure um limite de patente válido para transferências.")
        try:
            level = int(configured)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Configure um limite de patente válido para transferências."
            ) from exc
        if level < 1:
            raise ValidationError("Configure um limite de patente válido para transferências.")
        return level

    async def transfer_rank_options(self, guild_id: int):
        max_level = await self._transfer_max_rank_level(guild_id)
        return await self.database.fetchall(
            """
            SELECT id, name, prefix, level, discord_role_id
            FROM ranks
            WHERE guild_id=? AND active=1 AND level<=?
            ORDER BY level, id
            """,
            (guild_id, max_level),
        )

    async def decide_transfer(
        self,
        guild_id: int,
        ticket_id: int,
        reviewer_id: int,
        *,
        approved: bool,
        reason: str,
        approved_rank_id: int | None = None,
    ):
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Informe o motivo da decisão.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            if ticket["ticket_type"] != "TRANSFER":
                raise ValidationError("Este atendimento não é uma transferência.")
            if ticket["status"] not in {"PENDING", "IN_REVIEW"}:
                raise ConflictError("Esta transferência já foi analisada.")
            cursor = await connection.execute(
                """
                SELECT * FROM transfer_cases
                WHERE guild_id=? AND ticket_id=?
                """,
                (guild_id, ticket_id),
            )
            transfer = await cursor.fetchone()
            if not transfer:
                raise NotFoundError("Protocolo de transferência não encontrado.")
            if transfer["status"] != "PENDING":
                raise ConflictError("Esta transferência já foi analisada.")

            application_id = None
            target_rank = None
            max_rank_level = None
            if approved:
                if approved_rank_id is None:
                    raise ValidationError("Selecione a patente autorizada para a transferência.")
                max_rank_level = await self._transfer_max_rank_level(guild_id)
                cursor = await connection.execute(
                    """
                    SELECT id, name, level FROM ranks
                    WHERE guild_id=? AND id=? AND active=1
                    """,
                    (guild_id, approved_rank_id),
                )
                target_rank = await cursor.fetchone()
                if not target_rank:
                    raise NotFoundError("A patente selecionada não está ativa.")
                if int(target_rank["level"]) > max_rank_level:
                    raise ValidationError(
                        "A patente selecionada excede o limite de patente para transferências."
                    )
                payload = json.loads(str(ticket["payload_json"]))
                application_id = await self.members.submit_application(
                    guild_id,
                    int(ticket["discord_id"]),
                    str(payload["mta_nick"]),
                    str(payload.get("character_id") or "") or None,
                    "BGR",
                    f"Transferência {transfer['protocol']} • {reviewer_id}",
                    connection,
                )

            status = "APPROVED" if approved else "REJECTED"
            cursor = await connection.execute(
                """
                UPDATE service_tickets
                SET status=?, reviewed_by=?, reviewed_at=?, review_reason=?,
                    member_application_id=?, updated_at=?, version=version+1
                WHERE guild_id=? AND id=? AND status IN ('PENDING','IN_REVIEW')
                """,
                (
                    status,
                    reviewer_id,
                    now,
                    normalized_reason,
                    application_id,
                    now,
                    guild_id,
                    ticket_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta transferência foi analisada por outra pessoa.")
            cursor = await connection.execute(
                """
                UPDATE transfer_cases
                SET status=?, approved_rank_id=?, max_rank_level_snapshot=?,
                    member_application_id=?, decided_by=?, decided_at=?,
                    decision_reason=?, updated_at=?, version=version+1
                WHERE guild_id=? AND ticket_id=? AND status='PENDING'
                """,
                (
                    status,
                    int(target_rank["id"]) if target_rank else None,
                    max_rank_level,
                    application_id,
                    reviewer_id,
                    now,
                    normalized_reason,
                    now,
                    guild_id,
                    ticket_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta transferência foi analisada por outra pessoa.")
            await self._transfer_event(
                connection,
                guild_id,
                int(transfer["id"]),
                status,
                actor_id=reviewer_id,
                metadata={
                    "ticket_id": ticket_id,
                    "approved_rank_id": int(target_rank["id"]) if target_rank else None,
                    "approved_rank_name": str(target_rank["name"]) if target_rank else None,
                    "member_application_id": application_id,
                    "max_rank_level": max_rank_level,
                },
                created_at=now,
            )
            await self.audit.record(
                guild_id,
                "SERVICE_TICKET_APPROVED" if approved else "SERVICE_TICKET_REJECTED",
                actor_id=reviewer_id,
                target_id=int(ticket["discord_id"]),
                before={"status": ticket["status"]},
                after={
                    "status": status,
                    "ticket_id": ticket_id,
                    "member_application_id": application_id,
                },
                reason=normalized_reason,
                connection=connection,
            )
            await self.audit.record(
                guild_id,
                "TRANSFER_APPROVED" if approved else "TRANSFER_REJECTED",
                actor_id=reviewer_id,
                target_id=int(ticket["discord_id"]),
                before={"status": transfer["status"]},
                after={
                    "status": status,
                    "protocol": str(transfer["protocol"]),
                    "approved_rank_id": int(target_rank["id"]) if target_rank else None,
                    "member_application_id": application_id,
                    "max_rank_level": max_rank_level,
                },
                reason=normalized_reason,
                connection=connection,
            )
        return await self.get(guild_id, ticket_id)

    async def decide(
        self,
        guild_id: int,
        ticket_id: int,
        reviewer_id: int,
        *,
        approved: bool,
        reason: str,
    ):
        if not reason.strip():
            raise ValidationError("Informe o motivo da decisão.")
        existing = await self.get(guild_id, ticket_id)
        if existing["ticket_type"] == "TRANSFER":
            if approved:
                raise ValidationError(
                    "Transferências usam fluxo próprio com seleção de patente autorizada."
                )
            return await self.decide_transfer(
                guild_id,
                ticket_id,
                reviewer_id,
                approved=False,
                reason=reason,
            )
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM service_tickets WHERE guild_id=? AND id=?",
                (guild_id, ticket_id),
            )
            ticket = await cursor.fetchone()
            if not ticket:
                raise NotFoundError("Atendimento não encontrado.")
            if ticket["status"] not in {"PENDING", "IN_REVIEW"}:
                raise ConflictError("Este atendimento já foi analisado.")
            application_id = None
            if approved and ticket["ticket_type"] == "CANDIDACY":
                payload = json.loads(ticket["payload_json"])
                application_id = await self.members.submit_application(
                    guild_id,
                    int(ticket["discord_id"]),
                    str(payload["mta_nick"]),
                    str(payload.get("character_id") or "") or None,
                    "BGR",
                    f"Recrutamento • {reviewer_id}",
                    connection,
                )
            status = "APPROVED" if approved else "REJECTED"
            cursor = await connection.execute(
                """
                UPDATE service_tickets SET status=?, reviewed_by=?, reviewed_at=?,
                    review_reason=?, member_application_id=?, updated_at=?
                WHERE guild_id=? AND id=? AND status IN ('PENDING','IN_REVIEW')
                """,
                (
                    status,
                    reviewer_id,
                    now,
                    reason.strip(),
                    application_id,
                    now,
                    guild_id,
                    ticket_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Este atendimento foi analisado por outra pessoa.")
            await self.audit.record(
                guild_id,
                "SERVICE_TICKET_APPROVED" if approved else "SERVICE_TICKET_REJECTED",
                actor_id=reviewer_id,
                target_id=int(ticket["discord_id"]),
                before={"status": ticket["status"]},
                after={
                    "status": status,
                    "ticket_id": ticket_id,
                    "member_application_id": application_id,
                },
                reason=reason.strip(),
                connection=connection,
            )
        return await self.get(guild_id, ticket_id)
