"""Tests for configuration."""

import pytest
from app.config import get_settings, Settings


def test_settings_singleton():
    """Test that settings is a singleton."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_default_settings():
    """Test default setting values."""
    s = Settings()
    assert s.app_name == "Accountia AI Accountant"
    assert s.version == "1.0.0"
    assert s.port == 8000
    assert s.max_period_days == 365


def test_get_platform_db_name():
    """Test platform DB name extraction from URI."""
    s = Settings()
    db_name = s.get_platform_db_name()
    # Should extract DB name from URI (last segment after /)
    assert db_name is not None
    assert len(db_name) > 0
