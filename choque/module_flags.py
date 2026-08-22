from __future__ import annotations

from .audit import AuditService
from .database import Database
from .errors import ValidationError
from .settings import MODULE_DEFAULTS, SettingsService


class ModuleFlagService:
    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit

    async def states(self, guild_id: int) -> dict[str, bool]:
        stored = await self.settings.get(guild_id, "module_flags")
        states = dict(MODULE_DEFAULTS)
        if isinstance(stored, dict):
            states.update(
                {key: bool(value) for key, value in stored.items() if key in MODULE_DEFAULTS}
            )
        return states

    async def is_enabled(self, guild_id: int, module: str) -> bool:
        normalized = module.upper()
        if normalized not in MODULE_DEFAULTS:
            raise ValidationError(f"Módulo desconhecido: {module}.")
        return (await self.states(guild_id))[normalized]

    async def require_enabled(self, guild_id: int, module: str) -> None:
        if not await self.is_enabled(guild_id, module):
            raise ValidationError("Este módulo está temporariamente desativado pela Administração.")
        maintenance = await self.database.fetchone(
            """
            SELECT reason, expected_end_at FROM module_maintenance
            WHERE guild_id=? AND module_key=? AND active=1
            """,
            (guild_id, module.upper()),
        )
        if maintenance:
            message = "Este módulo está em manutenção"
            if maintenance["reason"]:
                message += f": {maintenance['reason']}"
            raise ValidationError(message + ".")

    async def set_enabled(
        self,
        guild_id: int,
        module: str,
        enabled: bool,
        actor_id: int,
    ) -> dict[str, bool]:
        normalized = module.upper()
        if normalized not in MODULE_DEFAULTS:
            raise ValidationError(f"Módulo desconhecido: {module}.")
        before = await self.states(guild_id)
        if before[normalized] == enabled:
            return before
        after = dict(before)
        after[normalized] = enabled
        async with self.database.transaction() as connection:
            await self.settings.set(guild_id, "module_flags", after, actor_id, connection)
            await self.audit.record(
                guild_id,
                "MODULE_ENABLED" if enabled else "MODULE_DISABLED",
                actor_id=actor_id,
                before={"module": normalized, "enabled": before[normalized]},
                after={"module": normalized, "enabled": enabled},
                connection=connection,
            )
        return after
