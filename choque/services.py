from __future__ import annotations

from dataclasses import dataclass

from .activity import ActivityService
from .audit import AuditService
from .career import CareerService
from .database import Database
from .discipline import DisciplineService
from .duty_patrols import DutyPatrolService
from .financial_aid import FinancialAidService
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
from .status import StatusService
from .tags import TagService
from .tickets import TicketService
from .training import TrainingService


@dataclass(slots=True, kw_only=True)
class Services:
    database: Database
    settings: SettingsService
    audit: AuditService
    permissions: PermissionService
    members: MemberService
    modules: ModuleFlagService
    shifts: ShiftService
    personnel: PersonnelService
    career: CareerService
    discipline: DisciplineService
    training: TrainingService
    activity: ActivityService
    requests: RequestService
    tickets: TicketService
    rank_sync: RankSyncService
    operations: OperationsService
    duty_patrols: DutyPatrolService
    financial_aid: FinancialAidService
    recruitment: RecruitmentService
    recruitment_analysis: RecruitmentAnalysisService
    registration_gate: RegistrationGateService
    tags: TagService
    status: StatusService
    security: SecurityService
