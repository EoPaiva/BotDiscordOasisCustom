from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence

GRACEFUL_SHUTDOWN_SECONDS = 20
POLL_INTERVAL_SECONDS = 0.5


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


def main() -> int:
    _validate_environment()

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
