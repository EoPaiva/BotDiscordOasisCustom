import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.member_commands import MemberCommands
from cogs.ticket_commands import TicketCommands
from scripts.migrate_rec_choque import CHANNELS, _copy_data, _permission_overwrites, run


def test_recruitment_results_are_public_in_recruitment_category() -> None:
    results = {
        spec.key: spec
        for spec in CHANNELS
        if spec.key in {"recruitment.approved", "recruitment.rejected"}
    }

    assert set(results) == {"recruitment.approved", "recruitment.rejected"}
    assert all(spec.category == "recruitment" for spec in results.values())
    assert all(not spec.private for spec in results.values())


def test_private_interview_grants_candidate_access_without_moderation() -> None:
    overwrites = _permission_overwrites(
        100,
        staff_role_ids=[200],
        viewer_role_ids=[300],
        private=True,
        writable=False,
    )

    everyone = next(item for item in overwrites if item["id"] == "100")
    staff = next(item for item in overwrites if item["id"] == "200")
    candidate = next(item for item in overwrites if item["id"] == "300")
    view_channel = 1 << 10
    manage_messages = 1 << 13

    assert int(everyone["deny"]) & view_channel
    assert int(staff["allow"]) & manage_messages
    assert int(candidate["allow"]) & view_channel
    assert not int(candidate["allow"]) & manage_messages


def test_member_only_course_channel_denies_everyone_and_allows_member_chat() -> None:
    overwrites = _permission_overwrites(
        100,
        staff_role_ids=[200],
        viewer_role_ids=[300],
        private=True,
        writable=True,
        viewer_writable=True,
    )

    everyone = next(item for item in overwrites if item["id"] == "100")
    member = next(item for item in overwrites if item["id"] == "300")
    view_channel = 1 << 10
    send_messages = 1 << 11

    assert int(everyone["deny"]) & view_channel
    assert int(member["allow"]) & view_channel
    assert int(member["allow"]) & send_messages


def test_satellite_identity_uses_a_rank_sync_state_accepted_by_the_schema() -> None:
    migration_source = inspect.getsource(_copy_data)

    assert "rank_sync_status='MISSING_ROLE'" in migration_source
    assert "rank_sync_status='PENDING'" not in migration_source
    assert 'source_message_id=int(source_course["id"])' in migration_source
    assert "source_message_id=1" not in migration_source
    assert "UPDATE course_catalog SET source_channel_id" not in inspect.getsource(run)


@pytest.mark.asyncio
async def test_registration_recovery_skips_disabled_satellite_module() -> None:
    guild = SimpleNamespace(id=1541908574463070311)
    modules = SimpleNamespace(is_enabled=AsyncMock(return_value=False))
    cog = MemberCommands.__new__(MemberCommands)
    cog.bot = SimpleNamespace(check_mode=False, guilds=[guild])
    cog.services = SimpleNamespace(modules=modules)

    await MemberCommands.on_ready(cog)

    modules.is_enabled.assert_awaited_once_with(guild.id, "REGISTRATION")


@pytest.mark.asyncio
async def test_recruitment_recovery_does_not_publish_disabled_ticket_panels() -> None:
    guild = SimpleNamespace(id=1541908574463070311, me=None, get_channel=lambda _: None)

    async def module_enabled(_: int, module: str) -> bool:
        return module == "RECRUITMENT"

    services = SimpleNamespace(
        modules=SimpleNamespace(is_enabled=AsyncMock(side_effect=module_enabled)),
        settings=SimpleNamespace(get=AsyncMock(return_value=None)),
        tickets=SimpleNamespace(tickets_requiring_rooms=AsyncMock(return_value=[])),
        database=SimpleNamespace(fetchall=AsyncMock(return_value=[])),
    )
    cog = TicketCommands.__new__(TicketCommands)
    cog.bot = SimpleNamespace(check_mode=False, guilds=[guild], user=None)
    cog.services = services
    cog.publish_partnership_panels = AsyncMock()

    await TicketCommands.on_ready(cog)

    cog.publish_partnership_panels.assert_not_awaited()
