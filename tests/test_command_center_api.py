from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from choque.audit import AuditService
from choque.config import Branding
from choque.database import Database
from choque.members import MemberService
from choque.rbac import PermissionService
from choque.recruitment import RecruitmentService
from choque.settings import SettingsService
from command_center.app import app, validate_security_configuration

GUILD_ID = 8123
MEMBER_DISCORD_ID = 8456
ADMIN_DISCORD_ID = 8789
INSTRUCTOR_DISCORD_ID = 8790
CANDIDATE_DISCORD_ID = 8801
INTERNAL_SECRET = "test-internal-secret-with-sufficient-entropy"


async def _seed_database(path: Path) -> dict[str, int]:
    database = Database(path)
    await database.open()
    try:
        now = 1_700_000_000_000
        recruit_rank = await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
            VALUES (?, 'Recruta', 'REC', 1, 'MEMBRO', ?)
            """,
            (GUILD_ID, now),
        )
        soldier_rank = await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
            VALUES (?, 'Soldado', 'SD', 2, 'MEMBRO', ?)
            """,
            (GUILD_ID, now),
        )
        command_rank = await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
            VALUES (?, 'Comando', 'CMD', 100, 'COMANDO', ?)
            """,
            (GUILD_ID, now),
        )
        instructor_rank = await database.execute(
            """
            INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
            VALUES (?, 'Instrutor', 'INS', 50, 'INSTRUTOR', ?)
            """,
            (GUILD_ID, now),
        )
        audit = AuditService(database, None, Branding())
        members = MemberService(database, audit)
        member = await members.create_or_update(
            GUILD_ID,
            MEMBER_DISCORD_ID,
            discord_nick="Membro de teste",
            mta_nick="Membro_Teste",
            character_id="10",
            unit="BGR",
            rank_id=recruit_rank,
            actor_id=ADMIN_DISCORD_ID,
        )
        admin = await members.create_or_update(
            GUILD_ID,
            ADMIN_DISCORD_ID,
            discord_nick="Comando de teste",
            mta_nick="Comando_Teste",
            character_id="11",
            unit="BGR",
            rank_id=command_rank,
            actor_id=ADMIN_DISCORD_ID,
        )
        instructor = await members.create_or_update(
            GUILD_ID,
            INSTRUCTOR_DISCORD_ID,
            discord_nick="Instrutor de teste",
            mta_nick="Instrutor_Teste",
            character_id="12",
            unit="BGR",
            rank_id=instructor_rank,
            actor_id=ADMIN_DISCORD_ID,
        )
        permissions = PermissionService(SettingsService(database))
        await permissions.ensure_defaults(GUILD_ID)
        profile_rows = await database.fetchall(
            """
            SELECT id, code FROM access_profiles
            WHERE guild_id=? AND code IN ('MEMBRO', 'INSTRUTOR', 'COMANDO')
            """,
            (GUILD_ID,),
        )
        profile_ids = {
            str(row["code"]): int(row["id"])
            for row in profile_rows
        }
        synced_identities = (
            (member, "MEMBRO", 9_301),
            (admin, "COMANDO", 9_302),
            (instructor, "INSTRUTOR", 9_303),
        )
        for identity, profile_code, source_role_id in synced_identities:
            profile_id = profile_ids[profile_code]
            mapping_id = await database.execute(
                """
                INSERT INTO discord_role_mappings(
                    guild_id, discord_role_id, mapping_type, internal_code,
                    display_name, priority, access_profile_id, enabled,
                    created_at, updated_at, created_by
                ) VALUES (?, ?, 'ACCESS', ?, ?, 0, ?, 1, ?, ?, ?)
                """,
                (
                    GUILD_ID,
                    source_role_id,
                    f"TEST_{profile_code}_ACCESS",
                    f"Perfil {profile_code} de teste",
                    profile_id,
                    now,
                    now,
                    ADMIN_DISCORD_ID,
                ),
            )
            await database.execute(
                """
                INSERT INTO member_access_profiles(
                    member_id, access_profile_id, source_mapping_id,
                    source_role_id, assigned_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    identity["id"],
                    profile_id,
                    mapping_id,
                    source_role_id,
                    now,
                    now,
                ),
            )
            await database.execute(
                """
                UPDATE members
                SET access_profile_id=?, identity_sync_status='SYNCED',
                    identity_sync_error=NULL, discord_present=1,
                    discord_roles_synced_at=?, discord_roles_hash=?
                WHERE id=?
                """,
                (
                    profile_id,
                    now,
                    hashlib.sha256(str(source_role_id).encode()).hexdigest(),
                    identity["id"],
                ),
            )
        recruitment = RecruitmentService(
            database,
            audit,
            token_secret="api-recruitment-secret-with-sufficient-entropy",
        )
        await recruitment.ensure_defaults(GUILD_ID, ADMIN_DISCORD_ID)
        campaign = await recruitment.current_campaign(GUILD_ID)
        assert campaign
        await recruitment.update_campaign(
            GUILD_ID,
            int(campaign["id"]),
            ADMIN_DISCORD_ID,
            {
                "name": campaign["name"],
                "status": "OPEN",
                "opens_at": None,
                "closes_at": None,
                "cooldown_days": 30,
                "minimum_age": 16,
                "maximum_applications": None,
                "initial_rank_id": recruit_rank,
                "candidate_role_id": None,
                "interview_channel_id": None,
            },
        )
        await database.execute(
            """
            INSERT INTO patrol_queue_entries(
                guild_id, member_id, discord_id, status, source, queue_entered_at, updated_at
            ) VALUES (?, ?, ?, 'QUEUED', 'PANEL', ?, ?)
            """,
            (GUILD_ID, member["id"], MEMBER_DISCORD_ID, now, now),
        )
        await database.execute(
            """
            INSERT INTO patrol_queue_entries(
                guild_id, member_id, discord_id, status, source, queue_entered_at, updated_at
            ) VALUES (?, ?, ?, 'QUEUED', 'PANEL', ?, ?)
            """,
            (GUILD_ID, admin["id"], ADMIN_DISCORD_ID, now + 1, now + 1),
        )
        await database.execute(
            """
            INSERT INTO member_applications(
                guild_id, discord_id, mta_nick, status, submitted_at
            ) VALUES (?, 8999, 'Candidato_Teste', 'PENDING', ?)
            """,
            (GUILD_ID, now),
        )
        for resource in (
            (GUILD_ID, 9101, "VOICE_CHANNEL", "Patrulha QA", 1, now),
            (GUILD_ID, 9201, "ROLE", "Instrutores QA", 2, now),
        ):
            await database.execute(
                """
                INSERT INTO discord_resource_registry(
                    guild_id, resource_id, resource_type, name, position, active, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                resource,
            )
        return {
            "member_id": int(member["id"]),
            "soldier_rank": soldier_rank,
        }
    finally:
        await database.close()


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "command-center.db"
    seeded = asyncio.run(_seed_database(database_path))
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("COMMAND_CENTER_INTERNAL_SECRET", INTERNAL_SECRET)
    monkeypatch.setenv("COMMAND_CENTER_ALLOW_LEGACY_AUTH", "true")
    monkeypatch.setenv("WEB_AUDIT_HASH_SALT", "test-audit-salt")
    monkeypatch.setenv("WEB_ADMIN_DISCORD_IDS", str(ADMIN_DISCORD_ID))
    monkeypatch.setenv("RECRUITMENT_SKIP_GUILD_MEMBERSHIP_CHECK", "true")
    monkeypatch.setenv("RECRUITMENT_TOKEN_SECRET", "api-recruitment-secret-with-sufficient-entropy")
    with TestClient(app) as client:
        yield client, database_path, seeded


def _headers(discord_id: int, *, secret: str = INTERNAL_SECRET) -> dict[str, str]:
    return {
        "X-Internal-Secret": secret,
        "X-Actor-Discord-ID": str(discord_id),
        "X-Guild-ID": str(GUILD_ID),
        "X-Correlation-ID": "command-center-test",
        "X-Discord-Username": f"user-{discord_id}",
        "X-Discord-Global-Name": "Usuario de API",
        "X-Discord-Guild-Verified": "true",
    }


def _signed_headers(
    method: str,
    path: str,
    *,
    discord_id: int | None = None,
    body: str = "",
    nonce: str | None = None,
    issued_at: int | None = None,
) -> dict[str, str]:
    correlation_id = str(uuid.uuid4())
    timestamp = int(time.time())
    request_nonce = nonce or str(uuid.uuid4())
    session_issued_at = issued_at or timestamp
    actor = str(discord_id or "")
    username = f"user-{discord_id}" if discord_id else ""
    global_name = "Usuario%20de%20API" if discord_id else ""
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    canonical = "\n".join(
        (
            "choque-v1",
            method.upper(),
            path,
            body_hash,
            str(GUILD_ID),
            actor,
            correlation_id,
            str(timestamp),
            request_nonce,
            str(session_issued_at if discord_id else 0),
            username,
            global_name,
            "",
            "true" if discord_id else "false",
        )
    )
    signature = hmac.new(INTERNAL_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-Guild-ID": str(GUILD_ID),
        "X-Correlation-ID": correlation_id,
        "X-Request-Timestamp": str(timestamp),
        "X-Request-Nonce": request_nonce,
        "X-Request-Signature": signature,
        "X-Session-Issued-At": str(session_issued_at if discord_id else 0),
        "X-Discord-Guild-Verified": "true" if discord_id else "false",
    }
    if discord_id:
        headers.update(
            {
                "X-Actor-Discord-ID": actor,
                "X-Discord-Username": username,
                "X-Discord-Global-Name": global_name,
            }
        )
    return headers


def test_registration_gate_dashboard_configuration_and_review(api_client) -> None:
    client, database_path, _ = api_client
    connection = sqlite3.connect(database_path)
    try:
        now = 1_700_000_100_000
        connection.executemany(
            """
            INSERT INTO discord_resource_registry(
                guild_id, resource_id, resource_type, name, position, active, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (
                (GUILD_ID, 9210, "ROLE", "Aguardando cadastro", 10, now),
                (GUILD_ID, 9211, "ROLE", "Membro", 11, now),
                (GUILD_ID, 9310, "CATEGORY", "Recepção", 1, now),
                (GUILD_ID, 9410, "TEXT_CHANNEL", "Portaria", 1, now),
                (GUILD_ID, 9411, "TEXT_CHANNEL", "Suporte", 2, now),
            ),
        )
        cursor = connection.execute(
            """
            INSERT INTO registration_gate_records(
                guild_id, discord_id, status, access_tier, mta_nick, bgr_id,
                source, sync_status, submitted_at, created_at, updated_at
            ) VALUES (?, 9901, 'PENDING', 'CANDIDATE', 'Visitante_QA', '9901',
                      'SELF_REGISTRATION', 'NOT_REQUIRED', ?, ?, ?)
            """,
            (GUILD_ID, now, now, now),
        )
        registration_id = int(cursor.lastrowid)
        connection.commit()
    finally:
        connection.close()

    assert (
        client.get("/v1/registration-gate", headers=_headers(INSTRUCTOR_DISCORD_ID)).status_code
        == 403
    )
    for payload in (
        {"unregistered_role_id": 9210},
        {"member_role_id": 9211},
        {"registration_onboarding_category_id": 9310},
        {"registration_panel_channel_id": 9410},
        {"registration_support_channel_id": 9411},
        {"registration_gate_enabled": True},
    ):
        response = client.patch(
            "/v1/registration-gate/configuration",
            headers=_headers(ADMIN_DISCORD_ID),
            json=payload,
        )
        assert response.status_code == 200, response.text

    dashboard = client.get("/v1/registration-gate", headers=_headers(ADMIN_DISCORD_ID))
    assert dashboard.status_code == 200
    assert dashboard.json()["counts"]["PENDING"] == 1
    assert dashboard.json()["configuration"]["registration_gate_enabled"] is True

    decision = client.post(
        f"/v1/registration-gate/{registration_id}/decision",
        headers=_headers(ADMIN_DISCORD_ID),
        json={"action": "DENY", "reason": "Identidade de teste negada"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "BLOCKED"


def test_ticket_operations_configuration_is_registry_validated_and_command_only(
    api_client,
) -> None:
    client, database_path, _ = api_client
    connection = sqlite3.connect(database_path)
    try:
        now = 1_700_000_200_000
        connection.executemany(
            """
            INSERT INTO discord_resource_registry(
                guild_id, resource_id, resource_type, name, position, active, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (
                (GUILD_ID, 9221, "ROLE", "Responsável tickets", 10, now),
                (GUILD_ID, 9222, "ROLE", "Bot", 99, now),
                (GUILD_ID, 9321, "CATEGORY", "Tickets ativos", 10, now),
                (GUILD_ID, 9322, "CATEGORY", "Tickets arquivados", 11, now),
                (GUILD_ID, 9421, "TEXT_CHANNEL", "Transcrições", 10, now),
            ),
        )
        connection.execute(
            """
            INSERT INTO guild_settings(
                guild_id, setting_key, value_json, updated_at, updated_by
            ) VALUES (?, 'ticket_bot_role_id', '9222', ?, ?)
            """,
            (GUILD_ID, now, ADMIN_DISCORD_ID),
        )
        connection.commit()
    finally:
        connection.close()

    denied = client.get("/v1/tickets/operations", headers=_headers(MEMBER_DISCORD_ID))
    assert denied.status_code == 403
    for payload in (
        {"ticket_active_category_id": 9321},
        {"ticket_archive_category_id": 9322},
        {"ticket_responsible_role_id": 9221},
        {"ticket_transcript_channel_id": 9421},
        {"ticket_requester_notify_cooldown_seconds": 90},
    ):
        response = client.patch(
            "/v1/tickets/configuration",
            headers=_headers(ADMIN_DISCORD_ID),
            json=payload,
        )
        assert response.status_code == 200, response.text

    invalid = client.patch(
        "/v1/tickets/configuration",
        headers=_headers(ADMIN_DISCORD_ID),
        json={"ticket_active_category_id": 999_999},
    )
    dashboard = client.get("/v1/tickets/operations", headers=_headers(ADMIN_DISCORD_ID))
    assert invalid.status_code == 422
    assert dashboard.status_code == 200
    assert dashboard.json()["validation"] == {
        "ready": True,
        "hierarchy_valid": True,
        "blockers": [],
    }
    assert dashboard.json()["configuration"]["ticket_requester_notify_cooldown_seconds"] == 90


def test_signed_requests_block_replay_and_tampering(api_client, monkeypatch) -> None:
    client, database_path, _ = api_client
    monkeypatch.delenv("COMMAND_CENTER_ALLOW_LEGACY_AUTH")
    headers = _signed_headers("GET", "/v1/context", discord_id=ADMIN_DISCORD_ID)
    assert client.get("/v1/context", headers=headers).status_code == 200
    replay = client.get("/v1/context", headers=headers)
    assert replay.status_code == 401

    expected_body = json.dumps({"active": True}, separators=(",", ":"))
    tampered_headers = _signed_headers(
        "POST", "/v1/security/lockdown", discord_id=ADMIN_DISCORD_ID, body=expected_body
    )
    tampered = client.post(
        "/v1/security/lockdown",
        headers={**tampered_headers, "Content-Type": "application/json"},
        content=json.dumps(
            {"active": True, "reason": "Motivo suficientemente longo", "confirmation": "BLOQUEAR"},
            separators=(",", ":"),
        ),
    )
    assert tampered.status_code == 401
    connection = sqlite3.connect(database_path)
    try:
        blocked = connection.execute(
            "SELECT COUNT(*) FROM security_events WHERE event_type='SECURITY_REPLAY_BLOCKED'"
        ).fetchone()[0]
        assert blocked == 1
    finally:
        connection.close()


def test_security_lockdown_session_revocation_and_mass_assignment(api_client, monkeypatch) -> None:
    client, _, _ = api_client
    monkeypatch.delenv("COMMAND_CENTER_ALLOW_LEGACY_AUTH")
    member_session_issued_at = int(time.time()) - 1
    revoke_body = json.dumps(
        {
            "discord_id": MEMBER_DISCORD_ID,
            "reason": "Sessão comprometida no cenário de teste",
            "confirmation": "REVOGAR USUARIO",
        },
        separators=(",", ":"),
    )
    revoke_headers = _signed_headers(
        "POST",
        "/v1/security/sessions/revoke",
        discord_id=ADMIN_DISCORD_ID,
        body=revoke_body,
    )
    revoked = client.post(
        "/v1/security/sessions/revoke",
        headers={**revoke_headers, "Content-Type": "application/json"},
        content=revoke_body,
    )
    assert revoked.status_code == 200
    denied = client.get(
        "/v1/context",
        headers=_signed_headers(
            "GET",
            "/v1/context",
            discord_id=MEMBER_DISCORD_ID,
            issued_at=member_session_issued_at,
        ),
    )
    assert denied.status_code == 401

    invalid_body = json.dumps(
        {
            "active": True,
            "reason": "Contenção controlada para teste",
            "confirmation": "BLOQUEAR",
            "role": "SUPER_ADMIN",
        },
        separators=(",", ":"),
    )
    invalid_headers = _signed_headers(
        "POST", "/v1/security/lockdown", discord_id=ADMIN_DISCORD_ID, body=invalid_body
    )
    invalid = client.post(
        "/v1/security/lockdown",
        headers={**invalid_headers, "Content-Type": "application/json"},
        content=invalid_body,
    )
    assert invalid.status_code == 422


def test_internal_credential_is_mandatory(api_client) -> None:
    client, _, _ = api_client
    response = client.get("/v1/context", headers=_headers(MEMBER_DISCORD_ID, secret="wrong"))
    assert response.status_code == 401


def test_api_security_headers_origin_and_body_limits(api_client) -> None:
    client, _, _ = api_client
    health = client.get("/health")
    assert health.json() == {"status": "ok"}
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
    assert health.headers["cache-control"] == "no-store"
    blocked_origin = client.post(
        "/v1/security/lockdown",
        headers={**_headers(ADMIN_DISCORD_ID), "Origin": "https://attacker.invalid"},
        json={"active": True, "reason": "Motivo válido para o teste", "confirmation": "BLOQUEAR"},
    )
    assert blocked_origin.status_code == 403
    oversized = client.post(
        "/v1/security/lockdown",
        headers={**_headers(ADMIN_DISCORD_ID), "Content-Length": str(300 * 1024)},
        content=b"{}",
    )
    assert oversized.status_code == 413


def test_healthcheck_bypasses_only_the_platform_host_probe(api_client) -> None:
    client, _, _ = api_client
    untrusted_host = {"Host": "railway-healthcheck.internal"}

    health = client.get("/health", headers=untrusted_host)
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert health.headers["x-content-type-options"] == "nosniff"

    protected = client.get("/v1/context", headers=untrusted_host)
    assert protected.status_code == 400


def test_production_security_configuration_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("COMMAND_CENTER_INTERNAL_SECRET", "short")
    with pytest.raises(RuntimeError, match="COMMAND_CENTER_INTERNAL_SECRET"):
        validate_security_configuration()

    monkeypatch.setenv("COMMAND_CENTER_INTERNAL_SECRET", "a" * 32)
    monkeypatch.setenv("WEB_AUDIT_HASH_SALT", "b" * 32)
    monkeypatch.setenv("RECRUITMENT_TOKEN_SECRET", "c" * 32)
    monkeypatch.setenv("WEB_ALLOWED_ORIGINS", "https://painel.example.test")
    monkeypatch.setenv("WEB_ALLOWED_HOSTS", "api.example.test")
    validate_security_configuration()


def test_member_cannot_access_command_center_dashboard(api_client) -> None:
    client, _, _ = api_client
    response = client.get("/v1/dashboard", headers=_headers(MEMBER_DISCORD_ID))
    assert response.status_code == 403
    assert "Centro de Comando" in response.json()["detail"]


def test_command_center_access_matrix_is_server_authoritative(api_client) -> None:
    """URLs and API calls stay closed even when a caller bypasses the web menu."""

    client, database_path, _ = api_client

    # No browser session / signed server context cannot read a protected endpoint.
    assert client.get("/v1/me").status_code == 401

    # A Discord identity that is not an active Choque member never gets a portal context.
    outsider = client.get("/v1/me", headers=_headers(9_999_991))
    assert outsider.status_code == 403
    assert "member" not in outsider.text.lower()

    # A regular member and a non-command role cannot disclose data through direct URLs
    # nor mutate a member by calling the API directly.
    for discord_id in (MEMBER_DISCORD_ID, INSTRUCTOR_DISCORD_ID):
        assert client.get("/v1/me", headers=_headers(discord_id)).status_code == 403
        assert client.get("/v1/members", headers=_headers(discord_id)).status_code == 403
        assert (
            client.post(
                f"/v1/members/{MEMBER_DISCORD_ID}/rank",
                headers=_headers(discord_id),
                json={"target_rank_id": 1, "action": "PROMOTION", "reason": "Forjado"},
            ).status_code
            == 403
        )

    # An active command member is admitted by the backend, not by the client navigation.
    assert client.get("/v1/me", headers=_headers(ADMIN_DISCORD_ID)).status_code == 200
    assert client.get("/v1/dashboard", headers=_headers(ADMIN_DISCORD_ID)).status_code == 200

    # Loss of guild presence invalidates access immediately on the next server request,
    # including for the configured technical administrator in a development fixture.
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE members
            SET discord_present=0, identity_sync_status='DISCORD_ABSENT',
                authorization_version=authorization_version+1
            WHERE guild_id=? AND discord_id=?
            """,
            (GUILD_ID, ADMIN_DISCORD_ID),
        )
        connection.commit()
    removed = client.get("/v1/me", headers=_headers(ADMIN_DISCORD_ID))
    assert removed.status_code == 403
    assert "vínculo atual" in removed.json()["detail"].lower()


def test_command_can_view_inbox_and_rank_change_creates_outbox_atomically(api_client) -> None:
    client, database_path, seeded = api_client
    dashboard = client.get("/v1/dashboard", headers=_headers(ADMIN_DISCORD_ID))
    assert dashboard.status_code == 200
    assert dashboard.json()["capabilities"]["view_inbox"] is True
    assert len(dashboard.json()["inbox"]) == 1

    response = client.post(
        f"/v1/members/{MEMBER_DISCORD_ID}/rank",
        headers=_headers(ADMIN_DISCORD_ID),
        json={
            "target_rank_id": seeded["soldier_rank"],
            "action": "PROMOTION",
            "reason": "Progressão validada pelo teste web",
        },
    )
    assert response.status_code == 200
    assert response.json()["discord_sync"] == "PENDING"
    assert response.json()["correlation_id"]

    connection = sqlite3.connect(database_path)
    try:
        rank_id = connection.execute(
            "SELECT rank_id FROM members WHERE guild_id=? AND discord_id=?",
            (GUILD_ID, MEMBER_DISCORD_ID),
        ).fetchone()[0]
        outbox = connection.execute(
            """
            SELECT action_type, target_discord_id, requested_by, status
            FROM web_action_outbox
            """
        ).fetchone()
        audit_count = connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action='MEMBER_PROMOTION'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert rank_id == seeded["soldier_rank"]
    assert outbox == ("RANK_SYNC", MEMBER_DISCORD_ID, ADMIN_DISCORD_ID, "PENDING")
    assert audit_count == 1


def test_high_command_can_manage_qualification_and_member_cannot(api_client) -> None:
    client, database_path, _ = api_client
    discord_snowflake = 395061579101503491
    course_role_snowflake = 1146622062895579186
    connection = sqlite3.connect(database_path)
    try:
        now = 1_700_000_250_000
        connection.execute(
            "UPDATE members SET discord_id=? WHERE guild_id=? AND discord_id=?",
            (discord_snowflake, GUILD_ID, MEMBER_DISCORD_ID),
        )
        cursor = connection.execute(
            """
            INSERT INTO course_catalog(
                guild_id, internal_code, name, description, course_role_id,
                course_role_name, passing_score, cooldown_days, enrollment_status,
                source_channel_id, source_message_id, source_content_sha256,
                active, created_at, updated_at
            ) VALUES (?, 'abordagem_avancada', 'Abordagem Avançada', 'Curso API', ?,
                      'Abordagem Avançada', 80, 14, 'OPEN', 10, 11, 'api-test', 1, ?, ?)
            """,
            (GUILD_ID, course_role_snowflake, now, now),
        )
        course_id = int(cursor.lastrowid)
        connection.commit()
    finally:
        connection.close()

    payload = {
        # The web layer preserves Discord snowflakes as strings so JavaScript
        # never rounds them before this Python boundary.
        "discord_id": str(discord_snowflake),
        "course_id": course_id,
        "granted": True,
        "reason": "Concessão pelo painel de teste.",
    }
    denied = client.post(
        "/v1/qualifications/manage",
        headers=_headers(MEMBER_DISCORD_ID),
        json=payload,
    )
    granted = client.post(
        "/v1/qualifications/manage",
        headers=_headers(ADMIN_DISCORD_ID),
        json=payload,
    )
    matrix = client.get("/v1/qualifications", headers=_headers(ADMIN_DISCORD_ID))

    assert denied.status_code == 403
    assert granted.status_code == 200, granted.text
    assert granted.json()["changed"] is True
    assert matrix.status_code == 200
    member = next(
        item
        for item in matrix.json()["members"]
        if item["member"]["discord_id"] == str(discord_snowflake)
    )
    assert isinstance(member["member"]["discord_id"], str)
    assert member["member"]["discord_id"] == str(discord_snowflake)
    assert matrix.json()["courses"][0]["course_role_id"] == str(course_role_snowflake)
    assert member["courses"]["abordagem_avancada"]["granted"] is True
    connection = sqlite3.connect(database_path)
    try:
        action = connection.execute(
            """
            SELECT action_type, target_discord_id, status
            FROM web_action_outbox ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        assert action == ("QUALIFICATION_SYNC", discord_snowflake, "PENDING")
    finally:
        connection.close()


def test_career_overview_is_real_and_command_only(api_client) -> None:
    client, _database_path, _seeded = api_client

    denied = client.get("/v1/career", headers=_headers(MEMBER_DISCORD_ID))
    allowed = client.get("/v1/career", headers=_headers(ADMIN_DISCORD_ID))

    assert denied.status_code == 403
    assert allowed.status_code == 200
    payload = allowed.json()
    assert {row["discord_id"] for row in payload["members"]} == {
        MEMBER_DISCORD_ID,
        ADMIN_DISCORD_ID,
        INSTRUCTOR_DISCORD_ID,
    }
    assert payload["movements"] == []


def test_specialized_officer_reviewer_enters_only_the_officer_queue(api_client) -> None:
    client, database_path, seeded = api_client
    now = int(time.time() * 1000)
    role_id = 9_399
    with sqlite3.connect(database_path) as connection:
        profile_id = int(
            connection.execute(
                """
                SELECT id FROM access_profiles
                WHERE guild_id=? AND code='RESPONSAVEL_UPAMENTO'
                """,
                (GUILD_ID,),
            ).fetchone()[0]
        )
        mapping_id = int(
            connection.execute(
                """
                INSERT INTO discord_role_mappings(
                    guild_id, discord_role_id, mapping_type, internal_code,
                    display_name, priority, access_profile_id, enabled,
                    created_at, updated_at, created_by
                ) VALUES (?, ?, 'ACCESS', 'OFFICER_REVIEW_QA',
                          'Responsável por upamento QA', 60, ?, 1, ?, ?, ?)
                """,
                (GUILD_ID, role_id, profile_id, now, now, ADMIN_DISCORD_ID),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO member_access_profiles(
                member_id, access_profile_id, source_mapping_id,
                source_role_id, assigned_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (seeded["member_id"], profile_id, mapping_id, role_id, now, now),
        )
        connection.commit()

    headers = _headers(MEMBER_DISCORD_ID)
    identity = client.get("/v1/me", headers=headers)
    queue = client.get("/v1/officer-applications", headers=headers)
    settings = client.get("/v1/settings", headers=headers)
    career = client.get("/v1/career", headers=headers)

    assert identity.status_code == 200, identity.text
    assert "officer.review" in identity.json()["permissions"]
    assert "settings.manage" not in identity.json()["permissions"]
    assert queue.status_code == 200, queue.text
    assert settings.status_code == 403
    assert career.status_code == 403


def test_officer_candidacy_is_member_owned_lossless_and_human_decided(api_client) -> None:
    client, database_path, seeded = api_client
    now = int(time.time() * 1000)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE members
            SET rank_id=?, status='ACTIVE', rank_sync_status='SYNCED', updated_at=?
            WHERE guild_id=? AND discord_id=?
            """,
            (seeded["soldier_rank"], now, GUILD_ID, MEMBER_DISCORD_ID),
        )
        connection.execute(
            """
            INSERT INTO shifts(
                guild_id, member_id, status, started_at, ended_at, closed_at,
                end_reason, created_by, created_at, gross_duration_ms,
                patrol_duration_ms, validation_status, automatic_validation_status,
                validation_source, validated_at
            ) VALUES (?, ?, 'CLOSED', ?, ?, ?, 'API_TEST', ?, ?, ?, ?, 'VALID',
                      'VALID', 'AUTO', ?)
            """,
            (
                GUILD_ID,
                seeded["member_id"],
                now - 6 * 3_600_000,
                now,
                now,
                ADMIN_DISCORD_ID,
                now - 6 * 3_600_000,
                6 * 3_600_000,
                6 * 3_600_000,
                now,
            ),
        )
        connection.commit()

    member_headers = _headers(MEMBER_DISCORD_ID)
    eligibility = client.get(
        "/v1/officer-candidacy/eligibility", headers=member_headers
    )
    questionnaire = client.get(
        "/v1/officer-candidacy/questionnaire", headers=member_headers
    )
    started = client.post(
        "/v1/officer-candidacy/application", headers=member_headers
    )
    assert eligibility.status_code == 200, eligibility.text
    assert eligibility.json()["eligible"] is True
    assert questionnaire.status_code == 200, questionnaire.text
    assert len(questionnaire.json()["questions"]) == 30
    assert started.status_code == 200, started.text
    application_id = int(started.json()["id"])

    for question in questionnaire.json()["questions"]:
        answer = client.put(
            f"/v1/officer-candidacy/applications/{application_id}/answers/{question['id']}",
            headers=member_headers,
            json={
                "answer": (
                    "Eu preservaria a segurança, comunicaria a equipe e registraria "
                    "a decisão com ética, justificativa e responsabilidade."
                )
            },
        )
        assert answer.status_code == 200, answer.text

    submitted = client.post(
        f"/v1/officer-candidacy/applications/{application_id}/submit",
        headers=member_headers,
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "SUBMITTED"
    assert "analysis" not in submitted.json()

    admin_headers = _headers(ADMIN_DISCORD_ID)
    queue = client.get("/v1/officer-applications", headers=admin_headers)
    stale_admin_headers = {
        **admin_headers,
        "X-Session-Issued-At": str(int(time.time()) - 7_201),
    }
    stale_claim = client.post(
        f"/v1/officer-applications/{application_id}/claim",
        headers=stale_admin_headers,
    )
    claimed = client.post(
        f"/v1/officer-applications/{application_id}/claim", headers=admin_headers
    )
    decided = client.post(
        f"/v1/officer-applications/{application_id}/decision",
        headers=admin_headers,
        json={
            "decision": "APPROVED",
            "reason": "Respostas compatíveis, com decisão final registrada por avaliador humano.",
        },
    )
    assert queue.status_code == 200, queue.text
    assert queue.json()[0]["discord_id"] == str(MEMBER_DISCORD_ID)
    assert stale_claim.status_code == 401
    assert claimed.status_code == 200, claimed.text
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "APPROVED"
    assert decided.json()["reviewed_by"] == str(ADMIN_DISCORD_ID)

    mine = client.get("/v1/officer-candidacy/application", headers=member_headers)
    assert mine.status_code == 200, mine.text
    assert "analysis_report" not in mine.json()
    assert "score_summary" not in mine.json()
    assert all("actor_id" not in event for event in mine.json()["events"])
    assert all("metadata_json" not in event for event in mine.json()["events"])
    assert mine.json()["application"]["status"] == "APPROVED"


def test_member_cannot_open_admin_settings(api_client) -> None:
    client, _, _ = api_client
    response = client.get("/v1/settings", headers=_headers(MEMBER_DISCORD_ID))
    assert response.status_code == 403


def test_admin_settings_never_returns_financial_pix_key(api_client) -> None:
    client, database_path, _ = api_client
    secret = "dummy-pix-key-that-must-never-leave-settings"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            INSERT INTO guild_settings(guild_id, setting_key, value_json, updated_at, updated_by)
            VALUES (?, 'financial_pix_key', ?, ?, ?)
            """,
            (GUILD_ID, json.dumps(secret), 1_700_000_000_000, ADMIN_DISCORD_ID),
        )
        connection.commit()
    finally:
        connection.close()

    response = client.get("/v1/settings", headers=_headers(ADMIN_DISCORD_ID))
    assert response.status_code == 200, response.text
    settings = {item["setting_key"]: item for item in response.json()["general"]}
    assert settings["financial_pix_key"]["value"] == {"configured": True}
    assert secret not in response.text


def test_admin_configures_calls_and_rbac_by_registry_id(api_client) -> None:
    client, database_path, _ = api_client
    headers = _headers(ADMIN_DISCORD_ID)
    voice = client.put(
        "/v1/settings/voice-channels",
        headers=headers,
        json={
            "channel_id": 9101,
            "label": "Patrulha de validação",
            "counts_toward_patrol_minimum": False,
        },
    )
    binding = client.put(
        "/v1/settings/rbac-bindings",
        headers=headers,
        json={"role_id": 9201, "profile": "INSTRUTOR"},
    )
    assert voice.status_code == 200
    assert binding.status_code == 200

    connection = sqlite3.connect(database_path)
    try:
        voice_row = connection.execute(
            """
            SELECT label, service_allowed, counts_toward_patrol_minimum
            FROM authorized_voice_channels WHERE guild_id=? AND channel_id=9101
            """,
            (GUILD_ID,),
        ).fetchone()
        binding_row = connection.execute(
            "SELECT profile FROM rbac_bindings WHERE guild_id=? AND role_id=9201",
            (GUILD_ID,),
        ).fetchone()
        audit_count = connection.execute(
            """
            SELECT COUNT(*) FROM audit_logs
            WHERE action IN ('WEB_VOICE_CHANNEL_CONFIGURED','WEB_RBAC_BINDING_CONFIGURED')
            """
        ).fetchone()[0]
    finally:
        connection.close()
    assert voice_row == ("Patrulha de validação", 1, 0)
    assert binding_row == ("INSTRUTOR",)
    assert audit_count == 2


def test_candidate_flow_uses_oauth_identity_and_does_not_require_member_record(api_client) -> None:
    client, _, _ = api_client
    headers = _headers(CANDIDATE_DISCORD_ID)
    current = client.get("/v1/recruitment/current", headers=headers)
    eligibility = client.get("/v1/recruitment/eligibility", headers=headers)
    started = client.post(
        "/v1/recruitment/applications/start",
        headers=headers,
        json={
            "candidate_nick": "Candidato_API",
            "bgr_id": "5501",
            "age": 20,
            "consent_accepted": True,
            "idempotency_key": "candidate-api-idempotency-key",
        },
    )
    assert current.status_code == 200
    assert current.json()["campaign"]["status"] == "OPEN"
    assert eligibility.status_code == 200
    assert eligibility.json()["eligible"] is True
    assert started.status_code == 200
    assert started.json()["discord_id"] == CANDIDATE_DISCORD_ID
    mine = client.get("/v1/me/recruitment/application", headers=headers)
    assert mine.status_code == 200
    assert mine.json()["application"]["id"] == started.json()["id"]


def test_candidate_cannot_read_another_candidate_and_instructor_cannot_approve(
    api_client,
) -> None:
    client, database_path, _ = api_client
    started = client.post(
        "/v1/recruitment/applications/start",
        headers=_headers(CANDIDATE_DISCORD_ID),
        json={
            "candidate_nick": "Candidato_API",
            "bgr_id": "5502",
            "age": 20,
            "consent_accepted": True,
            "idempotency_key": "candidate-api-authorization-key",
        },
    ).json()
    denied = client.get(
        f"/v1/recruitment/applications/{started['id']}/next-question",
        headers=_headers(CANDIDATE_DISCORD_ID + 1),
    )
    assert denied.status_code == 404

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "UPDATE recruitment_applications SET status='UNDER_REVIEW' WHERE id=?",
            (started["id"],),
        )
        connection.commit()
    finally:
        connection.close()
    instructor_headers = _headers(INSTRUCTOR_DISCORD_ID)
    visible = client.get("/v1/admin/recruitment/applications", headers=instructor_headers)
    approve = client.post(
        f"/v1/admin/recruitment/applications/{started['id']}/approve",
        headers=instructor_headers,
        json={
            "expected_version": 1,
            "internal_reason": "Teste de permissão",
            "candidate_message": "Mensagem de teste",
        },
    )
    assert visible.status_code == 403
    assert approve.status_code == 403


def test_candidate_can_withdraw_and_only_command_can_manage_blocks(api_client) -> None:
    client, _, _ = api_client
    candidate_headers = _headers(CANDIDATE_DISCORD_ID + 20)
    started = client.post(
        "/v1/recruitment/applications/start",
        headers=candidate_headers,
        json={
            "candidate_nick": "Candidato_Retirada",
            "bgr_id": "5520",
            "age": 21,
            "consent_accepted": True,
            "idempotency_key": "candidate-api-withdraw-key",
        },
    ).json()
    withdrawn = client.post(
        f"/v1/recruitment/applications/{started['id']}/withdraw",
        headers=candidate_headers,
        json={"expected_version": 1},
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "WITHDRAWN"

    denied = client.get("/v1/admin/recruitment/blocks", headers=_headers(INSTRUCTOR_DISCORD_ID))
    created = client.post(
        "/v1/admin/recruitment/blocks",
        headers=_headers(ADMIN_DISCORD_ID),
        json={
            "discord_id": CANDIDATE_DISCORD_ID + 20,
            "bgr_id": None,
            "reason": "Impedimento administrativo de teste",
        },
    )
    assert denied.status_code == 403
    assert created.status_code == 200
    revoked = client.delete(
        f"/v1/admin/recruitment/blocks/{created.json()['id']}",
        headers=_headers(ADMIN_DISCORD_ID),
    )
    assert revoked.status_code == 200


def test_recruitment_sensitive_endpoints_are_rate_limited(api_client) -> None:
    client, _, _ = api_client
    headers = _headers(999_991)
    responses = [client.get("/v1/recruitment/eligibility", headers=headers) for _ in range(31)]
    assert all(response.status_code == 200 for response in responses[:30])
    assert responses[-1].status_code == 429
    assert int(responses[-1].headers["Retry-After"]) >= 1


def test_recruitment_ai_configuration_is_command_only_and_never_exposes_secret(
    api_client,
) -> None:
    client, _, _ = api_client
    admin_headers = _headers(ADMIN_DISCORD_ID)
    denied = client.get("/v1/admin/recruitment/ai/config", headers=_headers(INSTRUCTOR_DISCORD_ID))
    current = client.get("/v1/admin/recruitment/ai/config", headers=admin_headers)
    assert denied.status_code == 403
    assert current.status_code == 200
    assert current.json()["provider_ready"] is True
    assert current.json()["provider"] == "local-deterministic"
    assert current.json()["model"] == "transparent-rules-v1"
    assert "api_key" not in current.text.casefold()
    disabled = client.put(
        "/v1/admin/recruitment/ai/config",
        headers=admin_headers,
        json={
            "enabled": False,
            "auto_analyze": True,
            "analyze_integrity": True,
            "generate_interview_questions": True,
            "generate_summary": True,
            "final_assisted_after_interview": True,
            "discord_notice": False,
            "show_score": True,
        },
    )
    enabled = client.put(
        "/v1/admin/recruitment/ai/config",
        headers=admin_headers,
        json={
            "enabled": True,
            "auto_analyze": True,
            "analyze_integrity": True,
            "generate_interview_questions": True,
            "generate_summary": True,
            "final_assisted_after_interview": True,
            "discord_notice": False,
            "show_score": True,
        },
    )
    assert disabled.status_code == 200
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True


def test_context_rejects_profile_downgrade_outside_command(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, database_path, _ = api_client
    monkeypatch.delenv("WEB_ADMIN_DISCORD_IDS")
    headers = _headers(ADMIN_DISCORD_ID)

    before = client.get("/v1/context", headers=headers)
    allowed = client.get("/v1/admin/recruitment/applications", headers=headers)
    assert before.status_code == 200
    assert before.json()["access"]["profile"] == "COMANDO"
    assert allowed.status_code == 200

    connection = sqlite3.connect(database_path)
    try:
        member_rank = connection.execute(
            "SELECT id FROM ranks WHERE guild_id=? AND name='Recruta'",
            (GUILD_ID,),
        ).fetchone()[0]
        connection.execute(
            """
            UPDATE members
            SET rank_id=?, access_profile_id=NULL,
                authorization_version=authorization_version+1
            WHERE guild_id=? AND discord_id=?
            """,
            (member_rank, GUILD_ID, ADMIN_DISCORD_ID),
        )
        connection.execute(
            """
            DELETE FROM member_access_profiles
            WHERE member_id=(
                SELECT id FROM members WHERE guild_id=? AND discord_id=?
            )
            """,
            (GUILD_ID, ADMIN_DISCORD_ID),
        )
        connection.commit()
    finally:
        connection.close()

    after = client.get("/v1/me", headers=headers)
    denied = client.get("/v1/admin/recruitment/applications", headers=headers)
    assert after.status_code == 403
    assert "Centro de Comando" in after.json()["detail"]
    assert denied.status_code == 403


def test_discord_permission_rules_are_live_versioned_and_audited(api_client) -> None:
    client, database_path, seeded = api_client
    admin_headers = _headers(ADMIN_DISCORD_ID)
    member_headers = _headers(MEMBER_DISCORD_ID)

    denied_get = client.get("/v1/discord/permissions", headers=member_headers)
    denied_put = client.put(
        "/v1/discord/permissions",
        headers=member_headers,
        json={
            "subject_type": "MEMBER",
            "subject_id": seeded["member_id"],
            "permission": "shift.start",
            "effect": "DENY",
            "reason": "Teste sem autorização",
        },
    )
    assert denied_get.status_code == 403
    assert denied_put.status_code == 403

    initial = client.get("/v1/discord/permissions", headers=admin_headers)
    assert initial.status_code == 200, initial.text
    assert set(initial.json()) == {
        "catalog",
        "profiles",
        "ranks",
        "positions",
        "members",
        "rules",
        "summary",
    }
    assert "shift.start" in initial.json()["catalog"]
    member_profile = next(
        profile for profile in initial.json()["profiles"] if profile["code"] == "MEMBRO"
    )
    assert isinstance(member_profile["enabled"], bool)
    assert {
        "id",
        "discord_id",
        "mta_nick",
        "status",
    } == set(initial.json()["members"][0])

    connection = sqlite3.connect(database_path)
    try:
        versions_before = dict(
            connection.execute(
                """
                SELECT id, authorization_version
                FROM members WHERE guild_id=? ORDER BY id
                """,
                (GUILD_ID,),
            ).fetchall()
        )
    finally:
        connection.close()
    member_count = len(versions_before)

    custom_permission = "operations.custom.qa"
    custom = client.put(
        "/v1/discord/permissions",
        headers=admin_headers,
        json={
            "subject_type": "profile",
            "subject_id": member_profile["id"],
            "permission": custom_permission,
            "effect": "grant",
        },
    )
    assert custom.status_code == 200, custom.text
    assert custom.json() == {
        "rule": {
            "subject_type": "PROFILE",
            "subject_id": member_profile["id"],
            "subject_name": member_profile["name"],
            "permission": custom_permission,
            "effect": "GRANT",
            "reason": None,
            "updated_at": custom.json()["rule"]["updated_at"],
        },
        "authorization_versions_bumped": member_count,
    }

    deny = client.put(
        "/v1/discord/permissions",
        headers=admin_headers,
        json={
            "subject_type": "MEMBER",
            "subject_id": seeded["member_id"],
            "permission": "shift.start",
            "effect": "DENY",
            "reason": "Restrição individual controlada em QA",
        },
    )
    assert deny.status_code == 200, deny.text
    assert deny.json()["rule"]["effect"] == "DENY"
    assert deny.json()["rule"]["reason"] == "Restrição individual controlada em QA"
    assert deny.json()["authorization_versions_bumped"] == member_count

    listing = client.get("/v1/discord/permissions", headers=admin_headers)
    assert listing.status_code == 200
    assert custom_permission in listing.json()["catalog"]
    assert {
        (rule["subject_type"], rule["subject_id"], rule["permission"], rule["effect"])
        for rule in listing.json()["rules"]
    } >= {
        ("PROFILE", member_profile["id"], custom_permission, "GRANT"),
        ("MEMBER", seeded["member_id"], "shift.start", "DENY"),
    }
    assert listing.json()["summary"]["denies"] >= 1

    invalid_permission = client.put(
        "/v1/discord/permissions",
        headers=admin_headers,
        json={
            "subject_type": "PROFILE",
            "subject_id": member_profile["id"],
            "permission": "permissão inválida",
            "effect": "GRANT",
        },
    )
    wrong_guild_subject = client.put(
        "/v1/discord/permissions",
        headers=admin_headers,
        json={
            "subject_type": "RANK",
            "subject_id": 999_999,
            "permission": "reports.view",
            "effect": "GRANT",
        },
    )
    missing_member_reason = client.put(
        "/v1/discord/permissions",
        headers=admin_headers,
        json={
            "subject_type": "MEMBER",
            "subject_id": seeded["member_id"],
            "permission": "reports.view",
            "effect": "GRANT",
        },
    )
    assert invalid_permission.status_code == 422
    assert wrong_guild_subject.status_code == 422
    assert missing_member_reason.status_code == 422

    removed_custom = client.delete(
        f"/v1/discord/permissions/PROFILE/{member_profile['id']}/{custom_permission}",
        headers=admin_headers,
    )
    removed_deny = client.delete(
        f"/v1/discord/permissions/MEMBER/{seeded['member_id']}/shift.start",
        headers=admin_headers,
    )
    assert removed_custom.status_code == 200, removed_custom.text
    assert removed_custom.json() == {
        "removed": True,
        "subject_type": "PROFILE",
        "subject_id": member_profile["id"],
        "permission": custom_permission,
        "authorization_versions_bumped": member_count,
    }
    assert removed_deny.status_code == 200, removed_deny.text
    assert removed_deny.json()["authorization_versions_bumped"] == member_count

    connection = sqlite3.connect(database_path)
    try:
        versions_after = dict(
            connection.execute(
                """
                SELECT id, authorization_version
                FROM members WHERE guild_id=? ORDER BY id
                """,
                (GUILD_ID,),
            ).fetchall()
        )
        audits = connection.execute(
            """
            SELECT action, after_json
            FROM audit_logs
            WHERE action IN (
                'DISCORD_PERMISSION_RULE_CONFIGURED',
                'DISCORD_PERMISSION_RULE_REMOVED'
            )
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()
    assert versions_after == {
        member_id: version + 4 for member_id, version in versions_before.items()
    }
    assert [action for action, _ in audits] == [
        "DISCORD_PERMISSION_RULE_CONFIGURED",
        "DISCORD_PERMISSION_RULE_CONFIGURED",
        "DISCORD_PERMISSION_RULE_REMOVED",
        "DISCORD_PERMISSION_RULE_REMOVED",
    ]
    assert all(json.loads(payload)["request_id"] == "command-center-test" for _, payload in audits)


def test_discord_mapping_and_reconciliation_endpoints_are_audited(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, database_path, _ = api_client
    admin_headers = _headers(ADMIN_DISCORD_ID)

    denied = client.get(
        "/v1/discord/role-mappings", headers=_headers(MEMBER_DISCORD_ID)
    )
    assert denied.status_code == 403
    stale_headers = {
        **admin_headers,
        "X-Session-Issued-At": str(int(time.time()) - 7_201),
    }
    step_up = client.post(
        "/v1/discord/reconciliation/preview", headers=stale_headers
    )
    assert step_up.status_code == 401

    connection = sqlite3.connect(database_path)
    try:
        profile_id = connection.execute(
            "SELECT id FROM access_profiles WHERE guild_id=? AND code='INSTRUTOR'",
            (GUILD_ID,),
        ).fetchone()[0]
    finally:
        connection.close()

    configured = client.put(
        "/v1/discord/role-mappings",
        headers=admin_headers,
        json={
            "discord_role_id": 9201,
            "mapping_type": "ACCESS",
            "internal_code": "INSTRUCTOR_ACCESS",
            "display_name": "Instrutores QA",
            "priority": 45,
            "access_profile_id": profile_id,
            "is_primary_position_candidate": False,
            "enabled": True,
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["mapping"]["discord_role_id"] == 9201
    assert configured.json()["reconciliation"]["mode"] == "APPLY"

    listing = client.get("/v1/discord/role-mappings", headers=admin_headers)
    assert listing.status_code == 200
    assert any(
        row["discord_role_id"] == 9201 and row["mapping_type"] == "ACCESS"
        for row in listing.json()["mappings"]
    )

    individual = client.post(
        f"/v1/discord/identity/sync/{MEMBER_DISCORD_ID}", headers=admin_headers
    )
    preview = client.post("/v1/discord/reconciliation/preview", headers=admin_headers)
    assert individual.status_code == 200
    assert individual.json()["status"] == "PENDING"
    assert preview.status_code == 200
    preview_job_id = preview.json()["job_id"]

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            UPDATE identity_reconciliation_jobs
            SET status='COMPLETED', completed_at=? WHERE id=?
            """,
            (1_700_000_300_000, preview_job_id),
        )
        connection.commit()
    finally:
        connection.close()

    applied = client.post(
        "/v1/discord/reconciliation/apply",
        headers=admin_headers,
        json={"preview_job_id": preview_job_id},
    )
    details = client.get(
        f"/v1/discord/reconciliations/{preview_job_id}", headers=admin_headers
    )
    status_response = client.get("/v1/discord/identity/status", headers=admin_headers)
    assert applied.status_code == 200
    assert applied.json()["mode"] == "APPLY"
    assert details.status_code == 200
    assert details.json()["job"]["id"] == preview_job_id
    assert status_response.status_code == 200
    assert status_response.json()["summary"]["pending_queue"] >= 1

    # Simulate two requests that both passed the optimistic pre-check. The
    # database constraint remains the final arbiter and the API translates the
    # losing insert to a stable conflict instead of leaking an IntegrityError.
    database = client.app.state.services.database
    original_fetchone = database.fetchone

    async def race_window_fetchone(sql: str, params: tuple = ()):
        if "mode='APPLY' AND source_job_id" in sql:
            return None
        return await original_fetchone(sql, params)

    monkeypatch.setattr(database, "fetchone", race_window_fetchone)
    duplicate_apply = client.post(
        "/v1/discord/reconciliation/apply",
        headers=admin_headers,
        json={"preview_job_id": preview_job_id},
    )
    assert duplicate_apply.status_code == 409

    connection = sqlite3.connect(database_path)
    try:
        actions = {
            row[0]
            for row in connection.execute(
                """
                SELECT action FROM audit_logs
                WHERE action LIKE 'DISCORD_%' ORDER BY id
                """
            ).fetchall()
        }
    finally:
        connection.close()
    assert {
        "DISCORD_ROLE_MAPPING_CONFIGURED",
        "DISCORD_IDENTITY_SYNC_REQUESTED",
        "DISCORD_IDENTITY_RECONCILIATION_PREVIEW_REQUESTED",
        "DISCORD_IDENTITY_RECONCILIATION_APPLY_REQUESTED",
    } <= actions

    lockdown = client.post(
        "/v1/security/lockdown",
        headers=admin_headers,
        json={
            "active": True,
            "reason": "Contenção da reconciliação Discord no teste",
            "confirmation": "BLOQUEAR",
        },
    )
    blocked = client.post(
        "/v1/discord/reconciliation/preview", headers=admin_headers
    )
    assert lockdown.status_code == 200
    assert blocked.status_code == 423


def test_recruitment_signed_target_and_recent_authentication_boundaries(api_client) -> None:
    """The list target and its mutations must preserve distinct auth guarantees."""
    client, database_path, _ = api_client
    started = client.post(
        "/v1/recruitment/applications/start",
        headers=_headers(CANDIDATE_DISCORD_ID),
        json={
            "candidate_nick": "Candidato_Assinatura",
            "bgr_id": "5599",
            "age": 20,
            "consent_accepted": True,
            "idempotency_key": "candidate-api-signed-target-key",
        },
    ).json()
    application_id = int(started["id"])
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "UPDATE recruitment_applications SET status='SUBMITTED' WHERE id=?",
            (application_id,),
        )
        connection.commit()
    finally:
        connection.close()

    list_path = "/v1/admin/recruitment/applications"
    valid_list = client.get(
        list_path,
        headers=_signed_headers("GET", list_path, discord_id=ADMIN_DISCORD_ID),
    )
    signed_empty_query = client.get(
        list_path,
        headers=_signed_headers("GET", f"{list_path}?", discord_id=ADMIN_DISCORD_ID),
    )
    assert valid_list.status_code == 200, valid_list.text
    assert signed_empty_query.status_code == 401
    assert signed_empty_query.json()["detail"] == "Credencial interna inválida."
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "UPDATE recruitment_applications SET assigned_to=? WHERE id=?",
            (ADMIN_DISCORD_ID, application_id),
        )
        connection.commit()
    finally:
        connection.close()
    assigned_list_path = f"{list_path}?assigned_to={ADMIN_DISCORD_ID}"
    assigned_list = client.get(
        assigned_list_path,
        headers=_signed_headers("GET", assigned_list_path, discord_id=ADMIN_DISCORD_ID),
    )
    assert assigned_list.status_code == 200, assigned_list.text
    assert [item["id"] for item in assigned_list.json()["applications"]] == [application_id]

    assign_path = f"/v1/admin/recruitment/applications/{application_id}/assign"
    payload = json.dumps({"expected_version": 1}, separators=(",", ":"))
    stale = client.post(
        assign_path,
        content=payload,
        headers={
            **_signed_headers(
                "POST",
                assign_path,
                discord_id=ADMIN_DISCORD_ID,
                body=payload,
                issued_at=int(time.time()) - 1_801,
            ),
            "Content-Type": "application/json",
        },
    )
    assert stale.status_code == 401
    assert stale.json()["detail"] == "Autenticação recente necessária. Entre novamente."

    assigned = client.post(
        assign_path,
        content=payload,
        headers={
            **_signed_headers(
                "POST",
                assign_path,
                discord_id=ADMIN_DISCORD_ID,
                body=payload,
            ),
            "Content-Type": "application/json",
        },
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "UNDER_REVIEW"


def test_rank_mapping_and_legacy_rank_editor_share_the_canonical_registry(api_client) -> None:
    client, database_path, seeded = api_client
    headers = _headers(ADMIN_DISCORD_ID)
    rank_id = seeded["soldier_rank"]

    configured = client.put(
        "/v1/discord/role-mappings",
        headers=headers,
        json={
            "discord_role_id": 9201,
            "mapping_type": "RANK",
            "internal_code": "RANK_SOLDIER_QA",
            "display_name": "Soldado QA",
            "priority": 200,
            "rank_id": rank_id,
            "enabled": True,
        },
    )
    assert configured.status_code == 200, configured.text
    mapping_id = configured.json()["mapping"]["id"]

    connection = sqlite3.connect(database_path)
    try:
        mirror = connection.execute(
            "SELECT discord_role_id FROM ranks WHERE guild_id=? AND id=?",
            (GUILD_ID, rank_id),
        ).fetchone()
        canonical = connection.execute(
            """
            SELECT internal_code, display_name, priority, enabled
            FROM discord_role_mappings
            WHERE guild_id=? AND discord_role_id=9201 AND mapping_type='RANK'
            """,
            (GUILD_ID,),
        ).fetchone()
    finally:
        connection.close()
    assert mirror == (9201,)
    assert canonical == ("RANK_SOLDIER_QA", "Soldado QA", 200, 1)

    disabled = client.delete(
        f"/v1/discord/role-mappings/{mapping_id}", headers=headers
    )
    assert disabled.status_code == 200, disabled.text

    edited = client.patch(
        f"/v1/settings/ranks/{rank_id}",
        headers=headers,
        json={
            "name": "Soldado atualizado",
            "prefix": "SD",
            "level": 2,
            "discord_role_id": 9201,
            "rbac_profile": "MEMBRO",
            "active": True,
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["rank"]["discord_role_id"] == 9201
    assert edited.json()["reconciliation"]["mode"] == "APPLY"

    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute(
            """
            SELECT drm.display_name, drm.priority, drm.enabled, r.discord_role_id
            FROM discord_role_mappings drm
            JOIN ranks r ON r.id=drm.rank_id
            WHERE drm.guild_id=? AND drm.rank_id=? AND drm.mapping_type='RANK'
            ORDER BY drm.enabled DESC, drm.id DESC
            """,
            (GUILD_ID, rank_id),
        ).fetchall()
        pending_reconciliations = connection.execute(
            """
            SELECT COUNT(1) FROM web_action_outbox
            WHERE guild_id=? AND action_type='IDENTITY_RECONCILE_BULK'
            """,
            (GUILD_ID,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert rows[0] == ("Soldado atualizado", 2, 1, 9201)
    assert sum(row[2] for row in rows) == 1
    assert pending_reconciliations == 3
