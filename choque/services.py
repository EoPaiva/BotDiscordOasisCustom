from __future__ import annotations

from dataclasses import dataclass

from .activity import ActivityService
from .audit import AuditService
from .database import Database
from .discipline import DisciplineService
from .members import MemberService
from .module_flags import ModuleFlagService
from .operations import OperationsService
from .personnel import PersonnelService
from .rank_sync import RankSyncService
from .rbac import PermissionService
from .recruitment import RecruitmentService
from .recruitment_analysis import RecruitmentAnalysisService
from .registration_gate import RegistrationGateService
from .requests import RequestService
from .security import SecurityService
from .settings import SettingsService
from .shifts import ShiftService
from .tickets import TicketService
from .training import TrainingService


@dataclass(slots=True)
class Services:
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
