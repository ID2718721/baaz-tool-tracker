from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TMSBaseModel(BaseModel):
    """Базовая модель: UUID и даты сериализуются в JSON как строки (ISO 8601)."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
    )


# ---------------------------------------------------------------------------
# Перечисления
# ---------------------------------------------------------------------------


class ToolStatus(StrEnum):
    AVAILABLE = "available"
    IN_USE = "in_use"
    MAINTENANCE = "maintenance"
    SCRAPPED = "scrapped"
    PENDING_REPAIR = "pending_repair"
    PENDING_RETURN = "pending_return"


class InventoryHandoffMode(StrEnum):
    PICKUP_AT_WAREHOUSE = "pickup_at_warehouse"
    DELIVER_TO_DEPARTMENT = "deliver_to_department"


class UserRole(StrEnum):
    ADMIN = "admin"
    CLERK = "clerk"
    MASTER = "master"


class RequisitionLineKind(StrEnum):
    CATALOG = "catalog"
    FREE_TEXT = "free_text"
    TOOL_INSTANCE = "tool_instance"


class RequisitionLineStatus(StrEnum):
    PENDING = "pending"
    RESERVED = "reserved"
    ISSUED = "issued"
    RETURNED = "returned"


class RequisitionStatus(StrEnum):
    NEW = "new"
    PARTIALLY_RESERVED = "partially_reserved"
    READY_FOR_ISSUE = "ready_for_issue"
    ISSUED = "issued"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class WorkOrderKind(StrEnum):
    REQUEST = "request"
    SCHEDULE = "schedule"
    INTERNAL = "internal"


class WorkOrderStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SCHEDULED = "scheduled"


class CancelledBy(StrEnum):
    DISPATCHER = "dispatcher"
    STOREKEEPER = "storekeeper"


class DispatcherCancelReason(StrEnum):
    WORK_ORDER_CANCELLED = "work_order_cancelled"
    DISPATCHER_CANCELLED = "dispatcher_cancelled"
    DUPLICATE = "duplicate"


class StorekeeperCancelReason(StrEnum):
    OUT_OF_STOCK = "out_of_stock"
    DAMAGED = "damaged"
    DECOMMISSIONED = "decommissioned"
    OTHER = "other"


class RepairRequestType(StrEnum):
    INSPECTION = "inspection"
    SERVICE = "service"


class IntegrationSchemaVersion(TMSBaseModel):
    schema_version: int = Field(default=1, ge=1)


# ---------------------------------------------------------------------------
# locations
# ---------------------------------------------------------------------------


class LocationBase(TMSBaseModel):
    name: str = Field(min_length=1, max_length=255)


class LocationCreate(LocationBase):
    pass


class LocationUpdate(TMSBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class LocationRead(LocationBase):
    id: UUID


# ---------------------------------------------------------------------------
# warehouses
# ---------------------------------------------------------------------------


class WarehouseBase(TMSBaseModel):
    name: str = Field(min_length=1, max_length=255)
    location_id: UUID


class WarehouseCreate(WarehouseBase):
    pass


class WarehouseUpdate(TMSBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    location_id: UUID | None = None


class WarehouseRead(WarehouseBase):
    id: UUID


class WarehouseSummary(TMSBaseModel):
    """Краткое представление склада для интеграции ISS-API-3."""

    warehouse_id: UUID
    name: str


# ---------------------------------------------------------------------------
# employees
# ---------------------------------------------------------------------------


class EmployeeGender(StrEnum):
    MALE = "муж"
    FEMALE = "жен"


class EmployeeBase(TMSBaseModel):
    badge_number: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1, max_length=255)
    location_id: UUID
    gender: EmployeeGender | None = None
    birth_date: date | None = None


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(TMSBaseModel):
    badge_number: str | None = Field(default=None, min_length=1, max_length=64)
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    location_id: UUID | None = None
    gender: EmployeeGender | None = None
    birth_date: date | None = None


class EmployeeRead(EmployeeBase):
    id: UUID


# ---------------------------------------------------------------------------
# tool_categories
# ---------------------------------------------------------------------------


class ToolCategoryBase(TMSBaseModel):
    name: str = Field(min_length=1, max_length=255)


class ToolCategoryCreate(ToolCategoryBase):
    pass


class ToolCategoryUpdate(TMSBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class ToolCategoryRead(ToolCategoryBase):
    id: UUID


# ---------------------------------------------------------------------------
# tool_types
# ---------------------------------------------------------------------------


class ToolTypeBase(TMSBaseModel):
    model_name: str = Field(min_length=1, max_length=255)
    category_id: UUID


class ToolTypeCreate(ToolTypeBase):
    pass


class ToolTypeUpdate(TMSBaseModel):
    model_name: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: UUID | None = None


class ToolTypeRead(ToolTypeBase):
    id: UUID


# ---------------------------------------------------------------------------
# catalog_items (номенклатура склада, контур Б)
# ---------------------------------------------------------------------------


class CatalogItemBase(TMSBaseModel):
    warehouse_id: UUID
    name: str = Field(min_length=1, max_length=255)
    tool_type_id: UUID | None = None


class CatalogItemCreate(CatalogItemBase):
    pass


class CatalogItemUpdate(TMSBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    tool_type_id: UUID | None = None


class CatalogItemRead(CatalogItemBase):
    id: UUID


class CatalogItemAvailability(TMSBaseModel):
    """Позиция каталога с остатками (ISS-API-4)."""

    catalog_item_id: UUID
    name: str
    quantity_available: int = Field(ge=0)
    quantity_total: int = Field(ge=0)


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


class ToolBase(TMSBaseModel):
    type_id: UUID
    warehouse_id: UUID
    inventory_number: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=128)
    status: ToolStatus = ToolStatus.AVAILABLE
    wear_count: int = Field(default=0, ge=0)
    last_check: date | None = None


class ToolCreate(ToolBase):
    pass


class ToolUpdate(TMSBaseModel):
    type_id: UUID | None = None
    warehouse_id: UUID | None = None
    inventory_number: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=128)
    status: ToolStatus | None = None
    wear_count: int | None = Field(default=None, ge=0)
    last_check: date | None = None


class ToolRead(ToolBase):
    id: UUID
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------


class UserBase(TMSBaseModel):
    employee_id: UUID | None = None
    warehouse_id: UUID | None = None
    role: UserRole


class UserCreate(UserBase):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserUpdate(TMSBaseModel):
    employee_id: UUID | None = None
    warehouse_id: UUID | None = None
    role: UserRole | None = None
    login: str | None = Field(default=None, min_length=1, max_length=64)


class UserRead(UserBase):
    id: UUID
    login: str


class UserAuth(UserRead):
    """Пользователь с полями для аутентификации (не отдаётся наружу)."""

    password_hash: str
    created_at: datetime | None = None


class CurrentUser(UserRead):
    """Текущий аутентифицированный пользователь (без пароля)."""

    employee_full_name: str | None = None


class LoginRequest(TMSBaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(TMSBaseModel):
    access_token: str
    token_type: str = "bearer"
    user: CurrentUser


# ---------------------------------------------------------------------------
# issuance_log
# ---------------------------------------------------------------------------


class IssuanceLogBase(TMSBaseModel):
    tool_id: UUID
    employee_id: UUID
    issued_by: UUID
    issued_at: datetime
    returned_at: datetime | None = None
    condition_on_return: str | None = None
    external_order_id: UUID | None = None


class IssuanceLogCreate(TMSBaseModel):
    tool_id: UUID
    employee_id: UUID
    issued_by: UUID
    external_order_id: UUID | None = None


class IssuanceLogReturn(TMSBaseModel):
    condition_on_return: str = Field(min_length=1)


class IssuanceLogRead(IssuanceLogBase):
    id: UUID


# ---------------------------------------------------------------------------
# requisitions / requisition_lines (контур Б)
# ---------------------------------------------------------------------------


class RequisitionLineBase(TMSBaseModel):
    line_client_id: UUID
    kind: RequisitionLineKind
    catalog_item_id: UUID | None = None
    description: str | None = None
    quantity: int = Field(default=1, ge=1)
    tool_id: UUID | None = None


class RequisitionLineCreate(RequisitionLineBase):
    @model_validator(mode="after")
    def validate_line_rules(self) -> RequisitionLineCreate:
        if self.kind == RequisitionLineKind.CATALOG:
            if self.catalog_item_id is None:
                raise ValueError("catalog_item_id обязателен при kind=catalog")
            if self.description is not None:
                raise ValueError("description не передаётся при kind=catalog")
        elif self.kind == RequisitionLineKind.FREE_TEXT:
            if not (self.description and self.description.strip()):
                raise ValueError("description обязателен при kind=free_text")
            if self.catalog_item_id is not None:
                raise ValueError("catalog_item_id не передаётся при kind=free_text")
        return self


class RequisitionLineRead(RequisitionLineBase):
    id: UUID = Field(alias="line_id")
    requisition_id: UUID
    line_status: RequisitionLineStatus
    description: str


class WorkOrderSnapshot(TMSBaseModel):
    kind: WorkOrderKind
    id: UUID
    number: str
    status: WorkOrderStatus
    title: str
    asset_name: str | None = None
    location_name: str | None = None


class TechnicianSnapshot(TMSBaseModel):
    id: UUID
    full_name: str


class RequisitionBase(TMSBaseModel):
    client_reference_id: UUID
    warehouse_id: UUID
    cmms_request_id: UUID | None = None
    cmms_schedule_id: UUID | None = None
    work_order_kind: WorkOrderKind
    work_order_id: UUID
    work_order_number: str
    work_order_status: WorkOrderStatus
    work_order_title: str
    work_order_asset_name: str | None = None
    work_order_location_name: str | None = None
    technician_id: UUID
    technician_full_name: str
    notes: str | None = None


class RequisitionRead(RequisitionBase):
    id: UUID = Field(alias="requisition_id")
    warehouse_name: str
    status: RequisitionStatus
    created_at: datetime
    issued_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancelled_by: CancelledBy | None = None
    cancel_reason: str | None = None
    cancel_reason_text: str | None = None
    lines: list[RequisitionLineRead] = Field(default_factory=list)


class RequisitionLinesSummary(TMSBaseModel):
    total: int = Field(ge=0)
    pending: int = Field(ge=0)
    reserved: int = Field(ge=0)
    issued: int = Field(ge=0)
    returned: int = Field(ge=0)


class RequisitionStatusSummary(TMSBaseModel):
    requisition_id: UUID
    warehouse_id: UUID
    warehouse_name: str
    status: RequisitionStatus
    issued_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancelled_by: CancelledBy | None = None
    cancel_reason: str | None = None
    cancel_reason_text: str | None = None
    lines_summary: RequisitionLinesSummary


# ---------------------------------------------------------------------------
# Контур А — снимок заявки на ремонт (исходящий вызов CMMS)
# ---------------------------------------------------------------------------


class RepairRequestCreate(IntegrationSchemaVersion):
    client_reference_id: UUID
    tool_id: UUID
    tool_name: str
    tool_serial: str | None = None
    tool_type_name: str | None = None
    request_type: RepairRequestType
    title: str = Field(min_length=1)
    description: str | None = None
    target_repair_department_id: UUID
    inventory_handoff_mode: InventoryHandoffMode = InventoryHandoffMode.DELIVER_TO_DEPARTMENT
    inventory_warehouse_name: str | None = None

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("title не может быть пустым")
        return trimmed


class RepairRequestResponse(TMSBaseModel):
    request_id: UUID
    request_number: str
    status: str
    created_at: datetime


class CmmsRepairDepartmentItem(TMSBaseModel):
    repair_department_id: UUID
    name: str
    code: str | None = None


class CmmsRepairDepartmentListResponse(TMSBaseModel):
    departments: list[CmmsRepairDepartmentItem] = Field(default_factory=list)


class ToolRepairRequestHistory(TMSBaseModel):
    request_id: UUID
    request_number: str
    request_type: RepairRequestType
    status: str
    title: str
    created_at: datetime
    updated_at: datetime


class ToolWorkReport(TMSBaseModel):
    work_report_id: UUID
    request_id: UUID
    work_performed: str
    actual_duration_hours: float = Field(ge=0)
    created_at: datetime


class CmmsRepairLinkSnapshot(TMSBaseModel):
    cmms_request_id: UUID
    cmms_request_number: str | None = None
    client_reference_id: UUID | None = None


class CmmsInventoryRequestDetail(TMSBaseModel):
    request_id: UUID
    request_number: str
    inventory_id: UUID
    status: str
    title: str | None = None
    description: str | None = None
    type: str | None = None
    priority: str | None = None
    repair_zone: str | None = None
    requester_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CmmsInventoryWorkReport(TMSBaseModel):
    work_report_id: UUID
    request_id: UUID
    request_number: str | None = None
    work_performed: str
    actual_duration_hours: float | None = Field(default=None, ge=0)
    maintenance_type: str | None = None
    repair_department_name: str | None = None
    technician_full_name: str | None = None
    defects_found: str | None = None
    notes: str | None = None
    created_at: datetime


class ToolCmmsRepairDetailResponse(TMSBaseModel):
    tool_id: UUID
    tool_label: str
    link: CmmsRepairLinkSnapshot
    request: CmmsInventoryRequestDetail | None = None
    work_reports: list[CmmsInventoryWorkReport] = Field(default_factory=list)
    cmms_fetch_error: str | None = None


# ---------------------------------------------------------------------------
# Контур Б — контракт интеграции (ISS-API)
# ---------------------------------------------------------------------------


class CreateToolRequisitionRequest(IntegrationSchemaVersion):
    client_reference_id: UUID
    warehouse_id: UUID
    work_order: WorkOrderSnapshot
    technician: TechnicianSnapshot
    lines: Annotated[list[RequisitionLineCreate], Field(min_length=1)]
    notes: str | None = None


class CreateToolRequisitionLineResponse(TMSBaseModel):
    line_id: UUID
    line_client_id: UUID
    line_status: RequisitionLineStatus
    kind: RequisitionLineKind
    catalog_item_id: UUID | None = None
    description: str


class CreateToolRequisitionResponse(IntegrationSchemaVersion):
    requisition_id: UUID
    client_reference_id: UUID
    warehouse_id: UUID
    warehouse_name: str
    status: RequisitionStatus
    created_at: datetime
    lines: list[CreateToolRequisitionLineResponse]


class CancelByCmmsRequestId(TMSBaseModel):
    cmms_request_id: UUID
    reason: DispatcherCancelReason


class CancelByRequisitionIds(TMSBaseModel):
    requisition_ids: Annotated[list[UUID], Field(min_length=1)]
    reason: DispatcherCancelReason


class CancelToolRequisitionsRequest(IntegrationSchemaVersion):
    cmms_request_id: UUID | None = None
    requisition_ids: list[UUID] | None = None
    reason: DispatcherCancelReason | None = None


class CancelledRequisitionItem(TMSBaseModel):
    requisition_id: UUID
    status: Literal[RequisitionStatus.CANCELLED] = RequisitionStatus.CANCELLED


class SkippedRequisitionItem(TMSBaseModel):
    requisition_id: UUID
    reason: str


class CancelToolRequisitionsResponse(IntegrationSchemaVersion):
    cancelled: list[CancelledRequisitionItem] = Field(default_factory=list)
    skipped: list[SkippedRequisitionItem] = Field(default_factory=list)


class WarehouseListResponse(IntegrationSchemaVersion):
    warehouses: list[WarehouseSummary]


class WarehouseCatalogResponse(IntegrationSchemaVersion):
    warehouse_id: UUID
    items: list[CatalogItemAvailability]


class ToolRequisitionStatusResponse(IntegrationSchemaVersion):
    work_order: WorkOrderSnapshot | None = None
    requisitions: list[RequisitionStatusSummary]


class IntegrationValidationError(TMSBaseModel):
    error: Literal["validation_failed"] = "validation_failed"
    details: list[str]


# ---------------------------------------------------------------------------
# REP-EVT-1 — webhook статуса заявки на ремонт (входящий от CMMS)
# ---------------------------------------------------------------------------


class RepairRequestStatusWebhook(IntegrationSchemaVersion):
    event: Literal["request.status_changed"] = "request.status_changed"
    request_id: UUID
    request_number: str
    tool_id: UUID
    inventory_id: UUID | None = None
    inventory_kind: Literal["tool"] | None = "tool"
    previous_status: str
    new_status: str
    changed_at: datetime


class WebhookAckResponse(TMSBaseModel):
    ok: bool = True


# ---------------------------------------------------------------------------
# Внутренняя выдача / возврат (requisitions + requisition_lines)
# ---------------------------------------------------------------------------


class InternalIssueRequest(TMSBaseModel):
    tool_id: UUID
    employee_id: UUID
    issued_by: UUID
    notes: str | None = None


class InternalReturnRequest(TMSBaseModel):
    tool_id: UUID
    result_status: ToolStatus
    condition_on_return: str | None = Field(default=None, max_length=2000)
    wear_count: int | None = Field(default=None, ge=0)
    requisition_id: UUID | None = None
    requisition_line_id: UUID | None = None


class InternalIssueResponse(TMSBaseModel):
    requisition_id: UUID
    requisition_line_id: UUID
    issuance_log_id: UUID
    tool: ToolRead
    issued_at: datetime


class InternalReturnResponse(TMSBaseModel):
    requisition_id: UUID
    requisition_line_id: UUID
    issuance_log_id: UUID
    tool: ToolRead
    returned_at: datetime
    condition_on_return: str | None = None


# ---------------------------------------------------------------------------
# Аналитика
# ---------------------------------------------------------------------------


class PensionerEmployee(TMSBaseModel):
    id: UUID
    badge_number: str
    full_name: str
    birth_date: date
    age: int


class PensionersByDepartment(TMSBaseModel):
    location_id: UUID
    location_name: str
    employees: list[PensionerEmployee]


class PensionersResponse(TMSBaseModel):
    year: int
    departments: list[PensionersByDepartment]
    total: int


class ToolCategoryStat(TMSBaseModel):
    category_id: UUID
    category_name: str
    tool_count: int
    percentage: float = Field(ge=0, le=100)


class ToolStatsResponse(TMSBaseModel):
    total_tools: int
    categories: list[ToolCategoryStat]


class OverdueCalibrationTool(ToolRead):
    type_name: str | None = None
    category_name: str | None = None
    days_overdue: int


class OverdueCalibrationResponse(TMSBaseModel):
    as_of: date
    tools: list[OverdueCalibrationTool]
    total: int


class YoungWornTool(ToolRead):
    type_name: str | None = None
    age_days: int


class YoungWornToolsResponse(TMSBaseModel):
    tools: list[YoungWornTool]
    total: int
