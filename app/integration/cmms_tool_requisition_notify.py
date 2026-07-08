"""Уведомление CMMS (ISS-EVT-1) о смене статуса заявки на инструменты."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from supabase import Client

from app.core.config import get_settings
from app.core.db_utils import execute_supabase, first_row
from app.core.requisition_status import derive_requisition_status
from app.integration.cmms_client import CmmsRepairClientError, create_cmms_repair_client

logger = logging.getLogger(__name__)

TABLE_REQUISITIONS = "requisitions"
TABLE_REQUISITION_LINES = "requisition_lines"


def _load_requisition_status(supabase: Client, requisition_id: str) -> str | None:
    req_resp = execute_supabase(
        lambda: supabase.table(TABLE_REQUISITIONS)
        .select("cancelled_at")
        .eq("id", requisition_id)
        .execute()
    )
    req_row = first_row(req_resp, detail="Заявка не найдена")
    lines_resp = execute_supabase(
        lambda: supabase.table(TABLE_REQUISITION_LINES)
        .select("status")
        .eq("requisition_id", requisition_id)
        .execute()
    )
    lines: list[dict[str, Any]] = lines_resp.data or []
    if not lines and not req_row.get("cancelled_at"):
        return None
    return derive_requisition_status(lines, req_row.get("cancelled_at"))


def notify_cmms_tool_requisition_status(
    supabase: Client,
    requisition_id: str | UUID,
    *,
    previous_status: str | None = None,
    status: str | None = None,
) -> None:
    """Отправляет ISS-EVT-1 в CMMS; ошибки логируются и не пробрасываются."""
    rid = str(requisition_id)
    try:
        derived = status or _load_requisition_status(supabase, rid)
        if not derived:
            return

        settings = get_settings()
        mode = (settings.cmms_integration_mode or "mock").lower()
        if mode != "live":
            return

        client = create_cmms_repair_client(settings)
        client.notify_tool_requisition_status(
            UUID(rid),
            derived,
            previous_status=previous_status,
        )
    except CmmsRepairClientError as exc:
        logger.warning(
            "ISS-EVT-1 failed for requisition %s: %s",
            rid,
            exc.message,
        )
    except Exception:
        logger.exception("ISS-EVT-1 unexpected error for requisition %s", rid)
