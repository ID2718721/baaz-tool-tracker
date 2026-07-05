from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field
from supabase import Client

from app.api.deps import require_master_or_admin
from app.core.db_utils import execute_supabase, first_row
from app.core.supabase import get_supabase_client
from app.models.schemas import CurrentUser, TMSBaseModel

router = APIRouter(prefix="/master", tags=["master"])


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


class ToolCategoryCreate(TMSBaseModel):
    name: str = Field(min_length=1, max_length=255)


class ToolCategoryUpdate(TMSBaseModel):
    name: str = Field(min_length=1, max_length=255)


class ToolTypeCreate(TMSBaseModel):
    model_name: str = Field(min_length=1, max_length=255)
    category_id: UUID
    min_stock: int = Field(default=5, ge=0)


class ToolTypeUpdate(TMSBaseModel):
    model_name: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: UUID | None = None
    min_stock: int | None = Field(default=None, ge=0)


@router.post("/locations", status_code=status.HTTP_201_CREATED)
def create_location(
    payload: LocationCreate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> dict[str, Any]:
    """Создание цеха/участка."""
    response = execute_supabase(
        lambda: supabase.table("tms_locations")
        .insert({"name": payload.name})
        .select("*")
        .execute()
    )
    return first_row(response, detail="Не удалось создать цех/участок", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.put("/locations/{location_id}")
def update_location(
    location_id: UUID,
    payload: LocationUpdate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> dict[str, Any]:
    """Обновление названия цеха/участка."""
    response = execute_supabase(
        lambda: supabase.table("tms_locations")
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
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> None:
    """Удаление цеха/участка."""
    execute_supabase(lambda: supabase.table("tms_locations").delete().eq("id", str(location_id)).execute())


@router.post("/warehouses", status_code=status.HTTP_201_CREATED)
def create_warehouse(
    payload: WarehouseCreate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> dict[str, Any]:
    """Создание склада на указанном цехе."""
    insert_data = {
        "name": payload.name,
        "location_id": str(payload.location_id),
    }
    response = execute_supabase(
        lambda: supabase.table("tms_warehouses")
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
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> dict[str, Any]:
    """Обновление данных склада."""
    update_data = payload.model_dump(mode="json", exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет данных для обновления")
    response = execute_supabase(
        lambda: supabase.table("tms_warehouses")
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
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> None:
    """Удаление склада."""
    execute_supabase(lambda: supabase.table("tms_warehouses").delete().eq("id", str(warehouse_id)).execute())


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(
    payload: ToolCategoryCreate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> dict[str, Any]:
    """Создание категории инструментов."""
    response = execute_supabase(
        lambda: supabase.table("tms_tool_categories")
        .insert({"name": payload.name})
        .select("*")
        .execute()
    )
    return first_row(response, detail="Не удалось создать категорию", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.put("/categories/{category_id}")
def update_category(
    category_id: UUID,
    payload: ToolCategoryUpdate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> dict[str, Any]:
    """Обновление категории инструментов."""
    response = execute_supabase(
        lambda: supabase.table("tms_tool_categories")
        .update({"name": payload.name})
        .eq("id", str(category_id))
        .select("*")
        .execute()
    )
    return first_row(response, detail="Категория не найдена")


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> None:
    """Удаление категории инструментов."""
    execute_supabase(lambda: supabase.table("tms_tool_categories").delete().eq("id", str(category_id)).execute())


@router.post("/tool-types", status_code=status.HTTP_201_CREATED)
def create_tool_type(
    payload: ToolTypeCreate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> dict[str, Any]:
    """Создание типа инструмента."""
    response = execute_supabase(
        lambda: supabase.table("tms_tool_types")
        .insert(payload.model_dump(mode="json"))
        .select("*")
        .execute()
    )
    return first_row(response, detail="Не удалось создать тип инструмента", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.put("/tool-types/{tool_type_id}")
def update_tool_type(
    tool_type_id: UUID,
    payload: ToolTypeUpdate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> dict[str, Any]:
    """Обновление типа инструмента."""
    update_data = payload.model_dump(mode="json", exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет данных для обновления")
    response = execute_supabase(
        lambda: supabase.table("tms_tool_types")
        .update(update_data)
        .eq("id", str(tool_type_id))
        .select("*")
        .execute()
    )
    return first_row(response, detail="Тип инструмента не найден")


@router.delete("/tool-types/{tool_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool_type(
    tool_type_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> None:
    """Удаление типа инструмента."""
    execute_supabase(lambda: supabase.table("tms_tool_types").delete().eq("id", str(tool_type_id)).execute())
