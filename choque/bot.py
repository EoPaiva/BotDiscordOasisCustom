from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from .activity import ActivityService
from .audit import AuditService
from .career import CareerService
from .config import AppConfig
from .database import Database
from .discipline import DisciplineService
from .duty_patrols import DutyPatrolService
from .errors import ChoqueError
from .financial_aid import FinancialAidService
from .members import MemberService
from .module_flags import ModuleFlagService
from .operations import OperationsService
from .personnel import PersonnelService
from .rank_sync import RankSyncService
from .rbac import PermissionService
from .recruitment import RecruitmentService
from .recruitment_analysis import RecruitmentAnalysisService, RecruitmentAnalysisWorker
from .registration_gate import RegistrationGateService
from .requests import RequestService
from .security import SecurityService
from .services import Services
from .settings import SettingsService
from .shifts import ShiftService
from .status import StatusService
from .tags import TagService
from .tickets import TicketService
from .time_utils import utc_now_ms
from .training import TrainingService
from .web_outbox import WebActionWorker

LOGGER = logging.getLogger(__name__)

COGS = (
    "cogs.shift_commands",
    "cogs.member_commands",
    "cogs.registration_gate_system",
    "cogs.config_commands",
    "cogs.personnel_commands",
    "cogs.request_commands",
    "cogs.career_commands",
    "cogs.discipline_commands",
    "cogs.training_commands",
    "cogs.activity_commands",
    "cogs.ticket_commands",
    "cogs.tag_commands",
    "cogs.status_commands",
    "cogs.financial_aid_commands",
    "cogs.operations_commands",
    "cogs.hierarchy_system",
    "cogs.rank_sync_system",
    "cogs.utility_commands",
    "cogs.security_system",
)


class ChoqueBot(commands.Bot):
    def __init__(self, config: AppConfig, *, check_mode: bool = False) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.voice_states = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.config = config
        self.check_mode = check_mode
        self.started_at = utc_now_ms()
        self.guild_id = config.default_guild_id
        self.services: Services
        self._initialized = False
        self._synced = False
        self.web_action_worker: WebActionWorker | None = None
        self.recruitment_analysis_worker: RecruitmentAnalysisWorker | None = None
        self.tree.on_error = self.on_tree_error

    async def setup_hook(self) -> None:
        if self._initialized:
            return
        database = Database(self.config.database_path, self.config.legacy_database_path)
        await database.open()
        settings = SettingsService(database)
        imported_guild = await settings.import_legacy(Path("config.json"))
        self.guild_id = self.guild_id or imported_guild
        audit = AuditService(database, settings, self.config.branding, self)
        permissions = PermissionService(settings)
        members = MemberService(database, audit)
        modules = ModuleFlagService(database, settings, audit)
        shifts = ShiftService(database, settings, audit)
        personnel = PersonnelService(database, audit)
        career = CareerService(database, settings, audit, personnel, shifts)
        discipline = DisciplineService(database, audit)
        training = TrainingService(database, audit, settings=settings)
        activity = ActivityService(database, settings, audit, shifts)
        requests = RequestService(database, audit, clock=utc_now_ms)
        tickets = TicketService(database, audit, members)
        rank_sync = RankSyncService(database, settings, audit)
        operations = OperationsService(database, settings, audit, shifts)
        duty_patrols = DutyPatrolService(database, settings, audit, shifts, operations)
        recruitment = RecruitmentService(
            database,
            audit,
            token_secret=os.getenv("RECRUITMENT_TOKEN_SECRET")
            or os.getenv("COMMAND_CENTER_INTERNAL_SECRET")
            or "local-recruitment-token-secret",
        )
        recruitment_analysis = RecruitmentAnalysisService(database, settings, audit)
        registration_gate = RegistrationGateService(database, settings, audit)
        tags = TagService(database, audit)
        status = StatusService(database, audit)
        financial_aid = FinancialAidService(database, settings, audit)
        security = SecurityService(database, settings, audit)
        recruitment.analysis_service = recruitment_analysis
        self.services = Services(
            database=database,
            settings=settings,
            audit=audit,
            permissions=permissions,
            members=members,
            modules=modules,
            shifts=shifts,
            personnel=personnel,
            career=career,
            discipline=discipline,
            training=training,
            activity=activity,
            requests=requests,
            tickets=tickets,
            rank_sync=rank_sync,
            operations=operations,
            duty_patrols=duty_patrols,
            financial_aid=financial_aid,
            recruitment=recruitment,
            recruitment_analysis=recruitment_analysis,
            registration_gate=registration_gate,
            tags=tags,
            status=status,
            security=security,
        )
        if self.guild_id:
            await permissions.ensure_defaults(self.guild_id)
            await recruitment.ensure_defaults(self.guild_id)
            await recruitment_analysis.ensure_defaults(self.guild_id)
            await financial_aid.ensure_defaults(self.guild_id)
        self.web_action_worker = WebActionWorker(database, rank_sync, audit, self, tags=tags)
        self.recruitment_analysis_worker = RecruitmentAnalysisWorker(recruitment_analysis)
        if imported_guild and not await settings.get(
            imported_guild, "legacy_import_audited", False
        ):
            await audit.record(
                imported_guild,
                "LEGACY_CONFIG_IMPORTED",
                after={"source": "config.json", "guild_id": imported_guild},
            )
            await settings.set(imported_guild, "legacy_import_audited", True, None)

        for extension in COGS:
            await self.load_extension(extension)
            LOGGER.info("Cog carregado: %s", extension)
        self._initialized = True

        if not self.check_mode and self.guild_id and not self._synced:
            guild = discord.Object(id=self.guild_id)
            # A operação do CHOQUE - BGR é integralmente orientada por painéis.
            # Mantemos os handlers legados carregados durante a migração, mas
            # removemos todos os application commands publicados na guild.
            self.tree.clear_commands(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
            except discord.Forbidden:
                LOGGER.warning(
                    "Guild configurada %s não está acessível; sincronização será tentada após conexão",
                    self.guild_id,
                )
            else:
                self._synced = True
                LOGGER.info(
                    "Comandos removidos da guild %s; comandos publicados: %s",
                    self.guild_id,
                    len(synced),
                )

    async def on_ready(self) -> None:
        if self.web_action_worker:
            self.web_action_worker.start()
        if self.recruitment_analysis_worker:
            self.recruitment_analysis_worker.start()
        if not self._synced and self.guilds:
            guild = self.get_guild(self.guild_id) if self.guild_id else None
            if guild is None and len(self.guilds) == 1:
                guild = self.guilds[0]
                LOGGER.warning(
                    "Usando a única guild acessível como fallback: %s (%s)",
                    guild.name,
                    guild.id,
                )
            if guild:
                self.guild_id = guild.id
                target = discord.Object(id=guild.id)
                self.tree.clear_commands(guild=target)
                synced = await self.tree.sync(guild=target)
                self._synced = True
                LOGGER.info(
                    "Comandos removidos da guild %s; comandos publicados: %s",
                    guild.id,
                    len(synced),
                )
        LOGGER.info(
            "Bot conectado como %s em %s guild(s): %s",
            self.user,
            len(self.guilds),
            [(guild.name, guild.id) for guild in self.guilds],
        )

    async def on_tree_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        correlation_id = str(uuid.uuid4())
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        if isinstance(original, ChoqueError):
            message = f"❌ {original}"
            LOGGER.info(
                "Erro de domínio em comando: %s",
                original,
                extra={"correlation_id": correlation_id},
            )
        elif isinstance(original, app_commands.CheckFailure):
            message = "❌ Você não possui permissão para executar este comando."
        else:
            message = f"❌ Ocorreu um erro interno. Código: `{correlation_id}`"
            LOGGER.exception(
                "Erro não tratado em comando",
                exc_info=original,
                extra={"correlation_id": correlation_id},
            )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.DiscordException:
            LOGGER.warning(
                "Não foi possível responder ao erro da interação",
                extra={"correlation_id": correlation_id},
            )

    async def close(self) -> None:
        if getattr(self, "_initialized", False):
            try:
                if self.web_action_worker:
                    await self.web_action_worker.close()
                if self.recruitment_analysis_worker:
                    await self.recruitment_analysis_worker.close()
                await self.services.shifts.close()
                if not self.check_mode:
                    await self.services.database.execute("UPDATE bot_runtime SET clean_shutdown=1")
            finally:
                await self.services.database.close()
        await super().close()
