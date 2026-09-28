"""V16 — Redis-backed rate limiting. Uses a mock Redis client (duck-typed
.incr/.expire) rather than a real Redis server or the `redis` package,
so these run without any extra service in the test environment."""

from fastapi import HTTPException

from app.core.rate_limit import _enforce_redis


class _FakeRedis:
    """Minimal stand-in for redis.Redis, in-process only."""

    def __init__(self):
        self.counts: dict[str, int] = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        pass


class _BrokenRedis:
    """Simulates Redis being unreachable."""

    def incr(self, key):
        raise ConnectionError("simulated redis outage")


def test_redis_backend_enforces_limit():
    client = _FakeRedis()
    for _ in range(5):
        assert _enforce_redis(client, "test-bucket:1.2.3.4", limit=5, window=60, bucket="test") is True

    try:
        _enforce_redis(client, "test-bucket:1.2.3.4", limit=5, window=60, bucket="test")
        assert False, "expected HTTPException on the 6th attempt"
    except HTTPException as exc:
        assert exc.status_code == 429


def test_redis_backend_is_isolated_per_key():
    client = _FakeRedis()
    for _ in range(5):
        _enforce_redis(client, "test-bucket:1.1.1.1", limit=5, window=60, bucket="test")
    # A different key (different bucket/IP) has its own budget.
    assert _enforce_redis(client, "test-bucket:2.2.2.2", limit=5, window=60, bucket="test") is True


def test_redis_failure_falls_back_instead_of_raising():
    client = _BrokenRedis()
    # Should return False (signal to fall back to in-memory), not raise
    # or silently allow unlimited attempts.
    result = _enforce_redis(client, "test-bucket:9.9.9.9", limit=5, window=60, bucket="test-broken")
    assert result is False
