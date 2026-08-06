from __future__ import annotations

from collections.abc import Collection

_STATUS_PRIORITY = {
    "passed": 0,
    "skipped": 0,
    "cancelled": 1,
    "incomplete": 2,
    "failed": 3,
    "error": 4,
}


def worst_status(statuses: Collection[str], *, collapse_cancelled: bool = False) -> str:
    status = max(
        statuses,
        key=lambda item: _STATUS_PRIORITY.get(item, 5),
        default="passed",
    )
    return "incomplete" if collapse_cancelled and status == "cancelled" else status
