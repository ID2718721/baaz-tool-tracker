from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field, field_validator
from supabase import Client

from app.api.deps import require_admin_only
from app.core.db_utils import execute_supabase, first_row
from app.core.security import hash_password
from app.core.supabase import get_supabase_client
from app.models.schemas import CurrentUser, TMSBaseModel, UserRole

router = APIRouter(prefix="/admin", tags=["admin"])

TABLE_USERS = "users"
TABLE_LOCATIONS = "locations"
TABLE_WAREHOUSES = "warehouses"


class AdminUserCreate(TMSBaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    role: UserRole
    employee_id: UUID
    warehouse_id: UUID | None = None

    @field_validator("login", "password", mode="before")
    @classmethod
    def strip_required_fields(cls, value: str) -> str:
        """Обрезает пробелы у обязательных строк при создании пользователя."""
        if isinstance(value, str):
            return value.strip()
        return value


class AdminUserUpdate(TMSBaseModel):
    login: str | None = Field(default=None, min_length=1, max_length=64)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    role: UserRole | None = None
    employee_id: UUID | None = None
    warehouse_id: UUID | None = None

    @field_validator("login", mode="before")
    @classmethod
    def strip_login(cls, value: str | None) -> str | None:
        """Обрезает логин при обновлении; пустая строка → None."""
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("password", mode="before")
    @classmethod
    def normalize_password(cls, value: str | None) -> str | None:
        """Пустой пароль при редактировании = не менять."""
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class LocationCreate(TMSBaseModel):
    name: str = Field(min_length=1, max_length=255)


class LocationUpdate(TMSBaseModel):
    name: str = Field(min_length=1, max_length=255)


class WarehouseCreate(TMSBaseModel):
    name: str = Field(min_length=1, max_length=255)
    location_id: UUID


class WarehouseUpdate(TMSBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    location_id: UUID | None = None


def _role_value(role: UserRole | str) -> str:
    """Возвращает строковое значение роли (UserRole или str)."""
    return role.value if hasattr(role, "value") else str(role)


def _validate_clerk_warehouse(role: str, warehouse_id: UUID | None) -> None:
    """Проверяет, что у кладовщика указан склад."""
    if role == UserRole.CLERK.value and not warehouse_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для кладовщика необходимо указать склад",
        )


def _fetch_user_by_login(supabase: Client, login: str) -> dict[str, Any] | None:
    """Ищет пользователя users по login."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_USERS)
        .select("id, login")
        .eq("login", login)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


@router.get("/users")
def list_users(
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> list[dict[str, Any]]:
    """Список учётных записей с сотрудником и складом."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_USERS)
        .select("id, login, role, employee_id, warehouse_id, created_at, employees(full_name), warehouses(name)")
        .order("login")
        .execute()
    )
    return response.data or []


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> dict[str, Any]:
    """Создание учётной записи с хешированием пароля."""
    login = payload.login.strip()
    password = payload.password.strip()

    if not login:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Логин не может быть пустым")
    if not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль обязателен при создании пользователя",
        )
    if len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль должен содержать минимум 6 символов",
        )

    if _fetch_user_by_login(supabase, login):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Этот логин уже занят")

    role_value = _role_value(payload.role)
    _validate_clerk_warehouse(role_value, payload.warehouse_id)

    insert_data = {
        "login": login,
        "password_hash": hash_password(password),
        "role": role_value,
        "employee_id": str(payload.employee_id),
        "warehouse_id": str(payload.warehouse_id) if payload.warehouse_id else None,
    }

    response = execute_supabase(
        lambda: supabase.table(TABLE_USERS).insert(insert_data).select("id, login, role, employee_id, warehouse_id").execute()
    )
    return first_row(response, detail="Не удалось создать пользователя", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.put("/users/{user_id}")
def update_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> dict[str, Any]:
    """Частичное обновление учётной записи."""
    existing_resp = execute_supabase(
        lambda: supabase.table(TABLE_USERS).select("*").eq("id", str(user_id)).execute()
    )
    existing = first_row(existing_resp, detail="Пользователь не найден")

    new_role = _role_value(payload.role) if payload.role is not None else existing["role"]
    new_employee_id = str(payload.employee_id) if payload.employee_id is not None else existing.get("employee_id")
    new_warehouse_id = (
        str(payload.warehouse_id)
        if payload.warehouse_id is not None
        else existing.get("warehouse_id")
    )

    if not new_employee_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Необходимо указать сотрудника")

    _validate_clerk_warehouse(
        new_role,
        UUID(str(new_warehouse_id)) if new_warehouse_id else None,
    )

    update_data: dict[str, Any] = {}
    if payload.login is not None:
        new_login = payload.login.strip()
        if not new_login:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Логин не может быть пустым")
        existing_login = _fetch_user_by_login(supabase, new_login)
        if existing_login and str(existing_login["id"]) != str(user_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Этот логин уже занят")
        update_data["login"] = new_login
    if payload.password is not None:
        update_data["password_hash"] = hash_password(payload.password)
    if payload.role is not None:
        update_data["role"] = new_role
    if payload.employee_id is not None:
        update_data["employee_id"] = str(payload.employee_id)
    if payload.warehouse_id is not None:
        update_data["warehouse_id"] = str(payload.warehouse_id) if payload.warehouse_id else None

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет данных для обновления")

    response = execute_supabase(
        lambda: supabase.table(TABLE_USERS)
        .update(update_data)
        .eq("id", str(user_id))
        .select("id, login, role, employee_id, warehouse_id")
        .execute()
    )
    return first_row(response, detail="Не удалось обновить пользователя")


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(require_admin_only)],
) -> None:
    """Удаление учётной записи (кроме собственной)."""
    if str(current_user.id) == str(user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя удалить собственную учётную запись")
    execute_supabase(lambda: supabase.table(TABLE_USERS).delete().eq("id", str(user_id)).execute())


@router.get("/locations")
def list_locations(
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> list[dict[str, Any]]:
    """Список цехов/участков."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_LOCATIONS).select("id, name").order("name").execute()
    )
    return response.data or []


@router.post("/locations", status_code=status.HTTP_201_CREATED)
def create_location(
    payload: LocationCreate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> dict[str, Any]:
    """Создание цеха/участка."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_LOCATIONS).insert({"name": payload.name}).select("*").execute()
    )
    return first_row(response, detail="Не удалось создать цех/участок", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.put("/locations/{location_id}")
def update_location(
    location_id: UUID,
    payload: LocationUpdate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> dict[str, Any]:
    """Переименование цеха/участка."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_LOCATIONS)
        .update({"name": payload.name})
        .eq("id", str(location_id))
        .select("*")
        .execute()
    )
    return first_row(response, detail="Цех/участок не найден")


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(
    location_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> None:
    """Удаление цеха/участка."""
    execute_supabase(lambda: supabase.table(TABLE_LOCATIONS).delete().eq("id", str(location_id)).execute())


@router.get("/warehouses")
def list_warehouses(
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> list[dict[str, Any]]:
    """Список складов с привязкой к цеху."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_WAREHOUSES)
        .select("id, name, location_id, locations(name)")
        .order("name")
        .execute()
    )
    return response.data or []


@router.post("/warehouses", status_code=status.HTTP_201_CREATED)
def create_warehouse(
    payload: WarehouseCreate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> dict[str, Any]:
    """Создание склада на указанном цехе."""
    insert_data = {
        "name": payload.name,
        "location_id": str(payload.location_id),
    }
    response = execute_supabase(
        lambda: supabase.table(TABLE_WAREHOUSES)
        .insert(insert_data)
        .select("*")
        .execute()
    )
    return first_row(response, detail="Не удалось создать склад", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.put("/warehouses/{warehouse_id}")
def update_warehouse(
    warehouse_id: UUID,
    payload: WarehouseUpdate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> dict[str, Any]:
    """Частичное обновление склада."""
    update_data = payload.model_dump(mode="json", exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет данных для обновления")
    response = execute_supabase(
        lambda: supabase.table(TABLE_WAREHOUSES)
        .update(update_data)
        .eq("id", str(warehouse_id))
        .select("*")
        .execute()
    )
    return first_row(response, detail="Склад не найден")


@router.delete("/warehouses/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_warehouse(
    warehouse_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_admin_only)],
) -> None:
    """Удаление склада."""
    execute_supabase(lambda: supabase.table(TABLE_WAREHOUSES).delete().eq("id", str(warehouse_id)).execute())
