"""DropBack API: FastAPI app assembly.

Routes live in app/routes, business logic in app/services, response shapes in
app/serializers.py, and sessions/access checks in app/security.py.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.bootstrap import startup
from app.config import get_settings
from app.mcp_server import BearerProtectedMCP, build_mcp
from app.routes import auth, buyer, catalog, checkout, merchant, setup, system, webhooks

logging.basicConfig(level=logging.INFO)
settings = get_settings()
CSRF_EXEMPT = {"/api/v1/webhooks/paypal", "/api/v1/webhooks/channel3"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup()
    mcp = build_mcp()
    app.state.mcp_http = mcp.streamable_http_app()
    async with mcp.session_manager.run():
        yield
    app.state.mcp_http = None


app = FastAPI(title="DropBack", version="1.1.0", docs_url="/api/docs" if not settings.is_production else None, redoc_url=None, lifespan=lifespan)
app.state.mcp_http = None
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "Idempotency-Key"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Cookie-authenticated writes must come from an allowed origin (CSRF defence in depth).
    if request.method in {"POST", "PATCH", "DELETE"} and request.url.path.startswith("/api/v1/") and request.url.path not in CSRF_EXEMPT:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in {item.rstrip("/") for item in settings.cors_origins}:
            return JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


for module in (system, auth, setup, catalog, checkout, buyer, merchant, webhooks):
    app.include_router(module.router)

app.mount("/mcp", BearerProtectedMCP(lambda: app.state.mcp_http))

# Single-service deployment (Render / root Dockerfile): serve the built React app from the API.
_static = Path(settings.static_dir).resolve() if settings.static_dir else None
if _static and (_static / "index.html").is_file():
    if (_static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith(("api/", "mcp")):
            raise HTTPException(404, "Not found.")
        candidate = (_static / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(_static):
            return FileResponse(candidate)
        return FileResponse(_static / "index.html", headers={"Cache-Control": "no-cache"})


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
