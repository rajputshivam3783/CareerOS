"""CareerOS API entrypoint — FastAPI app wiring, middleware, and lifespan."""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

import app.models.domain  # noqa: F401 — registers models on Base.metadata
import app.search.models  # noqa: F401 — V21.1 registers search_index_documents/search_query_logs on Base.metadata
import app.reliability.models  # noqa: F401 — V25.5 registers failed_job_records on Base.metadata
from app.api.routes import router
from app.core.config import settings
from app.core.hardening import (
    api_security_headers,
    production_config_findings,
    safe_equals,
    sanitize_request_id,
)
from app.core.logging import configure_logging
from app.core.metrics import record_request, render_prometheus_text
from app.core.request_context import get_request_id, set_client_ip, set_request_id
from app.core.url_guard import install_url_guards
from app.db.base import Base
from app.db.session import engine
from app.scheduler import start_scheduler, stop_scheduler

configure_logging()
logger = logging.getLogger("careeros")

# V25.6: drop javascript:/data:/... URLs from every URL-like column, whatever path wrote them.
install_url_guards(Base)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed in production if deployment secrets/config are unsafe. Rules live in
    # app.core.hardening.production_config_findings so they are unit-tested in isolation
    # (V25.6: also rejects .env.example placeholders, wildcard CORS, and test-only flags).
    if settings.is_production:
        _errors, _warnings = production_config_findings(
            jwt_secret=settings.jwt_secret,
            admin_api_key=settings.admin_api_key,
            database_url=settings.database_url,
            smtp_host=settings.smtp_host,
            smtp_from_email=settings.smtp_from_email,
            cors_origins=settings.cors_origins,
            auto_verify_email_in_tests=settings.auto_verify_email_in_tests,
            email_mode=settings.email_mode,
        )
        for _w in _warnings:
            logger.warning("Production configuration warning: %s", _w)
        if _errors:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(_errors))
    Base.metadata.create_all(bind=engine)
    # V19.4 — seed default notification templates (idempotent: only
    # inserts keys that don't already exist, never overwrites an
    # admin's edits — see notification_templates.seed_default_templates).
    from app.db.session import SessionLocal
    from app.services.notification_templates import seed_default_templates

    _seed_db = SessionLocal()
    try:
        seed_default_templates(_seed_db)
    finally:
        _seed_db.close()

    # V20.1 — seed default AI prompt templates (idempotent, same
    # pattern as notification templates above).
    from app.ai.prompt_service import seed_default_prompts

    _seed_ai_db = SessionLocal()
    try:
        seed_default_prompts(_seed_ai_db)
    finally:
        _seed_ai_db.close()

    # V20.5 — seed the canonical skill catalog (idempotent, same
    # pattern as the two seeders above).
    from app.skill_intelligence.catalog import seed_skills

    _seed_skills_db = SessionLocal()
    try:
        seed_skills(_seed_skills_db)
    finally:
        _seed_skills_db.close()
    logger.info("CareerOS API started (env=%s)", settings.environment)
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("CareerOS API shutting down")


app = FastAPI(
    title=settings.app_name,
    version="25.6.0",
    description="CareerOS production-oriented career opportunity and hiring platform",
    lifespan=lifespan,
    # Hide interactive docs outside local/dev to reduce attack surface.
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

@app.middleware("http")
async def request_context_and_metrics(request: Request, call_next):
    """V16 — added first so it's the outermost middleware: it must see
    every request (including ones later middleware might reject) to
    assign a request ID and record metrics for it.

    Accepts an inbound X-Request-ID so a reverse proxy or calling
    service can propagate its own trace ID end-to-end; generates one
    otherwise. The ID is stashed in a contextvar (app.core.
    request_context) so it's available to the logging formatter,
    error handlers and app.core.audit.log_audit without threading it
    through every function signature, and echoed back in the response
    header so a client can correlate a failed request with server-side
    logs when reporting a bug.
    """
    # V25.6: an inbound id is only propagated if it is a short, boring token
    # (it ends up in logs, audit rows and a response header).
    request_id = sanitize_request_id(request.headers.get("X-Request-ID"), lambda: uuid.uuid4().hex)
    set_request_id(request_id)
    set_client_ip(request.client.host if request.client else None)

    route_template = request.url.path
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match.value == 2:  # Match.FULL
            route_template = getattr(route, "path", route_template)
            break

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        record_request(request.method, route_template, 500, time.perf_counter() - started)
        raise
    record_request(request.method, route_template, response.status_code, time.perf_counter() - started)
    response.headers["X-Request-ID"] = request_id
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    # V25.6: explicit lists instead of "*" — this API only uses these verbs/headers.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "X-Request-ID", "X-Partner-Id", "X-Partner-Key"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# V25.2 — maintenance mode. Registered here so it runs INSIDE the
# request-context/metrics middleware (which must see every request,
# including a blocked one) but before routing, so a maintenance
# response never touches a route handler. Platform admins, auth and
# health endpoints are exempt — see app.core.maintenance.
@app.middleware("http")
async def maintenance_mode(request: Request, call_next):
    from app.core.maintenance import maintenance_mode_middleware

    return await maintenance_mode_middleware(request, call_next)


_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Security headers for every API response.

    V25.6: the API returns JSON and attachments only, so its CSP is ``default-src 'none'``
    (the previous policy allowed 'unsafe-inline'/'unsafe-eval' and any https: connect
    target, which protects nothing on a JSON API). The interactive docs (development
    only) load Swagger UI assets and are exempt from the CSP. Responses to requests that
    carried credentials are marked ``Cache-Control: no-store`` so shared caches never keep
    per-user data; public, unauthenticated GETs keep their existing caching behaviour."""
    response = await call_next(request)
    for name, value in api_security_headers(is_production=settings.is_production).items():
        if name == "Content-Security-Policy" and request.url.path in _DOC_PATHS:
            continue
        response.headers.setdefault(name, value)
    if request.headers.get("authorization") or request.headers.get("x-admin-key"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Return a stable, minimal shape for bad input (avoids echoing
    internal pydantic error objects verbatim to the client).

    exc.errors() can include a raw exception object in an error's
    ``ctx`` (Pydantic puts the original exception there whenever a
    custom @field_validator/@model_validator raises ValueError with a
    message — a common, ordinary pattern used throughout this API).
    JSONResponse can't serialize that directly and would raise
    TypeError from inside this handler itself, turning what should be
    a clean 422 into an unhandled 500 — jsonable_encoder sanitizes it.
    """
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid request data", "errors": jsonable_encoder(exc.errors()), "request_id": get_request_id()},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """Never leak stack traces or internals to the client; log them
    server-side instead so they're debuggable without exposing them."""
    if isinstance(exc, HTTPException):
        # Let FastAPI's default handling deal with intentional HTTP errors.
        raise exc
    logger.exception("Unhandled error on %s %s [request_id=%s]", request.method, request.url.path, get_request_id())
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": get_request_id()})


app.include_router(router, prefix="/api/v1")


@app.get("/")
def root():
    return {"name": "CareerOS API", "version": "25.6.0", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "healthy", "version": "25.6.0"}


@app.get("/ready")
def ready():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok"}


@app.get("/live")
def live():
    """V16 liveness probe, distinct from /ready on purpose: an
    orchestrator should restart a process that fails this (event loop
    wedged) but not one that only fails /ready (DB temporarily down)
    -- that would kill a healthy process during a brief DB blip. Does
    no I/O, so it can only fail if the process itself can't respond."""
    return {"status": "alive"}


@app.get("/metrics")
def metrics(request: Request):
    """V16 Prometheus text-exposition endpoint. See app.core.metrics
    for what's tracked and the tradeoffs of the in-memory approach.

    V25.6: not public in production. Configure ``METRICS_TOKEN`` and scrape with
    ``Authorization: Bearer <token>``. With no token configured the endpoint is disabled
    (403) in production and left open in development/test."""
    if settings.metrics_token:
        supplied = request.headers.get("authorization", "")
        if not supplied.lower().startswith("bearer ") or not safe_equals(supplied[7:].strip(), settings.metrics_token):
            raise HTTPException(status_code=401, detail="Metrics authentication required")
    elif settings.is_production:
        raise HTTPException(status_code=403, detail="Metrics endpoint is disabled; set METRICS_TOKEN to enable it")
    return PlainTextResponse(render_prometheus_text(), media_type="text/plain; version=0.0.4")
