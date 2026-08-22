from __future__ import annotations

import json
import logging

from choque.logging_config import UtcJsonFormatter


def test_structured_logging_redacts_secrets() -> None:
    formatter = UtcJsonFormatter()
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "Authorization: Bearer abc.def.ghi COMMAND_CENTER_INTERNAL_SECRET=super-secret "
        "postgresql://user:password@example.test/db",
        (),
        None,
    )
    payload = json.loads(formatter.format(record))
    message = payload["message"]
    assert "super-secret" not in message
    assert "password" not in message
    assert "Bearer abc" not in message
    assert "REDACTED" in message
