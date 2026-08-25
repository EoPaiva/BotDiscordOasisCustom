from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import Mapping
from contextlib import suppress
from urllib.parse import urlsplit

import discord

from .audit import AuditService
from .database import Database
from .rank_sync import RankSyncResult, RankSyncService
from .tags import TagService
from .time_utils import utc_now_ms

LOGGER = logging.getLogger(__name__)
IDLE_POLL_SECONDS = 2.0
BATCH_POLL_SECONDS = 0.25
RECOVERY_REVIEW_CARD_REFRESH_INTERVAL_MS = 6_000
TAG_ROLE_RECONCILIATION_INTERVAL_MS = 300_000


# The review card is private to the recruitment team.  Keep its operational
# state in one renderer so an update made by the portal or by Discord produces
# the same message, rather than a second card for the same candidate.
RECRUITMENT_DECISION_STATUSES = frozenset({"UNDER_REVIEW", "INTERVIEW_COMPLETED", "FINAL_REVIEW"})
RECRUITMENT_FINAL_STATUSES = frozenset({"APPROVED", "REJECTED", "WITHDRAWN", "EXPIRED"})


def _review_timestamp(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"<t:{int(value) // 1000}:F>"
    except (TypeError, ValueError):
        return "—"


def recruitment_review_state(application: Mapping[str, object]) -> tuple[str, str, int]:
    """Return a concise, accessible state for the private review card."""
    status = str(application.get("status") or "SUBMITTED")
    states = {
        "SUBMITTED": (
            "🕒 AGUARDANDO ANÁLISE",
            "A ficha aguarda a atribuição de um responsável.",
            0xC69A45,
        ),
        "UNDER_REVIEW": ("🔎 EM ANÁLISE", "O responsável está avaliando o dossiê.", 0x4C78A8),
        "INTERVIEW_PENDING": (
            "🗣️ ENTREVISTA PENDENTE",
            "A candidatura aguarda encaminhamento para entrevista.",
            0xC69A45,
        ),
        "INTERVIEW_SCHEDULED": (
            "📅 ENTREVISTA AGENDADA",
            "Há uma entrevista agendada para esta candidatura.",
            0x4C78A8,
        ),
        "INTERVIEW_COMPLETED": (
            "📋 DECISÃO FINAL",
            "A entrevista foi concluída e a decisão final está disponível.",
            0xC69A45,
        ),
        "FINAL_REVIEW": ("📋 DECISÃO FINAL", "A candidatura está pronta para uma decisão humana.", 0xC69A45),
        "APPROVED": ("✅ APROVADA", "A decisão foi registrada e as próximas orientações foram encaminhadas.", 0x71906D),
        "REJECTED": ("❌ REPROVADA", "A decisão final foi registrada de forma reservada.", 0xA94F43),
        "WITHDRAWN": ("⚪ RETIRADA", "A candidatura foi retirada pelo candidato.", 0x6B7280),
        "EXPIRED": ("⌛ EXPIRADA", "O prazo desta candidatura foi encerrado.", 0x6B7280),
    }
    return states.get(status, (f"ℹ️ {status}", "Acompanhe o dossiê para detalhes.", 0x5865F2))


def build_recruitment_review_embed(branding, application: Mapping[str, object]) -> discord.Embed:
    """Render the single private card used by the Discord analysis desk."""
    title, description, color = recruitment_review_state(application)
    status = str(application.get("status") or "SUBMITTED")
    embed = discord.Embed(title=f"{title} • MESA DE ANÁLISE", description=description, color=color)
    embed.add_field(name="Protocolo", value=str(application.get("protocol") or "—"), inline=True)
    embed.add_field(name="Candidato", value=str(application.get("candidate_nick") or "—"), inline=True)
    embed.add_field(name="ID BGR", value=str(application.get("bgr_id") or "—"), inline=True)

    assigned_to = application.get("assigned_to")
    if assigned_to is None:
        responsible = "Não atribuído"
    else:
        responsible = f"<@{assigned_to}>"
    embed.add_field(name="Responsável", value=responsible, inline=True)
    embed.add_field(
        name="Atribuída em",
        value=_review_timestamp(application.get("assigned_at")),
        inline=True,
    )
    embed.add_field(name="Estado", value=status, inline=True)

    if status in {"APPROVED", "REJECTED"}:
        decided_by = application.get("decided_by")
        embed.add_field(
            name="Decidida por",
            value=f"<@{decided_by}>" if decided_by is not None else "—",
            inline=True,
        )
        embed.add_field(
            name="Decisão em",
            value=_review_timestamp(application.get("decided_at")),
            inline=True,
        )
        reason = str(application.get("internal_reason") or "Justificativa não registrada.").strip()
        embed.add_field(name="Justificativa interna", value=reason[:1000], inline=False)
    elif status in RECRUITMENT_DECISION_STATUSES:
        embed.add_field(
            name="Próxima ação",
            value="Use **Aprovar** ou **Reprovar** após registrar uma justificativa.",
            inline=False,
        )
    else:
        embed.add_field(
            name="Próxima ação",
            value="Abra o dossiê e assuma a análise antes da decisão final.",
            inline=False,
        )
    embed.set_footer(text=branding.footer)
    return embed


def build_recruitment_review_view(
    application: Mapping[str, object], public_url: str | None
) -> discord.ui.View:
    """Build a persistent card view; dynamic decision handlers live in the cog."""
    view = discord.ui.View(timeout=None)
    status = str(application.get("status") or "SUBMITTED")
    application_id = int(application["id"])
    decision_enabled = status in RECRUITMENT_DECISION_STATUSES
    final = status in RECRUITMENT_FINAL_STATUSES
    if isinstance(public_url, str) and public_url.startswith(("https://", "http://")):
        parsed_url = urlsplit(public_url)
        dossier_url = f"{parsed_url.scheme}://{parsed_url.netloc}/recruitment/{application['id']}"
        for label, anchor in (
            ("Abrir dossiê", ""),
            ("Adicionar nota", "#notas"),
            ("Entrevista", "#entrevista"),
            ("Decidir", "#decisao"),
        ):
            view.add_item(
                discord.ui.Button(
                    label=label,
                    style=discord.ButtonStyle.link,
                    url=f"{dossier_url}{anchor}",
                    disabled=final and label != "Abrir dossiê",
                    row=0,
                )
            )
    for label, emoji, action, style in (
        ("Aprovar", "✅", "approve", discord.ButtonStyle.success),
        ("Reprovar", "❌", "reject", discord.ButtonStyle.danger),
    ):
        view.add_item(
            discord.ui.Button(
                label=label,
                emoji=emoji,
                style=style,
                custom_id=f"choque:recruitment:decision:{application_id}:{action}:v1",
                disabled=final or not decision_enabled,
                row=1,
            )
        )
    return view


def _optional_actor_id(value: object) -> int | None:
    return int(value) if value is not None else None


def _audit_correlation_id(base: object, suffix: str) -> str:
    return f"{base}:audit:{suffix}"


class WebActionWorker:
    def __init__(
        self,
        database: Database,
        rank_sync: RankSyncService,
        audit: AuditService,
        bot: discord.Client,
        *,
        tags: TagService | None = None,
    ) -> None:
        self.database = database
        self.rank_sync = rank_sync
        self.audit = audit
        self.bot = bot
        self.tags = tags
        self._task: asyncio.Task[None] | None = None
        self._last_registry_refresh = 0
        self._last_stale_scan = 0
        self._last_review_card_refresh_scan = 0
        self._last_tag_role_reconciliation = 0
        self._next_recovery_review_card_refresh_at = 0
        self._recovered_inflight = False

    def start(self) -> None:
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._run(), name="web-action-outbox")

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                if not self._recovered_inflight:
                    await self._recover_inflight_actions()
                    self._recovered_inflight = True
                if utc_now_ms() - self._last_registry_refresh >= 300_000:
                    await self.refresh_discord_registry()
                    self._last_registry_refresh = utc_now_ms()
                if utc_now_ms() - self._last_tag_role_reconciliation >= TAG_ROLE_RECONCILIATION_INTERVAL_MS:
                    await self.reconcile_tag_roles()
                    self._last_tag_role_reconciliation = utc_now_ms()
                processed = await self.process_pending()
                processed += await self.process_recruitment_pending()
            except Exception:
                LOGGER.exception("Falha no worker de ações do Command Center")
                processed = 0
            # The worker lives in the Gateway process while the public API
            # writes the durable queue from a sibling process.  There is no
            # cross-process wake-up primitive, so a short bounded poll keeps
            # an approved registration visible in Discord promptly without
            # sacrificing the durable outbox contract.
            await asyncio.sleep(BATCH_POLL_SECONDS if processed else IDLE_POLL_SECONDS)

    async def _recover_inflight_actions(self) -> None:
        """Make work claimed by a terminated single instance retryable."""
        now = utc_now_ms()
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                UPDATE web_action_outbox
                SET status='FAILED', available_at=?,
                    last_error='Recuperado após reinício do worker'
                WHERE status='PROCESSING'
                """,
                (now,),
            )
            await connection.execute(
                """
                UPDATE identity_reconciliation_jobs
                SET status='FAILED', completed_at=?,
                    last_error='Recuperado após reinício do worker'
                WHERE status='PROCESSING'
                """,
                (now,),
            )

    async def refresh_discord_registry(self) -> int:
        now = utc_now_ms()
        resources: list[tuple[int, int, str, str, int | None, int, int]] = []
        for guild in self.bot.guilds:
            resources.extend(
                (
                    guild.id,
                    role.id,
                    "ROLE",
                    role.name,
                    None,
                    role.position,
                    now,
                )
                for role in guild.roles
                if not role.is_default()
            )
            for channel in guild.channels:
                if isinstance(channel, discord.CategoryChannel):
                    resource_type = "CATEGORY"
                    parent_id = None
                elif isinstance(channel, discord.VoiceChannel):
                    resource_type = "VOICE_CHANNEL"
                    parent_id = channel.category_id
                elif isinstance(channel, discord.TextChannel):
                    resource_type = "TEXT_CHANNEL"
                    parent_id = channel.category_id
                else:
                    continue
                resources.append(
                    (
                        guild.id,
                        channel.id,
                        resource_type,
                        channel.name,
                        parent_id,
                        channel.position,
                        now,
                    )
                )
        if not resources:
            return 0
        guild_ids = sorted({item[0] for item in resources})
        async with self.database.transaction() as connection:
            for guild_id in guild_ids:
                await connection.execute(
                    "UPDATE discord_resource_registry SET active=0 WHERE guild_id=?",
                    (guild_id,),
                )
            await connection.executemany(
                """
                INSERT INTO discord_resource_registry(
                    guild_id, resource_id, resource_type, name, parent_id,
                    position, active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(guild_id, resource_id, resource_type) DO UPDATE SET
                    name=excluded.name, parent_id=excluded.parent_id,
                    position=excluded.position, active=1, updated_at=excluded.updated_at
                """,
                resources,
            )
        return len(resources)

    async def process_pending(self, limit: int = 10) -> int:
        rows = await self.database.fetchall(
            """
            SELECT * FROM web_action_outbox
            WHERE status IN ('PENDING','FAILED') AND attempts < 10 AND available_at <= ?
            ORDER BY CASE status WHEN 'PENDING' THEN 0 ELSE 1 END, created_at, id LIMIT ?
            """,
            (utc_now_ms(), limit),
        )
        processed = 0
        for row in rows:
            claimed = await self._claim(int(row["id"]))
            if not claimed:
                continue
            try:
                result = await self._dispatch(row)
                await self._complete_action(row, result)
            except Exception as exc:
                await self.database.execute(
                    """
                    UPDATE web_action_outbox SET status='FAILED', attempts=attempts+1,
                        available_at=?, last_error=? WHERE id=? AND status='PROCESSING'
                    """,
                    (utc_now_ms() + 30_000, str(exc)[:500], row["id"]),
                )
                with suppress(Exception):
                    if row["action_type"] == "MEMBER_SYNC":
                        await self._mark_registration_sync(
                            int(row["guild_id"]),
                            int(row["target_discord_id"]),
                            success=False,
                            actor_id=_optional_actor_id(row["requested_by"]),
                            error=str(exc),
                            correlation_id=str(row["correlation_id"]),
                        )
                    await self.audit.record(
                        int(row["guild_id"]),
                        "DISCORD_SYNC_FAILED",
                        actor_id=_optional_actor_id(row["requested_by"]),
                        target_id=(
                            int(row["target_discord_id"])
                            if row["target_discord_id"] is not None
                            else None
                        ),
                        after={
                            "action_id": int(row["id"]),
                            "attempt": int(row["attempts"]) + 1,
                            "operation_correlation_id": str(row["correlation_id"]),
                        },
                        correlation_id=_audit_correlation_id(
                            row["correlation_id"],
                            f"outbox-failed-{row['id']}-{int(row['attempts']) + 1}",
                        ),
                    )
                LOGGER.warning("Ação web %s falhou: %s", row["id"], exc)
                LOGGER.warning(
                    "Latência da ação web %s até falha: %sms",
                    row["id"],
                    self._queue_latency_ms(row),
                )
            else:
                processed += 1
        return processed

    async def _complete_action(self, row, result: RankSyncResult | None) -> None:
        if str(row["action_type"]) != "IDENTITY_SYNC":
            await self.database.execute(
                """
                UPDATE web_action_outbox SET status='COMPLETED', attempts=attempts+1,
                    processed_at=?, last_error=NULL WHERE id=? AND status='PROCESSING'
                """,
                (utc_now_ms(), row["id"]),
            )
            LOGGER.info(
                "Ação web %s concluída em %sms",
                row["id"],
                self._queue_latency_ms(row),
            )
            return

        audit_correlation_id = _audit_correlation_id(
            row["correlation_id"], f"outbox-completed-{row['id']}"
        )
        after: dict[str, object] = {
            "action_id": int(row["id"]),
            "action_type": "IDENTITY_SYNC",
            "operation_correlation_id": str(row["correlation_id"]),
        }
        if result and result.identity_sync_status:
            after["identity_sync_status"] = result.identity_sync_status
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE web_action_outbox SET status='COMPLETED', attempts=attempts+1,
                    processed_at=?, last_error=NULL WHERE id=? AND status='PROCESSING'
                """,
                (utc_now_ms(), row["id"]),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Ação de identidade perdeu a posse antes da conclusão")
            cursor = await connection.execute(
                "SELECT action FROM audit_logs WHERE correlation_id=?",
                (audit_correlation_id,),
            )
            existing_audit = await cursor.fetchone()
            if existing_audit is None:
                await self.audit.record(
                    int(row["guild_id"]),
                    "DISCORD_IDENTITY_SYNC_COMPLETED",
                    actor_id=_optional_actor_id(row["requested_by"]),
                    target_id=int(row["target_discord_id"]),
                    after=after,
                    correlation_id=audit_correlation_id,
                    connection=connection,
                )
            elif str(existing_audit["action"]) != "DISCORD_IDENTITY_SYNC_COMPLETED":
                raise RuntimeError("Correlação do outbox já pertence a outra auditoria")
        LOGGER.info(
            "Ação web %s concluída em %sms",
            row["id"],
            self._queue_latency_ms(row),
        )

    @staticmethod
    def _queue_latency_ms(row) -> int:
        """Age from the API commit to terminal worker handling for operations."""
        return max(0, utc_now_ms() - int(row["created_at"]))

    async def _claim(self, action_id: int) -> bool:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE web_action_outbox SET status='PROCESSING'
                WHERE id=? AND status IN ('PENDING','FAILED')
                """,
                (action_id,),
            )
            return cursor.rowcount == 1

    async def _dispatch(self, row) -> RankSyncResult | None:
        action_type = str(row["action_type"])
        supported = {
            "RANK_SYNC",
            "MEMBER_SYNC",
            "IDENTITY_SYNC",
            "IDENTITY_RECONCILE_BULK",
            "QUALIFICATION_SYNC",
            "TAG_ROLE_SYNC",
        }
        if action_type not in supported:
            raise ValueError(f"Ação web não suportada: {row['action_type']}")
        guild = self.bot.get_guild(int(row["guild_id"]))
        if not guild:
            raise RuntimeError("Guild indisponível no Discord")
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Payload da ação web é inválido") from exc
        if action_type == "IDENTITY_RECONCILE_BULK":
            job_id = int(payload.get("job_id") or 0)
            if job_id <= 0:
                raise ValueError("Job de reconciliação ausente no payload")
            summary = await self.rank_sync.process_reconciliation_job(
                job_id,
                guild,
                source=str(payload.get("source") or "COMMAND_CENTER_WEB"),
                correlation_id=str(row["correlation_id"]),
            )
            if summary.failed:
                raise RuntimeError(f"Reconciliação {job_id} terminou com {summary.failed} falha(s)")
            return None

        if row["target_discord_id"] is None:
            raise ValueError("Ação individual sem membro de destino")
        target_id = int(row["target_discord_id"])
        member = guild.get_member(target_id)
        if not member:
            try:
                member = await guild.fetch_member(target_id)
            except discord.NotFound:
                if action_type != "IDENTITY_SYNC":
                    raise RuntimeError("Membro indisponível no Discord") from None
                result = await self.rank_sync.mark_discord_absent(
                    int(row["guild_id"]),
                    target_id,
                    source=str(payload.get("source") or "COMMAND_CENTER_WEB"),
                    actor_id=_optional_actor_id(row["requested_by"]),
                    correlation_id=str(row["correlation_id"]),
                )
                if not result.registered:
                    raise RuntimeError("Membro não cadastrado") from None
                return result
            except discord.DiscordException as exc:
                raise RuntimeError("Membro indisponível no Discord") from exc
        if action_type == "QUALIFICATION_SYNC":
            await self._sync_qualification_role(row, payload, guild, member)
            await self.audit.record(
                int(row["guild_id"]),
                "DISCORD_QUALIFICATION_SYNC_COMPLETED",
                actor_id=_optional_actor_id(row["requested_by"]),
                target_id=target_id,
                after={
                    "action_id": int(row["id"]),
                    "course_id": int(payload.get("course_id") or 0),
                    "operation_correlation_id": str(row["correlation_id"]),
                },
                correlation_id=_audit_correlation_id(
                    row["correlation_id"], f"qualification-sync-completed-{row['id']}"
                ),
            )
            return None
        if action_type == "TAG_ROLE_SYNC":
            await self._sync_tag_roles(row, payload, guild, member)
            return None
        if action_type == "IDENTITY_SYNC":
            result = await self.rank_sync.sync_from_member(
                member,
                source=str(payload.get("source") or "COMMAND_CENTER_WEB"),
                actor_id=_optional_actor_id(row["requested_by"]),
                correlation_id=str(row["correlation_id"]),
            )
        else:
            result = await self.rank_sync.sync_to_member(
                member,
                source=str(payload.get("source") or "COMMAND_CENTER_WEB"),
                actor_id=_optional_actor_id(row["requested_by"]),
                ensure_member_role=action_type == "MEMBER_SYNC",
                explicit_remove_role_ids=await self._registration_remove_roles(
                    int(row["guild_id"]), action_type
                ),
                correlation_id=str(row["correlation_id"]),
            )
        if result.warning:
            raise RuntimeError(result.warning)
        if action_type != "IDENTITY_SYNC":
            await self.audit.record(
                int(row["guild_id"]),
                "DISCORD_SYNC_COMPLETED",
                actor_id=_optional_actor_id(row["requested_by"]),
                target_id=target_id,
                after={
                    "action_id": int(row["id"]),
                    "action_type": action_type,
                    "operation_correlation_id": str(row["correlation_id"]),
                },
                correlation_id=_audit_correlation_id(
                    row["correlation_id"], f"discord-sync-completed-{row['id']}"
                ),
            )
        if action_type == "MEMBER_SYNC":
            await self._mark_registration_sync(
                int(row["guild_id"]),
                target_id,
                success=True,
                actor_id=_optional_actor_id(row["requested_by"]),
                correlation_id=str(row["correlation_id"]),
            )
        return result

    async def _sync_tag_roles(
        self,
        row,
        payload: dict[str, object],
        guild: discord.Guild,
        member: discord.Member,
    ) -> None:
        """Converge Discord roles from the durable request state, never vice versa."""
        if self.tags is None:
            raise RuntimeError("Serviço de tags indisponível para sincronização")
        request_id = int(payload.get("request_id") or 0)
        requested_version = int(payload.get("request_version") or 0)
        if request_id <= 0 or requested_version <= 0:
            raise ValueError("Solicitação ou versão de tag ausente no payload")
        request = await self.database.fetchone(
            "SELECT * FROM tag_requests WHERE id=? AND guild_id=?",
            (request_id, int(row["guild_id"])),
        )
        if not request:
            raise RuntimeError("Solicitação de tag não encontrada")
        current_request = await self.database.fetchone(
            """
            SELECT id FROM tag_requests
            WHERE guild_id=? AND member_id=?
            ORDER BY requested_at DESC, id DESC LIMIT 1
            """,
            (int(row["guild_id"]), int(request["member_id"])),
        )
        if current_request is None or int(current_request["id"]) != request_id:
            # A later request is authoritative for this member.  A delayed
            # terminal sync from an older cycle must never strip its new tag
            # or waiting role.
            return
        # A later domain transition already queued its own role intent.  Do
        # not let a delayed old worker undo the newest role state.
        if int(request["version"]) != requested_version:
            return
        settings = self.audit.settings
        if settings is None:
            raise RuntimeError("Configuração de cargos de tag indisponível")
        waiting_role_id = await settings.get(int(row["guild_id"]), "tag_waiting_role_id")
        set_role_id = await settings.get(int(row["guild_id"]), "tag_set_role_id")
        if not waiting_role_id or not set_role_id:
            raise RuntimeError("Configure os cargos AGUARDANDO SET e TAG SETADA antes de sincronizar")
        waiting_role_id = int(waiting_role_id)
        set_role_id = int(set_role_id)
        if waiting_role_id == set_role_id:
            raise RuntimeError("Os cargos de aguardando set e tag setada devem ser diferentes")

        role_cache = {int(role.id): role for role in getattr(guild, "roles", ())}
        for role_id in (waiting_role_id, set_role_id):
            role = guild.get_role(role_id) or role_cache.get(role_id)
            if role is None:
                roles = await guild.fetch_roles()
                role = next((item for item in roles if int(item.id) == role_id), None)
            if role is None:
                raise RuntimeError(f"Cargo de tag {role_id} não foi encontrado no Discord")
            role_cache[role_id] = role

        status = str(request["status"])
        active = status in TagService.ACTIVE_STATUSES
        existing_tag_pending_validation = (
            str(request["request_origin"] or "SET_REQUEST") == "EXISTING_DECLARATION"
            and request["set_at"] is None
        )
        should_wait = active and not existing_tag_pending_validation
        should_set = status == "CONCLUIDO"
        current_role_ids = {int(role.id) for role in member.roles}
        reason = f"CHOQUE - BGR • Central de Tags • solicitação #{request_id} v{requested_version}"
        for role_id, should_have in (
            (waiting_role_id, should_wait),
            (set_role_id, should_set),
        ):
            has_role = role_id in current_role_ids
            if should_have and not has_role:
                await member.add_roles(role_cache[role_id], reason=reason)
                current_role_ids.add(role_id)
            elif not should_have and has_role:
                await member.remove_roles(role_cache[role_id], reason=reason)
                current_role_ids.discard(role_id)

        now = utc_now_ms()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE tag_role_sync_state
                SET applied_version=?, last_error=NULL, updated_at=?
                WHERE tag_request_id=? AND requested_version<=?
                """,
                (requested_version, now, request_id, requested_version),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Estado de sincronização da tag não encontrado")
            await self.audit.record(
                int(row["guild_id"]),
                "DISCORD_TAG_ROLE_SYNC_COMPLETED",
                actor_id=_optional_actor_id(row["requested_by"]),
                target_id=int(row["target_discord_id"]),
                after={
                    "tag_request_id": request_id,
                    "status": status,
                    "waiting_role_id": waiting_role_id if should_wait else None,
                    "set_role_id": set_role_id if should_set else None,
                    "request_version": requested_version,
                },
                correlation_id=_audit_correlation_id(
                    row["correlation_id"], f"tag-role-sync-{request_id}-v{requested_version}"
                ),
                connection=connection,
            )

    async def reconcile_tag_roles(self, limit: int = 100) -> int:
        """Detect Discord-role drift and enqueue one bounded repair per request.

        The durable request remains authoritative.  Reconciliation only queues
        work after observing a real mismatch; the existing outbox continues to
        own retries, rate limiting and audit delivery.
        """
        if self.tags is None or self.audit.settings is None:
            return 0
        safe_limit = max(1, min(int(limit), 100))
        rows = await self.database.fetchall(
            """
            SELECT r.*, s.last_reconcile_requested_at
            FROM tag_requests r
            JOIN tag_role_sync_state s ON s.tag_request_id=r.id
            WHERE r.id=(
                SELECT newer.id FROM tag_requests newer
                WHERE newer.guild_id=r.guild_id AND newer.member_id=r.member_id
                ORDER BY newer.requested_at DESC, newer.id DESC LIMIT 1
            )
            ORDER BY r.updated_at, r.id LIMIT ?
            """,
            (safe_limit,),
        )
        now = utc_now_ms()
        scheduled = 0
        for request in rows:
            guild_id = int(request["guild_id"])
            waiting_role_id = await self.audit.settings.get(guild_id, "tag_waiting_role_id")
            set_role_id = await self.audit.settings.get(guild_id, "tag_set_role_id")
            if not waiting_role_id or not set_role_id or int(waiting_role_id) == int(set_role_id):
                continue
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            try:
                member = guild.get_member(int(request["discord_id"]))
                if member is None:
                    member = await guild.fetch_member(int(request["discord_id"]))
            except discord.DiscordException:
                continue
            status = str(request["status"])
            current_roles = {int(role.id) for role in member.roles}
            expected_waiting = status in TagService.ACTIVE_STATUSES
            expected_set = status == "CONCLUIDO"
            mismatched = (
                (int(waiting_role_id) in current_roles) != expected_waiting
                or (int(set_role_id) in current_roles) != expected_set
            )
            if not mismatched:
                continue
            request_id = int(request["id"])
            version = int(request["version"])
            async with self.database.transaction() as connection:
                cursor = await connection.execute(
                    """
                    UPDATE tag_role_sync_state
                    SET last_reconcile_requested_at=?, updated_at=?
                    WHERE tag_request_id=? AND (
                        last_reconcile_requested_at IS NULL
                        OR last_reconcile_requested_at<=?
                    )
                    """,
                    (
                        now,
                        now,
                        request_id,
                        now - TAG_ROLE_RECONCILIATION_INTERVAL_MS,
                    ),
                )
                if cursor.rowcount != 1:
                    continue
                correlation_id = f"tag-role-reconcile:{request_id}:v{version}:{now}"
                await connection.execute(
                    """
                    INSERT OR IGNORE INTO web_action_outbox(
                        guild_id, action_type, target_discord_id, payload_json,
                        requested_by, correlation_id, status, attempts, available_at, created_at
                    ) VALUES (?, 'TAG_ROLE_SYNC', ?, ?, 0, ?, 'PENDING', 0, ?, ?)
                    """,
                    (
                        guild_id,
                        int(request["discord_id"]),
                        json.dumps(
                            {"request_id": request_id, "request_version": version},
                            sort_keys=True,
                        ),
                        correlation_id,
                        now,
                        now,
                    ),
                )
            scheduled += 1
        return scheduled

    async def _sync_qualification_role(
        self,
        row,
        payload: dict[str, object],
        guild: discord.Guild,
        member: discord.Member,
    ) -> None:
        course_id = int(payload.get("course_id") or 0)
        if course_id <= 0:
            raise ValueError("Curso ausente na ação de qualificação")
        course = await self.database.fetchone(
            """
            SELECT id, name, course_role_id FROM course_catalog
            WHERE guild_id=? AND id=? AND active=1
            """,
            (int(row["guild_id"]), course_id),
        )
        if not course:
            raise RuntimeError("Curso ativo não encontrado")
        latest = await self.database.fetchone(
            """
            SELECT qc.action FROM qualification_changes qc
            JOIN members m ON m.id=qc.member_id
            WHERE qc.guild_id=? AND qc.course_id=? AND m.discord_id=?
            ORDER BY qc.recorded_at DESC, qc.id DESC LIMIT 1
            """,
            (int(row["guild_id"]), course_id, int(member.id)),
        )
        if not latest:
            raise RuntimeError("Estado de qualificação não encontrado")
        should_have_role = str(latest["action"]) == "GRANT"
        role_id = int(course["course_role_id"])
        role = guild.get_role(role_id)
        if role is None:
            roles = await guild.fetch_roles()
            role = next((item for item in roles if int(item.id) == role_id), None)
        if role is None:
            raise RuntimeError("Cargo do curso não foi encontrado no Discord")
        has_role = any(int(item.id) == role_id for item in member.roles)
        reason = f"CHOQUE - BGR • qualificação {course['name']} via Centro de Comando"
        if should_have_role and not has_role:
            await member.add_roles(role, reason=reason)
        elif not should_have_role and has_role:
            await member.remove_roles(role, reason=reason)

    async def _registration_remove_roles(self, guild_id: int, action_type: str) -> set[int]:
        if action_type != "MEMBER_SYNC" or not self.audit.settings:
            return set()
        role_id = await self.audit.settings.get(guild_id, "unregistered_role_id")
        return {int(role_id)} if role_id else set()

    async def _mark_registration_sync(
        self,
        guild_id: int,
        discord_id: int,
        *,
        success: bool,
        actor_id: int | None,
        error: str | None = None,
        correlation_id: str,
    ) -> None:
        record = await self.database.fetchone(
            """
            SELECT * FROM registration_gate_records
            WHERE guild_id=? AND discord_id=?
            """,
            (guild_id, discord_id),
        )
        if not record:
            return
        now = utc_now_ms()
        next_status = "SYNCED" if success else "FAILED"
        next_error = None if success else (error or "erro")[:500]
        if (
            str(record["sync_status"]) == next_status
            and (record["sync_error"] or None) == next_error
        ):
            return
        event = "REGISTRATION_ACCESS_GRANTED" if success else "REGISTRATION_SYNC_FAILED"
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET sync_status=?, sync_error=?, last_attempt_at=?,
                    version=version+1, updated_at=? WHERE id=?
                """,
                (
                    next_status,
                    next_error,
                    now,
                    now,
                    record["id"],
                ),
            )
            await connection.execute(
                """
                INSERT INTO registration_gate_events(
                    guild_id, registration_id, event_type, actor_id, source,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, 'SYSTEM_RECONCILIATION', ?, ?)
                """,
                (
                    guild_id,
                    record["id"],
                    event,
                    actor_id,
                    json.dumps({"error": error[:500] if error else None}),
                    now,
                ),
            )
            if record["member_id"]:
                await connection.execute(
                    """
                    UPDATE recruit_onboarding_checklists
                    SET nickname_status=?, role_status=?, rank_status=?, updated_at=?
                    WHERE guild_id=? AND member_id=?
                    """,
                    (
                        "COMPLETED" if success else "PENDING",
                        "COMPLETED" if success else "PENDING",
                        "COMPLETED" if success else "PENDING",
                        now,
                        guild_id,
                        record["member_id"],
                    ),
                )
            await self.audit.record(
                guild_id,
                event,
                actor_id=actor_id,
                target_id=discord_id,
                after={
                    "registration_id": int(record["id"]),
                    "sync_status": "SYNCED" if success else "FAILED",
                },
                reason=error,
                connection=connection,
                correlation_id=_audit_correlation_id(
                    correlation_id,
                    f"registration-{event.lower()}-{record['id']}-v{int(record['version']) + 1}",
                ),
            )

    async def process_recruitment_pending(self, limit: int = 10) -> int:
        now = utc_now_ms()
        if self.audit.settings and now - self._last_stale_scan >= 300_000:
            await self._enqueue_stale_recruitment(now)
            self._last_stale_scan = now
        if now - self._last_review_card_refresh_scan >= 300_000:
            await self._enqueue_recruitment_review_card_refreshes(now)
            self._last_review_card_refresh_scan = now
        await self._coalesce_recruitment_public_status_backlog(now)
        rows = await self.database.fetchall(
            """
            SELECT * FROM recruitment_notification_outbox
            WHERE status IN ('PENDING','FAILED') AND attempts < 10 AND available_at <= ?
            ORDER BY CASE WHEN event_type='RECRUITMENT_REVIEW_CARD_REFRESH' THEN 1 ELSE 0 END,
                     created_at, id LIMIT ?
            """,
            (utc_now_ms(), limit),
        )
        processed = 0
        for row in rows:
            event_type = str(row["event_type"])
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            recovery_refresh = (
                event_type == "RECRUITMENT_REVIEW_CARD_REFRESH"
                and bool(payload.get("recovery"))
            )
            if recovery_refresh and utc_now_ms() < self._next_recovery_review_card_refresh_at:
                continue
            if not await self._claim_recruitment(int(row["id"])):
                continue
            if recovery_refresh:
                # Existing cards only need a visual/control migration.  Pace
                # those PATCHes below Discord's channel limit so they cannot
                # delay real decisions or generate a rate-limit burst.
                self._next_recovery_review_card_refresh_at = (
                    utc_now_ms() + RECOVERY_REVIEW_CARD_REFRESH_INTERVAL_MS
                )
            try:
                delivery = await self._dispatch_recruitment(row)
            except Exception as exc:
                await self.database.execute(
                    """
                    UPDATE recruitment_notification_outbox
                    SET status='FAILED', attempts=attempts+1, available_at=?, last_error=?
                    WHERE id=? AND status='PROCESSING'
                    """,
                    (utc_now_ms() + 30_000, str(exc)[:500], row["id"]),
                )
                LOGGER.warning("Notificação de recrutamento %s falhou: %s", row["id"], exc)
            else:
                await self.database.execute(
                    """
                    UPDATE recruitment_notification_outbox
                    SET status='COMPLETED', attempts=attempts+1, processed_at=?,
                        last_error=NULL, delivery_channel_id=COALESCE(delivery_channel_id,?),
                        delivery_message_id=COALESCE(delivery_message_id,?)
                    WHERE id=? AND status='PROCESSING'
                    """,
                    (utc_now_ms(), delivery[0], delivery[1], row["id"]),
                )
                processed += 1
        return processed

    async def _enqueue_recruitment_review_card_refreshes(self, now: int) -> int:
        """Bring existing private cards forward to the current persistent view.

        The submitted-notification row is the one and only authority for a
        review card's Discord message.  A version-keyed refresh only edits
        that message, so startup/reconnect recovery can install new controls
        without duplicating cards or replaying a candidate notification.
        """
        applications = await self.database.fetchall(
            """
            SELECT application.id, application.guild_id, application.status, application.version
            FROM recruitment_applications AS application
            WHERE application.submitted_at IS NOT NULL
              AND application.status <> 'DRAFT'
              AND EXISTS (
                  SELECT 1 FROM recruitment_notification_outbox AS submitted
                  WHERE submitted.guild_id=application.guild_id
                    AND submitted.application_id=application.id
                    AND submitted.event_type='RECRUITMENT_APPLICATION_SUBMITTED'
                    AND submitted.status='COMPLETED'
                    AND submitted.delivery_channel_id IS NOT NULL
                    AND submitted.delivery_message_id IS NOT NULL
              )
            ORDER BY application.updated_at, application.id
            """
        )
        created = 0
        async with self.database.transaction() as connection:
            for application in applications:
                cursor = await connection.execute(
                    """
                    INSERT INTO recruitment_notification_outbox(
                        guild_id, application_id, event_type, event_key,
                        payload_json, available_at, created_at
                    ) VALUES (?, ?, 'RECRUITMENT_REVIEW_CARD_REFRESH', ?, ?, ?, ?)
                    ON CONFLICT(guild_id, event_key) DO NOTHING
                    """,
                    (
                        int(application["guild_id"]),
                        int(application["id"]),
                        f"application-review-card:{application['id']}:v{application['version']}",
                        json.dumps(
                            {
                                "application_id": int(application["id"]),
                                "status": str(application["status"]),
                                "version": int(application["version"]),
                                "recovery": True,
                            },
                            ensure_ascii=False,
                        ),
                        now,
                        now,
                    ),
                )
                created += int(cursor.rowcount == 1)
        return created

    async def _coalesce_recruitment_public_status_backlog(self, now: int) -> int:
        """Deliver only the latest state for a public recruitment card.

        The public card is an upsert, not an event history.  If a worker was
        offline while a candidate moved through several stages, every pending
        state would render the *current* application and repeatedly PATCH the
        same Discord message.  Retain those durable outbox rows for audit, but
        mark superseded pending states as coalesced before they reach Discord.
        """
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE recruitment_notification_outbox AS stale
                SET status='COMPLETED', processed_at=?,
                    last_error='Coalescida sem envio: estado público mais recente já disponível'
                WHERE stale.event_type='RECRUITMENT_PUBLIC_STATUS'
                  AND stale.status IN ('PENDING','FAILED')
                  AND EXISTS (
                    SELECT 1 FROM recruitment_notification_outbox newer
                    WHERE newer.guild_id=stale.guild_id
                      AND newer.application_id=stale.application_id
                      AND newer.event_type='RECRUITMENT_PUBLIC_STATUS'
                      AND newer.id>stale.id
                  )
                """,
                (now,),
            )
            return int(cursor.rowcount)

    async def _enqueue_stale_recruitment(self, now: int) -> int:
        guilds = await self.database.fetchall(
            """
            SELECT DISTINCT guild_id FROM recruitment_applications
            WHERE status IN ('SUBMITTED','UNDER_REVIEW') AND submitted_at IS NOT NULL
            """
        )
        created = 0
        for guild in guilds:
            guild_id = int(guild["guild_id"])
            hours = 24
            if self.audit.settings:
                configured = await self.audit.settings.get(
                    guild_id, "recruitment_stale_warning_hours", 24
                )
                hours = max(1, min(720, int(configured)))
            stale = await self.database.fetchall(
                """
                SELECT id, protocol FROM recruitment_applications
                WHERE guild_id=? AND status IN ('SUBMITTED','UNDER_REVIEW')
                  AND submitted_at IS NOT NULL AND submitted_at<=?
                """,
                (guild_id, now - hours * 3_600_000),
            )
            for application in stale:
                async with self.database.transaction() as connection:
                    cursor = await connection.execute(
                        """
                        INSERT OR IGNORE INTO recruitment_notification_outbox(
                            guild_id, application_id, event_type, event_key,
                            payload_json, available_at, created_at
                        ) VALUES (?, ?, 'RECRUITMENT_APPLICATION_STALE', ?, ?, ?, ?)
                        """,
                        (
                            guild_id,
                            application["id"],
                            f"application-stale:{application['id']}",
                            json.dumps(
                                {
                                    "application_id": application["id"],
                                    "protocol": application["protocol"],
                                    "stale_hours": hours,
                                },
                                ensure_ascii=False,
                            ),
                            now,
                            now,
                        ),
                    )
                    created += int(cursor.rowcount == 1)
        return created

    async def _claim_recruitment(self, notification_id: int) -> bool:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE recruitment_notification_outbox SET status='PROCESSING'
                WHERE id=? AND status IN ('PENDING','FAILED')
                """,
                (notification_id,),
            )
            return cursor.rowcount == 1

    async def _dispatch_recruitment(self, row) -> tuple[int | None, int | None]:
        event_type = str(row["event_type"])
        # A refresh is deliberately an edit of the original private card.  Its
        # own outbox delivery pointers are merely retry bookkeeping and must
        # never turn a failed edit into a no-op on the next worker pass.
        if (
            event_type != "RECRUITMENT_REVIEW_CARD_REFRESH"
            and row["delivery_channel_id"]
            and row["delivery_message_id"]
        ):
            channel = self.bot.get_channel(int(row["delivery_channel_id"]))
            if channel and hasattr(channel, "fetch_message"):
                try:
                    await channel.fetch_message(int(row["delivery_message_id"]))
                    return int(row["delivery_channel_id"]), int(row["delivery_message_id"])
                except discord.NotFound:
                    pass
        application_row = await self.database.fetchone(
            "SELECT * FROM recruitment_applications WHERE id=? AND guild_id=?",
            (row["application_id"], row["guild_id"]),
        )
        if not application_row:
            raise RuntimeError("Candidatura da notificação não encontrada")
        # aiosqlite.Row is subscriptable but does not implement Mapping.get().
        # Renderers intentionally accept normal mappings so the same card
        # can be refreshed from a Discord callback or from the durable outbox.
        application = dict(application_row)
        guild = self.bot.get_guild(int(row["guild_id"]))
        if not guild:
            raise RuntimeError("Guild indisponível no Discord")
        payload = json.loads(row["payload_json"])
        if event_type == "RECRUITMENT_PUBLIC_STATUS":
            return await self._dispatch_recruitment_public_status(row, application)
        if event_type in {
            "RECRUITMENT_REVIEW_CARD_REFRESH",
            "RECRUITMENT_APPLICATION_STALE",
            "RECRUITMENT_ANALYSIS_COMPLETED",
        }:
            return await self._refresh_recruitment_review_card(row, application)
        member = guild.get_member(int(application["discord_id"]))
        if not member:
            try:
                member = await guild.fetch_member(int(application["discord_id"]))
            except discord.DiscordException:
                member = None
        if event_type == "RECRUITMENT_INTERVIEW_SCHEDULED":
            if member:
                campaign = await self.database.fetchone(
                    "SELECT candidate_role_id FROM recruitment_campaigns WHERE id=?",
                    (application["campaign_id"],),
                )
                if campaign and campaign["candidate_role_id"]:
                    role = guild.get_role(int(campaign["candidate_role_id"]))
                    if role and role not in member.roles:
                        await member.add_roles(role, reason="Etapa de entrevista do recrutamento")
                        await self.audit.record(
                            int(row["guild_id"]),
                            "CANDIDATE_ROLE_ASSIGNED",
                            target_id=int(application["discord_id"]),
                            after={"application_id": int(application["id"]), "role_id": role.id},
                        )
                embed = self._recruitment_embed(
                    "Entrevista agendada",
                    application,
                    f"Entrevista marcada para <t:{int(payload['scheduled_at']) // 1000}:F>.",
                )
                message = await member.send(embed=embed)
                return message.channel.id, message.id
            raise RuntimeError("Candidato indisponível para notificação de entrevista")
        if event_type in {
            "RECRUITMENT_APPLICATION_APPROVED",
            "RECRUITMENT_APPLICATION_REJECTED",
        }:
            approved = event_type.endswith("APPROVED")
            if member:
                campaign = await self.database.fetchone(
                    "SELECT candidate_role_id FROM recruitment_campaigns WHERE id=?",
                    (application["campaign_id"],),
                )
                if campaign and campaign["candidate_role_id"]:
                    role = guild.get_role(int(campaign["candidate_role_id"]))
                    if role and role in member.roles:
                        await member.remove_roles(role, reason="Decisão final do recrutamento")
                title = "Candidatura aprovada" if approved else "Resultado da candidatura"
                description = str(
                    application["candidate_message"] or "Consulte seu protocolo no portal."
                )
                if approved:
                    tag_channel_id = await self.audit.settings.get(
                        int(row["guild_id"]), "recruitment_tag_setup_channel_id"
                    )
                    if tag_channel_id:
                        tag_channel = guild.get_channel(int(tag_channel_id))
                        if not isinstance(tag_channel, discord.TextChannel):
                            try:
                                tag_channel = await self.bot.fetch_channel(int(tag_channel_id))
                            except discord.DiscordException:
                                tag_channel = None
                        if isinstance(tag_channel, discord.TextChannel):
                            try:
                                await tag_channel.set_permissions(
                                    member,
                                    view_channel=True,
                                    send_messages=True,
                                    read_message_history=True,
                                    attach_files=True,
                                    embed_links=True,
                                    reason="Candidato aprovado • acesso à setagem",
                                )
                            except discord.DiscordException:
                                LOGGER.exception(
                                    "Falha ao liberar canal de setagem para o candidato %s",
                                    member.id,
                                )
                        description += (
                            "\n\n**Próxima ordem:** acesse "
                            f"<#{int(tag_channel_id)}> e informe seu **ID**, "
                            "**horário disponível** e **localização no jogo** para a setagem."
                        )
                try:
                    message = await member.send(
                        embed=self._recruitment_embed(
                            title,
                            application,
                            description,
                            approved=approved,
                        )
                    )
                except discord.Forbidden:
                    return await self._recruitment_dm_fallback(
                        row, application, "Mensagens privadas bloqueadas pelo candidato."
                    )
                return message.channel.id, message.id
            return await self._recruitment_dm_fallback(
                row, application, "Candidato não está disponível no servidor."
            )
        if event_type in {
            "RECRUITMENT_APPLICATION_APPROVED_LOG",
            "RECRUITMENT_APPLICATION_REJECTED_LOG",
        }:
            approved = "APPROVED" in event_type
            setting_key = (
                "recruitment_approved_channel_id" if approved else "recruitment_rejected_channel_id"
            )
            channel_id = await self.audit.settings.get(int(row["guild_id"]), setting_key)
            if not channel_id:
                channel_id = await self.audit.settings.get(
                    int(row["guild_id"]), "recruitment_notification_channel_id"
                )
            if not channel_id:
                raise RuntimeError("Canal de resultado do recrutamento não configurado")
            channel = self.bot.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                channel = await self.bot.fetch_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                raise RuntimeError("Canal de resultado não é textual")
            review_sla_hours = await self.audit.settings.get(
                int(row["guild_id"]), "recruitment_review_sla_hours", 72
            )
            mention = f"<@{int(application['discord_id'])}>" if approved else None
            embed = self._recruitment_public_embed(application, int(review_sla_hours))
            allowed_mentions = (
                discord.AllowedMentions(
                    everyone=False,
                    roles=False,
                    users=[discord.Object(id=int(application["discord_id"]))],
                    replied_user=False,
                )
                if approved
                else discord.AllowedMentions.none()
            )
            previous = await self.database.fetchone(
                """
                SELECT delivery_channel_id, delivery_message_id
                FROM recruitment_notification_outbox
                WHERE guild_id=? AND application_id=? AND event_type=?
                  AND status='COMPLETED' AND delivery_message_id IS NOT NULL
                  AND id<>?
                ORDER BY processed_at DESC, id DESC LIMIT 1
                """,
                (
                    int(row["guild_id"]),
                    int(application["id"]),
                    event_type,
                    int(row["id"]),
                ),
            )
            if previous:
                previous_channel = self.bot.get_channel(
                    int(previous["delivery_channel_id"])
                )
                if not isinstance(previous_channel, discord.TextChannel):
                    previous_channel = await self.bot.fetch_channel(
                        int(previous["delivery_channel_id"])
                    )
                if isinstance(previous_channel, discord.TextChannel):
                    try:
                        previous_message = await previous_channel.fetch_message(
                            int(previous["delivery_message_id"])
                        )
                    except discord.NotFound:
                        pass
                    else:
                        await previous_message.edit(
                            content=mention,
                            embed=embed,
                            allowed_mentions=allowed_mentions,
                        )
                        return previous_message.channel.id, previous_message.id
            message = await channel.send(
                content=mention,
                embed=embed,
                allowed_mentions=allowed_mentions,
            )
            return message.channel.id, message.id
        if event_type not in {
            "RECRUITMENT_APPLICATION_SUBMITTED",
        }:
            raise ValueError(f"Evento de recrutamento não suportado: {event_type}")
        channel_id = None
        for key in (
            "recruitment_review_channel_id",
            "recruitment_notification_channel_id",
            "recruitment_queue_channel_id",
            "personnel_admin_channel_id",
        ):
            channel_id = await self.audit.settings.get(int(row["guild_id"]), key)
            if channel_id:
                break
        if not channel_id:
            raise RuntimeError("Canal de notificações do recrutamento não configurado")
        channel = self.bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            fetched = await self.bot.fetch_channel(int(channel_id))
            if not isinstance(fetched, discord.TextChannel):
                raise RuntimeError("Canal configurado não é textual")
            channel = fetched
        public_url = await self.audit.settings.get(int(row["guild_id"]), "recruitment_public_url")
        view = build_recruitment_review_view(application, public_url)
        embed = build_recruitment_review_embed(self.bot.config.branding, application)
        attachment = None
        if event_type == "RECRUITMENT_APPLICATION_SUBMITTED":
            answers = await self.database.fetchall(
                """
                SELECT question_snapshot_json, final_answer_json
                FROM recruitment_application_questions
                WHERE application_id=? ORDER BY ordinal
                """,
                (int(application["id"]),),
            )
            lines = [f"CANDIDATURA {application['protocol']}", ""]
            for index, answer in enumerate(answers, 1):
                question = json.loads(answer["question_snapshot_json"])
                value = json.loads(answer["final_answer_json"]) if answer["final_answer_json"] else "Sem resposta"
                rendered = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
                lines.extend((f"Q{index:02d} — {question.get('title', 'Questão')}", rendered, ""))
            attachment = discord.File(
                io.BytesIO("\n".join(lines).encode("utf-8")),
                filename=f"{application['protocol']}-respostas.txt",
            )
            embed.add_field(
                name="Dossiê recebido",
                value=f"{len(answers)} respostas completas anexadas para análise do recrutador.",
                inline=False,
            )
        mention_content = None
        allowed_mentions = discord.AllowedMentions.none()
        if event_type in {
            "RECRUITMENT_APPLICATION_SUBMITTED",
            "RECRUITMENT_APPLICATION_STALE",
        }:
            staff_rows = await self.database.fetchall(
                """
                SELECT DISTINCT discord_role_id FROM discord_role_mappings
                WHERE guild_id=? AND mapping_type='POSITION' AND enabled=1
                  AND internal_code IN ('RECRUITMENT_LEAD','RECRUITER')
                ORDER BY priority DESC, discord_role_id
                """,
                (int(row["guild_id"]),),
            )
            staff_role_ids = [
                int(item["discord_role_id"])
                for item in staff_rows
                if guild.get_role(int(item["discord_role_id"])) is not None
            ]
            if staff_role_ids:
                mention_content = "🔔 " + " ".join(
                    f"<@&{role_id}>" for role_id in staff_role_ids
                )
                allowed_mentions = discord.AllowedMentions(
                    everyone=False,
                    users=False,
                    roles=[discord.Object(id=role_id) for role_id in staff_role_ids],
                    replied_user=False,
                )
        message = await channel.send(
            content=mention_content,
            embed=embed,
            view=view,
            file=attachment,
            allowed_mentions=allowed_mentions,
        )
        return message.channel.id, message.id

    async def _refresh_recruitment_review_card(self, row, application) -> tuple[int | None, int | None]:
        """Edit the single private review card; never publish a second one."""
        event_id = row["id"] if "id" in row.keys() else "unknown"
        original = await self.database.fetchone(
            """
            SELECT delivery_channel_id, delivery_message_id
            FROM recruitment_notification_outbox
            WHERE guild_id=? AND application_id=?
              AND event_type='RECRUITMENT_APPLICATION_SUBMITTED'
              AND status='COMPLETED' AND delivery_channel_id IS NOT NULL
              AND delivery_message_id IS NOT NULL
            ORDER BY processed_at DESC, id DESC LIMIT 1
            """,
            (int(row["guild_id"]), int(application["id"])),
        )
        if not original:
            # Legacy follow-up rows can survive a migration or a manual deletion of
            # an old review card.  Recreating a card here would duplicate the
            # candidate's Mesa entry, so keep the durable outbox history and finish
            # this refresh as a no-op.  A newly delivered submission already renders
            # the current domain state, so it does not need a second refresh either.
            LOGGER.info(
                "Skipping review-card refresh %s: no original submitted card for application %s",
                event_id,
                application["id"],
            )
            return None, None
        channel_id = int(original["delivery_channel_id"])
        message_id = int(original["delivery_message_id"])
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            fetched = await self.bot.fetch_channel(channel_id)
            if not isinstance(fetched, discord.TextChannel):
                raise RuntimeError("Canal da Mesa de Análise não é textual")
            channel = fetched
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            # Do not resurrect an intentionally removed legacy card and create a
            # duplicate in the private review queue.  The final decision and audit
            # records remain durable in the database.
            LOGGER.info(
                "Skipping review-card refresh %s: original card %s is no longer present",
                event_id,
                message_id,
            )
            return None, None
        public_url = await self.audit.settings.get(int(row["guild_id"]), "recruitment_public_url")
        await message.edit(
            embed=build_recruitment_review_embed(self.bot.config.branding, application),
            view=build_recruitment_review_view(application, public_url),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return channel.id, message.id

    async def _dispatch_recruitment_public_status(
        self,
        row,
        application,
    ) -> tuple[int | None, int | None]:
        guild_id = int(row["guild_id"])
        channel_id = await self.audit.settings.get(
            guild_id, "recruitment_public_status_channel_id"
        )
        if not channel_id:
            raise RuntimeError("Canal público de candidaturas não configurado")
        channel = self.bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            channel = await self.bot.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError("Canal público de candidaturas não é textual")
        review_sla_hours = int(
            await self.audit.settings.get(guild_id, "recruitment_review_sla_hours", 72)
        )
        embed = self._recruitment_public_embed(application, review_sla_hours)
        approved = str(application["status"]) == "APPROVED"
        mention = f"<@{int(application['discord_id'])}>" if approved else None
        allowed_mentions = (
            discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=[discord.Object(id=int(application["discord_id"]))],
                replied_user=False,
            )
            if approved
            else discord.AllowedMentions.none()
        )
        view = None
        public_url = await self.audit.settings.get(guild_id, "recruitment_public_url")
        if isinstance(public_url, str) and public_url.startswith(("https://", "http://")):
            parsed_url = urlsplit(public_url)
            status_url = f"{parsed_url.scheme}://{parsed_url.netloc}/minha-candidatura"
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label="Acompanhar candidatura",
                    style=discord.ButtonStyle.link,
                    url=status_url,
                )
            )
        previous = await self.database.fetchone(
            """
            SELECT delivery_channel_id, delivery_message_id
            FROM recruitment_notification_outbox
            WHERE guild_id=? AND application_id=?
              AND event_type='RECRUITMENT_PUBLIC_STATUS'
              AND status='COMPLETED' AND delivery_message_id IS NOT NULL
              AND id<>?
            ORDER BY processed_at DESC, id DESC LIMIT 1
            """,
            (guild_id, int(application["id"]), int(row["id"])),
        )
        if previous:
            previous_channel = self.bot.get_channel(int(previous["delivery_channel_id"]))
            if not isinstance(previous_channel, discord.TextChannel):
                previous_channel = await self.bot.fetch_channel(
                    int(previous["delivery_channel_id"])
                )
            if isinstance(previous_channel, discord.TextChannel):
                try:
                    message = await previous_channel.fetch_message(
                        int(previous["delivery_message_id"])
                    )
                except discord.NotFound:
                    pass
                else:
                    await message.edit(
                        content=mention,
                        embed=embed,
                        view=view,
                        allowed_mentions=allowed_mentions,
                    )
                    return message.channel.id, message.id
        message = await channel.send(
            content=mention,
            embed=embed,
            view=view,
            allowed_mentions=allowed_mentions,
        )
        return message.channel.id, message.id

    async def _recruitment_dm_fallback(
        self,
        row,
        application,
        reason: str,
    ) -> tuple[int | None, int | None]:
        guild_id = int(row["guild_id"])
        channel_id = await self.audit.settings.get(guild_id, "recruitment_review_channel_id")
        if not channel_id:
            raise RuntimeError(f"Resultado não entregue por DM: {reason}")
        channel = self.bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            channel = await self.bot.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"Resultado não entregue por DM: {reason}")
        await self.audit.record(
            guild_id,
            "RECRUITMENT_RESULT_DM_UNDELIVERABLE",
            target_id=int(application["discord_id"]),
            after={"application_id": int(application["id"]), "reason": reason},
            deliver_immediately=False,
        )
        embed = self._recruitment_embed(
            "Entrega privada pendente",
            application,
            f"{reason} O resultado administrativo foi preservado; contate o candidato pelo servidor.",
            approved=str(application["status"]) == "APPROVED",
        )
        message = await channel.send(
            content=f"⚠️ <@{int(application['discord_id'])}>",
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return message.channel.id, message.id

    def _recruitment_embed(
        self,
        title: str,
        application,
        description: str,
        *,
        approved: bool | None = None,
    ) -> discord.Embed:
        if approved is True:
            color = 0x71906D
        elif approved is False:
            color = 0xA94F43
        else:
            color = self.audit.branding.embed_color
        embed = discord.Embed(title=title, description=description, color=color)
        embed.add_field(name="Protocolo", value=str(application["protocol"]), inline=True)
        embed.add_field(name="Candidato", value=str(application["candidate_nick"]), inline=True)
        embed.add_field(name="ID BGR", value=str(application["bgr_id"]), inline=True)
        embed.set_footer(text=self.audit.branding.footer)
        return embed

    def _recruitment_public_embed(
        self,
        application,
        review_sla_hours: int,
    ) -> discord.Embed:
        data = dict(application)
        status = str(data.get("status") or "SUBMITTED")
        labels = {
            "SUBMITTED": "Recebida",
            "UNDER_REVIEW": "Em análise",
            "INTERVIEW_PENDING": "Entrevista pendente",
            "INTERVIEW_SCHEDULED": "Entrevista agendada",
            "INTERVIEW_COMPLETED": "Entrevista concluída",
            "FINAL_REVIEW": "Decisão final",
            "APPROVED": "Aprovada",
            "REJECTED": "Reprovada",
        }
        if status == "APPROVED":
            color = 0x71906D
        elif status == "REJECTED":
            color = 0xA94F43
        else:
            color = self.audit.branding.embed_color
        if status == "APPROVED":
            title = "🎖️ ALISTAMENTO APROVADO"
            description = (
                "**MISSÃO CUMPRIDA.** O protocolo concluiu o formulário com aprovação. "
                "A próxima orientação será comunicada pelos responsáveis do Recrutamento."
            )
        elif status == "REJECTED":
            title = "📋 PROCESSO SELETIVO ENCERRADO"
            description = (
                "O protocolo concluiu esta etapa sem aprovação. A decisão é registrada de "
                "forma reservada e respeitosa; dados pessoais e pareceres não são publicados."
            )
        else:
            title = "🛡️ ACOMPANHAMENTO DE ALISTAMENTO"
            description = (
                "Atualização pública e anonimizada. Dados pessoais e respostas "
                "permanecem restritos à equipe responsável."
            )
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_author(name="CHOQUE - BGR • COMANDO DE RECRUTAMENTO")
        embed.add_field(name="Protocolo", value=str(data.get("protocol") or "—"), inline=True)
        embed.add_field(name="Etapa", value=labels.get(status, status), inline=True)
        final = status in {"APPROVED", "REJECTED"}
        embed.add_field(
            name="Prazo",
            value=(
                "Processo concluído"
                if final
                else f"Até {max(1, min(720, review_sla_hours))} horas para a primeira análise"
            ),
            inline=False,
        )
        if status == "APPROVED":
            embed.add_field(
                name="Candidato convocado",
                value=f"<@{int(data['discord_id'])}>",
                inline=False,
            )
            embed.add_field(
                name="Ordem do dia",
                value="🏅 Consulte sua mensagem privada e apresente-se no canal de setagem.",
                inline=False,
            )
        elif status == "REJECTED":
            embed.add_field(
                name="Orientação",
                value="Consulte o protocolo no portal para verificar o encerramento do processo.",
                inline=False,
            )
        if self.audit.branding.logo_url:
            embed.set_thumbnail(url=self.audit.branding.logo_url)
        embed.set_footer(text=self.audit.branding.footer)
        return embed
