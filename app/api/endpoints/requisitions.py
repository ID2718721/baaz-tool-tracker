from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field
from supabase import Client

from app.api.deps import require_clerk_only
from app.core.db_utils import execute_supabase, first_row
from app.core.supabase import get_supabase_client
from app.models.schemas import CurrentUser, TMSBaseModel, ToolStatus, UserRole

router = APIRouter(prefix="/requisitions", tags=["requisitions"])

TABLE_REQUISITIONS = "tms_requisitions"
TABLE_REQUISITION_LINES = "tms_requisition_lines"
TABLE_TOOLS = "tms_tools"

RETURN_RESULT_STATUSES = frozenset(
    {ToolStatus.AVAILABLE.value, ToolStatus.MAINTENANCE.value, ToolStatus.SCRAPPED.value}
)


class ReserveLineRequest(TMSBaseModel):
    tool_id: UUID


class ReturnLineRequest(TMSBaseModel):
    result_status: ToolStatus
    condition_on_return: str | None = Field(default=None, max_length=2000)


def _fetch_line(supabase: Client, line_id: UUID) -> dict[str, Any]:
    """Загружает строку заявки с данными родительской заявки."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_REQUISITION_LINES)
        .select("id, requisition_id, line_client_id, catalog_item_id, tool_id, status, condition_on_return, tms_requisitions(id, warehouse_id, status)")
        .eq("id", str(line_id))
        .execute()
    )
    return first_row(response, detail="Строка заявки не найдена")


def _validate_return_status(result_status: ToolStatus) -> str:
    """Проверяет допустимый статус инструмента при возврате."""
    status_value = result_status.value if hasattr(result_status, "value") else str(result_status)
    if status_value not in RETURN_RESULT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="result_status должен быть: available, maintenance или scrapped",
        )
    return status_value


def _check_warehouse_access(current_user: CurrentUser, warehouse_id: str | None) -> None:
    """Кладовщик может работать только со своим складом."""
    if current_user.role == UserRole.CLERK.value and current_user.warehouse_id:
        if warehouse_id and str(current_user.warehouse_id) != str(warehouse_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Доступ к заявкам другого склада запрещён",
            )


def _sync_requisition_status(supabase: Client, requisition_id: str) -> None:
    """Пересчитывает статус заявки по статусам строк."""
    lines_resp = execute_supabase(
        lambda: supabase.table(TABLE_REQUISITION_LINES)
        .select("status")
        .eq("requisition_id", requisition_id)
        .execute()
    )
    statuses = [row["status"] for row in lines_resp.data or []]
    if not statuses:
        return

    if all(s == "returned" for s in statuses):
        new_status = "returned"
    elif all(s == "issued" for s in statuses):
        new_status = "issued"
    elif all(s in ("reserved", "issued", "returned") for s in statuses) and any(
        s == "reserved" for s in statuses
    ):
        new_status = "partially_reserved"
    elif all(s == "reserved" for s in statuses):
        new_status = "ready_for_issue"
    elif any(s == "reserved" for s in statuses):
        new_status = "partially_reserved"
    else:
        new_status = "new"

    execute_supabase(
        lambda: supabase.table(TABLE_REQUISITIONS)
        .update({"status": new_status})
        .eq("id", requisition_id)
        .execute()
    )


@router.post("/lines/{line_id}/reserve")
def reserve_line(
    line_id: UUID,
    payload: ReserveLineRequest,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(require_clerk_only)],
) -> dict[str, str | bool]:
    """Подбор конкретного экземпляра инструмента для строки заявки."""
    line = _fetch_line(supabase, line_id)
    requisition = line.get("tms_requisitions") or {}

    if line.get("status") != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Строка уже обработана")

    warehouse_id = requisition.get("warehouse_id")
    _check_warehouse_access(current_user, warehouse_id)

    tool_resp = execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .select("id, type_id, warehouse_id, status, wear_count")
        .eq("id", str(payload.tool_id))
        .execute()
    )
    tool = first_row(tool_resp, detail="Инструмент не найден")

    if str(tool["warehouse_id"]) != str(warehouse_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Инструмент с другого склада")

    if tool["status"] != ToolStatus.AVAILABLE.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Инструмент недоступен")

    if line.get("catalog_item_id") and str(line["catalog_item_id"]) != str(tool["type_id"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Тип инструмента не соответствует номенклатуре строки",
        )

    execute_supabase(
        lambda: supabase.table(TABLE_REQUISITION_LINES)
        .update({"tool_id": str(payload.tool_id), "status": "reserved"})
        .eq("id", str(line_id))
        .execute()
    )
    _sync_requisition_status(supabase, line["requisition_id"])

    return {"ok": True, "detail": "Инструмент зарезервирован"}


@router.post("/{requisition_id}/issue")
def issue_requisition(
    requisition_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(require_clerk_only)],
) -> dict[str, str | bool]:
    """Выдача комплекта: все строки должны быть в статусе reserved."""
    req_resp = execute_supabase(
        lambda: supabase.table(TABLE_REQUISITIONS)
        .select("id, warehouse_id, status")
        .eq("id", str(requisition_id))
        .execute()
    )
    requisition = first_row(req_resp, detail="Заявка не найдена")

    _check_warehouse_access(current_user, requisition.get("warehouse_id"))

    lines_resp = execute_supabase(
        lambda: supabase.table(TABLE_REQUISITION_LINES)
        .select("id, tool_id, status")
        .eq("requisition_id", str(requisition_id))
        .execute()
    )
    lines = lines_resp.data or []
    if not lines:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Заявка без строк")

    if any(line["status"] != "reserved" for line in lines):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Выдача возможна только когда все строки зарезервированы",
        )

    for line in lines:
        line_id = str(line["id"])
        tool_id = str(line["tool_id"])
        execute_supabase(
            lambda lid=line_id: supabase.table(TABLE_REQUISITION_LINES)
            .update({"status": "issued"})
            .eq("id", lid)
            .execute()
        )
        execute_supabase(
            lambda tid=tool_id: supabase.table(TABLE_TOOLS)
            .update({"status": ToolStatus.IN_USE.value})
            .eq("id", tid)
            .execute()
        )

    execute_supabase(
        lambda: supabase.table(TABLE_REQUISITIONS)
        .update({"status": "issued"})
        .eq("id", str(requisition_id))
        .execute()
    )

    return {"ok": True, "detail": "Комплект выдан"}


@router.post("/lines/{line_id}/return")
def return_line(
    line_id: UUID,
    payload: ReturnLineRequest,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(require_clerk_only)],
) -> dict[str, str | bool]:
    """Приём возврата с фиксацией технического состояния."""
    line = _fetch_line(supabase, line_id)
    requisition = line.get("tms_requisitions") or {}

    if line.get("status") != "issued":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Строка не выдана")

    _check_warehouse_access(current_user, requisition.get("warehouse_id"))

    tool_id = line.get("tool_id")
    if not tool_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Инструмент не привязан к строке")

    tool_id_str = str(tool_id)

    tool_resp = execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .select("id, wear_count, status")
        .eq("id", tool_id_str)
        .execute()
    )
    tool_row = first_row(tool_resp, detail="Инструмент не найден")
    new_wear_count = int(tool_row.get("wear_count") or 0) + 1
    result_status = _validate_return_status(payload.result_status)
    comment = (payload.condition_on_return or "").strip() or None

    # 1) Строка заявки: status + condition_on_return (комментарий в лог)
    execute_supabase(
        lambda: supabase.table(TABLE_REQUISITION_LINES)
        .update(
            {
                "status": "returned",
                "condition_on_return": comment,
            }
        )
        .eq("id", str(line_id))
        .execute()
    )

    # 2) Инструмент: износ +1, явный result_status; дата списания при scrapped
    tool_update: dict[str, Any] = {"wear_count": new_wear_count, "status": result_status}
    if result_status == ToolStatus.SCRAPPED.value:
        tool_update["last_check"] = date.today().isoformat()

    execute_supabase(
        lambda: supabase.table(TABLE_TOOLS).update(tool_update).eq("id", tool_id_str).execute()
    )

    _sync_requisition_status(supabase, str(line["requisition_id"]))

    return {"ok": True, "detail": "Возврат оформлен"}
