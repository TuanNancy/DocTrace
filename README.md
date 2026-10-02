# 🔴 DocTrace — Document Q&A with source citations

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
| **API deployment** | Docker FastAPI + Nginx reverse proxy + Certbot HTTPS |
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
│   │   │   ├── config.py         # AppConfig dataclass + env loading + singleton
│   │   │   └── auth.py           # Supabase JWT verification (Bearer token)
│   │   │
│   │   ├── routers/
│   │   │   ├── upload.py         # POST /api/upload — auth, validation, gọi indexing service
│   │   │   └── chat.py           # POST /api/chat — SSE streaming chat
│   │   │
│   │   ├── processors/
│   │   │   └── pdf.py            # PDF loading (PyPDFLoader) + chunking
│   │   │
│   │   ├── providers/
│   │   │   ├── base.py           # ChatProvider: generate/stream chat completions
│   │   │   ├── openrouter.py     # OpenRouterChatProvider (AsyncOpenAI SDK)
│   │   │   ├── embeddings.py     # OpenRouterEmbedder: text → vectors
│   │   │   └── factory.py        # create_chat_provider()
│   │   │
│   │   ├── storage/
│   │   │   ├── base.py           # VectorStore + RetrievedChunk/InsertResult
│   │   │   ├── milvus_vector_store.py # MilvusVectorStore (pymilvus)
│   │   │   └── factory.py        # Milvus adapter construction + connection helpers
│   │   │
│   │   ├── ai/
│   │   │   ├── prompts.py        # System prompts (VI + EN) + PromptTemplates
│   │   │   └── rag_pipeline.py   # RAGPipeline: retrieve → build context → stream answer
│   │   │
│   │   ├── models/
│   │   │   └── document.py       # DocumentStatus, IndexingResult
│   │   │
│   │   └── services/
│   │       ├── pdf_indexing.py  # index_pdf_bytes(): extract → chunk → embed → insert
│   │       └── supabase_pdf_storage.py  # PDF backup to Supabase S3 (boto3)
│   │
│   ├── tests/
│   │   ├── conftest.py           # Pytest fixtures (TestClient, auth override)
│   │   ├── test_upload.py        # Upload validation; indexing và S3 được mock
│   │   ├── test_chat.py          # Pipeline/SSE thật; external services được mock
│   │   ├── test_pdf_indexing.py  # Metadata, dimensions, cleanup khi indexing lỗi
│   │   └── test_vector_store.py  # Bảo toàn collection, stable chunk IDs
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
│       ├── lib/                   # Các module được import nhưng hiện thiếu trong checkout
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

Copy `backend/.env.example` thành `backend/.env`, rồi điền key và chọn model. `AppConfig` giữ các mặc định; biến trong `.env` ghi đè chúng. Root `.env` vẫn được hỗ trợ, sau đó `backend/.env` ghi đè. Khởi động lại backend sau khi sửa cấu hình.

```bash
# OpenRouter (chat + embeddings)
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
RAG_MODEL=google/gemini-2.0-flash-lite-001
EMBEDDING_MODEL=qwen/qwen3-embedding-8b

# Milvus
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=pdf_chunks

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
RETRIEVAL_TOP_K=8
CONTEXT_MAX_CHARS=12000
RAG_MAX_TOKENS=2048
```

`RAG_MODEL` và `EMBEDDING_MODEL` không có model dự phòng ngầm: cần khai báo model cho luồng tương ứng. Dimension được lấy từ vector thực tế. PDF Storage là tùy chọn: để trống endpoint và hai S3 key để tắt; khi bật phải điền đủ endpoint, region, hai key và bucket. Cấu hình thiếu/sai sẽ báo tên biến cần sửa.

`CONTEXT_MAX_CHARS` giới hạn ký tự tài liệu cho mỗi lượt tóm tắt/ngữ cảnh hỏi đáp; `RAG_MAX_TOKENS` giới hạn token sinh. Tóm tắt trung gian dùng ngân sách `min(RAG_MAX_TOKENS, max(64, CONTEXT_MAX_CHARS // 8))`, không phải quy đổi ký tự sang token.

Chẩn đoán retrieval từ `backend/`: `python scripts/test_retrieval.py <user_id> <doc_id> "câu hỏi"`. Script đọc cùng config với ứng dụng; dùng `--top-k 12 --min-score 0.2` để chủ động ghi đè.

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

### Deploy API với Nginx + Certbot

`compose.production.yml` là bộ riêng cho API + Nginx; Certbot chỉ chạy khi cấp/gia hạn certificate. Xem [DEPLOYMENT.md](DEPLOYMENT.md) để cấu hình EC2, domain và env, sau đó chạy trên EC2:

```sh
sh deploy/certificates.sh bootstrap
sh deploy/certificates.sh issue
```

Bootstrap chỉ phục vụ ACME challenge; API được mở sau khi HTTPS hoạt động. Timer systemd trong `deploy/systemd/` tự gọi renewal và reload Nginx. `GET /health` kiểm tra API process mà không gọi dịch vụ ngoài.

Frontend `src/lib` đã được khôi phục. Backend hiện vẫn cần adapter URI/token trước khi chạy end-to-end trên Vercel + Zilliz; bộ Nginx không tự bổ sung khả năng đó.

---

## ▶️ Chạy project

### Backend

Sử dụng Python 3.10+; bộ test đã được kiểm tra với Python 3.12.

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
npm ci
npm run dev
```

Mở `http://localhost:3000`

Trước khi chạy, tạo `frontend/.env.local` theo `frontend/.env.example`, điền URL/public key Supabase, Site URL và API URL. Các module `frontend/src/lib/` đã được khôi phục và có ngoại lệ Git ignore. `ChatWindow` dùng tên local `parseChatEvents` cho `streamChatSSEParser`.

Kiểm tra trong `frontend/`: `npm run typecheck`, `npm run lint`, `npm test`, `npm run build`. Browser test: `npx playwright install chromium` rồi `npm run test:e2e`. Xem [frontend/README.md](frontend/README.md) cho cấu hình Vercel/Supabase và phạm vi fixtures.

---

## 🔄 Luồng xử lý

### Upload Pipeline

```
User upload PDF → POST /api/upload → services/pdf_indexing.py:index_pdf_bytes()
  │
  ├─ 1. Xác thực Supabase JWT (Bearer token)
  ├─ 2. Validate: content-type, extension, size ≤ 50MB
  ├─ 3. Upload PDF gốc lên Supabase S3 (boto3, non-blocking)
  ├─ 4. load_pdf_pages() → PyPDFLoader (phát hiện scanned PDF)
  ├─ 5. chunk_documents() → RecursiveCharacterTextSplitter (1000/150)
  ├─ 6. Embed chunks → OpenRouter embeddings (batch 2048)
  ├─ 7. ensure_collection() → Tạo nếu chưa có; báo lỗi khi dimension không tương thích
  └─ 8. insert_chunks() → Batch insert vào Milvus (64/batch)

Response: { doc_id, chunks_count, processing_time, warnings, pdf_storage_key }
```

### Chat Pipeline (SSE Streaming)

```
User gửi câu hỏi → POST /api/chat
  │
  ├─ 1. Xác thực Supabase JWT
  ├─ 2. Validate query + doc_id
  ├─ 3. RAGPipeline.retrieve_chunks()
  │     ├─ Embed query → OpenRouter
  │     └─ search_chunks() → Milvus (top_k=8, min_score=0.32)
  │
  ├─ 4. SSE "sources" → [{page, source, score}, ...]
  ├─ 5. Nếu không có chunks → Fallback message (VI/EN)
  ├─ 6. _build_context() → "[Trang X] (độ liên quan: Y)\n{nội dung}"
  ├─ 7. RAGPipeline.stream_answer() → chat_provider.stream_with_context() → OpenRouter
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
| **Factory** | `create_chat_provider()`, `create_vector_store()`, `create_initialized_rag_pipeline()` |
| **Strategy** | `ChatProvider` → `OpenRouterChatProvider`, `VectorStore` → `MilvusVectorStore` |
| **Singleton** | `get_config()`, `get_embedder()` (@lru_cache) |
| **Dependency Injection** | FastAPI `Depends(require_supabase_user)` |
| **Streaming/Generator** | SSE events, LLM token streaming, SSE parser |
| **Observer** | Supabase `onAuthStateChange` subscription |

### Phân lớp Backend

```
routers/ (API endpoints, auth, validation)
    │
    ├── ai/rag_pipeline.py (retrieve → context → stream answer)
    │       ├── providers/ (LLM + embeddings)
    │       └── storage/ (vector DB)
    │
    └── services/pdf_indexing.py (extract → chunk → embed → insert)
            ├── processors/ (PDF extraction + chunking)
            ├── providers/embeddings.py (OpenRouterEmbedder)
            └── storage/ (VectorStore)
```

---

## 🧪 Testing

```bash
cd backend
python -m pytest -v

# Chạy tập trung một luồng hoặc một test
python -m pytest tests/test_vector_store.py
python -m pytest tests/test_chat.py::test_chat_sse_stream
```

Tests mock các API bên ngoài; không cần Milvus, OpenRouter hay Supabase đang chạy. Fixture `client` bypass authentication. Test chat đi qua `RAGPipeline`, chat provider và SSE thật; test indexing kiểm tra cleanup; test vector store kiểm tra dimension mismatch và ID chunk. Test upload mock cả indexing service và S3.

---

## 📌 Ghi chú

- **Không commit `.env`** — chứa API keys thực
- **CORS** — đang cho phép `localhost:3000/3001`, cần giới hạn khi deploy
- **Single-turn chat** — mỗi query độc lập, không lưu lịch sử hội thoại
- **Tóm tắt/tổng quan** — các câu như “hãy tóm tắt file PDF này” hoặc “file này viết về cái gì” đọc các chunks theo `user_id` + `doc_id`, không dùng embedding hay ngưỡng similarity. Tài liệu dài được tóm tắt từng phần rồi tổng hợp trong giới hạn `CONTEXT_MAX_CHARS`; các lời gọi tóm tắt tắt reasoning để dành token cho nội dung trả lời.
- **Nguồn tóm tắt** — SSE `sources` trả `score: null` vì không có điểm similarity; frontend hiển thị “Nội dung tài liệu”. Câu hỏi chi tiết vẫn dùng vector search và `MIN_RELEVANCE_SCORE`.
- **Single-document** — chỉ hỗ trợ 1 `doc_id` mỗi phiên chat
- **Collection dimensions** — `ensure_collection()` không xoá collection hiện có. Đổi model sang dimension khác cần collection mới hoặc gọi rõ `recreate_collection()` sau khi bảo toàn dữ liệu; hàm này xoá toàn bộ chunks cũ.
- **Connection status** — `get_connection_status()` chỉ báo trạng thái connection local, không phải health check đến server.

---

## 🌍 English Summary

**DocTrace** is a Retrieval-Augmented Generation chatbot for PDFs. The backend (FastAPI) handles PDF upload, text extraction, chunking, embedding, and vector storage in Milvus, then uses OpenRouter for streaming LLM answers over Server-Sent Events (SSE). The frontend (Next.js 14) provides a modern UI with Supabase authentication, drag-drop PDF upload, real-time streaming chat, and cited source cards with page numbers.
