# Deploy FastAPI với Nginx + Certbot trên EC2

```text
Browser / frontend trên Vercel
          │ HTTPS
          ▼
EC2: Nginx container ──→ api:8000 (FastAPI container)
          │                   └── dịch vụ auth/storage/vector/LLM
          └── certificate volume ← Certbot (chạy khi cấp/gia hạn)
```

## Trạng thái checkout

Bộ deploy này đóng gói API và reverse proxy. Frontend đã có shared modules, build checks và browser test với fixtures; cấu hình Vercel theo `frontend/.env.example` và `frontend/README.md`. Backend hiện dùng Milvus host/port, chưa đọc `MILVUS_URI`/`MILVUS_TOKEN`; các biến mới đó trong `backend/.env.example` chưa có tác dụng với code hiện tại. Cần bổ sung adapter tương ứng trước khi chạy end-to-end trên Vercel + Zilliz.

`GET /health` là liveness của process, không gọi Supabase, Milvus hay OpenRouter. Container healthy không có nghĩa các dịch vụ ngoài đã được cấu hình đúng.

## 1. Hiểu các image và service

| Service | Nguồn image | Vai trò |
|---|---|---|
| `api` | Build từ `backend/Dockerfile` + context `backend/` | Python, dependency và code FastAPI |
| `nginx` | Image `nginx:1.28-alpine` có sẵn | TLS, reverse proxy, upload/SSE |
| `certbot` | Image `certbot/certbot:v5.1.0` có sẵn | Cấp/gia hạn certificate qua HTTP-01 |

`docker build` tạo image; `docker compose up` tạo/chạy container từ image. Compose thiết lập network, env, mount và healthcheck. API image không chứa database server hay frontend. Frontend được build/deploy riêng trên Vercel với Root Directory là `frontend`.

Root `docker-compose.yml` chạy **Milvus local + etcd + MinIO + Attu**. File `compose.production.yml` chạy **API + Nginx**; Certbot ở profile `tools` và chỉ chạy khi gọi rõ service. Đừng nhầm hai file.

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

`backend/.env` được inject lúc chạy; không copy vào image. `.env.production` chứa domain/cấu hình Compose và được Git ignore. Các giá trị `NEXT_PUBLIC_*` của frontend được cấu hình trên Vercel; API URL phải dùng HTTPS.

## 3. Lần đầu: bootstrap HTTP → cấp certificate → bật HTTPS

### Bước A — Khởi động HTTP cho ACME

```sh
sh deploy/certificates.sh bootstrap
```

Lệnh này build API, chạy API + Nginx và chờ healthcheck. Nó tạm đặt `TLS_MODE=http` cho lần chạy đó; file `.env.production` vẫn là `https`.

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
docker compose --env-file .env.production -f compose.production.yml up -d --build --wait api nginx
docker compose --env-file .env.production -f compose.production.yml ps
docker compose --env-file .env.production -f compose.production.yml logs --tail=100 api nginx
docker compose --env-file .env.production -f compose.production.yml exec nginx nginx -t
```

Sửa file template trên host không tự render lại config. Sau khi sửa, chạy:

```sh
docker compose --env-file .env.production -f compose.production.yml up -d --force-recreate --wait nginx
```

Certificate renewal chỉ đổi file PEM, nên graceful reload là đủ. Giữ nguyên tên project Compose giữa các lệnh và timer để dùng đúng volumes. `down` giữ named volumes; **`down -v` xóa certificate/account state**. Không dùng bootstrap cho một deployment đã chạy HTTPS.

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
