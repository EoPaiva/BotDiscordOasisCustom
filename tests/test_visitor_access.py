from __future__ import annotations

import pytest

from choque.visitor_access import (
    MEMBER_CATEGORY_KEYS,
    PRIVATE_CATEGORY_KEYS,
    PUBLIC_CATEGORY_KEYS,
    all_category_keys,
    category_access,
    channel_access,
)
from scripts.remodel_discord_layout import CATEGORY_BY_KEY, CHANNEL_BY_KEY


def test_every_layout_category_has_exactly_one_access_policy() -> None:
    assert PUBLIC_CATEGORY_KEYS.isdisjoint(MEMBER_CATEGORY_KEYS)
    assert PUBLIC_CATEGORY_KEYS.isdisjoint(PRIVATE_CATEGORY_KEYS)
    assert MEMBER_CATEGORY_KEYS.isdisjoint(PRIVATE_CATEGORY_KEYS)
    assert all_category_keys() == set(CATEGORY_BY_KEY)


@pytest.mark.parametrize(
    ("category_key", "expected"),
    [
        ("reception", "public"),
        ("ticket", "public"),
        ("partnerships", "public"),
        ("recruitment", "public"),
        ("member", "member"),
        ("registration", "member"),
        ("info", "member"),
        ("community", "member"),
        ("admin", "private"),
        ("audit", "private"),
    ],
)
def test_category_policy(category_key: str, expected: str) -> None:
    assert category_access(category_key) == expected


def test_staff_channels_inside_public_categories_remain_private() -> None:
    assert channel_access("registration", "registration.panel") == "public"
    assert channel_access("ticket", "ticket.queue") == "private"
    assert channel_access("recruitment", "recruitment.approved") == "private"
    assert channel_access("recruitment", "recruitment.rejected") == "private"
    assert channel_access("ticket", "ticket.panel") == "public"
    assert channel_access("recruitment", "recruitment.panel") == "public"


def test_every_registered_channel_inherits_a_known_policy() -> None:
    for key, spec in CHANNEL_BY_KEY.items():
        assert channel_access(spec.category, key) in {"public", "member", "private"}


def test_unknown_category_fails_closed() -> None:
    with pytest.raises(KeyError):
        category_access("unknown")
