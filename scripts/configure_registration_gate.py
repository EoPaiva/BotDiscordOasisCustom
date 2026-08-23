from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import discord

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.registration_gate import RegistrationGateService  # noqa: E402
from choque.settings import SettingsService  # noqa: E402
from choque.time_utils import utc_now_ms  # noqa: E402
from choque.visitor_access import category_access, channel_access  # noqa: E402
from scripts.provision_discord_layout import permission_snapshot  # noqa: E402
from scripts.remodel_discord_layout import CHANNEL_BY_KEY, REGISTRY_SETTING  # noqa: E402

REASON = "Portaria Digital CHOQUE - BGR"
NON_RANK_GROUP_ROLE_IDS = frozenset(
    {
        1146622062966886412,  # Praças
        1146622062966886417,  # Praças Graduados
        1161734642349637674,  # Oficiais
    }
)
OFFICIAL_NICKNAME = re.compile(
    r"^\[[^\]]{1,20}\]\s*(?P<nick>.+?)\s*\[(?P<bgr>[A-Za-z0-9._-]{1,32})\]$"
)
SETTING_KEYS = (
    "registration_gate_enabled",
    "unregistered_role_id",
    "candidate_role_id",
    "member_role_id",
    "registration_onboarding_category_id",
    "registration_panel_channel_id",
    "registration_support_channel_id",
    "registration_onboarding_channel_ids",
    "registration_bypass_role_ids",
    "registration_bypass_user_ids",
    "registration_dm_enabled",
    "registration_gate_activated_at",
)


def overwrite_digest(channel: discord.abc.GuildChannel) -> str:
    return json.dumps(permission_snapshot(channel), sort_keys=True, separators=(",", ":"))


class RegistrationGateConfigurator(discord.Client):
    def __init__(
        self,
        config: AppConfig,
        *,
        apply: bool,
        validate_only: bool,
        rollback_path: Path | None,
    ) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(intents=intents)
        self.config = config
        self.apply = apply
        self.validate_only = validate_only
        self.rollback_path = rollback_path
        self.database = Database(config.database_path, config.legacy_database_path)
        self.settings = SettingsService(self.database)
        self.audit = AuditService(self.database, self.settings, config.branding)
        self.gate = RegistrationGateService(self.database, self.settings, self.audit)
        self._ran = False
        self.exit_code = 1

    async def on_ready(self) -> None:
        if self._ran:
            return
        self._ran = True
        try:
            guild = self.get_guild(self.config.default_guild_id or 0)
            if guild is None:
                raise RuntimeError("Guild configurada não foi encontrada pelo bot.")
            await self.database.open()
            if self.validate_only:
                validation = await self.validate(guild)
                counts = await self.gate.counts(guild.id)
                if validation["leaks"] or validation["unclassified"]:
                    raise RuntimeError(f"Validação da Portaria falhou: {validation}")
                self.exit_code = 0
                print(
                    "REGISTRATION_GATE_LIVE_PASS "
                    f"protected={validation['protected']} onboarding={validation['onboarding']} "
                    f"restricted_role_members={validation['restricted_role_members']} "
                    f"sampled_accounts={validation['sampled_restricted_accounts']} "
                    f"panel_message_id={validation['panel_message_id']} "
                    f"unregistered={counts['UNREGISTERED']} pending={counts['PENDING']} "
                    f"review={counts['REQUIRES_REVIEW']}"
                )
                return
            if self.rollback_path:
                await self.rollback(guild, self.rollback_path)
                self.exit_code = 0
                print("REGISTRATION_GATE_ROLLBACK_PASS")
                return
            registry = await self.load_registry(guild.id)
            preview = await self.preview(guild, registry)
            print("REGISTRATION_GATE_PREVIEW=" + json.dumps(preview, sort_keys=True))
            if not self.apply:
                self.exit_code = 0
                print("REGISTRATION_GATE_DRY_RUN_PASS")
                return
            snapshot_path, snapshot = await self.capture_snapshot(guild)
            try:
                await self.apply_gate(guild, registry, snapshot)
                validation = await self.validate(guild)
                if validation["leaks"] or validation["unclassified"]:
                    raise RuntimeError(f"Validação da Portaria falhou: {validation}")
                await self.gate.set_configuration(
                    guild.id,
                    {
                        "registration_gate_enabled": True,
                        "registration_dm_enabled": True,
                    },
                    actor_id=self.user.id if self.user else 0,
                )
                await self.settings.set(
                    guild.id,
                    "registration_gate_activated_at",
                    utc_now_ms(),
                    self.user.id if self.user else None,
                )
                await self.audit.record(
                    guild.id,
                    "REGISTRATION_GATE_ACTIVATED",
                    actor_id=self.user.id if self.user else None,
                    after={**preview, **validation, "snapshot": str(snapshot_path)},
                )
                snapshot["post_apply"] = self.capture_post_apply(guild)
                snapshot_path.write_text(
                    json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                operation_id = await self.gate.store_permission_snapshot(
                    guild.id,
                    snapshot,
                    actor_id=self.user.id if self.user else None,
                    status="APPLIED",
                )
                print(
                    "REGISTRATION_GATE_APPLY_PASS "
                    f"snapshot={snapshot_path.resolve()} operation_id={operation_id} "
                    f"protected={validation['protected']} onboarding={validation['onboarding']}"
                )
            except Exception:
                await self.restore_in_memory(guild, snapshot, compare_post_apply=False)
                raise
            self.exit_code = 0
        except Exception:
            traceback.print_exc()
        finally:
            await self.database.close()
            await self.close()

    async def load_registry(self, guild_id: int) -> dict[str, dict[str, int]]:
        raw = await self.settings.get(guild_id, REGISTRY_SETTING, {})
        if not isinstance(raw, dict):
            raise RuntimeError("Registry do layout ausente.")
        result: dict[str, dict[str, int]] = {}
        for group in ("categories", "channels"):
            values = raw.get(group)
            if not isinstance(values, dict):
                raise RuntimeError(f"Registry sem o grupo {group}.")
            result[group] = {str(key): int(value) for key, value in values.items()}
        for required in ("reception", "registration", "ticket", "recruitment", "partnerships"):
            if required not in result["categories"]:
                raise RuntimeError(f"Categoria obrigatória não registrada: {required}")
        for required in ("registration.panel", "ticket.panel"):
            if required not in result["channels"]:
                raise RuntimeError(f"Canal obrigatório não registrado: {required}")
        return result

    async def preview(
        self, guild: discord.Guild, registry: dict[str, dict[str, int]]
    ) -> dict[str, int]:
        known_active = {
            int(row["discord_id"])
            for row in await self.database.fetchall(
                "SELECT discord_id FROM members WHERE guild_id=? AND status='ACTIVE'",
                (guild.id,),
            )
        }
        recruitment = {
            int(row["discord_id"])
            for row in await self.database.fetchall(
                """
                SELECT discord_id FROM recruitment_applications
                WHERE guild_id=? AND status IN (
                  'SUBMITTED','UNDER_REVIEW','INTERVIEW_PENDING','INTERVIEW_SCHEDULED',
                  'INTERVIEW_COMPLETED','FINAL_REVIEW','APPROVED'
                )
                """,
                (guild.id,),
            )
        }
        protected = await self.protected_ids(guild)
        humans = [member for member in guild.members if not member.bot and member.id not in protected]
        rank_role_ids = {
            int(row["discord_role_id"])
            for row in await self.database.fetchall(
                """
                SELECT discord_role_id FROM ranks
                WHERE guild_id=? AND active=1 AND discord_role_id IS NOT NULL
                """,
                (guild.id,),
            )
            if int(row["discord_role_id"]) not in NON_RANK_GROUP_ROLE_IDS
        }
        member_role_id = await self.settings.get(guild.id, "member_role_id")
        legacy_identified = {
            member.id
            for member in humans
            if OFFICIAL_NICKNAME.fullmatch(member.display_name)
            and any(
                role.id in rank_role_ids | ({int(member_role_id)} if member_role_id else set())
                for role in member.roles
            )
        }
        affected = [
            member
            for member in humans
            if member.id not in known_active | recruitment | legacy_identified
        ]
        managed_role_holders = {
            member.id
            for member in humans
            if any(
                role.id in rank_role_ids | ({int(member_role_id)} if member_role_id else set())
                for role in member.roles
            )
        }
        review = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total FROM registration_gate_records
            WHERE guild_id=? AND status='REQUIRES_REVIEW'
            """,
            (guild.id,),
        )
        internal = sum(
            category_access(key) != "public" for key in registry["categories"]
        )
        return {
            "users_affected": len(affected),
            "registered_members": len(known_active),
            "candidates": len(recruitment),
            "legacy_identified": len(legacy_identified),
            "legacy_rank_without_identity": len(
                managed_role_holders - known_active - recruitment - legacy_identified
            ),
            "pure_visitors": len(
                {member.id for member in affected} - managed_role_holders
            ),
            "requires_review": int(review["total"] if review else 0),
            "categories_protected": internal,
            "channels_total": len(guild.channels),
        }

    async def protected_ids(self, guild: discord.Guild) -> set[int]:
        bypass_users = {
            int(value)
            for value in await self.settings.get(guild.id, "registration_bypass_user_ids", [])
        }
        bypass_roles = {
            int(value)
            for value in await self.settings.get(guild.id, "registration_bypass_role_ids", [])
        }
        result = {guild.owner_id, *bypass_users}
        for member in guild.members:
            if member.bot or member.guild_permissions.administrator:
                result.add(member.id)
            elif any(role.id in bypass_roles for role in member.roles):
                result.add(member.id)
        return result

    async def capture_snapshot(
        self, guild: discord.Guild
    ) -> tuple[Path, dict[str, Any]]:
        destination = Path("data/server_layout_backups")
        destination.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = destination / f"registration_gate_{guild.id}_{timestamp}.json"
        settings = {key: await self.settings.get(guild.id, key) for key in SETTING_KEYS}
        classifications = [
            dict(row) for row in await self.gate.classifications(guild.id)
        ]
        snapshot: dict[str, Any] = {
            "captured_at": datetime.now(UTC).isoformat(),
            "guild_id": guild.id,
            "settings": settings,
            "classifications": classifications,
            "created_role_ids": [],
            "channels": [
                {
                    "id": channel.id,
                    "parent_id": channel.category_id,
                    "position": channel.position,
                    "overwrites": permission_snapshot(channel),
                    "digest": overwrite_digest(channel),
                }
                for channel in guild.channels
            ],
            "member_roles": {
                str(member.id): sorted(role.id for role in member.roles if not role.is_default())
                for member in guild.members
                if not member.bot
            },
        }
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return path, snapshot

    async def resolve_or_create_role(
        self,
        guild: discord.Guild,
        setting_key: str,
        name: str,
        snapshot: dict[str, Any],
    ) -> discord.Role:
        role_id = await self.settings.get(guild.id, setting_key)
        role = guild.get_role(int(role_id)) if role_id else None
        if role is None:
            role = await guild.create_role(
                name=name,
                permissions=discord.Permissions.none(),
                colour=discord.Colour.dark_grey(),
                hoist=False,
                mentionable=False,
                reason=REASON,
            )
            snapshot["created_role_ids"].append(role.id)
        return role

    async def apply_gate(
        self,
        guild: discord.Guild,
        registry: dict[str, dict[str, int]],
        snapshot: dict[str, Any],
    ) -> None:
        actor_id = self.user.id if self.user else 0
        unregistered = await self.resolve_or_create_role(
            guild, "unregistered_role_id", "Aguardando Cadastro", snapshot
        )
        candidate = await self.resolve_or_create_role(
            guild, "candidate_role_id", "Candidato", snapshot
        )
        member_role_id = await self.settings.get(guild.id, "member_role_id")
        member_role = guild.get_role(int(member_role_id)) if member_role_id else None
        if member_role is None:
            raise RuntimeError("Cargo base de membro não foi configurado.")
        bot_member = guild.me
        if not bot_member or not bot_member.guild_permissions.manage_roles:
            raise RuntimeError("O bot não possui Manage Roles.")
        for role in (unregistered, candidate, member_role):
            if role >= bot_member.top_role:
                raise RuntimeError(f"O cargo do bot não está acima de {role.name}.")

        reception = guild.get_channel(registry["categories"]["reception"])
        panel = guild.get_channel(registry["channels"]["registration.panel"])
        support = guild.get_channel(registry["channels"]["ticket.panel"])
        if not isinstance(reception, discord.CategoryChannel):
            raise RuntimeError("Categoria de recepção inválida.")
        if not isinstance(panel, discord.TextChannel) or not isinstance(
            support, discord.TextChannel
        ):
            raise RuntimeError("Painel da Portaria ou suporte inválido.")
        if panel.category_id != reception.id:
            await panel.edit(category=reception, sync_permissions=False, reason=REASON)

        category_keys = {value: key for key, value in registry["categories"].items()}
        channel_keys = {value: key for key, value in registry["channels"].items()}
        onboarding_ids: list[int] = []
        for channel in guild.channels:
            if isinstance(channel, discord.CategoryChannel):
                resource_type = "CATEGORY"
                key = category_keys.get(channel.id)
                access = category_access(key) if key else "member"
                internal_key = key or f"unmanaged.category.{channel.id}"
            else:
                resource_type = "CHANNEL"
                key = channel_keys.get(channel.id)
                if key == "registration.panel":
                    access = "public"
                elif key and key in CHANNEL_BY_KEY:
                    access = channel_access(CHANNEL_BY_KEY[key].category, key)
                else:
                    access = "member"
                internal_key = key or f"unmanaged.channel.{channel.id}"
            access_class = (
                "ONBOARDING_VISIBLE"
                if access == "public"
                else "STAFF_ONLY"
                if access == "private"
                else "MEMBER_ONLY"
            )
            await self.gate.classify_resource(
                guild.id,
                resource_type=resource_type,
                resource_id=channel.id,
                internal_key=internal_key,
                access_class=access_class,
                actor_id=actor_id,
            )
            if access == "public" and resource_type == "CHANNEL":
                onboarding_ids.append(channel.id)
            await self.set_access(channel, guild, member_role, unregistered, candidate, access)

        await self.gate.set_configuration(
            guild.id,
            {
                "unregistered_role_id": unregistered.id,
                "candidate_role_id": candidate.id,
                "member_role_id": member_role.id,
                "registration_onboarding_category_id": reception.id,
                "registration_panel_channel_id": panel.id,
                "registration_support_channel_id": support.id,
                "registration_onboarding_channel_ids": sorted(onboarding_ids),
            },
            actor_id=actor_id,
        )
        await self.bootstrap_legacy_members(guild, member_role)
        await self.reconcile_roles(guild, unregistered, candidate, member_role)

    async def bootstrap_legacy_members(
        self, guild: discord.Guild, member_role: discord.Role
    ) -> int:
        rank_rows = await self.database.fetchall(
            """
            SELECT id, name, level, discord_role_id FROM ranks
            WHERE guild_id=? AND active=1 AND discord_role_id IS NOT NULL
            ORDER BY level DESC
            """,
            (guild.id,),
        )
        ranks_by_role = {
            int(row["discord_role_id"]): row
            for row in rank_rows
            if int(row["discord_role_id"]) not in NON_RANK_GROUP_ROLE_IDS
        }
        protected = await self.protected_ids(guild)
        created = 0
        for target in guild.members:
            if target.bot or target.id in protected:
                continue
            if await self.database.fetchone(
                "SELECT 1 FROM members WHERE guild_id=? AND discord_id=?",
                (guild.id, target.id),
            ):
                continue
            match = OFFICIAL_NICKNAME.fullmatch(target.display_name)
            matched_ranks = [ranks_by_role[role.id] for role in target.roles if role.id in ranks_by_role]
            if not match or (member_role not in target.roles and not matched_ranks):
                continue
            rank = max(matched_ranks, key=lambda row: int(row["level"])) if matched_ranks else None
            bgr_id = match.group("bgr")
            conflict = await self.database.fetchone(
                """
                SELECT 1 FROM members
                WHERE guild_id=? AND lower(trim(character_id))=lower(trim(?))
                """,
                (guild.id, bgr_id),
            )
            if conflict:
                continue
            now = utc_now_ms()
            async with self.database.transaction() as connection:
                cursor = await connection.execute(
                    """
                    INSERT INTO members(
                        guild_id, discord_id, discord_nick, mta_nick, character_id,
                        rank_id, unit, status, joined_at, last_activity_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'BGR', 'ACTIVE', ?, ?, ?, ?)
                    """,
                    (
                        guild.id,
                        target.id,
                        target.name,
                        match.group("nick").strip(),
                        bgr_id,
                        int(rank["id"]) if rank else None,
                        now,
                        now,
                        now,
                        now,
                    ),
                )
                member_id = int(cursor.lastrowid)
                tier = (
                    "RECRUIT"
                    if rank and "RECRUTA" in str(rank["name"]).upper()
                    else "MEMBER"
                )
                await connection.execute(
                    """
                    INSERT INTO registration_gate_records(
                        guild_id, discord_id, status, access_tier, mta_nick, bgr_id,
                        member_id, source, sync_status, completed_at,
                        created_at, updated_at
                    ) VALUES (?, ?, 'REGISTERED', ?, ?, ?, ?,
                              'SYSTEM_RECONCILIATION', 'PENDING', ?, ?, ?)
                    """,
                    (
                        guild.id,
                        target.id,
                        tier,
                        match.group("nick").strip(),
                        bgr_id,
                        member_id,
                        now,
                        now,
                        now,
                    ),
                )
                registration = await connection.execute(
                    """
                    SELECT id FROM registration_gate_records
                    WHERE guild_id=? AND discord_id=?
                    """,
                    (guild.id, target.id),
                )
                registration_id = int((await registration.fetchone())["id"])
                await connection.execute(
                    """
                    INSERT INTO registration_gate_events(
                        guild_id, registration_id, event_type, actor_id, source,
                        metadata_json, created_at
                    ) VALUES (?, ?, 'REGISTRATION_RECONCILED', ?,
                              'SYSTEM_RECONCILIATION', ?, ?)
                    """,
                    (
                        guild.id,
                        registration_id,
                        self.user.id if self.user else None,
                        json.dumps({"legacy_import": True, "rank_id": int(rank["id"]) if rank else None}),
                        now,
                    ),
                )
                await self.audit.record(
                    guild.id,
                    "REGISTRATION_LEGACY_IDENTITY_IMPORTED",
                    actor_id=self.user.id if self.user else None,
                    target_id=target.id,
                    after={"registration_id": registration_id, "member_id": member_id},
                    connection=connection,
                )
            created += 1
        return created

    @staticmethod
    async def set_access(
        channel: discord.abc.GuildChannel,
        guild: discord.Guild,
        member_role: discord.Role,
        unregistered: discord.Role,
        candidate: discord.Role,
        access: str,
    ) -> None:
        for role, can_view in (
            (guild.default_role, access == "public"),
            (unregistered, access == "public"),
            (candidate, access == "public"),
            (member_role, access in {"public", "member"}),
        ):
            overwrite = channel.overwrites_for(role)
            overwrite.view_channel = can_view
            if can_view:
                overwrite.read_message_history = True
            await channel.set_permissions(role, overwrite=overwrite, reason=REASON)

    async def reconcile_roles(
        self,
        guild: discord.Guild,
        unregistered: discord.Role,
        candidate: discord.Role,
        member_role: discord.Role,
    ) -> None:
        active_members = {
            int(row["discord_id"])
            for row in await self.database.fetchall(
                "SELECT discord_id FROM members WHERE guild_id=? AND status='ACTIVE'",
                (guild.id,),
            )
        }
        candidates = {
            int(row["discord_id"])
            for row in await self.database.fetchall(
                """
                SELECT discord_id FROM recruitment_applications
                WHERE guild_id=? AND status IN (
                  'SUBMITTED','UNDER_REVIEW','INTERVIEW_PENDING','INTERVIEW_SCHEDULED',
                  'INTERVIEW_COMPLETED','FINAL_REVIEW'
                )
                """,
                (guild.id,),
            )
        }
        protected = await self.protected_ids(guild)
        rank_role_ids = {
            int(row["discord_role_id"])
            for row in await self.database.fetchall(
                """
                SELECT discord_role_id FROM ranks
                WHERE guild_id=? AND discord_role_id IS NOT NULL
                """,
                (guild.id,),
            )
        }
        for target in guild.members:
            if target.id in protected or target.bot:
                continue
            if target.id in active_members:
                if unregistered in target.roles:
                    await target.remove_roles(unregistered, reason=REASON)
                continue
            if target.id in candidates:
                remove = [role for role in target.roles if role.id in rank_role_ids | {member_role.id, unregistered.id}]
                if remove:
                    await target.remove_roles(*remove, reason=REASON)
                if candidate not in target.roles:
                    await target.add_roles(candidate, reason=REASON)
                continue
            remove = [role for role in target.roles if role.id in rank_role_ids | {member_role.id, candidate.id}]
            if remove:
                await target.remove_roles(*remove, reason=REASON)
            if unregistered not in target.roles:
                await target.add_roles(unregistered, reason=REASON)

    async def validate(self, guild: discord.Guild) -> dict[str, Any]:
        unregistered_id = await self.settings.get(guild.id, "unregistered_role_id")
        unregistered = guild.get_role(int(unregistered_id)) if unregistered_id else None
        if unregistered is None:
            raise RuntimeError("Cargo não cadastrado ausente.")
        rows = await self.gate.classifications(guild.id)
        classes = {
            (str(row["resource_type"]), int(row["resource_id"])): str(row["access_class"])
            for row in rows
        }
        protected = 0
        onboarding = 0
        leaks: list[int] = []
        unclassified: list[int] = []
        for channel in guild.channels:
            kind = "CATEGORY" if isinstance(channel, discord.CategoryChannel) else "CHANNEL"
            access_class = classes.get((kind, channel.id))
            if access_class is None:
                unclassified.append(channel.id)
                continue
            visible = channel.permissions_for(unregistered).view_channel
            if access_class in {"ONBOARDING_VISIBLE", "PUBLIC"}:
                onboarding += 1
                if not visible:
                    leaks.append(channel.id)
            else:
                protected += 1
                if visible:
                    leaks.append(channel.id)
        panel_id = await self.settings.get(guild.id, "registration_panel_channel_id")
        support_id = await self.settings.get(guild.id, "registration_support_channel_id")
        for required_id in (panel_id, support_id):
            channel = guild.get_channel(int(required_id)) if required_id else None
            if not channel or not channel.permissions_for(unregistered).view_channel:
                leaks.append(int(required_id or 0))
        bot_member = guild.me
        panel = guild.get_channel(int(panel_id)) if panel_id else None
        if not bot_member or not isinstance(panel, discord.TextChannel):
            raise RuntimeError("Bot ou canal da Portaria indisponível.")
        permissions = panel.permissions_for(bot_member)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            raise RuntimeError("O bot perdeu acesso operacional ao canal da Portaria.")
        owner = guild.owner
        if owner and not panel.permissions_for(owner).view_channel:
            raise RuntimeError("A configuração bloquearia o owner.")
        panel_row = await self.settings.get_panel(guild.id, "MEMBER")
        if not panel_row or int(panel_row["channel_id"]) != panel.id:
            raise RuntimeError("Mensagem persistida da Portaria não está registrada no canal atual.")
        try:
            panel_message = await panel.fetch_message(int(panel_row["message_id"]))
        except discord.DiscordException as exc:
            raise RuntimeError("Mensagem persistida da Portaria não foi encontrada.") from exc
        custom_ids = {
            str(component.custom_id)
            for row in panel_message.components
            for component in row.children
            if getattr(component, "custom_id", None)
        }
        expected_ids = {
            "choque:member:identify:v2",
            "choque:registration:status:v1",
            "choque:registration:help:v1",
        }
        if not expected_ids.issubset(custom_ids):
            raise RuntimeError("Painel da Portaria não contém as três ações persistentes.")
        allowed_categories = {
            resource_id
            for (kind, resource_id), access_class in classes.items()
            if kind == "CATEGORY" and access_class in {"ONBOARDING_VISIBLE", "PUBLIC"}
        }
        sampled = 0
        for visitor in unregistered.members[:10]:
            visible_categories = {
                category.id
                for category in guild.categories
                if category.permissions_for(visitor).view_channel
            }
            if visible_categories != allowed_categories:
                raise RuntimeError(
                    f"Conta restrita {visitor.id} possui categorias efetivas divergentes."
                )
            sampled += 1
        return {
            "protected": protected,
            "onboarding": onboarding,
            "leaks": sorted(set(leaks)),
            "unclassified": sorted(set(unclassified)),
            "panel_message_id": panel_message.id,
            "restricted_role_members": len(unregistered.members),
            "sampled_restricted_accounts": sampled,
        }

    @staticmethod
    def capture_post_apply(guild: discord.Guild) -> dict[str, Any]:
        return {
            "channels": {
                str(channel.id): {
                    "parent_id": channel.category_id,
                    "digest": overwrite_digest(channel),
                }
                for channel in guild.channels
            },
            "member_roles": {
                str(member.id): sorted(role.id for role in member.roles if not role.is_default())
                for member in guild.members
                if not member.bot
            },
        }

    async def rollback(self, guild: discord.Guild, path: Path) -> None:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if int(snapshot.get("guild_id", 0)) != guild.id:
            raise RuntimeError("Snapshot pertence a outra guild.")
        await self.restore_in_memory(guild, snapshot, compare_post_apply=True)
        await self.audit.record(
            guild.id,
            "REGISTRATION_GATE_ROLLED_BACK",
            actor_id=self.user.id if self.user else None,
            after={"snapshot": str(path)},
        )

    async def restore_in_memory(
        self,
        guild: discord.Guild,
        snapshot: dict[str, Any],
        *,
        compare_post_apply: bool,
    ) -> None:
        post = snapshot.get("post_apply", {}) if compare_post_apply else {}
        post_channels = post.get("channels", {}) if isinstance(post, dict) else {}
        conflicts: list[int] = []
        for item in snapshot.get("channels", []):
            channel = guild.get_channel(int(item["id"]))
            if not isinstance(channel, discord.abc.GuildChannel):
                continue
            expected = post_channels.get(str(channel.id), {})
            if compare_post_apply and expected.get("digest") != overwrite_digest(channel):
                conflicts.append(channel.id)
                continue
            overwrites: dict[Any, discord.PermissionOverwrite] = {}
            for raw in item.get("overwrites", []):
                target = guild.get_role(int(raw["target_id"])) or guild.get_member(
                    int(raw["target_id"])
                )
                if target:
                    overwrites[target] = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(int(raw["allow"])),
                        discord.Permissions(int(raw["deny"])),
                    )
            parent_id = item.get("parent_id")
            category = guild.get_channel(int(parent_id)) if parent_id else None
            if isinstance(channel, discord.CategoryChannel):
                await channel.edit(
                    position=int(item["position"]),
                    overwrites=overwrites,
                    reason=f"{REASON} • rollback",
                )
            else:
                await channel.edit(
                    category=category if isinstance(category, discord.CategoryChannel) else None,
                    position=int(item["position"]),
                    overwrites=overwrites,
                    sync_permissions=False,
                    reason=f"{REASON} • rollback",
                )

        post_roles = post.get("member_roles", {}) if isinstance(post, dict) else {}
        for raw_id, original_ids in snapshot.get("member_roles", {}).items():
            member = guild.get_member(int(raw_id))
            if not member:
                continue
            current_ids = sorted(role.id for role in member.roles if not role.is_default())
            if compare_post_apply and current_ids != post_roles.get(raw_id, []):
                conflicts.append(member.id)
                continue
            original = {
                role
                for role_id in original_ids
                if (role := guild.get_role(int(role_id))) is not None
            }
            current = {role for role in member.roles if not role.is_default()}
            bot_member = guild.me
            if bot_member is None:
                raise RuntimeError("Membro do bot indisponível durante rollback.")
            add = [role for role in original - current if role < bot_member.top_role]
            remove = [role for role in current - original if role < bot_member.top_role]
            if remove:
                await member.remove_roles(*remove, reason=f"{REASON} • rollback")
            if add:
                await member.add_roles(*add, reason=f"{REASON} • rollback")

        async with self.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM registration_access_classifications WHERE guild_id=?",
                (guild.id,),
            )
            for row in snapshot.get("classifications", []):
                await connection.execute(
                    """
                    INSERT INTO registration_access_classifications(
                        id, guild_id, resource_type, resource_id, internal_key,
                        access_class, created_at, created_by, updated_at, updated_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"], row["guild_id"], row["resource_type"], row["resource_id"],
                        row["internal_key"], row["access_class"], row["created_at"],
                        row["created_by"], row["updated_at"], row["updated_by"],
                    ),
                )
            for key, value in snapshot.get("settings", {}).items():
                await self.settings.set(
                    guild.id, key, value, self.user.id if self.user else None, connection
                )
        for role_id in snapshot.get("created_role_ids", []):
            role = guild.get_role(int(role_id))
            if role and not role.members and role.permissions.value == 0:
                await role.delete(reason=f"{REASON} • rollback")
        if conflicts:
            raise RuntimeError(
                "Rollback parcial: recursos alterados após o apply foram preservados: "
                + ",".join(str(value) for value in conflicts)
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configura a Portaria Digital por IDs")
    parser.add_argument("--apply", action="store_true", help="Aplica após preview e snapshot")
    parser.add_argument("--validate", action="store_true", help="Valida o estado real sem alterar")
    parser.add_argument("--rollback", type=Path, help="Restaura um snapshot compatível")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    client = RegistrationGateConfigurator(
        config,
        apply=bool(args.apply),
        validate_only=bool(args.validate),
        rollback_path=args.rollback,
    )
    async with client:
        await client.start(config.token)
    return client.exit_code


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
