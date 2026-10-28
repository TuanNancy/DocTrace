# Deploy: VPS Docker + Vercel + Supabase + Zilliz

```text
Browser / frontend trên Vercel
          │ HTTPS
          ▼
VPS: Nginx container ──→ api:8000 (FastAPI container)
          │                   └── Supabase Auth / Storage, Zilliz, OpenRouter
          └── certificate volume ← Certbot (chạy khi cấp/gia hạn)

FastAPI → Redis (thư viện + queue + quota) → RQ worker → Supabase S3 / Zilliz
   │                                  └──────→ cập nhật metadata Redis
   └──→ cache Redis riêng (đáp án exact, disposable)
```

## Trạng thái checkout

Bộ deploy chạy API, Redis, worker xử lý PDF và Nginx/Certbot bằng Docker Compose trên VPS Linux. Frontend deploy riêng trên Vercel; Supabase cung cấp Auth và bucket PDF private qua S3; Zilliz Cloud giữ vector/chunk qua `MILVUS_URI`/`MILVUS_TOKEN` (mặc định AUTOINDEX). Cấu hình frontend tham chiếu `frontend/.env.example` và `frontend/README.md`.

Tạo bucket PDF private, cấu hình Supabase Auth cùng S3 keys trong `backend/.env`, rồi chạy Redis và worker. Postgres giữ control plane (`doctrace` schema: workspace, membership, plan/quota, transcript, usage); Redis vẫn giữ thư viện/queue và PDF nằm trong Storage. Không dùng service-role key cho database. Bản PostgreSQL cũ chuyển sang thư viện Redis mới theo quy trình bên dưới và tải lại PDF.

`GET /health` là liveness của API process. `GET /ready` yêu cầu Redis và Postgres/schema/quyền runtime hợp lệ; Compose production và CD dùng endpoint này. Probe dùng kết nối riêng, connect/statement timeout 2 giây, không chờ pool query nghiệp vụ. Thiếu DB, thiếu migration/quyền hoặc runtime có quyền admin/DDL trả `503`. Theo dõi heartbeat và trạng thái tài liệu để kiểm tra worker, Supabase Auth/Storage, Milvus và OpenRouter.

## 1. Hiểu các image và service

| Service | Nguồn image | Vai trò |
|---|---|---|
| `migrate` | Cùng image API; `alembic upgrade head` | Một lần mỗi deploy: tạo/cập nhật schema `doctrace` trước API/worker |
| `api` | Build từ `backend/Dockerfile` + context `backend/` | Python, dependency và code FastAPI |
| `worker` | Cùng image API; `python -m app.worker` | RQ + scheduler: indexing, xóa, timeout/retry |
| `redis` | `redis:7.4.8-alpine` | Thư viện + queue/RQ; AOF `everysec`, volume `redis_data`, `noeviction` |
| `cache` | `redis:7.4.8-alpine` | Cache đáp án exact; không persist, `allkeys-lru`, tách hoàn toàn khỏi Redis thư viện/queue |
| `nginx` | Image `nginx:1.28-alpine` có sẵn | TLS, reverse proxy, upload/SSE |
| `certbot` | Image `certbot/certbot:v5.1.0` có sẵn | Cấp/gia hạn certificate qua HTTP-01 |

`docker build` tạo image; `docker compose up` tạo/chạy container từ image. Compose thiết lập network, env, mount và healthcheck. API image không chứa database server hay frontend. Frontend được build/deploy riêng trên Vercel với Root Directory là `frontend`.

Root `docker-compose.yml` chạy Redis + cụm Milvus; profile `jobs` thêm worker. Production chạy API + Redis + cache Redis + worker + Nginx; Certbot ở profile `tools`.

## 2. Chuẩn bị VPS, DNS và env

Các lệnh vận hành bên dưới dùng shell Linux trên VPS. Cài Docker Engine và Compose v2 hỗ trợ `up --wait`.

1. Đặt repository tại `/opt/DocTrace` (hoặc sửa đường dẫn trong systemd service nếu dùng chỗ khác).
2. Trỏ DNS `api.YOUR-DOMAIN` tới địa chỉ public ổn định của VPS.
3. Cho phép inbound TCP **80 và 443**. Port 80 cần giữ mở để HTTP-01 renewal hoạt động.
4. API port 8000 chỉ nằm trong Docker network; không publish ra VPS.

Nếu đang có container Caddy phục vụ domain này, xác định nó bằng `docker ps` và dừng trước khi bootstrap Nginx để nhả cổng 80/443. Giữ lại cấu hình/volumes cũ cho rollback; bộ deploy mới dùng certificate volumes riêng.

Từ repository root:

```sh
cp .env.production.example .env.production
```

Điền:

```dotenv
API_DOMAIN=api.YOUR-DOMAIN
ACME_EMAIL=YOUR-EMAIL
TLS_MODE=https
```

Copy `backend/.env.example` thành `backend/.env`, giữ các giá trị tuning mặc định rồi điền:

| Nhóm | Biến / giá trị |
|---|---|
| Supabase Auth | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` từ project |
| Postgres control plane | `DATABASE_URL` (runtime, login `doctrace_app`, session pooler hỗ trợ IPv4). Lưu riêng `DIRECT_DATABASE_URL` (migration/DDL) trong `backend/.env.migrations` |
| PDF private | `SUPABASE_S3_ENDPOINT`, `SUPABASE_S3_REGION`, `SUPABASE_S3_ACCESS_KEY_ID`, `SUPABASE_S3_SECRET_ACCESS_KEY`, `SUPABASE_STORAGE_BUCKET` theo S3 settings của cùng project |
| Zilliz Cloud | `MILVUS_URI` là endpoint HTTPS của cluster; `MILVUS_TOKEN` là credential được cấp quyền truy cập; `MILVUS_COLLECTION=pdf_chunks_owned_v1` |
| OpenRouter | `OPENROUTER_API_KEY`, `RAG_MODEL`, `EMBEDDING_MODEL` theo model bạn chọn |
| Usage/cost | Giữ `DATABASE_URL` cho cả API và worker để ghi `doctrace.provider_calls`; `SUMMARY_MAX_CALLS=8` giới hạn lượt tóm tắt mỗi request |
| Cache đáp án | `ANSWER_CACHE_URL` trỏ Redis cache riêng (Compose đặt `redis://cache:6379/0`); để trống để tắt. `ANSWER_CACHE_TTL_SECONDS` mặc định 259200 (3 ngày) |
| Routing/ngân sách | `MODEL_ROUTING_ENABLED=false` mặc định; nếu bật phải đặt `CHEAP_MODEL`. `REQUEST_COST_CAP_MICROS=100000`, giá `MODEL_*_MICROS_PER_MTOK`/`CHEAP_*_MICROS_PER_MTOK` phải khớp model thật |
| Transcript | `TRANSCRIPT_DELETE_MODE=retain_30d` hoặc `cascade`; `TRANSCRIPT_RETENTION_DAYS=30`. Chạy purge định kỳ (xem bên dưới) |
| Admin / lỗi | Seed platform admin bằng migration identity; `SENTRY_DSN` tùy chọn (bỏ trống để tắt), `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE` |
| Queue | `RQ_QUEUE_NAME=documents-v2`; Compose đã override `REDIS_URL` cho API/worker |

S3 access key/secret là credential riêng của Storage, không phải Supabase publishable key. Giữ `MILVUS_INDEX_TYPE` không khai báo để URI mode chọn AUTOINDEX. Dùng collection mới cho bộ embedding mới; không trộn vector từ hai model hoặc recreate collection đang có dữ liệu.

### Tách credential runtime và migration

Postgres dùng schema riêng `doctrace`; không expose qua Supabase Data API. Runtime bắt buộc dùng login ít quyền riêng. Chuẩn bị trước khi deploy bản kiểm tra `/ready` chặt hơn:

1. Copy `backend/.env.migrations.example` thành `backend/.env.migrations`, điền `DIRECT_DATABASE_URL` bằng role sở hữu schema/migration. Bọc URL trong dấu nháy đơn nếu source file từ shell; percent-encode ký tự đặc biệt trong password. File này được Git ignore và chỉ inject vào service `migrate`. Có thể đổi đường dẫn bằng `MIGRATION_ENV_FILE` trong `.env.production`.
2. Kết nối `psql` bằng migration identity qua direct/session pooler; dùng `\i deploy/postgres/bootstrap-runtime-role.sql` từ repository root, sau đó `\password doctrace_app` để đặt password riêng bằng prompt. Script idempotent, không reset password và từ chối role đã có quyền admin/role membership.
3. Chạy `alembic upgrade head` bằng credential migration để áp dụng schema và grant cụ thể cho `doctrace_app` (kể cả khi đã ở head). Runtime chỉ có quyền DML cần thiết và `EXECUTE` hàm tra cứu Auth riêng: không DDL, không sửa plan definitions/platform admins/migration stamp và không sửa/xóa audit. Không cấp quyền trực tiếp trên `auth`, `storage`, `realtime` hay mặc định quyền trên bảng tương lai.
4. Đổi `DATABASE_URL` trong `backend/.env` sang role mới và bỏ `DIRECT_DATABASE_URL` khỏi file runtime. Với Supabase shared session pooler, dùng host/port từ Dashboard Connect và username `doctrace_app.PROJECT_REF` thay `postgres.PROJECT_REF`, password riêng của role; direct connection dùng username `doctrace_app`. Giữ SSL. API/worker chỉ nhận file runtime.
5. Recreate API/worker và kiểm tra `/ready`, upload → ready → chat. Quyền `CREATE` kế thừa từ `PUBLIC` trên schema tùy biến cũng làm readiness thất bại; kiểm tra và thu hồi grant rộng đó bằng migration identity nếu database cũ có cấu hình này.

Alembic chỉ nhận `DIRECT_DATABASE_URL` hoặc URL test được cấp rõ ràng, không fallback sang `DATABASE_URL`. Local shell dùng subshell như README. Production migration chạy qua `migrate` và `deploy/deploy.sh`; nếu migration lỗi, deployment dừng trước khi recreate API/worker. Với cập nhật thủ công, build image mới trước migration:

```sh
docker compose --env-file .env.production -f compose.production.yml build api
docker compose --env-file .env.production -f compose.production.yml run --rm --no-deps migrate
```

Migration `0002_auth_member_lookup` thêm `doctrace.auth_user_exists(uuid)` để owner thêm đúng tài khoản Auth đang tồn tại. Hàm `SECURITY DEFINER` trả boolean, cố định `search_path`, chỉ đọc `id`/`deleted_at` của `auth.users` bằng quyền migration owner; `row_security=off` báo lỗi nếu owner mất quyền bypass RLS. Trên Supabase hosted, dùng migration identity `postgres` vốn có quyền đọc Auth và bypass RLS. Nếu dùng role migration tùy chỉnh, role đó phải có quyền tương đương cho đúng phép đọc này; kiểm tra trước khi chuyển credential. Backend kiểm tra owner trước khi gọi hàm, trả `404 member_user_not_found` cho tài khoản không tồn tại/đã xóa, kể cả thêm lại thành viên cũ.

Supabase hosted không cho `postgres` cấp `USAGE` schema `auth` cho custom role. Vì vậy migration chỉ tạo hàm trong `doctrace`, không thay policy hay ACL của Auth, và thu hồi `EXECUTE` khỏi `PUBLIC`/`anon`/`authenticated`/`service_role`. Không thêm `doctrace_app` vào các role Data API để né lỗi quyền. `/ready` kiểm tra quyền gọi hàm, cấu hình definer, quyền Auth thừa và chạy thử lookup để phát hiện quyền underlying bị thiếu. Tham khảo [hướng dẫn Supabase](https://supabase.com/kb/troubleshooting/permission-errors-when-granting-custom-roles-access-to-the-auth-schema).

Migration `0003_admin_observability` thêm `workspace_purges`, `workspace_purge_documents`, `document_failures`, cột timing của `chat_requests` và bỏ FK audit→workspace để giữ lịch sử sau hard purge. Runtime chỉ nhận DML cần thiết; bảng lỗi/audit là append-only. Seed platform admin bằng migration identity (runtime không có quyền ghi bảng này). Chỉ cấp cho tài khoản vận hành thực sự:

```sql
INSERT INTO doctrace.platform_admins (user_id)
VALUES ('AUTH-USER-UUID')
ON CONFLICT (user_id) DO NOTHING;
```

Gỡ quyền bằng `DELETE FROM doctrace.platform_admins WHERE user_id = ...` bằng cùng identity. Admin UI/API kiểm tra bảng này sau Auth; owner workspace không tự động có quyền. Admin chỉ thấy metadata/định danh/cost, không đọc PDF, chunk hay transcript.

Migration `0004_answer_cache` thêm cột `chat_requests.cache_hit` (mặc định `false`, tương thích image cũ trong rollout). Cache đáp án không nằm trong Postgres và không dùng chung Redis thư viện/queue: Compose production chạy service `cache` riêng, không volume, `maxmemory=64mb`, `allkeys-lru`; mất cache chỉ làm tăng chi phí/latency, không mất tài liệu hay quota. `/ready` kiểm tra cột mới; API/worker vẫn cần migration hoàn tất trước khi nhận traffic.

Worker duy trì outbox lỗi terminal và tiến trình purge mỗi chu kỳ maintenance (idle dequeue tối đa 30 giây). Có thể chạy bù một lượt giới hạn bằng:

```sh
docker compose --env-file .env.production -f compose.production.yml exec -T worker python -m app.purge_workspaces
```

Lệnh này drain `document_failures` và advance purge đang `running`; không xóa workspace chưa archive, không tự retry tài liệu `delete_error` (admin phải retry có audit), và không đụng workspace khác. Purge chỉ hoàn tất sau khi manifest xác nhận mọi tài liệu đã `deleted`; lỗi/restart để lại trạng thái `purging` để chạy tiếp. Sentry chỉ gửi event đã scrub; đặt `SENTRY_DSN` trong runtime env của cả API/worker và restart cả hai.

Schema được tạo/xóa bằng Alembic. Không chạy `down -v` để "làm sạch" database; `down -v` chỉ xóa volume Redis/certificate. Không auto-downgrade khi rollback image: migration dùng expand/contract để image cũ vẫn đọc được schema mới trong thời gian chuyển tiếp.

`provider_calls` ghi usage/cost theo từng lượt provider. API và worker phải cùng có `DATABASE_URL` để ghi; nếu thiếu thì không lưu cost (workspace/quota vẫn yêu cầu Postgres). Ghi usage là best effort nên lỗi Postgres không làm hỏng request; cost thiếu được lưu `unknown`/`NULL`, không phải `0`. Bảng này không chứa nội dung PDF hay prompt.

P2b dùng lại `plan_limits`, `usage_counters` và `chat_requests` đã có trong migration `0001`, không cần migration mới. Seed mặc định: free `10` câu hỏi/tháng, `5` tài liệu, `1` workspace; pro `100`, `50`, `10`. Chat reserve quota trong một transaction Postgres nên nhiều API instance/request đồng thời không vượt giới hạn; upload kiểm tra lại số tài liệu trong transaction Redis. Thiếu hoặc lỗi Postgres trả `503 quota_unavailable` trước khi mở SSE/lưu PDF. Hạn mức chat reset theo tháng UTC. `GET /api/usage` trả `scope=workspace` cho owner, `scope=self` cho member; member chỉ thấy số câu hỏi/tài liệu/chi phí của mình và `remaining=null`. Hạn mức gói vẫn áp dụng chung cho workspace. `costs.known_micros` và `costs.unknown_calls` là tổng chi phí đã biết và lượt thiếu giá đã được ghi nhận trong tháng. Frontend hiển thị USD; triển khai API hỗ trợ contract này trước frontend mới. Muốn đổi giới hạn cho demo, cập nhật `doctrace.plan_limits` bằng migration/DDL có kiểm soát, không sửa trực tiếp Redis.

Chat giữ nguyên `request_id` cho thao tác thử lại thủ công sau mất kết nối. Nếu backend trả `request_completed`, frontend lấy lại transcript thay vì gửi câu hỏi mới; `request_in_progress` cho phép kiểm tra lại sau. `request_failed` cần thao tác gửi lại rõ ràng và dùng lượt mới. Không tự động POST lại khi chưa rõ kết quả admission. ID chờ khôi phục nằm trong bộ nhớ của phiên giao diện; reload trang khôi phục transcript đã lưu.

P3 cũng dùng lại `conversations`/`messages` trong migration `0001`, không cần migration mới. Admission ghi conversation + câu hỏi + placeholder assistant cùng transaction quota; stream cập nhật nội dung/nguồn/trạng thái cuối. Transcript chỉ đọc được bởi chính user trong workspace; owner không thấy hội thoại của thành viên. Xóa tài liệu ẩn transcript ngay; mặc định purge sau `TRANSCRIPT_RETENTION_DAYS=30` ngày, hoặc xóa ngay với `TRANSCRIPT_DELETE_MODE=cascade`.

Xóa tài liệu và admission chat dùng cùng transaction advisory lock theo workspace/user/document. Chỉ khi Redis chấp nhận xóa mới áp dụng retention; `404`/`409` do sai owner hoặc job còn chạy không làm mất transcript. Nếu Redis đã commit nhưng Postgres lỗi, API có thể trả `503`; list/get transcript vẫn ẩn theo trạng thái Redis. Worker hoàn tất retention trước khi dọn PDF/vector và retry nếu Postgres chưa phục hồi. `delete_requested_at` giữ mốc retention ban đầu qua các lần retry. Cần triển khai API và worker cùng phiên bản.

Unit purge được lưu trong repository, chạy hằng ngày lúc **03:00 UTC**, chạy bù sau downtime bằng `Persistent=true`. Từ `/opt/DocTrace`, cài hoặc cập nhật:

```bash
sudo install -m 644 deploy/systemd/doctrace-transcript-purge.service deploy/systemd/doctrace-transcript-purge.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now doctrace-transcript-purge.timer
sudo systemctl start doctrace-transcript-purge.service
sudo systemctl list-timers doctrace-transcript-purge.timer
sudo journalctl -u doctrace-transcript-purge.service -n 30 --no-pager
```

Có thể chạy tay `docker compose --env-file .env.production -f compose.production.yml exec -T worker python -m app.purge_transcripts`; lệnh chỉ xóa conversation có `purge_after < now()`, không đụng `provider_calls`, Redis, PDF hay Milvus. Timer cần worker đang chạy; lỗi được ghi vào journal để kiểm tra và chạy lại. Tránh cài thêm cron trùng lịch. Nếu checkout khác `/opt/DocTrace`, sửa `WorkingDirectory` trong service trước khi cài.

Đặt đúng origin frontend Vercel (không có path):

```dotenv
CORS_ALLOW_ORIGINS=https://YOUR-FRONTEND
```

**Networking:** `MILVUS_URI` được ưu tiên hơn host/port, nên VPS dùng endpoint Zilliz thay vì chạy cụm Milvus local. Dùng `compose.production.yml` cho production; `docker compose up -d` không chỉ định file sẽ chạy stack phát triển gồm Milvus/etcd/MinIO. `localhost` trong API container là chính container đó.

API và worker có giới hạn riêng `1400m`; Redis `256m`, cache `96m`, Nginx `128m` (tổng khoảng 3.2 GiB chưa tính OS). Redis `maxmemory=128mb` chừa dung lượng cho persistence; khi đầy nó từ chối ghi và API báo lỗi để người dùng thử lại. Cache dùng `maxmemory=64mb` và `allkeys-lru`; đầy cache chỉ gây miss. Redis chỉ truy cập qua mạng Docker, không publish port production. Metadata tài liệu không có TTL; theo dõi RAM và backup volume vì Redis giữ toàn bộ thư viện.

Compose đặt `REDIS_URL=redis://redis:6379/0` cho API và worker. Cả hai phải dùng cùng `RQ_QUEUE_NAME` (mặc định `documents-v2`). `DOCUMENT_INDEX_TIMEOUT_SECONDS=900`, `DOCUMENT_DELETE_TIMEOUT_SECONDS=300`; tăng timeout cần điều chỉnh `stop_grace_period` (mặc định 16 phút) tương ứng. RQ graceful shutdown chờ job hiện tại; force kill cần chờ RQ phát hiện job bị bỏ dở và lên lịch retry.

Service `cache` chỉ phục vụ exact-answer cache và không cần backup: xóa/restart cache chỉ làm miss toàn bộ. Không trỏ `ANSWER_CACHE_URL` vào `redis` thư viện/queue và không bật persistence cho cache. Theo dõi `docker compose ... logs cache` và `docker stats`; cache đầy sẽ tự loại key cũ (`allkeys-lru`). Cache hit vẫn tính một lượt quota nhưng không ghi `provider_calls`; admin report có `cache_hits`.

`backend/.env` và `backend/.env.migrations` được inject riêng lúc chạy; không copy vào image. Cả hai cùng `.env.production` được Git ignore; giới hạn quyền đọc các file credential trên host (`chmod 600`). Các giá trị `NEXT_PUBLIC_*` của frontend được cấu hình trên Vercel; API URL phải dùng HTTPS.

### Đánh giá RAG và chi phí model

Golden set và baseline nằm trong repository (`backend/evals/`); VPS không cần thêm service. Chạy smoke offline trong CI hoặc từ checkout:

```sh
cd backend
python -m pip install -r requirements-dev.txt
python -m evals --mode smoke
```

`verify.yml` chạy smoke và upload artifact; smoke không gọi provider. Live eval chỉ chạy khi cấu hình secret `OPENROUTER_EVAL_API_KEY` trong GitHub Actions (workflow `.github/workflows/eval-live.yml`). Dùng project/key OpenRouter riêng với hard budget cho eval, không dùng key production; CLI còn giới hạn `--budget-micros` và `--request-cap-micros` như guardrail thứ hai:

```sh
python -m evals --mode live --budget-micros 2000000 --request-cap-micros 100000 --plan pro
```

Nếu bật routing production, đặt `CHEAP_MODEL` và giá micro-USD/triệu token cho cả hai model. `REQUEST_COST_CAP_MICROS` chặn trước khi gọi provider và trả `budget_exceeded` thay vì âm thầm đổi model. Sau khi đổi prompt/retrieval/model hoặc golden set, chạy live eval và cập nhật baseline có review; threshold live hiện là provisional cho tới lần chạy thật đầu tiên.

### Vercel và kết nối Auth/API

Import repository vào Vercel, chọn framework Next.js và **Root Directory `frontend`**. Dùng build command `npm run build` và Node 22 như CI. Đặt các biến trong môi trường Production:

```dotenv
NEXT_PUBLIC_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY=YOUR-PUBLISHABLE-KEY
NEXT_PUBLIC_SITE_URL=https://YOUR-FRONTEND
NEXT_PUBLIC_GOOGLE_CLIENT_ID=YOUR-WEB-CLIENT-ID.apps.googleusercontent.com
NEXT_PUBLIC_API_URL=https://api.YOUR-DOMAIN
```

API URL là origin, không thêm `/api`; để trống sẽ bật demo upload/chat. Browser gọi trực tiếp HTTPS API trên VPS, gồm upload và SSE. Không đưa S3 credentials, Zilliz token hoặc OpenRouter key vào biến frontend.

Trong Supabase Auth, đặt Site URL bằng origin frontend và allowlist `https://YOUR-FRONTEND/auth/login` cho email confirmation. Google login dùng Google Identity Services: thêm origin frontend vào **Google Auth Platform → Clients → Authorized JavaScript origins**, bật Google provider trong Supabase với cùng Web Client ID. Giữ Client Secret ở Supabase; giữ **Skip nonce checks** tắt. Đặt `NEXT_PUBLIC_GOOGLE_CLIENT_ID` trên Vercel rồi rebuild/redeploy; bỏ trống thì chỉ có đăng nhập email.

Popup trả ID token trực tiếp cho frontend, không dùng Vercel redirect URI trong Google Console. Giữ callback `https://YOUR-PROJECT.supabase.co/auth/v1/callback` nếu còn cần OAuth cũ; allowlist `/auth/callback` trong Supabase cho luồng cũ đó. Route `/auth/callback` không nhận Google ID token trực tiếp. Nếu Audience của Google ở Testing, thêm tài khoản vào Test users. Xem [frontend/README.md](frontend/README.md#google-login-google-identity-services) để cấu hình local và kiểm tra đăng nhập thật. CORS backend phải chứa origin frontend; Vercel Preview cần đăng ký riêng origin Google và URL email redirect tương ứng.

Sau khi API đã có HTTPS, deploy/redeploy frontend; thay `NEXT_PUBLIC_*` cần rebuild trên Vercel. Kiểm tra thực tế theo luồng: đăng nhập → upload PDF → chờ ready → chat/citation → mở PDF → reload khôi phục transcript → “Chat mới” xóa transcript → trang Mức sử dụng → xóa tài liệu. Với platform admin đã seed, mở `/admin`, kiểm tra metadata không lộ tên/nội dung, đổi plan, archive/restore và chỉ purge một workspace test sau khi archive với đúng UUID.

### Rate limit theo user

API mặc định giới hạn upload 5/600 giây, chat 10/60 giây và retry indexing 3/600 giây qua Redis dùng chung. Đây là burst limit, tách biệt với hạn mức tháng của plan trong Postgres. `RATE_LIMIT_*` nằm trong `backend/.env`; mọi API instance cần cùng cấu hình. Đổi env phải recreate API để Compose inject lại giá trị (lệnh cập nhật ở mục 5). `RATE_LIMIT_ENABLED=false` tắt burst limit; không cần xóa Redis.

Hết burst limit trả `429` (`code: "rate_limited"`) + `Retry-After`; Redis lỗi trả `503`. Hết hạn mức tháng trả `429` (`code: "quota_exceeded"`) kèm `reset_at`. Key burst tự hết TTL, còn catalog không có TTL. Các giới hạn này độc lập với model và không phải giới hạn số lần worker gọi OpenRouter. Chạy `python scripts/verify_rate_limits.py` từ `backend/` để kiểm tra bằng Redis Docker riêng trước deploy.

## 3. Lần đầu: bootstrap HTTP → cấp certificate → bật HTTPS

### Bước A — Khởi động HTTP cho ACME

```sh
sh deploy/certificates.sh bootstrap
```

Lệnh này build image, chạy API + worker + Redis + Nginx. Redis/API/Nginx có healthcheck; worker được kiểm tra ở mức process running. Nó tạm đặt `TLS_MODE=http` cho lần chạy đó; file `.env.production` vẫn là `https`.

Bootstrap chỉ phục vụ:

- `/.well-known/acme-challenge/*`: Certbot đặt file xác thực tại đây.
- `/nginx-health`: kiểm tra process Nginx.
- Các đường dẫn khác: **503**, vì API chưa được mở qua HTTP.

Kiểm tra DNS/firewall từ bên ngoài VPS:

```sh
curl --fail http://api.YOUR-DOMAIN/nginx-health
```

### Bước B — Cấp certificate và chuyển sang HTTPS

```sh
sh deploy/certificates.sh issue
```

Script chạy Certbot webroot với email/domain trong `.env.production`, chấp nhận Let's Encrypt Terms of Service bằng `--agree-tos`, đặt tên certificate cố định là `doctrace`. Sau khi cấp thành công, nó chuyển Nginx sang HTTPS, kiểm tra `nginx -t` rồi reload.

Nếu Certbot thất bại, script dừng và giữ bootstrap HTTP để sửa DNS/firewall rồi thử lại. HTTPS mode sẽ từ chối khởi động nếu chưa có certificate; không dùng certificate giả để phục vụ production.

```sh
curl --fail https://api.YOUR-DOMAIN/health
```

Kỳ vọng: `{"status":"ok"}`. HTTP thông thường được redirect 308 sang domain HTTPS đã cấu hình. Đường dẫn ACME vẫn phục vụ qua HTTP để gia hạn.

## 4. Gia hạn tự động

Certbot và Nginx chia sẻ hai named volume:

- `certificates`: toàn bộ `/etc/letsencrypt`, gồm account, live/archive và renewal config; Certbot read-write, Nginx read-only.
- `acme_webroot`: file HTTP-01 challenge; Certbot read-write, Nginx read-only.

Script chạy trên **host**, không mount Docker socket vào Certbot:

```sh
sh deploy/certificates.sh renew
```

Nếu certificate chưa cần gia hạn, Certbot trả thành công mà không thay đổi file. Script vẫn kiểm tra config và graceful reload Nginx. Nếu Certbot hoặc `nginx -t` lỗi, không gửi tín hiệu reload.

Sau khi HTTPS đã hoạt động, cài systemd timer:

```sh
sudo cp deploy/systemd/doctrace-cert-renew.service /etc/systemd/system/
sudo cp deploy/systemd/doctrace-cert-renew.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now doctrace-cert-renew.timer
sudo systemctl list-timers doctrace-cert-renew.timer
```

Timer kiểm tra hai lần/ngày với độ trễ ngẫu nhiên tối đa một giờ. Nếu repo không ở `/opt/DocTrace`, sửa cả `WorkingDirectory` và `ExecStart` trong service trước khi cài. Có thể đặt `DEPLOY_ENV_FILE` thành đường dẫn tuyệt đối nếu dùng env file khác.

Kiểm tra renewal với ACME staging sau khi đã cấp certificate thật:

```sh
docker compose --env-file .env.production -f compose.production.yml run --rm certbot renew --dry-run
sudo journalctl -u doctrace-cert-renew.service
```

`--dry-run` có gọi Let's Encrypt staging; đây là bước vận hành trên domain thật, khác với test local tự ký.

## 5. Cập nhật và quan sát

Sau lần cấp certificate đầu tiên, nếu chưa bật CD, build image mới trước bước migration:

```sh
docker compose --env-file .env.production -f compose.production.yml build api
docker compose --env-file .env.production -f compose.production.yml run --rm --no-deps migrate
docker compose --env-file .env.production -f compose.production.yml up -d --no-build --wait api worker nginx
docker compose --env-file .env.production -f compose.production.yml ps
docker compose --env-file .env.production -f compose.production.yml logs --tail=100 api worker redis nginx
docker compose --env-file .env.production -f compose.production.yml exec nginx nginx -t
```

Sửa file template trên host không tự render lại config. Sau khi sửa, chạy:

```sh
docker compose --env-file .env.production -f compose.production.yml up -d --force-recreate --wait nginx
```

Certificate renewal chỉ đổi file PEM, nên graceful reload là đủ. Giữ nguyên tên project Compose giữa các lệnh và timer để dùng đúng volumes. `down` giữ named volumes; **`down -v` xóa certificate/account state**. Không dùng bootstrap cho một deployment đã chạy HTTPS.

Khi đã bật CD (mục 8), cập nhật code qua workflow hoặc `deploy/deploy.sh`. Script quản lý checkout detached và tag `API_IMAGE` theo commit; không chạy `git pull` hoặc `up --build` trên tag release đã ghi nhận. Sau khi chỉ sửa `backend/.env`, dùng `up -d --no-build --wait api worker` với cùng production Compose/env để inject lại cấu hình.

`POST /api/upload` trả `202` sau khi giữ PDF và xác nhận Redis đã ghi metadata/enqueue. Redis tắt thì trả `503`. RQ thực thi và retry sau 10/30 giây; tối đa ba lần mỗi job. API đối chiếu metadata với RQ khi đọc thư viện, để lỗi trước task hoặc job bị mất trở thành lỗi có thể thử lại. Job `started` bị bỏ dở phải chờ RQ heartbeat/registry maintenance trước khi retry; restart worker không có nghĩa hoàn tất ngay. Xóa/retry trả `409` khi còn job đang chạy hoặc chờ.

Quan sát queue mặc định bằng:

```sh
docker compose --env-file .env.production -f compose.production.yml exec worker rq info --url redis://redis:6379/0
```

Theo dõi worker heartbeat, queue `documents-v2`, RAM Redis và trạng thái `error/delete_error`. Platform admin xem `/admin` hoặc `GET /api/admin/health`, `GET /api/admin/overview`, `GET /api/admin/failures` để có queue depth/oldest job, Milvus, lỗi terminal, cost và latency p50/p95. Log nối bằng `request_id`, `workspace_id`, `user_id`, `doc_id`, `job_id`, `attempt`. Upload ghi request ID cùng transaction catalog/enqueue; automatic retry giữ ID, retry/delete thủ công ghi ID mới. `LOG_JSON=true` bật JSON; cả JSON và text chỉ ghi event đăng ký, metadata cho phép, exception class và vị trí code. SDK/RQ/SQL không ghi raw messages/parameters/exception values; RQ failure records dùng thông báo chung.

Nginx phát JSON access log gồm route label, request ID, status/upstream status và thời gian; bỏ raw URL/query/header/IP/body. Request-level error log được tắt vì Nginx không hỗ trợ scrub request line; dùng access status `4xx/5xx` và log API để truy lỗi. Lỗi startup/config vẫn có diagnostic của Nginx. `X-Request-ID` được validate/generate tại proxy và truyền tới API. `/ready` là health gate; `/health` là liveness.

`down -v` xóa thư viện và queue trong Redis. AOF `everysec` có cửa sổ mất ghi gần nhất khi crash; PDF/vector riêng không tự khôi phục được danh mục nếu mất volume. Sau sự cố Storage/Redis ở thời điểm không xác định, có thể cần dọn PDF/vector không còn trong thư viện bằng tay; không có periodic cleanup service.

### Chuyển từ thư viện PostgreSQL sang Redis

1. Giữ image/cấu hình cũ để có thể quay lại. Trên checkout cũ, dừng API và dispatcher; chờ hoặc dừng worker có kiểm soát. Xác nhận các process cũ đã dừng trước khi đổi code.
2. Đặt `RQ_QUEUE_NAME=documents-v2` trong `backend/.env` cho API/worker; bỏ biến service-role và dispatch-poll cũ. Namespace metadata mới là `doctrace:library:v2`. Queue mới tránh nhận payload của worker cũ; không dùng lại tên queue `documents` khi cutover.
3. Deploy API/worker mới bằng lệnh cập nhật ở trên; service `migrate` tạo schema control plane trước khi API/worker start. Gỡ container dispatcher cũ đã dừng bằng `docker compose --env-file .env.production -f compose.production.yml up -d --remove-orphans`; giữ nguyên Compose project và volumes.
4. Thư viện Redis mới bắt đầu trống. Tải lại PDF cần dùng, xác nhận ready → chat/citation → xóa. Các bảng PostgreSQL, PDF và vector cũ không bị tự động xóa; không import metadata cũ và không dùng chúng làm control plane.

Rollback: dừng API/worker mới rồi dùng lại checkout/image và cấu hình cũ với database cũ. Tài liệu tải lên thư viện Redis mới không tự xuất hiện trong thư viện cũ. Không chạy hai phiên bản worker trên cùng queue và không dùng `FLUSHDB`/`down -v` để chuyển phiên bản.

### Backfill workspace P1

P1 đọc được bản ghi cũ thiếu `workspace_id`/`owner_user_id` bằng cách gán về workspace cá nhân của người tải. Backfill chỉ cần khi nâng cấp một thư viện Redis đã có tài liệu; script giữ nguyên `user_id`, ghi metadata chuẩn hóa và dựng lại sorted set workspace/global. Mặc định dry run, chạy lại an toàn, không xóa Redis hay Milvus.

Từ root checkout deploy, chạy dry run trong container API (image production không chứa `scripts/`, nên mount file):

```sh
docker compose --env-file .env.production -f compose.production.yml run --rm --no-deps \
  -v "$PWD/backend/scripts/backfill_workspaces.py:/app/backfill_workspaces.py:ro" \
  api python /app/backfill_workspaces.py
```

Kiểm tra `scanned`, `hashes_updated`, `personal_workspaces`, `skipped_invalid`, `index_entries_added`, `index_entries_removed` và `deleted_records`; sau đó chạy lại với `--apply`. `hashes_updated=0` không có nghĩa index đã đúng: tombstone có thể vẫn cần loại khỏi index. Script giữ hash `deleted`, nhưng xóa ID đó khỏi cả bốn sorted set; các trạng thái `error`/`delete_error` vẫn chiếm quota.

`.env.production` phải trỏ đúng Redis và `DATABASE_URL`. API/worker có thể tiếp tục chạy: mỗi bản ghi được đọc lại dưới `WATCH`, metadata và index được cập nhật cùng `MULTI/EXEC`; khi worker publish/xóa đồng thời, script đọc lại trạng thái mới. Sau 10 tranh chấp trên cùng bản ghi, script dừng để có thể chạy lại, thay vì ghi đè snapshot cũ. Index per-user cũ vẫn được duy trì để rollback image. Sau apply, dry run lại và kiểm tra cả số index thêm/xóa cần thiết.

## 6. Upload và SSE

Nginx được cấu hình:

- `client_max_body_size 55m`: chừa multipart overhead cho PDF tối đa 50 MiB ở API.
- `proxy_request_buffering off`: chuyển upload tới API liên tục.
- `proxy_buffering off`, `proxy_cache off`, `gzip off`: trả SSE ngay khi có dữ liệu.
- `proxy_read_timeout 300s`: giới hạn thời gian im lặng giữa các lần đọc, không phải tổng thời lượng stream.
- `proxy_ignore_client_abort off`: đóng client thì hủy request upstream.
- Docker DNS resolver: tìm lại IP của `api` khi container được tạo lại.

Nginx là public edge: nó ghi đè các forwarding headers do client gửi. Nếu sau này thêm CDN/load balancer trước Nginx, cần cấu hình trusted proxy tương ứng thay vì tin mọi `X-Forwarded-For`.

## 7. Kiểm thử local/CI

Yêu cầu Docker đang chạy và Python 3.10+ trên host. Từ repository root:

```sh
docker build -t doctrace-api:verify ./backend
python deploy/tests/verify_nginx.py --api-image doctrace-api:verify
docker run --rm -v "$PWD/deploy:/workspace/deploy:ro" doctrace-api:verify python -m unittest discover -s /workspace/deploy/tests -p test_certificates.py -v
```

Trong PowerShell, dùng đường dẫn tuyệt đối cho tham số `-v` ở lệnh cuối.

Integration test dùng production Compose/templates với project name ngẫu nhiên, ports loopback ngẫu nhiên, auth/RAG giả lập và certificate tự ký. Nó kiểm tra bootstrap, TLS, redirect, forwarding/CORS, upload limit, stream trước khi upstream hoàn tất, cancellation, certificate rotation, API recreation và privacy log khi lỗi 404/413/502/504. Proxy fixture dùng `/health` vì không có Postgres; production dùng `/ready`. Containers/volumes test được dọn trong `finally`; không gọi ACME hay dịch vụ AI thật.

CI chạy backend tests, deployment checks và frontend typecheck/lint/Vitest/Chromium/build. Frontend checks dùng cấu hình public giả và Auth/API fixtures local; chưa chứng minh dịch vụ cloud thực đã được kết nối đúng.

Kiểm tra script CD trên Linux (Python 3.12, Git, Bash và `flock`; Docker CLI/HTTPS được giả lập):

```sh
python3 -m unittest discover -s deploy/tests -p test_deploy.py -v
```

Các test dùng repository Git tạm và kiểm tra đúng SHA, lượt CI đến muộn, khóa deploy, bảo toàn file local, lỗi build/health/worker và rollback về cả phiên bản trước khi có CD. Trên macOS, chạy trong Linux container; test sẽ skip khi thiếu `flock`.

Kiểm tra thư viện/queue độc lập với cloud: từ `backend/`, chạy `python scripts/verify_document_queue.py`. Script build image (hoặc dùng `--api-image`), tạo Redis và hai Linux RQ workers thật; PDF/AI/Storage/Milvus được giả lập. Kiểm tra transaction, owner scope, outage/restart, timeout/retry, kill và xóa. Script đẩy thời điểm maintenance RQ sau khi kill container để rút ngắn thời gian chờ; tự dọn tài nguyên test.

## 8. CI/CD: GitHub Actions → VPS, Vercel Git Integration

`.github/workflows/verify.yml` chạy ba job `backend`, `frontend`, `deployment` cho push/PR. Chỉ push vào `main` (hoặc **Actions → Verify and deploy → Run workflow** chọn `main`) mới chạy job `deploy`, sau khi cả ba job thành công. PR và các nhánh khác chỉ chạy CI.

### Chuẩn bị VPS một lần

CD dùng checkout hiện có tại `/opt/DocTrace`, với HTTPS đã được bootstrap và API/worker đang dùng cùng image. Checkout phải tương ứng phiên bản đang chạy, không có sửa đổi tracked chưa lưu. Trên Ubuntu 24.04, bên cạnh Docker Engine/Compose v2 cần:

```sh
apt-get update
apt-get install -y git curl python3 util-linux
```

User SSH cần quyền ghi repository, đọc `.env.production`/`backend/.env` và chạy Docker. Có thể dùng user `root` đang vận hành VPS. Script dùng tên project Compose được resolve từ cấu hình hiện tại; nếu trước đây dùng `-p`, ghi đúng tên đó vào `COMPOSE_PROJECT_NAME` trong `.env.production` để cả CD và timer certificate dùng chung volumes.

Script lấy commit qua `git fetch origin main` trên VPS. Với repository public, origin HTTPS hiện tại dùng được. Nếu repository private, thêm **read-only GitHub deploy key** riêng trên VPS, đăng ký public key ở Repository → Settings → Deploy keys rồi đổi origin sang `git@github.com:OWNER/REPO.git`. Kiểm tra `GIT_TERMINAL_PROMPT=0 git ls-remote origin refs/heads/main` chạy được bằng user deploy mà không hỏi mật khẩu. Key VPS → GitHub này khác key Actions → VPS bên dưới.

### Tạo SSH key cho GitHub Actions

Trên Mac, tạo key riêng, không có passphrase để runner dùng không tương tác:

```sh
ssh-keygen -t ed25519 -C doctrace-github-actions -f ~/.ssh/doctrace_actions -N ''
```

Thêm public key vào VPS (thay `VPS_IP` bằng IP thật; lệnh có thể hỏi mật khẩu SSH):

```sh
cat ~/.ssh/doctrace_actions.pub | ssh root@VPS_IP 'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys'
```

Lấy host key đã xác nhận của VPS qua phiên SSH đang tin cậy:

```sh
ssh root@VPS_IP 'cat /etc/ssh/ssh_host_ed25519_key.pub'
```

Kết quả là `ssh-ed25519 AAAA... comment`. Giá trị `VPS_KNOWN_HOSTS` cần một dòng dạng **`VPS_IP ssh-ed25519 AAAA...`** (thêm IP ở đầu; comment cuối không bắt buộc). CI bật strict host-key checking, không tự tin cậy key lấy qua `ssh-keyscan` trong mỗi lần deploy.

Nếu VPS không có file Ed25519 nhưng đang dùng host key RSA, lấy `/etc/ssh/ssh_host_rsa_key.pub` thay thế và dùng dòng **`VPS_IP ssh-rsa AAAA...`**. Host key RSA của VPS vẫn dùng được với key đăng nhập Ed25519 của Actions; đây là hai bộ key độc lập.

Trong **GitHub → Repository → Settings → Secrets and variables → Actions → Repository secrets**, thêm:

| Secret | Giá trị |
|---|---|
| `VPS_HOST` | IP hoặc hostname VPS, không có `https://`; SSH port 22 |
| `VPS_USER` | User SSH, ví dụ `root` |
| `VPS_SSH_KEY` | Toàn bộ nội dung `~/.ssh/doctrace_actions`, gồm BEGIN/END OPENSSH PRIVATE KEY |
| `VPS_KNOWN_HOSTS` | Dòng host key đã xác nhận theo định dạng trên |

Tạo secrets trước khi push cấu hình CD lên `main`. Nếu thiếu, job deploy báo tên secret cần thêm; các job CI vẫn chạy bình thường. Supabase/S3/OpenRouter/Zilliz credentials tiếp tục nằm ở `backend/.env` trên VPS; không cần đưa chúng vào Actions.

### Mỗi lượt deploy

1. Runner gửi script từ đúng checkout đã kiểm tra qua SSH; VPS fetch và checkout **chính xác `github.sha`**, không tự deploy HEAD mới nhất của `main`.
2. Build image `doctrace-api:sha-<SHA>` trên VPS. Nếu tag đã tồn tại, dùng lại image đó. Build xong mới đổi `API_IMAGE` trong `.env.production`, để lệnh Compose và certificate timer dùng đúng release.
3. Cập nhật API/worker với `--no-build --wait`, giữ thời gian dừng worker **16 phút**; recreate Nginx để render lại mounted templates. Đây là cập nhật tại chỗ, có thể có gián đoạn ngắn.
4. Kiểm tra Nginx config, worker của **chính container hiện tại** đăng ký heartbeat/queue trong Redis, rồi gọi HTTPS `/ready` qua domain cấu hình.
5. Ghi release thành công và release trước vào `.git/doctrace-deploy/`. Image đang chạy trước lần CD đầu được giữ dưới tag `doctrace-api:retained-<image-id>`.

GitHub concurrency và host `flock` ngăn deploy chồng nhau. Một run CI cũ đến sau release mới hơn sẽ được bỏ qua bằng kiểm tra Git ancestry. Job có timeout 45 phút để chừa thời gian build và graceful shutdown. Script không dọn image/volume khi deploy. Theo dõi `docker system df` trên VPS 40 GB; khi dọn image cũ, giữ các tag trong `.git/doctrace-deploy/current` và `previous` để rollback.

### Khi deploy thất bại / rollback

Job in trạng thái và log cuối của containers. Nếu lỗi sau khi bắt đầu thay checkout, file `pending` đánh dấu lượt chưa hoàn tất; lần deploy sau yêu cầu phục hồi trước. Trên VPS:

```sh
cd /opt/DocTrace
bash .git/doctrace-deploy/recover.sh rollback
```

Lệnh này dùng script đã lưu ngoài checkout, nên hoạt động cả khi release cũ chưa có `deploy/deploy.sh`. Nếu đang có `pending`, nó khôi phục release thành công gần nhất; nếu deployment đã hoàn tất, nó quay về release `previous`. Rollback dùng lại image đã giữ, checkout code/Compose/templates tương ứng và chạy lại health checks. Khi còn script trong checkout, `bash deploy/deploy.sh rollback` cũng tương đương.

Sau phục hồi, sửa lỗi rồi push commit mới, hoặc chạy lại workflow nếu chỉ sửa env trên VPS. Nếu cần deploy thủ công một commit đã qua CI:

```sh
bash .git/doctrace-deploy/recover.sh deploy FULL_40_CHARACTER_COMMIT_SHA
```

Rollback không đảo dữ liệu Redis, PDF, vector hay nội dung `backend/.env`; giữ thay đổi schema/queue tương thích giữa hai phiên bản. Không xóa `.git/doctrace-deploy/` hoặc prune image đang được release state tham chiếu. Cả health check CD cũng chưa thay thế kiểm tra upload → ready → chat với dịch vụ cloud thật.

### Vercel và quy tắc merge

Vercel project liên kết repository này, Root Directory `frontend`, Production Branch **`main`**. Giữ các biến public trong Vercel Production như mục 2; frontend không cần SSH key hay Vercel token trong GitHub Actions.

Vercel Git Integration bắt đầu deployment khi có push, **không chờ job `deploy` hoặc CI trên push**. Trong GitHub Settings → Rules → Rulesets (hoặc Branch protection), đặt `main` yêu cầu Pull Request và ba status checks `backend`, `frontend`, `deployment` trước merge, cùng nhánh đã cập nhật với `main`. Không chọn job `deploy` làm required check cho PR vì job đó chỉ chạy trên `main`.

Luồng thường ngày: tạo nhánh → push → PR → CI xanh → merge → backend CD và Vercel production deploy. Frontend/backend có thể lên phiên bản mới ở thời điểm khác nhau, nên giữ API tương thích trong khoảng cập nhật.
