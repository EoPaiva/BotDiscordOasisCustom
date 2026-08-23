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

from choque.audit import AuditService  # noqa: E402
from choque.channel_names import format_channel_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402
from scripts.configure_recruitment_workflow import (  # noqa: E402
    ADD_REACTIONS,
    ATTACH_FILES,
    EMBED_LINKS,
    READ_MESSAGE_HISTORY,
    RECRUITMENT_APPROVED_ID,
    RECRUITMENT_PANEL_ID,
    RECRUITMENT_REJECTED_ID,
    RECRUITMENT_REQUIREMENTS_ID,
    SEND_MESSAGES,
    VIEW_CHANNEL,
    DiscordRest,
    _find_recruitment_role_ids,
    _load_staff_role_ids,
    _overwrite,
    _snapshot_channel,
    normalize_name,
)

PUBLIC_STATUS_ID = 1541006410672766986
PRIVATE_REVIEW_ID = 1541006412296228864
COMMUNITY_CATEGORY_ID = 1146622065399566420
COMMUNITY_MEMBER_CHANNEL_ID = 1161830033858515035
REGISTRY_SETTING = "discord_layout_registry_v2"
TAG_CHANNEL_NAME = format_channel_name("Setar tag", "🏷️")
REASON = "CHOQUE - BGR • acesso público do recrutamento e posto de setagem"


def _upsert_overwrite(
    overwrites: list[dict[str, Any]],
    target_id: int,
    *,
    target_type: int,
    allow: int,
    deny: int = 0,
) -> list[dict[str, Any]]:
    result = [
        item
        for item in overwrites
        if not (
            int(item.get("id", 0)) == target_id
            and int(item.get("type", -1)) == target_type
        )
    ]
    result.append(_overwrite(target_id, target_type=target_type, allow=allow, deny=deny))
    return result


async def _persist(config: AppConfig, channel_id: int, message_id: int | None = None) -> None:
    guild_id = int(config.default_guild_id or 0)
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        registry = await settings.get(guild_id, REGISTRY_SETTING, {})
        if not isinstance(registry, dict):
            registry = {}
        channels = dict(registry.get("channels") or {})
        channels["recruitment.tag_setup"] = channel_id
        registry = {**registry, "channels": channels}
        async with database.transaction() as connection:
            await settings.set(
                guild_id, "recruitment_tag_setup_channel_id", channel_id, None, connection
            )
            await settings.set(guild_id, REGISTRY_SETTING, registry, None, connection)
            if message_id:
                await connection.execute(
                    """
                    INSERT INTO panels(guild_id, panel_type, channel_id, message_id, updated_at)
                    VALUES (?, 'RECRUITMENT_TAG_SETUP', ?, ?, ?)
                    ON CONFLICT(guild_id, panel_type) DO UPDATE SET
                        channel_id=excluded.channel_id,
                        message_id=excluded.message_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        guild_id,
                        channel_id,
                        message_id,
                        int(datetime.now(UTC).timestamp() * 1000),
                    ),
                )
            await audit.record(
                guild_id,
                "RECRUITMENT_CANDIDATE_ACCESS_CONFIGURED",
                after={"tag_setup_channel_id": channel_id, "public_channels": 5},
                reason=REASON,
                connection=connection,
                deliver_immediately=False,
            )
    finally:
        await database.close()


def _panel_payload() -> dict[str, Any]:
    return {
        "content": "",
        "embeds": [
            {
                "title": "🏷️ POSTO DE SETAGEM • APRESENTAÇÃO OPERACIONAL",
                "description": (
                    "Canal destinado aos candidatos aprovados no formulário. "
                    "Use este posto para solicitar sua identificação dentro do jogo."
                ),
                "color": 0xB11226,
                "fields": [
                    {
                        "name": "Informações obrigatórias",
                        "value": (
                            "`01` Seu **ID no jogo**\n"
                            "`02` Seu **horário disponível**\n"
                            "`03` Sua **localização atual no jogo**"
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Procedimento",
                        "value": (
                            "Envie uma única mensagem completa e aguarde um responsável. "
                            "Não publique senhas, documentos ou qualquer dado pessoal."
                        ),
                        "inline": False,
                    },
                ],
                "footer": {"text": "CHOQUE - BGR • Sistema de Gestão"},
            }
        ],
        "allowed_mentions": {"parse": []},
    }


async def run() -> int:
    parser = argparse.ArgumentParser(
        description="Libera a jornada pública e cria o posto privado de setagem."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--settings-only", action="store_true")
    parser.add_argument("--channel-id", type=int)
    parser.add_argument("--message-id", type=int)
    args = parser.parse_args()
    config = AppConfig.load()
    if args.settings_only:
        if not args.channel_id:
            raise RuntimeError("--settings-only exige --channel-id.")
        await _persist(config, args.channel_id, args.message_id)
        print("RECRUITMENT_CANDIDATE_ACCESS_SETTINGS_PASS")
        return 0
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")

    guild_id = int(config.default_guild_id)
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    api = DiscordRest(config.token)
    try:
        me, roles, channels = await asyncio.gather(
            api.request("GET", "/users/@me"),
            api.request("GET", f"/guilds/{guild_id}/roles"),
            api.request("GET", f"/guilds/{guild_id}/channels"),
        )
        by_id = {int(channel["id"]): channel for channel in channels}
        required_ids = (
            RECRUITMENT_REQUIREMENTS_ID,
            RECRUITMENT_PANEL_ID,
            PUBLIC_STATUS_ID,
            PRIVATE_REVIEW_ID,
            RECRUITMENT_APPROVED_ID,
            RECRUITMENT_REJECTED_ID,
            COMMUNITY_CATEGORY_ID,
            COMMUNITY_MEMBER_CHANNEL_ID,
        )
        missing = [channel_id for channel_id in required_ids if channel_id not in by_id]
        if missing:
            raise RuntimeError(f"Recursos oficiais ausentes: {len(missing)}")

        settings = SettingsService(database)
        candidate_role_id = await settings.get(guild_id, "candidate_role_id")
        live_role_ids = {int(role["id"]) for role in roles}
        if not candidate_role_id or int(candidate_role_id) not in live_role_ids:
            candidates = [
                int(role["id"])
                for role in roles
                if "candidato" in normalize_name(str(role["name"]))
            ]
            if len(candidates) != 1:
                raise RuntimeError("Cargo de candidato não pôde ser identificado com segurança.")
            candidate_role_id = candidates[0]
        candidate_role_id = int(candidate_role_id)
        staff_role_ids = await _load_staff_role_ids(database, guild_id)
        staff_role_ids.update(_find_recruitment_role_ids(roles))
        staff_role_ids.intersection_update(live_role_ids)
        if not staff_role_ids:
            raise RuntimeError("Nenhum cargo responsável pelo recrutamento foi encontrado.")

        existing_tag = next(
            (
                channel
                for channel in channels
                if int(channel.get("parent_id") or 0) == COMMUNITY_CATEGORY_ID
                and str(channel.get("name")) == TAG_CHANNEL_NAME
                and int(channel.get("type", -1)) == 0
            ),
            None,
        )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = config.database_path.parent / "server_layout_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = backup_dir / f"recruitment_candidate_access_{guild_id}_{stamp}.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "captured_at": stamp,
                    "channels": [
                        _snapshot_channel(by_id[channel_id]) for channel_id in required_ids
                    ]
                    + ([_snapshot_channel(existing_tag)] if existing_tag else []),
                    "planned": {
                        "candidate_role_id": candidate_role_id,
                        "staff_role_ids": sorted(staff_role_ids),
                        "tag_channel_name": TAG_CHANNEL_NAME,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            "RECRUITMENT_CANDIDATE_ACCESS_PREVIEW_PASS "
            f"tag_exists={bool(existing_tag)} snapshot={snapshot_path.name}"
        )
        if not args.apply:
            return 0

        public_allow = VIEW_CHANNEL | READ_MESSAGE_HISTORY
        for channel_id in (
            RECRUITMENT_REQUIREMENTS_ID,
            RECRUITMENT_PANEL_ID,
            PUBLIC_STATUS_ID,
            RECRUITMENT_APPROVED_ID,
            RECRUITMENT_REJECTED_ID,
        ):
            channel = by_id[channel_id]
            overwrites = _upsert_overwrite(
                list(channel.get("permission_overwrites") or []),
                guild_id,
                target_type=0,
                allow=public_allow,
                deny=SEND_MESSAGES,
            )
            await api.request(
                "PATCH",
                f"/channels/{channel_id}",
                payload={"permission_overwrites": overwrites},
            )

        tag_allow = (
            VIEW_CHANNEL
            | SEND_MESSAGES
            | READ_MESSAGE_HISTORY
            | ATTACH_FILES
            | EMBED_LINKS
            | ADD_REACTIONS
        )
        tag_overwrites = [_overwrite(guild_id, target_type=0, deny=VIEW_CHANNEL)]
        tag_overwrites.append(
            _overwrite(candidate_role_id, target_type=0, allow=tag_allow)
        )
        tag_overwrites.extend(
            _overwrite(role_id, target_type=0, allow=tag_allow)
            for role_id in sorted(staff_role_ids)
        )
        tag_overwrites.append(_overwrite(int(me["id"]), target_type=1, allow=tag_allow))
        if existing_tag is None:
            existing_tag = await api.request(
                "POST",
                f"/guilds/{guild_id}/channels",
                payload={
                    "name": TAG_CHANNEL_NAME,
                    "type": 0,
                    "parent_id": str(COMMUNITY_CATEGORY_ID),
                    "topic": "Posto privado para candidatos aprovados solicitarem a setagem no jogo.",
                    "permission_overwrites": tag_overwrites,
                },
            )
        else:
            existing_tag = await api.request(
                "PATCH",
                f"/channels/{existing_tag['id']}",
                payload={"permission_overwrites": tag_overwrites},
            )
        await api.request(
            "PATCH",
            f"/channels/{existing_tag['id']}",
            payload={"position": int(by_id[COMMUNITY_MEMBER_CHANNEL_ID].get("position", 0)) + 1},
        )
        messages = await api.request(
            "GET", f"/channels/{existing_tag['id']}/messages?limit=50"
        )
        panel = next(
            (
                message
                for message in messages
                if bool(message.get("author", {}).get("bot"))
                and any(
                    "POSTO DE SETAGEM" in str(embed.get("title") or "")
                    for embed in message.get("embeds", [])
                )
            ),
            None,
        )
        if panel:
            panel = await api.request(
                "PATCH",
                f"/channels/{existing_tag['id']}/messages/{panel['id']}",
                payload=_panel_payload(),
            )
        else:
            panel = await api.request(
                "POST",
                f"/channels/{existing_tag['id']}/messages",
                payload=_panel_payload(),
            )
        await _persist(config, int(existing_tag["id"]), int(panel["id"]))
        refreshed = await api.request("GET", f"/guilds/{guild_id}/channels")
        fresh_by_id = {int(channel["id"]): channel for channel in refreshed}
        actual = fresh_by_id.get(int(existing_tag["id"]))
        if not actual or str(actual.get("name")) != TAG_CHANNEL_NAME:
            raise RuntimeError("Validação do canal de setagem falhou.")
        private = next(
            (
                item
                for item in actual.get("permission_overwrites", [])
                if int(item.get("id", 0)) == guild_id and int(item.get("type", -1)) == 0
            ),
            None,
        )
        if not private or not (int(private.get("deny", 0)) & VIEW_CHANNEL):
            raise RuntimeError("Canal de setagem não permaneceu privado.")
        print(
            "RECRUITMENT_CANDIDATE_ACCESS_APPLY_PASS "
            f"channel_id={existing_tag['id']} message_id={panel['id']}"
        )
        return 0
    finally:
        await api.close()
        await database.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
