"""Зависимости FastAPI: JWT, текущий пользователь, проверка ролей."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from supabase import Client

from app.core.config import Settings, get_settings
from app.core.db_utils import execute_supabase
from app.core.security import decode_access_token
from app.core.supabase import get_supabase_client
from app.models.schemas import CurrentUser, UserRole

TABLE_USERS = "users"
TABLE_EMPLOYEES = "employees"

_bearer_scheme = HTTPBearer(auto_error=False)


def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    settings: Settings,
) -> str | None:
    """Извлекает JWT из заголовка Authorization или cookie."""
    if credentials and credentials.credentials:
        return credentials.credentials
    return request.cookies.get(settings.access_token_cookie_name)


def _clear_auth_cookie(response: Response, settings: Settings) -> None:
    """Удаляет cookie с access-токеном."""
    response.delete_cookie(
        key=settings.access_token_cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


def _load_user_row(supabase: Client, user_id: UUID) -> dict[str, Any] | None:
    """Загружает строку пользователя из БД по UUID."""
    try:
        response = execute_supabase(
            lambda: supabase.table(TABLE_USERS)
            .select("id, employee_id, warehouse_id, login, role, employees(full_name)")
            .eq("id", str(user_id))
            .limit(1)
            .execute()
        )
    except HTTPException:
        return None

    if response is None:
        return None

    data = getattr(response, "data", None)
    if not data:
        return None
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def _row_to_current_user(row: dict[str, Any]) -> CurrentUser:
    """Преобразует строку БД в модель CurrentUser."""
    employee = row.get("employees") or {}
    return CurrentUser(
        id=UUID(str(row["id"])),
        login=row["login"],
        employee_id=UUID(str(row["employee_id"])) if row.get("employee_id") else None,
        warehouse_id=UUID(str(row["warehouse_id"])) if row.get("warehouse_id") else None,
        role=row["role"],
        employee_full_name=employee.get("full_name"),
    )


def get_current_user(
    request: Request,
    response: Response,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> CurrentUser:
    """Извлекает JWT из заголовка Authorization или cookie, возвращает пользователя."""
    token = _extract_token(request, credentials, settings)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется аутентификация",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(token)
        user_id = UUID(str(payload["sub"]))
    except (JWTError, ValueError, KeyError) as exc:
        _clear_auth_cookie(response, settings)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или просроченный токен",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    row = _load_user_row(supabase, user_id)
    if row is None:
        _clear_auth_cookie(response, settings)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _row_to_current_user(row)


def get_current_user_optional(
    request: Request,
    response: Response,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> CurrentUser | None:
    """Возвращает пользователя или None, если токен отсутствует/невалиден."""
    token = _extract_token(request, credentials, settings)
    if not token:
        return None

    try:
        payload = decode_access_token(token)
        user_id = UUID(str(payload["sub"]))
        row = _load_user_row(supabase, user_id)
        if row is None:
            _clear_auth_cookie(response, settings)
            return None
        return _row_to_current_user(row)
    except (JWTError, ValueError, KeyError):
        _clear_auth_cookie(response, settings)
        return None


def require_roles(*allowed_roles: UserRole) -> Callable[..., CurrentUser]:
    """Фабрика зависимостей: разрешает доступ только указанным ролям."""

    def _check_role(
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        """Проверяет роль текущего пользователя против разрешённого списка."""
        if current_user.role not in {role.value for role in allowed_roles}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения операции",
            )
        return current_user

    return _check_role


# Алиас по ТЗ
check_role = require_roles

# Удобные алиасы для частых проверок (строго одна роль)
require_admin_only = require_roles(UserRole.ADMIN)
require_master_only = require_roles(UserRole.MASTER)
require_clerk_only = require_roles(UserRole.CLERK)

# Комбинированные (операционные)
require_clerk_or_master = require_roles(UserRole.CLERK, UserRole.MASTER)
require_send_to_cmms = require_clerk_or_master
require_view_cmms_repair = require_roles(UserRole.CLERK, UserRole.MASTER, UserRole.ADMIN)
require_master_or_admin = require_roles(UserRole.MASTER, UserRole.ADMIN)
require_report_access = require_roles(UserRole.MASTER, UserRole.CLERK, UserRole.ADMIN)
require_authenticated = get_current_user
