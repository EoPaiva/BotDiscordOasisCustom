from __future__ import annotations

import re

from .errors import ValidationError

BGR_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


def normalize_bgr_id(value: str) -> str:
    """Normalize and validate the canonical BGR/MTA identity identifier."""
    normalized = str(value or "").strip()
    if not BGR_ID_PATTERN.fullmatch(normalized):
        raise ValidationError(
            "O ID BGR deve possuir até 32 caracteres: letras, números, ponto, hífen ou _."
        )
    return normalized
