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
| Worker | RQ 2.12; `python -m app.worker`, JSON jobs, timeout và retry có scheduler |
| Queue / thư viện | Redis 7.4: RQ jobs + metadata tài liệu riêng, AOF và volume giữ dữ liệu qua restart |
| PDF gốc | Bucket Supabase Storage riêng tư, giao thức S3 |
| Vector/text chunks | Milvus local hoặc Zilliz URI/token |
| Chat/embedding | OpenRouter, model cấu hình rõ trong env |

Chi tiết luồng và các bất biến: [ARCHITECTURE.md](ARCHITECTURE.md).

## Chạy local

CI sử dụng Python **3.12** và Node **22**. Docker cần thiết cho Redis, worker Linux, Milvus local và kiểm thử tích hợp.

### 1. Supabase và môi trường backend

1. Tạo project Supabase, bật Auth và tạo bucket PDF **private**.
2. Copy `backend/.env.example` thành `backend/.env`, điền:
   - `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`: xác thực người dùng.
   - Toàn bộ các biến `SUPABASE_S3_*` và `SUPABASE_STORAGE_BUCKET`: giữ PDF gốc.
   - `OPENROUTER_API_KEY`, `RAG_MODEL`, `EMBEDDING_MODEL`.
   - Milvus host/port hoặc `MILVUS_URI` + `MILVUS_TOKEN` cho Zilliz.
   - `REDIS_URL=redis://localhost:6379/0`, `RQ_QUEUE_NAME=documents-v2`.

Thư viện dùng Redis, không cần SQL migration hay service-role key. Supabase cung cấp Auth và Storage.

Root `.env` được hỗ trợ; `backend/.env` ghi đè cả root và biến process. `get_config()` cache một lần, nên khởi động lại API/worker sau khi đổi cấu hình.

Phiên bản này bắt đầu thư viện mới (`doctrace:library:v2` và queue `documents-v2`); tải lại các PDF cần dùng. Chuyển từ bản PostgreSQL: xem [DEPLOYMENT.md](DEPLOYMENT.md#chuyển-từ-thư-viện-postgresql-sang-redis). Dữ liệu cloud cũ không bị xóa.

### 2. Redis và Milvus local

Từ root:

```sh
docker compose up -d
```

Lệnh này chạy Redis, Milvus, etcd, MinIO và Attu. Attu ở `http://localhost:8001`. Nếu dùng Zilliz, chỉ cần `docker compose up -d redis`.

### 3. API và worker

Từ `backend/`:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Worker nên chạy bằng Linux container, từ repository root:

```sh
docker compose --profile jobs up -d --build worker
```

Trên Linux, cũng có thể chạy `python -m app.worker` trong terminal riêng từ `backend/`. Worker container dùng `MILVUS_HOST=milvus`; cấu hình `MILVUS_URI` vẫn được ưu tiên nếu dùng Zilliz.

API docs: `http://localhost:8000/docs`. API lưu PDF rồi ghi metadata và enqueue trực tiếp trong một Redis transaction; trả `202` sau khi xác nhận. Worker xử lý và cập nhật thư viện. RQ thử tối đa ba lần, chờ 10/30 giây giữa các lần thử. Lỗi cuối cùng cho phép bấm Thử lại để tạo job mới. Xóa/retry chỉ được nhận khi job trước đã kết thúc.

Redis tắt thì upload mới trả `503`. Metadata không hết hạn cùng job RQ; Redis dùng volume và AOF `everysec`, nhưng mất toàn bộ volume sẽ mất thư viện/queue. PDF và vector nằm riêng không tự tái tạo được danh mục. Xem giới hạn phục hồi trong `ARCHITECTURE.md`.

### 4. Frontend

Từ `frontend/`:

```sh
npm ci
cp .env.example .env.local
npm run dev
```

Điền public Supabase settings và `NEXT_PUBLIC_API_URL=http://localhost:8000` (không thêm `/api`). Mở `http://localhost:3000`. Xem [frontend/README.md](frontend/README.md) cho cấu hình OAuth và kiểm tra UI.

API URL trống bật demo upload/chat; Auth vẫn dùng Supabase. Tài liệu demo chỉ giữ trong phiên. `NEXT_PUBLIC_*` được đóng vào bundle khi build; đổi giá trị cần rebuild. OpenRouter và S3 keys chỉ đặt ở backend.

## API chính

Các endpoint `/api/*` đều yêu cầu `Authorization: Bearer <Supabase access token>`.

| Method | Endpoint | Kết quả |
|---|---|---|
| POST | `/api/upload` | Multipart `file` PDF; `202` với bản ghi tài liệu đã xếp hàng |
| GET | `/api/documents?limit=100&offset=0` | `{items, has_more}`, chỉ tài liệu của người dùng |
| GET | `/api/documents/{doc_id}` | Metadata và trạng thái |
| POST | `/api/documents/{doc_id}/retry` | Xếp lại indexing hoặc cleanup bị lỗi |
| DELETE | `/api/documents/{doc_id}` | `202` và xếp tác vụ xóa; `409` nếu job hiện tại chưa kết thúc |
| GET | `/api/documents/{doc_id}/file` | URL PDF riêng tư, hiệu lực 300 giây |
| GET | `/api/documents/{doc_id}/chunks/{chunk_id}` | Đoạn trích gốc, tên PDF, trang |
| POST | `/api/chat` | `{query, doc_id, language: "vi"}` → SSE |

SSE: `sources` chứa `{citation_id, chunk_id, doc_id, page, source, score}`, `token` chứa text delta, `error` chứa `{message}`, `done` chứa chuỗi `"[DONE]"`. `score: null` cho tóm tắt toàn tài liệu.

Sau upload: `queued → processing → ready / error`; xóa: `deleting → deleted / delete_error`. Retry theo lịch vẫn là `queued` (hoặc `deleting`). Lỗi indexing thuộc trạng thái tài liệu, không thuộc request upload đã nhận `202`.

## Kiểm tra

Từ `backend/` (pytest mock dịch vụ ngoài, không cần cloud credentials):

```sh
python -m pytest
python -m pytest tests/test_chat.py::test_chat_sse_stream
python -m pytest tests/test_documents.py tests/test_worker.py
python scripts/verify_document_queue.py
```

Lệnh cuối cần Docker; build image rồi chạy Redis và hai RQ workers thật trên Linux. Nó kiểm tra transaction thư viện/queue, owner scope, Redis restart/outage, retry/timeout, kill worker và xóa; tự dọn tài nguyên. Có thể truyền `--api-image doctrace-api:verify` để dùng image đã build. Pytest dùng fake Redis và mocks; integration thay PDF/AI/S3/Milvus bằng fixture.

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

[DEPLOYMENT.md](DEPLOYMENT.md) hướng dẫn API + Redis + RQ worker + Nginx/Certbot; frontend deploy riêng. `/health` chỉ kiểm tra API process, không kiểm tra queue hay nhà cung cấp AI.
