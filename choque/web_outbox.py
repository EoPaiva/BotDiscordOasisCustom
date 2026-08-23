from __future__ import annotations

import asyncio
import io
import json
import logging
from contextlib import suppress

import discord

from .audit import AuditService
from .database import Database
from .rank_sync import RankSyncResult, RankSyncService
from .time_utils import utc_now_ms

LOGGER = logging.getLogger(__name__)


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
    ) -> None:
        self.database = database
        self.rank_sync = rank_sync
        self.audit = audit
        self.bot = bot
        self._task: asyncio.Task[None] | None = None
        self._last_registry_refresh = 0
        self._last_stale_scan = 0
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
                processed = await self.process_pending()
                processed += await self.process_recruitment_pending()
            except Exception:
                LOGGER.exception("Falha no worker de ações do Command Center")
                processed = 0
            await asyncio.sleep(2 if processed else 10)

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
            ORDER BY created_at, id LIMIT ?
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
        event = "REGISTRATION_ACCESS_GRANTED" if success else "REGISTRATION_SYNC_FAILED"
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                UPDATE registration_gate_records
                SET sync_status=?, sync_error=?, last_attempt_at=?,
                    version=version+1, updated_at=? WHERE id=?
                """,
                (
                    "SYNCED" if success else "FAILED",
                    None if success else (error or "erro")[:500],
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
        rows = await self.database.fetchall(
            """
            SELECT * FROM recruitment_notification_outbox
            WHERE status IN ('PENDING','FAILED') AND attempts < 10 AND available_at <= ?
            ORDER BY created_at, id LIMIT ?
            """,
            (utc_now_ms(), limit),
        )
        processed = 0
        for row in rows:
            if not await self._claim_recruitment(int(row["id"])):
                continue
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
        if row["delivery_channel_id"] and row["delivery_message_id"]:
            channel = self.bot.get_channel(int(row["delivery_channel_id"]))
            if channel and hasattr(channel, "fetch_message"):
                try:
                    await channel.fetch_message(int(row["delivery_message_id"]))
                    return int(row["delivery_channel_id"]), int(row["delivery_message_id"])
                except discord.NotFound:
                    pass
        application = await self.database.fetchone(
            "SELECT * FROM recruitment_applications WHERE id=? AND guild_id=?",
            (row["application_id"], row["guild_id"]),
        )
        if not application:
            raise RuntimeError("Candidatura da notificação não encontrada")
        guild = self.bot.get_guild(int(row["guild_id"]))
        if not guild:
            raise RuntimeError("Guild indisponível no Discord")
        event_type = str(row["event_type"])
        payload = json.loads(row["payload_json"])
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
                message = await member.send(
                    embed=self._recruitment_embed(
                        title,
                        application,
                        str(
                            application["candidate_message"] or "Consulte seu protocolo no portal."
                        ),
                        approved=approved,
                    )
                )
                return message.channel.id, message.id
            raise RuntimeError("Candidato indisponível para notificação de resultado")
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
            message = await channel.send(
                embed=self._recruitment_embed(
                    "Candidatura aprovada" if approved else "Candidatura encerrada",
                    application,
                    "Decisão humana registrada. Consulte o dossiê protegido para os detalhes.",
                    approved=approved,
                )
            )
            return message.channel.id, message.id
        if event_type not in {
            "RECRUITMENT_APPLICATION_SUBMITTED",
            "RECRUITMENT_APPLICATION_STALE",
            "RECRUITMENT_ANALYSIS_COMPLETED",
        }:
            raise ValueError(f"Evento de recrutamento não suportado: {event_type}")
        channel_id = None
        for key in (
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
        view = None
        public_url = await self.audit.settings.get(int(row["guild_id"]), "recruitment_public_url")
        if isinstance(public_url, str) and public_url.startswith(("https://", "http://")):
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label="Analisar no painel",
                    style=discord.ButtonStyle.link,
                    url=f"{public_url.rstrip('/')}/recruitment/{application['id']}",
                )
            )
        stale = event_type == "RECRUITMENT_APPLICATION_STALE"
        analysis_completed = event_type == "RECRUITMENT_ANALYSIS_COMPLETED"
        embed = self._recruitment_embed(
                (
                    "Análise automatizada disponível"
                    if analysis_completed
                    else "Candidatura aguardando análise"
                    if stale
                    else "Nova candidatura recebida"
                ),
                application,
                (
                    f"O protocolo aguarda tratamento há pelo menos {int(payload['stale_hours'])} horas."
                    if stale
                    else "O relatório assistivo está disponível no dossiê. A decisão continua humana."
                    if analysis_completed
                    else "Conteúdo completo disponível somente no Centro de Comando."
                ),
            )
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
        elif analysis_completed:
            analysis = await self.database.fetchone(
                """
                SELECT recommendation, overall_score, summary
                FROM recruitment_analysis_results
                WHERE guild_id=? AND application_id=?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (int(row["guild_id"]), int(application["id"])),
            )
            if analysis:
                labels = {
                    "RECOMMENDED": "Recomendado para análise",
                    "REVIEW": "Revisão recomendada",
                    "NOT_RECOMMENDED": "Pontos relevantes para revisão",
                }
                embed.add_field(
                    name="Classificação consultiva",
                    value=f"{labels.get(str(analysis['recommendation']), 'Revisão humana')} • índice {int(analysis['overall_score'])}/100",
                    inline=False,
                )
                embed.add_field(
                    name="Resumo automatizado",
                    value=str(analysis["summary"])[:1024] or "Resumo indisponível.",
                    inline=False,
                )
        message = await channel.send(embed=embed, view=view, file=attachment)
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
