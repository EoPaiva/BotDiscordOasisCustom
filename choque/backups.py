from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BackupEvidence:
    path: Path
    manifest_path: Path
    sha256: str
    size: int
    migration: int
    integrity: str
    foreign_key_violations: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_consistent_backup(source: Path, destination_dir: Path) -> BackupEvidence:
    source = source.resolve(strict=True)
    destination_dir = destination_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = destination_dir / f"choque_bgr-{timestamp}.db"
    if destination.exists():
        destination = destination_dir / f"choque_bgr-{timestamp}-{source.stat().st_size}.db"
    with tempfile.NamedTemporaryFile(
        prefix="choque-backup-", suffix=".db", dir=destination_dir, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with closing(sqlite3.connect(source)) as source_connection, closing(
            sqlite3.connect(temporary_path)
        ) as backup_connection:
            source_connection.backup(backup_connection)
            integrity = str(backup_connection.execute("PRAGMA integrity_check").fetchone()[0])
            violations = len(backup_connection.execute("PRAGMA foreign_key_check").fetchall())
            migration = int(
                backup_connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()[0]
            )
        if integrity != "ok" or violations:
            raise RuntimeError(
                f"Backup inválido: integrity={integrity}, foreign_keys={violations}"
            )
        temporary_path.replace(destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    evidence = BackupEvidence(
        path=destination,
        manifest_path=destination.with_suffix(".manifest.json"),
        sha256=_sha256(destination),
        size=destination.stat().st_size,
        migration=migration,
        integrity=integrity,
        foreign_key_violations=violations,
    )
    evidence.manifest_path.write_text(
        json.dumps(
            {
                "created_at": datetime.now(UTC).isoformat(),
                "database_file": evidence.path.name,
                "sha256": evidence.sha256,
                "size": evidence.size,
                "migration": evidence.migration,
                "integrity": evidence.integrity,
                "foreign_key_violations": evidence.foreign_key_violations,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return evidence


def restore_drill(backup_path: Path) -> BackupEvidence:
    backup_path = backup_path.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="choque-restore-drill-") as directory:
        restored = Path(directory) / "restored.db"
        with closing(sqlite3.connect(backup_path)) as source, closing(
            sqlite3.connect(restored)
        ) as target:
            source.backup(target)
            integrity = str(target.execute("PRAGMA integrity_check").fetchone()[0])
            violations = len(target.execute("PRAGMA foreign_key_check").fetchall())
            migration = int(
                target.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()[0]
            )
        if integrity != "ok" or violations:
            raise RuntimeError(
                f"Restore inválido: integrity={integrity}, foreign_keys={violations}"
            )
        return BackupEvidence(
            path=backup_path,
            manifest_path=backup_path.with_suffix(".manifest.json"),
            sha256=_sha256(backup_path),
            size=backup_path.stat().st_size,
            migration=migration,
            integrity=integrity,
            foreign_key_violations=violations,
        )
