from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.endpoints import admin, analytics, auth, integration, master, pages, reports, requisitions, tools
from app.core.config import get_settings


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
    app.include_router(integration.router, prefix="/api/v1")

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

    return app


app = create_app()
