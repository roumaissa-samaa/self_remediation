import re
import time
import random
from langchain_core.messages import BaseMessage
from config.logger import get_logger

log = get_logger("agent.llm_retry")

_MAX_RETRIES = 4
_BASE_DELAY  = 10.0


def _parse_wait_from_error(e: Exception) -> float | None:
    response = getattr(e, "response", None)
    if response is not None:
        headers = getattr(response, "headers", {})
        ra = headers.get("retry-after") or headers.get("Retry-After")
        if ra:
            try:
                return float(ra) + 1.0
            except ValueError:
                pass
        reset = headers.get("x-ratelimit-reset-requests") or headers.get("x-ratelimit-reset-tokens")
        if reset:
            return _parse_duration(reset)

    # "Please try again in 6.5s" present in Groq error messages
    m = re.search(r"try again in\s+([\d.]+)s", str(e), re.IGNORECASE)
    if m:
        return float(m.group(1)) + 1.0
    return None


def _parse_duration(s: str) -> float | None:
    """Parse '6s', '1m30s' → seconds."""
    total = 0.0
    m = re.search(r"([\d.]+)m", s)
    if m:
        total += float(m.group(1)) * 60
    m = re.search(r"([\d.]+)s", s)
    if m:
        total += float(m.group(1))
    return total + 1.0 if total > 0 else None


def invoke_with_retry(llm, messages: list[BaseMessage], max_retries: int = _MAX_RETRIES):
    """Call llm.invoke() with Retry-After-aware backoff on Groq 429 errors."""
    delay = _BASE_DELAY
    for attempt in range(max_retries):
        try:
            return llm.invoke(messages)
        except Exception as e:
            msg = str(e).lower()
            is_rate_limit = "429" in msg or "rate limit" in msg or "too many requests" in msg
            is_last       = attempt == max_retries - 1
            if is_last or not is_rate_limit:
                raise

            suggested = _parse_wait_from_error(e)
            if suggested:
                wait   = suggested
                source = "header"
            else:
                jitter = random.uniform(0, delay * 0.3)
                wait   = delay + jitter
                delay  = min(delay * 2, 120.0)
                source = "backoff"

            log.warning("Groq 429 — retrying", extra={
                "attempt": attempt + 1,
                "max":     max_retries,
                "wait_s":  round(wait, 1),
                "source":  source,
            })
            time.sleep(wait)
