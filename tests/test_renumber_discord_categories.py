from __future__ import annotations

from copy import deepcopy

from scripts.renumber_discord_categories import (
    EXPECTED_CATEGORIES,
    OBSOLETE_POINT_CATEGORY_ID,
    expected_name_by_id,
    validate_after,
    validate_inventory,
)


def _inventory() -> list[dict[str, object]]:
    categories = [
        {
            "id": str(category_id),
            "name": f"old-{index}",
            "type": 4,
            "parent_id": None,
            "position": index - 1,
            "permission_overwrites": [],
        }
        for index, (category_id, _) in enumerate(EXPECTED_CATEGORIES, start=1)
    ]
    categories.insert(
        9,
        {
            "id": str(OBSOLETE_POINT_CATEGORY_ID),
            "name": "old-point",
            "type": 4,
            "parent_id": None,
            "position": 9,
            "permission_overwrites": [],
        },
    )
    for index, category in enumerate(categories):
        category["position"] = index
    return categories


def test_expected_categories_are_unique_and_sequential() -> None:
    identifiers = [category_id for category_id, _ in EXPECTED_CATEGORIES]
    names = expected_name_by_id()

    assert len(identifiers) == len(set(identifiers)) == 16
    assert list(names) == identifiers
    assert all(f"{position:02d}" not in name for position, name in enumerate(names.values(), 1))


def test_inventory_and_after_validation_preserve_everything_except_names() -> None:
    before = _inventory()
    assert validate_inventory(before) is True
    after = [
        channel
        for channel in deepcopy(before)
        if int(channel["id"]) != OBSOLETE_POINT_CATEGORY_ID
    ]
    names = expected_name_by_id()
    for channel in after:
        channel["name"] = names[int(channel["id"])]
    for index, channel in enumerate(after):
        channel["position"] = index

    assert validate_after(before, after) == []
    assert validate_inventory(after) is False
