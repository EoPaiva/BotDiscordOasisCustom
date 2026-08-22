from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemberStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    AWAY = "AWAY"
    RESERVE = "RESERVE"
    SUSPENDED = "SUSPENDED"
    DISMISSED = "DISMISSED"


class ShiftStatus(StrEnum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CLOSED = "CLOSED"


class RbacProfile(StrEnum):
    CANDIDATE = "CANDIDATO"
    RECRUIT = "RECRUTA"
    MEMBER = "MEMBRO"
    GRADUATE = "GRADUADO"
    INSTRUCTOR = "INSTRUTOR"
    SUPERVISOR = "SUPERVISOR"
    COMMAND = "COMANDO"
    HIGH_COMMAND = "ALTO_COMANDO"
    ADMIN = "ADMINISTRADOR"


RBAC_PROFILE_METADATA: dict[RbacProfile, tuple[str, int]] = {
    RbacProfile.CANDIDATE: ("Candidato", 10),
    RbacProfile.RECRUIT: ("Recruta", 20),
    RbacProfile.MEMBER: ("Membro", 30),
    RbacProfile.GRADUATE: ("Graduado", 40),
    RbacProfile.INSTRUCTOR: ("Instrutor", 45),
    RbacProfile.SUPERVISOR: ("Supervisor", 50),
    RbacProfile.COMMAND: ("Comando", 70),
    RbacProfile.HIGH_COMMAND: ("Alto Comando", 90),
    RbacProfile.ADMIN: ("Administrador técnico", 100),
}


class PersonnelActionType(StrEnum):
    PROMOTION = "PROMOTION"
    DEMOTION = "DEMOTION"


class PunishmentType(StrEnum):
    WARNING = "WARNING"
    SUSPENSION = "SUSPENSION"
    DISMISSAL = "DISMISSAL"


class AbsenceStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ENDED = "ENDED"


class AdministrativeRequestType(StrEnum):
    EARLY_RETURN = "EARLY_RETURN"
    RESERVE_ENTRY = "RESERVE_ENTRY"
    RESERVE_EXIT = "RESERVE_EXIT"
    HOURS_CORRECTION = "HOURS_CORRECTION"
    DATA_CHANGE = "DATA_CHANGE"
    DISMISSAL = "DISMISSAL"


class AdministrativeRequestStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class ShiftResult:
    shift_id: int
    status: ShiftStatus
    started_at: int
    voice_channel_id: int | None
    grace_deadline: int | None = None
    validation_status: str | None = None
    patrol_duration_ms: int = 0
    minimum_patrol_ms: int = 0
