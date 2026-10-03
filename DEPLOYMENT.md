# Deploy FastAPI + Redis/RQ với Nginx + Certbot trên EC2

```text
Browser / frontend trên Vercel
          │ HTTPS
          ▼
EC2: Nginx container ──→ api:8000 (FastAPI container)
          │                   └── dịch vụ auth/storage/vector/LLM
          └── certificate volume ← Certbot (chạy khi cấp/gia hạn)

Postgres outbox → dispatcher → Redis → RQ worker → Storage/Milvus/Postgres
```

## Trạng thái checkout

Bộ deploy đóng gói API, worker xử lý PDF và reverse proxy. Frontend cấu hình trên Vercel theo `frontend/.env.example` và `frontend/README.md`. Milvus hỗ trợ host/port hoặc `MILVUS_URI`/`MILVUS_TOKEN`; URI mode mặc định AUTOINDEX.

Với database mới, áp dụng migrations `001_document_library.sql` rồi `002_rq_document_jobs.sql` trong Supabase SQL Editor. Tạo bucket PDF private và cấu hình `SUPABASE_SERVICE_ROLE_KEY` cùng các S3 keys trong `backend/.env`. Đây là migrations chạy một lần. Database đã chạy worker cũ cần quy trình chuyển đổi bên dưới. PDF chưa có metadata thư viện cần tải lại.

`GET /health` là liveness của API process, không kiểm tra worker, Supabase, Milvus hay OpenRouter. Theo dõi log worker và trạng thái tài liệu để kiểm tra xử lý nền.

## 1. Hiểu các image và service

| Service | Nguồn image | Vai trò |
|---|---|---|
| `api` | Build từ `backend/Dockerfile` + context `backend/` | Python, dependency và code FastAPI |
| `worker` | Cùng image API; `python -m app.worker` | RQ + scheduler: indexing, xóa, cleanup, timeout/retry |
| `dispatcher` | Cùng image API; `python -m app.dispatcher` | Giao outbox, đối soát RQ, lên lịch cleanup/stale uploads |
| `redis` | `redis:7.4.8-alpine` | Queue/RQ metadata; AOF `everysec`, volume `redis_data`, `noeviction` |
| `nginx` | Image `nginx:1.28-alpine` có sẵn | TLS, reverse proxy, upload/SSE |
| `certbot` | Image `certbot/certbot:v5.1.0` có sẵn | Cấp/gia hạn certificate qua HTTP-01 |

`docker build` tạo image; `docker compose up` tạo/chạy container từ image. Compose thiết lập network, env, mount và healthcheck. API image không chứa database server hay frontend. Frontend được build/deploy riêng trên Vercel với Root Directory là `frontend`.

Root `docker-compose.yml` chạy Redis + cụm Milvus; profile `jobs` thêm worker/dispatcher. Production chạy API + Redis + dispatcher + worker + Nginx; Certbot ở profile `tools`.

## 2. Chuẩn bị EC2, DNS và env

Các lệnh vận hành bên dưới dùng shell Linux trên EC2. Cài Docker Engine và Compose v2 hỗ trợ `up --wait`.

1. Đặt repository tại `/opt/DocTrace` (hoặc sửa đường dẫn trong systemd service nếu dùng chỗ khác).
2. Trỏ DNS `api.YOUR-DOMAIN` tới địa chỉ public ổn định của EC2.
3. Cho phép inbound TCP **80 và 443**. Port 80 cần giữ mở để HTTP-01 renewal hoạt động.
4. API port 8000 chỉ nằm trong Docker network; không publish ra EC2.

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

Tạo `backend/.env` theo phần cấu hình backend trong README. Điền OpenRouter, Supabase Auth/Storage và Milvus endpoint mà code hiện hỗ trợ. Đặt:

```dotenv
CORS_ALLOW_ORIGINS=https://YOUR-FRONTEND
```

**Networking:** `localhost` trong API container là chính container đó. Nếu Milvus ở cùng Docker network, dùng `MILVUS_HOST=milvus`; nếu Milvus ở máy khác, dùng hostname/IP truy cập được. Trên Docker Desktop, có thể dùng `host.docker.internal` để đi qua cổng của host. Không chạy thêm cả cụm Milvus trên EC2 t3.small theo cấu hình này mà chưa đo tài nguyên.

API và worker có giới hạn riêng `1400m`; dispatcher `192m`, Redis `256m`, Nginx `128m` (tổng khoảng 3.3 GiB chưa tính OS). Redis `maxmemory=128mb` chừa dung lượng cho persistence; khi đầy nó từ chối ghi, dispatcher giữ yêu cầu trong outbox để giao lại. Redis chỉ truy cập qua mạng Docker, không publish port production.

Compose đặt `REDIS_URL=redis://redis:6379/0` cho worker/dispatcher. `DOCUMENT_INDEX_TIMEOUT_SECONDS=900`, `DOCUMENT_DELETE_TIMEOUT_SECONDS=300`; tăng timeout cần điều chỉnh `stop_grace_period` (mặc định 16 phút) tương ứng. RQ graceful shutdown chờ job hiện tại; force kill được phục hồi bằng RQ + deadline database.

`backend/.env` được inject lúc chạy; không copy vào image. `.env.production` chứa domain/cấu hình Compose và được Git ignore. Các giá trị `NEXT_PUBLIC_*` của frontend được cấu hình trên Vercel; API URL phải dùng HTTPS.

## 3. Lần đầu: bootstrap HTTP → cấp certificate → bật HTTPS

### Bước A — Khởi động HTTP cho ACME

```sh
sh deploy/certificates.sh bootstrap
```

Lệnh này build image, chạy API + worker + dispatcher + Redis + Nginx. Redis/API/Nginx có healthcheck; worker/dispatcher được kiểm tra ở mức process running. Nó tạm đặt `TLS_MODE=http` cho lần chạy đó; file `.env.production` vẫn là `https`.

Bootstrap chỉ phục vụ:

- `/.well-known/acme-challenge/*`: Certbot đặt file xác thực tại đây.
- `/nginx-health`: kiểm tra process Nginx.
- Các đường dẫn khác: **503**, vì API chưa được mở qua HTTP.

Kiểm tra DNS/firewall từ bên ngoài EC2:

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

Sau lần cấp certificate đầu tiên:

```sh
docker compose --env-file .env.production -f compose.production.yml up -d --build --wait api worker dispatcher nginx
docker compose --env-file .env.production -f compose.production.yml ps
docker compose --env-file .env.production -f compose.production.yml logs --tail=100 api worker dispatcher redis nginx
docker compose --env-file .env.production -f compose.production.yml exec nginx nginx -t
```

Sửa file template trên host không tự render lại config. Sau khi sửa, chạy:

```sh
docker compose --env-file .env.production -f compose.production.yml up -d --force-recreate --wait nginx
```

Certificate renewal chỉ đổi file PEM, nên graceful reload là đủ. Giữ nguyên tên project Compose giữa các lệnh và timer để dùng đúng volumes. `down` giữ named volumes; **`down -v` xóa certificate/account state**. Không dùng bootstrap cho một deployment đã chạy HTTPS.

`POST /api/upload` trả `202 queued` sau khi giữ PDF và commit yêu cầu vào outbox, kể cả khi Redis đang gián đoạn. Dispatcher giao việc mỗi khoảng 2 giây; RQ thực thi và retry sau 10/30 giây. Mỗi operation có ngân sách bền vững tối đa ba lần thực thi. Recovery job bị kill/mất Redis có thể chờ timeout của lần chạy cũ + 60 giây và chu kỳ maintenance. PostgreSQL kiểm tra operation/delivery/attempt trước khi công bố generation. Cleanup định kỳ bắt các thao tác remote kết thúc muộn.

Quan sát queue mặc định bằng:

```sh
docker compose --env-file .env.production -f compose.production.yml exec worker rq info --url redis://redis:6379/0
```

Theo dõi worker heartbeat, tuổi operation `pending`, log `Dispatcher heartbeat`, các trạng thái `error/delete_error`. Log nối được bằng `doc`, `operation`, `attempt`. `/health` thành công không chứng minh dispatcher/worker đang chạy. `down -v` cũng xóa dữ liệu Redis; AOF `everysec` có cửa sổ mất ghi gần nhất, còn outbox/attempt budget trong PostgreSQL cho phép đối soát.

### Chuyển từ worker PostgreSQL sang RQ

1. Backup database và giữ image backend cũ. Dừng API để tạm ngừng upload/retry/delete; chờ hoặc dừng worker cũ có kiểm soát. Xác nhận không còn process cũ đang ghi vector.
2. Áp dụng **002** (không chạy lại 001). Migration chuyển queued/processing/deleting thành outbox mới, giữ toàn bộ generation cũ và active pointer; xóa RPC worker cũ để mọi publish muộn thất bại. `document_jobs` được giữ làm dữ liệu lịch sử, thu hồi quyền service-role.
3. Build/start Redis, dispatcher, worker và API mới bằng lệnh ở trên. Xác nhận một PDF mới đạt ready, mở nguồn và xóa được trước khi mở lại frontend.
4. Kiểm tra log, outbox còn pending và cleanup. Chỉ bỏ bảng lịch sử bằng một migration sau khi đã xác nhận vận hành; runtime mới không đọc bảng đó.

Rollback trước khi mở lại traffic: dừng toàn bộ binary mới, phục hồi backup/schema cũ cùng image cũ và đối soát các generation đã phát sinh. Sau khi đã nhận dữ liệu mới, ưu tiên sửa tiến thay vì restore backup làm mất metadata; việc đổi image đơn thuần không tương thích schema 002. Không chạy đồng thời worker cũ và mới.

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

Integration test dùng production Compose/templates với project name ngẫu nhiên, ports loopback ngẫu nhiên, auth/RAG giả lập và certificate tự ký. Nó kiểm tra bootstrap, TLS, redirect, forwarding/CORS, upload limit, stream trước khi upstream hoàn tất, cancellation, certificate rotation và API recreation. Containers/volumes test được dọn trong `finally`; không gọi ACME hay dịch vụ AI thật.

CI chạy backend tests, deployment checks và frontend typecheck/lint/Vitest/Chromium/build. Frontend checks dùng cấu hình public giả và Auth/API fixtures local; chưa chứng minh dịch vụ cloud thực đã được kết nối đúng.

Kiểm tra migration/queue/RLS độc lập với cloud: từ `backend/`, chạy `python scripts/verify_document_queue.py`. Script build image (hoặc dùng `--api-image`), tạo PostgreSQL/PostgREST/Redis cùng Linux RQ workers thật; các dịch vụ PDF/AI/Storage/Milvus được giả lập. Tự dọn container, network, volume test.
