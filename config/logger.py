import logging
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone

# Silence noisy third-party HTTP loggers — irrelevant in console
for _noisy in ("httpx", "httpcore", "elastic_transport", "urllib3", "hpack"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        # Merge any extra fields passed via extra={...}
        for key, value in record.__dict__.items():
            if key not in logging.LogRecord(
                "", 0, "", 0, "", (), None
            ).__dict__ and key not in ("msg", "args", "levelname", "name"):
                entry[key] = value
        return json.dumps(entry, ensure_ascii=False, default=str)


class _LogstashHandler(logging.Handler):
    """Best-effort JSON-over-TCP shipping to Logstash.

    Never blocks the app: if Logstash is unreachable, logs are silently
    dropped and reconnection is attempted at most once per retry_interval.
    """

    def __init__(self, host: str, port: int, retry_interval: float = 60.0):
        super().__init__()
        self._addr = (host, port)
        self._retry_interval = retry_interval
        self._sock = None
        self._next_attempt = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        if self._sock is None:
            now = time.monotonic()
            if now < self._next_attempt:
                return
            try:
                self._sock = socket.create_connection(self._addr, timeout=0.5)
                self._sock.settimeout(2.0)
            except OSError:
                self._next_attempt = now + self._retry_interval
                return
        try:
            self._sock.sendall(self.format(record).encode("utf-8") + b"\n")
        except OSError:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            self._next_attempt = time.monotonic() + self._retry_interval


_logstash_handler = None
_logstash_checked = False


def _get_logstash_handler():
    global _logstash_handler, _logstash_checked
    if not _logstash_checked:
        _logstash_checked = True
        if os.getenv("LOGSTASH_ENABLED", "true").lower() in ("1", "true", "yes"):
            handler = _LogstashHandler(
                os.getenv("LOGSTASH_HOST", "localhost"),
                int(os.getenv("LOGSTASH_PORT", "5000")),
            )
            handler.setFormatter(_JsonFormatter())
            _logstash_handler = handler
    return _logstash_handler


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logstash = _get_logstash_handler()
        if logstash is not None:
            logger.addHandler(logstash)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    return logger
