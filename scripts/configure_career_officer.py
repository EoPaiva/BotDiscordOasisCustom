from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

import discord

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.channel_names import format_channel_name, normalize_stylized_label  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.embeds import branded_embed  # noqa: E402
from choque.models import RbacProfile  # noqa: E402
from choque.settings import SettingsService  # noqa: E402

CHANNELS: tuple[tuple[str, str, str, bool], ...] = (
    ("career_promotion_channel_id", "Promoções", "⬆️", False),
    ("career_automatic_progression_channel_id", "Progressão automática", "📈", False),
    ("career_demotion_channel_id", "Rebaixamentos", "⬇️", True),
    ("officer_candidacy_channel_id", "Candidatura oficial", "🛡️", False),
    ("officer_upamento_channel_id", "Upamentos", "🎖️", True),
)


class CareerConfigurator(discord.Client):
    def __init__(self, config: AppConfig, *, apply: bool, validate_only: bool) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(intents=intents)
        self.config = config
        self.apply_changes = apply
        self.validate_only = validate_only
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
                raise RuntimeError("Guild configurada não encontrada.")
            await self.database.open()
            if self.validate_only:
                result = await self.validate(guild)
                if result["failures"]:
                    raise RuntimeError(f"Validação falhou: {result['failures']}")
                print("CAREER_OFFICER_LIVE_PASS " + json.dumps(result, sort_keys=True))
            elif self.apply_changes:
                snapshot = await self.snapshot(guild)
                snapshot_path = PROJECT_ROOT / "data" / "backups" / (
                    "career-officer-layout-"
                    + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
                    + ".json"
                )
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot_path.write_text(
                    json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                await self.apply(guild)
                result = await self.validate(guild)
                if result["failures"]:
                    raise RuntimeError(f"Validação pós-aplicação falhou: {result['failures']}")
                print(
                    "CAREER_OFFICER_APPLY_PASS "
                    + json.dumps({**result, "snapshot": str(snapshot_path)}, sort_keys=True)
                )
            else:
                print("CAREER_OFFICER_PREVIEW=" + json.dumps(await self.preview(guild), sort_keys=True))
            self.exit_code = 0
        except Exception:
            traceback.print_exc()
        finally:
            await self.database.close()
            await self.close()

    async def _upamento_role(self, guild: discord.Guild) -> discord.Role:
        configured = await self.settings.get(guild.id, "officer_upamento_role_id")
        role = guild.get_role(int(configured)) if configured else None
        if role is None:
            candidates = [
                item
                for item in guild.roles
                if {"responsavel", "upamento"}
                <= set(normalize_stylized_label(item.name).split())
            ]
            if len(candidates) > 1:
                raise RuntimeError(
                    "Mais de um cargo de responsável por upamento foi encontrado; "
                    "configure o ID explicitamente antes de continuar."
                )
            role = candidates[0] if candidates else None
        if role is None:
            raise RuntimeError(
                "O cargo existente RESPONSÁVEL POR UPAMENTO não foi encontrado; nenhum cargo novo foi criado."
            )
        return role

    async def _command_roles(self, guild: discord.Guild) -> list[discord.Role]:
        rows = await self.database.fetchall(
            """
            SELECT DISTINCT drm.discord_role_id
            FROM discord_role_mappings drm
            JOIN access_profiles ap ON ap.id=drm.access_profile_id
            WHERE drm.guild_id=? AND drm.mapping_type='ACCESS' AND drm.enabled=1
              AND ap.code IN ('COMANDO','ALTO_COMANDO','ADMINISTRADOR')
            """,
            (guild.id,),
        )
        return [
            role
            for row in rows
            if (role := guild.get_role(int(row["discord_role_id"]))) is not None
        ]

    async def _category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        panel_id = await self.settings.get(guild.id, "career_panel_channel_id")
        panel = guild.get_channel(int(panel_id)) if panel_id else None
        if isinstance(panel, discord.TextChannel) and panel.category:
            return panel.category
        return next(
            (
                item
                for item in guild.categories
                if any(
                    self._normalized_label_matches(item.name, expected)
                    for expected in ("efetivo", "carreira")
                )
            ),
            None,
        )

    @staticmethod
    def _normalized_label_matches(value: str, expected: str) -> bool:
        normalized = normalize_stylized_label(value)
        target = normalize_stylized_label(expected)
        return normalized == target or normalized.endswith(f" {target}")

    @staticmethod
    def _find_channel(guild: discord.Guild, label: str) -> discord.TextChannel | None:
        key = normalize_stylized_label(label)
        aliases = {
            key,
            key.replace("candidatura oficial", "oficialato"),
            key.replace("progressao automatica", "progressao"),
        }
        return next(
            (
                channel
                for channel in guild.text_channels
                if any(
                    CareerConfigurator._normalized_label_matches(channel.name, alias)
                    for alias in aliases
                )
            ),
            None,
        )

    async def preview(self, guild: discord.Guild) -> dict[str, object]:
        role = await self._upamento_role(guild)
        return {
            "guild_id": guild.id,
            "upamento_role_id": role.id,
            "channels": {
                key: (self._find_channel(guild, label).id if self._find_channel(guild, label) else None)
                for key, label, _emoji, _private in CHANNELS
            },
        }

    async def snapshot(self, guild: discord.Guild) -> dict[str, object]:
        keys = [key for key, _label, _emoji, _private in CHANNELS]
        keys.append("officer_upamento_role_id")
        return {
            "guild_id": guild.id,
            "captured_at": datetime.now(UTC).isoformat(),
            "settings": {key: await self.settings.get(guild.id, key) for key in keys},
            "existing_channel_ids": [channel.id for channel in guild.text_channels],
        }

    async def apply(self, guild: discord.Guild) -> None:
        role = await self._upamento_role(guild)
        command_roles = await self._command_roles(guild)
        category = await self._category(guild)
        bot_member = guild.me
        if bot_member is None:
            raise RuntimeError("Membro do bot não foi encontrado.")
        channels: dict[str, discord.TextChannel] = {}
        for key, label, emoji, private in CHANNELS:
            channel = self._find_channel(guild, label)
            overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=False if private else True,
                    send_messages=False,
                    read_message_history=True,
                ),
                bot_member: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    read_message_history=True,
                ),
            }
            if private:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=False, read_message_history=True
                )
                for command_role in command_roles:
                    overwrites[command_role] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=False, read_message_history=True
                    )
            if channel is None:
                channel = await guild.create_text_channel(
                    format_channel_name(label, emoji),
                    category=category,
                    overwrites=overwrites,
                    reason="Central integrada de carreira, mérito e oficialato",
                )
            else:
                await channel.edit(
                    category=channel.category or category,
                    overwrites=overwrites,
                    reason="Proteção da central integrada de carreira e oficialato",
                )
            channels[key] = channel
            await self.settings.set(guild.id, key, channel.id, bot_member.id)

        await self.settings.set(
            guild.id, "officer_upamento_role_id", role.id, bot_member.id
        )
        await self.settings.bind_role(
            guild.id,
            role.id,
            RbacProfile.OFFICER_REVIEWER,
            bot_member.id,
            "OFFICER_UPAMENTO_ROLE_CONFIGURED",
        )
        await self._upsert_panel(
            guild,
            channels["officer_candidacy_channel_id"],
            "OFFICER_CANDIDACY",
            title="🛡️ Candidatura ao Oficialato",
            description=(
                "Processo interno para militares elegíveis. O questionário possui 30 perguntas "
                "profissionais e é respondido somente no site. A análise automática é consultiva; "
                "a decisão final é sempre humana."
            ),
            url="https://choquebgr.online/candidatura-oficial",
            button_label="Abrir candidatura",
        )
        await self._upsert_panel(
            guild,
            channels["officer_upamento_channel_id"],
            "OFFICER_UPAMENTO",
            title="🎖️ Central de Upamentos",
            description=(
                "Fila privada dos responsáveis. Assuma, entreviste, pontue e registre a decisão "
                "humana no Centro de Comando."
            ),
            url="https://choquebgr.online/central-upamentos",
            button_label="Abrir fila no site",
        )
        await self.audit.record(
            guild.id,
            "CAREER_OFFICER_LAYOUT_CONFIGURED",
            actor_id=bot_member.id,
            after={
                "upamento_role_id": role.id,
                "channels": {key: channel.id for key, channel in channels.items()},
            },
        )

    async def _upsert_panel(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        panel_type: str,
        *,
        title: str,
        description: str,
        url: str,
        button_label: str,
    ) -> None:
        panel = await self.settings.get_panel(guild.id, panel_type)
        message = None
        if panel and int(panel["channel_id"]) == channel.id:
            try:
                message = await channel.fetch_message(int(panel["message_id"]))
            except discord.DiscordException:
                message = None
        embed = branded_embed(self.config.branding, title=title, description=description)
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label=button_label, url=url))
        if message is None:
            message = await channel.send(embed=embed, view=view)
        else:
            await message.edit(embed=embed, view=view)
        try:
            await message.pin(reason="Painel persistente de carreira e oficialato")
        except discord.HTTPException:
            pass
        await self.settings.upsert_panel(guild.id, panel_type, channel.id, message.id)

    async def validate(self, guild: discord.Guild) -> dict[str, object]:
        failures: list[str] = []
        role = await self._upamento_role(guild)
        mapping = await self.database.fetchone(
            """
            SELECT ap.code FROM discord_role_mappings drm
            JOIN access_profiles ap ON ap.id=drm.access_profile_id
            WHERE drm.guild_id=? AND drm.discord_role_id=?
              AND drm.mapping_type='ACCESS' AND drm.enabled=1
            """,
            (guild.id, role.id),
        )
        if not mapping or mapping["code"] != RbacProfile.OFFICER_REVIEWER.value:
            failures.append("upamento-role-rbac")
        channel_ids: dict[str, int] = {}
        for key, _label, _emoji, private in CHANNELS:
            value = await self.settings.get(guild.id, key)
            channel = guild.get_channel(int(value)) if value else None
            if not isinstance(channel, discord.TextChannel):
                failures.append(key)
                continue
            channel_ids[key] = channel.id
            if private and channel.permissions_for(guild.default_role).view_channel:
                failures.append(f"{key}-public")
            if private and not channel.permissions_for(role).view_channel:
                failures.append(f"{key}-responsible-denied")
        for panel_type in ("OFFICER_CANDIDACY", "OFFICER_UPAMENTO"):
            panel = await self.settings.get_panel(guild.id, panel_type)
            if not panel:
                failures.append(f"panel-{panel_type.lower()}")
        question_count = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM officer_questions oq
            JOIN officer_questionnaire_versions oqv
              ON oqv.id=oq.questionnaire_version_id
            WHERE oqv.guild_id=? AND oqv.status='ACTIVE'
            """,
            (guild.id,),
        )
        if int(question_count["total"]) != 30:
            failures.append("questionnaire-30")
        return {
            "failures": failures,
            "role_id": role.id,
            "channels": channel_ids,
            "question_count": int(question_count["total"]),
        }


async def async_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    client = CareerConfigurator(
        config, apply=args.apply, validate_only=args.validate_only
    )
    await client.start(config.token)
    return client.exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
