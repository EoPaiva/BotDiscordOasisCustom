from __future__ import annotations

import sqlite3
import tomllib
from pathlib import Path

import pytest

from scripts import run_combined

REQUIRED_ENVIRONMENT = {
    "APP_ENV": "production",
    "DISCORD_TOKEN": "synthetic-test-token",
    "DATABASE_PATH": "/data/choque_bgr.db",
    "DEFAULT_GUILD_ID": "123456789",
    "COMMAND_CENTER_INTERNAL_SECRET": "a" * 32,
    "WEB_AUDIT_HASH_SALT": "b" * 32,
    "WEB_ALLOWED_ORIGINS": "https://choque.example",
    "WEB_ALLOWED_HOSTS": "choque.example",
    "RECRUITMENT_TOKEN_SECRET": "c" * 32,
}


def test_root_railway_manifest_uses_combined_runtime() -> None:
    manifest_path = Path(__file__).parents[1] / "railway.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["build"]["builder"] == "NIXPACKS"
    assert manifest["deploy"]["startCommand"] == "python scripts/run_combined.py"
    assert manifest["deploy"]["healthcheckPath"] == "/health"
    assert manifest["deploy"]["restartPolicyType"] == "ON_FAILURE"


def test_combined_runtime_fails_closed_without_required_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in REQUIRED_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="Variaveis obrigatorias ausentes"):
        run_combined._validate_environment()


def test_combined_runtime_accepts_complete_production_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in REQUIRED_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    run_combined._validate_environment()


def test_combined_runtime_refuses_non_production_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in REQUIRED_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("APP_ENV", "development")

    with pytest.raises(RuntimeError, match="APP_ENV deve ser production"):
        run_combined._validate_environment()


def _create_database(path, *, version: int = 24) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 1)",
        (version,),
    )
    connection.execute("CREATE TABLE evidence(value TEXT NOT NULL)")
    connection.execute("INSERT INTO evidence(value) VALUES ('preserved')")
    connection.commit()
    connection.close()


def test_one_time_database_recovery_is_validated_and_removes_stale_wal(tmp_path) -> None:
    database_path = tmp_path / "choque_bgr.db"
    database_path.write_bytes(b"corrupted")
    (tmp_path / "choque_bgr.db-wal").write_bytes(b"stale-wal")
    (tmp_path / "choque_bgr.db-shm").write_bytes(b"stale-shm")
    _create_database(tmp_path / "recovery-once")

    incident_dir = run_combined._restore_database_if_requested(database_path)

    assert incident_dir == tmp_path / "security_backups"
    assert not (tmp_path / "recovery-once").exists()
    assert not (tmp_path / "choque_bgr.db-wal").exists()
    assert not (tmp_path / "choque_bgr.db-shm").exists()
    connection = sqlite3.connect(database_path)
    assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert connection.execute("SELECT value FROM evidence").fetchone()[0] == "preserved"
    connection.close()
    assert len(list(incident_dir.iterdir())) == 3


def test_database_recovery_is_a_noop_without_explicit_candidate(tmp_path) -> None:
    database_path = tmp_path / "choque_bgr.db"
    _create_database(database_path)

    assert run_combined._restore_database_if_requested(database_path) is None
