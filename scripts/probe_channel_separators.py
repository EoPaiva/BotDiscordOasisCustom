from __future__ import annotations

import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from choque.config import AppConfig
from scripts.validate_live_phase5 import API_BASE

CANDIDATES = (
    ("HANGUL_FILLER", "\u3164"),
    ("HANGUL_FILLER_VS16", "\u3164\ufe0f"),
    ("HANGUL_FILLER_CGJ", "\u3164\u034f"),
    ("CGJ_HANGUL_FILLER", "\u034f\u3164"),
    ("HANGUL_FILLER_WORD_JOINER", "\u3164\u2060"),
    ("WORD_JOINER_HANGUL_FILLER", "\u2060\u3164"),
    ("HANGUL_FILLER_ZWJ", "\u3164\u200d"),
    ("ZWJ_HANGUL_FILLER", "\u200d\u3164"),
    ("HANGUL_FILLER_ZWNJ", "\u3164\u200c"),
    ("ZWNJ_HANGUL_FILLER", "\u200c\u3164"),
    ("BRAILLE_BLANK", "\u2800"),
    ("KHMER_VOWEL", "\u17b5"),
    ("HANGUL_CHOSEONG_FILLER", "\u115f"),
    ("HANGUL_JUNGSEONG_FILLER", "\u1160"),
    ("HALFWIDTH_HANGUL_FILLER", "\uffa0"),
    ("ZERO_WIDTH_SPACE", "\u200b"),
    ("INVISIBLE_SEPARATOR", "\u2063"),
    ("KATAKANA_MIDDLE_DOT", "・"),
    ("MIDDLE_DOT", "·"),
)


def discord_request(
    method: str,
    path: str,
    token: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "CHOQUE-BGR-QA/1.0",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - Discord API fixa
            body = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API {exc.code}: {detail[:300]}") from exc
    return json.loads(body) if body else {}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")

    import sqlite3

    connection = sqlite3.connect(config.database_path)
    try:
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
    archive_id = int(registry["categories"]["archive"])

    print("CHANNEL_SEPARATOR_PROBE")
    for label, separator in CANDIDATES:
        expected = f"🧪・𝐶ℎ𝑎𝑡{separator}𝑠𝑢𝑝𝑒𝑟𝑖𝑜𝑟𝑒𝑠"
        created = discord_request(
            "POST",
            f"/guilds/{config.default_guild_id}/channels",
            config.token,
            {
                "name": expected,
                "type": 0,
                "parent_id": archive_id,
                "permission_overwrites": [
                    {
                        "id": str(config.default_guild_id),
                        "type": 0,
                        "allow": "0",
                        "deny": str(1 << 10),
                    }
                ],
            },
        )
        try:
            actual = str(created["name"])
            print(
                f"{label}={' '.join(f'U+{ord(character):04X}' for character in separator)} "
                f"preserved={actual == expected} contains_3164={chr(0x3164) in actual} "
                f"hyphen={'-' in actual} length={len(actual)} repr={actual!r}"
            )
        finally:
            discord_request("DELETE", f"/channels/{created['id']}", config.token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
