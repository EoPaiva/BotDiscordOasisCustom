from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.registration_gate_system import RegistrationGateSystem


class FakeSettings:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    async def get(self, _guild_id: int, key: str, default=None):
        return self.values.get(key, default)


def fake_member(
    *,
    member_id: int = 10,
    owner_id: int = 999,
    bot: bool = False,
    role_ids: tuple[int, ...] = (),
    manage_roles: bool = True,
):
    roles = [SimpleNamespace(id=role_id) for role_id in role_ids]
    bot_member = SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=manage_roles))
    guild = SimpleNamespace(id=123, owner_id=owner_id, me=bot_member)
    return SimpleNamespace(id=member_id, bot=bot, guild=guild, roles=roles)


@pytest.mark.asyncio
async def test_registration_gate_protects_owner_bots_and_explicit_bypass() -> None:
    system = object.__new__(RegistrationGateSystem)
    system.services = SimpleNamespace(
        settings=FakeSettings(
            {
                "registration_bypass_user_ids": [20],
                "registration_bypass_role_ids": [30],
            }
        )
    )
    assert await system._protected(fake_member(member_id=999, owner_id=999))
    assert await system._protected(fake_member(bot=True))
    assert await system._protected(fake_member(member_id=20))
    assert await system._protected(fake_member(role_ids=(30,)))
    assert not await system._protected(fake_member(member_id=21))


@pytest.mark.asyncio
async def test_registration_gate_persists_sync_failure_without_manage_roles() -> None:
    gate = SimpleNamespace(
        status=AsyncMock(),
        mark_sync=AsyncMock(),
        record_finding=AsyncMock(),
    )
    system = object.__new__(RegistrationGateSystem)
    system.services = SimpleNamespace(
        settings=FakeSettings(
            {
                "registration_gate_enabled": True,
                "registration_bypass_user_ids": [],
                "registration_bypass_role_ids": [],
            }
        ),
        registration_gate=gate,
    )
    system._locks = {}
    member = fake_member(manage_roles=False)
    record = {"id": 77, "status": "REGISTERED", "member_id": 1}

    assert not await system.sync_member_access(member, record)
    gate.mark_sync.assert_awaited_once()
    assert gate.mark_sync.await_args.kwargs["success"] is False
    gate.record_finding.assert_awaited_once()
    assert gate.record_finding.await_args.args[1] == "BOT_PERMISSION_ERROR"
    assert system._locks == {}


@pytest.mark.asyncio
async def test_rank_compliance_expiration_removes_only_originating_rank_role() -> None:
    rank_role = SimpleNamespace(id=501, name="Major")
    unrelated_role = SimpleNamespace(id=502, name="Companheiro de Farda")

    class Member:
        id = 10
        bot = False

        def __init__(self) -> None:
            self.roles = [rank_role, unrelated_role]

        async def remove_roles(self, *roles, reason: str) -> None:
            assert reason
            removed = {role.id for role in roles}
            self.roles = [role for role in self.roles if role.id not in removed]

    member = Member()

    class Guild:
        id = 123

        def get_member(self, discord_id: int):
            return member if discord_id == member.id else None

        def get_role(self, role_id: int):
            return {rank_role.id: rank_role, unrelated_role.id: unrelated_role}.get(role_id)

    pending = {"id": 91, "discord_id": member.id, "rank_role_id": rank_role.id}
    gate = SimpleNamespace(
        pending_rank_compliance_notifications=AsyncMock(return_value=[]),
        expired_rank_compliance=AsyncMock(return_value=[pending]),
        claim_rank_compliance_expiration=AsyncMock(return_value=pending),
        finalize_rank_compliance_expiration=AsyncMock(),
        cancel_obsolete_rank_compliance=AsyncMock(),
    )
    system = object.__new__(RegistrationGateSystem)
    system.services = SimpleNamespace(
        settings=FakeSettings({"registration_rank_compliance_enabled": True}),
        registration_gate=gate,
    )

    result = await system.process_rank_compliance(Guild())

    assert result == {"notified": 0, "expired": 1, "failed": 0}
    assert [role.id for role in member.roles] == [unrelated_role.id]
    gate.finalize_rank_compliance_expiration.assert_awaited_once_with(
        pending["id"],
        removed=True,
        reason="Prazo expirado sem cadastro aprovado; somente a patente foi removida.",
    )
