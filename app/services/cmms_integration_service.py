"""Бизнес-логика ISS-API / REP-EVT-1 для интеграции CMMS ↔ TMS."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from supabase import Client

from app.core.db_utils import execute_supabase, first_row
from app.core.requisition_status import derive_requisition_status
from app.models.schemas import (
    CancelToolRequisitionsRequest,
    CancelToolRequisitionsResponse,
    CancelledRequisitionItem,
    CreateToolRequisitionLineResponse,
    CreateToolRequisitionRequest,
    CreateToolRequisitionResponse,
    RepairRequestStatusWebhook,
    RequisitionLineKind,
    RequisitionLineStatus,
    RequisitionLinesSummary,
    RequisitionStatus,
    RequisitionStatusSummary,
    SkippedRequisitionItem,
    ToolRequisitionStatusResponse,
    WarehouseCatalogResponse,
    WarehouseListResponse,
    WarehouseSummary,
    CatalogItemAvailability,
    WebhookAckResponse,
    WorkOrderKind,
)

TABLE_REQUISITIONS = "requisitions"
TABLE_REQUISITION_LINES = "requisition_lines"
TABLE_WAREHOUSES = "warehouses"
TABLE_TOOL_TYPES = "tool_types"
TABLE_TOOLS = "tools"
TABLE_CMMS_LINKS = "cmms_work_order_links"
TABLE_CMMS_REPAIR = "cmms_repair_links"

TERMINAL_LINE_STATUSES = frozenset({"issued", "returned"})
CANCELLABLE_REQUISITION_STATUSES = frozenset(
    {"new", "partially_reserved", "ready_for_issue"}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _enum_str(value: StrEnum | str) -> str:
    return value if isinstance(value, str) else value.value


def _line_description(kind: str, catalog_name: str | None, description: str | None) -> str:
    if kind == RequisitionLineKind.FREE_TEXT.value:
        return (description or "").strip()
    return (catalog_name or description or "—").strip()


def _lines_summary(lines: list[dict[str, Any]]) -> RequisitionLinesSummary:
    counts = {"pending": 0, "reserved": 0, "issued": 0, "returned": 0}
    for row in lines:
        st = row.get("status") or "pending"
        if st in counts:
            counts[st] += 1
    return RequisitionLinesSummary(
        total=len(lines),
        pending=counts["pending"],
        reserved=counts["reserved"],
        issued=counts["issued"],
        returned=counts["returned"],
    )


class CmmsIntegrationService:
    def __init__(self, supabase: Client) -> None:
        self._supabase = supabase

    def create_tool_requisition(self, payload: CreateToolRequisitionRequest) -> CreateToolRequisitionResponse:
        existing = execute_supabase(
            lambda: self._supabase.table(TABLE_REQUISITIONS)
            .select(
                "id, client_reference_id, warehouse_id, status, created_at, "
                "warehouses(name), "
                f"{TABLE_REQUISITION_LINES}(id, line_client_id, kind, catalog_item_id, description, status, tool_types(model_name))"
            )
            .eq("client_reference_id", str(payload.client_reference_id))
            .execute()
        )
        if existing.data:
            return self._map_create_response(first_row(existing))

        if payload.work_order.status not in ("in_progress", "scheduled"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "validation_failed", "details": ["work_order.status must be in_progress or scheduled"]},
            )

        wh_resp = execute_supabase(
            lambda: self._supabase.table(TABLE_WAREHOUSES)
            .select("id, name")
            .eq("id", str(payload.warehouse_id))
            .execute()
        )
        warehouse = first_row(wh_resp, detail="warehouse_id not found")

        for line in payload.lines:
            if line.kind == RequisitionLineKind.CATALOG:
                cat_resp = execute_supabase(
                    lambda cid=str(line.catalog_item_id): self._supabase.table(TABLE_TOOL_TYPES)
                    .select("id, model_name")
                    .eq("id", cid)
                    .execute()
                )
                first_row(cat_resp, detail=f"catalog_item_id {line.catalog_item_id} not found")

        req_insert = execute_supabase(
            lambda: self._supabase.table(TABLE_REQUISITIONS)
            .insert(
                {
                    "client_reference_id": str(payload.client_reference_id),
                    "warehouse_id": str(payload.warehouse_id),
                    "external_order_id": str(payload.work_order.id),
                    "status": RequisitionStatus.NEW.value,
                }
            )
            .execute()
        )
        requisition = first_row(req_insert)

        execute_supabase(
            lambda: self._supabase.table(TABLE_CMMS_LINKS)
            .insert(
                {
                    "requisition_id": requisition["id"],
                    "cmms_work_order_id": str(payload.work_order.id),
                    "work_order_kind": _enum_str(payload.work_order.kind),
                    "cmms_work_order_number": payload.work_order.number,
                    "cmms_work_order_status": RequisitionStatus.NEW.value,
                    "technician_badge": str(payload.technician.id),
                    "technician_name": payload.technician.full_name,
                }
            )
            .execute()
        )

        line_rows: list[dict[str, Any]] = []
        for line in payload.lines:
            desc = line.description if line.kind == RequisitionLineKind.FREE_TEXT else None
            line_rows.append(
                {
                    "requisition_id": requisition["id"],
                    "line_client_id": str(line.line_client_id),
                    "kind": _enum_str(line.kind),
                    "catalog_item_id": str(line.catalog_item_id) if line.catalog_item_id else None,
                    "description": desc,
                    "quantity": line.quantity,
                    "status": RequisitionLineStatus.PENDING.value,
                }
            )

        lines_resp = execute_supabase(
            lambda: self._supabase.table(TABLE_REQUISITION_LINES).insert(line_rows).execute()
        )
        requisition["requisition_lines"] = lines_resp.data or []
        requisition["warehouses"] = warehouse
        return self._map_create_response(requisition)

    def _map_create_response(self, row: dict[str, Any]) -> CreateToolRequisitionResponse:
        warehouse = row.get("warehouses") or {}
        if isinstance(warehouse, list):
            warehouse = warehouse[0] if warehouse else {}
        lines_out: list[CreateToolRequisitionLineResponse] = []
        for line in row.get("requisition_lines") or []:
            tool_type = line.get("tool_types") or {}
            if isinstance(tool_type, list):
                tool_type = tool_type[0] if tool_type else {}
            lines_out.append(
                CreateToolRequisitionLineResponse(
                    line_id=line["id"],
                    line_client_id=line["line_client_id"],
                    line_status=line.get("status") or RequisitionLineStatus.PENDING.value,
                    kind=line["kind"],
                    catalog_item_id=line.get("catalog_item_id"),
                    description=_line_description(
                        line["kind"],
                        tool_type.get("model_name"),
                        line.get("description"),
                    ),
                )
            )
        return CreateToolRequisitionResponse(
            requisition_id=row["id"],
            client_reference_id=row["client_reference_id"],
            warehouse_id=row["warehouse_id"],
            warehouse_name=warehouse.get("name") or "",
            status=row.get("status") or RequisitionStatus.NEW.value,
            created_at=row.get("created_at") or _utc_now(),
            lines=lines_out,
        )

    def cancel_tool_requisitions(self, payload: CancelToolRequisitionsRequest) -> CancelToolRequisitionsResponse:
        if payload.cmms_request_id:
            req_resp = execute_supabase(
                lambda: self._supabase.table(TABLE_REQUISITIONS)
                .select("id, status, cancelled_at, requisition_lines(status)")
                .eq("external_order_id", str(payload.cmms_request_id))
                .execute()
            )
            targets = req_resp.data or []
        else:
            ids = [str(rid) for rid in payload.requisition_ids or []]
            req_resp = execute_supabase(
                lambda: self._supabase.table(TABLE_REQUISITIONS)
                .select("id, status, cancelled_at, requisition_lines(status)")
                .in_("id", ids)
                .execute()
            )
            targets = req_resp.data or []

        cancelled: list[CancelledRequisitionItem] = []
        skipped: list[SkippedRequisitionItem] = []
        reason = _enum_str(payload.reason) if payload.reason else "dispatcher_cancelled"

        for req in targets:
            lines = req.get("requisition_lines") or []
            if any((ln.get("status") or "") in TERMINAL_LINE_STATUSES for ln in lines):
                skipped.append(SkippedRequisitionItem(requisition_id=req["id"], reason="already_issued"))
                continue
            if req.get("cancelled_at") or req.get("status") == RequisitionStatus.CANCELLED.value:
                skipped.append(SkippedRequisitionItem(requisition_id=req["id"], reason="already_cancelled"))
                continue

            execute_supabase(
                lambda rid=str(req["id"]): self._supabase.table(TABLE_REQUISITIONS)
                .update(
                    {
                        "status": RequisitionStatus.CANCELLED.value,
                        "cancelled_at": _utc_now().isoformat(),
                        "cancel_reason": reason,
                    }
                )
                .eq("id", rid)
                .execute()
            )
            execute_supabase(
                lambda rid=str(req["id"]): self._supabase.table(TABLE_CMMS_LINKS)
                .update({"cancelled_by": "dispatcher", "cancel_reason_text": reason})
                .eq("requisition_id", rid)
                .execute()
            )
            cancelled.append(CancelledRequisitionItem(requisition_id=req["id"]))

        return CancelToolRequisitionsResponse(cancelled=cancelled, skipped=skipped)

    def list_warehouses(self) -> WarehouseListResponse:
        resp = execute_supabase(
            lambda: self._supabase.table(TABLE_WAREHOUSES).select("id, name").order("name").execute()
        )
        warehouses = [
            WarehouseSummary(warehouse_id=row["id"], name=row["name"]) for row in resp.data or []
        ]
        return WarehouseListResponse(warehouses=warehouses)

    def get_warehouse_catalog(self, warehouse_id: UUID, availability: str) -> WarehouseCatalogResponse:
        tools_resp = execute_supabase(
            lambda: self._supabase.table(TABLE_TOOLS)
            .select("type_id, status, tool_types(id, model_name, category_id)")
            .eq("warehouse_id", str(warehouse_id))
            .execute()
        )
        counts: dict[str, dict[str, Any]] = {}
        for tool in tools_resp.data or []:
            tt = tool.get("tool_types") or {}
            if isinstance(tt, list):
                tt = tt[0] if tt else {}
            type_id = str(tool.get("type_id") or tt.get("id") or "")
            if not type_id:
                continue
            bucket = counts.setdefault(type_id, {"model_name": tt.get("model_name") or "", "available": 0, "total": 0})
            bucket["total"] += 1
            if tool.get("status") == "available":
                bucket["available"] += 1

        items = [
            CatalogItemAvailability(
                catalog_item_id=UUID(type_id),
                name=data["model_name"],
                quantity_available=data["available"],
                quantity_total=data["total"],
            )
            for type_id, data in counts.items()
            if availability != "available" or data["available"] > 0
        ]
        return WarehouseCatalogResponse(warehouse_id=warehouse_id, items=items)

    def get_tool_requisition_status(
        self,
        *,
        requisition_id: UUID | None,
        cmms_request_id: UUID | None,
        cmms_schedule_id: UUID | None,
        fields: str,
    ) -> ToolRequisitionStatusResponse:
        query = (
            self._supabase.table(TABLE_REQUISITIONS)
            .select(
                "id, warehouse_id, status, created_at, cancelled_at, cancel_reason, "
                "warehouses(name), "
                "cmms_work_order_links(cancelled_by, cancel_reason_text), "
                "requisition_lines(status)"
            )
        )
        if requisition_id:
            query = query.eq("id", str(requisition_id))
        elif cmms_request_id:
            query = query.eq("external_order_id", str(cmms_request_id))
        elif cmms_schedule_id:
            query = query.eq("external_order_id", str(cmms_schedule_id))
        else:
            raise HTTPException(status_code=400, detail="Missing query parameter")

        resp = execute_supabase(lambda: query.execute())
        rows = resp.data or []
        requisitions = [self._map_status_summary(row) for row in rows]
        return ToolRequisitionStatusResponse(requisitions=requisitions)

    def _map_status_summary(self, row: dict[str, Any]) -> RequisitionStatusSummary:
        warehouse = row.get("warehouses") or {}
        if isinstance(warehouse, list):
            warehouse = warehouse[0] if warehouse else {}
        link = row.get("cmms_work_order_links") or {}
        if isinstance(link, list):
            link = link[0] if link else {}
        lines = row.get("requisition_lines") or []
        status_value = derive_requisition_status(lines, row.get("cancelled_at"))
        return RequisitionStatusSummary(
            requisition_id=row["id"],
            warehouse_id=row["warehouse_id"],
            warehouse_name=warehouse.get("name") or "",
            status=status_value,
            cancelled_at=row.get("cancelled_at"),
            cancelled_by=link.get("cancelled_by"),
            cancel_reason=row.get("cancel_reason"),
            cancel_reason_text=link.get("cancel_reason_text"),
            lines_summary=_lines_summary(lines),
        )

    def repair_request_status_webhook(self, payload: RepairRequestStatusWebhook) -> WebhookAckResponse:
        tool_id = self._resolve_tool_id(payload)
        if not tool_id:
            return WebhookAckResponse(ok=True)

        new_status = payload.new_status
        previous_status = payload.previous_status

        if new_status == "in_progress":
            self._set_tool_status_if(tool_id, "pending_repair", "maintenance")
            return WebhookAckResponse(ok=True)

        terminal = {"closed", "rejected", "cancelled"}
        if new_status not in terminal:
            return WebhookAckResponse(ok=True)

        if previous_status in {"new", "accepted"}:
            target = "available"
        else:
            target = "pending_return"

        execute_supabase(
            lambda: self._supabase.table(TABLE_TOOLS)
            .update({"status": target})
            .eq("id", str(tool_id))
            .execute()
        )
        return WebhookAckResponse(ok=True)

    def _resolve_tool_id(self, payload: RepairRequestStatusWebhook) -> str | None:
        repair_resp = execute_supabase(
            lambda: self._supabase.table(TABLE_CMMS_REPAIR)
            .select("tool_id")
            .eq("cmms_request_id", str(payload.request_id))
            .maybe_single()
            .execute()
        )
        if repair_resp.data:
            return repair_resp.data["tool_id"]
        lookup_id = getattr(payload, "inventory_id", None) or payload.tool_id
        tool_resp = execute_supabase(
            lambda: self._supabase.table(TABLE_TOOLS)
            .select("id")
            .eq("id", str(lookup_id))
            .maybe_single()
            .execute()
        )
        if not tool_resp.data:
            return None
        return tool_resp.data["id"]

    def _set_tool_status_if(self, tool_id: str, expected: str, target: str) -> None:
        tool_resp = execute_supabase(
            lambda: self._supabase.table(TABLE_TOOLS)
            .select("status")
            .eq("id", str(tool_id))
            .maybe_single()
            .execute()
        )
        if not tool_resp.data or tool_resp.data.get("status") != expected:
            return
        execute_supabase(
            lambda: self._supabase.table(TABLE_TOOLS)
            .update({"status": target})
            .eq("id", str(tool_id))
            .execute()
        )
