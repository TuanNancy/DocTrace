## 📄 RAG PDF Chatbot

Chatbot RAG (Retrieval-Augmented Generation) cho phép **upload file PDF và đặt câu hỏi trực tiếp trên nội dung tài liệu**.  
Hệ thống sẽ:

- **Trích xuất text** từ PDF
- **Chia nhỏ thành các chunk**, tạo **embeddings**
- **Lưu vào Milvus** (vector database)
- Khi người dùng hỏi, hệ thống **tìm các đoạn liên quan nhất** rồi **gọi LLM qua OpenRouter** để sinh câu trả lời có trích dẫn số trang.

**Phạm vi hiện tại (explicit):**
- Không dùng thị giác máy tính / OCR / multimodal trong luồng chính
- Không dùng điều phối nhiều agent / task planner (chỉ RAG pipeline “chuẩn”)

---

## 🚀 Tech Stack

- **Backend**
  - Python, FastAPI
  - LangChain (PDF loader + text splitter)
  - OpenAI embeddings
  - OpenRouter (LLM, mặc định `openai/gpt-4o-mini`)
- **Vector DB**
  - Milvus Standalone (pymilvus)
  - Etcd + MinIO theo chuẩn Milvus
- **Frontend**
  - Next.js (App Router), React 18
  - Tailwind CSS, dark mode
- **Khác**
  - Docker, Docker Compose
  - pytest, pytest-asyncio

---

## 📁 Cấu trúc thư mục

- **`backend/`**: FastAPI + RAG pipeline
  - `app/main.py`: entrypoint FastAPI, mount router `upload` và `chat`
  - `app/routers/upload.py`: API `/api/upload` nhận PDF, kiểm tra size/type, chạy pipeline index
  - `app/routers/chat.py`: API `/api/chat` trả về **SSE stream** (`token`, `sources`, `done`)
  - `app/ai/rag_agent.py`: RAG pipeline (retrieve → build context → call LLM, có streaming)
  - `app/providers/`: LLM provider + embedding provider
  - `app/storage/`: Milvus storage + factory
  - `app/core/config.py`: cấu hình (provider-agnostic)
  - `app/schemas.py`: Pydantic models cho request/response
- **`frontend/`**: giao diện Next.js
  - `src/app/page.tsx`: trang chính (upload + chat)
  - `src/components/UploadZone.tsx`: UI upload PDF, hiển thị tiến trình & kết quả index
  - `src/components/ChatWindow.tsx`: UI chat, stream token, hiển thị nguồn trích dẫn
  - `src/components/SourceCard(.tsx|List.tsx)`: hiển thị nguồn (trang, score, preview)
  - `src/components/ThemeToggle.tsx`: dark/light mode
- **`docker-compose.yml`**: khởi tạo cụm Milvus (etcd, minio, milvus, attu)

---

## 🔧 Cấu hình môi trường

### 1. Backend `.env` (trong thư mục gốc project, được `backend/app/config.py` tự động load)

Tạo file `.env` tại **root** (`g:\project\RAG-PDF-chatbot\.env`) với các biến tối thiểu:

```bash
# Milvus
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=pdf_chunks
MILVUS_VECTOR_DIM=1536          # 1536 cho OpenAI embeddings

# Embedding (OpenAI)
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Upload
UPLOAD_MAX_SIZE_MB=50

# Chunking
CHUNK_SIZE=1000
CHUNK_OVERLAP=150

# LLM qua OpenRouter
OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_CHAT_MODEL=openai/gpt-4o-mini
```

- Nếu đổi model embeddings OpenAI, nhớ **cập nhật `MILVUS_VECTOR_DIM`** khớp với dimension của model (nếu cần).

### 2. Frontend `.env.local`

Trong thư mục `frontend/`:

```bash
cd frontend
cp .env.local.example .env.local  # nếu có sẵn, hoặc tự tạo
```

Biến quan trọng:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

`NEXT_PUBLIC_API_URL` là base URL đến backend FastAPI (để `UploadZone` và `ChatWindow` gọi API thực, thay vì mock).

---

## 🐳 Chạy Milvus stack bằng Docker

Hệ thống sử dụng Docker Compose để chạy:

- `etcd`: metadata store cho Milvus
- `minio`: object storage
- `milvus`: Milvus standalone (gRPC port `19530`)
- `attu`: giao diện web để inspect dữ liệu Milvus (`http://localhost:8001`)

### 1. Tạo thư mục dữ liệu (bắt buộc)

**Linux/macOS**:

```bash
mkdir -p volumes/etcd volumes/minio volumes/milvus
```

**Windows (PowerShell)**:

```powershell
New-Item -ItemType Directory -Force -Path volumes/etcd, volumes/minio, volumes/milvus
```

### 2. Khởi động stack

```bash
docker compose up -d
```

### 3. Theo dõi và kiểm tra

- **Xem log Milvus realtime**:

```bash
docker compose logs -f milvus
```

- **Kiểm tra container đang chạy**:

```bash
docker compose ps
```

- **Attu (UI)**: truy cập `http://localhost:8001` (mặc định sẽ kết nối tới `milvus:19530` trong docker network).

---

## ▶️ Chạy backend (FastAPI)

### Cài đặt

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -r requirements.txt
```

Đảm bảo đã:

- Chạy Milvus (bằng Docker như trên) **hoặc** có một cụm Milvus khác sẵn sàng.
- Cấu hình `.env` ở root như phần trên.

### Chạy server

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API docs (Swagger): truy cập `http://localhost:8000/docs`.

---

## 💻 Chạy frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
```

Mở `http://localhost:3000`.

Nếu đã cấu hình `NEXT_PUBLIC_API_URL`, frontend sẽ gọi trực tiếp:

- `POST {NEXT_PUBLIC_API_URL}/api/upload` cho upload PDF
- `POST {NEXT_PUBLIC_API_URL}/api/chat` (SSE) cho phần chat

Nếu chưa, frontend có thể đang ở chế độ **mock** (xem thêm trong `frontend/README.md`).

---

## 🔌 API chính

### 1. Upload PDF

- **Endpoint**: `POST /api/upload`
- **Content-Type**: `multipart/form-data`
- **Field**: `file` (PDF)
- **Response** (`UploadResponse`):

```json
{
  "doc_id": "string",
  "chunks_count": 123,
  "message": "Upload and indexing completed."
}
```

- Validate:
  - Chỉ cho phép `application/pdf`
  - Extension `.pdf`
  - Giới hạn dung lượng theo `UPLOAD_MAX_SIZE_MB`

### 2. Chat với tài liệu (SSE)

- **Endpoint**: `POST /api/chat`
- **Body** (`ChatRequest`):

```json
{
  "query": "Câu hỏi của người dùng",
  "doc_id": "id nhận được từ /api/upload"
}
```

- **Response**: `text/event-stream` với các event:
  - `event: sources` — `data`: JSON array `{page, source, score}`
  - `event: token` — `data`: chuỗi token (đoạn text nhỏ) từ LLM
  - `event: error` — `data`: `{ "message": "..." }` nếu có lỗi
  - `event: done` — `data`: `[DONE]`

Frontend cần parser SSE để ghép token liên tục thành câu trả lời hoàn chỉnh.

---

## 🧠 Luồng xử lý RAG

- **Upload**
  - Người dùng upload PDF → `/api/upload`
  - Backend đọc và validate file, chạy pipeline:
    1. Đọc PDF (pypdf), tách theo trang
    2. Kiểm tra số ký tự để phát hiện tài liệu scan (ít text)
    3. Chunking theo `CHUNK_SIZE` và `CHUNK_OVERLAP`
    4. Gọi embedding (OpenAI)
    5. Lưu `{doc_id, page, source, text, vector}` vào Milvus
- **Chat**
  - Nhận `query` và `doc_id`
  - Embed query, search Milvus với metric `COSINE` + filter theo `doc_id`
  - Build context:
    - Gộp các chunk: `[Trang X] (độ liên quan: Y)\n<nội dung>`
    - Giới hạn `max_chars`
  - LLM:
    - Tạo system prompt tiếng Việt (`SYSTEM_PROMPT_VI`) + context
    - Gửi đến OpenRouter, stream từng token
  - Trả về SSE cho frontend:
    - Stream `token`
    - Gửi `sources` (danh sách chunk) khi đã có kết quả retrieval
    - Cuối cùng gửi `done`

---

## ✅ Kiểm thử & script hỗ trợ

- **Unit tests / script** (trong `backend/scripts/`):
  - `test_chunking.py`: test logic chunking PDF
  - `test_retrieval.py` (nếu có): test retrieval từ Milvus
- Chạy pytest:

```bash
cd backend
pytest
```

---

## 📌 Ghi chú & hướng phát triển

- **Bảo mật**:
  - Không commit file `.env`, API keys.
  - Khi deploy, nên giới hạn CORS thay vì `allow_origins=["*"]`.
- **Mở rộng**:
  - Hỗ trợ nhiều tài liệu / nhiều `doc_id` cho 1 phiên chat.
  - Thêm UI quản lý tài liệu (danh sách, xóa, re-index).
  - Thêm auth (JWT, OAuth) nếu dùng trong môi trường multi-user.

---

## 🌍 English Summary

This project is a **Retrieval-Augmented Generation chatbot for PDFs**.  
The backend (FastAPI) handles PDF upload, chunking, embedding, and vector storage in Milvus, then uses OpenRouter for streaming LLM answers over SSE.  
The frontend (Next.js) provides a modern UI to upload PDFs, ask questions, and view answers with cited page numbers and relevant source snippets.
