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

from choque.channel_names import format_category_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from scripts.compact_discord_layout import (  # noqa: E402
    DiscordRest,
    fields_equal,
    snapshot_channel,
)

OBSOLETE_POINT_CATEGORY_ID = 1540589584679833680

EXPECTED_CATEGORIES = (
    (1540589573304881293, "Recepcao"),
    (1540589574667898920, "Ticket"),
    (1540735600167227453, "Atendimentos ativos"),
    (1540589576140357712, "Superiores"),
    (1540540581728485597, "Administracao"),
    (1540546763939782676, "Central do membro"),
    (1540589580028219432, "Registro"),
    (1161833335618801687, "Informacoes"),
    (1146622065399566420, "Membros choque"),
    (1146622065647046776, "Patrulhas"),
    (1540589592263139388, "Gerenciamento"),
    (1162263284108501092, "Recrutamento"),
    (1162114516318949529, "Cursos"),
    (1146622066527850585, "Auditoria"),
    (1540735603333922867, "Tickets arquivados"),
    (1540589594691772477, "Transferencias e parcerias"),
)


def expected_name_by_id() -> dict[int, str]:
    return {
        category_id: format_category_name(position, display_name)
        for position, (category_id, display_name) in enumerate(EXPECTED_CATEGORIES, start=1)
    }


def validate_inventory(channels: list[dict[str, Any]]) -> bool:
    categories = sorted(
        (channel for channel in channels if int(channel.get("type", -1)) == 4),
        key=lambda channel: int(channel.get("position", 0)),
    )
    actual_ids = [int(channel["id"]) for channel in categories]
    expected_before_ids = [
        *[category_id for category_id, _ in EXPECTED_CATEGORIES[:9]],
        OBSOLETE_POINT_CATEGORY_ID,
        *[category_id for category_id, _ in EXPECTED_CATEGORIES[9:]],
    ]
    expected_after_ids = [category_id for category_id, _ in EXPECTED_CATEGORIES]
    if tuple(actual_ids) not in {tuple(expected_before_ids), tuple(expected_after_ids)}:
        raise RuntimeError(
            "A ordem real das categorias diverge do plano autorizado; nenhuma renumeracao foi feita."
        )
    has_obsolete_category = OBSOLETE_POINT_CATEGORY_ID in actual_ids
    point_children = [
        int(channel["id"])
        for channel in channels
        if int(channel.get("parent_id") or 0) == OBSOLETE_POINT_CATEGORY_ID
    ]
    if point_children:
        raise RuntimeError(
            "A categoria Bate Ponto nao esta vazia; nenhuma exclusao foi feita."
        )
    return has_obsolete_category


def validate_after(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[str]:
    failures: list[str] = []
    before_by_id = {int(channel["id"]): channel for channel in before}
    after_by_id = {int(channel["id"]): channel for channel in after}
    names = expected_name_by_id()
    expected_after_ids = set(before_by_id) - {OBSOLETE_POINT_CATEGORY_ID}
    if set(after_by_id) != expected_after_ids:
        failures.append("unexpected-resource-set")
    for resource_id, before_channel in before_by_id.items():
        after_channel = after_by_id.get(resource_id)
        if resource_id == OBSOLETE_POINT_CATEGORY_ID:
            if after_channel is not None:
                failures.append("obsolete-point-category-still-present")
            continue
        if after_channel is None:
            failures.append(f"resource-missing:{resource_id}")
            continue
        if resource_id in names and after_channel.get("name") != names[resource_id]:
            failures.append(f"wrong-name:{resource_id}")
        elif resource_id not in names and after_channel.get("name") != before_channel.get("name"):
            failures.append(f"unrelated-name-changed:{resource_id}")
        for key in ("type", "parent_id", "position", "permission_overwrites"):
            if key == "position" and int(before_channel.get("type", -1)) == 4:
                continue
            if key == "position":
                equal = int(before_channel.get(key, 0)) == int(after_channel.get(key, 0))
            else:
                equal = fields_equal(before_channel, after_channel, key)
            if not equal:
                failures.append(f"changed-{key}:{resource_id}")
    ordered_after_categories = [
        int(channel["id"])
        for channel in sorted(
            (channel for channel in after if int(channel.get("type", -1)) == 4),
            key=lambda channel: int(channel.get("position", 0)),
        )
    ]
    expected_category_ids = [category_id for category_id, _ in EXPECTED_CATEGORIES]
    if ordered_after_categories != expected_category_ids:
        failures.append("unexpected-category-order")
    return failures


async def execute(apply: bool) -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID sao obrigatorios.")
    guild_id = int(config.default_guild_id)
    api = DiscordRest(config.token)
    try:
        before = await api.request("GET", f"/guilds/{guild_id}/channels")
        has_obsolete_category = validate_inventory(before)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = config.database_path.parent / "server_layout_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = backup_dir / f"category_renumber_{guild_id}_{stamp}.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "captured_at": datetime.now(UTC).isoformat(),
                    "guild_id": guild_id,
                    "channels": [snapshot_channel(channel) for channel in before],
                    "expected_names": expected_name_by_id(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            "CATEGORY_RENUMBER_PREVIEW_PASS "
            f"categories={len(EXPECTED_CATEGORIES)} snapshot={snapshot_path}"
        )
        if not apply:
            return 0
        if has_obsolete_category:
            await api.request("DELETE", f"/channels/{OBSOLETE_POINT_CATEGORY_ID}")
        for category_id, expected_name in expected_name_by_id().items():
            await api.request("PATCH", f"/channels/{category_id}", payload={"name": expected_name})
        after = await api.request("GET", f"/guilds/{guild_id}/channels")
        failures = validate_after(before, after)
        if failures:
            raise RuntimeError(f"Validacao final falhou: {failures}")
        print(f"CATEGORY_RENUMBER_APPLY_PASS categories={len(EXPECTED_CATEGORIES)}")
        return 0
    finally:
        await api.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Renumera as categorias CHOQUE - BGR.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(execute(args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
