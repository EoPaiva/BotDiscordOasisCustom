from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from choque.web_outbox import WebActionWorker

from .conftest import DISCORD_ID, GUILD_ID

COURSE_ROLE_ID = 70_001


async def _course(service_bundle) -> int:
    now = service_bundle["clock"]()
    return await service_bundle["database"].execute(
        """
        INSERT INTO course_catalog(
            guild_id, internal_code, name, description, course_role_id,
            course_role_name, passing_score, cooldown_days, enrollment_status,
            source_channel_id, source_message_id, source_content_sha256,
            active, created_at, updated_at
        ) VALUES (?, 'abordagem_avancada', 'Abordagem Avançada', 'Curso de teste', ?,
                  'Abordagem Avançada', 80, 14, 'OPEN', 10, 11, 'test-hash', 1, ?, ?)
        """,
        (GUILD_ID, COURSE_ROLE_ID, now, now),
    )


@pytest.mark.asyncio
async def test_web_qualification_is_append_only_audited_and_idempotent(service_bundle) -> None:
    operations = service_bundle["operations"]
    database = service_bundle["database"]
    course_id = await _course(service_bundle)

    granted = await operations.set_member_qualification(
        GUILD_ID,
        DISCORD_ID,
        course_id,
        granted=True,
        actor_id=999,
        reason="Concessão administrativa de teste.",
        source="WEB",
        enqueue_discord_sync=True,
        correlation_id="qualification-grant-test",
    )
    repeated = await operations.set_member_qualification(
        GUILD_ID,
        DISCORD_ID,
        course_id,
        granted=True,
        actor_id=999,
        reason="Concessão administrativa repetida.",
        source="WEB",
        enqueue_discord_sync=True,
        correlation_id="qualification-grant-repeat-test",
    )

    assert granted["changed"] is True
    assert repeated["changed"] is False
    changes = await database.fetchall("SELECT * FROM qualification_changes")
    outbox = await database.fetchall("SELECT * FROM web_action_outbox")
    audits = await database.fetchall(
        "SELECT action FROM audit_logs WHERE action='MEMBER_QUALIFICATION_GRANTED'"
    )
    assert len(changes) == 1
    assert len(outbox) == 1
    assert json.loads(outbox[0]["payload_json"]) == {
        "course_id": course_id,
        "granted": True,
        "source": "WEB",
    }
    assert len(audits) == 1
    matrix = await operations.qualification_matrix(GUILD_ID)
    assert matrix["courses"][0]["course_role_id"] == COURSE_ROLE_ID
    assert matrix["members"][0]["courses"]["abordagem_avancada"]["granted"] is True
    current = await operations.current_member_qualifications(GUILD_ID, DISCORD_ID)
    assert [(row["internal_code"], row["result"]) for row in current] == [
        ("abordagem_avancada", "APPROVED")
    ]
    dossier = await operations.dossier(GUILD_ID, DISCORD_ID)
    assert dossier["qualifications"][0]["course_name"] == "Abordagem Avançada"


@pytest.mark.asyncio
async def test_discord_role_change_updates_matrix_without_echo_outbox(service_bundle) -> None:
    operations = service_bundle["operations"]
    database = service_bundle["database"]
    course_id = await _course(service_bundle)
    await operations.set_member_qualification(
        GUILD_ID,
        DISCORD_ID,
        course_id,
        granted=True,
        actor_id=999,
        reason="Preparação do teste.",
        source="WEB",
        enqueue_discord_sync=True,
        correlation_id="qualification-before-discord-revoke",
    )
    await database.execute("DELETE FROM web_action_outbox")

    results = await operations.record_discord_qualification_roles(
        GUILD_ID,
        DISCORD_ID,
        added_role_ids=set(),
        removed_role_ids={COURSE_ROLE_ID},
    )

    assert len(results) == 1
    assert results[0]["granted"] is False
    assert await database.fetchone("SELECT 1 FROM web_action_outbox") is None
    latest = await database.fetchone(
        "SELECT action, source FROM qualification_changes ORDER BY id DESC LIMIT 1"
    )
    assert dict(latest) == {"action": "REVOKE", "source": "DISCORD"}
    matrix = await operations.qualification_matrix(GUILD_ID)
    assert matrix["members"][0]["courses"]["abordagem_avancada"] is None


class _Role:
    def __init__(self, role_id: int) -> None:
        self.id = role_id


class _Member:
    def __init__(self, discord_id: int) -> None:
        self.id = discord_id
        self.roles: list[_Role] = []
        self.add_roles = AsyncMock(side_effect=self._add)
        self.remove_roles = AsyncMock(side_effect=self._remove)

    async def _add(self, role: _Role, **_: object) -> None:
        self.roles.append(role)

    async def _remove(self, role: _Role, **_: object) -> None:
        self.roles = [item for item in self.roles if item.id != role.id]


class _Guild:
    def __init__(self, member: _Member, role: _Role) -> None:
        self.id = GUILD_ID
        self.member = member
        self.role = role

    def get_member(self, discord_id: int):
        return self.member if discord_id == self.member.id else None

    def get_role(self, role_id: int):
        return self.role if role_id == self.role.id else None


class _Bot:
    def __init__(self, guild: _Guild) -> None:
        self.guild = guild

    def get_guild(self, guild_id: int):
        return self.guild if guild_id == self.guild.id else None


@pytest.mark.asyncio
async def test_outbox_applies_latest_qualification_role_state(service_bundle) -> None:
    database = service_bundle["database"]
    operations = service_bundle["operations"]
    course_id = await _course(service_bundle)
    result = await operations.set_member_qualification(
        GUILD_ID,
        DISCORD_ID,
        course_id,
        granted=True,
        actor_id=999,
        reason="Sincronização pelo site.",
        source="WEB",
        enqueue_discord_sync=True,
        correlation_id="qualification-outbox-worker",
    )
    role = _Role(COURSE_ROLE_ID)
    member = _Member(DISCORD_ID)
    guild = _Guild(member, role)
    audit = SimpleNamespace(record=AsyncMock(), settings=None)
    worker = WebActionWorker(
        database,
        SimpleNamespace(),
        audit,
        _Bot(guild),
    )

    assert await worker.process_pending() == 1
    member.add_roles.assert_awaited_once_with(
        role,
        reason="CHOQUE - BGR • qualificação Abordagem Avançada via Centro de Comando",
    )
    action = await database.fetchone(
        "SELECT status, attempts FROM web_action_outbox WHERE id=?",
        (result["outbox_id"],),
    )
    assert dict(action) == {"status": "COMPLETED", "attempts": 1}
