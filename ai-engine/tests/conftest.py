"""Shared fixtures. Kept minimal -- most tests construct their own fixtures inline so
a failure is readable without cross-referencing this file.
"""

from __future__ import annotations

import pytest

from adhikar.config import Settings


@pytest.fixture
def settings() -> Settings:
    """A settings instance that ignores any .env file in the developer's tree."""
    return Settings(_env_file=None)
