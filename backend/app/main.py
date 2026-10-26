"""
FastAPI entry point, CORS, and routers.
"""
from contextlib import asynccontextmanager
from anyio import CapacityLimiter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import chat, upload, documents
from app.core.config import get_config
from app.core.observability import RequestContextMiddleware, configure_logging
from app.db import dispose_engines
from app.services.readiness import readiness


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.upload_limiter = CapacityLimiter(get_config().upload_max_concurrent)
    try:
        yield
    finally:
        dispose_engines()

app = FastAPI(
    title="RAG PDF Chatbot API",
    description="Upload PDFs and chat with indexed content.",
    version="0.1.0",
    lifespan=lifespan,
)

configure_logging(get_config())
allowed_origins = list(get_config().cors_allow_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After", "X-Request-ID"],
)
app.add_middleware(RequestContextMiddleware)

app.include_router(upload.router)
app.include_router(chat.router)
app.include_router(documents.router)


@app.get("/ready", tags=["health"])
async def ready() -> JSONResponse:
    """Dependencies required by workspace requests; never calls paid services."""
    status, checks = await readiness()
    return JSONResponse(
        {"status": status, "checks": checks},
        status_code=200 if status == "ok" else 503,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Process liveness only; do not call remote/paid services from health checks."""
    return {"status": "ok"}
