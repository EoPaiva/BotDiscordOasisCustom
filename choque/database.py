from __future__ import annotations

import asyncio
import contextvars
import inspect
import logging
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

LOGGER = logging.getLogger(__name__)


MIGRATION_001 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER NOT NULL,
    setting_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    updated_by INTEGER,
    PRIMARY KEY (guild_id, setting_key)
);

CREATE TABLE IF NOT EXISTS authorized_voice_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    label TEXT,
    created_at INTEGER NOT NULL,
    created_by INTEGER,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS rbac_bindings (
    guild_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    profile TEXT NOT NULL CHECK (profile IN ('MEMBRO','GRADUADO','INSTRUTOR','COMANDO','ADMINISTRADOR')),
    created_at INTEGER NOT NULL,
    created_by INTEGER,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS ranks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL DEFAULT '',
    level INTEGER NOT NULL,
    discord_role_id INTEGER,
    rbac_profile TEXT NOT NULL DEFAULT 'MEMBRO',
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    UNIQUE (guild_id, level),
    UNIQUE (guild_id, discord_role_id)
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    discord_id INTEGER NOT NULL,
    discord_nick TEXT,
    mta_nick TEXT NOT NULL,
    character_id TEXT,
    rank_id INTEGER REFERENCES ranks(id),
    unit TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('PENDING','ACTIVE','AWAY','RESERVE','SUSPENDED','DISMISSED')),
    joined_at INTEGER NOT NULL,
    notes TEXT,
    last_activity_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE (guild_id, discord_id)
);

CREATE TABLE IF NOT EXISTS member_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    discord_id INTEGER NOT NULL,
    mta_nick TEXT NOT NULL,
    character_id TEXT,
    unit TEXT,
    recruiter TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    submitted_at INTEGER NOT NULL,
    reviewed_at INTEGER,
    reviewed_by INTEGER,
    review_reason TEXT
);

CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','GRACE','REVIEW_REQUIRED','CLOSED')),
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    closed_at INTEGER,
    end_reason TEXT,
    grace_started_at INTEGER,
    grace_deadline INTEGER,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS shift_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE RESTRICT,
    voice_channel_id INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    end_reason TEXT
);

CREATE TABLE IF NOT EXISTS shift_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE RESTRICT,
    delta_ms INTEGER NOT NULL,
    reason TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS voice_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER,
    shift_id INTEGER,
    discord_id INTEGER NOT NULL,
    before_channel_id INTEGER,
    after_channel_id INTEGER,
    event_type TEXT NOT NULL,
    occurred_at INTEGER NOT NULL,
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id TEXT NOT NULL UNIQUE,
    guild_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor_id INTEGER,
    target_id INTEGER,
    before_json TEXT,
    after_json TEXT,
    reason TEXT,
    created_at INTEGER NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (delivery_status IN ('PENDING','DELIVERED','FAILED')),
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    delivered_at INTEGER,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS panels (
    guild_id INTEGER NOT NULL,
    panel_type TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, panel_type)
);

CREATE TABLE IF NOT EXISTS bot_runtime (
    guild_id INTEGER PRIMARY KEY,
    last_heartbeat_at INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    clean_shutdown INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_active_shift_per_member
ON shifts(guild_id, member_id)
WHERE status IN ('ACTIVE', 'GRACE');

CREATE UNIQUE INDEX IF NOT EXISTS ux_open_segment_per_shift
ON shift_segments(shift_id)
WHERE ended_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_members_discord ON members(guild_id, discord_id);
CREATE INDEX IF NOT EXISTS ix_members_status ON members(guild_id, status);
CREATE INDEX IF NOT EXISTS ix_shifts_member_started ON shifts(member_id, started_at);
CREATE INDEX IF NOT EXISTS ix_shifts_status ON shifts(guild_id, status);
CREATE INDEX IF NOT EXISTS ix_segments_shift_started ON shift_segments(shift_id, started_at);
CREATE INDEX IF NOT EXISTS ix_voice_events_member_time ON voice_events(guild_id, discord_id, occurred_at);
CREATE INDEX IF NOT EXISTS ix_audit_delivery ON audit_logs(delivery_status, created_at);
"""

MIGRATION_002 = """
ALTER TABLE shift_segments RENAME TO shift_segments_v1;

CREATE TABLE shift_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE RESTRICT,
    voice_channel_id INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    end_reason TEXT
);

INSERT INTO shift_segments(id, guild_id, shift_id, voice_channel_id, started_at, ended_at, end_reason)
SELECT ss.id, s.guild_id, ss.shift_id, ss.voice_channel_id, ss.started_at, ss.ended_at, ss.end_reason
FROM shift_segments_v1 ss JOIN shifts s ON s.id=ss.shift_id;

DROP TABLE shift_segments_v1;

ALTER TABLE shift_adjustments RENAME TO shift_adjustments_v1;

CREATE TABLE shift_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE RESTRICT,
    delta_ms INTEGER NOT NULL,
    reason TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

INSERT INTO shift_adjustments(id, guild_id, shift_id, delta_ms, reason, actor_id, created_at)
SELECT sa.id, s.guild_id, sa.shift_id, sa.delta_ms, sa.reason, sa.actor_id, sa.created_at
FROM shift_adjustments_v1 sa JOIN shifts s ON s.id=sa.shift_id;

DROP TABLE shift_adjustments_v1;

CREATE UNIQUE INDEX ux_open_segment_per_shift
ON shift_segments(shift_id)
WHERE ended_at IS NULL;

CREATE INDEX ix_segments_guild_shift_started
ON shift_segments(guild_id, shift_id, started_at);

CREATE INDEX ix_adjustments_guild_shift
ON shift_adjustments(guild_id, shift_id);
"""

MIGRATION_003 = """
CREATE TABLE personnel_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('PROMOTION','DEMOTION')),
    from_rank_id INTEGER REFERENCES ranks(id),
    to_rank_id INTEGER NOT NULL REFERENCES ranks(id),
    reason TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE punishments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    punishment_type TEXT NOT NULL CHECK (
        punishment_type IN ('WARNING','SUSPENSION','DISMISSAL')
    ),
    reason TEXT NOT NULL,
    previous_member_status TEXT,
    starts_at INTEGER NOT NULL,
    ends_at INTEGER,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (
        status IN ('ACTIVE','REVOKED','EXPIRED')
    ),
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    revoked_by INTEGER,
    revoked_at INTEGER,
    revoke_reason TEXT
);

CREATE TABLE absence_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    starts_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','APPROVED','REJECTED','CANCELLED','ENDED')
    ),
    submitted_at INTEGER NOT NULL,
    reviewed_by INTEGER,
    reviewed_at INTEGER,
    review_reason TEXT,
    cancelled_at INTEGER,
    ended_at INTEGER
);

CREATE INDEX ix_personnel_actions_member_time
ON personnel_actions(guild_id, discord_id, created_at DESC);

CREATE INDEX ix_punishments_member_status
ON punishments(guild_id, discord_id, status, created_at DESC);

CREATE INDEX ix_absences_status_time
ON absence_requests(guild_id, status, starts_at, ends_at);

CREATE UNIQUE INDEX ux_open_absence_per_member
ON absence_requests(guild_id, member_id)
WHERE status IN ('PENDING','APPROVED');
"""

MIGRATION_004 = """
ALTER TABLE absence_requests ADD COLUMN observation TEXT;
ALTER TABLE absence_requests ADD COLUMN previous_member_status TEXT;

CREATE TABLE administrative_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    request_type TEXT NOT NULL CHECK (
        request_type IN (
            'EARLY_RETURN','RESERVE_ENTRY','RESERVE_EXIT',
            'HOURS_CORRECTION','DATA_CHANGE','DISMISSAL'
        )
    ),
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','APPROVED','REJECTED','CANCELLED')
    ),
    submitted_at INTEGER NOT NULL,
    reviewed_by INTEGER,
    reviewed_at INTEGER,
    review_reason TEXT,
    applied_at INTEGER,
    cancelled_at INTEGER
);

CREATE UNIQUE INDEX ux_pending_administrative_request
ON administrative_requests(guild_id, member_id, request_type)
WHERE status='PENDING';

CREATE INDEX ix_administrative_requests_queue
ON administrative_requests(guild_id, status, submitted_at);

CREATE INDEX ix_administrative_requests_member
ON administrative_requests(guild_id, discord_id, submitted_at DESC);
"""

MIGRATION_005 = """
DROP INDEX IF EXISTS ix_punishments_member_status;

ALTER TABLE punishments RENAME TO punishments_v4;

CREATE TABLE punishments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    punishment_type TEXT NOT NULL CHECK (
        punishment_type IN ('WARNING','SUSPENSION','DISMISSAL')
    ),
    warning_type TEXT,
    reason TEXT NOT NULL,
    evidence_url TEXT,
    observation TEXT,
    previous_member_status TEXT,
    starts_at INTEGER NOT NULL,
    ends_at INTEGER,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (
        status IN ('SCHEDULED','ACTIVE','FULFILLED','REVOKED','EXPIRED')
    ),
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    fulfilled_by INTEGER,
    fulfilled_at INTEGER,
    fulfilled_reason TEXT,
    revoked_by INTEGER,
    revoked_at INTEGER,
    revoke_reason TEXT
);

INSERT INTO punishments(
    id, guild_id, member_id, discord_id, punishment_type, reason,
    previous_member_status, starts_at, ends_at, status, created_by, created_at,
    revoked_by, revoked_at, revoke_reason
)
SELECT
    id, guild_id, member_id, discord_id, punishment_type, reason,
    previous_member_status, starts_at, ends_at, status, created_by, created_at,
    revoked_by, revoked_at, revoke_reason
FROM punishments_v4;

DROP TABLE punishments_v4;

CREATE INDEX ix_punishments_member_status
ON punishments(guild_id, discord_id, status, created_at DESC);

CREATE UNIQUE INDEX ux_open_suspension_per_member
ON punishments(guild_id, member_id)
WHERE punishment_type='SUSPENSION' AND status IN ('SCHEDULED','ACTIVE');

CREATE TABLE disciplinary_occurrences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    evidence_url TEXT,
    observation TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (
        status IN ('OPEN','ARCHIVED','CONVERTED_TO_WARNING')
    ),
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    archived_by INTEGER,
    archived_at INTEGER,
    archive_reason TEXT,
    converted_punishment_id INTEGER REFERENCES punishments(id) ON DELETE RESTRICT,
    converted_by INTEGER,
    converted_at INTEGER
);

CREATE INDEX ix_disciplinary_occurrences_member
ON disciplinary_occurrences(guild_id, discord_id, created_at DESC);

CREATE INDEX ix_disciplinary_occurrences_status
ON disciplinary_occurrences(guild_id, status, created_at);
"""

MIGRATION_006 = """
CREATE TABLE training_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    scheduled_at INTEGER NOT NULL,
    responsible_id INTEGER NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity BETWEEN 1 AND 100),
    course_name TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (
        status IN ('OPEN','CLOSED','COMPLETED','CANCELLED')
    ),
    channel_id INTEGER,
    message_id INTEGER,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    enrollment_closed_at INTEGER,
    completed_by INTEGER,
    completed_at INTEGER,
    cancelled_by INTEGER,
    cancelled_at INTEGER,
    cancel_reason TEXT,
    UNIQUE(guild_id, name, scheduled_at)
);

CREATE TABLE training_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    training_id INTEGER NOT NULL REFERENCES training_events(id) ON DELETE RESTRICT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    enrollment_status TEXT NOT NULL DEFAULT 'ENROLLED' CHECK (
        enrollment_status IN ('ENROLLED','CANCELLED')
    ),
    attendance_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        attendance_status IN ('PENDING','PRESENT','ABSENT')
    ),
    result_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        result_status IN ('PENDING','APPROVED','FAILED')
    ),
    enrolled_at INTEGER NOT NULL,
    cancelled_at INTEGER,
    decided_by INTEGER,
    decided_at INTEGER,
    decision_notes TEXT,
    UNIQUE(training_id, member_id)
);

CREATE TABLE member_qualifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    training_id INTEGER REFERENCES training_events(id) ON DELETE RESTRICT,
    course_name TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('APPROVED','FAILED')),
    responsible_id INTEGER NOT NULL,
    recorded_at INTEGER NOT NULL,
    notes TEXT,
    UNIQUE(training_id, member_id)
);

CREATE INDEX ix_training_events_status_time
ON training_events(guild_id, status, scheduled_at);

CREATE INDEX ix_training_enrollments_member
ON training_enrollments(guild_id, discord_id, enrolled_at DESC);

CREATE INDEX ix_training_enrollments_event
ON training_enrollments(training_id, enrollment_status, attendance_status);

CREATE INDEX ix_member_qualifications_member
ON member_qualifications(guild_id, discord_id, recorded_at DESC);
"""

MIGRATION_007 = """
CREATE TABLE weekly_activity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    week_start_at INTEGER NOT NULL,
    week_end_at INTEGER NOT NULL,
    total_ms INTEGER NOT NULL,
    goal_minutes INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('FULFILLED','NEAR','NOT_MET','EXEMPT')
    ),
    exemption_reason TEXT,
    member_status_at_close TEXT NOT NULL,
    closed_by INTEGER,
    created_at INTEGER NOT NULL,
    UNIQUE(guild_id, member_id, week_start_at)
);

CREATE INDEX ix_weekly_activity_member
ON weekly_activity_snapshots(guild_id, discord_id, week_start_at DESC);

CREATE INDEX ix_weekly_activity_period_status
ON weekly_activity_snapshots(guild_id, week_start_at, status);
"""

MIGRATION_008 = """
CREATE TABLE service_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    discord_id INTEGER NOT NULL,
    ticket_type TEXT NOT NULL CHECK (ticket_type IN ('CANDIDACY','TRANSFER','REPORT')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','IN_REVIEW','APPROVED','REJECTED','CANCELLED','CLOSED')
    ),
    subject_discord_id INTEGER,
    payload_json TEXT NOT NULL,
    submitted_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    claimed_by INTEGER,
    claimed_at INTEGER,
    reviewed_by INTEGER,
    reviewed_at INTEGER,
    review_reason TEXT,
    member_application_id INTEGER REFERENCES member_applications(id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ux_open_service_ticket
ON service_tickets(guild_id, discord_id, ticket_type)
WHERE status IN ('PENDING','IN_REVIEW');

CREATE INDEX ix_service_tickets_queue
ON service_tickets(guild_id, ticket_type, status, submitted_at);

CREATE INDEX ix_service_tickets_requester
ON service_tickets(guild_id, discord_id, submitted_at DESC);
"""

MIGRATION_009 = """
CREATE TABLE service_tickets_v9 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    discord_id INTEGER NOT NULL,
    ticket_type TEXT NOT NULL CHECK (
        ticket_type IN ('CANDIDACY','TRANSFER','REPORT','OTHER')
    ),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','IN_REVIEW','APPROVED','REJECTED','CANCELLED','CLOSED')
    ),
    subject_discord_id INTEGER,
    payload_json TEXT NOT NULL,
    submitted_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    claimed_by INTEGER,
    claimed_at INTEGER,
    reviewed_by INTEGER,
    reviewed_at INTEGER,
    review_reason TEXT,
    member_application_id INTEGER REFERENCES member_applications(id) ON DELETE RESTRICT
);

INSERT INTO service_tickets_v9(
    id, guild_id, discord_id, ticket_type, status, subject_discord_id,
    payload_json, submitted_at, updated_at, claimed_by, claimed_at,
    reviewed_by, reviewed_at, review_reason, member_application_id
)
SELECT
    id, guild_id, discord_id, ticket_type, status, subject_discord_id,
    payload_json, submitted_at, updated_at, claimed_by, claimed_at,
    reviewed_by, reviewed_at, review_reason, member_application_id
FROM service_tickets;

DROP TABLE service_tickets;
ALTER TABLE service_tickets_v9 RENAME TO service_tickets;

CREATE UNIQUE INDEX ux_open_service_ticket
ON service_tickets(guild_id, discord_id, ticket_type)
WHERE status IN ('PENDING','IN_REVIEW');

CREATE INDEX ix_service_tickets_queue
ON service_tickets(guild_id, ticket_type, status, submitted_at);

CREATE INDEX ix_service_tickets_requester
ON service_tickets(guild_id, discord_id, submitted_at DESC);
"""

MIGRATION_010 = """
ALTER TABLE members ADD COLUMN rank_sync_status TEXT NOT NULL DEFAULT 'SYNCED'
    CHECK (rank_sync_status IN ('SYNCED','MISSING_ROLE','MULTIPLE_RANKS','ERROR'));
ALTER TABLE members ADD COLUMN rank_sync_checked_at INTEGER;

CREATE TABLE rank_sync_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK (
        event_type IN ('PROMOTION','DEMOTION','SYNC','MISSING_ROLE','INCONSISTENCY')
    ),
    source TEXT NOT NULL,
    from_rank_id INTEGER REFERENCES ranks(id),
    to_rank_id INTEGER REFERENCES ranks(id),
    actor_id INTEGER,
    role_ids_json TEXT NOT NULL,
    previous_nickname TEXT,
    expected_nickname TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_rank_sync_member_time
ON rank_sync_events(guild_id, discord_id, created_at DESC);

CREATE INDEX ix_rank_sync_source_time
ON rank_sync_events(guild_id, source, created_at DESC);
"""

MIGRATION_011 = """
CREATE TABLE ticket_rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    ticket_id INTEGER NOT NULL REFERENCES service_tickets(id) ON DELETE RESTRICT,
    requester_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    control_message_id INTEGER,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED','ARCHIVED')),
    created_at INTEGER NOT NULL,
    closed_by INTEGER,
    closed_at INTEGER,
    close_reason TEXT,
    archived_at INTEGER,
    UNIQUE(guild_id, ticket_id),
    UNIQUE(guild_id, channel_id)
);

CREATE INDEX ix_ticket_rooms_status
ON ticket_rooms(guild_id, status, created_at);
"""

MIGRATION_012 = """
ALTER TABLE member_applications ADD COLUMN review_channel_id INTEGER;
ALTER TABLE member_applications ADD COLUMN review_message_id INTEGER;
ALTER TABLE member_applications ADD COLUMN result_channel_id INTEGER;
ALTER TABLE member_applications ADD COLUMN result_message_id INTEGER;
ALTER TABLE member_applications ADD COLUMN delivery_status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (delivery_status IN ('PENDING','DELIVERED','LEGACY'));

UPDATE member_applications
SET delivery_status='LEGACY'
WHERE status IN ('APPROVED','REJECTED');

CREATE INDEX ix_member_applications_delivery
ON member_applications(guild_id, status, delivery_status, submitted_at);
"""

MIGRATION_013 = """
CREATE TABLE course_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    internal_code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    course_role_id INTEGER NOT NULL,
    course_role_name TEXT NOT NULL,
    passing_score INTEGER NOT NULL CHECK (passing_score BETWEEN 0 AND 100),
    cooldown_days INTEGER NOT NULL DEFAULT 14 CHECK (cooldown_days BETWEEN 0 AND 365),
    enrollment_status TEXT NOT NULL DEFAULT 'CLOSED' CHECK (
        enrollment_status IN ('OPEN','CLOSED')
    ),
    notes TEXT,
    source_channel_id INTEGER NOT NULL,
    source_message_id INTEGER NOT NULL,
    source_content_sha256 TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, internal_code),
    UNIQUE(guild_id, course_role_id),
    UNIQUE(guild_id, source_channel_id, source_message_id)
);

CREATE TABLE course_requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL REFERENCES course_catalog(id) ON DELETE RESTRICT,
    required_role_id INTEGER NOT NULL,
    required_role_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(course_id, required_role_id)
);

CREATE TABLE course_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL REFERENCES course_catalog(id) ON DELETE RESTRICT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','APPROVED','REJECTED','CANCELLED')
    ),
    eligibility_json TEXT NOT NULL,
    submitted_at INTEGER NOT NULL,
    decided_by INTEGER,
    decided_at INTEGER,
    decision_reason TEXT
);

CREATE UNIQUE INDEX uq_course_applications_pending
ON course_applications(guild_id, course_id, member_id)
WHERE status='PENDING';

CREATE INDEX ix_course_catalog_status
ON course_catalog(guild_id, active, enrollment_status, internal_code);

CREATE INDEX ix_course_requirements_course
ON course_requirements(guild_id, course_id, active, sort_order);

CREATE INDEX ix_course_applications_status
ON course_applications(guild_id, status, submitted_at, id);

CREATE INDEX ix_course_applications_member
ON course_applications(guild_id, discord_id, submitted_at DESC, id DESC);
"""

MIGRATION_014 = """
ALTER TABLE authorized_voice_channels
ADD COLUMN service_allowed INTEGER NOT NULL DEFAULT 1 CHECK (service_allowed IN (0,1));

ALTER TABLE authorized_voice_channels
ADD COLUMN counts_toward_patrol_minimum INTEGER NOT NULL DEFAULT 1
    CHECK (counts_toward_patrol_minimum IN (0,1));

ALTER TABLE shift_segments
ADD COLUMN counts_toward_patrol_minimum INTEGER NOT NULL DEFAULT 1
    CHECK (counts_toward_patrol_minimum IN (0,1));

ALTER TABLE shifts ADD COLUMN minimum_patrol_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE shifts ADD COLUMN patrol_duration_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE shifts ADD COLUMN gross_duration_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE shifts ADD COLUMN patrol_requirement_met_at INTEGER;
ALTER TABLE shifts ADD COLUMN validation_status TEXT NOT NULL DEFAULT 'VALID' CHECK (
    validation_status IN ('PENDING','VALID','INVALIDATED','REVIEW_REQUIRED')
);
ALTER TABLE shifts ADD COLUMN automatic_validation_status TEXT NOT NULL DEFAULT 'VALID' CHECK (
    automatic_validation_status IN ('PENDING','VALID','INVALIDATED','REVIEW_REQUIRED')
);
ALTER TABLE shifts ADD COLUMN invalid_reason TEXT;
ALTER TABLE shifts ADD COLUMN validation_source TEXT NOT NULL DEFAULT 'LEGACY' CHECK (
    validation_source IN ('AUTO','ADMIN_OVERRIDE','LEGACY')
);
ALTER TABLE shifts ADD COLUMN validated_by INTEGER;
ALTER TABLE shifts ADD COLUMN validated_at INTEGER;
ALTER TABLE shifts ADD COLUMN validation_reason TEXT;

UPDATE shifts
SET patrol_duration_ms = COALESCE((
        SELECT SUM(MAX(0, COALESCE(ss.ended_at, shifts.ended_at, ss.started_at) - ss.started_at))
        FROM shift_segments ss
        WHERE ss.shift_id=shifts.id AND ss.counts_toward_patrol_minimum=1
    ), 0),
    gross_duration_ms = MAX(0, COALESCE(ended_at, started_at) - started_at),
    validation_status = CASE
        WHEN status IN ('ACTIVE','GRACE') THEN 'PENDING'
        WHEN status='REVIEW_REQUIRED' THEN 'REVIEW_REQUIRED'
        ELSE 'VALID'
    END,
    automatic_validation_status = CASE
        WHEN status IN ('ACTIVE','GRACE') THEN 'PENDING'
        WHEN status='REVIEW_REQUIRED' THEN 'REVIEW_REQUIRED'
        ELSE 'VALID'
    END,
    validation_source = CASE
        WHEN status IN ('ACTIVE','GRACE','REVIEW_REQUIRED') THEN 'AUTO'
        ELSE 'LEGACY'
    END;

CREATE TABLE shift_validation_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE RESTRICT,
    actor_id INTEGER NOT NULL,
    previous_validation_status TEXT NOT NULL,
    resulting_validation_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_shift_validation_status
ON shifts(guild_id, validation_status, started_at DESC);

CREATE INDEX ix_shift_validation_overrides_shift
ON shift_validation_overrides(guild_id, shift_id, created_at DESC);
"""

MIGRATION_015 = """
CREATE TABLE member_operational_status (
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    manual_status TEXT NOT NULL DEFAULT 'UNAVAILABLE' CHECK (
        manual_status IN ('AVAILABLE_FOR_PATROL','UNAVAILABLE')
    ),
    updated_at INTEGER NOT NULL,
    updated_by INTEGER,
    PRIMARY KEY(guild_id, member_id),
    UNIQUE(guild_id, discord_id)
);

CREATE TABLE patrol_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    channel_type TEXT NOT NULL CHECK (channel_type IN ('WAITING','ACTIVE')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    label TEXT,
    created_at INTEGER NOT NULL,
    created_by INTEGER,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(guild_id, channel_id)
);

CREATE UNIQUE INDEX ux_patrol_waiting_channel
ON patrol_channels(guild_id)
WHERE channel_type='WAITING' AND enabled=1;

CREATE INDEX ix_patrol_channels_order
ON patrol_channels(guild_id, channel_type, enabled, sort_order, channel_id);

CREATE TABLE patrols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    sequence_number INTEGER NOT NULL,
    voice_channel_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RESERVED','ACTIVE','CLOSED','CANCELLED')),
    origin TEXT NOT NULL CHECK (origin IN ('AUTO','ADMIN')),
    minimum_members INTEGER NOT NULL,
    continue_until_empty INTEGER NOT NULL DEFAULT 1 CHECK (continue_until_empty IN (0,1)),
    leader_member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    reserved_at INTEGER NOT NULL,
    started_at INTEGER,
    ended_at INTEGER,
    end_reason TEXT,
    created_by INTEGER,
    movement_error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, sequence_number)
);

CREATE UNIQUE INDEX ux_active_patrol_call
ON patrols(guild_id, voice_channel_id)
WHERE status IN ('RESERVED','ACTIVE');

CREATE INDEX ix_patrol_status
ON patrols(guild_id, status, started_at, id);

CREATE TABLE patrol_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    patrol_id INTEGER NOT NULL REFERENCES patrols(id) ON DELETE RESTRICT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    member_role TEXT NOT NULL DEFAULT 'MEMBER' CHECK (member_role IN ('LEADER','MEMBER')),
    status TEXT NOT NULL DEFAULT 'RESERVED' CHECK (
        status IN ('RESERVED','ACTIVE','LEFT','CANCELLED')
    ),
    reserved_at INTEGER NOT NULL,
    joined_at INTEGER,
    left_at INTEGER,
    associated_shift_id INTEGER REFERENCES shifts(id) ON DELETE RESTRICT,
    UNIQUE(patrol_id, member_id)
);

CREATE UNIQUE INDEX ux_member_active_patrol
ON patrol_members(guild_id, member_id)
WHERE status IN ('RESERVED','ACTIVE');

CREATE INDEX ix_patrol_members_patrol
ON patrol_members(patrol_id, status, reserved_at);

CREATE TABLE patrol_queue_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (
        status IN ('QUEUED','FORMING','REMOVED','FORMED','INVALIDATED')
    ),
    source TEXT NOT NULL CHECK (source IN ('VOICE','PANEL','RECOVERY')),
    queue_entered_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    exited_at INTEGER,
    exit_reason TEXT,
    patrol_id INTEGER REFERENCES patrols(id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ux_member_current_patrol_queue
ON patrol_queue_entries(guild_id, member_id)
WHERE status IN ('QUEUED','FORMING');

CREATE INDEX ix_patrol_queue_fifo
ON patrol_queue_entries(guild_id, status, queue_entered_at, id);

CREATE TABLE patrol_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    patrol_id INTEGER NOT NULL REFERENCES patrols(id) ON DELETE RESTRICT,
    subject_member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    subject_discord_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    rating TEXT NOT NULL CHECK (rating IN ('POSITIVE','NEUTRAL','NEEDS_ATTENTION')),
    observation TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE(patrol_id, subject_member_id, author_id)
);

CREATE INDEX ix_patrol_feedback_subject
ON patrol_feedback(guild_id, subject_member_id, created_at DESC);

CREATE TABLE operational_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    shift_id INTEGER REFERENCES shifts(id) ON DELETE RESTRICT,
    flag_type TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','DISMISSED','RESOLVED')),
    created_at INTEGER NOT NULL,
    reviewed_by INTEGER,
    reviewed_at INTEGER,
    review_reason TEXT,
    UNIQUE(guild_id, fingerprint)
);

CREATE INDEX ix_operational_flags_status
ON operational_flags(guild_id, status, created_at DESC);

CREATE TABLE integrity_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER,
    finding_type TEXT NOT NULL,
    fix_class TEXT NOT NULL CHECK (fix_class IN ('AUTO_FIX_SAFE','REQUIRES_REVIEW')),
    evidence_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESOLVED','DISMISSED')),
    detected_at INTEGER NOT NULL,
    resolved_by INTEGER,
    resolved_at INTEGER,
    resolution TEXT,
    UNIQUE(guild_id, fingerprint)
);

CREATE INDEX ix_integrity_findings_status
ON integrity_findings(guild_id, status, fix_class, detected_at DESC);

ALTER TABLE course_catalog ADD COLUMN minimum_rank_level INTEGER;
ALTER TABLE course_catalog ADD COLUMN minimum_valid_hours_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE course_catalog ADD COLUMN minimum_tenure_days INTEGER NOT NULL DEFAULT 0;
ALTER TABLE course_catalog ADD COLUMN require_no_active_suspension INTEGER NOT NULL DEFAULT 1
    CHECK (require_no_active_suspension IN (0,1));
ALTER TABLE course_catalog ADD COLUMN prerequisite_course_name TEXT;

CREATE TABLE training_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    training_id INTEGER NOT NULL REFERENCES training_events(id) ON DELETE RESTRICT,
    enrollment_id INTEGER NOT NULL REFERENCES training_enrollments(id) ON DELETE RESTRICT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    attendance TEXT NOT NULL CHECK (attendance IN ('PRESENT','ABSENT')),
    result TEXT NOT NULL CHECK (result IN ('APPROVED','FAILED')),
    performance TEXT NOT NULL CHECK (performance IN ('EXCELLENT','GOOD','REGULAR','INSUFFICIENT')),
    observation TEXT,
    evaluator_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(training_id, enrollment_id)
);

CREATE INDEX ix_training_evaluations_member
ON training_evaluations(guild_id, member_id, created_at DESC);

CREATE TABLE recruit_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    evaluator_id INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('POSITIVE','NEUTRAL','NEEDS_ATTENTION')),
    observation TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_recruit_evaluations_member
ON recruit_evaluations(guild_id, member_id, created_at DESC);

CREATE TABLE activity_swap_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    requester_member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    requester_discord_id INTEGER NOT NULL,
    target_member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    target_discord_id INTEGER NOT NULL,
    activity_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    requires_command INTEGER NOT NULL DEFAULT 1 CHECK (requires_command IN (0,1)),
    status TEXT NOT NULL CHECK (
        status IN ('WAITING_MEMBER','WAITING_COMMAND','APPROVED','DENIED','CANCELLED')
    ),
    submitted_at INTEGER NOT NULL,
    member_decided_at INTEGER,
    member_decision_reason TEXT,
    command_decided_at INTEGER,
    command_decided_by INTEGER,
    command_decision_reason TEXT
);

CREATE UNIQUE INDEX ux_open_activity_swap
ON activity_swap_requests(guild_id, requester_member_id, target_member_id, activity_name)
WHERE status IN ('WAITING_MEMBER','WAITING_COMMAND');

CREATE INDEX ix_activity_swaps_status
ON activity_swap_requests(guild_id, status, submitted_at);

CREATE TABLE module_maintenance (
    guild_id INTEGER NOT NULL,
    module_key TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0,1)),
    reason TEXT,
    expected_end_at INTEGER,
    enabled_by INTEGER,
    enabled_at INTEGER,
    disabled_by INTEGER,
    disabled_at INTEGER,
    PRIMARY KEY(guild_id, module_key)
);

CREATE TABLE domain_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id INTEGER,
    event_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(guild_id, event_key)
);

CREATE INDEX ix_domain_events_type
ON domain_events(guild_id, event_type, created_at DESC);
"""

MIGRATION_016 = """
CREATE TABLE web_action_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    action_type TEXT NOT NULL CHECK (
        action_type IN ('RANK_SYNC','MEMBER_SYNC','PANEL_REFRESH')
    ),
    target_discord_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    requested_by INTEGER NOT NULL,
    correlation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','PROCESSING','COMPLETED','FAILED')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    processed_at INTEGER,
    last_error TEXT
);

CREATE INDEX ix_web_action_outbox_delivery
ON web_action_outbox(status, available_at, created_at);

CREATE TABLE web_access_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    discord_id INTEGER,
    event_type TEXT NOT NULL,
    route TEXT,
    result TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    ip_hash TEXT,
    user_agent_hash TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_web_access_events_time
ON web_access_events(guild_id, created_at DESC);

CREATE TABLE discord_resource_registry (
    guild_id INTEGER NOT NULL,
    resource_id INTEGER NOT NULL,
    resource_type TEXT NOT NULL CHECK (
        resource_type IN ('CATEGORY','TEXT_CHANNEL','VOICE_CHANNEL','ROLE')
    ),
    name TEXT NOT NULL,
    parent_id INTEGER,
    position INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(guild_id, resource_id, resource_type)
);

CREATE INDEX ix_discord_resource_registry_type
ON discord_resource_registry(guild_id, resource_type, active, position, name);
"""

MIGRATION_017 = """
CREATE TABLE recruitment_form_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','PUBLISHED','RETIRED')),
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    created_by INTEGER,
    published_at INTEGER,
    published_by INTEGER,
    UNIQUE(guild_id, version_number)
);

CREATE TABLE recruitment_question_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    position INTEGER NOT NULL,
    questions_per_application INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    UNIQUE(guild_id, code)
);

CREATE TABLE recruitment_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    stable_key TEXT NOT NULL,
    group_id INTEGER NOT NULL REFERENCES recruitment_question_groups(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    description TEXT,
    question_type TEXT NOT NULL CHECK (
        question_type IN ('SHORT_TEXT','LONG_TEXT','NUMBER','DATE','BOOLEAN','SINGLE_SELECT','MULTI_SELECT')
    ),
    required INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    position INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    min_length INTEGER,
    max_length INTEGER,
    expected_min_length INTEGER,
    expected_max_length INTEGER,
    security_level TEXT NOT NULL DEFAULT 'NORMAL' CHECK (
        security_level IN ('NORMAL','CONTROLLED','STRICT')
    ),
    timer_enabled INTEGER NOT NULL DEFAULT 0 CHECK (timer_enabled IN (0,1)),
    timer_mode TEXT NOT NULL DEFAULT 'AUTO' CHECK (timer_mode IN ('AUTO','FIXED','NONE')),
    fixed_time_seconds INTEGER,
    allow_back INTEGER NOT NULL DEFAULT 1 CHECK (allow_back IN (0,1)),
    shuffle_position INTEGER NOT NULL DEFAULT 0 CHECK (shuffle_position IN (0,1)),
    difficulty TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (difficulty IN ('EASY','MEDIUM','HARD')),
    options_json TEXT NOT NULL DEFAULT '[]',
    condition_json TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, stable_key)
);

CREATE INDEX ix_recruitment_questions_group
ON recruitment_questions(guild_id, group_id, enabled, difficulty, position);

CREATE TABLE recruitment_form_version_questions (
    form_version_id INTEGER NOT NULL REFERENCES recruitment_form_versions(id) ON DELETE RESTRICT,
    question_id INTEGER NOT NULL REFERENCES recruitment_questions(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    PRIMARY KEY(form_version_id, question_id)
);

CREATE TABLE recruitment_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    public_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (
        status IN ('DRAFT','SCHEDULED','OPEN','PAUSED','CLOSED','ARCHIVED')
    ),
    opens_at INTEGER,
    closes_at INTEGER,
    form_version_id INTEGER REFERENCES recruitment_form_versions(id) ON DELETE RESTRICT,
    cooldown_days INTEGER NOT NULL DEFAULT 30 CHECK (cooldown_days BETWEEN 0 AND 365),
    minimum_age INTEGER NOT NULL DEFAULT 15 CHECK (minimum_age BETWEEN 13 AND 100),
    maximum_applications INTEGER,
    initial_rank_id INTEGER REFERENCES ranks(id) ON DELETE RESTRICT,
    candidate_role_id INTEGER,
    interview_channel_id INTEGER,
    created_at INTEGER NOT NULL,
    created_by INTEGER,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, name)
);

CREATE INDEX ix_recruitment_campaign_status
ON recruitment_campaigns(guild_id, status, opens_at, closes_at);

CREATE TABLE recruitment_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    public_id TEXT NOT NULL UNIQUE,
    protocol TEXT UNIQUE,
    campaign_id INTEGER NOT NULL REFERENCES recruitment_campaigns(id) ON DELETE RESTRICT,
    form_version_id INTEGER NOT NULL REFERENCES recruitment_form_versions(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    discord_username TEXT,
    discord_global_name TEXT,
    discord_avatar TEXT,
    guild_membership_verified_at INTEGER,
    consent_accepted_at INTEGER,
    bgr_id TEXT NOT NULL,
    candidate_nick TEXT NOT NULL,
    age INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (
        status IN ('DRAFT','SUBMITTED','UNDER_REVIEW','INTERVIEW_PENDING',
                   'INTERVIEW_SCHEDULED','INTERVIEW_COMPLETED','FINAL_REVIEW',
                   'APPROVED','REJECTED','WITHDRAWN','EXPIRED')
    ),
    stage TEXT NOT NULL DEFAULT 'APPLICATION',
    version INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT NOT NULL,
    assigned_to INTEGER,
    assigned_at INTEGER,
    started_at INTEGER NOT NULL,
    submitted_at INTEGER,
    reviewed_at INTEGER,
    decided_at INTEGER,
    decided_by INTEGER,
    internal_reason TEXT,
    candidate_message TEXT,
    cooldown_until INTEGER,
    legacy_incomplete INTEGER NOT NULL DEFAULT 0 CHECK (legacy_incomplete IN (0,1)),
    legacy_ticket_id INTEGER REFERENCES service_tickets(id) ON DELETE RESTRICT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, idempotency_key),
    UNIQUE(guild_id, legacy_ticket_id)
);

CREATE UNIQUE INDEX ux_recruitment_active_discord
ON recruitment_applications(guild_id, discord_id)
WHERE status IN ('DRAFT','SUBMITTED','UNDER_REVIEW','INTERVIEW_PENDING',
                 'INTERVIEW_SCHEDULED','INTERVIEW_COMPLETED','FINAL_REVIEW');

CREATE UNIQUE INDEX ux_recruitment_active_bgr_id
ON recruitment_applications(guild_id, bgr_id)
WHERE status IN ('DRAFT','SUBMITTED','UNDER_REVIEW','INTERVIEW_PENDING',
                 'INTERVIEW_SCHEDULED','INTERVIEW_COMPLETED','FINAL_REVIEW');

CREATE INDEX ix_recruitment_application_queue
ON recruitment_applications(guild_id, status, submitted_at, created_at);

CREATE TABLE recruitment_application_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    question_id INTEGER NOT NULL REFERENCES recruitment_questions(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL,
    question_snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'NOT_STARTED' CHECK (
        status IN ('NOT_STARTED','ACTIVE','SUBMITTED','TIME_EXPIRED','SKIPPED')
    ),
    token_nonce TEXT,
    started_at INTEGER,
    expires_at INTEGER,
    draft_answer_json TEXT,
    final_answer_json TEXT,
    saved_at INTEGER,
    submitted_at INTEGER,
    duration_ms INTEGER,
    UNIQUE(application_id, question_id),
    UNIQUE(application_id, ordinal)
);

CREATE INDEX ix_recruitment_application_questions_progress
ON recruitment_application_questions(application_id, status, ordinal);

CREATE TABLE recruitment_integrity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    application_question_id INTEGER REFERENCES recruitment_application_questions(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (
        event_type IN ('QUESTION_STARTED','QUESTION_SUBMITTED','QUESTION_TIMEOUT',
                       'COPY_BLOCKED','PASTE_BLOCKED','CUT_BLOCKED','DROP_BLOCKED',
                       'TAB_HIDDEN','TAB_VISIBLE','WINDOW_BLURRED','WINDOW_FOCUSED',
                       'UNUSUAL_INPUT_PATTERN','POSSIBLE_SIMILAR_RESPONSE')
    ),
    occurred_at INTEGER NOT NULL,
    duration_ms INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX ix_recruitment_integrity_application
ON recruitment_integrity_events(application_id, occurred_at, event_type);

CREATE TABLE recruitment_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    reviewer_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    reason TEXT,
    from_status TEXT,
    to_status TEXT,
    application_version INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_recruitment_reviews_application
ON recruitment_reviews(application_id, created_at DESC);

CREATE TABLE recruitment_interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    scheduled_at INTEGER NOT NULL,
    interviewer_id INTEGER NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK (
        status IN ('SCHEDULED','COMPLETED','CANCELLED','NO_SHOW')
    ),
    created_at INTEGER NOT NULL,
    completed_at INTEGER
);

CREATE INDEX ix_recruitment_interviews_application
ON recruitment_interviews(application_id, scheduled_at DESC);

CREATE TABLE recruitment_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    interview_id INTEGER REFERENCES recruitment_interviews(id) ON DELETE RESTRICT,
    evaluator_id INTEGER NOT NULL,
    communication TEXT NOT NULL,
    posture TEXT NOT NULL,
    knowledge TEXT NOT NULL,
    discipline TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('FIT','UNFIT','REEVALUATE')),
    observation TEXT,
    evaluated_at INTEGER NOT NULL
);

CREATE TABLE recruitment_internal_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    author_id INTEGER NOT NULL,
    note TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE recruitment_adaptations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    extra_time_percent INTEGER NOT NULL DEFAULT 0 CHECK (extra_time_percent BETWEEN 0 AND 200),
    clipboard_adapted INTEGER NOT NULL DEFAULT 0 CHECK (clipboard_adapted IN (0,1)),
    alternative_format TEXT,
    reason TEXT NOT NULL,
    approved_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE recruitment_cooldowns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    discord_id INTEGER NOT NULL,
    application_id INTEGER REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    starts_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_recruitment_cooldowns_candidate
ON recruitment_cooldowns(guild_id, discord_id, ends_at DESC);

CREATE TABLE recruitment_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    discord_id INTEGER,
    bgr_id TEXT,
    reason TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    revoked_by INTEGER,
    revoked_at INTEGER,
    CHECK (discord_id IS NOT NULL OR bgr_id IS NOT NULL)
);

CREATE INDEX ix_recruitment_blocks_candidate
ON recruitment_blocks(guild_id, active, discord_id, bgr_id);

CREATE TABLE recruitment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    actor_id INTEGER,
    public_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_recruitment_history_application
ON recruitment_history(application_id, created_at, id);

CREATE TABLE recruitment_notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    event_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','PROCESSING','COMPLETED','FAILED')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    processed_at INTEGER,
    last_error TEXT,
    delivery_channel_id INTEGER,
    delivery_message_id INTEGER,
    UNIQUE(guild_id, event_key)
);

CREATE INDEX ix_recruitment_notification_delivery
ON recruitment_notification_outbox(status, available_at, created_at);

CREATE TABLE recruit_followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    origin_application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','COMPLETED','CANCELLED')),
    started_at INTEGER NOT NULL,
    completed_at INTEGER,
    UNIQUE(guild_id, origin_application_id),
    UNIQUE(guild_id, member_id, status)
);

ALTER TABLE members ADD COLUMN origin_recruitment_application_id INTEGER
    REFERENCES recruitment_applications(id) ON DELETE RESTRICT;
"""

MIGRATION_018 = """
CREATE TABLE recruitment_evaluation_context_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','PUBLISHED','RETIRED')),
    name TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    created_by INTEGER,
    published_at INTEGER,
    published_by INTEGER,
    UNIQUE(guild_id, version_number)
);

CREATE TABLE recruitment_rubric_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','PUBLISHED','RETIRED')),
    name TEXT NOT NULL,
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    created_by INTEGER,
    published_at INTEGER,
    published_by INTEGER,
    UNIQUE(guild_id, version_number)
);

CREATE TABLE recruitment_rubric_criteria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rubric_version_id INTEGER NOT NULL REFERENCES recruitment_rubric_versions(id) ON DELETE RESTRICT,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    description TEXT NOT NULL,
    weight INTEGER NOT NULL CHECK (weight BETWEEN 1 AND 100),
    maximum_score REAL NOT NULL DEFAULT 10 CHECK (maximum_score > 0 AND maximum_score <= 100),
    position INTEGER NOT NULL,
    UNIQUE(rubric_version_id, code),
    UNIQUE(rubric_version_id, position)
);

CREATE TABLE recruitment_analysis_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    analysis_type TEXT NOT NULL DEFAULT 'PRE_INTERVIEW' CHECK (
        analysis_type IN ('PRE_INTERVIEW','FINAL_ASSISTED','PREVIEW')
    ),
    request_reason TEXT NOT NULL CHECK (
        request_reason IN ('AUTOMATIC','MANUAL','RUBRIC_CHANGED','CONTEXT_CHANGED','INTERVIEW_COMPLETED','PREVIEW')
    ),
    requested_by INTEGER,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','PROCESSING','COMPLETED','FAILED','OUTDATED')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    available_at INTEGER NOT NULL,
    rubric_version_id INTEGER NOT NULL REFERENCES recruitment_rubric_versions(id) ON DELETE RESTRICT,
    context_version_id INTEGER NOT NULL REFERENCES recruitment_evaluation_context_versions(id) ON DELETE RESTRICT,
    prompt_version TEXT NOT NULL,
    input_hash TEXT,
    result_id INTEGER,
    last_error_code TEXT,
    last_error_detail TEXT,
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER,
    updated_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX ux_recruitment_analysis_active_job
ON recruitment_analysis_jobs(application_id, analysis_type)
WHERE status IN ('PENDING','PROCESSING');

CREATE INDEX ix_recruitment_analysis_jobs_delivery
ON recruitment_analysis_jobs(status, available_at, created_at);

CREATE TABLE recruitment_analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    job_id INTEGER NOT NULL REFERENCES recruitment_analysis_jobs(id) ON DELETE RESTRICT,
    analysis_type TEXT NOT NULL CHECK (analysis_type IN ('PRE_INTERVIEW','FINAL_ASSISTED','PREVIEW')),
    status TEXT NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('COMPLETED','OUTDATED')),
    recommendation TEXT NOT NULL CHECK (recommendation IN ('RECOMMENDED','REVIEW','NOT_RECOMMENDED')),
    confidence TEXT NOT NULL CHECK (confidence IN ('LOW','MEDIUM','HIGH')),
    overall_score REAL NOT NULL CHECK (overall_score BETWEEN 0 AND 100),
    summary TEXT NOT NULL,
    criteria_json TEXT NOT NULL,
    strengths_json TEXT NOT NULL,
    concerns_json TEXT NOT NULL,
    contradictions_json TEXT NOT NULL,
    interview_questions_json TEXT NOT NULL,
    integrity_review_recommended INTEGER NOT NULL DEFAULT 0 CHECK (integrity_review_recommended IN (0,1)),
    deterministic_checks_json TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    rubric_version_id INTEGER NOT NULL REFERENCES recruitment_rubric_versions(id) ON DELETE RESTRICT,
    context_version_id INTEGER NOT NULL REFERENCES recruitment_evaluation_context_versions(id) ON DELETE RESTRICT,
    input_hash TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(application_id, analysis_type, input_hash)
);

CREATE INDEX ix_recruitment_analysis_results_application
ON recruitment_analysis_results(application_id, created_at DESC, id DESC);

CREATE TABLE recruitment_analysis_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    result_id INTEGER NOT NULL REFERENCES recruitment_analysis_results(id) ON DELETE RESTRICT,
    reviewer_id INTEGER NOT NULL,
    usefulness TEXT NOT NULL CHECK (usefulness IN ('YES','PARTIAL','NO')),
    note TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE(result_id, reviewer_id)
);
"""

MIGRATION_019 = """
CREATE TABLE security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')),
    actor_discord_id INTEGER,
    target_type TEXT,
    target_id TEXT,
    source TEXT NOT NULL,
    route TEXT,
    request_id TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('ALLOWED','DENIED','BLOCKED','FAILED','DETECTED','RESOLVED')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_security_events_guild_time
ON security_events(guild_id, created_at DESC, id DESC);

CREATE INDEX ix_security_events_type_time
ON security_events(event_type, created_at DESC, id DESC);

CREATE TABLE security_session_revocations (
    guild_id INTEGER NOT NULL,
    discord_id INTEGER NOT NULL,
    revoked_at INTEGER NOT NULL,
    reason TEXT NOT NULL,
    revoked_by INTEGER,
    PRIMARY KEY (guild_id, discord_id)
);

CREATE TABLE internal_request_nonces (
    nonce TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    request_timestamp INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_internal_request_nonces_expiry
ON internal_request_nonces(expires_at);

CREATE TABLE security_discord_audit_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    findings_hash TEXT NOT NULL,
    findings_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(guild_id, findings_hash)
);

CREATE INDEX ix_security_discord_snapshots_guild_time
ON security_discord_audit_snapshots(guild_id, created_at DESC, id DESC);
"""

MIGRATION_020 = """
ALTER TABLE patrols ADD COLUMN commander_member_id INTEGER
    REFERENCES members(id) ON DELETE RESTRICT;
ALTER TABLE patrols ADD COLUMN commander_assigned_at INTEGER;
ALTER TABLE patrols ADD COLUMN commander_assignment_source TEXT
    CHECK (commander_assignment_source IN ('AUTOMATIC','MANUAL_OVERRIDE','REASSIGNMENT'));
ALTER TABLE patrols ADD COLUMN commander_manual_lock INTEGER NOT NULL DEFAULT 0
    CHECK (commander_manual_lock IN (0,1));

CREATE TABLE patrol_commander_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    patrol_id INTEGER NOT NULL REFERENCES patrols(id) ON DELETE RESTRICT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    source TEXT NOT NULL CHECK (source IN ('AUTOMATIC','MANUAL_OVERRIDE','REASSIGNMENT')),
    reason TEXT NOT NULL,
    assigned_by INTEGER
);

CREATE UNIQUE INDEX ux_patrol_open_commander_history
ON patrol_commander_history(patrol_id)
WHERE ended_at IS NULL;

CREATE INDEX ix_patrol_commander_history_timeline
ON patrol_commander_history(guild_id, patrol_id, started_at, id);

CREATE TABLE patrol_operational_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    patrol_id INTEGER NOT NULL REFERENCES patrols(id) ON DELETE RESTRICT,
    flag_type TEXT NOT NULL CHECK (flag_type IN ('PATROL_WITHOUT_ELIGIBLE_COMMANDER')),
    evidence_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESOLVED','DISMISSED')),
    created_at INTEGER NOT NULL,
    resolved_at INTEGER,
    resolution TEXT
);

CREATE UNIQUE INDEX ux_patrol_open_operational_flag
ON patrol_operational_flags(patrol_id, flag_type)
WHERE status='OPEN';

CREATE INDEX ix_patrol_operational_flags_inbox
ON patrol_operational_flags(guild_id, status, created_at DESC);
"""

MIGRATION_021 = """
CREATE UNIQUE INDEX ux_members_bgr_identity
ON members(guild_id, lower(trim(character_id)))
WHERE character_id IS NOT NULL AND trim(character_id)<>'';

CREATE TABLE registration_gate_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    discord_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('UNREGISTERED','PENDING','REGISTERED','REQUIRES_REVIEW','BLOCKED')
    ),
    access_tier TEXT NOT NULL DEFAULT 'REGISTERED_VISITOR' CHECK (
        access_tier IN ('REGISTERED_VISITOR','CANDIDATE','RECRUIT','MEMBER')
    ),
    mta_nick TEXT,
    bgr_id TEXT,
    member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    recruitment_application_id INTEGER REFERENCES recruitment_applications(id) ON DELETE RESTRICT,
    source TEXT NOT NULL CHECK (
        source IN ('SELF_REGISTRATION','ADMIN_APPROVAL','SYSTEM_RECONCILIATION','REJOIN')
    ),
    conflict_code TEXT,
    conflict_member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    sync_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED' CHECK (
        sync_status IN ('NOT_REQUIRED','PENDING','SYNCED','FAILED')
    ),
    sync_error TEXT,
    idempotency_key TEXT,
    submitted_at INTEGER,
    completed_at INTEGER,
    reviewed_at INTEGER,
    reviewed_by INTEGER,
    review_reason TEXT,
    last_attempt_at INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, discord_id),
    UNIQUE(guild_id, idempotency_key)
);

CREATE INDEX ix_registration_gate_queue
ON registration_gate_records(guild_id, status, updated_at, id);

CREATE INDEX ix_registration_gate_bgr_id
ON registration_gate_records(guild_id, bgr_id, status);

CREATE TABLE registration_gate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    registration_id INTEGER NOT NULL REFERENCES registration_gate_records(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'REGISTRATION_STARTED','REGISTRATION_COMPLETED','REGISTRATION_REVIEW_REQUIRED',
            'REGISTRATION_APPROVED','REGISTRATION_REJECTED','REGISTRATION_IDENTITY_LINKED',
            'REGISTRATION_ACCESS_GRANTED','REGISTRATION_ACCESS_REVOKED',
            'REGISTRATION_RECONCILED','REGISTRATION_SYNC_FAILED'
        )
    ),
    actor_id INTEGER,
    source TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_registration_gate_events_timeline
ON registration_gate_events(guild_id, registration_id, created_at, id);

CREATE TABLE registration_access_classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('CATEGORY','CHANNEL')),
    resource_id INTEGER NOT NULL,
    internal_key TEXT NOT NULL,
    access_class TEXT NOT NULL CHECK (
        access_class IN ('ONBOARDING_VISIBLE','MEMBER_ONLY','STAFF_ONLY','PUBLIC')
    ),
    created_at INTEGER NOT NULL,
    created_by INTEGER,
    updated_at INTEGER NOT NULL,
    updated_by INTEGER,
    UNIQUE(guild_id, resource_type, resource_id),
    UNIQUE(guild_id, resource_type, internal_key)
);

CREATE INDEX ix_registration_access_class
ON registration_access_classifications(guild_id, access_class, resource_type);

CREATE TABLE registration_permission_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    snapshot_json TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PREVIEW' CHECK (
        status IN ('PREVIEW','APPLIED','ROLLED_BACK','FAILED','STALE')
    ),
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    applied_at INTEGER,
    rolled_back_at INTEGER
);

CREATE INDEX ix_registration_permission_snapshots
ON registration_permission_snapshots(guild_id, created_at DESC);

CREATE TABLE registration_access_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    finding_type TEXT NOT NULL CHECK (
        finding_type IN (
            'UNCLASSIFIED_RESOURCE','UNREGISTERED_ACCESS_LEAK','BOT_PERMISSION_ERROR',
            'OWNER_LOCKOUT_RISK','ONBOARDING_UNAVAILABLE','SYNC_FAILURE'
        )
    ),
    resource_id INTEGER,
    discord_id INTEGER,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESOLVED','DISMISSED')),
    created_at INTEGER NOT NULL,
    resolved_at INTEGER,
    resolution TEXT,
    UNIQUE(guild_id, fingerprint)
);

CREATE INDEX ix_registration_access_findings_queue
ON registration_access_findings(guild_id, status, created_at DESC);

CREATE TABLE recruit_onboarding_checklists (
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    registration_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        registration_status IN ('PENDING','COMPLETED')
    ),
    nickname_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        nickname_status IN ('PENDING','COMPLETED')
    ),
    role_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        role_status IN ('PENDING','COMPLETED')
    ),
    rank_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        rank_status IN ('PENDING','COMPLETED')
    ),
    regulation_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        regulation_status IN ('PENDING','COMPLETED')
    ),
    training_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        training_status IN ('PENDING','COMPLETED')
    ),
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(guild_id, member_id)
);
"""

MIGRATION_022 = """
ALTER TABLE service_tickets ADD COLUMN priority TEXT NOT NULL DEFAULT 'NORMAL'
    CHECK (priority IN ('LOW','NORMAL','HIGH','URGENT'));
ALTER TABLE service_tickets ADD COLUMN last_requester_notification_at INTEGER;
ALTER TABLE service_tickets ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE ticket_rooms ADD COLUMN active_category_id INTEGER;
ALTER TABLE ticket_rooms ADD COLUMN archive_category_id INTEGER;
ALTER TABLE ticket_rooms ADD COLUMN responsible_role_id INTEGER;
ALTER TABLE ticket_rooms ADD COLUMN responsible_role_mentioned_at INTEGER;
ALTER TABLE ticket_rooms ADD COLUMN reopened_by INTEGER;
ALTER TABLE ticket_rooms ADD COLUMN reopened_at INTEGER;
ALTER TABLE ticket_rooms ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE ticket_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    ticket_id INTEGER NOT NULL REFERENCES service_tickets(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    added_by INTEGER NOT NULL,
    added_at INTEGER NOT NULL,
    removed_by INTEGER,
    removed_at INTEGER,
    UNIQUE(guild_id, ticket_id, discord_id, added_at)
);

CREATE UNIQUE INDEX ux_ticket_active_participant
ON ticket_participants(guild_id, ticket_id, discord_id)
WHERE removed_at IS NULL;

CREATE INDEX ix_ticket_participants_current
ON ticket_participants(guild_id, ticket_id, removed_at, added_at);

CREATE TABLE ticket_operation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    ticket_id INTEGER NOT NULL REFERENCES service_tickets(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'ROOM_CREATED','RESPONSIBLE_ROLE_MENTIONED','CLAIMED','RELEASED',
            'PRIORITY_CHANGED','PARTICIPANT_ADDED','PARTICIPANT_REMOVED',
            'REQUESTER_NOTIFIED','TRANSCRIPT_GENERATED','CLOSED','ARCHIVED','REOPENED'
        )
    ),
    actor_id INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_ticket_operation_timeline
ON ticket_operation_events(guild_id, ticket_id, created_at, id);

CREATE TABLE ticket_transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    ticket_id INTEGER NOT NULL REFERENCES service_tickets(id) ON DELETE RESTRICT,
    generated_by INTEGER NOT NULL,
    reason TEXT NOT NULL,
    message_count INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    format_version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_ticket_transcripts_history
ON ticket_transcripts(guild_id, ticket_id, created_at DESC);
"""

MIGRATION_023 = """
CREATE TABLE access_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, code)
);

CREATE TABLE access_profile_permissions (
    access_profile_id INTEGER NOT NULL REFERENCES access_profiles(id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'GRANT' CHECK (effect IN ('GRANT','DENY')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(access_profile_id, permission)
);

CREATE TABLE functional_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    access_profile_id INTEGER REFERENCES access_profiles(id) ON DELETE RESTRICT,
    is_primary_candidate INTEGER NOT NULL DEFAULT 1 CHECK (is_primary_candidate IN (0,1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, code)
);

CREATE TABLE functional_position_permissions (
    position_id INTEGER NOT NULL REFERENCES functional_positions(id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'GRANT' CHECK (effect IN ('GRANT','DENY')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(position_id, permission)
);

CREATE TABLE rank_permissions (
    rank_id INTEGER NOT NULL REFERENCES ranks(id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'GRANT' CHECK (effect IN ('GRANT','DENY')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(rank_id, permission)
);

CREATE TABLE discord_role_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    discord_role_id INTEGER NOT NULL,
    mapping_type TEXT NOT NULL CHECK (
        mapping_type IN ('RANK','POSITION','QUALIFICATION','SYSTEM','COSMETIC','ACCESS')
    ),
    internal_code TEXT NOT NULL,
    display_name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    rank_id INTEGER REFERENCES ranks(id) ON DELETE CASCADE,
    position_id INTEGER REFERENCES functional_positions(id) ON DELETE CASCADE,
    access_profile_id INTEGER REFERENCES access_profiles(id) ON DELETE RESTRICT,
    is_primary_position_candidate INTEGER NOT NULL DEFAULT 0
        CHECK (is_primary_position_candidate IN (0,1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    created_by INTEGER,
    CHECK (
        (mapping_type='RANK' AND rank_id IS NOT NULL)
        OR (mapping_type='POSITION' AND position_id IS NOT NULL)
        OR (mapping_type='ACCESS' AND access_profile_id IS NOT NULL)
        OR mapping_type IN ('QUALIFICATION','SYSTEM','COSMETIC')
    ),
    UNIQUE(guild_id, discord_role_id, mapping_type)
);

CREATE INDEX ix_discord_role_mappings_lookup
ON discord_role_mappings(guild_id, discord_role_id, enabled, mapping_type);

CREATE TRIGGER validate_discord_role_mappings_insert
BEFORE INSERT ON discord_role_mappings
FOR EACH ROW
WHEN (
    NEW.rank_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM ranks r WHERE r.id=NEW.rank_id AND r.guild_id=NEW.guild_id
    )
) OR (
    NEW.position_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM functional_positions p
        WHERE p.id=NEW.position_id AND p.guild_id=NEW.guild_id
    )
) OR (
    NEW.access_profile_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM access_profiles ap
        WHERE ap.id=NEW.access_profile_id AND ap.guild_id=NEW.guild_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'cross-guild discord role mapping');
END;

CREATE TRIGGER validate_discord_role_mappings_update
BEFORE UPDATE OF guild_id, rank_id, position_id, access_profile_id
ON discord_role_mappings
FOR EACH ROW
WHEN (
    NEW.rank_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM ranks r WHERE r.id=NEW.rank_id AND r.guild_id=NEW.guild_id
    )
) OR (
    NEW.position_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM functional_positions p
        WHERE p.id=NEW.position_id AND p.guild_id=NEW.guild_id
    )
) OR (
    NEW.access_profile_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM access_profiles ap
        WHERE ap.id=NEW.access_profile_id AND ap.guild_id=NEW.guild_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'cross-guild discord role mapping');
END;

CREATE UNIQUE INDEX ux_discord_role_mappings_enabled_rank
ON discord_role_mappings(guild_id, rank_id)
WHERE mapping_type='RANK' AND enabled=1 AND rank_id IS NOT NULL;

CREATE TABLE member_positions (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    position_id INTEGER NOT NULL REFERENCES functional_positions(id) ON DELETE RESTRICT,
    source_role_id INTEGER NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
    assigned_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    PRIMARY KEY(member_id, position_id)
);

CREATE UNIQUE INDEX ux_member_primary_position
ON member_positions(member_id)
WHERE is_primary=1;

CREATE TRIGGER validate_member_positions_insert
BEFORE INSERT ON member_positions
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM members m
    JOIN functional_positions p
      ON p.id=NEW.position_id AND p.guild_id=m.guild_id
    JOIN discord_role_mappings drm
      ON drm.guild_id=m.guild_id
     AND drm.discord_role_id=NEW.source_role_id
     AND drm.mapping_type='POSITION'
     AND drm.position_id=NEW.position_id
    WHERE m.id=NEW.member_id
)
BEGIN
    SELECT RAISE(ABORT, 'invalid member position projection');
END;

CREATE TRIGGER validate_member_positions_update
BEFORE UPDATE OF member_id, position_id, source_role_id ON member_positions
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM members m
    JOIN functional_positions p
      ON p.id=NEW.position_id AND p.guild_id=m.guild_id
    JOIN discord_role_mappings drm
      ON drm.guild_id=m.guild_id
     AND drm.discord_role_id=NEW.source_role_id
     AND drm.mapping_type='POSITION'
     AND drm.position_id=NEW.position_id
    WHERE m.id=NEW.member_id
)
BEGIN
    SELECT RAISE(ABORT, 'invalid member position projection');
END;

CREATE TABLE member_access_profiles (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    access_profile_id INTEGER NOT NULL REFERENCES access_profiles(id) ON DELETE RESTRICT,
    source_mapping_id INTEGER NOT NULL
        REFERENCES discord_role_mappings(id) ON DELETE CASCADE,
    source_role_id INTEGER NOT NULL,
    assigned_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    PRIMARY KEY(member_id, source_mapping_id)
);

CREATE INDEX ix_member_access_profiles_member
ON member_access_profiles(member_id, access_profile_id);

CREATE INDEX ix_member_access_profiles_mapping
ON member_access_profiles(source_mapping_id);

CREATE INDEX ix_member_access_profiles_profile
ON member_access_profiles(access_profile_id);

CREATE TRIGGER validate_member_access_profiles_insert
BEFORE INSERT ON member_access_profiles
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM members m
    JOIN access_profiles ap
      ON ap.id=NEW.access_profile_id
     AND ap.guild_id=m.guild_id
    JOIN discord_role_mappings drm
      ON drm.id=NEW.source_mapping_id
     AND drm.guild_id=m.guild_id
     AND drm.mapping_type='ACCESS'
     AND drm.access_profile_id=NEW.access_profile_id
     AND drm.discord_role_id=NEW.source_role_id
    WHERE m.id=NEW.member_id
)
BEGIN
    SELECT RAISE(ABORT, 'invalid member access projection');
END;

CREATE TRIGGER validate_member_access_profiles_update
BEFORE UPDATE OF member_id, access_profile_id, source_mapping_id, source_role_id
ON member_access_profiles
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM members m
    JOIN access_profiles ap
      ON ap.id=NEW.access_profile_id
     AND ap.guild_id=m.guild_id
    JOIN discord_role_mappings drm
      ON drm.id=NEW.source_mapping_id
     AND drm.guild_id=m.guild_id
     AND drm.mapping_type='ACCESS'
     AND drm.access_profile_id=NEW.access_profile_id
     AND drm.discord_role_id=NEW.source_role_id
    WHERE m.id=NEW.member_id
)
BEGIN
    SELECT RAISE(ABORT, 'invalid member access projection');
END;

CREATE TABLE member_permission_overrides (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    effect TEXT NOT NULL CHECK (effect IN ('GRANT','DENY')),
    reason TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(member_id, permission)
);

CREATE TABLE member_identity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    actor_id INTEGER,
    correlation_id TEXT NOT NULL,
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    role_ids_json TEXT NOT NULL DEFAULT '[]',
    authorization_version INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_member_identity_events_timeline
ON member_identity_events(guild_id, member_id, created_at DESC, id DESC);

CREATE INDEX ix_member_identity_events_correlation
ON member_identity_events(correlation_id, id);

ALTER TABLE rank_sync_events ADD COLUMN correlation_id TEXT;

CREATE INDEX ix_rank_sync_events_correlation
ON rank_sync_events(correlation_id, id);

CREATE TRIGGER validate_member_identity_events_insert
BEFORE INSERT ON member_identity_events
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM members m
    WHERE m.id=NEW.member_id
      AND m.guild_id=NEW.guild_id
      AND m.discord_id=NEW.discord_id
)
BEGIN
    SELECT RAISE(ABORT, 'cross-guild identity event');
END;

CREATE TABLE identity_reconciliation_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('PREVIEW','APPLY')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','PROCESSING','COMPLETED','FAILED')
    ),
    requested_by INTEGER NOT NULL,
    source_job_id INTEGER REFERENCES identity_reconciliation_jobs(id) ON DELETE RESTRICT,
    correlation_id TEXT NOT NULL UNIQUE,
    catalog_hash TEXT,
    total_members INTEGER NOT NULL DEFAULT 0,
    unchanged_members INTEGER NOT NULL DEFAULT 0,
    divergent_positions INTEGER NOT NULL DEFAULT 0,
    divergent_ranks INTEGER NOT NULL DEFAULT 0,
    review_required INTEGER NOT NULL DEFAULT 0,
    failed_members INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER,
    last_error TEXT
);

CREATE TABLE identity_reconciliation_job_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES identity_reconciliation_jobs(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    result TEXT NOT NULL CHECK (
        result IN ('UNCHANGED','DIVERGENT','REVIEW_REQUIRED','APPLIED','FAILED')
    ),
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    role_ids_json TEXT NOT NULL DEFAULT '[]',
    roles_hash TEXT,
    discord_present_snapshot INTEGER NOT NULL DEFAULT 1
        CHECK (discord_present_snapshot IN (0,1)),
    error TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE(job_id, member_id)
);

CREATE INDEX ix_identity_reconciliation_jobs_status
ON identity_reconciliation_jobs(guild_id, status, created_at DESC);

CREATE UNIQUE INDEX ux_identity_reconciliation_apply_source
ON identity_reconciliation_jobs(source_job_id)
WHERE mode='APPLY' AND source_job_id IS NOT NULL;

CREATE TRIGGER validate_identity_reconciliation_items_insert
BEFORE INSERT ON identity_reconciliation_job_items
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM identity_reconciliation_jobs j
    JOIN members m
      ON m.id=NEW.member_id
     AND m.guild_id=j.guild_id
     AND m.discord_id=NEW.discord_id
    WHERE j.id=NEW.job_id
)
BEGIN
    SELECT RAISE(ABORT, 'cross-guild reconciliation item');
END;

ALTER TABLE members ADD COLUMN primary_position_id INTEGER
    REFERENCES functional_positions(id) ON DELETE SET NULL;
ALTER TABLE members ADD COLUMN access_profile_id INTEGER
    REFERENCES access_profiles(id) ON DELETE RESTRICT;
ALTER TABLE members ADD COLUMN discord_roles_synced_at INTEGER;
ALTER TABLE members ADD COLUMN authorization_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE members ADD COLUMN identity_sync_status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (identity_sync_status IN ('PENDING','SYNCED','REVIEW_REQUIRED','ERROR','DISCORD_ABSENT'));
ALTER TABLE members ADD COLUMN identity_sync_error TEXT;
ALTER TABLE members ADD COLUMN discord_roles_hash TEXT;
ALTER TABLE members ADD COLUMN discord_present INTEGER NOT NULL DEFAULT 0
    CHECK (discord_present IN (0,1));
ALTER TABLE members ADD COLUMN original_discord_nickname TEXT;
ALTER TABLE members ADD COLUMN original_nickname_captured INTEGER NOT NULL DEFAULT 0
    CHECK (original_nickname_captured IN (0,1));

UPDATE members
SET original_discord_nickname = CASE
        WHEN EXISTS (
            SELECT 1 FROM rank_sync_events e
            WHERE e.guild_id=members.guild_id AND e.discord_id=members.discord_id
        ) THEN (
            SELECT e.previous_nickname FROM rank_sync_events e
            WHERE e.guild_id=members.guild_id AND e.discord_id=members.discord_id
            ORDER BY e.created_at, e.id LIMIT 1
        )
        ELSE discord_nick
    END,
    original_nickname_captured = CASE
        WHEN EXISTS (
            SELECT 1 FROM rank_sync_events e
            WHERE e.guild_id=members.guild_id AND e.discord_id=members.discord_id
        ) OR discord_nick IS NOT NULL THEN 1
        ELSE 0
    END;

ALTER TABLE registration_gate_records ADD COLUMN review_channel_id INTEGER;
ALTER TABLE registration_gate_records ADD COLUMN review_message_id INTEGER;
ALTER TABLE registration_gate_records ADD COLUMN result_channel_id INTEGER;
ALTER TABLE registration_gate_records ADD COLUMN result_message_id INTEGER;
ALTER TABLE registration_gate_records ADD COLUMN delivery_status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (delivery_status IN ('PENDING','DELIVERED'));

UPDATE registration_gate_records
SET delivery_status='DELIVERED'
WHERE status NOT IN ('PENDING','REQUIRES_REVIEW') AND reviewed_at IS NULL;

CREATE INDEX ix_registration_gate_delivery
ON registration_gate_records(guild_id, status, delivery_status, submitted_at);

CREATE TRIGGER validate_member_identity_references_update
BEFORE UPDATE OF primary_position_id, access_profile_id ON members
FOR EACH ROW
WHEN (
    NEW.primary_position_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM functional_positions p
        WHERE p.id=NEW.primary_position_id AND p.guild_id=NEW.guild_id
    )
) OR (
    NEW.access_profile_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM access_profiles ap
        WHERE ap.id=NEW.access_profile_id AND ap.guild_id=NEW.guild_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'cross-guild member identity reference');
END;

INSERT INTO access_profiles(guild_id, code, name, priority, created_at, updated_at)
SELECT guilds.guild_id, seed.code, seed.name, seed.priority, 0, 0
FROM (
    SELECT guild_id FROM members
    UNION SELECT guild_id FROM ranks
    UNION SELECT guild_id FROM rbac_bindings
    UNION SELECT guild_id FROM discord_resource_registry
    UNION SELECT guild_id FROM guild_settings
) guilds
CROSS JOIN (
    SELECT 'CANDIDATO' AS code, 'Candidato' AS name, 10 AS priority
    UNION ALL SELECT 'RECRUTA', 'Recruta', 20
    UNION ALL SELECT 'MEMBRO', 'Membro', 30
    UNION ALL SELECT 'GRADUADO', 'Graduado', 40
    UNION ALL SELECT 'INSTRUTOR', 'Instrutor', 45
    UNION ALL SELECT 'SUPERVISOR', 'Supervisor', 50
    UNION ALL SELECT 'COMANDO', 'Comando', 70
    UNION ALL SELECT 'ALTO_COMANDO', 'Alto Comando', 90
    UNION ALL SELECT 'ADMINISTRADOR', 'Administrador técnico', 100
) seed;

INSERT INTO discord_role_mappings(
    guild_id, discord_role_id, mapping_type, internal_code, display_name,
    priority, rank_id, enabled, created_at, updated_at
)
SELECT guild_id, discord_role_id, 'RANK', 'RANK_' || id, name,
       level, id, active, created_at, created_at
FROM ranks
WHERE discord_role_id IS NOT NULL;

INSERT INTO discord_role_mappings(
    guild_id, discord_role_id, mapping_type, internal_code, display_name,
    priority, access_profile_id, enabled, created_at, updated_at, created_by
)
SELECT b.guild_id, b.role_id, 'ACCESS', 'ACCESS_ROLE_' || b.role_id,
       COALESCE(rr.name, 'Cargo ' || b.role_id), ap.priority,
       ap.id, 1, b.created_at, b.created_at, b.created_by
FROM rbac_bindings b
JOIN access_profiles ap ON ap.guild_id=b.guild_id AND ap.code=b.profile
LEFT JOIN discord_resource_registry rr
  ON rr.guild_id=b.guild_id AND rr.resource_id=b.role_id AND rr.resource_type='ROLE';

INSERT INTO functional_positions(
    guild_id, code, name, priority, access_profile_id,
    is_primary_candidate, enabled, created_at, updated_at
)
SELECT guild_roles.guild_id, seed.code, seed.name, seed.priority, ap.id,
       seed.primary_candidate, 1, 0, 0
FROM (
    SELECT 1146622063004635306 AS role_id, 'COMMANDER_GENERAL' AS code,
           'Comandante Geral' AS name, 1000 AS priority, 'ALTO_COMANDO' AS profile,
           1 AS primary_candidate
    UNION ALL SELECT 1146622062987841555, 'COMMANDER', 'Comandante', 950, 'COMANDO', 1
    UNION ALL SELECT 1146622062987841554, 'DEPUTY_COMMANDER', 'Sub Comandante', 900, 'COMANDO', 1
    UNION ALL SELECT 1146632112787693670, 'HIGH_COMMAND_STAFF', 'Alto Comando', 850, 'ALTO_COMANDO', 1
    UNION ALL SELECT 1162996505678991360, 'INTERNAL_AFFAIRS', 'Corregedoria', 700, 'COMANDO', 1
    UNION ALL SELECT 1146622062924943470, 'RECRUITMENT_LEAD', 'Responsável pelo Recrutamento', 600, 'INSTRUTOR', 1
    UNION ALL SELECT 1147302660442161243, 'RECRUITER', 'Recrutador', 500, 'INSTRUTOR', 1
    UNION ALL SELECT 1162975230453616740, 'INSTRUCTOR', 'Instrutor', 500, 'INSTRUTOR', 1
    UNION ALL SELECT 1146622062924943461, 'MEMBER', 'Membro CHOQUE', 100, 'MEMBRO', 1
) seed
JOIN (
    SELECT guild_id, role_id FROM rbac_bindings
    UNION
    SELECT guild_id, resource_id AS role_id
    FROM discord_resource_registry
    WHERE resource_type='ROLE'
    UNION
    SELECT guild_id, discord_role_id AS role_id
    FROM ranks
    WHERE discord_role_id IS NOT NULL
) guild_roles ON guild_roles.role_id=seed.role_id
JOIN access_profiles ap
  ON ap.guild_id=guild_roles.guild_id AND ap.code=seed.profile;

INSERT INTO discord_role_mappings(
    guild_id, discord_role_id, mapping_type, internal_code, display_name,
    priority, position_id, access_profile_id, is_primary_position_candidate,
    enabled, created_at, updated_at
)
SELECT p.guild_id, seed.role_id, 'POSITION', p.code, p.name, p.priority,
       p.id, p.access_profile_id, p.is_primary_candidate, 1, p.created_at, p.updated_at
FROM (
    SELECT 1146622063004635306 AS role_id, 'COMMANDER_GENERAL' AS code
    UNION ALL SELECT 1146622062987841555, 'COMMANDER'
    UNION ALL SELECT 1146622062987841554, 'DEPUTY_COMMANDER'
    UNION ALL SELECT 1146632112787693670, 'HIGH_COMMAND_STAFF'
    UNION ALL SELECT 1162996505678991360, 'INTERNAL_AFFAIRS'
    UNION ALL SELECT 1146622062924943470, 'RECRUITMENT_LEAD'
    UNION ALL SELECT 1147302660442161243, 'RECRUITER'
    UNION ALL SELECT 1162975230453616740, 'INSTRUCTOR'
    UNION ALL SELECT 1146622062924943461, 'MEMBER'
) seed
JOIN functional_positions p ON p.code=seed.code;

UPDATE members
SET access_profile_id = (
    SELECT ap.id FROM access_profiles ap
    WHERE ap.guild_id=members.guild_id
      AND ap.code='MEMBRO'
);

ALTER TABLE web_action_outbox RENAME TO web_action_outbox_v16;
DROP INDEX IF EXISTS ix_web_action_outbox_delivery;

CREATE TABLE web_action_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    action_type TEXT NOT NULL CHECK (
        action_type IN (
            'RANK_SYNC','MEMBER_SYNC','PANEL_REFRESH',
            'IDENTITY_SYNC','IDENTITY_RECONCILE_BULK'
        )
    ),
    target_discord_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    requested_by INTEGER NOT NULL,
    correlation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','PROCESSING','COMPLETED','FAILED')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    processed_at INTEGER,
    last_error TEXT
);

INSERT INTO web_action_outbox(
    id, guild_id, action_type, target_discord_id, payload_json,
    requested_by, correlation_id, status, attempts, available_at,
    created_at, processed_at, last_error
)
SELECT id, guild_id, action_type, target_discord_id, payload_json,
       requested_by, correlation_id, status, attempts, available_at,
       created_at, processed_at, last_error
FROM web_action_outbox_v16;

DROP TABLE web_action_outbox_v16;

CREATE INDEX ix_web_action_outbox_delivery
ON web_action_outbox(status, available_at, created_at);
"""

MIGRATION_024 = """
CREATE TABLE rank_registration_compliance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    discord_id INTEGER NOT NULL,
    rank_role_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','EXPIRING','COMPLETED','EXPIRED','CANCELLED')
    ),
    detected_at INTEGER NOT NULL,
    due_at INTEGER NOT NULL,
    last_reminder_at INTEGER,
    next_reminder_at INTEGER,
    reminder_count INTEGER NOT NULL DEFAULT 0,
    dm_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        dm_status IN ('PENDING','SENT','FAILED')
    ),
    dm_message_id INTEGER,
    dm_error TEXT,
    alert_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED' CHECK (
        alert_status IN ('NOT_REQUIRED','PENDING','SENT','FAILED')
    ),
    alert_error TEXT,
    completed_at INTEGER,
    completion_reason TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX ux_rank_registration_compliance_pending
ON rank_registration_compliance(guild_id, discord_id, rank_role_id)
WHERE status IN ('PENDING','EXPIRING');

CREATE INDEX ix_rank_registration_compliance_due
ON rank_registration_compliance(guild_id, status, due_at, next_reminder_at, id);
"""

MIGRATION_025 = """
CREATE TABLE patrol_voice_presence (
    guild_id INTEGER NOT NULL,
    voice_channel_id INTEGER NOT NULL,
    discord_id INTEGER NOT NULL,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    display_name TEXT NOT NULL,
    joined_at INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, voice_channel_id, discord_id)
);

CREATE INDEX ix_patrol_voice_presence_observed
ON patrol_voice_presence(guild_id, observed_at, voice_channel_id);
"""

MIGRATION_026 = """
CREATE TABLE qualification_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL REFERENCES course_catalog(id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK (action IN ('GRANT','REVOKE')),
    source TEXT NOT NULL CHECK (source IN ('WEB','DISCORD','TRAINING','SYSTEM')),
    actor_id INTEGER,
    reason TEXT NOT NULL,
    correlation_id TEXT NOT NULL UNIQUE,
    recorded_at INTEGER NOT NULL
);

CREATE INDEX ix_qualification_changes_member_course
ON qualification_changes(guild_id, member_id, course_id, recorded_at DESC, id DESC);

CREATE INDEX ix_qualification_changes_discord
ON qualification_changes(guild_id, discord_id, recorded_at DESC, id DESC);

ALTER TABLE web_action_outbox RENAME TO web_action_outbox_v26;
DROP INDEX IF EXISTS ix_web_action_outbox_delivery;

CREATE TABLE web_action_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    action_type TEXT NOT NULL CHECK (
        action_type IN (
            'RANK_SYNC','MEMBER_SYNC','PANEL_REFRESH',
            'IDENTITY_SYNC','IDENTITY_RECONCILE_BULK','QUALIFICATION_SYNC'
        )
    ),
    target_discord_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    requested_by INTEGER NOT NULL,
    correlation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','PROCESSING','COMPLETED','FAILED')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    processed_at INTEGER,
    last_error TEXT
);

INSERT INTO web_action_outbox(
    id, guild_id, action_type, target_discord_id, payload_json,
    requested_by, correlation_id, status, attempts, available_at,
    created_at, processed_at, last_error
)
SELECT id, guild_id, action_type, target_discord_id, payload_json,
       requested_by, correlation_id, status, attempts, available_at,
       created_at, processed_at, last_error
FROM web_action_outbox_v26;

DROP TABLE web_action_outbox_v26;

CREATE INDEX ix_web_action_outbox_delivery
ON web_action_outbox(status, available_at, created_at);
"""

MIGRATION_027 = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id TEXT NOT NULL UNIQUE,
    guild_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor_id INTEGER,
    target_id INTEGER,
    before_json TEXT,
    after_json TEXT,
    reason TEXT,
    created_at INTEGER NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        delivery_status IN ('PENDING','DELIVERED','FAILED')
    ),
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    delivered_at INTEGER,
    last_error TEXT
);

INSERT OR IGNORE INTO audit_logs(
    correlation_id, guild_id, action, before_json, after_json,
    reason, created_at, delivery_status
)
SELECT
    'migration-27-recruitment-minimum-age-' || id,
    guild_id,
    'RECRUITMENT_MINIMUM_AGE_ALIGNED',
    '{"minimum_age":' || minimum_age || '}',
    '{"minimum_age":15}',
    'Alinhamento do requisito público de alistamento para 15 anos fora do personagem',
    CAST(strftime('%s', 'now') AS INTEGER) * 1000,
    'PENDING'
FROM recruitment_campaigns
WHERE status != 'ARCHIVED' AND minimum_age != 15;

UPDATE recruitment_campaigns
SET minimum_age=15,
    updated_at=CAST(strftime('%s', 'now') AS INTEGER) * 1000
WHERE status != 'ARCHIVED' AND minimum_age != 15;
"""

MIGRATION_028 = """
-- Delivery claims make Discord publication safe across concurrent callbacks,
-- reconnects and a controlled restart.  They intentionally live outside the
-- business rows, so audit and member-history records remain append-only.
CREATE TABLE audit_delivery_claims (
    audit_id INTEGER PRIMARY KEY REFERENCES audit_logs(id) ON DELETE CASCADE,
    claim_token TEXT NOT NULL UNIQUE,
    claimed_at INTEGER NOT NULL
);

CREATE INDEX ix_audit_delivery_claims_stale
ON audit_delivery_claims(claimed_at, audit_id);

CREATE TABLE registration_delivery_claims (
    registration_id INTEGER NOT NULL REFERENCES registration_gate_records(id) ON DELETE CASCADE,
    phase TEXT NOT NULL CHECK (phase IN ('RESULT','CLEANUP')),
    claim_token TEXT NOT NULL UNIQUE,
    claimed_at INTEGER NOT NULL,
    PRIMARY KEY (registration_id, phase)
);

CREATE INDEX ix_registration_delivery_claims_stale
ON registration_delivery_claims(claimed_at, registration_id);

CREATE TABLE member_application_delivery_claims (
    application_id INTEGER NOT NULL REFERENCES member_applications(id) ON DELETE CASCADE,
    phase TEXT NOT NULL CHECK (phase IN ('RESULT','CLEANUP')),
    claim_token TEXT NOT NULL UNIQUE,
    claimed_at INTEGER NOT NULL,
    PRIMARY KEY (application_id, phase)
);

CREATE INDEX ix_member_application_delivery_claims_stale
ON member_application_delivery_claims(claimed_at, application_id);
"""

MIGRATION_029 = """
-- Central de Tags: the request is the durable aggregate.  Identity remains
-- canonical in members/registration_gate_records; immutable snapshots make
-- each tag history explainable even if the profile changes later.
CREATE TABLE tag_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    mta_nick_snapshot TEXT NOT NULL,
    character_id_snapshot TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'SOLICITADO','AGUARDANDO_SET','ATENDIMENTO_ASSUMIDO','SET_REALIZADO',
        'AGUARDANDO_CONFIRMACAO','CONCLUIDO','PENDENCIA','RECUSADO',
        'CANCELADO','EXPIRADO'
    )),
    version INTEGER NOT NULL DEFAULT 1,
    requested_at INTEGER NOT NULL,
    requested_by INTEGER NOT NULL,
    claimed_by INTEGER,
    claimed_at INTEGER,
    set_by INTEGER,
    set_at INTEGER,
    set_character_id TEXT,
    confirmation_requested_at INTEGER,
    confirmed_by INTEGER,
    confirmed_at INTEGER,
    terminal_by INTEGER,
    terminal_at INTEGER,
    terminal_reason TEXT,
    identity_conflict_json TEXT,
    expires_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- SQLite partial uniqueness is the final guard even when bot/API callbacks
-- race or a runtime reconnects while a click is in flight.
CREATE UNIQUE INDEX ux_tag_requests_one_active_member
ON tag_requests(guild_id, member_id)
WHERE status IN (
    'SOLICITADO','AGUARDANDO_SET','ATENDIMENTO_ASSUMIDO','SET_REALIZADO',
    'AGUARDANDO_CONFIRMACAO','PENDENCIA'
);

CREATE INDEX ix_tag_requests_queue
ON tag_requests(guild_id, status, requested_at, id);

CREATE INDEX ix_tag_requests_discord
ON tag_requests(guild_id, discord_id, requested_at DESC, id DESC);

CREATE TABLE tag_request_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_request_id INTEGER NOT NULL REFERENCES tag_requests(id) ON DELETE RESTRICT,
    guild_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    previous_status TEXT,
    next_status TEXT,
    actor_id INTEGER,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT NOT NULL UNIQUE,
    occurred_at INTEGER NOT NULL
);

CREATE INDEX ix_tag_request_events_timeline
ON tag_request_events(tag_request_id, occurred_at, id);

-- Desired/applied state separates the domain transition from Discord role I/O.
-- The generic outbox claims delivery, while this row prevents an old request
-- version from correcting roles after a newer transition.
CREATE TABLE tag_role_sync_state (
    tag_request_id INTEGER PRIMARY KEY REFERENCES tag_requests(id) ON DELETE CASCADE,
    requested_version INTEGER NOT NULL,
    applied_version INTEGER,
    last_error TEXT,
    updated_at INTEGER NOT NULL
);

ALTER TABLE web_action_outbox RENAME TO web_action_outbox_v29;
DROP INDEX IF EXISTS ix_web_action_outbox_delivery;

CREATE TABLE web_action_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    action_type TEXT NOT NULL CHECK (
        action_type IN (
            'RANK_SYNC','MEMBER_SYNC','PANEL_REFRESH',
            'IDENTITY_SYNC','IDENTITY_RECONCILE_BULK','QUALIFICATION_SYNC',
            'TAG_ROLE_SYNC'
        )
    ),
    target_discord_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    requested_by INTEGER NOT NULL,
    correlation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','PROCESSING','COMPLETED','FAILED')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    processed_at INTEGER,
    last_error TEXT
);

INSERT INTO web_action_outbox(
    id, guild_id, action_type, target_discord_id, payload_json,
    requested_by, correlation_id, status, attempts, available_at,
    created_at, processed_at, last_error
)
SELECT id, guild_id, action_type, target_discord_id, payload_json,
       requested_by, correlation_id, status, attempts, available_at,
       created_at, processed_at, last_error
FROM web_action_outbox_v29;

DROP TABLE web_action_outbox_v29;

CREATE INDEX ix_web_action_outbox_delivery
ON web_action_outbox(status, available_at, created_at);
"""

MIGRATION_030 = """
-- Confirmation delivery belongs to the tag aggregate rather than process RAM.
-- The claim state makes normal retries/reconnects idempotent and leaves a
-- recoverable trail when Discord is temporarily unavailable.
ALTER TABLE tag_requests ADD COLUMN confirmation_delivery_status TEXT NOT NULL
    DEFAULT 'NOT_REQUESTED' CHECK (confirmation_delivery_status IN (
        'NOT_REQUESTED','PENDING','PROCESSING','DELIVERED','FAILED'
    ));
ALTER TABLE tag_requests ADD COLUMN confirmation_delivery_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tag_requests ADD COLUMN confirmation_delivery_claimed_at INTEGER;
ALTER TABLE tag_requests ADD COLUMN confirmation_delivery_message_id INTEGER;
ALTER TABLE tag_requests ADD COLUMN confirmation_delivery_error TEXT;

UPDATE tag_requests
SET confirmation_delivery_status='PENDING'
WHERE status='AGUARDANDO_CONFIRMACAO'
  AND confirmation_delivery_status='NOT_REQUESTED';

CREATE INDEX ix_tag_requests_confirmation_delivery
ON tag_requests(guild_id, status, confirmation_delivery_status, confirmation_requested_at, id);

-- These fields are a denormalized, auditable projection of the latest tag
-- state.  The request/event tables remain the complete historical authority.
ALTER TABLE members ADD COLUMN tag_status TEXT;
ALTER TABLE members ADD COLUMN tag_completed_at INTEGER;
ALTER TABLE members ADD COLUMN tag_set_by INTEGER;
ALTER TABLE members ADD COLUMN tag_last_confirmed_at INTEGER;
"""

MIGRATION_031 = """
-- Rate-limit reconciliation requests independently from the normal versioned
-- domain transitions.  A manual Discord-side role edit is repairable without
-- creating an unbounded outbox stream every worker tick.
ALTER TABLE tag_role_sync_state ADD COLUMN last_reconcile_requested_at INTEGER;
"""

MIGRATION_032 = """
-- A durable call reservation enforces the anti-spam window across restart and
-- concurrent responsible users.  The actual successful DM remains a separate
-- immutable event in tag_request_events.
ALTER TABLE tag_requests ADD COLUMN last_call_at INTEGER;
ALTER TABLE tag_requests ADD COLUMN last_call_by INTEGER;
"""

MIGRATION_033 = """
-- A role notification is a durable delivery, not a best-effort side effect of
-- a button callback.  It is intentionally separate from the member's later
-- confirmation notice, because a restart between these two phases must not
-- duplicate either message.
ALTER TABLE tag_requests ADD COLUMN responsible_notification_status TEXT NOT NULL
    DEFAULT 'NOT_REQUESTED' CHECK (responsible_notification_status IN (
        'NOT_REQUESTED','PENDING','PROCESSING','DELIVERED','FAILED'
    ));
ALTER TABLE tag_requests ADD COLUMN responsible_notification_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tag_requests ADD COLUMN responsible_notification_claimed_at INTEGER;
ALTER TABLE tag_requests ADD COLUMN responsible_notification_message_id INTEGER;
ALTER TABLE tag_requests ADD COLUMN responsible_notification_error TEXT;

CREATE INDEX ix_tag_requests_responsible_delivery
ON tag_requests(guild_id, status, responsible_notification_status, requested_at, id);
"""

MIGRATION_034 = """
-- Terminal outcomes have their own recoverable member notice.  A recusal,
-- cancellation or expiration must remain explainable even if Discord was down
-- at the moment the domain decision committed.
ALTER TABLE tag_requests ADD COLUMN terminal_notification_status TEXT NOT NULL
    DEFAULT 'NOT_REQUESTED' CHECK (terminal_notification_status IN (
        'NOT_REQUESTED','PENDING','PROCESSING','DELIVERED','FAILED'
    ));
ALTER TABLE tag_requests ADD COLUMN terminal_notification_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tag_requests ADD COLUMN terminal_notification_claimed_at INTEGER;
ALTER TABLE tag_requests ADD COLUMN terminal_notification_message_id INTEGER;
ALTER TABLE tag_requests ADD COLUMN terminal_notification_error TEXT;

CREATE INDEX ix_tag_requests_terminal_delivery
ON tag_requests(guild_id, status, terminal_notification_status, terminal_at, id);
"""

MIGRATION_035 = """
-- Distinguish a normal request from a member declaration that the MTA tag is
-- already present.  Both paths remain subject to responsible validation; the
-- declaration must never grant TAG SETADA directly from a member click.
ALTER TABLE tag_requests ADD COLUMN request_origin TEXT NOT NULL
    DEFAULT 'SET_REQUEST' CHECK (request_origin IN (
        'SET_REQUEST','EXISTING_DECLARATION'
    ));

CREATE INDEX ix_tag_requests_origin_queue
ON tag_requests(guild_id, request_origin, status, requested_at, id);
"""

MIGRATION_036 = """
-- Public operational status is durable and independent from Discord message
-- state. Manual overrides and automatic observations coexist; the effective
-- projection is rebuilt after restart instead of trusting process memory.
CREATE TABLE system_status_components (
    guild_id INTEGER NOT NULL,
    component_key TEXT NOT NULL,
    detected_state TEXT NOT NULL DEFAULT 'OPERACIONAL' CHECK (detected_state IN (
        'OPERACIONAL','ATUALIZANDO','EM_MANUTENCAO','INSTAVEL_DEGRADADO',
        'TEMPORARIAMENTE_DESATIVADO','INDISPONIVEL'
    )),
    detected_summary TEXT NOT NULL DEFAULT 'Monitoramento iniciado.',
    detected_at INTEGER NOT NULL,
    candidate_state TEXT,
    candidate_summary TEXT,
    candidate_streak INTEGER NOT NULL DEFAULT 0,
    last_signal_at INTEGER,
    last_success_at INTEGER,
    override_state TEXT CHECK (override_state IS NULL OR override_state IN (
        'ATUALIZANDO','EM_MANUTENCAO','INSTAVEL_DEGRADADO',
        'TEMPORARIAMENTE_DESATIVADO','INDISPONIVEL'
    )),
    override_reason TEXT,
    override_responsible_id INTEGER,
    override_started_at INTEGER,
    override_expected_at INTEGER,
    override_expires_at INTEGER,
    last_notification_at INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, component_key)
);

CREATE INDEX ix_system_status_effective
ON system_status_components(guild_id, override_state, detected_state, updated_at);

CREATE TABLE system_status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    component_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    previous_state TEXT,
    next_state TEXT NOT NULL,
    summary TEXT NOT NULL,
    reason TEXT,
    actor_id INTEGER,
    responsible_id INTEGER,
    expected_at INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT NOT NULL UNIQUE,
    notification_status TEXT NOT NULL DEFAULT 'NOT_REQUESTED' CHECK (
        notification_status IN ('NOT_REQUESTED','PENDING','PROCESSING','DELIVERED','FAILED','SUPPRESSED')
    ),
    notification_attempts INTEGER NOT NULL DEFAULT 0,
    notification_claimed_at INTEGER,
    notification_message_id INTEGER,
    notification_error TEXT,
    occurred_at INTEGER NOT NULL
);

CREATE INDEX ix_system_status_timeline
ON system_status_events(guild_id, component_key, occurred_at DESC, id DESC);

CREATE INDEX ix_system_status_notifications
ON system_status_events(guild_id, notification_status, occurred_at, id);
"""

MIGRATION_037 = """
-- Automatic duty is an additive evolution of shifts and patrols.  Shifts
-- remain the official source of service time; patrols become the durable
-- vehicle aggregate for both queue formations and direct voice presence.
ALTER TABLE shifts ADD COLUMN start_source TEXT NOT NULL DEFAULT 'MANUAL' CHECK (
    start_source IN ('MANUAL','VOICE_AUTO','ADMIN','RECOVERY')
);
ALTER TABLE shifts ADD COLUMN initial_voice_channel_id INTEGER;
ALTER TABLE shifts ADD COLUMN current_patrol_id INTEGER
    REFERENCES patrols(id) ON DELETE SET NULL;
ALTER TABLE shifts ADD COLUMN role_snapshot TEXT;
ALTER TABLE shifts ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE patrols ADD COLUMN creation_source TEXT NOT NULL DEFAULT 'QUEUE_AUTO' CHECK (
    creation_source IN ('VOICE_AUTO','QUEUE_AUTO','ADMIN','RECOVERY')
);
ALTER TABLE patrols ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

UPDATE patrols
SET creation_source=CASE WHEN origin='ADMIN' THEN 'ADMIN' ELSE 'QUEUE_AUTO' END;

ALTER TABLE patrol_channels ADD COLUMN logical_key TEXT;
ALTER TABLE patrol_channels ADD COLUMN capacity INTEGER NOT NULL DEFAULT 0
    CHECK (capacity BETWEEN 0 AND 99);
ALTER TABLE patrol_channels ADD COLUMN allowed_role_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE patrol_channels ADD COLUMN automatic_clock INTEGER NOT NULL DEFAULT 1
    CHECK (automatic_clock IN (0,1));

UPDATE patrol_channels SET logical_key='voice:' || channel_id WHERE logical_key IS NULL;

CREATE UNIQUE INDEX ux_patrol_channel_logical_key
ON patrol_channels(guild_id, logical_key)
WHERE logical_key IS NOT NULL;

CREATE TABLE patrol_composition_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    patrol_id INTEGER NOT NULL REFERENCES patrols(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'VEHICLE_CREATED','MEMBER_JOINED','MEMBER_LEFT','MEMBER_MOVED',
        'COMMANDER_CHANGED','CHANNEL_CHANGED','VEHICLE_CLOSED','ADMIN_ADJUSTED'
    )),
    member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER,
    before_channel_id INTEGER,
    after_channel_id INTEGER,
    previous_commander_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    next_commander_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    actor_id INTEGER,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    event_key TEXT NOT NULL UNIQUE,
    occurred_at INTEGER NOT NULL
);

CREATE INDEX ix_patrol_composition_timeline
ON patrol_composition_events(guild_id, patrol_id, occurred_at, id);

CREATE TABLE patrol_occurrence_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, code)
);

CREATE TABLE patrol_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT NOT NULL DEFAULT 'NORMAL' CHECK (
        severity IN ('LOW','NORMAL','HIGH','CRITICAL')
    ),
    category_id INTEGER REFERENCES patrol_occurrence_categories(id) ON DELETE RESTRICT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, code)
);

CREATE TABLE patrol_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    patrol_id INTEGER NOT NULL REFERENCES patrols(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','FINALIZED','VOID')),
    vehicle_number INTEGER NOT NULL,
    voice_channel_id INTEGER NOT NULL,
    commander_member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    commander_discord_id INTEGER,
    started_at INTEGER NOT NULL,
    ended_at INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL CHECK (duration_ms>=0),
    responsible_id INTEGER,
    description TEXT,
    observations TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    finalized_at INTEGER,
    UNIQUE(guild_id, patrol_id)
);

CREATE INDEX ix_patrol_reports_queue
ON patrol_reports(guild_id, status, ended_at DESC, id DESC);

CREATE TABLE patrol_report_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    report_id INTEGER NOT NULL REFERENCES patrol_reports(id) ON DELETE RESTRICT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    rank_name TEXT,
    member_role TEXT NOT NULL,
    joined_at INTEGER,
    left_at INTEGER,
    UNIQUE(report_id, member_id)
);

CREATE INDEX ix_patrol_report_members_member
ON patrol_report_members(guild_id, member_id, report_id DESC);

CREATE TABLE patrol_report_occurrences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    report_id INTEGER NOT NULL REFERENCES patrol_reports(id) ON DELETE RESTRICT,
    subject_member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    subject_discord_id INTEGER,
    subject_name TEXT,
    subject_rank TEXT,
    category_id INTEGER NOT NULL REFERENCES patrol_occurrence_categories(id) ON DELETE RESTRICT,
    article_id INTEGER REFERENCES patrol_articles(id) ON DELETE RESTRICT,
    occurred_at INTEGER NOT NULL,
    reason TEXT NOT NULL,
    description TEXT NOT NULL,
    responsible_id INTEGER NOT NULL,
    observations TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_patrol_report_occurrences_report
ON patrol_report_occurrences(guild_id, report_id, occurred_at, id);

CREATE TABLE patrol_report_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    report_id INTEGER NOT NULL REFERENCES patrol_reports(id) ON DELETE RESTRICT,
    occurrence_id INTEGER REFERENCES patrol_report_occurrences(id) ON DELETE RESTRICT,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('IMAGE','LINK','FILE','NOTE')),
    locator TEXT NOT NULL,
    description TEXT,
    author_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_patrol_report_evidence_report
ON patrol_report_evidence(guild_id, report_id, occurrence_id, created_at, id);

CREATE TABLE patrol_admin_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN (
        'SHIFT_OPENED','SHIFT_CLOSED','SHIFT_CORRECTED','SHIFT_INVALIDATED',
        'MEMBER_ASSIGNED','MEMBER_REMOVED','COMMANDER_OVERRIDDEN','REPORT_VOIDED'
    )),
    patrol_id INTEGER REFERENCES patrols(id) ON DELETE RESTRICT,
    shift_id INTEGER REFERENCES shifts(id) ON DELETE RESTRICT,
    target_discord_id INTEGER,
    actor_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_patrol_admin_adjustments_timeline
ON patrol_admin_adjustments(guild_id, created_at DESC, id DESC);
"""

MIGRATION_038 = """
-- Career progression, merit and officer candidacy extend the canonical member,
-- rank and shift sources. No parallel identity or hour counter is introduced.
-- Some supported legacy snapshots start their recorded migration history at v8
-- and may not contain optional v3 personnel tables. Recreate the canonical
-- action table before extending it so those snapshots can still reach v38.
CREATE TABLE IF NOT EXISTS personnel_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('PROMOTION','DEMOTION')),
    from_rank_id INTEGER REFERENCES ranks(id),
    to_rank_id INTEGER NOT NULL REFERENCES ranks(id),
    reason TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_personnel_actions_member_time
ON personnel_actions(guild_id, discord_id, created_at DESC);

ALTER TABLE personnel_actions ADD COLUMN source TEXT NOT NULL DEFAULT 'MANUAL' CHECK (
    source IN ('MANUAL','AUTOMATIC_HOURS','OFFICER_DECISION','DISCORD_SYNC')
);
ALTER TABLE personnel_actions ADD COLUMN evidence_locator TEXT;
ALTER TABLE personnel_actions ADD COLUMN observations TEXT;
ALTER TABLE personnel_actions ADD COLUMN article_code TEXT;
ALTER TABLE personnel_actions ADD COLUMN correlation_id TEXT;

CREATE UNIQUE INDEX ux_personnel_actions_correlation
ON personnel_actions(correlation_id) WHERE correlation_id IS NOT NULL;

CREATE TABLE career_progression_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    sequence_number INTEGER NOT NULL CHECK (sequence_number BETWEEN 1 AND 100),
    from_rank_id INTEGER NOT NULL REFERENCES ranks(id) ON DELETE RESTRICT,
    to_rank_id INTEGER NOT NULL REFERENCES ranks(id) ON DELETE RESTRICT,
    target_total_ms INTEGER NOT NULL CHECK (target_total_ms>=0),
    minimum_tenure_ms INTEGER NOT NULL DEFAULT 0 CHECK (minimum_tenure_ms>=0),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    updated_by INTEGER,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, sequence_number),
    UNIQUE(guild_id, from_rank_id)
);

CREATE TABLE career_progression_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    rule_id INTEGER NOT NULL REFERENCES career_progression_rules(id) ON DELETE RESTRICT,
    personnel_action_id INTEGER NOT NULL UNIQUE REFERENCES personnel_actions(id) ON DELETE RESTRICT,
    from_rank_id INTEGER NOT NULL REFERENCES ranks(id) ON DELETE RESTRICT,
    to_rank_id INTEGER NOT NULL REFERENCES ranks(id) ON DELETE RESTRICT,
    valid_hours_ms INTEGER NOT NULL,
    rank_tenure_ms INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('AUTOMATIC_HOURS','RECOVERY')),
    idempotency_key TEXT NOT NULL UNIQUE,
    correlation_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    published_at INTEGER
);

CREATE INDEX ix_career_progression_member_time
ON career_progression_events(guild_id, member_id, created_at DESC, id DESC);

CREATE TABLE career_merits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    merit_type TEXT NOT NULL CHECK (merit_type IN ('POSITIVE','NEGATIVE')),
    category TEXT NOT NULL,
    weight INTEGER NOT NULL CHECK (weight BETWEEN 1 AND 10),
    reason TEXT NOT NULL,
    evidence_locator TEXT,
    observation TEXT,
    actor_id INTEGER NOT NULL,
    correlation_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_career_merits_member_time
ON career_merits(guild_id, member_id, created_at DESC, id DESC);

CREATE TABLE officer_questionnaire_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','ACTIVE','RETIRED')),
    title TEXT NOT NULL,
    weights_json TEXT NOT NULL,
    criteria_json TEXT NOT NULL DEFAULT '{}',
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    activated_at INTEGER,
    UNIQUE(guild_id, version_number)
);

CREATE UNIQUE INDEX ux_active_officer_questionnaire
ON officer_questionnaire_versions(guild_id) WHERE status='ACTIVE';

CREATE TABLE officer_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    questionnaire_version_id INTEGER NOT NULL
        REFERENCES officer_questionnaire_versions(id) ON DELETE RESTRICT,
    question_number INTEGER NOT NULL CHECK (question_number BETWEEN 1 AND 30),
    competency TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK (
        question_type IN ('SCENARIO','OPEN','PRIORITIZATION','CONFLICT','ETHICAL','COMMAND','MANAGEMENT')
    ),
    prompt TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1 CHECK (weight>0),
    red_flag_rules_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(questionnaire_version_id, question_number)
);

CREATE TABLE officer_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    questionnaire_version_id INTEGER NOT NULL
        REFERENCES officer_questionnaire_versions(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (
        status IN ('DRAFT','SUBMITTED','IN_REVIEW','INTERVIEW_REQUIRED',
                   'APPROVED_CONDITIONAL','APPROVED','REJECTED','RETURNED','CANCELLED')
    ),
    identity_snapshot_json TEXT NOT NULL,
    career_snapshot_json TEXT NOT NULL,
    score_summary_json TEXT,
    analysis_report_json TEXT,
    assigned_to INTEGER,
    assigned_at INTEGER,
    submitted_at INTEGER,
    reviewed_by INTEGER,
    reviewed_at INTEGER,
    decision_reason TEXT,
    result_released_at INTEGER,
    resubmit_after INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX ux_open_officer_application
ON officer_applications(guild_id, member_id)
WHERE status IN ('DRAFT','SUBMITTED','IN_REVIEW','INTERVIEW_REQUIRED','RETURNED');

CREATE INDEX ix_officer_application_queue
ON officer_applications(guild_id, status, submitted_at, id);

CREATE TABLE officer_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES officer_applications(id) ON DELETE RESTRICT,
    question_id INTEGER NOT NULL REFERENCES officer_questions(id) ON DELETE RESTRICT,
    answer_text TEXT NOT NULL,
    answered_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(application_id, question_id)
);

CREATE TABLE officer_question_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES officer_applications(id) ON DELETE RESTRICT,
    question_id INTEGER NOT NULL REFERENCES officer_questions(id) ON DELETE RESTRICT,
    score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 10),
    rationale TEXT NOT NULL,
    evaluator_id INTEGER,
    source TEXT NOT NULL CHECK (source IN ('RULES','ASSISTANT','HUMAN')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(application_id, question_id, source)
);

CREATE TABLE officer_interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES officer_applications(id) ON DELETE RESTRICT,
    interviewer_id INTEGER NOT NULL,
    scheduled_at INTEGER,
    completed_at INTEGER,
    result TEXT CHECK (result IN ('PENDING','POSITIVE','NEUTRAL','NEGATIVE')),
    observations TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE officer_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES officer_applications(id) ON DELETE RESTRICT,
    condition_text TEXT NOT NULL,
    due_at INTEGER,
    responsible_id INTEGER,
    observation TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','MET','FAILED','CANCELLED')),
    created_at INTEGER NOT NULL,
    resolved_at INTEGER
);

CREATE TABLE officer_application_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES officer_applications(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    previous_status TEXT,
    next_status TEXT,
    actor_id INTEGER,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT NOT NULL UNIQUE,
    occurred_at INTEGER NOT NULL
);

CREATE INDEX ix_officer_application_timeline
ON officer_application_events(application_id, occurred_at, id);
"""

MIGRATION_039 = """
-- Durable Discord/channel delivery for career, merit and officer events. Kept
-- separate from migration 38 so an environment that already opened the new
-- domain schema still receives the delivery outbox.
CREATE TABLE career_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    notification_type TEXT NOT NULL CHECK (
        notification_type IN (
            'PROMOTION','DEMOTION','MERIT','OFFICER_SUBMITTED','OFFICER_DECISION'
        )
    ),
    subject_id INTEGER NOT NULL,
    target_discord_id INTEGER,
    channel_setting_key TEXT,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','PROCESSING','DELIVERED','FAILED')
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts>=0),
    available_at INTEGER NOT NULL,
    delivered_at INTEGER,
    channel_message_id INTEGER,
    dm_message_id INTEGER,
    last_error TEXT,
    correlation_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX ix_career_notifications_delivery
ON career_notifications(status, available_at, id);
"""

MIGRATION_040 = """
-- Central de Auxílio Financeiro. Valores são sempre inteiros em centavos;
-- não há FLOAT nem saldo mutável sem lançamento correspondente. A base é
-- append-only: cancelamentos/estornos acrescentam eventos e lançamentos.
CREATE TABLE financial_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    public_code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    target_cents INTEGER NOT NULL CHECK (target_cents > 0),
    collected_cents INTEGER NOT NULL DEFAULT 0 CHECK (collected_cents >= 0),
    status TEXT NOT NULL DEFAULT 'EM_PLANEJAMENTO' CHECK (status IN (
        'EM_PLANEJAMENTO','EM_ANDAMENTO','CONCLUIDA','CANCELADA','SUSPENSA'
    )),
    deadline_at INTEGER,
    responsible_id INTEGER,
    notes TEXT,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    completed_at INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(guild_id, public_code)
);

CREATE INDEX ix_financial_projects_active
ON financial_projects(guild_id, status, created_at DESC, id DESC);

CREATE TABLE financial_contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    destination_kind TEXT NOT NULL CHECK (destination_kind IN ('FUNDO_GERAL','PROJETO')),
    project_id INTEGER REFERENCES financial_projects(id) ON DELETE RESTRICT,
    visibility TEXT NOT NULL CHECK (visibility IN ('PUBLICO','ANONIMO')),
    observation TEXT,
    status TEXT NOT NULL DEFAULT 'PENDENTE' CHECK (status IN (
        'PENDENTE','CONFIRMADA','NAO_CONFIRMADA','CANCELADA'
    )),
    declared_at INTEGER NOT NULL,
    confirmed_at INTEGER,
    confirmed_by INTEGER,
    final_reason TEXT,
    reversed_at INTEGER,
    reversed_by INTEGER,
    reversal_reason TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    CHECK (
        (destination_kind='FUNDO_GERAL' AND project_id IS NULL)
        OR (destination_kind='PROJETO' AND project_id IS NOT NULL)
    ),
    UNIQUE(guild_id, idempotency_key)
);

CREATE INDEX ix_financial_contributions_review
ON financial_contributions(guild_id, status, declared_at, id);
CREATE INDEX ix_financial_contributions_member
ON financial_contributions(guild_id, member_id, declared_at DESC, id DESC);

CREATE TABLE financial_contribution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contribution_id INTEGER NOT NULL REFERENCES financial_contributions(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'DECLARED','CONFIRMED','NOT_CONFIRMED','CANCELLED','REVERSED'
    )),
    actor_id INTEGER,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT NOT NULL UNIQUE,
    occurred_at INTEGER NOT NULL
);

CREATE INDEX ix_financial_contribution_events_timeline
ON financial_contribution_events(contribution_id, occurred_at, id);

CREATE TABLE financial_ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    entry_type TEXT NOT NULL CHECK (entry_type IN (
        'CONTRIBUICAO_CONFIRMADA','DESPESA','ESTORNO_CONTRIBUICAO','ESTORNO_DESPESA'
    )),
    amount_cents INTEGER NOT NULL CHECK (amount_cents <> 0),
    fund_code TEXT NOT NULL DEFAULT 'FUNDO_GERAL',
    project_id INTEGER REFERENCES financial_projects(id) ON DELETE RESTRICT,
    contribution_id INTEGER REFERENCES financial_contributions(id) ON DELETE RESTRICT,
    expense_id INTEGER,
    reverses_entry_id INTEGER REFERENCES financial_ledger_entries(id) ON DELETE RESTRICT,
    description TEXT NOT NULL,
    actor_id INTEGER,
    status TEXT NOT NULL DEFAULT 'POSTADO' CHECK (status IN ('POSTADO','ESTORNADO')),
    correlation_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX ux_financial_ledger_confirmed_contribution
ON financial_ledger_entries(contribution_id)
WHERE entry_type='CONTRIBUICAO_CONFIRMADA';
CREATE UNIQUE INDEX ux_financial_ledger_reversal
ON financial_ledger_entries(reverses_entry_id)
WHERE reverses_entry_id IS NOT NULL;
CREATE INDEX ix_financial_ledger_project_time
ON financial_ledger_entries(guild_id, project_id, created_at DESC, id DESC);

CREATE TABLE financial_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    project_id INTEGER REFERENCES financial_projects(id) ON DELETE RESTRICT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    recorded_by INTEGER NOT NULL,
    recorded_at INTEGER NOT NULL,
    reversed_at INTEGER,
    reversed_by INTEGER,
    reversal_reason TEXT,
    ledger_entry_id INTEGER UNIQUE REFERENCES financial_ledger_entries(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX ix_financial_expenses_project_time
ON financial_expenses(guild_id, project_id, recorded_at DESC, id DESC);

CREATE TABLE financial_project_sponsors (
    project_id INTEGER NOT NULL REFERENCES financial_projects(id) ON DELETE RESTRICT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    visibility TEXT NOT NULL CHECK (visibility IN ('PUBLICO','ANONIMO')),
    declared_at INTEGER NOT NULL,
    withdrawn_at INTEGER,
    PRIMARY KEY(project_id, member_id)
);

CREATE TABLE financial_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    estimated_cents INTEGER CHECK (estimated_cents IS NULL OR estimated_cents >= 0),
    motivation TEXT NOT NULL,
    reference_url TEXT,
    status TEXT NOT NULL DEFAULT 'PENDENTE' CHECK (status IN (
        'PENDENTE','EM_ANALISE','ACEITA','RECUSADA','ARQUIVADA'
    )),
    reviewed_by INTEGER,
    reviewed_at INTEGER,
    review_reason TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX ix_financial_suggestions_queue
ON financial_suggestions(guild_id, status, created_at, id);

CREATE TABLE financial_honor_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    honor_key TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    discord_role_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    symbolic_only INTEGER NOT NULL DEFAULT 1 CHECK (symbolic_only=1),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, honor_key)
);

CREATE TABLE financial_member_honors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    honor_definition_id INTEGER NOT NULL REFERENCES financial_honor_definitions(id) ON DELETE RESTRICT,
    source TEXT NOT NULL CHECK (source IN ('AUTOMATICA','MANUAL')),
    justification TEXT NOT NULL,
    granted_by INTEGER,
    granted_at INTEGER NOT NULL,
    expires_at INTEGER,
    removed_by INTEGER,
    removed_at INTEGER,
    removal_reason TEXT,
    correlation_id TEXT NOT NULL UNIQUE,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX ux_financial_member_honor_active
ON financial_member_honors(guild_id, member_id, honor_definition_id)
WHERE removed_at IS NULL;
CREATE INDEX ix_financial_member_honors_member
ON financial_member_honors(guild_id, member_id, granted_at DESC, id DESC);

CREATE TABLE financial_achievement_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    achievement_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE financial_member_achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    achievement_definition_id INTEGER NOT NULL REFERENCES financial_achievement_definitions(id) ON DELETE RESTRICT,
    source TEXT NOT NULL CHECK (source IN ('AUTOMATICA','MANUAL')),
    reason TEXT NOT NULL,
    awarded_by INTEGER,
    awarded_at INTEGER NOT NULL,
    correlation_id TEXT NOT NULL UNIQUE,
    UNIQUE(guild_id, member_id, achievement_definition_id)
);

CREATE TABLE financial_certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    honor_id INTEGER REFERENCES financial_member_honors(id) ON DELETE RESTRICT,
    project_id INTEGER REFERENCES financial_projects(id) ON DELETE RESTRICT,
    validation_code TEXT NOT NULL UNIQUE,
    issued_by INTEGER NOT NULL,
    issued_at INTEGER NOT NULL,
    revoked_by INTEGER,
    revoked_at INTEGER,
    revocation_reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE financial_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    actor_id INTEGER,
    target_member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    contribution_id INTEGER REFERENCES financial_contributions(id) ON DELETE RESTRICT,
    project_id INTEGER REFERENCES financial_projects(id) ON DELETE RESTRICT,
    ledger_entry_id INTEGER REFERENCES financial_ledger_entries(id) ON DELETE RESTRICT,
    honor_id INTEGER REFERENCES financial_member_honors(id) ON DELETE RESTRICT,
    before_json TEXT,
    after_json TEXT,
    reason TEXT,
    correlation_id TEXT NOT NULL UNIQUE,
    occurred_at INTEGER NOT NULL
);

CREATE INDEX ix_financial_audit_timeline
ON financial_audit_events(guild_id, occurred_at DESC, id DESC);
"""

MIGRATION_041 = """
-- Durable, privacy-minimized financial notifications. The payment and audit
-- transaction writes the intent; Discord delivery is retried by the sole
-- Gateway process after commit and never determines a financial decision.
CREATE TABLE financial_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    notification_type TEXT NOT NULL CHECK (notification_type IN (
        'CONTRIBUTION_DECIDED','PROJECT_COMPLETED','HONOR_GRANTED',
        'HONOR_REMOVED','CERTIFICATE_ISSUED','SUGGESTION_REVIEWED'
    )),
    subject_type TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    target_discord_id INTEGER,
    channel_setting_key TEXT,
    payload_json TEXT NOT NULL,
    event_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PROCESSING','DELIVERED','FAILED')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts>=0),
    available_at INTEGER NOT NULL,
    delivered_at INTEGER,
    channel_message_id INTEGER,
    dm_message_id INTEGER,
    last_error TEXT,
    correlation_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, event_key)
);

CREATE INDEX ix_financial_notifications_delivery
ON financial_notifications(status, available_at, id);
"""

MIGRATION_042 = """
-- Destaques financeiros são uma projeção pública opt-in e recuperável. A
-- identidade continua controlada por visibility; o valor individual exige um
-- consentimento separado, que é falso para todo registro preexistente.
ALTER TABLE financial_contributions ADD COLUMN public_amount INTEGER NOT NULL
    DEFAULT 0 CHECK (public_amount IN (0,1));

-- Recrie a outbox para acrescentar o destaque e uma revisão compare-and-set.
-- O event_key permanece único por contribuição e o channel_message_id é
-- preservado quando um estorno rearma a mesma publicação para edição.
ALTER TABLE financial_notifications RENAME TO financial_notifications_v41;
DROP INDEX IF EXISTS ix_financial_notifications_delivery;

CREATE TABLE financial_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    notification_type TEXT NOT NULL CHECK (notification_type IN (
        'CONTRIBUTION_DECIDED','CONTRIBUTION_HIGHLIGHT','PROJECT_COMPLETED',
        'HONOR_GRANTED','HONOR_REMOVED','CERTIFICATE_ISSUED','SUGGESTION_REVIEWED'
    )),
    subject_type TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    target_discord_id INTEGER,
    channel_setting_key TEXT,
    payload_json TEXT NOT NULL,
    event_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PROCESSING','DELIVERED','FAILED')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts>=0),
    available_at INTEGER NOT NULL,
    delivered_at INTEGER,
    channel_message_id INTEGER,
    dm_message_id INTEGER,
    last_error TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision>=1),
    correlation_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, event_key)
);

INSERT INTO financial_notifications(
    id, guild_id, notification_type, subject_type, subject_id,
    target_discord_id, channel_setting_key, payload_json, event_key,
    status, attempts, available_at, delivered_at, channel_message_id,
    dm_message_id, last_error, revision, correlation_id, created_at, updated_at
)
SELECT id, guild_id, notification_type, subject_type, subject_id,
       target_discord_id, channel_setting_key, payload_json, event_key,
       status, attempts, available_at, delivered_at, channel_message_id,
       dm_message_id, last_error, 1, correlation_id, created_at, updated_at
FROM financial_notifications_v41;

DROP TABLE financial_notifications_v41;

CREATE INDEX ix_financial_notifications_delivery
ON financial_notifications(status, available_at, id);

-- Alinhe somente os títulos canônicos anteriores; concessões e histórico não
-- são tocados e Patrono continua estritamente manual.
UPDATE financial_honor_definitions
SET title=CASE honor_key
    WHEN 'APOIADOR' THEN '💎 Apoiador da CHOQUE'
    WHEN 'COLABORADOR' THEN '🌟 Colaborador da CHOQUE'
    WHEN 'BENFEITOR' THEN '🏅 Benfeitor da CHOQUE'
    WHEN 'PATRONO' THEN '👑 Patrono da CHOQUE'
    ELSE title
END
WHERE honor_key IN ('APOIADOR','COLABORADOR','BENFEITOR','PATRONO');
"""

MIGRATION_043 = """
-- A ficha única da Central de Tags é uma projeção versionada do agregado.
-- Somente solicitações ativas preexistentes precisam de uma primeira
-- atualização visual; fichas futuras avançam junto com a versão do pedido.
ALTER TABLE tag_requests ADD COLUMN request_card_rendered_version INTEGER;

UPDATE tag_requests
SET request_card_rendered_version=version
WHERE responsible_notification_message_id IS NOT NULL
  AND status IN ('CONCLUIDO','RECUSADO','CANCELADO','EXPIRADO');

CREATE INDEX ix_tag_requests_card_refresh
ON tag_requests(guild_id, responsible_notification_message_id,
                request_card_rendered_version, version, updated_at, id);
"""

MIGRATION_044 = """
-- Níveis legados permitiam concluir a Portaria sem criar vínculo no efetivo.
-- Cadastros completos e sem conflito tornam-se membros ativos; registros vazios
-- continuam não cadastrados e conflitos voltam para a revisão humana.
DROP TABLE IF EXISTS visitor_effective_members;
CREATE TEMP TABLE visitor_effective_members AS
SELECT r.id AS registration_id,
       r.guild_id,
       r.discord_id,
       r.mta_nick,
       r.bgr_id,
       COALESCE(r.completed_at, r.submitted_at, r.created_at) AS joined_at,
       (
           SELECT rk.id
           FROM ranks rk
           WHERE rk.guild_id=r.guild_id AND rk.active=1
           ORDER BY rk.level, rk.id
           LIMIT 1
       ) AS rank_id
FROM registration_gate_records r
WHERE r.status='REGISTERED'
  AND r.access_tier IN ('REGISTERED_VISITOR','CANDIDATE','RECRUIT')
  AND r.member_id IS NULL
  AND trim(COALESCE(r.mta_nick, ''))<>''
  AND trim(COALESCE(r.bgr_id, ''))<>''
  AND NOT EXISTS (
      SELECT 1 FROM members m
      WHERE m.guild_id=r.guild_id AND m.discord_id=r.discord_id
  )
  AND NOT EXISTS (
      SELECT 1 FROM members m
      WHERE m.guild_id=r.guild_id
        AND lower(trim(COALESCE(m.character_id, '')))=lower(trim(r.bgr_id))
  );

INSERT INTO members(
    guild_id, discord_id, discord_nick, mta_nick, character_id,
    rank_id, status, joined_at, last_activity_at, created_at, updated_at
)
SELECT guild_id, discord_id, mta_nick, mta_nick, bgr_id,
       rank_id, 'ACTIVE', joined_at, joined_at, joined_at, joined_at
FROM visitor_effective_members;

INSERT INTO recruit_onboarding_checklists(
    guild_id, member_id, registration_status, updated_at
)
SELECT v.guild_id, m.id, 'COMPLETED',
       CAST(strftime('%s','now') AS INTEGER) * 1000
FROM visitor_effective_members v
JOIN members m ON m.guild_id=v.guild_id AND m.discord_id=v.discord_id
WHERE 1
ON CONFLICT(guild_id, member_id) DO UPDATE SET
    registration_status='COMPLETED', updated_at=excluded.updated_at;

INSERT INTO web_action_outbox(
    guild_id, action_type, target_discord_id, payload_json,
    requested_by, correlation_id, available_at, created_at
)
SELECT v.guild_id, 'MEMBER_SYNC', v.discord_id,
       '{"source":"REGISTERED_VISITOR_RETIREMENT","flow":"PORTARIA_DIGITAL"}',
       v.discord_id, 'visitor-retirement-member-sync:' || v.registration_id,
       CAST(strftime('%s','now') AS INTEGER) * 1000,
       CAST(strftime('%s','now') AS INTEGER) * 1000
FROM visitor_effective_members v;

UPDATE registration_gate_records
SET member_id=(
        SELECT m.id FROM members m
        WHERE m.guild_id=registration_gate_records.guild_id
          AND m.discord_id=registration_gate_records.discord_id
    ),
    access_tier=CASE
        WHEN EXISTS (
            SELECT 1 FROM visitor_effective_members v
            WHERE v.registration_id=registration_gate_records.id AND v.rank_id IS NOT NULL
        ) THEN 'RECRUIT'
        ELSE 'MEMBER'
    END,
    conflict_code=NULL, conflict_member_id=NULL,
    sync_status='PENDING', sync_error=NULL,
    completed_at=COALESCE(completed_at, submitted_at, created_at),
    version=version+1,
    updated_at=CAST(strftime('%s','now') AS INTEGER) * 1000
WHERE id IN (SELECT registration_id FROM visitor_effective_members);

INSERT INTO registration_gate_events(
    guild_id, registration_id, event_type, actor_id, source, metadata_json, created_at
)
SELECT guild_id, registration_id, 'REGISTRATION_IDENTITY_LINKED', NULL,
       'SYSTEM_RECONCILIATION',
       '{"source":"REGISTERED_VISITOR_RETIREMENT"}',
       CAST(strftime('%s','now') AS INTEGER) * 1000
FROM visitor_effective_members;

INSERT INTO audit_logs(
    correlation_id, guild_id, action, actor_id, target_id,
    before_json, after_json, reason, created_at
)
SELECT 'registration-visitor-retirement:' || registration_id,
       guild_id, 'REGISTRATION_IDENTITY_LINKED', NULL, discord_id,
       '{"access_tier":"LEGACY_UNLINKED","member_id":null}',
       '{"access_tier":"RECRUIT_OR_MEMBER","member_linked":true}',
       'Aposentadoria do nível visitante; cadastro funcional convertido em membro efetivo.',
       CAST(strftime('%s','now') AS INTEGER) * 1000
FROM visitor_effective_members;

-- Um ID já usado por outro membro nunca é sobrescrito automaticamente.
DELETE FROM registration_delivery_claims
WHERE registration_id IN (
    SELECT r.id
    FROM registration_gate_records r
    WHERE r.status='REGISTERED'
      AND r.access_tier IN ('REGISTERED_VISITOR','CANDIDATE','RECRUIT')
      AND r.member_id IS NULL
      AND trim(COALESCE(r.mta_nick, ''))<>''
      AND trim(COALESCE(r.bgr_id, ''))<>''
      AND EXISTS (
          SELECT 1 FROM members m
          WHERE m.guild_id=r.guild_id
            AND lower(trim(COALESCE(m.character_id, '')))=lower(trim(r.bgr_id))
      )
);

UPDATE registration_gate_records
SET status='REQUIRES_REVIEW', access_tier='CANDIDATE',
    conflict_code='BGR_ID_ALREADY_LINKED',
    conflict_member_id=(
        SELECT m.id FROM members m
        WHERE m.guild_id=registration_gate_records.guild_id
          AND lower(trim(COALESCE(m.character_id, '')))=
              lower(trim(registration_gate_records.bgr_id))
        ORDER BY m.id LIMIT 1
    ),
    completed_at=NULL, reviewed_at=NULL, reviewed_by=NULL, review_reason=NULL,
    review_channel_id=NULL, review_message_id=NULL,
    result_channel_id=NULL, result_message_id=NULL,
    delivery_status='PENDING', sync_status='NOT_REQUIRED', sync_error=NULL,
    version=version+1,
    updated_at=CAST(strftime('%s','now') AS INTEGER) * 1000
WHERE status='REGISTERED'
  AND access_tier IN ('REGISTERED_VISITOR','CANDIDATE','RECRUIT')
  AND member_id IS NULL
  AND trim(COALESCE(mta_nick, ''))<>''
  AND trim(COALESCE(bgr_id, ''))<>''
  AND EXISTS (
      SELECT 1 FROM members m
      WHERE m.guild_id=registration_gate_records.guild_id
        AND lower(trim(COALESCE(m.character_id, '')))=
            lower(trim(registration_gate_records.bgr_id))
  );

-- Registros sem identidade continuam sem cadastro; nenhum membro falso é criado.
UPDATE registration_gate_records
SET status='UNREGISTERED', access_tier='CANDIDATE', member_id=NULL,
    completed_at=NULL, sync_status='NOT_REQUIRED', sync_error=NULL,
    version=version+1,
    updated_at=CAST(strftime('%s','now') AS INTEGER) * 1000
WHERE status='REGISTERED'
  AND access_tier IN ('REGISTERED_VISITOR','CANDIDATE','RECRUIT')
  AND member_id IS NULL
  AND (trim(COALESCE(mta_nick, ''))='' OR trim(COALESCE(bgr_id, ''))='');

UPDATE registration_gate_records
SET access_tier=CASE
        WHEN member_id IS NOT NULL AND status='REGISTERED' THEN
            CASE WHEN (
                SELECT m.rank_id FROM members m
                WHERE m.id=registration_gate_records.member_id
            )=(
                SELECT rk.id FROM ranks rk
                WHERE rk.guild_id=registration_gate_records.guild_id AND rk.active=1
                ORDER BY rk.level, rk.id LIMIT 1
            ) THEN 'RECRUIT' ELSE 'MEMBER' END
        ELSE 'CANDIDATE'
    END,
    version=version+1,
    updated_at=CAST(strftime('%s','now') AS INTEGER) * 1000
WHERE access_tier='REGISTERED_VISITOR';

DROP TABLE visitor_effective_members;

DROP TRIGGER IF EXISTS registration_gate_reject_visitor_insert;
CREATE TRIGGER registration_gate_reject_visitor_insert
BEFORE INSERT ON registration_gate_records
WHEN NEW.access_tier='REGISTERED_VISITOR'
BEGIN
    SELECT RAISE(ABORT, 'REGISTERED_VISITOR foi aposentado');
END;

DROP TRIGGER IF EXISTS registration_gate_reject_visitor_update;
CREATE TRIGGER registration_gate_reject_visitor_update
BEFORE UPDATE OF access_tier ON registration_gate_records
WHEN NEW.access_tier='REGISTERED_VISITOR'
BEGIN
    SELECT RAISE(ABORT, 'REGISTERED_VISITOR foi aposentado');
END;
"""

MIGRATION_045 = """
-- O Responsável pelo Recrutamento precisa concluir a análise sem receber
-- permissões administrativas fora do módulo. O Auxiliar permanece restrito
-- a visualizar, assumir e avaliar candidaturas.
INSERT INTO functional_position_permissions(
    position_id, permission, effect, created_at, updated_at
)
SELECT id, 'recruitment.approve', 'GRANT',
       CAST(strftime('%s','now') AS INTEGER) * 1000,
       CAST(strftime('%s','now') AS INTEGER) * 1000
FROM functional_positions
WHERE code='RECRUITMENT_LEAD' AND enabled=1
ON CONFLICT(position_id, permission) DO UPDATE SET
    effect='GRANT', updated_at=excluded.updated_at;

INSERT INTO functional_position_permissions(
    position_id, permission, effect, created_at, updated_at
)
SELECT id, 'recruitment.reject', 'GRANT',
       CAST(strftime('%s','now') AS INTEGER) * 1000,
       CAST(strftime('%s','now') AS INTEGER) * 1000
FROM functional_positions
WHERE code='RECRUITMENT_LEAD' AND enabled=1
ON CONFLICT(position_id, permission) DO UPDATE SET
    effect='GRANT', updated_at=excluded.updated_at;
"""

MIGRATION_046 = """
-- Unidades especiais estendem identidade, patente, auditoria e outbox
-- canônicos. Apenas candidatura, vínculo e recursos Discord específicos
-- precisam de estado próprio.
ALTER TABLE web_action_outbox RENAME TO web_action_outbox_v46;
DROP INDEX IF EXISTS ix_web_action_outbox_delivery;

CREATE TABLE web_action_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    action_type TEXT NOT NULL CHECK (
        action_type IN (
            'RANK_SYNC','MEMBER_SYNC','PANEL_REFRESH',
            'IDENTITY_SYNC','IDENTITY_RECONCILE_BULK','QUALIFICATION_SYNC',
            'TAG_ROLE_SYNC','SPECIAL_UNIT_ROLE_SYNC'
        )
    ),
    target_discord_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    requested_by INTEGER NOT NULL,
    correlation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','PROCESSING','COMPLETED','FAILED')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    processed_at INTEGER,
    last_error TEXT
);

INSERT INTO web_action_outbox(
    id, guild_id, action_type, target_discord_id, payload_json,
    requested_by, correlation_id, status, attempts, available_at,
    created_at, processed_at, last_error
)
SELECT id, guild_id, action_type, target_discord_id, payload_json,
       requested_by, correlation_id, status, attempts, available_at,
       created_at, processed_at, last_error
FROM web_action_outbox_v46;

DROP TABLE web_action_outbox_v46;

CREATE INDEX ix_web_action_outbox_delivery
ON web_action_outbox(status, available_at, created_at);

CREATE TABLE special_units (
    code TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

INSERT INTO special_units(code, display_name, sort_order, created_at, updated_at)
VALUES
    ('ROCAM', 'COMANDO ROCAM', 10, CAST(strftime('%s','now') AS INTEGER)*1000, CAST(strftime('%s','now') AS INTEGER)*1000),
    ('TATICO', 'COMANDO TÁTICO', 20, CAST(strftime('%s','now') AS INTEGER)*1000, CAST(strftime('%s','now') AS INTEGER)*1000),
    ('ELITE', 'COMANDO ELITE', 30, CAST(strftime('%s','now') AS INTEGER)*1000, CAST(strftime('%s','now') AS INTEGER)*1000),
    ('CORREGEDORIA', 'COMANDO CORREGEDORIA', 40, CAST(strftime('%s','now') AS INTEGER)*1000, CAST(strftime('%s','now') AS INTEGER)*1000);

CREATE TABLE special_unit_guild_resources (
    unit_code TEXT NOT NULL REFERENCES special_units(code) ON DELETE RESTRICT,
    guild_id INTEGER NOT NULL,
    category_id INTEGER,
    central_channel_id INTEGER,
    panel_message_id INTEGER,
    member_role_id INTEGER,
    assistant_role_id INTEGER,
    command_role_id INTEGER,
    updated_by INTEGER,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(unit_code, guild_id)
);

CREATE TABLE special_unit_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recruitment_guild_id INTEGER NOT NULL,
    canonical_guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    unit_code TEXT NOT NULL REFERENCES special_units(code) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','APPROVED','REJECTED','CANCELLED')
    ),
    assigned_to INTEGER,
    assigned_at INTEGER,
    reviewed_by INTEGER,
    reviewed_at INTEGER,
    decision_reason TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    submitted_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX ux_special_unit_open_application
ON special_unit_applications(canonical_guild_id, member_id)
WHERE status='PENDING';

CREATE INDEX ix_special_unit_application_queue
ON special_unit_applications(recruitment_guild_id, status, submitted_at, id);

CREATE TABLE special_unit_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    unit_code TEXT NOT NULL REFERENCES special_units(code) ON DELETE RESTRICT,
    role_level TEXT NOT NULL DEFAULT 'MEMBER' CHECK (
        role_level IN ('MEMBER','ASSISTANT','COMMAND')
    ),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (
        status IN ('ACTIVE','LEFT','TRANSFERRED')
    ),
    version INTEGER NOT NULL DEFAULT 1,
    joined_at INTEGER NOT NULL,
    left_at INTEGER,
    changed_by INTEGER,
    change_reason TEXT,
    updated_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX ux_special_unit_active_membership
ON special_unit_memberships(canonical_guild_id, member_id)
WHERE status='ACTIVE';

CREATE INDEX ix_special_unit_membership_unit
ON special_unit_memberships(canonical_guild_id, unit_code, status, role_level);

CREATE TABLE special_unit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_guild_id INTEGER NOT NULL,
    unit_code TEXT NOT NULL REFERENCES special_units(code) ON DELETE RESTRICT,
    member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT,
    application_id INTEGER REFERENCES special_unit_applications(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    actor_id INTEGER,
    previous_state TEXT,
    next_state TEXT,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);

CREATE INDEX ix_special_unit_events_timeline
ON special_unit_events(canonical_guild_id, unit_code, created_at DESC, id DESC);
"""

MIGRATION_047 = """
-- Ausencia operacional: o ciclo e os alertas sao duraveis para que um
-- reinicio nunca repita os avisos de 3/7/10 dias.
CREATE TABLE activity_absence_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    discord_id INTEGER NOT NULL,
    unit_code TEXT,
    cycle_started_at INTEGER NOT NULL,
    threshold_days INTEGER NOT NULL CHECK (threshold_days IN (3,7,10)),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','DELIVERED','DISABLED','JUSTIFIED')
    ),
    channel_id INTEGER,
    message_id INTEGER,
    created_at INTEGER NOT NULL,
    delivered_at INTEGER,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, member_id, cycle_started_at, threshold_days)
);

CREATE INDEX ix_activity_absence_alert_delivery
ON activity_absence_alerts(guild_id, status, created_at, id);

CREATE TABLE activity_absence_controls (
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0,1)),
    disabled_by INTEGER,
    disabled_at INTEGER,
    reason TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(guild_id, member_id)
);

-- Entrada por indicacao usa a candidatura e a admissao existentes. Estes
-- campos apenas identificam a origem e os metadados minimos do novo caminho.
ALTER TABLE recruitment_applications
ADD COLUMN entry_method TEXT NOT NULL DEFAULT 'FORM';
ALTER TABLE recruitment_applications ADD COLUMN indicated_by INTEGER;
ALTER TABLE recruitment_applications ADD COLUMN requested_unit_code TEXT;
ALTER TABLE recruitment_applications ADD COLUMN indication_notes TEXT;

CREATE INDEX ix_recruitment_entry_method
ON recruitment_applications(guild_id, entry_method, status, submitted_at, id);
"""

MIGRATIONS = (
    (1, MIGRATION_001),
    (2, MIGRATION_002),
    (3, MIGRATION_003),
    (4, MIGRATION_004),
    (5, MIGRATION_005),
    (6, MIGRATION_006),
    (7, MIGRATION_007),
    (8, MIGRATION_008),
    (9, MIGRATION_009),
    (10, MIGRATION_010),
    (11, MIGRATION_011),
    (12, MIGRATION_012),
    (13, MIGRATION_013),
    (14, MIGRATION_014),
    (15, MIGRATION_015),
    (16, MIGRATION_016),
    (17, MIGRATION_017),
    (18, MIGRATION_018),
    (19, MIGRATION_019),
    (20, MIGRATION_020),
    (21, MIGRATION_021),
    (22, MIGRATION_022),
    (23, MIGRATION_023),
    (24, MIGRATION_024),
    (25, MIGRATION_025),
    (26, MIGRATION_026),
    (27, MIGRATION_027),
    (28, MIGRATION_028),
    (29, MIGRATION_029),
    (30, MIGRATION_030),
    (31, MIGRATION_031),
    (32, MIGRATION_032),
    (33, MIGRATION_033),
    (34, MIGRATION_034),
    (35, MIGRATION_035),
    (36, MIGRATION_036),
    (37, MIGRATION_037),
    (38, MIGRATION_038),
    (39, MIGRATION_039),
    (40, MIGRATION_040),
    (41, MIGRATION_041),
    (42, MIGRATION_042),
    (43, MIGRATION_043),
    (44, MIGRATION_044),
    (45, MIGRATION_045),
    (46, MIGRATION_046),
    (47, MIGRATION_047),
)


@dataclass
class _TransactionState:
    """Task-local ownership of the single aiosqlite connection."""

    depth: int = 1
    rollback_only: bool = False
    callbacks: list[Callable[[], Awaitable[object] | object]] = field(default_factory=list)
    owner_task: asyncio.Task[object] | None = None


class Database:
    def __init__(self, path: Path, legacy_path: Path | None = None):
        self.path = path
        self.legacy_path = legacy_path
        self.connection: aiosqlite.Connection | None = None
        # One aiosqlite connection is shared by many Discord callbacks.  A
        # normal asyncio.Lock around only BEGIN is insufficient: reads from a
        # different callback can interleave with an open write transaction and
        # a nested service call can attempt a second BEGIN.  Keep ownership in
        # a ContextVar so the owning task can compose transactions while all
        # other tasks wait for the connection to become idle.
        self._connection_lock = asyncio.Lock()
        self._transaction_state: contextvars.ContextVar[_TransactionState | None] = (
            contextvars.ContextVar("database_transaction_state", default=None)
        )

    async def open(self) -> None:
        if self.connection:
            return
        self._prepare_files()
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA foreign_keys=ON")
        await self.connection.execute("PRAGMA busy_timeout=5000")
        await self._migrate()
        # PRAGMAs e leituras de bootstrap nao podem deixar uma transacao de
        # leitura aberta. Em producao, bot e API sao processos distintos sobre
        # o mesmo SQLite; um snapshot preso aqui impede a API de enxergar
        # presencas de voz gravadas pelo bot ate o proximo restart.
        await self.connection.commit()

    def _prepare_files(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() and self.legacy_path and self.legacy_path.exists():
            shutil.copy2(self.legacy_path, self.path)
            LOGGER.info("Banco legado copiado para %s", self.path)
        if self.path.exists():
            backup_marker = self.path.with_suffix(self.path.suffix + ".migration-backup")
            if not backup_marker.exists():
                shutil.copy2(self.path, backup_marker)
                LOGGER.info("Backup pre-migration criado em %s", backup_marker)

    async def _migrate(self) -> None:
        assert self.connection is not None
        row = await self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        applied_versions: set[int] = set()
        if row:
            # Do not infer the full migration history from MAX(version).  A
            # restored/partially-repaired database can have a non-terminal
            # gap (for example 28 recorded while 27 is absent); skipping that
            # gap silently leaves its data migration unapplied.
            applied_rows = await self.fetchall("SELECT version FROM schema_migrations")
            applied_versions = {int(item["version"]) for item in applied_rows}
        # A few pre-versioned legacy snapshots begin their history at a
        # migration floor (for example, only v8 is recorded).  Versions below
        # that floor are intentionally implicit in those snapshots.  From the
        # first recorded version onward, however, every absent version is a
        # real gap and must be executed even if a later version exists.
        migration_floor = min(applied_versions) if applied_versions else 1
        for migration_version, script in MIGRATIONS:
            if migration_version < migration_floor or migration_version in applied_versions:
                continue
            async with self._connection_lock:
                try:
                    await self.connection.executescript("BEGIN IMMEDIATE;\n" + script)
                    await self.connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (migration_version, int(time.time() * 1000)),
                    )
                    await self.connection.commit()
                except Exception:
                    await self.connection.rollback()
                    raise
            applied_versions.add(migration_version)

    async def close(self) -> None:
        if self.connection:
            await self.connection.close()
            self.connection = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        if not self.connection:
            raise RuntimeError("Banco nao inicializado")
        state = self._owned_transaction_state()
        if state is not None:
            state.depth += 1
            try:
                yield self.connection
            except Exception:
                state.rollback_only = True
                raise
            finally:
                state.depth -= 1
            return

        state = _TransactionState(owner_task=asyncio.current_task())
        async with self._connection_lock:
            token = self._transaction_state.set(state)
            try:
                await self.connection.execute("BEGIN IMMEDIATE")
                try:
                    yield self.connection
                except Exception:
                    state.rollback_only = True
                    await self.connection.rollback()
                    raise
                else:
                    if state.rollback_only:
                        await self.connection.rollback()
                        raise RuntimeError("Transação marcada para rollback por uma operação aninhada.")
                    await self.connection.commit()
            except Exception:
                raise
            finally:
                self._transaction_state.reset(token)
        for callback in state.callbacks:
            try:
                result = callback()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                LOGGER.exception("Falha em callback pós-commit")

    def after_commit(self, callback: Callable[[], Awaitable[object] | object]) -> None:
        state = self._owned_transaction_state()
        if state is None:
            raise RuntimeError("Callback pós-commit registrado fora de uma transação")
        state.callbacks.append(callback)

    async def fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        if not self.connection:
            raise RuntimeError("Banco nao inicializado")
        if self._owned_transaction_state() is not None:
            async with self.connection.execute(sql, params) as cursor:
                return await cursor.fetchone()
        async with self._connection_lock:
            async with self.connection.execute(sql, params) as cursor:
                return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        if not self.connection:
            raise RuntimeError("Banco nao inicializado")
        if self._owned_transaction_state() is not None:
            async with self.connection.execute(sql, params) as cursor:
                return list(await cursor.fetchall())
        async with self._connection_lock:
            async with self.connection.execute(sql, params) as cursor:
                return list(await cursor.fetchall())

    async def fetchall_fresh(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        """Read through a short-lived connection for cross-process live views.

        The combined runtime intentionally runs the Discord bot and FastAPI in
        separate processes. Operational dashboards must not depend on the read
        snapshot held by either process' long-lived connection.
        """
        def read_snapshot() -> list[sqlite3.Row]:
            # Do not reuse aiosqlite's worker/connection state here. The bot
            # and FastAPI run in separate processes and SQLite WAL visibility
            # for live voice presence must come from a completely independent
            # native connection on every request.
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA busy_timeout=5000")
                return list(connection.execute(sql, params).fetchall())
            finally:
                connection.close()

        return await asyncio.to_thread(read_snapshot)

    async def execute(self, sql: str, params: tuple = ()) -> int:
        async with self.transaction() as connection:
            cursor = await connection.execute(sql, params)
            return int(cursor.lastrowid or 0)

    def _owned_transaction_state(self) -> _TransactionState | None:
        """Return a transaction only to the task that opened it.

        asyncio copies ContextVars into child tasks.  Without the explicit
        owner check, a task created during a transaction would bypass the
        connection lock and issue SQL in somebody else's transaction.
        """
        state = self._transaction_state.get()
        return state if state and state.owner_task is asyncio.current_task() else None
