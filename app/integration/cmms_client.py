from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

import httpx

from app.models.schemas import RepairRequestCreate, RepairRequestResponse


class CmmsRepairClientError(Exception):
    """Ошибка вызова CMMS REP-API-1 с HTTP-кодом для маппинга в FastAPI."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ICmmsRepairClient(Protocol):
    def create_repair_request(self, payload: RepairRequestCreate) -> RepairRequestResponse: ...

    def confirm_inventory_received(
        self, request_id: UUID, inventory_id: UUID, handed_over_at: datetime | None = None
    ) -> dict[str, Any]: ...

    def list_repair_departments(self) -> list[dict[str, Any]]: ...

    def get_inventory_request_by_inventory_id(
        self, inventory_id: UUID
    ) -> dict[str, Any] | None: ...

    def list_inventory_work_reports(self, inventory_id: UUID) -> list[dict[str, Any]]: ...


_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

REP_API_CREATE_REQUEST_FUNCTION = "integration-tms-create-request"
REP_API_INVENTORY_RECEIVED_FUNCTION = "integration-tms-inventory-received"

_CMMS_KNOWN_ERRORS: dict[str, str] = {
    "Function not found": (
        "Edge Function ТОиР «integration-tms-create-request» не зарегистрирована. "
        "В CMMS выполните `supabase stop` и `supabase start` (не `supabase functions serve admin-users`). "
        "Проверьте CMMS_FUNCTIONS_URL=http://127.0.0.1:54321/functions/v1."
    ),
    "Unauthorized": "Не авторизован при обращении к ТОиР. Проверьте CMMS_INTEGRATION_SECRET.",
    "Forbidden": "Доступ к ТОиР запрещён: неверный секрет интеграции (CMMS_INTEGRATION_SECRET).",
    "Open inventory request already exists": (
        "В ТОиР уже есть открытая заявка на этот инструмент. Повторная отправка невозможна."
    ),
    "Server configuration error": "Ошибка конфигурации сервера ТОиР (Edge Function).",
    "No integration requester configured": (
        "В ТОиР не настроен пользователь-заявитель интеграции (CMMS_INTEGRATION_REQUESTER_ID)."
    ),
    "target_repair_department_id required": (
        "В ТОиР не найден активный ремонтный отдел. Создайте отдел в CMMS или укажите target_repair_department_id."
    ),
    "Invalid JSON body": "Некорректное тело запроса к ТОиР.",
    "client_reference_id, inventory_id and title are required": (
        "ТОиР отклонил запрос: не указаны обязательные поля (client_reference_id, inventory_id, title)."
    ),
    "Method not allowed": "Неверный HTTP-метод при обращении к ТОиР.",
}


def _extract_response_detail(response: httpx.Response) -> str | None:
    """Извлекает текст ошибки из JSON или plain-text ответа CMMS/Kong."""
    try:
        payload = response.json()
    except Exception:
        text = (response.text or "").strip()
        return text[:500] if text else None

    if isinstance(payload, str):
        trimmed = payload.strip()
        return trimmed or None

    if not isinstance(payload, dict):
        return None

    for key in ("error", "detail", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("message") or value.get("error") or value.get("detail")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _default_message_for_status(status_code: int, *, context: str) -> str:
    if status_code in {401, 403}:
        return (
            f"{context}: ошибка авторизации ТОиР. "
            "Проверьте CMMS_INTEGRATION_SECRET и CMMS_SUPABASE_KEY."
        )
    if status_code == 404:
        return (
            f"{context}: Edge Function «{REP_API_CREATE_REQUEST_FUNCTION}» не найдена. "
            "Проверьте CMMS_FUNCTIONS_URL (должен быть …/functions/v1, без имени функции) "
            "и что в CMMS запущены все Edge Functions (`supabase stop` → `supabase start`)."
        )
    if status_code == 409:
        return "В ТОиР уже есть открытая заявка на этот инструмент. Повторная отправка невозможна."
    if status_code in {502, 503, 504}:
        return (
            f"{context}: сервис ТОиР недоступен. "
            "Убедитесь, что Supabase CMMS запущен (supabase start) и Edge Functions доступны."
        )
    if status_code >= 500:
        return f"{context}: внутренняя ошибка ТОиР."
    if status_code >= 400:
        return f"{context}: запрос отклонён ТОиР (код {status_code})."
    return context


def _map_cmms_error(raw: str | None, status_code: int, *, context: str) -> str:
    if raw:
        mapped = _CMMS_KNOWN_ERRORS.get(raw.strip())
        if mapped:
            return mapped
        return raw.strip()
    return _default_message_for_status(status_code, context=context)


def _http_error_to_cmms_error(
    exc: httpx.HTTPStatusError,
    *,
    context: str,
) -> CmmsRepairClientError:
    response = exc.response
    raw_detail = _extract_response_detail(response)
    message = _map_cmms_error(raw_detail, response.status_code, context=context)
    if raw_detail and message == raw_detail and not message.startswith(context):
        message = f"{context}: {raw_detail}"
    return CmmsRepairClientError(message, status_code=response.status_code)


def _request_error_to_cmms_error(exc: httpx.RequestError, *, context: str) -> CmmsRepairClientError:
    if isinstance(exc, httpx.TimeoutException):
        return CmmsRepairClientError(
            f"{context}: ТОиР не ответил вовремя. Проверьте CMMS_FUNCTIONS_URL и доступность CMMS.",
            status_code=504,
        )
    return CmmsRepairClientError(
        f"{context}: не удалось подключиться к ТОиР. "
        "Проверьте, что Supabase CMMS запущен и CMMS_FUNCTIONS_URL указан верно.",
        status_code=503,
    )


def _parse_repair_response(data: Any) -> RepairRequestResponse:
    if not isinstance(data, dict):
        raise CmmsRepairClientError("ТОиР вернул некорректный ответ", status_code=502)
    try:
        return RepairRequestResponse(
            request_id=UUID(str(data["request_id"])),
            request_number=str(data["request_number"]),
            status=str(data["status"]),
            created_at=data["created_at"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CmmsRepairClientError(
            f"ТОиР вернул неполный ответ: {exc}",
            status_code=502,
        ) from exc


def _load_fixture_list(name: str) -> list[dict[str, Any]]:
    path = _FIXTURES_DIR / name
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise CmmsRepairClientError(f"Fixture {name} must be a JSON array", status_code=500)
    return data


_OPEN_INVENTORY_STATUSES = frozenset({"closed", "rejected", "cancelled"})


class MockCmmsRepairClient:
    def create_repair_request(self, payload: RepairRequestCreate) -> RepairRequestResponse:
        inv = str(payload.tool_id)
        for row in _load_fixture_list("inventory_requests.json"):
            if str(row.get("inventory_id")) != inv:
                continue
            status = str(row.get("status") or "").strip().lower()
            if status and status not in _OPEN_INVENTORY_STATUSES:
                raise CmmsRepairClientError(
                    _CMMS_KNOWN_ERRORS["Open inventory request already exists"],
                    status_code=409,
                )
            break

        path = _FIXTURES_DIR / "create_repair_request_response.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return RepairRequestResponse(
            request_id=UUID(data["request_id"]),
            request_number=data["request_number"],
            status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
        )

    def list_repair_departments(self) -> list[dict[str, Any]]:
        return _load_fixture_list("repair_departments.json")

    def confirm_inventory_received(
        self, request_id: UUID, inventory_id: UUID, handed_over_at: datetime | None = None
    ) -> dict[str, Any]:
        return {
            "request_id": str(request_id),
            "status": "in_progress",
            "inventory_received_at": (handed_over_at or datetime.now(tz=UTC)).isoformat(),
        }

    def get_inventory_request_by_inventory_id(
        self, inventory_id: UUID
    ) -> dict[str, Any] | None:
        inv = str(inventory_id)
        for row in _load_fixture_list("inventory_requests.json"):
            if str(row.get("inventory_id")) == inv:
                return row
        return None

    def list_inventory_work_reports(self, inventory_id: UUID) -> list[dict[str, Any]]:
        inv = str(inventory_id)
        return [
            row
            for row in _load_fixture_list("inventory_work_reports.json")
            if str(row.get("inventory_id")) == inv
        ]


def _enum_value(value: StrEnum | str) -> str:
    return value if isinstance(value, str) else value.value


def _resolve_create_request_url(functions_url: str) -> str:
    """Собирает URL REP-API-1 из базы …/functions/v1 (без имени функции в env)."""
    base = functions_url.strip().rstrip("/")
    suffix = f"/{REP_API_CREATE_REQUEST_FUNCTION}"
    if base.endswith(suffix):
        return base
    if base.endswith("/functions/v1/integration-tms-create-request/"):
        return base.rstrip("/")
    return base + suffix


def _resolve_inventory_received_url(functions_url: str) -> str:
    base = functions_url.strip().rstrip("/")
    suffix = f"/{REP_API_INVENTORY_RECEIVED_FUNCTION}"
    if base.endswith(suffix):
        return base
    return base + suffix


class SupabaseCmmsRepairClient:
    def __init__(self, rest_url: str, functions_url: str, integration_secret: str, supabase_key: str) -> None:
        self._rest_url = rest_url.rstrip("/")
        self._url = _resolve_create_request_url(functions_url)
        self._inventory_received_url = _resolve_inventory_received_url(functions_url)
        self._secret = integration_secret
        self._key = supabase_key

    def _integration_headers(self) -> dict[str, str]:
        return {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Accept-Profile": "integration",
        }

    def create_repair_request(self, payload: RepairRequestCreate) -> RepairRequestResponse:
        body = {
            "schema_version": 1,
            "client_reference_id": str(payload.client_reference_id),
            "inventory_id": str(payload.tool_id),
            "inventory_kind": "tool",
            "inventory_name": payload.tool_name,
            "inventory_serial": payload.tool_serial,
            "inventory_type_name": payload.tool_type_name,
            "request_type": _enum_value(payload.request_type),
            "title": payload.title,
            "description": payload.description,
            "target_repair_department_id": str(payload.target_repair_department_id),
            "inventory_handoff_mode": _enum_value(payload.inventory_handoff_mode),
            "inventory_warehouse_name": payload.inventory_warehouse_name,
        }
        headers = {
            "Authorization": f"Bearer {self._secret}",
            "apikey": self._key,
            "Content-Type": "application/json",
        }
        context = "Не удалось создать заявку в ТОиР"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(self._url, json=body, headers=headers)
                if response.status_code == 409:
                    raw = _extract_response_detail(response)
                    message = _map_cmms_error(raw, 409, context=context)
                    raise CmmsRepairClientError(message, status_code=409)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise _http_error_to_cmms_error(exc, context=context) from exc
                try:
                    data = response.json()
                except json.JSONDecodeError as exc:
                    raise CmmsRepairClientError(
                        f"{context}: ТОиР вернул не-JSON ответ",
                        status_code=502,
                    ) from exc
        except httpx.RequestError as exc:
            raise _request_error_to_cmms_error(exc, context=context) from exc

        return _parse_repair_response(data)

    def confirm_inventory_received(
        self, request_id: UUID, inventory_id: UUID, handed_over_at: datetime | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema_version": 1,
            "request_id": str(request_id),
            "inventory_id": str(inventory_id),
        }
        if handed_over_at is not None:
            body["handed_over_at"] = handed_over_at.isoformat()
        headers = {
            "Authorization": f"Bearer {self._secret}",
            "apikey": self._key,
            "Content-Type": "application/json",
        }
        context = "Не удалось подтвердить передачу инструмента в ТОиР"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(self._inventory_received_url, json=body, headers=headers)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise _http_error_to_cmms_error(exc, context=context) from exc
                try:
                    data = response.json()
                except json.JSONDecodeError as exc:
                    raise CmmsRepairClientError(
                        f"{context}: ТОиР вернул не-JSON ответ",
                        status_code=502,
                    ) from exc
        except httpx.RequestError as exc:
            raise _request_error_to_cmms_error(exc, context=context) from exc
        return data if isinstance(data, dict) else {}

    def list_repair_departments(self) -> list[dict[str, Any]]:
        url = f"{self._rest_url}/v_repair_departments"
        params = {"order": "name.asc"}
        context = "Не удалось загрузить список отделов ТОиР"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=params, headers=self._integration_headers())
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise _http_error_to_cmms_error(exc, context=context) from exc
                rows = response.json()
        except httpx.RequestError as exc:
            raise _request_error_to_cmms_error(exc, context=context) from exc
        return rows if isinstance(rows, list) else []

    def get_inventory_request_by_inventory_id(
        self, inventory_id: UUID
    ) -> dict[str, Any] | None:
        url = f"{self._rest_url}/v_inventory_requests"
        params = {"inventory_id": f"eq.{inventory_id}", "limit": "1"}
        context = "Не удалось загрузить заявку из ТОиР"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=params, headers=self._integration_headers())
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise _http_error_to_cmms_error(exc, context=context) from exc
                rows = response.json()
        except httpx.RequestError as exc:
            raise _request_error_to_cmms_error(exc, context=context) from exc
        if not rows:
            return None
        return rows[0]

    def list_inventory_work_reports(self, inventory_id: UUID) -> list[dict[str, Any]]:
        url = f"{self._rest_url}/v_inventory_work_reports"
        params = {
            "inventory_id": f"eq.{inventory_id}",
            "order": "created_at.desc",
        }
        context = "Не удалось загрузить отчёты из ТОиР"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=params, headers=self._integration_headers())
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise _http_error_to_cmms_error(exc, context=context) from exc
                rows = response.json()
        except httpx.RequestError as exc:
            raise _request_error_to_cmms_error(exc, context=context) from exc
        return rows if isinstance(rows, list) else []


def create_cmms_repair_client(settings) -> ICmmsRepairClient:
    mode = (getattr(settings, "cmms_integration_mode", None) or "mock").lower()
    if mode == "live":
        functions_url = (getattr(settings, "cmms_functions_url", None) or "").strip()
        integration_secret = (getattr(settings, "cmms_integration_secret", None) or "").strip()
        supabase_key = (getattr(settings, "cmms_supabase_key", None) or "").strip()
        supabase_url = (getattr(settings, "cmms_supabase_url", None) or "").strip()

        if not functions_url:
            raise CmmsRepairClientError(
                "Интеграция с ТОиР не настроена: не указан CMMS_FUNCTIONS_URL.",
                status_code=503,
            )
        if not integration_secret:
            raise CmmsRepairClientError(
                "Интеграция с ТОиР не настроена: не указан CMMS_INTEGRATION_SECRET.",
                status_code=503,
            )
        if not supabase_key:
            raise CmmsRepairClientError(
                "Интеграция с ТОиР не настроена: не указан CMMS_SUPABASE_KEY.",
                status_code=503,
            )
        if not supabase_url:
            raise CmmsRepairClientError(
                "Интеграция с ТОиР не настроена: не указан CMMS_SUPABASE_URL.",
                status_code=503,
            )

        rest_url = supabase_url.rstrip("/") + "/rest/v1"
        return SupabaseCmmsRepairClient(
            rest_url,
            functions_url,
            integration_secret,
            supabase_key,
        )
    return MockCmmsRepairClient()
