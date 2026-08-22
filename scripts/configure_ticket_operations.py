from __future__ import annotations

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

from choque.audit import AuditService  # noqa: E402
from choque.channel_names import format_category_name, format_channel_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.settings import SettingsService  # noqa: E402

SETTING_KEYS = (
    "ticket_active_category_id",
    "ticket_archive_category_id",
    "ticket_responsible_role_id",
    "ticket_transcript_channel_id",
    "ticket_bot_role_id",
)
REASON = "Expansão operacional de tickets CHOQUE - BGR"


def serialize_overwrites(channel: discord.abc.GuildChannel) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for target, overwrite in channel.overwrites.items():
        allow, deny = overwrite.pair()
        result.append(
            {
                "id": target.id,
                "type": "role" if isinstance(target, discord.Role) else "member",
                "allow": allow.value,
                "deny": deny.value,
            }
        )
    return sorted(result, key=lambda item: (item["type"], item["id"]))


async def deserialize_overwrites(
    guild: discord.Guild, rows: list[dict[str, Any]]
) -> dict[Any, discord.PermissionOverwrite]:
    result: dict[Any, discord.PermissionOverwrite] = {}
    for row in rows:
        if row["type"] == "role":
            target = guild.get_role(int(row["id"]))
        else:
            target = guild.get_member(int(row["id"]))
            if target is None:
                try:
                    target = await guild.fetch_member(int(row["id"]))
                except discord.DiscordException:
                    target = None
        if target is not None:
            result[target] = discord.PermissionOverwrite.from_pair(
                discord.Permissions(int(row["allow"])),
                discord.Permissions(int(row["deny"])),
            )
    return result


class TicketOperationsConfigurator(discord.Client):
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
        self.apply_changes = apply
        self.validate_only = validate_only
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
            if self.rollback_path:
                await self.rollback(guild, self.rollback_path)
                print("TICKET_OPERATIONS_ROLLBACK_PASS")
            elif self.validate_only:
                validation = await self.validate(guild, live_permission_matrix=True)
                if validation["failures"]:
                    raise RuntimeError(f"Validação falhou: {validation['failures']}")
                print(
                    "TICKET_OPERATIONS_LIVE_PASS "
                    f"active_rooms={validation['active_rooms']} "
                    f"archived_rooms={validation['archived_rooms']} "
                    f"visitor_samples={validation['visitor_samples']} "
                    f"controls={validation['controls']} "
                    f"permission_matrix={validation['permission_matrix']}"
                )
            else:
                preview = await self.preview(guild)
                print("TICKET_OPERATIONS_PREVIEW=" + json.dumps(preview, sort_keys=True))
                if self.apply_changes:
                    snapshot_path, snapshot = await self.capture_snapshot(guild)
                    try:
                        await self.apply(guild, snapshot)
                        validation = await self.validate(guild, require_controls=False)
                        if validation["failures"]:
                            raise RuntimeError(f"Validação falhou: {validation['failures']}")
                    except Exception:
                        await self.restore_snapshot(guild, snapshot, remove_created=True)
                        raise
                    snapshot["post_apply"] = await self.capture_post_apply(guild)
                    snapshot_path.write_text(
                        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print(
                        "TICKET_OPERATIONS_APPLY_PASS "
                        f"snapshot={snapshot_path.resolve()} "
                        f"active_rooms={validation['active_rooms']} "
                        f"archived_rooms={validation['archived_rooms']}"
                    )
                else:
                    print("TICKET_OPERATIONS_DRY_RUN_PASS")
            self.exit_code = 0
        except Exception:
            traceback.print_exc()
        finally:
            await self.database.close()
            await self.close()

    async def _registry(self, guild_id: int) -> dict[str, dict[str, int]]:
        raw = await self.settings.get(guild_id, "discord_layout_registry_v2", {})
        if not isinstance(raw, dict):
            raise RuntimeError("Registry Discord inválido.")
        return {
            "categories": {
                str(key): int(value) for key, value in raw.get("categories", {}).items()
            },
            "channels": {str(key): int(value) for key, value in raw.get("channels", {}).items()},
        }

    async def _responsible_role(self, guild: discord.Guild) -> discord.Role:
        configured = await self.settings.get(guild.id, "ticket_responsible_role_id")
        role = guild.get_role(int(configured)) if configured else None
        if role is None:
            row = await self.database.fetchone(
                """
                SELECT discord_role_id FROM ranks
                WHERE guild_id=? AND discord_role_id IS NOT NULL
                  AND upper(name) LIKE '%ALTO COMANDO%'
                ORDER BY level DESC LIMIT 1
                """,
                (guild.id,),
            )
            role = guild.get_role(int(row["discord_role_id"])) if row else None
        if role is None:
            command_ids = {
                int(row["role_id"])
                for row in await self.database.fetchall(
                    """
                    SELECT role_id FROM rbac_bindings
                    WHERE guild_id=? AND profile IN ('COMANDO','ADMINISTRADOR')
                    """,
                    (guild.id,),
                )
            }
            role = max(
                (candidate for candidate in guild.roles if candidate.id in command_ids),
                key=lambda candidate: candidate.position,
                default=None,
            )
        if role is None:
            raise RuntimeError("Cargo responsável por tickets não pôde ser identificado.")
        if guild.me is None or guild.me.top_role <= role:
            raise RuntimeError("O cargo do bot deve ficar acima do cargo responsável por tickets.")
        return role

    async def _command_roles(self, guild: discord.Guild) -> list[discord.Role]:
        ids = {
            int(row["role_id"])
            for row in await self.database.fetchall(
                """
                SELECT role_id FROM rbac_bindings
                WHERE guild_id=? AND profile IN ('COMANDO','ADMINISTRADOR')
                """,
                (guild.id,),
            )
        }
        return [role for role in guild.roles if role.id in ids]

    async def _staff_overwrites(
        self, guild: discord.Guild, responsible: discord.Role | None
    ) -> dict[Any, discord.PermissionOverwrite]:
        result: dict[Any, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False)
        }
        staff = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            manage_messages=True,
        )
        for role in await self._command_roles(guild):
            result[role] = staff
        if responsible is not None:
            result[responsible] = staff
        if guild.me is not None:
            result[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                manage_messages=True,
                manage_channels=True,
            )
        return result

    async def _room_overwrites(
        self,
        guild: discord.Guild,
        room,
        responsible: discord.Role,
        *,
        active: bool,
    ) -> dict[Any, discord.PermissionOverwrite]:
        result = await self._staff_overwrites(guild, responsible if active else None)
        if not active:
            return result
        requester = guild.get_member(int(room["requester_id"]))
        if requester is None:
            requester = await guild.fetch_member(int(room["requester_id"]))
        result[requester] = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
        )
        participants = await self.database.fetchall(
            """
            SELECT discord_id FROM ticket_participants
            WHERE guild_id=? AND ticket_id=? AND removed_at IS NULL
            """,
            (guild.id, int(room["ticket_id"])),
        )
        for participant in participants:
            member = guild.get_member(int(participant["discord_id"]))
            if member is not None:
                result[member] = discord.PermissionOverwrite(
                    view_channel=True,
                    read_message_history=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                )
        return result

    async def preview(self, guild: discord.Guild) -> dict[str, Any]:
        responsible = await self._responsible_role(guild)
        rooms = await self.database.fetchall(
            "SELECT status, COUNT(*) AS total FROM ticket_rooms WHERE guild_id=? GROUP BY status",
            (guild.id,),
        )
        return {
            "create_active_category": not bool(
                await self.settings.get(guild.id, "ticket_active_category_id")
            ),
            "create_archive_category": not bool(
                await self.settings.get(guild.id, "ticket_archive_category_id")
            ),
            "responsible_role_position": responsible.position,
            "bot_role_position": guild.me.top_role.position if guild.me else 0,
            "rooms": {str(row["status"]): int(row["total"]) for row in rooms},
        }

    async def capture_snapshot(self, guild: discord.Guild) -> tuple[Path, dict[str, Any]]:
        settings = {key: await self.settings.get(guild.id, key) for key in SETTING_KEYS}
        rooms = []
        for row in await self.database.fetchall(
            "SELECT * FROM ticket_rooms WHERE guild_id=?", (guild.id,)
        ):
            channel = guild.get_channel(int(row["channel_id"]))
            if isinstance(channel, discord.TextChannel):
                rooms.append(
                    {
                        "ticket_id": int(row["ticket_id"]),
                        "channel_id": channel.id,
                        "name": channel.name,
                        "category_id": channel.category_id,
                        "overwrites": serialize_overwrites(channel),
                        "db": {
                            "active_category_id": row["active_category_id"],
                            "archive_category_id": row["archive_category_id"],
                            "responsible_role_id": row["responsible_role_id"],
                        },
                    }
                )
        snapshot = {
            "guild_id": guild.id,
            "created_at": datetime.now(UTC).isoformat(),
            "settings": settings,
            "rooms": rooms,
            "created_category_ids": [],
        }
        folder = self.config.database_path.parent / "server_layout_backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = folder / f"ticket_operations_{guild.id}_{stamp}.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return path, snapshot

    async def _ensure_category(
        self,
        guild: discord.Guild,
        setting_key: str,
        name: str,
        order: int,
        overwrites: dict[Any, discord.PermissionOverwrite],
        snapshot: dict[str, Any],
    ) -> discord.CategoryChannel:
        configured = await self.settings.get(guild.id, setting_key)
        category = guild.get_channel(int(configured)) if configured else None
        if not isinstance(category, discord.CategoryChannel):
            category = await guild.create_category(
                format_category_name(order, name),
                overwrites=overwrites,
                reason=REASON,
            )
            snapshot["created_category_ids"].append(category.id)
        else:
            await category.edit(overwrites=overwrites, reason=REASON)
        return category

    async def apply(self, guild: discord.Guild, snapshot: dict[str, Any]) -> None:
        registry = await self._registry(guild.id)
        responsible = await self._responsible_role(guild)
        active = await self._ensure_category(
            guild,
            "ticket_active_category_id",
            "Atendimentos ativos",
            2,
            await self._staff_overwrites(guild, responsible),
            snapshot,
        )
        archive = await self._ensure_category(
            guild,
            "ticket_archive_category_id",
            "Tickets arquivados",
            98,
            await self._staff_overwrites(guild, None),
            snapshot,
        )
        ticket_public = guild.get_channel(registry["categories"].get("ticket", 0))
        if isinstance(ticket_public, discord.CategoryChannel):
            await active.edit(position=ticket_public.position + 1, reason=REASON)
        transcript_id = await self.settings.get(guild.id, "ticket_transcript_channel_id")
        if not transcript_id:
            transcript_id = await self.settings.get(guild.id, "audit_channel_id") or registry[
                "channels"
            ].get("ticket.queue")
        actor_id = self.user.id if self.user else None
        async with self.database.transaction() as connection:
            for key, value in {
                "ticket_active_category_id": active.id,
                "ticket_archive_category_id": archive.id,
                "ticket_responsible_role_id": responsible.id,
                "ticket_transcript_channel_id": int(transcript_id) if transcript_id else None,
                "ticket_bot_role_id": guild.me.top_role.id if guild.me else None,
            }.items():
                await self.settings.set(guild.id, key, value, actor_id, connection)
            await self.audit.record(
                guild.id,
                "TICKET_OPERATIONS_CONFIGURED",
                actor_id=actor_id,
                after={
                    "active_category_id": active.id,
                    "archive_category_id": archive.id,
                    "responsible_role_id": responsible.id,
                    "snapshot_created": True,
                },
                connection=connection,
                deliver_immediately=False,
            )
        for room in await self.database.fetchall(
            "SELECT * FROM ticket_rooms WHERE guild_id=?", (guild.id,)
        ):
            channel = guild.get_channel(int(room["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                continue
            is_active = room["status"] == "OPEN"
            target = active if is_active else archive
            await channel.edit(
                category=target,
                overwrites=await self._room_overwrites(guild, room, responsible, active=is_active),
                sync_permissions=False,
                reason=REASON,
            )
            await self.database.execute(
                """
                UPDATE ticket_rooms SET active_category_id=?, archive_category_id=?,
                    responsible_role_id=?, version=version+1
                WHERE guild_id=? AND ticket_id=?
                """,
                (active.id, archive.id, responsible.id, guild.id, int(room["ticket_id"])),
            )
        now = int(datetime.now(UTC).timestamp() * 1000)
        for category in (active, archive):
            await self.database.execute(
                """
                INSERT INTO discord_resource_registry(
                    guild_id, resource_id, resource_type, name, position, active, updated_at
                ) VALUES (?, ?, 'CATEGORY', ?, ?, 1, ?)
                ON CONFLICT(guild_id, resource_type, resource_id) DO UPDATE SET
                    name=excluded.name, position=excluded.position, active=1,
                    updated_at=excluded.updated_at
                """,
                (guild.id, category.id, category.name, category.position, now),
            )

    async def validate(
        self,
        guild: discord.Guild,
        *,
        require_controls: bool = True,
        live_permission_matrix: bool = False,
    ) -> dict[str, Any]:
        active_id = await self.settings.get(guild.id, "ticket_active_category_id")
        archive_id = await self.settings.get(guild.id, "ticket_archive_category_id")
        responsible_id = await self.settings.get(guild.id, "ticket_responsible_role_id")
        bot_role_id = await self.settings.get(guild.id, "ticket_bot_role_id")
        failures: list[str] = []
        active = guild.get_channel(int(active_id)) if active_id else None
        archive = guild.get_channel(int(archive_id)) if archive_id else None
        responsible = guild.get_role(int(responsible_id)) if responsible_id else None
        command_role_ids = {role.id for role in await self._command_roles(guild)}
        if not isinstance(active, discord.CategoryChannel):
            failures.append("active-category-missing")
        if not isinstance(archive, discord.CategoryChannel):
            failures.append("archive-category-missing")
        if active_id == archive_id:
            failures.append("categories-not-distinct")
        if responsible is None:
            failures.append("responsible-role-missing")
        if guild.me is None or responsible is None or guild.me.top_role <= responsible:
            failures.append("bot-role-hierarchy")
        if guild.me is not None and bot_role_id != guild.me.top_role.id:
            failures.append("bot-role-registry")
        active_rooms = 0
        archived_rooms = 0
        controls = 0
        required_controls = {
            "choque:ticket:room:claim:v1",
            "choque:ticket:room:priority:v1",
            "choque:ticket:room:add:v1",
            "choque:ticket:room:remove:v1",
            "choque:ticket:room:notify:v1",
            "choque:ticket:room:transcript:v1",
            "choque:ticket:room:reopen:v1",
            "choque:ticket:room:close:v1",
        }
        for room in await self.database.fetchall(
            "SELECT * FROM ticket_rooms WHERE guild_id=?", (guild.id,)
        ):
            channel = guild.get_channel(int(room["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                failures.append(f"room-{room['ticket_id']}:channel-missing")
                continue
            is_active = room["status"] == "OPEN"
            active_rooms += int(is_active)
            archived_rooms += int(not is_active)
            expected = int(active_id if is_active else archive_id)
            if channel.category_id != expected:
                failures.append(f"room-{room['ticket_id']}:wrong-category")
            default = channel.overwrites_for(guild.default_role)
            if default.view_channel is not False:
                failures.append(f"room-{room['ticket_id']}:everyone-not-denied")
            if guild.me is None or channel.overwrites_for(guild.me).view_channel is not True:
                failures.append(f"room-{room['ticket_id']}:bot-not-allowed")
            requester = guild.get_member(int(room["requester_id"]))
            if requester is not None:
                expected_requester = True if is_active else None
                actual = channel.overwrites_for(requester).view_channel
                if actual is not expected_requester:
                    failures.append(f"room-{room['ticket_id']}:requester-access")
            if responsible is not None:
                expected_responsible = (
                    True if is_active or responsible.id in command_role_ids else None
                )
                if channel.overwrites_for(responsible).view_channel is not expected_responsible:
                    failures.append(f"room-{room['ticket_id']}:responsible-access")
            if room["control_message_id"]:
                try:
                    message = await channel.fetch_message(int(room["control_message_id"]))
                    custom_ids = {
                        item.custom_id
                        for row in message.components
                        for item in row.children
                        if getattr(item, "custom_id", None)
                    }
                    if required_controls <= custom_ids:
                        controls += 1
                    elif require_controls:
                        failures.append(f"room-{room['ticket_id']}:controls")
                except discord.DiscordException:
                    failures.append(f"room-{room['ticket_id']}:control-message")
        restricted_role_id = await self.settings.get(guild.id, "unregistered_role_id")
        restricted_role = guild.get_role(int(restricted_role_id)) if restricted_role_id else None
        samples = list(restricted_role.members[:10]) if restricted_role else []
        for member in samples:
            if (
                isinstance(active, discord.CategoryChannel)
                and active.permissions_for(member).view_channel
            ):
                failures.append("visitor-active-category-leak")
                break
        permission_matrix = False
        if (
            live_permission_matrix
            and isinstance(active, discord.CategoryChannel)
            and responsible is not None
        ):
            permission_matrix = await self._validate_permission_matrix(
                guild, active, responsible, failures
            )
        return {
            "active_rooms": active_rooms,
            "archived_rooms": archived_rooms,
            "visitor_samples": len(samples),
            "controls": controls,
            "permission_matrix": permission_matrix,
            "failures": failures,
        }

    async def _validate_permission_matrix(
        self,
        guild: discord.Guild,
        active: discord.CategoryChannel,
        responsible: discord.Role,
        failures: list[str],
    ) -> bool:
        restricted_role_id = await self.settings.get(guild.id, "unregistered_role_id")
        member_role_id = await self.settings.get(guild.id, "member_role_id")
        restricted = guild.get_role(int(restricted_role_id)) if restricted_role_id else None
        member_role = guild.get_role(int(member_role_id)) if member_role_id else None
        command_roles = await self._command_roles(guild)
        command_role_ids = {role.id for role in command_roles}
        requester = next(
            (
                member
                for member in (restricted.members if restricted else [])
                if not member.bot and not member.guild_permissions.administrator
            ),
            None,
        )
        visitor = next(
            (
                member
                for member in (restricted.members if restricted else [])
                if requester is not None
                and member.id != requester.id
                and not member.bot
                and not member.guild_permissions.administrator
            ),
            None,
        )
        common_member = next(
            (
                member
                for member in (member_role.members if member_role else [])
                if not member.bot
                and not member.guild_permissions.administrator
                and responsible not in member.roles
                and not any(role.id in command_role_ids for role in member.roles)
            ),
            None,
        )
        common_subject: discord.Member | discord.Role | None = common_member or member_role
        command_role = next(iter(command_roles), None)
        if not all((requester, visitor, common_subject, command_role, guild.me)):
            failures.append("permission-matrix-identities-unavailable")
            return False
        overwrites = await self._staff_overwrites(guild, responsible)
        overwrites[requester] = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
        )
        channel: discord.TextChannel | None = None
        try:
            channel = await guild.create_text_channel(
                format_channel_name("ValidacaoTicket", "🧪"),
                category=active,
                overwrites=overwrites,
                reason=f"Matriz temporária • {REASON}",
            )
            fresh = await guild.fetch_channel(channel.id)
            if not isinstance(fresh, discord.TextChannel):
                failures.append("permission-matrix-channel-type")
                return False
            checks = {
                "requester": fresh.permissions_for(requester).view_channel,
                "visitor": fresh.permissions_for(visitor).view_channel,
                "member": fresh.permissions_for(common_subject).view_channel,
                "responsible": fresh.permissions_for(responsible).view_channel,
                "command": fresh.permissions_for(command_role).view_channel,
                "bot": fresh.permissions_for(guild.me).view_channel,
            }
            expected = {
                "requester": True,
                "visitor": False,
                "member": False,
                "responsible": True,
                "command": True,
                "bot": True,
            }
            if checks != expected:
                failures.append("permission-matrix:" + json.dumps(checks, sort_keys=True))
                return False
            return True
        finally:
            if channel is not None:
                await channel.delete(reason=f"Fim da matriz temporária • {REASON}")

    async def capture_post_apply(self, guild: discord.Guild) -> dict[str, Any]:
        return {
            "settings": {key: await self.settings.get(guild.id, key) for key in SETTING_KEYS},
            "categories": [
                channel.id
                for channel in guild.categories
                if channel.id
                in {
                    await self.settings.get(guild.id, "ticket_active_category_id"),
                    await self.settings.get(guild.id, "ticket_archive_category_id"),
                }
            ],
        }

    async def restore_snapshot(
        self,
        guild: discord.Guild,
        snapshot: dict[str, Any],
        *,
        remove_created: bool,
    ) -> None:
        for room in snapshot.get("rooms", []):
            channel = guild.get_channel(int(room["channel_id"]))
            category = guild.get_channel(int(room["category_id"])) if room["category_id"] else None
            if isinstance(channel, discord.TextChannel):
                await channel.edit(
                    name=str(room["name"]),
                    category=category if isinstance(category, discord.CategoryChannel) else None,
                    overwrites=await deserialize_overwrites(guild, room["overwrites"]),
                    sync_permissions=False,
                    reason=f"Rollback • {REASON}",
                )
            db = room["db"]
            await self.database.execute(
                """
                UPDATE ticket_rooms SET active_category_id=?, archive_category_id=?,
                    responsible_role_id=?, version=version+1
                WHERE guild_id=? AND ticket_id=?
                """,
                (
                    db["active_category_id"],
                    db["archive_category_id"],
                    db["responsible_role_id"],
                    guild.id,
                    int(room["ticket_id"]),
                ),
            )
        for key, value in snapshot.get("settings", {}).items():
            await self.settings.set(guild.id, key, value, self.user.id if self.user else None)
        if remove_created:
            for category_id in snapshot.get("created_category_ids", []):
                category = guild.get_channel(int(category_id))
                if isinstance(category, discord.CategoryChannel) and not category.channels:
                    await category.delete(reason=f"Rollback • {REASON}")

    async def rollback(self, guild: discord.Guild, path: Path) -> None:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if int(snapshot.get("guild_id") or 0) != guild.id:
            raise RuntimeError("Snapshot pertence a outra guild.")
        await self.restore_snapshot(guild, snapshot, remove_created=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configura a operação avançada de tickets")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--rollback", type=Path)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    client = TicketOperationsConfigurator(
        config,
        apply=args.apply,
        validate_only=args.validate,
        rollback_path=args.rollback,
    )
    await client.start(config.token, reconnect=False)
    return client.exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
