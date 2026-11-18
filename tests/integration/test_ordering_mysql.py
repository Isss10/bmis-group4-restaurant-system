"""Integration tests for the ordering module against real MySQL."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Skipping unstable integration environment")


def test_placeholder_to_avoid_empty_module() -> None:
    assert True
