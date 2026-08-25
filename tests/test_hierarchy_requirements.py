from __future__ import annotations

from cogs.hierarchy_system import promotion_requirement_text


def test_automatic_rank_requirement_shows_cumulative_hours_and_tenure() -> None:
    text = promotion_requirement_text(
        {
            "level": 2,
            "target_total_ms": 8 * 3_600_000,
            "minimum_tenure_ms": 2 * 3_600_000,
            "next_rank_name": "Cabo",
        }
    )

    assert "Cabo" in text
    assert "08h00 totais" in text
    assert "02h00 na patente atual" in text
    assert "progressão automática" in text


def test_recruit_requirement_explains_zero_additional_tenure() -> None:
    text = promotion_requirement_text(
        {
            "level": 1,
            "target_total_ms": 4 * 3_600_000,
            "minimum_tenure_ms": 0,
            "next_rank_name": "Soldado",
        }
    )

    assert "04h00 totais" in text
    assert "sem permanência adicional" in text


def test_cadet_requires_human_officer_process() -> None:
    text = promotion_requirement_text(
        {
            "level": 8,
            "target_total_ms": None,
            "minimum_tenure_ms": None,
            "next_rank_name": None,
        }
    )

    assert "candidatura ao Oficialato" in text
    assert "decisão humana" in text
    assert "horas isoladamente não promovem" in text


def test_officer_rank_is_manual_and_audited() -> None:
    text = promotion_requirement_text(
        {
            "level": 9,
            "target_total_ms": None,
            "minimum_tenure_ms": None,
            "next_rank_name": None,
        }
    )

    assert "mérito" in text
    assert "manual e auditada" in text


def test_strategic_command_rank_has_no_public_hours_or_merit_requirement() -> None:
    text = promotion_requirement_text(
        {
            "level": 16,
            "target_total_ms": None,
            "minimum_tenure_ms": None,
            "next_rank_name": None,
        }
    )

    assert "não há requisito público de horas ou mérito" in text
    assert "nomeação interna" in text


def test_commander_general_is_owner_only_and_not_a_promotion() -> None:
    text = promotion_requirement_text(
        {
            "level": 18,
            "target_total_ms": None,
            "minimum_tenure_ms": None,
            "next_rank_name": None,
        }
    )

    assert "exclusivo do proprietário" in text
    assert "não é promoção nem upamento" in text
