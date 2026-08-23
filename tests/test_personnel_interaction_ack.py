from __future__ import annotations

from types import SimpleNamespace

import pytest

import cogs.personnel_commands as personnel_commands
from choque.errors import NotFoundError


@pytest.mark.asyncio
async def test_registration_decision_acknowledges_discord_before_database_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Response:
        def __init__(self) -> None:
            self.done = False

        async def defer(self, **_: object) -> None:
            self.done = True
            events.append("defer")

        def is_done(self) -> bool:
            return self.done

    class RegistrationGate:
        async def get(self, _: int):
            events.append("database")
            return None

    response = Response()
    interaction = SimpleNamespace(
        response=response,
        client=SimpleNamespace(
            services=SimpleNamespace(registration_gate=RegistrationGate())
        ),
    )

    async def require_permission(_interaction, _permission):
        assert response.is_done() is True
        events.append("permission")
        return SimpleNamespace(guild=SimpleNamespace(id=1))

    monkeypatch.setattr(
        personnel_commands, "require_registration_permission", require_permission
    )
    modal = personnel_commands.GateApprovalModal(999, action="APPROVE")

    with pytest.raises(NotFoundError):
        await modal.on_submit(interaction)

    assert events == ["defer", "permission", "database"]
