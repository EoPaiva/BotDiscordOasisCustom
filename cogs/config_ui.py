from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite
import discord

from choque.embeds import branded_embed
from choque.errors import ChoqueError, PermissionDenied, ValidationError
from choque.identity_queue import enqueue_identity_reconciliation
from choque.models import RbacProfile
from choque.settings import MODULE_DEFINITIONS, SettingsService
from choque.time_utils import utc_now_ms

LOGGER = logging.getLogger(__name__)

CHANNEL_SETTINGS = (
    ("audit_channel_id", "Canal de auditoria", "📜"),
    ("registration_approval_channel_id", "Canal de aprovação", "✅"),
    ("registration_history_channel_id", "Histórico de cadastros", "📜"),
    ("registration_panel_channel_id", "Canal do painel de cadastro", "📝"),
    ("point_panel_channel_id", "Canal do painel de ponto", "⏱️"),
    ("service_panel_channel_id", "Canal do efetivo", "👥"),
    ("hierarchy_channel_id", "Canal da hierarquia", "🎖️"),
    ("config_panel_channel_id", "Canal da configuração", "⚙️"),
    ("personnel_admin_channel_id", "Canal administrativo de RH", "🛡️"),
    ("requests_panel_channel_id", "Canal de solicitações", "📥"),
    ("career_panel_channel_id", "Canal de carreira", "📈"),
    ("discipline_panel_channel_id", "Canal de disciplina", "⚖️"),
    ("training_panel_channel_id", "Canal de treinamentos", "🎓"),
    ("course_catalog_channel_id", "Canal do catálogo de cursos", "🎖️"),
    ("activity_panel_channel_id", "Canal de atividade semanal", "📊"),
    ("ranking_panel_channel_id", "Canal do ranking", "🏆"),
    ("recruitment_requirements_channel_id", "Canal de requisitos", "📋"),
    ("recruitment_panel_channel_id", "Canal de recrutamento", "🧑‍💼"),
    ("ticket_panel_channel_id", "Canal de atendimento", "🎫"),
    ("recruitment_queue_channel_id", "Canal da fila de candidatos", "📥"),
    ("recruitment_review_channel_id", "Mesa privada de análise", "🛡️"),
    ("recruitment_public_status_channel_id", "Acompanhamento público de candidaturas", "📨"),
    ("transfer_results_channel_id", "Canal de transferências", "🔄"),
    ("recruitment_approved_channel_id", "Canal de aprovados", "✅"),
    ("recruitment_rejected_channel_id", "Canal de reprovados", "❌"),
)

ITEMS_PER_PAGE = 25

SMALL_CAPS_TRANSLATION = {
    **str.maketrans(
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘꞯʀꜱᴛᴜᴠᴡxʏᴢ",
        "abcdefghijklmnopqrstuvwxyz",
    ),
    ord("ғ"): "f",  # Variante usada atualmente no cargo ᴏғɪᴄɪᴀɪs.
}

MILITARY_RANK_PREFIXES = {
    "recruta": "[REC]",
    "soldado": "[SD]",
    "cabo": "[CB]",
    "3 sargento": "[3SGT]",
    "2 sargento": "[2SGT]",
    "1 sargento": "[1SGT]",
    "sub tenente": "[ST]",
    "cadete": "[CAD]",
    "aspirante": "[ASP]",
    "2 tenente": "[2TEN]",
    "1 tenente": "[1TEN]",
    "capitao": "[CAP]",
    "major": "[MAJ]",
    "tenente coronel": "[TC]",
    "coronel": "[CEL]",
    "sub comandante": "[SCMD]",
    "comandante": "[CMD]",
    "comandante geral": "[CMDG]",
}

# Cargos funcionais que ficam próximos das patentes no Discord, mas não fazem
# parte da progressão hierárquica militar.
IGNORED_RANK_ROLE_NAMES = frozenset(
    {
        "alto comando",
        "xenon",
        # Agrupadores de acesso/apresentação, não patentes individuais.
        "oficiais",
        "pracas",
        "pracas graduados",
    }
)


@dataclass(frozen=True, slots=True)
class ChannelChoice:
    channel_id: int
    name: str
    category_name: str | None
    category_position: int
    channel_position: int


@dataclass(frozen=True, slots=True)
class RoleChoice:
    role_id: int
    name: str
    position: int
    managed: bool


def channel_choices_for_guild(guild: discord.Guild, *, voice: bool = False) -> list[ChannelChoice]:
    channels = [*guild.voice_channels, *guild.stage_channels] if voice else guild.text_channels
    choices = [
        ChannelChoice(
            channel_id=channel.id,
            name=channel.name,
            category_name=channel.category.name if channel.category else None,
            category_position=channel.category.position if channel.category else -1,
            channel_position=channel.position,
        )
        for channel in channels
    ]
    return sorted(
        choices,
        key=lambda choice: (
            choice.category_position,
            choice.channel_position,
            choice.name.casefold(),
            choice.channel_id,
        ),
    )


def role_choices_for_guild(guild: discord.Guild) -> list[RoleChoice]:
    return [
        RoleChoice(role.id, role.name, role.position, role.managed)
        for role in sorted(guild.roles[1:], key=lambda item: (-item.position, item.name.casefold()))
    ]


def paginate_items[T](items: list[T], page: int) -> tuple[list[T], int, int]:
    page_count = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    safe_page = min(max(page, 0), page_count - 1)
    start = safe_page * ITEMS_PER_PAGE
    return items[start : start + ITEMS_PER_PAGE], safe_page, page_count


def search_channel_choices(choices: list[ChannelChoice], query: str) -> list[ChannelChoice]:
    normalized = query.strip().casefold().removeprefix("#")
    if not normalized:
        return []
    if normalized.isdigit():
        exact = [choice for choice in choices if choice.channel_id == int(normalized)]
        if exact:
            return exact
    return [
        choice
        for choice in choices
        if normalized in choice.name.casefold()
        or (choice.category_name and normalized in choice.category_name.casefold())
    ]


def search_role_choices(choices: list[RoleChoice], query: str) -> list[RoleChoice]:
    normalized = query.strip().casefold().removeprefix("@").removeprefix("&")
    if not normalized:
        return []
    if normalized.isdigit():
        exact = [choice for choice in choices if choice.role_id == int(normalized)]
        if exact:
            return exact
    return [choice for choice in choices if normalized in choice.name.casefold()]


def normalize_rank_name(name: str) -> str:
    normalized = name.casefold().translate(SMALL_CAPS_TRANSLATION)
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\b(\d+)o\b", r"\1", normalized)
    return " ".join(normalized.split())


def validate_minimum_patrol_minutes(value: str) -> int:
    normalized = value.strip()
    if not normalized.isdigit() or not 5 <= int(normalized) <= 120:
        raise ValidationError("O mínimo de patrulha deve ficar entre 5 e 120 minutos.")
    return int(normalized)


def detect_military_rank_roles(choices: list[RoleChoice]) -> list[tuple[RoleChoice, str]]:
    detected = []
    for choice in sorted(choices, key=lambda item: item.position):
        if choice.managed:
            continue
        prefix = MILITARY_RANK_PREFIXES.get(normalize_rank_name(choice.name))
        if prefix:
            detected.append((choice, prefix))
    return detected


async def import_military_rank_roles(
    bot: ChoqueBot,
    *,
    guild_id: int,
    choices: list[RoleChoice],
    actor_id: int | None,
) -> tuple[int, int, list[tuple[RoleChoice, str]]]:
    return await reconcile_military_rank_roles(
        bot.services.database,
        bot.services.audit,
        guild_id=guild_id,
        choices=choices,
        actor_id=actor_id,
    )


async def reconcile_military_rank_roles(
    database,
    audit,
    *,
    guild_id: int,
    choices: list[RoleChoice],
    actor_id: int | None,
) -> tuple[int, int, list[tuple[RoleChoice, str]]]:
    """Sincroniza as patentes pela posição real dos cargos no Discord.

    Registros antigos são preservados para manter histórico e chaves
    estrangeiras, mas patentes que não existem mais na lista oficial ficam
    inativas. Os níveis são reconstruídos de baixo para cima de forma atômica.
    """
    detected = detect_military_rank_roles(choices)
    if not detected:
        return 0, 0, []
    created = 0
    updated = 0
    reordered = 0
    deactivated = 0
    settings = SettingsService(database)
    async with database.transaction() as connection:
        cursor = await connection.execute(
            "SELECT * FROM ranks WHERE guild_id=? ORDER BY level, id",
            (guild_id,),
        )
        existing_rows = list(await cursor.fetchall())
        existing_by_role_id = {
            int(row["discord_role_id"]): row
            for row in existing_rows
            if row["discord_role_id"] is not None
        }

        # Libera a restrição UNIQUE(guild_id, level) antes de reconstruir todos
        # os níveis. O deslocamento negativo é temporário e fica na transaction.
        await connection.execute(
            "UPDATE ranks SET level=(-1000000000-id) WHERE guild_id=?",
            (guild_id,),
        )

        detected_role_ids = {choice.role_id for choice, _ in detected}
        next_level = 1
        for choice, prefix in detected:
            existing = existing_by_role_id.get(choice.role_id)
            if existing:
                await connection.execute(
                    """
                    UPDATE ranks SET name=?, prefix=?, level=?, active=1
                    WHERE id=?
                    """,
                    (choice.name, prefix, next_level, int(existing["id"])),
                )
                if int(existing["level"]) != next_level:
                    reordered += 1
                rank_id = int(existing["id"])
                updated += 1
            else:
                cursor = await connection.execute(
                    """
                    INSERT INTO ranks(
                        guild_id, name, prefix, level, rbac_profile, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        choice.name,
                        prefix,
                        next_level,
                        RbacProfile.MEMBER.value,
                        utc_now_ms(),
                    ),
                )
                rank_id = int(cursor.lastrowid)
                created += 1
            await settings.set_rank_role_mapping(
                guild_id,
                rank_id,
                choice.role_id,
                actor_id,
                enabled=True,
                connection=connection,
            )
            next_level += 1

        # Nenhum registro é apagado: patentes antigas ou cargos funcionais que
        # não pertencem à lista oficial são apenas desativados e mantidos depois
        # da progressão ativa, preservando membros e histórico.
        for row in existing_rows:
            role_id = int(row["discord_role_id"]) if row["discord_role_id"] else None
            if role_id in detected_role_ids:
                continue
            was_active = bool(row["active"])
            await connection.execute(
                "UPDATE ranks SET level=?, active=0 WHERE id=?",
                (next_level, int(row["id"])),
            )
            await settings.set_rank_role_mapping(
                guild_id,
                int(row["id"]),
                role_id,
                actor_id,
                enabled=False,
                connection=connection,
            )
            if was_active:
                deactivated += 1
            next_level += 1

        ignored_roles = [
            choice.role_id
            for choice in choices
            if normalize_rank_name(choice.name) in IGNORED_RANK_ROLE_NAMES
        ]
        reconciliation = await enqueue_identity_reconciliation(
            connection,
            guild_id=guild_id,
            requested_by=int(actor_id or 0),
            mode="APPLY",
            source="RANK_CATALOG_IMPORTED",
        )
        await audit.record(
            guild_id,
            "RANKS_IMPORTED_FROM_DISCORD",
            actor_id=actor_id,
            after={
                "created": created,
                "updated": updated,
                "reordered": reordered,
                "deactivated": deactivated,
                "role_ids": [choice.role_id for choice, _ in detected],
                "ignored_role_ids": ignored_roles,
                "reconciliation_job_id": reconciliation["job_id"],
            },
            connection=connection,
        )
    return created, updated, detected


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_settings_admin(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Este painel só pode ser usado dentro do servidor.")
    bot = get_bot(interaction)
    if not await bot.services.permissions.has(interaction.user, "settings.manage"):
        raise PermissionDenied("Você não possui permissão para configurar o sistema.")
    return interaction.user


async def respond_error(interaction: discord.Interaction, error: Exception) -> None:
    correlation_id = str(uuid.uuid4())
    if isinstance(error, ChoqueError):
        message = f"❌ {error}"
    else:
        message = f"❌ Erro interno no painel. Código: `{correlation_id}`"
        LOGGER.exception(
            "Erro em componente de configuração",
            exc_info=(type(error), error, error.__traceback__),
            extra={"correlation_id": correlation_id},
        )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.DiscordException:
        LOGGER.warning(
            "Falha ao responder erro do painel",
            extra={"correlation_id": correlation_id},
        )


class AdminView(discord.ui.View):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            await require_settings_admin(interaction)
        except ChoqueError as exc:
            await respond_error(interaction, exc)
            return False
        return True

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await respond_error(interaction, error)


class AdminModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await respond_error(interaction, error)


async def save_setting(
    interaction: discord.Interaction, key: str, value: object, action: str = "SETTING_CHANGED"
) -> None:
    actor = await require_settings_admin(interaction)
    bot = get_bot(interaction)
    before = await bot.services.settings.get(actor.guild.id, key)
    async with bot.services.database.transaction() as connection:
        await bot.services.settings.set(actor.guild.id, key, value, actor.id, connection)
        await bot.services.audit.record(
            actor.guild.id,
            action,
            actor_id=actor.id,
            before={key: before},
            after={key: value},
            connection=connection,
        )


async def build_configuration_status(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    values = {key: await bot.services.settings.get(guild.id, key) for key, _, _ in CHANNEL_SETTINGS}
    values.update(
        {
            "member_role_id": await bot.services.settings.get(guild.id, "member_role_id"),
            "service_role_id": await bot.services.settings.get(guild.id, "service_role_id"),
            "away_role_id": await bot.services.settings.get(guild.id, "away_role_id"),
            "reserve_role_id": await bot.services.settings.get(guild.id, "reserve_role_id"),
            "suspended_role_id": await bot.services.settings.get(guild.id, "suspended_role_id"),
            "timezone": await bot.services.settings.get(guild.id, "timezone"),
            "grace_period_seconds": await bot.services.settings.get(
                guild.id, "grace_period_seconds"
            ),
            "weekly_goal_minutes": await bot.services.settings.get(guild.id, "weekly_goal_minutes"),
            "minimum_patrol_minutes": await bot.services.settings.get(
                guild.id, "minimum_patrol_minutes", 15
            ),
        }
    )
    calls = await bot.services.database.fetchall(
        "SELECT channel_id, label FROM authorized_voice_channels WHERE guild_id=? ORDER BY label",
        (guild.id,),
    )
    bindings = await bot.services.database.fetchall(
        """
        SELECT drm.discord_role_id AS role_id, ap.code AS profile
        FROM discord_role_mappings drm
        JOIN access_profiles ap ON ap.id=drm.access_profile_id
        WHERE drm.guild_id=? AND drm.mapping_type='ACCESS' AND drm.enabled=1
        ORDER BY ap.priority, drm.discord_role_id
        """,
        (guild.id,),
    )
    ranks = await bot.services.database.fetchall(
        "SELECT level, name FROM ranks WHERE guild_id=? AND active=1 ORDER BY level",
        (guild.id,),
    )
    modules = await bot.services.modules.states(guild.id)
    checks = [
        *[bool(values[key]) for key, _, _ in CHANNEL_SETTINGS],
        bool(values["member_role_id"]),
        bool(values["service_role_id"]),
        bool(values["away_role_id"]),
        bool(values["reserve_role_id"]),
        bool(values["suspended_role_id"]),
        bool(calls),
        bool(bindings),
        bool(ranks),
    ]
    completed = sum(checks)
    total = len(checks)
    embed = branded_embed(
        bot.config.branding,
        title="⚙️ Central de Configuração • CHOQUE - BGR",
        description=(
            f"Progresso essencial: **{completed}/{total}**\n"
            "Use os botões do painel para configurar cada seção."
        ),
    )
    channel_lines = []
    for key, label, emoji in CHANNEL_SETTINGS:
        channel_id = values[key]
        channel_lines.append(f"{emoji} **{label}:** {f'<#{channel_id}>' if channel_id else '❌'}")
    midpoint = (len(channel_lines) + 1) // 2
    embed.add_field(name="Canais • 1/2", value="\n".join(channel_lines[:midpoint]), inline=False)
    embed.add_field(name="Canais • 2/2", value="\n".join(channel_lines[midpoint:]), inline=False)
    embed.add_field(
        name="Operação",
        value=(
            f"🔊 Calls: **{len(calls)}**\n"
            f"🛡️ Vínculos RBAC: **{len(bindings)}**\n"
            f"🎖️ Patentes: **{len(ranks)}**"
        ),
    )
    embed.add_field(
        name="Cargos",
        value=(
            f"Membro: {f'<@&{values["member_role_id"]}>' if values['member_role_id'] else '❌'}\n"
            f"Em serviço: {f'<@&{values["service_role_id"]}>' if values['service_role_id'] else '❌'}\n"
            f"Ausente: {f'<@&{values["away_role_id"]}>' if values['away_role_id'] else '❌'}\n"
            f"Reserva: {f'<@&{values["reserve_role_id"]}>' if values['reserve_role_id'] else '❌'}\n"
            f"Suspenso: {f'<@&{values["suspended_role_id"]}>' if values['suspended_role_id'] else '❌'}"
        ),
    )
    embed.add_field(
        name="Regras",
        value=(
            f"Tolerância: **{values['grace_period_seconds']}s**\n"
            f"Patrulha mínima: **{values['minimum_patrol_minutes']} min**\n"
            f"Meta: **{values['weekly_goal_minutes']} min/semana**\n"
            f"Timezone: `{values['timezone']}`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Módulos",
        value="\n".join(
            f"{emoji} **{label}:** {'🟢 Ativo' if modules[key] else '🔴 Desativado'}"
            for key, label, emoji in MODULE_DEFINITIONS
        ),
        inline=False,
    )
    return embed


class ConfigurationMenuView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Canais",
        emoji="📢",
        style=discord.ButtonStyle.primary,
        custom_id="choque:config:channels:v1",
        row=0,
    )
    async def channels(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await build_channel_settings_embed(get_bot(interaction), interaction.guild),
            view=ChannelSettingsView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Calls",
        emoji="🔊",
        style=discord.ButtonStyle.primary,
        custom_id="choque:config:calls:v1",
        row=0,
    )
    async def calls(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await build_calls_embed(get_bot(interaction), interaction.guild),
            view=AuthorizedCallsView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Cargos e RBAC",
        emoji="🛡️",
        style=discord.ButtonStyle.primary,
        custom_id="choque:config:roles:v1",
        row=0,
    )
    async def roles(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        view = RolesConfigurationView()
        await interaction.response.send_message(
            embed=await build_roles_embed(get_bot(interaction), interaction.guild),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Patentes",
        emoji="🎖️",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:config:ranks:v1",
        row=1,
    )
    async def ranks(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await build_ranks_embed(get_bot(interaction), interaction.guild),
            view=RanksConfigurationView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Regras",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:config:rules:v1",
        row=1,
    )
    async def rules(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        bot = get_bot(interaction)
        await interaction.response.send_modal(
            RulesModal(
                grace=await bot.services.settings.get(interaction.guild.id, "grace_period_seconds"),
                goal=await bot.services.settings.get(interaction.guild.id, "weekly_goal_minutes"),
                minimum_patrol=await bot.services.settings.get(
                    interaction.guild.id, "minimum_patrol_minutes", 15
                ),
                timezone_name=await bot.services.settings.get(interaction.guild.id, "timezone"),
            )
        )

    @discord.ui.button(
        label="Publicar painéis",
        emoji="🧩",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:config:panels:v1",
        row=1,
    )
    async def panels(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=branded_embed(
                get_bot(interaction).config.branding,
                title="🧩 Publicação de painéis",
                description="Escolha o painel e depois o canal onde ele será publicado.",
            ),
            view=PanelsConfigurationView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Módulos",
        emoji="🧰",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:config:modules:v1",
        row=2,
    )
    async def modules(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        bot = get_bot(interaction)
        states = await bot.services.modules.states(interaction.guild.id)
        await interaction.response.send_message(
            embed=build_modules_embed(bot, states),
            view=ModulesConfigurationView(states),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Ver status",
        emoji="📊",
        style=discord.ButtonStyle.success,
        custom_id="choque:config:status:v1",
        row=2,
    )
    async def status(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await build_configuration_status(get_bot(interaction), interaction.guild),
            ephemeral=True,
        )


def build_modules_embed(bot: ChoqueBot, states: dict[str, bool]) -> discord.Embed:
    lines = [
        f"{emoji} **{label}:** {'🟢 Ativo' if states[key] else '🔴 Desativado'}"
        for key, label, emoji in MODULE_DEFINITIONS
    ]
    return branded_embed(
        bot.config.branding,
        title="🧰 Controle de Módulos",
        description=(
            "Ative ou desative os módulos principais. A desativação bloqueia novas interações "
            "sem apagar dados, históricos ou ações já registradas.\n\n" + "\n".join(lines)
        ),
    )


class ModuleToggleButton(discord.ui.Button):
    def __init__(self, key: str, label: str, emoji: str, enabled: bool, row: int) -> None:
        self.module_key = key
        super().__init__(
            label=f"{label} • {'Ativo' if enabled else 'Desativado'}",
            emoji=emoji,
            style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger,
            custom_id=f"choque:config:module:{key.lower()}:v1",
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_settings_admin(interaction)
        bot = get_bot(interaction)
        current = await bot.services.modules.is_enabled(actor.guild.id, self.module_key)
        states = await bot.services.modules.set_enabled(
            actor.guild.id,
            self.module_key,
            not current,
            actor.id,
        )
        await interaction.response.edit_message(
            embed=build_modules_embed(bot, states),
            view=ModulesConfigurationView(states),
        )


class ModulesConfigurationView(AdminView):
    def __init__(self, states: dict[str, bool]) -> None:
        super().__init__(timeout=600)
        for index, (key, label, emoji) in enumerate(MODULE_DEFINITIONS):
            self.add_item(ModuleToggleButton(key, label, emoji, states[key], index // 4))


async def build_channel_settings_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    lines = []
    for key, label, emoji in CHANNEL_SETTINGS:
        channel_id = await bot.services.settings.get(guild.id, key)
        lines.append(f"{emoji} **{label}:** {f'<#{channel_id}>' if channel_id else '❌'}")
    return branded_embed(
        bot.config.branding,
        title="📢 Configuração de canais",
        description=(
            "Escolha primeiro o **destino do sistema**. Depois o bot mostrará todos "
            "os canais em páginas de 25, com busca por nome, categoria ou ID.\n\n"
            + "\n".join(lines)
        ),
    )


def build_channel_browser_embed(
    bot: ChoqueBot,
    *,
    label: str,
    total: int,
    page: int,
    page_count: int,
    voice: bool,
    query: str | None = None,
) -> discord.Embed:
    kind = "calls" if voice else "canais de texto"
    scope = f"Resultados para `{query}`" if query else f"Todos os {kind} do servidor"
    return branded_embed(
        bot.config.branding,
        title=f"📡 {label}",
        description=(
            f"{scope}: **{total}**\n"
            f"Página **{page + 1}/{page_count}**. O nome da categoria e o ID "
            "aparecem em cada opção."
        ),
    )


class ChannelDestinationButton(discord.ui.Button):
    def __init__(self, key: str, label: str, emoji: str, row: int) -> None:
        self.setting_key = key
        self.setting_label = label
        short_label = label.removeprefix("Canal ")
        for prefix in ("de ", "do ", "da "):
            short_label = short_label.removeprefix(prefix)
        super().__init__(
            label=short_label[:80],
            emoji=emoji,
            style=discord.ButtonStyle.primary,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            raise ValidationError("Este painel só pode ser usado dentro do servidor.")
        choices = channel_choices_for_guild(interaction.guild)
        if not choices:
            raise ValidationError("Nenhum canal de texto está disponível neste servidor.")
        bot = get_bot(interaction)
        selected_id = await bot.services.settings.get(interaction.guild.id, self.setting_key)
        view = ChannelBrowserView(
            action="SETTING",
            action_key=self.setting_key,
            label=self.setting_label,
            choices=choices,
            selected_id=int(selected_id) if selected_id else None,
        )
        await interaction.response.edit_message(
            content=None,
            embed=view.embed(bot),
            view=view,
        )


class ChannelSettingsView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=600)
        for index, (key, label, emoji) in enumerate(CHANNEL_SETTINGS):
            self.add_item(ChannelDestinationButton(key, label, emoji, index // 5))


class ChannelBrowserSelect(discord.ui.Select):
    def __init__(
        self,
        choices: list[ChannelChoice],
        *,
        page: int,
        selected_id: int | None,
    ) -> None:
        page_choices, safe_page, page_count = paginate_items(choices, page)
        super().__init__(
            placeholder=f"Escolha uma opção • página {safe_page + 1}/{page_count}",
            options=[
                discord.SelectOption(
                    label=f"# {choice.name}"[:100],
                    value=str(choice.channel_id),
                    description=(
                        f"{choice.category_name or 'Sem categoria'} • ID {choice.channel_id}"
                    )[:100],
                    default=choice.channel_id == selected_id,
                )
                for choice in page_choices
            ],
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = cast("ChannelBrowserView", self.view)
        channel_id = int(self.values[0])
        channel = interaction.guild.get_channel(channel_id) if interaction.guild else None
        expected_type = (
            (discord.VoiceChannel, discord.StageChannel) if view.voice else discord.TextChannel
        )
        if not isinstance(channel, expected_type):
            raise ValidationError("O canal selecionado não está mais disponível.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        bot = get_bot(interaction)

        if view.action == "SETTING":
            await save_setting(interaction, view.action_key, channel_id)
            jump_url: str | None = None
            if view.action_key == "config_panel_channel_id":
                cog = bot.get_cog("ConfigurationCommands")
                if cog and hasattr(cog, "publish_or_refresh_config_panel"):
                    message = await cog.publish_or_refresh_config_panel(
                        interaction.guild, cast(discord.TextChannel, channel)
                    )
                    jump_url = message.jump_url
            result = f"✅ **{view.label}** definido como {channel.mention}."
            if jump_url:
                result += f" [Abrir menu]({jump_url})"
        elif view.action == "CALL_ADD":
            actor = await require_settings_admin(interaction)
            async with bot.services.database.transaction() as connection:
                await connection.execute(
                    """
                    INSERT INTO authorized_voice_channels(
                        guild_id, channel_id, label, created_at, created_by,
                        service_allowed, counts_toward_patrol_minimum
                    ) VALUES (?, ?, ?, ?, ?, 1, 1)
                    ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                        label=excluded.label,
                        service_allowed=1
                    """,
                    (actor.guild.id, channel.id, channel.name, utc_now_ms(), actor.id),
                )
                await bot.services.audit.record(
                    actor.guild.id,
                    "AUTHORIZED_CALL_ADDED",
                    actor_id=actor.id,
                    target_id=channel.id,
                    after={"channel_id": channel.id, "name": channel.name},
                    connection=connection,
                )
            result = f"✅ {channel.mention} autorizada para o ponto."
        elif view.action == "CALL_REMOVE":
            actor = await require_settings_admin(interaction)
            async with bot.services.database.transaction() as connection:
                cursor = await connection.execute(
                    "DELETE FROM authorized_voice_channels WHERE guild_id=? AND channel_id=?",
                    (actor.guild.id, channel.id),
                )
                if cursor.rowcount != 1:
                    raise ValidationError("Essa call não estava autorizada.")
                await bot.services.audit.record(
                    actor.guild.id,
                    "AUTHORIZED_CALL_REMOVED",
                    actor_id=actor.id,
                    target_id=channel.id,
                    before={"channel_id": channel.id},
                    connection=connection,
                )
            result = f"✅ {channel.mention} removida das calls autorizadas."
        elif view.action == "CALL_TOGGLE_PATROL":
            actor = await require_settings_admin(interaction)
            async with bot.services.database.transaction() as connection:
                cursor = await connection.execute(
                    """
                    SELECT counts_toward_patrol_minimum
                    FROM authorized_voice_channels
                    WHERE guild_id=? AND channel_id=? AND service_allowed=1
                    """,
                    (actor.guild.id, channel.id),
                )
                current = await cursor.fetchone()
                if not current:
                    raise ValidationError("Essa call não está autorizada para serviço.")
                new_value = not bool(current["counts_toward_patrol_minimum"])
                await connection.execute(
                    """
                    UPDATE authorized_voice_channels
                    SET counts_toward_patrol_minimum=?
                    WHERE guild_id=? AND channel_id=? AND service_allowed=1
                    """,
                    (int(new_value), actor.guild.id, channel.id),
                )
                await bot.services.audit.record(
                    actor.guild.id,
                    "AUTHORIZED_CALL_PATROL_CLASSIFICATION_CHANGED",
                    actor_id=actor.id,
                    target_id=channel.id,
                    before={"counts_toward_patrol_minimum": bool(current[0])},
                    after={"counts_toward_patrol_minimum": new_value},
                    connection=connection,
                )
            result = (
                f"✅ {channel.mention} agora **conta para o mínimo de patrulha**."
                if new_value
                else f"✅ {channel.mention} agora **mantém o serviço, mas não conta patrulha**."
            )
        else:
            await publish_panel_to_channel(
                interaction, view.action_key, cast(discord.TextChannel, channel)
            )
            result = f"✅ Painel **{view.action_key}** publicado em {channel.mention}."

        updated = view.clone(selected_id=channel_id)
        await interaction.edit_original_response(
            content=result,
            embed=updated.embed(bot),
            view=updated,
        )


class ChannelPageButton(discord.ui.Button):
    def __init__(self, direction: int, *, disabled: bool) -> None:
        self.direction = direction
        super().__init__(
            label="Anterior" if direction < 0 else "Próxima",
            emoji="◀️" if direction < 0 else "▶️",
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = cast("ChannelBrowserView", self.view)
        updated = view.clone(page=view.page + self.direction)
        await interaction.response.edit_message(
            content=None, embed=updated.embed(get_bot(interaction)), view=updated
        )


class ChannelSearchModal(AdminModal, title="Buscar canal ou call"):
    query_input = discord.ui.TextInput(
        label="Nome, categoria ou ID",
        placeholder="Ex.: logs, comandos ou 123456789...",
        max_length=100,
    )

    def __init__(self, source: ChannelBrowserView) -> None:
        super().__init__()
        self.source = source

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await require_settings_admin(interaction)
        query = str(self.query_input).strip()
        matches = search_channel_choices(self.source.all_choices, query)
        if not matches:
            await interaction.response.send_message(
                f"❌ Nenhum resultado para `{query}`. Tente parte do nome ou o ID.",
                ephemeral=True,
            )
            return
        view = self.source.clone(choices=matches, page=0, query=query)
        await interaction.response.send_message(
            embed=view.embed(get_bot(interaction)), view=view, ephemeral=True
        )


class ChannelBrowserView(AdminView):
    def __init__(
        self,
        *,
        action: str,
        action_key: str,
        label: str,
        choices: list[ChannelChoice],
        selected_id: int | None,
        page: int = 0,
        query: str | None = None,
        all_choices: list[ChannelChoice] | None = None,
        voice: bool = False,
    ) -> None:
        super().__init__(timeout=600)
        self.action = action
        self.action_key = action_key
        self.label = label
        self.choices = choices
        self.all_choices = all_choices or choices
        self.selected_id = selected_id
        self.query = query
        self.voice = voice
        _, self.page, self.page_count = paginate_items(choices, page)
        self.add_item(ChannelBrowserSelect(choices, page=self.page, selected_id=selected_id))
        self.add_item(ChannelPageButton(-1, disabled=self.page == 0))
        self.add_item(ChannelPageButton(1, disabled=self.page >= self.page_count - 1))

    def clone(
        self,
        *,
        choices: list[ChannelChoice] | None = None,
        selected_id: int | None = None,
        page: int | None = None,
        query: str | None = None,
    ) -> ChannelBrowserView:
        return ChannelBrowserView(
            action=self.action,
            action_key=self.action_key,
            label=self.label,
            choices=choices or self.choices,
            selected_id=self.selected_id if selected_id is None else selected_id,
            page=self.page if page is None else page,
            query=self.query if query is None else query,
            all_choices=self.all_choices,
            voice=self.voice,
        )

    def embed(self, bot: ChoqueBot) -> discord.Embed:
        return build_channel_browser_embed(
            bot,
            label=self.label,
            total=len(self.choices),
            page=self.page,
            page_count=self.page_count,
            voice=self.voice,
            query=self.query,
        )

    @discord.ui.button(label="Buscar", emoji="🔎", style=discord.ButtonStyle.primary, row=1)
    async def search(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ChannelSearchModal(self))

    @discord.ui.button(label="Voltar", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        bot = get_bot(interaction)
        if self.action.startswith("CALL_"):
            embed = await build_calls_embed(bot, interaction.guild)
            view: discord.ui.View = AuthorizedCallsView()
        elif self.action == "PANEL":
            embed = branded_embed(
                bot.config.branding,
                title="🧩 Publicação de painéis",
                description="Escolha o painel e depois o canal onde ele será publicado.",
            )
            view = PanelsConfigurationView()
        else:
            embed = await build_channel_settings_embed(bot, interaction.guild)
            view = ChannelSettingsView()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


async def build_calls_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    rows = await bot.services.database.fetchall(
        """
        SELECT channel_id, label, service_allowed, counts_toward_patrol_minimum
        FROM authorized_voice_channels WHERE guild_id=? ORDER BY label
        """,
        (guild.id,),
    )
    description = "\n".join(
        f"• <#{row['channel_id']}> — {row['label']}\n"
        f"  Serviço: {'✅' if row['service_allowed'] else '❌'} • "
        f"Patrulha mínima: {'✅ Conta' if row['counts_toward_patrol_minimum'] else '➖ Não conta'}"
        for row in rows
    )
    return branded_embed(
        bot.config.branding,
        title="🔊 Calls autorizadas",
        description=description or "Nenhuma call autorizada.",
    )


class AuthorizedCallsView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=600)

    async def open_browser(self, interaction: discord.Interaction, *, remove: bool) -> None:
        if not interaction.guild:
            raise ValidationError("Este painel só pode ser usado dentro do servidor.")
        choices = channel_choices_for_guild(interaction.guild, voice=True)
        if remove:
            authorized_ids = await get_bot(interaction).services.settings.authorized_voice_ids(
                interaction.guild.id
            )
            choices = [choice for choice in choices if choice.channel_id in authorized_ids]
            if not choices:
                raise ValidationError("Nenhuma call autorizada para remover.")
        view = ChannelBrowserView(
            action="CALL_REMOVE" if remove else "CALL_ADD",
            action_key="authorized_voice_channels",
            label="Remover call autorizada" if remove else "Adicionar call autorizada",
            choices=choices,
            selected_id=None,
            voice=True,
        )
        await interaction.response.edit_message(
            content=None, embed=view.embed(get_bot(interaction)), view=view
        )

    async def open_patrol_classification(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            raise ValidationError("Este painel só pode ser usado dentro do servidor.")
        choices = channel_choices_for_guild(interaction.guild, voice=True)
        authorized_ids = await get_bot(interaction).services.settings.authorized_voice_ids(
            interaction.guild.id
        )
        choices = [choice for choice in choices if choice.channel_id in authorized_ids]
        if not choices:
            raise ValidationError("Nenhuma call autorizada está disponível para classificar.")
        view = ChannelBrowserView(
            action="CALL_TOGGLE_PATROL",
            action_key="counts_toward_patrol_minimum",
            label="Alternar contagem de patrulha",
            choices=choices,
            selected_id=None,
            voice=True,
        )
        await interaction.response.edit_message(
            content=None, embed=view.embed(get_bot(interaction)), view=view
        )

    @discord.ui.button(label="Adicionar call", emoji="➕", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_browser(interaction, remove=False)

    @discord.ui.button(label="Remover call", emoji="➖", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_browser(interaction, remove=True)

    @discord.ui.button(label="Conta patrulha", emoji="🎯", style=discord.ButtonStyle.secondary)
    async def patrol(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_patrol_classification(interaction)

    @discord.ui.button(label="Atualizar lista", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=None,
            embed=await build_calls_embed(get_bot(interaction), interaction.guild),
            view=self,
        )


async def build_roles_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    member_role = await bot.services.settings.get(guild.id, "member_role_id")
    service_role = await bot.services.settings.get(guild.id, "service_role_id")
    away_role = await bot.services.settings.get(guild.id, "away_role_id")
    reserve_role = await bot.services.settings.get(guild.id, "reserve_role_id")
    suspended_role = await bot.services.settings.get(guild.id, "suspended_role_id")
    rows = await bot.services.database.fetchall(
        """
        SELECT drm.discord_role_id AS role_id, ap.code AS profile
        FROM discord_role_mappings drm
        JOIN access_profiles ap ON ap.id=drm.access_profile_id
        WHERE drm.guild_id=? AND drm.mapping_type='ACCESS' AND drm.enabled=1
        ORDER BY ap.priority, drm.discord_role_id
        """,
        (guild.id,),
    )
    bindings = "\n".join(f"• <@&{row['role_id']}> → `{row['profile']}`" for row in rows)
    return branded_embed(
        bot.config.branding,
        title="🛡️ Cargos e permissões",
        description=(
            f"**Cargo de membro:** {f'<@&{member_role}>' if member_role else '❌'}\n"
            f"**Cargo em serviço:** {f'<@&{service_role}>' if service_role else '❌'}\n\n"
            f"**Cargo de ausente:** {f'<@&{away_role}>' if away_role else '❌'}\n"
            f"**Cargo da reserva:** {f'<@&{reserve_role}>' if reserve_role else '❌'}\n"
            f"**Cargo de suspenso:** {f'<@&{suspended_role}>' if suspended_role else '❌'}\n\n"
            f"**RBAC**\n{bindings or 'Nenhum vínculo configurado.'}"
        ),
    )


class RolesConfigurationView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=600)

    async def open_browser(
        self,
        interaction: discord.Interaction,
        *,
        action: str,
        action_key: str,
        label: str,
    ) -> None:
        if not interaction.guild:
            raise ValidationError("Este painel só pode ser usado dentro do servidor.")
        choices = role_choices_for_guild(interaction.guild)
        selected_id = None
        if action == "SETTING":
            selected_id = await get_bot(interaction).services.settings.get(
                interaction.guild.id, action_key
            )
        view = RoleBrowserView(
            action=action,
            action_key=action_key,
            label=label,
            choices=choices,
            selected_id=int(selected_id) if selected_id else None,
        )
        await interaction.response.edit_message(
            content=None, embed=view.embed(get_bot(interaction)), view=view
        )

    @discord.ui.button(label="Cargo de membro", emoji="👤", style=discord.ButtonStyle.primary)
    async def member_role(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_browser(
            interaction,
            action="SETTING",
            action_key="member_role_id",
            label="Definir cargo de membro",
        )

    @discord.ui.button(label="Cargo em serviço", emoji="🟢", style=discord.ButtonStyle.primary)
    async def service_role(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_browser(
            interaction,
            action="SETTING",
            action_key="service_role_id",
            label="Definir cargo em serviço",
        )

    @discord.ui.button(
        label="Cargo de ausente", emoji="🟠", style=discord.ButtonStyle.secondary, row=1
    )
    async def away_role(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_browser(
            interaction,
            action="SETTING",
            action_key="away_role_id",
            label="Definir cargo de ausente",
        )

    @discord.ui.button(
        label="Cargo da reserva", emoji="🟡", style=discord.ButtonStyle.secondary, row=1
    )
    async def reserve_role(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_browser(
            interaction,
            action="SETTING",
            action_key="reserve_role_id",
            label="Definir cargo da reserva",
        )

    @discord.ui.button(
        label="Cargo de suspenso", emoji="🔴", style=discord.ButtonStyle.secondary, row=1
    )
    async def suspended_role(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_browser(
            interaction,
            action="SETTING",
            action_key="suspended_role_id",
            label="Definir cargo de suspenso",
        )

    @discord.ui.button(label="Vincular RBAC", emoji="🛡️", style=discord.ButtonStyle.secondary)
    async def bind_rbac(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_browser(
            interaction,
            action="RBAC_BIND",
            action_key="rbac_bindings",
            label="Escolher cargo para vincular ao RBAC",
        )

    @discord.ui.button(label="Remover RBAC", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def unbind_rbac(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_browser(
            interaction,
            action="RBAC_UNBIND",
            action_key="rbac_bindings",
            label="Escolher cargo para remover do RBAC",
        )

    @discord.ui.button(label="Atualizar", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=None,
            embed=await build_roles_embed(get_bot(interaction), interaction.guild),
            view=self,
        )


def build_role_browser_embed(
    bot: ChoqueBot,
    *,
    label: str,
    total: int,
    page: int,
    page_count: int,
    query: str | None = None,
) -> discord.Embed:
    scope = f"Resultados para `{query}`" if query else "Todos os cargos do servidor"
    return branded_embed(
        bot.config.branding,
        title=f"🛡️ {label}",
        description=(
            f"{scope}: **{total}**\nPágina **{page + 1}/{page_count}**. "
            "Cargos gerenciados por bots aparecem na lista, mas não podem ser usados "
            "como cargo operacional."
        ),
    )


class RoleBrowserSelect(discord.ui.Select):
    def __init__(self, choices: list[RoleChoice], *, page: int, selected_id: int | None) -> None:
        page_choices, safe_page, page_count = paginate_items(choices, page)
        super().__init__(
            placeholder=f"Escolha um cargo • página {safe_page + 1}/{page_count}",
            options=[
                discord.SelectOption(
                    label=f"@ {choice.name}"[:100],
                    value=str(choice.role_id),
                    description=(
                        f"Posição {choice.position} • ID {choice.role_id}"
                        + (" • gerenciado" if choice.managed else "")
                    )[:100],
                    default=choice.role_id == selected_id,
                )
                for choice in page_choices
            ],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = cast("RoleBrowserView", self.view)
        role_id = int(self.values[0])
        role = interaction.guild.get_role(role_id) if interaction.guild else None
        if not role:
            raise ValidationError("O cargo selecionado não está mais disponível.")
        if role.managed and view.action in {"SETTING", "RBAC_BIND"}:
            raise ValidationError("Cargos gerenciados por integrações não podem ser usados aqui.")

        if view.action == "RBAC_BIND":
            await interaction.response.edit_message(
                content=f"Cargo selecionado: {role.mention}. Agora escolha o perfil RBAC.",
                embed=None,
                view=RbacProfileView(role.id, role.name),
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        if view.action == "SETTING":
            await save_setting(interaction, view.action_key, role.id)
            result = f"✅ Cargo definido como {role.mention}."
        else:
            actor = await require_settings_admin(interaction)
            bot = get_bot(interaction)
            async with bot.services.database.transaction() as connection:
                cursor = await connection.execute(
                    """
                    SELECT 1 FROM discord_role_mappings
                    WHERE guild_id=? AND discord_role_id=? AND mapping_type='ACCESS'
                    """,
                    (actor.guild.id, role.id),
                )
                if not await cursor.fetchone():
                    raise ValidationError("Esse cargo não possuía vínculo RBAC.")
                reconciliation = await bot.services.settings.unbind_role(
                    actor.guild.id,
                    role.id,
                    actor.id,
                    "DISCORD_PANEL_RBAC_REMOVED",
                    connection=connection,
                )
                await bot.services.audit.record(
                    actor.guild.id,
                    "RBAC_ROLE_UNBOUND",
                    actor_id=actor.id,
                    target_id=role.id,
                    before={"role_id": role.id},
                    after={"reconciliation_job_id": reconciliation["job_id"]},
                    connection=connection,
                )
            await bot.services.permissions.invalidate(actor.guild.id)
            result = f"✅ Vínculo de {role.mention} removido."

        updated = view.clone(selected_id=role.id)
        await interaction.edit_original_response(
            content=result,
            embed=updated.embed(get_bot(interaction)),
            view=updated,
        )


class RolePageButton(discord.ui.Button):
    def __init__(self, direction: int, *, disabled: bool) -> None:
        self.direction = direction
        super().__init__(
            label="Anterior" if direction < 0 else "Próxima",
            emoji="◀️" if direction < 0 else "▶️",
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = cast("RoleBrowserView", self.view)
        updated = view.clone(page=view.page + self.direction)
        await interaction.response.edit_message(
            content=None, embed=updated.embed(get_bot(interaction)), view=updated
        )


class RoleSearchModal(AdminModal, title="Buscar cargo"):
    query_input = discord.ui.TextInput(
        label="Nome ou ID do cargo",
        placeholder="Ex.: soldado, comando ou 123456789...",
        max_length=100,
    )

    def __init__(self, source: RoleBrowserView) -> None:
        super().__init__()
        self.source = source

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await require_settings_admin(interaction)
        query = str(self.query_input).strip()
        matches = search_role_choices(self.source.all_choices, query)
        if not matches:
            await interaction.response.send_message(
                f"❌ Nenhum cargo encontrado para `{query}`.", ephemeral=True
            )
            return
        view = self.source.clone(choices=matches, page=0, query=query)
        await interaction.response.send_message(
            embed=view.embed(get_bot(interaction)), view=view, ephemeral=True
        )


class RoleBrowserView(AdminView):
    def __init__(
        self,
        *,
        action: str,
        action_key: str,
        label: str,
        choices: list[RoleChoice],
        selected_id: int | None,
        page: int = 0,
        query: str | None = None,
        all_choices: list[RoleChoice] | None = None,
    ) -> None:
        super().__init__(timeout=600)
        self.action = action
        self.action_key = action_key
        self.label = label
        self.choices = choices
        self.all_choices = all_choices or choices
        self.selected_id = selected_id
        self.query = query
        _, self.page, self.page_count = paginate_items(choices, page)
        self.add_item(RoleBrowserSelect(choices, page=self.page, selected_id=selected_id))
        self.add_item(RolePageButton(-1, disabled=self.page == 0))
        self.add_item(RolePageButton(1, disabled=self.page >= self.page_count - 1))

    def clone(
        self,
        *,
        choices: list[RoleChoice] | None = None,
        selected_id: int | None = None,
        page: int | None = None,
        query: str | None = None,
    ) -> RoleBrowserView:
        return RoleBrowserView(
            action=self.action,
            action_key=self.action_key,
            label=self.label,
            choices=choices or self.choices,
            selected_id=self.selected_id if selected_id is None else selected_id,
            page=self.page if page is None else page,
            query=self.query if query is None else query,
            all_choices=self.all_choices,
        )

    def embed(self, bot: ChoqueBot) -> discord.Embed:
        return build_role_browser_embed(
            bot,
            label=self.label,
            total=len(self.choices),
            page=self.page,
            page_count=self.page_count,
            query=self.query,
        )

    @discord.ui.button(label="Buscar", emoji="🔎", style=discord.ButtonStyle.primary, row=1)
    async def search(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RoleSearchModal(self))

    @discord.ui.button(label="Cargos", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
    async def roles(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=None,
            embed=await build_roles_embed(get_bot(interaction), interaction.guild),
            view=RolesConfigurationView(),
        )


class RbacProfileSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Escolha o perfil RBAC",
            options=[
                discord.SelectOption(label=profile.value, value=profile.value)
                for profile in RbacProfile
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = cast("RbacProfileView", self.view)
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = await require_settings_admin(interaction)
        bot = get_bot(interaction)
        role = actor.guild.get_role(view.role_id)
        if not role:
            raise ValidationError("O cargo selecionado não existe mais.")
        profile = RbacProfile(self.values[0])
        async with bot.services.database.transaction() as connection:
            reconciliation = await bot.services.settings.bind_role(
                actor.guild.id,
                role.id,
                profile,
                actor.id,
                "DISCORD_PANEL_RBAC_CHANGED",
                connection=connection,
            )
            await bot.services.audit.record(
                actor.guild.id,
                "RBAC_ROLE_BOUND",
                actor_id=actor.id,
                target_id=role.id,
                after={
                    "role_id": role.id,
                    "profile": profile.value,
                    "reconciliation_job_id": reconciliation["job_id"],
                },
                connection=connection,
            )
        await bot.services.permissions.invalidate(actor.guild.id)
        await interaction.edit_original_response(
            content=f"✅ {role.mention} vinculado a `{profile.value}`.",
            embed=await build_roles_embed(bot, actor.guild),
            view=RolesConfigurationView(),
        )


class RbacProfileView(AdminView):
    def __init__(self, role_id: int, role_name: str) -> None:
        super().__init__(timeout=300)
        self.role_id = role_id
        self.role_name = role_name
        self.add_item(RbacProfileSelect())


async def build_ranks_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    rows = await bot.services.database.fetchall(
        """
        SELECT level, name, prefix, discord_role_id, rbac_profile, active
        FROM ranks WHERE guild_id=? ORDER BY level
        """,
        (guild.id,),
    )
    lines = [
        f"`{row['level']:03d}` {row['prefix']} **{row['name']}** "
        f"{f'<@&{row["discord_role_id"]}>' if row['discord_role_id'] else ''} "
        f"`{row['rbac_profile']}`{' • inativa' if not row['active'] else ''}"
        for row in rows
    ]
    return branded_embed(
        bot.config.branding,
        title="🎖️ Patentes",
        description="\n".join(lines)[:4000] or "Nenhuma patente configurada.",
    )


async def refresh_hierarchy_panel(bot: ChoqueBot, guild: discord.Guild) -> None:
    cog = bot.get_cog("HierarchyCommands")
    if not cog:
        return
    try:
        await cog.refresh_configured_panel(guild)
    except Exception:
        LOGGER.exception("Falha ao atualizar painel de hierarquia da guild %s", guild.id)


class RankModal(AdminModal, title="Criar ou editar patente"):
    level = discord.ui.TextInput(label="Nível", placeholder="1", max_length=3)
    name = discord.ui.TextInput(label="Nome", placeholder="Soldado", max_length=60)
    prefix = discord.ui.TextInput(label="Prefixo", placeholder="[SD]", max_length=20)
    role_id = discord.ui.TextInput(
        label="ID do cargo Discord", placeholder="123456789...", max_length=25, required=False
    )
    profile = discord.ui.TextInput(
        label="Perfil RBAC",
        placeholder="MEMBRO / GRADUADO / INSTRUTOR / COMANDO / ADMINISTRADOR",
        default="MEMBRO",
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = await require_settings_admin(interaction)
        if not str(self.level).isdigit() or not 1 <= int(str(self.level)) <= 999:
            raise ValidationError("O nível deve ser um número entre 1 e 999.")
        if not str(self.name).strip():
            raise ValidationError("O nome da patente é obrigatório.")
        try:
            profile = RbacProfile(str(self.profile).strip().upper())
        except ValueError as exc:
            raise ValidationError("Perfil RBAC inválido.") from exc
        role_id: int | None = None
        if str(self.role_id).strip():
            if not str(self.role_id).strip().isdigit():
                raise ValidationError("O ID do cargo deve conter somente números.")
            role_id = int(str(self.role_id).strip())
            if not actor.guild.get_role(role_id):
                raise ValidationError("O cargo informado não existe neste servidor.")
        bot = get_bot(interaction)
        level = int(str(self.level))
        try:
            async with bot.services.database.transaction() as connection:
                cursor = await connection.execute(
                    "SELECT * FROM ranks WHERE guild_id=? AND level=?",
                    (actor.guild.id, level),
                )
                before = await cursor.fetchone()
                await connection.execute(
                    """
                    INSERT INTO ranks(
                        guild_id, name, prefix, level, rbac_profile, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, level) DO UPDATE SET name=excluded.name,
                        prefix=excluded.prefix, rbac_profile=excluded.rbac_profile, active=1
                    """,
                    (
                        actor.guild.id,
                        str(self.name).strip(),
                        str(self.prefix).strip(),
                        level,
                        profile.value,
                        utc_now_ms(),
                    ),
                )
                saved_cursor = await connection.execute(
                    "SELECT id FROM ranks WHERE guild_id=? AND level=?",
                    (actor.guild.id, level),
                )
                saved_rank = await saved_cursor.fetchone()
                assert saved_rank is not None
                await bot.services.settings.set_rank_role_mapping(
                    actor.guild.id,
                    int(saved_rank["id"]),
                    role_id,
                    actor.id,
                    enabled=True,
                    connection=connection,
                )
                reconciliation = await enqueue_identity_reconciliation(
                    connection,
                    guild_id=actor.guild.id,
                    requested_by=actor.id,
                    mode="APPLY",
                    source="RANK_MAPPING_CHANGED",
                )
                await bot.services.audit.record(
                    actor.guild.id,
                    "RANK_UPSERTED",
                    actor_id=actor.id,
                    target_id=role_id,
                    before=dict(before) if before else None,
                    after={
                        "level": level,
                        "name": str(self.name).strip(),
                        "prefix": str(self.prefix).strip(),
                        "profile": profile.value,
                        "role_id": role_id,
                        "reconciliation_job_id": reconciliation["job_id"],
                    },
                    connection=connection,
                )
        except aiosqlite.IntegrityError as exc:
            raise ValidationError("Esse cargo já está vinculado a outra patente.") from exc
        await refresh_hierarchy_panel(bot, actor.guild)
        await interaction.followup.send(
            f"✅ Patente nível **{level}** salva como **{self.name}**.", ephemeral=True
        )


class DeactivateRankModal(AdminModal, title="Desativar patente"):
    level = discord.ui.TextInput(label="Nível da patente", placeholder="1", max_length=3)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = await require_settings_admin(interaction)
        if not str(self.level).isdigit():
            raise ValidationError("Informe um nível numérico.")
        level = int(str(self.level))
        bot = get_bot(interaction)
        async with bot.services.database.transaction() as connection:
            rank_cursor = await connection.execute(
                """
                SELECT id, discord_role_id
                FROM ranks
                WHERE guild_id=? AND level=? AND active=1
                """,
                (actor.guild.id, level),
            )
            rank = await rank_cursor.fetchone()
            if rank is None:
                raise ValidationError("Patente ativa não encontrada nesse nível.")
            cursor = await connection.execute(
                "UPDATE ranks SET active=0 WHERE guild_id=? AND level=? AND active=1",
                (actor.guild.id, level),
            )
            if cursor.rowcount != 1:
                raise ValidationError("Patente ativa não encontrada nesse nível.")
            await bot.services.settings.set_rank_role_mapping(
                actor.guild.id,
                int(rank["id"]),
                int(rank["discord_role_id"]) if rank["discord_role_id"] is not None else None,
                actor.id,
                enabled=False,
                connection=connection,
            )
            reconciliation = await enqueue_identity_reconciliation(
                connection,
                guild_id=actor.guild.id,
                requested_by=actor.id,
                mode="APPLY",
                source="RANK_MAPPING_DISABLED",
            )
            await bot.services.audit.record(
                actor.guild.id,
                "RANK_DEACTIVATED",
                actor_id=actor.id,
                after={
                    "level": level,
                    "active": False,
                    "reconciliation_job_id": reconciliation["job_id"],
                },
                connection=connection,
            )
        await refresh_hierarchy_panel(bot, actor.guild)
        await interaction.followup.send(f"✅ Patente nível **{level}** desativada.", ephemeral=True)


class RanksConfigurationView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=600)

    @discord.ui.button(label="Criar/editar", emoji="➕", style=discord.ButtonStyle.primary)
    async def upsert(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RankModal())

    @discord.ui.button(label="Desativar", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def deactivate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(DeactivateRankModal())

    @discord.ui.button(label="Atualizar lista", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=await build_ranks_embed(get_bot(interaction), interaction.guild), view=self
        )

    @discord.ui.button(label="Importar dos cargos", emoji="📥", style=discord.ButtonStyle.success)
    async def import_roles(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = await require_settings_admin(interaction)
        created, updated, detected = await import_military_rank_roles(
            get_bot(interaction),
            guild_id=actor.guild.id,
            choices=role_choices_for_guild(actor.guild),
            actor_id=actor.id,
        )
        if not detected:
            raise ValidationError(
                "Nenhum cargo com nome de patente militar reconhecido foi encontrado."
            )
        await refresh_hierarchy_panel(get_bot(interaction), actor.guild)
        await interaction.edit_original_response(
            content=(
                f"✅ Importação concluída: **{created}** patentes criadas e "
                f"**{updated}** atualizadas, na ordem real do Discord. "
                "Agrupadores (`Oficiais`, `Praças` e `Praças Graduados`) e funções "
                "(`Alto Comando` e `Xenon`) não foram tratados como patentes; "
                "nenhum registro histórico foi apagado."
            ),
            embed=await build_ranks_embed(get_bot(interaction), actor.guild),
            view=self,
        )

    @discord.ui.button(label="Sincronização", emoji="🔗", style=discord.ButtonStyle.secondary)
    async def sync_rules(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_settings_admin(interaction)
        bot = get_bot(interaction)
        await interaction.response.send_modal(
            RankSyncRulesModal(
                enforce_nickname=bool(
                    await bot.services.settings.get(actor.guild.id, "enforce_member_nickname", True)
                ),
                auto_remove=bool(
                    await bot.services.settings.get(
                        actor.guild.id, "auto_remove_old_rank_roles", False
                    )
                ),
                missing_policy=str(
                    await bot.services.settings.get(
                        actor.guild.id, "missing_rank_role_policy", "KEEP_LAST"
                    )
                ),
            )
        )


class RankSyncRulesModal(AdminModal, title="Sincronização de patentes"):
    enforce_nickname = discord.ui.TextInput(label="Impor apelido oficial? (sim/não)", max_length=3)
    auto_remove = discord.ui.TextInput(label="Remover patentes antigas? (sim/não)", max_length=3)
    missing_policy = discord.ui.TextInput(
        label="Sem cargo: KEEP_LAST ou MARK_UNSYNCED", max_length=13
    )

    def __init__(self, *, enforce_nickname: bool, auto_remove: bool, missing_policy: str) -> None:
        super().__init__()
        self.enforce_nickname.default = "sim" if enforce_nickname else "não"
        self.auto_remove.default = "sim" if auto_remove else "não"
        self.missing_policy.default = missing_policy.upper()

    @staticmethod
    def _boolean(value: str) -> bool:
        normalized = (
            unicodedata.normalize("NFKD", value.strip().lower()).encode("ascii", "ignore").decode()
        )
        if normalized in {"sim", "s", "true", "1"}:
            return True
        if normalized in {"nao", "n", "false", "0"}:
            return False
        raise ValidationError("Use sim ou não nas opções de sincronização.")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = await require_settings_admin(interaction)
        policy = str(self.missing_policy).strip().upper()
        if policy not in {"KEEP_LAST", "MARK_UNSYNCED"}:
            raise ValidationError("A política deve ser KEEP_LAST ou MARK_UNSYNCED.")
        bot = get_bot(interaction)
        before = {
            "enforce_member_nickname": await bot.services.settings.get(
                actor.guild.id, "enforce_member_nickname", True
            ),
            "auto_remove_old_rank_roles": await bot.services.settings.get(
                actor.guild.id, "auto_remove_old_rank_roles", False
            ),
            "missing_rank_role_policy": await bot.services.settings.get(
                actor.guild.id, "missing_rank_role_policy", "KEEP_LAST"
            ),
        }
        after = {
            "enforce_member_nickname": self._boolean(str(self.enforce_nickname)),
            "auto_remove_old_rank_roles": self._boolean(str(self.auto_remove)),
            "missing_rank_role_policy": policy,
        }
        async with bot.services.database.transaction() as connection:
            for key, value in after.items():
                await bot.services.settings.set(actor.guild.id, key, value, actor.id, connection)
            await bot.services.audit.record(
                actor.guild.id,
                "RANK_SYNC_RULES_CHANGED",
                actor_id=actor.id,
                before=before,
                after=after,
                connection=connection,
            )
        await interaction.followup.send(
            "✅ Políticas de sincronização de patentes atualizadas.", ephemeral=True
        )


class RulesModal(AdminModal, title="Regras operacionais"):
    grace = discord.ui.TextInput(label="Tolerância fora da call (segundos)", max_length=3)
    minimum_patrol = discord.ui.TextInput(label="Patrulha mínima (5 a 120 min)", max_length=3)
    goal = discord.ui.TextInput(label="Meta semanal (minutos)", max_length=5)
    timezone_name = discord.ui.TextInput(label="Timezone IANA", max_length=60)

    def __init__(self, *, grace: int, minimum_patrol: int, goal: int, timezone_name: str) -> None:
        super().__init__()
        self.grace.default = str(grace)
        self.minimum_patrol.default = str(minimum_patrol)
        self.goal.default = str(goal)
        self.timezone_name.default = str(timezone_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = await require_settings_admin(interaction)
        if not str(self.grace).isdigit() or not 0 <= int(str(self.grace)) <= 600:
            raise ValidationError("A tolerância deve ficar entre 0 e 600 segundos.")
        if not str(self.goal).isdigit() or int(str(self.goal)) <= 0:
            raise ValidationError("A meta semanal deve ser um número positivo.")
        minimum_patrol = validate_minimum_patrol_minutes(str(self.minimum_patrol))
        timezone_name = str(self.timezone_name).strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValidationError("Timezone IANA inválido.") from exc
        bot = get_bot(interaction)
        before = {
            "grace_period_seconds": await bot.services.settings.get(
                actor.guild.id, "grace_period_seconds"
            ),
            "weekly_goal_minutes": await bot.services.settings.get(
                actor.guild.id, "weekly_goal_minutes"
            ),
            "minimum_patrol_minutes": await bot.services.settings.get(
                actor.guild.id, "minimum_patrol_minutes", 15
            ),
            "timezone": await bot.services.settings.get(actor.guild.id, "timezone"),
        }
        after = {
            "grace_period_seconds": int(str(self.grace)),
            "weekly_goal_minutes": int(str(self.goal)),
            "minimum_patrol_minutes": minimum_patrol,
            "timezone": timezone_name,
        }
        async with bot.services.database.transaction() as connection:
            for key, value in after.items():
                await bot.services.settings.set(actor.guild.id, key, value, actor.id, connection)
            await bot.services.audit.record(
                actor.guild.id,
                "RULES_CHANGED",
                actor_id=actor.id,
                before=before,
                after=after,
                connection=connection,
            )
        await interaction.followup.send("✅ Regras operacionais atualizadas.", ephemeral=True)


class PanelsConfigurationView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=600)

    async def choose_channel(self, interaction: discord.Interaction, panel_type: str) -> None:
        if not interaction.guild:
            raise ValidationError("Este painel só pode ser usado dentro do servidor.")
        choices = channel_choices_for_guild(interaction.guild)
        panel_labels = {
            "POINT": "Publicar painel de ponto",
            "MEMBER": "Publicar painel de cadastro",
            "SERVICE": "Publicar painel de efetivo",
            "HIERARCHY": "Publicar painel de hierarquia",
            "PERSONNEL_ADMIN": "Publicar central administrativa",
            "REQUESTS": "Publicar central de solicitações",
            "CAREER": "Publicar painel de carreira",
            "DISCIPLINE": "Publicar painel de disciplina",
            "ADV": "Publicar painel global de ADVs",
            "TRAINING": "Publicar painel de treinamentos",
            "COURSE_CATALOG": "Publicar catálogo de cursos",
            "ACTIVITY": "Publicar painel de atividade semanal",
            "RANKING": "Publicar painel de ranking",
            "RECRUITMENT": "Publicar painel de recrutamento",
            "TICKET": "Publicar painel de atendimento",
        }
        view = ChannelBrowserView(
            action="PANEL",
            action_key=panel_type,
            label=panel_labels[panel_type],
            choices=choices,
            selected_id=None,
        )
        await interaction.response.send_message(
            embed=view.embed(get_bot(interaction)),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Ponto", emoji="⏱️", style=discord.ButtonStyle.primary)
    async def point(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "POINT")

    @discord.ui.button(label="Cadastro", emoji="📝", style=discord.ButtonStyle.primary)
    async def member(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "MEMBER")

    @discord.ui.button(label="Efetivo", emoji="👥", style=discord.ButtonStyle.secondary)
    async def service(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "SERVICE")

    @discord.ui.button(label="Hierarquia", emoji="🎖️", style=discord.ButtonStyle.secondary)
    async def hierarchy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "HIERARCHY")

    @discord.ui.button(label="Administração", emoji="🛡️", style=discord.ButtonStyle.danger)
    async def personnel_admin(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "PERSONNEL_ADMIN")

    @discord.ui.button(label="Solicitações", emoji="📥", style=discord.ButtonStyle.primary)
    async def requests(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "REQUESTS")

    @discord.ui.button(label="Carreira", emoji="📈", style=discord.ButtonStyle.primary)
    async def career(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "CAREER")

    @discord.ui.button(label="Disciplina", emoji="⚖️", style=discord.ButtonStyle.danger)
    async def discipline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "DISCIPLINE")

    @discord.ui.button(label="ADVs ativas", emoji="📋", style=discord.ButtonStyle.danger)
    async def adv(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "ADV")

    @discord.ui.button(label="Treinamentos", emoji="🎓", style=discord.ButtonStyle.primary)
    async def training(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "TRAINING")

    @discord.ui.button(label="Catálogo de cursos", emoji="🎖️", style=discord.ButtonStyle.primary)
    async def course_catalog(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "COURSE_CATALOG")

    @discord.ui.button(label="Atividade", emoji="📊", style=discord.ButtonStyle.primary)
    async def activity(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "ACTIVITY")

    @discord.ui.button(label="Ranking", emoji="🏆", style=discord.ButtonStyle.success)
    async def ranking(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "RANKING")

    @discord.ui.button(label="Recrutamento", emoji="🧑‍💼", style=discord.ButtonStyle.primary)
    async def recruitment(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "RECRUITMENT")

    @discord.ui.button(label="Atendimento", emoji="🎫", style=discord.ButtonStyle.secondary)
    async def ticket(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.choose_channel(interaction, "TICKET")


async def publish_panel_to_channel(
    interaction: discord.Interaction, panel_type: str, channel: discord.TextChannel
) -> discord.Message:
    actor = await require_settings_admin(interaction)
    bot = get_bot(interaction)
    if panel_type == "POINT":
        cog = bot.get_cog("ShiftCommands")
        if not cog:
            raise ValidationError("O módulo de ponto não está carregado.")
        message = await cog.publish_or_refresh_point_panel(actor.guild, channel)
        setting_key = "point_panel_channel_id"
    elif panel_type == "MEMBER":
        cog = bot.get_cog("MemberCommands")
        if not cog:
            raise ValidationError("O módulo de cadastro não está carregado.")
        message = await cog.publish_or_refresh_panel(actor.guild, channel)
        setting_key = "registration_panel_channel_id"
    elif panel_type == "SERVICE":
        cog = bot.get_cog("ShiftCommands")
        if not cog:
            raise ValidationError("O módulo de efetivo não está carregado.")
        message = await channel.send(embed=await cog.build_service_embed(actor.guild.id))
        setting_key = "service_panel_channel_id"
    elif panel_type == "HIERARCHY":
        cog = bot.get_cog("HierarchyCommands")
        if not cog:
            raise ValidationError("O módulo de hierarquia não está carregado.")
        message = await cog.publish_or_refresh(actor.guild, channel)
        setting_key = "hierarchy_channel_id"
    elif panel_type == "REQUESTS":
        cog = bot.get_cog("RequestCommands")
        if not cog:
            raise ValidationError("O módulo de solicitações não está carregado.")
        message = await cog.publish_or_refresh(actor.guild, channel)
        setting_key = "requests_panel_channel_id"
    elif panel_type == "CAREER":
        cog = bot.get_cog("CareerCommands")
        if not cog:
            raise ValidationError("O módulo de carreira não está carregado.")
        message = await cog.publish_or_refresh(actor.guild, channel)
        setting_key = "career_panel_channel_id"
    elif panel_type in {"DISCIPLINE", "ADV"}:
        cog = bot.get_cog("DisciplineCommands")
        if not cog:
            raise ValidationError("O módulo disciplinar não está carregado.")
        if panel_type == "ADV":
            message = await cog.publish_adv_dashboard(actor.guild, channel)
            setting_key = "discipline_adv_channel_id"
        else:
            message = await cog.publish_or_refresh(actor.guild, channel)
            setting_key = "discipline_panel_channel_id"
    elif panel_type in {"TRAINING", "COURSE_CATALOG"}:
        cog = bot.get_cog("TrainingCommands")
        if not cog:
            raise ValidationError("O módulo de treinamentos não está carregado.")
        if panel_type == "COURSE_CATALOG":
            message = await cog.publish_course_catalog(actor.guild, channel)
            setting_key = "course_catalog_channel_id"
        else:
            message = await cog.publish_or_refresh(actor.guild, channel)
            setting_key = "training_panel_channel_id"
    elif panel_type == "ACTIVITY":
        cog = bot.get_cog("ActivityCommands")
        if not cog:
            raise ValidationError("O módulo de atividade não está carregado.")
        message = await cog.publish_or_refresh(actor.guild, channel)
        setting_key = "activity_panel_channel_id"
    elif panel_type in {"RECRUITMENT", "TICKET"}:
        cog = bot.get_cog("TicketCommands")
        if not cog:
            raise ValidationError("O módulo de atendimento não está carregado.")
        message = await cog.publish_or_refresh(actor.guild, channel, panel_type)
        setting_key = {
            "RECRUITMENT": "recruitment_panel_channel_id",
            "TICKET": "ticket_panel_channel_id",
        }[panel_type]
    else:
        cog = bot.get_cog("PersonnelCommands")
        if not cog:
            raise ValidationError("O módulo administrativo não está carregado.")
        message = await cog.publish_or_refresh(actor.guild, channel, panel_type)
        setting_key = {
            "PERSONNEL_ADMIN": "personnel_admin_channel_id",
            "RANKING": "ranking_panel_channel_id",
        }[panel_type]

    async with bot.services.database.transaction() as connection:
        await connection.execute(
            """
            INSERT INTO panels(guild_id, panel_type, channel_id, message_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, panel_type) DO UPDATE SET
                channel_id=excluded.channel_id, message_id=excluded.message_id,
                updated_at=excluded.updated_at
            """,
            (actor.guild.id, panel_type, channel.id, message.id, utc_now_ms()),
        )
        await bot.services.settings.set(
            actor.guild.id, setting_key, channel.id, actor.id, connection
        )
        await bot.services.audit.record(
            actor.guild.id,
            "PANEL_PUBLISHED",
            actor_id=actor.id,
            target_id=message.id,
            after={
                "panel_type": panel_type,
                "channel_id": channel.id,
                "message_id": message.id,
            },
            connection=connection,
        )
    return message


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
