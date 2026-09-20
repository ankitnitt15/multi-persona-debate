import os

REDIS_URL = os.getenv("REDIS_URL")

if REDIS_URL:
    import redis

    client = redis.from_url(REDIS_URL, decode_responses=True)
else:
    print(
        "REDIS_URL not set -- cache/debate_cache.py and limits/rate_limiter.py "
        "will fall back to an in-memory store. Fine for local dev; do not run "
        "production traffic this way (state is lost on restart and not shared "
        "across instances)."
    )
    client = None
