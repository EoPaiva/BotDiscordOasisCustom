from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from choque.errors import ValidationError
from choque.recruitment import RecruitmentService
from choque.settings import SettingsService
from choque.source_cutover import (
    require_source_cutover_writable,
    source_cutover_is_read_only,
    validated_source_cutover,
)
from cogs.ticket_commands import TicketCommands
from cogs.training_commands import TrainingCommands
from scripts.archive_rec_source_layout import (
    RESTORE_CONFIRMATION,
    VIEW_CHANNEL,
    _restore,
    active_source_work,
    archived_name,
    archived_overwrites,
    select_archivable_resources,
)


def test_dc2_cutover_defaults_are_additive_and_disabled() -> None:
    assert SettingsService.DEFAULTS["recruitment_courses_dc2_cutover_enabled"] is False
    assert SettingsService.DEFAULTS["recruitment_courses_dc2_target_guild_id"] is None


def test_archive_payload_hides_users_but_preserves_bot_restore_route() -> None:
    guild_id = 100
    bot_user_id = 200
    bot_role_id = 300
    result = archived_overwrites(
        [
            {"id": str(guild_id), "type": 0, "allow": str(VIEW_CHANNEL), "deny": "0"},
            {"id": "250", "type": 0, "allow": str(VIEW_CHANNEL), "deny": "0"},
            {"id": str(bot_role_id), "type": 0, "allow": "0", "deny": "0"},
        ],
        guild_id=guild_id,
        bot_user_id=bot_user_id,
        bot_role_ids={bot_role_id},
    )
    by_id = {(int(item["type"]), int(item["id"])): item for item in result}

    assert int(by_id[(0, guild_id)]["allow"]) & VIEW_CHANNEL == 0
    assert int(by_id[(0, guild_id)]["deny"]) & VIEW_CHANNEL
    assert int(by_id[(0, 250)]["deny"]) & VIEW_CHANNEL
    assert int(by_id[(0, bot_role_id)]["allow"]) & VIEW_CHANNEL
    assert int(by_id[(0, bot_role_id)]["deny"]) & VIEW_CHANNEL == 0
    assert int(by_id[(1, bot_user_id)]["allow"]) & VIEW_CHANNEL


def test_archive_selection_only_includes_categories_whose_children_all_migrated() -> None:
    channels = [
        {"id": "1", "type": 4, "name": "Cursos"},
        {"id": "2", "type": 0, "name": "curso-a", "parent_id": "1"},
        {"id": "3", "type": 0, "name": "curso-b", "parent_id": "1"},
        {"id": "4", "type": 4, "name": "Mista"},
        {"id": "5", "type": 0, "name": "recrutamento", "parent_id": "4"},
        {"id": "6", "type": 0, "name": "nao-migrado", "parent_id": "4"},
    ]

    # Mesmo se a categoria mista vier registrada, um filho alheio impede que
    # a categoria inteira seja arquivada.
    selected = select_archivable_resources(channels, {1, 2, 3, 4, 5})

    assert {int(item["id"]) for item in selected} == {1, 2, 3, 5}
    assert archived_name("cursos") == "arquivo-cursos"
    assert archived_name("arquivo-cursos") == "arquivo-cursos"


@pytest.mark.asyncio
async def test_preflight_reports_pending_course_application_as_blocker() -> None:
    database = SimpleNamespace()

    async def fetchone(sql: str, _params: tuple[object, ...]) -> dict[str, int]:
        return {"total": 1 if "FROM course_applications" in sql else 0}

    database.fetchone = fetchone
    counts = await active_source_work(database, 123)

    assert counts["course_applications"] == 1
    assert sum(counts.values()) == 1


@pytest.mark.asyncio
async def test_training_on_ready_does_not_restore_source_panels_after_cutover() -> None:
    guild = SimpleNamespace(id=123)
    settings = SimpleNamespace(get=AsyncMock(return_value=True))
    database = SimpleNamespace(
        fetchone=AsyncMock(
            side_effect=[
                None,
                {"value_json": "true"},
                {"value_json": "123"},
                {"value_json": "456"},
                {"value_json": "123"},
            ]
        )
    )
    cog = TrainingCommands.__new__(TrainingCommands)
    cog.bot = SimpleNamespace(check_mode=False, guilds=[guild])
    cog.services = SimpleNamespace(settings=settings, database=database)
    cog.publish_or_refresh = AsyncMock()
    cog.publish_course_catalog = AsyncMock()
    cog.publish_configured_course_panels = AsyncMock()

    await cog.on_ready()

    cog.publish_or_refresh.assert_not_awaited()
    cog.publish_course_catalog.assert_not_awaited()
    cog.publish_configured_course_panels.assert_not_awaited()


@pytest.mark.asyncio
async def test_ticket_on_ready_keeps_recruitment_source_panels_archived() -> None:
    guild = SimpleNamespace(id=123, me=None, get_channel=lambda _channel_id: None)

    async def module_enabled(_guild_id: int, module: str) -> bool:
        return module == "RECRUITMENT"

    settings = SimpleNamespace(get=AsyncMock(return_value=True), set=AsyncMock())
    database = SimpleNamespace(
        fetchone=AsyncMock(
            side_effect=[
                None,
                {"value_json": "true"},
                {"value_json": "123"},
                {"value_json": "456"},
                {"value_json": "123"},
            ]
        ),
        fetchall=AsyncMock(return_value=[]),
    )
    services = SimpleNamespace(
        settings=settings,
        modules=SimpleNamespace(is_enabled=module_enabled),
        tickets=SimpleNamespace(tickets_requiring_rooms=AsyncMock(return_value=[])),
        database=database,
    )
    cog = TicketCommands.__new__(TicketCommands)
    cog.bot = SimpleNamespace(check_mode=False, guilds=[guild], user=None)
    cog.services = services
    cog.publish_or_refresh = AsyncMock()
    cog.publish_partnership_panels = AsyncMock()

    await cog.on_ready()

    cog.publish_or_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_cutover_requires_explicit_bidirectional_link() -> None:
    database = SimpleNamespace(
        fetchone=AsyncMock(
            side_effect=[
                {"value_json": "true"},
                {"value_json": "123"},
                {"value_json": "456"},
                {"value_json": "999"},
            ]
        )
    )

    state = await validated_source_cutover(database, 123)

    assert state.active is False
    assert state.reason == "target_not_linked"


@pytest.mark.asyncio
async def test_source_cutover_blocks_new_writes_after_validated_cutover() -> None:
    database = SimpleNamespace(
        fetchone=AsyncMock(
            side_effect=[
                None,
                {"value_json": "true"},
                {"value_json": "123"},
                {"value_json": "456"},
                {"value_json": "123"},
            ]
        )
    )

    with pytest.raises(ValidationError, match="migrado para o DC2"):
        await require_source_cutover_writable(database, 123, "Cursos")


@pytest.mark.asyncio
async def test_maintenance_lock_keeps_source_read_only_before_final_flag() -> None:
    lock = {
        "state": "ARCHIVING",
        "source_guild_id": 123,
        "target_guild_id": 456,
    }
    database = SimpleNamespace(
        fetchone=AsyncMock(
            side_effect=[
                {"value_json": json.dumps(lock)},
                {"value_json": "123"},
            ]
        )
    )

    assert await source_cutover_is_read_only(database, 123) is True


@pytest.mark.asyncio
async def test_recruitment_service_refuses_to_seed_archived_source(service_bundle) -> None:
    source_guild_id = 123
    target_guild_id = 456
    settings = service_bundle["settings"]
    await settings.set(target_guild_id, "identity_source_guild_id", source_guild_id, 999)
    await settings.set(
        source_guild_id,
        "recruitment_courses_dc2_source_guild_id",
        source_guild_id,
        999,
    )
    await settings.set(
        source_guild_id,
        "recruitment_courses_dc2_target_guild_id",
        target_guild_id,
        999,
    )
    await settings.set(
        source_guild_id,
        "recruitment_courses_dc2_cutover_enabled",
        True,
        999,
    )
    service = RecruitmentService(
        service_bundle["database"],
        service_bundle["audit"],
        token_secret="test-secret",
    )

    with pytest.raises(ValidationError, match="migrado para o DC2"):
        await service.ensure_defaults(source_guild_id, 999)


@pytest.mark.asyncio
async def test_restore_rejects_channel_outside_declared_source(tmp_path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "operation": "DC2_SOURCE_LAYOUT_ARCHIVE",
                "source_guild_id": 123,
                "target_guild_id": 456,
                "resources": [
                    {
                        "id": 999,
                        "name": "recrutamento",
                        "permission_overwrites": [],
                    }
                ],
                "source_setting_rows": [],
            }
        ),
        encoding="utf-8",
    )
    api = SimpleNamespace(request=AsyncMock(return_value=[{"id": "111"}]))
    args = SimpleNamespace(
        confirm=RESTORE_CONFIRMATION,
        restore_snapshot=snapshot_path,
        source_guild=123,
        target_guild=456,
    )

    with pytest.raises(RuntimeError, match="fora do servidor de origem"):
        await _restore(args, api, SimpleNamespace())

    api.request.assert_awaited_once_with("GET", "/guilds/123/channels")
