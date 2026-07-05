"""Эндпоинты CRUD инструментов и внутренней выдачи/возврата."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.api.deps import get_current_user, require_clerk_only, require_clerk_or_master, require_master_only
from app.core.db_utils import execute_supabase, first_row
from app.core.supabase import get_supabase_client
from app.models.schemas import (
    CurrentUser,
    InternalIssueRequest,
    InternalIssueResponse,
    InternalReturnRequest,
    InternalReturnResponse,
    RequisitionLineStatus,
    RequisitionStatus,
    ToolCreate,
    ToolRead,
    ToolStatus,
    ToolUpdate,
    UserRole,
)

router = APIRouter(prefix="/tools", tags=["tools"])

TABLE_TOOLS = "tms_tools"
TABLE_REQUISITIONS = "tms_requisitions"
TABLE_REQUISITION_LINES = "tms_requisition_lines"
TABLE_EMPLOYEES = "tms_employees"

RETURN_RESULT_STATUSES = frozenset(
    {ToolStatus.AVAILABLE.value, ToolStatus.MAINTENANCE.value, ToolStatus.SCRAPPED.value}
)


def _validate_return_status(result_status: ToolStatus) -> str:
    """Проверяет допустимый статус инструмента после возврата."""
    status_value = result_status.value if hasattr(result_status, "value") else str(result_status)
    if status_value not in RETURN_RESULT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="result_status должен быть: available, maintenance или scrapped",
        )
    return status_value


def _parse_tool_row(row: dict[str, Any]) -> ToolRead:
    """Преобразует строку Supabase в Pydantic-модель ToolRead."""
    return ToolRead.model_validate(row)


def _fetch_tool(supabase: Client, tool_id: UUID) -> dict[str, Any]:
    """Загружает одну запись tms_tools по id."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .select("*")
        .eq("id", str(tool_id))
        .limit(1)
        .execute()
    )
    return first_row(response, detail="Инструмент не найден")


def _fetch_employee(supabase: Client, employee_id: UUID) -> dict[str, Any]:
    """Загружает сотрудника tms_employees по id."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_EMPLOYEES)
        .select("*")
        .eq("id", str(employee_id))
        .limit(1)
        .execute()
    )
    return first_row(response, detail="Сотрудник не найден")


# ---------------------------------------------------------------------------
# Внутренняя выдача / возврат (до маршрутов с path-параметрами)
# ---------------------------------------------------------------------------


def _apply_clerk_warehouse_filter(
    query,
    current_user: CurrentUser,
    warehouse_id: UUID | None,
):
    """Кладовщик видит только инструменты своего склада."""
    if current_user.role == UserRole.CLERK.value:
        if not current_user.warehouse_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Кладовщику не назначен склад",
            )
        if warehouse_id and warehouse_id != current_user.warehouse_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Доступ к инструментам другого склада запрещён",
            )
        return query.eq("warehouse_id", str(current_user.warehouse_id))
    if warehouse_id is not None:
        return query.eq("warehouse_id", str(warehouse_id))
    return query


@router.post(
    "/internal/issue",
    response_model=InternalIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
def internal_issue(
    payload: InternalIssueRequest,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(require_clerk_only)],
) -> InternalIssueResponse:
    """Внутренняя выдача: заявка + строка + статус in_use (schema.sql)."""
    tool = _fetch_tool(supabase, payload.tool_id)
    if current_user.role == UserRole.CLERK.value and current_user.warehouse_id:
        if str(tool["warehouse_id"]) != str(current_user.warehouse_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нельзя выдать инструмент с другого склада",
            )

    if tool["status"] != ToolStatus.AVAILABLE.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя выдать инструмент: статус не «Доступен»",
        )

    employee = _fetch_employee(supabase, payload.employee_id)

    if payload.issued_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="issued_by должен совпадать с текущим пользователем",
        )

    warehouse_id = tool["warehouse_id"]
    now = datetime.now(tz=UTC)

    requisition_data = {
        "client_reference_id": str(uuid4()),
        "warehouse_id": warehouse_id,
        "status": RequisitionStatus.ISSUED.value,
        "technician_name": employee["full_name"],
    }

    requisition_response = execute_supabase(
        lambda: supabase.table(TABLE_REQUISITIONS)
        .insert(requisition_data)
        .select("id")
        .execute()
    )
    requisition_id = first_row(requisition_response, detail="Не удалось создать заявку")["id"]

    line_data = {
        "requisition_id": requisition_id,
        "line_client_id": str(uuid4()),
        "catalog_item_id": str(tool["type_id"]) if tool.get("type_id") else None,
        "tool_id": str(payload.tool_id),
        "status": RequisitionLineStatus.ISSUED.value,
    }

    line_response = execute_supabase(
        lambda: supabase.table(TABLE_REQUISITION_LINES)
        .insert(line_data)
        .select("id")
        .execute()
    )
    line_id = first_row(line_response, detail="Не удалось создать строку заявки")["id"]

    tool_response = execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .update({"status": ToolStatus.IN_USE.value})
        .eq("id", str(payload.tool_id))
        .select("*")
        .execute()
    )
    tool_row = first_row(tool_response, detail="Не удалось обновить инструмент")

    return InternalIssueResponse(
        requisition_id=UUID(str(requisition_id)),
        requisition_line_id=UUID(str(line_id)),
        issuance_log_id=UUID(str(line_id)),
        tool=_parse_tool_row(tool_row),
        issued_at=now,
    )


@router.post("/internal/return", response_model=InternalReturnResponse)
def internal_return(
    payload: InternalReturnRequest,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(require_clerk_only)],
) -> InternalReturnResponse:
    """Приём инструмента: обновление wear_count, фиксация condition_on_return."""
    tool = _fetch_tool(supabase, payload.tool_id)
    if current_user.role == UserRole.CLERK.value and current_user.warehouse_id:
        if str(tool["warehouse_id"]) != str(current_user.warehouse_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нельзя принять инструмент с другого склада",
            )

    line_query = (
        supabase.table(TABLE_REQUISITION_LINES)
        .select("*")
        .eq("tool_id", str(payload.tool_id))
        .eq("status", RequisitionLineStatus.ISSUED.value)
    )

    if payload.requisition_line_id is not None:
        line_query = line_query.eq("id", str(payload.requisition_line_id))
    if payload.requisition_id is not None:
        line_query = line_query.eq("requisition_id", str(payload.requisition_id))

    line_response = execute_supabase(lambda: line_query.limit(1).execute())
    if not line_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Активная строка выдачи для инструмента не найдена",
        )

    line = line_response.data[0]
    requisition_id = line["requisition_id"]
    now = datetime.now(tz=UTC)
    new_wear_count = payload.wear_count if payload.wear_count is not None else int(tool["wear_count"]) + 1
    result_status = _validate_return_status(payload.result_status)
    comment = (payload.condition_on_return or "").strip() or None

    execute_supabase(
        lambda: supabase.table(TABLE_REQUISITION_LINES)
        .update(
            {
                "status": RequisitionLineStatus.RETURNED.value,
                "condition_on_return": comment,
            }
        )
        .eq("id", line["id"])
        .execute()
    )

    execute_supabase(
        lambda: supabase.table(TABLE_REQUISITIONS)
        .update({"status": RequisitionStatus.RETURNED.value})
        .eq("id", requisition_id)
        .execute()
    )

    execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .update(
            {
                "wear_count": new_wear_count,
                "status": result_status,
                **({"last_check": date.today().isoformat()} if result_status == ToolStatus.SCRAPPED.value else {}),
            }
        )
        .eq("id", str(payload.tool_id))
        .execute()
    )

    tool_response = execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .select("*")
        .eq("id", str(payload.tool_id))
        .execute()
    )
    tool_row = first_row(tool_response, detail="Инструмент не найден")

    return InternalReturnResponse(
        requisition_id=UUID(str(requisition_id)),
        requisition_line_id=UUID(str(line["id"])),
        issuance_log_id=UUID(str(line["id"])),
        tool=_parse_tool_row(tool_row),
        returned_at=now,
        condition_on_return=comment,
    )


# ---------------------------------------------------------------------------
# CRUD tms_tools
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ToolRead])
def list_tools(
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    warehouse_id: UUID | None = Query(default=None),
    type_id: UUID | None = Query(default=None),
    status_filter: ToolStatus | None = Query(default=None, alias="status"),
) -> list[ToolRead]:
    """Список инструментов с фильтрацией по складу, типу и статусу."""
    query = supabase.table(TABLE_TOOLS).select("*")
    query = _apply_clerk_warehouse_filter(query, current_user, warehouse_id)
    if type_id is not None:
        query = query.eq("type_id", str(type_id))
    if status_filter is not None:
        query = query.eq("status", status_filter.value)

    response = execute_supabase(lambda: query.order("inventory_number").execute())
    return [_parse_tool_row(row) for row in response.data or []]


@router.post("/", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
def create_tool(
    payload: ToolCreate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_clerk_or_master)],
) -> ToolRead:
    """Создание нового экземпляра инструмента."""
    insert_data = payload.model_dump(mode="json")
    response = execute_supabase(
        lambda: supabase.table(TABLE_TOOLS).insert(insert_data).select("*").execute()
    )
    return _parse_tool_row(first_row(response, detail="Не удалось создать инструмент", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR))


@router.get("/{tool_id}", response_model=ToolRead)
def get_tool(
    tool_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ToolRead:
    """Получение инструмента по id с проверкой склада для кладовщика."""
    tool = _fetch_tool(supabase, tool_id)
    if current_user.role == UserRole.CLERK.value and current_user.warehouse_id:
        if str(tool["warehouse_id"]) != str(current_user.warehouse_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Доступ к инструменту другого склада запрещён",
            )
    return _parse_tool_row(tool)


@router.put("/{tool_id}", response_model=ToolRead)
def update_tool(
    tool_id: UUID,
    payload: ToolUpdate,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_clerk_or_master)],
) -> ToolRead:
    """Обновление полей инструмента."""
    update_data = payload.model_dump(mode="json", exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет данных для обновления")

    _fetch_tool(supabase, tool_id)

    response = execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .update(update_data)
        .eq("id", str(tool_id))
        .select("*")
        .execute()
    )
    return _parse_tool_row(first_row(response, detail="Не удалось обновить инструмент"))


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool(
    tool_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_only)],
) -> None:
    """Удаление инструмента (только мастер)."""
    _fetch_tool(supabase, tool_id)
    execute_supabase(lambda: supabase.table(TABLE_TOOLS).delete().eq("id", str(tool_id)).execute())
