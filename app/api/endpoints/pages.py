from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from markupsafe import Markup

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase import Client

from app.api.deps import get_current_user, get_current_user_optional
from app.core.db_utils import execute_supabase
from app.core.helpers import normalize_join
from app.core.requisition_status import derive_requisition_status
from app.core.status_labels import (
    requisition_line_status_label,
    requisition_status_label,
    tool_status_label,
)
from app.core.supabase import get_supabase_client
from app.models.schemas import CurrentUser, UserRole

router = APIRouter(tags=["pages"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _json_default(value: Any) -> str:
    """Сериализует UUID в строку для json.dumps."""
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _tojson_filter(value: Any) -> Markup:
    """Jinja2-фильтр: безопасный JSON для встраивания в HTML."""
    return Markup(json.dumps(value, ensure_ascii=False, default=_json_default))


templates.env.filters["tojson"] = _tojson_filter
templates.env.filters["requisition_status_label"] = requisition_status_label
templates.env.filters["requisition_line_status_label"] = requisition_line_status_label
templates.env.filters["tool_status_label"] = tool_status_label

TABLE_TOOLS = "tools"
TABLE_REQUISITIONS = "requisitions"
TABLE_WAREHOUSES = "warehouses"
TABLE_TOOL_TYPES = "tool_types"
TABLE_CMMS_REPAIR_LINKS = "cmms_repair_links"


def _role_home(user: CurrentUser) -> str:
    """URL главной страницы после входа."""
    return "/"


def _role_work_url(user: CurrentUser) -> str:
    """URL рабочего раздела по роли пользователя."""
    if user.role == UserRole.ADMIN.value:
        return "/admin/users"
    if user.role == UserRole.CLERK.value:
        return "/inventory"
    return "/analytics"


def _load_admin_dashboard(supabase: Client) -> dict[str, Any]:
    """Загружает сводку для главной страницы администратора."""
    users_resp = execute_supabase(lambda: supabase.table("users").select("id", count="exact").execute())
    wh_resp = execute_supabase(lambda: supabase.table(TABLE_WAREHOUSES).select("id", count="exact").execute())
    req_resp = execute_supabase(
        lambda: supabase.table(TABLE_REQUISITIONS)
        .select("id, status, created_at, warehouses(name), cmms_work_order_links(technician_name)")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    activity: list[dict[str, str]] = []
    for req in req_resp.data or []:
        wh = normalize_join(req.get("warehouses"))
        link = normalize_join(req.get("cmms_work_order_links"))
        created = str(req.get("created_at") or "")[:16].replace("T", " ")
        activity.append(
            {
                "time": created or "—",
                "text": f"Заявка {requisition_status_label(req.get('status'))} · {link.get('technician_name') or '—'} · {wh.get('name') or '—'}",
            }
        )
    return {
        "users_count": users_resp.count or len(users_resp.data or []),
        "warehouses_count": wh_resp.count or len(wh_resp.data or []),
        "activity_log": activity,
    }


def _load_clerk_dashboard(supabase: Client, user: CurrentUser) -> dict[str, Any]:
    """Загружает сводку для главной страницы кладовщика."""
    today = date.today().isoformat()
    wh_filter = str(user.warehouse_id) if user.warehouse_id else None

    req_query = supabase.table(TABLE_REQUISITIONS).select("id, status, created_at, cmms_work_order_links(requisition_id)")
    if wh_filter:
        req_query = req_query.eq("warehouse_id", wh_filter)
    reqs = execute_supabase(lambda: req_query.execute()).data or []

    issued_today = sum(
        1 for r in reqs if r.get("status") == "issued" and str(r.get("created_at") or "").startswith(today)
    )
    cmms_pending = sum(
        1
        for r in reqs
        if normalize_join(r.get("cmms_work_order_links"))
        and r.get("status") not in {"returned", "cancelled"}
    )

    tools_query = supabase.table(TABLE_TOOLS).select("id", count="exact").eq("status", "in_use")
    if wh_filter:
        tools_query = tools_query.eq("warehouse_id", wh_filter)
    in_use_resp = execute_supabase(lambda: tools_query.execute())

    return {
        "issued_today": issued_today,
        "awaiting_return": in_use_resp.count or len(in_use_resp.data or []),
        "cmms_pending": cmms_pending,
    }


def _page_context(user: CurrentUser, **extra: Any) -> dict[str, Any]:
    """Формирует базовый контекст шаблона с флагами прав доступа."""
    can_edit = user.role in {UserRole.CLERK.value, UserRole.MASTER.value}
    can_send_to_cmms = user.role in {UserRole.CLERK.value, UserRole.MASTER.value}
    return {
        "user": user,
        "is_admin": user.role == UserRole.ADMIN.value,
        "is_clerk": user.role == UserRole.CLERK.value,
        "is_master": user.role == UserRole.MASTER.value,
        "can_edit_tools": can_edit,
        "can_delete_tools": user.role == UserRole.MASTER.value,
        "can_add_tools": can_edit,
        "can_send_to_cmms": can_send_to_cmms,
        **extra,
    }


def _require_roles(user: CurrentUser, *roles: str) -> None:
    """Проверяет, что роль пользователя входит в разрешённые."""
    if user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")


def _load_warehouses(supabase: Client, user: CurrentUser) -> list[dict[str, Any]]:
    """Загружает склады; для кладовщика — только его склад."""
    query = (
        supabase.table(TABLE_WAREHOUSES)
        .select("id, name, location_id, locations(name)")
        .order("name")
    )
    if user.role == UserRole.CLERK.value and user.warehouse_id:
        query = query.eq("id", str(user.warehouse_id))
    response = execute_supabase(lambda: query.execute())
    return response.data or []


def _load_tool_types(supabase: Client) -> list[dict[str, Any]]:
    """Загружает типы инструментов с категориями."""
    response = execute_supabase(
        lambda: supabase.table(TABLE_TOOL_TYPES)
        .select("id, model_name, min_stock, category_id, tool_categories(id, name)")
        .order("model_name")
        .execute()
    )
    return response.data or []


def _load_categories(supabase: Client) -> list[dict[str, Any]]:
    """Загружает категории инструментов."""
    response = execute_supabase(
        lambda: supabase.table("tool_categories").select("id, name").order("name").execute()
    )
    return response.data or []


def _load_locations(supabase: Client) -> list[dict[str, Any]]:
    """Загружает локации (площадки)."""
    response = execute_supabase(
        lambda: supabase.table("locations").select("id, name").order("name").execute()
    )
    return response.data or []


def _load_users(supabase: Client) -> list[dict[str, Any]]:
    """Загружает пользователей с данными сотрудников и складов."""
    response = execute_supabase(
        lambda: supabase.table("users")
        .select(
            "id, login, role, employee_id, warehouse_id, created_at, "
            "employees(full_name, locations(name)), warehouses(name)"
        )
        .order("login")
        .execute()
    )
    return response.data or []


def _load_employees(supabase: Client) -> list[dict[str, Any]]:
    """Загружает сотрудников с привязкой к локациям."""
    response = execute_supabase(
        lambda: supabase.table("employees")
        .select("id, full_name, badge_number, location_id, locations(id, name)")
        .order("full_name")
        .execute()
    )
    return response.data or []


def _normalize_requisition_row(row: dict[str, Any]) -> dict[str, Any]:
    """Приводит embed-поля заявки (dict/list) к плоским dict для Jinja2."""
    normalized = dict(row)
    normalized["warehouses"] = normalize_join(row.get("warehouses"))
    normalized["cmms_work_order_links"] = normalize_join(row.get("cmms_work_order_links"))
    lines: list[dict[str, Any]] = []
    for line in row.get("requisition_lines") or []:
        ln = dict(line)
        ln["tools"] = normalize_join(line.get("tools"))
        ln["tool_types"] = normalize_join(line.get("tool_types"))
        lines.append(ln)
    normalized["requisition_lines"] = lines
    normalized["status"] = derive_requisition_status(lines, row.get("cancelled_at"))
    return normalized


def _load_requisitions(
    supabase: Client,
    user: CurrentUser,
    *,
    cmms: bool,
) -> list[dict[str, Any]]:
    """Загружает заявки (CMMS или внутренние) с учётом склада кладовщика."""
    select_fields = (
        "id, client_reference_id, warehouse_id, status, "
        "created_at, cancelled_at, cancel_reason, "
        "warehouses(name), "
        "cmms_work_order_links(work_order_kind, cmms_work_order_number, technician_name, technician_badge, "
        "cancelled_by, cancel_reason_text), "
        "requisition_lines("
        "id, line_client_id, catalog_item_id, tool_id, status, condition_on_return, "
        "tools(id, inventory_number, serial_number, status), "
        "tool_types(model_name)"
        ")"
    )
    query = supabase.table(TABLE_REQUISITIONS).select(select_fields).order("created_at", desc=True)

    if cmms:
        query = query.not_.is_("cmms_work_order_links", "null")
    else:
        query = query.is_("cmms_work_order_links", "null")

    if user.role == UserRole.CLERK.value and user.warehouse_id:
        query = query.eq("warehouse_id", str(user.warehouse_id))

    response = execute_supabase(lambda: query.execute())
    return [_normalize_requisition_row(row) for row in (response.data or [])]


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_page(
    request: Request,
    current_user: Annotated[CurrentUser | None, Depends(get_current_user_optional)],
) -> HTMLResponse | RedirectResponse:
    """Страница входа; авторизованных перенаправляет на главную."""
    if current_user is not None:
        return RedirectResponse(url=_role_home(current_user), status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": request.query_params.get("error")},
    )


@router.get("/", response_class=HTMLResponse, response_model=None)
def home_page(
    request: Request,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> HTMLResponse:
    """Главная страница с дашбордом по роли пользователя."""
    extra: dict[str, Any] = {"work_url": _role_work_url(current_user)}
    if current_user.role == UserRole.ADMIN.value:
        extra["dashboard"] = _load_admin_dashboard(supabase)
    elif current_user.role == UserRole.CLERK.value:
        extra["dashboard"] = _load_clerk_dashboard(supabase, current_user)
    else:
        extra["dashboard"] = {}

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context=_page_context(current_user, **extra),
    )


@router.get("/inventory", response_class=HTMLResponse, response_model=None)
def inventory_page(
    request: Request,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    warehouse_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> HTMLResponse:
    """Страница инвентаря инструментов с фильтрами по складу и статусу."""
    _require_roles(
        current_user,
        UserRole.ADMIN.value,
        UserRole.CLERK.value,
        UserRole.MASTER.value,
    )

    query = (
        supabase.table(TABLE_TOOLS)
        .select(
            "id, type_id, inventory_number, serial_number, status, wear_count, "
            "last_check, warehouse_id, "
            "tool_types(id, model_name, tool_categories(name)), "
            "warehouses(name), "
            "cmms_repair_links(cmms_request_id, cmms_request_number, handoff_mode, handoff_status)"
        )
        .order("inventory_number")
    )

    if current_user.role == UserRole.CLERK.value and current_user.warehouse_id:
        query = query.eq("warehouse_id", str(current_user.warehouse_id))
    elif warehouse_id is not None:
        query = query.eq("warehouse_id", str(warehouse_id))

    if status_filter:
        query = query.eq("status", status_filter)

    response = execute_supabase(lambda: query.execute())
    warehouses = _load_warehouses(supabase, current_user)

    employees: list[dict[str, Any]] = []
    if current_user.role == UserRole.CLERK.value:
        employees_response = execute_supabase(
            lambda: supabase.table("employees")
            .select("*, locations(name)")
            .order("full_name")
            .execute()
        )
        employees = employees_response.data or []

    return templates.TemplateResponse(
        request=request,
        name="inventory.html",
        context=_page_context(
            current_user,
            tools=response.data or [],
            warehouses=warehouses,
            tool_types=_load_tool_types(supabase) if current_user.role != UserRole.ADMIN.value else [],
            selected_warehouse=str(warehouse_id) if warehouse_id else "",
            selected_status=status_filter or "",
            read_only=current_user.role == UserRole.ADMIN.value,
            employees=employees,
        ),
    )


@router.get("/inventory/{tool_id}/cmms-repair", response_class=HTMLResponse, response_model=None)
def inventory_cmms_repair_page(
    request: Request,
    tool_id: UUID,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> HTMLResponse:
    """Детали заявки ТОиР и отчётов по инструменту (контур А, только чтение)."""
    _require_roles(
        current_user,
        UserRole.ADMIN.value,
        UserRole.CLERK.value,
        UserRole.MASTER.value,
    )

    tool_resp = execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .select(
            "id, inventory_number, serial_number, status, warehouse_id, "
            "tool_types(model_name), warehouses(name), "
            "cmms_repair_links(id, cmms_request_id, cmms_request_number, client_reference_id)"
        )
        .eq("id", str(tool_id))
        .maybe_single()
        .execute()
    )
    tool = tool_resp.data
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Инструмент не найден")

    if current_user.role == UserRole.CLERK.value and current_user.warehouse_id:
        if str(tool.get("warehouse_id")) != str(current_user.warehouse_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    cmms_link_raw = tool.get("cmms_repair_links")
    if cmms_link_raw is None:
        cmms_link: dict[str, Any] | None = None
    elif isinstance(cmms_link_raw, list):
        cmms_link = cmms_link_raw[0] if cmms_link_raw else None
    else:
        cmms_link = cmms_link_raw

    if not cmms_link or not cmms_link.get("cmms_request_id"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Для этого инструмента нет связи с заявкой ТОиР",
        )

    from app.core.config import get_settings
    from app.integration.cmms_client import CmmsRepairClientError, create_cmms_repair_client

    settings = get_settings()
    client = create_cmms_repair_client(settings)
    cmms_error: str | None = None
    cmms_request: dict[str, Any] | None = None
    work_reports: list[dict[str, Any]] = []

    try:
        cmms_request = client.get_inventory_request_by_inventory_id(tool_id)
        work_reports = client.list_inventory_work_reports(tool_id)
    except CmmsRepairClientError as exc:
        cmms_error = exc.message

    return templates.TemplateResponse(
        request=request,
        name="cmms_repair_detail.html",
        context=_page_context(
            current_user,
            tool=tool,
            cmms_link=cmms_link,
            cmms_request=cmms_request,
            work_reports=work_reports,
            cmms_error=cmms_error,
            integration_mode=(settings.cmms_integration_mode or "mock").lower(),
        ),
    )


@router.get("/requisitions", response_class=HTMLResponse, response_model=None)
def requisitions_page(
    request: Request,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> HTMLResponse:
    """Страница заявок на выдачу инструментов (CMMS и внутренние)."""
    _require_roles(current_user, UserRole.CLERK.value)

    cmms_requisitions = _load_requisitions(supabase, current_user, cmms=True)
    internal_requisitions = _load_requisitions(supabase, current_user, cmms=False)

    warehouse_filter = None
    if current_user.warehouse_id:
        warehouse_filter = str(current_user.warehouse_id)

    tools_query = (
        supabase.table(TABLE_TOOLS)
        .select("id, type_id, inventory_number, serial_number, warehouse_id, status, tool_types(model_name)")
        .eq("status", "available")
        .order("inventory_number")
    )
    if warehouse_filter:
        tools_query = tools_query.eq("warehouse_id", warehouse_filter)

    available_tools_raw = execute_supabase(lambda: tools_query.execute()).data or []
    available_tools = [
        {
            **tool,
            "tool_types": normalize_join(tool.get("tool_types")),
        }
        for tool in available_tools_raw
    ]

    return templates.TemplateResponse(
        request=request,
        name="requisitions.html",
        context=_page_context(
            current_user,
            cmms_requisitions=cmms_requisitions,
            internal_requisitions=internal_requisitions,
            available_tools=available_tools,
        ),
    )


@router.get("/analytics", response_class=HTMLResponse, response_model=None)
def analytics_page(
    request: Request,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> HTMLResponse:
    """Страница аналитики со списком списанных инструментов."""
    _require_roles(current_user, UserRole.MASTER.value, UserRole.ADMIN.value)

    scrapped_resp = execute_supabase(
        lambda: supabase.table(TABLE_TOOLS)
        .select("id, inventory_number, serial_number, last_check, tool_types(model_name)")
        .eq("status", "scrapped")
        .order("last_check", desc=True)
        .limit(100)
        .execute()
    )

    return templates.TemplateResponse(
        request=request,
        name="analytics.html",
        context=_page_context(
            current_user,
            warehouses=_load_warehouses(supabase, current_user),
            scrapped_tools=scrapped_resp.data or [],
        ),
    )


@router.get("/admin/users", response_class=HTMLResponse, response_model=None)
def admin_users_page(
    request: Request,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> HTMLResponse:
    """Админ-страница управления пользователями."""
    _require_roles(current_user, UserRole.ADMIN.value)

    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context=_page_context(
            current_user,
            users=_load_users(supabase),
            employees=_load_employees(supabase),
            warehouses=_load_warehouses(supabase, current_user),
        ),
    )


@router.get("/admin/structure", response_class=HTMLResponse, response_model=None)
def admin_structure_page(
    request: Request,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> HTMLResponse:
    """Админ-страница структуры: локации и склады."""
    _require_roles(current_user, UserRole.ADMIN.value)

    return templates.TemplateResponse(
        request=request,
        name="admin/structure.html",
        context=_page_context(
            current_user,
            locations=_load_locations(supabase),
            warehouses=_load_warehouses(supabase, current_user),
        ),
    )


@router.get("/master/catalog", response_class=HTMLResponse, response_model=None)
def master_catalog_page(
    request: Request,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> HTMLResponse:
    """Страница каталога типов инструментов и категорий."""
    _require_roles(current_user, UserRole.MASTER.value, UserRole.ADMIN.value)

    return templates.TemplateResponse(
        request=request,
        name="master/catalog.html",
        context=_page_context(
            current_user,
            categories=_load_categories(supabase),
            tool_types=_load_tool_types(supabase),
            catalog_admin_mode=current_user.role == UserRole.ADMIN.value,
        ),
    )


@router.get("/master/structure", response_class=HTMLResponse, response_model=None)
def master_structure_page(
    request: Request,
    supabase: Annotated[Client, Depends(get_supabase_client)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> HTMLResponse:
    """Страница структуры складов для мастера."""
    _require_roles(current_user, UserRole.MASTER.value, UserRole.ADMIN.value)

    return templates.TemplateResponse(
        request=request,
        name="master/structure.html",
        context=_page_context(
            current_user,
            locations=_load_locations(supabase),
            warehouses=_load_warehouses(supabase, current_user),
        ),
    )
