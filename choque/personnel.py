from __future__ import annotations

import json
import uuid
from collections.abc import Callable

import aiosqlite

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from .models import AbsenceStatus, MemberStatus, PersonnelActionType, PunishmentType
from .shift_validation import closed_validation_values, countable_shift_clause
from .time_utils import utc_now_ms


class PersonnelService:
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

    async def change_rank(
        self,
        guild_id: int,
        discord_id: int,
        action: PersonnelActionType,
        actor_id: int,
        reason: str,
    ) -> dict[str, object]:
        targets = await self.rank_targets(guild_id, discord_id, action)
        if not targets:
            message = (
                "O membro já está na patente mais alta."
                if action is PersonnelActionType.PROMOTION
                else "O membro já está na patente mais baixa."
            )
            raise ConflictError(message)
        return await self.change_rank_to(
            guild_id,
            discord_id,
            int(targets[0]["id"]),
            action,
            actor_id,
            reason,
        )

    async def rank_targets(
        self,
        guild_id: int,
        discord_id: int,
        action: PersonnelActionType,
    ):
        member = await self.career_profile(guild_id, discord_id)
        if member["status"] == MemberStatus.DISMISSED.value:
            raise ConflictError("Membro desligado não pode ter a patente alterada.")
        if action is PersonnelActionType.PROMOTION:
            operator, order = ">", "ASC"
            current_level = int(member["rank_level"] or 0)
        else:
            if member["rank_level"] is None:
                raise ConflictError("O membro ainda não possui patente.")
            operator, order = "<", "DESC"
            current_level = int(member["rank_level"])
        return await self.database.fetchall(
            f"""
            SELECT id, level, name, prefix, discord_role_id
            FROM ranks WHERE guild_id=? AND active=1 AND level {operator} ?
            ORDER BY level {order}
            """,
            (guild_id, current_level),
        )

    async def change_rank_to(
        self,
        guild_id: int,
        discord_id: int,
        target_rank_id: int,
        action: PersonnelActionType,
        actor_id: int,
        reason: str,
        *,
        enqueue_discord_sync: bool = False,
        source: str = "MANUAL",
        evidence_locator: str | None = None,
        observations: str | None = None,
        article_code: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, object]:
        movement_reason = reason.strip()
        if not movement_reason:
            raise ValidationError("Informe o motivo da movimentação.")
        if discord_id == actor_id:
            raise PermissionDenied("Você não pode alterar a própria patente.")
        source = source.strip().upper()
        if source not in {"MANUAL", "OFFICER_DECISION", "DISCORD_SYNC"}:
            raise ValidationError("Origem da movimentação inválida.")
        action_correlation_id = correlation_id or str(uuid.uuid4())
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT m.id, m.status, m.rank_id, m.mta_nick, m.character_id,
                       r.level AS rank_level, r.name AS rank_name,
                       r.discord_role_id AS rank_role_id
                FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
                WHERE m.guild_id=? AND m.discord_id=?
                """,
                (guild_id, discord_id),
            )
            member = await cursor.fetchone()
            if not member:
                raise NotFoundError("Membro não cadastrado.")
            if member["status"] == MemberStatus.DISMISSED.value:
                raise ConflictError("Membro desligado não pode ter a patente alterada.")
            cursor = await connection.execute(
                """
                SELECT id, level, name, prefix, discord_role_id
                FROM ranks WHERE guild_id=? AND id=? AND active=1
                """,
                (guild_id, target_rank_id),
            )
            target = await cursor.fetchone()
            if not target:
                raise NotFoundError("A patente selecionada não está ativa.")
            current_level = int(member["rank_level"] or 0)
            target_level = int(target["level"])
            if action is PersonnelActionType.PROMOTION and target_level <= current_level:
                raise ValidationError("A nova patente precisa estar acima da patente atual.")
            if action is PersonnelActionType.DEMOTION:
                if member["rank_level"] is None or target_level >= current_level:
                    raise ValidationError("A nova patente precisa estar abaixo da patente atual.")

            now = self.clock()
            cursor = await connection.execute(
                """
                UPDATE members SET rank_id=?, updated_at=?
                WHERE id=? AND (
                    rank_id=? OR (rank_id IS NULL AND ? IS NULL)
                )
                """,
                (target["id"], now, member["id"], member["rank_id"], member["rank_id"]),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A patente do membro foi alterada simultaneamente.")
            cursor = await connection.execute(
                """
                INSERT INTO personnel_actions(
                    guild_id, member_id, discord_id, action_type, from_rank_id,
                    to_rank_id, reason, actor_id, created_at, source,
                    evidence_locator, observations, article_code, correlation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    member["id"],
                    discord_id,
                    action.value,
                    member["rank_id"],
                    target["id"],
                    movement_reason,
                    actor_id,
                    now,
                    source,
                    evidence_locator.strip() if evidence_locator else None,
                    observations.strip() if observations else None,
                    article_code.strip() if article_code else None,
                    action_correlation_id,
                ),
            )
            action_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                f"MEMBER_{action.value}",
                actor_id=actor_id,
                target_id=discord_id,
                before={"rank_id": member["rank_id"], "rank_name": member["rank_name"]},
                after={
                    "rank_id": target["id"],
                    "rank_name": target["name"],
                    "source": source,
                    "evidence_locator": evidence_locator,
                    "observations": observations,
                    "article_code": article_code,
                },
                reason=movement_reason,
                correlation_id=f"personnel-rank-{action_correlation_id}",
                connection=connection,
            )
            notification_type = (
                "PROMOTION"
                if action is PersonnelActionType.PROMOTION
                else "DEMOTION"
            )
            channel_setting_key = (
                "career_promotion_channel_id"
                if action is PersonnelActionType.PROMOTION
                else "career_demotion_channel_id"
            )
            await connection.execute(
                """
                INSERT OR IGNORE INTO career_notifications(
                    guild_id, notification_type, subject_id, target_discord_id,
                    channel_setting_key, payload_json, status, attempts,
                    available_at, correlation_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    notification_type,
                    action_id,
                    discord_id,
                    channel_setting_key,
                    json.dumps(
                        {
                            "discord_id": discord_id,
                            "from_rank_name": member["rank_name"],
                            "to_rank_name": target["name"],
                            "reason": movement_reason,
                            "source": source,
                            "actor_id": actor_id,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                    f"personnel-notification-{action_correlation_id}",
                    now,
                    now,
                ),
            )
            sync_correlation_id = None
            if enqueue_discord_sync:
                sync_correlation_id = str(uuid.uuid4())
                await connection.execute(
                    """
                    INSERT INTO web_action_outbox(
                        guild_id, action_type, target_discord_id, payload_json,
                        requested_by, correlation_id, available_at, created_at
                    ) VALUES (?, 'RANK_SYNC', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        discord_id,
                        json.dumps(
                            {
                                "action": action.value,
                                "from_rank_id": member["rank_id"],
                                "to_rank_id": target["id"],
                            },
                            ensure_ascii=False,
                        ),
                        actor_id,
                        sync_correlation_id,
                        now,
                        now,
                    ),
                )
        return {
            "action_id": action_id,
            "action": action.value,
            "discord_id": discord_id,
            "mta_nick": member["mta_nick"],
            "character_id": member["character_id"],
            "from_rank_id": member["rank_id"],
            "from_rank_name": member["rank_name"],
            "from_role_id": member["rank_role_id"],
            "to_rank_id": target["id"],
            "to_rank_name": target["name"],
            "to_prefix": target["prefix"],
            "to_role_id": target["discord_role_id"],
            "sync_correlation_id": sync_correlation_id,
            "correlation_id": action_correlation_id,
        }

    async def career_profile(self, guild_id: int, discord_id: int):
        row = await self.database.fetchone(
            """
            SELECT m.*, r.name AS rank_name, r.prefix AS rank_prefix,
                   r.level AS rank_level, r.discord_role_id AS rank_role_id,
                   COALESCE((
                       SELECT MAX(changed_at) FROM (
                           SELECT pa.created_at AS changed_at
                           FROM personnel_actions pa
                           WHERE pa.guild_id=m.guild_id AND pa.member_id=m.id
                             AND pa.to_rank_id=m.rank_id
                           UNION ALL
                           SELECT rse.created_at AS changed_at
                           FROM rank_sync_events rse
                           WHERE rse.guild_id=m.guild_id AND rse.member_id=m.id
                             AND rse.to_rank_id=m.rank_id
                             AND rse.from_rank_id IS NOT rse.to_rank_id
                       )
                   ), m.joined_at) AS rank_since,
                   (SELECT COUNT(*) FROM punishments p
                    WHERE p.guild_id=m.guild_id AND p.member_id=m.id
                      AND p.punishment_type='WARNING' AND p.status='ACTIVE') AS active_warnings
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        if not row:
            raise NotFoundError("Membro não cadastrado.")
        return row

    async def career_history(
        self,
        guild_id: int,
        discord_id: int,
        *,
        limit: int = 10,
        offset: int = 0,
    ):
        return await self.database.fetchall(
            """
            SELECT * FROM (
                SELECT 'P-' || pa.id AS id, pa.action_type,
                       pa.from_rank_id, pa.to_rank_id, pa.actor_id, pa.reason,
                       pa.created_at, pa.source,
                       pa.evidence_locator, pa.observations, pa.article_code,
                       fr.name AS from_rank_name, tr.name AS to_rank_name
                FROM personnel_actions pa
                LEFT JOIN ranks fr ON fr.id=pa.from_rank_id
                LEFT JOIN ranks tr ON tr.id=pa.to_rank_id
                WHERE pa.guild_id=? AND pa.discord_id=?
                UNION ALL
                SELECT 'S-' || rse.id AS id, rse.event_type AS action_type,
                       rse.from_rank_id, rse.to_rank_id, rse.actor_id,
                       'Sincronização automática de patente' AS reason,
                       rse.created_at, rse.source,
                       NULL AS evidence_locator, NULL AS observations,
                       NULL AS article_code,
                       fr.name AS from_rank_name, tr.name AS to_rank_name
                FROM rank_sync_events rse
                LEFT JOIN ranks fr ON fr.id=rse.from_rank_id
                LEFT JOIN ranks tr ON tr.id=rse.to_rank_id
                WHERE rse.guild_id=? AND rse.discord_id=?
                  AND rse.from_rank_id IS NOT rse.to_rank_id
            ) history
            ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
            """,
            (guild_id, discord_id, guild_id, discord_id, limit, offset),
        )

    async def career_history_count(self, guild_id: int, discord_id: int) -> int:
        row = await self.database.fetchone(
            """
            SELECT (
                (SELECT COUNT(*) FROM personnel_actions WHERE guild_id=? AND discord_id=?) +
                (SELECT COUNT(*) FROM rank_sync_events
                 WHERE guild_id=? AND discord_id=? AND from_rank_id IS NOT to_rank_id)
            ) AS total
            """,
            (guild_id, discord_id, guild_id, discord_id),
        )
        return int(row["total"])

    async def apply_punishment(
        self,
        guild_id: int,
        discord_id: int,
        punishment_type: PunishmentType,
        actor_id: int,
        reason: str,
        *,
        duration_days: int | None = None,
    ) -> dict[str, object]:
        if not reason.strip():
            raise ValidationError("Informe o motivo da punição.")
        if punishment_type is PunishmentType.SUSPENSION and (
            duration_days is None or not 1 <= duration_days <= 365
        ):
            raise ValidationError("A suspensão deve durar entre 1 e 365 dias.")
        now = self.clock()
        ends_at = now + duration_days * 86_400_000 if duration_days else None
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT id, status FROM members WHERE guild_id=? AND discord_id=?",
                (guild_id, discord_id),
            )
            member = await cursor.fetchone()
            if not member:
                raise NotFoundError("Membro não cadastrado.")
            if punishment_type is not PunishmentType.WARNING:
                cursor = await connection.execute(
                    """
                    SELECT id FROM punishments
                    WHERE guild_id=? AND member_id=? AND punishment_type=?
                      AND status IN ('SCHEDULED','ACTIVE')
                    """,
                    (guild_id, member["id"], punishment_type.value),
                )
                if await cursor.fetchone():
                    raise ConflictError("Já existe uma punição ativa desse tipo.")
            if punishment_type is PunishmentType.DISMISSAL and (
                member["status"] == MemberStatus.DISMISSED.value
            ):
                raise ConflictError("O membro já está desligado.")

            cursor = await connection.execute(
                """
                INSERT INTO punishments(
                    guild_id, member_id, discord_id, punishment_type, reason,
                    previous_member_status, starts_at, ends_at, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    member["id"],
                    discord_id,
                    punishment_type.value,
                    reason.strip(),
                    member["status"],
                    now,
                    ends_at,
                    actor_id,
                    now,
                ),
            )
            punishment_id = int(cursor.lastrowid)
            new_status = member["status"]
            if punishment_type is PunishmentType.SUSPENSION:
                new_status = MemberStatus.SUSPENDED.value
            elif punishment_type is PunishmentType.DISMISSAL:
                new_status = MemberStatus.DISMISSED.value
            if new_status != member["status"]:
                await connection.execute(
                    "UPDATE members SET status=?, updated_at=? WHERE id=?",
                    (new_status, now, member["id"]),
                )
            await self.audit.record(
                guild_id,
                "PUNISHMENT_APPLIED",
                actor_id=actor_id,
                target_id=discord_id,
                before={"member_status": member["status"]},
                after={
                    "punishment_id": punishment_id,
                    "type": punishment_type.value,
                    "member_status": new_status,
                    "ends_at": ends_at,
                },
                reason=reason.strip(),
                connection=connection,
            )
        return {
            "punishment_id": punishment_id,
            "type": punishment_type.value,
            "status": new_status,
            "ends_at": ends_at,
        }

    async def active_punishments(self, guild_id: int, discord_id: int):
        return await self.database.fetchall(
            """
            SELECT * FROM punishments
            WHERE guild_id=? AND discord_id=? AND status IN ('SCHEDULED','ACTIVE')
            ORDER BY created_at DESC
            """,
            (guild_id, discord_id),
        )

    async def revoke_punishment(
        self,
        guild_id: int,
        punishment_id: int,
        actor_id: int,
        reason: str,
    ) -> dict[str, object]:
        if not reason.strip():
            raise ValidationError("Informe o motivo da revogação.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM punishments WHERE id=? AND guild_id=?",
                (punishment_id, guild_id),
            )
            punishment = await cursor.fetchone()
            if not punishment:
                raise NotFoundError("Punição não encontrada.")
            if punishment["status"] not in {"SCHEDULED", "ACTIVE"}:
                raise ConflictError("Essa punição não está ativa.")
            await connection.execute(
                """
                UPDATE punishments SET status='REVOKED', revoked_by=?, revoked_at=?,
                    revoke_reason=? WHERE id=? AND status IN ('SCHEDULED','ACTIVE')
                """,
                (actor_id, now, reason.strip(), punishment_id),
            )
            if (
                punishment["punishment_type"] == PunishmentType.WARNING.value
                or punishment["status"] == "SCHEDULED"
            ):
                cursor = await connection.execute(
                    "SELECT status FROM members WHERE id=?", (punishment["member_id"],)
                )
                new_status = (await cursor.fetchone())["status"]
            else:
                new_status = await self._effective_status(
                    connection,
                    guild_id,
                    int(punishment["member_id"]),
                    now,
                    fallback=str(punishment["previous_member_status"] or MemberStatus.ACTIVE.value),
                )
                await connection.execute(
                    "UPDATE members SET status=?, updated_at=? WHERE id=?",
                    (new_status, now, punishment["member_id"]),
                )
            await self.audit.record(
                guild_id,
                "PUNISHMENT_REVOKED",
                actor_id=actor_id,
                target_id=int(punishment["discord_id"]),
                before={"punishment_id": punishment_id, "status": punishment["status"]},
                after={"status": "REVOKED", "member_status": new_status},
                reason=reason.strip(),
                connection=connection,
            )
        return {
            "punishment_id": punishment_id,
            "discord_id": int(punishment["discord_id"]),
            "member_status": new_status,
        }

    async def submit_absence(
        self,
        guild_id: int,
        discord_id: int,
        starts_at: int,
        ends_at: int,
        reason: str,
        observation: str | None = None,
    ) -> int:
        now = self.clock()
        if not reason.strip():
            raise ValidationError("Informe o motivo do afastamento.")
        if starts_at >= ends_at:
            raise ValidationError("A data final deve ser posterior à data inicial.")
        if ends_at <= now:
            raise ValidationError("A data final precisa estar no futuro.")
        if ends_at - starts_at > 366 * 86_400_000:
            raise ValidationError("O afastamento não pode ultrapassar 366 dias.")
        try:
            async with self.database.transaction() as connection:
                cursor = await connection.execute(
                    "SELECT id, status FROM members WHERE guild_id=? AND discord_id=?",
                    (guild_id, discord_id),
                )
                member = await cursor.fetchone()
                if not member:
                    raise NotFoundError("Você ainda não possui cadastro aprovado.")
                if member["status"] in {
                    MemberStatus.SUSPENDED.value,
                    MemberStatus.DISMISSED.value,
                }:
                    raise ConflictError("Seu status atual não permite solicitar afastamento.")
                cursor = await connection.execute(
                    """
                    INSERT INTO absence_requests(
                        guild_id, member_id, discord_id, starts_at, ends_at,
                        reason, observation, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        member["id"],
                        discord_id,
                        starts_at,
                        ends_at,
                        reason.strip(),
                        observation.strip() if observation else None,
                        now,
                    ),
                )
                absence_id = int(cursor.lastrowid)
                await self.audit.record(
                    guild_id,
                    "ABSENCE_SUBMITTED",
                    actor_id=discord_id,
                    target_id=discord_id,
                    after={
                        "absence_id": absence_id,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                    },
                    reason=reason.strip(),
                    connection=connection,
                )
        except aiosqlite.IntegrityError as exc:
            raise ConflictError("Você já possui um afastamento pendente ou aprovado.") from exc
        return absence_id

    async def get_absence(self, guild_id: int, absence_id: int):
        return await self.database.fetchone(
            "SELECT * FROM absence_requests WHERE guild_id=? AND id=?",
            (guild_id, absence_id),
        )

    async def pending_absences(self, guild_id: int, limit: int = 25, offset: int = 0):
        return await self.database.fetchall(
            """
            SELECT ar.*, m.mta_nick
            FROM absence_requests ar JOIN members m ON m.id=ar.member_id
            WHERE ar.guild_id=? AND ar.status='PENDING'
            ORDER BY ar.submitted_at ASC LIMIT ? OFFSET ?
            """,
            (guild_id, limit, offset),
        )

    async def absences_for_member(self, guild_id: int, discord_id: int, limit: int = 10):
        return await self.database.fetchall(
            """
            SELECT * FROM absence_requests
            WHERE guild_id=? AND discord_id=? ORDER BY submitted_at DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )

    async def review_absence(
        self,
        guild_id: int,
        absence_id: int,
        approved: bool,
        actor_id: int,
        reason: str,
    ) -> dict[str, object]:
        if not reason.strip():
            raise ValidationError("Informe o motivo da decisão.")
        now = self.clock()
        status = AbsenceStatus.APPROVED if approved else AbsenceStatus.REJECTED
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM absence_requests WHERE id=? AND guild_id=?",
                (absence_id, guild_id),
            )
            absence = await cursor.fetchone()
            if not absence:
                raise NotFoundError("Solicitação de afastamento não encontrada.")
            if absence["status"] != AbsenceStatus.PENDING.value:
                raise ConflictError("Essa solicitação já foi analisada.")
            cursor = await connection.execute(
                "SELECT status FROM members WHERE id=?", (absence["member_id"],)
            )
            member = await cursor.fetchone()
            if not member:
                raise NotFoundError("O cadastro vinculado à solicitação não existe mais.")
            previous_status = str(member["status"])
            cursor = await connection.execute(
                """
                UPDATE absence_requests SET status=?, reviewed_by=?, reviewed_at=?,
                    review_reason=?, previous_member_status=?
                WHERE id=? AND status='PENDING'
                """,
                (
                    status.value,
                    actor_id,
                    now,
                    reason.strip(),
                    previous_status if approved else None,
                    absence_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Essa solicitação foi analisada simultaneamente.")
            member_status = None
            if approved and int(absence["starts_at"]) <= now < int(absence["ends_at"]):
                if member["status"] not in {
                    MemberStatus.SUSPENDED.value,
                    MemberStatus.DISMISSED.value,
                }:
                    member_status = MemberStatus.AWAY.value
                    await connection.execute(
                        "UPDATE members SET status=?, updated_at=? WHERE id=?",
                        (member_status, now, absence["member_id"]),
                    )
            await self.audit.record(
                guild_id,
                "ABSENCE_REVIEWED",
                actor_id=actor_id,
                target_id=int(absence["discord_id"]),
                before={"status": AbsenceStatus.PENDING.value},
                after={"absence_id": absence_id, "status": status.value},
                reason=reason.strip(),
                connection=connection,
            )
        return {
            "absence_id": absence_id,
            "discord_id": int(absence["discord_id"]),
            "status": status.value,
            "member_status": member_status,
        }

    async def register_justified_absence(
        self,
        guild_id: int,
        discord_id: int,
        starts_at: int,
        ends_at: int,
        actor_id: int,
        reason: str,
    ) -> dict[str, object]:
        """Register an already-authorized absence using the canonical table."""
        now = self.clock()
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Informe o motivo da ausência justificada.")
        if starts_at >= ends_at or ends_at <= now:
            raise ValidationError("Informe um período futuro válido.")
        try:
            async with self.database.transaction() as connection:
                cursor = await connection.execute(
                    "SELECT id, status FROM members WHERE guild_id=? AND discord_id=?",
                    (guild_id, discord_id),
                )
                member = await cursor.fetchone()
                if member is None:
                    raise NotFoundError("Membro não encontrado.")
                if str(member["status"]) in {
                    MemberStatus.SUSPENDED.value,
                    MemberStatus.DISMISSED.value,
                }:
                    raise ConflictError("O status atual não permite registrar afastamento.")
                cursor = await connection.execute(
                    """
                    INSERT INTO absence_requests(
                        guild_id, member_id, discord_id, starts_at, ends_at,
                        reason, status, submitted_at, reviewed_by, reviewed_at,
                        review_reason, previous_member_status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'APPROVED', ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        int(member["id"]),
                        discord_id,
                        starts_at,
                        ends_at,
                        normalized_reason,
                        now,
                        actor_id,
                        now,
                        normalized_reason,
                        str(member["status"]),
                    ),
                )
                absence_id = int(cursor.lastrowid)
                if starts_at <= now < ends_at and str(member["status"]) != MemberStatus.AWAY.value:
                    await connection.execute(
                        "UPDATE members SET status='AWAY', updated_at=? WHERE id=?",
                        (now, int(member["id"])),
                    )
                await self.audit.record(
                    guild_id,
                    "ABSENCE_JUSTIFIED_REGISTERED",
                    actor_id=actor_id,
                    target_id=discord_id,
                    after={
                        "absence_id": absence_id,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                    },
                    reason=normalized_reason,
                    connection=connection,
                )
        except aiosqlite.IntegrityError as exc:
            raise ConflictError("O membro já possui afastamento pendente ou aprovado.") from exc
        return {
            "absence_id": absence_id,
            "discord_id": discord_id,
            "status": "APPROVED",
            "starts_at": starts_at,
            "ends_at": ends_at,
        }

    async def cancel_absence(self, guild_id: int, discord_id: int) -> int:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM absence_requests
                WHERE guild_id=? AND discord_id=? AND status='PENDING'
                ORDER BY submitted_at DESC LIMIT 1
                """,
                (guild_id, discord_id),
            )
            absence = await cursor.fetchone()
            if not absence:
                raise NotFoundError("Você não possui solicitação pendente para cancelar.")
            await connection.execute(
                "UPDATE absence_requests SET status='CANCELLED', cancelled_at=? WHERE id=?",
                (now, absence["id"]),
            )
            await self.audit.record(
                guild_id,
                "ABSENCE_CANCELLED",
                actor_id=discord_id,
                target_id=discord_id,
                after={"absence_id": absence["id"], "status": "CANCELLED"},
                connection=connection,
            )
        return int(absence["id"])

    async def ranking(
        self,
        guild_id: int,
        start_ms: int,
        end_ms: int,
        limit: int = 20,
    ):
        now = self.clock()
        countable = countable_shift_clause()
        return await self.database.fetchall(
            f"""
            SELECT m.discord_id, m.mta_nick, m.status, r.name AS rank_name,
                COALESCE((
                    SELECT SUM(MAX(0, MIN(COALESCE(ss.ended_at, ?), ?) -
                        MAX(ss.started_at, ?)))
                    FROM shift_segments ss JOIN shifts s ON s.id=ss.shift_id
                    WHERE s.member_id=m.id AND s.guild_id=m.guild_id
                      AND {countable}
                      AND ss.started_at < ? AND COALESCE(ss.ended_at, ?) > ?
                ), 0) + COALESCE((
                    SELECT SUM(sa.delta_ms)
                    FROM shift_adjustments sa JOIN shifts s ON s.id=sa.shift_id
                    WHERE s.member_id=m.id AND s.guild_id=m.guild_id
                      AND {countable}
                      AND s.started_at >= ? AND s.started_at < ?
                ), 0) AS total_ms
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.status != 'DISMISSED'
            ORDER BY total_ms DESC, m.mta_nick COLLATE NOCASE ASC
            LIMIT ?
            """,
            (
                now,
                end_ms,
                start_ms,
                now,
                end_ms,
                now,
                start_ms,
                now,
                start_ms,
                end_ms,
                guild_id,
                limit,
            ),
        )

    async def history(self, guild_id: int, discord_id: int, limit: int = 10) -> dict[str, list]:
        actions = await self.database.fetchall(
            """
            SELECT pa.*, fr.name AS from_rank_name, tr.name AS to_rank_name
            FROM personnel_actions pa
            LEFT JOIN ranks fr ON fr.id=pa.from_rank_id
            JOIN ranks tr ON tr.id=pa.to_rank_id
            WHERE pa.guild_id=? AND pa.discord_id=?
            ORDER BY pa.created_at DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )
        punishments = await self.database.fetchall(
            """
            SELECT * FROM punishments WHERE guild_id=? AND discord_id=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )
        absences = await self.database.fetchall(
            """
            SELECT * FROM absence_requests WHERE guild_id=? AND discord_id=?
            ORDER BY submitted_at DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )
        return {
            "actions": list(actions),
            "punishments": list(punishments),
            "absences": list(absences),
        }

    async def expire_due(self, guild_id: int) -> list[tuple[int, str]]:
        now = self.clock()
        affected: set[int] = set()
        restore_status: dict[int, str] = {}
        status_changes: dict[int, str] = {}
        async with self.database.transaction() as connection:
            # Suspensões futuras são ativadas pelo relógio persistido no banco.
            # O fechamento do ponto ocorre na mesma transação da ativação.
            cursor = await connection.execute(
                """
                SELECT p.*, m.status AS member_status
                FROM punishments p JOIN members m ON m.id=p.member_id
                WHERE p.guild_id=? AND p.status='SCHEDULED'
                  AND p.punishment_type='SUSPENSION' AND p.starts_at <= ?
                ORDER BY p.starts_at, p.id
                """,
                (guild_id, now),
            )
            for suspension in await cursor.fetchall():
                member_id = int(suspension["member_id"])
                discord_id = int(suspension["discord_id"])
                if suspension["member_status"] == MemberStatus.DISMISSED.value:
                    await connection.execute(
                        """
                        UPDATE punishments SET status='REVOKED', revoked_at=?,
                            revoke_reason='Membro desligado antes do início'
                        WHERE id=? AND status='SCHEDULED'
                        """,
                        (now, suspension["id"]),
                    )
                    continue
                update = await connection.execute(
                    """
                    UPDATE punishments SET status='ACTIVE', previous_member_status=?
                    WHERE id=? AND status='SCHEDULED'
                    """,
                    (suspension["member_status"], suspension["id"]),
                )
                if update.rowcount != 1:
                    continue
                await connection.execute(
                    "UPDATE members SET status='SUSPENDED', updated_at=? WHERE id=?",
                    (now, member_id),
                )
                if suspension["member_status"] != MemberStatus.SUSPENDED.value:
                    status_changes[discord_id] = MemberStatus.SUSPENDED.value
                cursor = await connection.execute(
                    """
                    SELECT * FROM shifts WHERE guild_id=? AND member_id=?
                      AND status IN ('ACTIVE','GRACE') ORDER BY id DESC LIMIT 1
                    """,
                    (guild_id, member_id),
                )
                shift = await cursor.fetchone()
                if shift:
                    valid_end = int(shift["grace_started_at"] or now)
                    await connection.execute(
                        """
                        UPDATE shift_segments SET ended_at=?, end_reason='MEMBER_SUSPENDED'
                        WHERE shift_id=? AND ended_at IS NULL
                        """,
                        (valid_end, shift["id"]),
                    )
                    validation = await closed_validation_values(connection, shift, valid_end)
                    closed = await connection.execute(
                        """
                        UPDATE shifts SET status='CLOSED', ended_at=?, closed_at=?,
                            end_reason='MEMBER_SUSPENDED', grace_started_at=NULL,
                            grace_deadline=NULL, gross_duration_ms=?, patrol_duration_ms=?,
                            patrol_requirement_met_at=?, validation_status=?,
                            automatic_validation_status=?, invalid_reason=?,
                            validation_source='AUTO', validated_at=?
                        WHERE id=? AND status IN ('ACTIVE','GRACE')
                        """,
                        (
                            valid_end,
                            now,
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
                    if closed.rowcount == 1:
                        await self.audit.record(
                            guild_id,
                            "SHIFT_CLOSED",
                            target_id=discord_id,
                            before={"status": shift["status"]},
                            after={
                                "status": "CLOSED",
                                "shift_id": shift["id"],
                                "ended_at": valid_end,
                                "validation_status": validation["validation_status"],
                            },
                            reason="MEMBER_SUSPENDED",
                            connection=connection,
                        )
                affected.add(member_id)
                await self.audit.record(
                    guild_id,
                    "SUSPENSION_STARTED_AUTOMATED",
                    target_id=discord_id,
                    before={"member_status": suspension["member_status"]},
                    after={
                        "punishment_id": suspension["id"],
                        "status": "ACTIVE",
                        "member_status": MemberStatus.SUSPENDED.value,
                    },
                    connection=connection,
                )

            cursor = await connection.execute(
                """
                SELECT id, member_id, discord_id, previous_member_status FROM punishments
                WHERE guild_id=? AND status='ACTIVE' AND punishment_type='SUSPENSION'
                  AND ends_at IS NOT NULL AND ends_at <= ?
                """,
                (guild_id, now),
            )
            due_punishments = await cursor.fetchall()
            affected.update(int(row["member_id"]) for row in due_punishments)
            for row in due_punishments:
                if row["previous_member_status"] == MemberStatus.RESERVE.value:
                    restore_status[int(row["member_id"])] = MemberStatus.RESERVE.value
                updated = await connection.execute(
                    "UPDATE punishments SET status='EXPIRED' WHERE id=? AND status='ACTIVE'",
                    (row["id"],),
                )
                if updated.rowcount == 1:
                    await self.audit.record(
                        guild_id,
                        "SUSPENSION_ENDED_AUTOMATED",
                        target_id=int(row["discord_id"]),
                        before={"punishment_id": row["id"], "status": "ACTIVE"},
                        after={"status": "EXPIRED", "ended_at": now},
                        connection=connection,
                    )
            cursor = await connection.execute(
                """
                SELECT member_id, previous_member_status FROM absence_requests
                WHERE guild_id=? AND status='APPROVED' AND ends_at <= ?
                """,
                (guild_id, now),
            )
            due_absences = await cursor.fetchall()
            affected.update(int(row["member_id"]) for row in due_absences)
            for row in due_absences:
                if row["previous_member_status"] == MemberStatus.RESERVE.value:
                    restore_status[int(row["member_id"])] = MemberStatus.RESERVE.value
            await connection.execute(
                """
                UPDATE absence_requests SET status='ENDED', ended_at=?
                WHERE guild_id=? AND status='APPROVED' AND ends_at <= ?
                """,
                (now, guild_id, now),
            )
            cursor = await connection.execute(
                """
                SELECT member_id FROM absence_requests
                WHERE guild_id=? AND status='APPROVED' AND starts_at <= ? AND ends_at > ?
                """,
                (guild_id, now, now),
            )
            affected.update(int(row["member_id"]) for row in await cursor.fetchall())

            for member_id in affected:
                cursor = await connection.execute(
                    "SELECT discord_id, status FROM members WHERE id=?", (member_id,)
                )
                member = await cursor.fetchone()
                if not member:
                    continue
                new_status = await self._effective_status(
                    connection,
                    guild_id,
                    member_id,
                    now,
                    fallback=restore_status.get(member_id, MemberStatus.ACTIVE.value),
                )
                if member["status"] == new_status:
                    continue
                await connection.execute(
                    "UPDATE members SET status=?, updated_at=? WHERE id=?",
                    (new_status, now, member_id),
                )
                status_changes[int(member["discord_id"])] = new_status
                await self.audit.record(
                    guild_id,
                    "MEMBER_STATUS_AUTOMATED",
                    target_id=int(member["discord_id"]),
                    before={"status": member["status"]},
                    after={"status": new_status},
                    connection=connection,
                )
        return list(status_changes.items())

    async def _effective_status(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        member_id: int,
        now: int,
        *,
        fallback: str = MemberStatus.ACTIVE.value,
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
                if punishment["punishment_type"] == PunishmentType.DISMISSAL.value
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
