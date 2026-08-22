from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime


class UtcJsonFormatter(logging.Formatter):
    _patterns = (
        re.compile(r"(?i)\b(authorization|cookie|set-cookie)\s*[:=]\s*[^\s,;]+"),
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|DATABASE_URL)[A-Z0-9_]*)"
            r"\s*[:=]\s*[^\s,;]+"
        ),
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
        re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^\s:/]+:)[^\s@]+(@)"),
    )

    @classmethod
    def redact(cls, value: str) -> str:
        redacted = value
        for index, pattern in enumerate(cls._patterns):
            if index == 1:
                redacted = pattern.sub(r"\1=[REDACTED]", redacted)
            elif index == 4:
                redacted = pattern.sub(r"\1[REDACTED]\2", redacted)
            else:
                redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.redact(record.getMessage()),
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id:
            payload["correlation_id"] = str(correlation_id)
        if record.exc_info:
            payload["exception"] = self.redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(UtcJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
