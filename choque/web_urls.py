from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def recruitment_portal_url(configured_url: str) -> str:
    """Retorna a rota pública do recrutamento sem duplicar o caminho."""
    parsed = urlsplit(configured_url.strip())
    path = parsed.path.rstrip("/")
    if not path.endswith("/recrutamento"):
        path = f"{path}/recrutamento" if path else "/recrutamento"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def recruitment_status_url(configured_url: str) -> str:
    """Retorna a rota de acompanhamento a partir da raiz pública configurada."""
    parsed = urlsplit(configured_url.strip())
    path = parsed.path.rstrip("/")
    if path.endswith("/recrutamento"):
        path = path.removesuffix("/recrutamento")
    path = f"{path}/minha-candidatura" if path else "/minha-candidatura"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))
