"""Аналитические JSON API: пенсионеры, статистика, просроченная поверка."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from supabase import Client

from app.api.deps import require_master_or_admin
from app.core.db_utils import execute_supabase
from app.core.helpers import normalize_join
from app.core.supabase import get_supabase_client
from app.models.schemas import (
    CurrentUser,
    EmployeeGender,
    OverdueCalibrationResponse,
    OverdueCalibrationTool,
    PensionerEmployee,
    PensionersByDepartment,
    PensionersResponse,
    ToolCategoryStat,
    ToolStatsResponse,
    ToolStatus,
    YoungWornTool,
    YoungWornToolsResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

CALIBRATION_INTERVAL_DAYS = 365
PENSION_AGE_FEMALE = 55
NIL_UUID = UUID("00000000-0000-0000-0000-000000000000")


def _calc_age(birth_date: date, on: date | None = None) -> int:
    """Возраст сотрудника в полных годах на указанную дату."""
    on = on or date.today()
    return on.year - birth_date.year - ((on.month, on.day) < (birth_date.month, birth_date.day))


def _parse_date(value: str | None) -> date | None:
    """Парсит дату ISO из строки Supabase."""
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _normalize_join(value: Any) -> dict[str, Any]:
    """Алиас для совместимости; делегирует в app.core.helpers.normalize_join."""
    return normalize_join(value)


def _is_measuring_category(name: str | None) -> bool:
    if not name:
        return False
    lowered = name.lower()
    return "мерит" in lowered or "измер" in lowered


def _is_calibration_overdue(last_check: date | None, today: date) -> tuple[bool, int]:
    if last_check is None:
        return False, 0
    next_due = last_check + timedelta(days=CALIBRATION_INTERVAL_DAYS)
    if today <= next_due:
        return False, 0
    return True, (today - next_due).days


def _safe_status(value: str | None) -> ToolStatus:
    try:
        return ToolStatus(value) if value else ToolStatus.AVAILABLE
    except ValueError:
        return ToolStatus.AVAILABLE


def _row_to_overdue_tool(row: dict[str, Any], tool_type: dict[str, Any], days_overdue: int) -> OverdueCalibrationTool:
    category = _normalize_join(tool_type.get("tms_tool_categories"))
    return OverdueCalibrationTool(
        id=UUID(str(row["id"])),
        type_id=UUID(str(row["type_id"])),
        warehouse_id=UUID(str(row["warehouse_id"])),
        inventory_number=row.get("inventory_number"),
        serial_number=row.get("serial_number"),
        status=_safe_status(row.get("status")),
        wear_count=int(row.get("wear_count") or 0),
        last_check=_parse_date(row.get("last_check")),
        type_name=tool_type.get("model_name"),
        category_name=category.get("name"),
        days_overdue=days_overdue,
    )


@router.get("/pensioners", response_model=PensionersResponse)
def get_pensioners(
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> PensionersResponse:
    """Сотрудницы 55 лет и старше на текущую дату."""
    today = date.today()
    # Граница по году рождения: в 2026 — все, кто родился в 1971 году и раньше
    birth_date_cutoff = date(today.year - PENSION_AGE_FEMALE, 12, 31)

    response = execute_supabase(
        lambda: supabase.table("tms_employees")
        .select("id, badge_number, full_name, birth_date, gender, location_id, tms_locations(id, name)")
        .eq("gender", EmployeeGender.FEMALE.value)
        .not_.is_("birth_date", "null")
        .lte("birth_date", birth_date_cutoff.isoformat())
        .execute()
    )

    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"employees": [], "location_name": ""})

    for row in response.data or []:
        birth_date = _parse_date(row.get("birth_date"))
        if birth_date is None:
            continue
        age = _calc_age(birth_date, today)
        if age < PENSION_AGE_FEMALE:
            continue

        location_data = _normalize_join(row.get("tms_locations"))
        location_id = UUID(str(row["location_id"])) if row.get("location_id") else NIL_UUID
        location_name = location_data.get("name") or "Без подразделения"
        key = str(location_id)

        grouped[key]["location_id"] = location_id
        grouped[key]["location_name"] = location_name
        grouped[key]["employees"].append(
            PensionerEmployee(
                id=UUID(str(row["id"])),
                badge_number=str(row.get("badge_number") or ""),
                full_name=str(row.get("full_name") or ""),
                birth_date=birth_date,
                age=age,
            )
        )

    departments_list = [
        PensionersByDepartment(
            location_id=item["location_id"],
            location_name=item["location_name"],
            employees=sorted(item["employees"], key=lambda emp: emp.full_name),
        )
        for item in grouped.values()
        if item["employees"]
    ]

    total = sum(len(dept.employees) for dept in departments_list)

    return PensionersResponse(
        year=today.year,
        departments=sorted(departments_list, key=lambda item: item.location_name),
        total=total,
    )


@router.get("/tool-stats", response_model=ToolStatsResponse)
def get_tool_stats(
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> ToolStatsResponse:
    """Распределение инструментов по категориям (количество и доля %)."""
    tools_response = execute_supabase(
        lambda: supabase.table("tms_tools")
        .select("id, tms_tool_types(category_id, tms_tool_categories(id, name))")
        .execute()
    )
    tools = tools_response.data or []
    total = len(tools)
    if total == 0:
        return ToolStatsResponse(total_tools=0, categories=[])

    category_counts: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "name": "Без категории"})

    for tool in tools:
        tool_type = _normalize_join(tool.get("tms_tool_types"))
        category = _normalize_join(tool_type.get("tms_tool_categories"))
        category_id = str(category.get("id") or "unknown")
        category_name = category.get("name") or "Без категории"
        category_counts[category_id]["count"] += 1
        category_counts[category_id]["name"] = category_name

    categories = [
        ToolCategoryStat(
            category_id=UUID(cat_id) if cat_id != "unknown" else NIL_UUID,
            category_name=data["name"],
            tool_count=data["count"],
            percentage=round(data["count"] / total * 100, 2),
        )
        for cat_id, data in category_counts.items()
    ]
    categories.sort(key=lambda item: item.percentage, reverse=True)

    return ToolStatsResponse(total_tools=total, categories=categories)


@router.get("/overdue-calibration", response_model=OverdueCalibrationResponse)
def get_overdue_calibration(
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> OverdueCalibrationResponse:
    """Мерительный инструмент с просроченной поверкой (интервал 365 дней)."""
    today = date.today()

    response = execute_supabase(
        lambda: supabase.table("tms_tools")
        .select("id, type_id, warehouse_id, inventory_number, serial_number, status, wear_count, last_check, tms_tool_types(model_name, tms_tool_categories(name))")
        .neq("status", "scrapped")
        .not_.is_("last_check", "null")
        .order("last_check")
        .execute()
    )

    tools: list[OverdueCalibrationTool] = []
    for row in response.data or []:
        if not row.get("type_id") or not row.get("warehouse_id"):
            continue

        tool_type = _normalize_join(row.get("tms_tool_types"))
        category_name = _normalize_join(tool_type.get("tms_tool_categories")).get("name")

        if not _is_measuring_category(category_name):
            continue

        last_check = _parse_date(row.get("last_check"))
        overdue, days_overdue = _is_calibration_overdue(last_check, today)
        if not overdue or last_check is None:
            continue

        tools.append(_row_to_overdue_tool(row, tool_type, days_overdue))

    return OverdueCalibrationResponse(as_of=today, tools=tools, total=len(tools))


@router.get("/young-worn-tools", response_model=YoungWornToolsResponse)
def get_young_worn_tools(
    supabase: Annotated[Client, Depends(get_supabase_client)],
    _: Annotated[CurrentUser, Depends(require_master_or_admin)],
) -> YoungWornToolsResponse:
    """Инструмент с износом >50 и сроком эксплуатации от 365 дней."""
    response = execute_supabase(
        lambda: supabase.table("tms_tools")
        .select("id, type_id, warehouse_id, inventory_number, serial_number, status, wear_count, last_check, tms_tool_types(model_name)")
        .gt("wear_count", 50)
        .execute()
    )

    today = date.today()
    tools: list[YoungWornTool] = []
    for row in response.data or []:
        if not row.get("type_id") or not row.get("warehouse_id"):
            continue

        last_check = _parse_date(row.get("last_check"))
        age_days = (today - last_check).days if last_check else 0
        if last_check and age_days < 365:
            continue

        tool_type = _normalize_join(row.get("tms_tool_types"))
        tools.append(
            YoungWornTool(
                id=UUID(str(row["id"])),
                type_id=UUID(str(row["type_id"])),
                warehouse_id=UUID(str(row["warehouse_id"])),
                inventory_number=row.get("inventory_number"),
                serial_number=row.get("serial_number"),
                status=_safe_status(row.get("status")),
                wear_count=int(row.get("wear_count") or 0),
                last_check=last_check,
                type_name=tool_type.get("model_name"),
                age_days=age_days,
            )
        )

    tools.sort(key=lambda item: item.wear_count, reverse=True)
    return YoungWornToolsResponse(tools=tools, total=len(tools))
