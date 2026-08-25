from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from choque.services import Services


def test_bot_wires_every_service_by_name() -> None:
    """Adding a service must never shift dependencies assigned to active cogs."""

    source_path = Path(__file__).parents[1] / "choque" / "bot.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Services"
    ]

    assert len(calls) == 1
    call = calls[0]
    assert call.args == []
    assert {keyword.arg for keyword in call.keywords} == {
        field.name for field in fields(Services)
    }
