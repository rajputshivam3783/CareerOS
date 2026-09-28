"""AI metrics: latency, failures, token usage, cost, success rate, and
per-provider health.

Two layers, matching the split app.core.metrics already uses for HTTP
requests: an in-memory rolling registry for cheap "is this provider
healthy right now" checks (per-process, resets on restart — the same
tradeoff documented in app.core.metrics), and durable ``AIUsageLog``
rows in the database for historical/admin-dashboard queries that must
survive a restart.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import AIUsageLog

_lock = Lock()
# Rolling window of the last N outcomes per provider, for a live health
# signal without scanning the database on every /ai/health request.
_ROLLING_WINDOW = 50
_provider_outcomes: dict[str, deque] = defaultdict(lambda: deque(maxlen=_ROLLING_WINDOW))
_provider_latencies_ms: dict[str, deque] = defaultdict(lambda: deque(maxlen=_ROLLING_WINDOW))
_process_started_at = time.time()


@dataclass
class UsageEvent:
    service: str  # completion / embedding / moderation
    provider: str
    model: str | None
    operation: str | None
    used_fallback: bool
    prompt_tokens: int
    completion_tokens: int
    cost_estimate_usd: float
    latency_ms: float
    success: bool
    error: str | None = None
    user_id: int | None = None


def record_event(db: Session, event: UsageEvent) -> AIUsageLog:
    """Persists the event and updates the in-memory rolling health
    stats. Called by every AI service after each provider call,
    success or failure — the log table is the append-only source of
    truth; the in-memory deques are a fast derived cache."""
    with _lock:
        _provider_outcomes[event.provider].append(event.success)
        _provider_latencies_ms[event.provider].append(event.latency_ms)

    row = AIUsageLog(
        service=event.service,
        operation=event.operation,
        provider=event.provider,
        model=event.model,
        used_fallback=event.used_fallback,
        prompt_tokens=event.prompt_tokens,
        completion_tokens=event.completion_tokens,
        cost_estimate_usd=event.cost_estimate_usd,
        latency_ms=event.latency_ms,
        success=event.success,
        error=event.error,
        user_id=event.user_id,
    )
    db.add(row)
    db.commit()
    return row


def live_provider_health() -> dict[str, dict]:
    """In-memory, zero-DB-query snapshot per provider that has made at
    least one call this process's lifetime: recent success rate and
    average latency over the last _ROLLING_WINDOW calls."""
    with _lock:
        health = {}
        for provider, outcomes in _provider_outcomes.items():
            if not outcomes:
                continue
            latencies = _provider_latencies_ms[provider]
            health[provider] = {
                "recent_calls": len(outcomes),
                "recent_success_rate": round(sum(outcomes) / len(outcomes), 4),
                "recent_avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
                "status": "healthy" if (sum(outcomes) / len(outcomes)) >= 0.5 else "degraded",
            }
        return health


def usage_summary(db: Session, *, since_hours: int = 24) -> dict:
    """Durable, DB-backed usage aggregation for the admin dashboard —
    survives a process restart, unlike live_provider_health()."""
    # SQLite/Postgres interval syntax diverges enough that a plain
    # Python cutoff comparison is simpler and portable than trying to
    # express "now() - N hours" identically in both dialects.
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(hours=since_hours)

    rows = db.execute(
        select(
            AIUsageLog.provider,
            AIUsageLog.service,
            func.count(AIUsageLog.id),
            func.sum(AIUsageLog.prompt_tokens),
            func.sum(AIUsageLog.completion_tokens),
            func.sum(AIUsageLog.cost_estimate_usd),
            func.avg(AIUsageLog.latency_ms),
        ).where(AIUsageLog.created_at >= since).group_by(AIUsageLog.provider, AIUsageLog.service)
    ).all()

    by_provider: dict[str, dict] = {}
    for provider, service, count, prompt_tokens, completion_tokens, cost, avg_latency in rows:
        entry = by_provider.setdefault(
            provider, {"total_calls": 0, "total_tokens": 0, "total_cost_usd": 0.0, "by_service": {}}
        )
        entry["total_calls"] += count
        entry["total_tokens"] += (prompt_tokens or 0) + (completion_tokens or 0)
        entry["total_cost_usd"] = round(entry["total_cost_usd"] + (cost or 0.0), 6)
        entry["by_service"][service] = {
            "calls": count,
            "prompt_tokens": prompt_tokens or 0,
            "completion_tokens": completion_tokens or 0,
            "cost_usd": round(cost or 0.0, 6),
            "avg_latency_ms": round(avg_latency or 0.0, 2),
        }

    success_total = db.execute(
        select(func.count(AIUsageLog.id)).where(AIUsageLog.created_at >= since, AIUsageLog.success.is_(True))
    ).scalar_one()
    failure_total = db.execute(
        select(func.count(AIUsageLog.id)).where(AIUsageLog.created_at >= since, AIUsageLog.success.is_(False))
    ).scalar_one()

    return {
        "since_hours": since_hours,
        "total_calls": success_total + failure_total,
        "success_count": success_total,
        "failure_count": failure_total,
        "success_rate": round(success_total / (success_total + failure_total), 4)
        if (success_total + failure_total)
        else None,
        "by_provider": by_provider,
    }


def recent_logs(db: Session, *, limit: int = 50, provider: str | None = None, success: bool | None = None) -> list[AIUsageLog]:
    query = select(AIUsageLog).order_by(AIUsageLog.created_at.desc()).limit(limit)
    if provider:
        query = query.where(AIUsageLog.provider == provider)
    if success is not None:
        query = query.where(AIUsageLog.success == success)
    return list(db.execute(query).scalars())


def process_uptime_seconds() -> float:
    return time.time() - _process_started_at
