from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar

from .database import Database
from .errors import ValidationError

FEATURE_FLAG = "recruitment_courses_dc2_cutover_enabled"
SOURCE_GUILD_SETTING = "recruitment_courses_dc2_source_guild_id"
TARGET_GUILD_SETTING = "recruitment_courses_dc2_target_guild_id"
MAINTENANCE_LOCK_SETTING = "recruitment_courses_dc2_maintenance_lock"
ACTIVE_MAINTENANCE_STATES = frozenset({"PREPARING", "ARCHIVING", "RESTORING"})


@dataclass(frozen=True, slots=True)
class SourceCutoverState:
    active: bool
    source_guild_id: int
    target_guild_id: int | None
    reason: str


async def _setting(database: Database, guild_id: int, key: str, default: Any = None) -> Any:
    row = await database.fetchone(
        "SELECT value_json FROM guild_settings WHERE guild_id=? AND setting_key=?",
        (guild_id, key),
    )
    return json.loads(row["value_json"]) if row else default


def _snowflake(value: Any) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


async def validated_source_cutover(
    database: Database, guild_id: int
) -> SourceCutoverState:
    """Resolve only an explicitly linked source-to-DC2 cutover."""

    enabled = bool(await _setting(database, guild_id, FEATURE_FLAG, False))
    source_guild_id = _snowflake(await _setting(database, guild_id, SOURCE_GUILD_SETTING))
    target_guild_id = _snowflake(await _setting(database, guild_id, TARGET_GUILD_SETTING))
    if not enabled:
        return SourceCutoverState(False, guild_id, target_guild_id, "flag_disabled")
    if source_guild_id != guild_id:
        return SourceCutoverState(False, guild_id, target_guild_id, "guild_is_not_source")
    if target_guild_id is None or target_guild_id == guild_id:
        return SourceCutoverState(False, guild_id, target_guild_id, "invalid_target")
    target_source = _snowflake(
        await _setting(database, target_guild_id, "identity_source_guild_id")
    )
    if target_source != guild_id:
        return SourceCutoverState(False, guild_id, target_guild_id, "target_not_linked")
    return SourceCutoverState(True, guild_id, target_guild_id, "validated")


async def source_cutover_maintenance_target(
    database: Database, guild_id: int
) -> int | None:
    lock = await _setting(database, guild_id, MAINTENANCE_LOCK_SETTING, {})
    if not isinstance(lock, dict) or str(lock.get("state")) not in ACTIVE_MAINTENANCE_STATES:
        return None
    source_guild_id = _snowflake(lock.get("source_guild_id"))
    target_guild_id = _snowflake(lock.get("target_guild_id"))
    if source_guild_id != guild_id or target_guild_id in {None, guild_id}:
        return None
    target_source = _snowflake(
        await _setting(database, int(target_guild_id), "identity_source_guild_id")
    )
    return target_guild_id if target_source == guild_id else None


async def source_cutover_is_read_only(database: Database, guild_id: int) -> bool:
    """Return whether the source must stay quiet during or after cutover."""

    if await source_cutover_maintenance_target(database, guild_id) is not None:
        return True
    return (await validated_source_cutover(database, guild_id)).active


async def require_source_cutover_writable(
    database: Database, guild_id: int, area: str
) -> None:
    maintenance_target = await source_cutover_maintenance_target(database, guild_id)
    state = await validated_source_cutover(database, guild_id)
    target_guild_id = maintenance_target or (state.target_guild_id if state.active else None)
    if target_guild_id is None:
        return
    raise ValidationError(
        f"{area} foi migrado para o DC2 (servidor {target_guild_id}). "
        "Use os painéis do DC2; o histórico desta origem permanece somente para consulta."
    )


F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def block_source_cutover_writes(area: str) -> Callable[[F], F]:
    """Guard a service mutator whose first argument after self is guild_id."""

    def decorator(method: F) -> F:
        @wraps(method)
        async def guarded(self: Any, guild_id: int, *args: Any, **kwargs: Any) -> Any:
            await require_source_cutover_writable(self.database, int(guild_id), area)
            return await method(self, guild_id, *args, **kwargs)

        return guarded  # type: ignore[return-value]

    return decorator
