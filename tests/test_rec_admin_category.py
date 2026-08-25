from scripts.separate_rec_admin_category import (
    ADMIN_KEYS,
    build_admin_channel_plan,
)


def test_admin_plan_moves_only_review_and_result_channels() -> None:
    channels = [
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

    plan = build_admin_channel_plan(100, channels, 200, [300, 301])

    assert {item["key"] for item in plan} == set(ADMIN_KEYS)
    assert all(item["parent_id"] == 200 for item in plan)
    for item in plan:
        everyone = next(
            overwrite
            for overwrite in item["permission_overwrites"]
            if overwrite["id"] == "100"
        )
        assert int(everyone["deny"]) & (1 << 10)
