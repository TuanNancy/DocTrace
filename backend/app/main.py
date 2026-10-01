"""
FastAPI entry point, CORS, and routers.
"""
import os
from contextlib import asynccontextmanager
from anyio import CapacityLimiter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import chat, upload
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

raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001")
allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(chat.router)


@app.get("/health", tags=["health"])
async def health():
    """Liveness only: do not probe paid upstream services on every health check."""
    return {"status": "ok"}
