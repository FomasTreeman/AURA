"""
Structured logging utilities for AURA backend.
Uses Rich for console output and Python's logging for structured records.
"""
import logging
import sys
from rich.console import Console
from rich.logging import RichHandler

console = Console(stderr=True)

# ── Module-level logger factory ───────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger configured with a Rich handler.

    Args:
        name: Logger name, typically __name__ of the calling module.

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


# Default application-level logger
log = get_logger("aura")
