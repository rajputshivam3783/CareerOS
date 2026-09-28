"""V10 — a minimal load-test script for the two endpoints most likely
to matter at scale: the public job listing and the personalized
recommendations feed (the only one that iterates up to 200 published
jobs per request server-side — see app/api/platform.py).

This is a starting point for someone with a real deployment to run,
not a verified benchmark: it hasn't been run against a live deployment
as part of this project, since none is running in this environment.
Treat any numbers it prints as a baseline to compare future changes
against, not as a claim about production capacity.

Usage:
    python -m scripts.load_test --url http://localhost:8000/api/v1 --requests 200 --concurrency 20
"""

import argparse
import asyncio
import statistics
import time

import httpx


async def _timed_get(client: httpx.AsyncClient, url: str) -> float:
    start = time.perf_counter()
    response = await client.get(url)
    response.raise_for_status()
    return time.perf_counter() - start


async def run(base_url: str, path: str, total_requests: int, concurrency: int) -> None:
    url = f"{base_url}{path}"
    durations: list[float] = []
    errors = 0

    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_request(client: httpx.AsyncClient):
        nonlocal errors
        async with semaphore:
            try:
                durations.append(await _timed_get(client, url))
            except Exception:
                errors += 1

    async with httpx.AsyncClient(timeout=30) as client:
        await asyncio.gather(*(bounded_request(client) for _ in range(total_requests)))

    if not durations:
        print(f"{path}: every request failed ({errors} errors) — is the server running at {base_url}?")
        return

    durations.sort()
    p50 = durations[len(durations) // 2]
    p95 = durations[int(len(durations) * 0.95) - 1]
    print(
        f"{path}: {len(durations)} ok, {errors} failed | "
        f"mean={statistics.mean(durations)*1000:.0f}ms p50={p50*1000:.0f}ms p95={p95*1000:.0f}ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000/api/v1", help="API base URL")
    parser.add_argument("--requests", type=int, default=200, help="Total requests per endpoint")
    parser.add_argument("--concurrency", type=int, default=20, help="Concurrent in-flight requests")
    args = parser.parse_args()

    for path in ("/jobs", "/jobs?search=engineer"):
        asyncio.run(run(args.url, path, args.requests, args.concurrency))


if __name__ == "__main__":
    main()
