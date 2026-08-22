from __future__ import annotations

import argparse
import traceback
from dataclasses import dataclass
from typing import Any, Literal

import discord

from choque.channel_names import (
    SMALL_CAPS_WORD_SEPARATOR,
    format_category_name,
    format_channel_name,
)
from choque.config import AppConfig
from scripts.provision_discord_layout import REASON, ProvisionClient

REGISTRY_SETTING = "discord_layout_registry_v2"
LAYOUT_REASON = f"{REASON} - referencia visual v2"


@dataclass(frozen=True, slots=True)
class CategorySpec:
    key: str
    order: int
    name: str
    permission: Literal["public", "member", "private", "audit"]
    known_id: int | None = None

    @property
    def visual_name(self) -> str:
        return format_category_name(self.order, self.name)


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    key: str
    category: str
    emoji: str
    name: str
    kind: Literal["text", "voice"] = "text"
    known_id: int | None = None

    @property
    def visual_name(self) -> str:
        return format_channel_name(self.name, self.emoji)


CATEGORY_SPECS = (
    CategorySpec("reception", 1, "Recepcao", "public"),
    CategorySpec("ticket", 2, "Ticket", "public"),
    CategorySpec("superiors", 3, "Superiores", "private"),
    CategorySpec("admin", 4, "Administracao", "private", 1540540581728485597),
    CategorySpec("member", 5, "Central do membro", "member", 1540546763939782676),
    CategorySpec("registration", 6, "Registro", "member"),
    CategorySpec("info", 7, "Informacoes", "member", 1161833335618801687),
    CategorySpec("community", 8, "Membros choque", "member", 1146622065399566420),
    CategorySpec("point", 9, "Bate ponto", "member"),
    CategorySpec("events", 10, "Eventos", "member"),
    CategorySpec("patrol", 11, "Patrulhas", "member", 1146622065647046776),
    CategorySpec("management", 12, "Gerenciamento", "private"),
    CategorySpec("partnerships", 13, "Transferencias e parcerias", "public"),
    CategorySpec("recruitment", 14, "Recrutamento", "public", 1162263284108501092),
    CategorySpec("courses", 15, "Cursos", "member", 1162114516318949529),
    CategorySpec("away", 16, "Ausente", "member"),
    CategorySpec("meeting", 17, "Reuniao", "member"),
    CategorySpec("audit", 18, "Auditoria", "audit", 1146622066527850585),
    CategorySpec("archive", 99, "Arquivo legado", "private", 1146622065110171669),
)


CHANNEL_SPECS = (
    # 01 Recepcao
    ChannelSpec("reception.entries", "reception", "🚤", "Entrou", known_id=1146622066817253460),
    ChannelSpec("reception.exits", "reception", "🚤", "Saiu", known_id=1163604719747473438),
    ChannelSpec("reception.invite", "reception", "🚪", "Convite"),
    # 02 Ticket
    ChannelSpec("ticket.panel", "ticket", "🎫", "Atendimento", known_id=1146622065852563593),
    ChannelSpec(
        "ticket.queue",
        "ticket",
        "📥",
        "Fila de atendimento",
        known_id=1540546971251777567,
    ),
    ChannelSpec("ticket.waiting", "ticket", "⏳", "Aguardando atendimento", "voice"),
    ChannelSpec("ticket.room.1", "ticket", "🎧", "Atendimento 1", "voice"),
    ChannelSpec("ticket.room.2", "ticket", "🎧", "Atendimento 2", "voice"),
    ChannelSpec("ticket.room.3", "ticket", "🎧", "Atendimento 3", "voice"),
    # 03 Superiores
    ChannelSpec("superiors.notices", "superiors", "📢", "Avisos do comando"),
    ChannelSpec("superiors.chat", "superiors", "💬", "Chat superiores"),
    ChannelSpec("superiors.records", "superiors", "📜", "Registros superiores"),
    ChannelSpec("superiors.manual", "superiors", "📖", "Manual do comando"),
    ChannelSpec("superiors.qa", "superiors", "🧪", "Area de qa"),
    # 04 Administracao
    ChannelSpec(
        "admin.central",
        "admin",
        "🛡️",
        "Central administrativa",
        known_id=1540540583704141915,
    ),
    # 05 Central do membro
    ChannelSpec(
        "member.central",
        "member",
        "🏠",
        "Central do membro",
        known_id=1540546961114013706,
    ),
    ChannelSpec(
        "member.requests", "member", "📥", "Solicitacoes", known_id=1540540585289715722
    ),
    ChannelSpec("member.career", "member", "📈", "Carreira", known_id=1540560219359412264),
    ChannelSpec(
        "member.discipline", "member", "⚖️", "Disciplina", known_id=1540565258404626552
    ),
    ChannelSpec(
        "member.activity", "member", "📊", "Atividade semanal", known_id=1540578026071396372
    ),
    ChannelSpec(
        "member.ranking", "member", "🏆", "Ranking de horas", known_id=1540540587307040810
    ),
    # Cadastro público permanece na Recepção; a categoria Registro é interna/legada.
    ChannelSpec(
        "registration.panel", "reception", "📝", "Cadastro", known_id=1540546963454304326
    ),
    # 07 Informacoes
    ChannelSpec("info.notices", "info", "📢", "Avisos", known_id=1161742911105421393),
    ChannelSpec("info.bgr", "info", "📣", "Anuncios bgr", known_id=1176911554629861396),
    ChannelSpec("info.rules", "info", "📘", "Regras gerais", known_id=1146622064736882707),
    ChannelSpec(
        "info.regulations", "info", "📕", "Regulamento interno", known_id=1164287787898503228
    ),
    ChannelSpec(
        "info.patrol", "info", "📋", "Procedimentos patrulha", known_id=1146622065110171661
    ),
    ChannelSpec("info.rocam", "info", "🏍️", "Doutrina rocam", known_id=1161833937232990330),
    ChannelSpec("info.eagle", "info", "🚁", "Doutrina aguia", known_id=1161835204642603128),
    ChannelSpec("info.uniforms", "info", "👮", "Fardamentos", known_id=1146622065110171664),
    ChannelSpec("info.vehicles", "info", "🚓", "Viaturas", known_id=1146622065110171665),
    ChannelSpec("info.binds", "info", "⌨️", "Binds operacionais", known_id=1146622065110171667),
    ChannelSpec("info.codes", "info", "📻", "Codigos q", known_id=1161810176718930071),
    ChannelSpec("info.hierarchy", "info", "📈", "Hierarquia", known_id=1146622065110171666),
    ChannelSpec("info.medals", "info", "🏅", "Medalhas", known_id=1165940959318655037),
    ChannelSpec(
        "info.decorations", "info", "🎖️", "Condecoracoes", known_id=1165939530474475530
    ),
    # 08 Membros choque
    ChannelSpec("community.general", "community", "💬", "Chat geral", known_id=1201450207917899786),
    ChannelSpec("community.member", "community", "💬", "Chat choque", known_id=1161830033858515035),
    ChannelSpec("community.suggestions", "community", "💡", "Sugestoes", known_id=1153774907088441354),
    ChannelSpec("community.media", "community", "📷", "Midia e instagram", known_id=1161829510627459172),
    # 09 Bate ponto
    ChannelSpec("point.panel", "point", "⏱️", "Bate ponto", known_id=1540546965362974731),
    ChannelSpec(
        "point.active", "point", "👥", "Efetivo em servico", known_id=1540546967938011186
    ),
    # 10 Eventos
    ChannelSpec("events.notices", "events", "📣", "Notificacoes de eventos"),
    ChannelSpec("events.waiting", "events", "⏳", "Aguardando evento", "voice"),
    ChannelSpec("events.room", "events", "🎉", "Evento", "voice"),
    # 11 Patrulhas
    ChannelSpec(
        "patrol.availability",
        "patrol",
        "🟢",
        "Disponivel para patrulha",
        known_id=1164363506083172413,
    ),
    ChannelSpec("patrol.report", "patrol", "📋", "Relatorio ptr"),
    ChannelSpec(
        "patrol.waiting",
        "patrol",
        "🚔",
        "Aguardando patrulha",
        "voice",
        1161829541292028075,
    ),
    ChannelSpec("patrol.alpha", "patrol", "🚔", "Patrulha alfa", "voice", 1146622065647046780),
    ChannelSpec("patrol.bravo", "patrol", "🚔", "Patrulha bravo", "voice", 1146622065647046781),
    ChannelSpec(
        "patrol.charlie", "patrol", "🚔", "Patrulha charlie", "voice", 1146622065647046782
    ),
    ChannelSpec("patrol.delta", "patrol", "🚔", "Patrulha delta", "voice", 1146622065647046784),
    ChannelSpec("patrol.convoy", "patrol", "🚙", "Comboio", "voice", 1164957395370385519),
    ChannelSpec("patrol.rocam.1", "patrol", "🏍️", "Rocam 1", "voice", 1161833828793450566),
    ChannelSpec("patrol.rocam.2", "patrol", "🏍️", "Rocam 2", "voice", 1161848955764748359),
    ChannelSpec("patrol.eagle.1", "patrol", "🚁", "Aguia 1", "voice", 1161835749952471130),
    ChannelSpec("patrol.eagle.2", "patrol", "🚁", "Aguia 2", "voice", 1161848786637828107),
    ChannelSpec("patrol.blitz.lv", "patrol", "🚧", "Blitz lv", "voice", 1146622065852563591),
    ChannelSpec("patrol.blitz.ls", "patrol", "🚧", "Blitz ls", "voice", 1161828293062967340),
    # 12 Gerenciamento
    ChannelSpec(
        "management.config",
        "management",
        "⚙️",
        "Configuracoes do bot",
        known_id=1166681424154333277,
    ),
    # 13 Transferencias e parcerias
    ChannelSpec(
        "partnerships.transfers",
        "partnerships",
        "🔄",
        "Transferencias",
        known_id=1166861438728548432,
    ),
    ChannelSpec("partnerships.partners", "partnerships", "🤝", "Parceiros"),
    ChannelSpec("partnerships.terms", "partnerships", "📜", "Termos institucionais"),
    # 14 Recrutamento
    ChannelSpec(
        "recruitment.requirements",
        "recruitment",
        "📋",
        "Requisitos",
        known_id=1161840087483564092,
    ),
    ChannelSpec(
        "recruitment.panel",
        "recruitment",
        "📝",
        "Recrutamento",
        known_id=1162263355885629540,
    ),
    ChannelSpec(
        "recruitment.approved",
        "recruitment",
        "✅",
        "Aprovados entrevista",
        known_id=1166175384119812166,
    ),
    ChannelSpec(
        "recruitment.rejected",
        "recruitment",
        "❌",
        "Reprovados entrevista",
        known_id=1166176079724154910,
    ),
    ChannelSpec("recruitment.waiting", "recruitment", "⏳", "Aguardando recrutamento", "voice"),
    ChannelSpec("recruitment.interview", "recruitment", "🎙️", "Entrevista", "voice"),
    ChannelSpec("recruitment.result", "recruitment", "📣", "Resultado", "voice"),
    # 15 Cursos
    ChannelSpec("courses.panel", "courses", "🎯", "Treinamentos", known_id=1540546969649291376),
    ChannelSpec("courses.list", "courses", "📖", "Cursos", known_id=1162114694581059584),
    ChannelSpec("courses.chat", "courses", "💬", "Chat de formacao", known_id=1168335359990566912),
    ChannelSpec("courses.instructors", "courses", "🧑‍🏫", "Instrutores", known_id=1166622479196901438),
    ChannelSpec("courses.approved", "courses", "✅", "Aprovados em cursos", known_id=1165345443786543144),
    ChannelSpec("courses.rejected", "courses", "❌", "Reprovados em cursos", known_id=1165348711895932948),
    ChannelSpec("courses.graduates", "courses", "🎒", "Formados", known_id=1164983916902490182),
    ChannelSpec("courses.waiting", "courses", "🎓", "Aguardando formacao", "voice", 1162240695629795348),
    ChannelSpec("courses.room.1", "courses", "📚", "Sala de curso 1", "voice", 1162240256913965086),
    ChannelSpec("courses.room.2", "courses", "📚", "Sala de curso 2", "voice", 1162934172554367097),
    # 16 Ausente
    ChannelSpec("away.room", "away", "💤", "Ausente", "voice"),
    # 17 Reuniao
    ChannelSpec("meeting.room", "meeting", "📞", "Reuniao", "voice"),
    # 18 Auditoria
    ChannelSpec("audit.bot", "audit", "📜", "Auditoria do bot", known_id=1146622066817253458),
    ChannelSpec(
        "audit.discord",
        "audit",
        "🛡️",
        "Moderacao discord",
        known_id=1146622066817253459,
    ),
    # 99 Arquivo legado
    ChannelSpec("archive.tags", "archive", "🔖", "Solicitacoes de tag legadas", known_id=1166194316935446539),
    ChannelSpec("archive.referrals", "archive", "📩", "Indicacoes legadas", known_id=1164316808933822487),
    ChannelSpec("archive.central", "archive", "🌐", "Central antiga", known_id=1147294527846092820),
    ChannelSpec("archive.demotions", "archive", "🔻", "Rebaixamentos legados", known_id=1161766293628801034),
    ChannelSpec("archive.exonerations", "archive", "🔙", "Exoneracoes legadas", known_id=1161766389116325978),
    ChannelSpec("archive.blacklist", "archive", "⬛", "Blacklist legada", known_id=1167387428277981214),
    ChannelSpec("archive.departures", "archive", "📤", "Pedidos de saida legados", known_id=1162977145426022400),
    ChannelSpec("archive.absences", "archive", "💤", "Ausencias legadas", known_id=1147294480005877826),
    ChannelSpec("archive.friends", "archive", "💭", "Chat amigos legado", known_id=1163015080141664378),
    ChannelSpec("archive.point.rules", "archive", "🚨", "Regras antigas do ponto", known_id=1161811169795899412),
    ChannelSpec("archive.point.panel", "archive", "📝", "Painel antigo do ponto", known_id=1147293613886283817),
    ChannelSpec("archive.members", "archive", "📜", "Historico de membros", known_id=1147292121234161783),
    ChannelSpec("archive.point.records", "archive", "💠", "Registros antigos do ponto", known_id=1161828543152541726),
)


CATEGORY_BY_KEY = {spec.key: spec for spec in CATEGORY_SPECS}
CHANNEL_BY_KEY = {spec.key: spec for spec in CHANNEL_SPECS}

LEGACY_NAME_ALIASES = {
    "📜│auditoria-do-bot": "audit.bot",
    "🛡️│central-administrativa": "admin.central",
    "📝│cadastro": "registration.panel",
    "⏱️│controle-de-serviço": "point.panel",
    "👥│efetivo-em-serviço": "point.active",
    "📈│hierarquia": "info.hierarchy",
    "⚙️│configurações-do-bot": "management.config",
    "📥│solicitações": "member.requests",
    "📈│carreira": "member.career",
    "⚖️│disciplina": "member.discipline",
    "🎯│treinamentos": "courses.panel",
    "📊│atividade-semanal": "member.activity",
    "🏆│ranking-de-horas": "member.ranking",
    "📋│requisitos": "recruitment.requirements",
    "📝│recrutamento": "recruitment.panel",
    "🎫│atendimento": "ticket.panel",
    "📥│fila-de-candidatos": "ticket.queue",
    "🔄│transferências": "partnerships.transfers",
    "✅│aprovados-entrevista": "recruitment.approved",
    "❌│reprovados-entrevista": "recruitment.rejected",
    "🏠│central-do-membro": "member.central",
    "📜│histórico-de-membros": "archive.members",
}


class RemodelClient(ProvisionClient):
    def __init__(self, config: AppConfig, *, apply: bool) -> None:
        super().__init__(config, apply=apply)
        self.registry: dict[str, dict[str, int]] = {"categories": {}, "channels": {}}
        self.layout_channels: dict[str, discord.abc.GuildChannel] = {}
        self.exit_code = 1

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
            await self.load_registry(guild.id)
            if not self.apply:
                print(
                    f"DRY_RUN_OK categories={len(CATEGORY_SPECS)} "
                    f"channels={len(CHANNEL_SPECS)} separator={SMALL_CAPS_WORD_SEPARATOR!r}"
                )
                self.exit_code = 0
                return

            await self.resolve_roles(guild)
            await self.ensure_status_roles(guild)
            await self.ensure_layout_categories(guild)
            await self.test_name_separator(guild)
            await self.ensure_layout_channels(guild)
            await self.order_layout_channels()
            await self.apply_channel_permissions(guild)
            await self.configure_database(guild)
            await self.persist_registry(guild.id)
            await self.publish_layout_messages(guild)
            await self.validate_layout(guild)
            self.exit_code = 0
            print(
                f"REMODEL_OK categories={len(CATEGORY_SPECS)} "
                f"channels={len(CHANNEL_SPECS)}"
            )
        except Exception:
            traceback.print_exc()
        finally:
            await self.database.close()
            await self.close()

    async def load_registry(self, guild_id: int) -> None:
        stored = await self.settings.get(guild_id, REGISTRY_SETTING, {})
        if not isinstance(stored, dict):
            return
        for group in ("categories", "channels"):
            values = stored.get(group, {})
            if isinstance(values, dict):
                self.registry[group] = {
                    str(key): int(value)
                    for key, value in values.items()
                    if str(value).isdigit()
                }

    def category_overwrites(
        self, guild: discord.Guild, permission: str
    ) -> dict[Any, discord.PermissionOverwrite]:
        if permission == "public":
            return self.public_readonly_overwrites(guild)
        if permission == "member":
            return self.member_overwrites(guild)
        if permission == "audit":
            return self.private_overwrites(guild, ("corrections",))
        return self.private_overwrites(guild)

    async def ensure_layout_categories(self, guild: discord.Guild) -> None:
        for spec in CATEGORY_SPECS:
            registry_id = self.registry["categories"].get(spec.key)
            category_id = registry_id or spec.known_id
            category = guild.get_channel(category_id) if category_id else None
            if category is not None and not isinstance(category, discord.CategoryChannel):
                raise RuntimeError(f"ID de categoria aponta para outro tipo: {spec.key}")
            if category is None:
                category = discord.utils.get(guild.categories, name=spec.visual_name)
            if category is None:
                category = await guild.create_category(
                    spec.visual_name,
                    overwrites=self.category_overwrites(guild, spec.permission),
                    reason=LAYOUT_REASON,
                )
            else:
                await category.edit(
                    name=spec.visual_name,
                    overwrites=self.category_overwrites(guild, spec.permission),
                    reason=LAYOUT_REASON,
                )
            self.categories[spec.key] = category
            self.registry["categories"][spec.key] = category.id

        for position, spec in enumerate(CATEGORY_SPECS):
            await self.categories[spec.key].edit(position=position, reason=LAYOUT_REASON)

    async def test_name_separator(self, guild: discord.Guild) -> None:
        expected = format_channel_name("Canal de teste", "🧪")
        test_channel = await guild.create_text_channel(
            expected,
            category=self.categories["archive"],
            overwrites=self.categories["archive"].overwrites,
            reason=f"{LAYOUT_REASON} - teste de separador",
        )
        try:
            fetched = await guild.fetch_channel(test_channel.id)
            if fetched.name != expected:
                raise RuntimeError(
                    f"Discord alterou o separador: esperado={expected!r} recebido={fetched.name!r}"
                )
            if fetched.mention != f"<#{fetched.id}>":
                raise RuntimeError("Mencao do canal de teste nao foi preservada.")
            print(f"NAME_TEST_OK separator={SMALL_CAPS_WORD_SEPARATOR!r}")
        finally:
            await test_channel.delete(reason=f"{LAYOUT_REASON} - fim do teste de separador")

    async def ensure_layout_channels(self, guild: discord.Guild) -> None:
        for spec in CHANNEL_SPECS:
            registry_id = self.registry["channels"].get(spec.key)
            channel_id = registry_id or spec.known_id
            channel = guild.get_channel(channel_id) if channel_id else None
            expected_type = discord.TextChannel if spec.kind == "text" else discord.VoiceChannel
            if channel is not None and not isinstance(channel, expected_type):
                raise RuntimeError(f"ID de canal aponta para outro tipo: {spec.key}")
            if channel is None and spec.known_id:
                raise RuntimeError(f"Canal conhecido nao foi encontrado: {spec.key}:{spec.known_id}")
            if channel is None:
                category = self.categories[spec.category]
                channel = discord.utils.get(category.channels, name=spec.visual_name)
            if channel is None:
                category = self.categories[spec.category]
                if spec.kind == "text":
                    channel = await guild.create_text_channel(
                        spec.visual_name,
                        category=category,
                        overwrites=category.overwrites,
                        reason=LAYOUT_REASON,
                    )
                else:
                    channel = await guild.create_voice_channel(
                        spec.visual_name,
                        category=category,
                        overwrites=category.overwrites,
                        reason=LAYOUT_REASON,
                    )
            else:
                await channel.edit(
                    name=spec.visual_name,
                    category=self.categories[spec.category],
                    sync_permissions=False,
                    reason=LAYOUT_REASON,
                )
            self.layout_channels[spec.key] = channel
            self.registry["channels"][spec.key] = channel.id

    async def order_layout_channels(self) -> None:
        positions: dict[str, int] = {}
        for spec in CHANNEL_SPECS:
            position = positions.get(spec.category, 0)
            await self.layout_channels[spec.key].edit(position=position, reason=LAYOUT_REASON)
            positions[spec.category] = position + 1

    def text_channel(self, name: str) -> discord.TextChannel:
        key = LEGACY_NAME_ALIASES.get(name, name)
        channel = self.layout_channels.get(key)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"Canal de texto obrigatorio nao encontrado: {key}")
        return channel

    async def persist_registry(self, guild_id: int) -> None:
        actor_id = self.user.id if self.user else None
        await self.settings.set(guild_id, REGISTRY_SETTING, self.registry, actor_id)
        authorized_ids = await self.settings.authorized_voice_ids(guild_id)
        async with self.database.transaction() as connection:
            for channel_id in authorized_ids:
                channel = self.get_channel(channel_id)
                if isinstance(channel, discord.VoiceChannel):
                    await connection.execute(
                        """
                        UPDATE authorized_voice_channels SET label=?
                        WHERE guild_id=? AND channel_id=?
                        """,
                        (channel.name, guild_id, channel.id),
                    )

    async def validate_layout(self, guild: discord.Guild) -> None:
        failures: list[str] = []
        fresh_channels = {channel.id: channel for channel in await guild.fetch_channels()}
        for spec in CATEGORY_SPECS:
            category = fresh_channels.get(self.registry["categories"][spec.key])
            if not isinstance(category, discord.CategoryChannel) or category.name != spec.visual_name:
                failures.append(f"category:{spec.key}")
        for spec in CHANNEL_SPECS:
            channel = fresh_channels.get(self.registry["channels"][spec.key])
            if channel is None or channel.name != spec.visual_name:
                failures.append(f"channel:{spec.key}")
            elif any(character in channel.name for character in ("-", "_", "│", " ")):
                failures.append(f"format:{spec.key}")
        if failures:
            raise RuntimeError(f"Layout visual invalido: {failures}")
        category_count = sum(
            isinstance(channel, discord.CategoryChannel) for channel in fresh_channels.values()
        )
        if category_count != len(CATEGORY_SPECS):
            raise RuntimeError(
                f"Quantidade de categorias inesperada: {category_count} "
                f"(esperado {len(CATEGORY_SPECS)})"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remodela o layout visual CHOQUE - BGR")
    parser.add_argument(
        "--apply", action="store_true", help="Aplica a remodelacao; sem isso apenas inventaria."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AppConfig.load()
    if not config.token or not config.default_guild_id:
        raise SystemExit("DISCORD_TOKEN e DEFAULT_GUILD_ID precisam estar configurados.")
    client = RemodelClient(config, apply=args.apply)
    client.run(config.token, log_handler=None)
    return client.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
