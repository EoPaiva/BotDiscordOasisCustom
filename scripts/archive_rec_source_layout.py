from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.backups import create_consistent_backup  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402
from choque.source_cutover import (  # noqa: E402
    FEATURE_FLAG,
    MAINTENANCE_LOCK_SETTING,
    SOURCE_GUILD_SETTING,
    TARGET_GUILD_SETTING,
    validated_source_cutover,
)
from choque.time_utils import utc_now_ms  # noqa: E402
from scripts.migrate_rec_choque import (  # noqa: E402
    DEFAULT_SOURCE_GUILD_ID,
    DEFAULT_TARGET_GUILD_ID,
)

API_BASE = "https://discord.com/api/v10"
APPLY_CONFIRMATION = "ARQUIVAR ORIGEM NO DC2"
RESTORE_CONFIRMATION = "RESTAURAR ORIGEM DO DC2"
REASON = "CHOQUE - BGR • arquivamento reversível da origem após cutover para DC2"

VIEW_CHANNEL = 1 << 10

SOURCE_CHANNEL_SETTING_KEYS = (
    "recruitment_requirements_channel_id",
    "recruitment_panel_channel_id",
    "recruitment_queue_channel_id",
    "recruitment_review_channel_id",
    "recruitment_public_status_channel_id",
    "recruitment_notification_channel_id",
    "recruitment_approved_channel_id",
    "recruitment_rejected_channel_id",
    "recruitment_tag_setup_channel_id",
    "training_panel_channel_id",
    "course_catalog_channel_id",
)

TARGET_CHANNEL_SETTING_KEYS = (
    "recruitment_requirements_channel_id",
    "recruitment_panel_channel_id",
    "recruitment_queue_channel_id",
    "recruitment_review_channel_id",
    "recruitment_public_status_channel_id",
    "recruitment_approved_channel_id",
    "recruitment_rejected_channel_id",
    "training_panel_channel_id",
    "course_catalog_channel_id",
)

TARGET_PANEL_TYPES = (
    "RECRUITMENT",
    "RECRUITMENT_ADMIN",
    "TRAINING",
    "COURSE_CATALOG",
)

ACTIVE_RECRUITMENT_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "INTERVIEW_PENDING",
    "INTERVIEW_SCHEDULED",
    "INTERVIEW_COMPLETED",
    "FINAL_REVIEW",
)


class DiscordRest:
    def __init__(self, token: str) -> None:
        self.session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": "CHOQUE-BGR/DC2-Source-Archiver",
            }
        )

    async def close(self) -> None:
        await self.session.close()

    async def request(
        self, method: str, path: str, *, payload: Any | None = None
    ) -> Any:
        if method.upper() == "DELETE":
            raise RuntimeError("Este arquivador nunca executa DELETE na API do Discord.")
        for _ in range(8):
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
                    detail = data.get("message") if isinstance(data, dict) else str(data)
                    raise RuntimeError(f"Discord API {response.status}: {detail}")
                return data
        raise RuntimeError("Discord permaneceu limitado após tentativas seguras.")


def archived_name(name: str) -> str:
    normalized = name.strip()
    if normalized.casefold().startswith("arquivo-"):
        return normalized[:100]
    return f"arquivo-{normalized}"[:100]


def archived_overwrites(
    overwrites: Iterable[dict[str, Any]],
    *,
    guild_id: int,
    bot_user_id: int,
    bot_role_ids: set[int],
) -> list[dict[str, str | int]]:
    """Hide archived resources while preserving a route for the bot to restore them."""

    result: list[dict[str, str | int]] = []
    seen: set[tuple[int, int]] = set()
    for overwrite in overwrites:
        resource_id = int(overwrite["id"])
        overwrite_type = int(overwrite["type"])
        allow = int(overwrite.get("allow") or 0)
        deny = int(overwrite.get("deny") or 0)
        is_bot_route = (
            (overwrite_type == 0 and resource_id in bot_role_ids)
            or (overwrite_type == 1 and resource_id == bot_user_id)
        )
        if is_bot_route:
            allow |= VIEW_CHANNEL
            deny &= ~VIEW_CHANNEL
        else:
            allow &= ~VIEW_CHANNEL
            deny |= VIEW_CHANNEL
        result.append(
            {
                "id": str(resource_id),
                "type": overwrite_type,
                "allow": str(allow),
                "deny": str(deny),
            }
        )
        seen.add((overwrite_type, resource_id))

    if (0, guild_id) not in seen:
        result.append(
            {
                "id": str(guild_id),
                "type": 0,
                "allow": "0",
                "deny": str(VIEW_CHANNEL),
            }
        )
    if (1, bot_user_id) not in seen:
        result.append(
            {
                "id": str(bot_user_id),
                "type": 1,
                "allow": str(VIEW_CHANNEL),
                "deny": "0",
            }
        )
    return result


def select_archivable_resources(
    channels: list[dict[str, Any]], channel_ids: set[int]
) -> list[dict[str, Any]]:
    by_id = {int(channel["id"]): channel for channel in channels}
    selected = {
        resource_id
        for resource_id in channel_ids
        if resource_id in by_id and int(by_id[resource_id].get("type", -1)) != 4
    }

    # A category is archived only if every child belongs to the migrated layout.
    for category in channels:
        if int(category.get("type", -1)) != 4:
            continue
        category_id = int(category["id"])
        children = {
            int(channel["id"])
            for channel in channels
            if int(channel.get("parent_id") or 0) == category_id
        }
        if children and children.issubset(selected):
            selected.add(category_id)
    return [by_id[resource_id] for resource_id in sorted(selected)]


async def active_source_work(database: Database, guild_id: int) -> dict[str, int]:
    placeholders = ",".join("?" for _ in ACTIVE_RECRUITMENT_STATUSES)
    queries: dict[str, tuple[str, tuple[Any, ...]]] = {
        "recruitment_applications": (
            f"""
            SELECT COUNT(*) AS total FROM recruitment_applications
            WHERE guild_id=? AND status IN ({placeholders})
            """,
            (guild_id, *ACTIVE_RECRUITMENT_STATUSES),
        ),
        "legacy_candidacy_tickets": (
            """
            SELECT COUNT(*) AS total FROM service_tickets
            WHERE guild_id=? AND ticket_type='CANDIDACY'
              AND status IN ('PENDING','IN_REVIEW')
            """,
            (guild_id,),
        ),
        "recruitment_campaigns": (
            """
            SELECT COUNT(*) AS total FROM recruitment_campaigns
            WHERE guild_id=? AND status IN ('SCHEDULED','OPEN','PAUSED')
            """,
            (guild_id,),
        ),
        "course_applications": (
            """
            SELECT COUNT(*) AS total FROM course_applications
            WHERE guild_id=? AND status='PENDING'
            """,
            (guild_id,),
        ),
        "open_course_catalogs": (
            """
            SELECT COUNT(*) AS total FROM course_catalog
            WHERE guild_id=? AND active=1 AND enrollment_status='OPEN'
            """,
            (guild_id,),
        ),
        "training_events": (
            """
            SELECT COUNT(*) AS total FROM training_events
            WHERE guild_id=? AND status IN ('OPEN','CLOSED')
            """,
            (guild_id,),
        ),
    }
    counts: dict[str, int] = {}
    for key, (sql, params) in queries.items():
        row = await database.fetchone(sql, params)
        counts[key] = int(row["total"] if row else 0)
    return counts


async def _setting_rows(
    database: Database, guild_id: int, keys: Iterable[str]
) -> list[dict[str, Any]]:
    keys = tuple(keys)
    placeholders = ",".join("?" for _ in keys)
    rows = await database.fetchall(
        f"""
        SELECT guild_id,setting_key,value_json,updated_at,updated_by
        FROM guild_settings
        WHERE guild_id=? AND setting_key IN ({placeholders})
        ORDER BY setting_key
        """,
        (guild_id, *keys),
    )
    return [dict(row) for row in rows]


async def _source_channel_ids(
    database: Database, settings: SettingsService, guild_id: int
) -> set[int]:
    resource_ids: set[int] = set()
    for key in SOURCE_CHANNEL_SETTING_KEYS:
        value = await settings.get(guild_id, key)
        if value:
            resource_ids.add(int(value))
    registry = await settings.get(guild_id, "discord_layout_registry_v2", {})
    if isinstance(registry, dict):
        registry_channels = registry.get("channels", {})
        if isinstance(registry_channels, dict):
            for key, value in registry_channels.items():
                if value and str(key).startswith(("recruitment.", "courses.")):
                    resource_ids.add(int(value))
        registry_categories = registry.get("categories", {})
        if isinstance(registry_categories, dict):
            for key in ("recruitment", "courses"):
                value = registry_categories.get(key)
                if value:
                    resource_ids.add(int(value))
    for sql in (
        "SELECT channel_id FROM panels WHERE guild_id=? AND panel_type IN "
        "('RECRUITMENT','RECRUITMENT_ADMIN','RECRUITMENT_REQUIREMENTS','TRAINING','COURSE_CATALOG')",
        "SELECT channel_id FROM course_panel_messages WHERE guild_id=?",
        "SELECT source_channel_id AS channel_id FROM course_catalog WHERE guild_id=?",
        "SELECT panel_channel_id AS channel_id FROM course_catalog WHERE guild_id=?",
        "SELECT channel_id FROM training_events WHERE guild_id=?",
    ):
        for row in await database.fetchall(sql, (guild_id,)):
            if row["channel_id"]:
                resource_ids.add(int(row["channel_id"]))
    return resource_ids


async def _validate_target(
    api: DiscordRest,
    database: Database,
    settings: SettingsService,
    *,
    source_guild_id: int,
    target_guild_id: int,
    target_channels: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {int(channel["id"]): channel for channel in target_channels}
    configured: dict[str, int] = {}
    for key in TARGET_CHANNEL_SETTING_KEYS:
        value = await settings.get(target_guild_id, key)
        if not value or int(value) not in by_id:
            raise RuntimeError(f"Preflight bloqueado: canal DC2 ausente para {key}.")
        configured[key] = int(value)

    identity_source = await settings.get(target_guild_id, "identity_source_guild_id")
    if int(identity_source or 0) != source_guild_id:
        raise RuntimeError("Preflight bloqueado: DC2 não aponta para a guild de identidade correta.")

    registry = await settings.get(target_guild_id, "discord_layout_registry_v2", {})
    migration = registry.get("migration", {}) if isinstance(registry, dict) else {}
    if int(migration.get("source_guild_id") or 0) != source_guild_id:
        raise RuntimeError("Preflight bloqueado: registro da migração DC2 não confere.")

    panels = await database.fetchall(
        """
        SELECT panel_type,channel_id,message_id FROM panels
        WHERE guild_id=? AND panel_type IN ('RECRUITMENT','RECRUITMENT_ADMIN','TRAINING','COURSE_CATALOG')
        """,
        (target_guild_id,),
    )
    by_type = {str(panel["panel_type"]): panel for panel in panels}
    for panel_type in TARGET_PANEL_TYPES:
        panel = by_type.get(panel_type)
        if panel is None or int(panel["channel_id"]) not in by_id:
            raise RuntimeError(f"Preflight bloqueado: painel {panel_type} ausente no DC2.")
        await api.request(
            "GET",
            f"/channels/{int(panel['channel_id'])}/messages/{int(panel['message_id'])}",
        )

    source_courses = await database.fetchone(
        "SELECT COUNT(*) AS total FROM course_catalog WHERE guild_id=? AND active=1",
        (source_guild_id,),
    )
    target_courses = await database.fetchone(
        "SELECT COUNT(*) AS total FROM course_catalog WHERE guild_id=? AND active=1",
        (target_guild_id,),
    )
    source_total = int(source_courses["total"] if source_courses else 0)
    target_total = int(target_courses["total"] if target_courses else 0)
    if target_total < source_total:
        raise RuntimeError(
            "Preflight bloqueado: catálogo ativo do DC2 é menor que o catálogo da origem."
        )
    return {
        "configured_channels": configured,
        "panels": {
            panel_type: {
                "channel_id": int(by_type[panel_type]["channel_id"]),
                "message_id": int(by_type[panel_type]["message_id"]),
            }
            for panel_type in TARGET_PANEL_TYPES
        },
        "source_active_courses": source_total,
        "target_active_courses": target_total,
    }


def _snapshot_channel(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(channel["id"]),
        "name": str(channel["name"]),
        "type": int(channel["type"]),
        "parent_id": int(channel["parent_id"]) if channel.get("parent_id") else None,
        "position": int(channel.get("position", 0)),
        "topic": channel.get("topic"),
        "permission_overwrites": list(channel.get("permission_overwrites") or []),
    }


async def _restore_resources(api: DiscordRest, resources: Iterable[dict[str, Any]]) -> None:
    for resource in resources:
        await api.request(
            "PATCH",
            f"/channels/{int(resource['id'])}",
            payload={
                "name": str(resource["name"]),
                "permission_overwrites": list(resource.get("permission_overwrites") or []),
            },
        )


async def _restore_setting_rows(
    database: Database, guild_id: int, rows: list[dict[str, Any]]
) -> None:
    keys = (
        FEATURE_FLAG,
        SOURCE_GUILD_SETTING,
        TARGET_GUILD_SETTING,
        MAINTENANCE_LOCK_SETTING,
    )
    by_key = {str(row["setting_key"]): row for row in rows}
    async with database.transaction() as connection:
        for key in keys:
            row = by_key.get(key)
            if row is None:
                await connection.execute(
                    "DELETE FROM guild_settings WHERE guild_id=? AND setting_key=?",
                    (guild_id, key),
                )
                continue
            await connection.execute(
                """
                INSERT INTO guild_settings(guild_id,setting_key,value_json,updated_at,updated_by)
                VALUES(?,?,?,?,?)
                ON CONFLICT(guild_id,setting_key) DO UPDATE SET
                  value_json=excluded.value_json,updated_at=excluded.updated_at,
                  updated_by=excluded.updated_by
                """,
                (
                    int(row["guild_id"]),
                    str(row["setting_key"]),
                    str(row["value_json"]),
                    int(row["updated_at"]),
                    row["updated_by"],
                ),
            )


async def _restore(args: argparse.Namespace, api: DiscordRest, database: Database) -> int:
    if args.confirm != RESTORE_CONFIRMATION:
        raise RuntimeError(f"Restauração exige --confirm {RESTORE_CONFIRMATION!r}.")
    snapshot = json.loads(args.restore_snapshot.read_text(encoding="utf-8"))
    if snapshot.get("operation") != "DC2_SOURCE_LAYOUT_ARCHIVE":
        raise RuntimeError("Snapshot não pertence ao arquivador DC2.")
    source_guild_id = int(snapshot.get("source_guild_id") or 0)
    target_guild_id = int(snapshot.get("target_guild_id") or 0)
    if source_guild_id != int(args.source_guild):
        raise RuntimeError("Snapshot não pertence ao servidor de origem informado.")
    if target_guild_id != int(args.target_guild):
        raise RuntimeError("Snapshot não pertence ao DC2 informado.")
    resources = list(snapshot.get("resources") or [])
    resource_ids = [int(resource.get("id") or 0) for resource in resources]
    if not resources or any(resource_id <= 0 for resource_id in resource_ids):
        raise RuntimeError("Snapshot não contém recursos restauráveis válidos.")
    if len(resource_ids) != len(set(resource_ids)):
        raise RuntimeError("Snapshot contém IDs de recursos duplicados.")
    live_channels = await api.request("GET", f"/guilds/{source_guild_id}/channels")
    live_ids = {int(channel["id"]) for channel in live_channels}
    if not set(resource_ids).issubset(live_ids):
        raise RuntimeError("Snapshot referencia canal fora do servidor de origem atual.")
    await _restore_resources(api, resources)
    await _restore_setting_rows(
        database,
        source_guild_id,
        list(snapshot.get("source_setting_rows") or []),
    )
    print(
        "DC2_SOURCE_RESTORE_PASS "
        f"guild={source_guild_id} resources={len(resources)}"
    )
    return 0


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token:
        raise RuntimeError("DISCORD_TOKEN não configurado.")
    source_guild_id = int(args.source_guild)
    target_guild_id = int(args.target_guild)
    if source_guild_id == target_guild_id:
        raise RuntimeError("Origem e DC2 precisam ser guilds diferentes.")

    database_path = args.database or config.database_path
    database = Database(database_path, config.legacy_database_path)
    api = DiscordRest(config.token)
    await database.open()
    try:
        if args.restore_snapshot and args.apply:
            raise RuntimeError("Use --apply ou --restore-snapshot, nunca ambos.")
        if args.restore_snapshot:
            return await _restore(args, api, database)

        settings = SettingsService(database)
        if bool(await settings.get(source_guild_id, FEATURE_FLAG)):
            raise RuntimeError("A origem já está marcada como arquivada; nada foi alterado.")

        bot_user, source_guild, target_guild, source_channels, target_channels = (
            await asyncio.gather(
                api.request("GET", "/users/@me"),
                api.request("GET", f"/guilds/{source_guild_id}"),
                api.request("GET", f"/guilds/{target_guild_id}"),
                api.request("GET", f"/guilds/{source_guild_id}/channels"),
                api.request("GET", f"/guilds/{target_guild_id}/channels"),
            )
        )
        bot_member = await api.request(
            "GET", f"/guilds/{source_guild_id}/members/{int(bot_user['id'])}"
        )
        active = await active_source_work(database, source_guild_id)
        blocking = {key: total for key, total in active.items() if total}
        if blocking:
            raise RuntimeError(
                "Preflight bloqueado por trabalho ativo na origem: "
                + json.dumps(blocking, sort_keys=True)
            )
        target_evidence = await _validate_target(
            api,
            database,
            settings,
            source_guild_id=source_guild_id,
            target_guild_id=target_guild_id,
            target_channels=target_channels,
        )
        source_ids = await _source_channel_ids(database, settings, source_guild_id)
        resources = select_archivable_resources(source_channels, source_ids)
        if not resources:
            raise RuntimeError("Preflight bloqueado: nenhum recurso migrado foi encontrado na origem.")

        setting_rows = await _setting_rows(
            database,
            source_guild_id,
            (
                FEATURE_FLAG,
                SOURCE_GUILD_SETTING,
                TARGET_GUILD_SETTING,
                MAINTENANCE_LOCK_SETTING,
            ),
        )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = args.snapshot_dir or database_path.parent / "server_layout_backups"
        destination.mkdir(parents=True, exist_ok=True)
        snapshot_path = destination / f"dc2_source_layout_{source_guild_id}_{stamp}.json"
        snapshot = {
            "operation": "DC2_SOURCE_LAYOUT_ARCHIVE",
            "captured_at": stamp,
            "source_guild_id": source_guild_id,
            "source_guild_name": source_guild["name"],
            "target_guild_id": target_guild_id,
            "target_guild_name": target_guild["name"],
            "active_source_work": active,
            "target_evidence": target_evidence,
            "source_setting_rows": setting_rows,
            "resources": [_snapshot_channel(resource) for resource in resources],
        }
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            "DC2_SOURCE_ARCHIVE_PREFLIGHT_PASS "
            f"source={source_guild_id} target={target_guild_id} "
            f"resources={len(resources)} snapshot={snapshot_path}"
        )
        if not args.apply:
            print(f"DRY_RUN_ONLY apply_confirmation={APPLY_CONFIRMATION!r}")
            return 0
        if args.confirm != APPLY_CONFIRMATION:
            raise RuntimeError(f"--apply exige --confirm {APPLY_CONFIRMATION!r}.")

        backup = create_consistent_backup(database_path, destination)
        archived_payloads: list[dict[str, Any]] = []
        bot_role_ids = {int(role_id) for role_id in bot_member.get("roles", [])}
        try:
            # O lock é persistido antes da primeira mutação do Discord. Se o
            # processo ou o bot reiniciar no meio, a origem continua sem
            # republicar painéis nem aceitar gravações até restauração manual.
            await settings.set(
                source_guild_id,
                MAINTENANCE_LOCK_SETTING,
                {
                    "state": "ARCHIVING",
                    "source_guild_id": source_guild_id,
                    "target_guild_id": target_guild_id,
                    "started_at": utc_now_ms(),
                },
                int(bot_user["id"]),
            )
            for resource in resources:
                payload = {
                    "name": archived_name(str(resource["name"])),
                    "permission_overwrites": archived_overwrites(
                        resource.get("permission_overwrites") or [],
                        guild_id=source_guild_id,
                        bot_user_id=int(bot_user["id"]),
                        bot_role_ids=bot_role_ids,
                    ),
                }
                archived = await api.request(
                    "PATCH", f"/channels/{int(resource['id'])}", payload=payload
                )
                archived_payloads.append(archived)

            async with database.transaction() as connection:
                await settings.set(
                    source_guild_id,
                    SOURCE_GUILD_SETTING,
                    source_guild_id,
                    int(bot_user["id"]),
                    connection,
                )
                await settings.set(
                    source_guild_id,
                    TARGET_GUILD_SETTING,
                    target_guild_id,
                    int(bot_user["id"]),
                    connection,
                )
                await settings.set(
                    source_guild_id,
                    FEATURE_FLAG,
                    True,
                    int(bot_user["id"]),
                    connection,
                )
                await settings.set(
                    source_guild_id,
                    MAINTENANCE_LOCK_SETTING,
                    None,
                    int(bot_user["id"]),
                    connection,
                )

            cutover_state = await validated_source_cutover(database, source_guild_id)
            if not cutover_state.active or cutover_state.target_guild_id != target_guild_id:
                raise RuntimeError("Validação pós-arquivo falhou: vínculo DC1/DC2 não ficou ativo.")

            refreshed = await api.request("GET", f"/guilds/{source_guild_id}/channels")
            refreshed_by_id = {int(channel["id"]): channel for channel in refreshed}
            failures = [
                int(resource["id"])
                for resource in resources
                if int(resource["id"]) not in refreshed_by_id
                or not str(refreshed_by_id[int(resource["id"])]["name"]).startswith("arquivo-")
            ]
            if failures:
                raise RuntimeError(f"Validação pós-arquivo falhou: {failures}")
        except Exception:
            await _restore_resources(api, snapshot["resources"])
            await _restore_setting_rows(database, source_guild_id, setting_rows)
            raise

        result_path = snapshot_path.with_name(snapshot_path.stem + "_applied.json")
        result_path.write_text(
            json.dumps(
                {
                    **snapshot,
                    "applied_at": datetime.now(UTC).isoformat(),
                    "database_backup": {
                        "path": str(backup.path),
                        "sha256": backup.sha256,
                        "size": backup.size,
                        "migration": backup.migration,
                    },
                    "archived_resource_ids": [int(item["id"]) for item in archived_payloads],
                    "feature_flag": True,
                    "completed_at_ms": utc_now_ms(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            "DC2_SOURCE_ARCHIVE_APPLY_PASS "
            f"resources={len(resources)} backup={backup.path} result={result_path}"
        )
        return 0
    finally:
        await database.close()
        await api.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Arquiva reversivelmente os canais antigos de Recrutamento/Cursos após "
            "validar o DC2. Dry-run é o padrão e nenhum canal/mensagem é excluído."
        )
    )
    parser.add_argument("--source-guild", type=int, default=DEFAULT_SOURCE_GUILD_ID)
    parser.add_argument("--target-guild", type=int, default=DEFAULT_TARGET_GUILD_ID)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--restore-snapshot", type=Path)
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(build_parser().parse_args())))
