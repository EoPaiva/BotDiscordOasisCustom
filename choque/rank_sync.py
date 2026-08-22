from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import aiosqlite
import discord

from .audit import AuditService
from .database import Database
from .rbac import PROFILE_METADATA
from .settings import SettingsService
from .time_utils import utc_now_ms


@dataclass(frozen=True, slots=True)
class IdentityPosition:
    id: int
    code: str
    name: str
    priority: int
    source_role_id: int
    is_primary: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "priority": self.priority,
            "source_role_id": self.source_role_id,
            "is_primary": self.is_primary,
        }


@dataclass(frozen=True, slots=True)
class IdentityAccessProfile:
    id: int
    code: str
    name: str
    priority: int
    source_mapping_id: int
    source_role_id: int

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "priority": self.priority,
            "source_mapping_id": self.source_mapping_id,
            "source_role_id": self.source_role_id,
        }


@dataclass(frozen=True, slots=True)
class IdentityPreview:
    registered: bool
    discord_id: int
    source: str
    before: dict[str, object]
    after: dict[str, object]
    relevant_role_ids: tuple[int, ...] = ()
    rank_changed: bool = False
    positions_changed: bool = False
    access_changed: bool = False
    presence_changed: bool = False

    @property
    def differs(self) -> bool:
        return any(
            (
                self.rank_changed,
                self.positions_changed,
                self.access_changed,
                self.presence_changed,
                self.before.get("discord_roles_hash")
                != self.after.get("discord_roles_hash"),
                self.before.get("rank_sync_status") != self.after.get("rank_sync_status"),
            )
        )


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    checked: int
    changed: int
    unchanged: int
    absent: int
    failed: int
    errors: tuple[str, ...] = ()


@dataclass(slots=True)
class RankSyncResult:
    registered: bool
    discord_id: int
    source: str
    db_changed: bool = False
    event_created: bool = False
    rank_id: int | None = None
    rank_name: str | None = None
    rank_role_id: int | None = None
    expected_nickname: str | None = None
    sync_status: str | None = None
    matched_role_ids: tuple[int, ...] = ()
    primary_position_id: int | None = None
    primary_position_code: str | None = None
    primary_position_name: str | None = None
    position_codes: tuple[str, ...] = ()
    functions: tuple[str, ...] = ()
    access_profile_id: int | None = None
    access_profile: str | None = None
    access_profile_name: str | None = None
    authorization_version: int = 1
    identity_sync_status: str | None = None
    discord_roles_synced_at: int | None = None
    discord_present: bool = True
    relevant_role_ids: tuple[int, ...] = ()
    correlation_id: str | None = None
    warning: str | None = None


@dataclass(slots=True)
class _LockEntry:
    lock: asyncio.Lock
    users: int = 0


@dataclass(frozen=True, slots=True)
class _DesiredIdentity:
    rank_id: int | None
    rank_name: str | None
    rank_prefix: str
    rank_level: int | None
    rank_role_id: int | None
    rank_sync_status: str
    matched_rank_role_ids: tuple[int, ...]
    expected_nickname: str
    positions: tuple[IdentityPosition, ...]
    primary_position_id: int | None
    access_profiles: tuple[IdentityAccessProfile, ...]
    access_profile_id: int
    access_profile_code: str
    access_profile_name: str
    relevant_role_ids: tuple[int, ...]
    discord_roles_hash: str


@dataclass(frozen=True, slots=True)
class _DiscordApplyOutcome:
    warnings: tuple[str, ...]
    role_sync_succeeded: bool


def format_member_nickname(prefix: str | None, name: str, character_id: str | None) -> str:
    """Return the single official Discord nickname format: [PAT] NAME [ID]."""
    abbreviation = str(prefix or "").strip().strip("[]").strip()
    member_name = " ".join(str(name).split())
    member_id = str(character_id or "").strip().strip("[]").strip()
    prefix_part = f"[{abbreviation}] " if abbreviation else ""
    suffix_part = f" [{member_id}]" if member_id else ""
    # Discord limits nicknames to 32 characters. Preserve the bracketed
    # structure even for oversized legacy fields, trimming the ID first and
    # the abbreviation only when that is mathematically unavoidable.
    while len(prefix_part) + len(suffix_part) > 31:
        if len(member_id) > 1:
            member_id = member_id[:-1]
        elif len(abbreviation) > 1:
            abbreviation = abbreviation[:-1]
            prefix_part = f"[{abbreviation}] "
        else:
            break
        suffix_part = f" [{member_id}]" if member_id else ""
    available = max(1, 32 - len(prefix_part) - len(suffix_part))
    return f"{prefix_part}{member_name[:available].rstrip()}{suffix_part}"[:32]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _operation_correlation_id(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized or str(uuid.uuid4())


def _role_snapshot_hash(role_ids: set[int] | tuple[int, ...], *, present: bool) -> str:
    payload = {
        "discord_present": bool(present),
        "role_ids": sorted({int(role_id) for role_id in role_ids}),
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


_CANONICAL_RANK_ROLES_SQL = """
SELECT * FROM (
    SELECT r.id, r.name, r.prefix, r.level, r.rbac_profile,
           drm.discord_role_id, drm.priority AS mapping_priority
    FROM ranks r
    JOIN discord_role_mappings drm
      ON drm.guild_id=r.guild_id AND drm.rank_id=r.id
     AND drm.mapping_type='RANK' AND drm.enabled=1
    WHERE r.guild_id=? AND r.active=1

    UNION ALL

    SELECT r.id, r.name, r.prefix, r.level, r.rbac_profile,
           r.discord_role_id, r.level AS mapping_priority
    FROM ranks r
    WHERE r.guild_id=? AND r.active=1 AND r.discord_role_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM discord_role_mappings drm
          WHERE drm.guild_id=r.guild_id AND drm.rank_id=r.id
            AND drm.mapping_type='RANK'
      )
)
ORDER BY level DESC, id DESC, mapping_priority DESC, discord_role_id ASC
"""


class RankSyncService:
    """Project Discord roles into the single persisted member identity.

    RankSync remains the sole authority for rank and nickname reconciliation.
    The same transaction now also projects functional positions, the primary
    position, access profile, authorization version, identity history and
    audit. Cosmetic roles never enter this pipeline unless they are remapped
    explicitly to a functional mapping type.
    """

    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
        *,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit
        self.clock = clock
        self._locks_guard = asyncio.Lock()
        self._locks: dict[tuple[int, int], _LockEntry] = {}

    async def _record_correlated_audit(
        self,
        guild_id: int,
        action: str,
        *,
        correlation_id: str,
        suffix: str,
        actor_id: int | None = None,
        target_id: int | None = None,
        before: object = None,
        after: object = None,
        reason: str | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        """Record one idempotent audit linked to an operation correlation."""
        audit_correlation_id = f"{correlation_id}:audit:{suffix}"
        if connection is not None:
            cursor = await connection.execute(
                "SELECT action FROM audit_logs WHERE correlation_id=?",
                (audit_correlation_id,),
            )
            existing = await cursor.fetchone()
        else:
            existing = await self.database.fetchone(
                "SELECT action FROM audit_logs WHERE correlation_id=?",
                (audit_correlation_id,),
            )
        if existing is not None:
            if str(existing["action"]) != action:
                raise RuntimeError("Correlação de auditoria vinculada a outra ação")
            return
        if isinstance(after, dict):
            linked_after: object = {
                **after,
                "operation_correlation_id": correlation_id,
            }
        else:
            linked_after = {
                "value": after,
                "operation_correlation_id": correlation_id,
            }
        await self.audit.record(
            guild_id,
            action,
            actor_id=actor_id,
            target_id=target_id,
            before=before,
            after=linked_after,
            reason=reason,
            connection=connection,
            correlation_id=audit_correlation_id,
        )

    @property
    def active_lock_count(self) -> int:
        return len(self._locks)

    @asynccontextmanager
    async def _member_lock(self, guild_id: int, discord_id: int) -> AsyncIterator[None]:
        key = (guild_id, discord_id)
        async with self._locks_guard:
            entry = self._locks.setdefault(key, _LockEntry(asyncio.Lock()))
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._locks_guard:
                entry.users -= 1
                if entry.users == 0 and not entry.lock.locked():
                    self._locks.pop(key, None)

    async def rank_role_ids(self, guild_id: int) -> set[int]:
        rows = await self.database.fetchall(
            _CANONICAL_RANK_ROLES_SQL,
            (guild_id, guild_id),
        )
        return {int(row["discord_role_id"]) for row in rows}

    async def rank_role_id_for_rank(self, guild_id: int, rank_id: int) -> int | None:
        mapping = await self.database.fetchone(
            """
            SELECT discord_role_id
            FROM discord_role_mappings
            WHERE guild_id=? AND rank_id=? AND mapping_type='RANK' AND enabled=1
            ORDER BY priority DESC, id ASC LIMIT 1
            """,
            (guild_id, rank_id),
        )
        if mapping:
            return int(mapping["discord_role_id"])
        has_mapping = await self.database.fetchone(
            """
            SELECT 1 FROM discord_role_mappings
            WHERE guild_id=? AND rank_id=? AND mapping_type='RANK' LIMIT 1
            """,
            (guild_id, rank_id),
        )
        if has_mapping:
            return None
        rank = await self.database.fetchone(
            "SELECT discord_role_id FROM ranks WHERE guild_id=? AND id=? AND active=1",
            (guild_id, rank_id),
        )
        return (
            int(rank["discord_role_id"])
            if rank and rank["discord_role_id"] is not None
            else None
        )

    async def relevant_role_ids(self, guild_id: int) -> set[int]:
        """Return roles whose presence can affect identity or authorization."""
        rank_ids = await self.rank_role_ids(guild_id)
        rows = await self.database.fetchall(
            """
            SELECT DISTINCT discord_role_id
            FROM discord_role_mappings
            WHERE guild_id=? AND enabled=1 AND mapping_type!='COSMETIC'
            """,
            (guild_id,),
        )
        rank_ids.update(int(row["discord_role_id"]) for row in rows)
        companion_role_id = await self.settings.get(guild_id, "companion_role_id")
        if companion_role_id:
            rank_ids.add(int(companion_role_id))
        return rank_ids

    async def _nickname_prefix_for_roles(
        self, guild_id: int, rank_prefix: str, role_ids: set[int]
    ) -> str:
        """Apply the approved Companheiro de Farda identity prefix.

        This role changes only the visible nickname prefix. It is deliberately
        not modeled as a rank and therefore does not alter rank, RBAC or career
        state.
        """
        companion_role_id = await self.settings.get(guild_id, "companion_role_id")
        if companion_role_id and int(companion_role_id) in role_ids:
            return "COMP.F"
        return rank_prefix

    async def role_change_is_relevant(
        self, guild_id: int, before_role_ids: set[int], after_role_ids: set[int]
    ) -> bool:
        changed = before_role_ids.symmetric_difference(after_role_ids)
        return bool(changed.intersection(await self.relevant_role_ids(guild_id)))

    async def registered_discord_ids(self, guild_id: int) -> list[int]:
        rows = await self.database.fetchall(
            "SELECT discord_id FROM members WHERE guild_id=? ORDER BY id",
            (guild_id,),
        )
        return [int(row["discord_id"]) for row in rows]

    async def _identity_catalog_hash(self, guild_id: int) -> str:
        """Hash every catalog input capable of changing identity or authorization."""
        queries = {
            "mappings": """
                SELECT id, discord_role_id, mapping_type, internal_code, display_name,
                       priority, rank_id, position_id, access_profile_id,
                       is_primary_position_candidate, enabled, updated_at
                FROM discord_role_mappings
                WHERE guild_id=? AND mapping_type!='COSMETIC'
                ORDER BY id
            """,
            "ranks": """
                SELECT id, name, prefix, level, rbac_profile, active
                FROM ranks WHERE guild_id=? ORDER BY id
            """,
            "positions": """
                SELECT id, code, name, priority, access_profile_id,
                       is_primary_candidate, enabled, updated_at
                FROM functional_positions WHERE guild_id=? ORDER BY id
            """,
            "profiles": """
                SELECT id, code, name, priority, enabled, updated_at
                FROM access_profiles WHERE guild_id=? ORDER BY id
            """,
            "profile_permissions": """
                SELECT app.access_profile_id, app.permission, app.effect, app.updated_at
                FROM access_profile_permissions app
                JOIN access_profiles ap ON ap.id=app.access_profile_id
                WHERE ap.guild_id=?
                ORDER BY app.access_profile_id, app.permission
            """,
            "position_permissions": """
                SELECT fpp.position_id, fpp.permission, fpp.effect, fpp.updated_at
                FROM functional_position_permissions fpp
                JOIN functional_positions fp ON fp.id=fpp.position_id
                WHERE fp.guild_id=?
                ORDER BY fpp.position_id, fpp.permission
            """,
            "rank_permissions": """
                SELECT rp.rank_id, rp.permission, rp.effect, rp.updated_at
                FROM rank_permissions rp
                JOIN ranks r ON r.id=rp.rank_id
                WHERE r.guild_id=?
                ORDER BY rp.rank_id, rp.permission
            """,
        }
        payload: dict[str, object] = {}
        for key, query in queries.items():
            rows = await self.database.fetchall(query, (guild_id,))
            payload[key] = [dict(row) for row in rows]
        payload["missing_rank_role_policy"] = str(
            await self.settings.get(guild_id, "missing_rank_role_policy", "KEEP_LAST")
        ).upper()
        return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()

    async def resolve_rank(self, guild_id: int, role_ids: set[int]):
        if not role_ids:
            return None, []
        rows = await self.database.fetchall(
            _CANONICAL_RANK_ROLES_SQL,
            (guild_id, guild_id),
        )
        matched = [row for row in rows if int(row["discord_role_id"]) in role_ids]
        unique: list[Any] = []
        seen: set[int] = set()
        for row in matched:
            rank_id = int(row["id"])
            if rank_id in seen:
                continue
            seen.add(rank_id)
            unique.append(row)
        return (unique[0] if unique else None), unique

    async def initial_rank_id(self, guild_id: int, role_ids: set[int]) -> int | None:
        selected, _ = await self.resolve_rank(guild_id, role_ids)
        if selected:
            return int(selected["id"])
        lowest = await self.database.fetchone(
            "SELECT id FROM ranks WHERE guild_id=? AND active=1 ORDER BY level, id LIMIT 1",
            (guild_id,),
        )
        return int(lowest["id"]) if lowest else None

    async def _ensure_access_profiles(
        self, connection: aiosqlite.Connection, guild_id: int, now: int
    ) -> None:
        for code, (name, priority) in PROFILE_METADATA.items():
            await connection.execute(
                """
                INSERT OR IGNORE INTO access_profiles(
                    guild_id, code, name, priority, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (guild_id, code, name, priority, now, now),
            )

    async def _member_row(
        self, connection: aiosqlite.Connection, guild_id: int, discord_id: int
    ):
        cursor = await connection.execute(
            """
            SELECT m.*, r.name AS current_rank_name, r.prefix AS current_rank_prefix,
                   r.level AS current_rank_level,
                   r.discord_role_id AS current_rank_role_id,
                   r.rbac_profile AS current_rank_profile,
                   ap.code AS current_access_profile_code,
                   ap.name AS current_access_profile_name,
                   fp.code AS current_primary_position_code,
                   fp.name AS current_primary_position_name
            FROM members m
            LEFT JOIN ranks r ON r.id=m.rank_id
            LEFT JOIN access_profiles ap ON ap.id=m.access_profile_id
            LEFT JOIN functional_positions fp ON fp.id=m.primary_position_id
            WHERE m.guild_id=? AND m.discord_id=?
            """,
            (guild_id, discord_id),
        )
        return await cursor.fetchone()

    async def _current_positions(
        self, connection: aiosqlite.Connection, member_id: int
    ) -> tuple[IdentityPosition, ...]:
        cursor = await connection.execute(
            """
            SELECT fp.id, fp.code, fp.name, fp.priority,
                   mp.source_role_id, mp.is_primary
            FROM member_positions mp
            JOIN functional_positions fp ON fp.id=mp.position_id
            WHERE mp.member_id=?
            ORDER BY mp.is_primary DESC, fp.priority DESC, fp.id ASC
            """,
            (member_id,),
        )
        return tuple(
            IdentityPosition(
                id=int(row["id"]),
                code=str(row["code"]),
                name=str(row["name"]),
                priority=int(row["priority"]),
                source_role_id=int(row["source_role_id"]),
                is_primary=bool(row["is_primary"]),
            )
            for row in await cursor.fetchall()
        )

    async def _current_access_profiles(
        self, connection: aiosqlite.Connection, member_id: int
    ) -> tuple[IdentityAccessProfile, ...]:
        cursor = await connection.execute(
            """
            SELECT ap.id, ap.code, ap.name, ap.priority,
                   map.source_mapping_id, map.source_role_id
            FROM member_access_profiles map
            JOIN access_profiles ap ON ap.id=map.access_profile_id
            WHERE map.member_id=?
            ORDER BY ap.priority DESC, map.source_mapping_id ASC
            """,
            (member_id,),
        )
        return tuple(
            IdentityAccessProfile(
                id=int(row["id"]),
                code=str(row["code"]),
                name=str(row["name"]),
                priority=int(row["priority"]),
                source_mapping_id=int(row["source_mapping_id"]),
                source_role_id=int(row["source_role_id"]),
            )
            for row in await cursor.fetchall()
        )

    async def _resolve_desired_identity(
        self,
        connection: aiosqlite.Connection,
        member,
        role_ids: set[int],
        *,
        missing_policy: str,
    ) -> _DesiredIdentity:
        guild_id = int(member["guild_id"])
        cursor = await connection.execute(
            _CANONICAL_RANK_ROLES_SQL,
            (guild_id, guild_id),
        )
        configured_ranks = await cursor.fetchall()
        matched_rank_roles = [
            row for row in configured_ranks if int(row["discord_role_id"]) in role_ids
        ]
        matched_ranks: list[Any] = []
        seen_rank_ids: set[int] = set()
        for row in matched_rank_roles:
            rank_id = int(row["id"])
            if rank_id in seen_rank_ids:
                continue
            seen_rank_ids.add(rank_id)
            matched_ranks.append(row)
        selected_rank = matched_ranks[0] if matched_ranks else None
        if selected_rank:
            rank_id = int(selected_rank["id"])
            rank_name = str(selected_rank["name"])
            rank_prefix = str(selected_rank["prefix"] or "")
            rank_level = int(selected_rank["level"])
            rank_role_id = int(selected_rank["discord_role_id"])
            rank_profile_code = str(selected_rank["rbac_profile"] or "MEMBRO")
            rank_sync_status = "MULTIPLE_RANKS" if len(matched_ranks) > 1 else "SYNCED"
        elif missing_policy == "MARK_UNSYNCED":
            rank_id = None
            rank_name = None
            rank_prefix = ""
            rank_level = None
            rank_role_id = None
            rank_profile_code = "MEMBRO"
            rank_sync_status = "MISSING_ROLE"
        else:
            rank_id = int(member["rank_id"]) if member["rank_id"] is not None else None
            rank_name = (
                str(member["current_rank_name"])
                if member["current_rank_name"] is not None
                else None
            )
            rank_prefix = str(member["current_rank_prefix"] or "")
            rank_level = (
                int(member["current_rank_level"])
                if member["current_rank_level"] is not None
                else None
            )
            rank_role_id = (
                int(member["current_rank_role_id"])
                if member["current_rank_role_id"] is not None
                else None
            )
            # KEEP_LAST retains the historical rank/nickname only.  It must
            # never retain the access profile granted by a rank role that is
            # no longer present in Discord.
            rank_profile_code = "MEMBRO"
            rank_sync_status = "MISSING_ROLE"

        mappings: list[Any] = []
        if role_ids:
            placeholders = ",".join("?" for _ in role_ids)
            cursor = await connection.execute(
                f"""
                SELECT drm.id AS mapping_id, drm.discord_role_id, drm.mapping_type,
                       drm.internal_code, drm.priority AS mapping_priority,
                       drm.access_profile_id AS mapping_access_profile_id,
                       mapping_ap.id AS mapped_profile_id,
                       mapping_ap.code AS mapped_profile_code,
                       mapping_ap.name AS mapped_profile_name,
                       mapping_ap.priority AS mapped_profile_priority,
                       drm.is_primary_position_candidate,
                       fp.id AS position_id, fp.code AS position_code,
                       fp.name AS position_name, fp.priority AS position_priority,
                       fp.access_profile_id AS position_access_profile_id,
                       fp.is_primary_candidate
                FROM discord_role_mappings drm
                LEFT JOIN functional_positions fp
                  ON fp.id=drm.position_id AND fp.enabled=1
                LEFT JOIN access_profiles mapping_ap
                  ON mapping_ap.id=drm.access_profile_id AND mapping_ap.enabled=1
                WHERE drm.guild_id=? AND drm.enabled=1
                  AND drm.discord_role_id IN ({placeholders})
                ORDER BY drm.priority DESC, drm.id ASC
                """,
                (guild_id, *sorted(role_ids)),
            )
            mappings = list(await cursor.fetchall())

        companion_role_id = await self.settings.get(guild_id, "companion_role_id")
        nickname_prefix = await self._nickname_prefix_for_roles(
            guild_id, rank_prefix, role_ids
        )
        relevant_ids = {
            int(row["discord_role_id"])
            for row in matched_rank_roles
        }
        relevant_ids.update(
            int(row["discord_role_id"])
            for row in mappings
            if str(row["mapping_type"]) != "COSMETIC"
        )
        if companion_role_id and int(companion_role_id) in role_ids:
            relevant_ids.add(int(companion_role_id))

        position_rows = [
            row
            for row in mappings
            if str(row["mapping_type"]) == "POSITION" and row["position_id"] is not None
        ]
        position_rows.sort(
            key=lambda row: (
                -int(row["mapping_priority"]),
                -int(row["position_priority"]),
                int(row["position_id"]),
                int(row["discord_role_id"]),
            )
        )
        unique_position_rows: list[Any] = []
        seen_positions: set[int] = set()
        for row in position_rows:
            position_id = int(row["position_id"])
            if position_id in seen_positions:
                continue
            seen_positions.add(position_id)
            unique_position_rows.append(row)
        primary_row = next(
            (
                row
                for row in unique_position_rows
                if bool(row["is_primary_position_candidate"])
                and bool(row["is_primary_candidate"])
            ),
            None,
        )
        primary_position_id = int(primary_row["position_id"]) if primary_row else None
        positions = tuple(
            IdentityPosition(
                id=int(row["position_id"]),
                code=str(row["position_code"]),
                name=str(row["position_name"]),
                priority=max(
                    int(row["mapping_priority"]), int(row["position_priority"])
                ),
                source_role_id=int(row["discord_role_id"]),
                is_primary=int(row["position_id"]) == primary_position_id,
            )
            for row in unique_position_rows
        )

        access_profiles = tuple(
            IdentityAccessProfile(
                id=int(row["mapped_profile_id"]),
                code=str(row["mapped_profile_code"]),
                name=str(row["mapped_profile_name"]),
                priority=int(row["mapped_profile_priority"]),
                source_mapping_id=int(row["mapping_id"]),
                source_role_id=int(row["discord_role_id"]),
            )
            for row in mappings
            if str(row["mapping_type"]) == "ACCESS"
            and row["mapped_profile_id"] is not None
        )

        candidate_profile_ids: set[int] = {
            int(value)
            for row in mappings
            if str(row["mapping_type"]) != "COSMETIC"
            for value in (
                row["mapped_profile_id"],
                row["position_access_profile_id"],
            )
            if value is not None
        }
        cursor = await connection.execute(
            """
            SELECT id FROM access_profiles
            WHERE guild_id=? AND code=? AND enabled=1
            """,
            (guild_id, rank_profile_code),
        )
        rank_profile = await cursor.fetchone()
        if rank_profile:
            candidate_profile_ids.add(int(rank_profile["id"]))

        # A record that is still pending registration must not gain an
        # elevated web/bot identity merely by holding a Discord role.
        forced_profile_code = "CANDIDATO" if str(member["status"]) == "PENDING" else None
        if forced_profile_code:
            cursor = await connection.execute(
                """
                SELECT id, code, name, priority FROM access_profiles
                WHERE guild_id=? AND code=? AND enabled=1
                """,
                (guild_id, forced_profile_code),
            )
            access_profile = await cursor.fetchone()
        else:
            access_profile = None
            if candidate_profile_ids:
                placeholders = ",".join("?" for _ in candidate_profile_ids)
                cursor = await connection.execute(
                    f"""
                    SELECT id, code, name, priority FROM access_profiles
                    WHERE guild_id=? AND enabled=1 AND id IN ({placeholders})
                    ORDER BY priority DESC, id ASC LIMIT 1
                    """,
                    (guild_id, *sorted(candidate_profile_ids)),
                )
                access_profile = await cursor.fetchone()
            if access_profile is None:
                cursor = await connection.execute(
                    """
                    SELECT id, code, name, priority FROM access_profiles
                    WHERE guild_id=? AND code='MEMBRO' AND enabled=1
                    """,
                    (guild_id,),
                )
                access_profile = await cursor.fetchone()
        if access_profile is None:  # pragma: no cover - guarded by profile initialization
            raise RuntimeError("Perfil de acesso base não disponível")

        relevant_role_ids = tuple(sorted(relevant_ids))
        roles_hash = hashlib.sha256(_json(relevant_role_ids).encode("utf-8")).hexdigest()
        return _DesiredIdentity(
            rank_id=rank_id,
            rank_name=rank_name,
            rank_prefix=rank_prefix,
            rank_level=rank_level,
            rank_role_id=rank_role_id,
            rank_sync_status=rank_sync_status,
            matched_rank_role_ids=tuple(
                sorted({int(row["discord_role_id"]) for row in matched_rank_roles})
            ),
            expected_nickname=format_member_nickname(
                nickname_prefix,
                str(member["mta_nick"]),
                str(member["character_id"] or ""),
            ),
            positions=positions,
            primary_position_id=primary_position_id,
            access_profiles=access_profiles,
            access_profile_id=int(access_profile["id"]),
            access_profile_code=str(access_profile["code"]),
            access_profile_name=str(access_profile["name"]),
            relevant_role_ids=relevant_role_ids,
            discord_roles_hash=roles_hash,
        )

    @staticmethod
    def _snapshot(
        member,
        positions: tuple[IdentityPosition, ...],
        *,
        access_profiles: tuple[IdentityAccessProfile, ...] = (),
        desired: _DesiredIdentity | None = None,
        discord_present: bool | None = None,
        identity_sync_status: str | None = None,
        discord_roles_synced_at: int | None = None,
    ) -> dict[str, object]:
        if desired is None:
            primary = next((position for position in positions if position.is_primary), None)
            return {
                "rank_id": int(member["rank_id"]) if member["rank_id"] is not None else None,
                "rank_name": (
                    str(member["current_rank_name"])
                    if member["current_rank_name"] is not None
                    else None
                ),
                "rank_sync_status": str(member["rank_sync_status"]),
                "primary_position_id": (
                    int(member["primary_position_id"])
                    if member["primary_position_id"] is not None
                    else None
                ),
                "primary_position_code": primary.code if primary else None,
                "positions": [position.as_dict() for position in positions],
                "access_profiles": [profile.as_dict() for profile in access_profiles],
                "access_profile_id": (
                    int(member["access_profile_id"])
                    if member["access_profile_id"] is not None
                    else None
                ),
                "access_profile": (
                    str(member["current_access_profile_code"])
                    if member["current_access_profile_code"] is not None
                    else None
                ),
                "authorization_version": int(member["authorization_version"] or 1),
                "identity_sync_status": str(member["identity_sync_status"] or "PENDING"),
                "discord_present": bool(member["discord_present"]),
                "discord_roles_hash": (
                    str(member["discord_roles_hash"])
                    if member["discord_roles_hash"] is not None
                    else None
                ),
                "discord_roles_synced_at": (
                    int(member["discord_roles_synced_at"])
                    if member["discord_roles_synced_at"] is not None
                    else None
                ),
                "member_status": str(member["status"]),
            }
        primary = next((position for position in desired.positions if position.is_primary), None)
        return {
            "rank_id": desired.rank_id,
            "rank_name": desired.rank_name,
            "rank_sync_status": desired.rank_sync_status,
            "primary_position_id": desired.primary_position_id,
            "primary_position_code": primary.code if primary else None,
            "positions": [position.as_dict() for position in desired.positions],
            "access_profiles": [
                profile.as_dict() for profile in desired.access_profiles
            ],
            "access_profile_id": desired.access_profile_id,
            "access_profile": desired.access_profile_code,
            "authorization_version": int(member["authorization_version"] or 1),
            "identity_sync_status": identity_sync_status or "SYNCED",
            "discord_present": True if discord_present is None else discord_present,
            "discord_roles_hash": desired.discord_roles_hash,
            "discord_roles_synced_at": discord_roles_synced_at,
            "member_status": str(member["status"]),
        }

    async def preview_from_discord(
        self,
        guild_id: int,
        discord_id: int,
        role_ids: set[int],
        current_nickname: str | None,
        *,
        source: str,
    ) -> IdentityPreview:
        del current_nickname
        async with self._member_lock(guild_id, discord_id):
            now = self.clock()
            missing_policy = str(
                await self.settings.get(guild_id, "missing_rank_role_policy", "KEEP_LAST")
            ).upper()
            async with self.database.transaction() as connection:
                await self._ensure_access_profiles(connection, guild_id, now)
                member = await self._member_row(connection, guild_id, discord_id)
                if not member:
                    return IdentityPreview(False, discord_id, source, {}, {})
                current_positions = await self._current_positions(connection, int(member["id"]))
                current_access_profiles = await self._current_access_profiles(
                    connection, int(member["id"])
                )
                desired = await self._resolve_desired_identity(
                    connection, member, role_ids, missing_policy=missing_policy
                )
                before = self._snapshot(
                    member,
                    current_positions,
                    access_profiles=current_access_profiles,
                )
                after = self._snapshot(
                    member,
                    desired.positions,
                    desired=desired,
                    discord_roles_synced_at=now,
                )
            old_position_signature = {
                (position.id, position.source_role_id, position.is_primary)
                for position in current_positions
            }
            new_position_signature = {
                (position.id, position.source_role_id, position.is_primary)
                for position in desired.positions
            }
            return IdentityPreview(
                True,
                discord_id,
                source,
                before,
                after,
                relevant_role_ids=desired.relevant_role_ids,
                rank_changed=before["rank_id"] != after["rank_id"],
                positions_changed=old_position_signature != new_position_signature,
                access_changed=(
                    before["access_profile_id"] != after["access_profile_id"]
                    or before["access_profiles"] != after["access_profiles"]
                ),
                presence_changed=(
                    not bool(before["discord_present"])
                    or before["identity_sync_status"] != "SYNCED"
                ),
            )

    async def preview_from_member(
        self, target: discord.Member, *, source: str = "PANEL_ACTION"
    ) -> IdentityPreview:
        return await self.preview_from_discord(
            target.guild.id,
            target.id,
            {int(role.id) for role in target.roles},
            target.nick,
            source=source,
        )

    async def identity_state(self, guild_id: int, discord_id: int) -> dict[str, object] | None:
        """Return the persisted projection used by API/job observability."""
        async with self._member_lock(guild_id, discord_id):
            async with self.database.transaction() as connection:
                member = await self._member_row(connection, guild_id, discord_id)
                if not member:
                    return None
                positions = await self._current_positions(connection, int(member["id"]))
                access_profiles = await self._current_access_profiles(
                    connection, int(member["id"])
                )
                state = self._snapshot(
                    member, positions, access_profiles=access_profiles
                )
                state["member_id"] = int(member["id"])
                state["discord_id"] = discord_id
                return state

    async def reconcile_guild(
        self,
        guild: discord.Guild,
        *,
        source: str,
        actor_id: int | None = None,
        correlation_id: str | None = None,
        discord_ids: list[int] | tuple[int, ...] | None = None,
        batch_delay_seconds: float = 0.0,
    ) -> ReconciliationSummary:
        """Reconcile registered members against fresh Discord membership state."""
        operation_correlation_id = _operation_correlation_id(correlation_id)
        targets = (
            list(discord_ids)
            if discord_ids is not None
            else await self.registered_discord_ids(guild.id)
        )
        checked = changed = unchanged = absent = failed = 0
        errors: list[str] = []
        delay = max(0.0, min(float(batch_delay_seconds), 5.0))
        for index, discord_id in enumerate(targets):
            member = guild.get_member(int(discord_id))
            if member is None:
                try:
                    member = await guild.fetch_member(int(discord_id))
                except discord.NotFound:
                    result = await self.mark_discord_absent(
                        guild.id,
                        int(discord_id),
                        source=source,
                        actor_id=actor_id,
                        correlation_id=operation_correlation_id,
                    )
                    checked += int(result.registered)
                    changed += int(result.db_changed)
                    unchanged += int(result.registered and not result.db_changed)
                    absent += int(result.registered)
                    if delay and index + 1 < len(targets):
                        await asyncio.sleep(delay)
                    continue
                except (discord.Forbidden, discord.HTTPException) as exc:
                    failed += 1
                    errors.append(f"{discord_id}: {type(exc).__name__}")
                    if delay and index + 1 < len(targets):
                        await asyncio.sleep(delay)
                    continue
                except Exception as exc:  # defensive boundary for test adapters/custom guilds
                    failed += 1
                    errors.append(f"{discord_id}: {type(exc).__name__}")
                    if delay and index + 1 < len(targets):
                        await asyncio.sleep(delay)
                    continue
            try:
                result = await self.sync_from_member(
                    member,
                    source=source,
                    actor_id=actor_id,
                    correlation_id=operation_correlation_id,
                )
            except Exception as exc:
                failed += 1
                errors.append(f"{discord_id}: {type(exc).__name__}")
            else:
                checked += int(result.registered)
                changed += int(result.db_changed)
                unchanged += int(result.registered and not result.db_changed)
            if delay and index + 1 < len(targets):
                await asyncio.sleep(delay)
        return ReconciliationSummary(
            checked=checked,
            changed=changed,
            unchanged=unchanged,
            absent=absent,
            failed=failed,
            errors=tuple(errors),
        )

    async def process_reconciliation_job(
        self,
        job_id: int,
        guild: discord.Guild,
        *,
        source: str = "PANEL_ACTION",
        correlation_id: str | None = None,
    ) -> ReconciliationSummary:
        """Execute a persisted PREVIEW/APPLY identity reconciliation job.

        The web outbox may invoke this method directly; it never needs to find
        a Cog. Discord I/O is intentionally outside long SQLite transactions,
        while every item/result remains restart-safe and idempotent.
        """
        job = await self.database.fetchone(
            "SELECT * FROM identity_reconciliation_jobs WHERE id=?", (job_id,)
        )
        if not job:
            raise ValueError("Job de reconciliação não encontrado")
        if int(job["guild_id"]) != guild.id:
            raise ValueError("Job não pertence à guild informada")
        operation_correlation_id = str(job["correlation_id"])
        if correlation_id is not None and str(correlation_id) != operation_correlation_id:
            raise ValueError("Correlação do outbox diverge da correlação persistida do job")
        if str(job["status"]) == "COMPLETED":
            return await self._finalize_reconciliation_job(
                job_id,
                guild_id=guild.id,
                actor_id=int(job["requested_by"]),
                mode=str(job["mode"]),
                total_members=int(job["total_members"]),
                correlation_id=operation_correlation_id,
                record_audit=False,
            )
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE identity_reconciliation_jobs
                SET status='PROCESSING', started_at=?, completed_at=NULL, last_error=NULL
                WHERE id=? AND status IN ('PENDING','FAILED')
                """,
                (now, job_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Job já está sendo processado")
        mode = str(job["mode"])
        actor_id = int(job["requested_by"])
        source_job_id = int(job["source_job_id"]) if job["source_job_id"] else None
        source_items: dict[int, object] = {}
        if source_job_id is not None:
            source_job = await self.database.fetchone(
                """
                SELECT guild_id, mode, status, catalog_hash
                FROM identity_reconciliation_jobs WHERE id=?
                """,
                (source_job_id,),
            )
            if (
                not source_job
                or int(source_job["guild_id"]) != guild.id
                or str(source_job["mode"]) != "PREVIEW"
                or str(source_job["status"]) != "COMPLETED"
            ):
                await self.database.execute(
                    """
                    UPDATE identity_reconciliation_jobs
                    SET status='FAILED', completed_at=?, last_error=? WHERE id=?
                    """,
                    (self.clock(), "Preview de origem inválido ou incompleto", job_id),
                )
                raise ValueError("Preview de origem inválido ou incompleto")
            rows = await self.database.fetchall(
                """
                SELECT i.member_id, i.discord_id, i.before_json, i.after_json,
                       i.role_ids_json, i.roles_hash, i.discord_present_snapshot
                FROM identity_reconciliation_job_items i
                WHERE i.job_id=?
                ORDER BY i.id
                """,
                (source_job_id,),
            )
            targets = [(int(row["member_id"]), int(row["discord_id"])) for row in rows]
            source_items = {int(row["member_id"]): row for row in rows}
            expected_catalog_hash = str(source_job["catalog_hash"] or "")
        else:
            rows = await self.database.fetchall(
                "SELECT id AS member_id, discord_id FROM members WHERE guild_id=? ORDER BY id",
                (guild.id,),
            )
            targets = [(int(row["member_id"]), int(row["discord_id"])) for row in rows]
            expected_catalog_hash = str(job["catalog_hash"] or "")

        current_catalog_hash = await self._identity_catalog_hash(guild.id)
        if not expected_catalog_hash:
            expected_catalog_hash = current_catalog_hash
        await self.database.execute(
            """
            UPDATE identity_reconciliation_jobs SET catalog_hash=? WHERE id=?
            """,
            (expected_catalog_hash, job_id),
        )

        existing_rows = await self.database.fetchall(
            "SELECT member_id, result FROM identity_reconciliation_job_items WHERE job_id=?",
            (job_id,),
        )
        existing_results = {
            int(row["member_id"]): str(row["result"]) for row in existing_rows
        }
        terminal_results = (
            {"UNCHANGED", "DIVERGENT", "REVIEW_REQUIRED"}
            if mode == "PREVIEW"
            else {"UNCHANGED", "APPLIED"}
        )

        if current_catalog_hash != expected_catalog_hash:
            error = "Preview obsoleto: catálogo de identidade alterado"
            for member_id, discord_id in targets:
                if existing_results.get(member_id) in terminal_results:
                    continue
                source_item = source_items.get(member_id)
                before = (
                    json.loads(str(source_item["before_json"])) if source_item else {}
                )
                role_ids = (
                    tuple(json.loads(str(source_item["role_ids_json"])))
                    if source_item
                    else ()
                )
                await self._upsert_reconciliation_item(
                    job_id,
                    member_id,
                    discord_id,
                    "FAILED",
                    before,
                    before,
                    error,
                    role_ids=role_ids,
                    roles_hash=(str(source_item["roles_hash"] or "") if source_item else None),
                    discord_present=(
                        bool(source_item["discord_present_snapshot"])
                        if source_item
                        else False
                    ),
                )
            return await self._finalize_reconciliation_job(
                job_id,
                guild_id=guild.id,
                actor_id=actor_id,
                mode=mode,
                total_members=len(targets),
                correlation_id=operation_correlation_id,
                forced_error=error,
            )

        for member_id, discord_id in targets:
            if existing_results.get(member_id) in terminal_results:
                continue
            before: dict[str, object] = {}
            role_ids: tuple[int, ...] = ()
            roles_hash: str | None = None
            discord_present = False
            try:
                before = await self.identity_state(guild.id, discord_id) or {}
                if not before:
                    raise RuntimeError("Cadastro deixou de existir durante a reconciliação")
                member = guild.get_member(discord_id)
                if member is None:
                    try:
                        member = await guild.fetch_member(discord_id)
                    except discord.NotFound:
                        member = None
                discord_present = member is not None
                role_ids = (
                    tuple(sorted({int(role.id) for role in member.roles}))
                    if member is not None
                    else ()
                )
                roles_hash = _role_snapshot_hash(role_ids, present=discord_present)

                source_item = source_items.get(member_id)
                if source_item is not None:
                    if await self._identity_catalog_hash(guild.id) != expected_catalog_hash:
                        raise RuntimeError(
                            "Preview obsoleto: catálogo alterado durante a aplicação"
                        )
                    expected_roles_hash = str(source_item["roles_hash"] or "")
                    expected_present = bool(source_item["discord_present_snapshot"])
                    if (
                        not expected_roles_hash
                        or roles_hash != expected_roles_hash
                        or discord_present != expected_present
                    ):
                        raise RuntimeError(
                            "Preview obsoleto: cargos Discord do membro foram alterados"
                        )

                if member is None:
                    after = {
                        **before,
                        "primary_position_id": None,
                        "primary_position_code": None,
                        "positions": [],
                        "access_profiles": [],
                        "access_profile": (
                            "CANDIDATO"
                            if before.get("member_status") == "PENDING"
                            else "MEMBRO"
                        ),
                        "authorization_version": int(before["authorization_version"])
                        + int(
                            bool(before["discord_present"])
                            or before["identity_sync_status"] != "DISCORD_ABSENT"
                            or bool(before["positions"])
                            or bool(before.get("access_profiles"))
                        ),
                        "identity_sync_status": "DISCORD_ABSENT",
                        "discord_present": False,
                        "discord_roles_hash": None,
                    }
                    if mode == "APPLY":
                        result = await self.mark_discord_absent(
                            guild.id,
                            discord_id,
                            source=source,
                            actor_id=actor_id,
                            correlation_id=operation_correlation_id,
                        )
                        after = await self.identity_state(guild.id, discord_id) or after
                        item_result = "APPLIED" if result.db_changed else "UNCHANGED"
                    else:
                        item_result = "REVIEW_REQUIRED"
                else:
                    preview = await self.preview_from_member(
                        member,
                        source=source if mode == "APPLY" else f"{source}_PREVIEW",
                    )
                    if mode == "APPLY":
                        result = await self.sync_from_member(
                            member,
                            source=source,
                            actor_id=actor_id,
                            expected_roles_hash=roles_hash,
                            correlation_id=operation_correlation_id,
                        )
                        after = (
                            await self.identity_state(guild.id, discord_id)
                            or preview.after
                        )
                        item_result = "APPLIED" if result.db_changed else "UNCHANGED"
                    else:
                        after = preview.after
                        item_result = "DIVERGENT" if preview.differs else "UNCHANGED"
                await self._upsert_reconciliation_item(
                    job_id,
                    member_id,
                    discord_id,
                    item_result,
                    before,
                    after,
                    None,
                    role_ids=role_ids,
                    roles_hash=roles_hash,
                    discord_present=discord_present,
                )
            except Exception as exc:
                await self._upsert_reconciliation_item(
                    job_id,
                    member_id,
                    discord_id,
                    "FAILED",
                    before,
                    before,
                    f"{type(exc).__name__}: {exc}"[:500],
                    role_ids=role_ids,
                    roles_hash=roles_hash,
                    discord_present=discord_present,
                )

        return await self._finalize_reconciliation_job(
            job_id,
            guild_id=guild.id,
            actor_id=actor_id,
            mode=mode,
            total_members=len(targets),
            correlation_id=operation_correlation_id,
        )

    async def _finalize_reconciliation_job(
        self,
        job_id: int,
        *,
        guild_id: int,
        actor_id: int,
        mode: str,
        total_members: int,
        correlation_id: str,
        forced_error: str | None = None,
        record_audit: bool = True,
    ) -> ReconciliationSummary:
        rows = await self.database.fetchall(
            """
            SELECT result, before_json, after_json, error
            FROM identity_reconciliation_job_items WHERE job_id=? ORDER BY id
            """,
            (job_id,),
        )
        unchanged = changed = absent = failed = 0
        divergent_positions = divergent_ranks = review = 0
        errors: list[str] = []
        for row in rows:
            result = str(row["result"])
            before = json.loads(str(row["before_json"] or "{}"))
            after = json.loads(str(row["after_json"] or "{}"))
            unchanged += int(result == "UNCHANGED")
            changed += int(result in {"DIVERGENT", "APPLIED"})
            review += int(result == "REVIEW_REQUIRED")
            failed += int(result == "FAILED")
            absent += int(after.get("identity_sync_status") == "DISCORD_ABSENT")
            divergent_positions += int(
                before.get("positions") != after.get("positions")
            )
            divergent_ranks += int(
                before.get("rank_id") != after.get("rank_id")
                or before.get("rank_sync_status") != after.get("rank_sync_status")
            )
            if result == "FAILED" and row["error"]:
                errors.append(str(row["error"]))
        final_status = "FAILED" if failed or forced_error else "COMPLETED"
        last_error = forced_error or (f"{failed} membro(s) falharam" if failed else None)
        await self.database.execute(
            """
            UPDATE identity_reconciliation_jobs
            SET status=?, total_members=?, unchanged_members=?,
                divergent_positions=?, divergent_ranks=?, review_required=?,
                failed_members=?, completed_at=?, last_error=?
            WHERE id=?
            """,
            (
                final_status,
                total_members,
                unchanged,
                divergent_positions,
                divergent_ranks,
                review,
                failed,
                self.clock(),
                last_error,
                job_id,
            ),
        )
        summary = ReconciliationSummary(
            checked=max(0, total_members - failed),
            changed=changed,
            unchanged=unchanged,
            absent=absent,
            failed=failed,
            errors=tuple(errors),
        )
        if record_audit:
            await self._record_correlated_audit(
                guild_id,
                (
                    "IDENTITY_RECONCILIATION_JOB_FAILED"
                    if final_status == "FAILED"
                    else "IDENTITY_RECONCILIATION_JOB_COMPLETED"
                ),
                actor_id=actor_id,
                correlation_id=correlation_id,
                suffix=f"reconciliation-{job_id}-{final_status.lower()}",
                after={
                    "job_id": job_id,
                    "mode": mode,
                    "total": total_members,
                    "changed": summary.changed,
                    "unchanged": summary.unchanged,
                    "absent": summary.absent,
                    "failed": summary.failed,
                },
                reason="Reconciliação em lote da identidade Discord",
            )
        return summary

    async def _upsert_reconciliation_item(
        self,
        job_id: int,
        member_id: int,
        discord_id: int,
        result: str,
        before: dict[str, object],
        after: dict[str, object],
        error: str | None,
        *,
        role_ids: tuple[int, ...] = (),
        roles_hash: str | None = None,
        discord_present: bool = True,
    ) -> None:
        now = self.clock()
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO identity_reconciliation_job_items(
                    job_id, member_id, discord_id, result,
                    before_json, after_json, role_ids_json, roles_hash,
                    discord_present_snapshot, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, member_id) DO UPDATE SET
                    result=excluded.result,
                    before_json=excluded.before_json,
                    after_json=excluded.after_json,
                    role_ids_json=excluded.role_ids_json,
                    roles_hash=excluded.roles_hash,
                    discord_present_snapshot=excluded.discord_present_snapshot,
                    error=excluded.error,
                    created_at=excluded.created_at
                """,
                (
                    job_id,
                    member_id,
                    discord_id,
                    result,
                    _json(before),
                    _json(after),
                    _json(role_ids),
                    roles_hash,
                    int(discord_present),
                    error,
                    now,
                ),
            )

    async def sync_from_discord(
        self,
        guild_id: int,
        discord_id: int,
        role_ids: set[int],
        current_nickname: str | None,
        *,
        source: str,
        actor_id: int | None = None,
        correlation_id: str | None = None,
    ) -> RankSyncResult:
        operation_correlation_id = _operation_correlation_id(correlation_id)
        async with self._member_lock(guild_id, discord_id):
            return await self._sync_from_discord_unlocked(
                guild_id,
                discord_id,
                role_ids,
                current_nickname,
                source=source,
                actor_id=actor_id,
                correlation_id=operation_correlation_id,
            )

    async def _insert_identity_event(
        self,
        connection: aiosqlite.Connection,
        *,
        guild_id: int,
        member_id: int,
        discord_id: int,
        event_type: str,
        source: str,
        actor_id: int | None,
        before: object,
        after: object,
        role_ids: tuple[int, ...],
        authorization_version: int,
        correlation_id: str,
        now: int,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO member_identity_events(
                guild_id, member_id, discord_id, event_type, source, actor_id,
                correlation_id, before_json, after_json, role_ids_json,
                authorization_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                member_id,
                discord_id,
                event_type,
                source,
                actor_id,
                correlation_id,
                _json(before),
                _json(after),
                _json(role_ids),
                authorization_version,
                now,
            ),
        )

    async def _sync_from_discord_unlocked(
        self,
        guild_id: int,
        discord_id: int,
        role_ids: set[int],
        current_nickname: str | None,
        *,
        source: str,
        actor_id: int | None,
        correlation_id: str,
    ) -> RankSyncResult:
        missing_policy = str(
            await self.settings.get(guild_id, "missing_rank_role_policy", "KEEP_LAST")
        ).upper()
        now = self.clock()
        async with self.database.transaction() as connection:
            await self._ensure_access_profiles(connection, guild_id, now)
            member = await self._member_row(connection, guild_id, discord_id)
            if not member:
                return RankSyncResult(
                    False,
                    discord_id,
                    source,
                    correlation_id=correlation_id,
                )

            current_positions = await self._current_positions(connection, int(member["id"]))
            current_access_profiles = await self._current_access_profiles(
                connection, int(member["id"])
            )
            desired = await self._resolve_desired_identity(
                connection, member, role_ids, missing_policy=missing_policy
            )
            before = self._snapshot(
                member,
                current_positions,
                access_profiles=current_access_profiles,
            )
            after = self._snapshot(
                member,
                desired.positions,
                desired=desired,
                discord_roles_synced_at=now,
            )
            old_rank_id = before["rank_id"]
            old_rank_level = (
                int(member["current_rank_level"])
                if member["current_rank_level"] is not None
                else None
            )
            old_rank_status = str(member["rank_sync_status"])
            old_positions_by_id = {position.id: position for position in current_positions}
            new_positions_by_id = {position.id: position for position in desired.positions}
            old_position_signature = {
                (position.id, position.source_role_id, position.is_primary)
                for position in current_positions
            }
            new_position_signature = {
                (position.id, position.source_role_id, position.is_primary)
                for position in desired.positions
            }
            old_access_signature = {
                (profile.id, profile.source_mapping_id, profile.source_role_id)
                for profile in current_access_profiles
            }
            new_access_signature = {
                (profile.id, profile.source_mapping_id, profile.source_role_id)
                for profile in desired.access_profiles
            }
            rank_changed = old_rank_id != desired.rank_id
            positions_changed = old_position_signature != new_position_signature
            primary_changed = before["primary_position_id"] != desired.primary_position_id
            access_changed = (
                before["access_profile_id"] != desired.access_profile_id
                or old_access_signature != new_access_signature
            )
            authorization_changed = any(
                (
                    rank_changed,
                    positions_changed,
                    access_changed,
                    before["discord_roles_hash"] != desired.discord_roles_hash,
                    not bool(before["discord_present"]),
                    before["identity_sync_status"] != "SYNCED",
                )
            )
            authorization_version = int(member["authorization_version"] or 1) + int(
                authorization_changed
            )
            rank_event_created = rank_changed or old_rank_status != desired.rank_sync_status
            db_changed = authorization_changed or rank_event_created

            await connection.execute(
                """
                UPDATE members
                SET rank_id=?, rank_sync_status=?, rank_sync_checked_at=?,
                    primary_position_id=?, access_profile_id=?,
                    discord_roles_synced_at=?, authorization_version=?,
                    identity_sync_status='SYNCED', identity_sync_error=NULL,
                    discord_roles_hash=?, discord_present=1, updated_at=?
                WHERE id=?
                """,
                (
                    desired.rank_id,
                    desired.rank_sync_status,
                    now,
                    desired.primary_position_id,
                    desired.access_profile_id,
                    now,
                    authorization_version,
                    desired.discord_roles_hash,
                    now,
                    member["id"],
                ),
            )

            # Reset the old primary first so the partial unique index cannot be
            # violated while switching to a new primary position.
            await connection.execute(
                """
                UPDATE member_positions
                SET is_primary=0, last_seen_at=?
                WHERE member_id=?
                """,
                (now, member["id"]),
            )
            if new_positions_by_id:
                placeholders = ",".join("?" for _ in new_positions_by_id)
                await connection.execute(
                    f"""
                    DELETE FROM member_positions
                    WHERE member_id=? AND position_id NOT IN ({placeholders})
                    """,
                    (member["id"], *sorted(new_positions_by_id)),
                )
            else:
                await connection.execute(
                    "DELETE FROM member_positions WHERE member_id=?", (member["id"],)
                )
            for position in desired.positions:
                await connection.execute(
                    """
                    INSERT INTO member_positions(
                        member_id, position_id, source_role_id, is_primary,
                        assigned_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(member_id, position_id) DO UPDATE SET
                        source_role_id=excluded.source_role_id,
                        is_primary=excluded.is_primary,
                        last_seen_at=excluded.last_seen_at
                    """,
                    (
                        member["id"],
                        position.id,
                        position.source_role_id,
                        int(position.is_primary),
                        now,
                        now,
                    ),
                )

            desired_mapping_ids = {
                profile.source_mapping_id for profile in desired.access_profiles
            }
            if desired_mapping_ids:
                placeholders = ",".join("?" for _ in desired_mapping_ids)
                await connection.execute(
                    f"""
                    DELETE FROM member_access_profiles
                    WHERE member_id=? AND source_mapping_id NOT IN ({placeholders})
                    """,
                    (member["id"], *sorted(desired_mapping_ids)),
                )
            else:
                await connection.execute(
                    "DELETE FROM member_access_profiles WHERE member_id=?",
                    (member["id"],),
                )
            for profile in desired.access_profiles:
                await connection.execute(
                    """
                    INSERT INTO member_access_profiles(
                        member_id, access_profile_id, source_mapping_id,
                        source_role_id, assigned_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(member_id, source_mapping_id) DO UPDATE SET
                        access_profile_id=excluded.access_profile_id,
                        source_role_id=excluded.source_role_id,
                        last_seen_at=excluded.last_seen_at
                    """,
                    (
                        member["id"],
                        profile.id,
                        profile.source_mapping_id,
                        profile.source_role_id,
                        now,
                        now,
                    ),
                )

            if rank_event_created:
                if rank_changed:
                    if old_rank_level is not None and desired.rank_level is not None:
                        rank_event_type = (
                            "PROMOTION" if desired.rank_level > old_rank_level else "DEMOTION"
                        )
                    else:
                        rank_event_type = "SYNC"
                elif desired.rank_sync_status == "MULTIPLE_RANKS":
                    rank_event_type = "INCONSISTENCY"
                elif desired.rank_sync_status == "MISSING_ROLE":
                    rank_event_type = "MISSING_ROLE"
                else:
                    rank_event_type = "SYNC"
                await connection.execute(
                    """
                    INSERT INTO rank_sync_events(
                        guild_id, member_id, discord_id, event_type, source,
                        from_rank_id, to_rank_id, actor_id, correlation_id, role_ids_json,
                        previous_nickname, expected_nickname, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        member["id"],
                        discord_id,
                        rank_event_type,
                        source,
                        old_rank_id,
                        desired.rank_id,
                        actor_id,
                        correlation_id,
                        _json(desired.matched_rank_role_ids),
                        current_nickname,
                        desired.expected_nickname,
                        now,
                    ),
                )
                action = {
                    "MULTIPLE_RANKS": "RANK_ROLE_INCONSISTENCY",
                    "MISSING_ROLE": "RANK_ROLE_MISSING",
                }.get(desired.rank_sync_status, "RANK_SYNCED_FROM_DISCORD")
                await self._record_correlated_audit(
                    guild_id,
                    action,
                    correlation_id=correlation_id,
                    suffix=f"{action.lower()}-{discord_id}",
                    actor_id=actor_id,
                    target_id=discord_id,
                    before={"rank_id": old_rank_id, "sync_status": old_rank_status},
                    after={
                        "rank_id": desired.rank_id,
                        "rank_name": desired.rank_name,
                        "sync_status": desired.rank_sync_status,
                        "role_ids": desired.matched_rank_role_ids,
                        "source": source,
                    },
                    reason="Sincronização automática de patente pelo estado final dos cargos",
                    connection=connection,
                )

            identity_events = 0
            if rank_changed:
                await self._insert_identity_event(
                    connection,
                    guild_id=guild_id,
                    member_id=int(member["id"]),
                    discord_id=discord_id,
                    event_type="RANK_CHANGED",
                    source=source,
                    actor_id=actor_id,
                    before={"rank_id": old_rank_id, "rank_name": before["rank_name"]},
                    after={"rank_id": desired.rank_id, "rank_name": desired.rank_name},
                    role_ids=desired.relevant_role_ids,
                    authorization_version=authorization_version,
                    correlation_id=correlation_id,
                    now=now,
                )
                identity_events += 1
            if primary_changed:
                old_primary = old_positions_by_id.get(
                    int(before["primary_position_id"])
                    if before["primary_position_id"] is not None
                    else -1
                )
                new_primary = new_positions_by_id.get(desired.primary_position_id or -1)
                await self._insert_identity_event(
                    connection,
                    guild_id=guild_id,
                    member_id=int(member["id"]),
                    discord_id=discord_id,
                    event_type="POSITION_CHANGED",
                    source=source,
                    actor_id=actor_id,
                    before=old_primary.as_dict() if old_primary else {},
                    after=new_primary.as_dict() if new_primary else {},
                    role_ids=desired.relevant_role_ids,
                    authorization_version=authorization_version,
                    correlation_id=correlation_id,
                    now=now,
                )
                identity_events += 1
            for position_id in sorted(new_positions_by_id.keys() - old_positions_by_id.keys()):
                await self._insert_identity_event(
                    connection,
                    guild_id=guild_id,
                    member_id=int(member["id"]),
                    discord_id=discord_id,
                    event_type="FUNCTION_ASSIGNED",
                    source=source,
                    actor_id=actor_id,
                    before={},
                    after=new_positions_by_id[position_id].as_dict(),
                    role_ids=desired.relevant_role_ids,
                    authorization_version=authorization_version,
                    correlation_id=correlation_id,
                    now=now,
                )
                identity_events += 1
            for position_id in sorted(old_positions_by_id.keys() - new_positions_by_id.keys()):
                await self._insert_identity_event(
                    connection,
                    guild_id=guild_id,
                    member_id=int(member["id"]),
                    discord_id=discord_id,
                    event_type="FUNCTION_REMOVED",
                    source=source,
                    actor_id=actor_id,
                    before=old_positions_by_id[position_id].as_dict(),
                    after={},
                    role_ids=desired.relevant_role_ids,
                    authorization_version=authorization_version,
                    correlation_id=correlation_id,
                    now=now,
                )
                identity_events += 1
            if access_changed:
                await self._insert_identity_event(
                    connection,
                    guild_id=guild_id,
                    member_id=int(member["id"]),
                    discord_id=discord_id,
                    event_type="ACCESS_PROFILE_CHANGED",
                    source=source,
                    actor_id=actor_id,
                    before={
                        "id": before["access_profile_id"],
                        "code": before["access_profile"],
                    },
                    after={
                        "id": desired.access_profile_id,
                        "code": desired.access_profile_code,
                    },
                    role_ids=desired.relevant_role_ids,
                    authorization_version=authorization_version,
                    correlation_id=correlation_id,
                    now=now,
                )
                identity_events += 1
            if authorization_changed and identity_events == 0:
                await self._insert_identity_event(
                    connection,
                    guild_id=guild_id,
                    member_id=int(member["id"]),
                    discord_id=discord_id,
                    event_type="IDENTITY_RECONCILED",
                    source=source,
                    actor_id=actor_id,
                    before=before,
                    after={**after, "authorization_version": authorization_version},
                    role_ids=desired.relevant_role_ids,
                    authorization_version=authorization_version,
                    correlation_id=correlation_id,
                    now=now,
                )
                identity_events += 1
            if authorization_changed:
                await self._record_correlated_audit(
                    guild_id,
                    "MEMBER_IDENTITY_RECONCILED",
                    correlation_id=correlation_id,
                    suffix=f"member-identity-reconciled-{discord_id}",
                    actor_id=actor_id,
                    target_id=discord_id,
                    before=before,
                    after={**after, "authorization_version": authorization_version},
                    reason=f"Projeção funcional dos cargos Discord ({source})",
                    connection=connection,
                )

        primary = next((position for position in desired.positions if position.is_primary), None)
        return RankSyncResult(
            True,
            discord_id,
            source,
            db_changed=db_changed,
            event_created=rank_event_created or identity_events > 0,
            rank_id=desired.rank_id,
            rank_name=desired.rank_name,
            rank_role_id=desired.rank_role_id,
            expected_nickname=desired.expected_nickname,
            sync_status=desired.rank_sync_status,
            matched_role_ids=desired.matched_rank_role_ids,
            primary_position_id=desired.primary_position_id,
            primary_position_code=primary.code if primary else None,
            primary_position_name=primary.name if primary else None,
            position_codes=tuple(position.code for position in desired.positions),
            functions=tuple(
                position.code for position in desired.positions if not position.is_primary
            ),
            access_profile_id=desired.access_profile_id,
            access_profile=desired.access_profile_code,
            access_profile_name=desired.access_profile_name,
            authorization_version=authorization_version,
            identity_sync_status="SYNCED",
            discord_roles_synced_at=now,
            discord_present=True,
            relevant_role_ids=desired.relevant_role_ids,
            correlation_id=correlation_id,
        )

    async def mark_discord_absent(
        self,
        guild_id: int,
        discord_id: int,
        *,
        source: str,
        actor_id: int | None = None,
        error: str | None = None,
        correlation_id: str | None = None,
    ) -> RankSyncResult:
        """Revoke projected access when a registered member left the guild."""
        operation_correlation_id = _operation_correlation_id(correlation_id)
        async with self._member_lock(guild_id, discord_id):
            now = self.clock()
            async with self.database.transaction() as connection:
                await self._ensure_access_profiles(connection, guild_id, now)
                member = await self._member_row(connection, guild_id, discord_id)
                if not member:
                    return RankSyncResult(
                        False,
                        discord_id,
                        source,
                        correlation_id=operation_correlation_id,
                    )
                current_positions = await self._current_positions(connection, int(member["id"]))
                current_access_profiles = await self._current_access_profiles(
                    connection, int(member["id"])
                )
                before = self._snapshot(
                    member,
                    current_positions,
                    access_profiles=current_access_profiles,
                )
                safe_code = "CANDIDATO" if str(member["status"]) == "PENDING" else "MEMBRO"
                cursor = await connection.execute(
                    """
                    SELECT id, code, name FROM access_profiles
                    WHERE guild_id=? AND code=? AND enabled=1
                    """,
                    (guild_id, safe_code),
                )
                safe_profile = await cursor.fetchone()
                if safe_profile is None:  # pragma: no cover - profile initialization guards this
                    raise RuntimeError("Perfil seguro indisponível")
                authorization_changed = any(
                    (
                        bool(member["discord_present"]),
                        str(member["identity_sync_status"]) != "DISCORD_ABSENT",
                        member["primary_position_id"] is not None,
                        bool(current_positions),
                        bool(current_access_profiles),
                        member["access_profile_id"] != safe_profile["id"],
                        member["discord_roles_hash"] is not None,
                    )
                )
                authorization_version = int(member["authorization_version"] or 1) + int(
                    authorization_changed
                )
                await connection.execute(
                    "DELETE FROM member_positions WHERE member_id=?", (member["id"],)
                )
                await connection.execute(
                    "DELETE FROM member_access_profiles WHERE member_id=?",
                    (member["id"],),
                )
                await connection.execute(
                    """
                    UPDATE members
                    SET primary_position_id=NULL, access_profile_id=?,
                        discord_roles_synced_at=?, authorization_version=?,
                        identity_sync_status='DISCORD_ABSENT', identity_sync_error=?,
                        discord_roles_hash=NULL, discord_present=0,
                        rank_sync_checked_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        safe_profile["id"],
                        now,
                        authorization_version,
                        (error or "Membro não encontrado na guild")[:500],
                        now,
                        now,
                        member["id"],
                    ),
                )
                identity_events = 0
                primary = next(
                    (position for position in current_positions if position.is_primary), None
                )
                if primary:
                    await self._insert_identity_event(
                        connection,
                        guild_id=guild_id,
                        member_id=int(member["id"]),
                        discord_id=discord_id,
                        event_type="POSITION_CHANGED",
                        source=source,
                        actor_id=actor_id,
                        before=primary.as_dict(),
                        after={},
                        role_ids=(),
                        authorization_version=authorization_version,
                        correlation_id=operation_correlation_id,
                        now=now,
                    )
                    identity_events += 1
                for position in current_positions:
                    await self._insert_identity_event(
                        connection,
                        guild_id=guild_id,
                        member_id=int(member["id"]),
                        discord_id=discord_id,
                        event_type="FUNCTION_REMOVED",
                        source=source,
                        actor_id=actor_id,
                        before=position.as_dict(),
                        after={},
                        role_ids=(),
                        authorization_version=authorization_version,
                        correlation_id=operation_correlation_id,
                        now=now,
                    )
                    identity_events += 1
                if before["access_profile_id"] != int(safe_profile["id"]):
                    await self._insert_identity_event(
                        connection,
                        guild_id=guild_id,
                        member_id=int(member["id"]),
                        discord_id=discord_id,
                        event_type="ACCESS_PROFILE_CHANGED",
                        source=source,
                        actor_id=actor_id,
                        before={
                            "id": before["access_profile_id"],
                            "code": before["access_profile"],
                        },
                        after={"id": int(safe_profile["id"]), "code": safe_code},
                        role_ids=(),
                        authorization_version=authorization_version,
                        correlation_id=operation_correlation_id,
                        now=now,
                    )
                    identity_events += 1
                if authorization_changed:
                    await self._insert_identity_event(
                        connection,
                        guild_id=guild_id,
                        member_id=int(member["id"]),
                        discord_id=discord_id,
                        event_type="DISCORD_MEMBER_ABSENT",
                        source=source,
                        actor_id=actor_id,
                        before=before,
                        after={
                            "primary_position_id": None,
                            "positions": [],
                            "access_profile_id": int(safe_profile["id"]),
                            "access_profile": safe_code,
                            "authorization_version": authorization_version,
                            "identity_sync_status": "DISCORD_ABSENT",
                            "discord_present": False,
                        },
                        role_ids=(),
                        authorization_version=authorization_version,
                        correlation_id=operation_correlation_id,
                        now=now,
                    )
                    identity_events += 1
                    await self._record_correlated_audit(
                        guild_id,
                        "MEMBER_DISCORD_ABSENT",
                        correlation_id=operation_correlation_id,
                        suffix=f"member-discord-absent-{discord_id}",
                        actor_id=actor_id,
                        target_id=discord_id,
                        before=before,
                        after={
                            "access_profile": safe_code,
                            "authorization_version": authorization_version,
                            "identity_sync_status": "DISCORD_ABSENT",
                            "discord_present": False,
                        },
                        reason=f"Revogação por ausência na guild ({source})",
                        connection=connection,
                    )

            current_rank_id = (
                int(member["rank_id"]) if member["rank_id"] is not None else None
            )
            canonical_rank_role_id = (
                await self.rank_role_id_for_rank(guild_id, current_rank_id)
                if current_rank_id is not None
                else None
            )
            return RankSyncResult(
                True,
                discord_id,
                source,
                db_changed=authorization_changed,
                event_created=identity_events > 0,
                rank_id=current_rank_id,
                rank_name=(
                    str(member["current_rank_name"])
                    if member["current_rank_name"] is not None
                    else None
                ),
                rank_role_id=canonical_rank_role_id,
                expected_nickname=format_member_nickname(
                    str(member["current_rank_prefix"] or ""),
                    str(member["mta_nick"]),
                    str(member["character_id"] or ""),
                ),
                sync_status=str(member["rank_sync_status"]),
                access_profile_id=int(safe_profile["id"]),
                access_profile=safe_code,
                access_profile_name=str(safe_profile["name"]),
                authorization_version=authorization_version,
                identity_sync_status="DISCORD_ABSENT",
                discord_roles_synced_at=now,
                discord_present=False,
                correlation_id=operation_correlation_id,
            )

    async def sync_from_member(
        self,
        target: discord.Member,
        *,
        source: str,
        actor_id: int | None = None,
        expected_roles_hash: str | None = None,
        correlation_id: str | None = None,
    ) -> RankSyncResult:
        guild_id = target.guild.id
        operation_correlation_id = _operation_correlation_id(correlation_id)
        async with self._member_lock(guild_id, target.id):
            role_ids = {int(role.id) for role in target.roles}
            if expected_roles_hash is not None and _role_snapshot_hash(
                role_ids, present=True
            ) != expected_roles_hash:
                raise RuntimeError(
                    "Preview obsoleto: cargos Discord mudaram antes da aplicação"
                )
            result = await self._sync_from_discord_unlocked(
                guild_id,
                target.id,
                role_ids,
                target.nick,
                source=source,
                actor_id=actor_id,
                correlation_id=operation_correlation_id,
            )
            if not result.registered:
                return result
            auto_remove = bool(
                await self.settings.get(guild_id, "auto_remove_old_rank_roles", False)
            )
            remove_ids = (
                set(result.matched_role_ids) - {result.rank_role_id}
                if auto_remove and result.rank_role_id
                else set()
            )
            outcome = await self._apply_discord_state(
                target,
                result,
                remove_role_ids=remove_ids,
                add_role_ids=set(),
                reason=f"Sincronização de identidade ({source})",
                actor_id=actor_id,
            )
            result.warning = " ".join(outcome.warnings) or None
            return result

    async def sync_to_member(
        self,
        target: discord.Member,
        *,
        source: str,
        actor_id: int | None = None,
        explicit_remove_role_ids: set[int] | None = None,
        ensure_member_role: bool = False,
        correlation_id: str | None = None,
    ) -> RankSyncResult:
        guild_id = target.guild.id
        operation_correlation_id = _operation_correlation_id(correlation_id)
        async with self._member_lock(guild_id, target.id):
            member = await self.database.fetchone(
                """
                SELECT m.*, r.name AS rank_name, r.prefix AS rank_prefix,
                       r.discord_role_id AS rank_role_id,
                       ap.code AS access_profile_code, ap.name AS access_profile_name,
                       fp.code AS primary_position_code, fp.name AS primary_position_name
                FROM members m
                LEFT JOIN ranks r ON r.id=m.rank_id
                LEFT JOIN access_profiles ap ON ap.id=m.access_profile_id
                LEFT JOIN functional_positions fp ON fp.id=m.primary_position_id
                WHERE m.guild_id=? AND m.discord_id=?
                """,
                (guild_id, target.id),
            )
            if not member:
                return RankSyncResult(
                    False,
                    target.id,
                    source,
                    correlation_id=operation_correlation_id,
                )
            rank_role_id = (
                await self.rank_role_id_for_rank(guild_id, int(member["rank_id"]))
                if member["rank_id"] is not None
                else None
            )
            nickname_prefix = await self._nickname_prefix_for_roles(
                guild_id,
                str(member["rank_prefix"] or ""),
                {int(role.id) for role in target.roles},
            )
            result = RankSyncResult(
                True,
                target.id,
                source,
                rank_id=int(member["rank_id"]) if member["rank_id"] is not None else None,
                rank_name=str(member["rank_name"]) if member["rank_name"] else None,
                rank_role_id=rank_role_id,
                expected_nickname=format_member_nickname(
                    nickname_prefix,
                    str(member["mta_nick"]),
                    str(member["character_id"] or ""),
                ),
                sync_status=str(member["rank_sync_status"]),
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
                access_profile_id=(
                    int(member["access_profile_id"])
                    if member["access_profile_id"] is not None
                    else None
                ),
                access_profile=(
                    str(member["access_profile_code"])
                    if member["access_profile_code"] is not None
                    else None
                ),
                access_profile_name=(
                    str(member["access_profile_name"])
                    if member["access_profile_name"] is not None
                    else None
                ),
                authorization_version=int(member["authorization_version"] or 1),
                identity_sync_status=str(member["identity_sync_status"]),
                discord_roles_synced_at=(
                    int(member["discord_roles_synced_at"])
                    if member["discord_roles_synced_at"] is not None
                    else None
                ),
                discord_present=bool(member["discord_present"]),
                correlation_id=operation_correlation_id,
            )
            if (
                str(member["status"]) != "DISMISSED"
                and not bool(member["original_nickname_captured"])
                and target.nick != result.expected_nickname
            ):
                async with self.database.transaction() as connection:
                    cursor = await connection.execute(
                        """
                        UPDATE members
                        SET original_discord_nickname=?, original_nickname_captured=1,
                            updated_at=?
                        WHERE id=? AND original_nickname_captured=0
                        """,
                        (target.nick, utc_now_ms(), int(member["id"])),
                    )
                    if cursor.rowcount == 1:
                        await self.audit.record(
                            guild_id,
                            "MEMBER_ORIGINAL_NICKNAME_CAPTURED",
                            actor_id=actor_id,
                            target_id=target.id,
                            before={"captured": False},
                            after={
                                "captured": True,
                                "had_guild_nickname": target.nick is not None,
                                "source": source,
                                "operation_correlation_id": operation_correlation_id,
                            },
                            correlation_id=(
                                f"{operation_correlation_id}:audit:original-nickname-{target.id}"
                            ),
                            connection=connection,
                        )
            remove_ids = set(explicit_remove_role_ids or ())
            auto_remove = bool(
                await self.settings.get(guild_id, "auto_remove_old_rank_roles", False)
            )
            if auto_remove:
                remove_ids.update(await self.rank_role_ids(guild_id))
            if rank_role_id:
                remove_ids.discard(rank_role_id)
            add_ids = {rank_role_id} if rank_role_id else set()
            if ensure_member_role:
                member_role_id = await self.settings.get(guild_id, "member_role_id")
                if member_role_id:
                    add_ids.add(int(member_role_id))
            current_ids = {int(role.id) for role in target.roles}
            intended_ids = (current_ids - remove_ids) | add_ids
            outcome = await self._apply_discord_state(
                target,
                result,
                remove_role_ids=remove_ids,
                add_role_ids=add_ids,
                reason=f"Aplicação da identidade registrada ({source})",
                actor_id=actor_id,
            )
            if outcome.role_sync_succeeded:
                # Reconcile the intended final state in the same member lock.
                # This makes registration and panel-originated changes visible
                # to bot/API/site immediately, without waiting for Gateway.
                result = await self._sync_from_discord_unlocked(
                    guild_id,
                    target.id,
                    intended_ids,
                    result.expected_nickname,
                    source=source,
                    actor_id=actor_id,
                    correlation_id=operation_correlation_id,
                )
            result.warning = " ".join(outcome.warnings) or None
            return result

    async def _apply_discord_state(
        self,
        target: discord.Member,
        result: RankSyncResult,
        *,
        remove_role_ids: set[int],
        add_role_ids: set[int],
        reason: str,
        actor_id: int | None,
    ) -> _DiscordApplyOutcome:
        warnings: list[str] = []
        role_sync_succeeded = True
        operation_correlation_id = _operation_correlation_id(result.correlation_id)
        result.correlation_id = operation_correlation_id
        current_ids = {int(role.id) for role in target.roles}
        remove_roles = [role for role in target.roles if int(role.id) in remove_role_ids]
        add_roles = [
            role
            for role_id in sorted(add_role_ids - current_ids)
            if (role := target.guild.get_role(role_id)) is not None
        ]
        missing_ids = add_role_ids - current_ids - {int(role.id) for role in add_roles}
        if missing_ids:
            role_sync_succeeded = False
            await self._record_correlated_audit(
                target.guild.id,
                "ROLE_HIERARCHY_ERROR",
                correlation_id=operation_correlation_id,
                suffix=f"role-hierarchy-missing-{target.id}",
                actor_id=actor_id,
                target_id=target.id,
                after={"missing_role_ids": sorted(missing_ids), "source": result.source},
                reason="Cargo de patente configurado não existe mais no servidor",
            )
            warnings.append("Um cargo configurado não existe mais no servidor.")
        try:
            if remove_roles:
                await target.remove_roles(*remove_roles, reason=reason)
            if add_roles:
                await target.add_roles(*add_roles, reason=reason)
        except (discord.Forbidden, discord.HTTPException) as exc:
            role_sync_succeeded = False
            await self._record_correlated_audit(
                target.guild.id,
                "ROLE_HIERARCHY_ERROR",
                correlation_id=operation_correlation_id,
                suffix=f"role-hierarchy-forbidden-{target.id}",
                actor_id=actor_id,
                target_id=target.id,
                after={
                    "add_role_ids": sorted(add_role_ids),
                    "remove_role_ids": sorted(remove_role_ids),
                    "source": result.source,
                },
                reason=str(exc)[:500],
            )
            warnings.append("O Discord bloqueou a sincronização dos cargos por hierarquia.")

        member_status = await self.database.fetchone(
            "SELECT status FROM members WHERE guild_id=? AND discord_id=?",
            (target.guild.id, target.id),
        )
        enforce_nickname = bool(
            await self.settings.get(target.guild.id, "enforce_member_nickname", True)
        ) and not (member_status and str(member_status["status"]) == "DISMISSED")
        if enforce_nickname and target.nick != result.expected_nickname:
            try:
                await target.edit(nick=result.expected_nickname, reason=reason)
            except (discord.Forbidden, discord.HTTPException) as exc:
                await self._record_correlated_audit(
                    target.guild.id,
                    "NICKNAME_PERMISSION_ERROR",
                    correlation_id=operation_correlation_id,
                    suffix=f"nickname-permission-{target.id}",
                    actor_id=actor_id,
                    target_id=target.id,
                    before={"nickname": target.nick},
                    after={"nickname": result.expected_nickname, "source": result.source},
                    reason=str(exc)[:500],
                )
                warnings.append("O Discord bloqueou a correção do apelido por hierarquia.")
        return _DiscordApplyOutcome(tuple(warnings), role_sync_succeeded)
