from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from choque.embeds import branded_embed
from choque.errors import NotFoundError, PermissionDenied, ValidationError
from choque.models import PersonnelActionType, PunishmentType
from choque.time_utils import discord_timestamp, format_duration, period_bounds, utc_now_ms
from cogs.config_ui import respond_error
from cogs.member_sync import sync_member_status_roles, sync_rank_to_discord, sync_registered_member

LOGGER = logging.getLogger(__name__)


def get_bot(interaction: discord.Interaction) -> ChoqueBot:
    return cast("ChoqueBot", interaction.client)


async def require_admin(interaction: discord.Interaction) -> discord.Member:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValidationError("Este painel só pode ser usado dentro do servidor.")
    bot = get_bot(interaction)
    if not await bot.services.permissions.has(interaction.user, "personnel.manage"):
        raise PermissionDenied("Você não possui permissão para administrar o efetivo.")
    return interaction.user


class ErrorView(discord.ui.View):
    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await respond_error(interaction, error)


class AdminView(ErrorView):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            await require_admin(interaction)
        except Exception as exc:
            await respond_error(interaction, exc)
            return False
        return True


class ErrorModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await respond_error(interaction, error)


async def build_admin_embed(bot: ChoqueBot, guild: discord.Guild) -> discord.Embed:
    counts = await asyncio.gather(
        bot.services.database.fetchone(
            """
            SELECT
              (SELECT COUNT(*) FROM member_applications
               WHERE guild_id=? AND status='PENDING')
              +
              (SELECT COUNT(*) FROM registration_gate_records
               WHERE guild_id=? AND status IN ('PENDING','REQUIRES_REVIEW')) AS total
            """,
            (guild.id, guild.id),
        ),
        bot.services.database.fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM absence_requests
                 WHERE guild_id=? AND status='PENDING')
                +
                (SELECT COUNT(*) FROM administrative_requests
                 WHERE guild_id=? AND status='PENDING') AS total
            """,
            (guild.id, guild.id),
        ),
        bot.services.database.fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM punishments
                 WHERE guild_id=? AND status IN ('SCHEDULED','ACTIVE'))
                +
                (SELECT COUNT(*) FROM disciplinary_occurrences
                 WHERE guild_id=? AND status='OPEN') AS total
            """,
            (guild.id, guild.id),
        ),
        bot.services.database.fetchone(
            "SELECT COUNT(*) AS total FROM members WHERE guild_id=? AND status='ACTIVE'",
            (guild.id,),
        ),
        bot.services.database.fetchone(
            "SELECT COUNT(*) AS total FROM shifts WHERE guild_id=? AND status IN ('ACTIVE','GRACE')",
            (guild.id,),
        ),
    )
    applications, requests, punishments, active_members, active_shifts = (
        int(row["total"]) for row in counts
    )
    embed = branded_embed(
        bot.config.branding,
        title="🛡️ Central Administrativa • CHOQUE - BGR",
        description=(
            "Administre todo o efetivo pelos botões abaixo. Todas as decisões são "
            "transacionais, registradas na auditoria e sincronizadas com o Discord."
        ),
    )
    embed.add_field(
        name="Filas pendentes",
        value=f"🛡️ Portaria: **{applications}**\n📥 Solicitações: **{requests}**",
    )
    embed.add_field(
        name="Operação",
        value=f"👥 Ativos: **{active_members}**\n🎙️ Em serviço: **{active_shifts}**",
    )
    embed.add_field(name="Disciplina", value=f"⚠️ Itens em acompanhamento: **{punishments}**")
    embed.add_field(
        name="Fluxo",
        value=(
            "1. Escolha uma área.\n2. Selecione o membro ou solicitação.\n"
            "3. Confirme a ação e informe o motivo."
        ),
        inline=False,
    )
    return embed


def build_absence_landing_embed(bot: ChoqueBot) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title="🗓️ Afastamentos • CHOQUE - BGR",
        description=(
            "Solicite seu afastamento pelo botão abaixo. O período só entra em vigor após "
            "aprovação administrativa. Você pode consultar ou cancelar uma solicitação pendente."
        ),
    )


async def build_registration_admin_embed(
    bot: ChoqueBot, guild: discord.Guild
) -> discord.Embed:
    counts = await bot.services.registration_gate.counts(guild.id)
    legacy = await bot.services.database.fetchone(
        """
        SELECT COUNT(*) AS total FROM member_applications
        WHERE guild_id=? AND status='PENDING'
        """,
        (guild.id,),
    )
    findings = await bot.services.database.fetchone(
        """
        SELECT COUNT(*) AS total FROM registration_access_findings
        WHERE guild_id=? AND status='OPEN'
        """,
        (guild.id,),
    )
    enabled = await bot.services.settings.get(guild.id, "registration_gate_enabled", False)
    embed = branded_embed(
        bot.config.branding,
        title="🛡️ Portaria Digital • Administração",
        description=(
            "Controle de identidade, acesso mínimo e sincronização do Discord. "
            "Cadastro e candidatura permanecem fluxos independentes."
        ),
    )
    embed.add_field(
        name="Identidades",
        value=(
            f"Não cadastrados: **{counts['UNREGISTERED']}**\n"
            f"Pendentes: **{counts['PENDING']}**\n"
            f"Revisão: **{counts['REQUIRES_REVIEW']}**"
        ),
    )
    embed.add_field(
        name="Operação",
        value=(
            f"Registrados: **{counts['REGISTERED']}**\n"
            f"Bloqueados: **{counts['BLOCKED']}**\n"
            f"Concluídos/24h: **{counts['COMPLETED_LAST_24H']}**"
        ),
    )
    embed.add_field(
        name="Integridade",
        value=(
            f"Membros sem ID: **{counts['MEMBERS_WITHOUT_ID']}**\n"
            f"Alertas abertos: **{int(findings['total']) if findings else 0}**\n"
            f"Fila legada: **{int(legacy['total']) if legacy else 0}**"
        ),
    )
    embed.add_field(
        name="Estado do gate",
        value=f"`{'ATIVO' if enabled else 'DESATIVADO'}`",
        inline=False,
    )
    return embed


def build_registration_directory_embed(bot: ChoqueBot, result: dict) -> discord.Embed:
    query = str(result["query"] or "")
    embed = branded_embed(
        bot.config.branding,
        title="🗂️ Gerenciador de Cadastros • Alto Comando",
        description=(
            "Consulte, pesquise, edite, desative logicamente ou reabra cadastros. "
            "Nenhuma ação apaga o membro ou o histórico administrativo."
        ),
    )
    embed.add_field(
        name="Resultado",
        value=(
            f"Cadastros: **{int(result['total'])}**\n"
            f"Página: **{int(result['page']) + 1}/{int(result['pages'])}**\n"
            f"Busca: **{query or 'todos'}**"
        ),
        inline=False,
    )
    if not result["rows"]:
        embed.add_field(
            name="Nenhum cadastro localizado",
            value="Use **Pesquisar** para buscar por nome, ID BGR, Discord, patente ou unidade.",
            inline=False,
        )
    else:
        embed.add_field(
            name="Como usar",
            value=(
                "Selecione um cadastro na lista. As ações críticas exigem motivo e "
                "confirmação literal."
            ),
            inline=False,
        )
    return embed


def build_registration_directory_record_embed(bot: ChoqueBot, record) -> discord.Embed:
    status_icons = {
        "REGISTERED": "✅",
        "PENDING": "⏳",
        "REQUIRES_REVIEW": "⚠️",
        "UNREGISTERED": "🪪",
        "BLOCKED": "⛔",
    }
    status = str(record["status"])
    embed = branded_embed(
        bot.config.branding,
        title=f"{status_icons.get(status, '🪪')} CAD-{int(record['id']):04d} • Cadastro",
        description=(
            f"**Discord:** <@{record['discord_id']}>\n"
            f"**Nick BGR:** {record['mta_nick'] or '—'}\n"
            f"**ID BGR:** {record['bgr_id'] or '—'}\n"
            f"**Patente:** {record['rank_name'] or '—'}\n"
            f"**Unidade:** {record['unit'] or '—'}"
        ),
    )
    embed.add_field(
        name="Situação",
        value=(
            f"Portaria: `{status}`\n"
            f"Efetivo: `{record['member_status'] or 'SEM VÍNCULO'}`\n"
            f"Acesso: `{record['access_tier']}`\n"
            f"Sincronização: `{record['sync_status']}`"
        ),
    )
    embed.add_field(
        name="Integridade",
        value=(
            f"Vínculo interno: **{'sim' if record['member_id'] else 'não'}**\n"
            f"Conflito: `{record['conflict_code'] or 'NENHUM'}`\n"
            f"Versão: **{int(record['version'])}**"
        ),
    )
    embed.add_field(
        name="Regra de segurança",
        value=(
            "**Desativar** revoga o acesso sem excluir dados. **Reabrir** devolve o cadastro "
            "à Portaria para nova análise humana."
        ),
        inline=False,
    )
    return embed


def build_rank_compliance_embed(bot: ChoqueBot, result: dict) -> discord.Embed:
    embed = branded_embed(
        bot.config.branding,
        title="⏳ Patente sem Cadastro • Prazo de 72 horas",
        description=(
            "Acompanhe pessoas que receberam uma patente militar sem cadastro aprovado. "
            "O sistema avisa por DM, envia lembretes e remove somente a patente vencida."
        ),
    )
    embed.add_field(
        name="Fila ativa",
        value=(
            f"Pendências: **{int(result['total'])}**\n"
            f"Página: **{int(result['page']) + 1}/{int(result['pages'])}**"
        ),
        inline=False,
    )
    rows = result["rows"]
    if rows:
        lines = []
        for row in rows:
            lines.append(
                f"<@{row['discord_id']}> • **{row['rank_name'] or 'Patente'}**\n"
                f"└ prazo {discord_timestamp(int(row['due_at']), 'R')} • "
                f"DM `{row['dm_status']}` • lembretes **{int(row['reminder_count'])}/3**"
            )
        embed.add_field(name="Militares pendentes", value="\n".join(lines), inline=False)
    else:
        embed.add_field(
            name="Situação regular",
            value="✅ Nenhuma patente está aguardando regularização de cadastro.",
            inline=False,
        )
    embed.add_field(
        name="Proteção",
        value=(
            "Antes de remover uma patente, o bot confere novamente o cadastro, o cargo e o prazo. "
            "Outros cargos nunca são removidos por este fluxo."
        ),
        inline=False,
    )
    return embed


async def require_registration_permission(
    interaction: discord.Interaction, permission: str
) -> discord.Member:
    actor = await require_admin(interaction)
    if not await get_bot(interaction).services.permissions.has(actor, permission):
        raise PermissionDenied("Você não possui permissão para esta ação da Portaria.")
    return actor


class RegistrationAdminView(AdminView):
    @discord.ui.button(
        label="Gerenciar cadastros", emoji="🗂️", style=discord.ButtonStyle.danger
    )
    async def directory(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        result = await get_bot(interaction).services.registration_gate.directory(
            interaction.guild.id
        )
        await interaction.response.send_message(
            embed=build_registration_directory_embed(get_bot(interaction), result),
            view=RegistrationDirectoryView(result),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Sem cadastro • 72h", emoji="⏳", style=discord.ButtonStyle.primary
    )
    async def compliance(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        result = await get_bot(interaction).services.registration_gate.rank_compliance_directory(
            interaction.guild.id
        )
        await interaction.response.send_message(
            embed=build_rank_compliance_embed(get_bot(interaction), result),
            view=RankRegistrationComplianceView(result),
            ephemeral=True,
        )

    @discord.ui.button(label="Revisões", emoji="📥", style=discord.ButtonStyle.primary)
    async def reviews(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.view")
        rows = await get_bot(interaction).services.registration_gate.queue(interaction.guild.id)
        if not rows:
            await interaction.response.send_message(
                "✅ Nenhum cadastro aguardando revisão.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Selecione uma identidade para analisar:",
            view=GateRegistrationListView(rows),
            ephemeral=True,
        )

    @discord.ui.button(label="Fila legada", emoji="🗃️", style=discord.ButtonStyle.secondary)
    async def legacy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await get_bot(interaction).services.database.fetchall(
            """
            SELECT * FROM member_applications
            WHERE guild_id=? AND status='PENDING' ORDER BY submitted_at LIMIT 25
            """,
            (interaction.guild.id,),
        )
        if not rows:
            await interaction.response.send_message(
                "✅ Nenhum cadastro do fluxo legado pendente.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Solicitações antigas preservadas para conclusão:",
            view=ApplicationListView(rows),
            ephemeral=True,
        )

    @discord.ui.button(label="Configurar", emoji="⚙️", style=discord.ButtonStyle.secondary)
    async def settings(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.settings")
        await interaction.response.send_message(
            "Configure os recursos da Portaria. Alterações são auditadas.",
            view=RegistrationSettingsView(),
            ephemeral=True,
        )

    @discord.ui.button(label="Validar acesso", emoji="🔎", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.manage")
        cog = get_bot(interaction).get_cog("RegistrationGateSystem")
        if cog is None or not hasattr(cog, "validate_access"):
            raise NotFoundError("O validador da Portaria não está disponível.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await cog.validate_access(interaction.guild)
        await interaction.followup.send(
            "🛡️ **VALIDAÇÃO DE ACESSO**\n"
            f"Recursos internos verificados: **{result['protected']}**\n"
            f"Recursos de entrada: **{result['onboarding']}**\n"
            f"Exposições: **{len(result['leaks'])}**\n"
            f"Sem classificação: **{len(result['unclassified'])}**",
            ephemeral=True,
        )

    @discord.ui.button(label="Reconciliar", emoji="🔄", style=discord.ButtonStyle.danger)
    async def reconcile(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_registration_permission(interaction, "registration.manage")
        cog = get_bot(interaction).get_cog("RegistrationGateSystem")
        if cog is None or not hasattr(cog, "reconcile_member"):
            raise NotFoundError("O reconciliador da Portaria não está disponível.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        processed = 0
        failed = 0
        for member in interaction.guild.members:
            try:
                record = await cog.reconcile_member(member, actor_id=actor.id)
                processed += int(record is not None)
            except Exception:
                failed += 1
                LOGGER.exception("Falha ao reconciliar a identidade %s", member.id)
        await interaction.followup.send(
            f"🔄 Reconciliação concluída: **{processed}** identidades; **{failed}** falhas.",
            ephemeral=True,
        )

    @discord.ui.button(label="Segurança", emoji="🔐", style=discord.ButtonStyle.secondary)
    async def security_settings(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await require_registration_permission(interaction, "registration.settings")
        await interaction.response.send_message(
            "Configurações críticas da Portaria. A ativação só é aceita após validação sem falhas.",
            view=RegistrationSecuritySettingsView(),
            ephemeral=True,
        )


class RegistrationDirectorySelect(discord.ui.Select):
    def __init__(self, rows: list, *, query: str, page: int) -> None:
        self.query = query
        self.page = page
        super().__init__(
            placeholder="Escolha um cadastro",
            min_values=1,
            max_values=1,
            row=0,
            options=[
                discord.SelectOption(
                    label=(
                        f"CAD-{int(row['id']):04d} • "
                        f"{row['mta_nick'] or row['discord_nick'] or row['discord_id']}"
                    )[:100],
                    value=str(row["id"]),
                    description=(
                        f"{row['status']} • {row['rank_name'] or 'Sem patente'} • "
                        f"ID {row['bgr_id'] or '—'}"
                    )[:100],
                    emoji="⛔" if row["status"] == "BLOCKED" else "🪪",
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        bot = get_bot(interaction)
        record = await bot.services.registration_gate.directory_record(int(self.values[0]))
        if not record or int(record["guild_id"]) != interaction.guild.id:
            raise NotFoundError("Cadastro não encontrado.")
        await interaction.response.edit_message(
            embed=build_registration_directory_record_embed(bot, record),
            view=RegistrationDirectoryActionView(
                int(record["id"]), query=self.query, page=self.page
            ),
        )


class RegistrationDirectoryView(AdminView):
    def __init__(self, result: dict) -> None:
        super().__init__(timeout=300)
        self.result = result
        if result["rows"]:
            self.add_item(
                RegistrationDirectorySelect(
                    result["rows"], query=str(result["query"]), page=int(result["page"])
                )
            )
        self.previous.disabled = int(result["page"]) <= 0
        self.next.disabled = int(result["page"]) + 1 >= int(result["pages"])

    async def _show_page(self, interaction: discord.Interaction, page: int) -> None:
        bot = get_bot(interaction)
        result = await bot.services.registration_gate.directory(
            interaction.guild.id,
            query=str(self.result["query"]),
            page=page,
        )
        await interaction.response.edit_message(
            embed=build_registration_directory_embed(bot, result),
            view=RegistrationDirectoryView(result),
        )

    @discord.ui.button(label="Anterior", emoji="◀️", row=1)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        await self._show_page(interaction, int(self.result["page"]) - 1)

    @discord.ui.button(label="Pesquisar", emoji="🔎", style=discord.ButtonStyle.primary, row=1)
    async def search(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        await interaction.response.send_modal(
            RegistrationDirectorySearchModal(str(self.result["query"]))
        )

    @discord.ui.button(label="Próxima", emoji="▶️", row=1)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        await self._show_page(interaction, int(self.result["page"]) + 1)

    @discord.ui.button(label="Atualizar", emoji="🔄", style=discord.ButtonStyle.success, row=1)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        await self._show_page(interaction, int(self.result["page"]))


class RegistrationDirectorySearchModal(ErrorModal, title="Pesquisar cadastros"):
    query = discord.ui.TextInput(
        label="Nome, ID, Discord, patente ou unidade",
        required=False,
        max_length=100,
    )

    def __init__(self, current_query: str = "") -> None:
        super().__init__()
        self.query.default = current_query or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        bot = get_bot(interaction)
        result = await bot.services.registration_gate.directory(
            interaction.guild.id,
            query=str(self.query),
        )
        await interaction.response.edit_message(
            embed=build_registration_directory_embed(bot, result),
            view=RegistrationDirectoryView(result),
        )


class RegistrationDirectoryActionView(AdminView):
    def __init__(self, registration_id: int, *, query: str, page: int) -> None:
        super().__init__(timeout=300)
        self.registration_id = registration_id
        self.query = query
        self.page = page

    @discord.ui.button(label="Editar", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        record = await get_bot(interaction).services.registration_gate.directory_record(
            self.registration_id
        )
        if not record or int(record["guild_id"]) != interaction.guild.id:
            raise NotFoundError("Cadastro não encontrado.")
        await interaction.response.send_modal(RegistrationDirectoryEditModal(record))

    @discord.ui.button(label="Desativar", emoji="⛔", style=discord.ButtonStyle.danger)
    async def deactivate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        await interaction.response.send_modal(
            RegistrationDirectoryStateModal(self.registration_id, action="DEACTIVATE")
        )

    @discord.ui.button(label="Reabrir análise", emoji="♻️", style=discord.ButtonStyle.success)
    async def reopen(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        await interaction.response.send_modal(
            RegistrationDirectoryStateModal(self.registration_id, action="REOPEN")
        )

    @discord.ui.button(label="Voltar à lista", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        bot = get_bot(interaction)
        result = await bot.services.registration_gate.directory(
            interaction.guild.id, query=self.query, page=self.page
        )
        await interaction.response.edit_message(
            embed=build_registration_directory_embed(bot, result),
            view=RegistrationDirectoryView(result),
        )


class RegistrationDirectoryEditModal(ErrorModal, title="Editar cadastro"):
    mta_nick = discord.ui.TextInput(label="Nick BGR", min_length=1, max_length=64)
    bgr_id = discord.ui.TextInput(label="ID BGR", min_length=1, max_length=32)
    unit = discord.ui.TextInput(label="Unidade", required=False, max_length=64)
    reason = discord.ui.TextInput(
        label="Motivo obrigatório", style=discord.TextStyle.paragraph, min_length=3, max_length=500
    )

    def __init__(self, record) -> None:
        super().__init__()
        self.registration_id = int(record["id"])
        self.mta_nick.default = str(record["mta_nick"] or "") or None
        self.bgr_id.default = str(record["bgr_id"] or "") or None
        self.unit.default = str(record["unit"] or "") or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_registration_permission(
            interaction, "registration.directory.manage"
        )
        bot = get_bot(interaction)
        await interaction.response.defer(ephemeral=True)
        record = await bot.services.registration_gate.update_directory_identity(
            self.registration_id,
            actor_id=actor.id,
            mta_nick=str(self.mta_nick),
            bgr_id=str(self.bgr_id),
            unit=str(self.unit),
            reason=str(self.reason),
        )
        target = actor.guild.get_member(int(record["discord_id"]))
        warning = None
        if target:
            gate_cog = bot.get_cog("RegistrationGateSystem")
            if gate_cog and hasattr(gate_cog, "sync_member_access"):
                synced = await gate_cog.sync_member_access(target, record, actor_id=actor.id)
                if not synced:
                    warning = "A edição foi salva, mas a sincronização ficou pendente."
        detail = await bot.services.registration_gate.directory_record(self.registration_id)
        await interaction.edit_original_response(
            embed=build_registration_directory_record_embed(bot, detail),
            view=RegistrationDirectoryActionView(self.registration_id, query="", page=0),
        )
        if warning:
            await interaction.followup.send(f"⚠️ {warning}", ephemeral=True)


class RegistrationDirectoryStateModal(ErrorModal, title="Alterar estado do cadastro"):
    reason = discord.ui.TextInput(
        label="Motivo obrigatório", style=discord.TextStyle.paragraph, min_length=3, max_length=500
    )
    confirmation = discord.ui.TextInput(label="Confirmação", min_length=7, max_length=9)

    def __init__(self, registration_id: int, *, action: str) -> None:
        super().__init__()
        self.registration_id = registration_id
        self.action = action
        literal = "DESATIVAR" if action == "DEACTIVATE" else "REABRIR"
        self.confirmation.label = f"Digite {literal} para confirmar"
        self.confirmation.placeholder = literal
        self.confirmation.min_length = len(literal)
        self.confirmation.max_length = len(literal)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_registration_permission(
            interaction, "registration.directory.manage"
        )
        literal = "DESATIVAR" if self.action == "DEACTIVATE" else "REABRIR"
        if str(self.confirmation).strip().upper() != literal:
            raise ValidationError(f"Digite {literal} exatamente para confirmar.")
        bot = get_bot(interaction)
        await interaction.response.defer(ephemeral=True)
        if self.action == "DEACTIVATE":
            record = await bot.services.registration_gate.deactivate_directory_registration(
                self.registration_id,
                actor_id=actor.id,
                reason=str(self.reason),
            )
            target = actor.guild.get_member(int(record["discord_id"]))
            if target:
                gate_cog = bot.get_cog("RegistrationGateSystem")
                if gate_cog and hasattr(gate_cog, "sync_member_access"):
                    await gate_cog.sync_member_access(target, record, actor_id=actor.id)
        else:
            record = await bot.services.registration_gate.reopen_for_review(
                self.registration_id,
                actor_id=actor.id,
                reason=str(self.reason),
            )
        detail = await bot.services.registration_gate.directory_record(self.registration_id)
        await interaction.edit_original_response(
            embed=build_registration_directory_record_embed(bot, detail),
            view=RegistrationDirectoryActionView(self.registration_id, query="", page=0),
        )


class RankRegistrationComplianceView(AdminView):
    def __init__(self, result: dict) -> None:
        super().__init__(timeout=300)
        self.result = result
        self.previous.disabled = int(result["page"]) <= 0
        self.next.disabled = int(result["page"]) + 1 >= int(result["pages"])

    async def _show(self, interaction: discord.Interaction, page: int) -> None:
        bot = get_bot(interaction)
        result = await bot.services.registration_gate.rank_compliance_directory(
            interaction.guild.id,
            page=page,
        )
        await interaction.response.edit_message(
            embed=build_rank_compliance_embed(bot, result),
            view=RankRegistrationComplianceView(result),
        )

    @discord.ui.button(label="Anterior", emoji="◀️")
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        await self._show(interaction, int(self.result["page"]) - 1)

    @discord.ui.button(label="Processar agora", emoji="⚙️", style=discord.ButtonStyle.danger)
    async def process(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        cog = get_bot(interaction).get_cog("RegistrationGateSystem")
        if cog is None or not hasattr(cog, "process_rank_compliance"):
            raise NotFoundError("O processador de regularização não está disponível.")
        await interaction.response.defer(ephemeral=True)
        outcome = await cog.process_rank_compliance(interaction.guild)
        result = await get_bot(
            interaction
        ).services.registration_gate.rank_compliance_directory(interaction.guild.id)
        embed = build_rank_compliance_embed(get_bot(interaction), result)
        embed.add_field(
            name="Último processamento",
            value=(
                f"Avisos: **{outcome['notified']}** • "
                f"Patentes removidas: **{outcome['expired']}** • "
                f"Falhas: **{outcome['failed']}**"
            ),
            inline=False,
        )
        await interaction.edit_original_response(
            embed=embed,
            view=RankRegistrationComplianceView(result),
        )

    @discord.ui.button(label="Próxima", emoji="▶️")
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        await self._show(interaction, int(self.result["page"]) + 1)

    @discord.ui.button(label="Atualizar", emoji="🔄", style=discord.ButtonStyle.success)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.directory.manage")
        await self._show(interaction, int(self.result["page"]))


class GateRegistrationSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Escolha um cadastro da Portaria",
            options=[
                discord.SelectOption(
                    label=f"CAD-{int(row['id']):04d} • {row['mta_nick'] or 'Sem nick'}"[:100],
                    value=str(row["id"]),
                    description=f"{row['status']} • ID {row['bgr_id'] or 'não informado'}"[:100],
                    emoji="⚠️" if row["status"] == "REQUIRES_REVIEW" else "🪪",
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await require_registration_permission(interaction, "registration.view")
        record = await get_bot(interaction).services.registration_gate.get(int(self.values[0]))
        if not record or int(record["guild_id"]) != interaction.guild.id:
            raise NotFoundError("Cadastro não encontrado.")
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title=f"🪪 CAD-{int(record['id']):04d} • Revisão de identidade",
            description=(
                f"**Discord:** <@{record['discord_id']}>\n"
                f"**Nick BGR:** {record['mta_nick'] or '—'}\n"
                f"**ID BGR:** {record['bgr_id'] or '—'}\n"
                f"**Situação:** `{record['status']}`\n"
                f"**Conflito:** `{record['conflict_code'] or 'NENHUM'}`\n"
                f"**Origem:** `{record['source']}`"
            ),
        )
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=GateRegistrationDecisionView(int(record["id"])),
        )


class GateRegistrationListView(AdminView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(GateRegistrationSelect(rows))


class GateRegistrationDecisionView(AdminView):
    def __init__(self, registration_id: int) -> None:
        super().__init__(timeout=300)
        self.registration_id = registration_id

    @discord.ui.button(label="Aprovar cadastro", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.review")
        await interaction.response.send_modal(
            GateApprovalModal(self.registration_id, action="APPROVE")
        )

    @discord.ui.button(label="Vincular perfil", emoji="🔗", style=discord.ButtonStyle.primary)
    async def link(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.review")
        await interaction.response.send_message(
            "Selecione o usuário Discord que corresponde ao perfil existente:",
            view=GateLinkMemberView(self.registration_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Corrigir ID", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def correct(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.review")
        await interaction.response.send_modal(GateCorrectIdModal(self.registration_id))

    @discord.ui.button(label="Negar", emoji="⛔", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await require_registration_permission(interaction, "registration.review")
        await interaction.response.send_modal(
            GateApprovalModal(self.registration_id, action="DENY")
        )


class GateApprovalModal(ErrorModal, title="Decisão da Portaria Digital"):
    reason = discord.ui.TextInput(
        label="Motivo obrigatório", style=discord.TextStyle.paragraph, max_length=500
    )

    def __init__(self, registration_id: int, *, action: str) -> None:
        super().__init__()
        self.registration_id = registration_id
        self.action = action

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = await require_registration_permission(interaction, "registration.review")
        bot = get_bot(interaction)
        record = await bot.services.registration_gate.get(self.registration_id)
        if not record or int(record["guild_id"]) != actor.guild.id:
            raise NotFoundError("Cadastro não encontrado.")
        if self.action == "APPROVE":
            target = actor.guild.get_member(int(record["discord_id"]))
            if target is None:
                raise NotFoundError("O solicitante não está mais no servidor.")
            can_confirm_existing = bool(
                record["member_id"]
                and (
                    not record["conflict_member_id"]
                    or int(record["conflict_member_id"]) == int(record["member_id"])
                )
            )
            if can_confirm_existing:
                updated = await bot.services.registration_gate.link_existing_member(
                    self.registration_id,
                    member_id=int(record["member_id"]),
                    reviewer_id=actor.id,
                    reason=str(self.reason),
                )
            else:
                updated = await bot.services.registration_gate.approve_new_member(
                    self.registration_id,
                    reviewer_id=actor.id,
                    reason=str(self.reason),
                    discord_nick=target.display_name,
                )
            gate_cog = bot.get_cog("RegistrationGateSystem")
            synced = bool(
                gate_cog
                and hasattr(gate_cog, "sync_member_access")
                and await gate_cog.sync_member_access(target, updated, actor_id=actor.id)
            )
            message = (
                "✅ Cadastro aprovado e acesso sincronizado."
                if synced
                else "✅ Cadastro aprovado. A sincronização permanece pendente e foi alertada."
            )
        else:
            updated = await bot.services.registration_gate.reject(
                self.registration_id, reviewer_id=actor.id, reason=str(self.reason)
            )
            target = actor.guild.get_member(int(updated["discord_id"]))
            gate_cog = bot.get_cog("RegistrationGateSystem")
            if target and gate_cog and hasattr(gate_cog, "sync_member_access"):
                await gate_cog.sync_member_access(target, updated, actor_id=actor.id)
            message = "⛔ Cadastro negado e acesso restritivo reconciliado."
        gate_cog = bot.get_cog("RegistrationGateSystem")
        if gate_cog and hasattr(gate_cog, "finalize_registration_review"):
            try:
                await gate_cog.finalize_registration_review(
                    actor.guild, updated, actor_id=actor.id
                )
            except Exception:
                LOGGER.exception("Falha ao arquivar cadastro da Portaria %s", updated["id"])
                message += " O arquivamento será repetido automaticamente."
        await interaction.followup.send(message, ephemeral=True)


class GateCorrectIdModal(ErrorModal, title="Corrigir ID BGR"):
    bgr_id = discord.ui.TextInput(label="Novo ID BGR", min_length=1, max_length=32)
    reason = discord.ui.TextInput(
        label="Motivo", style=discord.TextStyle.paragraph, max_length=500
    )

    def __init__(self, registration_id: int) -> None:
        super().__init__()
        self.registration_id = registration_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = await require_registration_permission(interaction, "registration.review")
        bot = get_bot(interaction)
        updated = await bot.services.registration_gate.correct_bgr_id(
            self.registration_id,
            bgr_id=str(self.bgr_id),
            reviewer_id=actor.id,
            reason=str(self.reason),
        )
        gate_cog = bot.get_cog("RegistrationGateSystem")
        if gate_cog and hasattr(gate_cog, "publish_registration_for_review"):
            try:
                await gate_cog.publish_registration_for_review(actor.guild, updated)
            except Exception:
                LOGGER.exception("Falha ao atualizar cadastro da Portaria %s", updated["id"])
        await interaction.followup.send(
            "✏️ ID corrigido. O cadastro retornou à fila pendente.", ephemeral=True
        )


class GateLinkMemberSelect(discord.ui.UserSelect):
    def __init__(self, registration_id: int) -> None:
        super().__init__(placeholder="Selecione o perfil Discord", min_values=1, max_values=1)
        self.registration_id = registration_id

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_registration_permission(interaction, "registration.review")
        selected = self.values[0]
        member = await get_bot(interaction).services.members.get(actor.guild.id, selected.id)
        if not member:
            raise NotFoundError("O usuário selecionado não possui perfil de membro existente.")
        await interaction.response.send_modal(
            GateLinkReasonModal(self.registration_id, int(member["id"]))
        )


class GateLinkMemberView(AdminView):
    def __init__(self, registration_id: int) -> None:
        super().__init__(timeout=300)
        self.add_item(GateLinkMemberSelect(registration_id))


class GateLinkReasonModal(ErrorModal, title="Vincular identidade existente"):
    reason = discord.ui.TextInput(
        label="Motivo obrigatório", style=discord.TextStyle.paragraph, max_length=500
    )

    def __init__(self, registration_id: int, member_id: int) -> None:
        super().__init__()
        self.registration_id = registration_id
        self.member_id = member_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = await require_registration_permission(interaction, "registration.review")
        bot = get_bot(interaction)
        record = await bot.services.registration_gate.link_existing_member(
            self.registration_id,
            member_id=self.member_id,
            reviewer_id=actor.id,
            reason=str(self.reason),
        )
        target = actor.guild.get_member(int(record["discord_id"]))
        gate_cog = bot.get_cog("RegistrationGateSystem")
        synced = bool(
            target
            and gate_cog
            and hasattr(gate_cog, "sync_member_access")
            and await gate_cog.sync_member_access(target, record, actor_id=actor.id)
        )
        if gate_cog and hasattr(gate_cog, "finalize_registration_review"):
            try:
                await gate_cog.finalize_registration_review(
                    actor.guild, record, actor_id=actor.id
                )
            except Exception:
                LOGGER.exception("Falha ao arquivar cadastro da Portaria %s", record["id"])
        await interaction.followup.send(
            "🔗 Identidade vinculada. "
            + ("Acesso sincronizado." if synced else "Sincronização pendente/alertada."),
            ephemeral=True,
        )


class GateRoleSettingSelect(discord.ui.RoleSelect):
    def __init__(self, setting_key: str, placeholder: str) -> None:
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_registration_permission(interaction, "registration.settings")
        await get_bot(interaction).services.registration_gate.set_configuration(
            actor.guild.id,
            {self.setting_key: self.values[0].id},
            actor_id=actor.id,
        )
        await interaction.response.send_message(
            f"✅ Cargo {self.values[0].mention} configurado.", ephemeral=True
        )


class GateChannelSettingSelect(discord.ui.ChannelSelect):
    def __init__(self, setting_key: str, placeholder: str) -> None:
        super().__init__(
            placeholder=placeholder,
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_registration_permission(interaction, "registration.settings")
        channel = self.values[0]
        await get_bot(interaction).services.registration_gate.set_configuration(
            actor.guild.id,
            {self.setting_key: channel.id},
            actor_id=actor.id,
        )
        await interaction.response.send_message(
            f"✅ Canal <#{channel.id}> configurado.", ephemeral=True
        )


class RegistrationSettingsView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(GateRoleSettingSelect("unregistered_role_id", "Cargo não cadastrado"))
        self.add_item(GateRoleSettingSelect("candidate_role_id", "Cargo de candidato"))
        self.add_item(GateRoleSettingSelect("member_role_id", "Cargo base de membro"))
        self.add_item(
            GateChannelSettingSelect("registration_panel_channel_id", "Canal da Portaria")
        )
        self.add_item(
            GateChannelSettingSelect("registration_support_channel_id", "Canal de suporte")
        )


class GateCategorySettingSelect(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Categoria de recepção / onboarding",
            channel_types=[discord.ChannelType.category],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_registration_permission(interaction, "registration.settings")
        category = self.values[0]
        await get_bot(interaction).services.registration_gate.set_configuration(
            actor.guild.id,
            {"registration_onboarding_category_id": category.id},
            actor_id=actor.id,
        )
        await interaction.response.send_message(
            f"✅ Categoria <#{category.id}> configurada.", ephemeral=True
        )


class GateBypassRoleSelect(discord.ui.RoleSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Alternar cargo de bypass", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_registration_permission(interaction, "registration.bypass.manage")
        bot = get_bot(interaction)
        current = {
            int(value)
            for value in await bot.services.settings.get(
                actor.guild.id, "registration_bypass_role_ids", []
            )
        }
        role_id = self.values[0].id
        current.symmetric_difference_update({role_id})
        await bot.services.registration_gate.set_configuration(
            actor.guild.id,
            {"registration_bypass_role_ids": sorted(current)},
            actor_id=actor.id,
        )
        await interaction.response.send_message(
            f"🔐 Bypass de {self.values[0].mention} "
            f"{'ativado' if role_id in current else 'removido'}.",
            ephemeral=True,
        )


class GateBypassUserSelect(discord.ui.UserSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Alternar conta de bypass", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        actor = await require_registration_permission(interaction, "registration.bypass.manage")
        bot = get_bot(interaction)
        current = {
            int(value)
            for value in await bot.services.settings.get(
                actor.guild.id, "registration_bypass_user_ids", []
            )
        }
        user_id = self.values[0].id
        current.symmetric_difference_update({user_id})
        await bot.services.registration_gate.set_configuration(
            actor.guild.id,
            {"registration_bypass_user_ids": sorted(current)},
            actor_id=actor.id,
        )
        await interaction.response.send_message(
            f"🔐 Bypass de <@{user_id}> {'ativado' if user_id in current else 'removido'}.",
            ephemeral=True,
        )


class RegistrationSecuritySettingsView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(GateCategorySettingSelect())
        self.add_item(GateBypassRoleSelect())
        self.add_item(GateBypassUserSelect())

    @discord.ui.button(label="Ativar/desativar gate", emoji="🛡️", style=discord.ButtonStyle.danger)
    async def toggle_gate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_registration_permission(interaction, "registration.settings")
        bot = get_bot(interaction)
        current = bool(
            await bot.services.settings.get(actor.guild.id, "registration_gate_enabled", False)
        )
        if not current:
            cog = bot.get_cog("RegistrationGateSystem")
            if cog is None or not hasattr(cog, "validate_access"):
                raise NotFoundError("O validador da Portaria não está disponível.")
            result = await cog.validate_access(actor.guild)
            if result["leaks"] or result["unclassified"]:
                raise ValidationError(
                    "Ativação bloqueada: corrija exposições e recursos sem classificação."
                )
        await bot.services.registration_gate.set_configuration(
            actor.guild.id,
            {"registration_gate_enabled": not current},
            actor_id=actor.id,
        )
        if not current:
            await bot.services.settings.set(
                actor.guild.id, "registration_gate_activated_at", utc_now_ms(), actor.id
            )
        await interaction.response.send_message(
            f"🛡️ Portaria Digital {'ATIVADA' if not current else 'DESATIVADA'}.",
            ephemeral=True,
        )

    @discord.ui.button(label="Alternar DM", emoji="✉️", style=discord.ButtonStyle.secondary)
    async def toggle_dm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor = await require_registration_permission(interaction, "registration.settings")
        bot = get_bot(interaction)
        current = bool(
            await bot.services.settings.get(actor.guild.id, "registration_dm_enabled", True)
        )
        await bot.services.registration_gate.set_configuration(
            actor.guild.id,
            {"registration_dm_enabled": not current},
            actor_id=actor.id,
        )
        await interaction.response.send_message(
            f"✉️ DM de boas-vindas {'ativada' if not current else 'desativada'}.",
            ephemeral=True,
        )



def build_ranking_landing_embed(bot: ChoqueBot) -> discord.Embed:
    return branded_embed(
        bot.config.branding,
        title="🏆 Ranking de Horas • CHOQUE - BGR",
        description=(
            "Consulte o ranking atualizado por período. Intervalos fora de calls autorizadas "
            "e sessões em revisão não são contabilizados."
        ),
    )


async def build_ranking_embed(bot: ChoqueBot, guild: discord.Guild, period: str) -> discord.Embed:
    labels = {"today": "Hoje", "week": "Semana", "month": "Mês", "total": "Total"}
    timezone_name = await bot.services.settings.get(guild.id, "timezone")
    if period == "total":
        bounds = (0, utc_now_ms())
    else:
        bounds = period_bounds(period, timezone_name)
    rows = await bot.services.personnel.ranking(guild.id, *bounds, limit=20)
    lines = []
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for position, row in enumerate(rows, start=1):
        lines.append(
            f"{medals.get(position, f'`{position:02d}`')} <@{row['discord_id']}> • "
            f"**{format_duration(int(row['total_ms']))}**\n"
            f"└ {row['rank_name'] or 'Sem patente'} • `{row['status']}`"
        )
    embed = branded_embed(
        bot.config.branding,
        title=f"🏆 Ranking de Horas • {labels[period]}",
        description="\n".join(lines) or "Nenhum membro com horas registradas neste período.",
    )
    embed.add_field(
        name="Período",
        value=f"{discord_timestamp(bounds[0], 'd') if bounds[0] else 'Início'} → Agora",
        inline=False,
    )
    return embed


def build_personnel_area_embed(
    bot: ChoqueBot,
    *,
    title: str,
    description: str,
    actions: tuple[str, ...],
) -> discord.Embed:
    embed = branded_embed(bot.config.branding, title=title, description=description)
    embed.add_field(
        name="Ações disponíveis",
        value="\n".join(actions),
        inline=False,
    )
    embed.add_field(
        name="Como usar",
        value="Escolha uma ação abaixo. Todas as respostas administrativas são privadas.",
        inline=False,
    )
    return embed


class PersonnelCategoryView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="Voltar ao início", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=await build_admin_embed(get_bot(interaction), interaction.guild),
            view=PersonnelAdminView(),
        )


class PersonnelEffectiveView(PersonnelCategoryView):
    @discord.ui.button(label="Portaria e cadastros", emoji="🛡️", style=discord.ButtonStyle.primary)
    async def applications(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await get_bot(interaction).services.modules.require_enabled(
            interaction.guild.id, "REGISTRATION"
        )
        await interaction.response.send_message(
            embed=await build_registration_admin_embed(get_bot(interaction), interaction.guild),
            view=RegistrationAdminView(),
            ephemeral=True,
        )

    @discord.ui.button(label="Carreira e patentes", emoji="📈", style=discord.ButtonStyle.primary)
    async def career(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("CareerCommands")
        if cog is None:
            raise NotFoundError("O módulo de carreira não está disponível.")
        await cog.open_admin(interaction)

    @discord.ui.button(label="Histórico do membro", emoji="📚", style=discord.ButtonStyle.secondary)
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "Selecione o membro para consultar o histórico:",
            view=TargetMemberView("HISTORY"),
            ephemeral=True,
        )

    @discord.ui.button(label="Ranking", emoji="🏆", style=discord.ButtonStyle.secondary)
    async def ranking(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=build_ranking_landing_embed(get_bot(interaction)),
            view=RankingPeriodView(),
            ephemeral=True,
        )

    @discord.ui.button(label="Atividade", emoji="📊", style=discord.ButtonStyle.secondary)
    async def activity(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("ActivityCommands")
        if cog is None:
            raise NotFoundError("O módulo de atividade não está disponível.")
        await cog.open_admin(interaction)


class PersonnelProcessesView(PersonnelCategoryView):
    @discord.ui.button(label="Solicitações", emoji="📥", style=discord.ButtonStyle.primary)
    async def requests(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("RequestCommands")
        if cog is None:
            raise NotFoundError("O módulo de solicitações não está disponível.")
        await cog.open_admin(interaction)

    @discord.ui.button(label="Treinamentos", emoji="🎓", style=discord.ButtonStyle.primary)
    async def training(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("TrainingCommands")
        if cog is None:
            raise NotFoundError("O módulo de treinamentos não está disponível.")
        await cog.open_admin(interaction)

    @discord.ui.button(label="Atendimentos", emoji="🎫", style=discord.ButtonStyle.secondary)
    async def tickets(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("TicketCommands")
        if cog is None:
            raise NotFoundError("O módulo de atendimento não está disponível.")
        await cog.open_admin(interaction)


class PersonnelServiceView(PersonnelCategoryView):
    @discord.ui.button(label="Revisões de ponto", emoji="⏱️", style=discord.ButtonStyle.danger)
    async def shift_review(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("ShiftCommands")
        if cog is None:
            raise NotFoundError("O módulo de ponto não está disponível.")
        await cog.open_invalidated_admin(interaction)

    @discord.ui.button(label="Operações e patrulhas", emoji="🛡️", style=discord.ButtonStyle.primary)
    async def operations(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("OperationsCommands")
        if cog is None:
            raise NotFoundError("A Central de Operações não está disponível.")
        await cog.open_admin(interaction)


class PersonnelDisciplineView(PersonnelCategoryView):
    @discord.ui.button(label="Gestão disciplinar", emoji="⚖️", style=discord.ButtonStyle.primary)
    async def discipline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("DisciplineCommands")
        if cog is None:
            raise NotFoundError("O módulo disciplinar não está disponível.")
        await cog.open_admin(interaction)

    @discord.ui.button(label="Exonerar membro", emoji="🚪", style=discord.ButtonStyle.danger)
    async def dismiss(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("DisciplineCommands")
        if cog is None or not hasattr(cog, "open_exoneration"):
            raise NotFoundError("O fluxo de exoneração não está disponível.")
        await cog.open_exoneration(interaction)


class PersonnelAdminView(AdminView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Efetivo",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        custom_id="choque:personnel:area:effective:v1",
    )
    async def effective(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=build_personnel_area_embed(
                get_bot(interaction),
                title="👥 Efetivo e identidade",
                description="Cadastros, carreira, histórico, ranking e atividade do efetivo.",
                actions=(
                    "🛡️ Portaria e cadastros",
                    "📈 Carreira e patentes",
                    "📚 Histórico do membro",
                    "🏆 Ranking e 📊 Atividade",
                ),
            ),
            view=PersonnelEffectiveView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Disciplina",
        emoji="⚖️",
        style=discord.ButtonStyle.danger,
        custom_id="choque:personnel:area:discipline:v1",
    )
    async def discipline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=build_personnel_area_embed(
                get_bot(interaction),
                title="⚖️ Disciplina e exoneração",
                description="Ocorrências, medidas disciplinares e desligamento do efetivo.",
                actions=(
                    "⚖️ Gestão disciplinar completa",
                    "🚪 Exonerar sem expulsar do Discord",
                ),
            ),
            view=PersonnelDisciplineView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Processos",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:personnel:area:processes:v1",
    )
    async def processes(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=build_personnel_area_embed(
                get_bot(interaction),
                title="📋 Processos administrativos",
                description="Filas que exigem análise e acompanhamento do Comando.",
                actions=("📥 Solicitações", "🎓 Treinamentos", "🎫 Atendimentos"),
            ),
            view=PersonnelProcessesView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Serviço e operações",
        emoji="🎯",
        style=discord.ButtonStyle.primary,
        custom_id="choque:personnel:area:service:v1",
    )
    async def service(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=build_personnel_area_embed(
                get_bot(interaction),
                title="🎯 Serviço e operações",
                description="Revisões de ponto, patrulhas e controle operacional.",
                actions=("⏱️ Revisões de ponto", "🛡️ Operações e patrulhas"),
            ),
            view=PersonnelServiceView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Tags",
        emoji="🏷️",
        style=discord.ButtonStyle.primary,
        custom_id="choque:personnel:tags:v1",
    )
    async def tags(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog = get_bot(interaction).get_cog("TagCommands")
        if cog is None or not hasattr(cog, "open_admin"):
            raise NotFoundError("A Central de Tags não está disponível.")
        await cog.open_admin(interaction)

    @discord.ui.button(
        label="Atualizar resumo",
        emoji="🔄",
        style=discord.ButtonStyle.success,
        custom_id="choque:personnel:refresh:v1",
    )
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=await build_admin_embed(get_bot(interaction), interaction.guild), view=self
        )


class TargetMemberSelect(discord.ui.UserSelect):
    def __init__(self, mode: str) -> None:
        self.mode = mode
        super().__init__(placeholder="Escolha um membro", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        target = interaction.guild.get_member(self.values[0].id) if interaction.guild else None
        if not target:
            raise NotFoundError("O membro selecionado não está mais no servidor.")
        bot = get_bot(interaction)
        row = await bot.services.members.get(interaction.guild.id, target.id)
        if not row:
            raise NotFoundError("O membro selecionado ainda não possui cadastro aprovado.")
        if self.mode == "RANK":
            await interaction.response.edit_message(
                content=(
                    f"Membro: {target.mention}\n"
                    f"Patente atual: **{row['rank_name'] or 'Não definida'}**"
                ),
                view=RankActionView(target.id),
            )
        elif self.mode == "PUNISHMENT":
            await interaction.response.edit_message(
                content=f"Administrando punições de {target.mention} • status `{row['status']}`",
                view=PunishmentActionView(target.id),
            )
        else:
            await interaction.response.edit_message(
                content=None,
                embed=await build_history_embed(bot, interaction.guild, target),
                view=None,
            )


class TargetMemberView(AdminView):
    def __init__(self, mode: str) -> None:
        super().__init__(timeout=300)
        self.add_item(TargetMemberSelect(mode))


class RankActionView(AdminView):
    def __init__(self, target_id: int) -> None:
        super().__init__(timeout=300)
        self.target_id = target_id

    @discord.ui.button(label="Promover", emoji="📈", style=discord.ButtonStyle.success)
    async def promote(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            RankChangeModal(self.target_id, PersonnelActionType.PROMOTION)
        )

    @discord.ui.button(label="Rebaixar", emoji="📉", style=discord.ButtonStyle.danger)
    async def demote(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            RankChangeModal(self.target_id, PersonnelActionType.DEMOTION)
        )


class RankChangeModal(ErrorModal, title="Movimentação de patente"):
    reason = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, target_id: int, action: PersonnelActionType) -> None:
        super().__init__()
        self.target_id = target_id
        self.action = action

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        target = actor.guild.get_member(self.target_id)
        if not target:
            raise NotFoundError("O membro não está mais no servidor.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        bot = get_bot(interaction)
        result = await bot.services.personnel.change_rank(
            actor.guild.id, target.id, self.action, actor.id, str(self.reason)
        )
        warning = await sync_rank_to_discord(bot, actor.guild, target, result, actor.id)
        action_label = "promovido" if self.action is PersonnelActionType.PROMOTION else "rebaixado"
        suffix = f"\n⚠️ {warning}" if warning else ""
        await interaction.followup.send(
            f"✅ {target.mention} {action_label} para **{result['to_rank_name']}**.{suffix}",
            ephemeral=True,
        )


class PunishmentActionView(AdminView):
    def __init__(self, target_id: int) -> None:
        super().__init__(timeout=300)
        self.target_id = target_id

    async def open_modal(self, interaction: discord.Interaction, kind: PunishmentType) -> None:
        await interaction.response.send_modal(PunishmentModal(self.target_id, kind))

    @discord.ui.button(label="Advertir", emoji="⚠️", style=discord.ButtonStyle.secondary)
    async def warn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_modal(interaction, PunishmentType.WARNING)

    @discord.ui.button(label="Suspender", emoji="⏸️", style=discord.ButtonStyle.danger)
    async def suspend(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_modal(interaction, PunishmentType.SUSPENSION)

    @discord.ui.button(label="Desligar", emoji="🚫", style=discord.ButtonStyle.danger)
    async def dismiss(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.open_modal(interaction, PunishmentType.DISMISSAL)

    @discord.ui.button(label="Revogar", emoji="↩️", style=discord.ButtonStyle.primary)
    async def revoke(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rows = await get_bot(interaction).services.personnel.active_punishments(
            interaction.guild.id, self.target_id
        )
        if not rows:
            raise NotFoundError("Esse membro não possui punições ativas.")
        await interaction.response.edit_message(
            content="Selecione a punição que será revogada:",
            view=ActivePunishmentView(rows),
        )


class PunishmentModal(ErrorModal, title="Aplicar punição"):
    reason = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=500)
    duration = discord.ui.TextInput(
        label="Duração em dias (somente suspensão)", required=False, max_length=3
    )

    def __init__(self, target_id: int, kind: PunishmentType) -> None:
        super().__init__()
        self.target_id = target_id
        self.kind = kind

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        target = actor.guild.get_member(self.target_id)
        if not target:
            raise NotFoundError("O membro não está mais no servidor.")
        duration_days = None
        if self.kind is PunishmentType.SUSPENSION:
            if not str(self.duration).strip().isdigit():
                raise ValidationError("Informe a duração numérica da suspensão em dias.")
            duration_days = int(str(self.duration).strip())
        await interaction.response.defer(ephemeral=True, thinking=True)
        bot = get_bot(interaction)
        result = await bot.services.personnel.apply_punishment(
            actor.guild.id,
            target.id,
            self.kind,
            actor.id,
            str(self.reason),
            duration_days=duration_days,
        )
        if self.kind in {PunishmentType.SUSPENSION, PunishmentType.DISMISSAL}:
            await bot.services.shifts.finalize_role_loss(
                actor.guild.id, target.id, reason=f"PUNISHMENT_{self.kind.value}"
            )
        warning = (
            await sync_member_status_roles(
                bot, actor.guild, target, str(result["status"])
            )
            if self.kind in {PunishmentType.SUSPENSION, PunishmentType.DISMISSAL}
            else None
        )
        suffix = f"\n⚠️ {warning}" if warning else ""
        await interaction.followup.send(
            f"✅ Punição **{result['type']}** aplicada a {target.mention}.{suffix}", ephemeral=True
        )


class ActivePunishmentSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Escolha a punição ativa",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['punishment_type']}",
                    value=str(row["id"]),
                    description=str(row["reason"])[:100],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RevokePunishmentModal(int(self.values[0])))


class ActivePunishmentView(AdminView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(ActivePunishmentSelect(rows))


class RevokePunishmentModal(ErrorModal, title="Revogar punição"):
    reason = discord.ui.TextInput(
        label="Motivo da revogação", style=discord.TextStyle.paragraph, max_length=500
    )

    def __init__(self, punishment_id: int) -> None:
        super().__init__()
        self.punishment_id = punishment_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await get_bot(interaction).services.personnel.revoke_punishment(
            actor.guild.id, self.punishment_id, actor.id, str(self.reason)
        )
        await interaction.followup.send(
            f"✅ Punição **#{self.punishment_id}** revogada. Status atual: "
            f"`{result['member_status']}`.",
            ephemeral=True,
        )


class ApplicationSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Escolha um cadastro pendente",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['mta_nick']}"[:100],
                    value=str(row["id"]),
                    description=f"Discord ID {row['discord_id']}",
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        application = await get_bot(interaction).services.members.get_application(
            int(self.values[0])
        )
        if not application or application["status"] != "PENDING":
            raise NotFoundError("A solicitação não está mais pendente.")
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title=f"Cadastro pendente #{application['id']}",
            description=(
                f"**Membro:** <@{application['discord_id']}>\n"
                f"**Nick MTA:** {application['mta_nick']}\n"
                f"**Personagem:** {application['character_id'] or '—'}\n"
                f"**Unidade:** {application['unit'] or '—'}\n"
                f"**Recrutador:** {application['recruiter'] or '—'}"
            ),
        )
        await interaction.response.edit_message(
            content=None, embed=embed, view=ApplicationDecisionView(int(application["id"]))
        )


class ApplicationListView(AdminView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(ApplicationSelect(rows))


class ApplicationDecisionView(AdminView):
    def __init__(self, application_id: int) -> None:
        super().__init__(timeout=300)
        self.application_id = application_id

    @discord.ui.button(label="Aprovar", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ApplicationDecisionModal(self.application_id, True))

    @discord.ui.button(label="Negar", emoji="❌", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ApplicationDecisionModal(self.application_id, False))


class ApplicationDecisionModal(ErrorModal, title="Analisar cadastro"):
    reason = discord.ui.TextInput(
        label="Motivo da decisão",
        style=discord.TextStyle.paragraph,
        default="Análise administrativa",
        max_length=500,
    )

    def __init__(self, application_id: int, approved: bool) -> None:
        super().__init__()
        self.application_id = application_id
        self.approved = approved

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        application = await get_bot(interaction).services.members.get_application(
            self.application_id
        )
        if not application or int(application["guild_id"]) != actor.guild.id:
            raise NotFoundError("Solicitação não encontrada.")
        target = actor.guild.get_member(int(application["discord_id"]))
        if not target:
            raise NotFoundError("O solicitante não está mais no servidor.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        bot = get_bot(interaction)
        initial_rank_id = (
            await bot.services.rank_sync.initial_rank_id(
                actor.guild.id, {int(role.id) for role in target.roles}
            )
            if self.approved
            else None
        )
        await bot.services.members.review_application(
            self.application_id,
            actor.id,
            self.approved,
            str(self.reason),
            target.display_name,
            initial_rank_id,
        )
        warning = (
            await sync_registered_member(bot, actor.guild, target, actor.id)
            if self.approved
            else None
        )
        member_cog = bot.get_cog("MemberCommands")
        if member_cog is not None:
            await member_cog.finalize_application_review(
                actor.guild,
                self.application_id,
                actor.id,
            )
        personnel_cog = bot.get_cog("PersonnelCommands")
        if isinstance(personnel_cog, PersonnelCommands):
            await personnel_cog.refresh_admin_panel(actor.guild)
        result = "aprovado" if self.approved else "negado"
        suffix = f"\n⚠️ {warning}" if warning else ""
        await interaction.followup.send(
            f"✅ Cadastro **#{self.application_id}** {result}.{suffix}", ephemeral=True
        )


class AbsenceRequestModal(ErrorModal, title="Solicitar afastamento"):
    start_date = discord.ui.TextInput(label="Data inicial (DD/MM/AAAA)", placeholder="25/08/2026")
    end_date = discord.ui.TextInput(label="Último dia (DD/MM/AAAA)", placeholder="31/08/2026")
    reason = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=500)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            raise ValidationError("Use este painel dentro do servidor.")
        bot = get_bot(interaction)
        timezone_name = await bot.services.settings.get(interaction.guild.id, "timezone")
        zone = ZoneInfo(timezone_name)
        try:
            starts = datetime.strptime(str(self.start_date), "%d/%m/%Y").replace(
                tzinfo=zone, hour=0, minute=0, second=0
            )
            ends = datetime.combine(
                datetime.strptime(str(self.end_date), "%d/%m/%Y").date(), time.max, tzinfo=zone
            )
        except ValueError as exc:
            raise ValidationError("Use datas válidas no formato DD/MM/AAAA.") from exc
        await interaction.response.defer(ephemeral=True, thinking=True)
        absence_id = await bot.services.personnel.submit_absence(
            interaction.guild.id,
            interaction.user.id,
            int(starts.timestamp() * 1000),
            int(ends.timestamp() * 1000),
            str(self.reason),
        )
        await notify_absence_request(bot, interaction.guild, absence_id)
        await interaction.followup.send(
            f"✅ Solicitação de afastamento **#{absence_id}** enviada para análise.",
            ephemeral=True,
        )


class AbsencePanelView(ErrorView):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Solicitar afastamento",
        emoji="📝",
        style=discord.ButtonStyle.primary,
        custom_id="choque:absence:request:v1",
    )
    async def request(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(AbsenceRequestModal())

    @discord.ui.button(
        label="Minha situação",
        emoji="🔎",
        style=discord.ButtonStyle.secondary,
        custom_id="choque:absence:status:v1",
    )
    async def status(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild:
            raise ValidationError("Use este painel dentro do servidor.")
        rows = await get_bot(interaction).services.personnel.absences_for_member(
            interaction.guild.id, interaction.user.id
        )
        lines = [
            f"**#{row['id']}** `{row['status']}` • {discord_timestamp(row['starts_at'], 'd')} "
            f"até {discord_timestamp(row['ends_at'], 'd')}"
            for row in rows
        ]
        await interaction.response.send_message(
            "\n".join(lines) or "Você ainda não possui solicitações de afastamento.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Cancelar pendente",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id="choque:absence:cancel:v1",
    )
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild:
            raise ValidationError("Use este painel dentro do servidor.")
        absence_id = await get_bot(interaction).services.personnel.cancel_absence(
            interaction.guild.id, interaction.user.id
        )
        await interaction.response.send_message(
            f"✅ Solicitação **#{absence_id}** cancelada.", ephemeral=True
        )


async def notify_absence_request(bot: ChoqueBot, guild: discord.Guild, absence_id: int) -> None:
    channel_id = await bot.services.settings.get(guild.id, "personnel_admin_channel_id")
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return
    row = await bot.services.personnel.get_absence(guild.id, absence_id)
    if not row:
        return
    embed = branded_embed(
        bot.config.branding,
        title=f"🗓️ Novo afastamento pendente #{absence_id}",
        description=(
            f"**Membro:** <@{row['discord_id']}>\n"
            f"**Período:** {discord_timestamp(row['starts_at'], 'd')} até "
            f"{discord_timestamp(row['ends_at'], 'd')}\n"
            f"**Motivo:** {row['reason']}\n\n"
            "Use o botão **Afastamentos** na Central Administrativa."
        ),
    )
    await channel.send(embed=embed)


class AbsenceSelect(discord.ui.Select):
    def __init__(self, rows: list) -> None:
        super().__init__(
            placeholder="Escolha um afastamento pendente",
            options=[
                discord.SelectOption(
                    label=f"#{row['id']} • {row['mta_nick']}"[:100],
                    value=str(row["id"]),
                    description=f"{row['reason']}"[:100],
                )
                for row in rows[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        absence = await get_bot(interaction).services.personnel.get_absence(
            interaction.guild.id, int(self.values[0])
        )
        if not absence or absence["status"] != "PENDING":
            raise NotFoundError("A solicitação não está mais pendente.")
        embed = branded_embed(
            get_bot(interaction).config.branding,
            title=f"Afastamento pendente #{absence['id']}",
            description=(
                f"**Membro:** <@{absence['discord_id']}>\n"
                f"**Início:** {discord_timestamp(absence['starts_at'], 'd')}\n"
                f"**Fim:** {discord_timestamp(absence['ends_at'], 'd')}\n"
                f"**Motivo:** {absence['reason']}"
            ),
        )
        await interaction.response.edit_message(
            content=None, embed=embed, view=AbsenceDecisionView(int(absence["id"]))
        )


class AbsenceListView(AdminView):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(AbsenceSelect(rows))


class AbsenceDecisionView(AdminView):
    def __init__(self, absence_id: int) -> None:
        super().__init__(timeout=300)
        self.absence_id = absence_id

    @discord.ui.button(label="Aprovar", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(AbsenceDecisionModal(self.absence_id, True))

    @discord.ui.button(label="Negar", emoji="❌", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(AbsenceDecisionModal(self.absence_id, False))


class AbsenceDecisionModal(ErrorModal, title="Analisar afastamento"):
    reason = discord.ui.TextInput(
        label="Motivo da decisão",
        style=discord.TextStyle.paragraph,
        default="Análise administrativa",
        max_length=500,
    )

    def __init__(self, absence_id: int, approved: bool) -> None:
        super().__init__()
        self.absence_id = absence_id
        self.approved = approved

    async def on_submit(self, interaction: discord.Interaction) -> None:
        actor = await require_admin(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        bot = get_bot(interaction)
        result = await bot.services.personnel.review_absence(
            actor.guild.id, self.absence_id, self.approved, actor.id, str(self.reason)
        )
        if result["member_status"] == "AWAY":
            await bot.services.shifts.finalize_role_loss(
                actor.guild.id, int(result["discord_id"]), reason="ABSENCE_APPROVED"
            )
        target = actor.guild.get_member(int(result["discord_id"]))
        if target:
            try:
                await target.send(
                    f"Sua solicitação de afastamento #{self.absence_id} foi "
                    f"**{result['status']}**. Motivo: {self.reason}"
                )
            except discord.Forbidden:
                pass
        await interaction.followup.send(
            f"✅ Afastamento **#{self.absence_id}** definido como `{result['status']}`.",
            ephemeral=True,
        )


async def build_history_embed(
    bot: ChoqueBot, guild: discord.Guild, target: discord.Member
) -> discord.Embed:
    history, requests = await asyncio.gather(
        bot.services.personnel.history(guild.id, target.id),
        bot.services.requests.for_member(guild.id, target.id),
    )
    embed = branded_embed(
        bot.config.branding,
        title=f"📚 Histórico administrativo • {target.display_name}",
        description=target.mention,
    )
    actions = [
        f"• `{row['action_type']}` {row['from_rank_name'] or 'Sem patente'} → "
        f"{row['to_rank_name']} • {discord_timestamp(row['created_at'], 'R')}"
        for row in history["actions"]
    ]
    punishments = [
        f"• **#{row['id']}** `{row['punishment_type']}/{row['status']}` • "
        f"{discord_timestamp(row['created_at'], 'R')}\n└ {row['reason']}"
        for row in history["punishments"]
    ]
    absences = [
        f"• **#{row['id']}** `{row['status']}` • {discord_timestamp(row['starts_at'], 'd')} "
        f"até {discord_timestamp(row['ends_at'], 'd')}"
        for row in history["absences"]
    ]
    administrative_requests = [
        f"• **#{row['id']}** `{row['request_type']}/{row['status']}` • "
        f"{discord_timestamp(row['submitted_at'], 'R')}"
        for row in requests
    ]
    embed.add_field(
        name="Patentes", value="\n".join(actions)[:1024] or "Nenhuma movimentação.", inline=False
    )
    embed.add_field(
        name="Punições", value="\n".join(punishments)[:1024] or "Nenhuma punição.", inline=False
    )
    embed.add_field(
        name="Afastamentos", value="\n".join(absences)[:1024] or "Nenhum afastamento.", inline=False
    )
    embed.add_field(
        name="Solicitações",
        value="\n".join(administrative_requests)[:1024] or "Nenhuma solicitação.",
        inline=False,
    )
    return embed


class RankingPeriodView(ErrorView):
    def __init__(self, *, persistent: bool = False) -> None:
        super().__init__(timeout=None if persistent else 300)
        if persistent:
            for child in self.children:
                child.custom_id = f"choque:ranking:{child.custom_id}:v1"

    async def show(self, interaction: discord.Interaction, period: str) -> None:
        if not interaction.guild:
            raise ValidationError("Use este painel dentro do servidor.")
        await get_bot(interaction).services.modules.require_enabled(interaction.guild.id, "RANKING")
        await interaction.response.send_message(
            embed=await build_ranking_embed(get_bot(interaction), interaction.guild, period),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Hoje", emoji="☀️", style=discord.ButtonStyle.primary, custom_id="today"
    )
    async def today(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, "today")

    @discord.ui.button(
        label="Semana", emoji="📅", style=discord.ButtonStyle.primary, custom_id="week"
    )
    async def week(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, "week")

    @discord.ui.button(
        label="Mês", emoji="🗓️", style=discord.ButtonStyle.secondary, custom_id="month"
    )
    async def month(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, "month")

    @discord.ui.button(
        label="Total", emoji="🏆", style=discord.ButtonStyle.success, custom_id="total"
    )
    async def total(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.show(interaction, "total")


class PersonnelCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = cast("ChoqueBot", bot)
        self.services = self.bot.services
        self._panel_lock = asyncio.Lock()
        self.bot.add_view(PersonnelAdminView())
        self.bot.add_view(RankingPeriodView(persistent=True))

    async def refresh_admin_panel(self, guild: discord.Guild) -> None:
        channel_id = await self.services.settings.get(guild.id, "personnel_admin_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            await self.publish_or_refresh(guild, channel, "PERSONNEL_ADMIN")

    async def publish_or_refresh(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        panel_type: str,
    ) -> discord.Message:
        if panel_type == "PERSONNEL_ADMIN":
            embed = await build_admin_embed(self.bot, guild)
            view: discord.ui.View = PersonnelAdminView()
        else:
            embed = build_ranking_landing_embed(self.bot)
            view = RankingPeriodView(persistent=True)
        async with self._panel_lock:
            panel = await self.services.settings.get_panel(guild.id, panel_type)
            if panel and int(panel["channel_id"]) == channel.id:
                try:
                    message = await channel.fetch_message(int(panel["message_id"]))
                    await message.edit(embed=embed, view=view)
                    return message
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            message = await channel.send(embed=embed, view=view)
            await self.services.settings.upsert_panel(guild.id, panel_type, channel.id, message.id)
            return message

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.bot.check_mode:
            return
        targets = {
            "PERSONNEL_ADMIN": "personnel_admin_channel_id",
            "RANKING": "ranking_panel_channel_id",
        }
        for guild in self.bot.guilds:
            for panel_type, setting_key in targets.items():
                channel_id = await self.services.settings.get(guild.id, setting_key)
                channel = guild.get_channel(int(channel_id)) if channel_id else None
                if not isinstance(channel, discord.TextChannel):
                    continue
                try:
                    await self.publish_or_refresh(guild, channel, panel_type)
                except discord.DiscordException:
                    LOGGER.exception("Falha ao restaurar painel %s", panel_type)
        if not self.expire_personnel_states.is_running():
            self.expire_personnel_states.start()

    @tasks.loop(minutes=1)
    async def expire_personnel_states(self) -> None:
        for guild in self.bot.guilds:
            changes = await self.services.personnel.expire_due(guild.id)
            for discord_id, status in changes:
                if status != "ACTIVE":
                    await self.services.shifts.finalize_role_loss(
                        guild.id, discord_id, reason=f"STATUS_{status}"
                    )
                target = guild.get_member(discord_id)
                if target:
                    await sync_member_status_roles(self.bot, guild, target, status)
                    try:
                        await target.send(
                            f"Seu status no CHOQUE - BGR foi atualizado automaticamente para "
                            f"**{status}**."
                        )
                    except discord.Forbidden:
                        pass

    @expire_personnel_states.before_loop
    async def before_expire_personnel_states(self) -> None:
        await self.bot.wait_until_ready()

    async def cog_unload(self) -> None:
        self.expire_personnel_states.cancel()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PersonnelCommands(bot))


if TYPE_CHECKING:
    from choque.bot import ChoqueBot
