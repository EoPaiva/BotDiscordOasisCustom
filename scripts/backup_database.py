from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.backups import create_consistent_backup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Cria backup SQLite consistente e verificável.")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.getenv("DATABASE_PATH", "data/choque_bgr.db")),
    )
    parser.add_argument("--destination", type=Path, default=Path("data/security_backups"))
    args = parser.parse_args()
    evidence = create_consistent_backup(args.database, args.destination)
    print(
        "BACKUP_OK "
        f"path={evidence.path} size={evidence.size} migration={evidence.migration} "
        f"integrity={evidence.integrity} fk={evidence.foreign_key_violations} "
        f"sha256={evidence.sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
