from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from choque.audit import AuditService  # noqa: E402
from choque.channel_names import format_category_name, format_channel_name  # noqa: E402
from choque.config import AppConfig  # noqa: E402
from choque.database import Database  # noqa: E402
from choque.rbac import PermissionService  # noqa: E402
from choque.recruitment import RecruitmentService  # noqa: E402
from choque.recruitment_analysis import RecruitmentAnalysisService  # noqa: E402
from choque.settings import MODULE_DEFAULTS, SettingsService  # noqa: E402
from choque.time_utils import utc_now_ms  # noqa: E402
from choque.training import TrainingService  # noqa: E402

API_BASE = "https://discord.com/api/v10"
DEFAULT_SOURCE_GUILD_ID = 1146622062895579186
DEFAULT_TARGET_GUILD_ID = 1541908574463070311
RECRUITMENT_URL = "https://choquebgr.online/recrutamento/servidor?guild=rec"
REASON = "CHOQUE - BGR • migração controlada de Recrutamento e Cursos para REC CHOQUE"


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    key: str
    category: str
    label: str
    emoji: str
    private: bool = False
    voice: bool = False


CHANNELS = (
    ChannelSpec("recruitment.requirements", "recruitment", "Requisitos", "📋"),
    ChannelSpec("recruitment.panel", "recruitment", "Recrutamento", "📝"),
    ChannelSpec("recruitment.public_status", "recruitment", "Candidaturas Recebidas", "📨"),
    ChannelSpec("recruitment.review", "recruitment", "Mesa de Análise", "🛡️", private=True),
    ChannelSpec("recruitment.approved", "recruitment", "Aprovados", "✅"),
    ChannelSpec("recruitment.rejected", "recruitment", "Reprovados", "❌"),
    ChannelSpec("recruitment.waiting", "recruitment", "Aguardando Recrutamento", "⏳", voice=True),
    ChannelSpec("recruitment.interview", "recruitment", "Entrevista", "🎙️", private=True, voice=True),
    ChannelSpec("courses.catalog", "courses", "Cursos", "📖"),
    ChannelSpec("courses.training", "courses", "Treinamentos", "🎯"),
    ChannelSpec("courses.chat", "courses", "Chat de Formação", "💬"),
    ChannelSpec("courses.graduates", "courses", "Formados", "🎒"),
    ChannelSpec("courses.approved", "courses", "Aprovados em Cursos", "✅"),
    ChannelSpec("courses.rejected", "courses", "Reprovados em Cursos", "❌"),
    ChannelSpec("courses.instructors", "courses", "Instrutores", "🧑‍🏫", private=True),
    ChannelSpec("courses.room.1", "courses", "Sala de Curso 1", "📚", private=True, voice=True),
    ChannelSpec("courses.room.2", "courses", "Sala de Curso 2", "📚", private=True, voice=True),
)

CORE_ROLE_NAMES = (
    "Membro Choque",
    "Candidato",
    "Responsável Recrutamento",
    "Auxiliar Recrutamento",
    "Instrutor de Cursos",
    "Comando REC",
)


class DiscordRest:
    def __init__(self, token: str) -> None:
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bot {token}", "User-Agent": "CHOQUE-BGR/REC-Migration"}
        )

    async def close(self) -> None:
        await self.session.close()

    async def request(
        self, method: str, path: str, *, payload: Any | None = None
    ) -> Any:
        for _ in range(8):
            async with self.session.request(
                method,
                API_BASE + path,
                json=payload,
                headers={"X-Audit-Log-Reason": quote(REASON)},
            ) as response:
                if response.status == 429:
                    data = await response.json()
                    await asyncio.sleep(min(float(data.get("retry_after", 1)), 15.0))
                    continue
                if response.status == 204:
                    return None
                data = await response.json()
                if response.status >= 400:
                    detail = data.get("message") if isinstance(data, dict) else str(data)
                    raise RuntimeError(f"Discord API {response.status}: {detail}")
                return data
        raise RuntimeError("Discord permaneceu limitado após tentativas seguras.")


def _role_key(name: str) -> str:
    return " ".join(name.casefold().split())


def _permission_overwrites(
    guild_id: int,
    *,
    staff_role_ids: list[int],
    viewer_role_ids: list[int] | None = None,
    private: bool,
    writable: bool,
) -> list[dict[str, str | int]]:
    view = 1 << 10
    send = 1 << 11
    history = 1 << 16
    manage_messages = 1 << 13
    connect = 1 << 20
    speak = 1 << 21
    allowed = view | history | connect | speak | (send if writable else 0)
    if private:
        result: list[dict[str, str | int]] = [
            {"id": str(guild_id), "type": 0, "allow": "0", "deny": str(view)}
        ]
    else:
        result = [
            {
                "id": str(guild_id),
                "type": 0,
                "allow": str(view | history),
                "deny": str(0 if writable else send),
            }
        ]
    for role_id in staff_role_ids:
        result.append(
            {
                "id": str(role_id),
                "type": 0,
                "allow": str(allowed | manage_messages),
                "deny": "0",
            }
        )
    for role_id in viewer_role_ids or []:
        result.append(
            {
                "id": str(role_id),
                "type": 0,
                "allow": str(view | history | connect | speak),
                "deny": "0",
            }
        )
    return result


async def _ensure_role(
    api: DiscordRest,
    guild_id: int,
    roles: list[dict[str, Any]],
    name: str,
    *,
    color: int = 0,
) -> dict[str, Any]:
    matches = [role for role in roles if _role_key(str(role["name"])) == _role_key(name)]
    if len(matches) > 1:
        raise RuntimeError(f"Cargo duplicado no REC CHOQUE: {name}")
    if matches:
        return matches[0]
    role = await api.request(
        "POST",
        f"/guilds/{guild_id}/roles",
        payload={
            "name": name,
            "permissions": "0",
            "color": color,
            "hoist": name in {"Comando REC", "Responsável Recrutamento", "Instrutor de Cursos"},
            "mentionable": False,
        },
    )
    roles.append(role)
    return role


async def _ensure_category(
    api: DiscordRest,
    guild_id: int,
    channels: list[dict[str, Any]],
    name: str,
) -> dict[str, Any]:
    matches = [
        channel
        for channel in channels
        if int(channel.get("type", -1)) == 4 and str(channel.get("name")) == name
    ]
    if len(matches) > 1:
        raise RuntimeError(f"Categoria duplicada no REC CHOQUE: {name}")
    if matches:
        return matches[0]
    category = await api.request(
        "POST", f"/guilds/{guild_id}/channels", payload={"name": name, "type": 4}
    )
    channels.append(category)
    return category


async def _ensure_channel(
    api: DiscordRest,
    guild_id: int,
    channels: list[dict[str, Any]],
    spec: ChannelSpec,
    category_id: int,
    staff_role_ids: list[int],
    viewer_role_ids: list[int] | None = None,
) -> dict[str, Any]:
    name = format_channel_name(spec.label, spec.emoji)
    channel_type = 2 if spec.voice else 0
    matches = [
        channel
        for channel in channels
        if int(channel.get("type", -1)) == channel_type
        and int(channel.get("parent_id") or 0) == category_id
        and str(channel.get("name")) == name
    ]
    if len(matches) > 1:
        raise RuntimeError(f"Canal duplicado no REC CHOQUE: {name}")
    overwrites = _permission_overwrites(
        guild_id,
        staff_role_ids=staff_role_ids,
        viewer_role_ids=viewer_role_ids,
        private=spec.private,
        writable=spec.key in {"courses.chat", "courses.instructors"} or spec.voice,
    )
    if matches:
        channel = matches[0]
        return await api.request(
            "PATCH",
            f"/channels/{channel['id']}",
            payload={"name": name, "parent_id": str(category_id), "permission_overwrites": overwrites},
        )
    payload: dict[str, Any] = {
        "name": name,
        "type": channel_type,
        "parent_id": str(category_id),
        "permission_overwrites": overwrites,
    }
    if not spec.voice:
        payload["topic"] = f"CHOQUE-BGR rec-migration:{spec.key}"
    channel = await api.request("POST", f"/guilds/{guild_id}/channels", payload=payload)
    channels.append(channel)
    return channel


async def _upsert_panel(
    api: DiscordRest,
    settings: SettingsService,
    guild_id: int,
    panel_type: str,
    channel_id: int,
    payload: dict[str, Any],
) -> int:
    panel = await settings.get_panel(guild_id, panel_type)
    message = None
    if panel and int(panel["channel_id"]) == channel_id:
        try:
            message = await api.request(
                "PATCH",
                f"/channels/{channel_id}/messages/{int(panel['message_id'])}",
                payload=payload,
            )
        except RuntimeError as exc:
            if "Discord API 404" not in str(exc):
                raise
    if message is None:
        message = await api.request(
            "POST", f"/channels/{channel_id}/messages", payload=payload
        )
    message_id = int(message["id"])
    await settings.upsert_panel(guild_id, panel_type, channel_id, message_id)
    try:
        await api.request("PUT", f"/channels/{channel_id}/pins/{message_id}")
    except RuntimeError as exc:
        if "Discord API 404" not in str(exc):
            raise
    return message_id


def _embed(title: str, description: str, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "title": title,
        "description": description,
        "color": 0xB11226,
        "footer": {"text": "CHOQUE - BGR • Sistema de Gestão"},
    }
    if fields:
        value["fields"] = fields
    return value


def _button(label: str, emoji: str, *, custom_id: str | None = None, url: str | None = None, style: int = 2) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": 2,
        "style": 5 if url else style,
        "label": label,
        "emoji": {"name": emoji},
    }
    if url:
        result["url"] = url
    else:
        result["custom_id"] = custom_id
    return result


async def _copy_data(
    database: Database,
    settings: SettingsService,
    permissions: PermissionService,
    recruitment: RecruitmentService,
    recruitment_analysis: RecruitmentAnalysisService,
    training: TrainingService,
    *,
    source_guild_id: int,
    target_guild_id: int,
    actor_id: int,
    role_map: dict[int, int],
    role_name_map: dict[int, str],
    channel_map: dict[str, int],
) -> dict[str, int]:
    await permissions.ensure_defaults(target_guild_id)
    target_defaults = await recruitment.ensure_defaults(target_guild_id, actor_id)
    await recruitment_analysis.ensure_defaults(target_guild_id, actor_id)

    source_ranks = await database.fetchall(
        "SELECT * FROM ranks WHERE guild_id=? ORDER BY level", (source_guild_id,)
    )
    rank_map: dict[int, int] = {}
    now = utc_now_ms()
    async with database.transaction() as connection:
        for source_rank in source_ranks:
            target_role_id = role_map.get(int(source_rank["discord_role_id"] or 0))
            await connection.execute(
                """
                INSERT INTO ranks(guild_id,name,prefix,level,discord_role_id,rbac_profile,active,created_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(guild_id,level) DO UPDATE SET
                  name=excluded.name,prefix=excluded.prefix,discord_role_id=excluded.discord_role_id,
                  rbac_profile=excluded.rbac_profile,active=excluded.active
                """,
                (
                    target_guild_id,
                    source_rank["name"],
                    source_rank["prefix"],
                    source_rank["level"],
                    target_role_id,
                    source_rank["rbac_profile"],
                    source_rank["active"],
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT id FROM ranks WHERE guild_id=? AND level=?",
                (target_guild_id, source_rank["level"]),
            )
            target_rank_id = int((await cursor.fetchone())["id"])
            rank_map[int(source_rank["id"])] = target_rank_id
            if target_role_id:
                profile = str(source_rank["rbac_profile"])
                legacy_profile = profile if profile in {"MEMBRO", "GRADUADO", "INSTRUTOR", "COMANDO", "ADMINISTRADOR"} else "MEMBRO"
                await connection.execute(
                    """
                    INSERT INTO rbac_bindings(guild_id,role_id,profile,created_at,created_by)
                    VALUES(?,?,?,?,?) ON CONFLICT(guild_id,role_id) DO UPDATE SET profile=excluded.profile
                    """,
                    (target_guild_id, target_role_id, legacy_profile, now, actor_id),
                )
                await connection.execute(
                    """
                    INSERT INTO discord_role_mappings(
                      guild_id,discord_role_id,mapping_type,internal_code,display_name,
                      priority,rank_id,enabled,created_at,updated_at,created_by
                    ) VALUES(?,?,'RANK',?,?,?,?,1,?,?,?)
                    ON CONFLICT(guild_id,discord_role_id,mapping_type) DO UPDATE SET
                      internal_code=excluded.internal_code,display_name=excluded.display_name,
                      priority=excluded.priority,rank_id=excluded.rank_id,enabled=1,
                      updated_at=excluded.updated_at
                    """,
                    (
                        target_guild_id,
                        target_role_id,
                        f"rank_{int(source_rank['level'])}",
                        source_rank["name"],
                        int(source_rank["level"]),
                        target_rank_id,
                        now,
                        now,
                        actor_id,
                    ),
                )

    source_members = await database.fetchall(
        "SELECT * FROM members WHERE guild_id=? AND status!='DISMISSED'", (source_guild_id,)
    )
    member_map: dict[int, int] = {}
    async with database.transaction() as connection:
        for source_member in source_members:
            target_rank_id = rank_map.get(int(source_member["rank_id"] or 0))
            await connection.execute(
                """
                INSERT INTO members(
                  guild_id,discord_id,discord_nick,mta_nick,character_id,rank_id,unit,status,
                  joined_at,notes,last_activity_at,created_at,updated_at,rank_sync_status,
                  authorization_version,identity_sync_status,discord_present
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'MISSING_ROLE',1,'PENDING',0)
                ON CONFLICT(guild_id,discord_id) DO UPDATE SET
                  discord_nick=excluded.discord_nick,mta_nick=excluded.mta_nick,
                  character_id=excluded.character_id,rank_id=excluded.rank_id,unit=excluded.unit,
                  status=excluded.status,joined_at=excluded.joined_at,updated_at=excluded.updated_at,
                  rank_sync_status='MISSING_ROLE',identity_sync_status='PENDING'
                """,
                (
                    target_guild_id,
                    source_member["discord_id"],
                    source_member["discord_nick"],
                    source_member["mta_nick"],
                    source_member["character_id"],
                    target_rank_id,
                    source_member["unit"],
                    source_member["status"],
                    source_member["joined_at"],
                    "Espelho de identidade do servidor principal para Recrutamento e Cursos.",
                    source_member["last_activity_at"],
                    now,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT id FROM members WHERE guild_id=? AND discord_id=?",
                (target_guild_id, source_member["discord_id"]),
            )
            member_map[int(source_member["id"])] = int((await cursor.fetchone())["id"])

    source_courses = await database.fetchall(
        "SELECT * FROM course_catalog WHERE guild_id=? AND active=1 ORDER BY id",
        (source_guild_id,),
    )
    course_count = 0
    for source_course in source_courses:
        requirements = await database.fetchall(
            "SELECT * FROM course_requirements WHERE guild_id=? AND course_id=? AND active=1 ORDER BY sort_order,id",
            (source_guild_id, source_course["id"]),
        )
        target_course_role = role_map[int(source_course["course_role_id"])]
        imported = await training.import_catalog_course(
            target_guild_id,
            actor_id,
            internal_code=str(source_course["internal_code"]),
            name=str(source_course["name"]),
            description=str(source_course["description"]),
            course_role_id=target_course_role,
            course_role_name=role_name_map[int(source_course["course_role_id"])],
            passing_score=int(source_course["passing_score"]),
            cooldown_days=int(source_course["cooldown_days"]),
            enrollment_status=str(source_course["enrollment_status"]),
            notes=source_course["notes"],
            source_channel_id=channel_map["courses.catalog"],
            source_message_id=int(source_course["id"]),
            source_content_sha256=str(source_course["source_content_sha256"]),
            requirements=[
                (
                    role_map[int(row["required_role_id"])],
                    role_name_map[int(row["required_role_id"])],
                )
                for row in requirements
            ],
        )
        await database.execute(
            """
            UPDATE course_catalog SET minimum_rank_level=?,minimum_valid_hours_ms=?,
              minimum_tenure_days=?,require_no_active_suspension=?,prerequisite_course_name=?
            WHERE guild_id=? AND id=?
            """,
            (
                source_course["minimum_rank_level"],
                source_course["minimum_valid_hours_ms"],
                source_course["minimum_tenure_days"],
                source_course["require_no_active_suspension"],
                source_course["prerequisite_course_name"],
                target_guild_id,
                imported["course_id"],
            ),
        )
        course_count += 1

    qualifications = await database.fetchall(
        """
        SELECT q.* FROM member_qualifications q
        JOIN members m ON m.id=q.member_id
        WHERE q.guild_id=? AND q.result='APPROVED'
        ORDER BY q.recorded_at,q.id
        """,
        (source_guild_id,),
    )
    for qualification in qualifications:
        target_member_id = member_map.get(int(qualification["member_id"]))
        if not target_member_id:
            continue
        exists = await database.fetchone(
            """
            SELECT 1 FROM member_qualifications
            WHERE guild_id=? AND member_id=? AND lower(course_name)=lower(?) AND result='APPROVED'
            """,
            (target_guild_id, target_member_id, qualification["course_name"]),
        )
        if not exists:
            await database.execute(
                """
                INSERT INTO member_qualifications(
                  guild_id,member_id,discord_id,training_id,course_name,result,
                  responsible_id,recorded_at,notes
                ) VALUES(?,?,?,NULL,?,'APPROVED',?,?,?)
                """,
                (
                    target_guild_id,
                    target_member_id,
                    qualification["discord_id"],
                    qualification["course_name"],
                    qualification["responsible_id"],
                    qualification["recorded_at"],
                    "Histórico migrado do servidor principal.",
                ),
            )

    source_campaign = await database.fetchone(
        """
        SELECT * FROM recruitment_campaigns WHERE guild_id=?
        ORDER BY CASE status WHEN 'OPEN' THEN 0 WHEN 'SCHEDULED' THEN 1 ELSE 2 END,id DESC LIMIT 1
        """,
        (source_guild_id,),
    )
    if source_campaign:
        target_campaign_id = int(target_defaults["campaign_id"])
        source_initial = await database.fetchone(
            "SELECT level FROM ranks WHERE id=?", (source_campaign["initial_rank_id"],)
        ) if source_campaign["initial_rank_id"] else None
        target_initial = await database.fetchone(
            "SELECT id FROM ranks WHERE guild_id=? AND level=?",
            (target_guild_id, int(source_initial["level"])),
        ) if source_initial else None
        await database.execute(
            """
            UPDATE recruitment_campaigns SET name=?,status=?,opens_at=?,closes_at=?,
              cooldown_days=?,minimum_age=?,maximum_applications=?,initial_rank_id=?,
              candidate_role_id=?,interview_channel_id=?,updated_at=?
            WHERE guild_id=? AND id=?
            """,
            (
                source_campaign["name"],
                source_campaign["status"],
                source_campaign["opens_at"],
                source_campaign["closes_at"],
                source_campaign["cooldown_days"],
                source_campaign["minimum_age"],
                source_campaign["maximum_applications"],
                int(target_initial["id"]) if target_initial else None,
                role_map.get(int(source_campaign["candidate_role_id"] or 0)),
                channel_map["recruitment.interview"],
                now,
                target_guild_id,
                target_campaign_id,
            ),
        )

    flags = {key: key in {"RECRUITMENT", "TRAINING"} for key in MODULE_DEFAULTS}
    await settings.set(target_guild_id, "module_flags", flags, actor_id)
    await settings.set(target_guild_id, "identity_source_guild_id", source_guild_id, actor_id)
    await settings.set(
        target_guild_id,
        "identity_source_role_map",
        {str(source): target for source, target in role_map.items()},
        actor_id,
    )
    await settings.set(target_guild_id, "registration_gate_enabled", False, actor_id)
    await settings.set(target_guild_id, "recruitment_public_url", RECRUITMENT_URL, actor_id)
    for key, value in {
        "recruitment_requirements_channel_id": channel_map["recruitment.requirements"],
        "recruitment_panel_channel_id": channel_map["recruitment.panel"],
        "recruitment_public_status_channel_id": channel_map["recruitment.public_status"],
        "recruitment_review_channel_id": channel_map["recruitment.review"],
        "recruitment_notification_channel_id": channel_map["recruitment.review"],
        "recruitment_queue_channel_id": channel_map["recruitment.review"],
        "recruitment_approved_channel_id": channel_map["recruitment.approved"],
        "recruitment_rejected_channel_id": channel_map["recruitment.rejected"],
        "training_panel_channel_id": channel_map["courses.training"],
        "course_catalog_channel_id": channel_map["courses.catalog"],
    }.items():
        await settings.set(target_guild_id, key, value, actor_id)
    return {"members": len(source_members), "courses": course_count}


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.load()
    if not config.token:
        raise RuntimeError("DISCORD_TOKEN não configurado.")
    source_guild_id = int(args.source_guild)
    target_guild_id = int(args.target_guild)
    api = DiscordRest(config.token)
    database = Database(config.database_path, config.legacy_database_path)
    await database.open()
    try:
        bot_user, source_guild, target_guild, source_roles, target_roles, target_channels = await asyncio.gather(
            api.request("GET", "/users/@me"),
            api.request("GET", f"/guilds/{source_guild_id}"),
            api.request("GET", f"/guilds/{target_guild_id}"),
            api.request("GET", f"/guilds/{source_guild_id}/roles"),
            api.request("GET", f"/guilds/{target_guild_id}/roles"),
            api.request("GET", f"/guilds/{target_guild_id}/channels"),
        )
        if str(target_guild["name"]).casefold() != "rec choque":
            raise RuntimeError("O servidor de destino não corresponde ao REC CHOQUE.")
        source_by_id = {int(role["id"]): role for role in source_roles}
        source_course_roles = await database.fetchall(
            "SELECT course_role_id FROM course_catalog WHERE guild_id=? AND active=1",
            (source_guild_id,),
        )
        source_requirement_roles = await database.fetchall(
            "SELECT DISTINCT required_role_id FROM course_requirements WHERE guild_id=? AND active=1",
            (source_guild_id,),
        )
        source_rank_roles = await database.fetchall(
            "SELECT discord_role_id FROM ranks WHERE guild_id=? AND active=1 AND discord_role_id IS NOT NULL",
            (source_guild_id,),
        )
        named_sources = {
            "Membro Choque": "ᴍᴇᴍʙʀᴏ ᴄʜᴏǫᴜᴇ",
            "Candidato": "Candidato",
            "Responsável Recrutamento": "ʀᴇsᴘᴏɴsᴀᴠᴇʟ ʀᴇᴄʀᴜᴛᴀᴍᴇɴᴛᴏ",
            "Auxiliar Recrutamento": "ᴀᴜxɪʟɪᴀʀ ʀᴇᴄʀᴜᴛᴀᴍᴇɴᴛᴏ",
            "Instrutor de Cursos": "ɪɴsᴛʀᴜᴛᴏʀ ᴅᴇ ᴄᴜʀsᴏs",
        }
        source_named_ids = {
            target_name: int(next(role["id"] for role in source_roles if str(role["name"]) == source_name))
            for target_name, source_name in named_sources.items()
        }
        source_ids = {
            int(row["course_role_id"]) for row in source_course_roles
        } | {
            int(row["required_role_id"]) for row in source_requirement_roles
        } | {
            int(row["discord_role_id"]) for row in source_rank_roles
        } | set(source_named_ids.values())

        role_map: dict[int, int] = {}
        role_name_map: dict[int, str] = {}
        for source_id in sorted(source_ids):
            source_role = source_by_id.get(source_id)
            if not source_role:
                raise RuntimeError(f"Cargo-fonte ausente: {source_id}")
            desired_name = next(
                (name for name, mapped in source_named_ids.items() if mapped == source_id),
                str(source_role["name"]),
            )
            target_role = await _ensure_role(
                api,
                target_guild_id,
                target_roles,
                desired_name,
                color=int(source_role.get("color") or 0),
            )
            role_map[source_id] = int(target_role["id"])
            role_name_map[source_id] = desired_name
        command_role = await _ensure_role(
            api, target_guild_id, target_roles, "Comando REC", color=0xB11226
        )
        staff_role_ids = [
            int(command_role["id"]),
            role_map[source_named_ids["Responsável Recrutamento"]],
            role_map[source_named_ids["Auxiliar Recrutamento"]],
            role_map[source_named_ids["Instrutor de Cursos"]],
        ]
        await api.request(
            "PUT",
            f"/guilds/{target_guild_id}/members/{int(target_guild['owner_id'])}/roles/{int(command_role['id'])}",
        )
        categories = {
            "recruitment": await _ensure_category(
                api, target_guild_id, target_channels, format_category_name(1, "Recrutamento")
            ),
            "courses": await _ensure_category(
                api, target_guild_id, target_channels, format_category_name(2, "Cursos")
            ),
        }
        channel_map: dict[str, int] = {}
        for spec in CHANNELS:
            viewer_role_ids = (
                [role_map[source_named_ids["Candidato"]]]
                if spec.key == "recruitment.interview"
                else []
            )
            channel = await _ensure_channel(
                api,
                target_guild_id,
                target_channels,
                spec,
                int(categories[spec.category]["id"]),
                staff_role_ids,
                viewer_role_ids,
            )
            channel_map[spec.key] = int(channel["id"])

        settings = SettingsService(database)
        audit = AuditService(database, settings, config.branding)
        permissions = PermissionService(settings)
        recruitment = RecruitmentService(database, audit, token_secret="rec-migration")
        recruitment_analysis = RecruitmentAnalysisService(database, settings, audit)
        training = TrainingService(database, audit, settings=settings)
        copied = await _copy_data(
            database,
            settings,
            permissions,
            recruitment,
            recruitment_analysis,
            training,
            source_guild_id=source_guild_id,
            target_guild_id=target_guild_id,
            actor_id=int(target_guild["owner_id"]),
            role_map=role_map,
            role_name_map=role_name_map,
            channel_map=channel_map,
        )
        await settings.set(target_guild_id, "discord_layout_registry_v2", {
            "categories": {key: int(value["id"]) for key, value in categories.items()},
            "channels": channel_map,
            "migration": {"source_guild_id": source_guild_id, "mode": "PARALLEL_VALIDATION"},
        }, int(target_guild["owner_id"]))
        bindings = {
            role_map[source_named_ids["Membro Choque"]]: "MEMBRO",
            role_map[source_named_ids["Candidato"]]: "MEMBRO",
            role_map[source_named_ids["Responsável Recrutamento"]]: "INSTRUTOR",
            role_map[source_named_ids["Auxiliar Recrutamento"]]: "INSTRUTOR",
            role_map[source_named_ids["Instrutor de Cursos"]]: "INSTRUTOR",
            int(command_role["id"]): "ADMINISTRADOR",
        }
        for role_id, profile in bindings.items():
            await database.execute(
                """
                INSERT INTO rbac_bindings(guild_id,role_id,profile,created_at,created_by)
                VALUES(?,?,?,?,?) ON CONFLICT(guild_id,role_id) DO UPDATE SET profile=excluded.profile
                """,
                (target_guild_id, role_id, profile, utc_now_ms(), int(target_guild["owner_id"])),
            )

        requirements_id = await _upsert_panel(
            api,
            settings,
            target_guild_id,
            "RECRUITMENT_REQUIREMENTS",
            channel_map["recruitment.requirements"],
            {
                "embeds": [_embed(
                    "🛡️ ALISTAMENTO • CHOQUE - BGR",
                    "Leia os requisitos antes de iniciar. A candidatura é enviada pelo portal oficial e a decisão final permanece humana.",
                    [
                        {"name": "📋 Requisitos", "value": "• 15 anos ou mais\n• Microfone funcional\n• Maturidade, respeito e compromisso\n• Noções de Roleplay policial", "inline": False},
                        {"name": "🎯 Etapas", "value": "Identificação → avaliação → análise humana → resultado.", "inline": False},
                    ],
                )],
                "components": [{"type": 1, "components": [
                    _button("Iniciar candidatura", "📝", url=RECRUITMENT_URL),
                    _button("Acompanhar candidatura", "📨", url="https://choquebgr.online/minha-candidatura"),
                ]}],
                "allowed_mentions": {"parse": []},
            },
        )
        recruitment_id = await _upsert_panel(
            api,
            settings,
            target_guild_id,
            "RECRUITMENT",
            channel_map["recruitment.panel"],
            {
                "embeds": [_embed(
                    "🪖 QUERO ENTRAR PARA A CHOQUE - BGR",
                    f"Confira <#{channel_map['recruitment.requirements']}> e use os botões abaixo para iniciar ou acompanhar seu alistamento.",
                )],
                "components": [{"type": 1, "components": [
                    _button("Candidatar-me agora", "🪖", url=RECRUITMENT_URL),
                    _button("Acompanhar candidatura", "📋", url="https://choquebgr.online/minha-candidatura"),
                ]}],
                "allowed_mentions": {"parse": []},
            },
        )
        await _upsert_panel(
            api,
            settings,
            target_guild_id,
            "RECRUITMENT_ADMIN",
            channel_map["recruitment.review"],
            {
                "embeds": [_embed("📥 Mesa de Análise", "Fila privada de candidaturas. As decisões são humanas, auditadas e idempotentes.")],
                "components": [{"type": 1, "components": [
                    _button("Candidaturas", "📝", custom_id="choque:recruitment:admin:candidacies:v1", style=1),
                    _button("Transferências", "🔄", custom_id="choque:recruitment:admin:transfers:v1"),
                    _button("Atualizar", "🔄", custom_id="choque:recruitment:admin:refresh:v1", style=3),
                ]}],
                "allowed_mentions": {"parse": []},
            },
        )
        await _upsert_panel(
            api,
            settings,
            target_guild_id,
            "TRAINING",
            channel_map["courses.training"],
            {
                "embeds": [_embed("🎓 Treinamentos • CHOQUE - BGR", "Consulte treinamentos abertos, suas inscrições e seu histórico de cursos.")],
                "components": [{"type": 1, "components": [
                    _button("Treinamentos abertos", "🎓", custom_id="choque:training:open:v1", style=1),
                    _button("Meus treinamentos", "📋", custom_id="choque:training:mine:v1"),
                    _button("Meus cursos", "🏅", custom_id="choque:training:courses:v1", style=3),
                    _button("Matriz", "🧭", custom_id="choque:training:matrix:v1"),
                ]}],
                "allowed_mentions": {"parse": []},
            },
        )
        target_courses = await training.catalog(target_guild_id)
        course_fields = []
        course_buttons = []
        for course in target_courses:
            reqs = await training.course_requirements(target_guild_id, int(course["id"]))
            course_fields.append({
                "name": f"{'🟢' if course['enrollment_status']=='OPEN' else '🔒'} {course['name']}",
                "value": "**Requisitos:** " + (" + ".join(f"<@&{row['required_role_id']}>" for row in reqs) or "Cadastro ativo"),
                "inline": False,
            })
            course_buttons.append(_button(
                str(course["name"])[:80],
                "📝",
                custom_id=f"choque:course:apply:{course['internal_code']}:v1",
                style=1,
            ))
        components = [
            {"type": 1, "components": course_buttons[index:index + 5]}
            for index in range(0, len(course_buttons), 5)
        ]
        catalog_id = await _upsert_panel(
            api,
            settings,
            target_guild_id,
            "COURSE_CATALOG",
            channel_map["courses.catalog"],
            {
                "embeds": [_embed("🎖️ Catálogo de Cursos • CHOQUE - BGR", "Escolha um curso. A elegibilidade é validada novamente no clique.", course_fields)],
                "components": components,
                "allowed_mentions": {"parse": []},
            },
        )
        await audit.record(
            target_guild_id,
            "REC_SERVER_RECRUITMENT_COURSES_MIGRATED",
            actor_id=int(target_guild["owner_id"]),
            after={
                "source_guild_id": source_guild_id,
                "channels": len(channel_map),
                "roles": len(role_map) + 1,
                "members": copied["members"],
                "courses": copied["courses"],
                "panels": [requirements_id, recruitment_id, catalog_id],
                "mode": "PARALLEL_VALIDATION",
            },
            reason=REASON,
            deliver_immediately=False,
        )
        print(json.dumps({
            "status": "REC_MIGRATION_APPLIED",
            "source": source_guild["name"],
            "target": target_guild["name"],
            "roles": len(role_map) + 1,
            "channels": len(channel_map),
            **copied,
            "bot": bot_user["username"],
        }, ensure_ascii=False))
        return 0
    finally:
        await database.close()
        await api.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migra Recrutamento e Cursos para REC CHOQUE.")
    parser.add_argument("--source-guild", type=int, default=DEFAULT_SOURCE_GUILD_ID)
    parser.add_argument("--target-guild", type=int, default=DEFAULT_TARGET_GUILD_ID)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print("DRY_RUN_ONLY: use --apply após backup íntegro e gates verdes.")
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
