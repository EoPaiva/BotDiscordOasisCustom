from __future__ import annotations

import pytest

from choque.channel_names import (
    CHANNEL_EMOJI_SEPARATOR,
    CHANNEL_SEPARATOR,
    CHANNEL_SEPARATOR_FALLBACK,
    DISCORD_INVISIBLE_SPACE,
    DISCORD_INVISIBLE_SPACE_FALLBACK,
    format_category_name,
    format_channel_name,
    format_legacy_italic_channel_name,
    format_small_caps_channel_name,
    normalize_channel_label,
)
from scripts.remodel_discord_layout import CATEGORY_SPECS, CHANNEL_SPECS


def test_small_caps_pilot_uses_visible_hyphens_between_words() -> None:
    assert (
        format_small_caps_channel_name("Avisos do comando", "📢")
        == "📢・ᴀᴠɪꜱᴏꜱ-ᴅᴏ-ᴄᴏᴍᴀɴᴅᴏ"
    )
    assert format_small_caps_channel_name("TRANSFERÊNCIA") == "ᴛʀᴀɴꜱꜰᴇʀᴇɴᴄɪᴀ"


def test_legacy_italic_formatter_remains_available_for_rollback() -> None:
    result = format_legacy_italic_channel_name("GESTÃO-DO-EFETIVO", "👥")

    assert result == f"👥・𝐺𝑒𝑠𝑡𝑎𝑜{CHANNEL_SEPARATOR}𝑑𝑜{CHANNEL_SEPARATOR}𝑒𝑓𝑒𝑡𝑖𝑣𝑜"
    assert " " not in result
    assert "-" not in result
    assert "│" not in result
    assert result.startswith(f"👥{CHANNEL_EMOJI_SEPARATOR}")
    assert CHANNEL_SEPARATOR == DISCORD_INVISIBLE_SPACE
    assert CHANNEL_SEPARATOR_FALLBACK == DISCORD_INVISIBLE_SPACE_FALLBACK
    assert ord(CHANNEL_SEPARATOR) == 0x3164
    assert ord(CHANNEL_SEPARATOR_FALLBACK) == 0x2800
    assert all(character not in result for character in (" ", "·", "•"))
    assert CHANNEL_EMOJI_SEPARATOR not in result.removeprefix("👥・")
    assert "□" not in result


def test_normalization_removes_accents_underscores_and_repeated_spaces() -> None:
    assert normalize_channel_label("  CENTRAL__DO--MEMBRO  ") == "Central do membro"
    assert format_channel_name("controle de serviço") == "ᴄᴏɴᴛʀᴏʟᴇ-ᴅᴇ-ꜱᴇʀᴠɪᴄᴏ"


def test_invisible_separator_is_generated_by_the_required_codepoint() -> None:
    direct_test = f"A{chr(0x3164)}B"
    assert ord(direct_test[1]) == 0x3164

    result = format_legacy_italic_channel_name("Avisos do comando", "📢")
    name = result.split(CHANNEL_EMOJI_SEPARATOR, 1)[1]
    separators = [character for character in name if character == CHANNEL_SEPARATOR]
    assert len(separators) == 2
    assert {ord(character) for character in separators} == {0x3164}
    assert not any(ord(character) in {0x0020, 0x00B7, 0x2022, 0x30FB} for character in name)


def test_category_name_keeps_monospaced_identity() -> None:
    assert format_category_name(7, "Informações") == "𝟶𝟽・𝙸𝙽𝙵𝙾𝚁𝙼𝙰𝙲𝙾𝙴𝚂"


def test_empty_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        format_channel_name(" --__ ")


def test_phase12_layout_has_stable_unique_identifiers() -> None:
    category_keys = [spec.key for spec in CATEGORY_SPECS]
    channel_keys = [spec.key for spec in CHANNEL_SPECS]
    known_ids = [spec.known_id for spec in CHANNEL_SPECS if spec.known_id]

    assert len(category_keys) == len(set(category_keys)) == 19
    assert len(channel_keys) == len(set(channel_keys))
    assert len(known_ids) == len(set(known_ids))
    assert all(spec.category in set(category_keys) for spec in CHANNEL_SPECS)
    assert all("·" not in spec.visual_name and "•" not in spec.visual_name for spec in CHANNEL_SPECS)
    assert all("│" not in spec.visual_name for spec in CHANNEL_SPECS)
