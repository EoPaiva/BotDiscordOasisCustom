from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable

from .audit import AuditService
from .channel_names import normalize_stylized_label
from .database import Database
from .errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from .personnel import PersonnelService
from .settings import SettingsService
from .shifts import ShiftService
from .time_utils import utc_now_ms

HOUR_MS = 3_600_000

DEFAULT_PROGRESSION: tuple[tuple[str, str, int, int], ...] = (
    ("RECRUTA", "SOLDADO", 4, 0),
    ("SOLDADO", "CABO", 8, 2),
    ("CABO", "3º SARGENTO", 13, 3),
    ("3º SARGENTO", "2º SARGENTO", 19, 4),
    ("2º SARGENTO", "1º SARGENTO", 26, 5),
    ("1º SARGENTO", "SUBTENENTE", 33, 5),
    ("SUBTENENTE", "CADETE", 40, 6),
)


def _rank_lookup_keys(value: object) -> tuple[str, ...]:
    normalized = normalize_stylized_label(str(value or ""))
    if not normalized:
        return ()
    compact = normalized.replace(" ", "")
    return (normalized,) if compact == normalized else (normalized, compact)

OFFICER_COMPETENCY_WEIGHTS: dict[str, int] = {
    "LIDERANCA": 10,
    "DISCIPLINA": 10,
    "ETICA": 10,
    "DECISAO": 10,
    "COMUNICACAO": 10,
    "CONFLITOS": 10,
    "PLANEJAMENTO": 10,
    "GESTAO_DE_PESSOAS": 10,
    "OPERACIONAL": 10,
    "RESPONSABILIDADE": 10,
}

# Três perguntas por competência. A versão fica gravada no banco para que uma
# alteração futura nunca mude o significado de candidaturas já enviadas.
OFFICER_QUESTIONS: tuple[tuple[str, str, str], ...] = (
    ("LIDERANCA", "SCENARIO", "Durante uma operação, parte da equipe perde a confiança no plano. Como você reorganiza a liderança?"),
    ("LIDERANCA", "OPEN", "Descreva uma situação em que você precisou influenciar pessoas sem depender apenas da patente."),
    ("LIDERANCA", "COMMAND", "Como você distribui autoridade e acompanha uma equipe sem centralizar todas as decisões?"),
    ("DISCIPLINA", "SCENARIO", "Um militar competente descumpre um procedimento para obter um resultado rápido. Como você age?"),
    ("DISCIPLINA", "OPEN", "Como você mantém disciplina e constância quando não há supervisão direta?"),
    ("DISCIPLINA", "MANAGEMENT", "Como corrigiria atrasos repetidos de um integrante sem expô-lo desnecessariamente?"),
    ("ETICA", "ETHICAL", "Uma ordem legítima pode prejudicar injustamente um terceiro. Como você avalia e documenta a situação?"),
    ("ETICA", "CONFLICT", "Um amigo próximo é alvo de uma apuração sob sua responsabilidade. Quais salvaguardas você aplica?"),
    ("ETICA", "OPEN", "Quais limites você nunca ultrapassaria para alcançar um resultado operacional?"),
    ("DECISAO", "SCENARIO", "Você recebe informações incompletas e precisa decidir rapidamente. Qual é seu processo?"),
    ("DECISAO", "PRIORITIZATION", "Priorize segurança, missão, comunicação e velocidade em uma ocorrência crítica e justifique."),
    ("DECISAO", "OPEN", "Conte uma decisão difícil que você revisaria hoje e explique o aprendizado."),
    ("COMUNICACAO", "COMMAND", "Como transmite uma ordem complexa para garantir entendimento e possibilidade de confirmação?"),
    ("COMUNICACAO", "CONFLICT", "Dois setores interpretam a mesma orientação de maneiras opostas. Como você alinha os envolvidos?"),
    ("COMUNICACAO", "OPEN", "Como adapta sua comunicação para novatos, pares e superiores sem perder objetividade?"),
    ("CONFLITOS", "CONFLICT", "Dois militares entram em conflito durante a operação. Como intervém sem comprometer a missão?"),
    ("CONFLITOS", "SCENARIO", "Uma crítica pública injusta é dirigida a você. Como responde no momento e depois?"),
    ("CONFLITOS", "MANAGEMENT", "Como diferencia discordância saudável de insubordinação?"),
    ("PLANEJAMENTO", "PRIORITIZATION", "Monte as prioridades para uma operação com equipe reduzida e recursos limitados."),
    ("PLANEJAMENTO", "SCENARIO", "O plano principal falha nos primeiros minutos. Como aciona contingência e comunica a mudança?"),
    ("PLANEJAMENTO", "OPEN", "Quais indicadores usa para saber se um plano está funcionando antes do resultado final?"),
    ("GESTAO_DE_PESSOAS", "MANAGEMENT", "Um integrante apresenta queda de desempenho. Como investiga, apoia e cobra evolução?"),
    ("GESTAO_DE_PESSOAS", "SCENARIO", "Você precisa formar um sucessor. Como escolhe e desenvolve essa pessoa?"),
    ("GESTAO_DE_PESSOAS", "OPEN", "Como reconhece mérito sem criar favoritismo ou competição prejudicial?"),
    ("OPERACIONAL", "SCENARIO", "A situação no terreno diverge do briefing. Quais verificações faz antes de adaptar a operação?"),
    ("OPERACIONAL", "PRIORITIZATION", "Em risco crescente, como equilibra preservação da equipe, contenção e continuidade da missão?"),
    ("OPERACIONAL", "COMMAND", "Como registra e transmite uma passagem de comando durante uma ocorrência prolongada?"),
    ("RESPONSABILIDADE", "ETHICAL", "Uma decisão sua causa um resultado ruim apesar de ter seguido o procedimento. Como presta contas?"),
    ("RESPONSABILIDADE", "OPEN", "Como documenta decisões importantes para permitir auditoria e aprendizado posterior?"),
    ("RESPONSABILIDADE", "MANAGEMENT", "Como reage quando identifica um erro próprio antes que outra pessoa o perceba?"),
)

OFFICER_RED_FLAG_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bmentir\b|\bomitir\b.*\bprova", "Admite ocultação ou falsidade."),
    (r"\bhumilhar\b|\bagredir\b", "Admite tratamento abusivo."),
    (r"qualquer custo|acima de tudo", "Prioriza resultado sem limites claros."),
    (r"ordem e ordem|nao preciso justificar", "Descarta análise ou prestação de contas."),
)


class CareerService:
    """Canonical career progression, merit and officer-candidacy domain service."""

    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
        personnel: PersonnelService,
        shifts: ShiftService,
        *,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit
        self.personnel = personnel
        self.shifts = shifts
        self.clock = clock
        self._member_locks: dict[tuple[int, int], asyncio.Lock] = {}

    def _member_lock(self, guild_id: int, discord_id: int) -> asyncio.Lock:
        return self._member_locks.setdefault((guild_id, discord_id), asyncio.Lock())

    async def ensure_default_progression(self, guild_id: int, actor_id: int | None) -> int:
        ranks = await self.database.fetchall(
            "SELECT id, name, prefix FROM ranks WHERE guild_id=? AND active=1",
            (guild_id,),
        )
        by_key: dict[str, object] = {}
        for rank in ranks:
            for value in (rank["name"], rank["prefix"]):
                for key in _rank_lookup_keys(value):
                    by_key.setdefault(key, rank)

        now = self.clock()
        configured = 0
        async with self.database.transaction() as connection:
            for sequence, (from_name, to_name, total_hours, tenure_hours) in enumerate(
                DEFAULT_PROGRESSION, start=1
            ):
                from_rank = next(
                    (by_key[key] for key in _rank_lookup_keys(from_name) if key in by_key),
                    None,
                )
                to_rank = next(
                    (by_key[key] for key in _rank_lookup_keys(to_name) if key in by_key),
                    None,
                )
                if from_rank is None or to_rank is None:
                    continue
                await connection.execute(
                    """
                    INSERT INTO career_progression_rules(
                        guild_id, sequence_number, from_rank_id, to_rank_id,
                        target_total_ms, minimum_tenure_ms, enabled,
                        created_by, created_at, updated_by, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, from_rank_id) DO UPDATE SET
                        sequence_number=excluded.sequence_number,
                        to_rank_id=excluded.to_rank_id,
                        target_total_ms=excluded.target_total_ms,
                        minimum_tenure_ms=excluded.minimum_tenure_ms,
                        updated_by=excluded.updated_by,
                        updated_at=excluded.updated_at
                    """,
                    (
                        guild_id,
                        sequence,
                        from_rank["id"],
                        to_rank["id"],
                        total_hours * HOUR_MS,
                        tenure_hours * HOUR_MS,
                        actor_id,
                        now,
                        actor_id,
                        now,
                    ),
                )
                configured += 1
            if configured:
                await self.audit.record(
                    guild_id,
                    "CAREER_PROGRESSION_CONFIGURED",
                    actor_id=actor_id,
                    after={"rules": configured, "authority": "CANONICAL_SHIFTS"},
                    connection=connection,
                )
        return configured

    async def progression_rules(self, guild_id: int) -> list[dict[str, object]]:
        rows = await self.database.fetchall(
            """
            SELECT cpr.*, fr.name AS from_rank_name, tr.name AS to_rank_name
            FROM career_progression_rules cpr
            JOIN ranks fr ON fr.id=cpr.from_rank_id
            JOIN ranks tr ON tr.id=cpr.to_rank_id
            WHERE cpr.guild_id=? ORDER BY cpr.sequence_number
            """,
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def career_summary(self, guild_id: int, discord_id: int) -> dict[str, object]:
        profile = await self.personnel.career_profile(guild_id, discord_id)
        valid_hours_ms = await self._valid_hours_ms(guild_id, int(profile["id"]))
        rule = await self.database.fetchone(
            """
            SELECT cpr.target_total_ms, cpr.minimum_tenure_ms,
                   tr.id AS next_rank_id, tr.name AS next_rank_name
            FROM career_progression_rules cpr
            JOIN ranks tr ON tr.id=cpr.to_rank_id
            WHERE cpr.guild_id=? AND cpr.from_rank_id=? AND cpr.enabled=1
            """,
            (guild_id, profile["rank_id"]),
        )
        merit = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN merit_type='POSITIVE' THEN weight ELSE 0 END),0)
                     AS positive_weight,
                   COALESCE(SUM(CASE WHEN merit_type='NEGATIVE' THEN weight ELSE 0 END),0)
                     AS negative_weight
            FROM career_merits WHERE guild_id=? AND member_id=?
            """,
            (guild_id, profile["id"]),
        )
        return {
            "profile": dict(profile),
            "valid_hours_ms": valid_hours_ms,
            "next_progression": dict(rule) if rule else None,
            "merit": dict(merit),
            "officer_eligibility": await self.officer_eligibility(guild_id, discord_id),
        }

    async def process_member(
        self,
        guild_id: int,
        discord_id: int,
        *,
        source: str = "AUTOMATIC_HOURS",
    ) -> dict[str, object]:
        if source not in {"AUTOMATIC_HOURS", "RECOVERY"}:
            raise ValidationError("Origem da progressão inválida.")
        async with self._member_lock(guild_id, discord_id):
            return await self._process_member_locked(guild_id, discord_id, source=source)

    async def _process_member_locked(
        self, guild_id: int, discord_id: int, *, source: str
    ) -> dict[str, object]:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT m.*, r.name AS rank_name, r.level AS rank_level,
                       r.discord_role_id AS rank_role_id,
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
                       ), m.joined_at) AS rank_since
                FROM members m JOIN ranks r ON r.id=m.rank_id
                WHERE m.guild_id=? AND m.discord_id=?
                """,
                (guild_id, discord_id),
            )
            member = await cursor.fetchone()
            if not member:
                raise NotFoundError("Membro ou patente atual não encontrados.")
            cursor = await connection.execute(
                """
                SELECT cpr.*, tr.name AS to_rank_name, tr.prefix AS to_prefix,
                       tr.discord_role_id AS to_role_id
                FROM career_progression_rules cpr
                JOIN ranks tr ON tr.id=cpr.to_rank_id
                WHERE cpr.guild_id=? AND cpr.from_rank_id=? AND cpr.enabled=1
                """,
                (guild_id, member["rank_id"]),
            )
            rule = await cursor.fetchone()
            if not rule:
                status = (
                    "COMPLETE"
                    if normalize_stylized_label(str(member["rank_name"])) == "cadete"
                    else "MANUAL_ONLY"
                )
                return {"status": status, "rank_name": member["rank_name"]}

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
                (guild_id, member["id"]),
            )
            hours_row = await cursor.fetchone()
            valid_hours_ms = max(0, int(hours_row["total_ms"] if hours_row else 0))
            rank_tenure_ms = max(0, now - int(member["rank_since"]))

            if member["status"] != "ACTIVE":
                return {"status": "BLOCKED_STATUS", "member_status": member["status"]}
            if not str(member["mta_nick"] or "").strip() or not str(
                member["character_id"] or ""
            ).strip():
                return {"status": "BLOCKED_IDENTITY"}
            if str(member["rank_sync_status"] or "SYNCED") != "SYNCED":
                return {
                    "status": "BLOCKED_RANK_SYNC",
                    "rank_sync_status": member["rank_sync_status"],
                }
            cursor = await connection.execute(
                """
                SELECT 1 FROM punishments WHERE guild_id=? AND member_id=?
                  AND status IN ('SCHEDULED','ACTIVE') LIMIT 1
                """,
                (guild_id, member["id"]),
            )
            if await cursor.fetchone():
                return {"status": "BLOCKED_PUNISHMENT"}
            if valid_hours_ms < int(rule["target_total_ms"]):
                return {
                    "status": "WAITING_HOURS",
                    "valid_hours_ms": valid_hours_ms,
                    "target_total_ms": int(rule["target_total_ms"]),
                }
            if rank_tenure_ms < int(rule["minimum_tenure_ms"]):
                return {
                    "status": "WAITING_TENURE",
                    "rank_tenure_ms": rank_tenure_ms,
                    "minimum_tenure_ms": int(rule["minimum_tenure_ms"]),
                }

            idempotency_key = (
                f"career:{guild_id}:{member['id']}:{rule['from_rank_id']}:{rule['to_rank_id']}"
            )
            cursor = await connection.execute(
                "SELECT id FROM career_progression_events WHERE idempotency_key=?",
                (idempotency_key,),
            )
            if await cursor.fetchone():
                return {"status": "ALREADY_PROCESSED", "rank_name": member["rank_name"]}

            correlation_id = str(uuid.uuid4())
            update = await connection.execute(
                """
                UPDATE members SET rank_id=?, updated_at=?
                WHERE id=? AND rank_id=? AND status='ACTIVE' AND rank_sync_status='SYNCED'
                """,
                (rule["to_rank_id"], now, member["id"], member["rank_id"]),
            )
            if update.rowcount != 1:
                raise ConflictError("A patente ou situação do membro mudou durante a progressão.")
            reason = (
                "Progressão automática por horas válidas e permanência mínima na patente."
            )
            cursor = await connection.execute(
                """
                INSERT INTO personnel_actions(
                    guild_id, member_id, discord_id, action_type, from_rank_id,
                    to_rank_id, reason, actor_id, created_at, source, correlation_id
                ) VALUES (?, ?, ?, 'PROMOTION', ?, ?, ?, 0, ?, 'AUTOMATIC_HOURS', ?)
                """,
                (
                    guild_id,
                    member["id"],
                    discord_id,
                    member["rank_id"],
                    rule["to_rank_id"],
                    reason,
                    now,
                    correlation_id,
                ),
            )
            action_id = int(cursor.lastrowid)
            await connection.execute(
                """
                INSERT INTO career_progression_events(
                    guild_id, member_id, discord_id, rule_id, personnel_action_id,
                    from_rank_id, to_rank_id, valid_hours_ms, rank_tenure_ms,
                    source, idempotency_key, correlation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    member["id"],
                    discord_id,
                    rule["id"],
                    action_id,
                    member["rank_id"],
                    rule["to_rank_id"],
                    valid_hours_ms,
                    rank_tenure_ms,
                    source,
                    idempotency_key,
                    correlation_id,
                    now,
                ),
            )
            sync_correlation_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO web_action_outbox(
                    guild_id, action_type, target_discord_id, payload_json,
                    requested_by, correlation_id, available_at, created_at
                ) VALUES (?, 'RANK_SYNC', ?, ?, 0, ?, ?, ?)
                """,
                (
                    guild_id,
                    discord_id,
                    json.dumps(
                        {
                            "action": "PROMOTION",
                            "source": source,
                            "from_rank_id": member["rank_id"],
                            "to_rank_id": rule["to_rank_id"],
                        },
                        ensure_ascii=False,
                    ),
                    sync_correlation_id,
                    now,
                    now,
                ),
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="PROMOTION",
                subject_id=action_id,
                target_discord_id=discord_id,
                channel_setting_key="career_promotion_channel_id",
                payload={
                    "discord_id": discord_id,
                    "from_rank_name": member["rank_name"],
                    "to_rank_name": rule["to_rank_name"],
                    "valid_hours_ms": valid_hours_ms,
                    "source": source,
                },
                correlation_id=f"career-notification-{correlation_id}",
                now=now,
            )
            await self.audit.record(
                guild_id,
                "PROMOTION_CREATED",
                actor_id=None,
                target_id=discord_id,
                before={
                    "rank_id": member["rank_id"],
                    "rank_name": member["rank_name"],
                },
                after={
                    "rank_id": rule["to_rank_id"],
                    "rank_name": rule["to_rank_name"],
                    "valid_hours_ms": valid_hours_ms,
                    "rank_tenure_ms": rank_tenure_ms,
                    "source": source,
                    "discord_sync": "PENDING",
                },
                reason=reason,
                correlation_id=f"career-promotion-{correlation_id}",
                connection=connection,
            )
        return {
            "status": "PROMOTED",
            "action_id": action_id,
            "discord_id": discord_id,
            "from_rank_id": int(member["rank_id"]),
            "from_rank_name": str(member["rank_name"]),
            "to_rank_id": int(rule["to_rank_id"]),
            "to_rank_name": str(rule["to_rank_name"]),
            "to_role_id": rule["to_role_id"],
            "valid_hours_ms": valid_hours_ms,
            "rank_tenure_ms": rank_tenure_ms,
            "discord_sync": "PENDING",
        }

    async def process_all(self, guild_id: int, *, source: str = "RECOVERY") -> list[dict[str, object]]:
        rows = await self.database.fetchall(
            """
            SELECT discord_id FROM members
            WHERE guild_id=? AND status='ACTIVE' ORDER BY id
            """,
            (guild_id,),
        )
        results: list[dict[str, object]] = []
        for row in rows:
            result = await self.process_member(
                guild_id, int(row["discord_id"]), source=source
            )
            if result["status"] == "PROMOTED":
                results.append(result)
        return results

    async def create_merit(
        self,
        guild_id: int,
        discord_id: int,
        actor_id: int,
        *,
        merit_type: str,
        category: str,
        weight: int,
        reason: str,
        evidence_locator: str | None = None,
        observation: str | None = None,
    ) -> int:
        merit_type = merit_type.strip().upper()
        category, reason = category.strip(), reason.strip()
        if merit_type not in {"POSITIVE", "NEGATIVE"}:
            raise ValidationError("Tipo de mérito inválido.")
        if not category or not reason:
            raise ValidationError("Categoria e motivo são obrigatórios.")
        if not 1 <= weight <= 10:
            raise ValidationError("O peso precisa ficar entre 1 e 10.")
        category_setting = (
            "career_positive_merit_categories"
            if merit_type == "POSITIVE"
            else "career_negative_merit_categories"
        )
        configured_categories = [
            str(value)
            for value in await self.settings.get(guild_id, category_setting, [])
        ]
        configured_by_key = {
            normalize_stylized_label(value): value for value in configured_categories
        }
        category_key = normalize_stylized_label(category)
        if category_key not in configured_by_key:
            raise ValidationError("A categoria de mérito não está configurada.")
        category = configured_by_key[category_key]
        ranks = await self.database.fetchall(
            "SELECT level, name, prefix FROM ranks WHERE guild_id=? AND active=1",
            (guild_id,),
        )
        cadet_level = next(
            (
                int(rank["level"])
                for rank in ranks
                if "cadete"
                in {
                    normalize_stylized_label(str(rank["name"] or "")),
                    normalize_stylized_label(str(rank["prefix"] or "")),
                }
            ),
            None,
        )
        if cadet_level is None:
            raise ValidationError("A patente Cadete não está configurada.")
        now, correlation_id = self.clock(), str(uuid.uuid4())
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT m.id, r.name AS rank_name, r.level AS rank_level FROM members m
                LEFT JOIN ranks r ON r.id=m.rank_id
                WHERE m.guild_id=? AND m.discord_id=? AND m.status!='DISMISSED'
                """,
                (guild_id, discord_id),
            )
            member = await cursor.fetchone()
            if not member:
                raise NotFoundError("Membro não cadastrado.")
            if member["rank_level"] is None or int(member["rank_level"]) < cadet_level:
                raise ConflictError("Registros de mérito são liberados somente a partir de Cadete.")
            cursor = await connection.execute(
                """
                INSERT INTO career_merits(
                    guild_id, member_id, discord_id, merit_type, category, weight,
                    reason, evidence_locator, observation, actor_id, correlation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    member["id"],
                    discord_id,
                    merit_type,
                    category,
                    weight,
                    reason,
                    evidence_locator.strip() if evidence_locator else None,
                    observation.strip() if observation else None,
                    actor_id,
                    correlation_id,
                    now,
                ),
            )
            merit_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "MERIT_CREATED",
                actor_id=actor_id,
                target_id=discord_id,
                after={
                    "merit_id": merit_id,
                    "type": merit_type,
                    "category": category,
                    "weight": weight,
                    "rank_name": member["rank_name"],
                },
                reason=reason,
                correlation_id=f"career-merit-{correlation_id}",
                connection=connection,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="MERIT",
                subject_id=merit_id,
                target_discord_id=discord_id,
                channel_setting_key=None,
                payload={
                    "discord_id": discord_id,
                    "merit_type": merit_type,
                    "category": category,
                    "weight": weight,
                    "reason": reason,
                },
                correlation_id=f"career-merit-notification-{correlation_id}",
                now=now,
            )
        return merit_id

    async def merit_history(
        self, guild_id: int, discord_id: int, *, limit: int = 50
    ) -> list[dict[str, object]]:
        rows = await self.database.fetchall(
            """
            SELECT * FROM career_merits WHERE guild_id=? AND discord_id=?
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (guild_id, discord_id, max(1, min(limit, 100))),
        )
        return [dict(row) for row in rows]

    async def ensure_officer_questionnaire(
        self, guild_id: int, actor_id: int | None
    ) -> int:
        active = await self.database.fetchone(
            """
            SELECT id FROM officer_questionnaire_versions
            WHERE guild_id=? AND status='ACTIVE'
            """,
            (guild_id,),
        )
        if active:
            count = await self.database.fetchone(
                "SELECT COUNT(*) AS total FROM officer_questions WHERE questionnaire_version_id=?",
                (active["id"],),
            )
            if int(count["total"]) != len(OFFICER_QUESTIONS):
                raise ConflictError(
                    "O questionário ativo está incompleto e precisa de revisão administrativa."
                )
            return int(active["id"])

        now = self.clock()
        async with self.database.transaction() as connection:
            # Bot recovery and the web API can initialize concurrently after a
            # deploy. Recheck while holding the database transaction lock.
            cursor = await connection.execute(
                """
                SELECT id FROM officer_questionnaire_versions
                WHERE guild_id=? AND status='ACTIVE'
                """,
                (guild_id,),
            )
            concurrent_active = await cursor.fetchone()
            if concurrent_active:
                cursor = await connection.execute(
                    """
                    SELECT COUNT(*) AS total FROM officer_questions
                    WHERE questionnaire_version_id=?
                    """,
                    (concurrent_active["id"],),
                )
                count = await cursor.fetchone()
                if int(count["total"]) != len(OFFICER_QUESTIONS):
                    raise ConflictError(
                        "O questionário ativo está incompleto e precisa de revisão administrativa."
                    )
                return int(concurrent_active["id"])
            cursor = await connection.execute(
                """
                SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
                FROM officer_questionnaire_versions WHERE guild_id=?
                """,
                (guild_id,),
            )
            version_row = await cursor.fetchone()
            cursor = await connection.execute(
                """
                INSERT INTO officer_questionnaire_versions(
                    guild_id, version_number, status, title, weights_json,
                    criteria_json, created_by, created_at, activated_at
                ) VALUES (?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    int(version_row["next_version"]),
                    "Candidatura ao Oficialato — Avaliação Profissional",
                    json.dumps(OFFICER_COMPETENCY_WEIGHTS, ensure_ascii=False),
                    json.dumps(
                        {
                            "advisory_only": True,
                            "score_range": [1, 10],
                            "final_decision": "HUMAN",
                            "question_count": len(OFFICER_QUESTIONS),
                        },
                        ensure_ascii=False,
                    ),
                    actor_id,
                    now,
                    now,
                ),
            )
            version_id = int(cursor.lastrowid)
            await connection.executemany(
                """
                INSERT INTO officer_questions(
                    questionnaire_version_id, question_number, competency,
                    question_type, prompt, weight, red_flag_rules_json
                ) VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    (
                        version_id,
                        number,
                        competency,
                        question_type,
                        prompt,
                        json.dumps(
                            [pattern for pattern, _ in OFFICER_RED_FLAG_PATTERNS],
                            ensure_ascii=False,
                        ),
                    )
                    for number, (competency, question_type, prompt) in enumerate(
                        OFFICER_QUESTIONS, start=1
                    )
                ),
            )
            await self.audit.record(
                guild_id,
                "OFFICER_QUESTIONNAIRE_ACTIVATED",
                actor_id=actor_id,
                after={
                    "questionnaire_version_id": version_id,
                    "question_count": len(OFFICER_QUESTIONS),
                    "final_decision": "HUMAN",
                },
                connection=connection,
            )
        return version_id

    async def officer_questionnaire(self, guild_id: int) -> dict[str, object]:
        version = await self.database.fetchone(
            """
            SELECT * FROM officer_questionnaire_versions
            WHERE guild_id=? AND status='ACTIVE'
            """,
            (guild_id,),
        )
        if not version:
            raise NotFoundError("O questionário do oficialato ainda não foi configurado.")
        questions = await self.database.fetchall(
            """
            SELECT id, question_number, competency, question_type, prompt, weight
            FROM officer_questions WHERE questionnaire_version_id=?
            ORDER BY question_number
            """,
            (version["id"],),
        )
        return {
            "id": int(version["id"]),
            "version_number": int(version["version_number"]),
            "title": str(version["title"]),
            "weights": json.loads(str(version["weights_json"])),
            "criteria": json.loads(str(version["criteria_json"])),
            "questions": [dict(row) for row in questions],
        }

    async def _valid_hours_ms(self, guild_id: int, member_id: int) -> int:
        row = await self.database.fetchone(
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
            (guild_id, member_id),
        )
        return max(0, int(row["total_ms"] if row else 0))

    async def officer_eligibility(
        self, guild_id: int, discord_id: int
    ) -> dict[str, object]:
        member = await self.database.fetchone(
            """
            SELECT m.id, m.status, m.mta_nick, m.character_id,
                   m.identity_sync_status, m.discord_present,
                   r.id AS rank_id, r.name AS rank_name, r.prefix AS rank_prefix,
                   r.level AS rank_level
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        if not member:
            raise NotFoundError("Membro não cadastrado.")
        minimum_name = str(
            await self.settings.get(guild_id, "officer_minimum_rank_name", "SOLDADO")
        )
        rank_rows = await self.database.fetchall(
            "SELECT id, level, name, prefix FROM ranks WHERE guild_id=? AND active=1",
            (guild_id,),
        )
        minimum_rank = next(
            (
                row
                for row in rank_rows
                if normalize_stylized_label(str(row["name"] or ""))
                == normalize_stylized_label(minimum_name)
                or normalize_stylized_label(str(row["prefix"] or ""))
                == normalize_stylized_label(minimum_name)
            ),
            None,
        )
        minimum_hours = max(
            0, int(await self.settings.get(guild_id, "officer_minimum_valid_hours", 5))
        )
        valid_hours_ms = await self._valid_hours_ms(guild_id, int(member["id"]))
        now = self.clock()
        last_rejection = await self.database.fetchone(
            """
            SELECT resubmit_after FROM officer_applications
            WHERE guild_id=? AND member_id=? AND status='REJECTED'
            ORDER BY reviewed_at DESC, id DESC LIMIT 1
            """,
            (guild_id, member["id"]),
        )
        active = await self.database.fetchone(
            """
            SELECT id, status FROM officer_applications
            WHERE guild_id=? AND member_id=?
              AND status IN ('DRAFT','SUBMITTED','IN_REVIEW','INTERVIEW_REQUIRED','RETURNED')
            ORDER BY id DESC LIMIT 1
            """,
            (guild_id, member["id"]),
        )
        missing: list[str] = []
        if member["status"] != "ACTIVE":
            missing.append("STATUS")
        if not str(member["mta_nick"] or "").strip() or not str(
            member["character_id"] or ""
        ).strip():
            missing.append("IDENTIDADE")
        if str(member["identity_sync_status"] or "") != "SYNCED" or not bool(
            member["discord_present"]
        ):
            missing.append("VINCULO_DISCORD")
        if (
            minimum_rank is None
            or member["rank_level"] is None
            or int(member["rank_level"]) < int(minimum_rank["level"])
        ):
            missing.append("PATENTE")
        if valid_hours_ms < minimum_hours * HOUR_MS:
            missing.append("HORAS")
        resubmit_after = (
            int(last_rejection["resubmit_after"])
            if last_rejection and last_rejection["resubmit_after"] is not None
            else None
        )
        if resubmit_after is not None and resubmit_after > now:
            missing.append("COOLDOWN")
        return {
            "eligible": not missing,
            "missing": missing,
            "member_id": int(member["id"]),
            "rank_id": int(member["rank_id"]) if member["rank_id"] is not None else None,
            "rank_name": member["rank_name"],
            "minimum_rank_name": minimum_name,
            "valid_hours_ms": valid_hours_ms,
            "minimum_valid_hours_ms": minimum_hours * HOUR_MS,
            "resubmit_after": resubmit_after,
            "active_application": dict(active) if active else None,
        }

    async def start_officer_application(
        self, guild_id: int, discord_id: int
    ) -> dict[str, object]:
        existing = await self.database.fetchone(
            """
            SELECT * FROM officer_applications
            WHERE guild_id=? AND discord_id=?
              AND status IN ('DRAFT','SUBMITTED','IN_REVIEW','INTERVIEW_REQUIRED','RETURNED')
            ORDER BY id DESC LIMIT 1
            """,
            (guild_id, discord_id),
        )
        if existing:
            return dict(existing)
        eligibility = await self.officer_eligibility(guild_id, discord_id)
        if not eligibility["eligible"]:
            if "COOLDOWN" in eligibility["missing"]:
                raise ConflictError("É necessário aguardar o período de reaplicação.")
            raise ConflictError(
                "Os requisitos mínimos ainda não foram atendidos: "
                + ", ".join(str(item) for item in eligibility["missing"])
                + "."
            )
        questionnaire_id = await self.ensure_officer_questionnaire(guild_id, actor_id=None)
        member = await self.database.fetchone(
            """
            SELECT m.id, m.discord_id, m.mta_nick, m.character_id, m.unit,
                   m.joined_at, m.rank_id, r.name AS rank_name, r.level AS rank_level
            FROM members m LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        merits = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN merit_type='POSITIVE' THEN weight ELSE 0 END),0)
                     AS positive_weight,
                   COALESCE(SUM(CASE WHEN merit_type='NEGATIVE' THEN weight ELSE 0 END),0)
                     AS negative_weight
            FROM career_merits WHERE guild_id=? AND member_id=?
            """,
            (guild_id, member["id"]),
        )
        now, correlation_id = self.clock(), str(uuid.uuid4())
        identity_snapshot = {
            "discord_id": discord_id,
            "mta_nick": member["mta_nick"],
            "character_id": member["character_id"],
            "unit": member["unit"],
        }
        career_snapshot = {
            "rank_id": member["rank_id"],
            "rank_name": member["rank_name"],
            "rank_level": member["rank_level"],
            "joined_at": member["joined_at"],
            "valid_hours_ms": eligibility["valid_hours_ms"],
            "merits": dict(merits),
        }
        async with self.database.transaction() as connection:
            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO officer_applications(
                        guild_id, member_id, discord_id, questionnaire_version_id,
                        status, identity_snapshot_json, career_snapshot_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        member["id"],
                        discord_id,
                        questionnaire_id,
                        json.dumps(identity_snapshot, ensure_ascii=False),
                        json.dumps(career_snapshot, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            except Exception as exc:
                duplicate = await connection.execute(
                    """
                    SELECT * FROM officer_applications
                    WHERE guild_id=? AND member_id=?
                      AND status IN ('DRAFT','SUBMITTED','IN_REVIEW','INTERVIEW_REQUIRED','RETURNED')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (guild_id, member["id"]),
                )
                row = await duplicate.fetchone()
                if row:
                    return dict(row)
                raise exc
            application_id = int(cursor.lastrowid)
            await self._record_officer_event(
                connection,
                application_id,
                "APPLICATION_CREATED",
                actor_id=discord_id,
                previous_status=None,
                next_status="DRAFT",
                reason=None,
                metadata={"eligibility": eligibility},
                correlation_id=correlation_id,
                occurred_at=now,
            )
            await self.audit.record(
                guild_id,
                "OFFICER_APPLICATION_CREATED",
                actor_id=discord_id,
                target_id=discord_id,
                after={"application_id": application_id, "status": "DRAFT"},
                correlation_id=f"officer-application-{correlation_id}",
                connection=connection,
            )
        created = await self.database.fetchone(
            "SELECT * FROM officer_applications WHERE id=?", (application_id,)
        )
        return dict(created)

    async def save_officer_answer(
        self,
        guild_id: int,
        application_id: int,
        actor_id: int,
        question_id: int,
        answer_text: str,
    ) -> dict[str, object]:
        answer = answer_text.strip()
        if len(answer) < 20:
            raise ValidationError("A resposta precisa ter pelo menos 20 caracteres.")
        if len(answer) > 4_000:
            raise ValidationError("A resposta excede o limite de 4.000 caracteres.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT oa.id, oa.discord_id, oa.status, oa.questionnaire_version_id
                FROM officer_applications oa
                WHERE oa.id=? AND oa.guild_id=?
                """,
                (application_id, guild_id),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Candidatura não encontrada.")
            if int(application["discord_id"]) != actor_id:
                raise PermissionDenied("Somente o candidato pode editar as respostas.")
            if application["status"] not in {"DRAFT", "RETURNED"}:
                raise ConflictError("Esta candidatura não aceita mais alterações.")
            cursor = await connection.execute(
                """
                SELECT id FROM officer_questions
                WHERE id=? AND questionnaire_version_id=?
                """,
                (question_id, application["questionnaire_version_id"]),
            )
            if not await cursor.fetchone():
                raise ValidationError("Pergunta inválida para esta candidatura.")
            await connection.execute(
                """
                INSERT INTO officer_answers(
                    application_id, question_id, answer_text, answered_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(application_id, question_id) DO UPDATE SET
                    answer_text=excluded.answer_text,
                    updated_at=excluded.updated_at
                """,
                (application_id, question_id, answer, now, now),
            )
            await connection.execute(
                """
                UPDATE officer_applications SET updated_at=?, version=version+1
                WHERE id=?
                """,
                (now, application_id),
            )
        return {"application_id": application_id, "question_id": question_id, "saved": True}

    @staticmethod
    def _score_answer(answer: str) -> tuple[int, list[str]]:
        normalized = normalize_stylized_label(answer)
        score = 4
        if len(answer) >= 80:
            score += 1
        if len(answer) >= 150:
            score += 1
        if len(answer) >= 260:
            score += 1
        reasoning_terms = ("porque", "portanto", "depois", "antes", "risco", "justific")
        if sum(term in normalized for term in reasoning_terms) >= 2:
            score += 1
        accountability_terms = ("registro", "document", "comunic", "responsabil", "etica")
        if sum(term in normalized for term in accountability_terms) >= 2:
            score += 1
        flags: list[str] = []
        for pattern, description in OFFICER_RED_FLAG_PATTERNS:
            if re.search(pattern, normalized):
                flags.append(description)
        score -= min(4, len(flags) * 2)
        return max(1, min(10, score)), flags

    async def _analyze_officer_application(
        self, connection, application_id: int
    ) -> tuple[dict[str, object], list[tuple[int, int, str]]]:
        cursor = await connection.execute(
            """
            SELECT oq.id AS question_id, oq.question_number, oq.competency,
                   oa.answer_text
            FROM officer_questions oq
            JOIN officer_applications app
              ON app.questionnaire_version_id=oq.questionnaire_version_id
             AND app.id=?
            JOIN officer_answers oa
              ON oa.application_id=app.id AND oa.question_id=oq.id
            ORDER BY oq.question_number
            """,
            (application_id,),
        )
        rows = await cursor.fetchall()
        scores: list[tuple[int, int, str]] = []
        competency_scores: dict[str, list[int]] = {}
        red_flags: list[dict[str, object]] = []
        normalized_answers: list[str] = []
        for row in rows:
            answer = str(row["answer_text"])
            score, flags = self._score_answer(answer)
            competency = str(row["competency"])
            competency_scores.setdefault(competency, []).append(score)
            normalized_answers.append(normalize_stylized_label(answer))
            rationale = (
                "Pontuação consultiva baseada em completude, justificativa, "
                "responsabilização e sinais de risco textual."
            )
            scores.append((int(row["question_id"]), score, rationale))
            for flag in flags:
                red_flags.append(
                    {"question_number": int(row["question_number"]), "reason": flag}
                )
        competencies = {
            competency: round(sum(values) / len(values), 2)
            for competency, values in competency_scores.items()
        }
        overall = round(
            sum(
                competencies[name] * OFFICER_COMPETENCY_WEIGHTS[name]
                for name in OFFICER_COMPETENCY_WEIGHTS
            )
            / 100,
            2,
        )
        consistency_flags: list[str] = []
        if len(set(normalized_answers)) < len(normalized_answers) * 0.75:
            consistency_flags.append("Há respostas excessivamente repetidas.")
        short_answers = sum(len(value) < 80 for value in normalized_answers)
        if short_answers >= 5:
            consistency_flags.append("Há várias respostas com pouca fundamentação.")
        if overall >= 8 and not red_flags:
            profile = "FORTE"
            recommendation = "Prosseguir para avaliação humana detalhada."
        elif overall >= 6:
            profile = "COMPATIVEL_COM_RESSALVAS"
            recommendation = "Recomenda-se entrevista humana para esclarecer ressalvas."
        else:
            profile = "DESENVOLVIMENTO_NECESSARIO"
            recommendation = "Recomenda-se análise humana cuidadosa antes de avançar."
        report: dict[str, object] = {
            "advisory_only": True,
            "authority": "HUMAN_REVIEW",
            "method": "DETERMINISTIC_LOCAL_RULES_V1",
            "overall_score": overall,
            "competencies": competencies,
            "red_flags": red_flags,
            "consistency_flags": consistency_flags,
            "profile": profile,
            "recommendation": recommendation,
        }
        return report, scores

    async def submit_officer_application(
        self, guild_id: int, application_id: int, actor_id: int
    ) -> dict[str, object]:
        now, correlation_id = self.clock(), str(uuid.uuid4())
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM officer_applications WHERE id=? AND guild_id=?",
                (application_id, guild_id),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Candidatura não encontrada.")
            if int(application["discord_id"]) != actor_id:
                raise PermissionDenied("Somente o candidato pode enviar a candidatura.")
            if application["status"] == "SUBMITTED":
                report = json.loads(str(application["analysis_report_json"] or "{}"))
                return {"id": application_id, "status": "SUBMITTED", "analysis": report}
            if application["status"] not in {"DRAFT", "RETURNED"}:
                raise ConflictError("Esta candidatura não pode ser enviada neste estado.")
            cursor = await connection.execute(
                """
                SELECT COUNT(*) AS total FROM officer_answers oa
                JOIN officer_questions oq ON oq.id=oa.question_id
                WHERE oa.application_id=? AND oq.questionnaire_version_id=?
                  AND LENGTH(TRIM(oa.answer_text))>=20
                """,
                (application_id, application["questionnaire_version_id"]),
            )
            answer_count = int((await cursor.fetchone())["total"])
            if answer_count != 30:
                raise ValidationError("Responda as 30 perguntas antes de enviar.")
            report, scores = await self._analyze_officer_application(
                connection, application_id
            )
            await connection.executemany(
                """
                INSERT INTO officer_question_scores(
                    application_id, question_id, score, rationale, evaluator_id,
                    source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, 'RULES', ?, ?)
                ON CONFLICT(application_id, question_id, source) DO UPDATE SET
                    score=excluded.score, rationale=excluded.rationale,
                    updated_at=excluded.updated_at
                """,
                (
                    (application_id, question_id, score, rationale, now, now)
                    for question_id, score, rationale in scores
                ),
            )
            update = await connection.execute(
                """
                UPDATE officer_applications
                SET status='SUBMITTED', submitted_at=COALESCE(submitted_at, ?),
                    score_summary_json=?, analysis_report_json=?,
                    assigned_to=NULL, assigned_at=NULL,
                    updated_at=?, version=version+1
                WHERE id=? AND version=? AND status IN ('DRAFT','RETURNED')
                """,
                (
                    now,
                    json.dumps(
                        {
                            "overall_score": report["overall_score"],
                            "competencies": report["competencies"],
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(report, ensure_ascii=False),
                    now,
                    application_id,
                    application["version"],
                ),
            )
            if update.rowcount != 1:
                raise ConflictError("A candidatura mudou durante o envio.")
            await self._record_officer_event(
                connection,
                application_id,
                "APPLICATION_SUBMITTED",
                actor_id=actor_id,
                previous_status=str(application["status"]),
                next_status="SUBMITTED",
                reason=None,
                metadata={"analysis_method": report["method"]},
                correlation_id=correlation_id,
                occurred_at=now,
            )
            await self.audit.record(
                guild_id,
                "OFFICER_APPLICATION_SUBMITTED",
                actor_id=actor_id,
                target_id=actor_id,
                after={
                    "application_id": application_id,
                    "status": "SUBMITTED",
                    "analysis_authority": "ADVISORY_ONLY",
                },
                correlation_id=f"officer-submit-{correlation_id}",
                connection=connection,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="OFFICER_SUBMITTED",
                subject_id=application_id,
                target_discord_id=actor_id,
                channel_setting_key="officer_upamento_channel_id",
                payload={
                    "application_id": application_id,
                    "discord_id": actor_id,
                    "status": "SUBMITTED",
                    "overall_score": report["overall_score"],
                    "advisory_only": True,
                },
                correlation_id=f"officer-submit-notification-{correlation_id}",
                now=now,
            )
        return {"id": application_id, "status": "SUBMITTED", "analysis": report}

    async def claim_officer_application(
        self, guild_id: int, application_id: int, actor_id: int
    ) -> dict[str, object]:
        now, correlation_id = self.clock(), str(uuid.uuid4())
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM officer_applications WHERE id=? AND guild_id=?",
                (application_id, guild_id),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Candidatura não encontrada.")
            if int(application["discord_id"]) == actor_id:
                raise PermissionDenied("Você não pode assumir a própria candidatura.")
            if application["assigned_to"] is not None:
                if int(application["assigned_to"]) == actor_id:
                    return dict(application)
                raise ConflictError("A candidatura já possui outro responsável.")
            if application["status"] != "SUBMITTED":
                raise ConflictError("A candidatura ainda não está disponível para análise.")
            update = await connection.execute(
                """
                UPDATE officer_applications
                SET status='IN_REVIEW', assigned_to=?, assigned_at=?,
                    updated_at=?, version=version+1
                WHERE id=? AND version=? AND status='SUBMITTED' AND assigned_to IS NULL
                """,
                (actor_id, now, now, application_id, application["version"]),
            )
            if update.rowcount != 1:
                raise ConflictError("A candidatura foi assumida simultaneamente.")
            await self._record_officer_event(
                connection,
                application_id,
                "REVIEW_CLAIMED",
                actor_id=actor_id,
                previous_status="SUBMITTED",
                next_status="IN_REVIEW",
                reason=None,
                metadata={},
                correlation_id=correlation_id,
                occurred_at=now,
            )
        row = await self.database.fetchone(
            "SELECT * FROM officer_applications WHERE id=?", (application_id,)
        )
        return dict(row)

    async def decide_officer_application(
        self,
        guild_id: int,
        application_id: int,
        actor_id: int,
        *,
        decision: str,
        reason: str,
        condition_text: str | None = None,
        condition_due_at: int | None = None,
    ) -> dict[str, object]:
        decision, decision_reason = decision.strip().upper(), reason.strip()
        allowed = {"APPROVED", "APPROVED_CONDITIONAL", "REJECTED", "RETURNED"}
        if decision not in allowed:
            raise ValidationError("Decisão de oficialato inválida.")
        if len(decision_reason) < 10:
            raise ValidationError("A justificativa da decisão é obrigatória.")
        condition = condition_text.strip() if condition_text else ""
        if decision == "APPROVED_CONDITIONAL" and not condition:
            raise ValidationError("Informe a condição da aprovação.")
        now, correlation_id = self.clock(), str(uuid.uuid4())
        cooldown_days = max(
            0, int(await self.settings.get(guild_id, "officer_reapplication_days", 30))
        )
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM officer_applications WHERE id=? AND guild_id=?",
                (application_id, guild_id),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Candidatura não encontrada.")
            if int(application["discord_id"]) == actor_id:
                raise PermissionDenied("Você não pode decidir a própria candidatura.")
            if application["assigned_to"] is None:
                raise ConflictError("A candidatura precisa ser assumida antes da decisão.")
            if int(application["assigned_to"]) != actor_id:
                raise PermissionDenied("Somente o responsável atual pode decidir.")
            if application["status"] not in {"IN_REVIEW", "INTERVIEW_REQUIRED"}:
                raise ConflictError("A candidatura não está em decisão.")
            resubmit_after = (
                now + cooldown_days * 24 * HOUR_MS if decision == "REJECTED" else None
            )
            update = await connection.execute(
                """
                UPDATE officer_applications
                SET status=?, reviewed_by=?, reviewed_at=?, decision_reason=?,
                    result_released_at=?, resubmit_after=?, updated_at=?, version=version+1
                WHERE id=? AND version=? AND assigned_to=?
                  AND status IN ('IN_REVIEW','INTERVIEW_REQUIRED')
                """,
                (
                    decision,
                    actor_id,
                    now,
                    decision_reason,
                    now,
                    resubmit_after,
                    now,
                    application_id,
                    application["version"],
                    actor_id,
                ),
            )
            if update.rowcount != 1:
                raise ConflictError("A candidatura mudou durante a decisão.")
            if decision == "APPROVED_CONDITIONAL":
                await connection.execute(
                    """
                    INSERT INTO officer_conditions(
                        application_id, condition_text, due_at, responsible_id,
                        status, created_at
                    ) VALUES (?, ?, ?, ?, 'OPEN', ?)
                    """,
                    (application_id, condition, condition_due_at, actor_id, now),
                )
            await self._record_officer_event(
                connection,
                application_id,
                "HUMAN_DECISION_RECORDED",
                actor_id=actor_id,
                previous_status=str(application["status"]),
                next_status=decision,
                reason=decision_reason,
                metadata={
                    "authority": "HUMAN",
                    "condition": condition or None,
                    "resubmit_after": resubmit_after,
                },
                correlation_id=correlation_id,
                occurred_at=now,
            )
            await self.audit.record(
                guild_id,
                "OFFICER_APPLICATION_DECIDED",
                actor_id=actor_id,
                target_id=int(application["discord_id"]),
                before={"status": application["status"]},
                after={
                    "application_id": application_id,
                    "status": decision,
                    "authority": "HUMAN",
                    "resubmit_after": resubmit_after,
                },
                reason=decision_reason,
                correlation_id=f"officer-decision-{correlation_id}",
                connection=connection,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="OFFICER_DECISION",
                subject_id=application_id,
                target_discord_id=int(application["discord_id"]),
                channel_setting_key="officer_upamento_channel_id",
                payload={
                    "application_id": application_id,
                    "discord_id": int(application["discord_id"]),
                    "status": decision,
                    "reason": decision_reason,
                    "condition": condition or None,
                    "resubmit_after": resubmit_after,
                    "authority": "HUMAN",
                },
                correlation_id=f"officer-decision-notification-{correlation_id}",
                now=now,
            )
        row = await self.database.fetchone(
            "SELECT * FROM officer_applications WHERE id=?", (application_id,)
        )
        return dict(row)

    async def officer_application_detail(
        self,
        guild_id: int,
        application_id: int,
        *,
        viewer_id: int,
        reviewer: bool,
    ) -> dict[str, object]:
        application = await self.database.fetchone(
            "SELECT * FROM officer_applications WHERE id=? AND guild_id=?",
            (application_id, guild_id),
        )
        if not application:
            raise NotFoundError("Candidatura não encontrada.")
        if not reviewer and int(application["discord_id"]) != viewer_id:
            raise PermissionDenied("Esta candidatura pertence a outro membro.")
        answers = await self.database.fetchall(
            """
            SELECT oq.id AS question_id, oq.question_number, oq.competency,
                   oq.question_type, oq.prompt,
                   oa.answer_text, oa.updated_at
            FROM officer_questions oq
            LEFT JOIN officer_answers oa
              ON oa.question_id=oq.id AND oa.application_id=?
            WHERE oq.questionnaire_version_id=? ORDER BY oq.question_number
            """,
            (application_id, application["questionnaire_version_id"]),
        )
        conditions = await self.database.fetchall(
            "SELECT * FROM officer_conditions WHERE application_id=? ORDER BY id",
            (application_id,),
        )
        interviews = await self.database.fetchall(
            "SELECT * FROM officer_interviews WHERE application_id=? ORDER BY id",
            (application_id,),
        )
        events = await self.database.fetchall(
            """
            SELECT event_type, previous_status, next_status, actor_id, reason,
                   metadata_json, occurred_at
            FROM officer_application_events WHERE application_id=?
            ORDER BY occurred_at, id
            """,
            (application_id,),
        )
        payload: dict[str, object] = {
            "application": dict(application),
            "identity_snapshot": json.loads(str(application["identity_snapshot_json"])),
            "career_snapshot": json.loads(str(application["career_snapshot_json"])),
            "answers": [dict(row) for row in answers],
            "conditions": [dict(row) for row in conditions],
            "interviews": [dict(row) for row in interviews],
            "events": [dict(row) for row in events],
        }
        if reviewer:
            payload["score_summary"] = json.loads(
                str(application["score_summary_json"] or "{}")
            )
            payload["analysis_report"] = json.loads(
                str(application["analysis_report_json"] or "{}")
            )
            scores = await self.database.fetchall(
                """
                SELECT oq.question_number, oq.competency, oqs.score, oqs.rationale,
                       oqs.evaluator_id, oqs.source, oqs.updated_at
                FROM officer_question_scores oqs
                JOIN officer_questions oq ON oq.id=oqs.question_id
                WHERE oqs.application_id=? ORDER BY oq.question_number, oqs.source
                """,
                (application_id,),
            )
            payload["scores"] = [dict(row) for row in scores]
        else:
            public_application = dict(application)
            public_application.pop("analysis_report_json", None)
            public_application.pop("score_summary_json", None)
            payload["application"] = public_application
            payload["conditions"] = [
                {
                    key: row[key]
                    for key in (
                        "id",
                        "condition_text",
                        "due_at",
                        "status",
                        "created_at",
                        "resolved_at",
                    )
                }
                for row in conditions
            ]
            payload["interviews"] = [
                {
                    key: row[key]
                    for key in ("id", "scheduled_at", "completed_at", "result", "created_at")
                }
                for row in interviews
            ]
            payload["events"] = [
                {
                    key: row[key]
                    for key in (
                        "event_type",
                        "previous_status",
                        "next_status",
                        "occurred_at",
                    )
                }
                for row in events
            ]
        return payload

    async def officer_queue(
        self,
        guild_id: int,
        *,
        status: str | None = None,
        assigned_to: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        filters, params = ["oa.guild_id=?", "oa.status!='DRAFT'"], [guild_id]
        if status:
            filters.append("oa.status=?")
            params.append(status.strip().upper())
        if assigned_to is not None:
            filters.append("oa.assigned_to=?")
            params.append(assigned_to)
        params.append(max(1, min(limit, 200)))
        rows = await self.database.fetchall(
            f"""
            SELECT oa.id, oa.discord_id, oa.status, oa.assigned_to, oa.assigned_at,
                   oa.submitted_at, oa.reviewed_by, oa.reviewed_at,
                   oa.result_released_at, oa.version, oa.created_at, oa.updated_at,
                   m.mta_nick, m.character_id, r.name AS rank_name
            FROM officer_applications oa
            JOIN members m ON m.id=oa.member_id
            LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE {' AND '.join(filters)}
            ORDER BY CASE WHEN oa.status='SUBMITTED' THEN 0 ELSE 1 END,
                     COALESCE(oa.submitted_at, oa.created_at), oa.id
            LIMIT ?
            """,
            tuple(params),
        )
        return [dict(row) for row in rows]

    async def current_officer_application(
        self, guild_id: int, discord_id: int
    ) -> dict[str, object] | None:
        row = await self.database.fetchone(
            """
            SELECT id FROM officer_applications
            WHERE guild_id=? AND discord_id=? ORDER BY id DESC LIMIT 1
            """,
            (guild_id, discord_id),
        )
        if not row:
            return None
        return await self.officer_application_detail(
            guild_id, int(row["id"]), viewer_id=discord_id, reviewer=False
        )

    async def record_officer_score(
        self,
        guild_id: int,
        application_id: int,
        actor_id: int,
        *,
        question_id: int,
        score: int,
        rationale: str,
    ) -> dict[str, object]:
        explanation = rationale.strip()
        if not 1 <= score <= 10:
            raise ValidationError("A nota precisa ficar entre 1 e 10.")
        if len(explanation) < 5:
            raise ValidationError("Justifique a nota atribuída.")
        now, correlation_id = self.clock(), str(uuid.uuid4())
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM officer_applications WHERE id=? AND guild_id=?",
                (application_id, guild_id),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Candidatura não encontrada.")
            if int(application["discord_id"]) == actor_id:
                raise PermissionDenied("Você não pode avaliar a própria candidatura.")
            if application["assigned_to"] is None or int(
                application["assigned_to"]
            ) != actor_id:
                raise PermissionDenied("Somente o responsável atual pode registrar notas.")
            if application["status"] not in {"IN_REVIEW", "INTERVIEW_REQUIRED"}:
                raise ConflictError("A candidatura não está em avaliação.")
            cursor = await connection.execute(
                """
                SELECT id FROM officer_questions
                WHERE id=? AND questionnaire_version_id=?
                """,
                (question_id, application["questionnaire_version_id"]),
            )
            if not await cursor.fetchone():
                raise ValidationError("Pergunta inválida para esta candidatura.")
            await connection.execute(
                """
                INSERT INTO officer_question_scores(
                    application_id, question_id, score, rationale, evaluator_id,
                    source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'HUMAN', ?, ?)
                ON CONFLICT(application_id, question_id, source) DO UPDATE SET
                    score=excluded.score, rationale=excluded.rationale,
                    evaluator_id=excluded.evaluator_id, updated_at=excluded.updated_at
                """,
                (application_id, question_id, score, explanation, actor_id, now, now),
            )
            await connection.execute(
                """
                UPDATE officer_applications SET updated_at=?, version=version+1 WHERE id=?
                """,
                (now, application_id),
            )
            await self._record_officer_event(
                connection,
                application_id,
                "HUMAN_SCORE_RECORDED",
                actor_id=actor_id,
                previous_status=str(application["status"]),
                next_status=str(application["status"]),
                reason=explanation,
                metadata={"question_id": question_id, "score": score},
                correlation_id=correlation_id,
                occurred_at=now,
            )
        return {
            "application_id": application_id,
            "question_id": question_id,
            "score": score,
            "source": "HUMAN",
        }

    async def record_officer_interview(
        self,
        guild_id: int,
        application_id: int,
        actor_id: int,
        *,
        scheduled_at: int | None,
        result: str,
        observations: str | None,
    ) -> dict[str, object]:
        normalized_result = result.strip().upper()
        if normalized_result not in {"PENDING", "POSITIVE", "NEUTRAL", "NEGATIVE"}:
            raise ValidationError("Resultado da entrevista inválido.")
        note = observations.strip() if observations else None
        now, correlation_id = self.clock(), str(uuid.uuid4())
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM officer_applications WHERE id=? AND guild_id=?",
                (application_id, guild_id),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Candidatura não encontrada.")
            if int(application["discord_id"]) == actor_id:
                raise PermissionDenied("Você não pode entrevistar a si próprio.")
            if application["assigned_to"] is None or int(
                application["assigned_to"]
            ) != actor_id:
                raise PermissionDenied("Somente o responsável atual pode registrar a entrevista.")
            if application["status"] not in {"IN_REVIEW", "INTERVIEW_REQUIRED"}:
                raise ConflictError("A candidatura não está em etapa de entrevista.")
            completed_at = now if normalized_result != "PENDING" else None
            cursor = await connection.execute(
                """
                INSERT INTO officer_interviews(
                    application_id, interviewer_id, scheduled_at, completed_at,
                    result, observations, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application_id,
                    actor_id,
                    scheduled_at,
                    completed_at,
                    normalized_result,
                    note,
                    now,
                ),
            )
            interview_id = int(cursor.lastrowid)
            update = await connection.execute(
                """
                UPDATE officer_applications
                SET status='INTERVIEW_REQUIRED', updated_at=?, version=version+1
                WHERE id=? AND version=? AND status IN ('IN_REVIEW','INTERVIEW_REQUIRED')
                """,
                (now, application_id, application["version"]),
            )
            if update.rowcount != 1:
                raise ConflictError("A candidatura mudou durante o registro da entrevista.")
            await self._record_officer_event(
                connection,
                application_id,
                "INTERVIEW_RECORDED",
                actor_id=actor_id,
                previous_status=str(application["status"]),
                next_status="INTERVIEW_REQUIRED",
                reason=note,
                metadata={
                    "interview_id": interview_id,
                    "scheduled_at": scheduled_at,
                    "result": normalized_result,
                },
                correlation_id=correlation_id,
                occurred_at=now,
            )
        return {
            "id": interview_id,
            "application_id": application_id,
            "status": "INTERVIEW_REQUIRED",
            "result": normalized_result,
        }

    @staticmethod
    async def _enqueue_notification(
        connection,
        *,
        guild_id: int,
        notification_type: str,
        subject_id: int,
        target_discord_id: int | None,
        channel_setting_key: str | None,
        payload: dict[str, object],
        correlation_id: str,
        now: int,
    ) -> None:
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
                subject_id,
                target_discord_id,
                channel_setting_key,
                json.dumps(payload, ensure_ascii=False),
                now,
                correlation_id,
                now,
                now,
            ),
        )

    @staticmethod
    async def _record_officer_event(
        connection,
        application_id: int,
        event_type: str,
        *,
        actor_id: int | None,
        previous_status: str | None,
        next_status: str | None,
        reason: str | None,
        metadata: dict[str, object],
        correlation_id: str,
        occurred_at: int,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO officer_application_events(
                application_id, event_type, previous_status, next_status,
                actor_id, reason, metadata_json, correlation_id, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                event_type,
                previous_status,
                next_status,
                actor_id,
                reason,
                json.dumps(metadata, ensure_ascii=False),
                correlation_id,
                occurred_at,
            ),
        )
