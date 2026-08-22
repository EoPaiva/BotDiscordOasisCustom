from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.backups import restore_drill  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Testa restauração sem tocar o banco operacional.")
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    evidence = restore_drill(args.backup)
    print(
        "RESTORE_DRILL_OK "
        f"source={evidence.path} size={evidence.size} migration={evidence.migration} "
        f"integrity={evidence.integrity} fk={evidence.foreign_key_violations} "
        f"sha256={evidence.sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
