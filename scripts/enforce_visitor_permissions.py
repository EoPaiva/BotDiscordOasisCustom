from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import asyncio
import json
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import discord

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.config import AppConfig
from choque.database import Database
from choque.settings import SettingsService
from choque.visitor_access import (
    AccessLevel,
    all_category_keys,
    category_access,
    channel_access,
)
from scripts.provision_discord_layout import ROLE_IDS, permission_snapshot
from scripts.remodel_discord_layout import CATEGORY_BY_KEY, CHANNEL_BY_KEY, REGISTRY_SETTING

REASON = "Correcao de acesso de visitantes CHOQUE - BGR"


class VisitorPermissionClient(discord.Client):
    def __init__(
        self,
        config: AppConfig,
        *,
        apply: bool,
        rollback_path: Path | None,
    ) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(intents=intents)
        self.config = config
        self.apply = apply
        self.rollback_path = rollback_path
        self.database = Database(config.database_path, config.legacy_database_path)
        self.settings = SettingsService(self.database)
        self._ran = False
        self.exit_code = 1

    async def on_ready(self) -> None:
        if self._ran:
            return
        self._ran = True
        try:
            guild = self.get_guild(self.config.default_guild_id or 0)
            if guild is None:
                raise RuntimeError("Guild configurada nao foi encontrada pelo bot.")
            await self.database.open()
            if self.rollback_path is not None:
                await self.restore_snapshot(guild, self.rollback_path)
                await self.validate(guild)
                self.exit_code = 0
                print("VISITOR_PERMISSIONS_ROLLBACK_PASS")
                return

            registry = await self.load_registry(guild.id)
            snapshot = await self.backup(guild)
            if self.apply:
                await self.enforce(guild, registry)
            await self.validate(guild, registry=registry, require_real_visitor=self.apply)
            self.exit_code = 0
            mode = "APPLY" if self.apply else "DRY_RUN"
            print(f"VISITOR_PERMISSIONS_{mode}_PASS snapshot={snapshot.resolve()}")
        except Exception:
            traceback.print_exc()
        finally:
            await self.database.close()
            await self.close()

    async def load_registry(self, guild_id: int) -> dict[str, dict[str, int]]:
        stored = await self.settings.get(guild_id, REGISTRY_SETTING, {})
        if not isinstance(stored, dict):
            raise RuntimeError("Registry de layout ausente ou invalido.")
        registry: dict[str, dict[str, int]] = {}
        for group in ("categories", "channels"):
            values = stored.get(group)
            if not isinstance(values, dict):
                raise RuntimeError(f"Registry sem grupo obrigatorio: {group}")
            registry[group] = {str(key): int(value) for key, value in values.items()}

        missing_categories = set(CATEGORY_BY_KEY) - set(registry["categories"])
        missing_channels = set(CHANNEL_BY_KEY) - set(registry["channels"])
        if missing_categories or missing_channels:
            raise RuntimeError(
                "Registry incompleto: "
                f"categories={sorted(missing_categories)} channels={sorted(missing_channels)}"
            )
        if set(CATEGORY_BY_KEY) != set(all_category_keys()):
            raise RuntimeError("Politica de visitantes nao cobre todas as categorias do layout.")
        return registry

    async def backup(self, guild: discord.Guild) -> Path:
        destination = Path("data/server_layout_backups")
        destination.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = destination / f"visitor_permissions_{guild.id}_{timestamp}.json"
        payload = {
            "captured_at": datetime.now(UTC).isoformat(),
            "guild_id": guild.id,
            "channels": [
                {
                    "id": channel.id,
                    "type": str(channel.type),
                    "overwrites": permission_snapshot(channel),
                }
                for channel in guild.channels
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    async def set_access(
        channel: discord.abc.GuildChannel,
        guild: discord.Guild,
        member_role: discord.Role,
        access: AccessLevel,
    ) -> None:
        visitor_overwrite = channel.overwrites_for(guild.default_role)
        visitor_overwrite.view_channel = access == "public"
        if access == "public":
            visitor_overwrite.read_message_history = True
        await channel.set_permissions(
            guild.default_role,
            overwrite=visitor_overwrite,
            reason=REASON,
        )

        member_overwrite = channel.overwrites_for(member_role)
        member_overwrite.view_channel = access in {"public", "member"}
        if access in {"public", "member"}:
            member_overwrite.read_message_history = True
        await channel.set_permissions(
            member_role,
            overwrite=member_overwrite,
            reason=REASON,
        )

    async def enforce(
        self,
        guild: discord.Guild,
        registry: dict[str, dict[str, int]],
    ) -> None:
        member_role = guild.get_role(ROLE_IDS["member"])
        if member_role is None:
            raise RuntimeError("Cargo de membro configurado nao foi encontrado.")

        for category_key, category_id in registry["categories"].items():
            category = guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                raise RuntimeError(f"Categoria registrada nao encontrada: {category_key}")
            await self.set_access(category, guild, member_role, category_access(category_key))

        for channel_key, channel_id in registry["channels"].items():
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.abc.GuildChannel):
                raise RuntimeError(f"Canal registrado nao encontrado: {channel_key}")
            category_key = CHANNEL_BY_KEY[channel_key].category
            await self.set_access(
                channel,
                guild,
                member_role,
                channel_access(category_key, channel_key),
            )

    @staticmethod
    def overwrite_view_state(channel: discord.abc.GuildChannel, role: discord.Role) -> bool | None:
        return channel.overwrites_for(role).view_channel

    async def validate(
        self,
        guild: discord.Guild,
        *,
        registry: dict[str, dict[str, int]] | None = None,
        require_real_visitor: bool = False,
    ) -> None:
        if registry is None:
            registry = await self.load_registry(guild.id)
        member_role = guild.get_role(ROLE_IDS["member"])
        if member_role is None:
            raise RuntimeError("Cargo de membro configurado nao foi encontrado.")

        failures: list[str] = []
        for category_key, category_id in registry["categories"].items():
            category = guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                failures.append(f"missing-category:{category_key}")
                continue
            access = category_access(category_key)
            if self.overwrite_view_state(category, guild.default_role) is not (access == "public"):
                failures.append(f"visitor-category:{category_key}")
            if self.overwrite_view_state(category, member_role) is not (
                access in {"public", "member"}
            ):
                failures.append(f"member-category:{category_key}")

        visible_category_keys: set[str] = set()
        category_key_by_id = {
            category_id: category_key
            for category_key, category_id in registry["categories"].items()
        }
        visitor = next(
            (
                member
                for member in guild.members
                if not member.bot and len(member.roles) == 1
            ),
            None,
        )
        for channel_key, channel_id in registry["channels"].items():
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.abc.GuildChannel):
                failures.append(f"missing-channel:{channel_key}")
                continue
            category_key = CHANNEL_BY_KEY[channel_key].category
            access = channel_access(category_key, channel_key)
            if self.overwrite_view_state(channel, guild.default_role) is not (access == "public"):
                failures.append(f"visitor-channel:{channel_key}")
            if self.overwrite_view_state(channel, member_role) is not (
                access in {"public", "member"}
            ):
                failures.append(f"member-channel:{channel_key}")
            if visitor is not None and channel.permissions_for(visitor).view_channel:
                effective_category_key = category_key_by_id.get(
                    int(channel.category_id or 0), category_key
                )
                visible_category_keys.add(effective_category_key)
                if access != "public":
                    failures.append(f"real-visitor-leak:{channel_key}")

        if require_real_visitor and visitor is None:
            failures.append("real-visitor-account:not-found")
        if visitor is not None and visible_category_keys != {
            "reception",
            "ticket",
            "partnerships",
            "recruitment",
        }:
            failures.append(f"real-visitor-categories:{sorted(visible_category_keys)}")
        if failures:
            raise RuntimeError(f"Validacao de visitantes falhou: {failures}")
        print(
            "VISITOR_ACCOUNT_VALIDATED="
            f"{'true' if visitor is not None else 'false'} visible_categories=4"
        )

    async def restore_snapshot(self, guild: discord.Guild, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("guild_id", 0)) != guild.id:
            raise RuntimeError("Snapshot pertence a outra guild.")
        for item in payload.get("channels", []):
            channel = guild.get_channel(int(item["id"]))
            if not isinstance(channel, discord.abc.GuildChannel):
                continue
            overwrites: dict[Any, discord.PermissionOverwrite] = {}
            for raw in item.get("overwrites", []):
                target_id = int(raw["target_id"])
                target = guild.get_role(target_id)
                if target is None:
                    target = guild.get_member(target_id)
                if target is None:
                    continue
                overwrites[target] = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(int(raw["allow"])),
                    discord.Permissions(int(raw["deny"])),
                )
            await channel.edit(overwrites=overwrites, reason=f"{REASON} - rollback")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Corrige e valida o acesso de visitantes")
    parser.add_argument("--apply", action="store_true", help="Aplica as permissoes por ID")
    parser.add_argument("--rollback", type=Path, help="Restaura um snapshot criado por este script")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID sao obrigatorios.")
    client = VisitorPermissionClient(
        config,
        apply=bool(args.apply),
        rollback_path=args.rollback,
    )
    async with client:
        await client.start(config.token)
    return client.exit_code


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
