from __future__ import annotations

import math
import re
import subprocess
from collections import Counter
from pathlib import Path

RULES = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("discord-token", re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "assigned-secret",
        re.compile(
            r"(?i)\b(?:token|secret|password|api[_-]?key)\b\s*[:=]\s*[\"']?"
            r"([A-Za-z0-9_./+=-]{24,})"
        ),
    ),
    ("public-secret-env", re.compile(r"(?i)\b(?:NEXT_PUBLIC|VITE)_[A-Z0-9_]*(?:SECRET|TOKEN|KEY)\b")),
)
SAFE_MARKERS = ("test", "example", "dummy", "sample", "redacted", "changeme", "sufficient-entropy")
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".toml", ".yml", ".yaml", ".md",
    ".txt", ".ini", ".cfg", ".ps1", ".html", ".css", ".sql",
}


def _candidate_files(root: Path) -> list[Path]:
    commands = (
        ["git", "ls-files", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    )
    names: set[str] = set()
    for command in commands:
        result = subprocess.run(command, cwd=root, capture_output=True, check=True)
        names.update(item.decode() for item in result.stdout.split(b"\0") if item)
    return sorted(root / name for name in names)


def _entropy(value: str) -> float:
    counts = Counter(value)
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values())


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings: list[tuple[str, int, str]] = []
    for path in _candidate_files(root):
        if path.resolve() == Path(__file__).resolve():
            continue
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in {"node_modules", ".git", ".venv", "data", "logs"} for part in path.parts):
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            for name, pattern in RULES:
                match = pattern.search(line)
                if not match:
                    continue
                candidate = match.group(1) if match.lastindex else match.group(0)
                lowered = candidate.lower()
                if any(marker in lowered for marker in SAFE_MARKERS):
                    continue
                if (
                    name == "assigned-secret"
                    and match.lastindex
                    and line[match.end(1) :].lstrip().startswith("(")
                ):
                    # Expressões como ``token = context_var.set(...)`` não são
                    # literais; o scanner continua cobrindo segredos atribuídos.
                    continue
                if name == "assigned-secret" and _entropy(candidate) < 3.2:
                    continue
                findings.append((str(path.relative_to(root)), number, name))
    if findings:
        for path, number, rule in findings:
            print(f"SECRET_SCAN_FINDING path={path} line={number} rule={rule}")
        return 1
    print("SECRET_SCAN_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
