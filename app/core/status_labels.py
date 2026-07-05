"""Русские подписи статусов для HTML-шаблонов TMS."""

from __future__ import annotations

REQUISITION_STATUS_LABELS: dict[str, str] = {
    "new": "Новая",
    "partially_reserved": "Частично зарезервирована",
    "ready_for_issue": "Готова к выдаче",
    "issued": "Выдана",
    "partially_returned": "Частично возвращена",
    "returned": "Возвращена",
    "cancelled": "Отменена",
}

REQUISITION_LINE_STATUS_LABELS: dict[str, str] = {
    "pending": "Ожидает подбора",
    "reserved": "Зарезервирована",
    "issued": "Выдана",
    "returned": "Возвращена",
}

TOOL_STATUS_LABELS: dict[str, str] = {
    "available": "Доступен",
    "in_use": "В работе",
    "maintenance": "На обслуживании",
    "scrapped": "Списан",
    "pending_repair": "Ожидает передачи в ТОиР",
    "pending_return": "Ожидает приёмки на склад",
}


def requisition_status_label(status: str | None) -> str:
    if not status:
        return REQUISITION_STATUS_LABELS["new"]
    return REQUISITION_STATUS_LABELS.get(status, status)


def requisition_line_status_label(status: str | None) -> str:
    if not status:
        return REQUISITION_LINE_STATUS_LABELS["pending"]
    return REQUISITION_LINE_STATUS_LABELS.get(status, status)


def tool_status_label(status: str | None) -> str:
    if not status:
        return "—"
    return TOOL_STATUS_LABELS.get(status, status)
