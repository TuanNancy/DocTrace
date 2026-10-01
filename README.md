# DocTrace — PDF Q&A with source citations

Project học tập/portfolio: đăng nhập, upload PDF, đặt câu hỏi và nhận câu trả lời stream kèm nguồn theo trang.

## Kiến trúc triển khai

```text
Browser ──→ Next.js / Vercel ──→ Supabase Auth (cookie session)
   │
   └── Bearer token + PDF / chat ──→ Caddy HTTPS / FastAPI / EC2
                                       ├── Supabase Auth: xác thực user
                                       ├── Supabase S3: PDF gốc
                                       ├── Zilliz Cloud: chunks + embeddings + user_id
                                       └── OpenRouter: embeddings + chat completion
```

- Frontend: Next.js 15, React, TypeScript, Tailwind 3, Supabase SSR.
- Backend: FastAPI, PyPDFLoader, text splitter, OpenAI-compatible SDK trỏ tới OpenRouter.
- Vector DB: Milvus local hoặc Zilliz managed, dùng cùng adapter PyMilvus.
- Test: pytest, Vitest và Playwright với external services được mock.

Giới hạn hiện tại: PDF có text (chưa có OCR), mỗi câu hỏi chỉ dùng một tài liệu, transcript/doc_id nằm trong state của browser. Reload giữ phiên đăng nhập nhưng không khôi phục tài liệu đã chọn hay lịch sử chat.

## Chạy local

### 1. Backend

Dùng Python 3.12 cho cùng phiên bản với Docker/CI. Trong `backend/`:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Trên Linux/macOS, activate bằng `source .venv/bin/activate`.

Tạo `backend/.env` từ [`backend/.env.example`](backend/.env.example), điền OpenRouter và Supabase. Nếu lưu PDF gốc, tạo private bucket và cấu hình đủ S3 endpoint, region, access key, secret và bucket.

Chọn một cách chạy vector DB:

- **Milvus local:** để `MILVUS_URI` và `MILVUS_TOKEN` trống, chạy `docker compose up -d` từ repo root. Compose này chỉ khởi động Milvus, etcd, MinIO và Attu (`http://localhost:8001`).
- **Zilliz:** đặt `MILVUS_URI=https://...` và `MILVUS_TOKEN=...`; không cần chạy stack Milvus local. Adapter tự chọn `AUTOINDEX` khi có URI.

Sau đó trong `backend/`:

```text
uvicorn app.main:app --reload --port 8000
```

API docs: `http://localhost:8000/docs`. Liveness: `GET /health`; endpoint này không kiểm tra dịch vụ cloud.

**Dữ liệu cũ:** schema mới có `user_id`. Dùng collection mới, ví dụ `pdf_chunks_owned_v1`, và upload lại PDF. Không dùng `recreate_collection()` để sửa lỗi dimension; hàm này xoá dữ liệu.

### 2. Frontend

Dùng Node.js 22.18+; trong `frontend/`:

```text
npm ci
```

Tạo `frontend/.env.local` từ [`frontend/.env.example`](frontend/.env.example), điền các giá trị public của Supabase, API URL và site URL. Sau đó:

```text
npm run dev
```

Mở `http://localhost:3000`. Thiết lập Supabase Site URL/Redirect URLs theo [hướng dẫn deployment](DEPLOYMENT.md#supabase).

`NEXT_PUBLIC_DEMO_MODE=true` chỉ bật upload/chat giả trong development; vẫn cần đăng nhập. Production luôn dùng backend thật. API URL là origin, ví dụ `https://api.example.com`, không thêm `/api`.

## Kiểm chứng

Trong `backend/`:

```text
python -m pytest
python -m pytest tests/test_vector_store.py
python -m pytest tests/test_chat.py::test_chat_sse_stream
```

Trong `frontend/`:

```text
npm run lint
npm run typecheck
npm test
npx playwright install chromium
npm run test:e2e
npm run build
```

- Typecheck/build cần bốn biến `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY`, `NEXT_PUBLIC_SITE_URL`. Typecheck tự sinh route types trước khi chạy `tsc`. CI dùng giá trị giả hợp lệ, không gọi Auth thật.
- Playwright tự khởi động Next dev trên `127.0.0.1:3005` và HTTP fixtures trên `127.0.0.1:8999`; không cần cloud credentials. Nó kiểm tra cookie login/reload/logout, upload, stream và xử lý mất kết nối.
- Backend tests mock dịch vụ ngoài; fixture `client` bypass auth. `test_auth_and_limits.py` kiểm tra riêng dependency auth thật với HTTP Supabase được mock.
- `backend/scripts/test_*.py` là diagnostic chạy thủ công. Retrieval: `python scripts/test_retrieval.py <user_id> <doc_id> "query"` — gọi dịch vụ thật.

## Những điểm kỹ thuật quan trọng

- **Auth vs ownership:** token được xác thực ở API; `user_id` lấy từ token, không lấy từ body. Vector search luôn lọc owner và document.
- **SSE:** event `sources`, `token`, `error`, `done`. Dữ liệu token và `"[DONE]"` là JSON string; lỗi giữa stream vẫn có thể đi kèm HTTP 200.
- **Indexing:** giữ PDF gốc trước khi index; lỗi index không rollback file đã lưu. Không cấu hình S3 thì retention được bỏ qua; storage failure có warning.
- **Dimension:** lấy từ vector trả về thực tế. Đổi embedding model cần index lại, kể cả model mới có cùng số chiều.
- **Concurrency:** SDK đồng bộ chạy trong worker thread. Mỗi vector-store instance có connection alias riêng; mặc định chỉ một upload đang xử lý mỗi API process.
- **Env:** backend nạp root `.env`, sau đó `backend/.env` với override. Frontend public env được đóng vào bundle lúc build.

## Tài liệu

- [ARCHITECTURE.md](ARCHITECTURE.md): luồng xử lý, ranh giới trách nhiệm và trade-off.
- [DEPLOYMENT.md](DEPLOYMENT.md): Vercel + EC2/Caddy + Zilliz + Supabase, smoke test và rollback.
- [AGENTS.md](AGENTS.md): hướng dẫn ngắn cho coding agent.

Workflow [Verify](.github/workflows/verify.yml) chạy tests/build và kiểm tra container; không tự tạo tài nguyên cloud hoặc deploy.
