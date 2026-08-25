from __future__ import annotations

import json

import pytest

from choque.errors import ValidationError

from .conftest import DISCORD_ID, GUILD_ID


async def _declare_and_confirm(
    finance,
    *,
    discord_id: int = DISCORD_ID,
    key: str,
    visibility: str = "PUBLICO",
    public_amount: bool = False,
    project_id: int | None = None,
):
    contribution = await finance.declare_contribution(
        GUILD_ID,
        discord_id,
        amount="25,00",
        destination_kind="PROJETO" if project_id is not None else "FUNDO_GERAL",
        project_id=project_id,
        visibility=visibility,
        public_amount=public_amount,
        idempotency_key=key,
    )
    return await finance.confirm_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        expected_version=int(contribution["version"]),
        reason="Recebimento conferido administrativamente.",
    )


@pytest.mark.asyncio
async def test_highlight_is_single_privacy_safe_and_amount_needs_separate_consent(service_bundle):
    finance = service_bundle["financial_aid"]
    anonymous = await _declare_and_confirm(
        finance,
        key="highlight-anonymous",
        visibility="ANONIMO",
    )
    repeated = await finance.confirm_contribution(
        GUILD_ID,
        int(anonymous["id"]),
        actor_id=900,
        expected_version=1,
        reason="Retry idempotente.",
    )
    rows = await service_bundle["database"].fetchall(
        """
        SELECT * FROM financial_notifications
        WHERE guild_id=? AND event_key=?
        """,
        (GUILD_ID, f"financial-contribution-highlight:{anonymous['id']}"),
    )
    snapshot = await finance.contribution_highlight_snapshot(
        GUILD_ID, int(anonymous["id"])
    )

    assert repeated["id"] == anonymous["id"]
    assert len(rows) == 1
    assert rows[0]["notification_type"] == "CONTRIBUTION_HIGHLIGHT"
    assert rows[0]["target_discord_id"] is None
    assert rows[0]["channel_setting_key"] == "financial_highlights_channel_id"
    assert json.loads(rows[0]["payload_json"]) == {"canonical_snapshot": True}
    assert str(DISCORD_ID) not in rows[0]["payload_json"]
    assert "2500" not in rows[0]["payload_json"]
    assert snapshot["visibility"] == "ANONIMO"
    assert snapshot["discord_id"] is None
    assert snapshot["member_name"] == "Apoiador anônimo"
    assert snapshot["public_amount"] is False
    assert snapshot["amount_cents"] is None

    public = await _declare_and_confirm(
        finance,
        key="highlight-public-amount",
        visibility="PUBLICO",
        public_amount=True,
    )
    public_snapshot = await finance.contribution_highlight_snapshot(
        GUILD_ID, int(public["id"])
    )
    assert public_snapshot["discord_id"] == DISCORD_ID
    assert public_snapshot["member_name"] == "Choque_User"
    assert public_snapshot["public_amount"] is True
    assert public_snapshot["amount_cents"] == 2500

    with pytest.raises(ValidationError, match="consentimento"):
        await finance.declare_contribution(
            GUILD_ID,
            DISCORD_ID,
            amount="1,00",
            destination_kind="FUNDO_GERAL",
            visibility="PUBLICO",
            public_amount="sim",  # type: ignore[arg-type]
            idempotency_key="invalid-public-consent",
        )


@pytest.mark.asyncio
async def test_reversal_rearms_same_highlight_revision_and_stale_delivery_cannot_win(service_bundle):
    finance = service_bundle["financial_aid"]
    database = service_bundle["database"]
    contribution = await _declare_and_confirm(finance, key="highlight-reversal")
    highlight = await database.fetchone(
        "SELECT * FROM financial_notifications WHERE event_key=?",
        (f"financial-contribution-highlight:{contribution['id']}",),
    )
    assert highlight is not None
    await database.execute(
        """
        UPDATE financial_notifications
        SET status='PROCESSING', attempts=3, channel_message_id=777
        WHERE id=?
        """,
        (int(highlight["id"]),),
    )
    stale_revision = int(highlight["revision"])

    reversal = await finance.reverse_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        reason="Estorno administrativo documentado.",
    )
    async with database.transaction() as connection:
        stale_cursor = await connection.execute(
            """
            UPDATE financial_notifications
            SET status='DELIVERED'
            WHERE id=? AND status='PROCESSING' AND revision=?
            """,
            (int(highlight["id"]), stale_revision),
        )
        stale_update = int(stale_cursor.rowcount)
    refreshed = await database.fetchone(
        "SELECT * FROM financial_notifications WHERE id=?", (int(highlight["id"]),)
    )
    snapshot = await finance.contribution_highlight_snapshot(
        GUILD_ID, int(contribution["id"])
    )

    assert reversal["entry_type"] == "ESTORNO_CONTRIBUICAO"
    assert stale_update == 0
    assert refreshed["status"] == "PENDING"
    assert refreshed["channel_message_id"] == 777
    assert refreshed["attempts"] == 0
    assert refreshed["revision"] == stale_revision + 1
    assert snapshot["status"] == "ESTORNADA"
    assert snapshot["reversed_at"] is not None
    assert snapshot["reversal_reason"] == "Estorno administrativo documentado."

    repeated = await finance.reverse_contribution(
        GUILD_ID,
        int(contribution["id"]),
        actor_id=900,
        reason="Retry idempotente.",
    )
    unchanged = await database.fetchone(
        "SELECT revision FROM financial_notifications WHERE id=?", (int(highlight["id"]),)
    )
    assert repeated["id"] == reversal["id"]
    assert unchanged["revision"] == refreshed["revision"]


@pytest.mark.asyncio
async def test_automatic_symbolic_tiers_upgrade_and_downgrade_without_touching_patrono(service_bundle):
    finance = service_bundle["financial_aid"]
    patrono = await finance.grant_honor(
        GUILD_ID,
        DISCORD_ID,
        honor_key="PATRONO",
        actor_id=900,
        justification="Concessão humana fundamentada da liderança.",
    )
    project = await finance.create_project(
        GUILD_ID,
        actor_id=900,
        name="Infraestrutura comunitária",
        description="Projeto usado para validar destinos distintos.",
        category="INFRAESTRUTURA",
        target_amount="500,00",
    )

    first = await _declare_and_confirm(finance, key="tier-first")
    profile = await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID)
    assert {item["honor_key"] for item in profile["honors"]} == {"APOIADOR", "PATRONO"}

    second = await _declare_and_confirm(finance, key="tier-second")
    profile = await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID)
    assert {item["honor_key"] for item in profile["honors"]} == {"COLABORADOR", "PATRONO"}

    third = await _declare_and_confirm(
        finance,
        key="tier-third-project",
        project_id=int(project["id"]),
    )
    profile = await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID)
    assert {item["honor_key"] for item in profile["honors"]} == {"BENFEITOR", "PATRONO"}

    await finance.reverse_contribution(
        GUILD_ID, int(third["id"]), actor_id=900, reason="Estorno do terceiro apoio."
    )
    profile = await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID)
    assert {item["honor_key"] for item in profile["honors"]} == {"COLABORADOR", "PATRONO"}

    await finance.reverse_contribution(
        GUILD_ID, int(second["id"]), actor_id=900, reason="Estorno do segundo apoio."
    )
    profile = await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID)
    assert {item["honor_key"] for item in profile["honors"]} == {"APOIADOR", "PATRONO"}

    await finance.reverse_contribution(
        GUILD_ID, int(first["id"]), actor_id=900, reason="Estorno do primeiro apoio."
    )
    profile = await finance.member_honor_snapshot(GUILD_ID, DISCORD_ID)
    assert {item["honor_key"] for item in profile["honors"]} == {"PATRONO"}
    assert profile["honors"][0]["id"] == patrono["id"]

    active_duplicates = await service_bundle["database"].fetchall(
        """
        SELECT honor_definition_id, COUNT(*) AS total
        FROM financial_member_honors
        WHERE guild_id=? AND member_id=? AND removed_at IS NULL
        GROUP BY honor_definition_id HAVING COUNT(*)>1
        """,
        (GUILD_ID, int(profile["honors"][0]["member_id"])),
    )
    assert active_duplicates == []


@pytest.mark.asyncio
async def test_backfill_two_confirmed_donors_preserves_ledger_and_recovers_only_nonce_failures(service_bundle):
    finance = service_bundle["financial_aid"]
    database = service_bundle["database"]
    second_discord_id = 789
    await service_bundle["members"].create_or_update(
        GUILD_ID,
        second_discord_id,
        discord_nick="Segundo Doador",
        mta_nick="Segundo_Doador",
        character_id="88",
        unit="BGR",
        rank_id=None,
        actor_id=900,
    )
    first = await _declare_and_confirm(finance, key="legacy-donor-one")
    second = await _declare_and_confirm(
        finance,
        discord_id=second_discord_id,
        key="legacy-donor-two",
        visibility="ANONIMO",
    )
    ledger_before = await finance.ledger_entries(GUILD_ID)

    await database.execute(
        "DELETE FROM financial_notifications WHERE notification_type='CONTRIBUTION_HIGHLIGHT'"
    )
    await database.execute(
        """
        UPDATE financial_member_honors
        SET removed_at=?, removal_reason='Simulação de estado legado', version=version+1
        WHERE guild_id=? AND source='AUTOMATICA' AND removed_at IS NULL
        """,
        (service_bundle["clock"](), GUILD_ID),
    )
    failed = await database.fetchone(
        """
        SELECT id FROM financial_notifications
        WHERE guild_id=? AND notification_type='CONTRIBUTION_DECIDED'
        ORDER BY id LIMIT 1
        """,
        (GUILD_ID,),
    )
    unrelated = await database.fetchone(
        """
        SELECT id FROM financial_notifications
        WHERE guild_id=? AND notification_type='HONOR_GRANTED'
        ORDER BY id LIMIT 1
        """,
        (GUILD_ID,),
    )
    await database.execute(
        "UPDATE financial_notifications SET status='FAILED', attempts=8, last_error=? WHERE id=?",
        ("send() got an unexpected keyword argument 'enforce_nonce'", int(failed["id"])),
    )
    await database.execute(
        "UPDATE financial_notifications SET status='FAILED', attempts=8, last_error=? WHERE id=?",
        ("Missing Access", int(unrelated["id"])),
    )

    result = await finance.reconcile_confirmed_contributions(GUILD_ID, actor_id=900)
    repeated = await finance.reconcile_confirmed_contributions(GUILD_ID, actor_id=900)
    ledger_after = await finance.ledger_entries(GUILD_ID)
    highlights = await database.fetchall(
        """
        SELECT subject_id, event_key, payload_json FROM financial_notifications
        WHERE guild_id=? AND notification_type='CONTRIBUTION_HIGHLIGHT'
        ORDER BY subject_id
        """,
        (GUILD_ID,),
    )
    recovered = await database.fetchone(
        "SELECT status, attempts, last_error FROM financial_notifications WHERE id=?",
        (int(failed["id"]),),
    )
    still_failed = await database.fetchone(
        "SELECT status, attempts, last_error FROM financial_notifications WHERE id=?",
        (int(unrelated["id"]),),
    )

    assert result == {
        "confirmed_contributions": 2,
        "highlights_created": 2,
        "honor_changes": 2,
        "recovered_notifications": 1,
    }
    assert repeated == {
        "confirmed_contributions": 2,
        "highlights_created": 0,
        "honor_changes": 0,
        "recovered_notifications": 0,
    }
    assert [(row["id"], row["amount_cents"]) for row in ledger_after] == [
        (row["id"], row["amount_cents"]) for row in ledger_before
    ]
    assert {row["subject_id"] for row in highlights} == {first["id"], second["id"]}
    assert all(json.loads(row["payload_json"]) == {"canonical_snapshot": True} for row in highlights)
    assert recovered["status"] == "PENDING"
    assert recovered["attempts"] == 0
    assert recovered["last_error"] is None
    assert still_failed["status"] == "FAILED"
    assert still_failed["attempts"] == 8
    assert still_failed["last_error"] == "Missing Access"
    for discord_id in (DISCORD_ID, second_discord_id):
        profile = await finance.member_honor_snapshot(GUILD_ID, discord_id)
        assert [item["honor_key"] for item in profile["honors"]] == ["APOIADOR"]


@pytest.mark.asyncio
async def test_highlights_channel_configuration_is_audited_without_channel_io(service_bundle):
    finance = service_bundle["financial_aid"]
    result = await finance.configure_highlights_channel(
        GUILD_ID,
        actor_id=900,
        channel_id=123456,
    )
    setting = await service_bundle["settings"].get(
        GUILD_ID, "financial_highlights_channel_id"
    )
    audit = await service_bundle["database"].fetchone(
        """
        SELECT actor_id, after_json FROM financial_audit_events
        WHERE guild_id=? AND event_type='FINANCIAL_HIGHLIGHTS_CHANNEL_CONFIGURED'
        """,
        (GUILD_ID,),
    )
    assert result == {"channel_id": 123456}
    assert setting == 123456
    assert audit["actor_id"] == 900
    assert json.loads(audit["after_json"]) == {"configured": True}
