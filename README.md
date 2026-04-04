# 🔴 Baymax — RAG PDF Chatbot

Chatbot RAG (Retrieval-Augmented Generation) cho phép **upload file PDF và đặt câu hỏi trực tiếp trên nội dung tài liệu**, với câu trả lời được stream realtime kèm trích dẫn nguồn.

---

## 🚀 Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python, FastAPI, Uvicorn |
| **LLM** | OpenRouter (chat completions, streaming) |
| **Embeddings** | OpenRouter (`/v1/embeddings`) |
| **Vector DB** | Milvus Standalone (pymilvus) |
| **PDF Processing** | LangChain (PyPDFLoader + RecursiveCharacterTextSplitter) |
| **Auth** | Supabase Auth (JWT verification) |
| **PDF Storage** | Supabase Storage (S3-compatible, boto3) |
| **Frontend** | Next.js 14 (App Router), React 18, TypeScript |
| **Styling** | Tailwind CSS, dark mode |
| **Infra** | Docker Compose (etcd, MinIO, Milvus, Attu) |
| **Testing** | pytest, pytest-asyncio |

---

## 📁 Cấu trúc thư mục

```
RAG-PDF-chatbot/
├── .env                          # Environment config (API keys, Milvus, Supabase)
├── docker-compose.yml            # Milvus stack (etcd, minio, milvus, attu)
├── README.md                     # Tài liệu này
│
├── backend/
│   ├── .env                      # Backend env (override root .env)
│   ├── requirements.txt          # Python dependencies
│   ├── pytest.ini                # Pytest config
│   │
│   ├── app/
│   │   ├── main.py               # FastAPI entrypoint, CORS, mount routers
│   │   ├── schemas.py            # Pydantic request models (ChatRequest)
│   │   │
│   │   ├── core/
│   │   │   ├── config.py         # RAGConfig dataclass + env loading + singleton
│   │   │   └── auth.py           # Supabase JWT verification (Bearer token)
│   │   │
│   │   ├── routers/
│   │   │   ├── upload.py         # POST /api/upload — PDF upload + indexing pipeline
│   │   │   └── chat.py           # POST /api/chat — SSE streaming chat
│   │   │
│   │   ├── processors/
│   │   │   └── pdf.py            # PDF loading (PyPDFLoader) + chunking
│   │   │
│   │   ├── providers/
│   │   │   ├── base.py           # Abstract BaseProvider interface (LLM ops)
│   │   │   ├── openrouter.py     # OpenRouter implementation (AsyncOpenAI)
│   │   │   ├── embeddings.py     # OpenAIEmbedder via OpenRouter /v1/embeddings
│   │   │   └── factory.py        # create_provider() factory
│   │   │
│   │   ├── storage/
│   │   │   ├── base.py           # Abstract BaseStorage + RetrievedChunk/InsertResult
│   │   │   ├── milvus_storage.py # Milvus implementation (pymilvus)
│   │   │   └── factory.py        # StorageFactory + create_storage helpers
│   │   │
│   │   ├── ai/
│   │   │   ├── prompts.py        # System prompts (VI + EN) + PromptTemplates
│   │   │   └── rag_agent.py      # RAGAgent: retrieve → build context → stream LLM
│   │   │
│   │   ├── models/
│   │   │   └── document.py       # DocumentStatus, IndexingResult
│   │   │
│   │   └── services/
│   │       └── supabase_pdf_storage.py  # PDF backup to Supabase S3 (boto3)
│   │
│   ├── tests/
│   │   ├── conftest.py           # Pytest fixtures (TestClient, auth override)
│   │   ├── test_upload.py        # 8 tests — upload validation + mocked pipeline
│   │   └── test_chat.py          # 4 tests — chat validation + mocked SSE
│   │
│   └── scripts/
│       ├── test_chunking.py      # Manual chunking test
│       └── test_retrieval.py     # Manual retrieval test
│
├── frontend/
│   ├── .env.local                # Frontend env (API URL, Supabase)
│   ├── package.json              # Next.js 14 + React 18 + Supabase + Tailwind
│   ├── tsconfig.json             # TypeScript config (paths: @/* → src/*)
│   ├── tailwind.config.ts        # Tailwind config (darkMode: "class")
│   │
│   └── src/
│       ├── middleware.ts          # Next.js edge middleware (auth redirect)
│       │
│       ├── types/
│       │   └── index.ts           # TypeScript types (UploadResponse, ChatSource, ChatMessage, SSEEvent)
│       │
│       ├── lib/
│       │   ├── api.ts             # streamChat(), uploadPDF(), streamChatSSEParser()
│       │   ├── client.ts          # Supabase browser client
│       │   ├── server.ts          # Supabase server client (cookie-based)
│       │   ├── middleware.ts      # updateSession() for auth redirect
│       │   └── utils.ts           # cn() — clsx + tailwind-merge
│       │
│       ├── app/
│       │   ├── layout.tsx         # Root layout (Inter font, metadata)
│       │   ├── globals.css        # Tailwind + CSS variables
│       │   ├── page.tsx           # Landing page (hero, features, how-it-works)
│       │   ├── loading.tsx        # Global loading spinner
│       │   ├── error.tsx          # Global error boundary
│       │   │
│       │   ├── chat/
│       │   │   └── page.tsx       # Main chat page (sidebar, upload, chat window)
│       │   │
│       │   ├── auth/
│       │   │   ├── actions.ts     # Server actions: loginAction, signupAction
│       │   │   ├── login/page.tsx        # Login page
│       │   │   ├── signup/page.tsx       # Signup page
│       │   │   ├── callback/route.ts     # OAuth callback handler
│       │   │   └── auth-code-error/page.tsx
│       │   │
│       │   └── brand/logo/route.ts       # GET /brand/logo — serves logo image
│       │
│       └── components/
│           ├── BrandMark.tsx             # Logo + branding
│           ├── ThemeToggle.tsx           # Dark/light mode toggle
│           ├── UploadZone.tsx            # PDF drag-drop upload
│           ├── ChatWindow.tsx            # Chat UI with SSE streaming
│           ├── SourceCard.tsx            # Single citation card
│           ├── SourceCardList.tsx        # List of source cards
│           ├── StreamingCursor.tsx       # Blinking cursor animation
│           └── auth/
│               ├── LoginForms.tsx        # Email/password + Google OAuth
│               ├── SignupForm.tsx        # Full name + email/password
│               └── AuthSubmitButton.tsx  # Submit button with pending state
```

---

## 🔧 Cấu hình môi trường

### Backend `.env`

Tạo file `.env` tại **root** project:

```bash
# OpenRouter (chat + embeddings)
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
RAG_MODEL=google/gemini-2.0-flash-lite-001
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
EMBEDDING_DIMENSION=4096

# Milvus
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=pdf_chunks
MILVUS_VECTOR_DIM=4096

# Upload
UPLOAD_MAX_SIZE_MB=50

# Supabase Auth
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=eyJ...

# Supabase Storage (S3-compatible) — PDF backup
SUPABASE_S3_ENDPOINT=https://your-project.storage.supabase.co/storage/v1/s3
SUPABASE_S3_REGION=ap-southeast-2
SUPABASE_S3_ACCESS_KEY_ID=...
SUPABASE_S3_SECRET_ACCESS_KEY=...
SUPABASE_STORAGE_BUCKET=pdfs

# Chunking
CHUNK_SIZE=1000
CHUNK_OVERLAP=150
```

### Frontend `.env.local`

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY=eyJ...
```

---

## 🐳 Chạy Milvus stack bằng Docker

```bash
# Tạo thư mục dữ liệu
mkdir -p volumes/etcd volumes/minio volumes/milvus

# Khởi động
docker compose up -d

# Kiểm tra
docker compose ps
docker compose logs -f milvus
```

Attu UI: `http://localhost:8001`

---

## ▶️ Chạy project

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API docs: `http://localhost:8000/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Mở `http://localhost:3000`

---

## 🔄 Luồng xử lý

### Upload Pipeline

```
User upload PDF → POST /api/upload
  │
  ├─ 1. Xác thực Supabase JWT (Bearer token)
  ├─ 2. Validate: content-type, extension, size ≤ 50MB
  ├─ 3. Upload PDF gốc lên Supabase S3 (boto3, non-blocking)
  ├─ 4. load_pdf_pages() → PyPDFLoader (phát hiện scanned PDF)
  ├─ 5. chunk_documents() → RecursiveCharacterTextSplitter (1000/150)
  ├─ 6. Embed chunks → OpenRouter embeddings (batch 2048)
  ├─ 7. ensure_collection() → Tạo Milvus collection nếu chưa có
  └─ 8. insert_chunks() → Batch insert vào Milvus (64/batch)

Response: { doc_id, chunks_count, processing_time, warnings, pdf_storage_key }
```

### Chat Pipeline (SSE Streaming)

```
User gửi câu hỏi → POST /api/chat
  │
  ├─ 1. Xác thực Supabase JWT
  ├─ 2. Validate query + doc_id
  ├─ 3. RAGAgent._retrieve_chunks()
  │     ├─ Embed query → OpenRouter
  │     └─ search_chunks() → Milvus (top_k=8, min_score=0.32)
  │
  ├─ 4. SSE "sources" → [{page, source, score}, ...]
  ├─ 5. Nếu không có chunks → Fallback message (VI/EN)
  ├─ 6. _build_context() → "[Trang X] (độ liên quan: Y)\n{nội dung}"
  ├─ 7. provider.stream_with_context() → OpenRouter chat (stream=True)
  ├─ 8. SSE "token" → từng token từ LLM
  └─ 9. SSE "done" → hoàn thành
```

---

## 🔌 API Endpoints

### `POST /api/upload`

- **Content-Type**: `multipart/form-data`
- **Headers**: `Authorization: Bearer <supabase_access_token>`
- **Field**: `file` (PDF, max 50MB)
- **Response**:

```json
{
  "doc_id": "uuid",
  "name": "document.pdf",
  "chunks_count": 123,
  "status": "completed",
  "processing_time": 5.432,
  "created_at": "2024-01-01T00:00:00",
  "warnings": ["Possible scanned PDF..."],
  "pdf_storage_key": "user_id/doc_id/document.pdf"
}
```

### `POST /api/chat`

- **Content-Type**: `application/json`
- **Headers**: `Authorization: Bearer <supabase_access_token>`
- **Body**:

```json
{
  "query": "Câu hỏi của bạn?",
  "doc_id": "uuid",
  "language": "vi"
}
```

- **Response**: `text/event-stream` với các event:
  - `sources` — JSON array `{page, source, score}`
  - `token` — từng token từ LLM
  - `error` — `{ "message": "..." }`
  - `done` — `[DONE]`

---

## 🏗️ Kiến trúc

### Design Patterns

| Pattern | Áp dụng |
|---------|---------|
| **Factory** | `create_provider()`, `StorageFactory`, `create_rag_agent_with_defaults()` |
| **Strategy** | `BaseProvider` → `OpenRouterProvider`, `BaseStorage` → `MilvusStorage` |
| **Singleton** | `get_config()`, `get_embedder()` (@lru_cache) |
| **Dependency Injection** | FastAPI `Depends(require_supabase_user)` |
| **Streaming/Generator** | SSE events, LLM token streaming, SSE parser |
| **Observer** | Supabase `onAuthStateChange` subscription |

### Phân lớp Backend

```
routers/ (API endpoints, auth, validation)
    │
    ├── ai/rag_agent.py (orchestration: retrieve → context → LLM)
    │       ├── providers/ (LLM + embeddings)
    │       └── storage/ (vector DB)
    │
    └── processors/ (PDF extraction + chunking)
```

---

## 🧪 Testing

```bash
cd backend
pytest -v
```

12 tests: 8 upload (validation + mocked pipeline), 4 chat (validation + mocked SSE).

---

## 📌 Ghi chú

- **Không commit `.env`** — chứa API keys thực
- **CORS** — đang cho phép `localhost:3000/3001`, cần giới hạn khi deploy
- **Single-turn chat** — mỗi query độc lập, không lưu lịch sử hội thoại
- **Single-document** — chỉ hỗ trợ 1 `doc_id` mỗi phiên chat

---

## 🌍 English Summary

**Baymax** is a Retrieval-Augmented Generation chatbot for PDFs. The backend (FastAPI) handles PDF upload, text extraction, chunking, embedding, and vector storage in Milvus, then uses OpenRouter for streaming LLM answers over Server-Sent Events (SSE). The frontend (Next.js 14) provides a modern UI with Supabase authentication, drag-drop PDF upload, real-time streaming chat, and cited source cards with page numbers.
