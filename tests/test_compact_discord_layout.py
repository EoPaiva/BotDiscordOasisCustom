from __future__ import annotations

from copy import deepcopy

from scripts.compact_discord_layout import (
    CATEGORY_IDS,
    CHANNEL_IDS,
    build_plan,
    validate_after,
)


def _channel(
    resource_id: int,
    *,
    resource_type: int,
    parent_id: int | None = None,
    position: int = 0,
) -> dict[str, object]:
    return {
        "id": str(resource_id),
        "name": f"resource-{resource_id}",
        "type": resource_type,
        "parent_id": str(parent_id) if parent_id else None,
        "position": position,
        "permission_overwrites": [],
    }


def _inventory() -> list[dict[str, object]]:
    channels = [
        _channel(category_id, resource_type=4, position=index)
        for index, category_id in enumerate(CATEGORY_IDS.values())
    ]
    parent_by_key = {
        "archive.members": "archive",
        "info.eagle": "info",
        "info.rocam": "info",
        "management.config": "management",
        "point.active": "point",
        "point.panel": "point",
        "superiors.manual": "superiors",
        "superiors.qa": "superiors",
        "ticket.room.2": "ticket",
        "ticket.room.3": "ticket",
    }
    for key, channel_id in CHANNEL_IDS.items():
        channels.append(
            _channel(
                channel_id,
                resource_type=0,
                parent_id=CATEGORY_IDS[parent_by_key[key]],
            )
        )
    channels.extend(
        [
            _channel(9001, resource_type=0, parent_id=CATEGORY_IDS["events"]),
            _channel(9002, resource_type=2, parent_id=CATEGORY_IDS["away"]),
            _channel(9003, resource_type=2, parent_id=CATEGORY_IDS["meeting"]),
            _channel(9004, resource_type=0, parent_id=CATEGORY_IDS["archive"]),
            _channel(9005, resource_type=0, parent_id=CATEGORY_IDS["patrol"]),
        ]
    )
    return channels


def test_build_plan_preserves_member_history_and_limits_deletions() -> None:
    plan = build_plan(_inventory())

    assert CHANNEL_IDS["archive.members"] not in plan.delete_channel_ids
    assert CHANNEL_IDS["archive.members"] in plan.move_parent_by_channel_id
    assert plan.move_parent_by_channel_id[CHANNEL_IDS["archive.members"]] == CATEGORY_IDS["audit"]
    assert CATEGORY_IDS["point"] not in plan.delete_category_ids
    assert CATEGORY_IDS["management"] not in plan.delete_category_ids
    assert CATEGORY_IDS["events"] in plan.delete_category_ids
    assert 9005 not in plan.delete_channel_ids


def test_validate_after_accepts_only_authorized_changes() -> None:
    before = _inventory()
    plan = build_plan(before)
    removed = set(plan.delete_channel_ids) | set(plan.delete_category_ids)
    after = [deepcopy(channel) for channel in before if int(channel["id"]) not in removed]
    after_by_id = {int(channel["id"]): channel for channel in after}
    for channel_id, parent_id in plan.move_parent_by_channel_id.items():
        after_by_id[channel_id]["parent_id"] = str(parent_id)
    max_position = max(
        int(channel["position"]) for channel in after if int(channel["type"]) == 4
    )
    after_by_id[CATEGORY_IDS["partnerships"]]["position"] = max_position

    assert validate_after(before, after, plan) == []


def test_validate_after_detects_unrelated_change() -> None:
    before = _inventory()
    plan = build_plan(before)
    removed = set(plan.delete_channel_ids) | set(plan.delete_category_ids)
    after = [deepcopy(channel) for channel in before if int(channel["id"]) not in removed]
    after_by_id = {int(channel["id"]): channel for channel in after}
    for channel_id, parent_id in plan.move_parent_by_channel_id.items():
        after_by_id[channel_id]["parent_id"] = str(parent_id)
    after_by_id[9005]["name"] = "unexpected"
    max_position = max(
        int(channel["position"]) for channel in after if int(channel["type"]) == 4
    )
    after_by_id[CATEGORY_IDS["partnerships"]]["position"] = max_position

    assert "unrelated_changed_name:9005" in validate_after(before, after, plan)


def test_validate_after_ignores_permission_overwrite_order() -> None:
    before = _inventory()
    before[-1]["permission_overwrites"] = [
        {"id": "2", "type": 0, "allow": "1", "deny": "0"},
        {"id": "1", "type": 0, "allow": "0", "deny": "1"},
    ]
    plan = build_plan(before)
    removed = set(plan.delete_channel_ids) | set(plan.delete_category_ids)
    after = [deepcopy(channel) for channel in before if int(channel["id"]) not in removed]
    after_by_id = {int(channel["id"]): channel for channel in after}
    for channel_id, parent_id in plan.move_parent_by_channel_id.items():
        after_by_id[channel_id]["parent_id"] = str(parent_id)
    after_by_id[9005]["permission_overwrites"] = list(
        reversed(after_by_id[9005]["permission_overwrites"])
    )
    max_position = max(
        int(channel["position"]) for channel in after if int(channel["type"]) == 4
    )
    after_by_id[CATEGORY_IDS["partnerships"]]["position"] = max_position

    assert validate_after(before, after, plan) == []
