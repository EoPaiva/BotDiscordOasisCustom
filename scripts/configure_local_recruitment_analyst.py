from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.recruitment_analysis import (  # noqa: E402
    LocalDeterministicRecruitmentAnalysisProvider,
    RecruitmentAnalysisService,
    build_recruitment_analysis_provider,
)
from choque.settings import SettingsService  # noqa: E402

LOCAL_CONFIGURATION = {
    "enabled": True,
    "auto_analyze": True,
    "analyze_integrity": True,
    "generate_interview_questions": True,
    "generate_summary": True,
    "final_assisted_after_interview": True,
    "discord_notice": True,
    "show_score": True,
}


async def run(*, apply: bool, validate_only: bool) -> dict[str, object]:
    config = AppConfig.load()
    if not config.default_guild_id:
        raise RuntimeError("DEFAULT_GUILD_ID é obrigatório.")
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        provider = build_recruitment_analysis_provider()
        if not isinstance(provider, LocalDeterministicRecruitmentAnalysisProvider):
            raise RuntimeError(
                "RECRUITMENT_AI_PROVIDER deve estar ausente ou definido como local-deterministic."
            )
        service = RecruitmentAnalysisService(database, settings, audit, provider)
        await service.ensure_defaults(config.default_guild_id)
        if apply:
            await service.update_configuration(
                config.default_guild_id,
                None,
                LOCAL_CONFIGURATION,
            )
            migration = await service.supersede_legacy_active_jobs(
                config.default_guild_id
            )
        else:
            migration = {"superseded": 0, "requeued": 0}
        current = await service.configuration(config.default_guild_id)
        preview = await service.preview_rubric(config.default_guild_id)
        pending = await database.fetchone(
            """
            SELECT
                SUM(CASE WHEN status IN ('PENDING','PROCESSING') THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN status='FAILED' AND attempts>=max_attempts THEN 1 ELSE 0 END) AS exhausted
            FROM recruitment_analysis_jobs WHERE guild_id=?
            """,
            (config.default_guild_id,),
        )
        checks = {
            "provider_local": current["provider"] == "local-deterministic",
            "model_transparent": current["model"] == "transparent-rules-v1",
            "provider_ready": current["provider_ready"] is True,
            "enabled": current["enabled"] is True,
            "automatic": current["auto_analyze"] is True,
            "rubric_weight": int((await service.rubric(config.default_guild_id))["weight_total"])
            == 100,
            "preview_criteria": len(preview["criteria"]) == 10,
        }
        if validate_only and not all(checks.values()):
            raise RuntimeError(
                "Validação do Robô Analista local falhou: "
                + ", ".join(key for key, valid in checks.items() if not valid)
            )
        return {
            "checks": checks,
            "provider": current["provider"],
            "model": current["model"],
            "prompt_version": current["prompt_version"],
            "active_jobs": int(pending["active"] or 0),
            "exhausted_jobs": int(pending["exhausted"] or 0),
            "legacy_jobs": migration,
        }
    finally:
        await database.close()


async def async_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    result = await run(apply=args.apply, validate_only=args.validate_only)
    prefix = (
        "LOCAL_ANALYST_APPLY_PASS"
        if args.apply
        else "LOCAL_ANALYST_LIVE_PASS"
        if args.validate_only
        else "LOCAL_ANALYST_PREVIEW"
    )
    print(prefix + " " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
