from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from supabase import Client

from app.core.config import Settings, get_settings
from app.core.db_utils import execute_supabase
from app.core.security import create_access_token, verify_password
from app.core.supabase import get_supabase_client
from app.models.schemas import CurrentUser, LoginRequest, LoginResponse, UserRole

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

TABLE_USERS = "tms_users"


def _set_auth_cookie(response: RedirectResponse | JSONResponse, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.access_token_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
    )


def _clear_auth_cookie(response: RedirectResponse | JSONResponse, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.access_token_cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


def _build_current_user(row: dict) -> CurrentUser:
    employee = row.get("tms_employees") or {}
    return CurrentUser(
        id=UUID(str(row["id"])),
        login=row["login"],
        employee_id=UUID(str(row["employee_id"])) if row.get("employee_id") else None,
        warehouse_id=UUID(str(row["warehouse_id"])) if row.get("warehouse_id") else None,
        role=UserRole(row["role"]),
        employee_full_name=employee.get("full_name"),
    )


def _authenticate_user(
    supabase: Client,
    login: str,
    password: str,
) -> tuple[dict, CurrentUser]:
    """Проверка учётной записи в tms_users по полям login и password_hash."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_USERS)
        .select("id, employee_id, warehouse_id, login, password_hash, role, created_at, tms_employees(full_name)")
        .eq("login", login)
        .limit(1)
        .execute()
    )
    data = response.data
    if not data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )
    row = data[0] if isinstance(data, list) else data

    password_hash = row.get("password_hash")
    if not password_hash or not verify_password(password, password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    return row, _build_current_user(row)


def _issue_token(row: dict) -> str:
    return create_access_token(
        user_id=UUID(str(row["id"])),
        role=row["role"],
        warehouse_id=UUID(str(row["warehouse_id"])) if row.get("warehouse_id") else None,
    )


def _login_error_redirect(detail: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"/login?error={quote(detail, safe='')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/login", response_model=None)
async def login_form(
    supabase: Annotated[Client, Depends(get_supabase_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> RedirectResponse:
    """
    Вход через HTML-форму (OAuth2: поле username = login в БД).
    JWT кладётся в HttpOnly cookie, редирект на /.
    """
    login = form_data.username.strip()
    password = form_data.password

    if not login or not password:
        return _login_error_redirect("Укажите логин и пароль")

    try:
        row, _user = _authenticate_user(supabase, login, password)
    except HTTPException as exc:
        return _login_error_redirect(str(exc.detail))

    token = _issue_token(row)
    redirect = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    _set_auth_cookie(redirect, token, settings)
    return redirect


@router.post("/login/json", response_model=None)
async def login_json(
    body: LoginRequest,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    """JSON-вариант входа для API-клиентов."""
    row, user = _authenticate_user(supabase, body.login.strip(), body.password)
    token = _issue_token(row)

    response = JSONResponse(
        content=LoginResponse(access_token=token, user=user).model_dump(mode="json")
    )
    _set_auth_cookie(response, token, settings)
    return response


@router.post("/logout", response_model=None)
def logout(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse | RedirectResponse:
    """Удаляет cookie с токеном. Form-запрос — редирект на /login."""
    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    is_html = "text/html" in accept or content_type.startswith("application/x-www-form-urlencoded")

    if is_html:
        redirect = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        _clear_auth_cookie(redirect, settings)
        return redirect

    response = JSONResponse(content={"ok": True, "detail": "Выход выполнен"})
    _clear_auth_cookie(response, settings)
    return response
