from __future__ import annotations

import re
import unicodedata

CHANNEL_EMOJI_SEPARATOR = "・"
# Nunca copie o glifo invisível de documentação/chat: ele é sempre gerado pelo codepoint.
DISCORD_INVISIBLE_SPACE = chr(0x3164)
DISCORD_INVISIBLE_SPACE_FALLBACK = chr(0x2800)
CHANNEL_SEPARATOR = DISCORD_INVISIBLE_SPACE
CHANNEL_SEPARATOR_FALLBACK = DISCORD_INVISIBLE_SPACE_FALLBACK
SMALL_CAPS_WORD_SEPARATOR = "-"

_ITALIC_UPPER = {chr(ord("A") + index): chr(0x1D434 + index) for index in range(26)}
_ITALIC_LOWER = {chr(ord("a") + index): chr(0x1D44E + index) for index in range(26)}
_ITALIC_LOWER["h"] = "ℎ"
_ITALIC_LOWER["i"] = "𝑖"
_ITALIC_LOWER["j"] = "𝑗"
_ITALIC_TRANSLATION = str.maketrans({**_ITALIC_UPPER, **_ITALIC_LOWER})

_MONOSPACE_TRANSLATION = str.maketrans(
    {
        **{chr(ord("A") + index): chr(0x1D670 + index) for index in range(26)},
        **{chr(ord("a") + index): chr(0x1D68A + index) for index in range(26)},
        **{chr(ord("0") + index): chr(0x1D7F6 + index) for index in range(10)},
    }
)

_SMALL_CAPS_GLYPHS = {
    "a": "ᴀ",
    "b": "ʙ",
    "c": "ᴄ",
    "d": "ᴅ",
    "e": "ᴇ",
    "f": "ꜰ",
    "g": "ɢ",
    "h": "ʜ",
    "i": "ɪ",
    "j": "ᴊ",
    "k": "ᴋ",
    "l": "ʟ",
    "m": "ᴍ",
    "n": "ɴ",
    "o": "ᴏ",
    "p": "ᴘ",
    "q": "ꞯ",
    "r": "ʀ",
    "s": "ꜱ",
    "t": "ᴛ",
    "u": "ᴜ",
    "v": "ᴠ",
    "w": "ᴡ",
    "x": "x",
    "y": "ʏ",
    "z": "ᴢ",
}
_SMALL_CAPS_TRANSLATION = str.maketrans(
    {
        **_SMALL_CAPS_GLYPHS,
        **{key.upper(): value for key, value in _SMALL_CAPS_GLYPHS.items()},
    }
)
_SMALL_CAPS_ASCII_TRANSLATION = str.maketrans(
    {
        **{value: key for key, value in _SMALL_CAPS_GLYPHS.items()},
        "ғ": "f",
    }
)


def normalize_channel_label(value: str) -> str:
    """Normaliza um rótulo humano antes de aplicar a identidade visual."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    words = re.sub(r"[-_|]+", " ", without_accents)
    words = re.sub(r"\s+", " ", words).strip().lower()
    return words[:1].upper() + words[1:] if words else ""


def normalize_stylized_label(value: str) -> str:
    """Normaliza texto humano ou Small Caps para uma chave sem acentos."""

    decoded = value.casefold().translate(_SMALL_CAPS_ASCII_TRANSLATION)
    decomposed = unicodedata.normalize("NFKD", decoded)
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    words = re.sub(r"[^a-z0-9]+", " ", without_accents)
    words = re.sub(r"\b(\d+)o\b", r"\1", words)
    return " ".join(words.split())


def format_legacy_italic_channel_name(value: str, emoji: str | None = None) -> str:
    """Return the previous italic style kept only for rollback and diagnostics."""
    normalized = normalize_channel_label(value)
    if not normalized:
        raise ValueError("O nome do canal não pode ficar vazio após a normalização.")
    styled = normalized.translate(_ITALIC_TRANSLATION).replace(" ", CHANNEL_SEPARATOR)
    return f"{emoji}{CHANNEL_EMOJI_SEPARATOR}{styled}" if emoji else styled


def format_small_caps_channel_name(value: str, emoji: str | None = None) -> str:
    """Return the opt-in Small Caps pilot style with visible word separators."""

    normalized = normalize_channel_label(value)
    if not normalized:
        raise ValueError("O nome do canal não pode ficar vazio após a normalização.")
    styled = SMALL_CAPS_WORD_SEPARATOR.join(
        word.translate(_SMALL_CAPS_TRANSLATION) for word in normalized.split(" ")
    )
    return f"{emoji}{CHANNEL_EMOJI_SEPARATOR}{styled}" if emoji else styled


def format_channel_name(value: str, emoji: str | None = None) -> str:
    """Return the approved CHOQUE channel style used by every creation path."""

    return format_small_caps_channel_name(value, emoji)


def format_category_name(order: int, value: str) -> str:
    """Mantém categorias no padrão monoespaçado já escolhido para a guild."""
    normalized = normalize_channel_label(value).upper()
    return f"{order:02d}{CHANNEL_EMOJI_SEPARATOR}{normalized}".translate(_MONOSPACE_TRANSLATION)
