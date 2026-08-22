from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import discord

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402

ROLE_NAME = "EXONERADO"
SETTING_KEY = "dismissed_role_id"


class ExonerationRoleConfigurator(discord.Client):
    def __init__(self, config: AppConfig, *, apply: bool) -> None:
        super().__init__(intents=discord.Intents.none())
        self.config = config
        self.apply_changes = apply
        self.database = Database(config.database_path, config.legacy_database_path)
        self.settings = SettingsService(self.database)
        self.audit = AuditService(self.database, self.settings, config.branding)
        self._ran = False
        self.exit_code = 1

    async def on_ready(self) -> None:
        if self._ran:
            return
        self._ran = True
        try:
            await self.database.open()
            guild = self.get_guild(self.config.default_guild_id or 0)
            if guild is None:
                raise RuntimeError("Guild configurada não foi encontrada.")
            configured_id = await self.settings.get(guild.id, SETTING_KEY)
            configured_role = guild.get_role(int(configured_id)) if configured_id else None
            if configured_role is not None:
                print("EXONERATION_ROLE_OK configured=true")
                self.exit_code = 0
                return
            if not self.apply_changes:
                print("EXONERATION_ROLE_PENDING configured=false apply=false")
                self.exit_code = 2
                return

            backup_dir = PROJECT_ROOT / "data" / "server_layout_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_dir / f"exoneration_role_{guild.id}_{stamp}.json"
            backup_path.write_text(
                json.dumps(
                    {
                        "guild_id": guild.id,
                        "captured_at": stamp,
                        "roles": [
                            {
                                "id": role.id,
                                "name": role.name,
                                "position": role.position,
                                "permissions": role.permissions.value,
                                "color": role.color.value,
                                "hoist": role.hoist,
                                "mentionable": role.mentionable,
                            }
                            for role in guild.roles
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            role = await guild.create_role(
                name=ROLE_NAME,
                permissions=discord.Permissions.none(),
                color=discord.Color.from_rgb(78, 93, 108),
                hoist=True,
                mentionable=False,
                reason="Cargo funcional de exoneração CHOQUE - BGR",
            )
            await self.settings.set(
                guild.id,
                SETTING_KEY,
                role.id,
                self.user.id if self.user else None,
            )
            await self.audit.record(
                guild.id,
                "EXONERATION_ROLE_CONFIGURED",
                actor_id=self.user.id if self.user else None,
                target_id=role.id,
                after={"setting_key": SETTING_KEY, "role_id": role.id},
                reason="Ativação do fluxo administrativo de exoneração",
            )
            refreshed = next((item for item in await guild.fetch_roles() if item.id == role.id), None)
            if refreshed is None or refreshed.permissions.value != 0:
                raise RuntimeError("O cargo criado não foi confirmado pela API do Discord.")
            print(f"EXONERATION_ROLE_APPLIED backup={backup_path.name} configured=true")
            self.exit_code = 0
        except Exception as exc:
            print(f"EXONERATION_ROLE_FAILED type={type(exc).__name__}")
            self.exit_code = 1
        finally:
            await self.database.close()
            await self.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configura o cargo seguro de exoneração.")
    parser.add_argument("--apply", action="store_true", help="Cria e registra o cargo no Discord.")
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        print("EXONERATION_ROLE_FAILED type=MissingConfiguration")
        return 1
    client = ExonerationRoleConfigurator(config, apply=args.apply)
    await client.start(config.token)
    return client.exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
