from __future__ import annotations

import pytest

from robotics_acceptance_harness.status import worst_status


@pytest.mark.parametrize(
    ("statuses", "collapse_cancelled", "expected"),
    [
        (set(), False, "passed"),
        ({"passed", "cancelled"}, False, "cancelled"),
        ({"passed", "cancelled"}, True, "incomplete"),
        ({"incomplete", "failed"}, False, "failed"),
        ({"failed", "error"}, False, "error"),
        ({"error", "unknown"}, False, "unknown"),
    ],
)
def test_worst_status(
    statuses: set[str],
    collapse_cancelled: bool,
    expected: str,
) -> None:
    assert worst_status(statuses, collapse_cancelled=collapse_cancelled) == expected
