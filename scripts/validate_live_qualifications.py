from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.request
import uuid
from pathlib import Path


def load_environment(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def signed_call(
    base_url: str,
    secret: str,
    guild_id: int,
    actor_id: int,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    body = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if payload is not None
        else b""
    )
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    canonical = "\n".join(
        (
            "choque-v1",
            method,
            path,
            hashlib.sha256(body).hexdigest(),
            str(guild_id),
            str(actor_id),
            correlation_id,
            timestamp,
            nonce,
            timestamp,
            "",
            "",
            "",
            "true",
        )
    )
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        data=body if payload is not None else None,
        headers={
            "Content-Type": "application/json",
            "X-Guild-ID": str(guild_id),
            "X-Actor-Discord-ID": str(actor_id),
            "X-Correlation-ID": correlation_id,
            "X-Request-Timestamp": timestamp,
            "X-Request-Nonce": nonce,
            "X-Request-Signature": signature,
            "X-Session-Issued-At": timestamp,
            "X-Discord-Guild-Verified": "true",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, json.load(response)


def main() -> None:
    load_environment()
    database_path = Path(os.getenv("DATABASE_PATH", "data/choque_bgr.db"))
    guild_id = int(os.environ["DEFAULT_GUILD_ID"])
    secret = os.environ["COMMAND_CENTER_INTERNAL_SECRET"]
    with sqlite3.connect(database_path) as connection:
        actor_row = connection.execute(
            """
            SELECT DISTINCT m.discord_id
            FROM members m
            JOIN member_access_profiles map ON map.member_id=m.id
            JOIN access_profiles ap ON ap.id=map.access_profile_id
            WHERE m.guild_id=? AND m.status='ACTIVE' AND m.discord_present=1
              AND m.identity_sync_status='SYNCED' AND ap.code='ADMINISTRADOR'
            ORDER BY m.id LIMIT 1
            """,
            (guild_id,),
        ).fetchone()
    if actor_row is None:
        raise RuntimeError("Nenhum administrador sincronizado disponível para o QA.")
    actor_id = int(actor_row[0])
    base_url = os.getenv("QUALIFICATIONS_QA_API_URL", "http://127.0.0.1:8080")
    me_status, me = signed_call(base_url, secret, guild_id, actor_id, "GET", "/v1/me")
    matrix_status, matrix = signed_call(
        base_url, secret, guild_id, actor_id, "GET", "/v1/qualifications"
    )
    courses = list(matrix.get("courses") or [])
    members = list(matrix.get("members") or [])
    no_op_status: int | None = None
    no_op_changed: bool | None = None
    if courses and members:
        course = dict(courses[0])
        member_entry = dict(members[0])
        member = dict(member_entry["member"])
        state = dict(member_entry.get("courses") or {})
        currently_granted = bool(state.get(str(course["internal_code"])))
        no_op_status, no_op = signed_call(
            base_url,
            secret,
            guild_id,
            actor_id,
            "POST",
            "/v1/qualifications/manage",
            {
                "discord_id": int(member["discord_id"]),
                "course_id": int(course["id"]),
                "granted": currently_granted,
                "reason": "Validação idempotente do rollout de qualificações.",
            },
        )
        no_op_changed = bool(no_op.get("changed"))
    print(
        json.dumps(
            {
                "me_status": me_status,
                "profile": me.get("profile"),
                "can_manage": "qualification.manage" in set(me.get("permissions") or []),
                "matrix_status": matrix_status,
                "courses": len(courses),
                "members": len(members),
                "no_op_status": no_op_status,
                "no_op_changed": no_op_changed,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
