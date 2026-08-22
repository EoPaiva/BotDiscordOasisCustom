from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "America/Sao_Paulo"


def utc_now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def discord_timestamp(timestamp_ms: int, style: str = "f") -> str:
    return f"<t:{timestamp_ms // 1000}:{style}>"


def format_duration(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}h{minutes:02d}"
    return f"{minutes}min"


def period_bounds(period: str, timezone_name: str = DEFAULT_TIMEZONE) -> tuple[int, int]:
    zone = ZoneInfo(timezone_name)
    now = datetime.now(zone)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Periodo invalido: {period}")
    end = now
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)
