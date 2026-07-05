"""Общие вспомогательные функции приложения."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID


def normalize_join(value: Any) -> dict[str, Any]:
    """Приводит вложенный объект Supabase (dict или list) к одному словарю."""
    if value is None:
        return {}
    if isinstance(value, list):
        return value[0] if value else {}
    return value if isinstance(value, dict) else {}


def to_json_value(value: Any) -> Any:
    """Рекурсивно приводит UUID и даты к строкам для JSON-ответов."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: to_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_json_value(item) for item in value]
    return value
