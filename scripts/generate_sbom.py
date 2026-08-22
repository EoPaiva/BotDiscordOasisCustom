from __future__ import annotations

import argparse
import importlib.metadata
import json
from datetime import UTC, datetime
from pathlib import Path


def _python_packages() -> list[dict[str, str]]:
    packages = {
        (distribution.metadata["Name"] or distribution.name, distribution.version)
        for distribution in importlib.metadata.distributions()
    }
    return [
        {
            "SPDXID": f"SPDXRef-Python-{index}",
            "name": name,
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "supplier": "NOASSERTION",
        }
        for index, (name, version) in enumerate(sorted(packages), 1)
    ]


def _node_packages(lock_path: Path, offset: int) -> list[dict[str, str]]:
    if not lock_path.exists():
        return []
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = []
    for location, metadata in sorted(lock.get("packages", {}).items()):
        if not location or not isinstance(metadata, dict) or not metadata.get("version"):
            continue
        name = metadata.get("name") or location.rsplit("node_modules/", 1)[-1]
        packages.append(
            {
                "SPDXID": f"SPDXRef-Node-{offset + len(packages)}",
                "name": str(name),
                "versionInfo": str(metadata["version"]),
                "downloadLocation": str(metadata.get("resolved") or "NOASSERTION"),
                "filesAnalyzed": False,
                "supplier": "NOASSERTION",
            }
        )
    return packages


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera SBOM SPDX 2.3 do ambiente validado.")
    parser.add_argument("--output", type=Path, default=Path("artifacts/security/sbom.spdx.json"))
    args = parser.parse_args()
    python_packages = _python_packages()
    packages = python_packages + _node_packages(Path("web/package-lock.json"), len(python_packages) + 1)
    created = datetime.now(UTC)
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "CHOQUE-BGR-security-sbom",
        "documentNamespace": f"https://choque-bgr.invalid/sbom/{created.strftime('%Y%m%dT%H%M%SZ')}",
        "creationInfo": {
            "created": created.isoformat().replace("+00:00", "Z"),
            "creators": ["Tool: scripts/generate_sbom.py"],
        },
        "packages": packages,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    print(f"SBOM_OK path={args.output} packages={len(packages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
