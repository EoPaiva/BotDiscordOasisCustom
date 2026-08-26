from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

import aiosqlite

from .audit import AuditService
from .channel_names import normalize_stylized_label
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .identity import normalize_bgr_id
from .settings import SettingsService
from .time_utils import utc_now_ms

REGISTRATION_STATUSES = frozenset(
    {"UNREGISTERED", "PENDING", "REGISTERED", "REQUIRES_REVIEW", "BLOCKED"}
)
ACCESS_TIERS = frozenset({"CANDIDATE", "RECRUIT", "MEMBER"})
ACCESS_CLASSES = frozenset({"ONBOARDING_VISIBLE", "MEMBER_ONLY", "STAFF_ONLY", "PUBLIC"})
RESULT_DELIVERY_CLAIM_TTL_MS = 5 * 60 * 1000
REGISTRATION_EVENTS = frozenset(
    {
        "REGISTRATION_STARTED",
        "REGISTRATION_COMPLETED",
        "REGISTRATION_REVIEW_REQUIRED",
        "REGISTRATION_APPROVED",
        "REGISTRATION_REJECTED",
        "REGISTRATION_IDENTITY_LINKED",
        "REGISTRATION_ACCESS_GRANTED",
        "REGISTRATION_ACCESS_REVOKED",
        "REGISTRATION_RECONCILED",
        "REGISTRATION_SYNC_FAILED",
    }
)
GATE_SETTING_KEYS = frozenset(
    {
        "registration_gate_enabled",
        "unregistered_role_id",
        "candidate_role_id",
        "member_role_id",
        "registration_onboarding_category_id",
        "registration_panel_channel_id",
        "registration_support_channel_id",
        "registration_onboarding_channel_ids",
        "registration_bypass_role_ids",
        "registration_bypass_user_ids",
        "registration_dm_enabled",
    }
)
RANK_COMPLIANCE_WINDOW_MS = 72 * 60 * 60 * 1000
RANK_COMPLIANCE_REMINDER_MS = 24 * 60 * 60 * 1000
RANK_COMPLIANCE_RETRY_MS = 6 * 60 * 60 * 1000


class RegistrationGateService:
    """Fonte de verdade transacional da Portaria Digital.

    O serviço não altera o Discord diretamente. Ele persiste a decisão e deixa
    a sincronização de cargos/nickname para o adapter Discord ou para a outbox.
    """

    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit

    async def status(self, guild_id: int, discord_id: int):
        return await self.database.fetchone(
            """
            SELECT r.*, m.status AS member_status, m.rank_id, rk.name AS rank_name,
                   a.status AS recruitment_status
            FROM registration_gate_records r
            LEFT JOIN members m ON m.id=r.member_id
            LEFT JOIN ranks rk ON rk.id=m.rank_id
            LEFT JOIN recruitment_applications a ON a.id=r.recruitment_application_id
            WHERE r.guild_id=? AND r.discord_id=?
            """,
            (guild_id, discord_id),
        )

    async def get(self, registration_id: int):
        return await self.database.fetchone(
            "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
        )

    async def pending_review_notifications(self, guild_id: int, *, limit: int = 100):
        return await self.database.fetchall(
            """
            SELECT * FROM registration_gate_records
            WHERE guild_id=? AND status IN ('PENDING','REQUIRES_REVIEW')
            ORDER BY submitted_at, id LIMIT ?
            """,
            (guild_id, limit),
        )

    async def undelivered_review_results(self, guild_id: int, *, limit: int = 100):
        return await self.database.fetchall(
            """
            SELECT * FROM registration_gate_records
            WHERE guild_id=? AND reviewed_at IS NOT NULL
              AND status IN ('REGISTERED','BLOCKED')
              AND delivery_status='PENDING'
            ORDER BY reviewed_at, id LIMIT ?
            """,
            (guild_id, limit),
        )

    async def pending_review_cleanup(self, guild_id: int, *, limit: int = 100):
        """Return only completed results whose temporary review card remains."""
        return await self.database.fetchall(
            """
            SELECT * FROM registration_gate_records
            WHERE guild_id=? AND status IN ('REGISTERED','BLOCKED')
              AND reviewed_at IS NOT NULL AND delivery_status='DELIVERED'
              AND review_channel_id IS NOT NULL AND review_message_id IS NOT NULL
            ORDER BY reviewed_at, id LIMIT ?
            """,
            (guild_id, limit),
        )

    async def claim_review_result_delivery(self, registration_id: int) -> str | None:
        return await self._claim_delivery_phase(registration_id, "RESULT")

    async def claim_review_cleanup(self, registration_id: int) -> str | None:
        return await self._claim_delivery_phase(registration_id, "CLEANUP")

    async def _claim_delivery_phase(self, registration_id: int, phase: str) -> str | None:
        now = utc_now_ms()
        token = str(uuid.uuid4())
        if phase not in {"RESULT", "CLEANUP"}:
            raise ValueError("Fase de entrega inválida.")
        condition = (
            "delivery_status='PENDING'"
            if phase == "RESULT"
            else (
                "status IN ('REGISTERED','BLOCKED') AND reviewed_at IS NOT NULL "
                "AND delivery_status='DELIVERED' AND review_channel_id IS NOT NULL "
                "AND review_message_id IS NOT NULL"
            )
        )
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                DELETE FROM registration_delivery_claims
                WHERE registration_id=? AND phase=? AND claimed_at<?
                """,
                (registration_id, phase, now - RESULT_DELIVERY_CLAIM_TTL_MS),
            )
            cursor = await connection.execute(
                f"""
                INSERT OR IGNORE INTO registration_delivery_claims(
                    registration_id, phase, claim_token, claimed_at
                )
                SELECT ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM registration_gate_records
                    WHERE id=? AND {condition}
                )
                """,
                (registration_id, phase, token, now, registration_id),
            )
            return token if cursor.rowcount == 1 else None

    async def release_delivery_claim(
        self, registration_id: int, phase: str, claim_token: str
    ) -> None:
        await self.database.execute(
            """
            DELETE FROM registration_delivery_claims
            WHERE registration_id=? AND phase=? AND claim_token=?
            """,
            (registration_id, phase, claim_token),
        )

    async def record_review_notification(
        self,
        registration_id: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE registration_gate_records
                SET review_channel_id=?, review_message_id=?, updated_at=?
                WHERE id=? AND status IN ('PENDING','REQUIRES_REVIEW')
                """,
                (channel_id, message_id, utc_now_ms(), registration_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esse cadastro não está mais aguardando revisão.")

    async def prepare_pending_review_delivery(self, registration_id: int):
        """Repair a stale result-delivery cycle before showing a pending review.

        This is a recovery guard for records created before review-cycle resets
        were enforced.  It deliberately preserves an already-persisted pending
        card pointer, so a reconnect can edit/reuse that card instead of
        deleting or duplicating it.
        """
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
            )
            record = await cursor.fetchone()
            if not record:
                raise NotFoundError("Cadastro não encontrado.")
            if record["status"] not in {"PENDING", "REQUIRES_REVIEW"}:
                raise ConflictError("Esse cadastro não está mais aguardando revisão.")
            stale_delivery = (
                record["delivery_status"] != "PENDING"
                or record["result_channel_id"] is not None
                or record["result_message_id"] is not None
                or record["reviewed_at"] is not None
                or record["reviewed_by"] is not None
                or record["review_reason"] is not None
            )
            if stale_delivery:
                await connection.execute(
                    """
                    UPDATE registration_gate_records
                    SET completed_at=NULL, reviewed_at=NULL, reviewed_by=NULL,
                        review_reason=NULL, result_channel_id=NULL, result_message_id=NULL,
                        delivery_status='PENDING', last_attempt_at=?, updated_at=?
                    WHERE id=? AND status IN ('PENDING','REQUIRES_REVIEW')
                    """,
                    (now, now, registration_id),
                )
                await connection.execute(
                    "DELETE FROM registration_delivery_claims WHERE registration_id=?",
                    (registration_id,),
                )
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
            )
            return await cursor.fetchone()

    async def mark_review_result_delivered(
        self,
        registration_id: int,
        *,
        actor_id: int | None,
        channel_id: int,
        message_id: int,
        claim_token: str | None = None,
    ) -> None:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?",
                (registration_id,),
            )
            record = await cursor.fetchone()
            if not record:
                raise NotFoundError("Cadastro não encontrado.")
            if record["status"] not in {"REGISTERED", "BLOCKED"} or not record["reviewed_at"]:
                raise ConflictError("Esse cadastro ainda não possui uma decisão final.")
            if (
                record["delivery_status"] == "DELIVERED"
                and int(record["result_channel_id"] or 0) == channel_id
                and int(record["result_message_id"] or 0) == message_id
            ):
                return
            if claim_token is not None:
                claim = await connection.execute(
                    """
                    SELECT 1 FROM registration_delivery_claims
                    WHERE registration_id=? AND phase='RESULT' AND claim_token=?
                    """,
                    (registration_id, claim_token),
                )
                if await claim.fetchone() is None:
                    raise ConflictError("A entrega do resultado foi assumida por outra instância.")
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET result_channel_id=?, result_message_id=?, delivery_status='DELIVERED',
                    updated_at=? WHERE id=?
                """,
                (channel_id, message_id, utc_now_ms(), registration_id),
            )
            await self.audit.record(
                int(record["guild_id"]),
                "REGISTRATION_REVIEW_RESULT_DELIVERED",
                actor_id=actor_id,
                target_id=int(record["discord_id"]),
                after={
                    "registration_id": registration_id,
                    "status": str(record["status"]),
                    "result_channel_id": channel_id,
                    "result_message_id": message_id,
                },
                connection=connection,
            )
            if claim_token is not None:
                await connection.execute(
                    """
                    DELETE FROM registration_delivery_claims
                    WHERE registration_id=? AND phase='RESULT' AND claim_token=?
                    """,
                    (registration_id, claim_token),
                )

    async def mark_review_cleanup_completed(
        self, registration_id: int, *, claim_token: str
    ) -> None:
        """Forget only the temporary-card pointer after its confirmed removal."""
        async with self.database.transaction() as connection:
            claim = await connection.execute(
                """
                SELECT 1 FROM registration_delivery_claims
                WHERE registration_id=? AND phase='CLEANUP' AND claim_token=?
                """,
                (registration_id, claim_token),
            )
            if await claim.fetchone() is None:
                raise ConflictError("A limpeza da ficha foi assumida por outra instância.")
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET review_channel_id=NULL, review_message_id=NULL, updated_at=?
                WHERE id=? AND status IN ('REGISTERED','BLOCKED')
                  AND reviewed_at IS NOT NULL AND delivery_status='DELIVERED'
                """,
                (utc_now_ms(), registration_id),
            )
            await connection.execute(
                """
                DELETE FROM registration_delivery_claims
                WHERE registration_id=? AND phase='CLEANUP' AND claim_token=?
                """,
                (registration_id, claim_token),
            )

    async def _member_by_discord(
        self, connection: aiosqlite.Connection, guild_id: int, discord_id: int
    ):
        cursor = await connection.execute(
            """
            SELECT m.*, r.name AS rank_name, r.level AS rank_level
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        return await cursor.fetchone()

    async def _member_by_bgr(
        self, connection: aiosqlite.Connection, guild_id: int, bgr_id: str
    ):
        cursor = await connection.execute(
            """
            SELECT m.*, r.name AS rank_name, r.level AS rank_level
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND lower(trim(m.character_id))=lower(trim(?))
            """,
            (guild_id, bgr_id),
        )
        return await cursor.fetchone()

    async def _recruitment_by_discord(
        self, connection: aiosqlite.Connection, guild_id: int, discord_id: int
    ):
        cursor = await connection.execute(
            """
            SELECT * FROM recruitment_applications
            WHERE guild_id=? AND discord_id=?
              AND status IN (
                'SUBMITTED','UNDER_REVIEW','INTERVIEW_PENDING','INTERVIEW_SCHEDULED',
                'INTERVIEW_COMPLETED','FINAL_REVIEW','APPROVED'
              )
            ORDER BY CASE status WHEN 'APPROVED' THEN 0 ELSE 1 END, updated_at DESC, id DESC
            LIMIT 1
            """,
            (guild_id, discord_id),
        )
        return await cursor.fetchone()

    @staticmethod
    def _normalize_identity(mta_nick: str, bgr_id: str) -> tuple[str, str]:
        nick = " ".join(mta_nick.split()).strip()
        normalized_id = normalize_bgr_id(bgr_id)
        if len(nick) < 2 or len(nick) > 32:
            raise ValidationError("O nick BGR deve possuir entre 2 e 32 caracteres.")
        return nick, normalized_id

    async def _event(
        self,
        connection: aiosqlite.Connection,
        *,
        guild_id: int,
        registration_id: int,
        event_type: str,
        actor_id: int | None,
        source: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if event_type not in REGISTRATION_EVENTS:
            raise ValueError(f"Evento de portaria desconhecido: {event_type}")
        await connection.execute(
            """
            INSERT INTO registration_gate_events(
                guild_id, registration_id, event_type, actor_id, source,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                registration_id,
                event_type,
                actor_id,
                source,
                json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                utc_now_ms(),
            ),
        )

    async def _upsert(
        self,
        connection: aiosqlite.Connection,
        *,
        guild_id: int,
        discord_id: int,
        status: str,
        access_tier: str,
        source: str,
        mta_nick: str | None = None,
        bgr_id: str | None = None,
        member_id: int | None = None,
        recruitment_application_id: int | None = None,
        conflict_code: str | None = None,
        conflict_member_id: int | None = None,
        sync_status: str = "NOT_REQUIRED",
        sync_error: str | None = None,
        idempotency_key: str | None = None,
        reviewed_by: int | None = None,
        review_reason: str | None = None,
    ):
        if status not in REGISTRATION_STATUSES or access_tier not in ACCESS_TIERS:
            raise ValueError("Estado inválido para a Portaria Digital.")
        now = utc_now_ms()
        submitted_at = now if status in {"PENDING", "REQUIRES_REVIEW", "REGISTERED"} else None
        completed_at = now if status == "REGISTERED" else None
        reviewed_at = now if reviewed_by else None
        await connection.execute(
            """
            INSERT INTO registration_gate_records(
                guild_id, discord_id, status, access_tier, mta_nick, bgr_id,
                member_id, recruitment_application_id, source, conflict_code,
                conflict_member_id, sync_status, sync_error, idempotency_key,
                submitted_at, completed_at, reviewed_at, reviewed_by, review_reason,
                last_attempt_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                status=excluded.status,
                access_tier=excluded.access_tier,
                mta_nick=COALESCE(excluded.mta_nick, registration_gate_records.mta_nick),
                bgr_id=COALESCE(excluded.bgr_id, registration_gate_records.bgr_id),
                member_id=excluded.member_id,
                recruitment_application_id=excluded.recruitment_application_id,
                source=excluded.source,
                conflict_code=excluded.conflict_code,
                conflict_member_id=excluded.conflict_member_id,
                sync_status=excluded.sync_status,
                sync_error=excluded.sync_error,
                idempotency_key=COALESCE(excluded.idempotency_key,
                                         registration_gate_records.idempotency_key),
                submitted_at=COALESCE(registration_gate_records.submitted_at,
                                      excluded.submitted_at),
                completed_at=excluded.completed_at,
                reviewed_at=excluded.reviewed_at,
                reviewed_by=excluded.reviewed_by,
                review_reason=excluded.review_reason,
                last_attempt_at=excluded.last_attempt_at,
                version=registration_gate_records.version+1,
                updated_at=excluded.updated_at
            """,
            (
                guild_id,
                discord_id,
                status,
                access_tier,
                mta_nick,
                bgr_id,
                member_id,
                recruitment_application_id,
                source,
                conflict_code,
                conflict_member_id,
                sync_status,
                sync_error,
                idempotency_key,
                submitted_at,
                completed_at,
                reviewed_at,
                reviewed_by,
                review_reason,
                now,
                now,
                now,
            ),
        )
        cursor = await connection.execute(
            "SELECT * FROM registration_gate_records WHERE guild_id=? AND discord_id=?",
            (guild_id, discord_id),
        )
        return await cursor.fetchone()

    async def _begin_review_delivery_cycle(
        self,
        connection: aiosqlite.Connection,
        registration_id: int,
        *,
        submitted_at: int,
    ) -> None:
        """Reset delivery state when one durable registration enters a new review cycle.

        A record is deliberately reused per guild/member.  Its final result and
        cleanup claim from a previous cycle must never authorize removal of the
        card that will represent the new pending review.
        """
        cursor = await connection.execute(
            """
            UPDATE registration_gate_records
            SET submitted_at=?, completed_at=NULL, reviewed_at=NULL, reviewed_by=NULL,
                review_reason=NULL, review_channel_id=NULL, review_message_id=NULL,
                result_channel_id=NULL, result_message_id=NULL,
                delivery_status='PENDING', last_attempt_at=?, updated_at=?
            WHERE id=? AND status IN ('PENDING','REQUIRES_REVIEW')
            """,
            (submitted_at, submitted_at, submitted_at, registration_id),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Esse cadastro não está mais aguardando revisão.")
        await connection.execute(
            "DELETE FROM registration_delivery_claims WHERE registration_id=?",
            (registration_id,),
        )

    async def registration_intent(self, guild_id: int, discord_id: int) -> dict[str, Any]:
        async with self.database.transaction() as connection:
            member = await self._member_by_discord(connection, guild_id, discord_id)
            recruitment = await self._recruitment_by_discord(connection, guild_id, discord_id)
            current_cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE guild_id=? AND discord_id=?",
                (guild_id, discord_id),
            )
            current = await current_cursor.fetchone()
            approved_recruitment_needs_registration = False
            if (
                member
                and member["status"] == "ACTIVE"
                and recruitment
                and recruitment["status"] == "APPROVED"
                and current
                and current["status"] == "REGISTERED"
                and int(current["recruitment_application_id"] or 0) == int(recruitment["id"])
            ):
                submitted_cursor = await connection.execute(
                    """
                    SELECT 1 FROM registration_gate_events
                    WHERE registration_id=? AND source='SELF_REGISTRATION'
                    LIMIT 1
                    """,
                    (int(current["id"]),),
                )
                approved_recruitment_needs_registration = await submitted_cursor.fetchone() is None
        # A aprovação do alistamento cria o vínculo operacional, mas não substitui a
        # identificação declarada pelo próprio recruta. Antes ela ficava parecendo um
        # cadastro concluído e escondia o formulário. O evento SELF_REGISTRATION é a
        # marca durável de que essa etapa já foi iniciada, inclusive após reconnect.
        if approved_recruitment_needs_registration:
            return {
                "mode": "FORM",
                "kind": "APPROVED_RECRUITMENT",
                "current": current,
            }
        if current and current["status"] in {"PENDING", "REQUIRES_REVIEW"}:
            return {"mode": "STATUS", "kind": str(current["status"]), "current": current}
        if (
            current
            and current["status"] == "BLOCKED"
            and current["conflict_code"] == "ADMIN_DEACTIVATED"
        ):
            return {"mode": "BLOCKED", "kind": "ADMIN_DEACTIVATED", "current": current}
        # A reabertura administrativa cria explicitamente um ciclo atual sem
        # cadastro. Ele precisa prevalecer sobre vínculos e candidaturas
        # históricos; caso contrário o botão persistente volta a mostrar a
        # situação antiga em vez de abrir o formulário do novo ciclo.
        if current and current["status"] == "UNREGISTERED" and not member:
            return {"mode": "FORM", "kind": "CURRENT_CYCLE", "current": current}
        if member:
            if member["status"] == "ACTIVE":
                if current and current["status"] == "REGISTERED" and current["reviewed_at"]:
                    return {"mode": "STATUS", "kind": "REGISTERED", "current": current}
                return {"mode": "FORM", "kind": "MEMBER_REVIEW", "current": current}
            return {"mode": "BLOCKED", "kind": "FORMER_MEMBER", "current": current}
        if recruitment:
            return {"mode": "CONFIRM_EXISTING", "kind": "CANDIDATE", "current": current}
        if current and current["status"] in {"PENDING", "REQUIRES_REVIEW", "REGISTERED"}:
            return {"mode": "STATUS", "kind": str(current["status"]), "current": current}
        return {"mode": "FORM", "kind": "VISITOR", "current": current}

    async def request_existing_member_review(self, guild_id: int, discord_id: int):
        """Encaminha um perfil legado para validação humana sem duplicá-lo.

        Reconciliações de startup anteriores podiam registrar um membro ativo como
        concluído sem que um responsável tivesse analisado a identidade. Esta operação
        reabre somente esses registros sem revisão; cadastros já decididos permanecem
        idempotentes e o acesso Discord atual não é alterado antes da decisão.
        """
        if await self.settings.get(guild_id, "security_lockdown", False):
            raise ValidationError("A Portaria está temporariamente bloqueada pelo modo de segurança.")
        if not await self.settings.get(guild_id, "registration_gate_enabled", False):
            raise ValidationError("A Portaria Digital ainda não foi ativada pela Administração.")

        now = utc_now_ms()
        async with self.database.transaction() as connection:
            member = await self._member_by_discord(connection, guild_id, discord_id)
            if not member or member["status"] != "ACTIVE":
                raise ConflictError("Não existe um perfil ativo para confirmar nesta conta.")
            if not member["character_id"]:
                raise ValidationError("Complete o Nick BGR e o ID BGR antes da revisão.")

            current_cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE guild_id=? AND discord_id=?",
                (guild_id, discord_id),
            )
            current = await current_cursor.fetchone()
            if current and current["status"] in {"PENDING", "REQUIRES_REVIEW"}:
                return current
            if current and current["status"] == "REGISTERED" and current["reviewed_at"]:
                return current
            if current and current["status"] == "BLOCKED" and current["reviewed_at"]:
                raise ConflictError("Este cadastro já foi analisado. Procure o suporte para revisão.")

            member_id = int(member["id"])
            record = await self._upsert(
                connection,
                guild_id=guild_id,
                discord_id=discord_id,
                status="REQUIRES_REVIEW",
                access_tier=self._tier_for_member(member),
                source="SELF_REGISTRATION",
                mta_nick=str(member["mta_nick"]),
                bgr_id=str(member["character_id"]),
                member_id=member_id,
                conflict_code="LEGACY_MEMBER_REVIEW_REQUIRED",
                conflict_member_id=member_id,
                sync_status="NOT_REQUIRED",
                idempotency_key=f"existing-review:{guild_id}:{discord_id}:{member_id}",
            )
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET submitted_at=?, completed_at=NULL, reviewed_at=NULL, reviewed_by=NULL,
                    review_reason=NULL, review_channel_id=NULL, review_message_id=NULL,
                    result_channel_id=NULL, result_message_id=NULL,
                    delivery_status='PENDING', updated_at=?
                WHERE id=?
                """,
                (now, now, int(record["id"])),
            )
            await self._event(
                connection,
                guild_id=guild_id,
                registration_id=int(record["id"]),
                event_type="REGISTRATION_REVIEW_REQUIRED",
                actor_id=discord_id,
                source="SELF_REGISTRATION",
                metadata={
                    "member_id": member_id,
                    "conflict_code": "LEGACY_MEMBER_REVIEW_REQUIRED",
                },
            )
            await self.audit.record(
                guild_id,
                "REGISTRATION_REVIEW_REQUIRED",
                actor_id=discord_id,
                target_id=discord_id,
                before={
                    "status": str(current["status"]) if current else None,
                    "source": str(current["source"]) if current else None,
                },
                after={
                    "registration_id": int(record["id"]),
                    "status": "REQUIRES_REVIEW",
                    "member_id": member_id,
                    "conflict_code": "LEGACY_MEMBER_REVIEW_REQUIRED",
                },
                connection=connection,
                deliver_immediately=False,
            )
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (int(record["id"]),)
            )
            return await cursor.fetchone()

    async def reopen_for_review(
        self,
        registration_id: int,
        *,
        actor_id: int | None,
        reason: str,
    ):
        """Reabre um cadastro vinculado sem apagar membro ou histórico.

        A operação deixa o registro sem decisão, mas não sincroniza cargos nem
        revoga acesso por conta própria. No próximo clique do titular, a Portaria
        abre novamente o formulário e a nova submissão segue para revisão humana.
        """
        normalized_reason = reason.strip()
        if len(normalized_reason) < 3:
            raise ValidationError("Informe o motivo da reabertura do cadastro.")
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
            )
            record = await cursor.fetchone()
            if not record:
                raise NotFoundError("Cadastro não encontrado.")
            if not record["member_id"]:
                compliance_cursor = await connection.execute(
                    """
                    SELECT 1 FROM rank_registration_compliance
                    WHERE guild_id=? AND discord_id=? AND status IN ('PENDING','EXPIRING')
                    LIMIT 1
                    """,
                    (int(record["guild_id"]), int(record["discord_id"])),
                )
                has_current_compliance = await compliance_cursor.fetchone() is not None
                recoverable_accidental_block = (
                    record["status"] == "BLOCKED"
                    and record["conflict_code"] == "ADMIN_DEACTIVATED"
                    and has_current_compliance
                )
                if not recoverable_accidental_block:
                    raise ConflictError(
                        "Somente cadastros vinculados ou um bloqueio administrativo com "
                        "cobrança funcional ativa podem ser reabertos por este fluxo."
                    )
            if record["status"] in {"PENDING", "REQUIRES_REVIEW"}:
                return record
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET status='UNREGISTERED', source='SYSTEM_RECONCILIATION', conflict_code=NULL,
                    conflict_member_id=NULL, sync_status='NOT_REQUIRED', sync_error=NULL,
                    idempotency_key=NULL, submitted_at=NULL, completed_at=NULL,
                    reviewed_at=NULL, reviewed_by=NULL, review_reason=NULL,
                    review_channel_id=NULL, review_message_id=NULL,
                    result_channel_id=NULL, result_message_id=NULL,
                    delivery_status='PENDING', version=version+1, updated_at=?
                WHERE id=?
                """,
                (now, registration_id),
            )
            await self._event(
                connection,
                guild_id=int(record["guild_id"]),
                registration_id=registration_id,
                event_type="REGISTRATION_RECONCILED",
                actor_id=actor_id,
                source="SYSTEM_RECONCILIATION",
                metadata={
                    "operation": "REOPEN_FOR_REVIEW",
                    "member_id": int(record["member_id"]) if record["member_id"] else None,
                },
            )
            await self.audit.record(
                int(record["guild_id"]),
                "REGISTRATION_REOPENED_FOR_REVIEW",
                actor_id=actor_id,
                target_id=int(record["discord_id"]),
                before={
                    "registration_id": registration_id,
                    "status": str(record["status"]),
                    "reviewed_at": record["reviewed_at"],
                },
                after={"registration_id": registration_id, "status": "UNREGISTERED"},
                reason=normalized_reason,
                connection=connection,
                deliver_immediately=False,
            )
        return await self.get(registration_id)

    async def directory(
        self,
        guild_id: int,
        *,
        query: str | None = None,
        page: int = 0,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Lista cadastros sem usar o nome visual como identidade interna."""
        normalized_query = (query or "").strip()[:100]
        safe_page_size = max(1, min(int(page_size), 25))
        where = "r.guild_id=?"
        parameters: list[Any] = [guild_id]
        if normalized_query:
            pattern = f"%{normalized_query}%"
            where += """
                AND (
                    CAST(r.id AS TEXT)=? OR CAST(r.discord_id AS TEXT) LIKE ?
                    OR r.mta_nick LIKE ? COLLATE NOCASE
                    OR r.bgr_id LIKE ? COLLATE NOCASE
                    OR m.unit LIKE ? COLLATE NOCASE
                    OR rk.name LIKE ? COLLATE NOCASE
                )
            """
            parameters.extend(
                [normalized_query, pattern, pattern, pattern, pattern, pattern]
            )
        total_row = await self.database.fetchone(
            f"""
            SELECT COUNT(*) AS total
            FROM registration_gate_records r
            LEFT JOIN members m ON m.id=r.member_id
            LEFT JOIN ranks rk ON rk.id=m.rank_id
            WHERE {where}
            """,
            tuple(parameters),
        )
        total = int(total_row["total"] if total_row else 0)
        pages = max(1, (total + safe_page_size - 1) // safe_page_size)
        safe_page = max(0, min(int(page), pages - 1))
        rows = await self.database.fetchall(
            f"""
            SELECT r.*, m.status AS member_status, m.unit, m.discord_nick,
                   rk.name AS rank_name
            FROM registration_gate_records r
            LEFT JOIN members m ON m.id=r.member_id
            LEFT JOIN ranks rk ON rk.id=m.rank_id
            WHERE {where}
            ORDER BY
                CASE r.status
                    WHEN 'REQUIRES_REVIEW' THEN 0
                    WHEN 'PENDING' THEN 1
                    WHEN 'BLOCKED' THEN 2
                    WHEN 'UNREGISTERED' THEN 3
                    ELSE 4
                END,
                COALESCE(r.mta_nick, m.mta_nick, '') COLLATE NOCASE,
                r.id
            LIMIT ? OFFSET ?
            """,
            (*parameters, safe_page_size, safe_page * safe_page_size),
        )
        return {
            "rows": rows,
            "query": normalized_query,
            "page": safe_page,
            "page_size": safe_page_size,
            "pages": pages,
            "total": total,
        }

    async def directory_record(self, registration_id: int):
        return await self.database.fetchone(
            """
            SELECT r.*, m.status AS member_status, m.unit, m.discord_nick,
                   m.joined_at, m.last_activity_at, rk.name AS rank_name
            FROM registration_gate_records r
            LEFT JOIN members m ON m.id=r.member_id
            LEFT JOIN ranks rk ON rk.id=m.rank_id
            WHERE r.id=?
            """,
            (registration_id,),
        )

    async def update_directory_identity(
        self,
        registration_id: int,
        *,
        actor_id: int,
        mta_nick: str,
        bgr_id: str,
        unit: str | None,
        reason: str,
    ):
        """Edita a identidade vinculada preservando registro e trilha de auditoria."""
        nick, normalized_id = self._normalize_identity(mta_nick, bgr_id)
        normalized_reason = reason.strip()
        if len(normalized_reason) < 3:
            raise ValidationError("Informe o motivo da edição do cadastro.")
        normalized_unit = (unit or "").strip() or None
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
            )
            record = await cursor.fetchone()
            if not record:
                raise NotFoundError("Cadastro não encontrado.")
            member = None
            if record["member_id"]:
                member_cursor = await connection.execute(
                    "SELECT * FROM members WHERE id=?", (int(record["member_id"]),)
                )
                member = await member_cursor.fetchone()
            conflict_cursor = await connection.execute(
                """
                SELECT id FROM members
                WHERE guild_id=? AND lower(trim(character_id))=lower(trim(?))
                  AND (? IS NULL OR id<>?)
                """,
                (
                    int(record["guild_id"]),
                    normalized_id,
                    record["member_id"],
                    record["member_id"],
                ),
            )
            if await conflict_cursor.fetchone():
                raise ConflictError("O ID BGR informado já pertence a outro membro.")
            before = {
                "mta_nick": record["mta_nick"],
                "bgr_id": record["bgr_id"],
                "unit": member["unit"] if member else None,
            }
            try:
                await connection.execute(
                    """
                    UPDATE registration_gate_records
                    SET mta_nick=?, bgr_id=?, source='ADMIN_APPROVAL',
                        reviewed_by=?, review_reason=?, version=version+1, updated_at=?
                    WHERE id=?
                    """,
                    (
                        nick,
                        normalized_id,
                        actor_id,
                        normalized_reason,
                        now,
                        registration_id,
                    ),
                )
                if member:
                    await connection.execute(
                        """
                        UPDATE members
                        SET mta_nick=?, character_id=?, unit=?, updated_at=?
                        WHERE id=?
                        """,
                        (nick, normalized_id, normalized_unit, now, int(member["id"])),
                    )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("O ID BGR informado já pertence a outro membro.") from exc
            await self._event(
                connection,
                guild_id=int(record["guild_id"]),
                registration_id=registration_id,
                event_type="REGISTRATION_RECONCILED",
                actor_id=actor_id,
                source="ADMIN_APPROVAL",
                metadata={"operation": "DIRECTORY_IDENTITY_EDITED"},
            )
            await self.audit.record(
                int(record["guild_id"]),
                "REGISTRATION_DIRECTORY_IDENTITY_EDITED",
                actor_id=actor_id,
                target_id=int(record["discord_id"]),
                before=before,
                after={"mta_nick": nick, "bgr_id": normalized_id, "unit": normalized_unit},
                reason=normalized_reason,
                connection=connection,
                deliver_immediately=False,
            )
            if record["status"] == "REGISTERED" and record["member_id"]:
                await self._enqueue_member_sync(
                    connection,
                    int(record["guild_id"]),
                    int(record["discord_id"]),
                    actor_id,
                )
        return await self.get(registration_id)

    async def deactivate_directory_registration(
        self,
        registration_id: int,
        *,
        actor_id: int,
        reason: str,
    ):
        """Desativa logicamente o acesso sem excluir o membro nem o histórico."""
        normalized_reason = reason.strip()
        if len(normalized_reason) < 3:
            raise ValidationError("Informe o motivo da desativação do cadastro.")
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
            )
            record = await cursor.fetchone()
            if not record:
                raise NotFoundError("Cadastro não encontrado.")
            if record["status"] == "BLOCKED" and record["conflict_code"] == "ADMIN_DEACTIVATED":
                raise ConflictError("Este cadastro já está desativado administrativamente.")
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET status='BLOCKED', access_tier='CANDIDATE',
                    source='ADMIN_APPROVAL', conflict_code='ADMIN_DEACTIVATED',
                    conflict_member_id=NULL, sync_status='PENDING', sync_error=NULL,
                    completed_at=NULL, reviewed_at=?, reviewed_by=?, review_reason=?,
                    version=version+1, updated_at=?
                WHERE id=?
                """,
                (now, actor_id, normalized_reason, now, registration_id),
            )
            await self._event(
                connection,
                guild_id=int(record["guild_id"]),
                registration_id=registration_id,
                event_type="REGISTRATION_ACCESS_REVOKED",
                actor_id=actor_id,
                source="ADMIN_APPROVAL",
                metadata={"operation": "DIRECTORY_LOGICAL_DEACTIVATION"},
            )
            await self.audit.record(
                int(record["guild_id"]),
                "REGISTRATION_DIRECTORY_DEACTIVATED",
                actor_id=actor_id,
                target_id=int(record["discord_id"]),
                before={
                    "registration_id": registration_id,
                    "status": str(record["status"]),
                    "conflict_code": record["conflict_code"],
                },
                after={
                    "registration_id": registration_id,
                    "status": "BLOCKED",
                    "conflict_code": "ADMIN_DEACTIVATED",
                },
                reason=normalized_reason,
                connection=connection,
                deliver_immediately=False,
            )
        return await self.get(registration_id)

    async def managed_rank_role_ids(self, guild_id: int) -> set[int]:
        rows = await self.database.fetchall(
            """
            SELECT discord_role_id FROM ranks
            WHERE guild_id=? AND active=1 AND discord_role_id IS NOT NULL
            """,
            (guild_id,),
        )
        role_ids = {int(row["discord_role_id"]) for row in rows}
        companion_role_id = await self.settings.get(guild_id, "companion_role_id")
        if companion_role_id:
            role_ids.add(int(companion_role_id))
        return role_ids

    async def registration_is_approved(self, guild_id: int, discord_id: int) -> bool:
        row = await self.database.fetchone(
            """
            SELECT 1 FROM registration_gate_records
            WHERE guild_id=? AND discord_id=? AND status='REGISTERED' AND member_id IS NOT NULL
            """,
            (guild_id, discord_id),
        )
        return row is not None

    async def ensure_rank_registration_compliance(
        self,
        guild_id: int,
        discord_id: int,
        rank_role_id: int,
        *,
        actor_id: int | None = None,
    ) -> tuple[Any | None, bool]:
        """Abre cobrança idempotente para patente ou Companheiro sem cadastro."""
        companion_role_id = await self.settings.get(guild_id, "companion_role_id")
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            rank_cursor = await connection.execute(
                """
                SELECT id, name FROM ranks
                WHERE guild_id=? AND discord_role_id=? AND active=1
                """,
                (guild_id, rank_role_id),
            )
            rank = await rank_cursor.fetchone()
            is_companion = bool(
                companion_role_id and int(companion_role_id) == int(rank_role_id)
            )
            if not rank and not is_companion:
                return None, False
            role_name = str(rank["name"]) if rank else "Companheiro de Farda"
            approved_cursor = await connection.execute(
                """
                SELECT 1 FROM registration_gate_records
                WHERE guild_id=? AND discord_id=? AND status='REGISTERED'
                  AND member_id IS NOT NULL
                """,
                (guild_id, discord_id),
            )
            if await approved_cursor.fetchone():
                return None, False
            existing_cursor = await connection.execute(
                """
                SELECT * FROM rank_registration_compliance
                WHERE guild_id=? AND discord_id=? AND rank_role_id=?
                  AND status IN ('PENDING','EXPIRING')
                """,
                (guild_id, discord_id, rank_role_id),
            )
            existing = await existing_cursor.fetchone()
            if existing:
                return existing, False
            cursor = await connection.execute(
                """
                INSERT INTO rank_registration_compliance(
                    guild_id, discord_id, rank_role_id, status, detected_at, due_at,
                    next_reminder_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'PENDING', ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    discord_id,
                    rank_role_id,
                    now,
                    now + RANK_COMPLIANCE_WINDOW_MS,
                    now,
                    now,
                    now,
                ),
            )
            compliance_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "RANK_WITHOUT_REGISTRATION_DETECTED",
                actor_id=actor_id,
                target_id=discord_id,
                after={
                    "compliance_id": compliance_id,
                    "rank_role_id": rank_role_id,
                    "rank_name": role_name,
                    "due_at": now + RANK_COMPLIANCE_WINDOW_MS,
                },
                connection=connection,
                deliver_immediately=False,
            )
            created_cursor = await connection.execute(
                "SELECT * FROM rank_registration_compliance WHERE id=?", (compliance_id,)
            )
            return await created_cursor.fetchone(), True

    async def cancel_obsolete_rank_compliance(
        self,
        guild_id: int,
        discord_id: int,
        current_rank_role_ids: set[int],
        *,
        actor_id: int | None = None,
    ) -> int:
        rows = await self.database.fetchall(
            """
            SELECT * FROM rank_registration_compliance
            WHERE guild_id=? AND discord_id=? AND status IN ('PENDING','EXPIRING')
            """,
            (guild_id, discord_id),
        )
        cancelled = 0
        for row in rows:
            if int(row["rank_role_id"]) in current_rank_role_ids:
                continue
            async with self.database.transaction() as connection:
                cursor = await connection.execute(
                    """
                    UPDATE rank_registration_compliance
                    SET status='CANCELLED', completed_at=?, completion_reason='RANK_REMOVED',
                        updated_at=?
                    WHERE id=? AND status IN ('PENDING','EXPIRING')
                    """,
                    (utc_now_ms(), utc_now_ms(), int(row["id"])),
                )
                if cursor.rowcount != 1:
                    continue
                cancelled += 1
                await self.audit.record(
                    guild_id,
                    "RANK_REGISTRATION_COMPLIANCE_CANCELLED",
                    actor_id=actor_id,
                    target_id=discord_id,
                    before={"status": str(row["status"])},
                    after={
                        "status": "CANCELLED",
                        "rank_role_id": int(row["rank_role_id"]),
                    },
                    reason="A patente monitorada foi removida antes do prazo.",
                    connection=connection,
                    deliver_immediately=False,
                )
        return cancelled

    async def resolve_rank_registration_compliance(
        self,
        guild_id: int,
        discord_id: int,
        *,
        actor_id: int | None = None,
    ) -> int:
        if not await self.registration_is_approved(guild_id, discord_id):
            return 0
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM rank_registration_compliance
                WHERE guild_id=? AND discord_id=? AND status IN ('PENDING','EXPIRING')
                """,
                (guild_id, discord_id),
            )
            rows = await cursor.fetchall()
            resolved = 0
            for row in rows:
                update = await connection.execute(
                    """
                    UPDATE rank_registration_compliance
                    SET status='COMPLETED', completed_at=?,
                        completion_reason='REGISTRATION_APPROVED', updated_at=?
                    WHERE id=? AND status IN ('PENDING','EXPIRING')
                    """,
                    (now, now, int(row["id"])),
                )
                if update.rowcount != 1:
                    continue
                resolved += 1
                await self.audit.record(
                    guild_id,
                    "RANK_REGISTRATION_COMPLIANCE_COMPLETED",
                    actor_id=actor_id,
                    target_id=discord_id,
                    before={"status": str(row["status"])},
                    after={
                        "status": "COMPLETED",
                        "rank_role_id": int(row["rank_role_id"]),
                    },
                    reason="Cadastro aprovado dentro do prazo.",
                    connection=connection,
                    deliver_immediately=False,
                )
            return resolved

    async def rank_compliance_directory(
        self,
        guild_id: int,
        *,
        page: int = 0,
        page_size: int = 25,
    ) -> dict[str, Any]:
        size = max(1, min(int(page_size), 25))
        total_row = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM rank_registration_compliance
            WHERE guild_id=? AND status IN ('PENDING','EXPIRING')
            """,
            (guild_id,),
        )
        total = int(total_row["total"] if total_row else 0)
        pages = max(1, (total + size - 1) // size)
        safe_page = max(0, min(int(page), pages - 1))
        rows = await self.database.fetchall(
            """
            SELECT c.*, r.name AS rank_name, g.status AS registration_status,
                   g.mta_nick, g.bgr_id
            FROM rank_registration_compliance c
            LEFT JOIN ranks r
              ON r.guild_id=c.guild_id AND r.discord_role_id=c.rank_role_id
            LEFT JOIN registration_gate_records g
              ON g.guild_id=c.guild_id AND g.discord_id=c.discord_id
            WHERE c.guild_id=? AND c.status IN ('PENDING','EXPIRING')
            ORDER BY c.due_at, c.id LIMIT ? OFFSET ?
            """,
            (guild_id, size, safe_page * size),
        )
        companion_role_id = await self.settings.get(guild_id, "companion_role_id")
        normalized_rows = [dict(row) for row in rows]
        for row in normalized_rows:
            if (
                not row["rank_name"]
                and companion_role_id
                and int(row["rank_role_id"]) == int(companion_role_id)
            ):
                row["rank_name"] = "Companheiro de Farda"
        return {
            "rows": normalized_rows,
            "page": safe_page,
            "page_size": size,
            "pages": pages,
            "total": total,
        }

    async def pending_rank_compliance_notifications(
        self, guild_id: int, *, limit: int = 25
    ):
        now = utc_now_ms()
        rows = await self.database.fetchall(
            """
            SELECT c.*, r.name AS rank_name
            FROM rank_registration_compliance c
            LEFT JOIN ranks r
              ON r.guild_id=c.guild_id AND r.discord_role_id=c.rank_role_id
            WHERE c.guild_id=? AND c.status='PENDING' AND c.due_at>?
              AND c.reminder_count<3
              AND COALESCE(c.next_reminder_at, c.detected_at)<=?
            ORDER BY c.next_reminder_at, c.id LIMIT ?
            """,
            (guild_id, now, now, max(1, min(limit, 100))),
        )
        companion_role_id = await self.settings.get(guild_id, "companion_role_id")
        normalized_rows = [dict(row) for row in rows]
        for row in normalized_rows:
            if (
                not row["rank_name"]
                and companion_role_id
                and int(row["rank_role_id"]) == int(companion_role_id)
            ):
                row["rank_name"] = "Companheiro de Farda"
        return normalized_rows

    async def mark_rank_compliance_dm(
        self,
        compliance_id: int,
        *,
        success: bool,
        message_id: int | None = None,
        error: str | None = None,
    ) -> None:
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM rank_registration_compliance WHERE id=?", (compliance_id,)
            )
            row = await cursor.fetchone()
            if not row or row["status"] != "PENDING":
                return
            reminder_count = int(row["reminder_count"]) + 1
            delay = RANK_COMPLIANCE_REMINDER_MS if success else RANK_COMPLIANCE_RETRY_MS
            next_at = min(int(row["due_at"]), now + delay)
            await connection.execute(
                """
                UPDATE rank_registration_compliance
                SET reminder_count=?, last_reminder_at=?, next_reminder_at=?,
                    dm_status=?, dm_message_id=?, dm_error=?, alert_status=?, updated_at=?
                WHERE id=? AND status='PENDING'
                """,
                (
                    reminder_count,
                    now,
                    next_at,
                    "SENT" if success else "FAILED",
                    message_id,
                    None if success else (error or "Falha ao enviar DM")[:500],
                    "NOT_REQUIRED" if success else "PENDING",
                    now,
                    compliance_id,
                ),
            )

    async def mark_rank_compliance_alert(
        self, compliance_id: int, *, success: bool, error: str | None = None
    ) -> None:
        await self.database.execute(
            """
            UPDATE rank_registration_compliance
            SET alert_status=?, alert_error=?, updated_at=? WHERE id=?
            """,
            (
                "SENT" if success else "FAILED",
                None if success else (error or "Falha ao alertar")[:500],
                utc_now_ms(),
                compliance_id,
            ),
        )

    async def expired_rank_compliance(self, guild_id: int, *, limit: int = 25):
        return await self.database.fetchall(
            """
            SELECT * FROM rank_registration_compliance
            WHERE guild_id=? AND status='PENDING' AND due_at<=?
            ORDER BY due_at, id LIMIT ?
            """,
            (guild_id, utc_now_ms(), max(1, min(limit, 100))),
        )

    async def claim_rank_compliance_expiration(self, compliance_id: int):
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM rank_registration_compliance WHERE id=?", (compliance_id,)
            )
            row = await cursor.fetchone()
            if not row or row["status"] != "PENDING" or int(row["due_at"]) > now:
                return None
            approved_cursor = await connection.execute(
                """
                SELECT 1 FROM registration_gate_records
                WHERE guild_id=? AND discord_id=? AND status='REGISTERED'
                  AND member_id IS NOT NULL
                """,
                (int(row["guild_id"]), int(row["discord_id"])),
            )
            if await approved_cursor.fetchone():
                await connection.execute(
                    """
                    UPDATE rank_registration_compliance
                    SET status='COMPLETED', completed_at=?,
                        completion_reason='REGISTRATION_APPROVED', updated_at=?
                    WHERE id=? AND status='PENDING'
                    """,
                    (now, now, compliance_id),
                )
                return None
            update = await connection.execute(
                """
                UPDATE rank_registration_compliance SET status='EXPIRING', updated_at=?
                WHERE id=? AND status='PENDING' AND due_at<=?
                """,
                (now, compliance_id, now),
            )
            if update.rowcount != 1:
                return None
            return row

    async def finalize_rank_compliance_expiration(
        self,
        compliance_id: int,
        *,
        removed: bool,
        reason: str,
    ) -> None:
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM rank_registration_compliance WHERE id=?", (compliance_id,)
            )
            row = await cursor.fetchone()
            if not row or row["status"] != "EXPIRING":
                return
            status = "EXPIRED" if removed else "PENDING"
            await connection.execute(
                """
                UPDATE rank_registration_compliance
                SET status=?, completed_at=?, completion_reason=?, alert_status=?,
                    next_reminder_at=?, updated_at=?
                WHERE id=? AND status='EXPIRING'
                """,
                (
                    status,
                    now if removed else None,
                    reason[:500],
                    "NOT_REQUIRED" if removed else "PENDING",
                    None if removed else now + RANK_COMPLIANCE_RETRY_MS,
                    now,
                    compliance_id,
                ),
            )
            await self.audit.record(
                int(row["guild_id"]),
                (
                    "RANK_REMOVED_AFTER_REGISTRATION_DEADLINE"
                    if removed
                    else "RANK_REGISTRATION_EXPIRATION_FAILED"
                ),
                target_id=int(row["discord_id"]),
                before={"status": "EXPIRING"},
                after={
                    "status": status,
                    "rank_role_id": int(row["rank_role_id"]),
                },
                reason=reason,
                connection=connection,
                deliver_immediately=False,
            )

    async def submit(
        self,
        guild_id: int,
        discord_id: int,
        *,
        mta_nick: str,
        bgr_id: str,
        discord_nick: str | None = None,
        idempotency_key: str | None = None,
    ):
        if await self.settings.get(guild_id, "security_lockdown", False):
            raise ValidationError("A Portaria está temporariamente bloqueada pelo modo de segurança.")
        if not await self.settings.get(guild_id, "registration_gate_enabled", False):
            raise ValidationError("A Portaria Digital ainda não foi ativada pela Administração.")
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            current_cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE guild_id=? AND discord_id=?",
                (guild_id, discord_id),
            )
            current = await current_cursor.fetchone()
            if current and current["status"] == "BLOCKED":
                if current["conflict_code"] == "ADMIN_DEACTIVATED":
                    raise ConflictError(
                        "Este cadastro foi desativado pela Administração. "
                        "Procure a Administração para orientação."
                    )
                raise ConflictError(
                    "Este cadastro está bloqueado. Procure a Administração para orientação."
                )

            # Um segundo envio nunca reinicia nem sobrescreve a ficha que já está
            # aguardando decisão humana, mesmo se o usuário digitar outro ID.
            if current and current["status"] in {"PENDING", "REQUIRES_REVIEW"}:
                result = dict(current)
                result["submission_outcome"] = "PENDING_EXISTING"
                return result

            member = await self._member_by_discord(connection, guild_id, discord_id)
            recruitment = await self._recruitment_by_discord(connection, guild_id, discord_id)
            compliance_cursor = await connection.execute(
                """
                SELECT * FROM rank_registration_compliance
                WHERE guild_id=? AND discord_id=? AND status IN ('PENDING','EXPIRING')
                ORDER BY detected_at, id
                LIMIT 1
                """,
                (guild_id, discord_id),
            )
            compliance = await compliance_cursor.fetchone()

            if member and member["status"] != "ACTIVE":
                raise ConflictError(
                    "Este vínculo não está ativo. Procure a Administração para orientação."
                )

            nick, normalized_id = self._normalize_identity(mta_nick, bgr_id)

            approved_recruitment_needs_registration = False
            if (
                member
                and member["status"] == "ACTIVE"
                and recruitment
                and recruitment["status"] == "APPROVED"
                and current
                and current["status"] == "REGISTERED"
                and int(current["recruitment_application_id"] or 0) == int(recruitment["id"])
            ):
                submitted_cursor = await connection.execute(
                    """
                    SELECT 1 FROM registration_gate_events
                    WHERE registration_id=? AND source='SELF_REGISTRATION'
                    LIMIT 1
                    """,
                    (int(current["id"]),),
                )
                approved_recruitment_needs_registration = (
                    await submitted_cursor.fetchone() is None
                )

            reopened_cycle = bool(current and current["status"] == "UNREGISTERED")
            registered_without_member = bool(
                current
                and current["status"] == "REGISTERED"
                and current["member_id"] is None
            )
            submitted_matches_member = bool(
                member
                and member["character_id"]
                and str(member["character_id"]).strip().lower() == normalized_id.lower()
            )
            if (
                member
                and submitted_matches_member
                and not reopened_cycle
                and not approved_recruitment_needs_registration
            ):
                result = dict(current) if current else {}
                result.update(
                    {
                        "status": "REGISTERED",
                        "access_tier": self._tier_for_member(member),
                        "sync_status": "NOT_REQUIRED",
                        "mta_nick": str(member["mta_nick"]),
                        "bgr_id": str(member["character_id"] or "") or None,
                        "member_id": int(member["id"]),
                        "submission_outcome": "ALREADY_REGISTERED",
                    }
                )
                return result
            if (
                current
                and current["status"] == "REGISTERED"
                and not approved_recruitment_needs_registration
                and not registered_without_member
                and not member
            ):
                result = dict(current)
                result["submission_outcome"] = "ALREADY_REGISTERED"
                return result

            key = idempotency_key or f"self:{guild_id}:{discord_id}:{normalized_id.lower()}"
            attempts_cursor = await connection.execute(
                """
                SELECT COUNT(*) AS total FROM registration_gate_events e
                JOIN registration_gate_records r ON r.id=e.registration_id
                WHERE r.guild_id=? AND r.discord_id=? AND e.event_type='REGISTRATION_STARTED'
                  AND e.created_at>=?
                """,
                (guild_id, discord_id, now - 10 * 60 * 1000),
            )
            if int((await attempts_cursor.fetchone())["total"]) >= 5:
                raise ValidationError("Muitas tentativas. Aguarde alguns minutos e tente novamente.")

            existing_key_cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE guild_id=? AND idempotency_key=?",
                (guild_id, key),
            )
            existing_key = await existing_key_cursor.fetchone()
            if existing_key and int(existing_key["discord_id"]) == discord_id:
                return existing_key

            conflicting_member = await self._member_by_bgr(connection, guild_id, normalized_id)

            status = "PENDING"
            tier = "CANDIDATE"
            member_id = None
            recruitment_id = None
            conflict_code = None
            conflict_member_id = None
            sync_status = "NOT_REQUIRED"
            event_type = "REGISTRATION_STARTED"

            if member:
                member_id = int(member["id"])
                if member["status"] == "ACTIVE":
                    tier = self._tier_for_member(member)
                    if conflicting_member and int(conflicting_member["id"]) != member_id:
                        status = "REQUIRES_REVIEW"
                        conflict_code = "BGR_ID_ALREADY_LINKED"
                        conflict_member_id = int(conflicting_member["id"])
                        event_type = "REGISTRATION_REVIEW_REQUIRED"
                    elif (
                        member["character_id"]
                        and str(member["character_id"]).strip().lower() != normalized_id.lower()
                    ):
                        status = "REQUIRES_REVIEW"
                        conflict_code = "DISCORD_IDENTITY_MISMATCH"
                        conflict_member_id = member_id
                        event_type = "REGISTRATION_REVIEW_REQUIRED"
                    else:
                        status = "REQUIRES_REVIEW"
                        conflict_code = "LEGACY_MEMBER_REVIEW_REQUIRED"
                        conflict_member_id = member_id
                        event_type = "REGISTRATION_REVIEW_REQUIRED"
                else:
                    status = "BLOCKED"
                    conflict_code = "FORMER_OR_INACTIVE_MEMBER"
                    event_type = "REGISTRATION_REVIEW_REQUIRED"
            elif conflicting_member:
                status = "REQUIRES_REVIEW"
                conflict_code = "BGR_ID_ALREADY_LINKED"
                conflict_member_id = int(conflicting_member["id"])
                event_type = "REGISTRATION_REVIEW_REQUIRED"
            elif recruitment:
                recruitment_id = int(recruitment["id"])
                expected_id = str(recruitment["bgr_id"] or "").strip()
                expected_nick = str(recruitment["candidate_nick"] or "").strip()
                if expected_id.lower() != normalized_id.lower():
                    status = "REQUIRES_REVIEW"
                    tier = "CANDIDATE"
                    conflict_code = "RECRUITMENT_IDENTITY_MISMATCH"
                    event_type = "REGISTRATION_REVIEW_REQUIRED"
                elif recruitment["status"] == "APPROVED":
                    member_id, tier = await self._create_effective_member(
                        connection,
                        guild_id=guild_id,
                        discord_id=discord_id,
                        discord_nick=discord_nick or nick,
                        mta_nick=expected_nick or nick,
                        bgr_id=normalized_id,
                        actor_id=discord_id,
                    )
                    status = "REGISTERED"
                    nick = expected_nick or nick
                    sync_status = "PENDING"
                    event_type = "REGISTRATION_COMPLETED"
                else:
                    status = "PENDING"
                    tier = "CANDIDATE"
                    nick = expected_nick or nick
                    conflict_code = "RECRUITMENT_APPROVAL_REQUIRED"
                    sync_status = "NOT_REQUIRED"
                    event_type = "REGISTRATION_REVIEW_REQUIRED"
            elif compliance:
                status = "PENDING"
                conflict_code = "FUNCTIONAL_ROLE_REVIEW_REQUIRED"
                sync_status = "NOT_REQUIRED"
                event_type = "REGISTRATION_REVIEW_REQUIRED"
            else:
                # A Portaria é o cadastro funcional da CHOQUE. Uma identidade válida e
                # sem conflito cria o membro canônico na mesma transação; nunca existe
                # um estado intermediário "cadastrado sem vínculo".
                member_id, tier = await self._create_effective_member(
                    connection,
                    guild_id=guild_id,
                    discord_id=discord_id,
                    discord_nick=discord_nick or nick,
                    mta_nick=nick,
                    bgr_id=normalized_id,
                    actor_id=discord_id,
                )
                status = "REGISTERED"
                sync_status = "PENDING"
                event_type = "REGISTRATION_COMPLETED"

            record = await self._upsert(
                connection,
                guild_id=guild_id,
                discord_id=discord_id,
                status=status,
                access_tier=tier,
                source="SELF_REGISTRATION",
                mta_nick=nick,
                bgr_id=normalized_id,
                member_id=member_id,
                recruitment_application_id=recruitment_id,
                conflict_code=conflict_code,
                conflict_member_id=conflict_member_id,
                sync_status=sync_status,
                idempotency_key=key,
            )
            if status in {"PENDING", "REQUIRES_REVIEW"}:
                await self._begin_review_delivery_cycle(
                    connection, int(record["id"]), submitted_at=now
                )
                cursor = await connection.execute(
                    "SELECT * FROM registration_gate_records WHERE id=?", (int(record["id"]),)
                )
                record = await cursor.fetchone()
            await self._event(
                connection,
                guild_id=guild_id,
                registration_id=int(record["id"]),
                event_type=event_type,
                actor_id=discord_id,
                source="SELF_REGISTRATION",
                metadata={"status": status, "access_tier": tier, "conflict_code": conflict_code},
            )
            await self.audit.record(
                guild_id,
                event_type,
                actor_id=discord_id,
                target_id=discord_id,
                after={"registration_id": int(record["id"]), "status": status, "tier": tier},
                connection=connection,
                deliver_immediately=False,
            )
        return await self.status(guild_id, discord_id)

    @staticmethod
    def _tier_for_member(member: Mapping[str, Any]) -> str:
        rank_name = normalize_stylized_label(str(member["rank_name"] or ""))
        return "RECRUIT" if "recruta" in rank_name else "MEMBER"

    @staticmethod
    async def _initial_rank(
        connection: aiosqlite.Connection,
        guild_id: int,
    ):
        cursor = await connection.execute(
            "SELECT id, name FROM ranks WHERE guild_id=? AND active=1 ORDER BY level, id",
            (guild_id,),
        )
        ranks = await cursor.fetchall()
        if not ranks:
            return None
        return next(
            (
                rank
                for rank in ranks
                if "recruta" in normalize_stylized_label(str(rank["name"] or ""))
            ),
            ranks[0],
        )

    async def _create_effective_member(
        self,
        connection: aiosqlite.Connection,
        *,
        guild_id: int,
        discord_id: int,
        discord_nick: str,
        mta_nick: str,
        bgr_id: str,
        actor_id: int,
    ) -> tuple[int, str]:
        now = utc_now_ms()
        rank = await self._initial_rank(connection, guild_id)
        rank_id = int(rank["id"]) if rank else None
        rank_name = str(rank["name"] or "") if rank else ""
        try:
            cursor = await connection.execute(
                """
                INSERT INTO members(
                    guild_id, discord_id, discord_nick, mta_nick, character_id,
                    rank_id, status, joined_at, last_activity_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    discord_id,
                    discord_nick,
                    mta_nick,
                    bgr_id,
                    rank_id,
                    now,
                    now,
                    now,
                    now,
                ),
            )
        except aiosqlite.IntegrityError as exc:
            raise ConflictError("Discord ou ID BGR já está vinculado a outro membro.") from exc
        member_id = int(cursor.lastrowid)
        await self._create_onboarding_checklist(connection, guild_id, member_id)
        await self._enqueue_member_sync(connection, guild_id, discord_id, actor_id)
        tier = (
            "RECRUIT"
            if "recruta" in normalize_stylized_label(rank_name)
            else "MEMBER"
        )
        return member_id, tier

    async def reconcile_identity(
        self,
        guild_id: int,
        discord_id: int,
        *,
        source: str = "SYSTEM_RECONCILIATION",
        actor_id: int | None = None,
    ):
        if source not in {"SYSTEM_RECONCILIATION", "REJOIN"}:
            raise ValueError("Origem de reconciliação inválida.")
        async with self.database.transaction() as connection:
            member = await self._member_by_discord(connection, guild_id, discord_id)
            recruitment = await self._recruitment_by_discord(connection, guild_id, discord_id)
            if member and member["status"] == "ACTIVE":
                status = "REGISTERED"
                tier = self._tier_for_member(member)
                sync_status = "PENDING"
                member_id = int(member["id"])
                recruitment_id = None
                nick = str(member["mta_nick"])
                bgr_id = str(member["character_id"] or "") or None
                conflict = None
            elif member:
                status = "BLOCKED"
                tier = "CANDIDATE"
                sync_status = "PENDING"
                member_id = int(member["id"])
                recruitment_id = None
                nick = str(member["mta_nick"])
                bgr_id = str(member["character_id"] or "") or None
                conflict = "FORMER_OR_INACTIVE_MEMBER"
            elif recruitment and recruitment["status"] == "APPROVED":
                member_id, tier = await self._create_effective_member(
                    connection,
                    guild_id=guild_id,
                    discord_id=discord_id,
                    discord_nick=str(recruitment["candidate_nick"]),
                    mta_nick=str(recruitment["candidate_nick"]),
                    bgr_id=str(recruitment["bgr_id"]),
                    actor_id=actor_id or discord_id,
                )
                status = "REGISTERED"
                sync_status = "PENDING"
                recruitment_id = int(recruitment["id"])
                nick = str(recruitment["candidate_nick"])
                bgr_id = str(recruitment["bgr_id"])
                conflict = None
            elif recruitment:
                status = "PENDING"
                tier = "CANDIDATE"
                sync_status = "NOT_REQUIRED"
                member_id = None
                recruitment_id = int(recruitment["id"])
                nick = str(recruitment["candidate_nick"])
                bgr_id = str(recruitment["bgr_id"])
                conflict = "RECRUITMENT_APPROVAL_REQUIRED"
            else:
                status = "UNREGISTERED"
                tier = "CANDIDATE"
                sync_status = "PENDING"
                member_id = None
                recruitment_id = None
                nick = None
                bgr_id = None
                conflict = None
            record = await self._upsert(
                connection,
                guild_id=guild_id,
                discord_id=discord_id,
                status=status,
                access_tier=tier,
                source=source,
                mta_nick=nick,
                bgr_id=bgr_id,
                member_id=member_id,
                recruitment_application_id=recruitment_id,
                conflict_code=conflict,
                sync_status=sync_status,
            )
            await self._event(
                connection,
                guild_id=guild_id,
                registration_id=int(record["id"]),
                event_type="REGISTRATION_RECONCILED",
                actor_id=actor_id,
                source=source,
                metadata={"status": status, "access_tier": tier},
            )
            await self.audit.record(
                guild_id,
                "REGISTRATION_RECONCILED",
                actor_id=actor_id,
                target_id=discord_id,
                after={"registration_id": int(record["id"]), "status": status, "tier": tier},
                connection=connection,
                deliver_immediately=False,
            )
        return await self.status(guild_id, discord_id)

    async def approve_new_member(
        self,
        registration_id: int,
        *,
        reviewer_id: int,
        reason: str,
        discord_nick: str,
    ):
        if not reason.strip():
            raise ValidationError("Informe o motivo da aprovação.")
        preliminary = await self.get(registration_id)
        if not preliminary:
            raise NotFoundError("Cadastro não encontrado.")
        companion_role_id = await self.settings.get(
            int(preliminary["guild_id"]), "companion_role_id"
        )
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
            )
            record = await cursor.fetchone()
            if not record:
                raise NotFoundError("Cadastro não encontrado.")
            if record["status"] not in {"PENDING", "REQUIRES_REVIEW"}:
                raise ConflictError("Este cadastro não está disponível para aprovação.")
            if record["conflict_member_id"]:
                raise ConflictError("Use o vínculo ao perfil existente para resolver este conflito.")
            compliance_cursor = await connection.execute(
                """
                SELECT c.*, r.id AS assigned_rank_id, r.name AS assigned_rank_name
                FROM rank_registration_compliance c
                LEFT JOIN ranks r
                  ON r.guild_id=c.guild_id AND r.discord_role_id=c.rank_role_id AND r.active=1
                WHERE c.guild_id=? AND c.discord_id=?
                  AND c.status IN ('PENDING','EXPIRING')
                ORDER BY CASE WHEN r.id IS NULL THEN 1 ELSE 0 END, c.detected_at, c.id
                LIMIT 1
                """,
                (record["guild_id"], record["discord_id"]),
            )
            compliance = await compliance_cursor.fetchone()
            is_companion = bool(
                compliance
                and companion_role_id
                and int(compliance["rank_role_id"]) == int(companion_role_id)
                and compliance["assigned_rank_id"] is None
            )
            rank_id = int(compliance["assigned_rank_id"]) if (
                compliance and compliance["assigned_rank_id"] is not None
            ) else None
            rank_name = str(compliance["assigned_rank_name"] or "") if compliance else ""
            if rank_id is None and not is_companion:
                rank = await self._initial_rank(connection, int(record["guild_id"]))
                rank_id = int(rank["id"]) if rank else None
                rank_name = str(rank["name"]) if rank else ""
            try:
                member_cursor = await connection.execute(
                    """
                    INSERT INTO members(
                        guild_id, discord_id, discord_nick, mta_nick, character_id,
                        rank_id, status, joined_at, last_activity_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
                    """,
                    (
                        record["guild_id"],
                        record["discord_id"],
                        discord_nick,
                        record["mta_nick"],
                        record["bgr_id"],
                        rank_id,
                        now,
                        now,
                        now,
                        now,
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("Discord ou ID BGR já está vinculado a outro membro.") from exc
            member_id = int(member_cursor.lastrowid)
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET status='REGISTERED', access_tier=?, member_id=?, conflict_code=NULL,
                    conflict_member_id=NULL, sync_status='PENDING', sync_error=NULL,
                    completed_at=?, reviewed_at=?, reviewed_by=?, review_reason=?,
                    version=version+1, updated_at=?
                WHERE id=? AND status IN ('PENDING','REQUIRES_REVIEW')
                """,
                (
                    (
                        "MEMBER"
                        if is_companion
                        else (
                            "RECRUIT"
                            if "recruta" in normalize_stylized_label(rank_name)
                            else "MEMBER"
                        )
                    ),
                    member_id,
                    now,
                    now,
                    reviewer_id,
                    reason.strip(),
                    now,
                    registration_id,
                ),
            )
            if not is_companion:
                await self._create_onboarding_checklist(
                    connection, int(record["guild_id"]), member_id
                )
            await self._enqueue_member_sync(
                connection,
                int(record["guild_id"]),
                int(record["discord_id"]),
                reviewer_id,
            )
            for event in ("REGISTRATION_APPROVED", "REGISTRATION_COMPLETED"):
                await self._event(
                    connection,
                    guild_id=int(record["guild_id"]),
                    registration_id=registration_id,
                    event_type=event,
                    actor_id=reviewer_id,
                    source="ADMIN_APPROVAL",
                    metadata={
                        "member_id": member_id,
                        "source": "COMPANION_ROLE" if is_companion else "AUTHORIZED_MEMBERSHIP",
                    },
                )
            await self.audit.record(
                int(record["guild_id"]),
                "REGISTRATION_APPROVED",
                actor_id=reviewer_id,
                target_id=int(record["discord_id"]),
                after={
                    "registration_id": registration_id,
                    "member_id": member_id,
                    "source": "COMPANION_ROLE" if is_companion else "AUTHORIZED_MEMBERSHIP",
                },
                reason=reason,
                connection=connection,
            )
        return await self.get(registration_id)

    async def link_existing_member(
        self,
        registration_id: int,
        *,
        member_id: int,
        reviewer_id: int,
        reason: str,
    ):
        if not reason.strip():
            raise ValidationError("Informe o motivo do vínculo.")
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            record_cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
            )
            record = await record_cursor.fetchone()
            member_cursor = await connection.execute(
                """
                SELECT m.*, r.name AS rank_name, r.level AS rank_level
                FROM members m LEFT JOIN ranks r ON r.id=m.rank_id WHERE m.id=?
                """,
                (member_id,),
            )
            member = await member_cursor.fetchone()
            if not record or not member or int(record["guild_id"]) != int(member["guild_id"]):
                raise NotFoundError("Cadastro ou perfil existente não encontrado.")
            if record["status"] not in {"PENDING", "REQUIRES_REVIEW", "BLOCKED"}:
                raise ConflictError("Este cadastro não pode mais ser vinculado.")
            occupied_cursor = await connection.execute(
                "SELECT id FROM members WHERE guild_id=? AND discord_id=? AND id<>?",
                (record["guild_id"], record["discord_id"], member_id),
            )
            if await occupied_cursor.fetchone():
                raise ConflictError("Este Discord já está associado a outro perfil.")
            old_discord_id = int(member["discord_id"])
            if old_discord_id != int(record["discord_id"]):
                old_registration = await self._upsert(
                    connection,
                    guild_id=int(record["guild_id"]),
                    discord_id=old_discord_id,
                    status="BLOCKED",
                    access_tier="CANDIDATE",
                    source="ADMIN_APPROVAL",
                    mta_nick=str(member["mta_nick"]),
                    bgr_id=str(member["character_id"] or "") or None,
                    conflict_code="IDENTITY_REBOUND_TO_ANOTHER_DISCORD",
                    conflict_member_id=member_id,
                    sync_status="PENDING",
                    reviewed_by=reviewer_id,
                    review_reason=reason,
                )
                await self._event(
                    connection,
                    guild_id=int(record["guild_id"]),
                    registration_id=int(old_registration["id"]),
                    event_type="REGISTRATION_ACCESS_REVOKED",
                    actor_id=reviewer_id,
                    source="ADMIN_APPROVAL",
                    metadata={"new_discord_id": int(record["discord_id"]), "member_id": member_id},
                )
            member_identity_missing = not str(member["character_id"] or "").strip()
            approved_nick = (
                str(record["mta_nick"])
                if member_identity_missing and record["mta_nick"]
                else str(member["mta_nick"])
            )
            approved_bgr_id = (
                str(record["bgr_id"])
                if member_identity_missing and record["bgr_id"]
                else member["character_id"]
            )
            await connection.execute(
                """
                UPDATE members
                SET discord_id=?, mta_nick=?, character_id=?, updated_at=?
                WHERE id=?
                """,
                (record["discord_id"], approved_nick, approved_bgr_id, now, member_id),
            )
            tier = (
                self._tier_for_member(member)
                if member["status"] == "ACTIVE"
                else "CANDIDATE"
            )
            status = "REGISTERED" if member["status"] == "ACTIVE" else "BLOCKED"
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET status=?, access_tier=?, mta_nick=?, bgr_id=?, member_id=?,
                    conflict_code=NULL, conflict_member_id=NULL, sync_status='PENDING',
                    sync_error=NULL, source='ADMIN_APPROVAL', completed_at=?, reviewed_at=?,
                    reviewed_by=?, review_reason=?, version=version+1, updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    tier,
                    approved_nick,
                    approved_bgr_id,
                    member_id,
                    now if status == "REGISTERED" else None,
                    now,
                    reviewer_id,
                    reason.strip(),
                    now,
                    registration_id,
                ),
            )
            if status == "REGISTERED":
                await self._enqueue_member_sync(
                    connection,
                    int(record["guild_id"]),
                    int(record["discord_id"]),
                    reviewer_id,
                )
            await self._event(
                connection,
                guild_id=int(record["guild_id"]),
                registration_id=registration_id,
                event_type="REGISTRATION_IDENTITY_LINKED",
                actor_id=reviewer_id,
                source="ADMIN_APPROVAL",
                metadata={"member_id": member_id, "previous_discord_id": old_discord_id},
            )
            await self.audit.record(
                int(record["guild_id"]),
                "REGISTRATION_IDENTITY_LINKED",
                actor_id=reviewer_id,
                target_id=int(record["discord_id"]),
                before={"member_id": member_id, "discord_id": old_discord_id},
                after={"member_id": member_id, "discord_id": int(record["discord_id"])},
                reason=reason,
                connection=connection,
            )
        return await self.get(registration_id)

    async def correct_bgr_id(
        self,
        registration_id: int,
        *,
        bgr_id: str,
        reviewer_id: int,
        reason: str,
    ):
        _, normalized_id = self._normalize_identity("OK", bgr_id)
        if not reason.strip():
            raise ValidationError("Informe o motivo da correção.")
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
            )
            record = await cursor.fetchone()
            if not record:
                raise NotFoundError("Cadastro não encontrado.")
            conflict = await self._member_by_bgr(connection, int(record["guild_id"]), normalized_id)
            if conflict and int(conflict["discord_id"]) != int(record["discord_id"]):
                raise ConflictError("O ID corrigido também pertence a outro perfil.")
            now = utc_now_ms()
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET bgr_id=?, status='PENDING', conflict_code=NULL, conflict_member_id=NULL,
                    reviewed_at=?, reviewed_by=?, review_reason=?, version=version+1, updated_at=?
                WHERE id=?
                """,
                (normalized_id, now, reviewer_id, reason.strip(), now, registration_id),
            )
            await self.audit.record(
                int(record["guild_id"]),
                "REGISTRATION_ID_CORRECTED",
                actor_id=reviewer_id,
                target_id=int(record["discord_id"]),
                before={"bgr_id": record["bgr_id"]},
                after={"bgr_id": normalized_id, "status": "PENDING"},
                reason=reason,
                connection=connection,
            )
        return await self.get(registration_id)

    async def reject(
        self, registration_id: int, *, reviewer_id: int, reason: str
    ):
        if not reason.strip():
            raise ValidationError("Informe o motivo da negativa.")
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
            )
            record = await cursor.fetchone()
            if not record:
                raise NotFoundError("Cadastro não encontrado.")
            if record["status"] not in {"PENDING", "REQUIRES_REVIEW"}:
                raise ConflictError("Este cadastro não está disponível para negativa.")
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET status='BLOCKED', sync_status='PENDING', source='ADMIN_APPROVAL',
                    reviewed_at=?, reviewed_by=?, review_reason=?, version=version+1, updated_at=?
                WHERE id=? AND status IN ('PENDING','REQUIRES_REVIEW')
                """,
                (now, reviewer_id, reason.strip(), now, registration_id),
            )
            await self._event(
                connection,
                guild_id=int(record["guild_id"]),
                registration_id=registration_id,
                event_type="REGISTRATION_REJECTED",
                actor_id=reviewer_id,
                source="ADMIN_APPROVAL",
                metadata={"reason": reason.strip()},
            )
            await self.audit.record(
                int(record["guild_id"]),
                "REGISTRATION_REJECTED",
                actor_id=reviewer_id,
                target_id=int(record["discord_id"]),
                before={"status": record["status"]},
                after={"status": "BLOCKED"},
                reason=reason,
                connection=connection,
            )
        return await self.get(registration_id)

    async def mark_sync(
        self,
        registration_id: int,
        *,
        success: bool,
        actor_id: int | None = None,
        error: str | None = None,
    ) -> bool:
        """Persist a real registration-sync transition exactly once.

        Gateway role events can be delivered more than once while Discord
        settles a member update.  A successful retry against an already
        ``SYNCED`` record is not an access grant and must not create another
        audit/history event.
        """
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM registration_gate_records WHERE id=?", (registration_id,)
            )
            record = await cursor.fetchone()
            if not record:
                raise NotFoundError("Cadastro não encontrado.")
            now = utc_now_ms()
            next_status = "SYNCED" if success else "FAILED"
            next_error = None if success else (error or "erro")[:500]
            if (
                str(record["sync_status"]) == next_status
                and (record["sync_error"] or None) == next_error
            ):
                return False
            await connection.execute(
                """
                UPDATE registration_gate_records SET sync_status=?, sync_error=?,
                    last_attempt_at=?, version=version+1, updated_at=? WHERE id=?
                """,
                (next_status, next_error, now, now, registration_id),
            )
            event_type = (
                "REGISTRATION_ACCESS_GRANTED"
                if success and record["status"] == "REGISTERED"
                else "REGISTRATION_ACCESS_REVOKED"
                if success
                else "REGISTRATION_SYNC_FAILED"
            )
            await self._event(
                connection,
                guild_id=int(record["guild_id"]),
                registration_id=registration_id,
                event_type=event_type,
                actor_id=actor_id,
                source="SYSTEM_RECONCILIATION",
                metadata={"error": error[:500] if error else None},
            )
            await self.audit.record(
                int(record["guild_id"]),
                event_type,
                actor_id=actor_id,
                target_id=int(record["discord_id"]),
                after={"registration_id": registration_id, "sync_status": "SYNCED" if success else "FAILED"},
                reason=error,
                connection=connection,
                deliver_immediately=False,
            )
            return True

    async def queue(self, guild_id: int, *, limit: int = 100):
        return await self.database.fetchall(
            """
            SELECT * FROM registration_gate_records
            WHERE guild_id=? AND status IN ('PENDING','REQUIRES_REVIEW')
            ORDER BY CASE status WHEN 'REQUIRES_REVIEW' THEN 0 ELSE 1 END,
                     submitted_at, id LIMIT ?
            """,
            (guild_id, max(1, min(limit, 250))),
        )

    async def pending_sync(self, guild_id: int, *, limit: int = 100):
        return await self.database.fetchall(
            """
            SELECT * FROM registration_gate_records
            WHERE guild_id=? AND sync_status IN ('PENDING','FAILED')
            ORDER BY last_attempt_at, updated_at, id LIMIT ?
            """,
            (guild_id, max(1, min(limit, 250))),
        )

    async def counts(self, guild_id: int) -> dict[str, int]:
        rows = await self.database.fetchall(
            """
            SELECT status, COUNT(*) AS total FROM registration_gate_records
            WHERE guild_id=? GROUP BY status
            """,
            (guild_id,),
        )
        result = {status: 0 for status in REGISTRATION_STATUSES}
        result.update({str(row["status"]): int(row["total"]) for row in rows})
        since = utc_now_ms() - 24 * 60 * 60 * 1000
        completed = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM registration_gate_records
            WHERE guild_id=? AND status='REGISTERED' AND completed_at>=?
            """,
            (guild_id, since),
        )
        missing_id = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM members
            WHERE guild_id=? AND status='ACTIVE'
              AND (character_id IS NULL OR trim(character_id)='')
            """,
            (guild_id,),
        )
        result["COMPLETED_LAST_24H"] = int(completed["total"] if completed else 0)
        result["MEMBERS_WITHOUT_ID"] = int(missing_id["total"] if missing_id else 0)
        return result

    async def set_configuration(
        self,
        guild_id: int,
        values: Mapping[str, Any],
        *,
        actor_id: int,
    ) -> dict[str, Any]:
        unknown = set(values) - GATE_SETTING_KEYS
        if unknown:
            raise ValidationError("Configurações desconhecidas: " + ", ".join(sorted(unknown)))
        before = {key: await self.settings.get(guild_id, key) for key in values}
        async with self.database.transaction() as connection:
            for key, value in values.items():
                await self.settings.set(guild_id, key, value, actor_id, connection)
            await self.audit.record(
                guild_id,
                "REGISTRATION_GATE_CONFIGURATION_CHANGED",
                actor_id=actor_id,
                before=before,
                after=dict(values),
                connection=connection,
            )
        return {key: await self.settings.get(guild_id, key) for key in GATE_SETTING_KEYS}

    async def classify_resource(
        self,
        guild_id: int,
        *,
        resource_type: str,
        resource_id: int,
        internal_key: str,
        access_class: str,
        actor_id: int | None,
    ) -> None:
        normalized_type = resource_type.upper()
        normalized_class = access_class.upper()
        if normalized_type not in {"CATEGORY", "CHANNEL"}:
            raise ValidationError("Tipo de recurso inválido.")
        if normalized_class not in ACCESS_CLASSES:
            raise ValidationError("Classificação de acesso inválida.")
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO registration_access_classifications(
                    guild_id, resource_type, resource_id, internal_key, access_class,
                    created_at, created_by, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, resource_type, resource_id) DO UPDATE SET
                    internal_key=excluded.internal_key, access_class=excluded.access_class,
                    updated_at=excluded.updated_at, updated_by=excluded.updated_by
                """,
                (
                    guild_id,
                    normalized_type,
                    resource_id,
                    internal_key,
                    normalized_class,
                    now,
                    actor_id,
                    now,
                    actor_id,
                ),
            )

    async def classifications(self, guild_id: int):
        return await self.database.fetchall(
            """
            SELECT * FROM registration_access_classifications
            WHERE guild_id=? ORDER BY resource_type, internal_key
            """,
            (guild_id,),
        )

    async def store_permission_snapshot(
        self,
        guild_id: int,
        snapshot: Mapping[str, Any],
        *,
        actor_id: int | None,
        status: str = "PREVIEW",
    ) -> str:
        operation_id = str(uuid.uuid4())
        payload = json.dumps(dict(snapshot), ensure_ascii=False, sort_keys=True)
        await self.database.execute(
            """
            INSERT INTO registration_permission_snapshots(
                guild_id, operation_id, snapshot_json, snapshot_sha256,
                status, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                operation_id,
                payload,
                hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                status,
                actor_id,
                utc_now_ms(),
            ),
        )
        return operation_id

    async def record_finding(
        self,
        guild_id: int,
        finding_type: str,
        *,
        fingerprint: str,
        evidence: Mapping[str, Any],
        resource_id: int | None = None,
        discord_id: int | None = None,
    ) -> None:
        now = utc_now_ms()
        await self.database.execute(
            """
            INSERT INTO registration_access_findings(
                guild_id, finding_type, resource_id, discord_id, evidence_json,
                fingerprint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, fingerprint) DO UPDATE SET
                evidence_json=excluded.evidence_json, status='OPEN',
                resolved_at=NULL, resolution=NULL
            """,
            (
                guild_id,
                finding_type,
                resource_id,
                discord_id,
                json.dumps(dict(evidence), ensure_ascii=False, sort_keys=True),
                fingerprint,
                now,
            ),
        )

    async def _enqueue_member_sync(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        discord_id: int,
        actor_id: int,
    ) -> None:
        now = utc_now_ms()
        await connection.execute(
            """
            INSERT INTO web_action_outbox(
                guild_id, action_type, target_discord_id, payload_json,
                requested_by, correlation_id, available_at, created_at
            ) VALUES (?, 'MEMBER_SYNC', ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                discord_id,
                json.dumps(
                    {"source": "REGISTRATION", "flow": "PORTARIA_DIGITAL"},
                    ensure_ascii=False,
                ),
                actor_id,
                str(uuid.uuid4()),
                now,
                now,
            ),
        )

    async def _create_onboarding_checklist(
        self, connection: aiosqlite.Connection, guild_id: int, member_id: int
    ) -> None:
        await connection.execute(
            """
            INSERT INTO recruit_onboarding_checklists(
                guild_id, member_id, registration_status, updated_at
            ) VALUES (?, ?, 'COMPLETED', ?)
            ON CONFLICT(guild_id, member_id) DO UPDATE SET
                registration_status='COMPLETED', updated_at=excluded.updated_at
            """,
            (guild_id, member_id, utc_now_ms()),
        )
