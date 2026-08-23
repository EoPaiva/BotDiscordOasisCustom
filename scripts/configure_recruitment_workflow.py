from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.channel_names import format_channel_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402

API_BASE = "https://discord.com/api/v10"
RECRUITMENT_CATEGORY_ID = 1162263284108501092
RECRUITMENT_REQUIREMENTS_ID = 1161840087483564092
RECRUITMENT_PANEL_ID = 1162263355885629540
RECRUITMENT_APPROVED_ID = 1166175384119812166
RECRUITMENT_REJECTED_ID = 1166176079724154910
REGISTRY_SETTING = "discord_layout_registry_v2"
REASON = "CHOQUE - BGR • fluxo seguro de recrutamento"

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
MANAGE_MESSAGES = 1 << 13
READ_MESSAGE_HISTORY = 1 << 16
ATTACH_FILES = 1 << 15
EMBED_LINKS = 1 << 14
ADD_REACTIONS = 1 << 6
CREATE_PUBLIC_THREADS = 1 << 35
CREATE_PRIVATE_THREADS = 1 << 36
SEND_MESSAGES_IN_THREADS = 1 << 38

PUBLIC_STATUS_NAME = format_channel_name("Candidaturas recebidas", "📨")
PRIVATE_REVIEW_NAME = format_channel_name("Mesa de analise", "🛡️")
APPROVED_NAME = format_channel_name("Aprovados formulario", "✅")
REJECTED_NAME = format_channel_name("Reprovados formulario", "❌")


def normalize_name(value: str) -> str:
    small_caps = str.maketrans(
        {
            "ᴀ": "a",
            "ʙ": "b",
            "ᴄ": "c",
            "ᴅ": "d",
            "ᴇ": "e",
            "ꜰ": "f",
            "ғ": "f",
            "ɢ": "g",
            "ʜ": "h",
            "ɪ": "i",
            "ᴊ": "j",
            "ᴋ": "k",
            "ʟ": "l",
            "ᴍ": "m",
            "ɴ": "n",
            "ᴏ": "o",
            "ᴘ": "p",
            "ʀ": "r",
            "ꜱ": "s",
            "ᴛ": "t",
            "ᴜ": "u",
            "ᴠ": "v",
            "ᴡ": "w",
            "ʏ": "y",
            "ᴢ": "z",
        }
    )
    decomposed = unicodedata.normalize("NFKD", value.translate(small_caps))
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    for separator in ("・", "·", "•", "-", "_", "ㅤ"):
        plain = plain.replace(separator, " ")
    return " ".join(plain.casefold().split())


class DiscordRest:
    def __init__(self, token: str) -> None:
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bot {token}", "User-Agent": "CHOQUE-BGR/1.0"}
        )

    async def close(self) -> None:
        await self.session.close()

    async def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | list[dict[str, Any]] | None = None,
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


def _overwrite(
    target_id: int,
    *,
    target_type: int,
    allow: int = 0,
    deny: int = 0,
) -> dict[str, str | int]:
    return {
        "id": str(target_id),
        "type": target_type,
        "allow": str(allow),
        "deny": str(deny),
    }


def _snapshot_channel(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(channel["id"]),
        "name": str(channel["name"]),
        "type": int(channel["type"]),
        "parent_id": int(channel["parent_id"]) if channel.get("parent_id") else None,
        "position": int(channel.get("position", 0)),
        "topic": channel.get("topic"),
        "permission_overwrites": channel.get("permission_overwrites", []),
    }


async def _load_staff_role_ids(database: Database, guild_id: int) -> set[int]:
    rows = await database.fetchall(
        """
        SELECT role_id FROM rbac_bindings
        WHERE guild_id=? AND profile IN ('COMANDO','ALTO_COMANDO','ADMINISTRADOR')
        """,
        (guild_id,),
    )
    return {int(row["role_id"]) for row in rows}


def _find_recruitment_role_ids(roles: list[dict[str, Any]]) -> set[int]:
    return {
        int(role["id"])
        for role in roles
        if "recrutamento" in normalize_name(str(role["name"]))
    }


def _find_existing_channel(
    channels: list[dict[str, Any]], *, category_id: int, canonical_name: str
) -> dict[str, Any] | None:
    exact = [
        channel
        for channel in channels
        if int(channel.get("type", -1)) == 0
        and int(channel.get("parent_id") or 0) == category_id
        and str(channel.get("name")) == canonical_name
    ]
    if len(exact) > 1:
        raise RuntimeError(f"Foram encontrados canais duplicados com o nome {canonical_name!r}.")
    return exact[0] if exact else None


async def _persist_settings(
    config: AppConfig,
    *,
    public_id: int,
    review_id: int,
    approved_id: int,
    rejected_id: int,
    public_url: str,
) -> None:
    guild_id = int(config.default_guild_id or 0)
    if not guild_id:
        raise RuntimeError("DEFAULT_GUILD_ID não configurado.")
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        before = {
            key: await settings.get(guild_id, key)
            for key in (
                "recruitment_public_status_channel_id",
                "recruitment_review_channel_id",
                "recruitment_notification_channel_id",
                "recruitment_queue_channel_id",
                "recruitment_approved_channel_id",
                "recruitment_rejected_channel_id",
            )
        }
        registry = await settings.get(guild_id, REGISTRY_SETTING, {})
        if not isinstance(registry, dict):
            registry = {}
        categories = dict(registry.get("categories") or {})
        channels = dict(registry.get("channels") or {})
        categories["recruitment"] = RECRUITMENT_CATEGORY_ID
        channels.update(
            {
                "recruitment.requirements": RECRUITMENT_REQUIREMENTS_ID,
                "recruitment.panel": RECRUITMENT_PANEL_ID,
                "recruitment.public_status": public_id,
                "recruitment.review": review_id,
                "recruitment.approved": approved_id,
                "recruitment.rejected": rejected_id,
            }
        )
        registry = {**registry, "categories": categories, "channels": channels}
        after = {
            "recruitment_public_status_channel_id": public_id,
            "recruitment_review_channel_id": review_id,
            "recruitment_notification_channel_id": review_id,
            "recruitment_queue_channel_id": review_id,
            "recruitment_approved_channel_id": approved_id,
            "recruitment_rejected_channel_id": rejected_id,
            "recruitment_public_url": public_url,
        }
        async with database.transaction() as connection:
            for key, value in after.items():
                await settings.set(guild_id, key, value, None, connection)
            await settings.set(guild_id, "recruitment_review_sla_hours", 72, None, connection)
            await settings.set(guild_id, REGISTRY_SETTING, registry, None, connection)
            await audit.record(
                guild_id,
                "RECRUITMENT_DISCORD_WORKFLOW_CONFIGURED",
                before=before,
                after={**after, "registry_keys": sorted(channels)},
                reason=REASON,
                connection=connection,
                deliver_immediately=False,
            )
    finally:
        await database.close()


async def _settings_only(args: argparse.Namespace, config: AppConfig) -> int:
    required = (args.public_id, args.review_id, args.approved_id, args.rejected_id)
    if not all(required):
        raise RuntimeError(
            "--settings-only exige --public-id, --review-id, --approved-id e --rejected-id."
        )
    await _persist_settings(
        config,
        public_id=int(args.public_id),
        review_id=int(args.review_id),
        approved_id=int(args.approved_id),
        rejected_id=int(args.rejected_id),
        public_url=(
            args.public_url
            or os.getenv("RECRUITMENT_PUBLIC_URL")
            or "https://web-plum-tau-82.vercel.app/recrutamento"
        ),
    )
    print("RECRUITMENT_SETTINGS_APPLY_PASS")
    return 0


async def run() -> int:
    parser = argparse.ArgumentParser(
        description="Configura os canais público e privado do recrutamento."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--settings-only", action="store_true")
    parser.add_argument("--public-id", type=int)
    parser.add_argument("--review-id", type=int)
    parser.add_argument("--approved-id", type=int, default=RECRUITMENT_APPROVED_ID)
    parser.add_argument("--rejected-id", type=int, default=RECRUITMENT_REJECTED_ID)
    parser.add_argument("--public-url")
    args = parser.parse_args()
    config = AppConfig.load()
    if args.settings_only:
        return await _settings_only(args, config)
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")

    guild_id = int(config.default_guild_id)
    api = DiscordRest(config.token)
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        me, roles, channels = await asyncio.gather(
            api.request("GET", "/users/@me"),
            api.request("GET", f"/guilds/{guild_id}/roles"),
            api.request("GET", f"/guilds/{guild_id}/channels"),
        )
        by_id = {int(channel["id"]): channel for channel in channels}
        category = by_id.get(RECRUITMENT_CATEGORY_ID)
        panel = by_id.get(RECRUITMENT_PANEL_ID)
        approved = by_id.get(RECRUITMENT_APPROVED_ID)
        rejected = by_id.get(RECRUITMENT_REJECTED_ID)
        if not category or int(category.get("type", -1)) != 4:
            raise RuntimeError("Categoria oficial de Recrutamento não encontrada.")
        if not panel or int(panel.get("parent_id") or 0) != RECRUITMENT_CATEGORY_ID:
            raise RuntimeError("Painel oficial de Recrutamento não encontrado na categoria.")
        if not approved or not rejected:
            raise RuntimeError("Canais oficiais de resultado não foram encontrados pelos IDs.")

        public = _find_existing_channel(
            channels,
            category_id=RECRUITMENT_CATEGORY_ID,
            canonical_name=PUBLIC_STATUS_NAME,
        )
        review = _find_existing_channel(
            channels,
            category_id=RECRUITMENT_CATEGORY_ID,
            canonical_name=PRIVATE_REVIEW_NAME,
        )
        staff_role_ids = await _load_staff_role_ids(database, guild_id)
        staff_role_ids.update(_find_recruitment_role_ids(roles))
        live_role_ids = {int(role["id"]) for role in roles}
        staff_role_ids.intersection_update(live_role_ids)
        if not staff_role_ids:
            raise RuntimeError("Nenhum cargo de Comando ou Recrutamento foi identificado.")

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = config.database_path.parent / "server_layout_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = backup_dir / f"recruitment_workflow_{guild_id}_{stamp}.json"
        snapshot = {
            "guild_id": guild_id,
            "captured_at": stamp,
            "reason": REASON,
            "category": _snapshot_channel(category),
            "channels": [
                _snapshot_channel(channel)
                for channel in channels
                if int(channel.get("parent_id") or 0) == RECRUITMENT_CATEGORY_ID
            ],
            "planned": {
                "public_name": PUBLIC_STATUS_NAME,
                "review_name": PRIVATE_REVIEW_NAME,
                "approved_name": APPROVED_NAME,
                "rejected_name": REJECTED_NAME,
                "staff_role_ids": sorted(staff_role_ids),
            },
        }
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            "RECRUITMENT_WORKFLOW_PREVIEW_PASS "
            f"public_exists={bool(public)} review_exists={bool(review)} "
            f"staff_roles={len(staff_role_ids)} snapshot={snapshot_path.name}"
        )
        if not args.apply:
            return 0

        panel_overwrites = list(panel.get("permission_overwrites") or [])
        staff_allow = (
            VIEW_CHANNEL
            | SEND_MESSAGES
            | READ_MESSAGE_HISTORY
            | ATTACH_FILES
            | EMBED_LINKS
            | ADD_REACTIONS
            | MANAGE_MESSAGES
            | CREATE_PUBLIC_THREADS
            | CREATE_PRIVATE_THREADS
            | SEND_MESSAGES_IN_THREADS
        )
        review_overwrites: list[dict[str, str | int]] = [
            _overwrite(guild_id, target_type=0, deny=VIEW_CHANNEL)
        ]
        review_overwrites.extend(
            _overwrite(role_id, target_type=0, allow=staff_allow)
            for role_id in sorted(staff_role_ids)
        )
        review_overwrites.append(
            _overwrite(int(me["id"]), target_type=1, allow=staff_allow)
        )

        created_ids: list[int] = []
        try:
            if public is None:
                public = await api.request(
                    "POST",
                    f"/guilds/{guild_id}/channels",
                    payload={
                        "name": PUBLIC_STATUS_NAME,
                        "type": 0,
                        "parent_id": str(RECRUITMENT_CATEGORY_ID),
                        "topic": (
                            "Acompanhamento público e anônimo das candidaturas: "
                            "protocolo, etapa, prazo e resultado."
                        ),
                        "permission_overwrites": panel_overwrites,
                    },
                )
                created_ids.append(int(public["id"]))
            if review is None:
                review = await api.request(
                    "POST",
                    f"/guilds/{guild_id}/channels",
                    payload={
                        "name": PRIVATE_REVIEW_NAME,
                        "type": 0,
                        "parent_id": str(RECRUITMENT_CATEGORY_ID),
                        "topic": (
                            "Mesa privada do Comando e Recrutamento para dossiês, "
                            "notas, entrevistas e decisões."
                        ),
                        "permission_overwrites": review_overwrites,
                    },
                )
                created_ids.append(int(review["id"]))

            await api.request(
                "PATCH", f"/channels/{RECRUITMENT_APPROVED_ID}", payload={"name": APPROVED_NAME}
            )
            await api.request(
                "PATCH", f"/channels/{RECRUITMENT_REJECTED_ID}", payload={"name": REJECTED_NAME}
            )

            # O Discord recalcula posições; mover em ordem inversa preserva os demais canais.
            target_order = [
                int(panel["id"]),
                int(public["id"]),
                int(review["id"]),
                RECRUITMENT_APPROVED_ID,
                RECRUITMENT_REJECTED_ID,
            ]
            base_position = int(panel.get("position", 0))
            for offset, channel_id in reversed(list(enumerate(target_order))):
                await api.request(
                    "PATCH",
                    f"/channels/{channel_id}",
                    payload={"position": base_position + offset},
                )
        except Exception:
            for channel_id in created_ids:
                try:
                    await api.request("DELETE", f"/channels/{channel_id}")
                except Exception:
                    pass
            raise

        refreshed = await api.request("GET", f"/guilds/{guild_id}/channels")
        fresh_by_id = {int(channel["id"]): channel for channel in refreshed}
        public_id = int(public["id"])
        review_id = int(review["id"])
        failures: list[str] = []
        for channel_id, name in (
            (public_id, PUBLIC_STATUS_NAME),
            (review_id, PRIVATE_REVIEW_NAME),
            (RECRUITMENT_APPROVED_ID, APPROVED_NAME),
            (RECRUITMENT_REJECTED_ID, REJECTED_NAME),
        ):
            actual = fresh_by_id.get(channel_id)
            if not actual or str(actual.get("name")) != name:
                failures.append(f"name:{channel_id}")
            elif int(actual.get("parent_id") or 0) != RECRUITMENT_CATEGORY_ID:
                failures.append(f"category:{channel_id}")
        review_actual = fresh_by_id.get(review_id) or {}
        default_overwrite = next(
            (
                item
                for item in review_actual.get("permission_overwrites", [])
                if int(item.get("type", -1)) == 0 and int(item.get("id", 0)) == guild_id
            ),
            None,
        )
        if not default_overwrite or not (int(default_overwrite.get("deny", 0)) & VIEW_CHANNEL):
            failures.append("review:not-private")
        category_order = [
            int(channel["id"])
            for channel in sorted(
                (
                    channel
                    for channel in refreshed
                    if int(channel.get("parent_id") or 0) == RECRUITMENT_CATEGORY_ID
                    and int(channel.get("type", -1)) in {0, 5}
                ),
                key=lambda channel: int(channel.get("position", 0)),
            )
        ]
        expected_sequence = [RECRUITMENT_PANEL_ID, public_id, review_id]
        try:
            start = category_order.index(RECRUITMENT_PANEL_ID)
        except ValueError:
            failures.append("position:panel")
        else:
            if category_order[start : start + 3] != expected_sequence:
                failures.append("position:workflow")
        if failures:
            raise RuntimeError(f"Validação ao vivo falhou: {failures}")

        await _persist_settings(
            config,
            public_id=public_id,
            review_id=review_id,
            approved_id=RECRUITMENT_APPROVED_ID,
            rejected_id=RECRUITMENT_REJECTED_ID,
            public_url=(
                args.public_url
                or os.getenv("RECRUITMENT_PUBLIC_URL")
                or "https://web-plum-tau-82.vercel.app/recrutamento"
            ),
        )
        result = {
            "public_id": public_id,
            "review_id": review_id,
            "approved_id": RECRUITMENT_APPROVED_ID,
            "rejected_id": RECRUITMENT_REJECTED_ID,
            "snapshot": snapshot_path.name,
        }
        print("RECRUITMENT_WORKFLOW_APPLY_PASS " + json.dumps(result, sort_keys=True))
        return 0
    finally:
        await database.close()
        await api.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
