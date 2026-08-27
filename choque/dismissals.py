from __future__ import annotations

import json
from typing import Literal

import aiosqlite

from .models import RbacProfile

HIGH_COMMAND_DISMISSAL_REASON = (
    "Por determinação do Alto Comando, em conformidade com as diretrizes internas "
    "e visando à manutenção da ordem, disciplina e adequada organização do efetivo."
)
STANDARD_DISMISSAL_REASON = (
    "Desligamento administrativo realizado em observância às normas internas, aos "
    "procedimentos disciplinares e à organização do efetivo da Corporação."
)
DISMISSAL_CHANNEL_SETTING_KEY = "dismissal_log_channel_id"

DismissalSource = Literal[
    "PUNISHMENT",
    "ADMINISTRATIVE_REQUEST",
    "INACTIVITY_ALERT",
    "DIRECT_STATUS_CHANGE",
]


def dismissal_public_reason(actor_has_high_command: bool) -> str:
    return HIGH_COMMAND_DISMISSAL_REASON if actor_has_high_command else STANDARD_DISMISSAL_REASON


async def actor_has_high_command(
    connection: aiosqlite.Connection,
    guild_id: int,
    actor_id: int,
) -> bool:
    """Resolve Alto Comando pelas projeções canônicas dentro da transação da ação."""

    profile_code = RbacProfile.HIGH_COMMAND.value
    cursor = await connection.execute(
        """
        SELECT EXISTS(
            SELECT 1
            FROM members m
            LEFT JOIN access_profiles direct_profile
              ON direct_profile.id=m.access_profile_id
             AND direct_profile.guild_id=m.guild_id
             AND direct_profile.enabled=1
            LEFT JOIN ranks r ON r.id=m.rank_id AND r.guild_id=m.guild_id
            WHERE m.guild_id=? AND m.discord_id=? AND (
                direct_profile.code=?
                OR r.rbac_profile=?
                OR EXISTS(
                    SELECT 1
                    FROM member_access_profiles projection
                    JOIN discord_role_mappings mapping
                      ON mapping.id=projection.source_mapping_id
                     AND mapping.guild_id=m.guild_id
                     AND mapping.mapping_type='ACCESS'
                     AND mapping.enabled=1
                     AND mapping.discord_role_id=projection.source_role_id
                     AND mapping.access_profile_id=projection.access_profile_id
                    JOIN access_profiles projected_profile
                      ON projected_profile.id=projection.access_profile_id
                     AND projected_profile.guild_id=m.guild_id
                     AND projected_profile.enabled=1
                    WHERE projection.member_id=m.id
                      AND projected_profile.code=?
                )
                OR EXISTS(
                    SELECT 1
                    FROM member_positions member_position
                    JOIN functional_positions position
                      ON position.id=member_position.position_id
                     AND position.guild_id=m.guild_id
                     AND position.enabled=1
                    JOIN access_profiles position_profile
                      ON position_profile.id=position.access_profile_id
                     AND position_profile.guild_id=m.guild_id
                     AND position_profile.enabled=1
                    WHERE member_position.member_id=m.id
                      AND position_profile.code=?
                )
            )
        ) AS has_high_command
        """,
        (guild_id, actor_id, profile_code, profile_code, profile_code, profile_code),
    )
    row = await cursor.fetchone()
    return bool(row and row["has_high_command"])


async def enqueue_dismissal_notification(
    connection: aiosqlite.Connection,
    *,
    guild_id: int,
    subject_id: int,
    discord_id: int,
    actor_id: int,
    occurred_at: int,
    source: DismissalSource,
    correlation_id: str,
) -> None:
    """Persiste registro público sem aceitar motivo fornecido pelo chamador."""

    is_high_command = await actor_has_high_command(connection, guild_id, actor_id)
    cursor = await connection.execute(
        "SELECT character_id FROM members WHERE guild_id=? AND discord_id=?",
        (guild_id, discord_id),
    )
    member = await cursor.fetchone()
    character_id = str(member["character_id"]).strip() if member and member["character_id"] else ""
    payload = {
        "discord_id": discord_id,
        "character_id": character_id or "Não informado",
        "actor_id": actor_id,
        "occurred_at": occurred_at,
        "actor_has_high_command": is_high_command,
        "public_reason": dismissal_public_reason(is_high_command),
        "source": source,
    }
    await connection.execute(
        """
        INSERT OR IGNORE INTO career_notifications(
            guild_id, notification_type, subject_id, target_discord_id,
            channel_setting_key, payload_json, status, attempts,
            available_at, correlation_id, created_at, updated_at
        ) VALUES (?, 'DISMISSAL', ?, NULL, ?, ?, 'PENDING', 0, ?, ?, ?, ?)
        """,
        (
            guild_id,
            subject_id,
            DISMISSAL_CHANNEL_SETTING_KEY,
            json.dumps(payload, ensure_ascii=False),
            occurred_at,
            correlation_id,
            occurred_at,
            occurred_at,
        ),
    )


async def missing_historical_dismissals(
    connection: aiosqlite.Connection,
    guild_id: int,
) -> list[aiosqlite.Row]:
    cursor = await connection.execute(
        """
        SELECT
            member.guild_id,
            member.discord_id,
            member.character_id,
            punishment.id AS punishment_id,
            punishment.created_by AS actor_id,
            punishment.created_at AS occurred_at
        FROM members AS member
        JOIN punishments AS punishment
          ON punishment.id=(
              SELECT latest.id
              FROM punishments AS latest
              WHERE latest.guild_id=member.guild_id
                AND latest.member_id=member.id
                AND latest.punishment_type='DISMISSAL'
              ORDER BY latest.created_at DESC, latest.id DESC
              LIMIT 1
          )
        WHERE member.guild_id=? AND member.status='DISMISSED'
        ORDER BY member.id
        """,
        (guild_id,),
    )
    dismissed = await cursor.fetchall()
    cursor = await connection.execute(
        """
        SELECT payload_json FROM career_notifications
        WHERE guild_id=? AND notification_type='DISMISSAL'
        """,
        (guild_id,),
    )
    notifications = await cursor.fetchall()
    already_recorded: set[int] = set()
    for notification in notifications:
        try:
            payload = json.loads(str(notification["payload_json"]))
            already_recorded.add(int(payload["discord_id"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return [row for row in dismissed if int(row["discord_id"]) not in already_recorded]


async def backfill_historical_dismissals(
    connection: aiosqlite.Connection,
    guild_id: int,
) -> int:
    missing = await missing_historical_dismissals(connection, guild_id)
    for row in missing:
        punishment_id = int(row["punishment_id"])
        await enqueue_dismissal_notification(
            connection,
            guild_id=guild_id,
            subject_id=punishment_id,
            discord_id=int(row["discord_id"]),
            actor_id=int(row["actor_id"]),
            occurred_at=int(row["occurred_at"]),
            source="PUNISHMENT",
            correlation_id=f"dismissal-retroactive-punishment-{guild_id}-{punishment_id}",
        )
    return len(missing)
