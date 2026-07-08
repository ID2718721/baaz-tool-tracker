"""Производный статус заявки по статусам строк (ISS-API-5 и UI кладовщика)."""

from __future__ import annotations

from typing import Any


def derive_requisition_status(lines: list[dict[str, Any]], cancelled_at: Any = None) -> str:
    """Единая логика для ISS-API-5 и _sync_requisition_status."""
    if cancelled_at:
        return "cancelled"
    if not lines:
        return "new"

    statuses = [row.get("status") or "pending" for row in lines]
    if all(s == "returned" for s in statuses):
        return "returned"
    if all(s == "issued" for s in statuses):
        return "issued"
    if all(s == "reserved" for s in statuses):
        return "ready_for_issue"
    if any(s == "reserved" for s in statuses):
        return "partially_reserved"
    if any(s == "issued" for s in statuses):
        return "issued"
    if any(s == "returned" for s in statuses):
        return "partially_returned"
    return "new"
