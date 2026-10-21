"""Structured application events with an explicit safe metadata allowlist."""
import json
import logging
from datetime import datetime, timezone

from dataforge.connections import current_connections


class JsonFormatter(logging.Formatter):
    """Format application log records as JSON with credential-safe metadata."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a record and redact any active connection credentials."""
        event = {"time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                 "level": record.levelname, "logger": record.name, "event": record.getMessage()}
        for key in ("run_id", "line", "error_type"):
            if hasattr(record, key):
                event[key] = getattr(record, key)
        if record.exc_info:
            event["error_type"] = record.exc_info[0].__name__
        return current_connections().redact(json.dumps(event))


def configure_logging(level: str = "INFO") -> None:
    """Configure the application's JSON stream logger at a supported level."""
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("Choose DEBUG, INFO, WARNING or ERROR logging")
    logger = logging.getLogger("dataforge")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def save_application_logging(store: object, level: str) -> None:
    """Apply a logging level and persist it in the application settings scope."""
    configure_logging(level)
    store.set_setting('__application__', 'log_level', level)
