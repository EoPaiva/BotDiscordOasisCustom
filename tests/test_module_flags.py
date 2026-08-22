from __future__ import annotations

import pytest

from choque.errors import ValidationError
from choque.settings import MODULE_DEFAULTS

from .conftest import DISCORD_ID, GUILD_ID


@pytest.mark.asyncio
async def test_modules_are_enabled_by_default(service_bundle):
    modules = service_bundle["modules"]

    assert await modules.states(GUILD_ID) == MODULE_DEFAULTS
    assert await modules.is_enabled(GUILD_ID, "point") is True
    await modules.require_enabled(GUILD_ID, "POINT")


@pytest.mark.asyncio
async def test_module_toggle_is_persisted_audited_and_enforced(service_bundle):
    modules = service_bundle["modules"]
    settings = service_bundle["settings"]
    database = service_bundle["database"]

    disabled = await modules.set_enabled(GUILD_ID, "POINT", False, DISCORD_ID)
    assert disabled["POINT"] is False
    assert (await settings.get(GUILD_ID, "module_flags"))["POINT"] is False
    assert await modules.is_enabled(GUILD_ID, "POINT") is False
    with pytest.raises(ValidationError, match="temporariamente desativado"):
        await modules.require_enabled(GUILD_ID, "POINT")

    same = await modules.set_enabled(GUILD_ID, "POINT", False, DISCORD_ID)
    assert same["POINT"] is False
    disabled_audits = await database.fetchone(
        "SELECT COUNT(*) AS total FROM audit_logs WHERE action='MODULE_DISABLED'"
    )
    assert disabled_audits["total"] == 1

    enabled = await modules.set_enabled(GUILD_ID, "point", True, DISCORD_ID)
    assert enabled["POINT"] is True
    enabled_audits = await database.fetchone(
        "SELECT COUNT(*) AS total FROM audit_logs WHERE action='MODULE_ENABLED'"
    )
    assert enabled_audits["total"] == 1


@pytest.mark.asyncio
async def test_module_registry_rejects_unknown_keys(service_bundle):
    modules = service_bundle["modules"]

    with pytest.raises(ValidationError, match="Módulo desconhecido"):
        await modules.is_enabled(GUILD_ID, "UNKNOWN")
    with pytest.raises(ValidationError, match="Módulo desconhecido"):
        await modules.set_enabled(GUILD_ID, "UNKNOWN", False, DISCORD_ID)
