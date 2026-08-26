from __future__ import annotations

from choque.config import Branding
from scripts.publish_system_updates import (
    CHANNEL_NAME,
    LATEST_UPDATE_FOOTER,
    LATEST_UPDATE_TITLE,
    MESSAGE_FOOTER,
    MESSAGE_TITLE,
    _normalized_overwrites,
    build_latest_update_embed,
    build_update_embed,
)
from scripts.remodel_discord_layout import CHANNEL_SPECS


def test_updates_channel_uses_the_approved_visual_identity() -> None:
    assert CHANNEL_NAME == "🆕・ᴀᴛᴜᴀʟɪᴢᴀᴄᴏᴇꜱ-ᴅᴏ-ʙᴏᴛ"
    assert any(spec.key == "info.updates" and spec.visual_name == CHANNEL_NAME for spec in CHANNEL_SPECS)


def test_update_summary_is_complete_and_keeps_decisions_human() -> None:
    embed = build_update_embed(Branding())

    assert embed["title"] == MESSAGE_TITLE
    assert embed["footer"]["text"] == MESSAGE_FOOTER
    assert len(embed["fields"]) == 16
    fields = {str(field["name"]): str(field["value"]) for field in embed["fields"]}
    text = " ".join(fields.values())
    assert "✅ Portaria e cadastro" in fields
    assert "vínculo único" in fields["✅ Portaria e cadastro"]
    assert "✅ Central Financeira" in fields
    assert "QR Code PIX" in fields["✅ Central Financeira"]
    assert "Pix Copia e Cola" in fields["✅ Central Financeira"]
    assert "Destaques Financeiros" in fields["✅ Central Financeira"]
    assert "honraria visual sem permissões" in fields["✅ Central Financeira"]
    assert "só aparecem com consentimento" in fields["✅ Central Financeira"]
    assert "chave PIX" not in fields["✅ Central Financeira"]
    assert "Sheikh" not in str(embed)
    assert "@everyone" not in str(embed)
    assert "obrigatoriamente humanas" in text
    assert "exclusivamente humana" in text
    assert "Comandante-Geral é exclusivo do proprietário" in text
    assert "Central de Upamentos" in text
    assert "redirecionamentos externos" in text
    assert "✅ ADV e disciplina" in fields
    assert "nenhuma punição é decidida automaticamente" in fields["✅ ADV e disciplina"]
    assert "✅ Cursos por canal" in fields
    assert "Após aprovação humana" in fields["✅ Cursos por canal"]
    assert "✅ Transferências auditáveis" in fields
    assert "duas decisões humanas" in fields["✅ Transferências auditáveis"]
    assert "✅ Registro de desligamentos" in fields
    assert "Motivos internos permanecem privados" in fields["✅ Registro de desligamentos"]
    assert "✅ Aguardando configuração da tag" in fields
    assert "atendimento humano" in fields["✅ Aguardando configuração da tag"]
    assert "🛡️ Informativo da Central de Tags" in fields
    assert "envio geral continua desligado" in fields["🛡️ Informativo da Central de Tags"]
    assert "nenhum lote coletivo foi iniciado" in fields["🛡️ Informativo da Central de Tags"]
    assert "26/08/2026" in str(embed["description"])
    assert sum(len(str(field["name"])) + len(str(field["value"])) for field in embed["fields"]) < 5_500


def test_permission_comparison_is_order_independent() -> None:
    first = [
        {"id": "2", "type": 0, "allow": "1", "deny": "0"},
        {"id": "1", "type": 0, "allow": "0", "deny": "2"},
    ]
    second = list(reversed(first))

    assert _normalized_overwrites(first) == _normalized_overwrites(second)


def test_latest_update_is_a_separate_safe_message() -> None:
    embed = build_latest_update_embed(Branding())

    assert embed["title"] == LATEST_UPDATE_TITLE
    assert embed["footer"]["text"] == LATEST_UPDATE_FOOTER
    assert len(embed["fields"]) == 6
    text = str(embed)
    assert "26/08/2026" in text
    assert "decisões humanas" in text
    assert "envio coletivo" in text
    assert "permanece desligado" in text
    assert "@everyone" not in text
