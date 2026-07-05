from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from supabase import Client

from app.core.config import Settings, get_settings
from app.core.supabase import get_supabase_client
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
from app.services.cmms_integration_service import CmmsIntegrationService

router = APIRouter(prefix="/integration/cmms", tags=["cmms-integration"])


def verify_cmms_integration_auth(
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


def _service(supabase: Annotated[Client, Depends(get_supabase_client)]) -> CmmsIntegrationService:
    return CmmsIntegrationService(supabase)


@router.post(
    "/tool-requisitions",
    response_model=CreateToolRequisitionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="ISS-API-1 — Создать заявку на получение инструмента",
)
def create_tool_requisition(
    payload: CreateToolRequisitionRequest,
    _: Annotated[None, Depends(verify_cmms_integration_auth)],
    service: Annotated[CmmsIntegrationService, Depends(_service)],
) -> CreateToolRequisitionResponse:
    return service.create_tool_requisition(payload)


@router.post(
    "/cancel-tool-requisitions",
    response_model=CancelToolRequisitionsResponse,
    summary="ISS-API-2 — Batch-отмена заявок диспетчером CMMS",
)
def cancel_tool_requisitions(
    payload: CancelToolRequisitionsRequest,
    _: Annotated[None, Depends(verify_cmms_integration_auth)],
    service: Annotated[CmmsIntegrationService, Depends(_service)],
) -> CancelToolRequisitionsResponse:
    has_request_id = payload.cmms_request_id is not None
    has_requisition_ids = bool(payload.requisition_ids)
    if has_request_id == has_requisition_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=IntegrationValidationError(
                details=["Укажите ровно один критерий: cmms_request_id или requisition_ids"],
            ).model_dump(),
        )
    return service.cancel_tool_requisitions(payload)


@router.get(
    "/warehouses",
    response_model=WarehouseListResponse,
    summary="ISS-API-3 — Список складов для формы CMMS",
)
def list_integration_warehouses(
    _: Annotated[None, Depends(verify_cmms_integration_auth)],
    service: Annotated[CmmsIntegrationService, Depends(_service)],
) -> WarehouseListResponse:
    return service.list_warehouses()


@router.get(
    "/warehouse-catalog",
    response_model=WarehouseCatalogResponse,
    summary="ISS-API-4 — Номенклатура склада",
)
def get_warehouse_catalog(
    _: Annotated[None, Depends(verify_cmms_integration_auth)],
    service: Annotated[CmmsIntegrationService, Depends(_service)],
    warehouse_id: UUID = Query(...),
    availability: str = Query(default="available"),
) -> WarehouseCatalogResponse:
    return service.get_warehouse_catalog(warehouse_id, availability)


@router.get(
    "/tool-requisition",
    response_model=ToolRequisitionStatusResponse,
    summary="ISS-API-5 — Статус заявки на выдачу",
)
def get_tool_requisition_status(
    _: Annotated[None, Depends(verify_cmms_integration_auth)],
    service: Annotated[CmmsIntegrationService, Depends(_service)],
    requisition_id: UUID | None = Query(default=None),
    cmms_request_id: UUID | None = Query(default=None),
    cmms_schedule_id: UUID | None = Query(default=None),
    fields: str = Query(default="summary"),
) -> ToolRequisitionStatusResponse:
    if not any([requisition_id, cmms_request_id, cmms_schedule_id]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=IntegrationValidationError(
                details=["Укажите requisition_id, cmms_request_id или cmms_schedule_id"],
            ).model_dump(),
        )
    return service.get_tool_requisition_status(
        requisition_id=requisition_id,
        cmms_request_id=cmms_request_id,
        cmms_schedule_id=cmms_schedule_id,
        fields=fields,
    )


@router.post(
    "/repair-request-status",
    response_model=WebhookAckResponse,
    summary="REP-EVT-1 — Webhook смены статуса заявки на ремонт",
)
def repair_request_status_webhook(
    payload: RepairRequestStatusWebhook,
    _: Annotated[None, Depends(verify_cmms_integration_auth)],
    service: Annotated[CmmsIntegrationService, Depends(_service)],
) -> WebhookAckResponse:
    return service.repair_request_status_webhook(payload)
