from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402
from choque.time_utils import utc_now_ms  # noqa: E402

API_BASE = "https://discord.com/api/v10"
PANEL_TYPE = "RECRUITMENT_REVIEW_DEMO"
DEMO_TITLE = "🧪 TESTE/DEMONSTRAÇÃO • MESA DE ANÁLISE"
REASON = "CHOQUE - BGR • demonstração segura da Mesa de Análise"


class DiscordRest:
    """Small REST client that never opens a second Discord Gateway session."""

    def __init__(self, token: str) -> None:
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bot {token}", "User-Agent": "CHOQUE-BGR/1.0"}
        )

    async def close(self) -> None:
        await self.session.close()

    async def request(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None
    ) -> Any:
        for _ in range(7):
            async with self.session.request(
                method,
                API_BASE + path,
                json=payload,
                headers={"X-Audit-Log-Reason": quote(REASON)},
            ) as response:
                if response.status == 429:
                    data = await response.json()
                    await asyncio.sleep(min(float(data.get("retry_after", 1)), 15.0))
                    continue
                if response.status == 204:
                    return None
                data = await response.json()
                if response.status >= 400:
                    message = data.get("message") if isinstance(data, dict) else str(data)
                    raise RuntimeError(f"Discord API {response.status}: {message}")
                return data
        raise RuntimeError("Discord API permaneceu limitada após as tentativas seguras.")


def demo_payload() -> dict[str, Any]:
    """A visual-only fixture.  Disabled controls cannot invoke real handlers."""
    controls = (
        ("Abrir dossiê", "📂", "open"),
        ("Adicionar nota", "📝", "note"),
        ("Entrevista", "🗓️", "interview"),
        ("Decidir", "⚖️", "decide"),
        ("Aprovar", "✅", "approve"),
        ("Reprovar", "❌", "reject"),
    )
    rows = []
    for group in (controls[:4], controls[4:]):
        rows.append(
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 2,
                        "label": label,
                        "emoji": {"name": emoji},
                        "custom_id": f"choque:recruitment:demo:{action}:v1",
                        "disabled": True,
                    }
                    for label, emoji, action in group
                ],
            }
        )
    return {
        "content": "",
        "embeds": [
            {
                "title": DEMO_TITLE,
                "description": (
                    "Esta é uma amostra visual do cartão operacional. **Não pertence a "
                    "nenhuma candidatura** e todos os controles estão desativados."
                ),
                "color": 0x4C78A8,
                "fields": [
                    {"name": "Protocolo", "value": "`AL-DEMO`", "inline": True},
                    {"name": "Estado", "value": "🔎 EM ANÁLISE", "inline": True},
                    {"name": "Responsável", "value": "Não atribuído", "inline": True},
                    {
                        "name": "Como funciona no cartão real",
                        "value": (
                            "O responsável abre o dossiê, registra notas, conduz a entrevista e "
                            "decide. Aprovar ou reprovar exige justificativa e atualiza a mesma ficha."
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Segurança da demonstração",
                        "value": (
                            "Estes botões não podem ser acionados, não registram dados e não alteram "
                            "cargos, membros, histórico ou candidaturas."
                        ),
                        "inline": False,
                    },
                ],
                "footer": {"text": "CHOQUE - BGR • Sistema de Gestão"},
            }
        ],
        "components": rows,
        "allowed_mentions": {"parse": []},
    }


def _is_demo(message: dict[str, Any]) -> bool:
    return bool(message.get("author", {}).get("bot")) and any(
        str(embed.get("title") or "") == DEMO_TITLE
        for embed in message.get("embeds", [])
        if isinstance(embed, dict)
    )


async def _record_publication(
    settings: SettingsService,
    config: AppConfig,
    channel_id: int,
    message_id: int,
) -> None:
    guild_id = int(config.default_guild_id or 0)
    await settings.upsert_panel(guild_id, PANEL_TYPE, channel_id, message_id)
    await settings.database.execute(
        """
        INSERT INTO audit_logs(
            correlation_id, guild_id, action, before_json, after_json,
            reason, created_at, delivery_status
        ) VALUES (lower(hex(randomblob(16))), ?, 'RECRUITMENT_REVIEW_DEMO_PUBLISHED',
                  NULL, ?, ?, ?, 'PENDING')
        """,
        (
            guild_id,
            json.dumps({"channel_id": channel_id, "message_id": message_id}),
            REASON,
            utc_now_ms(),
        ),
    )


async def run() -> int:
    parser = argparse.ArgumentParser(description="Publica uma demonstração segura da Mesa de Análise.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = demo_payload()
    if args.check:
        buttons = [
            button
            for row in payload["components"]
            for button in row["components"]
        ]
        assert len(buttons) == 6
        assert all(button["disabled"] for button in buttons)
        assert all(":demo:" in str(button["custom_id"]) for button in buttons)
        print("RECRUITMENT_REVIEW_DEMO_CHECK_OK")
        return 0
    if not args.apply:
        print("RECRUITMENT_REVIEW_DEMO_PREVIEW_OK")
        return 0

    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    api = DiscordRest(config.token)
    try:
        settings = SettingsService(database)
        channel_id = await settings.get(
            int(config.default_guild_id), "recruitment_review_channel_id"
        )
        if not channel_id:
            raise RuntimeError("Mesa de Análise não está configurada.")
        channel_id = int(channel_id)
        existing = None
        panel = await settings.get_panel(int(config.default_guild_id), PANEL_TYPE)
        if panel and int(panel["channel_id"]) == channel_id:
            try:
                message = await api.request(
                    "GET", f"/channels/{channel_id}/messages/{int(panel['message_id'])}"
                )
            except RuntimeError:
                message = None
            if isinstance(message, dict) and _is_demo(message):
                existing = message
        if existing is None:
            messages = await api.request("GET", f"/channels/{channel_id}/messages?limit=100")
            existing = next((message for message in messages if _is_demo(message)), None)

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = config.database_path.parent / "server_layout_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = backup_dir / f"recruitment_review_demo_{stamp}.json"
        snapshot_path.write_text(
            json.dumps({"captured_at": stamp, "previous_message": existing}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if existing:
            message = await api.request(
                "PATCH", f"/channels/{channel_id}/messages/{existing['id']}", payload=payload
            )
        else:
            message = await api.request("POST", f"/channels/{channel_id}/messages", payload=payload)
        await _record_publication(settings, config, channel_id, int(message["id"]))
        print(
            "RECRUITMENT_REVIEW_DEMO_APPLY_OK "
            f"message_id={message['id']} snapshot={snapshot_path.name}"
        )
        return 0
    finally:
        await api.close()
        await database.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
