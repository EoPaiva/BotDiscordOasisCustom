from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.channel_names import format_category_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402
from scripts.migrate_rec_choque import (  # noqa: E402
    DEFAULT_SOURCE_GUILD_ID,
    DEFAULT_TARGET_GUILD_ID,
    ChannelSpec,
    DiscordRest,
    _embed,
    _ensure_category,
    _ensure_channel,
    _permission_overwrites,
    _role_key,
    _upsert_panel,
)

MANAGER_ROLE_NAMES = (
    "Comando REC",
    "Responsável Recrutamento",
    "Auxiliar Recrutamento",
)
CHANNEL_SPEC = ChannelSpec(
    "recruitment.inactivity",
    "recruitment_admin",
    "Avisos de Inatividade",
    "⚠️",
    private=True,
)


def _validate_target_guild(guild: dict[str, object], expected_id: int) -> None:
    """Bind provisioning to the immutable Discord guild ID, never its display name."""
    actual_id = int(guild.get("id") or 0)
    if actual_id != expected_id:
        raise RuntimeError(
            f"Servidor de destino inesperado: esperado {expected_id}, recebido {actual_id}."
        )


def _unique_role_id(roles: list[dict[str, object]], name: str) -> int:
    matches = [
        role
        for role in roles
        if _role_key(str(role.get("name") or "")) == _role_key(name)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"O cargo {name!r} precisa existir uma única vez no REC CHOQUE; "
            f"encontrados: {len(matches)}."
        )
    return int(matches[0]["id"])


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token:
        raise RuntimeError("DISCORD_TOKEN não configurado.")
    source_guild_id = int(args.source_guild)
    target_guild_id = int(args.target_guild)
    api = DiscordRest(config.token)
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        target_guild, roles, channels = await asyncio.gather(
            api.request("GET", f"/guilds/{target_guild_id}"),
            api.request("GET", f"/guilds/{target_guild_id}/roles"),
            api.request("GET", f"/guilds/{target_guild_id}/channels"),
        )
        _validate_target_guild(target_guild, target_guild_id)
        manager_role_ids = [_unique_role_id(roles, name) for name in MANAGER_ROLE_NAMES]
        overwrites = _permission_overwrites(
            target_guild_id,
            staff_role_ids=manager_role_ids,
            private=True,
            writable=False,
        )
        category = await _ensure_category(
            api,
            target_guild_id,
            channels,
            format_category_name(2, "Administração do Recrutamento"),
            overwrites,
        )
        channel = await _ensure_channel(
            api,
            target_guild_id,
            channels,
            CHANNEL_SPEC,
            int(category["id"]),
            manager_role_ids,
        )

        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        actor_id = int(target_guild["owner_id"])
        await settings.set(
            source_guild_id,
            "activity_absence_alert_destination_guild_id",
            target_guild_id,
            actor_id,
        )
        await settings.set(
            source_guild_id,
            "activity_absence_alert_channel_id",
            int(channel["id"]),
            actor_id,
        )
        await settings.set(
            target_guild_id,
            "activity_absence_alert_channel_id",
            int(channel["id"]),
            actor_id,
        )
        await settings.set(
            target_guild_id,
            "activity_absence_alert_manager_role_ids",
            manager_role_ids,
            actor_id,
        )
        await _upsert_panel(
            api,
            settings,
            target_guild_id,
            "REC_INACTIVITY_ALERTS",
            int(channel["id"]),
            {
                "embeds": [
                    _embed(
                        "⚠️ Avisos de Inatividade",
                        (
                            "Este canal recebe os alertas de 3, 7 e 10 dias calculados pelo "
                            "cadastro oficial do servidor principal.\n\n"
                            "Cada aviso permite registrar ausência, silenciar novos alertas ou "
                            "desligar o membro por decisão humana confirmada. O desligamento "
                            "atinge o cadastro principal e o espelho do REC, encerra ponto aberto "
                            "e remove os cargos administrados nos dois servidores."
                        ),
                    )
                ],
                "components": [],
            },
        )
        await audit.record(
            source_guild_id,
            "REC_INACTIVITY_ALERT_CHANNEL_CONFIGURED",
            actor_id=actor_id,
            after={
                "destination_guild_id": target_guild_id,
                "channel_id": int(channel["id"]),
                "manager_role_ids": manager_role_ids,
            },
            reason="Canal administrativo solicitado para avisos e desligamento por inatividade.",
        )
        print(
            "REC_INACTIVITY_CONFIGURED "
            f"guild={target_guild_id} channel={int(channel['id'])} "
            f"managers={len(manager_role_ids)}"
        )
        return 0
    finally:
        await api.close()
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cria e vincula o canal de avisos de inatividade no REC CHOQUE."
    )
    parser.add_argument("--source-guild", default=DEFAULT_SOURCE_GUILD_ID, type=int)
    parser.add_argument("--target-guild", default=DEFAULT_TARGET_GUILD_ID, type=int)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
