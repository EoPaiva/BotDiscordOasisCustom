from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from choque.activity import ActivityService
from choque.audit import AuditService
from choque.config import Branding
from choque.database import Database
from choque.discipline import DisciplineService
from choque.members import MemberService
from choque.module_flags import ModuleFlagService
from choque.operations import OperationsService
from choque.personnel import PersonnelService
from choque.rank_sync import RankSyncService
from choque.rbac import PermissionService
from choque.recruitment import RecruitmentService
from choque.recruitment_analysis import RecruitmentAnalysisService
from choque.registration_gate import RegistrationGateService
from choque.requests import RequestService
from choque.security import SecurityService
from choque.settings import SettingsService
from choque.shifts import ShiftService
from choque.tickets import TicketService
from choque.training import TrainingService


@dataclass(slots=True)
class CommandCenterServices:
    database: Database
    settings: SettingsService
    audit: AuditService
    permissions: PermissionService
    members: MemberService
    modules: ModuleFlagService
    shifts: ShiftService
    personnel: PersonnelService
    discipline: DisciplineService
    training: TrainingService
    activity: ActivityService
    requests: RequestService
    tickets: TicketService
    rank_sync: RankSyncService
    operations: OperationsService
    recruitment: RecruitmentService
    recruitment_analysis: RecruitmentAnalysisService
    registration_gate: RegistrationGateService
    security: SecurityService

    @classmethod
    async def open(cls, database_path: Path) -> CommandCenterServices:
        database = Database(database_path)
        await database.open()
        settings = SettingsService(database)
        audit = AuditService(database, settings, Branding())
        members = MemberService(database, audit)
        modules = ModuleFlagService(database, settings, audit)
        permissions = PermissionService(settings)
        shifts = ShiftService(database, settings, audit)
        personnel = PersonnelService(database, audit)
        discipline = DisciplineService(database, audit)
        training = TrainingService(database, audit)
        activity = ActivityService(database, settings, audit, shifts)
        requests = RequestService(database, audit)
        tickets = TicketService(database, audit, members)
        rank_sync = RankSyncService(database, settings, audit)
        operations = OperationsService(database, settings, audit, shifts)
        recruitment_secret = (
            os.getenv("RECRUITMENT_TOKEN_SECRET")
            or os.getenv("COMMAND_CENTER_INTERNAL_SECRET")
            or "local-recruitment-token-secret"
        )
        if os.getenv("APP_ENV") == "production" and len(recruitment_secret) < 32:
            raise RuntimeError("RECRUITMENT_TOKEN_SECRET deve possuir ao menos 32 caracteres.")
        recruitment = RecruitmentService(
            database,
            audit,
            token_secret=recruitment_secret,
        )
        recruitment_analysis = RecruitmentAnalysisService(database, settings, audit)
        registration_gate = RegistrationGateService(database, settings, audit)
        security = SecurityService(database, settings, audit)
        recruitment.analysis_service = recruitment_analysis
        return cls(
            database,
            settings,
            audit,
            permissions,
            members,
            modules,
            shifts,
            personnel,
            discipline,
            training,
            activity,
            requests,
            tickets,
            rank_sync,
            operations,
            recruitment,
            recruitment_analysis,
            registration_gate,
            security,
        )

    async def close(self) -> None:
        await self.shifts.close()
        await self.database.close()
