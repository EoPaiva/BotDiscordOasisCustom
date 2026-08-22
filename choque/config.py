from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Branding:
    name: str = "CHOQUE - BGR"
    short_name: str = "CHOQUE - BGR"
    embed_color: int = 0xB11226
    logo_url: str | None = None
    footer: str = "CHOQUE - BGR • Sistema de Gestão"


@dataclass(frozen=True, slots=True)
class AppConfig:
    token: str | None
    database_path: Path
    legacy_database_path: Path
    default_guild_id: int | None
    log_level: str
    branding: Branding

    @classmethod
    def load(cls) -> AppConfig:
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN")
        legacy_token = os.getenv("TOKEN")
        if not token and legacy_token:
            logging.getLogger(__name__).warning("TOKEN esta obsoleto; migre para DISCORD_TOKEN.")
            token = legacy_token

        guild_id_raw = os.getenv("DEFAULT_GUILD_ID")
        guild_id = int(guild_id_raw) if guild_id_raw and guild_id_raw.isdigit() else None
        logo_url = os.getenv("BRANDING_LOGO_URL") or None

        return cls(
            token=token,
            database_path=Path(os.getenv("DATABASE_PATH", "data/choque_bgr.db")),
            legacy_database_path=Path("oasis_custom_data.db"),
            default_guild_id=guild_id,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            branding=Branding(logo_url=logo_url),
        )
