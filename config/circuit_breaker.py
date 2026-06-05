import threading
import time
import logging

_log = logging.getLogger("circuit_breaker")

_CLOSED    = "CLOSED"
_OPEN      = "OPEN"
_HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout: float = 30.0):
        self.name              = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout  = recovery_timeout
        self._state            = _CLOSED
        self._failures         = 0
        self._opened_at: float | None = None
        self._lock             = threading.Lock()

    def _current_state(self) -> str:
        if self._state == _OPEN and time.time() - self._opened_at >= self.recovery_timeout:
            return _HALF_OPEN
        return self._state

    def call(self, fn, *args, **kwargs):
        with self._lock:
            s = self._current_state()
            if s == _OPEN:
                raise RuntimeError(f"circuit breaker OPEN for '{self.name}' — call skipped")

        try:
            result = fn(*args, **kwargs)
            with self._lock:
                if self._failures > 0:
                    _log.info(
                        "Circuit breaker CLOSED: '%s' recovered after %d failure(s)",
                        self.name, self._failures,
                    )
                self._state     = _CLOSED
                self._failures  = 0
                self._opened_at = None
            return result
        except Exception as exc:
            with self._lock:
                self._failures += 1
                if self._failures >= self.failure_threshold and self._state != _OPEN:
                    self._state     = _OPEN
                    self._opened_at = time.time()
                    _log.warning(
                        "Circuit breaker OPENED: '%s' failed %d times — fast-failing for %.0fs",
                        self.name, self._failures, self.recovery_timeout,
                    )
            raise exc


_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(name: str, failure_threshold: int = 3, recovery_timeout: float = 30.0) -> CircuitBreaker:
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(name, failure_threshold, recovery_timeout)
        return _registry[name]
