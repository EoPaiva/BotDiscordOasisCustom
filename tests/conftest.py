from __future__ import annotations

from dataclasses import dataclass

import pytest_asyncio

from choque.activity import ActivityService
from choque.audit import AuditService
from choque.career import CareerService
from choque.config import Branding
from choque.database import Database
from choque.discipline import DisciplineService
from choque.duty_patrols import DutyPatrolService
from choque.financial_aid import FinancialAidService
from choque.members import MemberService
from choque.module_flags import ModuleFlagService
from choque.operations import OperationsService
from choque.personnel import PersonnelService
from choque.rank_sync import RankSyncService
from choque.rbac import PermissionService
from choque.registration_gate import RegistrationGateService
from choque.requests import RequestService
from choque.settings import SettingsService
from choque.shifts import ShiftService
from choque.tickets import TicketService
from choque.training import TrainingService

GUILD_ID = 123
DISCORD_ID = 456
CALL_A = 1001
CALL_B = 1002


@dataclass
class MutableClock:
    value: int = 1_700_000_000_000

    def __call__(self) -> int:
        return self.value

    def advance(self, milliseconds: int) -> None:
        self.value += milliseconds


@pytest_asyncio.fixture
async def service_bundle(tmp_path):
    database = Database(tmp_path / "choque.db")
    await database.open()
    settings = SettingsService(database)
    audit = AuditService(database, settings, Branding())
    members = MemberService(database, audit)
    modules = ModuleFlagService(database, settings, audit)
    permissions = PermissionService(settings)
    clock = MutableClock()
    shifts = ShiftService(database, settings, audit, clock=clock)
    personnel = PersonnelService(database, audit, clock=clock)
    career = CareerService(database, settings, audit, personnel, shifts, clock=clock)
    discipline = DisciplineService(database, audit, clock=clock)
    training = TrainingService(database, audit, clock=clock)
    activity = ActivityService(database, settings, audit, shifts, clock=clock)
    requests = RequestService(database, audit, clock=clock)
    tickets = TicketService(database, audit, members, clock=clock)
    rank_sync = RankSyncService(database, settings, audit, clock=clock)
    operations = OperationsService(database, settings, audit, shifts, clock=clock)
    duty_patrols = DutyPatrolService(
        database, settings, audit, shifts, operations, clock=clock
    )
    registration_gate = RegistrationGateService(database, settings, audit)
    financial_aid = FinancialAidService(database, settings, audit, clock=clock)
    await settings.add_voice_channel(GUILD_ID, CALL_A, "Call A", DISCORD_ID)
    await settings.add_voice_channel(GUILD_ID, CALL_B, "Call B", DISCORD_ID)
    await settings.set(GUILD_ID, "grace_period_seconds", 60, DISCORD_ID)
    # Existing unit scenarios exercise the original shift state machine with
    # very short synthetic durations. Phase-14 tests opt into the production
    # minimum explicitly.
    await settings.set(GUILD_ID, "minimum_patrol_minutes", 0, DISCORD_ID)
    await members.create_or_update(
        GUILD_ID,
        DISCORD_ID,
        discord_nick="Discord User",
        mta_nick="Choque_User",
        character_id="77",
        unit="BGR",
        rank_id=None,
        actor_id=DISCORD_ID,
    )
    yield {
        "database": database,
        "settings": settings,
        "audit": audit,
        "members": members,
        "modules": modules,
        "permissions": permissions,
        "clock": clock,
        "shifts": shifts,
        "personnel": personnel,
        "career": career,
        "discipline": discipline,
        "training": training,
        "activity": activity,
        "requests": requests,
        "tickets": tickets,
        "rank_sync": rank_sync,
        "operations": operations,
        "duty_patrols": duty_patrols,
        "registration_gate": registration_gate,
        "financial_aid": financial_aid,
    }
    await shifts.close()
    await database.close()
