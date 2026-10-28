# DocTrace · Baymax

Hỏi đáp PDF với nguồn trích dẫn có thể kiểm chứng. Giao diện **Soft glass light** gồm không gian chat và thư viện riêng theo tài khoản, có chuyển đổi giữa các workspace.

## Tính năng

- `/documents`: kéo thả PDF, tiến trình upload thực, trạng thái xử lý, tìm kiếm/lọc, xem PDF, thử lại và xóa.
- `/chat`: chọn PDF sẵn sàng, trả lời streaming bằng Markdown/GFM, dừng, sao chép và xuất hội thoại.
- `/usage`: plan hiện tại, lượt hỏi/tài liệu còn lại, ngày reset và chi phí OpenRouter theo user.
- Citation `[1]`, `[2]` mở nguyên văn chunk và PDF ở trang tương ứng, qua URL có thời hạn.
- Hội thoại được lưu theo workspace + người dùng + tài liệu; reload khôi phục hội thoại mới nhất. “Chat mới” xóa hội thoại hiện tại. Backend vẫn trả lời từng câu hỏi độc lập.
- Nguồn trích dẫn của generation cũ bị đánh dấu không khả dụng sau khi tài liệu được xử lý lại hoặc bị xóa; UI không mở chunk/PDF cũ.
- Mỗi tài khoản có workspace cá nhân; sidebar hiển thị và chuyển giữa các workspace đang hoạt động. Đổi workspace xóa ngay thư viện/chat đang chọn và bỏ qua phản hồi cũ.
- Tài liệu và transcript luôn riêng theo người tải. Thành viên cùng workspace không đọc được PDF, đoạn trích hay hội thoại của nhau; owner chỉ thấy số liệu tổng hợp.
- Sidebar và panel nguồn chuyển thành drawer trên mobile.

## Thành phần

| Thành phần | Công nghệ / nhiệm vụ |
|---|---|
| Frontend | Next.js 14 App Router, React 18, Tailwind, react-markdown + remark-gfm |
| API | FastAPI; Supabase Bearer authentication; API thư viện và SSE |
| Worker | RQ 2.12; `python -m app.worker`, JSON jobs, timeout và retry có scheduler |
| Queue / thư viện | Redis 7.4: RQ jobs + metadata tài liệu riêng, AOF và volume giữ dữ liệu qua restart |
| Control plane | PostgreSQL/Supabase schema `doctrace`: workspace, thành viên, plan, quota, transcript, usage |
| PDF gốc | Bucket Supabase Storage riêng tư, giao thức S3 |
| Vector/text chunks | Milvus local hoặc Zilliz URI/token |
| Chat/embedding | OpenRouter, model cấu hình rõ trong env |

Chi tiết luồng và các bất biến: [ARCHITECTURE.md](ARCHITECTURE.md).

## Cấu trúc repo

```text
backend/
  app/                 API, worker, RAG và các adapter Redis/Storage/Milvus
  scripts/             Kiểm tra queue và công cụ chẩn đoán PDF/retrieval
  tests/               Unit tests; fixtures/ dành cho Linux worker integration
  requirements.txt     Dependency chạy API/worker
  requirements-dev.txt Dependency runtime + kiểm thử
frontend/
  src/app/             Routes Next.js
  src/assets/          Asset được bundle, gồm logo Baymax
  src/components/      UI chat, upload, auth và workspace
  src/lib/             API client, SSE parser, hooks và tiện ích dùng chung
    supabase/          Auth clients, cấu hình public và session middleware
  src/types/           Hợp đồng dữ liệu frontend/backend
  tests/               Unit tests, E2E và Auth/API fixtures
deploy/                Nginx, Certbot, systemd và kiểm thử deployment
```

## Chạy local

CI sử dụng Python **3.12** và Node **22**. Docker cần thiết cho Redis, worker Linux, Milvus local và kiểm thử tích hợp.

### 1. Supabase và môi trường backend

1. Tạo project Supabase, bật Auth và tạo bucket PDF **private**.
2. Copy `backend/.env.example` thành `backend/.env`, điền:
   - `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`: xác thực người dùng.
   - Toàn bộ các biến `SUPABASE_S3_*` và `SUPABASE_STORAGE_BUCKET`: giữ PDF gốc.
   - `OPENROUTER_API_KEY`, `RAG_MODEL`, `EMBEDDING_MODEL`.
   - Milvus host/port hoặc `MILVUS_URI` + `MILVUS_TOKEN` cho Zilliz.
   - `DATABASE_URL` dùng login riêng `doctrace_app` cho control plane Postgres (session pooler hỗ trợ IPv4).
   - `REDIS_URL=redis://localhost:6379/0`, `RQ_QUEUE_NAME=documents-v2`.

Thư viện tài liệu vẫn dùng Redis và không cần service-role key. Postgres giữ control plane (workspace, thành viên, plan/quota, transcript, usage); schema nằm trong `doctrace` và không expose qua Supabase Data API. Tạo runtime role bằng `deploy/postgres/bootstrap-runtime-role.sql`, đặt mật khẩu riêng, rồi lưu credential DDL `DIRECT_DATABASE_URL` trong `backend/.env.migrations` theo file example. Xem [hướng dẫn tách quyền](DEPLOYMENT.md#tách-credential-runtime-và-migration) để bootstrap và chuyển cấu hình cũ. Alembic không dùng fallback `DATABASE_URL`.

Chạy migration trong một subshell để credential DDL không đi theo API/worker:

```sh
cd backend
(
  set -a
  . ./.env.migrations
  set +a
  alembic upgrade head
)
```

Nếu thư viện Redis đã có tài liệu từ bản trước P1, chạy backfill để gắn `workspace_id`/`owner_user_id` và dựng lại các sorted set workspace. Mặc định là dry run; script idempotent và giữ index per-user cũ để rollback:

```sh
cd backend
python scripts/backfill_workspaces.py
python scripts/backfill_workspaces.py --apply
```

`/ready` yêu cầu Redis và Postgres sẵn sàng: có migration stamp, đủ bảng/cột/quyền, runtime không có quyền DDL/admin. Thiếu DB hoặc dùng login migration sẽ trả `503`; schema mở rộng tương thích vẫn qua check khi rollback image. `/health` chỉ là liveness của process.

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

Các endpoint `/api/*` đều yêu cầu `Authorization: Bearer <Supabase access token>`. Upload, thư viện, file/chunk, chat và usage còn yêu cầu `X-Workspace-Id: <uuid>`; server kiểm tra membership đang hoạt động, không tin header tự nó. Thiếu header trả `400 workspace_required`; workspace không tồn tại, đã archive hoặc người dùng không còn là thành viên trả `404`. Endpoint quản lý workspace chọn workspace bằng path ID.

| Method | Endpoint | Kết quả |
|---|---|---|
| GET | `/api/workspaces` | Membership của user: `{items: [{id, name, kind, role, plan, status, created_at}]}` |
| POST | `/api/workspaces` | Tạo workspace nhóm, giới hạn theo plan; owner hiện tại |
| GET/POST | `/api/workspaces/{id}/members` | Owner xem/thêm thành viên, chỉ metadata |
| DELETE | `/api/workspaces/{id}/members/{user_id}` | `409 member_has_documents` nếu thành viên còn tài liệu |
| POST | `/api/workspaces/{id}/archive` | Owner archive workspace |
| POST | `/api/workspaces/{id}/restore` | Chỉ platform admin restore workspace đã archive |
| POST | `/api/upload` | Multipart `file` PDF; `202` với bản ghi tài liệu đã xếp hàng |
| GET | `/api/documents?limit=100&offset=0` | `{items, has_more}`, chỉ tài liệu của người dùng trong workspace |
| GET | `/api/documents/{doc_id}` | Metadata và trạng thái |
| POST | `/api/documents/{doc_id}/retry` | Xếp lại indexing hoặc cleanup bị lỗi |
| DELETE | `/api/documents/{doc_id}` | `202` và xếp tác vụ xóa; `409` nếu job hiện tại chưa kết thúc |
| GET | `/api/documents/{doc_id}/file` | URL PDF riêng tư, hiệu lực 300 giây |
| GET | `/api/documents/{doc_id}/chunks/{chunk_id}` | Đoạn trích gốc, tên PDF, trang |
| POST | `/api/chat` | `{query, doc_id, language: "vi", request_id}` + workspace header → SSE, kèm `X-Conversation-Id` |
| GET | `/api/conversations?doc_id=...&limit=20` | Hội thoại đang hoạt động của chính user; bỏ `doc_id` để lấy mới nhất trong workspace |
| GET | `/api/conversations/{id}` | Transcript, sources và cờ `stale` theo generation hiện tại |
| DELETE | `/api/conversations/{id}` | Xóa ngay hội thoại và messages của chính user (`204`) |
| GET | `/api/usage` | Plan, kỳ tháng hiện tại, lượt chat/tài liệu và cost theo user |

Mỗi user có workspace cá nhân với `id` bằng user id. Tài liệu chỉ thuộc về người tải (`owner_user_id`) và workspace đã chọn; owner workspace hay platform admin không đọc nội dung PDF/transcript, chỉ xem metadata và tổng hợp. Frontend hiện hỗ trợ chọn workspace; tạo/quản lý nhóm dùng API ở trên.

SSE: `sources` chứa `{citation_id, chunk_id, doc_id, page, source, score}`, `token` chứa text delta, `error` chứa `{message}`, `done` chứa chuỗi `"[DONE]"`. `score: null` cho tóm tắt toàn tài liệu. Response chat trả thêm header `X-Conversation-Id`; khi tải lại transcript, mỗi source có thêm `stale: true/false`.

Sau upload: `queued → processing → ready / error`; xóa: `deleting → deleted / delete_error`. Retry theo lịch vẫn là `queued` (hoặc `deleting`). Lỗi indexing thuộc trạng thái tài liệu, không thuộc request upload đã nhận `202`.

### Hạn mức theo gói

Workspace là đơn vị tính hạn mức; giới hạn seed trong bảng `doctrace.plan_limits`:

| Plan | Câu hỏi/tháng | Tài liệu | Workspace |
|---|---|---|---|
| Free | 10 | 5 | 1 |
| Pro | 100 | 50 | 10 |

- Lượt chat tính theo workspace và kỳ lịch UTC, reset lúc `00:00` ngày 1 tháng sau (`reset_at`). Đây là hạn mức tháng, tách biệt với giới hạn tần suất Redis bên dưới.
- Frontend sinh `request_id` UUID cho mỗi lần gửi và giữ nguyên khi retry cùng một câu hỏi. Server kiểm tra trùng trước burst limiter, rồi mới reserve quota trong một transaction Postgres (`chat_requests` + `usage_counters`), nên request đồng thời không thể vượt giới hạn.
- Request trùng không trừ thêm lượt: `409 request_completed`, `409 request_in_progress`, hoặc `409 request_failed` (request đã lỗi/bị hủy; phải gửi `request_id` mới).
- Hết lượt trả `429` với `code: "quota_exceeded"`, `metric`, `limit`, `used`, `reset_at`, `retry_after` và header `Retry-After`. Burst limit trả `429` với `code: "rate_limited"`; hai lỗi này được frontend hiển thị khác nhau.
- Lượt đã admit vẫn tính nếu stream lỗi hoặc người dùng dừng giữa chừng. Chat không trừ lượt khi tài liệu chưa ready hoặc không thuộc owner hiện tại.
- Tài liệu: upload pre-check `ZCARD` trước khi lưu Storage; `create()` kiểm tra lại trong `WATCH/MULTI`. Nếu hai upload tranh slot cuối, upload thua nhận `429 quota_exceeded` và PDF vừa lưu được xóa. Slot chỉ được giải phóng khi tài liệu đạt `deleted`; `error`/`delete_error` vẫn tính.
- `GET /api/usage` trả `{plan, period_start, reset_at, chat, documents, by_user}`. Owner thấy breakdown của mọi user; member chỉ thấy chính mình. Cost lấy từ `provider_calls`, gồm cả số call có cost `unknown`.

### Hội thoại & lưu trữ

- Một admission chat tạo/tìm conversation theo `(workspace, user, doc)`, ghi câu hỏi, placeholder assistant `pending` và `chat_requests` trong cùng transaction quota. Stream cập nhật `streaming`, rồi `complete`/`interrupted`/`error`; câu trả lời dở vẫn giữ phần đã gửi.
- `GET /api/conversations` chỉ trả hội thoại của user hiện tại trong workspace đang chọn. Owner workspace và platform admin không có endpoint đọc transcript của thành viên.
- “Chat mới” gọi `DELETE /api/conversations/{id}` và xóa vật lý hội thoại/messages ngay (demo chưa có lịch sử nhiều hội thoại). Reload khôi phục hội thoại mới nhất còn hiển thị cho tài liệu đang chọn.
- Xóa tài liệu ẩn transcript ngay khi API nhận `DELETE`. Mặc định giữ nội dung 30 ngày (`TRANSCRIPT_DELETE_MODE=retain_30d`) rồi purge; đặt `cascade` để xóa ngay. `TRANSCRIPT_RETENTION_DAYS` đổi cửa sổ giữ.
- Chạy `python -m app.purge_transcripts` từ `backend/` (hoặc trong worker container) hằng ngày để xóa conversation hết `purge_after`. `provider_calls` vẫn giữ số liệu cost, không chứa prompt/transcript.
- Khi tải transcript, server so `messages.index_id` với `active_index_id` hiện tại. Tài liệu chưa ready, đã xóa hoặc đã re-index khiến mọi source của message đó `stale`; frontend không mở chunk/PDF và hiện “nguồn không còn khả dụng”.

### Giới hạn tần suất (burst)

API dùng Redis sliding window: tối đa **5 upload/600 giây**, **10 chat/60 giây**, **3 retry indexing/600 giây** cho mỗi user, dùng chung giữa các tab và API process. Tóm tắt tính như chat; retry xóa và đọc thư viện không dùng giới hạn này. `UPLOAD_MAX_CONCURRENT` vẫn giới hạn riêng số request upload đang xử lý trong mỗi process.

Chỉnh `RATE_LIMIT_*` trong `backend/.env` theo mẫu `backend/.env.example`, rồi restart API; mọi API instance phải dùng cùng Redis và cấu hình. `RATE_LIMIT_ENABLED=false` tắt kiểm tra burst. Model LLM/embedding không ảnh hưởng cấu hình này. Lượt được cấp phép vẫn tính nếu xử lý tiếp theo thất bại; giới hạn mới sau khi đổi window chỉ phản ánh lịch sử còn lưu, không khôi phục lượt đã hết TTL.

Hết lượt burst trả `429` (`code: "rate_limited"`) + `Retry-After` (giây); frontend hiển thị thời gian chờ. Redis lỗi trả `503` trước Storage/enqueue/provider. Chat kiểm tra trước khi mở SSE. Key `doctrace:ratelimit:v1` có TTL riêng, không thay đổi TTL catalog hoặc RQ. Giới hạn này chỉ chặn thao tác user, không giới hạn request theo IP hay số lần worker gọi provider.

### Chi phí provider (OpenRouter)

Khi `DATABASE_URL` được cấu hình, API và worker ghi mỗi lượt gọi tính tiền vào `doctrace.provider_calls`: embedding truy vấn, embedding lúc index, từng lượt tóm tắt và câu trả lời. Mỗi dòng lưu workspace/user/document/job/request, model, token (gồm cached/reasoning), latency, `generation_id` và `cost_micros` dạng số nguyên micro-USD.

- Thiếu cost được ghi `cost_status='unknown'`, `cost_micros=NULL`; không bao giờ ghi `0` thay thế.
- Generation trùng được upsert, không tạo dòng thứ hai. Nếu response thiếu cost, server tra `GET /generation` một lần (best effort) và đánh dấu `reconciled`.
- Embedding nhiều batch gộp vào một dòng; nếu một batch thiếu cost, tổng được đánh dấu `unknown`. Dimension probe không tính.
- Không gửi cost qua SSE; dữ liệu để dành cho usage/admin UI.
- Ghi usage là best effort: lỗi Postgres không làm hỏng chat/indexing. Bỏ `DATABASE_URL` thì tắt ghi usage.
- `SUMMARY_MAX_CALLS` (mặc định 8) chặn tóm tắt quá lớn trước khi tốn thêm lượt gọi. SDK OpenRouter tắt retry tự động để một lượt logic không tạo request tính tiền ẩn.

## Kiểm tra

Từ `backend/` (pytest mock dịch vụ ngoài, không cần cloud credentials):

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
python -m pytest tests/test_chat.py::test_chat_sse_stream
python -m pytest tests/test_documents.py tests/test_worker.py
python scripts/verify_rate_limits.py
python scripts/verify_document_queue.py
```

`verify_rate_limits.py` cần Docker, tạo Redis riêng để kiểm tra Lua/sliding window, TTL, quota qua nhiều process và tranh lượt cuối bằng request đồng thời; tự dọn container, không dùng Redis ứng dụng.

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

Chẩn đoán thủ công từ `backend/`; retrieval gọi dịch vụ thật:

```sh
python scripts/inspect_pdf.py <path_to_pdf>
python scripts/inspect_retrieval.py <user_id> <doc_id> "câu hỏi" --top-k 8 --min-score 0.32
```

## Deploy

[DEPLOYMENT.md](DEPLOYMENT.md) hướng dẫn API + Redis + RQ worker + Nginx/Certbot; frontend deploy riêng. `/health` chỉ kiểm tra API process, không kiểm tra queue hay nhà cung cấp AI.
