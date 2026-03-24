"""Shared rate limiter for all Claude API calls."""
import threading
import time
import os

_api_semaphore = threading.Semaphore(int(os.getenv("MAX_PARALLEL_CUSTOMERS", "2")))


def with_rate_limit(fn, *args, max_retries=4, **kwargs):
    """Execute fn with semaphore + exponential backoff on rate limit errors."""
    import anthropic
    with _api_semaphore:
        for attempt in range(max_retries):
            try:
                return fn(*args, **kwargs)
            except anthropic.RateLimitError:
                if attempt == max_retries - 1:
                    raise
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
