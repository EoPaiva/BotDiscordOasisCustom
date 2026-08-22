from __future__ import annotations

import asyncio
import hashlib
import re

from choque.audit import AuditService
from choque.config import AppConfig
from choque.course_catalog_seed import (
    COURSE_DISPLAY_NAMES,
    HISTORICAL_COURSE_CHANNEL_ID,
    HISTORICAL_COURSES,
)
from choque.database import Database
from choque.settings import SettingsService
from choque.training import TrainingService
from scripts.validate_live_phase5 import discord_get

ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")


def clean_role_name(value: str) -> str:
    return " ".join(value.replace("ㅤ", " ").split())


async def run() -> int:
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise RuntimeError("DISCORD_TOKEN e DEFAULT_GUILD_ID são obrigatórios.")
    messages = discord_get(
        f"/channels/{HISTORICAL_COURSE_CHANNEL_ID}/messages?limit=100",
        config.token,
    )
    by_message_id = {int(message["id"]): message for message in messages}
    roles = discord_get(f"/guilds/{config.default_guild_id}/roles", config.token)
    role_names = {int(role["id"]): clean_role_name(str(role["name"])) for role in roles}

    expected_messages = {seed.source_message_id for seed in HISTORICAL_COURSES}
    missing = sorted(expected_messages - set(by_message_id))
    if missing:
        raise RuntimeError(f"Mensagens históricas ausentes: {missing}")

    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        training = TrainingService(database, audit)
        imported = 0
        for seed in HISTORICAL_COURSES:
            message = by_message_id[seed.source_message_id]
            content = str(message.get("content") or "")
            mentioned_roles = tuple(int(value) for value in ROLE_MENTION_RE.findall(content))
            expected_roles = (seed.course_role_id, *seed.required_role_ids)
            if mentioned_roles != expected_roles:
                raise RuntimeError(
                    f"Cargos divergentes na mensagem {seed.source_message_id}: "
                    f"expected={expected_roles} received={mentioned_roles}"
                )
            missing_roles = [role_id for role_id in expected_roles if role_id not in role_names]
            if missing_roles:
                raise RuntimeError(f"Cargos históricos ausentes no Discord: {missing_roles}")
            await training.import_catalog_course(
                config.default_guild_id,
                actor_id=0,
                internal_code=seed.internal_code,
                name=COURSE_DISPLAY_NAMES[seed.internal_code],
                description=seed.description,
                course_role_id=seed.course_role_id,
                course_role_name=role_names[seed.course_role_id],
                passing_score=seed.passing_score,
                cooldown_days=14,
                enrollment_status=seed.enrollment_status,
                notes=seed.notes,
                source_channel_id=HISTORICAL_COURSE_CHANNEL_ID,
                source_message_id=seed.source_message_id,
                source_content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                requirements=[(role_id, role_names[role_id]) for role_id in seed.required_role_ids],
            )
            imported += 1
        await settings.set(
            config.default_guild_id,
            "course_catalog_channel_id",
            HISTORICAL_COURSE_CHANNEL_ID,
            None,
        )
        rows = await training.catalog(config.default_guild_id)
        requirement_count = sum(int(row["requirement_count"]) for row in rows)
        print(
            f"COURSE_IMPORT_PASS historical_messages={len(expected_messages)} imported={imported} "
            f"catalog={len(rows)} requirements={requirement_count}"
        )
        return 0
    finally:
        await database.close()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
