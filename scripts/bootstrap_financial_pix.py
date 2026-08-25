"""One-time, stdin-only bootstrap for the administrative PIX setting.

This script deliberately accepts the key from standard input, never an
argument, environment echo or file.  Its sole output is a safe completion
marker.  It is intended for a trusted remote console after the Central
Financeira code has been deployed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.financial_aid import FinancialAidService  # noqa: E402
from choque.settings import SettingsService  # noqa: E402


async def configure_from_stdin(*, actor_id: int) -> None:
    if actor_id < 0:
        raise RuntimeError("actor-id inválido.")
    raw = sys.stdin.buffer.readline(512)
    if not raw:
        raise RuntimeError("Nenhuma chave PIX foi recebida na entrada segura.")
    if len(raw) >= 512 and not raw.endswith(b"\n"):
        raise RuntimeError("A entrada da chave PIX excede o tamanho permitido.")
    try:
        key = raw.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise RuntimeError("A chave PIX precisa usar UTF-8 válido.") from exc

    config = AppConfig.load()
    if not config.default_guild_id:
        raise RuntimeError("DEFAULT_GUILD_ID é obrigatório para configurar o PIX.")
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        finance = FinancialAidService(database, settings, audit)
        # Validation and the transaction occur inside the canonical service.
        # It stores the value only in the protected setting and omits it from
        # both financial and generic audit records.
        await finance.configure_pix_key(
            config.default_guild_id,
            actor_id=actor_id,
            key=key,
        )
    finally:
        await database.close()
    print("FINANCIAL_PIX_BOOTSTRAP_OK configured=true source=ADMINISTRATIVE_SETTING")


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap seguro da chave PIX financeira.")
    parser.add_argument(
        "--actor-id",
        type=int,
        default=0,
        help="ID administrativo para a auditoria; 0 identifica bootstrap controlado.",
    )
    args = parser.parse_args()
    await configure_from_stdin(actor_id=args.actor_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
