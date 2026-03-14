"""Structured logging configuration for Insight Forge backend services."""

import logging
import sys
from typing import Any


def setup_logging(
    service_name: str,
    level: int = logging.INFO,
    json_format: bool = False,
) -> logging.Logger:
    """
    Configure and return a logger for the given service.

    Args:
        service_name: Name of the service (e.g., generation, retriever, fill_engine)
        level: Logging level
        json_format: If True, use JSON format; otherwise use human-readable format

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(service_name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if json_format:
        # Simple JSON-like format for structured logging
        formatter = logging.Formatter(
            '{"timestamp":"%(asctime)s","level":"%(levelname)s","service":"%(name)s",'
            '"message":"%(message)s","module":"%(module)s","line":%(lineno)d}'
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def get_logger(name: str, extra: dict[str, Any] | None = None) -> logging.Logger:
    """
    Get a logger with optional extra context.

    Args:
        name: Logger name (typically __name__)
        extra: Optional dict of extra fields to include in log records

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
