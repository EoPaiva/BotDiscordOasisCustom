from scripts.separate_rec_admin_category import (
    ADMIN_KEYS,
    PUBLIC_RESULT_KEYS,
    build_admin_channel_plan,
    build_public_result_plan,
)


def _channels() -> list[dict[str, object]]:
    return [
        {
            "id": str(index),
            "name": key,
            "type": 0,
            "topic": f"CHOQUE-BGR rec-migration:{key}",
        }
        for index, key in enumerate(
            [
                "recruitment.review",
                "recruitment.approved",
                "recruitment.rejected",
                "recruitment.panel",
            ],
            1,
        )
    ]


def test_admin_plan_moves_only_review_channel() -> None:
    plan = build_admin_channel_plan(100, _channels(), 200, [300, 301])

    assert {item["key"] for item in plan} == set(ADMIN_KEYS)
    assert all(item["parent_id"] == 200 for item in plan)
    for item in plan:
        everyone = next(
            overwrite
            for overwrite in item["permission_overwrites"]
            if overwrite["id"] == "100"
        )
        assert int(everyone["deny"]) & (1 << 10)


def test_result_channels_move_to_public_recruitment_read_only() -> None:
    plan = build_public_result_plan(100, _channels(), 201, [300, 301])

    assert {item["key"] for item in plan} == set(PUBLIC_RESULT_KEYS)
    assert all(item["parent_id"] == 201 for item in plan)
    for item in plan:
        everyone = next(
            overwrite
            for overwrite in item["permission_overwrites"]
            if overwrite["id"] == "100"
        )
        assert int(everyone["allow"]) & (1 << 10)
        assert int(everyone["deny"]) & (1 << 11)
