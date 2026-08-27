from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping

import aiosqlite

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .models import MemberStatus
from .settings import SettingsService
from .source_cutover import block_source_cutover_writes
from .time_utils import utc_now_ms

DAY_MS = 86_400_000


class TrainingService:
    """Treinamentos, inscrições, presença e qualificações em transações auditadas."""

    def __init__(
        self,
        database: Database,
        audit: AuditService,
        *,
        settings: SettingsService | None = None,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.audit = audit
        self.settings = settings
        self.clock = clock

    async def _canonical_member_context(
        self,
        guild_id: int,
        discord_id: int,
        local_member: Mapping[str, object],
    ) -> tuple[int, Mapping[str, object]]:
        """Resolve read-only service history for a module-only satellite guild."""
        if self.settings is None:
            return guild_id, local_member
        source_guild_id = await self.settings.get(guild_id, "identity_source_guild_id")
        if not source_guild_id or int(source_guild_id) == guild_id:
            return guild_id, local_member
        source_member = await self.database.fetchone(
            "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
            (int(source_guild_id), discord_id),
        )
        if source_member is None:
            return guild_id, local_member
        return int(source_guild_id), source_member

    @staticmethod
    def _required(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValidationError(f"Informe {label}.")
        return normalized

    @staticmethod
    def _optional(value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @block_source_cutover_writes("Treinamentos")
    async def create_training(
        self,
        guild_id: int,
        actor_id: int,
        *,
        name: str,
        description: str,
        scheduled_at: int,
        responsible_id: int,
        capacity: int,
        course_name: str | None = None,
    ) -> dict[str, object]:
        name = self._required(name, "o nome do treinamento")
        description = self._required(description, "a descrição do treinamento")
        course_name = self._optional(course_name)
        if not 1 <= capacity <= 100:
            raise ValidationError("O número de vagas deve ficar entre 1 e 100.")
        now = self.clock()
        if scheduled_at <= now:
            raise ValidationError("A data do treinamento precisa estar no futuro.")
        if scheduled_at > now + 730 * DAY_MS:
            raise ValidationError("O treinamento não pode ser agendado com mais de dois anos.")
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
                (guild_id, responsible_id),
            )
            if not await cursor.fetchone():
                raise NotFoundError("O responsável precisa possuir cadastro aprovado.")
            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO training_events(
                        guild_id, name, description, scheduled_at, responsible_id,
                        capacity, course_name, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        name,
                        description,
                        scheduled_at,
                        responsible_id,
                        capacity,
                        course_name,
                        actor_id,
                        now,
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("Já existe um treinamento com esse nome nessa data.") from exc
            training_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "TRAINING_CREATED",
                actor_id=actor_id,
                target_id=responsible_id,
                after={
                    "training_id": training_id,
                    "name": name,
                    "scheduled_at": scheduled_at,
                    "capacity": capacity,
                    "course_name": course_name,
                    "status": "OPEN",
                },
                connection=connection,
            )
        return {
            "training_id": training_id,
            "name": name,
            "scheduled_at": scheduled_at,
            "responsible_id": responsible_id,
            "capacity": capacity,
            "course_name": course_name,
            "status": "OPEN",
        }

    @block_source_cutover_writes("Treinamentos")
    async def attach_message(
        self, guild_id: int, training_id: int, channel_id: int, message_id: int
    ) -> None:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE training_events SET channel_id=?, message_id=?
                WHERE guild_id=? AND id=?
                """,
                (channel_id, message_id, guild_id, training_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Treinamento não encontrado.")

    async def get_training(self, guild_id: int, training_id: int):
        return await self.database.fetchone(
            """
            SELECT t.*,
                COUNT(CASE WHEN e.enrollment_status='ENROLLED' THEN 1 END) AS enrolled_count,
                COUNT(CASE WHEN e.enrollment_status='ENROLLED'
                            AND e.attendance_status='PENDING' THEN 1 END) AS pending_count
            FROM training_events t
            LEFT JOIN training_enrollments e ON e.training_id=t.id
            WHERE t.guild_id=? AND t.id=?
            GROUP BY t.id
            """,
            (guild_id, training_id),
        )

    async def open_trainings(self, guild_id: int, *, limit: int = 25):
        now = self.clock()
        return await self.database.fetchall(
            """
            SELECT t.*,
                COUNT(CASE WHEN e.enrollment_status='ENROLLED' THEN 1 END) AS enrolled_count
            FROM training_events t
            LEFT JOIN training_enrollments e ON e.training_id=t.id
            WHERE t.guild_id=? AND t.status='OPEN' AND t.scheduled_at > ?
            GROUP BY t.id ORDER BY t.scheduled_at, t.id LIMIT ?
            """,
            (guild_id, now, limit),
        )

    async def active_trainings(self, guild_id: int, *, limit: int = 25):
        return await self.database.fetchall(
            """
            SELECT t.*,
                COUNT(CASE WHEN e.enrollment_status='ENROLLED' THEN 1 END) AS enrolled_count,
                COUNT(CASE WHEN e.enrollment_status='ENROLLED'
                            AND e.attendance_status='PENDING' THEN 1 END) AS pending_count
            FROM training_events t
            LEFT JOIN training_enrollments e ON e.training_id=t.id
            WHERE t.guild_id=? AND t.status IN ('OPEN','CLOSED')
            GROUP BY t.id ORDER BY t.scheduled_at, t.id LIMIT ?
            """,
            (guild_id, limit),
        )

    async def persistent_events(self):
        return await self.database.fetchall(
            """
            SELECT guild_id, id, channel_id, message_id FROM training_events
            WHERE status IN ('OPEN','CLOSED') AND channel_id IS NOT NULL AND message_id IS NOT NULL
            """
        )

    @block_source_cutover_writes("Treinamentos")
    async def enroll(self, guild_id: int, training_id: int, discord_id: int) -> dict[str, object]:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT id, status FROM members WHERE guild_id=? AND discord_id=?",
                (guild_id, discord_id),
            )
            member = await cursor.fetchone()
            if not member:
                raise NotFoundError("Você ainda não possui cadastro aprovado.")
            if member["status"] != MemberStatus.ACTIVE.value:
                raise ConflictError("Somente membros ativos podem participar de treinamentos.")
            cursor = await connection.execute(
                "SELECT * FROM training_events WHERE guild_id=? AND id=?",
                (guild_id, training_id),
            )
            training = await cursor.fetchone()
            if not training:
                raise NotFoundError("Treinamento não encontrado.")
            if training["status"] != "OPEN" or int(training["scheduled_at"]) <= now:
                raise ConflictError("As inscrições desse treinamento estão encerradas.")
            cursor = await connection.execute(
                """
                SELECT * FROM training_enrollments
                WHERE training_id=? AND member_id=?
                """,
                (training_id, member["id"]),
            )
            previous = await cursor.fetchone()
            if previous and previous["enrollment_status"] == "ENROLLED":
                raise ConflictError("Você já está inscrito nesse treinamento.")
            cursor = await connection.execute(
                """
                SELECT COUNT(*) AS total FROM training_enrollments
                WHERE training_id=? AND enrollment_status='ENROLLED'
                """,
                (training_id,),
            )
            if int((await cursor.fetchone())["total"]) >= int(training["capacity"]):
                raise ConflictError("Não há mais vagas nesse treinamento.")
            if previous:
                await connection.execute(
                    """
                    UPDATE training_enrollments
                    SET enrollment_status='ENROLLED', attendance_status='PENDING',
                        result_status='PENDING', enrolled_at=?, cancelled_at=NULL,
                        decided_by=NULL, decided_at=NULL, decision_notes=NULL
                    WHERE id=? AND enrollment_status='CANCELLED'
                    """,
                    (now, previous["id"]),
                )
                enrollment_id = int(previous["id"])
            else:
                cursor = await connection.execute(
                    """
                    INSERT INTO training_enrollments(
                        guild_id, training_id, member_id, discord_id, enrolled_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (guild_id, training_id, member["id"], discord_id, now),
                )
                enrollment_id = int(cursor.lastrowid)
            cursor = await connection.execute(
                """
                SELECT COUNT(*) AS total FROM training_enrollments
                WHERE training_id=? AND enrollment_status='ENROLLED'
                """,
                (training_id,),
            )
            enrolled_count = int((await cursor.fetchone())["total"])
            await self.audit.record(
                guild_id,
                "TRAINING_ENROLLED",
                actor_id=discord_id,
                target_id=discord_id,
                after={
                    "training_id": training_id,
                    "enrollment_id": enrollment_id,
                    "enrolled_count": enrolled_count,
                },
                connection=connection,
            )
        return {
            "training_id": training_id,
            "enrollment_id": enrollment_id,
            "enrolled_count": enrolled_count,
            "capacity": int(training["capacity"]),
        }

    @block_source_cutover_writes("Treinamentos")
    async def cancel_enrollment(
        self, guild_id: int, training_id: int, discord_id: int
    ) -> dict[str, object]:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM training_events WHERE guild_id=? AND id=?",
                (guild_id, training_id),
            )
            training = await cursor.fetchone()
            if not training:
                raise NotFoundError("Treinamento não encontrado.")
            if training["status"] != "OPEN" or int(training["scheduled_at"]) <= now:
                raise ConflictError("A participação não pode mais ser cancelada.")
            cursor = await connection.execute(
                """
                UPDATE training_enrollments
                SET enrollment_status='CANCELLED', cancelled_at=?
                WHERE guild_id=? AND training_id=? AND discord_id=?
                  AND enrollment_status='ENROLLED'
                """,
                (now, guild_id, training_id, discord_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Você não está inscrito nesse treinamento.")
            cursor = await connection.execute(
                """
                SELECT COUNT(*) AS total FROM training_enrollments
                WHERE training_id=? AND enrollment_status='ENROLLED'
                """,
                (training_id,),
            )
            enrolled_count = int((await cursor.fetchone())["total"])
            await self.audit.record(
                guild_id,
                "TRAINING_ENROLLMENT_CANCELLED",
                actor_id=discord_id,
                target_id=discord_id,
                before={"training_id": training_id, "status": "ENROLLED"},
                after={"status": "CANCELLED", "enrolled_count": enrolled_count},
                connection=connection,
            )
        return {
            "training_id": training_id,
            "enrolled_count": enrolled_count,
            "capacity": int(training["capacity"]),
        }

    async def member_trainings(self, guild_id: int, discord_id: int, *, limit: int = 20):
        return await self.database.fetchall(
            """
            SELECT e.*, t.name, t.description, t.scheduled_at, t.status AS training_status,
                   t.responsible_id, t.course_name, t.channel_id, t.message_id
            FROM training_enrollments e
            JOIN training_events t ON t.id=e.training_id
            WHERE e.guild_id=? AND e.discord_id=?
            ORDER BY t.scheduled_at DESC, e.id DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )

    async def member_courses(self, guild_id: int, discord_id: int, *, limit: int = 25):
        return await self.database.fetchall(
            """
            SELECT q.*, t.name AS training_name, t.scheduled_at
            FROM member_qualifications q
            LEFT JOIN training_events t ON t.id=q.training_id
            WHERE q.guild_id=? AND q.discord_id=?
            ORDER BY q.recorded_at DESC, q.id DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )

    async def enrollments(self, guild_id: int, training_id: int):
        return await self.database.fetchall(
            """
            SELECT e.*, m.mta_nick FROM training_enrollments e
            JOIN members m ON m.id=e.member_id
            WHERE e.guild_id=? AND e.training_id=? AND e.enrollment_status='ENROLLED'
            ORDER BY e.enrolled_at, e.id
            """,
            (guild_id, training_id),
        )

    @block_source_cutover_writes("Treinamentos")
    async def close_enrollment(
        self, guild_id: int, training_id: int, actor_id: int
    ) -> dict[str, object]:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE training_events SET status='CLOSED', enrollment_closed_at=?
                WHERE guild_id=? AND id=? AND status='OPEN'
                """,
                (now, guild_id, training_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("As inscrições já estão encerradas.")
            await self.audit.record(
                guild_id,
                "TRAINING_ENROLLMENT_CLOSED",
                actor_id=actor_id,
                after={"training_id": training_id, "status": "CLOSED"},
                connection=connection,
            )
        return {"training_id": training_id, "status": "CLOSED"}

    @block_source_cutover_writes("Treinamentos")
    async def decide_participant(
        self,
        guild_id: int,
        training_id: int,
        discord_id: int,
        actor_id: int,
        *,
        attendance: str,
        result: str,
        performance: str = "GOOD",
        notes: str | None = None,
    ) -> dict[str, object]:
        attendance = attendance.upper()
        result = result.upper()
        performance = performance.upper()
        if attendance not in {"PRESENT", "ABSENT"}:
            raise ValidationError("Situação de presença inválida.")
        if result not in {"APPROVED", "FAILED"}:
            raise ValidationError("Resultado de treinamento inválido.")
        if attendance == "ABSENT" and result != "FAILED":
            raise ValidationError("Participante ausente precisa ter resultado reprovado.")
        if performance not in {"EXCELLENT", "GOOD", "REGULAR", "INSUFFICIENT"}:
            raise ValidationError("Classificação de desempenho inválida.")
        notes = self._optional(notes)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT status FROM training_events WHERE guild_id=? AND id=?
                """,
                (guild_id, training_id),
            )
            training = await cursor.fetchone()
            if not training:
                raise NotFoundError("Treinamento não encontrado.")
            if training["status"] not in {"OPEN", "CLOSED"}:
                raise ConflictError("Esse treinamento já foi finalizado.")
            cursor = await connection.execute(
                """
                SELECT id, member_id, discord_id, attendance_status, result_status
                FROM training_enrollments
                WHERE guild_id=? AND training_id=? AND discord_id=?
                  AND enrollment_status='ENROLLED'
                """,
                (guild_id, training_id, discord_id),
            )
            enrollment = await cursor.fetchone()
            if not enrollment:
                raise NotFoundError("Participante não está inscrito nesse treinamento.")
            await connection.execute(
                """
                UPDATE training_enrollments
                SET attendance_status=?, result_status=?, decided_by=?, decided_at=?,
                    decision_notes=?
                WHERE guild_id=? AND training_id=? AND discord_id=?
                  AND enrollment_status='ENROLLED'
                """,
                (
                    attendance,
                    result,
                    actor_id,
                    now,
                    notes,
                    guild_id,
                    training_id,
                    discord_id,
                ),
            )
            try:
                await connection.execute(
                    """
                    INSERT INTO training_evaluations(
                        guild_id, training_id, enrollment_id, member_id, discord_id,
                        attendance, result, performance, observation, evaluator_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        training_id,
                        enrollment["id"],
                        enrollment["member_id"],
                        enrollment["discord_id"],
                        attendance,
                        result,
                        performance,
                        notes,
                        actor_id,
                        now,
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("Este participante já possui avaliação registrada.") from exc
            await self.audit.record(
                guild_id,
                "TRAINING_PARTICIPANT_DECIDED",
                actor_id=actor_id,
                target_id=discord_id,
                before={
                    "training_id": training_id,
                    "attendance": enrollment["attendance_status"],
                    "result": enrollment["result_status"],
                },
                after={
                    "attendance": attendance,
                    "result": result,
                    "performance": performance,
                },
                reason=notes,
                connection=connection,
            )
        return {
            "training_id": training_id,
            "discord_id": discord_id,
            "attendance": attendance,
            "result": result,
            "performance": performance,
        }

    @block_source_cutover_writes("Treinamentos")
    async def complete_training(
        self, guild_id: int, training_id: int, actor_id: int
    ) -> dict[str, object]:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM training_events WHERE guild_id=? AND id=?",
                (guild_id, training_id),
            )
            training = await cursor.fetchone()
            if not training:
                raise NotFoundError("Treinamento não encontrado.")
            if training["status"] not in {"OPEN", "CLOSED"}:
                raise ConflictError("Esse treinamento já foi finalizado.")
            cursor = await connection.execute(
                """
                SELECT * FROM training_enrollments
                WHERE guild_id=? AND training_id=? AND enrollment_status='ENROLLED'
                ORDER BY id
                """,
                (guild_id, training_id),
            )
            participants = await cursor.fetchall()
            pending = [
                row
                for row in participants
                if row["attendance_status"] == "PENDING" or row["result_status"] == "PENDING"
            ]
            if pending:
                raise ConflictError(
                    f"Ainda existem {len(pending)} participante(s) sem presença e resultado."
                )
            cursor = await connection.execute(
                """
                UPDATE training_events SET status='COMPLETED', completed_by=?, completed_at=?
                WHERE guild_id=? AND id=? AND status IN ('OPEN','CLOSED')
                """,
                (actor_id, now, guild_id, training_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("O treinamento foi finalizado simultaneamente.")
            course_name = str(training["course_name"] or training["name"])
            cursor = await connection.execute(
                """
                SELECT id, course_role_id FROM course_catalog
                WHERE guild_id=? AND lower(name)=lower(?) AND active=1
                ORDER BY id LIMIT 1
                """,
                (guild_id, course_name),
            )
            catalog_course = await cursor.fetchone()
            qualification_syncs = 0
            for participant in participants:
                await connection.execute(
                    """
                    INSERT INTO member_qualifications(
                        guild_id, member_id, discord_id, training_id, course_name,
                        result, responsible_id, recorded_at, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(training_id, member_id) DO UPDATE SET
                        result=excluded.result, responsible_id=excluded.responsible_id,
                        recorded_at=excluded.recorded_at, notes=excluded.notes
                    """,
                    (
                        guild_id,
                        participant["member_id"],
                        participant["discord_id"],
                        training_id,
                        course_name,
                        participant["result_status"],
                        actor_id,
                        now,
                        participant["decision_notes"],
                    ),
                )
                if participant["result_status"] == "APPROVED" and catalog_course:
                    operation_id = (
                        f"training:{guild_id}:{training_id}:{participant['member_id']}:"
                        f"course:{catalog_course['id']}"
                    )
                    cursor = await connection.execute(
                        """
                        INSERT OR IGNORE INTO qualification_changes(
                            guild_id, member_id, discord_id, course_id, action, source,
                            actor_id, reason, correlation_id, recorded_at
                        ) VALUES (?, ?, ?, ?, 'GRANT', 'TRAINING', ?, ?, ?, ?)
                        """,
                        (
                            guild_id,
                            participant["member_id"],
                            participant["discord_id"],
                            catalog_course["id"],
                            actor_id,
                            f"Aprovação no treinamento #{training_id}.",
                            operation_id,
                            now,
                        ),
                    )
                    if cursor.rowcount == 1:
                        await connection.execute(
                            """
                            INSERT OR IGNORE INTO web_action_outbox(
                                guild_id, action_type, target_discord_id, payload_json,
                                requested_by, correlation_id, status, available_at, created_at
                            ) VALUES (?, 'QUALIFICATION_SYNC', ?, ?, ?, ?, 'PENDING', ?, ?)
                            """,
                            (
                                guild_id,
                                participant["discord_id"],
                                json.dumps(
                                    {
                                        "course_id": int(catalog_course["id"]),
                                        "granted": True,
                                        "source": "TRAINING",
                                    },
                                    ensure_ascii=False,
                                    sort_keys=True,
                                ),
                                actor_id,
                                f"{operation_id}:discord",
                                now,
                                now,
                            ),
                        )
                        qualification_syncs += 1
            approved = sum(row["result_status"] == "APPROVED" for row in participants)
            failed = sum(row["result_status"] == "FAILED" for row in participants)
            await self.audit.record(
                guild_id,
                "TRAINING_COMPLETED",
                actor_id=actor_id,
                after={
                    "training_id": training_id,
                    "status": "COMPLETED",
                    "participants": len(participants),
                    "approved": approved,
                    "failed": failed,
                    "course_name": course_name,
                    "course_id": int(catalog_course["id"]) if catalog_course else None,
                    "qualification_syncs": qualification_syncs,
                },
                connection=connection,
            )
        return {
            "training_id": training_id,
            "status": "COMPLETED",
            "participants": len(participants),
            "approved": approved,
            "failed": failed,
        }

    @block_source_cutover_writes("Treinamentos")
    async def cancel_training(
        self, guild_id: int, training_id: int, actor_id: int, reason: str
    ) -> dict[str, object]:
        reason = self._required(reason, "o motivo do cancelamento")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT status FROM training_events WHERE guild_id=? AND id=?",
                (guild_id, training_id),
            )
            training = await cursor.fetchone()
            if not training:
                raise NotFoundError("Treinamento não encontrado.")
            cursor = await connection.execute(
                """
                UPDATE training_events
                SET status='CANCELLED', cancelled_by=?, cancelled_at=?, cancel_reason=?
                WHERE guild_id=? AND id=? AND status IN ('OPEN','CLOSED')
                """,
                (actor_id, now, reason, guild_id, training_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esse treinamento já foi finalizado ou cancelado.")
            await self.audit.record(
                guild_id,
                "TRAINING_CANCELLED",
                actor_id=actor_id,
                before={"training_id": training_id, "status": training["status"]},
                after={"status": "CANCELLED"},
                reason=reason,
                connection=connection,
            )
        return {"training_id": training_id, "status": "CANCELLED"}

    async def history(self, guild_id: int, *, limit: int = 25):
        return await self.database.fetchall(
            """
            SELECT t.*,
                COUNT(CASE WHEN e.enrollment_status='ENROLLED' THEN 1 END) AS participants,
                COUNT(CASE WHEN e.enrollment_status='ENROLLED'
                            AND e.result_status='APPROVED' THEN 1 END) AS approved,
                COUNT(CASE WHEN e.enrollment_status='ENROLLED'
                            AND e.result_status='FAILED' THEN 1 END) AS failed
            FROM training_events t
            LEFT JOIN training_enrollments e ON e.training_id=t.id
            WHERE t.guild_id=? AND t.status IN ('COMPLETED','CANCELLED')
            GROUP BY t.id ORDER BY COALESCE(t.completed_at, t.cancelled_at) DESC, t.id DESC
            LIMIT ?
            """,
            (guild_id, limit),
        )

    @block_source_cutover_writes("Cursos")
    async def import_catalog_course(
        self,
        guild_id: int,
        actor_id: int,
        *,
        internal_code: str,
        name: str,
        description: str,
        course_role_id: int,
        course_role_name: str,
        passing_score: int,
        cooldown_days: int,
        enrollment_status: str,
        notes: str | None,
        source_channel_id: int,
        source_message_id: int,
        source_content_sha256: str,
        requirements: list[tuple[int, str]],
    ) -> dict[str, object]:
        internal_code = self._required(internal_code, "o identificador interno do curso").lower()
        name = self._required(name, "o nome do curso")
        description = self._required(description, "a descrição do curso")
        course_role_name = self._required(course_role_name, "o nome do cargo do curso")
        enrollment_status = enrollment_status.upper()
        if enrollment_status not in {"OPEN", "CLOSED"}:
            raise ValidationError("Situação de inscrição do curso inválida.")
        if not 0 <= passing_score <= 100:
            raise ValidationError("A nota de aprovação deve ficar entre 0 e 100.")
        if not 0 <= cooldown_days <= 365:
            raise ValidationError("O intervalo para nova solicitação é inválido.")
        now = self.clock()
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO course_catalog(
                    guild_id, internal_code, name, description, course_role_id,
                    course_role_name, passing_score, cooldown_days, enrollment_status,
                    notes, source_channel_id, source_message_id, source_content_sha256,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, internal_code) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    course_role_id=excluded.course_role_id,
                    course_role_name=excluded.course_role_name,
                    passing_score=excluded.passing_score,
                    cooldown_days=excluded.cooldown_days,
                    enrollment_status=excluded.enrollment_status,
                    notes=excluded.notes,
                    source_channel_id=excluded.source_channel_id,
                    source_message_id=excluded.source_message_id,
                    source_content_sha256=excluded.source_content_sha256,
                    active=1,
                    updated_at=excluded.updated_at
                """,
                (
                    guild_id,
                    internal_code,
                    name,
                    description,
                    course_role_id,
                    course_role_name,
                    passing_score,
                    cooldown_days,
                    enrollment_status,
                    self._optional(notes),
                    source_channel_id,
                    source_message_id,
                    source_content_sha256,
                    now,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT id FROM course_catalog WHERE guild_id=? AND internal_code=?",
                (guild_id, internal_code),
            )
            course_id = int((await cursor.fetchone())["id"])
            await connection.execute(
                "UPDATE course_requirements SET active=0, updated_at=? WHERE course_id=?",
                (now, course_id),
            )
            for sort_order, (role_id, role_name) in enumerate(requirements):
                await connection.execute(
                    """
                    INSERT INTO course_requirements(
                        guild_id, course_id, required_role_id, required_role_name,
                        sort_order, active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(course_id, required_role_id) DO UPDATE SET
                        required_role_name=excluded.required_role_name,
                        sort_order=excluded.sort_order,
                        active=1,
                        updated_at=excluded.updated_at
                    """,
                    (guild_id, course_id, role_id, role_name, sort_order, now, now),
                )
            await self.audit.record(
                guild_id,
                "COURSE_CATALOG_IMPORTED",
                actor_id=actor_id,
                target_id=course_role_id,
                after={
                    "course_id": course_id,
                    "internal_code": internal_code,
                    "source_message_id": source_message_id,
                    "passing_score": passing_score,
                    "requirements": [role_id for role_id, _ in requirements],
                    "enrollment_status": enrollment_status,
                },
                connection=connection,
            )
        return {"course_id": course_id, "internal_code": internal_code, "name": name}

    async def catalog(self, guild_id: int, *, include_inactive: bool = False):
        active_filter = "" if include_inactive else "AND c.active=1"
        return await self.database.fetchall(
            f"""
            SELECT c.*,
                COUNT(DISTINCT CASE WHEN r.active=1 THEN r.id END) AS requirement_count,
                COUNT(DISTINCT CASE WHEN a.status='PENDING' THEN a.id END) AS pending_count
            FROM course_catalog c
            LEFT JOIN course_requirements r ON r.course_id=c.id
            LEFT JOIN course_applications a ON a.course_id=c.id
            WHERE c.guild_id=? {active_filter}
            GROUP BY c.id ORDER BY c.id
            """,
            (guild_id,),
        )

    async def course(self, guild_id: int, internal_code: str):
        return await self.database.fetchone(
            """
            SELECT * FROM course_catalog
            WHERE guild_id=? AND internal_code=? AND active=1
            """,
            (guild_id, internal_code.lower()),
        )

    async def course_by_id(self, guild_id: int, course_id: int):
        return await self.database.fetchone(
            "SELECT * FROM course_catalog WHERE guild_id=? AND id=? AND active=1",
            (guild_id, course_id),
        )

    async def course_requirements(self, guild_id: int, course_id: int):
        return await self.database.fetchall(
            """
            SELECT * FROM course_requirements
            WHERE guild_id=? AND course_id=? AND active=1
            ORDER BY sort_order, id
            """,
            (guild_id, course_id),
        )

    @block_source_cutover_writes("Cursos")
    async def configure_course_panel_channel(
        self, guild_id: int, course_id: int, channel_id: int, actor_id: int
    ) -> dict[str, object]:
        if channel_id <= 0:
            raise ValidationError("Selecione um canal de curso válido.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM course_catalog WHERE guild_id=? AND id=? AND active=1",
                (guild_id, course_id),
            )
            course = await cursor.fetchone()
            if not course:
                raise NotFoundError("Curso ativo não encontrado.")
            await connection.execute(
                "UPDATE course_catalog SET panel_channel_id=?, updated_at=? WHERE id=?",
                (channel_id, now, course_id),
            )
            await self.audit.record(
                guild_id,
                "COURSE_PANEL_CHANNEL_UPDATED",
                actor_id=actor_id,
                target_id=course_id,
                before={"panel_channel_id": course["panel_channel_id"]},
                after={"panel_channel_id": channel_id},
                reason="Canal do painel individual do curso atualizado.",
                connection=connection,
            )
        return {
            "course_id": course_id,
            "internal_code": str(course["internal_code"]),
            "course_name": str(course["name"]),
            "panel_channel_id": channel_id,
        }

    async def _course_eligibility(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        discord_id: int,
        internal_code: str,
        role_ids: Iterable[int],
    ) -> dict[str, object]:
        cursor = await connection.execute(
            """
            SELECT * FROM course_catalog
            WHERE guild_id=? AND internal_code=? AND active=1
            """,
            (guild_id, internal_code.lower()),
        )
        course = await cursor.fetchone()
        if not course:
            raise NotFoundError("Curso não encontrado no catálogo.")
        cursor = await connection.execute(
            """
            SELECT m.*, COALESCE(r.level, -1) AS rank_level
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        member = await cursor.fetchone()
        reasons: list[str] = []
        if not member:
            reasons.append("cadastro aprovado não encontrado")
        elif member["status"] != MemberStatus.ACTIVE.value:
            reasons.append("somente membros ativos podem solicitar cursos")
        if course["enrollment_status"] != "OPEN":
            reasons.append("inscrições temporariamente encerradas")

        current_roles = {int(role_id) for role_id in role_ids}
        if int(course["course_role_id"]) in current_roles:
            reasons.append("curso já consta nos seus cargos")
        cursor = await connection.execute(
            """
            SELECT 1 FROM member_qualifications
            WHERE guild_id=? AND discord_id=? AND course_name=? AND result='APPROVED'
            LIMIT 1
            """,
            (guild_id, discord_id, str(course["name"])),
        )
        if await cursor.fetchone():
            reasons.append("curso já consta no seu histórico aprovado")

        cursor = await connection.execute(
            """
            SELECT required_role_id, required_role_name FROM course_requirements
            WHERE guild_id=? AND course_id=? AND active=1
            ORDER BY sort_order, id
            """,
            (guild_id, int(course["id"])),
        )
        requirements = list(await cursor.fetchall())
        missing = [row for row in requirements if int(row["required_role_id"]) not in current_roles]
        if missing:
            reasons.append(
                "requisitos de cargo não atendidos: "
                + ", ".join(str(row["required_role_name"]) for row in missing)
            )

        if member:
            minimum_rank = course["minimum_rank_level"]
            if minimum_rank is not None and int(member["rank_level"]) < int(minimum_rank):
                cursor = await connection.execute(
                    """
                    SELECT name FROM ranks WHERE guild_id=? AND level>=?
                    ORDER BY level, id LIMIT 1
                    """,
                    (guild_id, minimum_rank),
                )
                minimum_rank_row = await cursor.fetchone()
                minimum_rank_name = (
                    str(minimum_rank_row["name"])
                    if minimum_rank_row
                    else f"nível {minimum_rank}"
                )
                reasons.append(f"patente mínima não atendida: {minimum_rank_name}")
            history_guild_id, history_member = await self._canonical_member_context(
                guild_id, discord_id, member
            )
            cursor = await connection.execute(
                """
                SELECT COALESCE(SUM(
                    s.patrol_duration_ms + COALESCE((
                        SELECT SUM(sa.delta_ms) FROM shift_adjustments sa WHERE sa.shift_id=s.id
                    ), 0)
                ), 0) AS total_ms
                FROM shifts s
                WHERE s.guild_id=? AND s.member_id=? AND s.status='CLOSED'
                  AND s.validation_status='VALID'
                """,
                (history_guild_id, history_member["id"]),
            )
            total_ms = max(0, int((await cursor.fetchone())["total_ms"]))
            if total_ms < int(course["minimum_valid_hours_ms"]):
                required_hours = int(course["minimum_valid_hours_ms"]) / 3_600_000
                current_hours = total_ms / 3_600_000
                reasons.append(
                    "tempo mínimo de serviço válido não atendido: "
                    f"{current_hours:.1f}h de {required_hours:.1f}h"
                )
            tenure_ms = max(0, self.clock() - int(history_member["joined_at"]))
            if tenure_ms < int(course["minimum_tenure_days"]) * DAY_MS:
                current_days = tenure_ms // DAY_MS
                reasons.append(
                    "tempo mínimo de corporação não atendido: "
                    f"{current_days} de {int(course['minimum_tenure_days'])} dia(s)"
                )
            if bool(course["require_no_active_suspension"]):
                cursor = await connection.execute(
                    """
                    SELECT 1 FROM punishments WHERE guild_id=? AND member_id=?
                      AND punishment_type='SUSPENSION' AND status IN ('SCHEDULED','ACTIVE')
                      AND starts_at<=? AND (ends_at IS NULL OR ends_at>?) LIMIT 1
                    """,
                    (
                        history_guild_id,
                        history_member["id"],
                        self.clock(),
                        self.clock(),
                    ),
                )
                if await cursor.fetchone():
                    reasons.append("suspensão ativa impede a solicitação")
            if bool(course["require_no_active_adv"]):
                cursor = await connection.execute(
                    """
                    SELECT 1 FROM punishments WHERE guild_id=? AND member_id=?
                      AND punishment_type='WARNING' AND status='ACTIVE'
                      AND (ends_at IS NULL OR ends_at>?) LIMIT 1
                    """,
                    (history_guild_id, history_member["id"], self.clock()),
                )
                if await cursor.fetchone():
                    reasons.append("ADV ativa impede a solicitação")
            prerequisite = course["prerequisite_course_name"]
            if prerequisite:
                cursor = await connection.execute(
                    """
                    SELECT 1 FROM member_qualifications
                    WHERE guild_id=? AND member_id=? AND lower(course_name)=lower(?)
                      AND result='APPROVED' LIMIT 1
                    """,
                    (guild_id, member["id"], prerequisite),
                )
                if not await cursor.fetchone():
                    reasons.append(f"pré-requisito {prerequisite} não concluído")

        if member:
            cursor = await connection.execute(
                """
                SELECT id FROM course_applications
                WHERE guild_id=? AND course_id=? AND member_id=? AND status='PENDING'
                """,
                (guild_id, int(course["id"]), int(member["id"])),
            )
            if await cursor.fetchone():
                reasons.append("já existe uma solicitação pendente")
            cursor = await connection.execute(
                """
                SELECT decided_at FROM course_applications
                WHERE guild_id=? AND course_id=? AND member_id=? AND status='REJECTED'
                ORDER BY decided_at DESC, id DESC LIMIT 1
                """,
                (guild_id, int(course["id"]), int(member["id"])),
            )
            rejected = await cursor.fetchone()
            if rejected and rejected["decided_at"] is not None:
                eligible_at = int(rejected["decided_at"]) + int(course["cooldown_days"]) * DAY_MS
                if self.clock() < eligible_at:
                    reasons.append(f"nova solicitação disponível após <t:{eligible_at // 1000}:F>")

        return {
            "eligible": not reasons,
            "reasons": reasons,
            "missing_role_ids": [int(row["required_role_id"]) for row in missing],
            "missing_role_names": [str(row["required_role_name"]) for row in missing],
            "course_id": int(course["id"]),
            "course_name": str(course["name"]),
            "passing_score": int(course["passing_score"]),
            "cooldown_days": int(course["cooldown_days"]),
            "minimum_rank_level": course["minimum_rank_level"],
            "minimum_valid_hours_ms": int(course["minimum_valid_hours_ms"]),
            "minimum_tenure_days": int(course["minimum_tenure_days"]),
            "require_no_active_adv": bool(course["require_no_active_adv"]),
            "prerequisite_course_name": course["prerequisite_course_name"],
            "_course": course,
            "_member": member,
        }

    @staticmethod
    def _public_eligibility(result: dict[str, object]) -> dict[str, object]:
        return {key: value for key, value in result.items() if not key.startswith("_")}

    async def course_eligibility(
        self,
        guild_id: int,
        discord_id: int,
        internal_code: str,
        role_ids: Iterable[int],
    ) -> dict[str, object]:
        if self.database.connection is None:
            raise RuntimeError("Banco de dados não inicializado.")
        result = await self._course_eligibility(
            self.database.connection,
            guild_id,
            discord_id,
            internal_code,
            role_ids,
        )
        return self._public_eligibility(result)

    @block_source_cutover_writes("Cursos")
    async def apply_to_course(
        self,
        guild_id: int,
        discord_id: int,
        internal_code: str,
        role_ids: Iterable[int],
    ) -> dict[str, object]:
        now = self.clock()
        async with self.database.transaction() as connection:
            eligibility = await self._course_eligibility(
                connection,
                guild_id,
                discord_id,
                internal_code,
                role_ids,
            )
            if not eligibility["eligible"]:
                raise ConflictError("; ".join(str(item) for item in eligibility["reasons"]))
            member = eligibility["_member"]
            course = eligibility["_course"]
            assert member is not None and course is not None
            public_eligibility = self._public_eligibility(eligibility)
            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO course_applications(
                        guild_id, course_id, member_id, discord_id,
                        eligibility_json, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        int(course["id"]),
                        int(member["id"]),
                        discord_id,
                        json.dumps(public_eligibility, ensure_ascii=False),
                        now,
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                raise ConflictError("Você já possui uma solicitação pendente para esse curso.") from exc
            application_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "COURSE_APPLICATION_SUBMITTED",
                actor_id=discord_id,
                target_id=discord_id,
                after={
                    "application_id": application_id,
                    "course_id": int(course["id"]),
                    "course_name": str(course["name"]),
                },
                connection=connection,
            )
        return {
            "application_id": application_id,
            "course_id": int(course["id"]),
            "course_name": str(course["name"]),
            "status": "PENDING",
        }

    async def course_applications_mine(
        self, guild_id: int, discord_id: int, *, limit: int = 20
    ):
        return await self.database.fetchall(
            """
            SELECT a.*, c.name AS course_name, c.course_role_id
            FROM course_applications a
            JOIN course_catalog c ON c.id=a.course_id
            WHERE a.guild_id=? AND a.discord_id=?
            ORDER BY a.submitted_at DESC, a.id DESC LIMIT ?
            """,
            (guild_id, discord_id, limit),
        )

    async def pending_course_applications(self, guild_id: int, *, limit: int = 25):
        return await self.database.fetchall(
            """
            SELECT a.*, c.name AS course_name, c.course_role_id,
                   c.passing_score, m.mta_nick
            FROM course_applications a
            JOIN course_catalog c ON c.id=a.course_id
            JOIN members m ON m.id=a.member_id
            WHERE a.guild_id=? AND a.status='PENDING'
            ORDER BY a.submitted_at, a.id LIMIT ?
            """,
            (guild_id, limit),
        )

    @block_source_cutover_writes("Cursos")
    async def decide_course_application(
        self,
        guild_id: int,
        application_id: int,
        actor_id: int,
        *,
        approved: bool,
        reason: str,
    ) -> dict[str, object]:
        reason = self._required(reason, "o motivo da decisão")
        status = "APPROVED" if approved else "REJECTED"
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT a.*, c.name AS course_name FROM course_applications a
                JOIN course_catalog c ON c.id=a.course_id
                WHERE a.guild_id=? AND a.id=?
                """,
                (guild_id, application_id),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Solicitação de curso não encontrada.")
            cursor = await connection.execute(
                """
                UPDATE course_applications
                SET status=?, decided_by=?, decided_at=?, decision_reason=?
                WHERE guild_id=? AND id=? AND status='PENDING'
                """,
                (status, actor_id, now, reason, guild_id, application_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Esta solicitação já foi analisada por outra pessoa.")
            await self.audit.record(
                guild_id,
                "COURSE_APPLICATION_DECIDED",
                actor_id=actor_id,
                target_id=int(application["discord_id"]),
                before={"status": "PENDING"},
                after={
                    "status": status,
                    "application_id": application_id,
                    "course_id": int(application["course_id"]),
                    "course_name": str(application["course_name"]),
                },
                reason=reason,
                connection=connection,
            )
        return {
            "application_id": application_id,
            "discord_id": int(application["discord_id"]),
            "course_name": str(application["course_name"]),
            "status": status,
            "reason": reason,
        }
