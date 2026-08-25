from __future__ import annotations

import json
import uuid

import aiosqlite

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .models import MemberStatus
from .time_utils import utc_now_ms

RESULT_DELIVERY_CLAIM_TTL_MS = 5 * 60 * 1000


class MemberService:
    def __init__(self, database: Database, audit: AuditService):
        self.database = database
        self.audit = audit

    async def get(self, guild_id: int, discord_id: int):
        return await self.database.fetchone(
            """
            SELECT m.*, r.name AS rank_name, r.prefix AS rank_prefix,
                   r.level AS rank_level, r.discord_role_id AS rank_role_id
            FROM members m LEFT JOIN ranks r ON r.id = m.rank_id
            WHERE m.guild_id = ? AND m.discord_id = ?
            """,
            (guild_id, discord_id),
        )

    async def create_or_update(
        self,
        guild_id: int,
        discord_id: int,
        *,
        discord_nick: str,
        mta_nick: str,
        character_id: str | None,
        unit: str | None,
        rank_id: int | None,
        actor_id: int,
        status: MemberStatus = MemberStatus.ACTIVE,
    ):
        if not mta_nick.strip():
            raise ValidationError("O nick MTA é obrigatório.")
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            current_cursor = await connection.execute(
                "SELECT * FROM members WHERE guild_id = ? AND discord_id = ?",
                (guild_id, discord_id),
            )
            current = await current_cursor.fetchone()
            await connection.execute(
                """
                INSERT INTO members(
                    guild_id, discord_id, discord_nick, mta_nick, character_id,
                    rank_id, unit, status, joined_at, last_activity_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                    discord_nick=excluded.discord_nick,
                    mta_nick=excluded.mta_nick,
                    character_id=excluded.character_id,
                    rank_id=COALESCE(excluded.rank_id, members.rank_id),
                    unit=excluded.unit,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    guild_id,
                    discord_id,
                    discord_nick,
                    mta_nick.strip(),
                    character_id.strip() if character_id else None,
                    rank_id,
                    unit.strip() if unit else None,
                    status.value,
                    now,
                    now,
                    now,
                    now,
                ),
            )
            await self.audit.record(
                guild_id,
                "MEMBER_UPSERT",
                actor_id=actor_id,
                target_id=discord_id,
                before=dict(current) if current else None,
                after={"mta_nick": mta_nick, "status": status.value, "rank_id": rank_id},
                connection=connection,
            )
        return await self.get(guild_id, discord_id)

    async def change_status(
        self,
        guild_id: int,
        discord_id: int,
        status: MemberStatus,
        actor_id: int,
        reason: str,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        if not reason.strip():
            raise ValidationError("Informe o motivo da alteração.")

        async def apply(conn: aiosqlite.Connection) -> None:
            cursor = await conn.execute(
                "SELECT status FROM members WHERE guild_id = ? AND discord_id = ?",
                (guild_id, discord_id),
            )
            row = await cursor.fetchone()
            if not row:
                raise NotFoundError("Membro não cadastrado.")
            if row["status"] == status.value:
                raise ConflictError("O membro já possui esse status.")
            await conn.execute(
                "UPDATE members SET status=?, updated_at=? WHERE guild_id=? AND discord_id=?",
                (status.value, utc_now_ms(), guild_id, discord_id),
            )
            await self.audit.record(
                guild_id,
                "MEMBER_STATUS_CHANGED",
                actor_id=actor_id,
                target_id=discord_id,
                before={"status": row["status"]},
                after={"status": status.value},
                reason=reason,
                connection=conn,
            )

        if connection:
            await apply(connection)
        else:
            async with self.database.transaction() as conn:
                await apply(conn)

    async def submit_application(
        self,
        guild_id: int,
        discord_id: int,
        mta_nick: str,
        character_id: str | None,
        unit: str | None,
        recruiter: str | None,
        connection: aiosqlite.Connection | None = None,
    ) -> int:
        if not mta_nick.strip():
            raise ValidationError("O nick MTA é obrigatório.")

        async def apply(conn: aiosqlite.Connection) -> int:
            cursor = await conn.execute(
                """
                SELECT id FROM member_applications
                WHERE guild_id=? AND discord_id=? AND status='PENDING'
                """,
                (guild_id, discord_id),
            )
            if await cursor.fetchone():
                raise ConflictError("Você já possui uma solicitação pendente.")
            cursor = await conn.execute(
                "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
                (guild_id, discord_id),
            )
            if await cursor.fetchone():
                raise ConflictError("Você já está cadastrado.")
            cursor = await conn.execute(
                """
                INSERT INTO member_applications(
                    guild_id, discord_id, mta_nick, character_id, unit, recruiter, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    discord_id,
                    mta_nick.strip(),
                    character_id.strip() if character_id else None,
                    unit.strip() if unit else None,
                    recruiter.strip() if recruiter else None,
                    utc_now_ms(),
                ),
            )
            application_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "MEMBER_APPLICATION_SUBMITTED",
                actor_id=discord_id,
                target_id=discord_id,
                after={"application_id": application_id, "mta_nick": mta_nick.strip()},
                connection=conn,
            )
            return application_id

        if connection:
            return await apply(connection)
        async with self.database.transaction() as conn:
            return await apply(conn)

    async def get_application(self, application_id: int):
        return await self.database.fetchone(
            "SELECT * FROM member_applications WHERE id = ?", (application_id,)
        )

    async def record_application_review_message(
        self,
        application_id: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE member_applications
                SET review_channel_id=?, review_message_id=?
                WHERE id=? AND status='PENDING'
                """,
                (channel_id, message_id, application_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Essa solicitação não está mais pendente.")

    async def mark_application_delivered(
        self,
        application_id: int,
        actor_id: int,
        result_channel_id: int,
        result_message_id: int,
        *,
        claim_token: str | None = None,
    ) -> None:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM member_applications WHERE id=?",
                (application_id,),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Solicitação não encontrada.")
            if application["status"] == "PENDING":
                raise ConflictError("Essa solicitação ainda não foi analisada.")
            if (
                application["delivery_status"] == "DELIVERED"
                and int(application["result_channel_id"] or 0) == result_channel_id
                and int(application["result_message_id"] or 0) == result_message_id
            ):
                return
            if claim_token is not None:
                claim = await connection.execute(
                    """
                    SELECT 1 FROM member_application_delivery_claims
                    WHERE application_id=? AND phase='RESULT' AND claim_token=?
                    """,
                    (application_id, claim_token),
                )
                if await claim.fetchone() is None:
                    raise ConflictError("A entrega do resultado foi assumida por outra instância.")
            await connection.execute(
                """
                UPDATE member_applications
                SET result_channel_id=?, result_message_id=?, delivery_status='DELIVERED'
                WHERE id=?
                """,
                (result_channel_id, result_message_id, application_id),
            )
            await self.audit.record(
                int(application["guild_id"]),
                "MEMBER_APPLICATION_RESULT_DELIVERED",
                actor_id=actor_id,
                target_id=int(application["discord_id"]),
                after={
                    "application_id": application_id,
                    "status": application["status"],
                    "result_channel_id": result_channel_id,
                    "result_message_id": result_message_id,
                },
                connection=connection,
            )
            if claim_token is not None:
                await connection.execute(
                    """
                    DELETE FROM member_application_delivery_claims
                    WHERE application_id=? AND phase='RESULT' AND claim_token=?
                    """,
                    (application_id, claim_token),
                )

    async def pending_applications(self, guild_id: int, *, limit: int = 100):
        return await self.database.fetchall(
            """
            SELECT * FROM member_applications
            WHERE guild_id=? AND status='PENDING'
            ORDER BY submitted_at, id LIMIT ?
            """,
            (guild_id, limit),
        )

    async def undelivered_reviews(self, guild_id: int, *, limit: int = 100):
        return await self.database.fetchall(
            """
            SELECT * FROM member_applications
            WHERE guild_id=? AND status IN ('APPROVED','REJECTED')
              AND delivery_status='PENDING'
            ORDER BY reviewed_at, id LIMIT ?
            """,
            (guild_id, limit),
        )

    async def pending_application_cleanup(self, guild_id: int, *, limit: int = 100):
        return await self.database.fetchall(
            """
            SELECT * FROM member_applications
            WHERE guild_id=? AND status IN ('APPROVED','REJECTED')
              AND reviewed_at IS NOT NULL AND delivery_status='DELIVERED'
              AND review_channel_id IS NOT NULL AND review_message_id IS NOT NULL
            ORDER BY reviewed_at, id LIMIT ?
            """,
            (guild_id, limit),
        )

    async def claim_application_result_delivery(self, application_id: int) -> str | None:
        return await self._claim_delivery_phase(application_id, "RESULT")

    async def claim_application_cleanup(self, application_id: int) -> str | None:
        return await self._claim_delivery_phase(application_id, "CLEANUP")

    async def _claim_delivery_phase(self, application_id: int, phase: str) -> str | None:
        now = utc_now_ms()
        token = str(uuid.uuid4())
        if phase not in {"RESULT", "CLEANUP"}:
            raise ValueError("Fase de entrega inválida.")
        condition = (
            "delivery_status='PENDING'"
            if phase == "RESULT"
            else (
                "status IN ('APPROVED','REJECTED') AND reviewed_at IS NOT NULL "
                "AND delivery_status='DELIVERED' AND review_channel_id IS NOT NULL "
                "AND review_message_id IS NOT NULL"
            )
        )
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                DELETE FROM member_application_delivery_claims
                WHERE application_id=? AND phase=? AND claimed_at<?
                """,
                (application_id, phase, now - RESULT_DELIVERY_CLAIM_TTL_MS),
            )
            cursor = await connection.execute(
                f"""
                INSERT OR IGNORE INTO member_application_delivery_claims(
                    application_id, phase, claim_token, claimed_at
                )
                SELECT ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM member_applications
                    WHERE id=? AND {condition}
                )
                """,
                (application_id, phase, token, now, application_id),
            )
            return token if cursor.rowcount == 1 else None

    async def release_application_delivery_claim(
        self, application_id: int, phase: str, claim_token: str
    ) -> None:
        await self.database.execute(
            """
            DELETE FROM member_application_delivery_claims
            WHERE application_id=? AND phase=? AND claim_token=?
            """,
            (application_id, phase, claim_token),
        )

    async def mark_application_cleanup_completed(
        self, application_id: int, *, claim_token: str
    ) -> None:
        async with self.database.transaction() as connection:
            claim = await connection.execute(
                """
                SELECT 1 FROM member_application_delivery_claims
                WHERE application_id=? AND phase='CLEANUP' AND claim_token=?
                """,
                (application_id, claim_token),
            )
            if await claim.fetchone() is None:
                raise ConflictError("A limpeza da ficha foi assumida por outra instância.")
            await connection.execute(
                """
                UPDATE member_applications
                SET review_channel_id=NULL, review_message_id=NULL
                WHERE id=? AND status IN ('APPROVED','REJECTED')
                  AND reviewed_at IS NOT NULL AND delivery_status='DELIVERED'
                """,
                (application_id,),
            )
            await connection.execute(
                """
                DELETE FROM member_application_delivery_claims
                WHERE application_id=? AND phase='CLEANUP' AND claim_token=?
                """,
                (application_id, claim_token),
            )

    async def review_application(
        self,
        application_id: int,
        reviewer_id: int,
        approved: bool,
        reason: str | None,
        discord_nick: str,
        initial_rank_id: int | None = None,
        *,
        enqueue_discord_sync: bool = False,
    ):
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM member_applications WHERE id = ?", (application_id,)
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Solicitação não encontrada.")
            if application["status"] != "PENDING":
                raise ConflictError("Essa solicitação já foi analisada.")
            status = "APPROVED" if approved else "REJECTED"
            cursor = await connection.execute(
                """
                UPDATE member_applications SET status=?, reviewed_at=?, reviewed_by=?, review_reason=?
                WHERE id=? AND status='PENDING'
                """,
                (status, now, reviewer_id, reason, application_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Essa solicitação foi analisada por outra pessoa.")
            member = None
            if approved:
                if initial_rank_id is None:
                    rank_cursor = await connection.execute(
                        "SELECT id FROM ranks WHERE guild_id=? AND active=1 ORDER BY level LIMIT 1",
                        (application["guild_id"],),
                    )
                else:
                    rank_cursor = await connection.execute(
                        "SELECT id FROM ranks WHERE guild_id=? AND id=? AND active=1",
                        (application["guild_id"], initial_rank_id),
                    )
                rank = await rank_cursor.fetchone()
                if rank is None and initial_rank_id is not None:
                    # O cargo pode ter sido desativado entre a abertura do modal e
                    # a decisão. Nesse caso, volte de forma determinística à menor
                    # patente ativa em vez de cadastrar o membro sem patente.
                    rank_cursor = await connection.execute(
                        "SELECT id FROM ranks WHERE guild_id=? AND active=1 ORDER BY level LIMIT 1",
                        (application["guild_id"],),
                    )
                    rank = await rank_cursor.fetchone()
                await connection.execute(
                    """
                    INSERT INTO members(
                        guild_id, discord_id, discord_nick, mta_nick, character_id,
                        rank_id, unit, status, joined_at, last_activity_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
                    ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                        mta_nick=excluded.mta_nick,
                        character_id=excluded.character_id,
                        rank_id=COALESCE(excluded.rank_id, members.rank_id),
                        unit=excluded.unit,
                        status='ACTIVE',
                        updated_at=excluded.updated_at
                    """,
                    (
                        application["guild_id"],
                        application["discord_id"],
                        discord_nick,
                        application["mta_nick"],
                        application["character_id"],
                        rank["id"] if rank else None,
                        application["unit"],
                        now,
                        now,
                        now,
                        now,
                    ),
                )
                member = {"status": "ACTIVE", "rank_id": rank["id"] if rank else None}
                if enqueue_discord_sync:
                    await connection.execute(
                        """
                        INSERT INTO web_action_outbox(
                            guild_id, action_type, target_discord_id, payload_json,
                            requested_by, correlation_id, available_at, created_at
                        ) VALUES (?, 'MEMBER_SYNC', ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            application["guild_id"],
                            application["discord_id"],
                            json.dumps(
                                {
                                    "source": "REGISTRATION",
                                    "flow": "MEMBER_APPLICATION",
                                    "member_application_id": int(application["id"]),
                                },
                                ensure_ascii=False,
                            ),
                            reviewer_id,
                            str(uuid.uuid4()),
                            now,
                            now,
                        ),
                    )
            await self.audit.record(
                int(application["guild_id"]),
                "MEMBER_APPLICATION_REVIEWED",
                actor_id=reviewer_id,
                target_id=int(application["discord_id"]),
                before={"status": "PENDING"},
                after={"status": status, "member": member},
                reason=reason,
                connection=connection,
            )
        return await self.get(int(application["guild_id"]), int(application["discord_id"]))
