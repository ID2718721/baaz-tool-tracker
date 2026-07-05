"""Эндпоинты CRUD инструментов и внутренней выдачи/возврата."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.api.deps import (
    get_current_user,
    require_clerk_only,
    require_clerk_or_master,
    require_master_only,
    require_send_to_cmms,
    require_view_cmms_repair,
)
from app.core.db_utils import execute_supabase, first_row
from app.core.supabase import get_supabase_client
from app.models.schemas import (
    CmmsInventoryRequestDetail,
    CmmsInventoryWorkReport,
    CmmsRepairLinkSnapshot,
    CurrentUser,
    InternalIssueRequest,
    InternalIssueResponse,
    InternalReturnRequest,
    InternalReturnResponse,
    RequisitionLineStatus,
    RequisitionStatus,
    RepairRequestType,
    TMSBaseModel,
    ToolCmmsRepairDetailResponse,
    ToolCreate,
    ToolRead,
    ToolStatus,
    ToolUpdate,
    UserRole,
    CmmsRepairDepartmentItem,
    CmmsRepairDepartmentListResponse,
    InventoryHandoffMode,
)

router = APIRouter(prefix="/tools", tags=["tools"])

TABLE_TOOLS = "tools"
TABLE_REQUISITIONS = "requisitions"
TABLE_REQUISITION_LINES = "requisition_lines"
TABLE_EMPLOYEES = "employees"
TABLE_CMMS_REPAIR_LINKS = "cmms_repair_links"

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
    """Загружает одну запись tools по id."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .select("*")
        .eq("id", str(tool_id))
        .limit(1)
        .execute()
    )
    return first_row(response, detail="Инструмент не найден")


def _fetch_cmms_repair_link(supabase: Client, tool_id: UUID) -> dict[str, Any] | None:
    """Возвращает связь инструмента с заявкой CMMS или None."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_CMMS_REPAIR_LINKS)
        .select("cmms_request_id, cmms_request_number, client_reference_id")
        .eq("tool_id", str(tool_id))
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def _parse_cmms_inventory_request(row: dict[str, Any]) -> CmmsInventoryRequestDetail:
    created_at = row.get("created_at")
    updated_at = row.get("updated_at")
    return CmmsInventoryRequestDetail(
        request_id=UUID(str(row["request_id"])),
        request_number=str(row.get("request_number") or ""),
        inventory_id=UUID(str(row["inventory_id"])),
        status=str(row.get("status") or ""),
        title=row.get("title") or None,
        description=row.get("description") or None,
        type=row.get("type") or None,
        priority=row.get("priority") or None,
        repair_zone=row.get("repair_zone") or None,
        requester_name=row.get("requester_name") or None,
        created_at=datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if created_at
        else None,
        updated_at=datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
        if updated_at
        else None,
    )


def _parse_cmms_work_report(row: dict[str, Any]) -> CmmsInventoryWorkReport:
    duration = row.get("actual_duration_hours")
    return CmmsInventoryWorkReport(
        work_report_id=UUID(str(row["work_report_id"])),
        request_id=UUID(str(row["request_id"])),
        request_number=row.get("request_number") or None,
        work_performed=str(row.get("work_performed") or ""),
        actual_duration_hours=float(duration) if duration is not None else None,
        maintenance_type=row.get("maintenance_type") or None,
        repair_department_name=row.get("repair_department_name") or None,
        technician_full_name=row.get("technician_full_name") or None,
        defects_found=row.get("defects_found") or None,
        notes=row.get("notes") or None,
        created_at=datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00")),
    )


def _reject_duplicate_cmms_send(
    tool: dict[str, Any],
    existing_link: dict[str, Any] | None,
) -> None:
    """Блокирует повторную отправку инструмента в ТОиР."""
    if existing_link:
        request_number = existing_link.get("cmms_request_number") or existing_link.get("cmms_request_id")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Для этого инструмента уже создана заявка в ТОиР"
                f"{f' (№ {request_number})' if request_number else ''}. "
                "Повторная отправка невозможна."
            ),
        )
    if tool["status"] == ToolStatus.MAINTENANCE.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Инструмент уже на обслуживании. Дождитесь завершения текущей заявки в ТОиР.",
        )
    if tool["status"] == ToolStatus.PENDING_REPAIR.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Инструмент уже зарезервирован под заявку в ТОиР.",
        )
    if tool["status"] == ToolStatus.PENDING_RETURN.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Инструмент ожидает приёмки на склад после ремонта.",
        )
    if tool["status"] != ToolStatus.AVAILABLE.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Инструмент недоступен для отправки в ТОиР",
        )


def _fetch_employee(supabase: Client, employee_id: UUID) -> dict[str, Any]:
    """Загружает сотрудника employees по id."""
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
        "kind": "catalog",
        "quantity": 1,
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
# CRUD tools
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


@router.get(
    "/cmms-repair-departments",
    response_model=CmmsRepairDepartmentListResponse,
    summary="Справочник ремонтных отделов CMMS для формы «Отправить в ТОиР»",
)
def list_cmms_repair_departments(
    _: Annotated[CurrentUser, Depends(require_send_to_cmms)],
) -> CmmsRepairDepartmentListResponse:
    from app.core.config import get_settings
    from app.integration.cmms_client import CmmsRepairClientError, create_cmms_repair_client

    settings = get_settings()
    try:
        client = create_cmms_repair_client(settings)
        rows = client.list_repair_departments()
    except CmmsRepairClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    departments = [
        CmmsRepairDepartmentItem(
            repair_department_id=UUID(str(row["repair_department_id"])),
            name=row.get("name") or "—",
            code=row.get("code"),
        )
        for row in rows
    ]
    return CmmsRepairDepartmentListResponse(departments=departments)


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


def _fetch_warehouse_name(supabase: Client, warehouse_id: UUID | str | None) -> str | None:
    if not warehouse_id:
        return None
    response = execute_supabase(
        lambda: supabase.table("warehouses")
        .select("name")
        .eq("id", str(warehouse_id))
        .limit(1)
        .execute()
    )
    row = first_row(response, detail="Склад не найден", status_code=status.HTTP_404_NOT_FOUND)
    return row.get("name")


class SendToCmmsRequest(TMSBaseModel):
    title: str
    description: str | None = None
    request_type: str = "inspection"
    target_repair_department_id: UUID
    inventory_handoff_mode: InventoryHandoffMode = InventoryHandoffMode.DELIVER_TO_DEPARTMENT


@router.post("/{tool_id}/send-to-cmms")
def send_tool_to_cmms(
    tool_id: UUID,
    payload: SendToCmmsRequest,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(require_send_to_cmms)],
) -> dict[str, str]:
    """Контур А: отправить инструмент на ремонт/поверку в CMMS (REP-API-1)."""
    from app.core.config import get_settings
    from app.integration.cmms_client import CmmsRepairClientError, _enum_value, create_cmms_repair_client
    from app.models.schemas import RepairRequestCreate

    tool = _fetch_tool(supabase, tool_id)
    if current_user.role == UserRole.CLERK.value and current_user.warehouse_id:
        if str(tool["warehouse_id"]) != str(current_user.warehouse_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нельзя отправить инструмент с другого склада",
            )
    existing_link = _fetch_cmms_repair_link(supabase, tool_id)
    _reject_duplicate_cmms_send(tool, existing_link)

    if not tool.get("type_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У инструмента не указан тип. Обратитесь к мастеру для заполнения карточки.",
        )

    type_resp = execute_supabase(
        lambda: supabase.table("tool_types")
        .select("model_name, tool_categories(name)")
        .eq("id", str(tool["type_id"]))
        .execute()
    )
    tool_type = first_row(type_resp, detail="Тип инструмента не найден")
    category = tool_type.get("tool_categories") or {}
    if isinstance(category, list):
        category = category[0] if category else {}

    warehouse_name = _fetch_warehouse_name(supabase, tool.get("warehouse_id"))
    handoff_mode = payload.inventory_handoff_mode

    settings = get_settings()
    try:
        client = create_cmms_repair_client(settings)
    except CmmsRepairClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    req_type = RepairRequestType.SERVICE if payload.request_type == "service" else RepairRequestType.INSPECTION
    client_ref = uuid4()
    try:
        result = client.create_repair_request(
            RepairRequestCreate(
                client_reference_id=client_ref,
                tool_id=tool_id,
                tool_name=tool_type.get("model_name") or "Инструмент",
                tool_serial=tool.get("serial_number"),
                tool_type_name=category.get("name"),
                request_type=req_type,
                title=payload.title.strip(),
                description=payload.description,
                target_repair_department_id=payload.target_repair_department_id,
                inventory_handoff_mode=handoff_mode,
                inventory_warehouse_name=warehouse_name,
            )
        )
    except CmmsRepairClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .update({"status": ToolStatus.PENDING_REPAIR.value})
        .eq("id", str(tool_id))
        .execute()
    )
    try:
        execute_supabase(
            lambda: supabase.table(TABLE_CMMS_REPAIR_LINKS)
            .insert(
                {
                    "tool_id": str(tool_id),
                    "cmms_request_id": str(result.request_id),
                    "cmms_request_number": result.request_number,
                    "client_reference_id": str(client_ref),
                    "handoff_mode": _enum_value(handoff_mode),
                    "handoff_status": "pending",
                    "warehouse_name": warehouse_name,
                }
            )
            .execute()
        )
    except HTTPException as exc:
        detail = str(exc.detail)
        if "cmms_repair_links_tool_id_key" in detail or "duplicate key" in detail.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Для этого инструмента уже создана заявка в ТОиР. Повторная отправка невозможна.",
            ) from exc
        raise

    return {
        "request_id": str(result.request_id),
        "request_number": result.request_number,
        "status": result.status,
    }


@router.post("/{tool_id}/handover-to-repair")
def handover_tool_to_repair(
    tool_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(require_send_to_cmms)],
) -> dict[str, str]:
    """Контур А: кладовщик передаёт инструмент в ремонтный отдел (REP-API-2)."""
    from app.core.config import get_settings
    from app.integration.cmms_client import CmmsRepairClientError, create_cmms_repair_client

    tool = _fetch_tool(supabase, tool_id)
    if current_user.role == UserRole.CLERK.value and current_user.warehouse_id:
        if str(tool["warehouse_id"]) != str(current_user.warehouse_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нельзя передать инструмент с другого склада",
            )

    link = _fetch_cmms_repair_link(supabase, tool_id)
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Нет активной заявки ТОиР")

    if link.get("handoff_mode") != InventoryHandoffMode.DELIVER_TO_DEPARTMENT.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для этого инструмента выбран режим «забор отделом», передача кладовщиком не требуется",
        )
    if link.get("handoff_status") == "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Инструмент уже передан в отдел")

    if tool["status"] != ToolStatus.PENDING_REPAIR.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Инструмент не ожидает передачи в ремонт",
        )

    settings = get_settings()
    try:
        client = create_cmms_repair_client(settings)
    except CmmsRepairClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    cmms_request_id = UUID(str(link["cmms_request_id"]))
    inv = client.get_inventory_request_by_inventory_id(tool_id)
    if not inv or inv.get("status") != "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Заявка ТОиР должна быть принята отделом и иметь назначенных исполнителей",
        )

    now = datetime.now(tz=UTC)
    try:
        result = client.confirm_inventory_received(cmms_request_id, tool_id, now)
    except CmmsRepairClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .update({"status": ToolStatus.MAINTENANCE.value})
        .eq("id", str(tool_id))
        .execute()
    )
    execute_supabase(
        lambda: supabase.table(TABLE_CMMS_REPAIR_LINKS)
        .update(
            {
                "handoff_status": "completed",
                "handed_over_at": now.isoformat(),
                "handed_over_by": str(current_user.id),
            }
        )
        .eq("tool_id", str(tool_id))
        .execute()
    )

    return {
        "request_id": str(cmms_request_id),
        "status": str(result.get("status", "in_progress")),
    }


@router.post("/{tool_id}/accept-return-from-repair")
def accept_return_from_repair(
    tool_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(require_clerk_only)],
) -> dict[str, str]:
    """Принять инструмент на склад после завершения ремонта в ТОиР."""
    tool = _fetch_tool(supabase, tool_id)
    if current_user.warehouse_id and str(tool["warehouse_id"]) != str(current_user.warehouse_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя принять инструмент с другого склада",
        )

    if tool["status"] != ToolStatus.PENDING_RETURN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Инструмент не ожидает приёмки на склад",
        )

    link = _fetch_cmms_repair_link(supabase, tool_id)
    now = datetime.now(tz=UTC)

    execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .update({"status": ToolStatus.AVAILABLE.value})
        .eq("id", str(tool_id))
        .execute()
    )
    if link:
        execute_supabase(
            lambda: supabase.table(TABLE_CMMS_REPAIR_LINKS)
            .update(
                {
                    "returned_at": now.isoformat(),
                    "returned_by": str(current_user.id),
                }
            )
            .eq("tool_id", str(tool_id))
            .execute()
        )

    return {"tool_id": str(tool_id), "status": ToolStatus.AVAILABLE.value}


@router.get("/{tool_id}/cmms-repair", response_model=ToolCmmsRepairDetailResponse)
def get_tool_cmms_repair_detail(
    tool_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_view_cmms_repair)],
) -> ToolCmmsRepairDetailResponse:
    """Контур А: read-only детали заявки ТОиР и отчётов по инструменту (REP-API-2/3)."""
    from app.core.config import get_settings
    from app.integration.cmms_client import CmmsRepairClientError, create_cmms_repair_client

    tool = _fetch_tool(supabase, tool_id)
    link_row = _fetch_cmms_repair_link(supabase, tool_id)
    if not link_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Для инструмента нет связи с заявкой ТОиР",
        )

    link = CmmsRepairLinkSnapshot(
        cmms_request_id=UUID(str(link_row["cmms_request_id"])),
        cmms_request_number=link_row.get("cmms_request_number"),
        client_reference_id=UUID(str(link_row["client_reference_id"]))
        if link_row.get("client_reference_id")
        else None,
    )
    tool_label = tool.get("inventory_number") or tool.get("serial_number") or str(tool_id)

    request_detail: CmmsInventoryRequestDetail | None = None
    work_reports: list[CmmsInventoryWorkReport] = []
    fetch_error: str | None = None

    client = create_cmms_repair_client(get_settings())
    try:
        req_row = client.get_inventory_request_by_inventory_id(tool_id)
        if req_row:
            request_detail = _parse_cmms_inventory_request(req_row)
        report_rows = client.list_inventory_work_reports(tool_id)
        work_reports = [_parse_cmms_work_report(row) for row in report_rows]
    except CmmsRepairClientError as exc:
        fetch_error = exc.message

    return ToolCmmsRepairDetailResponse(
        tool_id=tool_id,
        tool_label=str(tool_label),
        link=link,
        request=request_detail,
        work_reports=work_reports,
        cmms_fetch_error=fetch_error,
    )
