from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateRule:
    pattern: re.Pattern[str]
    requests: int
    window_seconds: int


RULES = (
    RateRule(re.compile(r"^/health$"), 60, 60),
    RateRule(re.compile(r"^/v1/security(?:/.*)?$"), 10, 60),
    RateRule(re.compile(r"^/v1/settings(?:/.*)?$"), 30, 60),
    RateRule(re.compile(r"^/v1/registration-gate(?:/.*)?$"), 20, 60),
    RateRule(re.compile(r"^/v1/members/\d+/rank$"), 10, 60),
    RateRule(re.compile(r"^/v1/(?:inbox|requests|maintenance)(?:/.*)?$"), 30, 60),
    RateRule(re.compile(r"^/v1/recruitment/eligibility$"), 30, 60),
    RateRule(re.compile(r"^/v1/recruitment/applications/start$"), 5, 60),
    RateRule(re.compile(r"^/v1/recruitment/applications/\d+/questions/\d+/start$"), 20, 60),
    RateRule(re.compile(r"^/v1/recruitment/applications/\d+/questions/\d+/autosave$"), 120, 60),
    RateRule(re.compile(r"^/v1/recruitment/applications/\d+/questions/\d+/submit$"), 30, 60),
    RateRule(re.compile(r"^/v1/recruitment/applications/\d+/questions/\d+/integrity$"), 120, 60),
    RateRule(re.compile(r"^/v1/recruitment/applications/\d+/(submit|withdraw)$"), 5, 60),
    RateRule(re.compile(r"^/v1/officer-candidacy/application$"), 5, 60),
    RateRule(
        re.compile(r"^/v1/officer-candidacy/applications/\d+/answers/\d+$"), 90, 60
    ),
    RateRule(
        re.compile(r"^/v1/officer-candidacy/applications/\d+/submit$"), 5, 60
    ),
    RateRule(re.compile(r"^/v1/officer-applications(?:/.*)?$"), 60, 60),
    RateRule(
        re.compile(r"^/v1/admin/recruitment/applications/\d+/analysis/reanalyze$"), 5, 60
    ),
    RateRule(re.compile(r"^/v1/admin/recruitment/ai/rubric/preview$"), 3, 60),
    RateRule(re.compile(r"^/v1/admin/recruitment(?:/.*)?$"), 60, 60),
    RateRule(re.compile(r"^/v1(?:/.*)?$"), 180, 60),
)


class SlidingWindowRateLimiter:
    """Process-local limiter for the deliberately single-instance API deployment."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._checks = 0

    @staticmethod
    def rule_for(path: str) -> RateRule | None:
        return next((rule for rule in RULES if rule.pattern.fullmatch(path)), None)

    async def check(self, identity: str, path: str) -> tuple[bool, int, int] | None:
        rule = self.rule_for(path)
        if not rule:
            return None
        now = time.monotonic()
        key = (identity, rule.pattern.pattern)
        async with self._lock:
            events = self._events[key]
            cutoff = now - rule.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= rule.requests:
                retry_after = max(1, round(rule.window_seconds - (now - events[0])))
                return False, 0, retry_after
            events.append(now)
            remaining = rule.requests - len(events)
            self._checks += 1
            if self._checks % 1000 == 0:
                self._purge(cutoff)
            return True, remaining, rule.window_seconds

    def _purge(self, cutoff: float) -> None:
        empty = []
        for key, events in self._events.items():
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                empty.append(key)
        for key in empty:
            self._events.pop(key, None)
