"""Unit tests for the auto-close decision rule (pure, boundary-focused).

This rule triggers REAL order execution, so the threshold behaviour is pinned
down exhaustively, including the guards against firing when disarmed or on a
missing / non-positive target.
"""

from __future__ import annotations

import pytest

from use_cases.autoclose import should_autoclose


@pytest.mark.parametrize(
    "profit,target,armed,expected",
    [
        # Disarmed never fires, even way over target.
        (1000.0, 100.0, False, False),
        # Missing / non-positive target never fires (fat-finger guard).
        (1000.0, None, True, False),
        (1000.0, 0.0, True, False),
        (1000.0, -50.0, True, False),
        # Armed + positive target: fires at/above, not below.
        (150.0, 100.0, True, True),
        (100.0, 100.0, True, True),  # inclusive boundary
        (99.99, 100.0, True, False),
        (0.0, 100.0, True, False),
        (-200.0, 100.0, True, False),  # losing trade never auto-closes on a profit target
    ],
)
def test_should_autoclose(profit: float, target: float | None, armed: bool, expected: bool) -> None:
    assert should_autoclose(profit, target, armed) is expected
