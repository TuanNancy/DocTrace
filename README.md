# DocTrace · Baymax

Hỏi đáp PDF với nguồn trích dẫn có thể kiểm chứng. Giao diện **Soft glass light** gồm không gian chat và thư viện riêng theo tài khoản.

## Tính năng

- `/documents`: kéo thả PDF, tiến trình upload thực, trạng thái xử lý, tìm kiếm/lọc, xem PDF, thử lại và xóa.
- `/chat`: chọn PDF sẵn sàng, trả lời streaming bằng Markdown/GFM, dừng, sao chép và xuất hội thoại.
- Citation `[1]`, `[2]` mở nguyên văn chunk và PDF ở trang tương ứng, qua URL có thời hạn.
- Chat giữ trong bộ nhớ của layout dùng chung khi chuyển Chat ↔ Thư viện; reload bắt đầu mới. Backend vẫn trả lời từng câu hỏi độc lập, chưa lưu lịch sử hội thoại.
- Sidebar và panel nguồn chuyển thành drawer trên mobile.

## Thành phần

| Thành phần | Công nghệ / nhiệm vụ |
|---|---|
| Frontend | Next.js 14 App Router, React 18, Tailwind, react-markdown + remark-gfm |
| API | FastAPI; Supabase Bearer authentication; API thư viện và SSE |
| Worker | `python -m app.worker`; claim/heartbeat/finish tác vụ bền vững |
| Metadata và jobs | Supabase Postgres, truy cập qua PostgREST với service-role key phía server |
| PDF gốc | Bucket Supabase Storage riêng tư, giao thức S3 |
| Vector/text chunks | Milvus local hoặc Zilliz URI/token |
| Chat/embedding | OpenRouter, model cấu hình rõ trong env |

Chi tiết luồng và các bất biến: [ARCHITECTURE.md](ARCHITECTURE.md).

## Chạy local

CI sử dụng Python **3.12** và Node **22**. Docker cần thiết nếu dùng Milvus local hoặc chạy kiểm tra migration/proxy.

### 1. Supabase và môi trường backend

1. Tạo project Supabase, bật Auth và tạo bucket PDF **private**.
2. Chạy `backend/migrations/001_document_library.sql` một lần trong SQL Editor của project. Migration tạo `documents`, `document_jobs`, RLS và các RPC cho worker.
3. Copy `backend/.env.example` thành `backend/.env`, điền:
   - `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`: xác thực người dùng.
   - `SUPABASE_SERVICE_ROLE_KEY`: key **server-only** cho metadata và jobs.
   - Toàn bộ các biến `SUPABASE_S3_*` và `SUPABASE_STORAGE_BUCKET`: giữ PDF gốc.
   - `OPENROUTER_API_KEY`, `RAG_MODEL`, `EMBEDDING_MODEL`.
   - Milvus host/port hoặc `MILVUS_URI` + `MILVUS_TOKEN` cho Zilliz.

Root `.env` được hỗ trợ; `backend/.env` ghi đè cả root và biến process. `get_config()` cache một lần, nên khởi động lại API/worker sau khi đổi cấu hình.

Thư viện mới cần metadata trong Postgres. PDF tải bằng phiên bản cũ chưa có bản ghi thư viện cần được tải lại; migration không xóa dữ liệu Milvus/Storage cũ.

### 2. Milvus local (bỏ qua nếu dùng Zilliz)

Từ root:

```sh
docker compose up -d
```

Lệnh này chỉ chạy Milvus, etcd, MinIO và Attu; không chạy API/frontend. Attu ở `http://localhost:8001`.

### 3. API và worker

Từ `backend/`:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Ở terminal thứ hai, cùng môi trường `backend/`:

```sh
python -m app.worker
```

API docs: `http://localhost:8000/docs`. Worker phải chạy để tài liệu chuyển từ **Chờ xử lý** sang **Sẵn sàng** và hoàn tất xóa. API có thể restart mà không mất hàng đợi. Worker bị ngắt sẽ được phục hồi sau khi lease hết hạn; tối đa ba lần claim tự động, sau đó người dùng có thể thử lại.

### 4. Frontend

Từ `frontend/`:

```sh
npm ci
cp .env.example .env.local
npm run dev
```

Điền public Supabase settings và `NEXT_PUBLIC_API_URL=http://localhost:8000` (không thêm `/api`). Mở `http://localhost:3000`. Xem [frontend/README.md](frontend/README.md) cho cấu hình OAuth và kiểm tra UI.

API URL trống bật demo upload/chat; Auth vẫn dùng Supabase. Tài liệu demo chỉ giữ trong phiên. `NEXT_PUBLIC_*` được đóng vào bundle khi build; đổi giá trị cần rebuild. Service-role, OpenRouter và S3 keys chỉ đặt ở backend.

## API chính

Các endpoint `/api/*` đều yêu cầu `Authorization: Bearer <Supabase access token>`.

| Method | Endpoint | Kết quả |
|---|---|---|
| POST | `/api/upload` | Multipart `file` PDF; `202` với bản ghi tài liệu đã xếp hàng |
| GET | `/api/documents?limit=100&offset=0` | `{items, has_more}`, chỉ tài liệu của người dùng |
| GET | `/api/documents/{doc_id}` | Metadata và trạng thái |
| POST | `/api/documents/{doc_id}/retry` | Xếp lại indexing hoặc cleanup bị lỗi |
| DELETE | `/api/documents/{doc_id}` | `202`, ẩn khỏi retrieval ngay và xếp tác vụ cleanup |
| GET | `/api/documents/{doc_id}/file` | URL PDF riêng tư, hiệu lực 300 giây |
| GET | `/api/documents/{doc_id}/chunks/{chunk_id}` | Đoạn trích gốc, tên PDF, trang |
| POST | `/api/chat` | `{query, doc_id, language: "vi"}` → SSE |

SSE: `sources` chứa `{citation_id, chunk_id, doc_id, page, source, score}`, `token` chứa text delta, `error` chứa `{message}`, `done` chứa chuỗi `"[DONE]"`. `score: null` cho tóm tắt toàn tài liệu.

Luồng trạng thái: `uploading → queued → processing → ready / error`; xóa: `deleting → deleted / delete_error`. Lỗi indexing được ghi ở metadata, không còn trả về trong request upload đã nhận `202`.

## Kiểm tra

Từ `backend/` (pytest mock dịch vụ ngoài, không cần cloud credentials):

```sh
python -m pytest
python -m pytest tests/test_chat.py::test_chat_sse_stream
python -m pytest tests/test_documents.py tests/test_worker.py
python scripts/verify_document_queue.py
```

Lệnh cuối cần Docker, chạy migration thật trên PostgreSQL tạm, kiểm tra RLS, lease, recovery và xóa/thử lại; tự dọn container.

Từ `frontend/`:

```sh
npm run typecheck
npm run lint
npm test
npx playwright install chromium
npm run test:e2e
npm run build
```

E2E dùng Auth/API fixtures local ở cổng 4310/4311, kiểm tra desktop/mobile, không xác nhận kết nối cloud RAG/OAuth thật.

Chẩn đoán retrieval với dịch vụ thật, từ `backend/`:

```sh
python scripts/test_retrieval.py <user_id> <doc_id> "câu hỏi" --top-k 8 --min-score 0.32
```

## Deploy

[DEPLOYMENT.md](DEPLOYMENT.md) hướng dẫn API + worker + Nginx/Certbot; frontend deploy riêng. `/health` chỉ kiểm tra API process, không kiểm tra database, worker hay nhà cung cấp AI.
