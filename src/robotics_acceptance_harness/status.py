from __future__ import annotations

from collections.abc import Collection

_SEVERITY = ("passed", "cancelled", "incomplete", "failed", "error")


def worst_status(statuses: Collection[str], *, collapse_cancelled: bool = False) -> str:
    status = max(statuses, key=_SEVERITY.index, default="passed")
    return "incomplete" if collapse_cancelled and status == "cancelled" else status
