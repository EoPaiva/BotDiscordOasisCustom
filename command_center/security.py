from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from urllib.parse import unquote

from fastapi import Header, HTTPException, Request, status

LOGGER = logging.getLogger(__name__)
SIGNATURE_VERSION = "choque-v1"
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
COMMAND_CENTER_PROFILES = frozenset({"COMANDO", "ALTO_COMANDO", "ADMINISTRADOR"})
COMMAND_CENTER_ENTRY_PERMISSIONS = frozenset({"officer.review"})


@dataclass(frozen=True, slots=True)
class WebActor:
    guild_id: int
    discord_id: int
    member_id: int
    profile: str
    profile_name: str
    permissions: frozenset[str]
    authorization_version: int
    rank_id: int | None
    primary_position_id: int | None
    primary_position_code: str | None
    primary_position_name: str | None
    functions: tuple[dict[str, object], ...]
    discord_roles_synced_at: int | None
    identity_sync_status: str
    discord_present: bool
    technical_bootstrap: bool
    correlation_id: str
    session_issued_at: int

    def can(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    guild_id: int
    discord_id: int
    username: str
    global_name: str | None
    avatar: str | None
    correlation_id: str
    guild_verified: bool


@dataclass(frozen=True, slots=True)
class InternalCaller:
    guild_id: int
    correlation_id: str


def _configured_secret() -> str:
    return os.getenv("COMMAND_CENTER_INTERNAL_SECRET", "")


def _admin_ids() -> set[int]:
    if os.getenv("APP_ENV") == "production" and os.getenv(
        "WEB_ADMIN_BOOTSTRAP_ENABLED", ""
    ).lower() not in {"1", "true", "yes"}:
        return set()
    result: set[int] = set()
    for item in os.getenv("WEB_ADMIN_DISCORD_IDS", "").split(","):
        value = item.strip()
        if value.isdigit():
            result.add(int(value))
    return result


def fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    salt = os.getenv("WEB_AUDIT_HASH_SALT") or _configured_secret()
    if not salt:
        return None
    return hmac.new(salt.encode(), value.encode(), hashlib.sha256).hexdigest()


async def authenticate_request(
    request: Request,
    x_internal_secret: str = Header(default=""),
    x_request_signature: str = Header(default=""),
    x_request_timestamp: str = Header(default=""),
    x_request_nonce: str = Header(default=""),
    x_session_issued_at: str = Header(default=""),
    x_discord_guild_verified: str = Header(default=""),
    x_actor_discord_id: str = Header(default=""),
    x_guild_id: str = Header(default=""),
    x_correlation_id: str = Header(default=""),
) -> WebActor:
    if not x_actor_discord_id.isdigit() or not x_guild_id.isdigit():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identidade web inválida.")
    guild_id, correlation_id, issued_at = await _authenticate_internal(
        request,
        x_internal_secret=x_internal_secret,
        x_request_signature=x_request_signature,
        x_request_timestamp=x_request_timestamp,
        x_request_nonce=x_request_nonce,
        x_session_issued_at=x_session_issued_at,
        x_actor_discord_id=x_actor_discord_id,
        x_guild_id=x_guild_id,
        x_correlation_id=x_correlation_id,
        x_discord_username=request.headers.get("x-discord-username", ""),
        x_discord_global_name=request.headers.get("x-discord-global-name", ""),
        x_discord_avatar=request.headers.get("x-discord-avatar", ""),
        x_discord_guild_verified=x_discord_guild_verified,
    )
    if issued_at <= 0:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão web inválida.")
    if x_discord_guild_verified.lower() != "true":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito ao servidor oficial.")
    discord_id, guild_id = int(x_actor_discord_id), int(x_guild_id)
    services = request.app.state.services
    access = await services.permissions.resolve_member_access(guild_id, discord_id)
    technical_bootstrap = discord_id in _admin_ids()
    if not access or access.member_status in {"DISMISSED", "SUSPENDED"}:
        await _record_access(request, guild_id, discord_id, "AUTH", "DENIED")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito ao efetivo cadastrado.")
    # The bootstrap list can elevate an already-authorized administrator, but it
    # must never keep a former guild member inside the Command Center. Presence
    # is resolved afresh from the identity projection on every request.
    if not access.discord_present:
        await _record_access(request, guild_id, discord_id, "AUTH", "DENIED")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Vínculo atual com o Discord não confirmado.")
    if not await services.security.session_allowed(guild_id, discord_id, issued_at):
        await _record_access(request, guild_id, discord_id, "AUTH", "DENIED")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão revogada. Entre novamente.")
    has_scoped_command_access = any(
        access.can(permission) for permission in COMMAND_CENTER_ENTRY_PERMISSIONS
    )
    if (
        not technical_bootstrap
        and access.profile not in COMMAND_CENTER_PROFILES
        and not has_scoped_command_access
    ):
        await _record_access(request, guild_id, discord_id, "AUTH", "DENIED")
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Centro de Comando restrito ao Comando e Alto Comando.",
        )
    permissions = frozenset({"*"}) if technical_bootstrap else access.permissions
    profile = "ADMINISTRADOR" if technical_bootstrap else access.profile
    profile_name = "Administrador técnico" if technical_bootstrap else access.profile_name
    actor = WebActor(
        guild_id=guild_id,
        discord_id=discord_id,
        member_id=access.member_id,
        profile=profile,
        profile_name=profile_name,
        permissions=permissions,
        authorization_version=access.authorization_version,
        rank_id=access.rank_id,
        primary_position_id=access.primary_position_id,
        primary_position_code=access.primary_position_code,
        primary_position_name=access.primary_position_name,
        functions=access.functions,
        discord_roles_synced_at=access.discord_roles_synced_at,
        identity_sync_status=access.identity_sync_status,
        discord_present=access.discord_present,
        technical_bootstrap=technical_bootstrap,
        correlation_id=correlation_id,
        session_issued_at=issued_at,
    )
    request.state.actor = actor
    if _is_sensitive_mutation(request):
        step_up_seconds = max(
            300, min(int(os.getenv("WEB_STEP_UP_MAX_AGE_SECONDS", "1800")), 7200)
        )
        if int(time.time()) - issued_at > step_up_seconds:
            await services.security.record(
                guild_id,
                "SECURITY_AUTH_FAILED",
                severity="MEDIUM",
                result="DENIED",
                source="API",
                actor_id=discord_id,
                route=request.url.path,
                request_id=correlation_id,
                metadata={"reason": "STEP_UP_REQUIRED"},
            )
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Autenticação recente necessária. Entre novamente.",
            )
    if _is_sensitive_mutation(request) and not request.url.path.startswith("/v1/security/"):
        lockdown = await services.security.lockdown(guild_id)
        if lockdown["active"]:
            await services.security.record(
                guild_id,
                "SECURITY_REQUEST_REJECTED",
                severity="HIGH",
                result="BLOCKED",
                source="API",
                actor_id=discord_id,
                route=request.url.path,
                request_id=correlation_id,
                metadata={"reason": "SECURITY_LOCKDOWN"},
            )
            raise HTTPException(
                status.HTTP_423_LOCKED,
                "Alterações administrativas estão bloqueadas pelo modo de emergência.",
            )
    return actor


def _legacy_auth_allowed() -> bool:
    return os.getenv("APP_ENV") != "production" and os.getenv(
        "COMMAND_CENTER_ALLOW_LEGACY_AUTH", ""
    ).lower() in {"1", "true", "yes"}


def _request_target(request: Request) -> str:
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


def _is_sensitive_mutation(request: Request) -> bool:
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    path = request.url.path
    return path.startswith(
        (
            "/v1/admin/",
            "/v1/settings",
            "/v1/members/",
            "/v1/discord/",
            "/v1/inbox/",
            "/v1/requests/",
            "/v1/maintenance/",
            "/v1/officer-applications/",
        )
    )


async def _security_failure(
    request: Request,
    guild_id: int,
    event_type: str,
    *,
    result: str = "DENIED",
) -> None:
    try:
        await request.app.state.services.security.record(
            guild_id,
            event_type,
            severity="HIGH",
            result=result,
            source="API",
            route=request.url.path,
            request_id=request.headers.get("x-correlation-id") or str(uuid.uuid4()),
        )
    except Exception:
        LOGGER.warning("Falha ao persistir evento de segurança", exc_info=True)


async def _authenticate_internal(
    request: Request,
    *,
    x_internal_secret: str,
    x_request_signature: str,
    x_request_timestamp: str,
    x_request_nonce: str,
    x_session_issued_at: str,
    x_actor_discord_id: str,
    x_guild_id: str,
    x_correlation_id: str,
    x_discord_username: str,
    x_discord_global_name: str,
    x_discord_avatar: str,
    x_discord_guild_verified: str,
) -> tuple[int, str, int]:
    expected = _configured_secret()
    if not x_guild_id.isdigit():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Guild inválida.")
    guild_id = int(x_guild_id)
    correlation_id = (x_correlation_id.strip() or str(uuid.uuid4()))[:100]
    if _legacy_auth_allowed() and expected and hmac.compare_digest(expected, x_internal_secret):
        issued_at = int(time.time()) if not x_session_issued_at.isdigit() else int(
            x_session_issued_at
        )
        return guild_id, correlation_id, issued_at
    if not expected or len(expected) < 32:
        await _security_failure(request, guild_id, "SECURITY_AUTH_FAILED")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Autenticação interna indisponível.")
    if (
        not x_request_timestamp.isdigit()
        or not x_session_issued_at.isdigit()
        or not NONCE_PATTERN.fullmatch(x_request_nonce)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", x_request_signature)
    ):
        await _security_failure(request, guild_id, "SECURITY_AUTH_FAILED")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credencial interna inválida.")
    timestamp = int(x_request_timestamp)
    ttl = max(15, min(int(os.getenv("COMMAND_CENTER_SIGNATURE_TTL_SECONDS", "90")), 300))
    if abs(int(time.time()) - timestamp) > ttl:
        await _security_failure(request, guild_id, "SECURITY_AUTH_FAILED")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credencial interna expirada.")
    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        (
            SIGNATURE_VERSION,
            request.method.upper(),
            _request_target(request),
            body_hash,
            x_guild_id,
            x_actor_discord_id,
            correlation_id,
            x_request_timestamp,
            x_request_nonce,
            x_session_issued_at,
            x_discord_username,
            x_discord_global_name,
            x_discord_avatar,
            x_discord_guild_verified.lower(),
        )
    )
    calculated = hmac.new(expected.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, x_request_signature.lower()):
        await _security_failure(request, guild_id, "SECURITY_AUTH_FAILED")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credencial interna inválida.")
    now_ms = int(time.time() * 1000)
    try:
        async with request.app.state.services.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM internal_request_nonces WHERE expires_at < ?", (now_ms,)
            )
            await connection.execute(
                """
                INSERT INTO internal_request_nonces(
                    nonce, guild_id, request_timestamp, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (x_request_nonce, guild_id, timestamp, now_ms + ttl * 1000, now_ms),
            )
    except sqlite3.IntegrityError as exc:
        await _security_failure(request, guild_id, "SECURITY_REPLAY_BLOCKED", result="BLOCKED")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Request já utilizado.") from exc
    return guild_id, correlation_id, int(x_session_issued_at)


async def authenticate_internal_request(
    request: Request,
    x_internal_secret: str = Header(default=""),
    x_request_signature: str = Header(default=""),
    x_request_timestamp: str = Header(default=""),
    x_request_nonce: str = Header(default=""),
    x_session_issued_at: str = Header(default="0"),
    x_guild_id: str = Header(default=""),
    x_correlation_id: str = Header(default=""),
) -> InternalCaller:
    guild_id, correlation_id, _ = await _authenticate_internal(
        request,
        x_internal_secret=x_internal_secret,
        x_request_signature=x_request_signature,
        x_request_timestamp=x_request_timestamp,
        x_request_nonce=x_request_nonce,
        x_session_issued_at=x_session_issued_at,
        x_actor_discord_id="",
        x_guild_id=x_guild_id,
        x_correlation_id=x_correlation_id,
        x_discord_username="",
        x_discord_global_name="",
        x_discord_avatar="",
        x_discord_guild_verified="false",
    )
    return InternalCaller(guild_id, correlation_id)


async def authenticate_candidate_request(
    request: Request,
    x_internal_secret: str = Header(default=""),
    x_request_signature: str = Header(default=""),
    x_request_timestamp: str = Header(default=""),
    x_request_nonce: str = Header(default=""),
    x_session_issued_at: str = Header(default=""),
    x_actor_discord_id: str = Header(default=""),
    x_guild_id: str = Header(default=""),
    x_correlation_id: str = Header(default=""),
    x_discord_username: str = Header(default=""),
    x_discord_global_name: str = Header(default=""),
    x_discord_avatar: str = Header(default=""),
    x_discord_guild_verified: str = Header(default=""),
) -> CandidateIdentity:
    if not x_actor_discord_id.isdigit():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identidade Discord inválida.")
    guild_id, correlation_id, issued_at = await _authenticate_internal(
        request,
        x_internal_secret=x_internal_secret,
        x_request_signature=x_request_signature,
        x_request_timestamp=x_request_timestamp,
        x_request_nonce=x_request_nonce,
        x_session_issued_at=x_session_issued_at,
        x_actor_discord_id=x_actor_discord_id,
        x_guild_id=x_guild_id,
        x_correlation_id=x_correlation_id,
        x_discord_username=x_discord_username,
        x_discord_global_name=x_discord_global_name,
        x_discord_avatar=x_discord_avatar,
        x_discord_guild_verified=x_discord_guild_verified,
    )
    if issued_at <= 0 or not await request.app.state.services.security.session_allowed(
        guild_id, int(x_actor_discord_id), issued_at
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão revogada. Entre novamente.")
    identity = CandidateIdentity(
        guild_id=guild_id,
        discord_id=int(x_actor_discord_id),
        username=(unquote(x_discord_username.strip()) or f"discord-{x_actor_discord_id}")[:100],
        global_name=unquote(x_discord_global_name.strip())[:100] or None,
        avatar=x_discord_avatar.strip()[:500] or None,
        correlation_id=correlation_id,
        guild_verified=x_discord_guild_verified.lower() == "true",
    )
    request.state.candidate = identity
    return identity


async def verify_candidate_guild_membership(identity: CandidateIdentity) -> bool:
    if (
        os.getenv("APP_ENV") != "production"
        and os.getenv("RECRUITMENT_SKIP_GUILD_MEMBERSHIP_CHECK", "").lower()
        in {"1", "true", "yes"}
    ):
        return True
    return identity.guild_verified


async def _record_access(
    request: Request,
    guild_id: int,
    discord_id: int | None,
    event_type: str,
    result: str,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    user_agent = request.headers.get("user-agent")
    try:
        await request.app.state.services.database.execute(
            """
            INSERT INTO web_access_events(
                guild_id, discord_id, event_type, route, result, correlation_id,
                ip_hash, user_agent_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                discord_id,
                event_type,
                request.url.path,
                result,
                request.headers.get("x-correlation-id") or str(uuid.uuid4()),
                fingerprint(forwarded),
                fingerprint(user_agent),
                int(time.time() * 1000),
            ),
        )
    except Exception:
        return


def require_permission(actor: WebActor, permission: str) -> None:
    if not actor.can(permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permissão insuficiente para esta ação.")
