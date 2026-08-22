from __future__ import annotations

import asyncio
import json
from pathlib import Path

from choque.backups import create_consistent_backup, restore_drill
from choque.database import Database


def test_consistent_backup_and_restore_drill(tmp_path: Path) -> None:
    source = tmp_path / "source.db"

    async def seed() -> None:
        database = Database(source)
        await database.open()
        try:
            await database.execute(
                """
                INSERT INTO ranks(guild_id, name, prefix, level, rbac_profile, created_at)
                VALUES (1, 'Recruta', 'REC', 1, 'MEMBRO', 1)
                """
            )
        finally:
            await database.close()

    asyncio.run(seed())
    evidence = create_consistent_backup(source, tmp_path / "backups")
    assert evidence.path.exists()
    assert evidence.manifest_path.exists()
    assert evidence.migration == 24
    assert evidence.integrity == "ok"
    assert evidence.foreign_key_violations == 0
    manifest = json.loads(evidence.manifest_path.read_text(encoding="utf-8"))
    assert manifest["sha256"] == evidence.sha256

    restored = restore_drill(evidence.path)
    assert restored.sha256 == evidence.sha256
    assert restored.migration == 24
    assert restored.integrity == "ok"
