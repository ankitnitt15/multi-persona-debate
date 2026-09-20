import datetime

from redis_client import client as _redis

_COUNTER_TTL = 60 * 60 * 26  # a little over a day, so a counter always outlives its calendar day
_memory_counts: dict[str, int] = {}


def _today() -> str:
    return datetime.date.today().isoformat()


def _read(key: str) -> int:
    if _redis:
        raw = _redis.get(key)
        return int(raw) if raw else 0
    return _memory_counts.get(key, 0)


def _increment(key: str, amount: int) -> int:
    if _redis:
        pipe = _redis.pipeline()
        pipe.incrby(key, amount)
        pipe.expire(key, _COUNTER_TTL)
        count, _ = pipe.execute()
        return count
    _memory_counts[key] = _memory_counts.get(key, 0) + amount
    return _memory_counts[key]


def check_user_cap(anon_id: str, daily_cap: int) -> tuple[bool, int]:
    count = _read(f"count:{anon_id}:{_today()}")
    return count < daily_cap, count


def record_user_usage(anon_id: str) -> int:
    return _increment(f"count:{anon_id}:{_today()}", 1)


def check_global_cap(daily_cap: int) -> tuple[bool, int]:
    count = _read(f"global:{_today()}")
    return count < daily_cap, count


def record_global_usage(gemini_calls: int) -> int:
    return _increment(f"global:{_today()}", gemini_calls)
