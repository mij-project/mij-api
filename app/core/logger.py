import sys
import json
import logging
from contextvars import ContextVar
from typing import Any, Optional, Dict

from pydantic import BaseModel

_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
_user_id: ContextVar[Optional[str]] = ContextVar("user_id", default=None)


class LogConfig(BaseModel):
    service: str = "Backend API"
    level: str = "INFO"


config = LogConfig()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log: Dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "file": record.filename,
            "line": record.lineno,
            "path": record.pathname,
        }

        # log["service"] = config.service
        cid = _correlation_id.get()
        if cid:
            log["correlation_id"] = cid

        uid = _user_id.get()
        if uid:
            log["user_id"] = uid

        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log.update(record.extra)

        if record.exc_info:
            log["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log, ensure_ascii=False)


class Logger:
    _instance = None

    def __init__(self, name: str = "app"):
        if Logger._instance is None:
            logger = logging.getLogger(config.service)
            logger.setLevel(config.level)

            if not logger.handlers:
                handler = logging.StreamHandler(sys.stdout)
                handler.setFormatter(JsonFormatter())
                logger.addHandler(handler)

            logger.propagate = False
            Logger._instance = logger

    @staticmethod
    def get_logger():
        if Logger._instance is None:
            Logger()
        return Logger._instance
