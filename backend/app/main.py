"""
FastAPI entry point, CORS, and routers.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import upload

app = FastAPI(
    title="RAG PDF Chatbot API",
    description="Upload PDFs and chat with indexed content.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
