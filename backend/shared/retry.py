import random
import time


def call_with_backoff(fn, *args, max_retries=2, base_delay=1.0, **kwargs):
    """Retries fn(*args, **kwargs) with exponential backoff + jitter -- so a
    single flaky Gemini call doesn't fail a whole debate round.
    """
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception:
            if attempt == max_retries:
                raise
            delay = base_delay * (2**attempt) + random.uniform(0, 1)
            time.sleep(delay)
