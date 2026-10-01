# DocTrace — Frontend

Next.js 14.2.21 (App Router) + Tailwind CSS. Trang chat chọn chế độ demo khi `NEXT_PUBLIC_API_URL` chưa được đặt.

Các module `src/lib/` cung cấp API client, SSE parser và Supabase browser/server/middleware clients. Thư mục này được Git track nhờ ngoại lệ trong root `.gitignore`.

## Chạy

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Mở [http://localhost:3000](http://localhost:3000).

Điền URL và public key Supabase trong `.env.local` trước khi chạy. Trên PowerShell, dùng `Copy-Item .env.example .env.local` để tạo file env.

## Tính năng

- **UploadZone**: Kéo thả / chọn file PDF, chọn file khác hoặc thử lại, khóa upload đồng thời và hủy request khi unmount. Progress khi gọi API là trạng thái chờ, không phải phần trăm byte thực tế.
- **ChatWindow**: Gửi câu hỏi, nhận sự kiện SSE, dùng `appendTextDelta()` để nối nội dung. `parseChatEvents` là tên local của import `streamChatSSEParser`. Parser xử lý UTF-8 bị chia giữa các network chunks và báo lỗi nếu stream kết thúc thiếu `done`.
- **SourceCard**: Hiển thị trang, nguồn và điểm liên quan của đoạn được truy xuất.
- **clearMessages()**: Hủy stream, xóa tin nhắn/draft/lỗi và mở lại ô nhập; tài liệu đang chọn vẫn giữ nguyên. Đổi PDF tự xóa chat cũ và hủy request cũ. Lịch sử chưa được lưu trên server.
- **Layout**: Responsive, dark mode (Tailwind `dark:`), scroll lịch sử chat, auto-scroll xuống, empty/loading/error.

## Cấu hình

| Biến | Ý nghĩa |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | URL project Supabase |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY` | Publishable key; hỗ trợ `NEXT_PUBLIC_SUPABASE_ANON_KEY` cho project cũ |
| `NEXT_PUBLIC_SITE_URL` | Origin frontend, ví dụ `http://localhost:3000` hoặc URL Vercel |
| `NEXT_PUBLIC_API_URL` | Origin backend, ví dụ `http://localhost:8000`; production dùng HTTPS, không thêm `/api` |

Không đặt service-role key, OpenRouter key hay S3 secret trong `NEXT_PUBLIC_*`. Các biến public được đóng vào bundle lúc build: đổi trên Vercel thì cần redeploy.

- Để API URL trống sẽ mô phỏng upload/chat; đăng nhập vẫn cần Supabase.
- Backend phải cho phép origin frontend trong `CORS_ALLOW_ORIGINS`. Upload/chat gửi Bearer token.
- Supabase Auth: đặt Site URL và allowlist `/auth/callback` cho Google OAuth, `/auth/login` cho luồng xác nhận email hiện tại. Bật Google provider nếu dùng Google login.
- Đăng nhập mật khẩu được chuyển hướng từ server action sau khi ghi session cookies. Middleware xác thực bằng `getUser()` và đồng bộ cookie refresh.

## Kiểm chứng

```sh
npm run typecheck
npm run lint
npm test
npx playwright install chromium
npm run test:e2e
npm run build
```

Vitest kiểm tra multipart/Bearer, SSE, cookie refresh, upload lại, chống upload đồng thời, đổi tài liệu và hủy stream. Playwright chạy Chromium qua UI đăng nhập → upload → SSE → xóa khi đang stream → đổi PDF → dark mode → đăng xuất.

E2E tự khởi động Next dev ở `localhost:4310` và Auth/API fixtures ở `127.0.0.1:4311`, sau đó dừng chúng; giữ hai cổng này trống. Không dùng credential thật và không gọi Supabase/OpenRouter/Milvus thật. Vì vậy vẫn cần kiểm thử Google OAuth/email và luồng RAG với project cloud thực khi deploy. Build cần biến Supabase hợp lệ về định dạng; CI dùng placeholder công khai, không dùng secrets.
