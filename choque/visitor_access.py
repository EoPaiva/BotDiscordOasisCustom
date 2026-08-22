from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AccessLevel = Literal["public", "member", "private"]


PUBLIC_CATEGORY_KEYS = frozenset(
    {
        "reception",
        "ticket",
        "partnerships",
        "recruitment",
    }
)

MEMBER_CATEGORY_KEYS = frozenset(
    {
        "member",
        "registration",
        "info",
        "community",
        "point",
        "events",
        "patrol",
        "courses",
        "away",
        "meeting",
    }
)

PRIVATE_CATEGORY_KEYS = frozenset(
    {
        "superiors",
        "admin",
        "management",
        "audit",
        "archive",
    }
)

# Estes canais vivem em categorias publicas, mas contem filas ou resultados internos.
PRIVATE_CHANNEL_KEYS = frozenset(
    {
        "ticket.queue",
        "recruitment.approved",
        "recruitment.rejected",
    }
)

# O painel de cadastro possui chave histórica da categoria Registro, mas foi
# movido fisicamente para Recepção durante o access gate. Ele continua público
# sem tornar a categoria Registro visível para visitantes.
PUBLIC_CHANNEL_KEYS = frozenset({"registration.panel"})


@dataclass(frozen=True, slots=True)
class VisitorAccessPolicy:
    category_key: str
    channel_key: str | None
    access: AccessLevel

    @property
    def visitor_can_view(self) -> bool:
        return self.access == "public"

    @property
    def member_can_view(self) -> bool:
        return self.access in {"public", "member"}


def category_access(category_key: str) -> AccessLevel:
    if category_key in PUBLIC_CATEGORY_KEYS:
        return "public"
    if category_key in MEMBER_CATEGORY_KEYS:
        return "member"
    if category_key in PRIVATE_CATEGORY_KEYS:
        return "private"
    raise KeyError(f"Categoria sem politica de acesso: {category_key}")


def channel_access(category_key: str, channel_key: str) -> AccessLevel:
    if channel_key in PUBLIC_CHANNEL_KEYS:
        return "public"
    if channel_key in PRIVATE_CHANNEL_KEYS:
        return "private"
    return category_access(category_key)


def all_category_keys() -> frozenset[str]:
    return PUBLIC_CATEGORY_KEYS | MEMBER_CATEGORY_KEYS | PRIVATE_CATEGORY_KEYS
