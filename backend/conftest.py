import pytest

from limits import rate_limiter


@pytest.fixture(autouse=True)
def _reset_in_memory_state():
    """rate_limiter falls back to a module-level dict when REDIS_URL is
    unset (true for the whole test run) -- without this, counters from one
    test would leak into the next.
    """
    rate_limiter._memory_counts.clear()
    yield
    rate_limiter._memory_counts.clear()
