import logging
import sys
from typing import Any

from app.core.config import settings

_LOG_FORMAT_DEV = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
_LOG_FORMAT_PROD = "%(levelname)s %(name)s %(message)s"


class _StructuredLogger:
    """
    Thin wrapper around ``logging.Logger`` that accepts keyword arguments
    and appends them as ``key=value`` pairs to the log message.

    This allows structlog-style calls::
        logger.info("Server started", env="production", port=8000)
    without requiring the structlog package.
    """

    def __init__(self, inner: logging.Logger) -> None:
        self._inner = inner

    def _fmt(self, msg: str, kwargs: dict[str, Any]) -> str:
        if not kwargs:
            return msg
        pairs = " ".join(f"{k}={v!r}" for k, v in kwargs.items())
        return f"{msg} | {pairs}"

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._inner.debug(self._fmt(msg, kwargs))

    def info(self, msg: str, **kwargs: Any) -> None:
        self._inner.info(self._fmt(msg, kwargs))

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._inner.warning(self._fmt(msg, kwargs))

    def error(self, msg: str, **kwargs: Any) -> None:
        self._inner.error(self._fmt(msg, kwargs))

    def critical(self, msg: str, **kwargs: Any) -> None:
        self._inner.critical(self._fmt(msg, kwargs))

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._inner.exception(self._fmt(msg, kwargs))


def _configure() -> _StructuredLogger:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    fmt = _LOG_FORMAT_DEV if settings.APP_ENV == "development" else _LOG_FORMAT_PROD

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger("exovance")
    root.setLevel(level)
    if not root.handlers:          # avoid duplicate handlers on reload
        root.addHandler(handler)
    root.propagate = False
    return _StructuredLogger(root)


# All modules must use:
#   from app.core.logger import logger
logger = _configure()
