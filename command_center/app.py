from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from choque.errors import (
    ChoqueError,
    ConflictError,
    NotFoundError,
    PermissionDenied,
    ValidationError,
)
from choque.identity_queue import (
    enqueue_identity_reconciliation as _enqueue_identity_reconciliation,
)
from choque.models import PersonnelActionType, RbacProfile
from choque.rbac import ALL_KNOWN_PERMISSIONS
from choque.time_utils import utc_now_ms

from .rate_limit import SlidingWindowRateLimiter
from .security import (
    CandidateIdentity,
    InternalCaller,
    WebActor,
    authenticate_candidate_request,
    authenticate_internal_request,
    authenticate_request,
    require_permission,
)
from .services import CommandCenterServices

LOGGER = logging.getLogger(__name__)
MAX_REQUEST_BODY_BYTES = 256 * 1024


def plain(value: Any) -> Any:
    if hasattr(value, "keys"):
        return {key: plain(value[key]) for key in value.keys()}
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    return value


def _job_with_observability(value: Any, *, observed_at: int) -> dict[str, object]:
    payload = plain(value) if value is not None else {}
    if not isinstance(payload, dict):
        payload = {}
    started_at = int(payload.get("started_at") or 0)
    completed_at = int(payload.get("completed_at") or 0)
    duration_ms: int | None = None
    if started_at > 0:
        finished_at = completed_at if completed_at >= started_at else observed_at
        duration_ms = max(0, finished_at - started_at)
    payload["duration_ms"] = duration_ms
    return payload


def _identity_event_payload(value: Any) -> dict[str, object]:
    row = plain(value) if value is not None else {}
    if not isinstance(row, dict):
        row = {}
    raw_actor_id = row.get("actor_id")
    actor_id = int(raw_actor_id) if raw_actor_id not in (None, 0, "0", "") else None
    correlation_id = str(row.get("correlation_id") or "").strip() or None
    return {
        "id": int(row.get("id") or 0),
        "event_type": str(row.get("event_type") or "IDENTITY_EVENT"),
        "source": str(row.get("source") or "UNKNOWN_SOURCE"),
        "actor": {
            "kind": "DISCORD_ACTOR" if actor_id is not None else "UNKNOWN_DISCORD_ACTOR",
            "discord_id": actor_id,
        },
        "correlation_id": correlation_id,
        "authorization_version": int(row.get("authorization_version") or 1),
        "created_at": int(row.get("created_at") or 0),
    }


def validate_security_configuration() -> None:
    if os.getenv("APP_ENV") != "production":
        return
    secret = os.getenv("COMMAND_CENTER_INTERNAL_SECRET", "")
    audit_salt = os.getenv("WEB_AUDIT_HASH_SALT", "")
    recruitment_secret = os.getenv("RECRUITMENT_TOKEN_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("COMMAND_CENTER_INTERNAL_SECRET deve possuir ao menos 32 caracteres.")
    if len(audit_salt) < 32 or hmac_compare(secret, audit_salt):
        raise RuntimeError("WEB_AUDIT_HASH_SALT deve ser forte e distinto do segredo interno.")
    if len(recruitment_secret) < 32 or hmac_compare(secret, recruitment_secret):
        raise RuntimeError("RECRUITMENT_TOKEN_SECRET deve ser forte e distinto do segredo interno.")
    origins = _allowed_origins()
    if not origins or any(not item.startswith("https://") or "*" in item for item in origins):
        raise RuntimeError("WEB_ALLOWED_ORIGINS deve conter somente origens HTTPS explícitas.")
    hosts = [item.strip() for item in os.getenv("WEB_ALLOWED_HOSTS", "").split(",") if item.strip()]
    if not hosts or any(item in {"*", "localhost", "127.0.0.1"} for item in hosts):
        raise RuntimeError("WEB_ALLOWED_HOSTS deve conter hosts de produção explícitos.")
    forbidden_flags = (
        "COMMAND_CENTER_ALLOW_LEGACY_AUTH",
        "RECRUITMENT_SKIP_GUILD_MEMBERSHIP_CHECK",
        "WEB_DEV_DISCORD_ID",
    )
    if any(os.getenv(key, "").lower() in {"1", "true", "yes"} for key in forbidden_flags):
        raise RuntimeError("Bypass de desenvolvimento não pode ser ativado em produção.")


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_configuration()
    database_path = Path(os.getenv("DATABASE_PATH", "data/choque_bgr.db"))
    app.state.services = await CommandCenterServices.open(database_path)
    try:
        yield
    finally:
        await app.state.services.close()


app = FastAPI(
    title="CHOQUE - BGR • Command Center API",
    version="1.0.0",
    docs_url=None if os.getenv("APP_ENV") == "production" else "/docs",
    redoc_url=None,
    lifespan=lifespan,
)
rate_limiter = SlidingWindowRateLimiter()


def _allowed_origins() -> list[str]:
    return [
        item.strip()
        for item in os.getenv("WEB_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        if item.strip()
    ]


def _apply_security_headers(response: JSONResponse, request_id: str) -> JSONResponse:
    response.headers["X-Correlation-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    response.headers["Cache-Control"] = "no-store"
    if os.getenv("APP_ENV") == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.middleware("http")
async def security_envelope(request: Request, call_next):
    request_id = (request.headers.get("x-correlation-id") or str(uuid.uuid4()))[:100]
    request.state.correlation_id = request_id
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_REQUEST_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": "Payload excede o limite permitido.", "error_id": request_id},
            headers={"X-Correlation-ID": request_id},
        )
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        body = await request.body()
        if len(body) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Payload excede o limite permitido.", "error_id": request_id},
                headers={"X-Correlation-ID": request_id},
            )
        origin = request.headers.get("origin")
        if origin and origin not in _allowed_origins():
            return JSONResponse(
                status_code=403,
                content={"detail": "Origem não autorizada.", "error_id": request_id},
                headers={"X-Correlation-ID": request_id},
            )
    response = await call_next(request)
    _apply_security_headers(response, request_id)
    if response.status_code == 403 and getattr(request.state, "actor", None):
        actor = request.state.actor
        try:
            await request.app.state.services.security.record(
                actor.guild_id,
                "SECURITY_PERMISSION_DENIED",
                severity="MEDIUM",
                result="DENIED",
                source="API",
                actor_id=actor.discord_id,
                route=request.url.path,
                request_id=request_id,
            )
        except Exception:
            LOGGER.warning("Falha ao registrar negação de permissão", exc_info=True)
    return response


@app.middleware("http")
async def recruitment_rate_limit(request: Request, call_next):
    identity = request.headers.get("X-Actor-Discord-ID")
    if not identity:
        identity = "anonymous"
    client_host = request.client.host if request.client else "unknown"
    identity = f"{client_host}:{identity}"
    result = await rate_limiter.check(identity, request.url.path)
    if result and not result[0]:
        guild_value = request.headers.get("X-Guild-ID", "0")
        if guild_value.isdigit() and hasattr(request.app.state, "services"):
            try:
                await request.app.state.services.security.record(
                    int(guild_value),
                    "SECURITY_RATE_LIMIT",
                    severity="MEDIUM",
                    result="BLOCKED",
                    source="API",
                    route=request.url.path,
                    request_id=request.headers.get("X-Correlation-ID") or str(uuid.uuid4()),
                )
            except Exception:
                LOGGER.warning("Falha ao registrar rate limit", exc_info=True)
        return JSONResponse(
            status_code=429,
            content={"detail": "Muitas tentativas. Aguarde antes de tentar novamente."},
            headers={"Retry-After": str(result[2])},
        )
    response = await call_next(request)
    if result:
        response.headers["X-RateLimit-Remaining"] = str(result[1])
    return response


origins = _allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=[
        "Content-Type",
        "X-Internal-Secret",
        "X-Request-Signature",
        "X-Request-Timestamp",
        "X-Request-Nonce",
        "X-Session-Issued-At",
        "X-Discord-Guild-Verified",
        "X-Actor-Discord-ID",
        "X-Guild-ID",
        "X-Correlation-ID",
        "X-Discord-Username",
        "X-Discord-Global-Name",
        "X-Discord-Avatar",
    ],
)
allowed_hosts = [
    item.strip()
    for item in os.getenv("WEB_ALLOWED_HOSTS", "testserver,localhost,127.0.0.1").split(",")
    if item.strip()
]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


@app.middleware("http")
async def platform_healthcheck(request: Request, call_next):
    if request.method == "GET" and request.scope.get("path") == "/health":
        request_id = (request.headers.get("x-correlation-id") or str(uuid.uuid4()))[:100]
        return _apply_security_headers(JSONResponse({"status": "ok"}), request_id)
    return await call_next(request)

Actor = Annotated[WebActor, Depends(authenticate_request)]
Candidate = Annotated[CandidateIdentity, Depends(authenticate_candidate_request)]
Internal = Annotated[InternalCaller, Depends(authenticate_internal_request)]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DecisionBody(StrictBody):
    approved: bool
    reason: str = Field(min_length=3, max_length=500)


class RankChangeBody(StrictBody):
    target_rank_id: int
    action: str
    reason: str = Field(min_length=3, max_length=500)


class MaintenanceBody(StrictBody):
    active: bool
    reason: str | None = Field(default=None, max_length=500)
    expected_end_at: int | None = None


class GeneralSettingBody(StrictBody):
    key: str
    value: str | int | bool | list[str]


class ChannelSettingBody(StrictBody):
    key: str
    resource_id: int


class RegistrationGateDecisionBody(StrictBody):
    action: str = Field(min_length=4, max_length=30)
    reason: str = Field(min_length=3, max_length=500)
    bgr_id: str | None = Field(default=None, min_length=1, max_length=32)
    member_id: int | None = Field(default=None, ge=1)


class RegistrationGateConfigurationBody(StrictBody):
    registration_gate_enabled: bool | None = None
    unregistered_role_id: int | None = Field(default=None, ge=1)
    candidate_role_id: int | None = Field(default=None, ge=1)
    member_role_id: int | None = Field(default=None, ge=1)
    registration_onboarding_category_id: int | None = Field(default=None, ge=1)
    registration_panel_channel_id: int | None = Field(default=None, ge=1)
    registration_support_channel_id: int | None = Field(default=None, ge=1)
    registration_onboarding_channel_ids: list[int] | None = None
    registration_bypass_role_ids: list[int] | None = None
    registration_bypass_user_ids: list[int] | None = None
    registration_dm_enabled: bool | None = None


class TicketConfigurationBody(StrictBody):
    ticket_active_category_id: int | None = Field(default=None, ge=1)
    ticket_archive_category_id: int | None = Field(default=None, ge=1)
    ticket_responsible_role_id: int | None = Field(default=None, ge=1)
    ticket_transcript_channel_id: int | None = Field(default=None, ge=1)
    ticket_requester_notify_cooldown_seconds: int | None = Field(default=None, ge=30, le=3600)


class RankSettingBody(StrictBody):
    name: str = Field(min_length=2, max_length=60)
    prefix: str = Field(max_length=20)
    level: int = Field(ge=0, le=999)
    discord_role_id: int | None = None
    rbac_profile: str
    active: bool = True


class VoiceChannelBody(StrictBody):
    channel_id: int
    label: str | None = Field(default=None, max_length=100)
    counts_toward_patrol_minimum: bool = True


class RbacBindingBody(StrictBody):
    role_id: int
    profile: str


class DiscordRoleMappingBody(StrictBody):
    discord_role_id: int = Field(gt=0)
    mapping_type: str = Field(min_length=4, max_length=30)
    internal_code: str = Field(min_length=2, max_length=80)
    display_name: str = Field(min_length=2, max_length=100)
    priority: int = Field(default=0, ge=-10_000, le=10_000)
    rank_id: int | None = Field(default=None, gt=0)
    position_id: int | None = Field(default=None, gt=0)
    access_profile_id: int | None = Field(default=None, gt=0)
    is_primary_position_candidate: bool = False
    enabled: bool = True


class DiscordPermissionRuleBody(StrictBody):
    subject_type: str = Field(min_length=4, max_length=20)
    subject_id: int = Field(gt=0)
    permission: str = Field(min_length=1, max_length=100)
    effect: str = Field(min_length=4, max_length=5)
    reason: str | None = Field(default=None, max_length=500)


class IdentityReconciliationApplyBody(StrictBody):
    preview_job_id: int = Field(gt=0)


class RecruitmentStartBody(StrictBody):
    candidate_nick: str = Field(min_length=2, max_length=80)
    bgr_id: str = Field(min_length=1, max_length=40)
    age: int = Field(ge=13, le=100)
    consent_accepted: bool
    idempotency_key: str = Field(min_length=12, max_length=100)


class RecruitmentQuestionBody(StrictBody):
    answer: Any
    question_token: str = Field(min_length=32, max_length=300)


class RecruitmentIntegrityBody(StrictBody):
    event_type: str = Field(min_length=3, max_length=60)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class RecruitmentSubmitBody(StrictBody):
    expected_version: int = Field(ge=1)


class RecruitmentAssignBody(RecruitmentSubmitBody):
    pass


class RecruitmentInterviewBody(RecruitmentSubmitBody):
    scheduled_at: int
    interviewer_id: int
    notes: str | None = Field(default=None, max_length=1000)


class RecruitmentEvaluationBody(RecruitmentSubmitBody):
    interview_id: int
    communication: str
    posture: str
    knowledge: str
    discipline: str
    result: str
    observation: str | None = Field(default=None, max_length=2000)


class RecruitmentDecisionBody(RecruitmentSubmitBody):
    internal_reason: str = Field(min_length=3, max_length=2000)
    candidate_message: str = Field(min_length=3, max_length=2000)


class RecruitmentNoteBody(StrictBody):
    note: str = Field(min_length=3, max_length=4000)


class RecruitmentBlockBody(StrictBody):
    discord_id: int | None = Field(default=None, gt=0)
    bgr_id: str | None = Field(default=None, max_length=40)
    reason: str = Field(min_length=3, max_length=2000)


class RecruitmentAdaptationBody(StrictBody):
    extra_time_percent: int = Field(default=0, ge=0, le=200)
    clipboard_adapted: bool = False
    alternative_format: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=3, max_length=2000)


class RecruitmentCampaignBody(StrictBody):
    name: str = Field(min_length=3, max_length=150)
    status: str
    opens_at: int | None = None
    closes_at: int | None = None
    cooldown_days: int = Field(ge=0, le=365)
    minimum_age: int = Field(ge=13, le=100)
    maximum_applications: int | None = Field(default=None, ge=1)
    initial_rank_id: int | None = None
    candidate_role_id: int | None = None
    interview_channel_id: int | None = None


class RecruitmentQuestionAdminBody(StrictBody):
    group_id: int = Field(gt=0)
    title: str = Field(min_length=3, max_length=1000)
    description: str | None = Field(default=None, max_length=2000)
    question_type: str
    required: bool = True
    position: int = Field(ge=1, le=10_000)
    enabled: bool = True
    min_length: int | None = Field(default=None, ge=0, le=10_000)
    max_length: int | None = Field(default=None, ge=1, le=10_000)
    expected_min_length: int | None = Field(default=None, ge=0, le=10_000)
    expected_max_length: int | None = Field(default=None, ge=1, le=10_000)
    security_level: str
    timer_enabled: bool
    timer_mode: str
    fixed_time_seconds: int | None = Field(default=None, ge=30, le=3600)
    allow_back: bool
    shuffle_position: bool
    difficulty: str
    options: list[str] = Field(default_factory=list, max_length=50)
    condition: dict[str, Any] | None = None


class RecruitmentQuestionCreateBody(RecruitmentQuestionAdminBody):
    stable_key: str = Field(min_length=2, max_length=50)


class RecruitmentQuestionGroupBody(StrictBody):
    name: str = Field(min_length=2, max_length=100)
    position: int = Field(ge=1, le=1000)
    questions_per_application: int = Field(ge=0, le=100)
    active: bool = True


class RecruitmentAiConfigurationBody(StrictBody):
    enabled: bool
    auto_analyze: bool
    analyze_integrity: bool
    generate_interview_questions: bool
    generate_summary: bool
    final_assisted_after_interview: bool
    discord_notice: bool
    show_score: bool


class RecruitmentAiReanalysisBody(StrictBody):
    analysis_type: str = "PRE_INTERVIEW"


class RecruitmentAiFeedbackBody(StrictBody):
    usefulness: str
    note: str | None = Field(default=None, max_length=1000)


class RecruitmentAiRubricCriterionBody(StrictBody):
    code: str = Field(min_length=2, max_length=50)
    label: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=5, max_length=1000)
    weight: int = Field(ge=1, le=100)


class RecruitmentAiRubricBody(StrictBody):
    criteria: list[RecruitmentAiRubricCriterionBody] = Field(min_length=1, max_length=25)
    review_min: int = Field(default=65, ge=0, le=99)
    recommended_min: int = Field(default=85, ge=1, le=100)
    show_score: bool = True


class RecruitmentAiContextBody(StrictBody):
    principles: list[str] = Field(min_length=1, max_length=50)
    prohibitions: list[str] = Field(min_length=1, max_length=50)


class SecurityLockdownBody(StrictBody):
    active: bool
    reason: str = Field(min_length=10, max_length=500)
    confirmation: str = Field(min_length=7, max_length=10)


class SecuritySessionRevocationBody(StrictBody):
    discord_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=10, max_length=500)
    confirmation: str = Field(min_length=7, max_length=20)


@app.exception_handler(ChoqueError)
async def domain_error_handler(_: Request, exc: ChoqueError) -> JSONResponse:
    status_code = 409
    if isinstance(exc, ValidationError):
        status_code = 422
    elif isinstance(exc, PermissionDenied):
        status_code = 403
    elif isinstance(exc, NotFoundError):
        status_code = 404
    elif isinstance(exc, ConflictError):
        status_code = 409
    return JSONResponse(
        status_code=status_code,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    LOGGER.exception("Erro não tratado na API", exc_info=exc, extra={"correlation_id": error_id})
    return JSONResponse(
        status_code=500,
        content={"detail": "Falha ao processar a operação.", "error_id": error_id},
        headers={"X-Correlation-ID": error_id},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _public_function(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": value.get("id"),
        "code": value.get("code"),
        "name": value.get("name"),
        "priority": value.get("priority"),
        "is_primary": bool(value.get("is_primary")),
    }


async def _member_identity_projection(
    request: Request,
    guild_id: int,
    *,
    member_id: int | None = None,
    discord_id: int | None = None,
) -> dict[str, object] | None:
    if member_id is None and discord_id is None:
        raise ValueError("member_id ou discord_id é obrigatório")
    selector = "m.id=?" if member_id is not None else "m.discord_id=?"
    selector_value = member_id if member_id is not None else discord_id
    row = await request.app.state.services.database.fetchone(
        f"""
        SELECT m.id, m.discord_id, m.mta_nick, m.character_id, m.status,
               m.rank_id, r.name AS rank_name, r.prefix AS rank_prefix,
               m.primary_position_id, fp.code AS primary_position_code,
               fp.name AS primary_position_name,
               m.access_profile_id, ap.code AS access_profile_code,
               ap.name AS access_profile_name,
               m.discord_roles_synced_at, m.authorization_version,
               m.identity_sync_status, m.discord_present
        FROM members m
        LEFT JOIN ranks r ON r.id=m.rank_id
        LEFT JOIN functional_positions fp ON fp.id=m.primary_position_id
        LEFT JOIN access_profiles ap ON ap.id=m.access_profile_id
        WHERE m.guild_id=? AND {selector}
        """,
        (guild_id, selector_value),
    )
    if not row:
        return None
    functions = await request.app.state.services.database.fetchall(
        """
        SELECT fp.id, fp.code, fp.name, fp.priority, mp.is_primary
        FROM member_positions mp
        JOIN functional_positions fp ON fp.id=mp.position_id
        WHERE mp.member_id=? AND fp.enabled=1
        ORDER BY mp.is_primary DESC, fp.priority DESC, fp.id
        """,
        (row["id"],),
    )
    rank = (
        {
            "id": int(row["rank_id"]),
            "name": row["rank_name"],
            "prefix": row["rank_prefix"],
        }
        if row["rank_id"] is not None
        else None
    )
    primary_position = (
        {
            "id": int(row["primary_position_id"]),
            "code": row["primary_position_code"],
            "name": row["primary_position_name"],
        }
        if row["primary_position_id"] is not None
        else None
    )
    access_profile = (
        {
            "id": int(row["access_profile_id"]),
            "code": row["access_profile_code"],
            "name": row["access_profile_name"],
        }
        if row["access_profile_id"] is not None
        else None
    )
    return {
        "id": int(row["id"]),
        "discord_id": int(row["discord_id"]),
        "mta_nick": row["mta_nick"],
        "character_id": row["character_id"],
        "status": row["status"],
        "rank": rank,
        "rank_name": rank["name"] if rank else None,
        "rank_prefix": rank["prefix"] if rank else None,
        "primary_position": primary_position,
        "primary_position_code": primary_position["code"] if primary_position else None,
        "primary_position_name": primary_position["name"] if primary_position else None,
        "functions": [_public_function(plain(item)) for item in functions],
        "access_profile": access_profile,
        "access_profile_code": access_profile["code"] if access_profile else None,
        "access_profile_name": access_profile["name"] if access_profile else None,
        "discord_synced_at": row["discord_roles_synced_at"],
        "discord_roles_synced_at": row["discord_roles_synced_at"],
        "authorization_version": int(row["authorization_version"] or 1),
        "identity_sync_status": row["identity_sync_status"],
        "discord_present": bool(row["discord_present"]),
    }


@app.get("/v1/security")
async def security_dashboard(request: Request, actor: Actor) -> Any:
    require_permission(actor, "security.manage")
    return plain(await request.app.state.services.security.dashboard(actor.guild_id))


@app.post("/v1/security/lockdown")
async def security_lockdown(
    request: Request,
    body: SecurityLockdownBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "security.manage")
    expected = "BLOQUEAR" if body.active else "LIBERAR"
    if body.confirmation.upper() != expected:
        raise HTTPException(422, f"Digite {expected} para confirmar.")
    return await request.app.state.services.security.set_lockdown(
        actor.guild_id,
        active=body.active,
        reason=body.reason,
        actor_id=actor.discord_id,
        request_id=actor.correlation_id,
    )


@app.post("/v1/security/sessions/revoke")
async def security_revoke_sessions(
    request: Request,
    body: SecuritySessionRevocationBody,
    actor: Actor,
) -> dict[str, str]:
    require_permission(actor, "security.manage")
    expected = "REVOGAR USUARIO" if body.discord_id else "REVOGAR TODAS"
    if body.confirmation.upper() != expected:
        raise HTTPException(422, f"Digite {expected} para confirmar.")
    await request.app.state.services.security.revoke_sessions(
        actor.guild_id,
        actor_id=actor.discord_id,
        reason=body.reason,
        discord_id=body.discord_id,
        request_id=actor.correlation_id,
    )
    return {"status": "REVOKED"}


@app.get("/v1/me")
@app.get("/v1/context")
async def context(request: Request, actor: Actor) -> dict[str, object]:
    member = await _member_identity_projection(
        request, actor.guild_id, member_id=actor.member_id
    )
    if member is None:
        raise HTTPException(404, "Membro não encontrado.")
    # Keep the original flat fields during the web client's transition to the
    # structured identity contract. Authorization is always server-resolved.
    legacy_member = {
        "discord_id": member["discord_id"],
        "mta_nick": member["mta_nick"],
        "character_id": member["character_id"],
        "status": member["status"],
        "rank_name": (member["rank"] or {}).get("name"),
        "rank_prefix": (member["rank"] or {}).get("prefix"),
        **member,
    }
    return {
        "member": legacy_member,
        "access": {
            "profile": actor.profile,
            "profile_name": actor.profile_name,
            "permissions": sorted(actor.permissions),
            "authorization_version": actor.authorization_version,
            "technical_bootstrap": actor.technical_bootstrap,
        },
        "profile": actor.profile,
        "permissions": sorted(actor.permissions),
        "authorization_version": actor.authorization_version,
        "guild_id": actor.guild_id,
    }


@app.get("/v1/dashboard")
async def dashboard(request: Request, actor: Actor) -> dict[str, object]:
    has_all_operations = actor.can("operations.view")
    if not has_all_operations:
        require_permission(actor, "patrol.view.self")
    services = request.app.state.services
    readiness, patrols, queue = await asyncio.gather(
        services.operations.readiness(actor.guild_id),
        services.operations.active_patrols(actor.guild_id),
        services.operations.queue(actor.guild_id),
    )
    if not has_all_operations:
        member_token = str(actor.member_id)
        patrols = [
            patrol
            for patrol in patrols
            if member_token in str(patrol["member_ids"] or "").split(",")
        ]
        queue = [entry for entry in queue if int(entry["member_id"] or 0) == actor.member_id]
        readiness = {"counts": {}, "generated_at": int(time.time() * 1000)}
    inbox = []
    changes: dict[str, object] = {"counts": {}, "events": []}
    if actor.can("admin.inbox.view"):
        inbox = (await services.operations.administrative_inbox(actor.guild_id))[:8]
    if actor.can("changes.view"):
        changes = plain(await services.operations.changes_summary(actor.guild_id))
    return plain(
        {
            "generated_at": int(time.time() * 1000),
            "readiness": readiness,
            "patrols": patrols,
            "queue": queue,
            "inbox": inbox,
            "changes": changes,
            "capabilities": {
                "view_inbox": actor.can("admin.inbox.view"),
                "view_changes": actor.can("changes.view"),
                "view_all_operations": actor.can("operations.view"),
            },
        }
    )


@app.get("/v1/readiness")
async def readiness(request: Request, actor: Actor) -> Any:
    require_permission(actor, "operations.view")
    dashboard_rows, summary = await asyncio.gather(
        request.app.state.services.activity.current_dashboard(actor.guild_id),
        request.app.state.services.operations.readiness(actor.guild_id),
    )
    return plain({"summary": summary, "members": dashboard_rows})


@app.get("/v1/patrols")
async def patrols(request: Request, actor: Actor) -> Any:
    require_permission(actor, "patrol.view.all")
    active, queue = await asyncio.gather(
        request.app.state.services.operations.active_patrols(actor.guild_id),
        request.app.state.services.operations.queue(actor.guild_id),
    )
    return plain({"generated_at": int(time.time() * 1000), "active": active, "queue": queue})


@app.get("/v1/shifts")
async def shifts(
    request: Request,
    actor: Actor,
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    require_permission(actor, "shift.view.all")
    rows = await request.app.state.services.database.fetchall(
        """
        SELECT s.*, m.discord_id, m.mta_nick, r.name AS rank_name
        FROM shifts s JOIN members m ON m.id=s.member_id
        LEFT JOIN ranks r ON r.id=m.rank_id
        WHERE s.guild_id=? ORDER BY s.started_at DESC LIMIT ?
        """,
        (actor.guild_id, limit),
    )
    return plain(rows)


@app.get("/v1/members")
async def members(
    request: Request,
    actor: Actor,
    search: str = Query(default="", max_length=100),
    member_status: str = "",
    limit: int = Query(100, ge=1, le=250),
) -> Any:
    require_permission(actor, "member.view")
    params: list[object] = [actor.guild_id]
    filters = ["m.guild_id=?"]
    if search.strip():
        filters.append(
            "(m.mta_nick LIKE ? OR CAST(m.discord_id AS TEXT) LIKE ? OR m.character_id LIKE ?)"
        )
        term = f"%{search.strip()}%"
        params.extend([term, term, term])
    if member_status.strip():
        filters.append("m.status=?")
        params.append(member_status.strip().upper())
    params.append(limit)
    rows = await request.app.state.services.database.fetchall(
        f"""
        SELECT m.id, m.discord_id, m.mta_nick, m.character_id, m.status,
               m.joined_at, m.last_activity_at, m.rank_sync_status,
               m.authorization_version, m.discord_roles_synced_at,
               m.identity_sync_status, m.discord_present,
               r.name AS rank_name, r.prefix AS rank_prefix, r.level AS rank_level,
               fp.code AS primary_position_code, fp.name AS primary_position_name,
               ap.code AS access_profile, ap.name AS access_profile_name,
               COALESCE((SELECT COUNT(*) FROM patrol_members pm JOIN patrols p ON p.id=pm.patrol_id
                         WHERE pm.member_id=m.id AND p.status='CLOSED'), 0) AS patrols,
               COALESCE((SELECT SUM(s.patrol_duration_ms + COALESCE((SELECT SUM(sa.delta_ms)
                         FROM shift_adjustments sa WHERE sa.shift_id=s.id), 0))
                         FROM shifts s WHERE s.member_id=m.id AND s.validation_status='VALID'), 0)
                         AS valid_hours_ms
        FROM members m
        LEFT JOIN ranks r ON r.id=m.rank_id
        LEFT JOIN functional_positions fp ON fp.id=m.primary_position_id
        LEFT JOIN access_profiles ap ON ap.id=m.access_profile_id
        WHERE {" AND ".join(filters)}
        ORDER BY COALESCE(r.level, -1) DESC, m.mta_nick LIMIT ?
        """,
        tuple(params),
    )
    result = [plain(row) for row in rows]
    member_ids = [int(row["id"]) for row in result]
    positions_by_member: dict[int, list[dict[str, object]]] = {
        member_id: [] for member_id in member_ids
    }
    if member_ids:
        position_rows = await request.app.state.services.database.fetchall(
            f"""
            SELECT mp.member_id, fp.id, fp.code, fp.name, fp.priority, mp.is_primary
            FROM member_positions mp
            JOIN functional_positions fp ON fp.id=mp.position_id
            WHERE mp.member_id IN ({','.join('?' for _ in member_ids)}) AND fp.enabled=1
            ORDER BY mp.member_id, mp.is_primary DESC, fp.priority DESC, fp.id
            """,
            tuple(member_ids),
        )
        for position in position_rows:
            positions_by_member[int(position["member_id"])].append(
                _public_function(plain(position))
            )
    for row in result:
        row["functions"] = positions_by_member[int(row["id"])]
        row["discord_present"] = bool(row["discord_present"])
    return result


@app.get("/v1/members/{discord_id}")
async def member_detail(request: Request, discord_id: int, actor: Actor) -> Any:
    if discord_id != actor.discord_id:
        require_permission(actor, "dossier.view")
    dossier, eligibility, identity = await asyncio.gather(
        request.app.state.services.operations.dossier(actor.guild_id, discord_id),
        request.app.state.services.operations.promotion_eligibility(actor.guild_id, discord_id),
        _member_identity_projection(request, actor.guild_id, discord_id=discord_id),
    )
    if identity is None:
        raise HTTPException(404, "Membro não encontrado.")
    return plain({"dossier": dossier, "eligibility": eligibility, "identity": identity})


@app.post("/v1/members/{discord_id}/rank")
async def change_rank(
    request: Request,
    discord_id: int,
    body: RankChangeBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "career.manage")
    try:
        action = PersonnelActionType(body.action.upper())
    except ValueError as exc:
        raise HTTPException(422, "Ação deve ser PROMOTION ou DEMOTION.") from exc
    result = await request.app.state.services.personnel.change_rank_to(
        actor.guild_id,
        discord_id,
        body.target_rank_id,
        action,
        actor.discord_id,
        body.reason,
        enqueue_discord_sync=True,
    )
    correlation_id = result.pop("sync_correlation_id")
    return plain(
        {
            "result": result,
            "discord_sync": "PENDING",
            "correlation_id": correlation_id,
        }
    )


_PERMISSION_RULE_TABLES: dict[str, tuple[str, str]] = {
    "PROFILE": ("access_profile_permissions", "access_profile_id"),
    "RANK": ("rank_permissions", "rank_id"),
    "POSITION": ("functional_position_permissions", "position_id"),
}
_PERMISSION_SUBJECT_TYPES = frozenset({*_PERMISSION_RULE_TABLES, "MEMBER"})
_PERMISSION_NAME_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*")


def _normalize_permission_subject_type(value: str) -> str:
    subject_type = value.strip().upper()
    if subject_type not in _PERMISSION_SUBJECT_TYPES:
        raise HTTPException(422, "Tipo de sujeito da permissão inválido.")
    return subject_type


def _normalize_permission_name(value: str) -> str:
    permission = value.strip().lower()
    if permission != "*" and not _PERMISSION_NAME_PATTERN.fullmatch(permission):
        raise HTTPException(422, "Nome de permissão inválido.")
    return permission


async def _permission_subject(
    connection,
    *,
    guild_id: int,
    subject_type: str,
    subject_id: int,
):
    if subject_type == "PROFILE":
        sql = "SELECT id, name FROM access_profiles WHERE guild_id=? AND id=?"
    elif subject_type == "RANK":
        sql = "SELECT id, name FROM ranks WHERE guild_id=? AND id=?"
    elif subject_type == "POSITION":
        sql = "SELECT id, name FROM functional_positions WHERE guild_id=? AND id=?"
    else:
        sql = """
            SELECT id, COALESCE(NULLIF(mta_nick, ''), CAST(discord_id AS TEXT)) AS name
            FROM members WHERE guild_id=? AND id=?
        """
    cursor = await connection.execute(sql, (guild_id, subject_id))
    subject = await cursor.fetchone()
    if subject is None:
        raise HTTPException(422, "Sujeito da permissão não pertence a esta guild.")
    return subject


async def _bump_guild_authorization_versions(connection, guild_id: int) -> int:
    cursor = await connection.execute(
        """
        UPDATE members
        SET authorization_version=authorization_version+1
        WHERE guild_id=?
        """,
        (guild_id,),
    )
    return max(0, int(cursor.rowcount))


@app.get("/v1/discord/permissions")
async def discord_permissions(request: Request, actor: Actor) -> Any:
    require_permission(actor, "identity.configure")
    services = request.app.state.services
    await services.permissions.ensure_defaults(actor.guild_id)
    profiles, ranks, positions, members, rules, configured_permissions = await asyncio.gather(
        services.database.fetchall(
            """
            SELECT id, code, name, priority, enabled
            FROM access_profiles
            WHERE guild_id=?
            ORDER BY priority DESC, name, id
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT id, name, prefix, level, active
            FROM ranks
            WHERE guild_id=?
            ORDER BY active DESC, level DESC, name, id
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT id, code, name, priority, enabled
            FROM functional_positions
            WHERE guild_id=?
            ORDER BY enabled DESC, priority DESC, name, id
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT id, discord_id, mta_nick, status
            FROM members
            WHERE guild_id=?
            ORDER BY mta_nick COLLATE NOCASE, id
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT 'PROFILE' AS subject_type, ap.id AS subject_id,
                   ap.name AS subject_name, rule.permission, rule.effect,
                   NULL AS reason, rule.updated_at
            FROM access_profile_permissions rule
            JOIN access_profiles ap ON ap.id=rule.access_profile_id
            WHERE ap.guild_id=?
            UNION ALL
            SELECT 'RANK', r.id, r.name, rule.permission, rule.effect,
                   NULL, rule.updated_at
            FROM rank_permissions rule
            JOIN ranks r ON r.id=rule.rank_id
            WHERE r.guild_id=?
            UNION ALL
            SELECT 'POSITION', fp.id, fp.name, rule.permission, rule.effect,
                   NULL, rule.updated_at
            FROM functional_position_permissions rule
            JOIN functional_positions fp ON fp.id=rule.position_id
            WHERE fp.guild_id=?
            UNION ALL
            SELECT 'MEMBER', m.id,
                   COALESCE(NULLIF(m.mta_nick, ''), CAST(m.discord_id AS TEXT)),
                   rule.permission, rule.effect, rule.reason, rule.updated_at
            FROM member_permission_overrides rule
            JOIN members m ON m.id=rule.member_id
            WHERE m.guild_id=?
            ORDER BY subject_type, subject_name, permission
            """,
            (actor.guild_id, actor.guild_id, actor.guild_id, actor.guild_id),
        ),
        services.database.fetchall(
            """
            SELECT rule.permission
            FROM access_profile_permissions rule
            JOIN access_profiles ap ON ap.id=rule.access_profile_id
            WHERE ap.guild_id=?
            UNION
            SELECT rule.permission
            FROM rank_permissions rule
            JOIN ranks r ON r.id=rule.rank_id
            WHERE r.guild_id=?
            UNION
            SELECT rule.permission
            FROM functional_position_permissions rule
            JOIN functional_positions fp ON fp.id=rule.position_id
            WHERE fp.guild_id=?
            UNION
            SELECT rule.permission
            FROM member_permission_overrides rule
            JOIN members m ON m.id=rule.member_id
            WHERE m.guild_id=?
            """,
            (actor.guild_id, actor.guild_id, actor.guild_id, actor.guild_id),
        ),
    )
    normalized_rules = [plain(row) for row in rules]
    catalog = sorted(
        {
            *ALL_KNOWN_PERMISSIONS,
            *(str(row["permission"]) for row in configured_permissions),
        }
    )
    return {
        "catalog": catalog,
        "profiles": [
            {
                "id": int(row["id"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "priority": int(row["priority"]),
                "enabled": bool(row["enabled"]),
            }
            for row in profiles
        ],
        "ranks": [
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "prefix": str(row["prefix"]),
                "level": int(row["level"]),
                "active": bool(row["active"]),
            }
            for row in ranks
        ],
        "positions": [
            {
                "id": int(row["id"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "priority": int(row["priority"]),
                "enabled": bool(row["enabled"]),
            }
            for row in positions
        ],
        "members": [
            {
                "id": int(row["id"]),
                "discord_id": int(row["discord_id"]),
                "mta_nick": str(row["mta_nick"]),
                "status": str(row["status"]),
            }
            for row in members
        ],
        "rules": normalized_rules,
        "summary": {
            "total": len(normalized_rules),
            "grants": sum(row["effect"] == "GRANT" for row in normalized_rules),
            "denies": sum(row["effect"] == "DENY" for row in normalized_rules),
        },
    }


@app.put("/v1/discord/permissions")
async def upsert_discord_permission_rule(
    request: Request,
    body: DiscordPermissionRuleBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "identity.configure")
    services = request.app.state.services
    subject_type = _normalize_permission_subject_type(body.subject_type)
    permission = _normalize_permission_name(body.permission)
    effect = body.effect.strip().upper()
    if effect not in {"GRANT", "DENY"}:
        raise HTTPException(422, "Efeito deve ser GRANT ou DENY.")
    reason = body.reason.strip() if body.reason else None
    if subject_type == "MEMBER" and (reason is None or len(reason) < 3):
        raise HTTPException(422, "Regras individuais exigem uma razão com ao menos 3 caracteres.")

    now = utc_now_ms()
    async with services.database.transaction() as connection:
        subject = await _permission_subject(
            connection,
            guild_id=actor.guild_id,
            subject_type=subject_type,
            subject_id=body.subject_id,
        )
        if subject_type == "MEMBER":
            cursor = await connection.execute(
                """
                SELECT permission, effect, reason, created_by, created_at, updated_at
                FROM member_permission_overrides
                WHERE member_id=? AND permission=?
                """,
                (body.subject_id, permission),
            )
            before = await cursor.fetchone()
            await connection.execute(
                """
                INSERT INTO member_permission_overrides(
                    member_id, permission, effect, reason, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(member_id, permission) DO UPDATE SET
                    effect=excluded.effect,
                    reason=excluded.reason,
                    created_by=excluded.created_by,
                    updated_at=excluded.updated_at
                """,
                (
                    body.subject_id,
                    permission,
                    effect,
                    reason,
                    actor.discord_id,
                    now,
                    now,
                ),
            )
        else:
            table, foreign_key = _PERMISSION_RULE_TABLES[subject_type]
            cursor = await connection.execute(
                f"""
                SELECT permission, effect, created_at, updated_at
                FROM {table}
                WHERE {foreign_key}=? AND permission=?
                """,
                (body.subject_id, permission),
            )
            before = await cursor.fetchone()
            await connection.execute(
                f"""
                INSERT INTO {table}({foreign_key}, permission, effect, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT({foreign_key}, permission) DO UPDATE SET
                    effect=excluded.effect,
                    updated_at=excluded.updated_at
                """,
                (body.subject_id, permission, effect, now, now),
            )

        rule = {
            "subject_type": subject_type,
            "subject_id": body.subject_id,
            "subject_name": str(subject["name"]),
            "permission": permission,
            "effect": effect,
            "reason": reason if subject_type == "MEMBER" else None,
            "updated_at": now,
        }
        bumped = await _bump_guild_authorization_versions(connection, actor.guild_id)
        await services.audit.record(
            actor.guild_id,
            "DISCORD_PERMISSION_RULE_CONFIGURED",
            actor_id=actor.discord_id,
            target_id=body.subject_id,
            before=plain(before),
            after={
                **rule,
                "authorization_versions_bumped": bumped,
                "request_id": actor.correlation_id,
            },
            connection=connection,
        )
    await services.permissions.invalidate(actor.guild_id)
    return {"rule": rule, "authorization_versions_bumped": bumped}


@app.delete("/v1/discord/permissions/{subject_type}/{subject_id}/{permission}")
async def delete_discord_permission_rule(
    request: Request,
    subject_type: str,
    subject_id: int,
    permission: str,
    actor: Actor,
) -> Any:
    require_permission(actor, "identity.configure")
    services = request.app.state.services
    normalized_subject_type = _normalize_permission_subject_type(subject_type)
    normalized_permission = _normalize_permission_name(permission)
    async with services.database.transaction() as connection:
        subject = await _permission_subject(
            connection,
            guild_id=actor.guild_id,
            subject_type=normalized_subject_type,
            subject_id=subject_id,
        )
        if normalized_subject_type == "MEMBER":
            table = "member_permission_overrides"
            foreign_key = "member_id"
            cursor = await connection.execute(
                """
                SELECT permission, effect, reason, created_by, created_at, updated_at
                FROM member_permission_overrides
                WHERE member_id=? AND permission=?
                """,
                (subject_id, normalized_permission),
            )
        else:
            table, foreign_key = _PERMISSION_RULE_TABLES[normalized_subject_type]
            cursor = await connection.execute(
                f"""
                SELECT permission, effect, created_at, updated_at
                FROM {table}
                WHERE {foreign_key}=? AND permission=?
                """,
                (subject_id, normalized_permission),
            )
        before = await cursor.fetchone()
        if before is None:
            raise HTTPException(404, "Regra de permissão não encontrada.")
        await connection.execute(
            f"DELETE FROM {table} WHERE {foreign_key}=? AND permission=?",
            (subject_id, normalized_permission),
        )
        bumped = await _bump_guild_authorization_versions(connection, actor.guild_id)
        await services.audit.record(
            actor.guild_id,
            "DISCORD_PERMISSION_RULE_REMOVED",
            actor_id=actor.discord_id,
            target_id=subject_id,
            before=plain(before),
            after={
                "subject_type": normalized_subject_type,
                "subject_id": subject_id,
                "subject_name": str(subject["name"]),
                "permission": normalized_permission,
                "authorization_versions_bumped": bumped,
                "request_id": actor.correlation_id,
            },
            connection=connection,
        )
    await services.permissions.invalidate(actor.guild_id)
    return {
        "removed": True,
        "subject_type": normalized_subject_type,
        "subject_id": subject_id,
        "permission": normalized_permission,
        "authorization_versions_bumped": bumped,
    }


@app.get("/v1/discord/role-mappings")
async def discord_role_mappings(request: Request, actor: Actor) -> Any:
    require_permission(actor, "identity.configure")
    services = request.app.state.services
    mappings, roles, ranks, positions, profiles = await asyncio.gather(
        services.database.fetchall(
            """
            SELECT drm.*, rr.name AS discord_role_name,
                   r.name AS rank_name,
                   fp.code AS position_code, fp.name AS position_name,
                   ap.code AS access_profile_code, ap.name AS access_profile_name
            FROM discord_role_mappings drm
            LEFT JOIN discord_resource_registry rr
              ON rr.guild_id=drm.guild_id AND rr.resource_id=drm.discord_role_id
             AND rr.resource_type='ROLE' AND rr.active=1
            LEFT JOIN ranks r ON r.id=drm.rank_id
            LEFT JOIN functional_positions fp ON fp.id=drm.position_id
            LEFT JOIN access_profiles ap ON ap.id=drm.access_profile_id
            WHERE drm.guild_id=?
            ORDER BY drm.enabled DESC, drm.priority DESC, drm.id
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT resource_id AS id, name, position
            FROM discord_resource_registry
            WHERE guild_id=? AND resource_type='ROLE' AND active=1
            ORDER BY position DESC, resource_id
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT id, name, prefix, level, discord_role_id, active
            FROM ranks WHERE guild_id=? ORDER BY active DESC, level DESC, id
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT fp.id, fp.code, fp.name, fp.priority, fp.is_primary_candidate,
                   fp.enabled, ap.code AS access_profile
            FROM functional_positions fp
            LEFT JOIN access_profiles ap ON ap.id=fp.access_profile_id
            WHERE fp.guild_id=? ORDER BY fp.enabled DESC, fp.priority DESC, fp.id
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT id, code, name, priority, enabled
            FROM access_profiles WHERE guild_id=?
            ORDER BY enabled DESC, priority DESC, id
            """,
            (actor.guild_id,),
        ),
    )
    return plain(
        {
            "mappings": mappings,
            "roles": roles,
            "ranks": ranks,
            "positions": positions,
            "access_profiles": profiles,
            "summary": {
                "total": len(mappings),
                "enabled": sum(bool(row["enabled"]) for row in mappings),
                "available_roles": len(roles),
            },
        }
    )


@app.put("/v1/discord/role-mappings")
async def upsert_discord_role_mapping(
    request: Request,
    body: DiscordRoleMappingBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "identity.configure")
    services = request.app.state.services
    mapping_type = body.mapping_type.strip().upper()
    allowed_types = {"RANK", "POSITION", "QUALIFICATION", "SYSTEM", "COSMETIC", "ACCESS"}
    if mapping_type not in allowed_types:
        raise HTTPException(422, "Tipo de mapeamento Discord inválido.")
    internal_code = body.internal_code.strip().upper().replace("-", "_").replace(" ", "_")
    if not re.fullmatch(r"[A-Z0-9_:.]{2,80}", internal_code):
        raise HTTPException(422, "Identificador interno inválido.")
    role = await services.database.fetchone(
        """
        SELECT name FROM discord_resource_registry
        WHERE guild_id=? AND resource_id=? AND resource_type='ROLE' AND active=1
        """,
        (actor.guild_id, body.discord_role_id),
    )
    if not role:
        raise HTTPException(422, "Cargo não encontrado no snapshot atual do Discord.")

    if mapping_type == "RANK":
        if body.rank_id is None or any(
            value is not None for value in (body.position_id, body.access_profile_id)
        ):
            raise HTTPException(422, "Mapeamento RANK exige somente uma patente.")
    elif mapping_type == "POSITION":
        if body.position_id is None or body.rank_id is not None:
            raise HTTPException(422, "Mapeamento POSITION exige uma função válida.")
    elif mapping_type == "ACCESS":
        if body.access_profile_id is None or any(
            value is not None for value in (body.rank_id, body.position_id)
        ):
            raise HTTPException(422, "Mapeamento ACCESS exige somente um perfil de acesso.")
    elif any(value is not None for value in (body.rank_id, body.position_id, body.access_profile_id)):
        raise HTTPException(422, "Este tipo não aceita patente, função ou perfil de acesso.")
    if mapping_type != "POSITION" and body.is_primary_position_candidate:
        raise HTTPException(422, "Somente POSITION pode ser candidato a cargo principal.")

    if body.rank_id is not None:
        rank = await services.database.fetchone(
            "SELECT id FROM ranks WHERE guild_id=? AND id=?",
            (actor.guild_id, body.rank_id),
        )
        if not rank:
            raise HTTPException(422, "Patente não pertence a esta guild.")
    if body.position_id is not None:
        position = await services.database.fetchone(
            "SELECT id FROM functional_positions WHERE guild_id=? AND id=?",
            (actor.guild_id, body.position_id),
        )
        if not position:
            raise HTTPException(422, "Função não pertence a esta guild.")
    if body.access_profile_id is not None:
        profile = await services.database.fetchone(
            "SELECT id FROM access_profiles WHERE guild_id=? AND id=?",
            (actor.guild_id, body.access_profile_id),
        )
        if not profile:
            raise HTTPException(422, "Perfil de acesso não pertence a esta guild.")

    now = utc_now_ms()
    async with services.database.transaction() as connection:
        cursor = await connection.execute(
            """
            SELECT * FROM discord_role_mappings
            WHERE guild_id=? AND discord_role_id=? AND mapping_type=?
            """,
            (actor.guild_id, body.discord_role_id, mapping_type),
        )
        before = await cursor.fetchone()
        if mapping_type == "RANK":
            assert body.rank_id is not None
            await services.settings.set_rank_role_mapping(
                actor.guild_id,
                body.rank_id,
                body.discord_role_id,
                actor.discord_id,
                enabled=body.enabled,
                connection=connection,
            )
            # RANK still accepts presentation metadata in the canonical editor;
            # the settings adapter first guarantees the one-to-one invariant.
            await connection.execute(
                """
                UPDATE discord_role_mappings
                SET internal_code=?, display_name=?, priority=?, updated_at=?
                WHERE guild_id=? AND discord_role_id=? AND mapping_type='RANK'
                """,
                (
                    internal_code,
                    body.display_name.strip(),
                    body.priority,
                    now,
                    actor.guild_id,
                    body.discord_role_id,
                ),
            )
        else:
            await connection.execute(
                """
                INSERT INTO discord_role_mappings(
                    guild_id, discord_role_id, mapping_type, internal_code, display_name,
                    priority, rank_id, position_id, access_profile_id,
                    is_primary_position_candidate, enabled, created_at, updated_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, discord_role_id, mapping_type) DO UPDATE SET
                    internal_code=excluded.internal_code,
                    display_name=excluded.display_name,
                    priority=excluded.priority,
                    rank_id=excluded.rank_id,
                    position_id=excluded.position_id,
                    access_profile_id=excluded.access_profile_id,
                    is_primary_position_candidate=excluded.is_primary_position_candidate,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at,
                    created_by=excluded.created_by
                """,
                (
                    actor.guild_id,
                    body.discord_role_id,
                    mapping_type,
                    internal_code,
                    body.display_name.strip(),
                    body.priority,
                    body.rank_id,
                    body.position_id,
                    body.access_profile_id,
                    int(body.is_primary_position_candidate),
                    int(body.enabled),
                    now,
                    now,
                    actor.discord_id,
                ),
            )
        cursor = await connection.execute(
            """
            SELECT * FROM discord_role_mappings
            WHERE guild_id=? AND discord_role_id=? AND mapping_type=?
            """,
            (actor.guild_id, body.discord_role_id, mapping_type),
        )
        after = await cursor.fetchone()
        reconciliation = await _enqueue_identity_reconciliation(
            connection,
            guild_id=actor.guild_id,
            requested_by=actor.discord_id,
            mode="APPLY",
            source="ROLE_MAPPING_CHANGED",
        )
        await services.audit.record(
            actor.guild_id,
            "DISCORD_ROLE_MAPPING_CONFIGURED",
            actor_id=actor.discord_id,
            before=plain(before),
            after={
                **plain(after),
                "discord_role_name": role["name"],
                "request_id": actor.correlation_id,
            },
            connection=connection,
        )
    await services.permissions.invalidate(actor.guild_id)
    return plain({"mapping": after, "reconciliation": reconciliation})


@app.delete("/v1/discord/role-mappings/{mapping_id}")
async def disable_discord_role_mapping(
    request: Request, mapping_id: int, actor: Actor
) -> Any:
    require_permission(actor, "identity.configure")
    services = request.app.state.services
    now = utc_now_ms()
    async with services.database.transaction() as connection:
        cursor = await connection.execute(
            "SELECT * FROM discord_role_mappings WHERE guild_id=? AND id=?",
            (actor.guild_id, mapping_id),
        )
        before = await cursor.fetchone()
        if not before:
            raise HTTPException(404, "Mapeamento Discord não encontrado.")
        if (
            before["mapping_type"] == "RANK"
            and before["rank_id"] is not None
            and bool(before["enabled"])
        ):
            await services.settings.set_rank_role_mapping(
                actor.guild_id,
                int(before["rank_id"]),
                None,
                actor.discord_id,
                enabled=False,
                connection=connection,
            )
        else:
            await connection.execute(
                "UPDATE discord_role_mappings SET enabled=0, updated_at=? WHERE id=?",
                (now, mapping_id),
            )
        reconciliation = await _enqueue_identity_reconciliation(
            connection,
            guild_id=actor.guild_id,
            requested_by=actor.discord_id,
            mode="APPLY",
            source="ROLE_MAPPING_DISABLED",
        )
        await services.audit.record(
            actor.guild_id,
            "DISCORD_ROLE_MAPPING_DISABLED",
            actor_id=actor.discord_id,
            before=plain(before),
            after={
                "id": mapping_id,
                "enabled": False,
                "request_id": actor.correlation_id,
            },
            connection=connection,
        )
    await services.permissions.invalidate(actor.guild_id)
    return {"mapping_id": mapping_id, "enabled": False, "reconciliation": reconciliation}


@app.get("/v1/discord/identity/status")
async def discord_identity_status(request: Request, actor: Actor) -> Any:
    require_permission(actor, "identity.reconcile")
    services = request.app.state.services
    counts, summary, pending, jobs = await asyncio.gather(
        services.database.fetchall(
            """
            SELECT identity_sync_status AS status, COUNT(*) AS total
            FROM members WHERE guild_id=? GROUP BY identity_sync_status ORDER BY status
            """,
            (actor.guild_id,),
        ),
        services.database.fetchone(
            """
            SELECT COUNT(*) AS members,
                   SUM(CASE WHEN discord_present=1 THEN 1 ELSE 0 END) AS discord_present,
                   SUM(CASE WHEN identity_sync_status='SYNCED' THEN 1 ELSE 0 END)
                       AS synced_members,
                   SUM(CASE WHEN identity_sync_status='REVIEW_REQUIRED' THEN 1 ELSE 0 END)
                       AS divergences,
                   SUM(CASE WHEN identity_sync_status='ERROR' THEN 1 ELSE 0 END)
                       AS failures,
                   SUM(CASE WHEN discord_present=0 THEN 1 ELSE 0 END) AS discord_absent,
                   MAX(discord_roles_synced_at) AS last_synced_at,
                   MAX(authorization_version) AS latest_authorization_version
            FROM members WHERE guild_id=?
            """,
            (actor.guild_id,),
        ),
        services.database.fetchone(
            """
            SELECT COUNT(*) AS total
            FROM web_action_outbox
            WHERE guild_id=? AND action_type IN ('IDENTITY_SYNC','IDENTITY_RECONCILE_BULK')
              AND status IN ('PENDING','PROCESSING')
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT id, mode, status, requested_by, source_job_id, correlation_id,
                   total_members, unchanged_members, divergent_positions,
                   divergent_ranks, review_required, failed_members,
                   created_at, started_at, completed_at, last_error
            FROM identity_reconciliation_jobs
            WHERE guild_id=? ORDER BY created_at DESC, id DESC LIMIT 20
            """,
            (actor.guild_id,),
        ),
    )
    summary_payload = plain(summary) if summary else {}
    summary_payload.update(
        {
            "last_sync_at": summary_payload.get("last_synced_at"),
            "pending_queue": int(pending["total"] if pending else 0),
            "pending_jobs": int(pending["total"] if pending else 0),
            "running_job_id": next(
                (
                    int(job["id"])
                    for job in jobs
                    if str(job["status"]) in {"PENDING", "PROCESSING"}
                ),
                None,
            ),
        }
    )
    return plain(
        {
            "summary": summary_payload,
            "sync_status_counts": counts,
            "pending_actions": int(pending["total"] if pending else 0),
            "recent_jobs": jobs,
        }
    )


@app.post("/v1/discord/identity/sync/{discord_id}")
async def sync_discord_identity(
    request: Request, discord_id: int, actor: Actor
) -> Any:
    require_permission(actor, "identity.reconcile")
    services = request.app.state.services
    now = utc_now_ms()
    async with services.database.transaction() as connection:
        cursor = await connection.execute(
            "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
            (actor.guild_id, discord_id),
        )
        member = await cursor.fetchone()
        if not member:
            raise HTTPException(404, "Membro não encontrado.")
        cursor = await connection.execute(
            """
            SELECT correlation_id, status FROM web_action_outbox
            WHERE guild_id=? AND action_type='IDENTITY_SYNC' AND target_discord_id=?
              AND status IN ('PENDING','PROCESSING')
            ORDER BY created_at DESC LIMIT 1
            """,
            (actor.guild_id, discord_id),
        )
        existing = await cursor.fetchone()
        if existing:
            return {
                "discord_id": discord_id,
                "status": existing["status"],
                "correlation_id": existing["correlation_id"],
                "deduplicated": True,
            }
        correlation_id = str(uuid.uuid4())
        await connection.execute(
            """
            INSERT INTO web_action_outbox(
                guild_id, action_type, target_discord_id, payload_json,
                requested_by, correlation_id, status, available_at, created_at
            ) VALUES (?, 'IDENTITY_SYNC', ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (
                actor.guild_id,
                discord_id,
                json.dumps({"source": "PANEL_ACTION"}),
                actor.discord_id,
                correlation_id,
                now,
                now,
            ),
        )
        await services.audit.record(
            actor.guild_id,
            "DISCORD_IDENTITY_SYNC_REQUESTED",
            actor_id=actor.discord_id,
            target_id=discord_id,
            after={
                "source": "PANEL_ACTION",
                "correlation_id": correlation_id,
                "request_id": actor.correlation_id,
            },
            connection=connection,
        )
    return {
        "discord_id": discord_id,
        "status": "PENDING",
        "correlation_id": correlation_id,
        "deduplicated": False,
    }


@app.post("/v1/discord/reconciliation/preview")
@app.post("/v1/discord/identity/reconciliation/preview")
async def preview_discord_identity_reconciliation(request: Request, actor: Actor) -> Any:
    require_permission(actor, "identity.reconcile")
    services = request.app.state.services
    async with services.database.transaction() as connection:
        job = await _enqueue_identity_reconciliation(
            connection,
            guild_id=actor.guild_id,
            requested_by=actor.discord_id,
            mode="PREVIEW",
            source="PANEL_ACTION",
        )
        await services.audit.record(
            actor.guild_id,
            "DISCORD_IDENTITY_RECONCILIATION_PREVIEW_REQUESTED",
            actor_id=actor.discord_id,
            after={**job, "request_id": actor.correlation_id},
            connection=connection,
        )
    return job


@app.post("/v1/discord/reconciliation/apply")
@app.post("/v1/discord/identity/reconciliation/apply")
async def apply_discord_identity_reconciliation(
    request: Request,
    body: IdentityReconciliationApplyBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "identity.reconcile")
    services = request.app.state.services
    preview = await services.database.fetchone(
        """
        SELECT id, mode, status FROM identity_reconciliation_jobs
        WHERE guild_id=? AND id=?
        """,
        (actor.guild_id, body.preview_job_id),
    )
    if not preview:
        raise HTTPException(404, "Preview de reconciliação não encontrado.")
    if preview["mode"] != "PREVIEW" or preview["status"] != "COMPLETED":
        raise HTTPException(409, "O preview precisa estar concluído antes da aplicação.")
    duplicate = await services.database.fetchone(
        """
        SELECT id, status FROM identity_reconciliation_jobs
        WHERE guild_id=? AND mode='APPLY' AND source_job_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (actor.guild_id, body.preview_job_id),
    )
    if duplicate:
        raise HTTPException(409, "Este preview já possui uma aplicação registrada.")
    try:
        async with services.database.transaction() as connection:
            job = await _enqueue_identity_reconciliation(
                connection,
                guild_id=actor.guild_id,
                requested_by=actor.discord_id,
                mode="APPLY",
                source="PANEL_ACTION",
                source_job_id=body.preview_job_id,
            )
            await services.audit.record(
                actor.guild_id,
                "DISCORD_IDENTITY_RECONCILIATION_APPLY_REQUESTED",
                actor_id=actor.discord_id,
                before={"preview_job_id": body.preview_job_id},
                after={**job, "request_id": actor.correlation_id},
                connection=connection,
            )
    except sqlite3.IntegrityError as exc:
        if "identity_reconciliation_jobs.source_job_id" not in str(exc):
            raise
        raise HTTPException(409, "Este preview já possui uma aplicação registrada.") from exc
    return job


@app.get("/v1/discord/reconciliations/{job_id}")
@app.get("/v1/discord/identity/reconciliations/{job_id}")
async def discord_identity_reconciliation(
    request: Request, job_id: int, actor: Actor
) -> Any:
    require_permission(actor, "identity.reconcile")
    services = request.app.state.services
    job = await services.database.fetchone(
        """
        SELECT id, mode, status, requested_by, source_job_id, correlation_id,
               total_members, unchanged_members, divergent_positions,
               divergent_ranks, review_required, failed_members,
               created_at, started_at, completed_at, last_error
        FROM identity_reconciliation_jobs WHERE guild_id=? AND id=?
        """,
        (actor.guild_id, job_id),
    )
    if not job:
        raise HTTPException(404, "Reconciliação não encontrada.")
    items = await services.database.fetchall(
        """
        SELECT member_id, discord_id, result, before_json, after_json, error, created_at
        FROM identity_reconciliation_job_items
        WHERE job_id=? ORDER BY id LIMIT 500
        """,
        (job_id,),
    )
    payload_items = []
    for item in items:
        payload = plain(item)
        for key in ("before_json", "after_json"):
            try:
                payload[key.removesuffix("_json")] = json.loads(payload.pop(key) or "{}")
            except json.JSONDecodeError:
                payload[key.removesuffix("_json")] = {}
        payload_items.append(payload)
    return plain({"job": job, "items": payload_items})


@app.get("/v1/qualifications")
async def qualifications(request: Request, actor: Actor) -> Any:
    require_permission(actor, "qualification.view.all")
    result = await request.app.state.services.operations.qualification_matrix(actor.guild_id)
    return plain(result)


@app.get("/v1/recruits")
async def recruits(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.review")
    return plain(await request.app.state.services.operations.recruits(actor.guild_id))


@app.get("/v1/trainings")
async def trainings(request: Request, actor: Actor) -> Any:
    require_permission(actor, "training.view.self")
    catalog, active, history = await asyncio.gather(
        request.app.state.services.training.catalog(actor.guild_id),
        request.app.state.services.training.active_trainings(actor.guild_id),
        request.app.state.services.training.history(actor.guild_id),
    )
    return plain({"catalog": catalog, "active": active, "history": history})


@app.get("/v1/inbox")
async def inbox(request: Request, actor: Actor) -> Any:
    require_permission(actor, "admin.inbox.view")
    result = await request.app.state.services.operations.administrative_inbox(actor.guild_id)
    return plain(result)


@app.get("/v1/registration-gate")
async def registration_gate_dashboard(request: Request, actor: Actor) -> Any:
    require_permission(actor, "registration.view")
    services = request.app.state.services
    setting_keys = (
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
        "registration_gate_activated_at",
    )
    counts, records, findings, classifications, roles, channels, categories = await asyncio.gather(
        services.registration_gate.counts(actor.guild_id),
        services.registration_gate.queue(actor.guild_id, limit=100),
        services.database.fetchall(
            """
            SELECT * FROM registration_access_findings
            WHERE guild_id=? AND status='OPEN' ORDER BY created_at DESC LIMIT 100
            """,
            (actor.guild_id,),
        ),
        services.registration_gate.classifications(actor.guild_id),
        services.database.fetchall(
            """
            SELECT resource_id, name FROM discord_resource_registry
            WHERE guild_id=? AND resource_type='ROLE' AND active=1 ORDER BY position DESC
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT resource_id, name FROM discord_resource_registry
            WHERE guild_id=? AND resource_type='TEXT_CHANNEL' AND active=1 ORDER BY position
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT resource_id, name FROM discord_resource_registry
            WHERE guild_id=? AND resource_type='CATEGORY' AND active=1 ORDER BY position
            """,
            (actor.guild_id,),
        ),
    )
    configuration = {key: await services.settings.get(actor.guild_id, key) for key in setting_keys}
    return plain(
        {
            "counts": counts,
            "records": records,
            "findings": findings,
            "classifications": classifications,
            "configuration": configuration,
            "resources": {"roles": roles, "channels": channels, "categories": categories},
        }
    )


@app.post("/v1/registration-gate/{registration_id}/decision")
async def registration_gate_decision(
    request: Request,
    registration_id: int,
    body: RegistrationGateDecisionBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "registration.review")
    services = request.app.state.services
    record = await services.registration_gate.get(registration_id)
    if not record or int(record["guild_id"]) != actor.guild_id:
        raise HTTPException(404, "Cadastro não encontrado.")
    action = body.action.upper()
    if action == "APPROVE":
        result = await services.registration_gate.approve_new_member(
            registration_id,
            reviewer_id=actor.discord_id,
            reason=body.reason,
            discord_nick=str(record["mta_nick"] or f"Discord {record['discord_id']}"),
        )
    elif action == "DENY":
        result = await services.registration_gate.reject(
            registration_id,
            reviewer_id=actor.discord_id,
            reason=body.reason,
        )
    elif action == "CORRECT_ID":
        if not body.bgr_id:
            raise HTTPException(422, "Informe o novo ID BGR.")
        result = await services.registration_gate.correct_bgr_id(
            registration_id,
            bgr_id=body.bgr_id,
            reviewer_id=actor.discord_id,
            reason=body.reason,
        )
    elif action == "LINK_EXISTING":
        if not body.member_id:
            raise HTTPException(422, "Informe o perfil de membro para vincular.")
        member = await services.database.fetchone(
            "SELECT 1 FROM members WHERE guild_id=? AND id=?",
            (actor.guild_id, body.member_id),
        )
        if not member:
            raise HTTPException(422, "Perfil de membro não pertence a esta guild.")
        result = await services.registration_gate.link_existing_member(
            registration_id,
            member_id=body.member_id,
            reviewer_id=actor.discord_id,
            reason=body.reason,
        )
    else:
        raise HTTPException(422, "Ação de Portaria não suportada.")
    return plain(result)


@app.patch("/v1/registration-gate/configuration")
async def registration_gate_configuration(
    request: Request,
    body: RegistrationGateConfigurationBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "registration.settings")
    services = request.app.state.services
    values = body.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(422, "Nenhuma configuração foi informada.")
    if {"registration_bypass_role_ids", "registration_bypass_user_ids"} & values.keys():
        require_permission(actor, "registration.bypass.manage")
    resource_expectations = {
        "unregistered_role_id": "ROLE",
        "candidate_role_id": "ROLE",
        "member_role_id": "ROLE",
        "registration_onboarding_category_id": "CATEGORY",
        "registration_panel_channel_id": "TEXT_CHANNEL",
        "registration_support_channel_id": "TEXT_CHANNEL",
    }
    for key, resource_type in resource_expectations.items():
        resource_id = values.get(key)
        if resource_id is None:
            continue
        exists = await services.database.fetchone(
            """
            SELECT 1 FROM discord_resource_registry
            WHERE guild_id=? AND resource_id=? AND resource_type=? AND active=1
            """,
            (actor.guild_id, int(resource_id), resource_type),
        )
        if not exists:
            raise HTTPException(422, f"Recurso Discord inválido para {key}.")
    for list_key, resource_type in (
        ("registration_onboarding_channel_ids", "TEXT_CHANNEL"),
        ("registration_bypass_role_ids", "ROLE"),
    ):
        for resource_id in values.get(list_key, []):
            exists = await services.database.fetchone(
                """
                SELECT 1 FROM discord_resource_registry
                WHERE guild_id=? AND resource_id=? AND resource_type=? AND active=1
                """,
                (actor.guild_id, int(resource_id), resource_type),
            )
            if not exists:
                raise HTTPException(422, f"Recurso Discord inválido em {list_key}.")
    if values.get("registration_gate_enabled") is True:
        effective = {
            key: values.get(key, await services.settings.get(actor.guild_id, key))
            for key in (
                "unregistered_role_id",
                "member_role_id",
                "registration_onboarding_category_id",
                "registration_panel_channel_id",
                "registration_support_channel_id",
            )
        }
        if any(value is None for value in effective.values()):
            raise HTTPException(
                422, "Complete cargos, categoria, painel e suporte antes de ativar."
            )
        blockers = await services.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM registration_access_findings
            WHERE guild_id=? AND status='OPEN'
              AND finding_type IN ('UNCLASSIFIED_RESOURCE','UNREGISTERED_ACCESS_LEAK',
                                   'OWNER_LOCKOUT_RISK','ONBOARDING_UNAVAILABLE')
            """,
            (actor.guild_id,),
        )
        if blockers and int(blockers["total"]):
            raise HTTPException(409, "Ativação bloqueada por achados de acesso ainda abertos.")
    result = await services.registration_gate.set_configuration(
        actor.guild_id, values, actor_id=actor.discord_id
    )
    if values.get("registration_gate_enabled") is True:
        await services.settings.set(
            actor.guild_id, "registration_gate_activated_at", utc_now_ms(), actor.discord_id
        )
    return plain(result)


@app.get("/v1/tickets/operations")
async def ticket_operations_dashboard(request: Request, actor: Actor) -> Any:
    require_permission(actor, "ticket.view")
    services = request.app.state.services
    setting_keys = (
        "ticket_active_category_id",
        "ticket_archive_category_id",
        "ticket_responsible_role_id",
        "ticket_transcript_channel_id",
        "ticket_requester_notify_cooldown_seconds",
        "ticket_bot_role_id",
    )
    dashboard, roles, channels, categories = await asyncio.gather(
        services.tickets.dashboard(actor.guild_id),
        services.database.fetchall(
            """
            SELECT resource_id, name, position FROM discord_resource_registry
            WHERE guild_id=? AND resource_type='ROLE' AND active=1 ORDER BY position DESC
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT resource_id, name, position FROM discord_resource_registry
            WHERE guild_id=? AND resource_type='TEXT_CHANNEL' AND active=1 ORDER BY position
            """,
            (actor.guild_id,),
        ),
        services.database.fetchall(
            """
            SELECT resource_id, name, position FROM discord_resource_registry
            WHERE guild_id=? AND resource_type='CATEGORY' AND active=1 ORDER BY position
            """,
            (actor.guild_id,),
        ),
    )
    configuration = {key: await services.settings.get(actor.guild_id, key) for key in setting_keys}
    blockers: list[str] = []
    for key in (
        "ticket_active_category_id",
        "ticket_archive_category_id",
        "ticket_responsible_role_id",
    ):
        if not configuration[key]:
            blockers.append(f"{key}:not-configured")
    if (
        configuration["ticket_active_category_id"]
        and configuration["ticket_active_category_id"]
        == configuration["ticket_archive_category_id"]
    ):
        blockers.append("ticket-categories:must-be-distinct")
    role_positions = {int(row["resource_id"]): int(row["position"]) for row in roles}
    bot_role_id = configuration["ticket_bot_role_id"]
    responsible_role_id = configuration["ticket_responsible_role_id"]
    hierarchy_valid = bool(
        bot_role_id
        and responsible_role_id
        and int(bot_role_id) in role_positions
        and int(responsible_role_id) in role_positions
        and role_positions[int(bot_role_id)] > role_positions[int(responsible_role_id)]
    )
    if responsible_role_id and not hierarchy_valid:
        blockers.append("bot-role-hierarchy:not-validated")
    return plain(
        {
            **dashboard,
            "configuration": configuration,
            "resources": {"roles": roles, "channels": channels, "categories": categories},
            "validation": {
                "ready": not blockers,
                "hierarchy_valid": hierarchy_valid,
                "blockers": blockers,
            },
        }
    )


@app.patch("/v1/tickets/configuration")
async def ticket_configuration(
    request: Request,
    body: TicketConfigurationBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "ticket.manage")
    services = request.app.state.services
    values = body.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(422, "Nenhuma configuração foi informada.")
    expectations = {
        "ticket_active_category_id": "CATEGORY",
        "ticket_archive_category_id": "CATEGORY",
        "ticket_responsible_role_id": "ROLE",
        "ticket_transcript_channel_id": "TEXT_CHANNEL",
    }
    for key, resource_type in expectations.items():
        resource_id = values.get(key)
        if resource_id is None:
            continue
        exists = await services.database.fetchone(
            """
            SELECT 1 FROM discord_resource_registry
            WHERE guild_id=? AND resource_id=? AND resource_type=? AND active=1
            """,
            (actor.guild_id, int(resource_id), resource_type),
        )
        if not exists:
            raise HTTPException(422, f"Recurso Discord inválido para {key}.")
    active = values.get(
        "ticket_active_category_id",
        await services.settings.get(actor.guild_id, "ticket_active_category_id"),
    )
    archive = values.get(
        "ticket_archive_category_id",
        await services.settings.get(actor.guild_id, "ticket_archive_category_id"),
    )
    if active and archive and int(active) == int(archive):
        raise HTTPException(422, "As categorias ativa e de arquivo devem ser diferentes.")
    async with services.database.transaction() as connection:
        for key, value in values.items():
            await services.settings.set(actor.guild_id, key, value, actor.discord_id, connection)
        await services.audit.record(
            actor.guild_id,
            "TICKET_CONFIGURATION_CHANGED",
            actor_id=actor.discord_id,
            after={"keys": sorted(values)},
            connection=connection,
        )
    return plain({key: await services.settings.get(actor.guild_id, key) for key in values})


@app.post("/v1/requests/{request_id}/decision")
async def decide_request(
    request: Request,
    request_id: int,
    body: DecisionBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "request.review")
    result = await request.app.state.services.requests.review(
        actor.guild_id,
        request_id,
        body.approved,
        actor.discord_id,
        body.reason,
    )
    return plain(result)


@app.post("/v1/inbox/{item_type}/{item_id}/decision")
async def decide_inbox_item(
    request: Request,
    item_type: str,
    item_id: int,
    body: DecisionBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "admin.inbox.view")
    services = request.app.state.services
    normalized = item_type.upper()
    if normalized == "ADMIN_REQUEST":
        require_permission(actor, "request.review")
        result = await services.requests.review(
            actor.guild_id, item_id, body.approved, actor.discord_id, body.reason
        )
    elif normalized == "ABSENCE":
        require_permission(actor, "absence.review")
        result = await services.personnel.review_absence(
            actor.guild_id, item_id, body.approved, actor.discord_id, body.reason
        )
    elif normalized == "SERVICE_TICKET":
        require_permission(actor, "ticket.review")
        result = await services.tickets.decide(
            actor.guild_id,
            item_id,
            actor.discord_id,
            approved=body.approved,
            reason=body.reason,
        )
    elif normalized == "COURSE_APPLICATION":
        require_permission(actor, "training.manage")
        result = await services.training.decide_course_application(
            actor.guild_id,
            item_id,
            actor.discord_id,
            approved=body.approved,
            reason=body.reason,
        )
    elif normalized == "ACTIVITY_SWAP":
        require_permission(actor, "swap.review")
        result = await services.operations.decide_activity_swap(
            actor.guild_id, item_id, actor.discord_id, body.approved, body.reason
        )
    elif normalized == "INTEGRITY":
        require_permission(actor, "integrity.review")
        await services.operations.resolve_integrity_finding(
            actor.guild_id,
            item_id,
            actor.discord_id,
            body.reason,
            dismissed=not body.approved,
        )
        result = {"status": "RESOLVED" if body.approved else "DISMISSED"}
    elif normalized == "OPERATIONAL_FLAG":
        require_permission(actor, "operations.flags.review")
        await services.operations.review_operational_flag(
            actor.guild_id,
            item_id,
            actor.discord_id,
            "RESOLVED" if body.approved else "DISMISSED",
            body.reason,
        )
        result = {"status": "RESOLVED" if body.approved else "DISMISSED"}
    elif normalized == "SHIFT_REVIEW":
        require_permission(actor, "shift.review")
        if not body.approved:
            raise HTTPException(
                422, "Sessões em revisão devem ser confirmadas ou continuadas em call."
            )
        result = await services.shifts.review_shift(
            actor.guild_id, item_id, "CONFIRMAR", actor.discord_id, body.reason
        )
    elif normalized == "MEMBER_APPLICATION":
        require_permission(actor, "recruitment.review")
        application = await services.members.get_application(item_id)
        if not application or int(application["guild_id"]) != actor.guild_id:
            raise HTTPException(404, "Solicitação de membro não encontrada.")
        result = await services.members.review_application(
            item_id,
            actor.discord_id,
            body.approved,
            body.reason,
            str(application["mta_nick"]),
            enqueue_discord_sync=body.approved,
        )
    elif normalized == "REGISTRATION_GATE":
        require_permission(actor, "registration.review")
        registration = await services.registration_gate.get(item_id)
        if not registration or int(registration["guild_id"]) != actor.guild_id:
            raise HTTPException(404, "Cadastro da Portaria não encontrado.")
        if body.approved:
            result = await services.registration_gate.approve_new_member(
                item_id,
                reviewer_id=actor.discord_id,
                reason=body.reason,
                discord_nick=str(registration["mta_nick"] or "Membro BGR"),
            )
        else:
            result = await services.registration_gate.reject(
                item_id,
                reviewer_id=actor.discord_id,
                reason=body.reason,
            )
    elif normalized == "REGISTRATION_ACCESS":
        require_permission(actor, "registration.manage")
        finding = await services.database.fetchone(
            "SELECT * FROM registration_access_findings WHERE guild_id=? AND id=?",
            (actor.guild_id, item_id),
        )
        if not finding:
            raise HTTPException(404, "Achado de acesso não encontrado.")
        status = "RESOLVED" if body.approved else "DISMISSED"
        await services.database.execute(
            """
            UPDATE registration_access_findings
            SET status=?, resolved_at=?, resolution=?
            WHERE guild_id=? AND id=? AND status='OPEN'
            """,
            (status, utc_now_ms(), body.reason, actor.guild_id, item_id),
        )
        await services.audit.record(
            actor.guild_id,
            "REGISTRATION_ACCESS_FINDING_REVIEWED",
            actor_id=actor.discord_id,
            before=plain(finding),
            after={"status": status},
            reason=body.reason,
        )
        result = {"status": status}
    else:
        raise HTTPException(422, "Tipo de item administrativo não suportado.")
    return plain(result)


@app.get("/v1/discipline")
async def discipline(request: Request, actor: Actor) -> Any:
    require_permission(actor, "discipline.manage")
    occurrences, punishments = await asyncio.gather(
        request.app.state.services.discipline.open_occurrences(actor.guild_id),
        request.app.state.services.database.fetchall(
            """
            SELECT p.*, m.mta_nick, r.name AS rank_name FROM punishments p
            JOIN members m ON m.id=p.member_id LEFT JOIN ranks r ON r.id=m.rank_id
            WHERE p.guild_id=? ORDER BY p.created_at DESC LIMIT 100
            """,
            (actor.guild_id,),
        ),
    )
    return plain({"occurrences": occurrences, "measures": punishments})


@app.get("/v1/changes")
async def changes(
    request: Request,
    actor: Actor,
    days: int = Query(7, ge=1, le=90),
) -> Any:
    require_permission(actor, "changes.view")
    result = await request.app.state.services.operations.changes_summary(
        actor.guild_id, period_days=days
    )
    return plain(result)


@app.get("/v1/reports")
async def reports(request: Request, actor: Actor) -> Any:
    require_permission(actor, "reports.view")
    daily, weekly, monthly, points = await asyncio.gather(
        request.app.state.services.activity.daily_report(actor.guild_id),
        request.app.state.services.activity.weekly_report(actor.guild_id),
        request.app.state.services.activity.monthly_report(actor.guild_id),
        request.app.state.services.activity.points_report(actor.guild_id),
    )
    return plain({"daily": daily, "weekly": weekly, "monthly": monthly, "points": points})


@app.get("/v1/audit")
async def audit(
    request: Request,
    actor: Actor,
    limit: int = Query(100, ge=1, le=250),
) -> Any:
    require_permission(actor, "decisions.view")
    rows = await request.app.state.services.database.fetchall(
        "SELECT * FROM audit_logs WHERE guild_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
        (actor.guild_id, limit),
    )
    return plain(rows)


@app.get("/v1/integrity")
async def integrity(request: Request, actor: Actor) -> Any:
    require_permission(actor, "integrity.view")
    findings = await request.app.state.services.operations.integrity_findings(actor.guild_id)
    summary = await request.app.state.services.database.fetchall(
        """
        SELECT finding_type, fix_class, COUNT(*) AS total FROM integrity_findings
        WHERE guild_id=? AND status='OPEN' GROUP BY finding_type, fix_class
        """,
        (actor.guild_id,),
    )
    return plain({"summary": summary, "findings": findings})


@app.get("/v1/settings")
async def settings(request: Request, actor: Actor) -> Any:
    require_permission(actor, "settings.manage")
    services = request.app.state.services
    (
        rows,
        ranks,
        calls,
        bindings,
        patrol_calls,
        panels,
        maintenance_rows,
        registry,
    ) = await asyncio.gather(
        services.database.fetchall(
            "SELECT * FROM guild_settings WHERE guild_id=? ORDER BY setting_key",
            (actor.guild_id,),
        ),
        services.database.fetchall(
            "SELECT * FROM ranks WHERE guild_id=? ORDER BY level", (actor.guild_id,)
        ),
        services.database.fetchall(
            "SELECT * FROM authorized_voice_channels WHERE guild_id=? ORDER BY label",
            (actor.guild_id,),
        ),
        services.database.fetchall(
            "SELECT * FROM rbac_bindings WHERE guild_id=? ORDER BY profile, role_id",
            (actor.guild_id,),
        ),
        services.operations.patrol_channels(actor.guild_id),
        services.database.fetchall(
            "SELECT * FROM panels WHERE guild_id=? ORDER BY panel_type",
            (actor.guild_id,),
        ),
        services.operations.maintenance_modules(actor.guild_id),
        services.database.fetchall(
            """
            SELECT * FROM discord_resource_registry
            WHERE guild_id=? AND active=1
            ORDER BY resource_type, position, name
            """,
            (actor.guild_id,),
        ),
    )
    stored = {str(row["setting_key"]): row for row in rows}
    decoded = []
    for key, default in services.settings.DEFAULTS.items():
        row = stored.get(key)
        decoded.append(
            {
                "setting_key": key,
                "value": json.loads(row["value_json"]) if row else default,
                "updated_at": row["updated_at"] if row else None,
                "updated_by": row["updated_by"] if row else None,
                "source": "DATABASE" if row else "DEFAULT",
            }
        )
    return plain(
        {
            "general": decoded,
            "ranks": ranks,
            "voice_channels": calls,
            "rbac_bindings": bindings,
            "patrol_channels": patrol_calls,
            "panels": panels,
            "maintenance": maintenance_rows,
            "discord_resources": registry,
        }
    )


@app.put("/v1/settings/voice-channels")
async def upsert_voice_channel(
    request: Request,
    body: VoiceChannelBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "settings.manage")
    services = request.app.state.services
    resource = await services.database.fetchone(
        """
        SELECT name FROM discord_resource_registry
        WHERE guild_id=? AND resource_id=? AND resource_type='VOICE_CHANNEL' AND active=1
        """,
        (actor.guild_id, body.channel_id),
    )
    if not resource:
        raise HTTPException(422, "A call selecionada não existe no snapshot atual do Discord.")
    label_value = (body.label or str(resource["name"])).strip()
    async with services.database.transaction() as connection:
        cursor = await connection.execute(
            "SELECT * FROM authorized_voice_channels WHERE guild_id=? AND channel_id=?",
            (actor.guild_id, body.channel_id),
        )
        before = await cursor.fetchone()
        await connection.execute(
            """
            INSERT INTO authorized_voice_channels(
                guild_id, channel_id, label, created_at, created_by,
                service_allowed, counts_toward_patrol_minimum
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                label=excluded.label, service_allowed=1,
                counts_toward_patrol_minimum=excluded.counts_toward_patrol_minimum
            """,
            (
                actor.guild_id,
                body.channel_id,
                label_value,
                int(time.time() * 1000),
                actor.discord_id,
                int(body.counts_toward_patrol_minimum),
            ),
        )
        await services.audit.record(
            actor.guild_id,
            "WEB_VOICE_CHANNEL_CONFIGURED",
            actor_id=actor.discord_id,
            before=plain(before),
            after={
                "channel_id": body.channel_id,
                "label": label_value,
                "counts_toward_patrol_minimum": body.counts_toward_patrol_minimum,
            },
            connection=connection,
        )
    return {"channel_id": body.channel_id, "label": label_value}


@app.delete("/v1/settings/voice-channels/{channel_id}")
async def delete_voice_channel(request: Request, channel_id: int, actor: Actor) -> Any:
    require_permission(actor, "settings.manage")
    services = request.app.state.services
    async with services.database.transaction() as connection:
        cursor = await connection.execute(
            "SELECT * FROM authorized_voice_channels WHERE guild_id=? AND channel_id=?",
            (actor.guild_id, channel_id),
        )
        before = await cursor.fetchone()
        if not before:
            raise HTTPException(404, "Call autorizada não encontrada.")
        await connection.execute(
            "DELETE FROM authorized_voice_channels WHERE guild_id=? AND channel_id=?",
            (actor.guild_id, channel_id),
        )
        await services.audit.record(
            actor.guild_id,
            "WEB_VOICE_CHANNEL_REMOVED",
            actor_id=actor.discord_id,
            before=plain(before),
            connection=connection,
        )
    return {"channel_id": channel_id, "removed": True}


@app.put("/v1/settings/rbac-bindings")
async def upsert_rbac_binding(
    request: Request,
    body: RbacBindingBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "settings.manage")
    try:
        profile = RbacProfile(body.profile.upper())
    except ValueError as exc:
        raise HTTPException(422, "Perfil RBAC inválido.") from exc
    services = request.app.state.services
    resource = await services.database.fetchone(
        """
        SELECT name FROM discord_resource_registry
        WHERE guild_id=? AND resource_id=? AND resource_type='ROLE' AND active=1
        """,
        (actor.guild_id, body.role_id),
    )
    if not resource:
        raise HTTPException(422, "O cargo selecionado não existe no snapshot atual do Discord.")
    async with services.database.transaction() as connection:
        cursor = await connection.execute(
            "SELECT * FROM rbac_bindings WHERE guild_id=? AND role_id=?",
            (actor.guild_id, body.role_id),
        )
        before = await cursor.fetchone()
        reconciliation = await services.settings.bind_role(
            actor.guild_id,
            body.role_id,
            profile,
            actor.discord_id,
            "LEGACY_RBAC_ADAPTER_CHANGED",
            connection=connection,
        )
        await services.audit.record(
            actor.guild_id,
            "WEB_RBAC_BINDING_CONFIGURED",
            actor_id=actor.discord_id,
            before=plain(before),
            after={
                "role_id": body.role_id,
                "role_name": resource["name"],
                "profile": profile.value,
                "request_id": actor.correlation_id,
            },
            connection=connection,
        )
    await services.permissions.invalidate(actor.guild_id)
    return {
        "role_id": body.role_id,
        "profile": profile.value,
        "reconciliation": reconciliation,
    }


@app.delete("/v1/settings/rbac-bindings/{role_id}")
async def delete_rbac_binding(request: Request, role_id: int, actor: Actor) -> Any:
    require_permission(actor, "settings.manage")
    services = request.app.state.services
    async with services.database.transaction() as connection:
        cursor = await connection.execute(
            """
            SELECT drm.*, b.profile AS legacy_profile
            FROM discord_role_mappings drm
            LEFT JOIN rbac_bindings b
              ON b.guild_id=drm.guild_id AND b.role_id=drm.discord_role_id
            WHERE drm.guild_id=? AND drm.discord_role_id=? AND drm.mapping_type='ACCESS'
            """,
            (actor.guild_id, role_id),
        )
        before = await cursor.fetchone()
        if not before:
            raise HTTPException(404, "Vínculo RBAC não encontrado.")
        reconciliation = await services.settings.unbind_role(
            actor.guild_id,
            role_id,
            actor.discord_id,
            "LEGACY_RBAC_ADAPTER_REMOVED",
            connection=connection,
        )
        await services.audit.record(
            actor.guild_id,
            "WEB_RBAC_BINDING_REMOVED",
            actor_id=actor.discord_id,
            before=plain(before),
            after={"role_id": role_id, "request_id": actor.correlation_id},
            connection=connection,
        )
    await services.permissions.invalidate(actor.guild_id)
    return {"role_id": role_id, "removed": True, "reconciliation": reconciliation}


@app.patch("/v1/settings/general")
async def update_general_setting(
    request: Request,
    body: GeneralSettingBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "settings.manage")
    allowed = {
        "timezone",
        "grace_period_seconds",
        "minimum_patrol_minutes",
        "minimum_patrol_members",
        "patrol_continue_until_empty",
        "weekly_goal_minutes",
        "weekly_near_threshold_percent",
        "low_activity_days",
        "no_activity_days",
        "auto_remove_old_rank_roles",
        "enforce_member_nickname",
        "missing_rank_role_policy",
        "promotion_min_rank_days",
        "promotion_min_valid_hours",
        "promotion_required_courses",
        "recruit_min_days",
        "recruit_min_valid_hours",
        "recruit_min_patrols",
        "recruit_min_evaluations",
        "recruit_required_courses",
        "recruitment_public_url",
        "recruitment_stale_warning_hours",
    }
    if body.key not in allowed:
        raise HTTPException(422, "Regra não editável por esta interface.")
    before = await request.app.state.services.settings.get(actor.guild_id, body.key)
    await request.app.state.services.settings.set(
        actor.guild_id, body.key, body.value, actor.discord_id
    )
    await request.app.state.services.audit.record(
        actor.guild_id,
        "WEB_SETTING_CHANGED",
        actor_id=actor.discord_id,
        before={body.key: before},
        after={body.key: body.value},
    )
    return {"key": body.key, "value": body.value}


@app.patch("/v1/settings/channel")
async def update_channel_setting(
    request: Request,
    body: ChannelSettingBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "settings.manage")
    allowed = {
        "audit_channel_id": "TEXT_CHANNEL",
        "registration_approval_channel_id": "TEXT_CHANNEL",
        "registration_history_channel_id": "TEXT_CHANNEL",
        "registration_panel_channel_id": "TEXT_CHANNEL",
        "point_panel_channel_id": "TEXT_CHANNEL",
        "service_panel_channel_id": "TEXT_CHANNEL",
        "hierarchy_channel_id": "TEXT_CHANNEL",
        "config_panel_channel_id": "TEXT_CHANNEL",
        "personnel_admin_channel_id": "TEXT_CHANNEL",
        "absence_panel_channel_id": "TEXT_CHANNEL",
        "requests_panel_channel_id": "TEXT_CHANNEL",
        "career_panel_channel_id": "TEXT_CHANNEL",
        "discipline_panel_channel_id": "TEXT_CHANNEL",
        "training_panel_channel_id": "TEXT_CHANNEL",
        "activity_panel_channel_id": "TEXT_CHANNEL",
        "recruitment_panel_channel_id": "TEXT_CHANNEL",
        "recruitment_queue_channel_id": "TEXT_CHANNEL",
        "recruitment_notification_channel_id": "TEXT_CHANNEL",
        "recruitment_approved_channel_id": "TEXT_CHANNEL",
        "recruitment_rejected_channel_id": "TEXT_CHANNEL",
        "ticket_panel_channel_id": "TEXT_CHANNEL",
    }
    expected_type = allowed.get(body.key)
    if not expected_type:
        raise HTTPException(422, "Destino de canal não suportado.")
    resource = await request.app.state.services.database.fetchone(
        """
        SELECT name FROM discord_resource_registry
        WHERE guild_id=? AND resource_id=? AND resource_type=? AND active=1
        """,
        (actor.guild_id, body.resource_id, expected_type),
    )
    if not resource:
        raise HTTPException(422, "O canal selecionado não existe no snapshot atual do Discord.")
    before = await request.app.state.services.settings.get(actor.guild_id, body.key)
    await request.app.state.services.settings.set(
        actor.guild_id, body.key, body.resource_id, actor.discord_id
    )
    await request.app.state.services.audit.record(
        actor.guild_id,
        "WEB_CHANNEL_SETTING_CHANGED",
        actor_id=actor.discord_id,
        before={body.key: before},
        after={body.key: body.resource_id, "channel_name": resource["name"]},
    )
    return {"key": body.key, "resource_id": body.resource_id}


@app.patch("/v1/settings/ranks/{rank_id}")
async def update_rank_setting(
    request: Request,
    rank_id: int,
    body: RankSettingBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "settings.manage")
    services = request.app.state.services
    try:
        profile = RbacProfile(body.rbac_profile.upper()).value
    except ValueError as exc:
        raise HTTPException(422, "Perfil RBAC inválido.") from exc
    if body.discord_role_id is not None:
        resource = await services.database.fetchone(
            """
            SELECT 1 FROM discord_resource_registry
            WHERE guild_id=? AND resource_id=? AND resource_type='ROLE' AND active=1
            """,
            (actor.guild_id, body.discord_role_id),
        )
        if not resource:
            raise HTTPException(422, "O cargo selecionado não existe no snapshot atual.")
    async with services.database.transaction() as connection:
        cursor = await connection.execute(
            "SELECT * FROM ranks WHERE guild_id=? AND id=?", (actor.guild_id, rank_id)
        )
        before = await cursor.fetchone()
        if not before:
            raise HTTPException(404, "Patente não encontrada.")
        await connection.execute(
            """
            UPDATE ranks SET name=?, prefix=?, level=?,
                rbac_profile=?, active=? WHERE guild_id=? AND id=?
            """,
            (
                body.name.strip(),
                body.prefix.strip(),
                body.level,
                profile,
                int(body.active),
                actor.guild_id,
                rank_id,
            ),
        )
        await services.settings.set_rank_role_mapping(
            actor.guild_id,
            rank_id,
            body.discord_role_id,
            actor.discord_id,
            enabled=body.active,
            connection=connection,
        )
        cursor = await connection.execute(
            "SELECT * FROM ranks WHERE guild_id=? AND id=?", (actor.guild_id, rank_id)
        )
        after = await cursor.fetchone()
        reconciliation = await _enqueue_identity_reconciliation(
            connection,
            guild_id=actor.guild_id,
            requested_by=actor.discord_id,
            mode="APPLY",
            source="LEGACY_RANK_ADAPTER_CHANGED",
        )
        await services.audit.record(
            actor.guild_id,
            "WEB_RANK_SETTING_CHANGED",
            actor_id=actor.discord_id,
            before=plain(before),
            after={
                **plain(after),
                "request_id": actor.correlation_id,
            },
            connection=connection,
        )
    await services.permissions.invalidate(actor.guild_id)
    return plain({"rank": after, "reconciliation": reconciliation})


@app.post("/v1/maintenance/{module_key}")
async def maintenance(
    request: Request,
    module_key: str,
    body: MaintenanceBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "maintenance.manage")
    await request.app.state.services.operations.set_maintenance(
        actor.guild_id,
        module_key.upper(),
        body.active,
        actor.discord_id,
        reason=body.reason,
        expected_end_at=body.expected_end_at,
    )
    return {"module": module_key.upper(), "active": body.active}


@app.get("/v1/recruitment/current")
async def recruitment_current(request: Request, caller: Internal) -> Any:
    services = request.app.state.services
    await services.recruitment.ensure_defaults(caller.guild_id)
    await services.recruitment_analysis.ensure_defaults(caller.guild_id)
    campaign = await services.recruitment.current_campaign(caller.guild_id)
    if not campaign:
        return {"campaign": None}
    public_fields = {
        key: campaign[key]
        for key in (
            "id",
            "public_id",
            "name",
            "status",
            "opens_at",
            "closes_at",
            "minimum_age",
            "maximum_applications",
        )
    }
    return {"campaign": plain(public_fields)}


@app.get("/v1/recruitment/eligibility")
async def recruitment_eligibility(request: Request, candidate: Candidate) -> Any:
    await request.app.state.services.recruitment.ensure_defaults(candidate.guild_id)
    await request.app.state.services.recruitment_analysis.ensure_defaults(candidate.guild_id)
    result = await request.app.state.services.recruitment.eligibility(
        candidate.guild_id, candidate.discord_id
    )
    if result.get("campaign"):
        result["campaign"] = {
            key: result["campaign"][key]
            for key in (
                "id",
                "public_id",
                "name",
                "status",
                "opens_at",
                "closes_at",
                "minimum_age",
                "maximum_applications",
            )
        }
    return plain(result)


@app.post("/v1/recruitment/applications/start")
async def recruitment_start_application(
    request: Request, body: RecruitmentStartBody, candidate: Candidate
) -> Any:
    await request.app.state.services.recruitment.ensure_defaults(candidate.guild_id)
    await request.app.state.services.recruitment_analysis.ensure_defaults(candidate.guild_id)
    return plain(
        await request.app.state.services.recruitment.start_application(
            candidate.guild_id,
            candidate.discord_id,
            discord_username=candidate.username,
            discord_global_name=candidate.global_name,
            discord_avatar=candidate.avatar,
            candidate_nick=body.candidate_nick,
            bgr_id=body.bgr_id,
            age=body.age,
            idempotency_key=body.idempotency_key,
            consent_accepted=body.consent_accepted,
            guild_membership_verified=candidate.guild_verified,
        )
    )


@app.get("/v1/me/recruitment/application")
async def recruitment_my_application(request: Request, candidate: Candidate) -> Any:
    return plain(
        await request.app.state.services.recruitment.my_application(
            candidate.guild_id, candidate.discord_id
        )
    )


@app.get("/v1/recruitment/applications/{application_id}/next-question")
async def recruitment_next_question(
    request: Request, application_id: int, candidate: Candidate
) -> Any:
    return plain(
        await request.app.state.services.recruitment.next_question(
            candidate.guild_id, candidate.discord_id, application_id
        )
    )


@app.post("/v1/recruitment/applications/{application_id}/questions/{question_id}/start")
async def recruitment_start_question(
    request: Request, application_id: int, question_id: int, candidate: Candidate
) -> Any:
    return plain(
        await request.app.state.services.recruitment.start_question(
            candidate.guild_id, candidate.discord_id, application_id, question_id
        )
    )


@app.patch("/v1/recruitment/applications/{application_id}/questions/{question_id}/autosave")
async def recruitment_autosave_question(
    request: Request,
    application_id: int,
    question_id: int,
    body: RecruitmentQuestionBody,
    candidate: Candidate,
) -> Any:
    return plain(
        await request.app.state.services.recruitment.save_answer(
            candidate.guild_id,
            candidate.discord_id,
            application_id,
            question_id,
            answer=body.answer,
            question_token=body.question_token,
            submit=False,
        )
    )


@app.post("/v1/recruitment/applications/{application_id}/questions/{question_id}/submit")
async def recruitment_submit_question(
    request: Request,
    application_id: int,
    question_id: int,
    body: RecruitmentQuestionBody,
    candidate: Candidate,
) -> Any:
    return plain(
        await request.app.state.services.recruitment.save_answer(
            candidate.guild_id,
            candidate.discord_id,
            application_id,
            question_id,
            answer=body.answer,
            question_token=body.question_token,
            submit=True,
        )
    )


@app.post("/v1/recruitment/applications/{application_id}/questions/{question_id}/integrity")
async def recruitment_integrity_event(
    request: Request,
    application_id: int,
    question_id: int,
    body: RecruitmentIntegrityBody,
    candidate: Candidate,
) -> Any:
    await request.app.state.services.recruitment.record_integrity_event(
        candidate.guild_id,
        candidate.discord_id,
        application_id,
        question_id,
        body.event_type,
        duration_ms=body.duration_ms,
    )
    return {"recorded": True}


@app.post("/v1/recruitment/applications/{application_id}/submit")
async def recruitment_submit_application(
    request: Request,
    application_id: int,
    body: RecruitmentSubmitBody,
    candidate: Candidate,
) -> Any:
    return plain(
        await request.app.state.services.recruitment.submit_application(
            candidate.guild_id,
            candidate.discord_id,
            application_id,
            body.expected_version,
        )
    )


@app.post("/v1/recruitment/applications/{application_id}/withdraw")
async def recruitment_withdraw_application(
    request: Request,
    application_id: int,
    body: RecruitmentSubmitBody,
    candidate: Candidate,
) -> Any:
    return plain(
        await request.app.state.services.recruitment.withdraw_application(
            candidate.guild_id,
            candidate.discord_id,
            application_id,
            body.expected_version,
        )
    )


@app.get("/v1/admin/recruitment/applications")
async def recruitment_admin_applications(
    request: Request,
    actor: Actor,
    status_filter: str | None = Query(default=None, alias="status"),
    search: str = Query(default="", max_length=100),
) -> Any:
    require_permission(actor, "recruitment.view")
    applications, statistics = await asyncio.gather(
        request.app.state.services.recruitment.list_applications(
            actor.guild_id, status=status_filter, search=search
        ),
        request.app.state.services.recruitment.statistics(actor.guild_id),
    )
    return plain({"applications": applications, "statistics": statistics})


@app.get("/v1/admin/recruitment/applications/{application_id}")
async def recruitment_admin_dossier(request: Request, application_id: int, actor: Actor) -> Any:
    require_permission(actor, "recruitment.read")
    dossier = await request.app.state.services.recruitment.application_dossier(
        actor.guild_id, application_id
    )
    if not actor.can("recruitment.integrity.read"):
        dossier.pop("integrity", None)
    if not actor.can("recruitment.notes.read"):
        dossier.pop("notes", None)
    if actor.can("recruitment.ai.read"):
        dossier[
            "automated_analysis"
        ] = await request.app.state.services.recruitment_analysis.dossier(
            actor.guild_id, application_id
        )
    return plain(dossier)


@app.post("/v1/admin/recruitment/applications/{application_id}/assign")
async def recruitment_admin_assign(
    request: Request,
    application_id: int,
    body: RecruitmentAssignBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.assign")
    return plain(
        await request.app.state.services.recruitment.assign(
            actor.guild_id, application_id, actor.discord_id, body.expected_version
        )
    )


@app.post("/v1/admin/recruitment/applications/{application_id}/interview")
async def recruitment_admin_interview(
    request: Request,
    application_id: int,
    body: RecruitmentInterviewBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.interview")
    return plain(
        await request.app.state.services.recruitment.schedule_interview(
            actor.guild_id,
            application_id,
            actor.discord_id,
            body.expected_version,
            body.scheduled_at,
            body.interviewer_id,
            body.notes,
        )
    )


@app.post("/v1/admin/recruitment/applications/{application_id}/evaluate")
async def recruitment_admin_evaluate(
    request: Request,
    application_id: int,
    body: RecruitmentEvaluationBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.evaluate")
    return plain(
        await request.app.state.services.recruitment.evaluate_interview(
            actor.guild_id,
            application_id,
            body.interview_id,
            actor.discord_id,
            body.expected_version,
            communication=body.communication,
            posture=body.posture,
            knowledge=body.knowledge,
            discipline=body.discipline,
            result=body.result,
            observation=body.observation,
        )
    )


@app.post("/v1/admin/recruitment/applications/{application_id}/approve")
async def recruitment_admin_approve(
    request: Request,
    application_id: int,
    body: RecruitmentDecisionBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.approve")
    return plain(
        await request.app.state.services.recruitment.decide(
            actor.guild_id,
            application_id,
            actor.discord_id,
            body.expected_version,
            approved=True,
            internal_reason=body.internal_reason,
            candidate_message=body.candidate_message,
        )
    )


@app.post("/v1/admin/recruitment/applications/{application_id}/reject")
async def recruitment_admin_reject(
    request: Request,
    application_id: int,
    body: RecruitmentDecisionBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.reject")
    return plain(
        await request.app.state.services.recruitment.decide(
            actor.guild_id,
            application_id,
            actor.discord_id,
            body.expected_version,
            approved=False,
            internal_reason=body.internal_reason,
            candidate_message=body.candidate_message,
        )
    )


@app.post("/v1/admin/recruitment/applications/{application_id}/notes")
async def recruitment_admin_note(
    request: Request,
    application_id: int,
    body: RecruitmentNoteBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.notes.create")
    note_id = await request.app.state.services.recruitment.add_note(
        actor.guild_id, application_id, actor.discord_id, body.note
    )
    return {"id": note_id}


@app.post("/v1/admin/recruitment/applications/{application_id}/adaptations")
async def recruitment_admin_adaptation(
    request: Request,
    application_id: int,
    body: RecruitmentAdaptationBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.adaptation.manage")
    adaptation_id = await request.app.state.services.recruitment.add_adaptation(
        actor.guild_id,
        application_id,
        actor.discord_id,
        extra_time_percent=body.extra_time_percent,
        clipboard_adapted=body.clipboard_adapted,
        alternative_format=body.alternative_format,
        reason=body.reason,
    )
    return {"id": adaptation_id}


@app.get("/v1/admin/recruitment/blocks")
async def recruitment_admin_blocks(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.block.manage")
    return plain(await request.app.state.services.recruitment.list_blocks(actor.guild_id))


@app.post("/v1/admin/recruitment/blocks")
async def recruitment_admin_create_block(
    request: Request, body: RecruitmentBlockBody, actor: Actor
) -> Any:
    require_permission(actor, "recruitment.block.manage")
    block_id = await request.app.state.services.recruitment.block_candidate(
        actor.guild_id,
        actor.discord_id,
        discord_id=body.discord_id,
        bgr_id=body.bgr_id,
        reason=body.reason,
    )
    return {"id": block_id}


@app.delete("/v1/admin/recruitment/blocks/{block_id}")
async def recruitment_admin_revoke_block(request: Request, block_id: int, actor: Actor) -> Any:
    require_permission(actor, "recruitment.block.manage")
    await request.app.state.services.recruitment.revoke_block(
        actor.guild_id, block_id, actor.discord_id
    )
    return {"revoked": True}


@app.get("/v1/admin/recruitment/campaign")
async def recruitment_admin_campaign(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.campaign.manage")
    await request.app.state.services.recruitment.ensure_defaults(actor.guild_id, actor.discord_id)
    return plain(await request.app.state.services.recruitment.current_campaign(actor.guild_id))


@app.get("/v1/admin/recruitment/resources")
async def recruitment_admin_resources(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.campaign.manage")
    ranks, roles, voice_channels = await asyncio.gather(
        request.app.state.services.database.fetchall(
            "SELECT id, name, prefix, level FROM ranks WHERE guild_id=? AND active=1 ORDER BY level",
            (actor.guild_id,),
        ),
        request.app.state.services.database.fetchall(
            """
            SELECT resource_id, name FROM discord_resource_registry
            WHERE guild_id=? AND resource_type='ROLE' AND active=1 ORDER BY position DESC
            """,
            (actor.guild_id,),
        ),
        request.app.state.services.database.fetchall(
            """
            SELECT resource_id, name FROM discord_resource_registry
            WHERE guild_id=? AND resource_type='VOICE_CHANNEL' AND active=1 ORDER BY position
            """,
            (actor.guild_id,),
        ),
    )
    return plain({"ranks": ranks, "roles": roles, "voice_channels": voice_channels})


@app.put("/v1/admin/recruitment/campaign/{campaign_id}")
async def recruitment_admin_update_campaign(
    request: Request,
    campaign_id: int,
    body: RecruitmentCampaignBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.campaign.manage")
    if body.initial_rank_id is not None:
        rank = await request.app.state.services.database.fetchone(
            "SELECT 1 FROM ranks WHERE guild_id=? AND id=? AND active=1",
            (actor.guild_id, body.initial_rank_id),
        )
        if not rank:
            raise HTTPException(422, "Patente inicial não pertence a esta guild.")
    if body.candidate_role_id is not None:
        role = await request.app.state.services.database.fetchone(
            """
            SELECT 1 FROM discord_resource_registry
            WHERE guild_id=? AND resource_id=? AND resource_type='ROLE' AND active=1
            """,
            (actor.guild_id, body.candidate_role_id),
        )
        if not role:
            raise HTTPException(422, "Cargo temporário não encontrado no registry Discord.")
    if body.interview_channel_id is not None:
        channel = await request.app.state.services.database.fetchone(
            """
            SELECT 1 FROM discord_resource_registry
            WHERE guild_id=? AND resource_id=? AND resource_type='VOICE_CHANNEL' AND active=1
            """,
            (actor.guild_id, body.interview_channel_id),
        )
        if not channel:
            raise HTTPException(422, "Call de entrevista não encontrada no registry Discord.")
    return plain(
        await request.app.state.services.recruitment.update_campaign(
            actor.guild_id, campaign_id, actor.discord_id, body.model_dump()
        )
    )


@app.get("/v1/admin/recruitment/questions")
async def recruitment_admin_questions(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.form.manage")
    await request.app.state.services.recruitment.ensure_defaults(actor.guild_id, actor.discord_id)
    return plain(await request.app.state.services.recruitment.questions_for_admin(actor.guild_id))


@app.get("/v1/admin/recruitment/question-groups")
async def recruitment_admin_question_groups(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.form.manage")
    await request.app.state.services.recruitment.ensure_defaults(actor.guild_id, actor.discord_id)
    return plain(await request.app.state.services.recruitment.groups_for_admin(actor.guild_id))


@app.post("/v1/admin/recruitment/questions")
async def recruitment_admin_create_question(
    request: Request,
    body: RecruitmentQuestionCreateBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.form.manage")
    return plain(
        await request.app.state.services.recruitment.create_question(
            actor.guild_id, actor.discord_id, body.model_dump()
        )
    )


@app.put("/v1/admin/recruitment/questions/{question_id}")
async def recruitment_admin_update_question(
    request: Request,
    question_id: int,
    body: RecruitmentQuestionAdminBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.form.manage")
    return plain(
        await request.app.state.services.recruitment.update_question(
            actor.guild_id, question_id, actor.discord_id, body.model_dump()
        )
    )


@app.put("/v1/admin/recruitment/question-groups/{group_id}")
async def recruitment_admin_update_question_group(
    request: Request,
    group_id: int,
    body: RecruitmentQuestionGroupBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.form.manage")
    return plain(
        await request.app.state.services.recruitment.update_group(
            actor.guild_id, group_id, actor.discord_id, body.model_dump()
        )
    )


@app.post("/v1/admin/recruitment/form/publish")
async def recruitment_admin_publish_form(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.form.manage")
    version_id = await request.app.state.services.recruitment.publish_form(
        actor.guild_id, actor.discord_id
    )
    return {"form_version_id": version_id}


@app.get("/v1/admin/recruitment/ai/config")
async def recruitment_ai_configuration(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(
        await request.app.state.services.recruitment_analysis.configuration(actor.guild_id)
    )


@app.put("/v1/admin/recruitment/ai/config")
async def recruitment_ai_update_configuration(
    request: Request, body: RecruitmentAiConfigurationBody, actor: Actor
) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(
        await request.app.state.services.recruitment_analysis.update_configuration(
            actor.guild_id, actor.discord_id, body.model_dump()
        )
    )


@app.get("/v1/admin/recruitment/ai/rubric")
async def recruitment_ai_rubric(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(await request.app.state.services.recruitment_analysis.rubric(actor.guild_id))


@app.post("/v1/admin/recruitment/ai/rubric/draft")
async def recruitment_ai_create_rubric_draft(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(
        await request.app.state.services.recruitment_analysis.create_rubric_draft(
            actor.guild_id, actor.discord_id
        )
    )


@app.put("/v1/admin/recruitment/ai/rubric/{rubric_id}")
async def recruitment_ai_update_rubric(
    request: Request,
    rubric_id: int,
    body: RecruitmentAiRubricBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(
        await request.app.state.services.recruitment_analysis.update_rubric_draft(
            actor.guild_id,
            actor.discord_id,
            rubric_id,
            [item.model_dump() for item in body.criteria],
            {
                "review_min": body.review_min,
                "recommended_min": body.recommended_min,
                "show_score": body.show_score,
            },
        )
    )


@app.post("/v1/admin/recruitment/ai/rubric/{rubric_id}/publish")
async def recruitment_ai_publish_rubric(request: Request, rubric_id: int, actor: Actor) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(
        await request.app.state.services.recruitment_analysis.publish_rubric(
            actor.guild_id, actor.discord_id, rubric_id
        )
    )


@app.post("/v1/admin/recruitment/ai/rubric/preview")
async def recruitment_ai_preview_rubric(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(
        await request.app.state.services.recruitment_analysis.preview_rubric(actor.guild_id)
    )


@app.get("/v1/admin/recruitment/ai/quality")
async def recruitment_ai_quality(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(
        await request.app.state.services.recruitment_analysis.quality_report(actor.guild_id)
    )


@app.get("/v1/admin/recruitment/ai/context")
async def recruitment_ai_context(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(await request.app.state.services.recruitment_analysis.context(actor.guild_id))


@app.post("/v1/admin/recruitment/ai/context/draft")
async def recruitment_ai_create_context_draft(request: Request, actor: Actor) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(
        await request.app.state.services.recruitment_analysis.create_context_draft(
            actor.guild_id, actor.discord_id
        )
    )


@app.put("/v1/admin/recruitment/ai/context/{context_id}")
async def recruitment_ai_update_context(
    request: Request,
    context_id: int,
    body: RecruitmentAiContextBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(
        await request.app.state.services.recruitment_analysis.update_context_draft(
            actor.guild_id, actor.discord_id, context_id, body.model_dump()
        )
    )


@app.post("/v1/admin/recruitment/ai/context/{context_id}/publish")
async def recruitment_ai_publish_context(request: Request, context_id: int, actor: Actor) -> Any:
    require_permission(actor, "recruitment.ai.config")
    return plain(
        await request.app.state.services.recruitment_analysis.publish_context(
            actor.guild_id, actor.discord_id, context_id
        )
    )


@app.post("/v1/admin/recruitment/applications/{application_id}/analysis/reanalyze")
async def recruitment_ai_reanalyze(
    request: Request,
    application_id: int,
    body: RecruitmentAiReanalysisBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.ai.reanalyze")
    job_id = await request.app.state.services.recruitment_analysis.enqueue(
        actor.guild_id,
        application_id,
        requested_by=actor.discord_id,
        request_reason="MANUAL",
        analysis_type=body.analysis_type,
    )
    return {"job_id": job_id, "status": "PENDING"}


@app.post("/v1/admin/recruitment/analysis/{result_id}/feedback")
async def recruitment_ai_feedback(
    request: Request,
    result_id: int,
    body: RecruitmentAiFeedbackBody,
    actor: Actor,
) -> Any:
    require_permission(actor, "recruitment.ai.read")
    feedback_id = await request.app.state.services.recruitment_analysis.record_feedback(
        actor.guild_id,
        result_id,
        actor.discord_id,
        body.usefulness,
        body.note,
    )
    return {"id": feedback_id}


@app.get("/v1/sync/{correlation_id}")
async def sync_status(request: Request, correlation_id: str, actor: Actor) -> Any:
    row = await request.app.state.services.database.fetchone(
        """
        SELECT correlation_id, action_type, target_discord_id, requested_by,
               status, attempts, created_at, processed_at, last_error
        FROM web_action_outbox WHERE guild_id=? AND correlation_id=?
        """,
        (actor.guild_id, correlation_id),
    )
    if not row:
        raise HTTPException(404, "Sincronização não encontrada.")
    if int(row["requested_by"]) != actor.discord_id and not actor.can("identity.reconcile"):
        raise HTTPException(404, "Sincronização não encontrada.")
    return plain(row)
