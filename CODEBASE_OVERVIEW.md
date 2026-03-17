# RAG PDF Chatbot - Codebase Overview

## Tổng quan

Repo này là một hệ thống **RAG (Retrieval-Augmented Generation) cho PDF** theo hướng “chuẩn/đơn giản”:

- **Không dùng thị giác máy tính** (không OCR/vision/multimodal trong luồng chính)
- **Không dùng điều phối nhiều agent / task planner**
- Luồng chính: **PDF → trích xuất text → chunking → embeddings → vector search → LLM trả lời/tóm tắt + trích dẫn trang**

## Luồng xử lý chính (end-to-end)

```
Upload PDF
  → Extract text by page
  → Split into chunks
  → Embed chunks
  → Store vectors (Milvus or other backend)

Query
  → Embed query
  → Vector search (filter by doc_id)
  → Build context (include page numbers)
  → LLM generates answer/summary grounded in context
```

## Cấu trúc thư mục (thực tế trong repo)

```
backend/app/
├── main.py                     # FastAPI entrypoint
├── core/                       # Config + utilities
├── providers/                  # LLM providers + embedding provider
├── storage/                    # Vector DB backends (Milvus, ...)
├── models/                     # Document/query models (and conversation helpers)
├── ai/                         # RAG pipeline (retrieve + build context + call LLM)
└── routers/                    # /api/upload, /api/chat

frontend/                       # Next.js UI (upload + chat + sources)
```

## Những điểm cần lưu ý

- **PDF scan (ít text)**: hệ thống chỉ cảnh báo “có thể là scan” (không tự OCR). Kết quả RAG sẽ kém nếu PDF không có text layer.
- **`backend/app/documents/`**: thư mục legacy (không nằm trong luồng hiện tại); luồng upload/index đang ở `backend/app/routers/upload.py`.

## Tài liệu liên quan

- `ARCHITECTURE.md`: kiến trúc chi tiết repo hiện tại
- `QUICKSTART.md`: chạy nhanh backend + Milvus + test API
