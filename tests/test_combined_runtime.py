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
