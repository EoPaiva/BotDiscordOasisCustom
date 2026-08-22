import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_railway_combined_runtime_keeps_sqlite_in_one_service() -> None:
    config = tomllib.loads(
        (ROOT / "deploy" / "railway.combined.toml").read_text(encoding="utf-8")
    )
    assert config["deploy"]["startCommand"] == "python scripts/run_combined.py"
    assert config["deploy"]["healthcheckPath"] == "/health"

    runtime = (ROOT / "scripts" / "run_combined.py").read_text(encoding="utf-8")
    assert '[sys.executable, "main.py", "--check"]' in runtime
    assert 'subprocess.Popen([sys.executable, "main.py"])' in runtime
    assert 'subprocess.Popen([sys.executable, "-m", "command_center"])' in runtime


def test_recruitment_rls_is_default_deny_for_every_sensitive_table() -> None:
    sql = (ROOT / "deploy" / "supabase" / "recruitment_rls.sql").read_text(encoding="utf-8")
    for table in (
        "recruitment_applications",
        "recruitment_application_questions",
        "recruitment_integrity_events",
        "recruitment_internal_notes",
        "recruitment_notification_outbox",
        "recruitment_questions",
    ):
        assert f"'{table}'" in sql
    assert "force row level security" in sql.lower()
    assert "revoke all on table" in sql.lower()
    assert "create policy" not in sql.lower()
