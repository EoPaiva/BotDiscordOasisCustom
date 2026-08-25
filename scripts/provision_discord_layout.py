from __future__ import annotations

import argparse
import json
import traceback
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import discord

from choque.config import AppConfig
from choque.database import Database
from choque.embeds import branded_embed
from choque.models import RbacProfile
from choque.settings import SettingsService
from choque.time_utils import utc_now_ms
from cogs.activity_commands import ActivityPanelView
from cogs.career_commands import CareerPanelView, build_career_landing_embed
from cogs.discipline_commands import DisciplinePanelView, build_discipline_landing_embed
from cogs.member_commands import RegistrationPanelView, build_registration_panel_embed
from cogs.request_commands import RequestPanelView, build_request_landing_embed
from cogs.shift_commands import PointPanelView, build_point_panel_embed
from cogs.ticket_commands import RecruitmentAdminPanelView, RecruitmentPanelView, TicketPanelView
from cogs.training_commands import TrainingPanelView, build_training_landing_embed

REASON = "Remodelacao estrutural CHOQUE - BGR"

CATEGORY_IDS = {
    "info": 1161833335618801687,
    "member": 1540546763939782676,
    "operations": 1146622065647046776,
    "training": 1162114516318949529,
    "recruitment": 1162263284108501092,
    "admin": 1540540581728485597,
    "audit": 1146622066527850585,
    "community": 1146622065399566420,
}

CATEGORY_NAMES = {
    "info": "01・📚 INFORMAÇÕES",
    "member": "02・👤 CENTRAL DO MEMBRO",
    "operations": "03・🚔 OPERAÇÕES",
    "training": "04・🎓 FORMAÇÃO",
    "recruitment": "05・📝 RECRUTAMENTO",
    "admin": "06・🛡️ ADMINISTRAÇÃO",
    "audit": "07・📜 AUDITORIA",
    "community": "08・💬 COMUNIDADE",
}

ROLE_IDS = {
    "owner_1": 1186577688987709470,
    "owner_2": 1202143082968252466,
    "commander_general": 1146622063004635306,
    "commander": 1146622062987841555,
    "sub_commander": 1146622062987841554,
    "high_command": 1146632112787693670,
    "colonel": 1146622062987841546,
    "lieutenant_colonel": 1150152395943325808,
    "major": 1146622062975270971,
    "captain": 1146622062975270970,
    "officers": 1161734642349637674,
    "graduates": 1146622062966886417,
    "member": 1146622062924943461,
    "corrections": 1162996505678991360,
    "recruiter": 1146622062924943470,
    "recruiter_assistant": 1147302660442161243,
    "instructor": 1162975230453616740,
}

COMMAND_ROLE_KEYS = (
    "owner_1",
    "owner_2",
    "commander_general",
    "commander",
    "sub_commander",
    "high_command",
    "colonel",
    "lieutenant_colonel",
    "major",
    "captain",
)

CHANNEL_LAYOUT: dict[int, tuple[str, str]] = {
    # Informacoes e doutrina
    1161742911105421393: ("info", "📢│avisos"),
    1176911554629861396: ("info", "📣│anúncios-bgr"),
    1146622064736882707: ("info", "📘│regras-gerais"),
    1164287787898503228: ("info", "📕│regulamento-interno"),
    1146622065110171661: ("info", "📋│procedimentos-patrulha"),
    1146622065110171664: ("info", "👮│fardamentos"),
    1146622065110171665: ("info", "🚓│viaturas"),
    1146622065110171667: ("info", "⌨️│binds-operacionais"),
    1161810176718930071: ("info", "📻│códigos-q"),
    1165939530474475530: ("info", "🎖️│condecorações"),
    1146622065110171666: ("info", "📈│hierarquia"),
    # Operacoes
    1161829541292028075: ("operations", "🚔│aguardando-patrulha"),
    1146622065647046780: ("operations", "🚔│patrulha-alfa"),
    1146622065647046781: ("operations", "🚔│patrulha-bravo"),
    1146622065647046782: ("operations", "🚔│patrulha-charlie"),
    1146622065647046784: ("operations", "🚔│patrulha-delta"),
    1164957395370385519: ("operations", "🚙│comboio"),
    1161833828793450566: ("operations", "🏍️│rocam-01"),
    1161848955764748359: ("operations", "🏍️│rocam-02"),
    1161835749952471130: ("operations", "🚁│águia-01"),
    1161848786637828107: ("operations", "🚁│águia-02"),
    1146622065852563591: ("operations", "🚧│blitz-lv"),
    1161828293062967340: ("operations", "🚧│blitz-ls"),
    1164363506083172413: ("operations", "🟢│disponível-para-patrulha"),
    # Formacao
    1162240695629795348: ("training", "🎓│aguardando-formação"),
    1162240256913965086: ("training", "📚│sala-de-curso-01"),
    1162934172554367097: ("training", "📚│sala-de-curso-02"),
    1168335359990566912: ("training", "💬│chat-de-formação"),
    1162114694581059584: ("training", "📖│cursos"),
    1166622479196901438: ("training", "🧑‍🏫│instrutores"),
    1165345443786543144: ("training", "✅│aprovados-em-cursos"),
    1165348711895932948: ("training", "❌│reprovados-em-cursos"),
    1164983916902490182: ("training", "🎒│formados"),
    # Recrutamento e transferencias
    1161840087483564092: ("recruitment", "📋│requisitos"),
    1162263355885629540: ("recruitment", "📝│recrutamento"),
    1146622065852563593: ("recruitment", "🎫│atendimento"),
    1166175384119812166: ("recruitment", "✅│aprovados-entrevista"),
    1166176079724154910: ("recruitment", "❌│reprovados-entrevista"),
    1166861438728548432: ("recruitment", "🔄│transferências"),
    # Administracao
    1540540583704141915: ("admin", "🛡️│central-administrativa"),
    1166681424154333277: ("admin", "⚙️│configurações-do-bot"),
    # Central do membro
    1540540585289715722: ("member", "📥│solicitações"),
    1540540587307040810: ("member", "🏆│ranking-de-horas"),
    # Auditoria
    1146622066817253458: ("audit", "📜│auditoria-do-bot"),
    1146622066817253459: ("audit", "🛡️│moderação-discord"),
    1146622066817253460: ("audit", "🚪│entradas"),
    1163604719747473438: ("audit", "🚪│saídas"),
    # Comunidade
    1161830033858515035: ("community", "💬│chat-choque"),
    1201450207917899786: ("community", "💬│chat-geral"),
    1153774907088441354: ("community", "💡│sugestões"),
    1161829510627459172: ("community", "📷│mídia-e-instagram"),
    # Histórico preservado do arquivo legado.
    1147292121234161783: ("audit", "📜│histórico-de-membros"),
}

EMPTY_CHANNELS_TO_DELETE = {
    1164320297688760413,  # convites
    1147294547844534304,  # membros vazio
    1146622065399566416,  # advertencias vazio
    1202156270761541702,  # upamentos vazio
    1147293690084216882,  # alertas antigos do ponto
}

LEGACY_CATEGORIES_TO_DELETE = {
    1146622065110171662,  # CHOQUE
    1147293582391255050,  # BATE PONTO
    1146622065852563592,  # TICKET
    1161839881409003570,  # REQUERIMENTOS
}

DUPLICATE_CATEGORIES_TO_DELETE = {
    1540550069298929664,  # Central do Membro criada durante execucao interrompida
}

AUTHORIZED_VOICE_IDS = {
    1146622065647046780,
    1146622065647046781,
    1146622065647046782,
    1146622065647046784,
    1164957395370385519,
    1161833828793450566,
    1161848955764748359,
    1161835749952471130,
    1161848786637828107,
    1146622065852563591,
    1161828293062967340,
}

MEMBER_ONLY_INFO_IDS = {
    1164287787898503228,
    1146622065110171661,
    1146622065110171664,
    1146622065110171665,
    1146622065110171667,
    1161810176718930071,
    1165939530474475530,
}

RECRUITMENT_STAFF_IDS = {
    1166175384119812166,
    1166176079724154910,
    1166861438728548432,
}

CHANNEL_ORDER = {
    "info": (
        "📢│avisos",
        "📣│anúncios-bgr",
        "📘│regras-gerais",
        "📕│regulamento-interno",
        "📋│procedimentos-patrulha",
        "👮│fardamentos",
        "🚓│viaturas",
        "⌨️│binds-operacionais",
        "📻│códigos-q",
        "📈│hierarquia",
        "🎖️│condecorações",
    ),
    "member": (
        "🏠│central-do-membro",
        "📝│cadastro",
        "⏱️│controle-de-serviço",
        "👥│efetivo-em-serviço",
        "📥│solicitações",
        "📈│carreira",
        "⚖️│disciplina",
        "📊│atividade-semanal",
        "🏆│ranking-de-horas",
    ),
    "operations": (
        "🟢│disponível-para-patrulha",
        "🚔│aguardando-patrulha",
        "🚔│patrulha-alfa",
        "🚔│patrulha-bravo",
        "🚔│patrulha-charlie",
        "🚔│patrulha-delta",
        "🚙│comboio",
        "🏍️│rocam-01",
        "🏍️│rocam-02",
        "🚁│águia-01",
        "🚁│águia-02",
        "🚧│blitz-lv",
        "🚧│blitz-ls",
    ),
    "training": (
        "🎯│treinamentos",
        "📖│cursos",
        "💬│chat-de-formação",
        "🧑‍🏫│instrutores",
        "✅│aprovados-em-cursos",
        "❌│reprovados-em-cursos",
        "🎒│formados",
        "🎓│aguardando-formação",
        "📚│sala-de-curso-01",
        "📚│sala-de-curso-02",
    ),
    "recruitment": (
        "📋│requisitos",
        "📝│recrutamento",
        "🎫│atendimento",
        "📥│fila-de-candidatos",
        "🔄│transferências",
        "✅│aprovados-entrevista",
        "❌│reprovados-entrevista",
    ),
    "admin": ("🛡️│central-administrativa", "⚙️│configurações-do-bot"),
    "audit": (
        "📜│auditoria-do-bot",
        "🛡️│moderação-discord",
        "🚪│entradas",
        "🚪│saídas",
    ),
    "community": (
        "💬│chat-geral",
        "💬│chat-choque",
        "💡│sugestões",
        "📷│mídia-e-instagram",
    ),
}

MONOSPACE_TRANSLATION = str.maketrans(
    {
        **{chr(ord("A") + index): chr(0x1D670 + index) for index in range(26)},
        **{chr(ord("a") + index): chr(0x1D68A + index) for index in range(26)},
        **{chr(ord("0") + index): chr(0x1D7F6 + index) for index in range(10)},
    }
)

SANS_SERIF_ITALIC_TRANSLATION = str.maketrans(
    {
        **{chr(ord("A") + index): chr(0x1D608 + index) for index in range(26)},
        **{chr(ord("a") + index): chr(0x1D622 + index) for index in range(26)},
        **{chr(ord("0") + index): chr(0x1D7E2 + index) for index in range(10)},
    }
)


def elegant_monospace(value: str) -> str:
    """Converte texto para o alfabeto monoespacado preservando emojis e separadores."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_accents.translate(MONOSPACE_TRANSLATION)


def sans_serif_italic(value: str) -> str:
    """Converte nomes de canais para Sans-Serif Italico."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_accents.translate(SANS_SERIF_ITALIC_TRANSLATION)


def permission_snapshot(channel: discord.abc.GuildChannel) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for target, overwrite in channel.overwrites.items():
        allow, deny = overwrite.pair()
        result.append(
            {
                "target_id": target.id,
                "target_name": getattr(target, "name", None),
                "target_type": type(target).__name__,
                "allow": allow.value,
                "deny": deny.value,
            }
        )
    return result


class ProvisionClient(discord.Client):
    def __init__(self, config: AppConfig, *, apply: bool) -> None:
        super().__init__(intents=discord.Intents.default())
        self.config = config
        self.apply = apply
        self._ran = False
        self.database = Database(config.database_path, config.legacy_database_path)
        self.settings = SettingsService(self.database)
        self.categories: dict[str, discord.CategoryChannel] = {}
        self.created_channels: dict[str, discord.TextChannel] = {}
        self.roles: dict[str, discord.Role] = {}

    async def on_ready(self) -> None:
        if self._ran:
            return
        self._ran = True
        try:
            guild = self.get_guild(self.config.default_guild_id or 0)
            if guild is None:
                raise RuntimeError("Guild configurada nao foi encontrada pelo bot.")
            await self.database.open()
            await self.backup(guild)
            if not self.apply:
                print("DRY_RUN_OK: inventario salvo; nenhuma alteracao aplicada.")
                return
            await self.resolve_roles(guild)
            await self.ensure_status_roles(guild)
            await self.ensure_categories(guild)
            await self.move_channels(guild)
            await self.ensure_new_channels(guild)
            await self.order_channels()
            await self.apply_channel_permissions(guild)
            await self.delete_empty_legacy_channels(guild)
            await self.delete_empty_legacy_categories(guild)
            await self.configure_database(guild)
            await self.publish_layout_messages(guild)
            print("PROVISION_OK")
        except Exception:
            traceback.print_exc()
        finally:
            await self.database.close()
            await self.close()

    async def backup(self, guild: discord.Guild) -> None:
        destination = Path("data/server_layout_backups")
        destination.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = destination / f"discord_layout_{guild.id}_{timestamp}.json"
        payload = {
            "captured_at": datetime.now(UTC).isoformat(),
            "guild": {"id": guild.id, "name": guild.name, "owner_id": guild.owner_id},
            "roles": [
                {
                    "id": role.id,
                    "name": role.name,
                    "position": role.position,
                    "permissions": role.permissions.value,
                    "managed": role.managed,
                }
                for role in sorted(guild.roles, key=lambda item: item.position, reverse=True)
            ],
            "channels": [
                {
                    "id": channel.id,
                    "name": channel.name,
                    "type": str(channel.type),
                    "position": channel.position,
                    "category_id": channel.category_id,
                    "overwrites": permission_snapshot(channel),
                }
                for channel in guild.channels
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"BACKUP={path.resolve()}")

    async def resolve_roles(self, guild: discord.Guild) -> None:
        missing: list[str] = []
        for key, role_id in ROLE_IDS.items():
            role = guild.get_role(role_id)
            if role is None:
                missing.append(f"{key}:{role_id}")
            else:
                self.roles[key] = role
        if missing:
            raise RuntimeError(f"Cargos obrigatorios ausentes: {', '.join(missing)}")

    async def ensure_status_roles(self, guild: discord.Guild) -> None:
        specifications = {
            "service": ("🟢 Em Serviço", discord.Colour.green()),
            "away": ("🟠 Ausente", discord.Colour.orange()),
            "reserve": ("🟡 Reserva", discord.Colour.gold()),
            "suspended": ("🔴 Suspenso", discord.Colour.red()),
        }
        for key, (name, colour) in specifications.items():
            role = discord.utils.get(guild.roles, name=name)
            if role is None:
                role = await guild.create_role(
                    name=name,
                    colour=colour,
                    permissions=discord.Permissions.none(),
                    reason=REASON,
                )
            self.roles[key] = role

    def command_roles(self) -> list[discord.Role]:
        return [self.roles[key] for key in COMMAND_ROLE_KEYS]

    def public_readonly_overwrites(self, guild: discord.Guild) -> dict[Any, Any]:
        overwrites: dict[Any, Any] = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                add_reactions=False,
                use_application_commands=False,
            )
        }
        for role in self.command_roles():
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=True
            )
        return overwrites

    def member_overwrites(self, guild: discord.Guild) -> dict[Any, Any]:
        overwrites: dict[Any, Any] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.roles["member"]: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                connect=True,
                speak=True,
            ),
        }
        for role in self.command_roles():
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                connect=True,
                speak=True,
                manage_messages=True,
            )
        return overwrites

    def private_overwrites(
        self, guild: discord.Guild, extra_roles: tuple[str, ...] = ()
    ) -> dict[Any, Any]:
        overwrites: dict[Any, Any] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False)
        }
        allowed = self.command_roles() + [self.roles[key] for key in extra_roles]
        for role in allowed:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                connect=True,
                speak=True,
                manage_messages=True,
            )
        return overwrites

    async def ensure_categories(self, guild: discord.Guild) -> None:
        overwrite_factories = {
            "info": lambda: self.public_readonly_overwrites(guild),
            "member": lambda: self.public_readonly_overwrites(guild),
            "operations": lambda: self.member_overwrites(guild),
            "training": lambda: self.member_overwrites(guild),
            "recruitment": lambda: self.public_readonly_overwrites(guild),
            "admin": lambda: self.private_overwrites(guild),
            "audit": lambda: self.private_overwrites(guild, ("corrections",)),
            "community": lambda: self.public_readonly_overwrites(guild),
        }
        for index, key in enumerate(CATEGORY_NAMES):
            desired_name = elegant_monospace(CATEGORY_NAMES[key])
            category = guild.get_channel(CATEGORY_IDS[key]) if key in CATEGORY_IDS else None
            if not isinstance(category, discord.CategoryChannel):
                category = discord.utils.get(guild.categories, name=desired_name)
            if not isinstance(category, discord.CategoryChannel):
                category = discord.utils.get(guild.categories, name=CATEGORY_NAMES[key])
            if category is None:
                category = await guild.create_category(
                    desired_name,
                    overwrites=overwrite_factories[key](),
                    reason=REASON,
                )
            else:
                await category.edit(
                    name=desired_name,
                    overwrites=overwrite_factories[key](),
                    reason=REASON,
                )
            self.categories[key] = category
            await category.edit(position=index, reason=REASON)

    async def move_channels(self, guild: discord.Guild) -> None:
        for channel_id, (category_key, name) in CHANNEL_LAYOUT.items():
            channel = guild.get_channel(channel_id)
            if channel is None:
                continue
            await channel.edit(
                name=sans_serif_italic(name),
                category=self.categories[category_key],
                sync_permissions=True,
                reason=REASON,
            )

    async def ensure_text_channel(
        self, guild: discord.Guild, category_key: str, name: str
    ) -> discord.TextChannel:
        category = self.categories[category_key]
        desired_name = sans_serif_italic(name)
        channel = discord.utils.get(category.text_channels, name=desired_name)
        if channel is None:
            channel = discord.utils.get(category.text_channels, name=name)
        if channel is None:
            channel = discord.utils.get(category.text_channels, name=elegant_monospace(name))
        if channel is None:
            channel = await guild.create_text_channel(
                desired_name,
                category=category,
                overwrites=category.overwrites,
                reason=REASON,
            )
        elif channel.name != desired_name:
            channel = await channel.edit(name=desired_name, reason=REASON)
        self.created_channels[name] = channel
        return channel

    async def ensure_new_channels(self, guild: discord.Guild) -> None:
        await self.ensure_text_channel(guild, "member", "🏠│central-do-membro")
        await self.ensure_text_channel(guild, "member", "📝│cadastro")
        await self.ensure_text_channel(guild, "member", "⏱️│controle-de-serviço")
        await self.ensure_text_channel(guild, "member", "👥│efetivo-em-serviço")
        await self.ensure_text_channel(guild, "member", "📈│carreira")
        await self.ensure_text_channel(guild, "member", "⚖️│disciplina")
        await self.ensure_text_channel(guild, "member", "📊│atividade-semanal")
        await self.ensure_text_channel(guild, "training", "🎯│treinamentos")
        await self.ensure_text_channel(guild, "recruitment", "📥│fila-de-candidatos")

    async def order_channels(self) -> None:
        for category_key, names in CHANNEL_ORDER.items():
            category = self.categories[category_key]
            for position, name in enumerate(names):
                channel = discord.utils.get(category.channels, name=sans_serif_italic(name))
                if channel is not None:
                    await channel.edit(position=position, reason=REASON)

    def text_channel(self, name: str) -> discord.TextChannel:
        desired_name = sans_serif_italic(name)
        for category in self.categories.values():
            channel = discord.utils.get(category.text_channels, name=desired_name)
            if channel is not None:
                return channel
        raise RuntimeError(f"Canal obrigatorio nao encontrado: {desired_name}")

    async def set_member_only(
        self, guild: discord.Guild, channel: discord.abc.GuildChannel
    ) -> None:
        await channel.set_permissions(guild.default_role, view_channel=False, reason=REASON)
        await channel.set_permissions(
            self.roles["member"],
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            reason=REASON,
        )

    async def apply_channel_permissions(self, guild: discord.Guild) -> None:
        for channel_id in MEMBER_ONLY_INFO_IDS:
            channel = guild.get_channel(channel_id)
            if channel:
                await self.set_member_only(guild, channel)

        for name in (
            "⏱️│controle-de-serviço",
            "👥│efetivo-em-serviço",
            "📥│solicitações",
            "📈│carreira",
            "⚖️│disciplina",
            "📊│atividade-semanal",
            "🏆│ranking-de-horas",
        ):
            await self.set_member_only(guild, self.text_channel(name))

        chat_general = guild.get_channel(1201450207917899786)
        if chat_general:
            await chat_general.set_permissions(
                guild.default_role,
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                add_reactions=True,
                reason=REASON,
            )
        chat_choque = guild.get_channel(1161830033858515035)
        if chat_choque:
            await chat_choque.set_permissions(guild.default_role, view_channel=False, reason=REASON)
            await chat_choque.set_permissions(
                self.roles["member"],
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                add_reactions=True,
                reason=REASON,
            )
        suggestions = guild.get_channel(1153774907088441354)
        if suggestions:
            await suggestions.set_permissions(
                guild.default_role,
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                add_reactions=True,
                reason=REASON,
            )
        media = guild.get_channel(1161829510627459172)
        if media:
            await media.set_permissions(
                guild.default_role,
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                add_reactions=True,
                reason=REASON,
            )

        course_chat = guild.get_channel(1168335359990566912)
        if course_chat:
            await course_chat.set_permissions(
                self.roles["member"],
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                reason=REASON,
            )
        instructors = guild.get_channel(1166622479196901438)
        if instructors:
            await instructors.set_permissions(guild.default_role, view_channel=False, reason=REASON)
            await instructors.set_permissions(
                self.roles["instructor"],
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                reason=REASON,
            )

        recruiter_roles = (
            self.roles["recruiter"],
            self.roles["recruiter_assistant"],
        )
        staff_ids = set(RECRUITMENT_STAFF_IDS)
        queue = self.text_channel("📥│fila-de-candidatos")
        if queue:
            staff_ids.add(queue.id)
        for channel_id in staff_ids:
            channel = guild.get_channel(channel_id)
            if channel is None:
                continue
            await channel.set_permissions(guild.default_role, view_channel=False, reason=REASON)
            for role in recruiter_roles + tuple(self.command_roles()):
                await channel.set_permissions(
                    role,
                    view_channel=True,
                    read_message_history=True,
                    send_messages=True,
                    reason=REASON,
                )

    async def delete_empty_legacy_channels(self, guild: discord.Guild) -> None:
        for channel_id in EMPTY_CHANNELS_TO_DELETE:
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            latest = [message async for message in channel.history(limit=1)]
            if not latest:
                await channel.delete(reason=f"{REASON} - canal vazio e obsoleto")

    async def delete_empty_legacy_categories(self, guild: discord.Guild) -> None:
        for category_id in DUPLICATE_CATEGORIES_TO_DELETE:
            category = guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                continue
            for channel in list(category.channels):
                if not isinstance(channel, discord.TextChannel):
                    raise RuntimeError(
                        f"Duplicata inesperada nao textual em {category.name}: {channel.name}"
                    )
                latest = [message async for message in channel.history(limit=1)]
                if latest:
                    raise RuntimeError(
                        f"Canal duplicado possui mensagens e nao sera removido: {channel.name}"
                    )
                await channel.delete(reason=f"{REASON} - duplicata vazia")
            await category.delete(reason=f"{REASON} - categoria duplicada vazia")
        for category_id in LEGACY_CATEGORIES_TO_DELETE:
            category = guild.get_channel(category_id)
            if isinstance(category, discord.CategoryChannel) and not category.channels:
                await category.delete(reason=f"{REASON} - categoria substituida")

    async def configure_database(self, guild: discord.Guild) -> None:
        actor_id = self.user.id if self.user else None
        setting_values = {
            "audit_channel_id": self.text_channel("📜│auditoria-do-bot").id,
            "registration_approval_channel_id": self.text_channel("🛡️│central-administrativa").id,
            "registration_history_channel_id": self.text_channel("📜│histórico-de-membros").id,
            "registration_panel_channel_id": self.text_channel("📝│cadastro").id,
            "point_panel_channel_id": self.text_channel("⏱️│controle-de-serviço").id,
            "service_panel_channel_id": self.text_channel("👥│efetivo-em-serviço").id,
            "hierarchy_channel_id": self.text_channel("📈│hierarquia").id,
            "config_panel_channel_id": self.text_channel("⚙️│configurações-do-bot").id,
            "personnel_admin_channel_id": self.text_channel("🛡️│central-administrativa").id,
            "absence_panel_channel_id": self.text_channel("📥│solicitações").id,
            "requests_panel_channel_id": self.text_channel("📥│solicitações").id,
            "career_panel_channel_id": self.text_channel("📈│carreira").id,
            "discipline_panel_channel_id": self.text_channel("⚖️│disciplina").id,
            "training_panel_channel_id": self.text_channel("🎯│treinamentos").id,
            "course_catalog_channel_id": self.text_channel("📖│cursos").id,
            "activity_panel_channel_id": self.text_channel("📊│atividade-semanal").id,
            "ranking_panel_channel_id": self.text_channel("🏆│ranking-de-horas").id,
            "recruitment_requirements_channel_id": self.text_channel("📋│requisitos").id,
            "recruitment_panel_channel_id": self.text_channel("📝│recrutamento").id,
            "ticket_panel_channel_id": self.text_channel("🎫│atendimento").id,
            "recruitment_queue_channel_id": self.text_channel("📥│fila-de-candidatos").id,
            "transfer_results_channel_id": self.text_channel("🔄│transferências").id,
            "recruitment_approved_channel_id": self.text_channel("✅│aprovados-entrevista").id,
            "recruitment_rejected_channel_id": self.text_channel("❌│reprovados-entrevista").id,
            "service_role_id": self.roles["service"].id,
            "member_role_id": self.roles["member"].id,
            "away_role_id": self.roles["away"].id,
            "reserve_role_id": self.roles["reserve"].id,
            "suspended_role_id": self.roles["suspended"].id,
            "timezone": "America/Sao_Paulo",
            "grace_period_seconds": 60,
            "weekly_goal_minutes": 360,
        }
        async with self.database.transaction() as connection:
            for key, value in setting_values.items():
                await self.settings.set(guild.id, key, value, actor_id, connection)
            await connection.execute(
                "DELETE FROM authorized_voice_channels WHERE guild_id=?", (guild.id,)
            )
            for channel_id in AUTHORIZED_VOICE_IDS:
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.VoiceChannel):
                    await connection.execute(
                        """
                        INSERT INTO authorized_voice_channels(
                            guild_id, channel_id, label, created_at, created_by
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (guild.id, channel.id, channel.name, utc_now_ms(), actor_id),
                    )
            await connection.execute("DELETE FROM rbac_bindings WHERE guild_id=?", (guild.id,))
            bindings = {
                "member": RbacProfile.MEMBER,
                "graduates": RbacProfile.GRADUATE,
                "officers": RbacProfile.GRADUATE,
                "instructor": RbacProfile.INSTRUCTOR,
                "recruiter": RbacProfile.INSTRUCTOR,
                "recruiter_assistant": RbacProfile.INSTRUCTOR,
                "high_command": RbacProfile.COMMAND,
                "commander": RbacProfile.COMMAND,
                "sub_commander": RbacProfile.COMMAND,
                "commander_general": RbacProfile.COMMAND,
                "colonel": RbacProfile.COMMAND,
                "lieutenant_colonel": RbacProfile.COMMAND,
                "major": RbacProfile.COMMAND,
                "captain": RbacProfile.COMMAND,
                "corrections": RbacProfile.COMMAND,
                "owner_1": RbacProfile.ADMIN,
                "owner_2": RbacProfile.ADMIN,
            }
            for role_key, profile in bindings.items():
                await connection.execute(
                    """
                    INSERT INTO rbac_bindings(guild_id, role_id, profile, created_at, created_by)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (guild.id, self.roles[role_key].id, profile.value, utc_now_ms(), actor_id),
                )

    async def upsert_panel_message(
        self,
        guild: discord.Guild,
        panel_type: str,
        channel: discord.TextChannel,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
    ) -> discord.Message:
        existing = await self.settings.get_panel(guild.id, panel_type)
        message: discord.Message | None = None
        if existing and int(existing["channel_id"]) == channel.id:
            try:
                message = await channel.fetch_message(int(existing["message_id"]))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                message = None
        if message:
            await message.edit(embed=embed, view=view)
        else:
            message = await channel.send(embed=embed, view=view)
        await self.settings.upsert_panel(guild.id, panel_type, channel.id, message.id)
        return message

    async def publish_layout_messages(self, guild: discord.Guild) -> None:
        registration = self.text_channel("📝│cadastro")
        point = self.text_channel("⏱️│controle-de-serviço")
        service = self.text_channel("👥│efetivo-em-serviço")
        requests = self.text_channel("📥│solicitações")
        career = self.text_channel("📈│carreira")
        discipline = self.text_channel("⚖️│disciplina")
        activity = self.text_channel("📊│atividade-semanal")

        await self.upsert_panel_message(
            guild,
            "MEMBER",
            registration,
            build_registration_panel_embed(self),
            RegistrationPanelView(),
        )
        await self.upsert_panel_message(
            guild,
            "POINT",
            point,
            build_point_panel_embed(self),
            PointPanelView(),
        )
        await self.upsert_panel_message(
            guild,
            "SERVICE",
            service,
            branded_embed(
                self.config.branding,
                title="CHOQUE - BGR • Efetivo em Serviço",
                description="Nenhum membro está em serviço no momento.",
            ),
        )
        request_panel = await self.settings.get_panel(guild.id, "REQUESTS")
        if not request_panel:
            legacy_panel = await self.settings.get_panel(guild.id, "ABSENCE")
            if legacy_panel and int(legacy_panel["channel_id"]) == requests.id:
                await self.settings.upsert_panel(
                    guild.id,
                    "REQUESTS",
                    requests.id,
                    int(legacy_panel["message_id"]),
                )
        await self.upsert_panel_message(
            guild,
            "REQUESTS",
            requests,
            build_request_landing_embed(self),
            RequestPanelView(),
        )
        await self.upsert_panel_message(
            guild,
            "CAREER",
            career,
            build_career_landing_embed(self),
            CareerPanelView(),
        )
        await self.upsert_panel_message(
            guild,
            "DISCIPLINE",
            discipline,
            build_discipline_landing_embed(self),
            DisciplinePanelView(),
        )
        await self.upsert_panel_message(
            guild,
            "ACTIVITY",
            activity,
            branded_embed(
                self.config.branding,
                title="📊 Atividade Semanal • CHOQUE - BGR",
                description=(
                    "Acompanhe sua meta, o quadro semanal e o histórico pelos botões abaixo. "
                    "Os indicadores não aplicam punições automaticamente."
                ),
            ),
            ActivityPanelView(),
        )

        central = self.text_channel("🏠│central-do-membro")
        navigation = discord.ui.View(timeout=None)
        links = (
            ("Cadastro", "📝", registration),
            ("Controle de serviço", "⏱️", point),
            ("Efetivo", "👥", service),
            ("Solicitações", "📥", requests),
            ("Carreira", "📈", career),
            ("Disciplina", "⚖️", discipline),
            ("Atividade", "📊", activity),
            ("Ranking", "🏆", self.text_channel("🏆│ranking-de-horas")),
            ("Treinamentos", "🎓", self.text_channel("🎯│treinamentos")),
        )
        for label, emoji, target in links:
            navigation.add_item(
                discord.ui.Button(
                    label=label,
                    emoji=emoji,
                    style=discord.ButtonStyle.link,
                    url=f"https://discord.com/channels/{guild.id}/{target.id}",
                )
            )
        await self.upsert_panel_message(
            guild,
            "MEMBER_CENTRAL",
            central,
            branded_embed(
                self.config.branding,
                title="CHOQUE - BGR • Central do Membro",
                description=(
                    "Acesse os serviços da corporação pelos botões abaixo. "
                    "Consultas e ações pessoais permanecem privadas."
                ),
            ),
            navigation,
        )

        training = self.text_channel("🎯│treinamentos")
        training_panel = await self.settings.get_panel(guild.id, "TRAINING")
        if not training_panel:
            legacy_panel = await self.settings.get_panel(guild.id, "TRAINING_LANDING")
            if legacy_panel and int(legacy_panel["channel_id"]) == training.id:
                await self.settings.upsert_panel(
                    guild.id,
                    "TRAINING",
                    training.id,
                    int(legacy_panel["message_id"]),
                )
        await self.upsert_panel_message(
            guild,
            "TRAINING",
            training,
            build_training_landing_embed(self),
            TrainingPanelView(),
        )

        recruitment = guild.get_channel(1162263355885629540)
        if isinstance(recruitment, discord.TextChannel):
            current_panel = await self.settings.get_panel(guild.id, "RECRUITMENT")
            if not current_panel:
                legacy_panel = await self.settings.get_panel(guild.id, "RECRUITMENT_LANDING")
                if legacy_panel and int(legacy_panel["channel_id"]) == recruitment.id:
                    await self.settings.upsert_panel(
                        guild.id, "RECRUITMENT", recruitment.id, int(legacy_panel["message_id"])
                    )
            await self.upsert_panel_message(
                guild,
                "RECRUITMENT",
                recruitment,
                branded_embed(
                    self.config.branding,
                    title="📝 Recrutamento • CHOQUE - BGR",
                    description=(
                        "Envie sua candidatura e acompanhe a análise pelos botões abaixo. "
                        "A aprovação encaminha o cadastro para a decisão final do Comando."
                    ),
                ),
                RecruitmentPanelView(),
            )

        ticket = guild.get_channel(1146622065852563593)
        if isinstance(ticket, discord.TextChannel):
            current_panel = await self.settings.get_panel(guild.id, "TICKET")
            if not current_panel:
                legacy_panel = await self.settings.get_panel(guild.id, "TICKET_LANDING")
                if legacy_panel and int(legacy_panel["channel_id"]) == ticket.id:
                    await self.settings.upsert_panel(
                        guild.id, "TICKET", ticket.id, int(legacy_panel["message_id"])
                    )
            await self.upsert_panel_message(
                guild,
                "TICKET",
                ticket,
                branded_embed(
                    self.config.branding,
                    title="🎫 Central de Atendimento • CHOQUE - BGR",
                    description=(
                        "Abra candidatura, transferência ou denúncia pelos botões abaixo. "
                        "Os dados e as respostas permanecem privados."
                    ),
                ),
                TicketPanelView(),
            )

        queue = self.text_channel("📥│fila-de-candidatos")
        await self.upsert_panel_message(
            guild,
            "RECRUITMENT_ADMIN",
            queue,
            branded_embed(
                self.config.branding,
                title="📥 Fila de Recrutamento e Atendimento",
                description="Nenhuma candidatura, transferência ou denúncia pendente.",
            ),
            RecruitmentAdminPanelView(),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provisiona o layout Discord CHOQUE - BGR")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica as alteracoes. Sem esta opcao apenas salva o inventario atual.",
    )
    return parser.parse_args()


def main() -> int:
    # A entrada pública permanece compatível, mas o layout oficial agora é a referência visual v2.
    from scripts.remodel_discord_layout import main as remodel_main

    return remodel_main()


if __name__ == "__main__":
    raise SystemExit(main())
