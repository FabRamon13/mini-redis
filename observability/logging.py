import json
import logging
import sys
from datetime import datetime, timezone


STANDARD_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}

RESERVED_OUTPUT_FIELDS = {
    "event",
    "exception",
    "level",
    "service",
    "timestamp",
}

SENSITIVE_LOG_FIELDS = {
    "api_key",
    "claim_token",
    "embedding",
    "password",
    "prompt",
    "response",
    "secret",
}


class JsonFormatter(logging.Formatter):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            ).isoformat(),
            "level": record.levelname.lower(),
            "service": self.service,
            "event": getattr(record, "event", record.getMessage()),
        }

        for key, value in record.__dict__.items():
            if (
                key not in STANDARD_LOG_RECORD_FIELDS
                and key not in RESERVED_OUTPUT_FIELDS
                and key not in SENSITIVE_LOG_FIELDS
            ):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_json_logger(service, level=logging.INFO):
    logger = logging.getLogger(service)
    logger.setLevel(level)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    logger.handlers = [handler]

    return logger


def log_event(logger, event, level=logging.INFO, exc_info=None, **fields):
    logger.log(
        level,
        event,
        extra={"event": event, **fields},
        exc_info=exc_info,
    )
