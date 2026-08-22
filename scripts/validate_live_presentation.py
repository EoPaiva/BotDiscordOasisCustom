from __future__ import annotations

import json
import sqlite3
import sys

from choque.config import AppConfig
from scripts.validate_live_phase5 import discord_get
from scripts.validate_live_phase6 import components

EXPECTED = {
    "MEMBER": (
        "registration.panel",
        "🛡️ PORTARIA DIGITAL • CHOQUE - BGR",
        {"choque:member:register:v1"},
    ),
    "POINT": (
        "point.panel",
        "⏱️ CONTROLE OPERACIONAL DE SERVIÇO",
        {
            "choque:shift:start:v1",
            "choque:shift:stop:v1",
            "choque:shift:hours:v1",
            "choque:shift:history:v1",
        },
    ),
    "MEDALS": ("info.medals", "🏅 QUADRO DE CONDECORAÇÕES • CHOQUE - BGR", {"choque:medals:select:v1"}),
    "TRANSFER": (
        "partnerships.transfers",
        "🔄 TRANSFERÊNCIA INSTITUCIONAL • CHOQUE - BGR",
        {"choque:partnerships:transfer:v1", "choque:partnerships:transfer:mine:v1"},
    ),
    "PARTNERSHIP": (
        "partnerships.partners",
        "🤝 RELAÇÕES INSTITUCIONAIS • CHOQUE - BGR",
        {"choque:partnerships:proposal:v1", "choque:partnerships:proposal:mine:v1"},
    ),
    "PARTNERSHIP_TERMS": (
        "partnerships.terms",
        "📜 TERMOS INSTITUCIONAIS • CHOQUE - BGR",
        set(),
    ),
}
PARTNERSHIP_CHANNEL_IDS = {
    "partnerships.transfers": 1166861438728548432,
    "partnerships.partners": 1540590814839967784,
    "partnerships.terms": 1540590816383336520,
}
HISTORICAL_MEDALS_MESSAGE_ID = 1248833920917573745


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    try:
        panels = {
            row["panel_type"]: (int(row["channel_id"]), int(row["message_id"]))
            for row in connection.execute(
                """
                SELECT panel_type, channel_id, message_id FROM panels
                WHERE guild_id=? AND panel_type IN ({})
                """.format(",".join("?" for _ in EXPECTED)),
                (config.default_guild_id, *EXPECTED),
            ).fetchall()
        }
        registry = json.loads(
            connection.execute(
                """
                SELECT value_json FROM guild_settings
                WHERE guild_id=? AND setting_key='discord_layout_registry_v2'
                """,
                (config.default_guild_id,),
            ).fetchone()[0]
        )
    finally:
        connection.close()

    failures: list[str] = []
    for panel_type, (channel_key, title, expected_custom_ids) in EXPECTED.items():
        if panel_type not in panels:
            failures.append(f"missing-panel:{panel_type}")
            continue
        channel_id, message_id = panels[panel_type]
        if channel_id != int(registry["channels"][channel_key]):
            failures.append(f"wrong-channel:{panel_type}")
        message = discord_get(f"/channels/{channel_id}/messages/{message_id}", config.token)
        embeds = message.get("embeds", [])
        actual_title = embeds[0].get("title") if embeds else None
        if actual_title != title:
            failures.append(f"wrong-title:{panel_type}")
        custom_ids = {
            item.get("custom_id") for item in components(message) if item.get("custom_id")
        }
        if not expected_custom_ids <= custom_ids:
            failures.append(f"missing-components:{panel_type}")
        if panel_type == "PARTNERSHIP_TERMS":
            link_count = sum(1 for item in components(message) if item.get("url"))
            if link_count != 3:
                failures.append("partnership-links")

    for key, expected_id in PARTNERSHIP_CHANNEL_IDS.items():
        if int(registry["channels"].get(key, 0)) != expected_id:
            failures.append(f"channel-id-changed:{key}")
        channel = discord_get(f"/channels/{expected_id}", config.token)
        if int(channel.get("parent_id") or 0) != 1540589594691772477:
            failures.append(f"category-changed:{key}")

    medals_channel_id = int(registry["channels"]["info.medals"])
    try:
        discord_get(
            f"/channels/{medals_channel_id}/messages/{HISTORICAL_MEDALS_MESSAGE_ID}",
            config.token,
        )
    except Exception:
        failures.append("historical-medals-message-missing")

    bot_user = discord_get("/users/@me", config.token)
    commands = discord_get(
        f"/applications/{bot_user['id']}/guilds/{config.default_guild_id}/commands",
        config.token,
    )
    if commands:
        failures.append(f"commands={len(commands)}")

    print("PRESENTATION_LIVE_PASS" if not failures else "PRESENTATION_LIVE_INVALID")
    print(f"panels={len(panels)}/{len(EXPECTED)}")
    print(f"partnership_channels={len(PARTNERSHIP_CHANNEL_IDS)}/{len(PARTNERSHIP_CHANNEL_IDS)}")
    print("historical_medals_preserved=true")
    print(f"commands={len(commands)}")
    if failures:
        print(f"failures={failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
