from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import date
from difflib import SequenceMatcher

import aiosqlite

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from .source_cutover import block_source_cutover_writes
from .time_utils import utc_now_ms

ACTIVE_APPLICATION_STATUSES = {
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "INTERVIEW_PENDING",
    "INTERVIEW_SCHEDULED",
    "INTERVIEW_COMPLETED",
    "FINAL_REVIEW",
}
INTEGRITY_EVENT_TYPES = {
    "COPY_BLOCKED",
    "PASTE_BLOCKED",
    "CUT_BLOCKED",
    "DROP_BLOCKED",
    "TAB_HIDDEN",
    "TAB_VISIBLE",
    "WINDOW_BLURRED",
    "WINDOW_FOCUSED",
    "UNUSUAL_INPUT_PATTERN",
}
INTERVIEW_RATINGS = {"EXCELLENT", "GOOD", "REGULAR", "INSUFFICIENT"}
QUESTION_TYPES = {
    "SHORT_TEXT",
    "LONG_TEXT",
    "NUMBER",
    "DATE",
    "BOOLEAN",
    "SINGLE_SELECT",
    "MULTI_SELECT",
}

DEFAULT_FORM_REVISION = 2
LEGACY_DEFAULT_GROUP_CODES = (
    "IDENTIFICATION",
    "AVAILABILITY",
    "EXPERIENCE",
    "MOTIVATION",
    "CONDUCT",
    "ROLEPLAY",
    "COMMUNICATION",
    "TEAMWORK",
    "SITUATIONS",
    "RESPONSIBILITY",
    "CHOQUE",
    "SELF_ASSESSMENT",
    "Q_CODES",
)
GROUPS = (
    ("MOTIVATION", "Motivação", 1, 1),
    ("ROLEPLAY", "Conhecimento de Roleplay", 2, 2),
    ("Q_CODES", "Códigos Q", 3, 4),
    ("COMMUNICATION", "Comunicação operacional", 4, 1),
    ("CONDUCT", "Conduta policial", 5, 1),
    ("CHOQUE", "Postura CHOQUE", 6, 1),
)


def _question(
    number: int,
    group: str,
    title: str,
    *,
    question_type: str = "LONG_TEXT",
    security: str = "CONTROLLED",
    minimum: int | None = 10,
    maximum: int | None = 300,
    options: tuple[str, ...] = (),
    enabled: bool = True,
    condition: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "stable_key": f"Q{number:02d}",
        "group": group,
        "title": title,
        "question_type": question_type,
        "security_level": security,
        "min_length": minimum,
        "max_length": maximum,
        "expected_min_length": minimum,
        "expected_max_length": maximum,
        "options": list(options),
        "enabled": enabled,
        "condition": dict(condition) if condition else None,
        "timer_enabled": security != "NORMAL",
        "allow_back": security != "STRICT",
        "shuffle_position": group not in {"IDENTIFICATION", "AVAILABILITY"},
        "difficulty": "HARD" if security == "STRICT" else "EASY" if security == "NORMAL" else "MEDIUM",
    }


DEFAULT_QUESTIONS = (
    _question(1, "MOTIVATION", "Por que você deseja ingressar na CHOQUE?", security="NORMAL"),
    _question(2, "ROLEPLAY", "Explique o que é Roleplay e por que ele deve ser preservado em uma ação policial.", security="NORMAL"),
    _question(3, "ROLEPLAY", "Qual situação representa Meta Gaming?", question_type="SINGLE_SELECT", security="NORMAL", minimum=None, maximum=None, options=("Usar no personagem uma informação obtida fora do RP", "Pedir apoio pelo rádio durante uma ocorrência", "Registrar uma denúncia após a ação", "Seguir a ordem de um superior")),
    _question(4, "Q_CODES", "No rádio policial, o código QAP significa:", question_type="SINGLE_SELECT", security="NORMAL", minimum=None, maximum=None, options=("Na escuta ou disponível", "Localização atual", "Mensagem entendida", "Pedido de apoio urgente")),
    _question(5, "Q_CODES", "No rádio policial, o código QSL significa:", question_type="SINGLE_SELECT", security="NORMAL", minimum=None, maximum=None, options=("Mensagem entendida", "Na escuta ou disponível", "Localização atual", "Encerrar comunicação")),
    _question(6, "Q_CODES", "No rádio policial, o código QTH significa:", question_type="SINGLE_SELECT", security="NORMAL", minimum=None, maximum=None, options=("Localização atual", "Mensagem entendida", "Aguardar no local", "Abordagem iniciada")),
    _question(7, "Q_CODES", "No rádio policial, o código QRR é usado para:", question_type="SINGLE_SELECT", security="NORMAL", minimum=None, maximum=None, options=("Solicitar apoio urgente", "Informar localização", "Confirmar entendimento", "Permanecer em silêncio")),
    _question(8, "COMMUNICATION", "Durante uma ocorrência, vários policiais falam ao mesmo tempo no rádio. Qual é a conduta correta?", question_type="SINGLE_SELECT", security="NORMAL", minimum=None, maximum=None, options=("Manter objetividade e respeitar a prioridade da comunicação", "Falar mais alto para ser ouvido", "Ignorar o comandante da patrulha", "Usar o chat externo para decidir a ação")),
    _question(9, "CONDUCT", "Um jogador provoca a equipe e tenta quebrar o Roleplay durante uma abordagem. Como você agiria?", security="NORMAL"),
    _question(10, "CHOQUE", "Como você deve agir ao discordar de uma ordem durante a operação, sem quebrar a hierarquia nem o Roleplay?", security="NORMAL"),
)


def calculate_question_time(question: Mapping[str, object], extra_time_percent: int = 0) -> int:
    if not question.get("timer_enabled"):
        return 0
    if question.get("timer_mode") == "FIXED" and question.get("fixed_time_seconds"):
        seconds = int(question["fixed_time_seconds"])
    else:
        expected = int(question.get("expected_max_length") or question.get("max_length") or 300)
        seconds = 45 + round(expected * 0.43)
        if question.get("security_level") == "STRICT":
            seconds += 30
        seconds = max(30, min(600, seconds))
    return round(seconds * (100 + max(0, min(200, extra_time_percent))) / 100)


class RecruitmentService:
    def __init__(
        self,
        database: Database,
        audit: AuditService,
        *,
        token_secret: str,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.audit = audit
        self.token_secret = token_secret
        self.clock = clock
        self.analysis_service = None

    @block_source_cutover_writes("Recrutamento")
    async def ensure_defaults(self, guild_id: int, actor_id: int | None = None) -> dict[str, int]:
        now = self.clock()
        async with self.database.transaction() as connection:
            await connection.execute(
                f"""
                UPDATE recruitment_question_groups SET active=0
                WHERE guild_id=? AND code IN ({','.join('?' for _ in LEGACY_DEFAULT_GROUP_CODES)})
                """,
                (guild_id, *LEGACY_DEFAULT_GROUP_CODES),
            )
            groups: dict[str, int] = {}
            for code, name, position, count in GROUPS:
                await connection.execute(
                    """
                    INSERT INTO recruitment_question_groups(
                        guild_id, code, name, position, questions_per_application
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, code) DO UPDATE SET
                        name=excluded.name, position=excluded.position,
                        questions_per_application=excluded.questions_per_application,
                        active=1
                    """,
                    (guild_id, code, name, position, count),
                )
                cursor = await connection.execute(
                    "SELECT id FROM recruitment_question_groups WHERE guild_id=? AND code=?",
                    (guild_id, code),
                )
                groups[code] = int((await cursor.fetchone())["id"])
            await connection.execute(
                """
                UPDATE recruitment_questions SET enabled=0, updated_at=?
                WHERE guild_id=? AND stable_key GLOB 'Q[0-9][0-9]'
                """,
                (now, guild_id),
            )
            for position, question in enumerate(DEFAULT_QUESTIONS, start=1):
                await connection.execute(
                    """
                    INSERT INTO recruitment_questions(
                        guild_id, stable_key, group_id, title, question_type, required,
                        position, enabled, min_length, max_length, expected_min_length,
                        expected_max_length, security_level, timer_enabled, timer_mode,
                        allow_back, shuffle_position, difficulty, options_json,
                        condition_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'AUTO', ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, stable_key) DO UPDATE SET
                        group_id=excluded.group_id,
                        title=excluded.title,
                        question_type=excluded.question_type,
                        required=excluded.required,
                        position=excluded.position,
                        enabled=excluded.enabled,
                        min_length=excluded.min_length,
                        max_length=excluded.max_length,
                        expected_min_length=excluded.expected_min_length,
                        expected_max_length=excluded.expected_max_length,
                        security_level=excluded.security_level,
                        timer_enabled=excluded.timer_enabled,
                        timer_mode=excluded.timer_mode,
                        allow_back=excluded.allow_back,
                        shuffle_position=excluded.shuffle_position,
                        difficulty=excluded.difficulty,
                        options_json=excluded.options_json,
                        condition_json=excluded.condition_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        guild_id,
                        question["stable_key"],
                        groups[str(question["group"])],
                        question["title"],
                        question["question_type"],
                        position,
                        int(bool(question["enabled"])),
                        question["min_length"],
                        question["max_length"],
                        question["expected_min_length"],
                        question["expected_max_length"],
                        question["security_level"],
                        int(bool(question["timer_enabled"])),
                        int(bool(question["allow_back"])),
                        int(bool(question["shuffle_position"])),
                        question["difficulty"],
                        json.dumps(question["options"], ensure_ascii=False),
                        json.dumps(question["condition"], ensure_ascii=False) if question["condition"] else None,
                        now,
                        now,
                    ),
                )
            cursor = await connection.execute(
                """
                SELECT id FROM recruitment_form_versions
                WHERE guild_id=? AND json_extract(settings_json, '$.seed_revision')=?
                ORDER BY version_number DESC LIMIT 1
                """,
                (guild_id, DEFAULT_FORM_REVISION),
            )
            version = await cursor.fetchone()
            created_default_version = version is None
            if not version:
                cursor = await connection.execute(
                    """
                    SELECT COALESCE(MAX(version_number), 0) + 1 AS next
                    FROM recruitment_form_versions WHERE guild_id=?
                    """,
                    (guild_id,),
                )
                version_number = int((await cursor.fetchone())["next"])
                await connection.execute(
                    """
                    UPDATE recruitment_form_versions SET status='RETIRED'
                    WHERE guild_id=? AND status='PUBLISHED'
                    """,
                    (guild_id,),
                )
                cursor = await connection.execute(
                    """
                    INSERT INTO recruitment_form_versions(
                        guild_id, version_number, status, settings_json, created_at,
                        created_by, published_at, published_by
                    ) VALUES (?, ?, 'PUBLISHED', ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        version_number,
                        json.dumps(
                            {
                                "network_grace_seconds": 5,
                                "seed_revision": DEFAULT_FORM_REVISION,
                                "question_count": len(DEFAULT_QUESTIONS),
                            }
                        ),
                        now,
                        actor_id,
                        now,
                        actor_id,
                    ),
                )
                version_id = int(cursor.lastrowid)
                questions = await connection.execute(
                    """
                    SELECT q.*, g.code AS group_code, g.name AS group_name,
                           g.position AS group_position,
                           g.questions_per_application, g.active AS group_active
                    FROM recruitment_questions q
                    JOIN recruitment_question_groups g ON g.id=q.group_id
                    WHERE q.guild_id=? AND q.enabled=1 AND g.active=1
                    ORDER BY g.position, q.position
                    """,
                    (guild_id,),
                )
                for row in await questions.fetchall():
                    await connection.execute(
                        """
                        INSERT INTO recruitment_form_version_questions(
                            form_version_id, question_id, position, snapshot_json
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (version_id, row["id"], row["position"], json.dumps(dict(row), ensure_ascii=False)),
                    )
            else:
                version_id = int(version["id"])
            cursor = await connection.execute(
                "SELECT id FROM recruitment_campaigns WHERE guild_id=? ORDER BY id LIMIT 1",
                (guild_id,),
            )
            campaign = await cursor.fetchone()
            if not campaign:
                rank = await connection.execute(
                    "SELECT id FROM ranks WHERE guild_id=? AND active=1 ORDER BY level LIMIT 1",
                    (guild_id,),
                )
                initial_rank = await rank.fetchone()
                cursor = await connection.execute(
                    """
                    INSERT INTO recruitment_campaigns(
                        guild_id, public_id, name, status, form_version_id, initial_rank_id,
                        created_at, created_by, updated_at
                    ) VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        str(uuid.uuid4()),
                        "Alistamento CHOQUE — Processo inicial",
                        version_id,
                        initial_rank["id"] if initial_rank else None,
                        now,
                        actor_id,
                        now,
                    ),
                )
                campaign_id = int(cursor.lastrowid)
            else:
                campaign_id = int(campaign["id"])
                if created_default_version:
                    await connection.execute(
                        """
                        UPDATE recruitment_campaigns
                        SET form_version_id=?, updated_at=?
                        WHERE guild_id=? AND status!='ARCHIVED'
                        """,
                        (version_id, now, guild_id),
                    )
        imported = await self.migrate_legacy_tickets(
            guild_id, campaign_id=campaign_id, form_version_id=version_id, actor_id=actor_id
        )
        return {
            "form_version_id": version_id,
            "campaign_id": campaign_id,
            "legacy_applications_imported": imported,
        }

    async def migrate_legacy_tickets(
        self,
        guild_id: int,
        *,
        campaign_id: int,
        form_version_id: int,
        actor_id: int | None,
    ) -> int:
        rows = await self.database.fetchall(
            """
            SELECT * FROM service_tickets
            WHERE guild_id=? AND ticket_type='CANDIDACY'
              AND id NOT IN (
                  SELECT legacy_ticket_id FROM recruitment_applications
                  WHERE guild_id=? AND legacy_ticket_id IS NOT NULL
              )
            ORDER BY submitted_at, id
            """,
            (guild_id, guild_id),
        )
        if not rows:
            return 0
        status_map = {
            "PENDING": ("SUBMITTED", "REVIEW"),
            "IN_REVIEW": ("UNDER_REVIEW", "REVIEW"),
            "APPROVED": ("APPROVED", "RESULT"),
            "REJECTED": ("REJECTED", "RESULT"),
            "CANCELLED": ("WITHDRAWN", "RESULT"),
            "CLOSED": ("WITHDRAWN", "RESULT"),
        }
        imported = 0
        async with self.database.transaction() as connection:
            for ticket in rows:
                payload = json.loads(ticket["payload_json"])
                status, stage = status_map[str(ticket["status"])]
                protocol = f"LEG-{int(ticket['id']):05d}"
                cursor = await connection.execute(
                    """
                    INSERT INTO recruitment_applications(
                        guild_id, public_id, protocol, campaign_id, form_version_id,
                        discord_id, discord_username, bgr_id, candidate_nick, age,
                        status, stage, version, idempotency_key, assigned_to, assigned_at,
                        started_at, submitted_at, reviewed_at, decided_at, decided_by,
                        internal_reason, candidate_message, legacy_incomplete,
                        legacy_ticket_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    ON CONFLICT(guild_id, legacy_ticket_id) DO NOTHING
                    """,
                    (
                        guild_id,
                        str(uuid.uuid5(uuid.NAMESPACE_URL, f"choque-ticket:{guild_id}:{ticket['id']}")),
                        protocol,
                        campaign_id,
                        form_version_id,
                        ticket["discord_id"],
                        f"legacy-{ticket['discord_id']}",
                        f"LEGACY-{ticket['id']}",
                        str(payload.get("mta_nick") or f"Candidato {ticket['discord_id']}")[:80],
                        status,
                        stage,
                        f"legacy-ticket:{ticket['id']}",
                        ticket["claimed_by"],
                        ticket["claimed_at"],
                        ticket["submitted_at"],
                        ticket["submitted_at"],
                        ticket["reviewed_at"],
                        ticket["reviewed_at"] if status in {"APPROVED", "REJECTED"} else None,
                        ticket["reviewed_by"],
                        ticket["review_reason"],
                        ticket["review_reason"],
                        ticket["id"],
                        ticket["submitted_at"],
                        ticket["updated_at"],
                    ),
                )
                if cursor.rowcount != 1:
                    continue
                application_id = int(cursor.lastrowid)
                await self._history(
                    connection,
                    guild_id,
                    application_id,
                    "LEGACY_CANDIDACY_IMPORTED",
                    actor_id,
                    "Candidatura histórica importada.",
                    {"legacy_ticket_id": int(ticket["id"])},
                )
                if status == "APPROVED":
                    await connection.execute(
                        """
                        UPDATE members SET origin_recruitment_application_id=COALESCE(
                            origin_recruitment_application_id, ?
                        ) WHERE guild_id=? AND discord_id=?
                        """,
                        (application_id, guild_id, ticket["discord_id"]),
                    )
                imported += 1
            if imported:
                await self.audit.record(
                    guild_id,
                    "RECRUITMENT_LEGACY_MIGRATION",
                    actor_id=actor_id,
                    after={"imported": imported},
                    connection=connection,
                )
        return imported

    async def current_campaign(self, guild_id: int):
        now = self.clock()
        row = await self.database.fetchone(
            """
            SELECT * FROM recruitment_campaigns
            WHERE guild_id=? AND status NOT IN ('ARCHIVED')
            ORDER BY CASE status WHEN 'OPEN' THEN 0 WHEN 'SCHEDULED' THEN 1 ELSE 2 END, id DESC
            LIMIT 1
            """,
            (guild_id,),
        )
        if not row:
            return None
        result = dict(row)
        if result["status"] == "SCHEDULED" and result["opens_at"] and now >= result["opens_at"]:
            result["status"] = "OPEN"
        if result["status"] == "OPEN" and result["closes_at"] and now >= result["closes_at"]:
            result["status"] = "CLOSED"
        return result

    async def eligibility(self, guild_id: int, discord_id: int) -> dict[str, object]:
        campaign = await self.current_campaign(guild_id)
        reasons: list[str] = []
        if not campaign or campaign["status"] != "OPEN":
            reasons.append("RECRUITMENT_CLOSED")
        member = await self.database.fetchone(
            "SELECT status FROM members WHERE guild_id=? AND discord_id=? AND status!='DISMISSED'",
            (guild_id, discord_id),
        )
        if member:
            reasons.append("ACTIVE_MEMBER_LINK")
        blocked = await self.database.fetchone(
            """
            SELECT id FROM recruitment_blocks
            WHERE guild_id=? AND active=1 AND discord_id=? LIMIT 1
            """,
            (guild_id, discord_id),
        )
        if blocked:
            reasons.append("ADMINISTRATIVE_BLOCK")
        active = await self.database.fetchone(
            f"SELECT id, protocol, status FROM recruitment_applications WHERE guild_id=? AND discord_id=? AND status IN ({','.join('?' for _ in ACTIVE_APPLICATION_STATUSES)})",
            (guild_id, discord_id, *sorted(ACTIVE_APPLICATION_STATUSES)),
        )
        if active:
            reasons.append("ACTIVE_APPLICATION")
        cooldown = await self.database.fetchone(
            """
            SELECT ends_at FROM recruitment_cooldowns
            WHERE guild_id=? AND discord_id=? AND ends_at>?
            ORDER BY ends_at DESC LIMIT 1
            """,
            (guild_id, discord_id, self.clock()),
        )
        if cooldown:
            reasons.append("COOLDOWN_ACTIVE")
        if campaign and campaign["maximum_applications"]:
            row = await self.database.fetchone(
                "SELECT COUNT(*) AS total FROM recruitment_applications WHERE campaign_id=?",
                (campaign["id"],),
            )
            if int(row["total"]) >= int(campaign["maximum_applications"]):
                reasons.append("CAPACITY_REACHED")
        return {
            "eligible": not reasons,
            "reasons": reasons,
            "campaign": campaign,
            "active_application": dict(active) if active else None,
            "cooldown_until": cooldown["ends_at"] if cooldown else None,
        }

    @block_source_cutover_writes("Recrutamento")
    async def start_application(
        self,
        guild_id: int,
        discord_id: int,
        *,
        discord_username: str,
        discord_global_name: str | None,
        discord_avatar: str | None,
        candidate_nick: str,
        bgr_id: str,
        age: int,
        idempotency_key: str,
        consent_accepted: bool,
        guild_membership_verified: bool,
    ) -> dict[str, object]:
        nick = candidate_nick.strip()
        bgr = bgr_id.strip()
        key = idempotency_key.strip()
        if not nick or not bgr or len(key) < 12:
            raise ValidationError("Nick, ID BGR e chave de idempotência são obrigatórios.")
        if not consent_accepted:
            raise ValidationError("É necessário aceitar os termos e o aviso de privacidade.")
        existing = await self.database.fetchone(
            "SELECT * FROM recruitment_applications WHERE guild_id=? AND idempotency_key=?",
            (guild_id, key),
        )
        if existing:
            if int(existing["discord_id"]) != discord_id:
                raise ConflictError("Chave de idempotência já utilizada.")
            return dict(existing)
        eligibility = await self.eligibility(guild_id, discord_id)
        if not eligibility["eligible"]:
            raise ConflictError("Candidatura indisponível: " + ", ".join(eligibility["reasons"]))
        campaign = eligibility["campaign"]
        assert isinstance(campaign, dict)
        if age < int(campaign["minimum_age"]):
            raise ValidationError("Idade abaixo do mínimo configurado para este processo.")
        blocked_bgr = await self.database.fetchone(
            """
            SELECT id FROM recruitment_blocks
            WHERE guild_id=? AND active=1 AND bgr_id=? LIMIT 1
            """,
            (guild_id, bgr),
        )
        if blocked_bgr:
            raise ConflictError("Candidatura indisponível por bloqueio administrativo.")
        now = self.clock()
        public_id = str(uuid.uuid4())
        try:
            async with self.database.transaction() as connection:
                campaign_cursor = await connection.execute(
                    "SELECT * FROM recruitment_campaigns WHERE guild_id=? AND id=?",
                    (guild_id, campaign["id"]),
                )
                current_campaign = await campaign_cursor.fetchone()
                if not current_campaign:
                    raise ConflictError("O processo seletivo não está mais disponível.")
                effective_status = str(current_campaign["status"])
                if (
                    effective_status == "SCHEDULED"
                    and current_campaign["opens_at"]
                    and now >= int(current_campaign["opens_at"])
                ):
                    effective_status = "OPEN"
                if (
                    effective_status == "OPEN"
                    and current_campaign["closes_at"]
                    and now >= int(current_campaign["closes_at"])
                ):
                    effective_status = "CLOSED"
                if effective_status != "OPEN":
                    raise ConflictError("O processo seletivo não está mais disponível.")
                if current_campaign["maximum_applications"]:
                    count_cursor = await connection.execute(
                        "SELECT COUNT(*) AS total FROM recruitment_applications WHERE campaign_id=?",
                        (campaign["id"],),
                    )
                    if int((await count_cursor.fetchone())["total"]) >= int(
                        current_campaign["maximum_applications"]
                    ):
                        raise ConflictError("O limite de candidaturas desta campanha foi atingido.")
                cursor = await connection.execute(
                    """
                    INSERT INTO recruitment_applications(
                        guild_id, public_id, campaign_id, form_version_id, discord_id,
                        discord_username, discord_global_name, discord_avatar, bgr_id,
                        guild_membership_verified_at, consent_accepted_at,
                        candidate_nick, age, idempotency_key, started_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id, public_id, campaign["id"], campaign["form_version_id"],
                        discord_id, discord_username[:100], (discord_global_name or "")[:100] or None,
                        (discord_avatar or "")[:500] or None, bgr[:40], now, now,
                        nick[:80], age, key[:100],
                        now, now, now,
                    ),
                )
                application_id = int(cursor.lastrowid)
                protocol = f"AL-{application_id:05d}"
                await connection.execute(
                    "UPDATE recruitment_applications SET protocol=? WHERE id=?",
                    (protocol, application_id),
                )
                await self._assign_questions(connection, application_id, int(campaign["form_version_id"]))
                await self._history(
                    connection, guild_id, application_id, "APPLICATION_STARTED", discord_id,
                    "Candidatura iniciada.", {"protocol": protocol},
                )
                await self.audit.record(
                    guild_id,
                    "RECRUITMENT_APPLICATION_STARTED",
                    actor_id=discord_id,
                    target_id=discord_id,
                    after={"application_id": application_id, "protocol": protocol},
                    connection=connection,
                )
        except aiosqlite.IntegrityError as exc:
            existing = await self.database.fetchone(
                """
                SELECT * FROM recruitment_applications
                WHERE guild_id=? AND (discord_id=? OR bgr_id=? OR idempotency_key=?)
                  AND status IN ('DRAFT','SUBMITTED','UNDER_REVIEW','INTERVIEW_PENDING',
                                 'INTERVIEW_SCHEDULED','INTERVIEW_COMPLETED','FINAL_REVIEW')
                """,
                (guild_id, discord_id, bgr, key),
            )
            if existing and int(existing["discord_id"]) == discord_id:
                return dict(existing)
            raise ConflictError("Já existe candidatura ativa para este Discord ou ID BGR.") from exc
        return dict(await self.database.fetchone("SELECT * FROM recruitment_applications WHERE id=?", (application_id,)))

    @block_source_cutover_writes("Recrutamento")
    async def submit_direct_indication(
        self,
        guild_id: int,
        discord_id: int,
        *,
        discord_username: str,
        candidate_nick: str,
        bgr_id: str,
        indicated_by: int,
        requested_unit_code: str | None = None,
        notes: str | None = None,
    ) -> dict[str, object]:
        """Open a review-ready application without the traditional form."""
        nick = candidate_nick.strip()
        bgr = bgr_id.strip()
        unit = (requested_unit_code or "").strip().upper() or None
        detail = (notes or "").strip() or None
        if not nick or not bgr:
            raise ValidationError("Nick e ID BGR são obrigatórios.")
        if indicated_by <= 0 or indicated_by == discord_id:
            raise ValidationError("Informe um indicador válido diferente do candidato.")
        if unit not in {None, "ROCAM", "TATICO", "ELITE", "CORREGEDORIA"}:
            raise ValidationError("Unidade especial inválida.")
        active = await self.database.fetchone(
            f"""
            SELECT * FROM recruitment_applications
            WHERE guild_id=? AND discord_id=?
              AND status IN ({','.join('?' for _ in ACTIVE_APPLICATION_STATUSES)})
            ORDER BY id DESC LIMIT 1
            """,
            (guild_id, discord_id, *sorted(ACTIVE_APPLICATION_STATUSES)),
        )
        if active:
            if str(active["entry_method"] or "FORM") == "INDICATION":
                raise ConflictError(
                    "Este candidato já possui uma solicitação de entrada por indicação em análise."
                )
            raise ConflictError("Este candidato já possui uma candidatura em andamento.")
        member = await self.database.fetchone(
            "SELECT id FROM members WHERE guild_id=? AND discord_id=? AND status!='DISMISSED'",
            (guild_id, discord_id),
        )
        if member:
            raise ConflictError("Este Discord já possui vínculo ativo no efetivo.")
        blocked = await self.database.fetchone(
            """
            SELECT id FROM recruitment_blocks
            WHERE guild_id=? AND active=1 AND (discord_id=? OR bgr_id=?) LIMIT 1
            """,
            (guild_id, discord_id, bgr),
        )
        if blocked:
            raise ConflictError("Entrada indisponível por bloqueio administrativo.")
        campaign = await self.current_campaign(guild_id)
        if not campaign:
            raise ConflictError("Configure o recrutamento antes de receber indicações.")
        now = self.clock()
        public_id = str(uuid.uuid4())
        idempotency_key = f"direct-indication:{guild_id}:{discord_id}:{uuid.uuid4()}"
        try:
            async with self.database.transaction() as connection:
                cursor = await connection.execute(
                    """
                    INSERT INTO recruitment_applications(
                        guild_id, public_id, campaign_id, form_version_id, discord_id,
                        discord_username, guild_membership_verified_at,
                        consent_accepted_at, bgr_id, candidate_nick, age,
                        status, stage, idempotency_key, started_at, submitted_at,
                        created_at, updated_at, entry_method, indicated_by,
                        requested_unit_code, indication_notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0,
                              'UNDER_REVIEW', 'REVIEW', ?, ?, ?, ?, ?,
                              'INDICATION', ?, ?, ?)
                    """,
                    (
                        guild_id,
                        public_id,
                        int(campaign["id"]),
                        int(campaign["form_version_id"]),
                        discord_id,
                        discord_username[:100],
                        now,
                        now,
                        bgr[:40],
                        nick[:80],
                        idempotency_key[:100],
                        now,
                        now,
                        now,
                        now,
                        indicated_by,
                        unit,
                        detail[:1000] if detail else None,
                    ),
                )
                application_id = int(cursor.lastrowid)
                protocol = f"IND-{application_id:05d}"
                await connection.execute(
                    "UPDATE recruitment_applications SET protocol=? WHERE id=?",
                    (protocol, application_id),
                )
                await self._history(
                    connection,
                    guild_id,
                    application_id,
                    "DIRECT_INDICATION_SUBMITTED",
                    discord_id,
                    "Entrada por indicação enviada para análise.",
                    {
                        "protocol": protocol,
                        "indicated_by": indicated_by,
                        "unit": unit,
                        "entry_method": "INDICATION",
                    },
                )
                await self._public_status_notification(
                    connection, guild_id, application_id, "UNDER_REVIEW", now
                )
                await self._review_card_notification(
                    connection, guild_id, application_id, "UNDER_REVIEW", 1, now
                )
                await self.audit.record(
                    guild_id,
                    "RECRUITMENT_DIRECT_INDICATION_SUBMITTED",
                    actor_id=discord_id,
                    target_id=discord_id,
                    after={
                        "application_id": application_id,
                        "protocol": protocol,
                        "indicated_by": indicated_by,
                        "unit": unit,
                        "entry_method": "INDICATION",
                    },
                    connection=connection,
                )
        except aiosqlite.IntegrityError as exc:
            raise ConflictError(
                "Este candidato já possui uma solicitação de entrada por indicação em análise."
            ) from exc
        return dict(
            await self.database.fetchone(
                "SELECT * FROM recruitment_applications WHERE id=?", (application_id,)
            )
        )

    async def _assign_questions(
        self, connection: aiosqlite.Connection, application_id: int, form_version_id: int
    ) -> None:
        cursor = await connection.execute(
            """
            SELECT fvq.question_id, fvq.snapshot_json
            FROM recruitment_form_version_questions fvq
            WHERE fvq.form_version_id=?
            ORDER BY fvq.position
            """,
            (form_version_id,),
        )
        grouped: dict[str, list[dict[str, object]]] = {}
        limits: dict[str, int] = {}
        positions: dict[str, int] = {}
        for row in await cursor.fetchall():
            snapshot = json.loads(row["snapshot_json"])
            if not snapshot.get("enabled", 1) or not snapshot.get("group_active", 1):
                continue
            code = str(snapshot.get("group_code") or snapshot.get("group_id"))
            grouped.setdefault(code, []).append(
                {
                    "question_id": int(row["question_id"]),
                    "snapshot_json": row["snapshot_json"],
                    "snapshot": snapshot,
                }
            )
            limits[code] = int(snapshot.get("questions_per_application") or 1)
            positions[code] = int(snapshot.get("group_position") or 0)
        chosen: list[dict[str, object]] = []
        randomizer = secrets.SystemRandom()
        for code in sorted(grouped, key=positions.get):
            pool = grouped[code]
            count = min(limits[code], len(pool))
            if count < len(pool):
                by_difficulty: dict[str, list[dict[str, object]]] = {}
                for item in pool:
                    difficulty = str(item["snapshot"]["difficulty"])
                    by_difficulty.setdefault(difficulty, []).append(item)
                quotas = {
                    difficulty: round(count * len(items) / len(pool))
                    for difficulty, items in by_difficulty.items()
                }
                while sum(quotas.values()) > count:
                    key = max(quotas, key=lambda value: (quotas[value], value))
                    quotas[key] -= 1
                while sum(quotas.values()) < count:
                    eligible = [
                        value
                        for value, items in by_difficulty.items()
                        if quotas[value] < len(items)
                    ]
                    key = max(
                        eligible,
                        key=lambda value: (len(by_difficulty[value]) - quotas[value], value),
                    )
                    quotas[key] += 1
                selected = []
                for difficulty, items in by_difficulty.items():
                    quota = min(quotas[difficulty], len(items))
                    selected.extend(randomizer.sample(items, quota))
                if len(selected) < count:
                    remaining = [item for item in pool if item not in selected]
                    selected.extend(randomizer.sample(remaining, count - len(selected)))
            else:
                selected = list(pool)
            selected.sort(key=lambda item: int(item["snapshot"]["position"]))
            chosen.extend(selected)
        for ordinal, row in enumerate(chosen, start=1):
            await connection.execute(
                """
                INSERT INTO recruitment_application_questions(
                    application_id, question_id, ordinal, question_snapshot_json
                ) VALUES (?, ?, ?, ?)
                """,
                (application_id, row["question_id"], ordinal, row["snapshot_json"]),
            )

    async def my_application(self, guild_id: int, discord_id: int) -> dict[str, object] | None:
        row = await self.database.fetchone(
            """
            SELECT * FROM recruitment_applications
            WHERE guild_id=? AND discord_id=? ORDER BY created_at DESC LIMIT 1
            """,
            (guild_id, discord_id),
        )
        if not row:
            return None
        progress = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status IN ('SUBMITTED','TIME_EXPIRED','SKIPPED') THEN 1 ELSE 0 END) AS completed
            FROM recruitment_application_questions WHERE application_id=?
            """,
            (row["id"],),
        )
        history = await self.database.fetchall(
            """
            SELECT event_type, public_message, created_at FROM recruitment_history
            WHERE application_id=? AND public_message IS NOT NULL ORDER BY created_at, id
            """,
            (row["id"],),
        )
        return {
            "application": dict(row),
            "progress": dict(progress),
            "history": [dict(item) for item in history],
        }

    async def next_question(self, guild_id: int, discord_id: int, application_id: int) -> dict[str, object]:
        application = await self._owned_application(guild_id, discord_id, application_id)
        row = await self._next_eligible_question(application_id)
        if not row:
            return {"complete": True, "application_version": application["version"]}
        snapshot = json.loads(row["question_snapshot_json"])
        total = await self.database.fetchone(
            "SELECT COUNT(*) AS total FROM recruitment_application_questions WHERE application_id=?",
            (application_id,),
        )
        adaptation = await self._application_adaptation(application_id)
        response: dict[str, object] = {
            "complete": False,
            "id": int(row["id"]),
            "ordinal": int(row["ordinal"]),
            "total": int(total["total"]),
            "status": row["status"],
            "security_level": snapshot["security_level"],
            "time_seconds": calculate_question_time(snapshot, int(adaptation["extra_time_percent"])),
        }
        if row["status"] == "ACTIVE":
            response.update(self._active_question_payload(row, snapshot, adaptation))
        return response

    async def _next_eligible_question(self, application_id: int):
        while True:
            row = await self.database.fetchone(
                """
                SELECT * FROM recruitment_application_questions
                WHERE application_id=? AND status IN ('ACTIVE','NOT_STARTED')
                ORDER BY CASE status WHEN 'ACTIVE' THEN 0 ELSE 1 END, ordinal LIMIT 1
                """,
                (application_id,),
            )
            if not row:
                return None
            snapshot = json.loads(row["question_snapshot_json"])
            condition_raw = snapshot.get("condition_json")
            condition = json.loads(condition_raw) if condition_raw else None
            if not condition:
                return row
            dependency = await self.database.fetchone(
                """
                SELECT aq.final_answer_json
                FROM recruitment_application_questions aq
                WHERE aq.application_id=?
                  AND json_extract(aq.question_snapshot_json, '$.stable_key')=?
                  AND aq.status IN ('SUBMITTED','TIME_EXPIRED')
                """,
                (application_id, condition["question"]),
            )
            expected = condition.get("equals")
            actual = json.loads(dependency["final_answer_json"]) if dependency and dependency["final_answer_json"] else None
            if actual == expected:
                return row
            await self.database.execute(
                """
                UPDATE recruitment_application_questions SET status='SKIPPED', submitted_at=?
                WHERE id=? AND status='NOT_STARTED'
                """,
                (self.clock(), row["id"]),
            )

    @block_source_cutover_writes("Recrutamento")
    async def start_question(
        self, guild_id: int, discord_id: int, application_id: int, application_question_id: int
    ) -> dict[str, object]:
        await self._owned_application(guild_id, discord_id, application_id)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT aq.*, a.version AS application_version
                FROM recruitment_application_questions aq
                JOIN recruitment_applications a ON a.id=aq.application_id
                WHERE aq.id=? AND aq.application_id=?
                """,
                (application_question_id, application_id),
            )
            row = await cursor.fetchone()
            if not row:
                raise NotFoundError("Questão atribuída não encontrada.")
            snapshot = json.loads(row["question_snapshot_json"])
            if row["status"] == "NOT_STARTED":
                earlier = await connection.execute(
                    """
                    SELECT 1 FROM recruitment_application_questions
                    WHERE application_id=? AND ordinal<?
                      AND status NOT IN ('SUBMITTED','TIME_EXPIRED','SKIPPED') LIMIT 1
                    """,
                    (application_id, row["ordinal"]),
                )
                if await earlier.fetchone():
                    raise ConflictError("Conclua a questão atual antes de avançar.")
                adaptation_cursor = await connection.execute(
                    "SELECT COALESCE(MAX(extra_time_percent),0) AS extra FROM recruitment_adaptations WHERE application_id=?",
                    (application_id,),
                )
                extra = int((await adaptation_cursor.fetchone())["extra"])
                seconds = calculate_question_time(snapshot, extra)
                nonce = secrets.token_urlsafe(24)
                expires_at = now + seconds * 1000 if seconds else None
                await connection.execute(
                    """
                    UPDATE recruitment_application_questions
                    SET status='ACTIVE', token_nonce=?, started_at=?, expires_at=?
                    WHERE id=? AND status='NOT_STARTED'
                    """,
                    (nonce, now, expires_at, application_question_id),
                )
                await self._integrity(
                    connection, guild_id, application_id, application_question_id,
                    "QUESTION_STARTED", now,
                )
                row = dict(row)
                row.update(status="ACTIVE", token_nonce=nonce, started_at=now, expires_at=expires_at)
            elif row["status"] != "ACTIVE":
                raise ConflictError("Essa questão já foi finalizada.")
            adaptation = await self._application_adaptation(application_id, connection=connection)
            return self._active_question_payload(row, snapshot, adaptation)

    async def _application_adaptation(
        self,
        application_id: int,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> dict[str, object]:
        query = """
            SELECT COALESCE(MAX(extra_time_percent),0) AS extra_time_percent,
                   COALESCE(MAX(clipboard_adapted),0) AS clipboard_adapted,
                   MAX(alternative_format) AS alternative_format
            FROM recruitment_adaptations WHERE application_id=?
        """
        if connection is None:
            row = await self.database.fetchone(query, (application_id,))
        else:
            cursor = await connection.execute(query, (application_id,))
            row = await cursor.fetchone()
        return dict(row)

    def _active_question_payload(
        self,
        row: Mapping[str, object],
        snapshot: dict[str, object],
        adaptation: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        adaptation = adaptation or {}
        token = self._question_token(
            int(row["application_id"]), int(row["id"]), str(row["token_nonce"]), row["expires_at"]
        )
        return {
            "question": {
                "id": int(row["id"]),
                "title": snapshot["title"],
                "description": snapshot.get("description"),
                "type": snapshot["question_type"],
                "required": bool(snapshot["required"]),
                "min_length": snapshot.get("min_length"),
                "max_length": snapshot.get("max_length"),
                "options": json.loads(snapshot.get("options_json") or "[]"),
                "security_level": snapshot["security_level"],
                "allow_back": bool(snapshot["allow_back"]),
                "clipboard_adapted": bool(adaptation.get("clipboard_adapted")),
                "alternative_format": adaptation.get("alternative_format"),
            },
            "started_at": row["started_at"],
            "expires_at": row["expires_at"],
            "draft": json.loads(row["draft_answer_json"]) if row["draft_answer_json"] else None,
            "question_token": token,
        }

    def _question_token(self, application_id: int, question_id: int, nonce: str, expires_at: object) -> str:
        message = f"{application_id}:{question_id}:{nonce}:{expires_at or 0}"
        signature = hmac.new(self.token_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return f"{nonce}.{signature}"

    def _verify_question_token(self, row: Mapping[str, object], token: str) -> bool:
        expected = self._question_token(
            int(row["application_id"]), int(row["id"]), str(row["token_nonce"]), row["expires_at"]
        )
        return hmac.compare_digest(expected, token)

    @block_source_cutover_writes("Recrutamento")
    async def save_answer(
        self,
        guild_id: int,
        discord_id: int,
        application_id: int,
        application_question_id: int,
        *,
        answer: object,
        question_token: str,
        submit: bool,
    ) -> dict[str, object]:
        await self._owned_application(guild_id, discord_id, application_id)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM recruitment_application_questions WHERE id=? AND application_id=?",
                (application_question_id, application_id),
            )
            row = await cursor.fetchone()
            if not row or not self._verify_question_token(row, question_token):
                raise ConflictError("Questão, estado ou token inválido.")
            if submit and row["status"] in {"SUBMITTED", "TIME_EXPIRED"}:
                return {
                    "saved": True,
                    "submitted": True,
                    "expired": row["status"] == "TIME_EXPIRED",
                    "status": row["status"],
                }
            if row["status"] != "ACTIVE":
                raise ConflictError("Questão, estado ou token inválido.")
            snapshot = json.loads(row["question_snapshot_json"])
            answer = self._validate_answer(snapshot, answer)
            serialized = json.dumps(answer, ensure_ascii=False)
            text_value = answer if isinstance(answer, str) else serialized
            maximum = snapshot.get("max_length")
            minimum = snapshot.get("min_length")
            if maximum is not None and len(str(text_value)) > int(maximum):
                raise ValidationError("Resposta excede o limite configurado.")
            expired = bool(row["expires_at"] and now > int(row["expires_at"]) + 5_000)
            if not submit and not expired:
                await connection.execute(
                    """
                    UPDATE recruitment_application_questions
                    SET draft_answer_json=?, saved_at=? WHERE id=? AND status='ACTIVE'
                    """,
                    (serialized, now, application_question_id),
                )
                return {"saved": True, "expired": False, "saved_at": now}
            if minimum is not None and len(str(text_value).strip()) < int(minimum) and not expired:
                raise ValidationError("Resposta abaixo do mínimo configurado.")
            status = "TIME_EXPIRED" if expired else "SUBMITTED"
            cursor = await connection.execute(
                """
                UPDATE recruitment_application_questions
                SET status=?, draft_answer_json=?, final_answer_json=?, saved_at=?,
                    submitted_at=?, duration_ms=?
                WHERE id=? AND status='ACTIVE'
                """,
                (
                    status, serialized, serialized, now, now,
                    max(0, now - int(row["started_at"])), application_question_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A questão foi finalizada simultaneamente.")
            await self._integrity(
                connection, guild_id, application_id, application_question_id,
                "QUESTION_TIMEOUT" if expired else "QUESTION_SUBMITTED", now,
                duration_ms=max(0, now - int(row["started_at"])),
            )
        return {"saved": True, "submitted": True, "expired": expired, "status": status}

    def _validate_answer(self, snapshot: Mapping[str, object], answer: object) -> object:
        question_type = str(snapshot["question_type"])
        options = set(json.loads(str(snapshot.get("options_json") or "[]")))
        required = bool(snapshot.get("required"))
        if question_type in {"SHORT_TEXT", "LONG_TEXT", "DATE"}:
            if not isinstance(answer, str):
                raise ValidationError("A resposta deve ser textual.")
            value = answer.strip()
            if required and not value:
                raise ValidationError("Esta resposta é obrigatória.")
            if question_type == "DATE" and value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValidationError("Informe uma data válida.") from exc
            return value
        if question_type == "NUMBER":
            if isinstance(answer, bool):
                raise ValidationError("Informe um número válido.")
            try:
                return int(str(answer).strip())
            except (TypeError, ValueError) as exc:
                raise ValidationError("Informe um número válido.") from exc
        if question_type == "BOOLEAN":
            if not isinstance(answer, bool):
                raise ValidationError("Selecione sim ou não.")
            return answer
        if question_type == "SINGLE_SELECT":
            if not isinstance(answer, str) or answer not in options:
                raise ValidationError("Selecione uma opção válida.")
            return answer
        if question_type == "MULTI_SELECT":
            if not isinstance(answer, list) or (required and not answer) or any(
                not isinstance(item, str) or item not in options for item in answer
            ):
                raise ValidationError("Selecione uma ou mais opções válidas.")
            return list(dict.fromkeys(answer))
        raise ValidationError("Tipo de questão não suportado.")

    @block_source_cutover_writes("Recrutamento")
    async def record_integrity_event(
        self,
        guild_id: int,
        discord_id: int,
        application_id: int,
        application_question_id: int,
        event_type: str,
        *,
        duration_ms: int | None = None,
    ) -> None:
        await self._owned_application(guild_id, discord_id, application_id)
        normalized = event_type.upper()
        if normalized not in INTEGRITY_EVENT_TYPES:
            raise ValidationError("Evento de integridade inválido.")
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT 1 FROM recruitment_application_questions
                WHERE id=? AND application_id=? AND status='ACTIVE'
                """,
                (application_question_id, application_id),
            )
            if not await cursor.fetchone():
                raise NotFoundError("Questão ativa não encontrada.")
            duplicate = await connection.execute(
                """
                SELECT 1 FROM recruitment_integrity_events
                WHERE application_id=? AND application_question_id=? AND event_type=?
                  AND occurred_at>=? LIMIT 1
                """,
                (application_id, application_question_id, normalized, self.clock() - 250),
            )
            if await duplicate.fetchone():
                return
            await self._integrity(
                connection, guild_id, application_id, application_question_id,
                normalized, self.clock(), duration_ms=duration_ms,
            )

    @block_source_cutover_writes("Recrutamento")
    async def submit_application(
        self, guild_id: int, discord_id: int, application_id: int, expected_version: int
    ) -> dict[str, object]:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM recruitment_applications WHERE id=? AND guild_id=? AND discord_id=?",
                (application_id, guild_id, discord_id),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Candidatura não encontrada.")
            if application["status"] == "SUBMITTED":
                return dict(application)
            if application["status"] != "DRAFT" or int(application["version"]) != expected_version:
                raise ConflictError("A candidatura foi atualizada. Recarregue antes de enviar.")
            cursor = await connection.execute(
                """
                SELECT COUNT(*) AS remaining FROM recruitment_application_questions
                WHERE application_id=? AND status NOT IN ('SUBMITTED','TIME_EXPIRED','SKIPPED')
                """,
                (application_id,),
            )
            if int((await cursor.fetchone())["remaining"]):
                raise ConflictError("Conclua todas as questões antes de enviar.")
            await self._flag_similar_responses(
                connection, guild_id, application_id, int(application["campaign_id"]), now
            )
            cursor = await connection.execute(
                """
                UPDATE recruitment_applications SET status='SUBMITTED', stage='REVIEW',
                    submitted_at=?, updated_at=?, version=version+1
                WHERE id=? AND status='DRAFT' AND version=?
                """,
                (now, now, application_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A candidatura foi enviada simultaneamente.")
            await self._history(
                connection, guild_id, application_id, "APPLICATION_SUBMITTED", discord_id,
                "Candidatura recebida.", {},
            )
            await self._notification(
                connection, guild_id, application_id, "RECRUITMENT_APPLICATION_SUBMITTED",
                f"application-submitted:{application_id}",
                {"application_id": application_id, "protocol": application["protocol"]}, now,
            )
            await self._public_status_notification(
                connection,
                guild_id,
                application_id,
                "SUBMITTED",
                now,
            )
            await self.audit.record(
                guild_id, "RECRUITMENT_APPLICATION_SUBMITTED", actor_id=discord_id,
                target_id=discord_id, after={"application_id": application_id}, connection=connection,
            )
            if self.analysis_service is not None:
                await self.analysis_service.enqueue_automatic_if_enabled(
                    guild_id, application_id, connection
                )
        return dict(await self.database.fetchone("SELECT * FROM recruitment_applications WHERE id=?", (application_id,)))

    async def _flag_similar_responses(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        application_id: int,
        campaign_id: int,
        now: int,
    ) -> None:
        cursor = await connection.execute(
            """
            SELECT aq.id, aq.question_id, aq.final_answer_json,
                   json_extract(aq.question_snapshot_json, '$.stable_key') AS stable_key
            FROM recruitment_application_questions aq
            WHERE aq.application_id=? AND aq.final_answer_json IS NOT NULL
            """,
            (application_id,),
        )
        for current in await cursor.fetchall():
            answer = json.loads(current["final_answer_json"])
            if not isinstance(answer, str):
                continue
            normalized = re.sub(r"\s+", " ", answer.casefold()).strip()
            if len(normalized) < 100:
                continue
            previous_cursor = await connection.execute(
                """
                SELECT aq.application_id, aq.final_answer_json
                FROM recruitment_application_questions aq
                JOIN recruitment_applications a ON a.id=aq.application_id
                WHERE a.guild_id=? AND a.campaign_id=? AND a.id<>?
                  AND a.status IN ('SUBMITTED','UNDER_REVIEW','INTERVIEW_PENDING',
                                   'INTERVIEW_SCHEDULED','INTERVIEW_COMPLETED',
                                   'FINAL_REVIEW','APPROVED','REJECTED')
                  AND aq.question_id=? AND aq.final_answer_json IS NOT NULL
                ORDER BY a.submitted_at DESC LIMIT 100
                """,
                (guild_id, campaign_id, application_id, current["question_id"]),
            )
            matched_application_id = None
            matched_ratio = 0.0
            for previous in await previous_cursor.fetchall():
                previous_answer = json.loads(previous["final_answer_json"])
                if not isinstance(previous_answer, str):
                    continue
                ratio = SequenceMatcher(
                    None,
                    normalized,
                    re.sub(r"\s+", " ", previous_answer.casefold()).strip(),
                    autojunk=False,
                ).ratio()
                if ratio >= 0.92 and ratio > matched_ratio:
                    matched_ratio = ratio
                    matched_application_id = int(previous["application_id"])
            if matched_application_id is not None:
                await self._integrity(
                    connection,
                    guild_id,
                    application_id,
                    int(current["id"]),
                    "POSSIBLE_SIMILAR_RESPONSE",
                    now,
                    metadata={
                        "stable_key": current["stable_key"],
                        "other_application_id": matched_application_id,
                        "similarity_percent": round(matched_ratio * 100),
                    },
                )

    @block_source_cutover_writes("Recrutamento")
    async def withdraw_application(
        self,
        guild_id: int,
        discord_id: int,
        application_id: int,
        expected_version: int,
    ) -> dict[str, object]:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM recruitment_applications WHERE guild_id=? AND id=? AND discord_id=?",
                (guild_id, application_id, discord_id),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Candidatura não encontrada.")
            if application["status"] == "WITHDRAWN":
                return dict(application)
            if application["status"] not in ACTIVE_APPLICATION_STATUSES:
                raise ConflictError("Esta candidatura não pode mais ser retirada.")
            cursor = await connection.execute(
                """
                UPDATE recruitment_applications
                SET status='WITHDRAWN', stage='RESULT', updated_at=?, version=version+1
                WHERE id=? AND version=? AND status=?
                """,
                (now, application_id, expected_version, application["status"]),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A candidatura foi atualizada simultaneamente.")
            await self._history(
                connection,
                guild_id,
                application_id,
                "APPLICATION_WITHDRAWN",
                discord_id,
                "Candidatura retirada pelo candidato.",
                {},
            )
            await self.audit.record(
                guild_id,
                "RECRUITMENT_APPLICATION_WITHDRAWN",
                actor_id=discord_id,
                target_id=discord_id,
                before={"status": application["status"]},
                after={"status": "WITHDRAWN"},
                connection=connection,
            )
        return dict(
            await self.database.fetchone(
                "SELECT * FROM recruitment_applications WHERE id=?", (application_id,)
            )
        )

    @block_source_cutover_writes("Recrutamento")
    async def block_candidate(
        self,
        guild_id: int,
        actor_id: int,
        *,
        discord_id: int | None,
        bgr_id: str | None,
        reason: str,
    ) -> int:
        normalized_reason = reason.strip()
        normalized_bgr = (bgr_id or "").strip() or None
        if discord_id is None and normalized_bgr is None:
            raise ValidationError("Informe Discord ID ou ID BGR para o bloqueio.")
        if len(normalized_reason) < 3:
            raise ValidationError("Informe uma justificativa administrativa.")
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO recruitment_blocks(
                    guild_id, discord_id, bgr_id, reason, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    discord_id,
                    normalized_bgr,
                    normalized_reason[:2000],
                    actor_id,
                    self.clock(),
                ),
            )
            block_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "RECRUITMENT_CANDIDATE_BLOCKED",
                actor_id=actor_id,
                target_id=discord_id,
                after={"block_id": block_id, "bgr_id": normalized_bgr},
                reason=normalized_reason,
                connection=connection,
            )
        return block_id

    @block_source_cutover_writes("Recrutamento")
    async def revoke_block(self, guild_id: int, block_id: int, actor_id: int) -> None:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE recruitment_blocks SET active=0, revoked_by=?, revoked_at=?
                WHERE guild_id=? AND id=? AND active=1
                """,
                (actor_id, self.clock(), guild_id, block_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("Bloqueio ativo não encontrado.")
            await self.audit.record(
                guild_id,
                "RECRUITMENT_CANDIDATE_BLOCK_REVOKED",
                actor_id=actor_id,
                after={"block_id": block_id},
                connection=connection,
            )

    async def list_blocks(self, guild_id: int, *, active_only: bool = False) -> list[dict[str, object]]:
        query = "SELECT * FROM recruitment_blocks WHERE guild_id=?"
        if active_only:
            query += " AND active=1"
        query += " ORDER BY active DESC, created_at DESC, id DESC"
        return [dict(row) for row in await self.database.fetchall(query, (guild_id,))]

    async def list_applications(
        self,
        guild_id: int,
        *,
        status: str | None = None,
        search: str = "",
        assigned_to: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        filters = ["a.guild_id=?"]
        params: list[object] = [guild_id]
        if status:
            filters.append("a.status=?")
            params.append(status.upper())
        if assigned_to is not None:
            filters.append("a.assigned_to=?")
            params.append(assigned_to)
        if search.strip():
            filters.append("(a.protocol LIKE ? OR a.candidate_nick LIKE ? OR a.bgr_id LIKE ? OR CAST(a.discord_id AS TEXT) LIKE ?)")
            term = f"%{search.strip()}%"
            params.extend([term, term, term, term])
        params.append(limit)
        rows = await self.database.fetchall(
            f"""
            SELECT a.*, c.name AS campaign_name,
                   (SELECT COUNT(*) FROM recruitment_integrity_events ie
                    WHERE ie.application_id=a.id AND ie.event_type IN
                    ('PASTE_BLOCKED','COPY_BLOCKED','CUT_BLOCKED','DROP_BLOCKED','UNUSUAL_INPUT_PATTERN'))
                    AS integrity_signals
            FROM recruitment_applications a JOIN recruitment_campaigns c ON c.id=a.campaign_id
            WHERE {' AND '.join(filters)}
            ORDER BY COALESCE(a.submitted_at,a.created_at) DESC LIMIT ?
            """,
            tuple(params),
        )
        return [dict(row) for row in rows]

    async def statistics(self, guild_id: int) -> dict[str, object]:
        rows = await self.database.fetchall(
            """
            SELECT status, COUNT(*) AS total
            FROM recruitment_applications WHERE guild_id=? GROUP BY status
            """,
            (guild_id,),
        )
        averages = await self.database.fetchone(
            """
            SELECT AVG(CASE WHEN submitted_at IS NOT NULL
                       THEN submitted_at-started_at END) AS application_ms,
                   AVG(CASE WHEN reviewed_at IS NOT NULL AND submitted_at IS NOT NULL
                       THEN reviewed_at-submitted_at END) AS review_ms
            FROM recruitment_applications WHERE guild_id=?
            """,
            (guild_id,),
        )
        stale_hours = 24
        if self.audit.settings:
            stale_hours = max(
                1,
                min(
                    720,
                    int(
                        await self.audit.settings.get(
                            guild_id, "recruitment_stale_warning_hours", 24
                        )
                    ),
                ),
            )
        stale = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM recruitment_applications
            WHERE guild_id=? AND status IN ('SUBMITTED','UNDER_REVIEW')
              AND submitted_at IS NOT NULL AND submitted_at<=?
            """,
            (guild_id, self.clock() - stale_hours * 3_600_000),
        )
        return {
            "by_status": {str(row["status"]): int(row["total"]) for row in rows},
            "averages": {
                "application_ms": round(float(averages["application_ms"]))
                if averages["application_ms"] is not None
                else None,
                "review_ms": round(float(averages["review_ms"]))
                if averages["review_ms"] is not None
                else None,
            },
            "stale": int(stale["total"]),
            "stale_hours": stale_hours,
        }

    async def application_dossier(self, guild_id: int, application_id: int) -> dict[str, object]:
        application = await self.database.fetchone(
            "SELECT * FROM recruitment_applications WHERE guild_id=? AND id=?",
            (guild_id, application_id),
        )
        if not application:
            raise NotFoundError("Candidatura não encontrada.")
        questions, integrity, interviews, evaluations, notes, adaptations, history = await self._dossier_rows(
            application_id
        )
        counts = Counter(str(event["event_type"]) for event in integrity)
        attention = sum(
            counts[event]
            for event in (
                "PASTE_BLOCKED",
                "COPY_BLOCKED",
                "CUT_BLOCKED",
                "DROP_BLOCKED",
                "UNUSUAL_INPUT_PATTERN",
                "POSSIBLE_SIMILAR_RESPONSE",
            )
        )
        classification = "REVIEW" if attention >= 5 else "ATTENTION" if attention else "NORMAL"
        events_by_question: dict[int, list[dict[str, object]]] = {}
        for event in integrity:
            if event["application_question_id"] is not None:
                events_by_question.setdefault(int(event["application_question_id"]), []).append(
                    dict(event)
                )
        return {
            "application": dict(application),
            "questions": [
                self._question_for_admin(row, events_by_question.get(int(row["id"]), []))
                for row in questions
            ],
            "integrity": {
                "classification": classification,
                "counts": dict(counts),
                "events": [dict(row) for row in integrity],
            },
            "interviews": [dict(row) for row in interviews],
            "evaluations": [dict(row) for row in evaluations],
            "notes": [dict(row) for row in notes],
            "adaptations": [dict(row) for row in adaptations],
            "history": [dict(row) for row in history],
        }

    async def _dossier_rows(self, application_id: int):
        import asyncio

        return await asyncio.gather(
            self.database.fetchall("SELECT * FROM recruitment_application_questions WHERE application_id=? ORDER BY ordinal", (application_id,)),
            self.database.fetchall("SELECT * FROM recruitment_integrity_events WHERE application_id=? ORDER BY occurred_at", (application_id,)),
            self.database.fetchall("SELECT * FROM recruitment_interviews WHERE application_id=? ORDER BY scheduled_at", (application_id,)),
            self.database.fetchall("SELECT * FROM recruitment_evaluations WHERE application_id=? ORDER BY evaluated_at", (application_id,)),
            self.database.fetchall("SELECT * FROM recruitment_internal_notes WHERE application_id=? ORDER BY created_at", (application_id,)),
            self.database.fetchall("SELECT * FROM recruitment_adaptations WHERE application_id=? ORDER BY created_at", (application_id,)),
            self.database.fetchall("SELECT * FROM recruitment_history WHERE application_id=? ORDER BY created_at,id", (application_id,)),
        )

    @block_source_cutover_writes("Recrutamento")
    async def add_adaptation(
        self,
        guild_id: int,
        application_id: int,
        actor_id: int,
        *,
        extra_time_percent: int,
        clipboard_adapted: bool,
        alternative_format: str | None,
        reason: str,
    ) -> int:
        if not 0 <= extra_time_percent <= 200:
            raise ValidationError("Tempo adicional deve ficar entre 0% e 200%.")
        normalized_reason = reason.strip()
        alternative = (alternative_format or "").strip() or None
        if len(normalized_reason) < 3:
            raise ValidationError("Informe o motivo da adaptação.")
        if not extra_time_percent and not clipboard_adapted and not alternative:
            raise ValidationError("Selecione ao menos uma adaptação.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT status, discord_id FROM recruitment_applications WHERE guild_id=? AND id=?",
                (guild_id, application_id),
            )
            application = await cursor.fetchone()
            if not application:
                raise NotFoundError("Candidatura não encontrada.")
            self._prevent_self_review(application, actor_id)
            if application["status"] not in ACTIVE_APPLICATION_STATUSES:
                raise ConflictError("A candidatura não aceita novas adaptações.")
            cursor = await connection.execute(
                """
                INSERT INTO recruitment_adaptations(
                    guild_id, application_id, extra_time_percent, clipboard_adapted,
                    alternative_format, reason, approved_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    application_id,
                    extra_time_percent,
                    int(clipboard_adapted),
                    alternative[:500] if alternative else None,
                    normalized_reason[:2000],
                    actor_id,
                    now,
                ),
            )
            adaptation_id = int(cursor.lastrowid)
            await self.audit.record(
                guild_id,
                "RECRUITMENT_ADAPTATION_CREATED",
                actor_id=actor_id,
                after={
                    "application_id": application_id,
                    "adaptation_id": adaptation_id,
                    "extra_time_percent": extra_time_percent,
                    "clipboard_adapted": clipboard_adapted,
                    "alternative_format": alternative,
                },
                reason=normalized_reason,
                connection=connection,
            )
        return adaptation_id

    def _question_for_admin(
        self,
        row: Mapping[str, object],
        integrity_events: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        snapshot = json.loads(row["question_snapshot_json"])
        return {
            "id": row["id"], "ordinal": row["ordinal"], "status": row["status"],
            "title": snapshot["title"], "security_level": snapshot["security_level"],
            "started_at": row["started_at"], "expires_at": row["expires_at"],
            "duration_ms": row["duration_ms"],
            "answer": json.loads(row["final_answer_json"]) if row["final_answer_json"] else None,
            "integrity_events": integrity_events or [],
        }

    @block_source_cutover_writes("Recrutamento")
    async def assign(
        self, guild_id: int, application_id: int, reviewer_id: int, expected_version: int
    ) -> dict[str, object]:
        existing = await self.database.fetchone(
            "SELECT * FROM recruitment_applications WHERE guild_id=? AND id=?",
            (guild_id, application_id),
        )
        if not existing:
            raise NotFoundError("Candidatura não encontrada.")
        self._prevent_self_review(existing, reviewer_id)
        if existing["status"] == "UNDER_REVIEW" and existing["assigned_to"] is not None:
            if int(existing["assigned_to"]) == reviewer_id:
                return dict(existing)
            raise ConflictError("Esta candidatura já está atribuída a outro responsável.")
        result = await self._transition(
            guild_id, application_id, reviewer_id, expected_version,
            allowed={"SUBMITTED", "UNDER_REVIEW"}, target="UNDER_REVIEW",
            action="APPLICATION_ASSIGNED",
            assignments={"assigned_to": reviewer_id, "assigned_at": self.clock()},
        )
        return result

    @block_source_cutover_writes("Recrutamento")
    async def schedule_interview(
        self,
        guild_id: int,
        application_id: int,
        actor_id: int,
        expected_version: int,
        scheduled_at: int,
        interviewer_id: int,
        notes: str | None,
    ) -> dict[str, object]:
        now = self.clock()
        if scheduled_at <= now:
            raise ValidationError("A entrevista deve ser agendada no futuro.")
        async with self.database.transaction() as connection:
            application = await self._application_for_update(connection, guild_id, application_id, expected_version)
            self._prevent_self_review(application, actor_id)
            if application["status"] not in {"SUBMITTED", "UNDER_REVIEW", "INTERVIEW_PENDING"}:
                raise ConflictError("A candidatura não está pronta para entrevista.")
            await connection.execute(
                """
                INSERT INTO recruitment_interviews(
                    guild_id, application_id, scheduled_at, interviewer_id, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (guild_id, application_id, scheduled_at, interviewer_id, (notes or "")[:1000] or None, now),
            )
            await self._set_application_status(
                connection, application, "INTERVIEW_SCHEDULED", actor_id, "INTERVIEW_SCHEDULED", now
            )
            await self._notification(
                connection,
                guild_id,
                application_id,
                "RECRUITMENT_INTERVIEW_SCHEDULED",
                f"interview-scheduled:{application_id}:{scheduled_at}",
                {"application_id": application_id, "scheduled_at": scheduled_at},
                now,
            )
            await self._public_status_notification(
                connection,
                guild_id,
                application_id,
                "INTERVIEW_SCHEDULED",
                now,
                extra_key=str(scheduled_at),
            )
            await self.audit.record(
                guild_id,
                "RECRUITMENT_INTERVIEW_SCHEDULED",
                actor_id=actor_id,
                target_id=int(application["discord_id"]),
                after={"scheduled_at": scheduled_at, "interviewer_id": interviewer_id},
                connection=connection,
            )
        return dict(await self.database.fetchone("SELECT * FROM recruitment_applications WHERE id=?", (application_id,)))

    @block_source_cutover_writes("Recrutamento")
    async def evaluate_interview(
        self,
        guild_id: int,
        application_id: int,
        interview_id: int,
        evaluator_id: int,
        expected_version: int,
        *,
        communication: str,
        posture: str,
        knowledge: str,
        discipline: str,
        result: str,
        observation: str | None,
    ) -> dict[str, object]:
        ratings = {communication.upper(), posture.upper(), knowledge.upper(), discipline.upper()}
        if not ratings.issubset(INTERVIEW_RATINGS) or result.upper() not in {"FIT", "UNFIT", "REEVALUATE"}:
            raise ValidationError("Avaliação de entrevista inválida.")
        now = self.clock()
        async with self.database.transaction() as connection:
            application = await self._application_for_update(connection, guild_id, application_id, expected_version)
            self._prevent_self_review(application, evaluator_id)
            cursor = await connection.execute(
                "SELECT * FROM recruitment_interviews WHERE id=? AND application_id=? AND status='SCHEDULED'",
                (interview_id, application_id),
            )
            interview = await cursor.fetchone()
            if not interview:
                raise NotFoundError("Entrevista agendada não encontrada.")
            await connection.execute(
                """
                INSERT INTO recruitment_evaluations(
                    guild_id, application_id, interview_id, evaluator_id, communication,
                    posture, knowledge, discipline, result, observation, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, application_id, interview_id, evaluator_id, communication.upper(), posture.upper(), knowledge.upper(), discipline.upper(), result.upper(), (observation or "")[:2000] or None, now),
            )
            await connection.execute(
                "UPDATE recruitment_interviews SET status='COMPLETED', completed_at=? WHERE id=? AND status='SCHEDULED'",
                (now, interview_id),
            )
            await self._set_application_status(
                connection, application, "FINAL_REVIEW", evaluator_id,
                "INTERVIEW_COMPLETED", now,
            )
            await self._public_status_notification(
                connection,
                guild_id,
                application_id,
                "FINAL_REVIEW",
                now,
            )
            await self.audit.record(
                guild_id,
                "RECRUITMENT_INTERVIEW_EVALUATED",
                actor_id=evaluator_id,
                target_id=int(application["discord_id"]),
                after={"interview_id": interview_id, "result": result.upper()},
                connection=connection,
            )
            if self.analysis_service is not None:
                await self.analysis_service.enqueue_final_if_enabled(
                    guild_id, application_id, evaluator_id, connection
                )
        return dict(await self.database.fetchone("SELECT * FROM recruitment_applications WHERE id=?", (application_id,)))

    @block_source_cutover_writes("Recrutamento")
    async def decide(
        self,
        guild_id: int,
        application_id: int,
        actor_id: int,
        expected_version: int,
        *,
        approved: bool,
        internal_reason: str,
        candidate_message: str,
        origin: str = "WEB",
        correlation_id: str | None = None,
    ) -> dict[str, object]:
        internal = internal_reason.strip()
        public = candidate_message.strip()
        if len(internal) < 3 or len(public) < 3:
            raise ValidationError("Informe motivo interno e mensagem ao candidato.")
        normalized_origin = origin.strip().upper()
        if normalized_origin not in {"WEB", "DISCORD"}:
            raise ValidationError("Origem de decisão de recrutamento inválida.")
        correlation = correlation_id.strip() if correlation_id else str(uuid.uuid4())
        target = "APPROVED" if approved else "REJECTED"
        existing = await self.database.fetchone(
            "SELECT * FROM recruitment_applications WHERE guild_id=? AND id=?",
            (guild_id, application_id),
        )
        if not existing:
            raise NotFoundError("Candidatura não encontrada.")
        self._prevent_self_review(existing, actor_id)
        if existing["status"] == target:
            return dict(existing)
        if existing["status"] in {"APPROVED", "REJECTED"}:
            raise ConflictError("A candidatura já possui uma decisão final diferente.")
        now = self.clock()
        async with self.database.transaction() as connection:
            try:
                application = await self._application_for_update(
                    connection, guild_id, application_id, expected_version
                )
            except ConflictError:
                # A repeated click may enter after the first transaction has
                # committed.  It is idempotent only when the same final
                # outcome already exists; the opposite result still conflicts.
                cursor = await connection.execute(
                    "SELECT * FROM recruitment_applications WHERE guild_id=? AND id=?",
                    (guild_id, application_id),
                )
                current = await cursor.fetchone()
                if current and current["status"] == target:
                    return dict(current)
                raise
            if application["status"] not in {"UNDER_REVIEW", "INTERVIEW_COMPLETED", "FINAL_REVIEW"}:
                raise ConflictError("A candidatura não está em decisão final.")
            cursor = await connection.execute(
                """
                UPDATE recruitment_applications
                SET status=?, stage='RESULT', decided_at=?, decided_by=?, reviewed_at=?,
                    internal_reason=?, candidate_message=?, updated_at=?, version=version+1
                WHERE id=? AND version=? AND status=?
                """,
                (target, now, actor_id, now, internal, public, now, application_id, expected_version, application["status"]),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A candidatura foi decidida simultaneamente.")
            if approved:
                member_id = await self._approve_member(connection, application, actor_id, now)
                await self._notification(
                    connection, guild_id, application_id, "RECRUITMENT_APPLICATION_APPROVED",
                    f"application-approved:{application_id}", {"application_id": application_id}, now,
                )
                await self._notification(
                    connection, guild_id, application_id, "RECRUITMENT_APPLICATION_APPROVED_LOG",
                    f"application-approved-log:{application_id}", {"application_id": application_id}, now,
                )
                event = "APPLICATION_APPROVED"
            else:
                campaign = await connection.execute(
                    "SELECT cooldown_days FROM recruitment_campaigns WHERE id=?", (application["campaign_id"],)
                )
                days = int((await campaign.fetchone())["cooldown_days"])
                cooldown_until = now + days * 86_400_000
                await connection.execute(
                    "UPDATE recruitment_applications SET cooldown_until=? WHERE id=?",
                    (cooldown_until, application_id),
                )
                await connection.execute(
                    """
                    INSERT INTO recruitment_cooldowns(
                        guild_id, discord_id, application_id, starts_at, ends_at,
                        reason, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (guild_id, application["discord_id"], application_id, now, cooldown_until, internal, actor_id, now),
                )
                await self._notification(
                    connection, guild_id, application_id, "RECRUITMENT_APPLICATION_REJECTED",
                    f"application-rejected:{application_id}", {"application_id": application_id, "cooldown_until": cooldown_until}, now,
                )
                await self._notification(
                    connection, guild_id, application_id, "RECRUITMENT_APPLICATION_REJECTED_LOG",
                    f"application-rejected-log:{application_id}", {"application_id": application_id}, now,
                )
                member_id = None
                event = "APPLICATION_REJECTED"
            await self._public_status_notification(
                connection,
                guild_id,
                application_id,
                target,
                now,
            )
            await self._review_card_notification(
                connection,
                guild_id,
                application_id,
                target,
                expected_version + 1,
                now,
            )
            await self._history(
                connection,
                guild_id,
                application_id,
                event,
                actor_id,
                public,
                {"origin": normalized_origin, "correlation_id": correlation},
            )
            await self.audit.record(
                guild_id, f"RECRUITMENT_{event}", actor_id=actor_id,
                target_id=int(application["discord_id"]), before={"status": application["status"]},
                after={
                    "status": target,
                    "member_id": member_id,
                    "origin": normalized_origin,
                    "correlation_id": correlation,
                    "entry_method": str(application["entry_method"] or "FORM"),
                    "indicated_by": application["indicated_by"],
                    "requested_unit_code": application["requested_unit_code"],
                },
                reason=internal,
                correlation_id=correlation,
                connection=connection,
            )
        return dict(await self.database.fetchone("SELECT * FROM recruitment_applications WHERE id=?", (application_id,)))

    async def _approve_member(
        self, connection: aiosqlite.Connection, application: Mapping[str, object], actor_id: int, now: int
    ) -> int:
        cursor = await connection.execute(
            "SELECT initial_rank_id FROM recruitment_campaigns WHERE id=?", (application["campaign_id"],)
        )
        campaign = await cursor.fetchone()
        rank_id = campaign["initial_rank_id"]
        if rank_id is None:
            cursor = await connection.execute(
                "SELECT id FROM ranks WHERE guild_id=? AND active=1 ORDER BY level LIMIT 1",
                (application["guild_id"],),
            )
            rank = await cursor.fetchone()
            if not rank:
                raise ConflictError("Configure uma patente inicial antes de aprovar.")
            rank_id = rank["id"]
        cursor = await connection.execute(
            """
            SELECT id, character_id FROM members
            WHERE guild_id=? AND discord_id=?
            LIMIT 1
            """,
            (application["guild_id"], application["discord_id"]),
        )
        discord_member = await cursor.fetchone()
        if (
            discord_member
            and str(discord_member["character_id"] or "").strip()
            and str(discord_member["character_id"]).strip().casefold()
            != str(application["bgr_id"]).strip().casefold()
        ):
            raise ConflictError(
                "Este Discord já está vinculado a outro ID in-game. "
                "Revise a identidade existente antes de aprovar esta candidatura."
            )
        cursor = await connection.execute(
            """
            SELECT id, discord_id FROM members
            WHERE guild_id=?
              AND lower(trim(character_id))=lower(trim(?))
              AND discord_id<>?
            LIMIT 1
            """,
            (
                application["guild_id"],
                application["bgr_id"],
                application["discord_id"],
            ),
        )
        conflicting_member = await cursor.fetchone()
        if conflicting_member:
            raise ConflictError(
                "O ID in-game informado já está vinculado a outro perfil. "
                "Revise a identidade existente antes de aprovar esta candidatura."
            )
        try:
            await connection.execute(
                """
                INSERT INTO members(
                    guild_id, discord_id, discord_nick, mta_nick, character_id, rank_id,
                    unit, status, joined_at, last_activity_at, created_at, updated_at,
                    origin_recruitment_application_id
                ) VALUES (?, ?, ?, ?, ?, ?, 'BGR', 'ACTIVE', ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                    mta_nick=excluded.mta_nick, character_id=excluded.character_id,
                    rank_id=excluded.rank_id, status='ACTIVE', updated_at=excluded.updated_at,
                    origin_recruitment_application_id=excluded.origin_recruitment_application_id
                """,
                (
                    application["guild_id"], application["discord_id"], application["discord_username"],
                    application["candidate_nick"], application["bgr_id"], rank_id,
                    now, now, now, now, application["id"],
                ),
            )
        except aiosqlite.IntegrityError as exc:
            if "ux_members_bgr_identity" in str(exc):
                raise ConflictError(
                    "O ID in-game informado já está vinculado a outro perfil. "
                    "Revise a identidade existente antes de aprovar esta candidatura."
                ) from exc
            raise
        cursor = await connection.execute(
            "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
            (application["guild_id"], application["discord_id"]),
        )
        member_id = int((await cursor.fetchone())["id"])
        await connection.execute(
            """
            INSERT INTO registration_gate_records(
                guild_id, discord_id, status, access_tier, mta_nick, bgr_id,
                member_id, recruitment_application_id, source, sync_status,
                idempotency_key, submitted_at, completed_at, reviewed_at,
                reviewed_by, review_reason, last_attempt_at, created_at, updated_at
            ) VALUES (?, ?, 'REGISTERED', 'RECRUIT', ?, ?, ?, ?, 'ADMIN_APPROVAL',
                      'PENDING', ?, ?, ?, ?, ?, 'Candidatura aprovada', ?, ?, ?)
            ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                status='REGISTERED', access_tier='RECRUIT',
                mta_nick=excluded.mta_nick, bgr_id=excluded.bgr_id,
                member_id=excluded.member_id,
                recruitment_application_id=excluded.recruitment_application_id,
                source='ADMIN_APPROVAL', conflict_code=NULL, conflict_member_id=NULL,
                sync_status='PENDING', sync_error=NULL, completed_at=excluded.completed_at,
                reviewed_at=excluded.reviewed_at, reviewed_by=excluded.reviewed_by,
                review_reason=excluded.review_reason, last_attempt_at=excluded.last_attempt_at,
                version=registration_gate_records.version+1, updated_at=excluded.updated_at
            """,
            (
                application["guild_id"],
                application["discord_id"],
                application["candidate_nick"],
                application["bgr_id"],
                member_id,
                application["id"],
                f"recruitment:{application['id']}",
                now,
                now,
                now,
                actor_id,
                now,
                now,
                now,
            ),
        )
        cursor = await connection.execute(
            """
            SELECT id FROM registration_gate_records
            WHERE guild_id=? AND discord_id=?
            """,
            (application["guild_id"], application["discord_id"]),
        )
        registration_id = int((await cursor.fetchone())["id"])
        await connection.execute(
            """
            INSERT INTO registration_gate_events(
                guild_id, registration_id, event_type, actor_id, source,
                metadata_json, created_at
            ) VALUES (?, ?, 'REGISTRATION_COMPLETED', ?, 'ADMIN_APPROVAL', ?, ?)
            """,
            (
                application["guild_id"],
                registration_id,
                actor_id,
                json.dumps(
                    {"recruitment_application_id": application["id"], "member_id": member_id}
                ),
                now,
            ),
        )
        await connection.execute(
            """
            INSERT INTO recruit_onboarding_checklists(
                guild_id, member_id, registration_status, updated_at
            ) VALUES (?, ?, 'COMPLETED', ?)
            ON CONFLICT(guild_id, member_id) DO UPDATE SET
                registration_status='COMPLETED', updated_at=excluded.updated_at
            """,
            (application["guild_id"], member_id, now),
        )
        await connection.execute(
            """
            INSERT INTO recruit_followups(
                guild_id, member_id, discord_id, origin_application_id, started_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, origin_application_id) DO NOTHING
            """,
            (application["guild_id"], member_id, application["discord_id"], application["id"], now),
        )
        correlation = str(uuid.uuid4())
        await connection.execute(
            """
            INSERT INTO web_action_outbox(
                guild_id, action_type, target_discord_id, payload_json,
                requested_by, correlation_id, available_at, created_at
            ) VALUES (?, 'MEMBER_SYNC', ?, ?, ?, ?, ?, ?)
            """,
            (
                application["guild_id"], application["discord_id"],
                json.dumps(
                    {
                        "source": "REGISTRATION",
                        "flow": "RECRUITMENT_APPROVAL",
                        "origin_application_id": application["id"],
                    },
                    ensure_ascii=False,
                ), actor_id,
                correlation, now, now,
            ),
        )
        await self.audit.record(
            int(application["guild_id"]),
            "RECRUIT_CREATED",
            actor_id=actor_id,
            target_id=int(application["discord_id"]),
            after={
                "member_id": member_id,
                "application_id": int(application["id"]),
                "rank_id": int(rank_id),
            },
            connection=connection,
        )
        await self.audit.record(
            int(application["guild_id"]),
            "REGISTRATION_COMPLETED",
            actor_id=actor_id,
            target_id=int(application["discord_id"]),
            after={
                "registration_id": registration_id,
                "member_id": member_id,
                "source": "RECRUITMENT",
            },
            connection=connection,
        )
        await self._import_approved_member_to_source(
            connection,
            application=application,
            satellite_rank_id=int(rank_id),
            actor_id=actor_id,
            now=now,
        )
        return member_id

    async def _import_approved_member_to_source(
        self,
        connection: aiosqlite.Connection,
        *,
        application: Mapping[str, object],
        satellite_rank_id: int,
        actor_id: int,
        now: int,
    ) -> int | None:
        """Project an approved REC identity into its canonical guild.

        The satellite keeps its own row and Discord roles.  The canonical guild
        receives a separate member/Portaria row mapped by rank level.  Existing
        higher ranks are preserved and a conflicting BGR identity is routed to
        human review instead of being overwritten.
        """
        satellite_guild_id = int(application["guild_id"])
        cursor = await connection.execute(
            """
            SELECT value_json FROM guild_settings
            WHERE guild_id=? AND setting_key='identity_source_guild_id'
            """,
            (satellite_guild_id,),
        )
        setting = await cursor.fetchone()
        if not setting:
            return None
        try:
            source_guild_id = int(json.loads(str(setting["value_json"])))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if source_guild_id == satellite_guild_id:
            return None

        cursor = await connection.execute(
            "SELECT level FROM ranks WHERE id=? AND guild_id=? AND active=1",
            (satellite_rank_id, satellite_guild_id),
        )
        satellite_rank = await cursor.fetchone()
        if not satellite_rank:
            return None
        cursor = await connection.execute(
            """
            SELECT id, level FROM ranks
            WHERE guild_id=? AND level=? AND active=1
            ORDER BY id LIMIT 1
            """,
            (source_guild_id, int(satellite_rank["level"])),
        )
        source_rank = await cursor.fetchone()
        if not source_rank:
            return None

        discord_id = int(application["discord_id"])
        bgr_id = str(application["bgr_id"] or "").strip()
        mta_nick = str(application["candidate_nick"] or "").strip()
        cursor = await connection.execute(
            "SELECT * FROM members WHERE guild_id=? AND discord_id=?",
            (source_guild_id, discord_id),
        )
        current_member = await cursor.fetchone()
        cursor = await connection.execute(
            """
            SELECT * FROM members
            WHERE guild_id=? AND lower(trim(COALESCE(character_id,'')))=lower(trim(?))
            ORDER BY id LIMIT 1
            """,
            (source_guild_id, bgr_id),
        )
        bgr_owner = await cursor.fetchone()
        discord_identity_conflict = bool(
            current_member
            and str(current_member["character_id"] or "").strip()
            and str(current_member["character_id"]).strip().casefold() != bgr_id.casefold()
        )
        bgr_identity_conflict = bool(
            bgr_owner and int(bgr_owner["discord_id"]) != discord_id
        )
        if discord_identity_conflict or bgr_identity_conflict:
            conflict_member_id = int(
                (bgr_owner or current_member)["id"]
            )
            await connection.execute(
                """
                INSERT INTO registration_gate_records(
                    guild_id, discord_id, status, access_tier, mta_nick, bgr_id,
                    recruitment_application_id, source, conflict_code,
                    conflict_member_id, sync_status, idempotency_key, submitted_at,
                    reviewed_at, reviewed_by, review_reason, created_at, updated_at
                ) VALUES (?, ?, 'REQUIRES_REVIEW', 'CANDIDATE', ?, ?, ?,
                          'ADMIN_APPROVAL', 'CROSS_GUILD_IDENTITY_CONFLICT', ?,
                          'NOT_REQUIRED', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                    status='REQUIRES_REVIEW', access_tier='CANDIDATE',
                    mta_nick=excluded.mta_nick, bgr_id=excluded.bgr_id,
                    recruitment_application_id=excluded.recruitment_application_id,
                    source='ADMIN_APPROVAL', conflict_code=excluded.conflict_code,
                    conflict_member_id=excluded.conflict_member_id,
                    sync_status='NOT_REQUIRED', sync_error=NULL,
                    submitted_at=excluded.submitted_at, reviewed_at=excluded.reviewed_at,
                    reviewed_by=excluded.reviewed_by, review_reason=excluded.review_reason,
                    version=registration_gate_records.version+1,
                    updated_at=excluded.updated_at
                """,
                (
                    source_guild_id,
                    discord_id,
                    mta_nick,
                    bgr_id,
                    int(application["id"]),
                    conflict_member_id,
                    f"rec-source-review:{satellite_guild_id}:{int(application['id'])}",
                    now,
                    now,
                    actor_id,
                    "Identidade aprovada no REC diverge do cadastro canônico.",
                    now,
                    now,
                ),
            )
            await connection.execute(
                """
                INSERT OR IGNORE INTO audit_logs(
                    correlation_id, guild_id, action, actor_id, target_id,
                    after_json, reason, created_at
                ) VALUES (?, ?, 'CROSS_GUILD_IDENTITY_REVIEW_REQUIRED', ?, ?, ?, ?, ?)
                """,
                (
                    f"rec-source-review:{satellite_guild_id}:{int(application['id'])}",
                    source_guild_id,
                    actor_id,
                    discord_id,
                    json.dumps(
                        {
                            "satellite_guild_id": satellite_guild_id,
                            "application_id": int(application["id"]),
                            "conflict_member_id": conflict_member_id,
                        },
                        ensure_ascii=False,
                    ),
                    "Importação automática bloqueada para impedir identidade duplicada.",
                    now,
                ),
            )
            return None

        selected_rank_id = int(source_rank["id"])
        selected_rank_level = int(source_rank["level"])
        if current_member and current_member["rank_id"] is not None:
            cursor = await connection.execute(
                "SELECT level FROM ranks WHERE id=? AND guild_id=?",
                (int(current_member["rank_id"]), source_guild_id),
            )
            current_rank = await cursor.fetchone()
            if current_rank and int(current_rank["level"]) > selected_rank_level:
                selected_rank_id = int(current_member["rank_id"])
                selected_rank_level = int(current_rank["level"])

        cursor = await connection.execute(
            """
            SELECT r.*, m.id AS linked_member_id
            FROM registration_gate_records r
            LEFT JOIN members m ON m.id=r.member_id
            WHERE r.guild_id=? AND r.discord_id=?
            """,
            (source_guild_id, discord_id),
        )
        current_registration = await cursor.fetchone()
        await connection.execute(
            """
            INSERT INTO members(
                guild_id, discord_id, discord_nick, mta_nick, character_id, rank_id,
                unit, status, joined_at, last_activity_at, created_at, updated_at,
                origin_recruitment_application_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'BGR', 'ACTIVE', ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                discord_nick=excluded.discord_nick,
                mta_nick=excluded.mta_nick,
                character_id=excluded.character_id,
                rank_id=excluded.rank_id,
                unit='BGR', status='ACTIVE', updated_at=excluded.updated_at,
                origin_recruitment_application_id=excluded.origin_recruitment_application_id
            """,
            (
                source_guild_id,
                discord_id,
                str(application["discord_username"] or ""),
                mta_nick,
                bgr_id,
                selected_rank_id,
                now,
                now,
                now,
                now,
                int(application["id"]),
            ),
        )
        cursor = await connection.execute(
            "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
            (source_guild_id, discord_id),
        )
        source_member_id = int((await cursor.fetchone())["id"])
        cursor = await connection.execute(
            "SELECT MIN(level) AS minimum_level FROM ranks WHERE guild_id=? AND active=1",
            (source_guild_id,),
        )
        minimum_rank = await cursor.fetchone()
        access_tier = (
            "RECRUIT"
            if minimum_rank and selected_rank_level == int(minimum_rank["minimum_level"])
            else "MEMBER"
        )
        await connection.execute(
            """
            INSERT INTO registration_gate_records(
                guild_id, discord_id, status, access_tier, mta_nick, bgr_id,
                member_id, recruitment_application_id, source, sync_status,
                idempotency_key, submitted_at, completed_at, reviewed_at,
                reviewed_by, review_reason, last_attempt_at, created_at, updated_at
            ) VALUES (?, ?, 'REGISTERED', ?, ?, ?, ?, ?, 'ADMIN_APPROVAL',
                      'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                status='REGISTERED', access_tier=excluded.access_tier,
                mta_nick=excluded.mta_nick, bgr_id=excluded.bgr_id,
                member_id=excluded.member_id,
                recruitment_application_id=excluded.recruitment_application_id,
                source='ADMIN_APPROVAL', conflict_code=NULL, conflict_member_id=NULL,
                sync_status='PENDING', sync_error=NULL,
                idempotency_key=COALESCE(registration_gate_records.idempotency_key,
                                         excluded.idempotency_key),
                completed_at=excluded.completed_at, reviewed_at=excluded.reviewed_at,
                reviewed_by=excluded.reviewed_by, review_reason=excluded.review_reason,
                last_attempt_at=excluded.last_attempt_at,
                version=registration_gate_records.version+1,
                updated_at=excluded.updated_at
            """,
            (
                source_guild_id,
                discord_id,
                access_tier,
                mta_nick,
                bgr_id,
                source_member_id,
                int(application["id"]),
                f"rec-source-import:{satellite_guild_id}:{int(application['id'])}",
                now,
                now,
                now,
                actor_id,
                "Candidatura aprovada no servidor de recrutamento.",
                now,
                now,
                now,
            ),
        )
        cursor = await connection.execute(
            """
            SELECT id FROM registration_gate_records
            WHERE guild_id=? AND discord_id=?
            """,
            (source_guild_id, discord_id),
        )
        registration_id = int((await cursor.fetchone())["id"])
        state_changed = not current_registration or (
            str(current_registration["status"]) != "REGISTERED"
            or current_registration["linked_member_id"] is None
        )
        if state_changed:
            await connection.execute(
                """
                INSERT INTO registration_gate_events(
                    guild_id, registration_id, event_type, actor_id, source,
                    metadata_json, created_at
                ) VALUES (?, ?, 'REGISTRATION_COMPLETED', ?, 'REC_APPROVAL_IMPORT', ?, ?)
                """,
                (
                    source_guild_id,
                    registration_id,
                    actor_id,
                    json.dumps(
                        {
                            "satellite_guild_id": satellite_guild_id,
                            "application_id": int(application["id"]),
                            "member_id": source_member_id,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
        await connection.execute(
            """
            INSERT INTO web_action_outbox(
                guild_id, action_type, target_discord_id, payload_json,
                requested_by, correlation_id, available_at, created_at
            ) VALUES (?, 'MEMBER_SYNC', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(correlation_id) DO UPDATE SET
                status='PENDING', attempts=0, available_at=excluded.available_at,
                processed_at=NULL, last_error=NULL
            """,
            (
                source_guild_id,
                discord_id,
                json.dumps(
                    {
                        "source": "REC_APPROVAL_IMPORT",
                        "satellite_guild_id": satellite_guild_id,
                        "origin_application_id": int(application["id"]),
                    },
                    ensure_ascii=False,
                ),
                actor_id,
                f"rec-source-member-sync:{satellite_guild_id}:{int(application['id'])}",
                now,
                now,
            ),
        )
        if state_changed:
            await connection.execute(
                """
                INSERT OR IGNORE INTO audit_logs(
                    correlation_id, guild_id, action, actor_id, target_id,
                    after_json, reason, created_at
                ) VALUES (?, ?, 'REC_APPROVAL_IMPORTED_TO_CANONICAL_GUILD', ?, ?, ?, ?, ?)
                """,
                (
                    f"rec-source-import:{satellite_guild_id}:{int(application['id'])}",
                    source_guild_id,
                    actor_id,
                    discord_id,
                    json.dumps(
                        {
                            "satellite_guild_id": satellite_guild_id,
                            "application_id": int(application["id"]),
                            "member_id": source_member_id,
                            "rank_level": selected_rank_level,
                        },
                        ensure_ascii=False,
                    ),
                    "Cadastro aprovado no REC importado para o efetivo canônico.",
                    now,
                ),
            )
        return source_member_id

    async def import_approved_identity_to_source(
        self,
        source_guild_id: int,
        discord_id: int,
        *,
        actor_id: int,
    ) -> dict[str, object] | None:
        """Backfill an approved satellite recruit when they join the source guild."""
        linked_settings = await self.database.fetchall(
            """
            SELECT guild_id, value_json FROM guild_settings
            WHERE setting_key='identity_source_guild_id'
            """
        )
        satellite_guild_ids: list[int] = []
        for setting in linked_settings:
            try:
                configured_source = int(json.loads(str(setting["value_json"])))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if configured_source == int(source_guild_id):
                satellite_guild_ids.append(int(setting["guild_id"]))
        for satellite_guild_id in satellite_guild_ids:
            application = await self.database.fetchone(
                """
                SELECT a.*, m.rank_id AS satellite_rank_id
                FROM recruitment_applications a
                JOIN members m
                  ON m.guild_id=a.guild_id AND m.discord_id=a.discord_id
                WHERE a.guild_id=? AND a.discord_id=? AND a.status='APPROVED'
                  AND m.status='ACTIVE'
                ORDER BY COALESCE(a.decided_at, a.updated_at) DESC, a.id DESC
                LIMIT 1
                """,
                (satellite_guild_id, discord_id),
            )
            if not application or application["satellite_rank_id"] is None:
                continue
            async with self.database.transaction() as connection:
                member_id = await self._import_approved_member_to_source(
                    connection,
                    application=application,
                    satellite_rank_id=int(application["satellite_rank_id"]),
                    actor_id=actor_id,
                    now=self.clock(),
                )
            if member_id is not None:
                row = await self.database.fetchone(
                    "SELECT * FROM members WHERE id=? AND guild_id=?",
                    (member_id, source_guild_id),
                )
                return dict(row) if row else None
        return None

    @block_source_cutover_writes("Recrutamento")
    async def add_note(
        self, guild_id: int, application_id: int, author_id: int, note: str
    ) -> int:
        value = note.strip()
        if len(value) < 3:
            raise ValidationError("A observação é muito curta.")
        if not await self.database.fetchone(
            "SELECT 1 FROM recruitment_applications WHERE guild_id=? AND id=?",
            (guild_id, application_id),
        ):
            raise NotFoundError("Candidatura não encontrada.")
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO recruitment_internal_notes(
                    guild_id, application_id, author_id, note, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, application_id, author_id, value[:4000], self.clock()),
            )
            await self.audit.record(
                guild_id,
                "RECRUITMENT_INTERNAL_NOTE_CREATED",
                actor_id=author_id,
                after={"application_id": application_id, "note_id": int(cursor.lastrowid)},
                connection=connection,
            )
            return int(cursor.lastrowid)

    @block_source_cutover_writes("Recrutamento")
    async def update_campaign(
        self, guild_id: int, campaign_id: int, actor_id: int, values: Mapping[str, object]
    ) -> dict[str, object]:
        allowed_statuses = {"DRAFT", "SCHEDULED", "OPEN", "PAUSED", "CLOSED", "ARCHIVED"}
        status = str(values["status"]).upper()
        if status not in allowed_statuses:
            raise ValidationError("Status de processo seletivo inválido.")
        opens_at = values.get("opens_at")
        closes_at = values.get("closes_at")
        if opens_at and closes_at and int(closes_at) <= int(opens_at):
            raise ValidationError("O encerramento deve ocorrer depois da abertura.")
        if status in {"SCHEDULED", "OPEN"}:
            form = await self.database.fetchone(
                """
                SELECT fv.status FROM recruitment_campaigns c
                JOIN recruitment_form_versions fv ON fv.id=c.form_version_id
                WHERE c.guild_id=? AND c.id=?
                """,
                (guild_id, campaign_id),
            )
            if not form or form["status"] != "PUBLISHED":
                raise ValidationError("Publique uma versão do formulário antes de abrir a campanha.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM recruitment_campaigns WHERE guild_id=? AND id=?",
                (guild_id, campaign_id),
            )
            before = await cursor.fetchone()
            if not before:
                raise NotFoundError("Processo seletivo não encontrado.")
            await connection.execute(
                """
                UPDATE recruitment_campaigns
                SET name=?, status=?, opens_at=?, closes_at=?, cooldown_days=?, minimum_age=?,
                    maximum_applications=?, initial_rank_id=?, candidate_role_id=?,
                    interview_channel_id=?, updated_at=? WHERE guild_id=? AND id=?
                """,
                (
                    str(values["name"]).strip(), status, values.get("opens_at"), values.get("closes_at"),
                    int(values["cooldown_days"]), int(values["minimum_age"]),
                    values.get("maximum_applications"), values.get("initial_rank_id"),
                    values.get("candidate_role_id"), values.get("interview_channel_id"), now,
                    guild_id, campaign_id,
                ),
            )
            await self.audit.record(
                guild_id, "RECRUITMENT_CAMPAIGN_UPDATED", actor_id=actor_id,
                before=dict(before), after=dict(values), connection=connection,
            )
        return dict(await self.database.fetchone("SELECT * FROM recruitment_campaigns WHERE id=?", (campaign_id,)))

    async def questions_for_admin(self, guild_id: int) -> list[dict[str, object]]:
        rows = await self.database.fetchall(
            """
            SELECT q.*, g.code AS group_code, g.name AS group_name
            FROM recruitment_questions q JOIN recruitment_question_groups g ON g.id=q.group_id
            WHERE q.guild_id=? ORDER BY g.position, q.position
            """,
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def groups_for_admin(self, guild_id: int) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in await self.database.fetchall(
                """
                SELECT g.*,
                       COUNT(q.id) AS question_count,
                       SUM(CASE WHEN q.enabled=1 THEN 1 ELSE 0 END) AS enabled_question_count
                FROM recruitment_question_groups g
                LEFT JOIN recruitment_questions q ON q.group_id=g.id
                WHERE g.guild_id=?
                GROUP BY g.id ORDER BY g.position, g.id
                """,
                (guild_id,),
            )
        ]

    @staticmethod
    def _validate_question_values(values: Mapping[str, object]) -> tuple[str, str, str, str]:
        question_type = str(values["question_type"]).upper()
        security_level = str(values["security_level"]).upper()
        timer_mode = str(values["timer_mode"]).upper()
        difficulty = str(values["difficulty"]).upper()
        if question_type not in QUESTION_TYPES:
            raise ValidationError("Tipo de questão inválido.")
        if security_level not in {"NORMAL", "CONTROLLED", "STRICT"}:
            raise ValidationError("Nível de segurança inválido.")
        if timer_mode not in {"AUTO", "FIXED", "NONE"}:
            raise ValidationError("Modo de temporizador inválido.")
        if difficulty not in {"EASY", "MEDIUM", "HARD"}:
            raise ValidationError("Dificuldade inválida.")
        minimum, maximum = values.get("min_length"), values.get("max_length")
        if minimum is not None and maximum is not None and int(minimum) > int(maximum):
            raise ValidationError("O mínimo não pode superar o máximo.")
        expected_minimum = values.get("expected_min_length")
        expected_maximum = values.get("expected_max_length")
        if (
            expected_minimum is not None
            and expected_maximum is not None
            and int(expected_minimum) > int(expected_maximum)
        ):
            raise ValidationError("O mínimo esperado não pode superar o máximo esperado.")
        if timer_mode == "FIXED" and not values.get("fixed_time_seconds"):
            raise ValidationError("Informe o tempo fixo da questão.")
        options = values.get("options") or []
        if question_type in {"SINGLE_SELECT", "MULTI_SELECT"} and len(options) < 2:
            raise ValidationError("Questões de seleção exigem ao menos duas opções.")
        return question_type, security_level, timer_mode, difficulty

    async def _validated_condition(
        self,
        guild_id: int,
        condition: object,
        *,
        current_stable_key: str | None = None,
    ) -> dict[str, object] | None:
        if condition in (None, {}):
            return None
        if not isinstance(condition, Mapping):
            raise ValidationError("Condição de questão inválida.")
        if set(condition) != {"question", "equals"}:
            raise ValidationError("A condição aceita somente question e equals.")
        dependency = str(condition["question"]).strip().upper()
        if not re.fullmatch(r"[A-Z0-9_]{2,50}", dependency):
            raise ValidationError("Identificador da questão dependente inválido.")
        if current_stable_key and dependency == current_stable_key:
            raise ValidationError("Uma questão não pode depender dela mesma.")
        value = condition["equals"]
        if isinstance(value, list | dict) or value is None:
            raise ValidationError("Valor condicional deve ser texto, número ou booleano.")
        if not await self.database.fetchone(
            "SELECT 1 FROM recruitment_questions WHERE guild_id=? AND stable_key=?",
            (guild_id, dependency),
        ):
            raise ValidationError("Questão dependente não encontrada.")
        return {"question": dependency, "equals": value}

    @block_source_cutover_writes("Recrutamento")
    async def create_question(
        self, guild_id: int, actor_id: int, values: Mapping[str, object]
    ) -> dict[str, object]:
        question_type, security_level, timer_mode, difficulty = self._validate_question_values(values)
        stable_key = str(values["stable_key"]).strip().upper()
        if not re.fullmatch(r"[A-Z0-9_]{2,50}", stable_key):
            raise ValidationError("Identificador deve usar apenas A-Z, 0-9 e underscore.")
        group_id = int(values["group_id"])
        group = await self.database.fetchone(
            "SELECT 1 FROM recruitment_question_groups WHERE guild_id=? AND id=?",
            (guild_id, group_id),
        )
        if not group:
            raise ValidationError("Grupo de questão inválido.")
        condition = await self._validated_condition(guild_id, values.get("condition"))
        now = self.clock()
        try:
            async with self.database.transaction() as connection:
                cursor = await connection.execute(
                    """
                    INSERT INTO recruitment_questions(
                        guild_id, stable_key, group_id, title, description, question_type,
                        required, position, enabled, min_length, max_length,
                        expected_min_length, expected_max_length, security_level,
                        timer_enabled, timer_mode, fixed_time_seconds, allow_back,
                        shuffle_position, difficulty, options_json, condition_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        stable_key,
                        group_id,
                        str(values["title"]).strip(),
                        values.get("description"),
                        question_type,
                        int(bool(values["required"])),
                        int(values["position"]),
                        int(bool(values["enabled"])),
                        values.get("min_length"),
                        values.get("max_length"),
                        values.get("expected_min_length"),
                        values.get("expected_max_length"),
                        security_level,
                        int(bool(values["timer_enabled"])),
                        timer_mode,
                        values.get("fixed_time_seconds"),
                        int(bool(values["allow_back"])),
                        int(bool(values["shuffle_position"])),
                        difficulty,
                        json.dumps(values.get("options", []), ensure_ascii=False),
                        json.dumps(condition, ensure_ascii=False)
                        if condition
                        else None,
                        now,
                        now,
                    ),
                )
                question_id = int(cursor.lastrowid)
                await self.audit.record(
                    guild_id,
                    "RECRUITMENT_QUESTION_CREATED",
                    actor_id=actor_id,
                    after={"question_id": question_id, "stable_key": stable_key},
                    connection=connection,
                )
        except aiosqlite.IntegrityError as exc:
            raise ConflictError("Já existe uma questão com esse identificador.") from exc
        return dict(
            await self.database.fetchone(
                "SELECT * FROM recruitment_questions WHERE id=?", (question_id,)
            )
        )

    @block_source_cutover_writes("Recrutamento")
    async def update_group(
        self, guild_id: int, group_id: int, actor_id: int, values: Mapping[str, object]
    ) -> dict[str, object]:
        count = int(values["questions_per_application"])
        if count < 0 or count > 100:
            raise ValidationError("Quantidade por candidatura inválida.")
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM recruitment_question_groups WHERE guild_id=? AND id=?",
                (guild_id, group_id),
            )
            before = await cursor.fetchone()
            if not before:
                raise NotFoundError("Grupo de questões não encontrado.")
            await connection.execute(
                """
                UPDATE recruitment_question_groups
                SET name=?, position=?, questions_per_application=?, active=?
                WHERE guild_id=? AND id=?
                """,
                (
                    str(values["name"]).strip(),
                    int(values["position"]),
                    count,
                    int(bool(values["active"])),
                    guild_id,
                    group_id,
                ),
            )
            await self.audit.record(
                guild_id,
                "RECRUITMENT_QUESTION_GROUP_UPDATED",
                actor_id=actor_id,
                before=dict(before),
                after=dict(values),
                connection=connection,
            )
        return dict(
            await self.database.fetchone(
                "SELECT * FROM recruitment_question_groups WHERE id=?", (group_id,)
            )
        )

    @block_source_cutover_writes("Recrutamento")
    async def update_question(
        self, guild_id: int, question_id: int, actor_id: int, values: Mapping[str, object]
    ) -> dict[str, object]:
        question_type, security_level, timer_mode, difficulty = self._validate_question_values(values)
        group_id = int(values["group_id"])
        if not await self.database.fetchone(
            "SELECT 1 FROM recruitment_question_groups WHERE guild_id=? AND id=?",
            (guild_id, group_id),
        ):
            raise ValidationError("Grupo de questão inválido.")
        existing = await self.database.fetchone(
            "SELECT stable_key FROM recruitment_questions WHERE guild_id=? AND id=?",
            (guild_id, question_id),
        )
        if not existing:
            raise NotFoundError("Questão não encontrada.")
        condition = await self._validated_condition(
            guild_id,
            values.get("condition"),
            current_stable_key=str(existing["stable_key"]),
        )
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM recruitment_questions WHERE guild_id=? AND id=?",
                (guild_id, question_id),
            )
            before = await cursor.fetchone()
            if not before:
                raise NotFoundError("Questão não encontrada.")
            await connection.execute(
                """
                UPDATE recruitment_questions SET group_id=?, title=?, description=?,
                    question_type=?, required=?, position=?, enabled=?,
                    min_length=?, max_length=?, expected_min_length=?, expected_max_length=?,
                    security_level=?, timer_enabled=?, timer_mode=?, fixed_time_seconds=?,
                    allow_back=?, shuffle_position=?, difficulty=?, options_json=?,
                    condition_json=?, updated_at=?
                WHERE guild_id=? AND id=?
                """,
                (
                    group_id, str(values["title"]).strip(), values.get("description"),
                    question_type, int(bool(values["required"])), int(values["position"]),
                    int(bool(values["enabled"])), values.get("min_length"), values.get("max_length"),
                    values.get("expected_min_length"), values.get("expected_max_length"),
                    security_level, int(bool(values["timer_enabled"])),
                    timer_mode, values.get("fixed_time_seconds"),
                    int(bool(values["allow_back"])), int(bool(values["shuffle_position"])),
                    difficulty, json.dumps(values.get("options", []), ensure_ascii=False),
                    json.dumps(condition, ensure_ascii=False)
                    if condition
                    else None,
                    now, guild_id, question_id,
                ),
            )
            await self.audit.record(
                guild_id, "RECRUITMENT_QUESTION_UPDATED", actor_id=actor_id,
                before=dict(before), after=dict(values), connection=connection,
            )
        return dict(await self.database.fetchone("SELECT * FROM recruitment_questions WHERE id=?", (question_id,)))

    @block_source_cutover_writes("Recrutamento")
    async def publish_form(self, guild_id: int, actor_id: int) -> int:
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT g.id, g.name, g.questions_per_application,
                       SUM(CASE WHEN q.enabled=1 THEN 1 ELSE 0 END) AS enabled_count
                FROM recruitment_question_groups g
                LEFT JOIN recruitment_questions q ON q.group_id=g.id
                WHERE g.guild_id=? AND g.active=1
                GROUP BY g.id ORDER BY g.position
                """,
                (guild_id,),
            )
            groups = await cursor.fetchall()
            if not groups:
                raise ValidationError("O formulário precisa de ao menos um grupo ativo.")
            for group in groups:
                available = int(group["enabled_count"] or 0)
                requested = int(group["questions_per_application"])
                if requested < 1 or requested > available:
                    raise ValidationError(
                        f"O grupo {group['name']} solicita {requested} questão(ões), mas possui {available} ativa(s)."
                    )
            cursor = await connection.execute(
                "SELECT COALESCE(MAX(version_number),0)+1 AS next FROM recruitment_form_versions WHERE guild_id=?",
                (guild_id,),
            )
            number = int((await cursor.fetchone())["next"])
            cursor = await connection.execute(
                """
                INSERT INTO recruitment_form_versions(
                    guild_id, version_number, status, settings_json, created_at,
                    created_by, published_at, published_by
                ) VALUES (?, ?, 'PUBLISHED', '{}', ?, ?, ?, ?)
                """,
                (guild_id, number, now, actor_id, now, actor_id),
            )
            version_id = int(cursor.lastrowid)
            questions = await connection.execute(
                """
                SELECT q.*, g.code AS group_code, g.name AS group_name,
                       g.position AS group_position,
                       g.questions_per_application, g.active AS group_active
                FROM recruitment_questions q
                JOIN recruitment_question_groups g ON g.id=q.group_id
                WHERE q.guild_id=? ORDER BY g.position, q.position
                """,
                (guild_id,),
            )
            for row in await questions.fetchall():
                await connection.execute(
                    """
                    INSERT INTO recruitment_form_version_questions(
                        form_version_id, question_id, position, snapshot_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (version_id, row["id"], row["position"], json.dumps(dict(row), ensure_ascii=False)),
                )
            await connection.execute(
                "UPDATE recruitment_campaigns SET form_version_id=?, updated_at=? WHERE guild_id=? AND status!='ARCHIVED'",
                (version_id, now, guild_id),
            )
            await self.audit.record(
                guild_id, "RECRUITMENT_FORM_PUBLISHED", actor_id=actor_id,
                after={"form_version_id": version_id, "version_number": number}, connection=connection,
            )
        return version_id

    async def _owned_application(self, guild_id: int, discord_id: int, application_id: int):
        row = await self.database.fetchone(
            "SELECT * FROM recruitment_applications WHERE id=? AND guild_id=? AND discord_id=?",
            (application_id, guild_id, discord_id),
        )
        if not row:
            raise NotFoundError("Candidatura não encontrada.")
        if row["status"] != "DRAFT":
            raise ConflictError("A avaliação desta candidatura não está mais editável.")
        return row

    async def _application_for_update(
        self, connection: aiosqlite.Connection, guild_id: int, application_id: int, expected_version: int
    ):
        cursor = await connection.execute(
            "SELECT * FROM recruitment_applications WHERE guild_id=? AND id=?",
            (guild_id, application_id),
        )
        row = await cursor.fetchone()
        if not row:
            raise NotFoundError("Candidatura não encontrada.")
        if int(row["version"]) != expected_version:
            raise ConflictError("Esta candidatura foi atualizada por outro usuário.")
        return row

    async def _transition(
        self,
        guild_id: int,
        application_id: int,
        actor_id: int,
        expected_version: int,
        *,
        allowed: set[str],
        target: str,
        action: str,
        assignments: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        now = self.clock()
        assignments = assignments or {}
        async with self.database.transaction() as connection:
            application = await self._application_for_update(connection, guild_id, application_id, expected_version)
            self._prevent_self_review(application, actor_id)
            if application["status"] not in allowed:
                raise ConflictError("Transição de candidatura inválida.")
            cursor = await connection.execute(
                """
                UPDATE recruitment_applications
                SET status=?, assigned_to=COALESCE(?,assigned_to),
                    assigned_at=COALESCE(?,assigned_at), updated_at=?, version=version+1
                WHERE id=? AND version=? AND status=?
                """,
                (target, assignments.get("assigned_to"), assignments.get("assigned_at"), now, application_id, expected_version, application["status"]),
            )
            if cursor.rowcount != 1:
                raise ConflictError("A candidatura foi atualizada simultaneamente.")
            await self._history(connection, guild_id, application_id, action, actor_id, None, {})
            await connection.execute(
                """
                INSERT INTO recruitment_reviews(
                    guild_id, application_id, reviewer_id, action, from_status,
                    to_status, application_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, application_id, actor_id, action, application["status"], target, expected_version + 1, now),
            )
            await self.audit.record(
                guild_id,
                f"RECRUITMENT_{action}",
                actor_id=actor_id,
                target_id=int(application["discord_id"]),
                before={"status": application["status"]},
                after={"status": target},
                connection=connection,
            )
            await self._public_status_notification(
                connection,
                guild_id,
                application_id,
                target,
                now,
            )
            await self._review_card_notification(
                connection,
                guild_id,
                application_id,
                target,
                expected_version + 1,
                now,
            )
        return dict(await self.database.fetchone("SELECT * FROM recruitment_applications WHERE id=?", (application_id,)))

    async def _set_application_status(
        self,
        connection: aiosqlite.Connection,
        application: Mapping[str, object],
        target: str,
        actor_id: int,
        event: str,
        now: int,
    ) -> None:
        cursor = await connection.execute(
            """
            UPDATE recruitment_applications SET status=?, updated_at=?, version=version+1
            WHERE id=? AND version=? AND status=?
            """,
            (target, now, application["id"], application["version"], application["status"]),
        )
        if cursor.rowcount != 1:
            raise ConflictError("A candidatura foi atualizada simultaneamente.")
        await self._history(connection, int(application["guild_id"]), int(application["id"]), event, actor_id, None, {})
        await self._review_card_notification(
            connection,
            int(application["guild_id"]),
            int(application["id"]),
            target,
            int(application["version"]) + 1,
            now,
        )

    async def _history(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        application_id: int,
        event_type: str,
        actor_id: int | None,
        public_message: str | None,
        metadata: Mapping[str, object],
    ) -> None:
        await connection.execute(
            """
            INSERT INTO recruitment_history(
                guild_id, application_id, event_type, actor_id,
                public_message, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, application_id, event_type, actor_id, public_message, json.dumps(metadata, ensure_ascii=False), self.clock()),
        )

    async def _integrity(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        application_id: int,
        application_question_id: int,
        event_type: str,
        occurred_at: int,
        *,
        duration_ms: int | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO recruitment_integrity_events(
                guild_id, application_id, application_question_id,
                event_type, occurred_at, duration_ms, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                application_id,
                application_question_id,
                event_type,
                occurred_at,
                duration_ms,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )

    async def _notification(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        application_id: int,
        event_type: str,
        event_key: str,
        payload: Mapping[str, object],
        now: int,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO recruitment_notification_outbox(
                guild_id, application_id, event_type, event_key,
                payload_json, available_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, event_key) DO NOTHING
            """,
            (guild_id, application_id, event_type, event_key, json.dumps(payload, ensure_ascii=False), now, now),
        )

    async def _public_status_notification(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        application_id: int,
        status: str,
        now: int,
        *,
        extra_key: str | None = None,
    ) -> None:
        suffix = f":{extra_key}" if extra_key else ""
        await self._notification(
            connection,
            guild_id,
            application_id,
            "RECRUITMENT_PUBLIC_STATUS",
            f"application-public-status:{application_id}:{status}{suffix}",
            {"application_id": application_id, "status": status},
            now,
        )

    async def _review_card_notification(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        application_id: int,
        status: str,
        version: int,
        now: int,
    ) -> None:
        """Request an in-place refresh of the one private Discord review card."""
        await self._notification(
            connection,
            guild_id,
            application_id,
            "RECRUITMENT_REVIEW_CARD_REFRESH",
            f"application-review-card:{application_id}:v{version}",
            {"application_id": application_id, "status": status, "version": version},
            now,
        )

    @staticmethod
    def _prevent_self_review(application: Mapping[str, object], actor_id: int) -> None:
        if int(application["discord_id"]) == actor_id:
            raise PermissionDenied("Você não pode analisar ou decidir a própria candidatura.")
