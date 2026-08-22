from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord

from choque.time_utils import utc_now_ms

_MANAGED_NICKNAME = re.compile(
    r"^\s*\[[^\]\r\n]{1,16}\]\s+(?P<name>.+?)\s+\[[^\]\r\n]{1,24}\]\s*$"
)


def _legacy_nickname_fallback(
    *,
    current_nickname: str | None,
    stored_discord_name: str | None,
    username: str | None,
    global_name: str | None,
) -> str | None:
    """Recover a human nickname when a legacy row captured the managed nickname.

    Older imports may have stored ``[PAT] Nome [ID]`` as the original nickname.
    In that case the safest reversible fallback is the name already present in
    the managed nickname, without the rank prefix and character id.
    """

    match = _MANAGED_NICKNAME.fullmatch(current_nickname or "")
    candidate = match.group("name").strip() if match else (stored_discord_name or "").strip()
    if not candidate:
        return None
    if candidate.casefold() in {
        value.strip().casefold()
        for value in (username, global_name)
        if value and value.strip()
    }:
        return None
    return candidate[:32]


def _restoration_nickname(
    *,
    captured: bool,
    original_nickname: str | None,
    current_nickname: str | None,
    stored_discord_name: str | None,
    username: str | None,
    global_name: str | None,
) -> tuple[str | None, str]:
    if captured and not _MANAGED_NICKNAME.fullmatch(original_nickname or ""):
        return original_nickname, "CAPTURED_ORIGINAL"
    return (
        _legacy_nickname_fallback(
            current_nickname=current_nickname,
            stored_discord_name=stored_discord_name,
            username=username,
            global_name=global_name,
        ),
        "LEGACY_MANAGED_NICKNAME_FALLBACK",
    )


async def sync_member_status_roles(
    bot: ChoqueBot,
    guild: discord.Guild,
    target: discord.Member,
    status: str,
) -> str | None:
    setting_keys = {
        "AWAY": "away_role_id",
        "RESERVE": "reserve_role_id",
        "SUSPENDED": "suspended_role_id",
        "DISMISSED": "dismissed_role_id",
    }
    configured: dict[str, int] = {}
    for state, key in setting_keys.items():
        value = await bot.services.settings.get(guild.id, key)
        if value:
            configured[state] = int(value)
    service_role_id = await bot.services.settings.get(guild.id, "service_role_id")
    member_role_id = await bot.services.settings.get(guild.id, "member_role_id")
    rank_rows = await bot.services.database.fetchall(
        "SELECT discord_role_id FROM ranks WHERE guild_id=? AND discord_role_id IS NOT NULL",
        (guild.id,),
    )
    rank_role_ids = {int(row["discord_role_id"]) for row in rank_rows}
    managed_status_ids = set(configured.values())
    if service_role_id:
        managed_status_ids.add(int(service_role_id))

    remove_ids = set(managed_status_ids)
    add_ids: set[int] = set()
    if status in configured:
        add_ids.add(configured[status])
    if status == "ACTIVE" and member_role_id:
        add_ids.add(int(member_role_id))
    if status == "DISMISSED":
        remove_ids.update(rank_role_ids)
        if member_role_id:
            remove_ids.add(int(member_role_id))

    to_remove = [role for role in target.roles if role.id in remove_ids and role.id not in add_ids]
    to_add = [guild.get_role(role_id) for role_id in add_ids if not target.get_role(role_id)]
    to_add = [role for role in to_add if role]
    warnings: list[str] = []
    try:
        if to_remove:
            await target.remove_roles(*to_remove, reason=f"Sincronização de status: {status}")
        if to_add:
            await target.add_roles(*to_add, reason=f"Sincronização de status: {status}")
    except (discord.Forbidden, discord.HTTPException):
        await bot.services.audit.record(
            guild.id,
            "MEMBER_STATUS_ROLE_SYNC_FAILED",
            target_id=target.id,
            reason=f"Hierarquia ou permissão insuficiente para o status {status}",
        )
        warnings.append("O status foi salvo, mas o Discord bloqueou a sincronização de cargos.")

    if status == "DISMISSED":
        member = await bot.services.database.fetchone(
            """
            SELECT original_discord_nickname, original_nickname_captured, discord_nick
            FROM members WHERE guild_id=? AND discord_id=?
            """,
            (guild.id, target.id),
        )
        if member:
            previous_nickname = target.nick
            restored_nickname, restoration_source = _restoration_nickname(
                captured=bool(member["original_nickname_captured"]),
                original_nickname=member["original_discord_nickname"],
                current_nickname=previous_nickname,
                stored_discord_name=member["discord_nick"],
                username=getattr(target, "name", None),
                global_name=getattr(target, "global_name", None),
            )
            try:
                if target.nick != restored_nickname:
                    await target.edit(
                        nick=restored_nickname,
                        reason="Restauração do apelido anterior ao cadastro",
                    )
                refreshed = await guild.fetch_member(target.id)
                if refreshed.nick != restored_nickname:
                    await refreshed.edit(
                        nick=restored_nickname,
                        reason="Segunda tentativa de restauração após exoneração",
                    )
                    refreshed = await guild.fetch_member(target.id)
                if refreshed.nick != restored_nickname:
                    raise RuntimeError("Discord não persistiu o apelido restaurado")
                if previous_nickname != restored_nickname:
                    async with bot.services.database.transaction() as connection:
                        if restoration_source == "LEGACY_MANAGED_NICKNAME_FALLBACK":
                            await connection.execute(
                                """
                                UPDATE members
                                SET original_discord_nickname=?, original_nickname_captured=1,
                                    updated_at=?
                                WHERE guild_id=? AND discord_id=?
                                """,
                                (restored_nickname, utc_now_ms(), guild.id, target.id),
                            )
                        await bot.services.audit.record(
                            guild.id,
                            "MEMBER_NICKNAME_RESTORED",
                            target_id=target.id,
                            before={"had_managed_nickname": previous_nickname is not None},
                            after={
                                "restored": True,
                                "had_original_guild_nickname": restored_nickname is not None,
                                "source": restoration_source,
                                "verified_by_api": True,
                            },
                            connection=connection,
                        )
            except (discord.Forbidden, discord.HTTPException, RuntimeError):
                await bot.services.audit.record(
                    guild.id,
                    "MEMBER_NICKNAME_RESTORE_FAILED",
                    target_id=target.id,
                    reason="Hierarquia ou permissão insuficiente para restaurar o apelido",
                )
                warnings.append(
                    "O Discord bloqueou a restauração do apelido anterior ao cadastro."
                )
        else:
            await bot.services.audit.record(
                guild.id,
                "MEMBER_NICKNAME_RESTORE_SKIPPED",
                target_id=target.id,
                reason="Apelido anterior ao cadastro não estava disponível",
            )
            warnings.append("O apelido original não estava disponível para restauração automática.")
    return " ".join(warnings) or None


async def sync_member_identity(
    bot: ChoqueBot,
    guild: discord.Guild,
    target: discord.Member,
    actor_id: int | None = None,
) -> str | None:
    result = await bot.services.rank_sync.sync_to_member(
        target,
        source="MEMBER_DATA_CHANGE",
        actor_id=actor_id,
    )
    if not result.registered:
        return "O cadastro atualizado não foi localizado."
    return result.warning


async def sync_rank_to_discord(
    bot: ChoqueBot,
    guild: discord.Guild,
    target: discord.Member,
    result: dict[str, object],
    actor_id: int | None = None,
) -> str | None:
    previous_role_id = result.get("from_role_id")
    sync_result = await bot.services.rank_sync.sync_to_member(
        target,
        source="FORMAL_CAREER_ACTION",
        actor_id=actor_id,
        explicit_remove_role_ids={int(previous_role_id)} if previous_role_id else set(),
    )
    if not sync_result.registered:
        return "A patente foi salva, mas o cadastro não foi localizado para sincronização."
    return sync_result.warning


async def sync_registered_member(
    bot: ChoqueBot,
    guild: discord.Guild,
    target: discord.Member,
    actor_id: int | None = None,
) -> str | None:
    result = await bot.services.rank_sync.sync_to_member(
        target,
        source="REGISTRATION_APPROVED",
        actor_id=actor_id,
        ensure_member_role=True,
    )
    if not result.registered:
        return "Cadastro salvo, mas o perfil não foi localizado para sincronização."
    return result.warning


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
