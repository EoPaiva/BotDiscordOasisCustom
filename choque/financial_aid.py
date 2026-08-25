from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import unicodedata
import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from .audit import AuditService
from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .settings import SettingsService
from .time_utils import utc_now_ms


class FinancialAidService:
    """Canonical, append-only domain for voluntary financial support.

    The service intentionally owns *records and decisions*, never payment
    confirmation itself. A member can declare a PIX, but only an authorized
    administrator can confirm it after an external check. Monetary values are
    integer cents throughout; public projections never expose those values per
    person. Discord I/O belongs to the cog/outbox and runs after commit.
    """

    PROJECT_STATUSES = frozenset(
        {"EM_PLANEJAMENTO", "EM_ANDAMENTO", "CONCLUIDA", "CANCELADA", "SUSPENSA"}
    )
    CONTRIBUTION_STATUSES = frozenset(
        {"PENDENTE", "CONFIRMADA", "NAO_CONFIRMADA", "CANCELADA"}
    )
    HONORS: tuple[tuple[str, str, str], ...] = (
        (
            "APOIADOR",
            "💎 Apoiador da CHOQUE",
            "Reconhecimento simbólico pelo apoio voluntário ao desenvolvimento da corporação.",
        ),
        (
            "COLABORADOR",
            "🌟 Colaborador da CHOQUE",
            "Reconhecimento simbólico por participação recorrente em melhorias e projetos.",
        ),
        (
            "BENFEITOR",
            "🏅 Benfeitor da CHOQUE",
            "Reconhecimento simbólico por participação relevante e recorrente no desenvolvimento.",
        ),
        (
            "PATRONO",
            "👑 Patrono da CHOQUE",
            "Honraria excepcional, concedida apenas por decisão humana fundamentada da liderança.",
        ),
    )
    ACHIEVEMENTS: tuple[tuple[str, str, str], ...] = (
        ("PRIMEIRO_APOIO", "🎖️ Primeiro Apoio", "Primeira contribuição voluntária confirmada."),
        ("APOIADOR_DE_PROJETO", "🎯 Apoiador de Projeto", "Apoiou uma meta específica."),
        ("APOIADOR_DE_VIATURA", "🚓 Apoiador de Viatura", "Apoiou um projeto de viatura."),
        (
            "APOIADOR_DE_IDENTIDADE",
            "🎨 Apoiador de Identidade",
            "Apoiou skin, plotagem, uniforme ou identidade visual.",
        ),
        (
            "APOIADOR_DE_INFRAESTRUTURA",
            "⚙️ Apoiador de Infraestrutura",
            "Apoiou sistema, mod, infraestrutura ou desenvolvimento técnico.",
        ),
        (
            "PROJETO_CONCLUIDO",
            "🏆 Projeto Concluído",
            "Participou de uma meta que foi concluída.",
        ),
        (
            "FUNDADOR_DE_PROJETO",
            "🏛️ Fundador de Projeto",
            "Esteve entre os primeiros apoiadores de um projeto comunitário.",
        ),
        (
            "APOIO_RECORRENTE",
            "🔥 Apoio Recorrente",
            "Participou voluntariamente de melhorias distintas ao longo do tempo.",
        ),
        (
            "BENFEITOR_DA_COMUNIDADE",
            "⭐ Benfeitor da Comunidade",
            "Reconhecimento manual por contribuição significativa que não depende apenas de valor.",
        ),
    )

    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        audit: AuditService,
        *,
        clock: Callable[[], int] = utc_now_ms,
    ) -> None:
        self.database = database
        self.settings = settings
        self.audit = audit
        self.clock = clock
        self._defaults_ready: set[int] = set()

    @staticmethod
    def _row(row: Any) -> dict[str, object]:
        return dict(row)

    @staticmethod
    def parse_amount_to_cents(
        raw: str | int | Decimal, *, allow_zero: bool = False
    ) -> int:
        """Parse Brazilian/decimal input without floating-point rounding."""
        text = str(raw).strip().replace(" ", "")
        if not text:
            raise ValidationError("Informe um valor positivo.")
        if "," in text:
            normalized = text.replace(".", "").replace(",", ".")
        else:
            normalized = text
        try:
            value = Decimal(normalized)
        except InvalidOperation as exc:
            raise ValidationError("Informe um valor monetário válido.") from exc
        if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
            raise ValidationError("O valor precisa ser positivo.")
        cents = value * 100
        if cents != cents.to_integral_value():
            raise ValidationError("O valor pode ter no máximo duas casas decimais.")
        # SQLite INTEGER is signed 64-bit.  Rejecting an out-of-range value here
        # keeps the financial transaction atomic instead of failing halfway through
        # an otherwise valid confirmation or expense reversal.
        if cents > Decimal("9223372036854775807"):
            raise ValidationError("O valor informado excede o limite suportado.")
        return int(cents)

    @staticmethod
    def format_cents(cents: int) -> str:
        sign = "-" if cents < 0 else ""
        absolute = abs(int(cents))
        return f"{sign}R$ {absolute // 100:,}.{absolute % 100:02d}".replace(",", ".")

    @staticmethod
    def _pix_text(value: str, label: str, *, minimum: int, maximum: int) -> str:
        """Validate a value that will be encoded into a static BR Code payload."""
        text = str(value or "").strip()
        if not (minimum <= len(text) <= maximum):
            raise ValidationError(f"{label} deve ter entre {minimum} e {maximum} caracteres.")
        if any(ord(character) < 32 for character in text):
            raise ValidationError(f"{label} contém caracteres inválidos.")
        return text

    @classmethod
    def validate_pix_key(cls, value: str) -> str:
        """Accept the Pix key formats without ever logging or auditing the value."""
        key = cls._pix_text(value, "A chave PIX", minimum=5, maximum=77)
        if any(character.isspace() for character in key):
            raise ValidationError("A chave PIX não pode conter espaços.")
        return key

    @staticmethod
    def _br_code_text(value: str, label: str, *, maximum: int) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii").upper()
        ascii_value = re.sub(r"[^A-Z0-9 ]", "", ascii_value)
        ascii_value = re.sub(r"\s+", " ", ascii_value).strip()
        if not (2 <= len(ascii_value) <= maximum):
            raise ValidationError(f"{label} deve ter entre 2 e {maximum} caracteres válidos.")
        return ascii_value

    @staticmethod
    def mask_pix_key(value: str | None) -> str:
        key = str(value or "").strip()
        if not key:
            return "Não configurada"
        if len(key) <= 4:
            return "•" * len(key)
        visible = min(3, max(1, len(key) // 4))
        return f"{key[:visible]}{'•' * max(4, len(key) - visible * 2)}{key[-visible:]}"

    @staticmethod
    def _br_tlv(identifier: str, value: str) -> str:
        encoded_length = len(value.encode("utf-8"))
        if len(identifier) != 2 or encoded_length > 99:
            raise ValidationError("O payload PIX excede o formato BR Code.")
        return f"{identifier}{encoded_length:02d}{value}"

    @staticmethod
    def _crc16_ccitt(payload: str) -> str:
        crc = 0xFFFF
        # BR Code lengths and the checksum are defined over the encoded bytes,
        # not Python character positions. Merchant fields are normalized to
        # ASCII, but a valid PIX key may still contain a non-ASCII e-mail form.
        for byte in payload.encode("utf-8"):
            crc ^= byte << 8
            for _ in range(8):
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        return f"{crc:04X}"

    @classmethod
    def build_static_pix_payload(
        cls,
        *,
        pix_key: str,
        recipient_name: str,
        recipient_city: str,
        amount_cents: int | None = None,
        txid: str = "***",
    ) -> str:
        """Build a local static Pix BR Code payload with no automatic confirmation."""
        key = cls.validate_pix_key(pix_key)
        name = cls._br_code_text(recipient_name, "Nome do recebedor", maximum=25)
        city = cls._br_code_text(recipient_city, "Cidade do recebedor", maximum=15)
        reference = "***" if str(txid).strip() == "***" else cls._br_code_text(
            txid, "Identificador da transação", maximum=25
        )
        if amount_cents is not None:
            if not isinstance(amount_cents, int) or amount_cents <= 0:
                raise ValidationError("O valor PIX precisa ser positivo em centavos.")
            amount = f"{amount_cents // 100}.{amount_cents % 100:02d}"
        else:
            amount = None

        merchant_account = cls._br_tlv("00", "br.gov.bcb.pix") + cls._br_tlv("01", key)
        parts = [
            cls._br_tlv("00", "01"),
            cls._br_tlv("26", merchant_account),
            cls._br_tlv("52", "0000"),
            cls._br_tlv("53", "986"),
        ]
        if amount is not None:
            parts.append(cls._br_tlv("54", amount))
        parts.extend(
            [
                cls._br_tlv("58", "BR"),
                cls._br_tlv("59", name),
                cls._br_tlv("60", city),
                cls._br_tlv("62", cls._br_tlv("05", reference)),
            ]
        )
        prefix = "".join(parts) + "6304"
        return prefix + cls._crc16_ccitt(prefix)

    @staticmethod
    def _normalize_visibility(value: str) -> str:
        normalized = str(value).strip().upper().replace("Ú", "U").replace("Ô", "O")
        aliases = {"PUBLICO": "PUBLICO", "PUBLIC": "PUBLICO", "ANONIMO": "ANONIMO", "ANONYMOUS": "ANONIMO"}
        if normalized not in aliases:
            raise ValidationError("Escolha visibilidade pública ou anônima.")
        return aliases[normalized]

    @staticmethod
    def _require_text(value: str, label: str, *, maximum: int = 1500) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValidationError(f"{label} é obrigatório.")
        if len(text) > maximum:
            raise ValidationError(f"{label} excede o limite permitido.")
        return text

    async def ensure_defaults(self, guild_id: int) -> None:
        if guild_id in self._defaults_ready:
            return
        now = self.clock()
        async with self.database.transaction() as connection:
            for key, title, description in self.HONORS:
                await connection.execute(
                    """
                    INSERT OR IGNORE INTO financial_honor_definitions(
                        guild_id, honor_key, title, description, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (guild_id, key, title, description, now, now),
                )
            for key, title, description in self.ACHIEVEMENTS:
                await connection.execute(
                    """
                    INSERT OR IGNORE INTO financial_achievement_definitions(
                        achievement_key, title, description, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (key, title, description, now, now),
                )
        self._defaults_ready.add(guild_id)

    async def pix_key(self, guild_id: int) -> str:
        """Resolve the administrative setting first; env remains compatibility-only."""
        configured = await self.settings.get(guild_id, "financial_pix_key")
        if configured:
            return self.validate_pix_key(str(configured))
        override = (os.getenv("FINANCIAL_PIX_KEY") or os.getenv("PIX_KEY") or "").strip()
        if override:
            return self.validate_pix_key(override)
        raise ValidationError("A chave PIX ainda não foi configurada pela Administração.")

    async def pix_configuration_status(self, guild_id: int) -> dict[str, object]:
        recipient_name = await self.settings.get(guild_id, "financial_pix_recipient_name")
        recipient_city = await self.settings.get(guild_id, "financial_pix_recipient_city")
        row = await self.database.fetchone(
            "SELECT value_json, updated_at, updated_by FROM guild_settings WHERE guild_id=? AND setting_key='financial_pix_key'",
            (guild_id,),
        )
        if row is not None:
            key = self.validate_pix_key(str(json.loads(row["value_json"])))
            return {
                "configured": True,
                "source": "ADMINISTRATIVE_SETTING",
                "masked_key": self.mask_pix_key(key),
                "updated_at": int(row["updated_at"]),
                "updated_by": int(row["updated_by"]) if row["updated_by"] is not None else None,
                "recipient_name": recipient_name,
                "recipient_city": recipient_city,
            }
        override = (os.getenv("FINANCIAL_PIX_KEY") or os.getenv("PIX_KEY") or "").strip()
        if override:
            key = self.validate_pix_key(override)
            return {
                "configured": True,
                "source": "ENVIRONMENT",
                "masked_key": self.mask_pix_key(key),
                "updated_at": None,
                "updated_by": None,
                "recipient_name": recipient_name,
                "recipient_city": recipient_city,
            }
        return {
            "configured": False,
            "source": None,
            "masked_key": "Não configurada",
            "updated_at": None,
            "updated_by": None,
            "recipient_name": recipient_name,
            "recipient_city": recipient_city,
        }

    async def configure_pix_key(self, guild_id: int, *, actor_id: int, key: str) -> dict[str, object]:
        configured = self.validate_pix_key(key)
        fingerprint = hashlib.sha256(configured.encode("utf-8")).hexdigest()[:16]
        existing = await self.pix_configuration_status(guild_id)
        now = self.clock()
        async with self.database.transaction() as connection:
            await self.settings.set(guild_id, "financial_pix_key", configured, actor_id, connection)
            await self.settings.set(
                guild_id, "financial_pix_key_fingerprint", fingerprint, actor_id, connection
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_PIX_CONFIGURATION_UPDATED",
                actor_id=actor_id,
                before={"configured": bool(existing["configured"]), "source": existing["source"]},
                after={"configured": True, "source": "ADMINISTRATIVE_SETTING"},
                reason="Configuração PIX atualizada pela Administração; valor preservado fora da auditoria.",
                now=now,
            )
        return await self.pix_configuration_status(guild_id)

    async def configure_pix_configuration(
        self,
        guild_id: int,
        *,
        actor_id: int,
        key: str,
        recipient_name: str,
        recipient_city: str,
    ) -> dict[str, object]:
        """Persist the complete PIX configuration atomically and audit it safely.

        The payment key is intentionally never part of the audit payload.  The
        recipient name and city are public BR Code fields, so recording those
        two values makes the change traceable without disclosing the key.
        """
        configured = self.validate_pix_key(key)
        name = self._br_code_text(recipient_name, "Nome do recebedor", maximum=25)
        city = self._br_code_text(recipient_city, "Cidade do recebedor", maximum=15)
        fingerprint = hashlib.sha256(configured.encode("utf-8")).hexdigest()[:16]
        existing = await self.pix_configuration_status(guild_id)
        now = self.clock()
        async with self.database.transaction() as connection:
            await self.settings.set(guild_id, "financial_pix_key", configured, actor_id, connection)
            await self.settings.set(
                guild_id, "financial_pix_key_fingerprint", fingerprint, actor_id, connection
            )
            await self.settings.set(
                guild_id, "financial_pix_recipient_name", name, actor_id, connection
            )
            await self.settings.set(
                guild_id, "financial_pix_recipient_city", city, actor_id, connection
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_PIX_CONFIGURATION_UPDATED",
                actor_id=actor_id,
                before={
                    "configured": bool(existing["configured"]),
                    "source": existing["source"],
                    "recipient_name": existing["recipient_name"],
                    "recipient_city": existing["recipient_city"],
                },
                after={
                    "configured": True,
                    "source": "ADMINISTRATIVE_SETTING",
                    "recipient_name": name,
                    "recipient_city": city,
                },
                reason="Configuração PIX atualizada pela Administração; a chave não é auditada.",
                now=now,
            )
        return await self.pix_configuration_status(guild_id)

    async def configure_pix_recipient(
        self,
        guild_id: int,
        *,
        actor_id: int,
        recipient_name: str,
        recipient_city: str,
    ) -> dict[str, str]:
        name = self._br_code_text(recipient_name, "Nome do recebedor", maximum=25)
        city = self._br_code_text(recipient_city, "Cidade do recebedor", maximum=15)
        now = self.clock()
        async with self.database.transaction() as connection:
            await self.settings.set(
                guild_id, "financial_pix_recipient_name", name, actor_id, connection
            )
            await self.settings.set(
                guild_id, "financial_pix_recipient_city", city, actor_id, connection
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_PIX_RECIPIENT_UPDATED",
                actor_id=actor_id,
                before={"configured": True},
                after={"configured": True, "recipient_name": name, "recipient_city": city},
                reason="Dados públicos do recebedor PIX atualizados pela Administração.",
                now=now,
            )
        return {"recipient_name": name, "recipient_city": city}

    async def pix_payment_payload(self, guild_id: int, *, amount_cents: int | None = None) -> dict[str, str]:
        key = await self.pix_key(guild_id)
        name = await self.settings.get(guild_id, "financial_pix_recipient_name")
        city = await self.settings.get(guild_id, "financial_pix_recipient_city")
        if not name or not city:
            raise ValidationError("Configure o nome e a cidade do recebedor PIX antes de gerar o QR Code.")
        return {
            "pix_key": key,
            "payload": self.build_static_pix_payload(
                pix_key=key,
                recipient_name=str(name),
                recipient_city=str(city),
                amount_cents=amount_cents,
            ),
        }

    @staticmethod
    def pix_qr_png(payload: str) -> bytes:
        """Render the BR Code locally; the payload is never logged or persisted."""
        try:
            import qrcode
        except ImportError as exc:  # pragma: no cover - deployment dependency guard
            raise ValidationError("O gerador local de QR Code PIX não está disponível.") from exc
        image = qrcode.make(payload)
        from io import BytesIO

        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    async def refresh_pix_configuration(self, guild_id: int, *, actor_id: int) -> dict[str, object]:
        """Refresh only an internal fingerprint for legacy maintenance callers."""
        key = await self.pix_key(guild_id)
        fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        async with self.database.transaction() as connection:
            await self.settings.set(
                guild_id,
                "financial_pix_key_fingerprint",
                fingerprint,
                actor_id,
                connection,
            )
        return {"configured": True}

    async def configure_panel_channel(
        self,
        guild_id: int,
        *,
        actor_id: int,
        panel_kind: str,
        channel_id: int,
    ) -> str:
        """Persist an audited panel destination; Discord publishing happens after commit."""
        key_by_kind = {
            "PUBLIC": "financial_panel_channel_id",
            "ADMIN": "financial_admin_channel_id",
        }
        kind = str(panel_kind).strip().upper()
        setting_key = key_by_kind.get(kind)
        if setting_key is None:
            raise ValidationError("Tipo de painel financeiro inválido.")
        if int(channel_id) <= 0:
            raise ValidationError("Canal financeiro inválido.")
        now = self.clock()
        async with self.database.transaction() as connection:
            previous = await self.settings.get(guild_id, setting_key)
            await self.settings.set(guild_id, setting_key, int(channel_id), actor_id, connection)
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_PANEL_CHANNEL_CONFIGURED",
                actor_id=actor_id,
                before={"panel_kind": kind, "channel_configured": previous is not None},
                after={"panel_kind": kind, "channel_configured": True},
                reason="Destino de painel financeiro configurado.",
                now=now,
            )
        return setting_key

    async def configure_panel_channels(
        self,
        guild_id: int,
        *,
        actor_id: int,
        public_channel_id: int,
        admin_channel_id: int,
    ) -> dict[str, int]:
        """Persist the public/private panel pair atomically after Discord validation."""
        if public_channel_id <= 0 or admin_channel_id <= 0:
            raise ValidationError("Os dois canais financeiros precisam ser canais válidos.")
        now = self.clock()
        async with self.database.transaction() as connection:
            await self.settings.set(
                guild_id,
                "financial_panel_channel_id",
                public_channel_id,
                actor_id,
                connection,
            )
            await self.settings.set(
                guild_id,
                "financial_admin_channel_id",
                admin_channel_id,
                actor_id,
                connection,
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_PANEL_PAIR_CONFIGURED",
                actor_id=actor_id,
                before=None,
                after={
                    "public_channel_id": public_channel_id,
                    "admin_channel_id": admin_channel_id,
                },
                reason="Canais público e administrativo validados e configurados atomicamente.",
                now=now,
            )
        return {
            "public_channel_id": public_channel_id,
            "admin_channel_id": admin_channel_id,
        }

    async def configure_highlights_channel(
        self,
        guild_id: int,
        *,
        actor_id: int,
        channel_id: int,
    ) -> dict[str, int]:
        """Persist the single public highlights destination without Discord I/O."""
        if int(channel_id) <= 0:
            raise ValidationError("Canal de destaques financeiros inválido.")
        setting_key = "financial_highlights_channel_id"
        now = self.clock()
        async with self.database.transaction() as connection:
            previous = await self.settings.get(guild_id, setting_key)
            await self.settings.set(
                guild_id,
                setting_key,
                int(channel_id),
                actor_id,
                connection,
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_HIGHLIGHTS_CHANNEL_CONFIGURED",
                actor_id=actor_id,
                before={"configured": previous is not None},
                after={"configured": True},
                reason="Canal único de destaques financeiros configurado.",
                now=now,
            )
        return {"channel_id": int(channel_id)}

    async def _member(self, connection: Any, guild_id: int, discord_id: int) -> Any:
        cursor = await connection.execute(
            """
            SELECT * FROM members WHERE guild_id=? AND discord_id=?
            """,
            (guild_id, discord_id),
        )
        member = await cursor.fetchone()
        if not member or str(member["status"]) != "ACTIVE":
            raise ValidationError("Somente membros ativos podem registrar apoio voluntário.")
        return member

    async def _audit_event(
        self,
        connection: Any,
        *,
        guild_id: int,
        event_type: str,
        actor_id: int | None,
        target_member_id: int | None = None,
        contribution_id: int | None = None,
        project_id: int | None = None,
        ledger_entry_id: int | None = None,
        honor_id: int | None = None,
        before: object | None = None,
        after: object | None = None,
        reason: str | None = None,
        now: int | None = None,
    ) -> str:
        correlation_id = str(uuid.uuid4())
        timestamp = self.clock() if now is None else now
        await connection.execute(
            """
            INSERT INTO financial_audit_events(
                guild_id, event_type, actor_id, target_member_id, contribution_id,
                project_id, ledger_entry_id, honor_id, before_json, after_json,
                reason, correlation_id, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                event_type,
                actor_id,
                target_member_id,
                contribution_id,
                project_id,
                ledger_entry_id,
                honor_id,
                json.dumps(before, ensure_ascii=False) if before is not None else None,
                json.dumps(after, ensure_ascii=False) if after is not None else None,
                reason,
                correlation_id,
                timestamp,
            ),
        )
        # The generic audit channel records the decision, never an individual
        # monetary value or PIX identifier. The detailed value stays in the
        # financial ledger behind financial RBAC.
        await self.audit.record(
            guild_id,
            event_type,
            actor_id=actor_id,
            target_id=None,
            after={
                "contribution_id": contribution_id,
                "project_id": project_id,
                "ledger_entry_id": ledger_entry_id,
                "honor_id": honor_id,
            },
            reason=reason,
            connection=connection,
            correlation_id=correlation_id,
        )
        return correlation_id

    async def _enqueue_notification(
        self,
        connection: Any,
        *,
        guild_id: int,
        notification_type: str,
        subject_type: str,
        subject_id: int,
        event_key: str,
        target_discord_id: int | None,
        channel_setting_key: str | None,
        payload: dict[str, object],
        now: int,
    ) -> None:
        """Persist a delivery intent without private monetary values or PIX data."""
        await connection.execute(
            """
            INSERT OR IGNORE INTO financial_notifications(
                guild_id, notification_type, subject_type, subject_id,
                target_discord_id, channel_setting_key, payload_json, event_key,
                status, attempts, available_at, correlation_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, ?, ?)
            """,
            (
                guild_id,
                notification_type,
                subject_type,
                subject_id,
                target_discord_id,
                channel_setting_key,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                event_key,
                now,
                str(uuid.uuid4()),
                now,
                now,
            ),
        )

    async def _upsert_contribution_highlight(
        self,
        connection: Any,
        *,
        guild_id: int,
        contribution_id: int,
        now: int,
        refresh: bool,
    ) -> bool:
        """Create or rearm the one durable highlight intent for a contribution.

        The outbox payload deliberately contains no member identity, amount or
        PIX data. Delivery rebuilds the presentation from the canonical
        snapshot. On reversal, the existing Discord pointer is preserved and
        the revision is incremented so an older in-flight delivery cannot win.
        """
        event_key = f"financial-contribution-highlight:{contribution_id}"
        cursor = await connection.execute(
            "SELECT id FROM financial_notifications WHERE guild_id=? AND event_key=?",
            (guild_id, event_key),
        )
        existing = await cursor.fetchone()
        if existing is None:
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="CONTRIBUTION_HIGHLIGHT",
                subject_type="CONTRIBUTION",
                subject_id=contribution_id,
                event_key=event_key,
                target_discord_id=None,
                channel_setting_key="financial_highlights_channel_id",
                payload={"canonical_snapshot": True},
                now=now,
            )
            return True
        if not refresh:
            return False
        await connection.execute(
            """
            UPDATE financial_notifications
            SET notification_type='CONTRIBUTION_HIGHLIGHT',
                subject_type='CONTRIBUTION', subject_id=?, target_discord_id=NULL,
                channel_setting_key='financial_highlights_channel_id',
                payload_json='{"canonical_snapshot": true}', status='PENDING',
                attempts=0, available_at=?, delivered_at=NULL, last_error=NULL,
                revision=revision+1, updated_at=?
            WHERE id=?
            """,
            (contribution_id, now, now, int(existing["id"])),
        )
        return True

    async def recover_unsupported_nonce_notifications(self, guild_id: int) -> int:
        """Rearm only legacy failures caused by the removed enforce_nonce kwarg."""
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE financial_notifications
                SET status='PENDING', attempts=0, available_at=?, last_error=NULL,
                    revision=revision+1, updated_at=?
                WHERE guild_id=? AND status='FAILED'
                  AND LOWER(COALESCE(last_error, '')) LIKE '%enforce_nonce%'
                """,
                (now, now, guild_id),
            )
            return int(cursor.rowcount)

    async def create_project(
        self,
        guild_id: int,
        *,
        actor_id: int,
        name: str,
        description: str,
        category: str,
        target_amount: str | int | Decimal,
        deadline_at: int | None = None,
        responsible_id: int | None = None,
        notes: str | None = None,
        start: bool = True,
    ) -> dict[str, object]:
        await self.ensure_defaults(guild_id)
        name = self._require_text(name, "Nome do projeto", maximum=160)
        description = self._require_text(description, "Descrição", maximum=2000)
        category = self._require_text(category, "Categoria", maximum=80).upper()
        target_cents = self.parse_amount_to_cents(target_amount)
        now = self.clock()
        status = "EM_ANDAMENTO" if start else "EM_PLANEJAMENTO"
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO financial_projects(
                    guild_id, public_code, name, description, category, target_cents,
                    status, deadline_at, responsible_id, notes, created_by, created_at, updated_at
                ) VALUES (?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    name,
                    description,
                    category,
                    target_cents,
                    status,
                    deadline_at,
                    responsible_id,
                    str(notes or "").strip() or None,
                    actor_id,
                    now,
                    now,
                ),
            )
            project_id = int(cursor.lastrowid)
            code = f"META-{project_id:05d}"
            await connection.execute(
                "UPDATE financial_projects SET public_code=? WHERE id=?", (code, project_id)
            )
            cursor = await connection.execute("SELECT * FROM financial_projects WHERE id=?", (project_id,))
            project = await cursor.fetchone()
            assert project is not None
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_PROJECT_CREATED",
                actor_id=actor_id,
                project_id=project_id,
                after={"public_code": code, "status": status, "category": category},
                reason="Meta financeira criada.",
                now=now,
            )
            return self._project_snapshot_from_row(project)

    @staticmethod
    def _project_snapshot_from_row(row: Any) -> dict[str, object]:
        item = dict(row)
        item["remaining_cents"] = max(0, int(row["target_cents"]) - int(row["collected_cents"]))
        item["percent"] = min(
            100,
            int((int(row["collected_cents"]) * 100) / int(row["target_cents"])),
        )
        return item

    async def project_snapshot(self, guild_id: int, project_id: int) -> dict[str, object]:
        row = await self.database.fetchone(
            "SELECT * FROM financial_projects WHERE id=? AND guild_id=?", (project_id, guild_id)
        )
        if not row:
            raise NotFoundError("Meta financeira não encontrada.")
        snapshot = self._project_snapshot_from_row(row)
        supporters = await self.project_supporters(guild_id, project_id)
        snapshot["supporters"] = supporters
        snapshot["supporter_count"] = await self.project_sponsor_count(guild_id, project_id)
        return snapshot

    async def active_projects(self, guild_id: int, *, limit: int = 25) -> list[dict[str, object]]:
        rows = await self.database.fetchall(
            """
            SELECT * FROM financial_projects
            WHERE guild_id=? AND status='EM_ANDAMENTO'
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (guild_id, max(1, min(int(limit), 25))),
        )
        return [self._project_snapshot_from_row(row) for row in rows]

    async def project_page(
        self,
        guild_id: int,
        *,
        statuses: tuple[str, ...] | None = None,
        limit: int = 25,
    ) -> list[dict[str, object]]:
        chosen = tuple(statuses or tuple(sorted(self.PROJECT_STATUSES)))
        if not chosen or any(item not in self.PROJECT_STATUSES for item in chosen):
            raise ValidationError("Filtro de metas inválido.")
        placeholders = ",".join("?" for _ in chosen)
        rows = await self.database.fetchall(
            f"""
            SELECT * FROM financial_projects
            WHERE guild_id=? AND status IN ({placeholders})
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (guild_id, *chosen, max(1, min(int(limit), 100))),
        )
        return [self._project_snapshot_from_row(row) for row in rows]

    async def update_project(
        self,
        guild_id: int,
        project_id: int,
        *,
        actor_id: int,
        expected_version: int,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        deadline_at: int | None = None,
        notes: str | None = None,
        status: str | None = None,
        reason: str,
    ) -> dict[str, object]:
        reason = self._require_text(reason, "Motivo", maximum=1500)
        if status is not None and status not in self.PROJECT_STATUSES:
            raise ValidationError("Status de meta inválido.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM financial_projects WHERE id=? AND guild_id=?", (project_id, guild_id)
            )
            project = await cursor.fetchone()
            if not project:
                raise NotFoundError("Meta financeira não encontrada.")
            if int(project["version"]) != int(expected_version):
                raise ConflictError("A meta mudou. Atualize antes de editar.")
            next_status = status or str(project["status"])
            if str(project["status"]) in {"CONCLUIDA", "CANCELADA"} and next_status != str(project["status"]):
                raise ConflictError("Uma meta finalizada não pode ser reaberta por edição comum.")
            next_name = self._require_text(name, "Nome do projeto", maximum=160) if name is not None else str(project["name"])
            next_description = self._require_text(description, "Descrição", maximum=2000) if description is not None else str(project["description"])
            next_category = self._require_text(category, "Categoria", maximum=80).upper() if category is not None else str(project["category"])
            next_notes = str(notes).strip() or None if notes is not None else project["notes"]
            completed_at = now if next_status == "CONCLUIDA" and project["completed_at"] is None else project["completed_at"]
            await connection.execute(
                """
                UPDATE financial_projects
                SET name=?, description=?, category=?, deadline_at=?, notes=?, status=?,
                    completed_at=?, version=version+1, updated_at=?
                WHERE id=? AND version=?
                """,
                (
                    next_name,
                    next_description,
                    next_category,
                    deadline_at if deadline_at is not None else project["deadline_at"],
                    next_notes,
                    next_status,
                    completed_at,
                    now,
                    project_id,
                    expected_version,
                ),
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_PROJECT_UPDATED",
                actor_id=actor_id,
                project_id=project_id,
                before={"status": project["status"], "version": project["version"]},
                after={"status": next_status},
                reason=reason,
                now=now,
            )
            if str(project["status"]) != "CONCLUIDA" and next_status == "CONCLUIDA":
                await self._grant_project_completion_achievements(
                    connection,
                    guild_id=guild_id,
                    project_id=project_id,
                    actor_id=actor_id,
                    now=now,
                )
                await self._enqueue_notification(
                    connection,
                    guild_id=guild_id,
                    notification_type="PROJECT_COMPLETED",
                    subject_type="PROJECT",
                    subject_id=project_id,
                    event_key=f"financial-project-completed:{project_id}:v{int(project['version']) + 1}",
                    target_discord_id=None,
                    channel_setting_key="financial_panel_channel_id",
                    payload={
                        "public_code": str(project["public_code"]),
                        "name": next_name,
                        "category": next_category,
                    },
                    now=now,
                )
            cursor = await connection.execute("SELECT * FROM financial_projects WHERE id=?", (project_id,))
            updated = await cursor.fetchone()
            assert updated is not None
            return self._project_snapshot_from_row(updated)

    async def contribution_page(
        self,
        guild_id: int,
        *,
        statuses: tuple[str, ...] | None = None,
        limit: int = 25,
    ) -> list[dict[str, object]]:
        chosen = tuple(statuses or tuple(sorted(self.CONTRIBUTION_STATUSES)))
        if not chosen or any(item not in self.CONTRIBUTION_STATUSES for item in chosen):
            raise ValidationError("Filtro de contribuições inválido.")
        placeholders = ",".join("?" for _ in chosen)
        rows = await self.database.fetchall(
            f"""
            SELECT c.*, m.mta_nick, p.public_code, p.name AS project_name
            FROM financial_contributions c
            JOIN members m ON m.id=c.member_id
            LEFT JOIN financial_projects p ON p.id=c.project_id
            WHERE c.guild_id=? AND c.status IN ({placeholders})
            ORDER BY c.declared_at ASC, c.id ASC LIMIT ?
            """,
            (guild_id, *chosen, max(1, min(int(limit), 100))),
        )
        return [self._row(row) for row in rows]

    async def review_suggestion(
        self,
        guild_id: int,
        suggestion_id: int,
        *,
        actor_id: int,
        expected_version: int,
        status: str,
        reason: str,
    ) -> dict[str, object]:
        decision = str(status).strip().upper()
        if decision not in {"EM_ANALISE", "ACEITA", "RECUSADA", "ARQUIVADA"}:
            raise ValidationError("Decisão de sugestão inválida.")
        reason = self._require_text(reason, "Justificativa", maximum=1500)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM financial_suggestions WHERE id=? AND guild_id=?", (suggestion_id, guild_id)
            )
            suggestion = await cursor.fetchone()
            if not suggestion:
                raise NotFoundError("Sugestão não encontrada.")
            if int(suggestion["version"]) != int(expected_version):
                raise ConflictError("A sugestão mudou. Atualize antes de decidir.")
            if str(suggestion["status"]) in {"ACEITA", "RECUSADA", "ARQUIVADA"}:
                if str(suggestion["status"]) == decision:
                    return self._row(suggestion)
                raise ConflictError("Esta sugestão já recebeu uma decisão final.")
            await connection.execute(
                """
                UPDATE financial_suggestions
                SET status=?, reviewed_by=?, reviewed_at=?, review_reason=?, version=version+1, updated_at=?
                WHERE id=? AND version=?
                """,
                (decision, actor_id, now, reason, now, suggestion_id, expected_version),
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_SUGGESTION_REVIEWED",
                actor_id=actor_id,
                target_member_id=int(suggestion["member_id"]),
                after={"suggestion_id": suggestion_id, "status": decision},
                reason=reason,
                now=now,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="SUGGESTION_REVIEWED",
                subject_type="SUGGESTION",
                subject_id=suggestion_id,
                event_key=f"financial-suggestion-reviewed:{suggestion_id}:v{int(suggestion['version']) + 1}",
                target_discord_id=int(suggestion["discord_id"]),
                channel_setting_key=None,
                payload={"status": decision, "title": str(suggestion["title"])[:180]},
                now=now,
            )
            cursor = await connection.execute("SELECT * FROM financial_suggestions WHERE id=?", (suggestion_id,))
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)

    async def configure_honor_role(
        self,
        guild_id: int,
        *,
        actor_id: int,
        honor_key: str,
        role_id: int | None,
    ) -> dict[str, object]:
        await self.ensure_defaults(guild_id)
        key = self._require_text(honor_key, "Honraria", maximum=40).upper()
        now = self.clock()
        async with self.database.transaction() as connection:
            definition = await self._definition(connection, guild_id, key)
            before = {"discord_role_id": definition["discord_role_id"]}
            await connection.execute(
                """
                UPDATE financial_honor_definitions
                SET discord_role_id=?, updated_at=? WHERE id=?
                """,
                (role_id, now, int(definition["id"])),
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_HONOR_ROLE_CONFIGURED",
                actor_id=actor_id,
                after={"honor_key": key, "role_configured": role_id is not None, "symbolic_only": True},
                before=before,
                reason="Cargo de honraria configurado; precisa permanecer sem permissões operacionais.",
                now=now,
            )
            cursor = await connection.execute("SELECT * FROM financial_honor_definitions WHERE id=?", (int(definition["id"]),))
            row = await cursor.fetchone()
            assert row is not None
            result = self._row(row)
            result["previous_discord_role_id"] = before["discord_role_id"]
            return result

    async def declare_contribution(
        self,
        guild_id: int,
        discord_id: int,
        *,
        amount: str | int | Decimal,
        destination_kind: str,
        visibility: str,
        idempotency_key: str,
        project_id: int | None = None,
        observation: str | None = None,
        public_amount: bool = False,
    ) -> dict[str, object]:
        await self.ensure_defaults(guild_id)
        amount_cents = self.parse_amount_to_cents(amount)
        destination = str(destination_kind).strip().upper()
        if destination not in {"FUNDO_GERAL", "PROJETO"}:
            raise ValidationError("Escolha Fundo Geral ou uma meta ativa.")
        if destination == "PROJETO" and project_id is None:
            raise ValidationError("Escolha uma meta ativa para essa contribuição.")
        if destination == "FUNDO_GERAL" and project_id is not None:
            raise ValidationError("O Fundo Geral não pode apontar para uma meta específica.")
        visibility = self._normalize_visibility(visibility)
        if not isinstance(public_amount, bool):
            raise ValidationError("O consentimento para exibir o valor precisa ser explícito.")
        key = self._require_text(idempotency_key, "Identificador da solicitação", maximum=180)
        note = str(observation or "").strip() or None
        if note and len(note) > 1500:
            raise ValidationError("A observação excede o limite permitido.")
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM financial_contributions WHERE guild_id=? AND idempotency_key=?",
                (guild_id, key),
            )
            existing = await cursor.fetchone()
            if existing:
                return self._row(existing)
            member = await self._member(connection, guild_id, discord_id)
            if project_id is not None:
                cursor = await connection.execute(
                    "SELECT * FROM financial_projects WHERE id=? AND guild_id=?", (project_id, guild_id)
                )
                project = await cursor.fetchone()
                if not project:
                    raise NotFoundError("Meta financeira não encontrada.")
                if str(project["status"]) != "EM_ANDAMENTO":
                    raise ConflictError("Esta meta não aceita novas contribuições específicas.")
            cursor = await connection.execute(
                """
                INSERT INTO financial_contributions(
                    guild_id, member_id, discord_id, amount_cents, destination_kind, project_id,
                    visibility, observation, public_amount, declared_at, idempotency_key,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    int(member["id"]),
                    discord_id,
                    amount_cents,
                    destination,
                    project_id,
                    visibility,
                    note,
                    int(bool(public_amount)),
                    now,
                    key,
                    now,
                    now,
                ),
            )
            contribution_id = int(cursor.lastrowid)
            await self._contribution_event(
                connection,
                contribution_id=contribution_id,
                event_type="DECLARED",
                actor_id=discord_id,
                metadata={"destination_kind": destination, "visibility": visibility},
                now=now,
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_CONTRIBUTION_DECLARED",
                actor_id=discord_id,
                target_member_id=int(member["id"]),
                contribution_id=contribution_id,
                project_id=project_id,
                after={
                    "status": "PENDENTE",
                    "destination_kind": destination,
                    "visibility": visibility,
                    "public_amount": bool(public_amount),
                },
                reason="Contribuição voluntária declarada; aguarda confirmação administrativa.",
                now=now,
            )
            cursor = await connection.execute(
                "SELECT * FROM financial_contributions WHERE id=?", (contribution_id,)
            )
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)

    async def _contribution_event(
        self,
        connection: Any,
        *,
        contribution_id: int,
        event_type: str,
        actor_id: int | None,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
        now: int,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO financial_contribution_events(
                contribution_id, event_type, actor_id, reason, metadata_json, correlation_id, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contribution_id,
                event_type,
                actor_id,
                reason,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                str(uuid.uuid4()),
                now,
            ),
        )

    async def confirm_contribution(
        self,
        guild_id: int,
        contribution_id: int,
        *,
        actor_id: int,
        expected_version: int,
        reason: str,
    ) -> dict[str, object]:
        await self.ensure_defaults(guild_id)
        reason = self._require_text(reason, "Justificativa", maximum=1500)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM financial_contributions WHERE id=? AND guild_id=?",
                (contribution_id, guild_id),
            )
            contribution = await cursor.fetchone()
            if not contribution:
                raise NotFoundError("Registro de contribuição não encontrado.")
            if str(contribution["status"]) == "CONFIRMADA":
                await self._upsert_contribution_highlight(
                    connection,
                    guild_id=guild_id,
                    contribution_id=contribution_id,
                    now=now,
                    refresh=False,
                )
                await self._reconcile_automatic_honor(
                    connection,
                    guild_id=guild_id,
                    member_id=int(contribution["member_id"]),
                    discord_id=int(contribution["discord_id"]),
                    actor_id=actor_id,
                    now=now,
                )
                return self._row(contribution)
            if str(contribution["status"]) != "PENDENTE":
                raise ConflictError("Este registro já recebeu uma decisão administrativa.")
            if int(contribution["version"]) != int(expected_version):
                raise ConflictError("O registro mudou. Atualize a fila antes de confirmar.")
            project_id = contribution["project_id"]
            project: Any | None = None
            if project_id is not None:
                cursor = await connection.execute(
                    "SELECT * FROM financial_projects WHERE id=? AND guild_id=?",
                    (int(project_id), guild_id),
                )
                project = await cursor.fetchone()
                if not project:
                    raise NotFoundError("A meta vinculada não existe mais.")
                if str(project["status"]) != "EM_ANDAMENTO":
                    raise ConflictError("A meta não está disponível para confirmação de novas contribuições.")
            cursor = await connection.execute(
                """
                INSERT INTO financial_ledger_entries(
                    guild_id, entry_type, amount_cents, project_id, contribution_id,
                    description, actor_id, correlation_id, created_at
                ) VALUES (?, 'CONTRIBUICAO_CONFIRMADA', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    int(contribution["amount_cents"]),
                    int(project_id) if project_id is not None else None,
                    contribution_id,
                    "Contribuição voluntária confirmada administrativamente.",
                    actor_id,
                    str(uuid.uuid4()),
                    now,
                ),
            )
            ledger_entry_id = int(cursor.lastrowid)
            if project is not None:
                collected = int(project["collected_cents"]) + int(contribution["amount_cents"])
                completed = collected >= int(project["target_cents"])
                await connection.execute(
                    """
                    UPDATE financial_projects
                    SET collected_cents=?, status=?, completed_at=?, version=version+1, updated_at=?
                    WHERE id=? AND version=?
                    """,
                    (
                        collected,
                        "CONCLUIDA" if completed else "EM_ANDAMENTO",
                        now if completed else None,
                        now,
                        int(project["id"]),
                        int(project["version"]),
                    ),
                )
            await connection.execute(
                """
                UPDATE financial_contributions
                SET status='CONFIRMADA', confirmed_at=?, confirmed_by=?, final_reason=?,
                    version=version+1, updated_at=?
                WHERE id=? AND version=? AND status='PENDENTE'
                """,
                (now, actor_id, reason, now, contribution_id, expected_version),
            )
            await self._contribution_event(
                connection,
                contribution_id=contribution_id,
                event_type="CONFIRMED",
                actor_id=actor_id,
                reason=reason,
                now=now,
            )
            await self._grant_automatic_recognition(
                connection,
                guild_id=guild_id,
                contribution=contribution,
                project=project,
                actor_id=actor_id,
                now=now,
            )
            await self._upsert_contribution_highlight(
                connection,
                guild_id=guild_id,
                contribution_id=contribution_id,
                now=now,
                refresh=False,
            )
            if project is not None and int(project["collected_cents"]) + int(contribution["amount_cents"]) >= int(project["target_cents"]):
                await self._grant_project_completion_achievements(
                    connection,
                    guild_id=guild_id,
                    project_id=int(project["id"]),
                    actor_id=actor_id,
                    now=now,
                )
                await self._enqueue_notification(
                    connection,
                    guild_id=guild_id,
                    notification_type="PROJECT_COMPLETED",
                    subject_type="PROJECT",
                    subject_id=int(project["id"]),
                    event_key=f"financial-project-completed:{project['id']}:v{int(project['version']) + 1}",
                    target_discord_id=None,
                    channel_setting_key="financial_panel_channel_id",
                    payload={
                        "public_code": str(project["public_code"]),
                        "name": str(project["name"]),
                        "category": str(project["category"]),
                    },
                    now=now,
                )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_CONTRIBUTION_CONFIRMED",
                actor_id=actor_id,
                target_member_id=int(contribution["member_id"]),
                contribution_id=contribution_id,
                project_id=int(project_id) if project_id is not None else None,
                ledger_entry_id=ledger_entry_id,
                after={"status": "CONFIRMADA"},
                reason=reason,
                now=now,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="CONTRIBUTION_DECIDED",
                subject_type="CONTRIBUTION",
                subject_id=contribution_id,
                event_key=f"financial-contribution-decided:{contribution_id}:CONFIRMADA",
                target_discord_id=int(contribution["discord_id"]),
                channel_setting_key=None,
                payload={"status": "CONFIRMADA", "reason": reason},
                now=now,
            )
            cursor = await connection.execute(
                "SELECT * FROM financial_contributions WHERE id=?", (contribution_id,)
            )
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)

    async def decide_unconfirmed_contribution(
        self,
        guild_id: int,
        contribution_id: int,
        *,
        actor_id: int,
        expected_version: int,
        confirmed: bool,
        reason: str,
    ) -> dict[str, object]:
        if confirmed:
            return await self.confirm_contribution(
                guild_id,
                contribution_id,
                actor_id=actor_id,
                expected_version=expected_version,
                reason=reason,
            )
        reason = self._require_text(reason, "Justificativa", maximum=1500)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM financial_contributions WHERE id=? AND guild_id=?",
                (contribution_id, guild_id),
            )
            contribution = await cursor.fetchone()
            if not contribution:
                raise NotFoundError("Registro de contribuição não encontrado.")
            if str(contribution["status"]) == "NAO_CONFIRMADA":
                return self._row(contribution)
            if str(contribution["status"]) != "PENDENTE" or int(contribution["version"]) != int(expected_version):
                raise ConflictError("O registro foi alterado por outra decisão. Atualize a fila.")
            await connection.execute(
                """
                UPDATE financial_contributions
                SET status='NAO_CONFIRMADA', confirmed_at=?, confirmed_by=?, final_reason=?,
                    version=version+1, updated_at=?
                WHERE id=? AND version=? AND status='PENDENTE'
                """,
                (now, actor_id, reason, now, contribution_id, expected_version),
            )
            await self._contribution_event(
                connection,
                contribution_id=contribution_id,
                event_type="NOT_CONFIRMED",
                actor_id=actor_id,
                reason=reason,
                now=now,
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_CONTRIBUTION_NOT_CONFIRMED",
                actor_id=actor_id,
                target_member_id=int(contribution["member_id"]),
                contribution_id=contribution_id,
                project_id=int(contribution["project_id"]) if contribution["project_id"] is not None else None,
                after={"status": "NAO_CONFIRMADA"},
                reason=reason,
                now=now,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="CONTRIBUTION_DECIDED",
                subject_type="CONTRIBUTION",
                subject_id=contribution_id,
                event_key=f"financial-contribution-decided:{contribution_id}:NAO_CONFIRMADA",
                target_discord_id=int(contribution["discord_id"]),
                channel_setting_key=None,
                payload={"status": "NAO_CONFIRMADA", "reason": reason},
                now=now,
            )
            cursor = await connection.execute("SELECT * FROM financial_contributions WHERE id=?", (contribution_id,))
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)

    async def cancel_contribution(
        self,
        guild_id: int,
        contribution_id: int,
        *,
        actor_id: int,
        expected_version: int,
        reason: str,
    ) -> dict[str, object]:
        reason = self._require_text(reason, "Motivo do cancelamento", maximum=1500)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM financial_contributions WHERE id=? AND guild_id=?",
                (contribution_id, guild_id),
            )
            contribution = await cursor.fetchone()
            if not contribution:
                raise NotFoundError("Registro de contribuição não encontrado.")
            if str(contribution["status"]) == "CANCELADA":
                return self._row(contribution)
            if str(contribution["status"]) != "PENDENTE" or int(contribution["version"]) != int(expected_version):
                raise ConflictError("Só é possível cancelar uma declaração pendente e atual.")
            await connection.execute(
                """
                UPDATE financial_contributions
                SET status='CANCELADA', final_reason=?, version=version+1, updated_at=?
                WHERE id=? AND version=? AND status='PENDENTE'
                """,
                (reason, now, contribution_id, expected_version),
            )
            await self._contribution_event(
                connection,
                contribution_id=contribution_id,
                event_type="CANCELLED",
                actor_id=actor_id,
                reason=reason,
                now=now,
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_CONTRIBUTION_CANCELLED",
                actor_id=actor_id,
                target_member_id=int(contribution["member_id"]),
                contribution_id=contribution_id,
                project_id=int(contribution["project_id"]) if contribution["project_id"] is not None else None,
                after={"status": "CANCELADA"},
                reason=reason,
                now=now,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="CONTRIBUTION_DECIDED",
                subject_type="CONTRIBUTION",
                subject_id=contribution_id,
                event_key=f"financial-contribution-decided:{contribution_id}:CANCELADA",
                target_discord_id=int(contribution["discord_id"]),
                channel_setting_key=None,
                payload={"status": "CANCELADA", "reason": reason},
                now=now,
            )
            cursor = await connection.execute("SELECT * FROM financial_contributions WHERE id=?", (contribution_id,))
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)

    async def reverse_contribution(
        self,
        guild_id: int,
        contribution_id: int,
        *,
        actor_id: int,
        reason: str,
    ) -> dict[str, object]:
        reason = self._require_text(reason, "Motivo do estorno", maximum=1500)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM financial_contributions WHERE id=? AND guild_id=?",
                (contribution_id, guild_id),
            )
            contribution = await cursor.fetchone()
            if not contribution:
                raise NotFoundError("Registro de contribuição não encontrado.")
            if str(contribution["status"]) != "CONFIRMADA":
                raise ConflictError("Somente contribuição confirmada pode ser estornada.")
            cursor = await connection.execute(
                """
                SELECT * FROM financial_ledger_entries
                WHERE contribution_id=? AND entry_type='CONTRIBUICAO_CONFIRMADA'
                """,
                (contribution_id,),
            )
            original = await cursor.fetchone()
            if not original:
                raise RuntimeError("Lançamento financeiro da contribuição não foi encontrado.")
            cursor = await connection.execute(
                "SELECT * FROM financial_ledger_entries WHERE reverses_entry_id=?", (int(original["id"]),)
            )
            existing = await cursor.fetchone()
            if existing:
                return self._row(existing)
            cursor = await connection.execute(
                """
                INSERT INTO financial_ledger_entries(
                    guild_id, entry_type, amount_cents, project_id, contribution_id,
                    reverses_entry_id, description, actor_id, correlation_id, created_at
                ) VALUES (?, 'ESTORNO_CONTRIBUICAO', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    -int(contribution["amount_cents"]),
                    int(contribution["project_id"]) if contribution["project_id"] is not None else None,
                    contribution_id,
                    int(original["id"]),
                    "Estorno administrativo de contribuição confirmada.",
                    actor_id,
                    str(uuid.uuid4()),
                    now,
                ),
            )
            reversal_id = int(cursor.lastrowid)
            if contribution["project_id"] is not None:
                cursor = await connection.execute(
                    "SELECT * FROM financial_projects WHERE id=?", (int(contribution["project_id"]),)
                )
                project = await cursor.fetchone()
                if project:
                    collected = max(0, int(project["collected_cents"]) - int(contribution["amount_cents"]))
                    status = "EM_ANDAMENTO" if str(project["status"]) == "CONCLUIDA" else str(project["status"])
                    await connection.execute(
                        """
                        UPDATE financial_projects
                        SET collected_cents=?, status=?, completed_at=?, version=version+1, updated_at=?
                        WHERE id=?
                        """,
                        (collected, status, None if status == "EM_ANDAMENTO" else project["completed_at"], now, int(project["id"])),
                    )
            await connection.execute(
                """
                UPDATE financial_contributions
                SET reversed_at=?, reversed_by=?, reversal_reason=?, version=version+1, updated_at=?
                WHERE id=? AND reversed_at IS NULL
                """,
                (now, actor_id, reason, now, contribution_id),
            )
            await self._reconcile_automatic_honor(
                connection,
                guild_id=guild_id,
                member_id=int(contribution["member_id"]),
                discord_id=int(contribution["discord_id"]),
                actor_id=actor_id,
                now=now,
            )
            await self._upsert_contribution_highlight(
                connection,
                guild_id=guild_id,
                contribution_id=contribution_id,
                now=now,
                refresh=True,
            )
            await self._contribution_event(
                connection,
                contribution_id=contribution_id,
                event_type="REVERSED",
                actor_id=actor_id,
                reason=reason,
                now=now,
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_CONTRIBUTION_REVERSED",
                actor_id=actor_id,
                target_member_id=int(contribution["member_id"]),
                contribution_id=contribution_id,
                project_id=int(contribution["project_id"]) if contribution["project_id"] is not None else None,
                ledger_entry_id=reversal_id,
                after={"reversal": True},
                reason=reason,
                now=now,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="CONTRIBUTION_DECIDED",
                subject_type="CONTRIBUTION",
                subject_id=contribution_id,
                event_key=f"financial-contribution-decided:{contribution_id}:ESTORNADA",
                target_discord_id=int(contribution["discord_id"]),
                channel_setting_key=None,
                payload={"status": "ESTORNADA", "reason": reason},
                now=now,
            )
            cursor = await connection.execute("SELECT * FROM financial_ledger_entries WHERE id=?", (reversal_id,))
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)

    async def record_expense(
        self,
        guild_id: int,
        *,
        actor_id: int,
        amount: str | int | Decimal,
        category: str,
        description: str,
        project_id: int | None = None,
    ) -> dict[str, object]:
        amount_cents = self.parse_amount_to_cents(amount)
        category = self._require_text(category, "Categoria", maximum=80).upper()
        description = self._require_text(description, "Descrição", maximum=1500)
        now = self.clock()
        async with self.database.transaction() as connection:
            if project_id is not None:
                cursor = await connection.execute(
                    "SELECT id FROM financial_projects WHERE id=? AND guild_id=?", (project_id, guild_id)
                )
                if not await cursor.fetchone():
                    raise NotFoundError("Meta financeira não encontrada.")
            cursor = await connection.execute(
                """
                INSERT INTO financial_expenses(
                    guild_id, project_id, amount_cents, category, description,
                    recorded_by, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, project_id, amount_cents, category, description, actor_id, now),
            )
            expense_id = int(cursor.lastrowid)
            cursor = await connection.execute(
                """
                INSERT INTO financial_ledger_entries(
                    guild_id, entry_type, amount_cents, project_id, expense_id,
                    description, actor_id, correlation_id, created_at
                ) VALUES (?, 'DESPESA', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    -amount_cents,
                    project_id,
                    expense_id,
                    description,
                    actor_id,
                    str(uuid.uuid4()),
                    now,
                ),
            )
            ledger_entry_id = int(cursor.lastrowid)
            await connection.execute(
                "UPDATE financial_expenses SET ledger_entry_id=? WHERE id=?",
                (ledger_entry_id, expense_id),
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_EXPENSE_RECORDED",
                actor_id=actor_id,
                project_id=project_id,
                ledger_entry_id=ledger_entry_id,
                after={"category": category, "expense_id": expense_id},
                reason=description,
                now=now,
            )
            cursor = await connection.execute("SELECT * FROM financial_expenses WHERE id=?", (expense_id,))
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)

    async def ledger_entries(self, guild_id: int, *, project_id: int | None = None) -> list[dict[str, object]]:
        if project_id is None:
            rows = await self.database.fetchall(
                """
                SELECT ledger.*, project.name AS project_name, project.public_code AS project_code
                FROM financial_ledger_entries AS ledger
                LEFT JOIN financial_projects AS project ON project.id=ledger.project_id
                WHERE ledger.guild_id=? ORDER BY ledger.created_at, ledger.id
                """,
                (guild_id,),
            )
        else:
            rows = await self.database.fetchall(
                """
                SELECT ledger.*, project.name AS project_name, project.public_code AS project_code
                FROM financial_ledger_entries AS ledger
                LEFT JOIN financial_projects AS project ON project.id=ledger.project_id
                WHERE ledger.guild_id=? AND ledger.project_id=? ORDER BY ledger.created_at, ledger.id
                """,
                (guild_id, project_id),
            )
        return [self._row(row) for row in rows]

    async def reverse_expense(
        self,
        guild_id: int,
        expense_id: int,
        *,
        actor_id: int,
        reason: str,
    ) -> dict[str, object]:
        """Append an expense reversal; never alter or delete the original book entry."""
        reason = self._require_text(reason, "Motivo do estorno", maximum=1500)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM financial_expenses WHERE id=? AND guild_id=?", (expense_id, guild_id)
            )
            expense = await cursor.fetchone()
            if not expense:
                raise NotFoundError("Despesa financeira não encontrada.")
            if expense["ledger_entry_id"] is None:
                raise RuntimeError("Despesa sem lançamento no livro-caixa.")
            cursor = await connection.execute(
                "SELECT * FROM financial_ledger_entries WHERE id=?", (int(expense["ledger_entry_id"]),)
            )
            original = await cursor.fetchone()
            if not original:
                raise RuntimeError("Lançamento original da despesa não encontrado.")
            cursor = await connection.execute(
                "SELECT * FROM financial_ledger_entries WHERE reverses_entry_id=?", (int(original["id"]),)
            )
            existing = await cursor.fetchone()
            if existing:
                return self._row(existing)
            cursor = await connection.execute(
                """
                INSERT INTO financial_ledger_entries(
                    guild_id, entry_type, amount_cents, project_id, expense_id,
                    reverses_entry_id, description, actor_id, correlation_id, created_at
                ) VALUES (?, 'ESTORNO_DESPESA', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    int(expense["amount_cents"]),
                    int(expense["project_id"]) if expense["project_id"] is not None else None,
                    expense_id,
                    int(original["id"]),
                    "Estorno administrativo de despesa registrada.",
                    actor_id,
                    str(uuid.uuid4()),
                    now,
                ),
            )
            reversal_id = int(cursor.lastrowid)
            await connection.execute(
                """
                UPDATE financial_expenses
                SET reversed_at=?, reversed_by=?, reversal_reason=?, version=version+1
                WHERE id=? AND reversed_at IS NULL
                """,
                (now, actor_id, reason, expense_id),
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_EXPENSE_REVERSED",
                actor_id=actor_id,
                project_id=int(expense["project_id"]) if expense["project_id"] is not None else None,
                ledger_entry_id=reversal_id,
                before={"expense_id": expense_id},
                after={"reversal": True},
                reason=reason,
                now=now,
            )
            cursor = await connection.execute("SELECT * FROM financial_ledger_entries WHERE id=?", (reversal_id,))
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)

    async def transparency_snapshot(self, guild_id: int) -> dict[str, object]:
        general = await self.database.fetchone(
            """
            SELECT
                COALESCE(SUM(CASE
                    WHEN entry_type IN ('CONTRIBUICAO_CONFIRMADA','ESTORNO_CONTRIBUICAO')
                    THEN amount_cents ELSE 0 END), 0) AS collected_cents,
                COALESCE(SUM(CASE
                    WHEN entry_type IN ('DESPESA','ESTORNO_DESPESA')
                    THEN -amount_cents ELSE 0 END), 0) AS used_cents,
                COALESCE(SUM(amount_cents), 0) AS balance_cents,
                COUNT(*) AS movement_count
            FROM financial_ledger_entries
            WHERE guild_id=? AND project_id IS NULL
            """,
            (guild_id,),
        )
        completed = await self.database.fetchall(
            """
            SELECT public_code, name, category, completed_at
            FROM financial_projects
            WHERE guild_id=? AND status='CONCLUIDA'
            ORDER BY completed_at DESC, id DESC
            """,
            (guild_id,),
        )
        return {
            "general_fund": self._row(general) if general else {
                "collected_cents": 0,
                "used_cents": 0,
                "balance_cents": 0,
                "movement_count": 0,
            },
            "completed_projects": [
                {"public_code": row["public_code"], "name": row["name"], "category": row["category"], "completed_at": row["completed_at"]}
                for row in completed
            ],
        }

    async def public_supporters(self, guild_id: int, *, limit: int = 50) -> list[dict[str, object]]:
        rows = await self.database.fetchall(
            """
            SELECT c.discord_id, MIN(c.confirmed_at) AS first_confirmed_at
            FROM financial_contributions c
            WHERE c.guild_id=? AND c.status='CONFIRMADA' AND c.visibility='PUBLICO'
              AND c.reversed_at IS NULL
            GROUP BY c.member_id, c.discord_id
            ORDER BY first_confirmed_at ASC, c.discord_id ASC
            LIMIT ?
            """,
            (guild_id, max(1, min(int(limit), 100))),
        )
        return [
            {"discord_id": int(row["discord_id"]), "label": "Apoiador da CHOQUE"}
            for row in rows
        ]

    async def contribution_highlight_snapshot(
        self,
        guild_id: int,
        contribution_id: int,
    ) -> dict[str, object]:
        """Build a privacy-safe public projection from canonical records."""
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT c.*, m.mta_nick, m.discord_nick,
                       p.name AS project_name, p.public_code AS project_public_code,
                       p.target_cents AS project_target_cents,
                       p.collected_cents AS project_collected_cents
                FROM financial_contributions AS c
                JOIN members AS m ON m.id=c.member_id
                LEFT JOIN financial_projects AS p ON p.id=c.project_id
                WHERE c.guild_id=? AND c.id=?
                """,
                (guild_id, contribution_id),
            )
            contribution = await cursor.fetchone()
            if contribution is None:
                raise NotFoundError("Contribuição financeira não encontrada.")
            cursor = await connection.execute(
                """
                SELECT d.title
                FROM financial_member_honors AS h
                JOIN financial_honor_definitions AS d ON d.id=h.honor_definition_id
                WHERE h.guild_id=? AND h.member_id=? AND h.removed_at IS NULL
                  AND (h.expires_at IS NULL OR h.expires_at>?)
                ORDER BY h.granted_at, h.id
                """,
                (guild_id, int(contribution["member_id"]), self.clock()),
            )
            honor_titles = [str(row["title"]) for row in await cursor.fetchall()]
            cursor = await connection.execute(
                """
                SELECT d.title
                FROM financial_member_achievements AS a
                JOIN financial_achievement_definitions AS d
                  ON d.id=a.achievement_definition_id
                WHERE a.guild_id=? AND a.member_id=?
                ORDER BY a.awarded_at, a.id
                """,
                (guild_id, int(contribution["member_id"])),
            )
            achievement_titles = [str(row["title"]) for row in await cursor.fetchall()]

        visibility = str(contribution["visibility"])
        amount_is_public = bool(contribution["public_amount"])
        identity_is_public = visibility == "PUBLICO"
        project_id = contribution["project_id"]
        reversed_at = contribution["reversed_at"]
        return {
            "id": int(contribution["id"]),
            "status": "ESTORNADA" if reversed_at is not None else str(contribution["status"]),
            "visibility": visibility,
            "public_amount": amount_is_public,
            "discord_id": int(contribution["discord_id"]) if identity_is_public else None,
            "member_name": (
                str(contribution["mta_nick"] or contribution["discord_nick"] or "Membro CHOQUE")
                if identity_is_public
                else "Apoiador anônimo"
            ),
            "amount_cents": int(contribution["amount_cents"]) if amount_is_public else None,
            "confirmed_at": (
                int(contribution["confirmed_at"])
                if contribution["confirmed_at"] is not None
                else None
            ),
            "reversed_at": int(reversed_at) if reversed_at is not None else None,
            "reversal_reason": contribution["reversal_reason"],
            "project_id": int(project_id) if project_id is not None else None,
            "project_name": contribution["project_name"],
            "project_public_code": contribution["project_public_code"],
            "project_target_cents": (
                int(contribution["project_target_cents"])
                if contribution["project_target_cents"] is not None
                else None
            ),
            "project_collected_cents": (
                int(contribution["project_collected_cents"])
                if contribution["project_collected_cents"] is not None
                else None
            ),
            "honor_titles": honor_titles,
            "achievement_titles": achievement_titles,
        }

    async def reconcile_confirmed_contributions(
        self,
        guild_id: int,
        actor_id: int | None = None,
    ) -> dict[str, int]:
        """Backfill highlights and automatic tiers without changing the ledger."""
        await self.ensure_defaults(guild_id)
        now = self.clock()
        async with self.database.transaction() as connection:
            recovered = await connection.execute(
                """
                UPDATE financial_notifications
                SET status='PENDING', attempts=0, available_at=?, last_error=NULL,
                    revision=revision+1, updated_at=?
                WHERE guild_id=? AND status='FAILED'
                  AND LOWER(COALESCE(last_error, '')) LIKE '%enforce_nonce%'
                """,
                (now, now, guild_id),
            )
            cursor = await connection.execute(
                """
                SELECT id, member_id, discord_id
                FROM financial_contributions
                WHERE guild_id=? AND status='CONFIRMADA'
                ORDER BY id
                """,
                (guild_id,),
            )
            contributions = await cursor.fetchall()
            highlights_created = 0
            member_pairs: dict[int, int] = {}
            for contribution in contributions:
                member_pairs[int(contribution["member_id"])] = int(
                    contribution["discord_id"]
                )
                if await self._upsert_contribution_highlight(
                    connection,
                    guild_id=guild_id,
                    contribution_id=int(contribution["id"]),
                    now=now,
                    refresh=False,
                ):
                    highlights_created += 1
            cursor = await connection.execute(
                """
                SELECT DISTINCT h.member_id, h.discord_id
                FROM financial_member_honors AS h
                WHERE h.guild_id=? AND h.source='AUTOMATICA' AND h.removed_at IS NULL
                """,
                (guild_id,),
            )
            for honor in await cursor.fetchall():
                member_pairs.setdefault(int(honor["member_id"]), int(honor["discord_id"]))
            honor_changes = 0
            for member_id, discord_id in sorted(member_pairs.items()):
                result = await self._reconcile_automatic_honor(
                    connection,
                    guild_id=guild_id,
                    member_id=member_id,
                    discord_id=discord_id,
                    actor_id=actor_id,
                    now=now,
                )
                honor_changes += int(result["changed"])
        return {
            "confirmed_contributions": len(contributions),
            "highlights_created": highlights_created,
            "honor_changes": honor_changes,
            "recovered_notifications": int(recovered.rowcount),
        }

    async def sponsor_project(
        self,
        guild_id: int,
        discord_id: int,
        *,
        project_id: int,
        visibility: str,
    ) -> dict[str, object]:
        visibility = self._normalize_visibility(visibility)
        now = self.clock()
        async with self.database.transaction() as connection:
            member = await self._member(connection, guild_id, discord_id)
            cursor = await connection.execute(
                "SELECT * FROM financial_projects WHERE id=? AND guild_id=?", (project_id, guild_id)
            )
            project = await cursor.fetchone()
            if not project or str(project["status"]) != "EM_ANDAMENTO":
                raise ConflictError("Essa meta não está disponível para apadrinhamento.")
            await connection.execute(
                """
                INSERT INTO financial_project_sponsors(
                    project_id, member_id, discord_id, visibility, declared_at, withdrawn_at
                ) VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(project_id, member_id) DO UPDATE SET
                    visibility=excluded.visibility, declared_at=excluded.declared_at, withdrawn_at=NULL
                """,
                (project_id, int(member["id"]), discord_id, visibility, now),
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_PROJECT_SPONSORED",
                actor_id=discord_id,
                target_member_id=int(member["id"]),
                project_id=project_id,
                after={"visibility": visibility},
                reason="Interesse voluntário em acompanhar a meta; não gera obrigação financeira.",
                now=now,
            )
            return {"project_id": project_id, "member_id": int(member["id"]), "visibility": visibility}

    async def project_supporters(
        self, guild_id: int, project_id: int, *, limit: int = 20
    ) -> list[dict[str, object]]:
        """Return the sponsor mural for one project without amounts or hidden identities."""
        rows = await self.database.fetchall(
            """
            SELECT sponsor.visibility, sponsor.discord_id,
                   member.mta_nick, member.discord_nick, sponsor.declared_at
            FROM financial_project_sponsors AS sponsor
            JOIN members AS member ON member.id=sponsor.member_id
            JOIN financial_projects AS project ON project.id=sponsor.project_id
            WHERE sponsor.project_id=? AND project.guild_id=? AND sponsor.withdrawn_at IS NULL
            ORDER BY sponsor.declared_at ASC, sponsor.discord_id ASC
            LIMIT ?
            """,
            (project_id, guild_id, max(1, min(int(limit), 50))),
        )
        result: list[dict[str, object]] = []
        for row in rows:
            public = str(row["visibility"]) == "PUBLICO"
            label = (
                str(row["mta_nick"] or row["discord_nick"] or "Apoiador da CHOQUE")
                if public
                else "Anônimo"
            )
            result.append(
                {
                    "visibility": "PUBLICO" if public else "ANONIMO",
                    "label": label,
                    "declared_at": int(row["declared_at"]),
                }
            )
        return result

    async def project_sponsor_count(self, guild_id: int, project_id: int) -> int:
        row = await self.database.fetchone(
            """
            SELECT COUNT(*) AS total
            FROM financial_project_sponsors AS sponsor
            JOIN financial_projects AS project ON project.id=sponsor.project_id
            WHERE sponsor.project_id=? AND project.guild_id=? AND sponsor.withdrawn_at IS NULL
            """,
            (project_id, guild_id),
        )
        return int(row["total"]) if row else 0

    async def create_suggestion(
        self,
        guild_id: int,
        discord_id: int,
        *,
        title: str,
        category: str,
        description: str,
        motivation: str,
        estimated_amount: str | int | Decimal | None = None,
        reference_url: str | None = None,
    ) -> dict[str, object]:
        title = self._require_text(title, "Título", maximum=180)
        category = self._require_text(category, "Categoria", maximum=80).upper()
        description = self._require_text(description, "Descrição", maximum=1800)
        motivation = self._require_text(motivation, "Motivo", maximum=1200)
        estimated_cents = (
            self.parse_amount_to_cents(estimated_amount, allow_zero=True)
            if estimated_amount
            else None
        )
        url = str(reference_url or "").strip() or None
        if url:
            parsed = urlsplit(url)
            if len(url) > 400 or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValidationError("A referência precisa ser um link http:// ou https:// válido.")
        now = self.clock()
        async with self.database.transaction() as connection:
            member = await self._member(connection, guild_id, discord_id)
            cursor = await connection.execute(
                """
                INSERT INTO financial_suggestions(
                    guild_id, member_id, discord_id, title, category, description,
                    estimated_cents, motivation, reference_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    int(member["id"]),
                    discord_id,
                    title,
                    category,
                    description,
                    estimated_cents,
                    motivation,
                    url,
                    now,
                    now,
                ),
            )
            suggestion_id = int(cursor.lastrowid)
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_SUGGESTION_CREATED",
                actor_id=discord_id,
                target_member_id=int(member["id"]),
                after={"suggestion_id": suggestion_id, "category": category},
                reason="Sugestão de melhoria enviada para análise administrativa.",
                now=now,
            )
            cursor = await connection.execute("SELECT * FROM financial_suggestions WHERE id=?", (suggestion_id,))
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)

    async def _definition(self, connection: Any, guild_id: int, honor_key: str) -> Any:
        cursor = await connection.execute(
            """
            SELECT * FROM financial_honor_definitions
            WHERE guild_id=? AND honor_key=? AND active=1
            """,
            (guild_id, honor_key),
        )
        definition = await cursor.fetchone()
        if not definition:
            raise NotFoundError("Honraria não encontrada ou desativada.")
        return definition

    async def _achievement(self, connection: Any, key: str) -> Any:
        cursor = await connection.execute(
            """
            SELECT * FROM financial_achievement_definitions
            WHERE achievement_key=? AND active=1
            """,
            (key,),
        )
        definition = await cursor.fetchone()
        if not definition:
            raise RuntimeError(f"Conquista financeira ausente: {key}")
        return definition

    async def _grant_achievement(
        self,
        connection: Any,
        *,
        guild_id: int,
        member_id: int,
        discord_id: int,
        key: str,
        source: str,
        reason: str,
        actor_id: int | None,
        now: int,
    ) -> int | None:
        definition = await self._achievement(connection, key)
        correlation_id = str(uuid.uuid4())
        cursor = await connection.execute(
            """
            INSERT OR IGNORE INTO financial_member_achievements(
                guild_id, member_id, discord_id, achievement_definition_id, source,
                reason, awarded_by, awarded_at, correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                member_id,
                discord_id,
                int(definition["id"]),
                source,
                reason,
                actor_id,
                now,
                correlation_id,
            ),
        )
        if cursor.rowcount == 0:
            return None
        achievement_id = int(cursor.lastrowid)
        await self._audit_event(
            connection,
            guild_id=guild_id,
            event_type="FINANCIAL_ACHIEVEMENT_GRANTED",
            actor_id=actor_id,
            target_member_id=member_id,
            after={"achievement_key": key, "source": source},
            reason=reason,
            now=now,
        )
        return achievement_id

    async def _grant_honor(
        self,
        connection: Any,
        *,
        guild_id: int,
        member_id: int,
        discord_id: int,
        honor_key: str,
        source: str,
        justification: str,
        actor_id: int | None,
        expires_at: int | None,
        now: int,
    ) -> dict[str, object]:
        definition = await self._definition(connection, guild_id, honor_key)
        cursor = await connection.execute(
            """
            SELECT * FROM financial_member_honors
            WHERE guild_id=? AND member_id=? AND honor_definition_id=? AND removed_at IS NULL
            """,
            (guild_id, member_id, int(definition["id"])),
        )
        existing = await cursor.fetchone()
        if existing:
            if existing["expires_at"] is not None and int(existing["expires_at"]) <= now:
                await self._expire_honor(
                    connection,
                    honor=existing,
                    now=now,
                    reason="Prazo de honraria simbólica encerrado automaticamente.",
                )
            else:
                return self._row(existing)
        correlation_id = str(uuid.uuid4())
        cursor = await connection.execute(
            """
            INSERT INTO financial_member_honors(
                guild_id, member_id, discord_id, honor_definition_id, source,
                justification, granted_by, granted_at, expires_at, correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                member_id,
                discord_id,
                int(definition["id"]),
                source,
                justification,
                actor_id,
                now,
                expires_at,
                correlation_id,
            ),
        )
        honor_id = int(cursor.lastrowid)
        await self._audit_event(
            connection,
            guild_id=guild_id,
            event_type="FINANCIAL_HONOR_GRANTED",
            actor_id=actor_id,
            target_member_id=member_id,
            honor_id=honor_id,
            after={"honor_key": honor_key, "source": source, "symbolic_only": True},
            reason=justification,
            now=now,
        )
        await self._enqueue_notification(
            connection,
            guild_id=guild_id,
            notification_type="HONOR_GRANTED",
            subject_type="HONOR",
            subject_id=honor_id,
            event_key=f"financial-honor-granted:{honor_id}",
            target_discord_id=discord_id,
            channel_setting_key=None,
            payload={"honor_key": honor_key, "source": source},
            now=now,
        )
        cursor = await connection.execute("SELECT * FROM financial_member_honors WHERE id=?", (honor_id,))
        row = await cursor.fetchone()
        assert row is not None
        return self._row(row)

    async def _automatic_recognition_state(
        self,
        connection: Any,
        *,
        guild_id: int,
        member_id: int,
    ) -> dict[str, object]:
        cursor = await connection.execute(
            """
            SELECT COUNT(*) AS total,
                   COUNT(DISTINCT CASE
                       WHEN project_id IS NULL THEN 'FUNDO_GERAL'
                       ELSE 'PROJETO:' || CAST(project_id AS TEXT)
                   END) AS destinations
            FROM financial_contributions
            WHERE guild_id=? AND member_id=? AND status='CONFIRMADA'
              AND reversed_at IS NULL
            """,
            (guild_id, member_id),
        )
        row = await cursor.fetchone()
        total = int(row["total"])
        destinations = int(row["destinations"])
        if total >= 3 and destinations >= 2:
            tier: str | None = "BENFEITOR"
        elif total >= 2 or destinations >= 2:
            tier = "COLABORADOR"
        elif total == 1:
            tier = "APOIADOR"
        else:
            tier = None
        return {"total": total, "destinations": destinations, "tier": tier}

    async def _reconcile_automatic_honor(
        self,
        connection: Any,
        *,
        guild_id: int,
        member_id: int,
        discord_id: int,
        actor_id: int | None,
        now: int,
    ) -> dict[str, object]:
        """Keep exactly the applicable automatic tier; preserve every manual honor."""
        state = await self._automatic_recognition_state(
            connection,
            guild_id=guild_id,
            member_id=member_id,
        )
        target = state["tier"]
        cursor = await connection.execute(
            """
            SELECT h.*, d.honor_key
            FROM financial_member_honors AS h
            JOIN financial_honor_definitions AS d ON d.id=h.honor_definition_id
            WHERE h.guild_id=? AND h.member_id=? AND h.source='AUTOMATICA'
              AND h.removed_at IS NULL
            ORDER BY h.id
            """,
            (guild_id, member_id),
        )
        active = await cursor.fetchall()
        changed = 0
        for honor in active:
            if str(honor["honor_key"]) == target:
                continue
            reason = (
                "Honraria automática ajustada ao histórico ativo de contribuições; "
                "nenhuma vantagem operacional é concedida."
            )
            update = await connection.execute(
                """
                UPDATE financial_member_honors
                SET removed_by=?, removed_at=?, removal_reason=?, version=version+1
                WHERE id=? AND source='AUTOMATICA' AND removed_at IS NULL
                """,
                (actor_id, now, reason, int(honor["id"])),
            )
            if update.rowcount != 1:
                continue
            changed += 1
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_HONOR_RECONCILED",
                actor_id=actor_id,
                target_member_id=member_id,
                honor_id=int(honor["id"]),
                before={"honor_key": str(honor["honor_key"]), "source": "AUTOMATICA"},
                after={"active": False, "next_tier": target},
                reason=reason,
                now=now,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="HONOR_REMOVED",
                subject_type="HONOR",
                subject_id=int(honor["id"]),
                event_key=(
                    f"financial-honor-auto-reconciled:{int(honor['id'])}:"
                    f"v{int(honor['version']) + 1}"
                ),
                target_discord_id=discord_id,
                channel_setting_key=None,
                payload={"reason": "RECONCILIACAO_AUTOMATICA"},
                now=now,
            )
        if target is not None and not any(
            str(honor["honor_key"]) == target for honor in active
        ):
            before = connection.total_changes
            await self._grant_honor(
                connection,
                guild_id=guild_id,
                member_id=member_id,
                discord_id=discord_id,
                honor_key=str(target),
                source="AUTOMATICA",
                justification=(
                    "Reconhecimento simbólico calculado por recorrência e diversidade de apoio; "
                    "nunca por valor financeiro."
                ),
                actor_id=actor_id,
                expires_at=None,
                now=now,
            )
            if connection.total_changes > before:
                changed += 1
        return {**state, "changed": changed}

    async def _grant_automatic_recognition(
        self,
        connection: Any,
        *,
        guild_id: int,
        contribution: Any,
        project: Any | None,
        actor_id: int,
        now: int,
    ) -> None:
        member_id = int(contribution["member_id"])
        discord_id = int(contribution["discord_id"])
        state = await self._reconcile_automatic_honor(
            connection,
            guild_id=guild_id,
            member_id=member_id,
            discord_id=discord_id,
            actor_id=actor_id,
            now=now,
        )
        total = int(state["total"])
        if total == 1:
            await self._grant_achievement(
                connection,
                guild_id=guild_id,
                member_id=member_id,
                discord_id=discord_id,
                key="PRIMEIRO_APOIO",
                source="AUTOMATICA",
                reason="Primeiro apoio voluntário confirmado.",
                actor_id=actor_id,
                now=now,
            )
        if project is not None:
            await self._grant_achievement(
                connection,
                guild_id=guild_id,
                member_id=member_id,
                discord_id=discord_id,
                key="APOIADOR_DE_PROJETO",
                source="AUTOMATICA",
                reason="Apoio confirmado para uma meta específica.",
                actor_id=actor_id,
                now=now,
            )
            category = str(project["category"]).upper()
            category_key = {
                "VIATURA": "APOIADOR_DE_VIATURA",
                "SKIN": "APOIADOR_DE_IDENTIDADE",
                "PLOTAGEM": "APOIADOR_DE_IDENTIDADE",
                "UNIFORME": "APOIADOR_DE_IDENTIDADE",
                "IDENTIDADE_VISUAL": "APOIADOR_DE_IDENTIDADE",
                "MOD": "APOIADOR_DE_INFRAESTRUTURA",
                "SISTEMA": "APOIADOR_DE_INFRAESTRUTURA",
                "INFRAESTRUTURA": "APOIADOR_DE_INFRAESTRUTURA",
            }.get(category)
            if category_key:
                await self._grant_achievement(
                    connection,
                    guild_id=guild_id,
                    member_id=member_id,
                    discord_id=discord_id,
                    key=category_key,
                    source="AUTOMATICA",
                    reason=f"Apoio confirmado em projeto de {category.lower()}.",
                    actor_id=actor_id,
                    now=now,
                )
        cursor = await connection.execute(
            """
            SELECT COUNT(DISTINCT COALESCE(project_id, -1)) AS destinations
            FROM financial_contributions
            WHERE guild_id=? AND member_id=? AND status='CONFIRMADA' AND reversed_at IS NULL
            """,
            (guild_id, member_id),
        )
        if int((await cursor.fetchone())["destinations"]) >= 2:
            await self._grant_achievement(
                connection,
                guild_id=guild_id,
                member_id=member_id,
                discord_id=discord_id,
                key="APOIO_RECORRENTE",
                source="AUTOMATICA",
                reason="Participação confirmada em destinos distintos; sem relação com valor financeiro.",
                actor_id=actor_id,
                now=now,
            )

    async def _grant_project_completion_achievements(
        self,
        connection: Any,
        *,
        guild_id: int,
        project_id: int,
        actor_id: int,
        now: int,
    ) -> None:
        cursor = await connection.execute(
            """
            SELECT DISTINCT member_id, discord_id FROM financial_contributions
            WHERE guild_id=? AND project_id=? AND status='CONFIRMADA' AND reversed_at IS NULL
            ORDER BY member_id
            """,
            (guild_id, project_id),
        )
        members = await cursor.fetchall()
        for index, member in enumerate(members):
            await self._grant_achievement(
                connection,
                guild_id=guild_id,
                member_id=int(member["member_id"]),
                discord_id=int(member["discord_id"]),
                key="PROJETO_CONCLUIDO",
                source="AUTOMATICA",
                reason="Participou de uma meta concluída.",
                actor_id=actor_id,
                now=now,
            )
            if index < 3:
                await self._grant_achievement(
                    connection,
                    guild_id=guild_id,
                    member_id=int(member["member_id"]),
                    discord_id=int(member["discord_id"]),
                    key="FUNDADOR_DE_PROJETO",
                    source="AUTOMATICA",
                    reason="Esteve entre os primeiros apoiadores confirmados da meta.",
                    actor_id=actor_id,
                    now=now,
                )

    async def grant_honor(
        self,
        guild_id: int,
        discord_id: int,
        *,
        honor_key: str,
        actor_id: int,
        justification: str,
        expires_at: int | None = None,
    ) -> dict[str, object]:
        await self.ensure_defaults(guild_id)
        key = self._require_text(honor_key, "Honraria", maximum=40).upper()
        justification = self._require_text(justification, "Justificativa", maximum=1500)
        now = self.clock()
        async with self.database.transaction() as connection:
            member = await self._member(connection, guild_id, discord_id)
            return await self._grant_honor(
                connection,
                guild_id=guild_id,
                member_id=int(member["id"]),
                discord_id=discord_id,
                honor_key=key,
                source="MANUAL",
                justification=justification,
                actor_id=actor_id,
                expires_at=expires_at,
                now=now,
            )

    async def remove_honor(
        self,
        guild_id: int,
        honor_id: int,
        *,
        actor_id: int,
        expected_version: int,
        reason: str,
    ) -> dict[str, object]:
        reason = self._require_text(reason, "Justificativa da remoção", maximum=1500)
        now = self.clock()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM financial_member_honors
                WHERE id=? AND guild_id=?
                """,
                (honor_id, guild_id),
            )
            honor = await cursor.fetchone()
            if not honor:
                raise NotFoundError("Honraria não encontrada.")
            if honor["removed_at"] is not None:
                return self._row(honor)
            if int(honor["version"]) != int(expected_version):
                raise ConflictError("A honraria mudou. Atualize antes de remover.")
            await connection.execute(
                """
                UPDATE financial_member_honors
                SET removed_by=?, removed_at=?, removal_reason=?, version=version+1
                WHERE id=? AND version=? AND removed_at IS NULL
                """,
                (actor_id, now, reason, honor_id, expected_version),
            )
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_HONOR_REMOVED",
                actor_id=actor_id,
                target_member_id=int(honor["member_id"]),
                honor_id=honor_id,
                before={"source": honor["source"]},
                after={"removed": True},
                reason=reason,
                now=now,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="HONOR_REMOVED",
                subject_type="HONOR",
                subject_id=honor_id,
                event_key=f"financial-honor-removed:{honor_id}:v{int(honor['version']) + 1}",
                target_discord_id=int(honor["discord_id"]),
                channel_setting_key=None,
                payload={"reason": reason},
                now=now,
            )
            cursor = await connection.execute("SELECT * FROM financial_member_honors WHERE id=?", (honor_id,))
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)

    async def _expire_honor(
        self,
        connection: Any,
        *,
        honor: Any,
        now: int,
        reason: str,
    ) -> bool:
        """Close a time-limited symbolic honor exactly once inside its transaction."""
        if honor["removed_at"] is not None:
            return False
        cursor = await connection.execute(
            """
            UPDATE financial_member_honors
            SET removed_at=?, removal_reason=?, version=version+1
            WHERE id=? AND removed_at IS NULL AND expires_at IS NOT NULL AND expires_at<=?
            """,
            (now, reason, int(honor["id"]), now),
        )
        if cursor.rowcount != 1:
            return False
        await self._audit_event(
            connection,
            guild_id=int(honor["guild_id"]),
            event_type="FINANCIAL_HONOR_EXPIRED",
            actor_id=None,
            target_member_id=int(honor["member_id"]),
            honor_id=int(honor["id"]),
            before={"expires_at": int(honor["expires_at"])},
            after={"removed": True, "reason": "EXPIRADA"},
            reason=reason,
            now=now,
        )
        await self._enqueue_notification(
            connection,
            guild_id=int(honor["guild_id"]),
            notification_type="HONOR_REMOVED",
            subject_type="HONOR",
            subject_id=int(honor["id"]),
            event_key=f"financial-honor-expired:{int(honor['id'])}:v{int(honor['version']) + 1}",
            target_discord_id=int(honor["discord_id"]),
            channel_setting_key=None,
            payload={"reason": reason},
            now=now,
        )
        return True

    async def expire_due_honors(self, guild_id: int) -> list[dict[str, object]]:
        """Expire only time-bounded honors; their immutable history remains available."""
        await self.ensure_defaults(guild_id)
        now = self.clock()
        expired: list[dict[str, object]] = []
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM financial_member_honors
                WHERE guild_id=? AND removed_at IS NULL AND expires_at IS NOT NULL AND expires_at<=?
                ORDER BY expires_at, id
                """,
                (guild_id, now),
            )
            for honor in await cursor.fetchall():
                if await self._expire_honor(
                    connection,
                    honor=honor,
                    now=now,
                    reason="Prazo de honraria simbólica encerrado automaticamente.",
                ):
                    expired.append(self._row(honor))
        return expired

    async def member_honor_snapshot(self, guild_id: int, discord_id: int) -> dict[str, object]:
        await self.ensure_defaults(guild_id)
        member = await self.database.fetchone(
            "SELECT id FROM members WHERE guild_id=? AND discord_id=?", (guild_id, discord_id)
        )
        if not member:
            raise NotFoundError("Membro não encontrado.")
        honors = await self.database.fetchall(
            """
            SELECT h.*, d.honor_key, d.title, d.description, d.symbolic_only
            FROM financial_member_honors h
            JOIN financial_honor_definitions d ON d.id=h.honor_definition_id
            WHERE h.guild_id=? AND h.member_id=? AND h.removed_at IS NULL
              AND (h.expires_at IS NULL OR h.expires_at>?)
            ORDER BY h.granted_at DESC, h.id DESC
            """,
            (guild_id, int(member["id"]), self.clock()),
        )
        achievements = await self.database.fetchall(
            """
            SELECT a.*, d.achievement_key, d.title, d.description
            FROM financial_member_achievements a
            JOIN financial_achievement_definitions d ON d.id=a.achievement_definition_id
            WHERE a.guild_id=? AND a.member_id=?
            ORDER BY a.awarded_at DESC, a.id DESC
            """,
            (guild_id, int(member["id"])),
        )
        honor_items = [self._row(row) for row in honors]
        for item in honor_items:
            item["symbolic_only"] = bool(item["symbolic_only"])
        return {
            "discord_id": discord_id,
            "honors": honor_items,
            "achievements": [self._row(row) for row in achievements],
        }

    async def certificate_snapshot(self, guild_id: int, certificate_id: int) -> dict[str, object]:
        """Return a non-financial certificate view from canonical records.

        The validation code is durable; the display is rebuilt on demand so a
        notification recovery never depends on a cached Discord payload.
        """
        certificate = await self.database.fetchone(
            """
            SELECT c.*, m.mta_nick, m.discord_nick,
                   h.title AS honor_title, p.public_code AS project_code, p.name AS project_name
            FROM financial_certificates AS c
            JOIN members AS m ON m.id=c.member_id
            LEFT JOIN financial_member_honors AS mh ON mh.id=c.honor_id
            LEFT JOIN financial_honor_definitions AS h ON h.id=mh.honor_definition_id
            LEFT JOIN financial_projects AS p ON p.id=c.project_id
            WHERE c.id=? AND c.guild_id=?
            """,
            (certificate_id, guild_id),
        )
        if not certificate:
            raise NotFoundError("Certificado financeiro não encontrado.")
        achievements = await self.database.fetchall(
            """
            SELECT d.title
            FROM financial_member_achievements AS a
            JOIN financial_achievement_definitions AS d ON d.id=a.achievement_definition_id
            WHERE a.guild_id=? AND a.member_id=?
            ORDER BY a.awarded_at DESC, a.id DESC LIMIT 8
            """,
            (guild_id, int(certificate["member_id"])),
        )
        item = self._row(certificate)
        item["member_name"] = str(certificate["mta_nick"] or certificate["discord_nick"] or "Membro CHOQUE")
        item["honor_title"] = str(certificate["honor_title"] or "Reconhecimento institucional")
        item["achievement_titles"] = [str(row["title"]) for row in achievements]
        return item

    async def issue_certificate(
        self,
        guild_id: int,
        discord_id: int,
        *,
        actor_id: int,
        honor_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, object]:
        now = self.clock()
        async with self.database.transaction() as connection:
            member = await self._member(connection, guild_id, discord_id)
            if honor_id is not None:
                cursor = await connection.execute(
                    """
                    SELECT 1 FROM financial_member_honors
                    WHERE id=? AND guild_id=? AND member_id=? AND removed_at IS NULL
                    """,
                    (honor_id, guild_id, int(member["id"])),
                )
                if not await cursor.fetchone():
                    raise ValidationError("A honraria informada não está ativa para este membro.")
            if project_id is not None:
                cursor = await connection.execute(
                    "SELECT 1 FROM financial_projects WHERE id=? AND guild_id=?", (project_id, guild_id)
                )
                if not await cursor.fetchone():
                    raise NotFoundError("Meta financeira não encontrada.")
            validation_code = f"CHOQUE-{secrets.token_hex(5).upper()}"
            cursor = await connection.execute(
                """
                INSERT INTO financial_certificates(
                    guild_id, member_id, discord_id, honor_id, project_id,
                    validation_code, issued_by, issued_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, int(member["id"]), discord_id, honor_id, project_id, validation_code, actor_id, now),
            )
            certificate_id = int(cursor.lastrowid)
            await self._audit_event(
                connection,
                guild_id=guild_id,
                event_type="FINANCIAL_CERTIFICATE_ISSUED",
                actor_id=actor_id,
                target_member_id=int(member["id"]),
                honor_id=honor_id,
                project_id=project_id,
                after={"certificate_id": certificate_id, "validation_code": validation_code},
                reason="Certificado simbólico emitido sem valor financeiro.",
                now=now,
            )
            await self._enqueue_notification(
                connection,
                guild_id=guild_id,
                notification_type="CERTIFICATE_ISSUED",
                subject_type="CERTIFICATE",
                subject_id=certificate_id,
                event_key=f"financial-certificate-issued:{certificate_id}",
                target_discord_id=discord_id,
                channel_setting_key=None,
                payload={"validation_code": validation_code},
                now=now,
            )
            cursor = await connection.execute("SELECT * FROM financial_certificates WHERE id=?", (certificate_id,))
            row = await cursor.fetchone()
            assert row is not None
            return self._row(row)
