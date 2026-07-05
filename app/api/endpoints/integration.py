from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.core.config import Settings, get_settings
from app.models.schemas import (
    CancelToolRequisitionsRequest,
    CancelToolRequisitionsResponse,
    CreateToolRequisitionRequest,
    CreateToolRequisitionResponse,
    IntegrationValidationError,
    RepairRequestStatusWebhook,
    ToolRequisitionStatusResponse,
    WarehouseCatalogResponse,
    WarehouseListResponse,
    WebhookAckResponse,
)

router = APIRouter(prefix="/integration", tags=["integration"])


def verify_integration_auth(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    apikey: Annotated[str | None, Header()] = None,
) -> None:
    """Проверка сервис-сервис аутентификации (Bearer + apikey Supabase)."""
    if not settings.tms_integration_secret:
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Отсутствует или некорректный заголовок Authorization",
        )

    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.tms_integration_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Неверный секрет интеграции")

    if not apikey or apikey != settings.supabase_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Неверный apikey")


# ---------------------------------------------------------------------------
# Контур Б — ISS-API (TMS принимает запросы от CMMS)
# ---------------------------------------------------------------------------


@router.post(
    "/cmms/tool-requisitions",
    response_model=CreateToolRequisitionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="ISS-API-1 — Создать заявку на получение инструмента",
)
def create_tool_requisition(
    payload: CreateToolRequisitionRequest,
    _: Annotated[None, Depends(verify_integration_auth)],
) -> CreateToolRequisitionResponse:
    """Заготовка: идемпотентное создание заявки по client_reference_id."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="ISS-API-1: создание заявки на выдачу — в разработке",
    )


@router.post(
    "/cmms/cancel-tool-requisitions",
    response_model=CancelToolRequisitionsResponse,
    summary="ISS-API-2 — Batch-отмена заявок диспетчером CMMS",
)
def cancel_tool_requisitions(
    payload: CancelToolRequisitionsRequest,
    _: Annotated[None, Depends(verify_integration_auth)],
) -> CancelToolRequisitionsResponse:
    """Заготовка: отмена по cmms_request_id или списку requisition_ids."""
    has_request_id = payload.cmms_request_id is not None
    has_requisition_ids = bool(payload.requisition_ids)
    if has_request_id == has_requisition_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=IntegrationValidationError(
                details=["Укажите ровно один критерий: cmms_request_id или requisition_ids"],
            ).model_dump(),
        )

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="ISS-API-2: batch-отмена заявок — в разработке",
    )


@router.get(
    "/cmms/warehouses",
    response_model=WarehouseListResponse,
    summary="ISS-API-3 — Список складов для формы CMMS",
)
def list_integration_warehouses(
    _: Annotated[None, Depends(verify_integration_auth)],
) -> WarehouseListResponse:
    """Заготовка: лёгкий список складов без номенклатуры."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="ISS-API-3: список складов — в разработке",
    )


@router.get(
    "/cmms/warehouse-catalog",
    response_model=WarehouseCatalogResponse,
    summary="ISS-API-4 — Номенклатура склада",
)
def get_warehouse_catalog(
    _: Annotated[None, Depends(verify_integration_auth)],
    warehouse_id: UUID = Query(...),
    availability: Literal["all", "available"] = Query(default="available"),
) -> WarehouseCatalogResponse:
    """Заготовка: каталог позиций с фильтром availability."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="ISS-API-4: номенклатура склада — в разработке",
    )


@router.get(
    "/cmms/tool-requisition",
    response_model=ToolRequisitionStatusResponse,
    summary="ISS-API-5 — Статус заявки на выдачу",
)
def get_tool_requisition_status(
    _: Annotated[None, Depends(verify_integration_auth)],
    requisition_id: UUID | None = Query(default=None),
    cmms_request_id: UUID | None = Query(default=None),
    cmms_schedule_id: UUID | None = Query(default=None),
    fields: Literal["summary", "full"] = Query(default="summary"),
) -> ToolRequisitionStatusResponse:
    """Заготовка: опрос статуса заявок по наряду или одной заявке."""
    if not any([requisition_id, cmms_request_id, cmms_schedule_id]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=IntegrationValidationError(
                details=["Укажите requisition_id, cmms_request_id или cmms_schedule_id"],
            ).model_dump(),
        )

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="ISS-API-5: статус заявки — в разработке",
    )


# ---------------------------------------------------------------------------
# Контур А — REP-EVT-1 (webhook от CMMS при закрытии заявки на ремонт)
# ---------------------------------------------------------------------------


@router.post(
    "/cmms/repair-request-status",
    response_model=WebhookAckResponse,
    summary="REP-EVT-1 — Webhook смены статуса заявки на ремонт",
)
def repair_request_status_webhook(
    payload: RepairRequestStatusWebhook,
    _: Annotated[None, Depends(verify_integration_auth)],
) -> WebhookAckResponse:
    """Заготовка: разблокировка инструмента при closed/rejected/cancelled."""
    terminal_statuses = {"closed", "rejected", "cancelled"}
    if payload.new_status not in terminal_statuses:
        return WebhookAckResponse(ok=True)

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="REP-EVT-1: обработка webhook — в разработке",
    )
