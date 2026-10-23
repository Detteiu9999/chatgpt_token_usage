"""Normalize the read-only Codex usage/reset-credit responses."""

from dataclasses import dataclass
from datetime import datetime
import math
import time


@dataclass(frozen=True)
class UsageWindow:
    used: float
    resets_at: float | None

    @property
    def remaining(self) -> float:
        return max(0.0, min(100.0, 100.0 - self.used))


@dataclass(frozen=True)
class Usage:
    five_hour: UsageWindow | None
    weekly: UsageWindow | None
    reset_count: int | None
    next_expiry: float | None
    plan: str
    fetched_at: float


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return float(value) if math.isfinite(value) else None


def count(value):
    n = number(value)
    return int(n) if n is not None and n >= 0 and n.is_integer() else None


def parse_usage(payload: dict, details: dict | None = None, now=None) -> Usage:
    """Missing fields stay unknown, especially unknown reset counts vs zero."""
    now = time.time() if now is None else now
    if not isinstance(payload, dict) or not any(
        key in payload for key in ("plan_type", "rate_limit", "rate_limit_reset_credits")
    ):
        raise ValueError("使用量データの形式を確認できませんでした")
    limits = payload.get("rate_limit") or {}
    if not isinstance(limits, dict):
        limits = {}
    windows = {}
    for key, fallback in (("primary_window", 18000), ("secondary_window", 604800)):
        item = limits.get(key)
        if not isinstance(item, dict):
            continue
        used = number(item.get("used_percent"))
        if used is None or used < 0:
            continue
        duration = item.get("limit_window_seconds", fallback)
        if duration not in (18000, 604800):
            continue
        reset = number(item.get("reset_at"))
        if reset is None:
            after = number(item.get("reset_after_seconds"))
            reset = now + after if after is not None and after >= 0 else None
        windows[duration] = UsageWindow(used, reset)
    summary = payload.get("rate_limit_reset_credits")
    available = count(summary.get("available_count")) if isinstance(summary, dict) else None
    expiry = None
    if isinstance(details, dict):
        detailed_count = count(details.get("available_count"))
        if detailed_count is not None:
            available = detailed_count
        expiries = []
        for credit in details.get("credits") or []:
            if not isinstance(credit, dict) or credit.get("status") != "available":
                continue
            try:
                expires = datetime.fromisoformat(credit["expires_at"].replace("Z", "+00:00"))
                timestamp = expires.timestamp()
                if timestamp > now:
                    expiries.append(timestamp)
            except (KeyError, ValueError, AttributeError, TypeError, OverflowError):
                continue
        expiry = min(expiries, default=None)
    return Usage(windows.get(18000), windows.get(604800), available, expiry,
                 str(payload.get("plan_type") or ""), now)
