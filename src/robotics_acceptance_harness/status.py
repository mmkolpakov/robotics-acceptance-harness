from __future__ import annotations

from collections.abc import Collection

_STATUS_PRIORITY = {
    "passed": 0,
    "skipped": 1,
    "cancelled": 2,
    "incomplete": 3,
    "failed": 4,
    "error": 5,
}


def worst_status(statuses: Collection[str], *, collapse_cancelled: bool = False) -> str:
    status = max(
        statuses,
        key=lambda item: (_STATUS_PRIORITY.get(item, len(_STATUS_PRIORITY)), item),
        default="passed",
    )
    return "incomplete" if collapse_cancelled and status == "cancelled" else status
