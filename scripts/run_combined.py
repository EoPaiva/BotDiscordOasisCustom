from __future__ import annotations

import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

GRACEFUL_SHUTDOWN_SECONDS = 20
POLL_INTERVAL_SECONDS = 0.5
DATABASE_RECOVERY_FILENAME = "recovery-once"


def _terminate(processes: Sequence[subprocess.Popen[bytes]]) -> None:
    running = [process for process in processes if process.poll() is None]
    for process in running:
        process.terminate()

    deadline = time.monotonic() + GRACEFUL_SHUTDOWN_SECONDS
    while running and time.monotonic() < deadline:
        running = [process for process in running if process.poll() is None]
        if running:
            time.sleep(POLL_INTERVAL_SECONDS)

    for process in running:
        process.kill()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _validate_environment() -> None:
    required = (
        "DISCORD_TOKEN",
        "DATABASE_PATH",
        "DEFAULT_GUILD_ID",
        "COMMAND_CENTER_INTERNAL_SECRET",
        "WEB_AUDIT_HASH_SALT",
        "WEB_ALLOWED_ORIGINS",
        "WEB_ALLOWED_HOSTS",
        "RECRUITMENT_TOKEN_SECRET",
    )
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError(
            "Variaveis obrigatorias ausentes no runtime combinado: " + ", ".join(missing)
        )
    if os.getenv("APP_ENV") != "production":
        raise RuntimeError("APP_ENV deve ser production no runtime combinado.")


def _validate_sqlite(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        migrations = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
    finally:
        connection.close()
    if quick_check != "ok":
        raise RuntimeError(f"Banco de recuperação inválido: {quick_check}")
    if foreign_keys:
        raise RuntimeError(
            f"Banco de recuperação possui {len(foreign_keys)} violações de foreign key"
        )
    if not migrations or int(migrations[0]) <= 0:
        raise RuntimeError("Banco de recuperação não possui migrations válidas")


def _restore_database_if_requested(database_path: Path) -> Path | None:
    recovery_path = database_path.parent / DATABASE_RECOVERY_FILENAME
    if not recovery_path.exists():
        return None
    _validate_sqlite(recovery_path)

    incident_dir = database_path.parent / "security_backups"
    incident_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for source in (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ):
        if source.exists():
            shutil.move(
                str(source),
                incident_dir / f"incident-{timestamp}-{source.name}",
            )

    os.replace(recovery_path, database_path)
    _validate_sqlite(database_path)
    print(
        f"DATABASE_RECOVERY_OK path={database_path} backup_dir={incident_dir}",
        flush=True,
    )
    return incident_dir


def main() -> int:
    load_dotenv(".env", override=False)
    load_dotenv(".env.combined", override=False)
    _validate_environment()
    _restore_database_if_requested(Path(os.environ["DATABASE_PATH"]))

    check = subprocess.run(
        [sys.executable, "main.py", "--check"],
        check=False,
    )
    if check.returncode != 0:
        return check.returncode

    processes = [
        subprocess.Popen([sys.executable, "main.py"]),
        subprocess.Popen([sys.executable, "-m", "command_center"]),
    ]
    stopping = False

    def request_shutdown(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    try:
        while not stopping:
            exited = [process for process in processes if process.poll() is not None]
            if exited:
                return next(
                    (process.returncode or 1 for process in exited if process.returncode),
                    1,
                )
            time.sleep(POLL_INTERVAL_SECONDS)
        return 0
    finally:
        _terminate(processes)


if __name__ == "__main__":
    raise SystemExit(main())
