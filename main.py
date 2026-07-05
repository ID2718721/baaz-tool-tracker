from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import httpx

from app.api.endpoints import admin, analytics, auth, integration_cmms, master, pages, reports, requisitions, tools
from app.core.config import get_settings
from app.integration.cmms_client import CmmsRepairClientError

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class TMSJSONResponse(JSONResponse):
    """JSON-ответ с явной сериализацией UUID и дат в строки."""

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            default=_json_default,
        ).encode("utf-8")


def create_app() -> FastAPI:
    settings = get_settings()
    print(f"SUPABASE_URL={settings.supabase_url}")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        default_response_class=TMSJSONResponse,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(master.router, prefix="/api/v1")
    app.include_router(tools.router, prefix="/api/v1")
    app.include_router(requisitions.router, prefix="/api/v1")
    app.include_router(analytics.router, prefix="/api/v1")
    app.include_router(reports.router, prefix="/api/v1")
    app.include_router(integration_cmms.router, prefix="/api/v1")

    @app.get("/health", tags=["system"])
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    @app.exception_handler(HTTPException)
    async def html_auth_redirect(request: Request, exc: HTTPException) -> JSONResponse | RedirectResponse:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            if exc.status_code == 401:
                redirect = RedirectResponse(url="/login", status_code=302)
                redirect.delete_cookie(
                    key=settings.access_token_cookie_name,
                    path="/",
                    httponly=True,
                    secure=settings.cookie_secure,
                    samesite=settings.cookie_samesite,
                )
                return redirect
            if exc.status_code == 403:
                return RedirectResponse(url="/login?error=Недостаточно+прав", status_code=302)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.exception_handler(CmmsRepairClientError)
    async def cmms_client_error_handler(
        request: Request, exc: CmmsRepairClientError
    ) -> JSONResponse:
        logger.warning("CMMS client error on %s: %s", request.url.path, exc.message)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, StarletteHTTPException):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        if isinstance(exc, httpx.RequestError):
            logger.warning("Upstream HTTP error on %s: %s", request.url.path, exc)
            detail = (
                f"Сервис недоступен: {exc}"
                if settings.debug
                else "Внешний сервис недоступен. Проверьте подключение и настройки интеграции."
            )
            return JSONResponse(status_code=503, content={"detail": detail})
        logger.exception("Unhandled error on %s", request.url.path)
        detail = str(exc) if settings.debug else "Internal server error"
        return JSONResponse(
            status_code=500,
            content={"detail": detail, "type": type(exc).__name__},
        )

    return app


app = create_app()
