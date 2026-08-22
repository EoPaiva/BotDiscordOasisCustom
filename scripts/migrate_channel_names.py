from __future__ import annotations

import argparse
import asyncio
import json
import traceback
from pathlib import Path

import discord

from choque.audit import AuditService
from choque.channel_names import (
    CHANNEL_SEPARATOR,
    CHANNEL_SEPARATOR_FALLBACK,
    format_channel_name,
)
from choque.config import AppConfig
from choque.database import Database
from choque.settings import SettingsService
from scripts.provision_discord_layout import ProvisionClient
from scripts.remodel_discord_layout import CHANNEL_BY_KEY, REGISTRY_SETTING

REASON = "Correcao centralizada dos nomes CHOQUE - BGR"


class ChannelNameMigrationClient(discord.Client):
    def __init__(
        self,
        config: AppConfig,
        *,
        apply: bool,
        rollback_path: Path | None,
    ) -> None:
        super().__init__(intents=discord.Intents.default())
        self.config = config
        self.apply = apply
        self.rollback_path = rollback_path
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
            guild = self.get_guild(self.config.default_guild_id or 0)
            if guild is None:
                raise RuntimeError("Guild configurada não foi encontrada.")
            await self.database.open()
            snapshot = await self.snapshot(guild)
            if self.rollback_path is not None:
                restored = await self.rollback(guild, self.rollback_path)
                print(f"CHANNEL_NAME_ROLLBACK_PASS restored={restored} snapshot={snapshot.resolve()}")
                self.exit_code = 0
                return
            registry = await self.load_registry(guild.id)
            result = await self.migrate(guild, registry)
            if self.apply and result["review"]:
                restored = await self.rollback(guild, snapshot)
                raise RuntimeError(
                    "Migração Small Caps incompleta; rollback global aplicado "
                    f"a {restored} canal(is)."
                )
            mode = "APPLY" if self.apply else "DRY_RUN"
            print(f"CHANNEL_NAME_{mode}_PASS snapshot={snapshot.resolve()}")
            print(
                f"identified={result['identified']} migrated={result['migrated']} "
                f"fallback={result['fallback']} review={result['review']} "
                f"labels_identified={result['labels_identified']} "
                f"labels_updated={result['labels_updated']}"
            )
            self.exit_code = 0
        except Exception:
            traceback.print_exc()
        finally:
            await self.database.close()
            await self.close()

    async def load_registry(self, guild_id: int) -> dict[str, int]:
        registry = await self.settings.get(guild_id, REGISTRY_SETTING, {})
        channels = registry.get("channels", {}) if isinstance(registry, dict) else {}
        if set(channels) != set(CHANNEL_BY_KEY):
            missing = sorted(set(CHANNEL_BY_KEY) - set(channels))
            extra = sorted(set(channels) - set(CHANNEL_BY_KEY))
            raise RuntimeError(f"Registry divergente: missing={missing} extra={extra}")
        return {str(key): int(value) for key, value in channels.items()}

    async def snapshot(self, guild: discord.Guild) -> Path:
        helper = ProvisionClient(self.config, apply=False)
        try:
            await helper.backup(guild)
        finally:
            await helper.close()
        destination = Path("data/server_layout_backups")
        return max(destination.glob(f"discord_layout_{guild.id}_*.json"), key=lambda p: p.stat().st_mtime)

    async def migrate(self, guild: discord.Guild, registry: dict[str, int]) -> dict[str, int]:
        result = {
            "identified": 0,
            "migrated": 0,
            "fallback": 0,
            "review": 0,
            "labels_identified": 0,
            "labels_updated": 0,
        }
        for channel_key, channel_id in registry.items():
            spec = CHANNEL_BY_KEY[channel_key]
            channel = guild.get_channel(channel_id)
            expected_type = discord.TextChannel if spec.kind == "text" else discord.VoiceChannel
            if not isinstance(channel, expected_type):
                result["review"] += 1
                if self.apply:
                    await self.audit.record(
                        guild.id,
                        "CHANNEL_NAME_REVIEW_REQUIRED",
                        target_id=channel_id,
                        after={
                            "channel_key": channel_key,
                            "reason": "CHANNEL_NOT_FOUND_OR_WRONG_TYPE",
                        },
                    )
                continue
            await self._migrate_channel(
                guild,
                channel,
                expected=spec.visual_name,
                internal_key=channel_key,
                result=result,
            )

        rooms = await self.database.fetchall(
            """
            SELECT ticket_id, channel_id, status
            FROM ticket_rooms
            WHERE guild_id=?
            ORDER BY ticket_id
            """,
            (guild.id,),
        )
        for room in rooms:
            channel_id = int(room["channel_id"])
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                result["review"] += 1
                if self.apply:
                    await self.audit.record(
                        guild.id,
                        "CHANNEL_NAME_REVIEW_REQUIRED",
                        target_id=channel_id,
                        after={
                            "ticket_id": int(room["ticket_id"]),
                            "reason": "TICKET_ROOM_NOT_FOUND_OR_WRONG_TYPE",
                        },
                    )
                continue
            ticket_id = int(room["ticket_id"])
            archived = str(room["status"]) == "ARCHIVED"
            label = f"Arquivo{ticket_id:04d}" if archived else f"Ticket{ticket_id:04d}"
            emoji = "📁" if archived else "🎫"
            await self._migrate_channel(
                guild,
                channel,
                expected=format_channel_name(label, emoji),
                internal_key=f"ticket_room:{ticket_id}",
                result=result,
            )
        await self._reconcile_authorized_labels(guild, result)
        return result

    async def _reconcile_authorized_labels(
        self,
        guild: discord.Guild,
        result: dict[str, int],
    ) -> None:
        rows = await self.database.fetchall(
            """
            SELECT channel_id, label FROM authorized_voice_channels
            WHERE guild_id=? ORDER BY channel_id
            """,
            (guild.id,),
        )
        for row in rows:
            channel_id = int(row["channel_id"])
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.VoiceChannel):
                result["review"] += 1
                continue
            if str(row["label"]) == channel.name:
                continue
            result["labels_identified"] += 1
            if not self.apply:
                continue
            await self.database.execute(
                """
                UPDATE authorized_voice_channels SET label=?
                WHERE guild_id=? AND channel_id=?
                """,
                (channel.name, guild.id, channel_id),
            )
            result["labels_updated"] += 1
            await self.audit.record(
                guild.id,
                "AUTHORIZED_VOICE_LABEL_RECONCILED",
                actor_id=self.user.id if self.user else None,
                target_id=channel_id,
                before={"label": str(row["label"])},
                after={"label": channel.name},
            )

    async def _migrate_channel(
        self,
        guild: discord.Guild,
        channel: discord.abc.GuildChannel,
        *,
        expected: str,
        internal_key: str,
        result: dict[str, int],
    ) -> None:
        if channel.name == expected:
            return
        result["identified"] += 1
        if not self.apply:
            return
        before = channel.name
        await channel.edit(name=expected, reason=REASON)
        fetched = await guild.fetch_channel(channel.id)
        used_fallback = False
        if fetched.name != expected:
            if CHANNEL_SEPARATOR not in expected:
                await fetched.edit(name=before, reason=f"{REASON} - rollback automatico")
                restored = await guild.fetch_channel(channel.id)
                result["review"] += 1
                await self.audit.record(
                    guild.id,
                    "CHANNEL_NAME_REVIEW_REQUIRED",
                    target_id=channel.id,
                    before={"name": before},
                    after={
                        "expected": expected,
                        "received": fetched.name,
                        "restored": restored.name,
                        "internal_key": internal_key,
                    },
                    reason="DISCORD_NORMALIZED_SMALL_CAPS_NAME",
                )
                if restored.name != before:
                    raise RuntimeError(f"Rollback automático falhou para o canal {channel.id}")
                return
            fallback = expected.replace(CHANNEL_SEPARATOR, CHANNEL_SEPARATOR_FALLBACK)
            await fetched.edit(name=fallback, reason=f"{REASON} - fallback")
            fetched = await guild.fetch_channel(channel.id)
            used_fallback = True
            if fetched.name != fallback:
                await fetched.edit(name=before, reason=f"{REASON} - rollback automatico")
                restored = await guild.fetch_channel(channel.id)
                result["review"] += 1
                await self.audit.record(
                    guild.id,
                    "CHANNEL_NAME_REVIEW_REQUIRED",
                    target_id=channel.id,
                    before={"name": before},
                    after={
                        "expected": expected,
                        "fallback": fallback,
                        "received": fetched.name,
                        "restored": restored.name,
                        "internal_key": internal_key,
                    },
                    reason="DISCORD_NORMALIZED_PRIMARY_AND_FALLBACK",
                )
                if restored.name != before:
                    raise RuntimeError(f"Rollback automático falhou para o canal {channel.id}")
                return
        if fetched.mention != f"<#{channel.id}>":
            raise RuntimeError(f"Menção alterada para o canal {channel.id}")
        result["migrated"] += 1
        result["fallback"] += int(used_fallback)
        await self.audit.record(
            guild.id,
            "CHANNEL_NAME_MIGRATED",
            actor_id=self.user.id if self.user else None,
            target_id=channel.id,
            before={"name": before},
            after={
                "name": fetched.name,
                "internal_key": internal_key,
                "fallback": used_fallback,
            },
        )

    async def rollback(self, guild: discord.Guild, path: Path) -> int:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("guild", {}).get("id", 0)) != guild.id:
            raise RuntimeError("Snapshot pertence a outra guild.")
        restored = 0
        for item in payload.get("channels", []):
            channel = guild.get_channel(int(item["id"]))
            if isinstance(channel, discord.abc.GuildChannel) and channel.name != item["name"]:
                await channel.edit(name=str(item["name"]), reason=f"{REASON} - rollback")
                restored += 1
        return restored


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migra nomes de canais por registry e ID")
    parser.add_argument("--apply", action="store_true", help="Aplica os renames identificados")
    parser.add_argument("--rollback", type=Path, help="Restaura somente os nomes de um snapshot")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    client = ChannelNameMigrationClient(
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
