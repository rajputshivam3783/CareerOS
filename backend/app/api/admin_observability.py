"""V25.5 — GET /admin/observability (spec section 35).

V25.2 already built ``app.services.platform_health`` — a genuine,
well-tested aggregate health module (database, migrations, scheduler,
email, AI provider, notifications, ingestion — see
``system_health``/``background_jobs``). This endpoint does NOT
re-derive any of that; it calls straight into it, matching this
spec's own instruction to reuse existing infrastructure rather than
duplicate it. What V25.5 actually adds on top, because nothing
existing covered it, is exactly three things:

1. An HTTP request/latency/error-rate summary from the counters
   ``app.core.metrics`` already collects (nothing previously exposed
   these as anything but raw Prometheus text at /metrics).
2. The durable, cross-job dead-letter summary from
   ``app.reliability.dead_letter`` — broader than platform_health's
   email-only failed-row tracking, since it also covers the scheduler
   jobs (ingestion, digests, reminders, ...) that have no per-row
   table of their own.
3. A DB connection-pool snapshot (spec section 17's "document the
   configuration", made live rather than static).

Gated behind the same ``require_platform_permission(PLATFORM_ANALYTICS)``
dependency already used for the V25.3 admin analytics endpoints — this
is another platform-analytics view, not a new permission domain.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core import metrics as metrics_module
from app.core.platform_admin import PlatformActor, PlatformPermission, require_platform_permission
from app.db.session import engine, get_db
from app.reliability import dead_letter
from app.services import platform_health

router = APIRouter()


def _request_metrics_summary() -> dict:
    """Reshapes app.core.metrics' counters into a small per-route
    summary (error rate, avg latency) rather than raw Prometheus
    text — easier for a dashboard to render. Read-only: does not
    touch the counters. Mirrors render_prometheus_text's own locking
    discipline since these dicts are written from every request's
    middleware."""
    total_requests = 0
    total_errors = 0
    per_route: dict[str, dict] = {}
    with metrics_module._lock:
        request_counts = dict(metrics_module._request_counts)
        duration_sums = dict(metrics_module._request_duration_sum_seconds)
        duration_counts = dict(metrics_module._request_duration_count)

    for (method, route, status), count in request_counts.items():
        total_requests += count
        if status >= 500:
            total_errors += count
        key = f"{method} {route}"
        entry = per_route.setdefault(key, {"count": 0, "errors": 0})
        entry["count"] += count
        if status >= 500:
            entry["errors"] += count

    for (method, route), duration_sum in duration_sums.items():
        key = f"{method} {route}"
        count = duration_counts.get((method, route), 0)
        if key in per_route and count:
            per_route[key]["avg_latency_ms"] = round((duration_sum / count) * 1000, 1)

    top_routes = sorted(per_route.items(), key=lambda kv: kv[1]["count"], reverse=True)[:15]
    return {
        "total_requests": total_requests,
        "total_5xx_errors": total_errors,
        "error_rate_pct": round((total_errors / total_requests) * 100, 3) if total_requests else 0.0,
        "top_routes": [{"route": k, **v} for k, v in top_routes],
    }


def _db_pool_snapshot() -> dict:
    """Best-effort — SQLAlchemy's QueuePool exposes these; SQLite's
    pool does not, so this degrades to an explicit note rather than
    raising. See app.db.session for why pool_size/max_overflow are
    Postgres-only."""
    pool = engine.pool
    try:
        return {
            "checked_out": pool.checkedout(),
            "checked_in": pool.checkedin(),
            "size": pool.size(),
            "overflow": pool.overflow(),
        }
    except AttributeError:
        return {"note": "Pool introspection not available for this database backend (e.g. SQLite in dev/test)."}


@router.get("/observability")
def observability_dashboard(
    since_hours: int = 24,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.PLATFORM_ANALYTICS)),
):
    """Platform-admin-only aggregate operations view.

    ``system_health``/``background_jobs`` are the existing V25.2
    source of truth for database/scheduler/email/AI/notification/
    ingestion status — reused here unchanged. api/dead_letter/database
    are the three additions described in this module's docstring.
    """
    since = datetime.utcnow() - timedelta(hours=since_hours)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "window_hours": since_hours,
        "api": _request_metrics_summary(),
        "system_health": platform_health.system_health(db),
        "background_jobs": {
            **platform_health.background_jobs(db),
            "dead_letter": dead_letter.summarize(db, since=since),
        },
        "database": {"connection_pool": _db_pool_snapshot()},
    }

