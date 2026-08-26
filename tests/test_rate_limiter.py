"""Daily per-account rate limiting (§6.2/§6.3)."""
import threading

from src.utils.rate_limiter import RateLimiter


def test_acquire_up_to_limit_then_block():
    limiter = RateLimiter("twitter", account_id="acct-rl-1", limit=2)
    assert limiter.remaining() == 2
    assert limiter.acquire() is True
    assert limiter.acquire() is True
    assert limiter.acquire() is False
    assert limiter.remaining() == 0


def test_limits_are_per_account():
    a = RateLimiter("twitter", account_id="acct-rl-2a", limit=1)
    b = RateLimiter("twitter", account_id="acct-rl-2b", limit=1)
    assert a.acquire() is True
    assert a.acquire() is False
    assert b.acquire() is True  # different account has its own budget


def test_limits_are_per_platform():
    x = RateLimiter("twitter", account_id="acct-rl-3", limit=1)
    y = RateLimiter("linkedin", account_id="acct-rl-3", limit=1)
    assert x.acquire() is True
    assert y.acquire() is True


def test_failed_acquire_does_not_burn_quota():
    """The atomic acquire rolls back its own over-shot increment."""
    limiter = RateLimiter("twitter", account_id="acct-rl-4", limit=1)
    assert limiter.acquire() is True
    assert limiter.acquire() is False
    assert limiter.acquire() is False
    limiter.refund()
    # Only one slot was ever really consumed: after the refund a new
    # acquire succeeds again.
    assert limiter.acquire() is True
    assert limiter.remaining() == 0


def test_refund_restores_slot():
    limiter = RateLimiter("twitter", account_id="acct-rl-5", limit=2)
    assert limiter.acquire() is True
    assert limiter.remaining() == 1
    limiter.refund()
    assert limiter.remaining() == 2


def test_refund_floor_at_zero():
    limiter = RateLimiter("twitter", account_id="acct-rl-6", limit=1)
    limiter.refund()  # nothing consumed — must not go negative
    assert limiter.remaining() == 1


def test_acquire_is_atomic_under_threads():
    """8 threads racing at limit=1 must yield exactly one success."""
    limiter = RateLimiter("twitter", account_id="acct-rl-7", limit=1)
    results: list[bool] = []
    lock = threading.Lock()

    def worker():
        ok = limiter.acquire()
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1
    assert limiter.remaining() == 0
