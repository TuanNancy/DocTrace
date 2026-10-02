"""
FastAPI entry point, CORS, and routers.
"""
from contextlib import asynccontextmanager
from anyio import CapacityLimiter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import chat, upload, documents
from app.core.config import get_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.upload_limiter = CapacityLimiter(get_config().upload_max_concurrent)
    yield

app = FastAPI(
    title="RAG PDF Chatbot API",
    description="Upload PDFs and chat with indexed content.",
    version="0.1.0",
    lifespan=lifespan,
)

allowed_origins = list(get_config().cors_allow_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(chat.router)
app.include_router(documents.router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Process liveness only; do not call remote/paid services from health checks."""
    return {"status": "ok"}
