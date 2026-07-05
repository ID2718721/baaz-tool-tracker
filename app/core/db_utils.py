"""Утилиты работы с Supabase/PostgREST и маппинг ошибок БД в HTTP."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from fastapi import HTTPException, status
from postgrest.base_request_builder import APIResponse
from postgrest.exceptions import APIError

T = TypeVar("T")


def supabase_error_to_http(exc: APIError) -> HTTPException:
    """Преобразует ошибку PostgREST/PostgreSQL в HTTP-ответ."""
    detail = exc.message or exc.details or str(exc)
    if exc.hint:
        detail = f"{detail} ({exc.hint})"

    db_error_codes = {
        "23503",
        "23505",
        "23514",
        "23502",
        "P0001",
        "check_violation",
        "foreign_key_violation",
        "unique_violation",
    }
    code = str(exc.code or "")
    is_client_error = (
        any(code.startswith(prefix) for prefix in db_error_codes)
        or code.startswith("23")
        or "violates" in detail.lower()
        or "limit" in detail.lower()
        or "лимит" in detail.lower()
    )

    if code == "23503" or "foreign_key" in detail.lower():
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    if is_client_error:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
    )


def execute_supabase(operation: Callable[[], APIResponse[T]]) -> APIResponse[T]:
    """Выполняет операцию Supabase с перехватом APIError."""
    try:
        return operation()
    except APIError as exc:
        raise supabase_error_to_http(exc) from exc
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="База данных недоступна. Проверьте интернет и настройки Supabase.",
        ) from exc


def first_row(
    response: APIResponse[Any],
    *,
    detail: str = "Запись не найдена",
    status_code: int = status.HTTP_404_NOT_FOUND,
) -> dict[str, Any]:
    """Возвращает первую строку из ответа Supabase (без .single())."""
    data = response.data
    if not data:
        raise HTTPException(status_code=status_code, detail=detail)
    if isinstance(data, list):
        if not data:
            raise HTTPException(status_code=status_code, detail=detail)
        return data[0]
    if isinstance(data, dict):
        return data
    raise HTTPException(status_code=status_code, detail=detail)
