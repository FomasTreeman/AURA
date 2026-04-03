"""
Unit tests for backend.utils.logging.
Tests logger factory and configuration.
"""

import logging
from unittest.mock import patch

import pytest


class TestGetLogger:
    """Tests for get_logger() function."""

    def test_returns_logger_instance(self):
        """get_logger should return a Logger instance."""
        from backend.utils.logging import get_logger

        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_logger_has_correct_name(self):
        """Logger name should match the passed name."""
        from backend.utils.logging import get_logger

        logger = get_logger("my.custom.module")
        assert logger.name == "my.custom.module"

    def test_logger_has_rich_handler(self):
        """Logger should have a RichHandler attached."""
        from backend.utils.logging import get_logger

        logger = get_logger("test_handler_module")
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "RichHandler" in handler_types

    def test_logger_level_is_info(self):
        """Logger level should be set to INFO."""
        from backend.utils.logging import get_logger

        logger = get_logger("test_level_module")
        assert logger.level == logging.INFO

    def test_same_name_returns_same_logger(self):
        """get_logger with same name should return same instance."""
        from backend.utils.logging import get_logger

        logger1 = get_logger("singleton_test")
        logger2 = get_logger("singleton_test")
        assert logger1 is logger2

    def test_different_names_return_different_loggers(self):
        """Different names should return different logger instances."""
        from backend.utils.logging import get_logger

        logger1 = get_logger("module_a")
        logger2 = get_logger("module_b")
        assert logger1 is not logger2

    def test_logger_does_not_propagate(self):
        """Logger should have propagate=False to avoid double logging."""
        from backend.utils.logging import get_logger

        logger = get_logger("test_propagate_module")
        assert logger.propagate is False

    def test_console_stderr_is_set(self):
        """Console should be configured for stderr."""
        from backend.utils.logging import console

        assert console.stderr is True


class TestDefaultLogger:
    """Tests for the default application logger."""

    def test_default_logger_exists(self):
        """Default 'aura' logger should be available."""
        from backend.utils.logging import log

        assert isinstance(log, logging.Logger)
        assert log.name == "aura"

    def test_default_logger_configured(self):
        """Default logger should be configured with handlers."""
        from backend.utils.logging import log

        assert len(log.handlers) > 0
