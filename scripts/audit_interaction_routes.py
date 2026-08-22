from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COGS_ROOT = PROJECT_ROOT / "cogs"
UI_SUFFIXES = ("View", "Modal", "Select")
INTENTIONALLY_RETIRED = {
    "AbsencePanelView": "Substituído pelo fluxo único de Solicitações; não deve ser reativado.",
    "AbsenceListView": "Substituído pela fila administrativa de Solicitações.",
}


def dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def literal_keyword(call: ast.Call, name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    return None


def audit() -> dict[str, object]:
    classes: dict[str, dict[str, object]] = {}
    calls: Counter[str] = Counter()
    inherited: Counter[str] = Counter()
    custom_ids: list[dict[str, object]] = []
    component_count = 0
    callback_missing: list[str] = []

    for path in sorted(COGS_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                calls[dotted_name(node.func).split(".")[-1]] += 1
            if not isinstance(node, ast.ClassDef) or not node.name.endswith(UI_SUFFIXES):
                continue
            for base in node.bases:
                inherited[dotted_name(base).split(".")[-1]] += 1
            methods = {item.name: item for item in node.body if isinstance(item, ast.AsyncFunctionDef)}
            components: list[dict[str, object]] = []
            for method in methods.values():
                for decorator in method.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    kind = dotted_name(decorator.func)
                    if kind not in {"discord.ui.button", "discord.ui.select"}:
                        continue
                    component_count += 1
                    custom_id = literal_keyword(decorator, "custom_id")
                    component = {
                        "kind": kind.rsplit(".", 1)[-1],
                        "label": literal_keyword(decorator, "label"),
                        "callback": method.name,
                        "custom_id": custom_id,
                    }
                    components.append(component)
                    if not method.body:
                        callback_missing.append(f"{path.name}:{node.name}.{method.name}")
                    if custom_id:
                        custom_ids.append(
                            {"custom_id": custom_id, "file": path.name, "class": node.name}
                        )
            if any(base.endswith("Select") for base in map(dotted_name, node.bases)):
                component_count += 1
                if "callback" not in methods:
                    callback_missing.append(f"{path.name}:{node.name}.callback")
            classes[node.name] = {
                "file": path.name,
                "components": components,
            }

    duplicate_ids = [
        value
        for value, count in Counter(item["custom_id"] for item in custom_ids).items()
        if count > 1
    ]
    unreferenced = sorted(
        name
        for name in classes
        if calls[name] == 0
        and inherited[name] == 0
        and name not in {"ErrorView", "AdminView"}
        and name not in INTENTIONALLY_RETIRED
    )
    return {
        "files": len(list(COGS_ROOT.glob("*.py"))),
        "ui_classes": len(classes),
        "components": component_count,
        "explicit_custom_ids": len(custom_ids),
        "duplicate_custom_ids": duplicate_ids,
        "missing_callbacks": callback_missing,
        "unreferenced_ui_classes": unreferenced,
        "intentionally_retired": INTENTIONALLY_RETIRED,
        "classes": classes,
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failed = any(
        result[key]
        for key in ("duplicate_custom_ids", "missing_callbacks", "unreferenced_ui_classes")
    )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
