from __future__ import annotations

from types import SimpleNamespace

import pytest

from choque.config import AppConfig, Branding
from scripts.publish_financial_update import (
    MESSAGE_MARKER,
    PANEL_TYPE,
    build_financial_update_embed,
    resolve_updates_channel_id,
)


def test_financial_release_uses_a_unique_persistent_marker_and_no_mentions() -> None:
    config = AppConfig(
        token="test",
        database_path=SimpleNamespace(),
        legacy_database_path=SimpleNamespace(),
        default_guild_id=123,
        log_level="INFO",
        branding=Branding(),
    )
    embed = build_financial_update_embed(config)
    payload = embed.to_dict()
    text = " ".join(str(field["value"]) for field in payload["fields"])

    assert PANEL_TYPE == "SYSTEM_UPDATE_FINANCIAL_AID_V1"
    assert payload["footer"]["text"] == MESSAGE_MARKER
    assert "voluntário" in payload["description"]
    assert "não concede cargo funcional" in payload["description"]
    assert "exclusivamente humana" in text
    assert "honraria visual sem permissões" in text
    assert "apoios anônimos continuam anônimos" in text
    assert "@everyone" not in str(payload)


def test_updates_channel_is_resolved_only_from_the_canonical_registry() -> None:
    registry = {"channels": {"info.updates": "123456789012345678"}}

    assert resolve_updates_channel_id(registry) == 123456789012345678
    with pytest.raises(RuntimeError, match="registro canônico"):
        resolve_updates_channel_id({"channels": {}})
    with pytest.raises(RuntimeError, match="layout Discord"):
        resolve_updates_channel_id(None)
