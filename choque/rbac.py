from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass

import discord

from .models import RBAC_PROFILE_METADATA, RbacProfile
from .settings import SettingsService
from .time_utils import utc_now_ms

_MEMBER_PERMISSIONS = {
    "shift.start",
    "shift.stop.self",
    "shift.view.self",
    "hours.view.self",
    "request.submit",
    "request.view.self",
    "career.view.self",
    "discipline.view.self",
    "training.view.self",
    "training.enroll",
    "activity.view.self",
    "activity.view.all",
    "patrol.queue",
    "patrol.view.self",
    "patrol.feedback",
    "qualification.view.self",
    "swap.request",
    "swap.respond",
}
_GRADUATE_PERMISSIONS = {
    "shift.view.all",
    "member.view",
    "hours.view.all",
    "patrol.view.all",
}
_INSTRUCTOR_PERMISSIONS = {
    "training.manage",
    "recruitment.review",
    "recruitment.view",
    "recruitment.read",
    "recruitment.assign",
    "recruitment.interview",
    "recruitment.evaluate",
    "recruitment.integrity.read",
    "recruitment.notes.read",
    "recruitment.notes.create",
    "recruitment.ai.read",
    "recruitment.ai.reanalyze",
    "training.evaluate",
    "qualification.view.all",
    "recruit.evaluate",
}
_COMMAND_PERMISSIONS = {
    "shift.adjust",
    "shift.review",
    "member.edit",
    "panel.manage",
    "personnel.manage",
    "absence.review",
    "punishment.manage",
    "request.review",
    "career.manage",
    "discipline.manage",
    "activity.manage",
    "reports.view",
    "recruitment.approve",
    "recruitment.reject",
    "recruitment.form.manage",
    "recruitment.campaign.manage",
    "recruitment.settings.manage",
    "recruitment.block.manage",
    "recruitment.adaptation.manage",
    "recruitment.ai.config",
    "ticket.review",
    "ticket.view",
    "ticket.manage",
    "ticket.claim",
    "ticket.participants.manage",
    "ticket.priority.manage",
    "ticket.notify",
    "ticket.transcript",
    "ticket.reopen",
    "patrol.manage",
    "patrol.commander.override",
    "operations.view",
    "operations.flags.review",
    "integrity.view",
    "integrity.review",
    "identity.manage",
    "identity.reconcile",
    "qualification.view.all",
    "course.requirements.manage",
    "promotion.eligibility.view",
    "dossier.view",
    "admin.inbox.view",
    "swap.review",
    "decisions.view",
    "changes.view",
    "maintenance.manage",
    "registration.view",
    "registration.review",
    "registration.manage",
    "registration.settings",
    "registration.bypass.manage",
}
_HIGH_COMMAND_PERMISSIONS = {
    "settings.manage",
    "security.manage",
    "identity.configure",
    "audit.read",
    "registration.directory.manage",
    "qualification.manage",
}


PROFILE_PERMISSIONS: dict[str, frozenset[str]] = {
    RbacProfile.CANDIDATE.value: frozenset({"request.submit", "request.view.self"}),
    RbacProfile.RECRUIT.value: frozenset(_MEMBER_PERMISSIONS),
    RbacProfile.MEMBER.value: frozenset(_MEMBER_PERMISSIONS),
    RbacProfile.GRADUATE.value: frozenset(_MEMBER_PERMISSIONS | _GRADUATE_PERMISSIONS),
    RbacProfile.INSTRUCTOR.value: frozenset(_MEMBER_PERMISSIONS | _INSTRUCTOR_PERMISSIONS),
    RbacProfile.SUPERVISOR.value: frozenset(
        _MEMBER_PERMISSIONS | _GRADUATE_PERMISSIONS
    ),
    RbacProfile.COMMAND.value: frozenset(
        _MEMBER_PERMISSIONS
        | _GRADUATE_PERMISSIONS
        | _INSTRUCTOR_PERMISSIONS
        | _COMMAND_PERMISSIONS
    ),
    RbacProfile.HIGH_COMMAND.value: frozenset(
        _MEMBER_PERMISSIONS
        | _GRADUATE_PERMISSIONS
        | _INSTRUCTOR_PERMISSIONS
        | _COMMAND_PERMISSIONS
        | _HIGH_COMMAND_PERMISSIONS
    ),
    RbacProfile.ADMIN.value: frozenset({"*"}),
}

ALL_KNOWN_PERMISSIONS = frozenset(
    permission
    for permissions in PROFILE_PERMISSIONS.values()
    for permission in permissions
    if permission != "*"
)

PROFILE_METADATA: dict[str, tuple[str, int]] = {
    profile.value: metadata for profile, metadata in RBAC_PROFILE_METADATA.items()
}


class _PermissionSet(set[str]):
    """Set-compatible wildcard grants with explicit DENY precedence."""

    def __init__(self, values=(), *, denied: set[str] | None = None) -> None:
        super().__init__(values)
        self.denied = frozenset(denied or ())

    def __contains__(self, permission: object) -> bool:
        if not isinstance(permission, str):
            return super().__contains__(permission)
        if "*" in self.denied or permission in self.denied:
            return False
        return super().__contains__(permission) or (
            permission != "*" and super().__contains__("*")
        )


@dataclass(frozen=True, slots=True)
class EffectiveAccess:
    member_id: int
    discord_id: int
    profile: str
    profile_name: str
    profile_priority: int
    permissions: frozenset[str]
    denied_permissions: frozenset[str]
    authorization_version: int
    rank_id: int | None
    primary_position_id: int | None
    primary_position_code: str | None
    primary_position_name: str | None
    functions: tuple[dict[str, object], ...]
    discord_roles_synced_at: int | None
    identity_sync_status: str
    discord_present: bool
    member_status: str

    def can(self, permission: str) -> bool:
        if "*" in self.denied_permissions or permission in self.denied_permissions:
            return False
        return "*" in self.permissions or permission in self.permissions


class PermissionService:
    """Single RBAC resolver shared by Discord, API, site and workers.

    Permission results are deliberately read from SQLite for every sensitive
    request. Only idempotent creation of the default profile catalog is cached.
    """

    def __init__(self, settings: SettingsService):
        self.settings = settings
        self.database = settings.database
        self._defaults_ready: set[int] = set()
        self._defaults_lock = asyncio.Lock()

    async def ensure_defaults(self, guild_id: int) -> None:
        if guild_id in self._defaults_ready:
            return
        async with self._defaults_lock:
            if guild_id in self._defaults_ready:
                return
            now = utc_now_ms()
            async with self.database.transaction() as connection:
                for code, (name, priority) in PROFILE_METADATA.items():
                    await connection.execute(
                        """
                        INSERT OR IGNORE INTO access_profiles(
                            guild_id, code, name, priority, enabled, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 1, ?, ?)
                        """,
                        (guild_id, code, name, priority, now, now),
                    )
                cursor = await connection.execute(
                    "SELECT id, code FROM access_profiles WHERE guild_id=?", (guild_id,)
                )
                profile_ids = {
                    str(row["code"]): int(row["id"]) for row in await cursor.fetchall()
                }
                for code, permissions in PROFILE_PERMISSIONS.items():
                    profile_id = profile_ids.get(code)
                    if profile_id is None:
                        continue
                    await connection.executemany(
                        """
                        INSERT OR IGNORE INTO access_profile_permissions(
                            access_profile_id, permission, effect, created_at, updated_at
                        ) VALUES (?, ?, 'GRANT', ?, ?)
                        """,
                        ((profile_id, permission, now, now) for permission in permissions),
                    )
            self._defaults_ready.add(guild_id)

    async def invalidate(self, guild_id: int, discord_id: int | None = None) -> None:
        """Compatibility hook: resolved permissions themselves are never cached."""
        del guild_id, discord_id

    @staticmethod
    def _apply_permission_rows(rows, grants: set[str], denies: set[str]) -> None:
        for row in rows:
            permission = str(row["permission"])
            if str(row["effect"]) == "DENY":
                denies.add(permission)
            else:
                grants.add(permission)

    @staticmethod
    def _effective_permissions(grants: set[str], denies: set[str]) -> set[str]:
        """Return grants with DENY taking precedence, including over admin `*`."""
        if "*" in denies:
            return _PermissionSet(denied=denies)
        return _PermissionSet(grants - denies, denied=denies)

    async def _profile_permissions(self, profile_ids: set[int]) -> tuple[set[str], set[str]]:
        if not profile_ids:
            return set(), set()
        placeholders = ",".join("?" for _ in profile_ids)
        rows = await self.database.fetchall(
            f"""
            SELECT permission, effect FROM access_profile_permissions
            WHERE access_profile_id IN ({placeholders})
            """,
            tuple(sorted(profile_ids)),
        )
        grants: set[str] = set()
        denies: set[str] = set()
        self._apply_permission_rows(rows, grants, denies)
        return grants, denies

    async def permissions_for(
        self,
        guild_id: int,
        role_ids: Iterable[int],
        *,
        is_owner: bool = False,
        is_discord_admin: bool = False,
    ) -> set[str]:
        if is_owner or is_discord_admin:
            return {"*"}
        await self.ensure_defaults(guild_id)
        ids = {int(role_id) for role_id in role_ids}
        if not ids:
            return set()
        placeholders = ",".join("?" for _ in ids)
        mappings = await self.database.fetchall(
            f"""
            SELECT drm.access_profile_id, drm.position_id,
                   fp.access_profile_id AS position_profile_id
            FROM discord_role_mappings drm
            LEFT JOIN functional_positions fp ON fp.id=drm.position_id AND fp.enabled=1
            WHERE drm.guild_id=? AND drm.enabled=1
              AND drm.discord_role_id IN ({placeholders})
            """,
            (guild_id, *sorted(ids)),
        )
        profile_ids = {
            int(value)
            for row in mappings
            for value in (row["access_profile_id"], row["position_profile_id"])
            if value is not None
        }
        legacy_profiles = await self.settings.role_profiles(guild_id, ids)
        if legacy_profiles:
            legacy_rows = await self.database.fetchall(
                f"""
                SELECT id FROM access_profiles
                WHERE guild_id=? AND code IN ({','.join('?' for _ in legacy_profiles)})
                """,
                (guild_id, *sorted(legacy_profiles)),
            )
            profile_ids.update(int(row["id"]) for row in legacy_rows)
        rank_rows = await self.database.fetchall(
            f"""
            SELECT ap.id FROM ranks r
            JOIN access_profiles ap ON ap.guild_id=r.guild_id AND ap.code=r.rbac_profile
            JOIN discord_role_mappings drm
              ON drm.guild_id=r.guild_id AND drm.rank_id=r.id
             AND drm.mapping_type='RANK' AND drm.enabled=1
            WHERE r.guild_id=? AND r.active=1
              AND drm.discord_role_id IN ({placeholders})

            UNION

            SELECT ap.id FROM ranks r
            JOIN access_profiles ap ON ap.guild_id=r.guild_id AND ap.code=r.rbac_profile
            WHERE r.guild_id=? AND r.active=1
              AND r.discord_role_id IN ({placeholders})
              AND NOT EXISTS (
                  SELECT 1 FROM discord_role_mappings drm
                  WHERE drm.guild_id=r.guild_id AND drm.rank_id=r.id
                    AND drm.mapping_type='RANK'
              )
            """,
            (guild_id, *sorted(ids), guild_id, *sorted(ids)),
        )
        profile_ids.update(int(row["id"]) for row in rank_rows)
        grants, denies = await self._profile_permissions(profile_ids)
        position_ids = {
            int(row["position_id"])
            for row in mappings
            if row["position_id"] is not None
        }
        if position_ids:
            rows = await self.database.fetchall(
                f"""
                SELECT permission, effect FROM functional_position_permissions
                WHERE position_id IN ({','.join('?' for _ in position_ids)})
                """,
                tuple(sorted(position_ids)),
            )
            self._apply_permission_rows(rows, grants, denies)
        return self._effective_permissions(grants, denies)

    async def resolve_member_access(
        self, guild_id: int, discord_id: int
    ) -> EffectiveAccess | None:
        await self.ensure_defaults(guild_id)
        member = await self.database.fetchone(
            """
            SELECT m.*, r.rbac_profile AS rank_profile,
                   ap.code AS access_profile_code, ap.name AS access_profile_name,
                   ap.priority AS access_profile_priority,
                   fp.code AS primary_position_code, fp.name AS primary_position_name
            FROM members m
            LEFT JOIN ranks r ON r.id=m.rank_id
            LEFT JOIN access_profiles ap ON ap.id=m.access_profile_id
            LEFT JOIN functional_positions fp ON fp.id=m.primary_position_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        if not member:
            return None
        positions = await self.database.fetchall(
            """
            SELECT fp.id, fp.code, fp.name, fp.priority, mp.is_primary,
                   mp.source_role_id, fp.access_profile_id
            FROM member_positions mp
            JOIN functional_positions fp ON fp.id=mp.position_id
            WHERE mp.member_id=? AND fp.enabled=1
            ORDER BY mp.is_primary DESC, fp.priority DESC, fp.id
            """,
            (member["id"],),
        )
        member_status = str(member["status"])
        identity_status = str(member["identity_sync_status"] or "PENDING")
        discord_present = bool(member["discord_present"])
        has_completed_sync = member["discord_roles_synced_at"] is not None
        trusted_identity = (
            identity_status == "SYNCED" and has_completed_sync and discord_present
        )
        blocked_status = member_status in {"DISMISSED", "SUSPENDED"}
        confirmed_absence = identity_status == "DISCORD_ABSENT" or (
            has_completed_sync and not discord_present
        )
        safe_code = "CANDIDATO" if member_status == "PENDING" else "MEMBRO"
        if blocked_status or confirmed_absence or member_status == "PENDING" or not trusted_identity:
            profile = await self.database.fetchone(
                """
                SELECT id, code, name, priority FROM access_profiles
                WHERE guild_id=? AND code=? AND enabled=1
                """,
                (guild_id, safe_code),
            )
            assert profile is not None
            if blocked_status or confirmed_absence:
                grants, denies = set(), {"*"}
            else:
                grants, denies = await self._profile_permissions({int(profile["id"])})
        else:
            profile_code = str(
                member["access_profile_code"]
                or member["rank_profile"]
                or RbacProfile.MEMBER.value
            )
            profile = await self.database.fetchone(
                """
                SELECT id, code, name, priority FROM access_profiles
                WHERE guild_id=? AND code=? AND enabled=1
                """,
                (guild_id, profile_code),
            )
            if not profile:
                profile = await self.database.fetchone(
                    """
                    SELECT id, code, name, priority FROM access_profiles
                    WHERE guild_id=? AND code='MEMBRO' AND enabled=1
                    """,
                    (guild_id,),
                )
            assert profile is not None
            projected_access = await self.database.fetchall(
                """
                SELECT map.access_profile_id
                FROM member_access_profiles map
                JOIN discord_role_mappings drm
                  ON drm.id=map.source_mapping_id
                 AND drm.mapping_type='ACCESS' AND drm.enabled=1
                 AND drm.discord_role_id=map.source_role_id
                 AND drm.access_profile_id=map.access_profile_id
                JOIN access_profiles ap
                  ON ap.id=map.access_profile_id AND ap.guild_id=? AND ap.enabled=1
                WHERE map.member_id=?
                """,
                (guild_id, member["id"]),
            )
            effective_profile_ids = {int(profile["id"])}
            effective_profile_ids.update(
                int(row["access_profile_id"])
                for row in projected_access
            )
            effective_profile_ids.update(
                int(row["access_profile_id"])
                for row in positions
                if row["access_profile_id"] is not None
            )
            rank_profile = member["rank_profile"]
            if rank_profile:
                rank_access = await self.database.fetchone(
                    """
                    SELECT id FROM access_profiles
                    WHERE guild_id=? AND code=? AND enabled=1
                    """,
                    (guild_id, str(rank_profile)),
                )
                if rank_access:
                    effective_profile_ids.add(int(rank_access["id"]))
            grants, denies = await self._profile_permissions(effective_profile_ids)
            if member["rank_id"] is not None:
                rank_rows = await self.database.fetchall(
                    "SELECT permission, effect FROM rank_permissions WHERE rank_id=?",
                    (member["rank_id"],),
                )
                self._apply_permission_rows(rank_rows, grants, denies)
            position_ids = {int(row["id"]) for row in positions}
            if position_ids:
                position_rows = await self.database.fetchall(
                    f"""
                    SELECT permission, effect FROM functional_position_permissions
                    WHERE position_id IN ({','.join('?' for _ in position_ids)})
                    """,
                    tuple(sorted(position_ids)),
                )
                self._apply_permission_rows(position_rows, grants, denies)
            override_rows = await self.database.fetchall(
                """
                SELECT permission, effect FROM member_permission_overrides
                WHERE member_id=?
                """,
                (member["id"],),
            )
            self._apply_permission_rows(override_rows, grants, denies)

        return EffectiveAccess(
            member_id=int(member["id"]),
            discord_id=int(member["discord_id"]),
            profile=str(profile["code"]),
            profile_name=str(profile["name"]),
            profile_priority=int(profile["priority"]),
            permissions=frozenset(self._effective_permissions(grants, denies)),
            denied_permissions=frozenset(denies),
            authorization_version=int(member["authorization_version"] or 1),
            rank_id=int(member["rank_id"]) if member["rank_id"] is not None else None,
            primary_position_id=(
                int(member["primary_position_id"])
                if member["primary_position_id"] is not None
                else None
            ),
            primary_position_code=(
                str(member["primary_position_code"])
                if member["primary_position_code"] is not None
                else None
            ),
            primary_position_name=(
                str(member["primary_position_name"])
                if member["primary_position_name"] is not None
                else None
            ),
            functions=tuple(dict(row) for row in positions),
            discord_roles_synced_at=(
                int(member["discord_roles_synced_at"])
                if member["discord_roles_synced_at"] is not None
                else None
            ),
            identity_sync_status=identity_status,
            discord_present=discord_present,
            member_status=member_status,
        )

    async def has(self, member: discord.Member, permission: str) -> bool:
        if member.id == member.guild.owner_id or member.guild_permissions.administrator:
            return True
        effective = await self.resolve_member_access(member.guild.id, member.id)
        if effective is None or not effective.can(permission):
            return False
        # Require the current Discord roles to grant the permission too. This
        # closes the debounce window after a role removal while the persisted
        # identity event is still being reconciled.
        live_permissions = await self.permissions_for(
            member.guild.id,
            (role.id for role in member.roles),
        )
        live_grants = set(live_permissions)
        live_denies = set(getattr(live_permissions, "denied", ()))
        override_rows = await self.database.fetchall(
            """
            SELECT permission, effect FROM member_permission_overrides
            WHERE member_id=?
            """,
            (effective.member_id,),
        )
        self._apply_permission_rows(override_rows, live_grants, live_denies)
        return permission in self._effective_permissions(live_grants, live_denies)

    async def require(self, member: discord.Member, permission: str) -> None:
        if not await self.has(member, permission):
            raise PermissionError("Você não possui permissão para esta ação.")

    async def has_authorized_service_role(self, member: discord.Member) -> bool:
        rank_rows = await self.database.fetchall(
            """
            SELECT discord_role_id FROM ranks
            WHERE guild_id=? AND active=1 AND discord_role_id IS NOT NULL
            """,
            (member.guild.id,),
        )
        authorized = {int(row["discord_role_id"]) for row in rank_rows}
        configured = await self.settings.get(member.guild.id, "member_role_id")
        if configured:
            authorized.add(int(configured))
        return any(role.id in authorized for role in member.roles)
