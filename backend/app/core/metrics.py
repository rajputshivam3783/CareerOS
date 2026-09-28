"""V16 — minimal metrics registry, exposed at GET /metrics.

Deliberately hand-rolled (stdlib only, no ``prometheus_client``
dependency) for the same reason ``app.core.rate_limit`` is hand-rolled
in-memory rather than Redis-backed: it keeps the project runnable
zero-config on a single instance, and the output is still standard
Prometheus text exposition format so a real Prometheus server (or
``docker-compose.production.yml`` sidecar) can scrape it as-is.

Like the rate limiter, these counters are per-process — with more than
one API replica, each exposes only its own counters rather than a
merged total. A multi-replica deployment should scrape every replica
individually (standard Prometheus practice) or pair this with a
push-gateway/shared backend; that upgrade path is the same one called
out for the rate limiter in README, not a new limitation.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

_lock = Lock()
_request_counts: dict[tuple[str, str, int], int] = defaultdict(int)
_request_duration_sum_seconds: dict[tuple[str, str], float] = defaultdict(float)
_request_duration_count: dict[tuple[str, str], int] = defaultdict(int)
_process_started_at = time.time()


def record_request(method: str, route: str, status_code: int, duration_seconds: float) -> None:
    with _lock:
        _request_counts[(method, route, status_code)] += 1
        _request_duration_sum_seconds[(method, route)] += duration_seconds
        _request_duration_count[(method, route)] += 1


def render_prometheus_text() -> str:
    """Render current counters as Prometheus text exposition format."""
    lines: list[str] = []

    lines.append("# HELP careeros_process_uptime_seconds Seconds since this API process started.")
    lines.append("# TYPE careeros_process_uptime_seconds gauge")
    lines.append(f"careeros_process_uptime_seconds {time.time() - _process_started_at:.3f}")

    with _lock:
        lines.append("# HELP careeros_http_requests_total Total HTTP requests.")
        lines.append("# TYPE careeros_http_requests_total counter")
        for (method, route, status_code), count in sorted(_request_counts.items()):
            lines.append(
                f'careeros_http_requests_total{{method="{method}",route="{route}",status="{status_code}"}} {count}'
            )

        lines.append("# HELP careeros_http_request_duration_seconds_sum Sum of request durations.")
        lines.append("# TYPE careeros_http_request_duration_seconds_sum counter")
        for (method, route), total in sorted(_request_duration_sum_seconds.items()):
            lines.append(
                f'careeros_http_request_duration_seconds_sum{{method="{method}",route="{route}"}} {total:.6f}'
            )

        lines.append("# HELP careeros_http_request_duration_seconds_count Count of measured requests.")
        lines.append("# TYPE careeros_http_request_duration_seconds_count counter")
        for (method, route), count in sorted(_request_duration_count.items()):
            lines.append(
                f'careeros_http_request_duration_seconds_count{{method="{method}",route="{route}"}} {count}'
            )

    return "\n".join(lines) + "\n"
