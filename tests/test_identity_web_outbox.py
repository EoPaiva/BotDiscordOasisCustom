from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from choque.rank_sync import RankSyncResult, ReconciliationSummary
from choque.time_utils import utc_now_ms
from choque.web_outbox import WebActionWorker

from .conftest import DISCORD_ID, GUILD_ID


@dataclass(slots=True)
class _NotFoundResponse:
    status: int = 404
    reason: str = "Not Found"


class _FakeGuild:
    def __init__(self, member: object | None = None, *, absent: bool = False) -> None:
        self.id = GUILD_ID
        self._member = member
        self._absent = absent

    def get_member(self, discord_id: int):
        assert discord_id == DISCORD_ID
        return self._member

    async def fetch_member(self, discord_id: int):
        assert discord_id == DISCORD_ID
        if self._absent:
            raise discord.NotFound(_NotFoundResponse(), "Unknown Member")
        if self._member is None:
            raise RuntimeError("consulta ao Discord indisponível")
        return self._member


class _FakeBot:
    def __init__(self, guild: _FakeGuild) -> None:
        self._guild = guild

    def get_guild(self, guild_id: int):
        return self._guild if guild_id == GUILD_ID else None


def _rank_sync_stub() -> SimpleNamespace:
    return SimpleNamespace(
        sync_from_member=AsyncMock(),
        sync_to_member=AsyncMock(),
        mark_discord_absent=AsyncMock(),
        process_reconciliation_job=AsyncMock(),
    )


def _worker(service_bundle, guild: _FakeGuild, *, audit=None):
    rank_sync = _rank_sync_stub()
    if audit is None:
        audit = SimpleNamespace(record=AsyncMock(), settings=None)
    worker = WebActionWorker(
        service_bundle["database"],
        rank_sync,
        audit,
        _FakeBot(guild),
    )
    return worker, rank_sync, audit


async def _enqueue(
    service_bundle,
    *,
    action_type: str,
    payload: dict[str, object] | None = None,
    target_discord_id: int | None = DISCORD_ID,
    status: str = "PENDING",
    correlation_id: str = "identity-outbox-test",
) -> int:
    now = utc_now_ms()
    return await service_bundle["database"].execute(
        """
        INSERT INTO web_action_outbox(
            guild_id, action_type, target_discord_id, payload_json,
            requested_by, correlation_id, status, available_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            GUILD_ID,
            action_type,
            target_discord_id,
            json.dumps(payload or {}),
            DISCORD_ID,
            correlation_id,
            status,
            now,
            now,
        ),
    )


@pytest.mark.asyncio
async def test_restart_recovers_processing_outbox_and_reconciliation_job(
    service_bundle,
) -> None:
    database = service_bundle["database"]
    action_id = await _enqueue(
        service_bundle,
        action_type="IDENTITY_RECONCILE_BULK",
        payload={"job_id": 1},
        target_discord_id=None,
        status="PROCESSING",
    )
    job_id = await database.execute(
        """
        INSERT INTO identity_reconciliation_jobs(
            guild_id, mode, status, requested_by, correlation_id,
            created_at, started_at
        ) VALUES (?, 'PREVIEW', 'PROCESSING', ?, ?, ?, ?)
        """,
        (GUILD_ID, DISCORD_ID, "processing-job", utc_now_ms(), utc_now_ms()),
    )
    worker, _, _ = _worker(service_bundle, _FakeGuild())

    before_recovery = utc_now_ms()
    await worker._recover_inflight_actions()

    action = await database.fetchone("SELECT * FROM web_action_outbox WHERE id=?", (action_id,))
    job = await database.fetchone(
        "SELECT * FROM identity_reconciliation_jobs WHERE id=?", (job_id,)
    )
    assert action is not None
    assert action["status"] == "FAILED"
    assert int(action["attempts"]) == 0
    assert int(action["available_at"]) >= before_recovery
    assert action["last_error"] == "Recuperado após reinício do worker"
    assert job is not None
    assert job["status"] == "FAILED"
    assert job["completed_at"] is not None
    assert job["last_error"] == "Recuperado após reinício do worker"


@pytest.mark.asyncio
async def test_identity_sync_dispatches_member_and_completes_outbox(service_bundle) -> None:
    member = SimpleNamespace(id=DISCORD_ID)
    worker, rank_sync, audit = _worker(service_bundle, _FakeGuild(member))
    rank_sync.sync_from_member.return_value = RankSyncResult(
        True,
        DISCORD_ID,
        "COMMAND_CENTER_WEB",
        identity_sync_status="SYNCED",
    )
    action_id = await _enqueue(
        service_bundle,
        action_type="IDENTITY_SYNC",
        payload={"source": "WEB_MANUAL_SYNC"},
    )

    assert await worker.process_pending() == 1

    rank_sync.sync_from_member.assert_awaited_once_with(
        member,
        source="WEB_MANUAL_SYNC",
        actor_id=DISCORD_ID,
        correlation_id="identity-outbox-test",
    )
    rank_sync.sync_to_member.assert_not_awaited()
    action = await service_bundle["database"].fetchone(
        "SELECT * FROM web_action_outbox WHERE id=?", (action_id,)
    )
    assert action is not None
    assert action["status"] == "COMPLETED"
    assert int(action["attempts"]) == 1
    assert action["processed_at"] is not None
    audit.record.assert_awaited_once()
    assert audit.record.await_args.args[1] == "DISCORD_IDENTITY_SYNC_COMPLETED"


@pytest.mark.asyncio
async def test_crash_after_identity_dispatch_retries_with_single_success_audit(
    service_bundle,
) -> None:
    member = SimpleNamespace(id=DISCORD_ID)
    audit = service_bundle["audit"]
    worker, rank_sync, _ = _worker(service_bundle, _FakeGuild(member), audit=audit)
    rank_sync.sync_from_member.return_value = RankSyncResult(
        True,
        DISCORD_ID,
        "COMMAND_CENTER_WEB",
        identity_sync_status="SYNCED",
    )
    action_id = await _enqueue(
        service_bundle,
        action_type="IDENTITY_SYNC",
        payload={"source": "WEB_MANUAL_SYNC"},
        correlation_id="identity-crash-boundary",
    )
    worker._complete_action = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await worker.process_pending()

    interrupted = await service_bundle["database"].fetchone(
        "SELECT status, attempts FROM web_action_outbox WHERE id=?", (action_id,)
    )
    assert interrupted is not None
    assert interrupted["status"] == "PROCESSING"
    assert int(interrupted["attempts"]) == 0
    assert rank_sync.sync_from_member.await_count == 1
    audit_count = await service_bundle["database"].fetchone(
        """
        SELECT COUNT(*) AS total FROM audit_logs
        WHERE action='DISCORD_IDENTITY_SYNC_COMPLETED'
          AND correlation_id='identity-crash-boundary:audit:outbox-completed-'
              || CAST(? AS TEXT)
        """
        ,
        (action_id,),
    )
    assert audit_count is not None
    assert int(audit_count["total"]) == 0

    retry_worker = WebActionWorker(
        service_bundle["database"],
        rank_sync,
        audit,
        _FakeBot(_FakeGuild(member)),
    )
    await retry_worker._recover_inflight_actions()
    assert await retry_worker.process_pending() == 1

    completed = await service_bundle["database"].fetchone(
        "SELECT status, attempts FROM web_action_outbox WHERE id=?", (action_id,)
    )
    assert completed is not None
    assert completed["status"] == "COMPLETED"
    assert int(completed["attempts"]) == 1
    assert rank_sync.sync_from_member.await_count == 2
    audits = await service_bundle["database"].fetchall(
        """
        SELECT action, correlation_id FROM audit_logs
        WHERE action='DISCORD_IDENTITY_SYNC_COMPLETED'
          AND correlation_id='identity-crash-boundary:audit:outbox-completed-'
              || CAST(? AS TEXT)
        """
        ,
        (action_id,),
    )
    assert len(audits) == 1


@pytest.mark.asyncio
async def test_identity_sync_marks_registered_member_absent_on_discord_not_found(
    service_bundle,
) -> None:
    worker, rank_sync, audit = _worker(service_bundle, _FakeGuild(absent=True))
    rank_sync.mark_discord_absent.return_value = RankSyncResult(
        True,
        DISCORD_ID,
        "COMMAND_CENTER_WEB",
        db_changed=True,
        identity_sync_status="DISCORD_ABSENT",
        discord_present=False,
    )
    action_id = await _enqueue(
        service_bundle,
        action_type="IDENTITY_SYNC",
        payload={"source": "WEB_MANUAL_SYNC"},
    )

    assert await worker.process_pending() == 1

    rank_sync.mark_discord_absent.assert_awaited_once_with(
        GUILD_ID,
        DISCORD_ID,
        source="WEB_MANUAL_SYNC",
        actor_id=DISCORD_ID,
        correlation_id="identity-outbox-test",
    )
    rank_sync.sync_from_member.assert_not_awaited()
    action = await service_bundle["database"].fetchone(
        "SELECT status, attempts, last_error FROM web_action_outbox WHERE id=?",
        (action_id,),
    )
    assert action is not None
    assert action["status"] == "COMPLETED"
    assert int(action["attempts"]) == 1
    assert action["last_error"] is None
    audit.record.assert_awaited_once()
    assert audit.record.await_args.kwargs["after"]["identity_sync_status"] == "DISCORD_ABSENT"


@pytest.mark.asyncio
async def test_bulk_reconciliation_dispatches_persisted_job(service_bundle) -> None:
    worker, rank_sync, audit = _worker(service_bundle, _FakeGuild())
    rank_sync.process_reconciliation_job.return_value = ReconciliationSummary(
        checked=4,
        changed=2,
        unchanged=2,
        absent=0,
        failed=0,
    )
    action_id = await _enqueue(
        service_bundle,
        action_type="IDENTITY_RECONCILE_BULK",
        payload={"job_id": 91, "source": "COMMAND_CENTER_RECONCILIATION"},
        target_discord_id=None,
    )

    assert await worker.process_pending() == 1

    rank_sync.process_reconciliation_job.assert_awaited_once_with(
        91,
        worker.bot.get_guild(GUILD_ID),
        source="COMMAND_CENTER_RECONCILIATION",
        correlation_id="identity-outbox-test",
    )
    action = await service_bundle["database"].fetchone(
        "SELECT status, attempts FROM web_action_outbox WHERE id=?", (action_id,)
    )
    assert action is not None
    assert action["status"] == "COMPLETED"
    assert int(action["attempts"]) == 1
    audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_reconciliation_with_failed_members_is_retried(service_bundle) -> None:
    worker, rank_sync, _ = _worker(service_bundle, _FakeGuild())
    rank_sync.process_reconciliation_job.side_effect = [
        ReconciliationSummary(
            checked=3,
            changed=1,
            unchanged=2,
            absent=0,
            failed=1,
            errors=("456: Forbidden",),
        ),
        ReconciliationSummary(
            checked=4,
            changed=2,
            unchanged=2,
            absent=0,
            failed=0,
        ),
    ]
    action_id = await _enqueue(
        service_bundle,
        action_type="IDENTITY_RECONCILE_BULK",
        payload={"job_id": 92, "source": "COMMAND_CENTER_RECONCILIATION"},
        target_discord_id=None,
    )

    assert await worker.process_pending() == 0

    failed = await service_bundle["database"].fetchone(
        "SELECT status, attempts, last_error FROM web_action_outbox WHERE id=?",
        (action_id,),
    )
    assert failed is not None
    assert failed["status"] == "FAILED"
    assert int(failed["attempts"]) == 1
    assert failed["last_error"] == "Reconciliação 92 terminou com 1 falha(s)"
    await service_bundle["database"].execute(
        "UPDATE web_action_outbox SET available_at=0 WHERE id=?", (action_id,)
    )

    assert await worker.process_pending() == 1

    completed = await service_bundle["database"].fetchone(
        "SELECT status, attempts, last_error FROM web_action_outbox WHERE id=?",
        (action_id,),
    )
    assert completed is not None
    assert completed["status"] == "COMPLETED"
    assert int(completed["attempts"]) == 2
    assert completed["last_error"] is None
    assert rank_sync.process_reconciliation_job.await_count == 2


@pytest.mark.asyncio
async def test_failed_identity_sync_becomes_retryable_then_completes(service_bundle) -> None:
    member = SimpleNamespace(id=DISCORD_ID)
    worker, rank_sync, audit = _worker(service_bundle, _FakeGuild(member))
    rank_sync.sync_from_member.side_effect = [
        RuntimeError("Discord temporariamente indisponível"),
        RankSyncResult(True, DISCORD_ID, "COMMAND_CENTER_WEB"),
    ]
    action_id = await _enqueue(
        service_bundle,
        action_type="IDENTITY_SYNC",
        payload={"source": "WEB_MANUAL_SYNC"},
    )

    assert await worker.process_pending() == 0

    failed = await service_bundle["database"].fetchone(
        "SELECT * FROM web_action_outbox WHERE id=?", (action_id,)
    )
    assert failed is not None
    assert failed["status"] == "FAILED"
    assert int(failed["attempts"]) == 1
    assert int(failed["available_at"]) > utc_now_ms()
    assert failed["last_error"] == "Discord temporariamente indisponível"
    await service_bundle["database"].execute(
        "UPDATE web_action_outbox SET available_at=0 WHERE id=?", (action_id,)
    )

    assert await worker.process_pending() == 1

    completed = await service_bundle["database"].fetchone(
        "SELECT * FROM web_action_outbox WHERE id=?", (action_id,)
    )
    assert completed is not None
    assert completed["status"] == "COMPLETED"
    assert int(completed["attempts"]) == 2
    assert completed["processed_at"] is not None
    assert completed["last_error"] is None
    assert rank_sync.sync_from_member.await_count == 2
    assert [call.args[1] for call in audit.record.await_args_list] == [
        "DISCORD_SYNC_FAILED",
        "DISCORD_IDENTITY_SYNC_COMPLETED",
    ]
