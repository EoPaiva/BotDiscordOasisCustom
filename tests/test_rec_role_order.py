from __future__ import annotations

import pytest

from scripts.sync_rec_role_order import (
    build_role_order_plan,
    snapshot_role_attributes,
    validate_role_attributes_unchanged,
)


def _role(
    role_id: int,
    name: str,
    position: int,
    *,
    managed: bool = False,
    permissions: str = "0",
) -> dict[str, object]:
    return {
        "id": str(role_id),
        "name": name,
        "position": position,
        "managed": managed,
        "permissions": permissions,
        "color": 0,
        "hoist": False,
        "mentionable": False,
        "icon": None,
        "unicode_emoji": None,
    }


def test_build_plan_copies_source_order_and_keeps_bot_above_managed_roles() -> None:
    source = [
        _role(1, "Candidato", 1),
        _role(2, "ᴍᴇᴍʙʀᴏ ᴄʜᴏǫᴜᴇ", 10),
        _role(3, "ʀᴇᴄʀᴜᴛᴀ", 20),
        _role(4, "ᴀᴜxɪʟɪᴀʀ ʀᴇᴄʀᴜᴛᴀᴍᴇɴᴛᴏ", 30),
        _role(5, "ʀᴇsᴘᴏɴsᴀᴠᴇʟ ʀᴇᴄʀᴜᴛᴀᴍᴇɴᴛᴏ", 40),
        _role(6, "ɪɴsᴛʀᴜᴛᴏʀ ᴅᴇ ᴄᴜʀsᴏs", 35),
        _role(7, "ᴄᴏᴍᴀɴᴅᴀɴᴛᴇ", 50),
    ]
    target = [
        _role(100, "@everyone", 0),
        _role(101, "Comando REC", 1),
        _role(102, "Candidato", 7),
        _role(103, "Membro Choque", 6),
        _role(104, "ʀᴇᴄʀᴜᴛᴀ", 5),
        _role(105, "Auxiliar Recrutamento", 4),
        _role(106, "Responsável Recrutamento", 3),
        _role(107, "Instrutor de Cursos", 2),
        _role(108, "ᴄᴏᴍᴀɴᴅᴀɴᴛᴇ", 8),
        _role(999, "SENTINELA | CHOQUE", 9, managed=True),
    ]

    plan = build_role_order_plan(source, target, {999})

    assert plan["bot_role_position"] == 9
    assert plan["order_top_to_bottom"] == [
        "Comando REC",
        "ᴄᴏᴍᴀɴᴅᴀɴᴛᴇ",
        "Responsável Recrutamento",
        "Instrutor de Cursos",
        "Auxiliar Recrutamento",
        "ʀᴇᴄʀᴜᴛᴀ",
        "Membro Choque",
        "Candidato",
    ]


def test_build_plan_rejects_unknown_target_role() -> None:
    source = [_role(1, "Candidato", 1)]
    target = [
        _role(100, "@everyone", 0),
        _role(101, "Comando REC", 1),
        _role(102, "Cargo sem origem", 2),
        _role(999, "Bot", 3, managed=True),
    ]

    with pytest.raises(RuntimeError, match="Cargo 'Cargo sem origem'"):
        build_role_order_plan(source, target, {999})


def test_build_plan_rejects_role_at_or_above_bot() -> None:
    source = [_role(1, "Candidato", 1)]
    target = [
        _role(100, "@everyone", 0),
        _role(101, "Comando REC", 1),
        _role(102, "Candidato", 3),
        _role(999, "Bot", 2, managed=True),
    ]

    with pytest.raises(RuntimeError, match="fora do alcance do bot"):
        build_role_order_plan(source, target, {999})


def test_attribute_validation_ignores_position_but_rejects_permission_change() -> None:
    role = _role(1, "Cargo", 1, permissions="8")
    before = snapshot_role_attributes([role])
    moved = {**role, "position": 5}

    validate_role_attributes_unchanged(before, [moved])

    changed = {**moved, "permissions": "0"}
    with pytest.raises(RuntimeError, match="Atributos de cargos mudaram"):
        validate_role_attributes_unchanged(before, [changed])
