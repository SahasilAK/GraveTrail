"""Structured application events with an explicit safe metadata allowlist."""
import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        event = {"time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                 "level": record.levelname, "logger": record.name, "event": record.getMessage()}
        for key in ("run_id", "line", "error_type"):
            if hasattr(record, key):
                event[key] = getattr(record, key)
        if record.exc_info:
            event["error_type"] = record.exc_info[0].__name__
        return json.dumps(event)


def configure_logging(level="INFO"):
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("Choose DEBUG, INFO, WARNING or ERROR logging")
    logger = logging.getLogger("dataforge")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
