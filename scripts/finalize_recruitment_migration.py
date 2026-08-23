from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.config import AppConfig  # noqa: E402
from scripts.configure_recruitment_workflow import DiscordRest  # noqa: E402


def _rendered(message: dict[str, Any]) -> str:
    return json.dumps(
        {
            "content": message.get("content"),
            "embeds": message.get("embeds", []),
            "attachments": [
                {"filename": item.get("filename"), "size": item.get("size")}
                for item in message.get("attachments", [])
            ],
        },
        ensure_ascii=False,
    )


def _validate_message(
    message: dict[str, Any], *, protocol: str, public: bool
) -> None:
    if not bool(message.get("author", {}).get("bot")):
        raise RuntimeError("A mensagem esperada não pertence ao bot.")
    rendered = _rendered(message)
    if protocol not in rendered:
        raise RuntimeError("O protocolo não aparece na mensagem entregue.")
    if public:
        fields = [
            str(field.get("name") or "").casefold()
            for embed in message.get("embeds", [])
            for field in embed.get("fields", [])
        ]
        if any(name in fields for name in ("candidato", "id bgr", "discord")):
            raise RuntimeError("A mensagem pública expõe um campo pessoal.")
    elif not any(
        str(item.get("filename") or "").startswith(protocol)
        for item in message.get("attachments", [])
    ):
        raise RuntimeError("O novo dossiê privado não contém o arquivo de respostas.")


async def run() -> int:
    parser = argparse.ArgumentParser(
        description="Valida a nova entrega e remove o cartão antigo de uma candidatura."
    )
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--old-channel-id", required=True, type=int)
    parser.add_argument("--old-message-id", required=True, type=int)
    parser.add_argument("--review-channel-id", required=True, type=int)
    parser.add_argument("--review-message-id", required=True, type=int)
    parser.add_argument("--public-channel-id", required=True, type=int)
    parser.add_argument("--public-message-id", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    protocol = args.protocol.strip().upper()
    config = AppConfig.load()
    if not config.token:
        raise RuntimeError("DISCORD_TOKEN não configurado.")
    api = DiscordRest(config.token)
    try:
        old_message, review_message, public_message = await asyncio.gather(
            api.request(
                "GET",
                f"/channels/{args.old_channel_id}/messages/{args.old_message_id}",
            ),
            api.request(
                "GET",
                f"/channels/{args.review_channel_id}/messages/{args.review_message_id}",
            ),
            api.request(
                "GET",
                f"/channels/{args.public_channel_id}/messages/{args.public_message_id}",
            ),
        )
        _validate_message(old_message, protocol=protocol, public=False)
        _validate_message(review_message, protocol=protocol, public=False)
        _validate_message(public_message, protocol=protocol, public=True)

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = config.database_path.parent / "server_layout_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = backup_dir / f"recruitment_card_migration_{protocol}_{stamp}.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "captured_at": stamp,
                    "protocol": protocol,
                    "old_message": old_message,
                    "review_message": review_message,
                    "public_message": public_message,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            "RECRUITMENT_CARD_MIGRATION_PREVIEW_PASS "
            f"protocol={protocol} snapshot={snapshot_path.name}"
        )
        if not args.apply:
            return 0
        await api.request(
            "DELETE",
            f"/channels/{args.old_channel_id}/messages/{args.old_message_id}",
        )
        try:
            await api.request(
                "GET",
                f"/channels/{args.old_channel_id}/messages/{args.old_message_id}",
            )
        except RuntimeError as exc:
            if "Discord API 404" not in str(exc):
                raise
        else:
            raise RuntimeError("O cartão antigo ainda existe após a remoção.")
        print(f"RECRUITMENT_CARD_MIGRATION_APPLY_PASS protocol={protocol}")
        return 0
    finally:
        await api.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
