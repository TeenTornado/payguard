"""
Token-bucket rate limiter for LLM API calls.
Tracks RPM and TPM in a sliding 60-second window.
"""
from __future__ import annotations

import threading
import time


class RateLimiter:
    """
    Sliding-window rate limiter for (rpm, tpm).
    Thread-safe. Blocks (sleeps) until the request can proceed.
    """

    def __init__(self, rpm: int, tpm: int) -> None:
        self._rpm = rpm
        self._tpm = tpm
        self._req_times: list[float] = []
        self._token_usage: list[tuple[float, int]] = []
        self._lock = threading.Lock()

    def acquire(self, estimated_tokens: int = 500) -> None:
        """Block until a request slot is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - 60.0
                self._req_times = [t for t in self._req_times if t > cutoff]
                self._token_usage = [(t, tok) for t, tok in self._token_usage if t > cutoff]

                req_count = len(self._req_times)
                tok_count = sum(tok for _, tok in self._token_usage)

                if req_count < self._rpm and tok_count + estimated_tokens <= self._tpm:
                    self._req_times.append(now)
                    self._token_usage.append((now, estimated_tokens))
                    return

                # Find earliest expiry
                oldest = min(
                    (self._req_times[0] if self._req_times else now + 60),
                    (self._token_usage[0][0] if self._token_usage else now + 60),
                )
                wait = max(0.05, oldest - cutoff)

            time.sleep(wait)

    def record_actual_tokens(self, tokens: int) -> None:
        """Update the last recorded estimate with the actual token count."""
        with self._lock:
            if self._token_usage:
                ts, _ = self._token_usage[-1]
                self._token_usage[-1] = (ts, tokens)


class NoopRateLimiter:
    """Used when no rate limits are configured."""

    def acquire(self, estimated_tokens: int = 500) -> None:
        pass

    def record_actual_tokens(self, tokens: int) -> None:
        pass
