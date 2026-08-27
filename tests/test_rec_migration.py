import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.member_commands import MemberCommands
from cogs.ticket_commands import TicketCommands
from scripts.configure_rec_inactivity_alerts import _validate_target_guild
from scripts.migrate_rec_choque import (
    CHANNELS,
    RECRUITMENT_URL,
    _copy_data,
    _permission_overwrites,
    _preserve_member_overwrites,
    _recruitment_position_rows,
    run,
)


def test_rec_recruitment_button_uses_the_public_portal_root() -> None:
    assert RECRUITMENT_URL == "https://choquebgr.online/recrutamento/"
    assert "/servidor" not in RECRUITMENT_URL


def test_rec_inactivity_channel_is_private_and_administrative() -> None:
    spec = next(item for item in CHANNELS if item.key == "recruitment.inactivity")
    assert spec.category == "recruitment_admin"
    assert spec.private is True


def test_rec_inactivity_provisioning_uses_immutable_guild_id_not_display_name() -> None:
    _validate_target_guild(
        {
            "id": "1541908574463070311",
            "name": "𝗖𝗛𝗢𝗤𝗨𝗘 | 𝗖𝗘𝗡𝗧𝗥𝗢 𝗗𝗘 𝗜𝗡𝗦𝗧𝗥𝗨ÇÃ𝗢",
        },
        1541908574463070311,
    )
    with pytest.raises(RuntimeError, match="Servidor de destino inesperado"):
        _validate_target_guild({"id": "1", "name": "REC Choque"}, 2)


def test_recruitment_results_are_public_in_recruitment_category() -> None:
    results = {
        spec.key: spec
        for spec in CHANNELS
        if spec.key in {"recruitment.approved", "recruitment.rejected"}
    }

    assert set(results) == {"recruitment.approved", "recruitment.rejected"}
    assert all(spec.category == "recruitment" for spec in results.values())
    assert all(not spec.private for spec in results.values())


def test_rec_review_mentions_use_all_three_staff_positions() -> None:
    rows = _recruitment_position_rows(
        {
            "Comando REC": 101,
            "Responsável Recrutamento": 102,
            "Auxiliar Recrutamento": 103,
        }
    )

    assert rows == [
        (101, "RECRUITMENT_LEAD", "Comando REC", 700, "ADMINISTRADOR"),
        (102, "RECRUITMENT_LEAD", "Responsável Recrutamento", 600, "INSTRUTOR"),
        (103, "RECRUITER", "Auxiliar Recrutamento", 500, "INSTRUTOR"),
    ]


def test_reprovision_preserves_only_member_specific_overwrites() -> None:
    base = _permission_overwrites(
        100,
        staff_role_ids=[200],
        private=True,
        writable=False,
    )
    merged = _preserve_member_overwrites(
        base,
        [
            {"id": "300", "type": 1, "allow": "66560", "deny": "2048"},
            {"id": "400", "type": 0, "allow": "1024", "deny": "0"},
        ],
    )

    assert any(item["id"] == "300" and item["type"] == 1 for item in merged)
    assert not any(item["id"] == "400" for item in merged)


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
        database=SimpleNamespace(
            fetchone=AsyncMock(return_value=None),
            fetchall=AsyncMock(return_value=[]),
        ),
    )
    cog = TicketCommands.__new__(TicketCommands)
    cog.bot = SimpleNamespace(check_mode=False, guilds=[guild], user=None)
    cog.services = services
    cog.publish_partnership_panels = AsyncMock()

    await TicketCommands.on_ready(cog)

    cog.publish_partnership_panels.assert_not_awaited()
