# DocTrace — Frontend

Next.js 14.2.21 (App Router) + Tailwind CSS. Trang chat chọn chế độ demo khi `NEXT_PUBLIC_API_URL` chưa được đặt.

**Checkout hiện tại:** thiếu `src/lib/{api,client,server,middleware,utils}.ts`, nên chưa thể build/chạy hoàn chỉnh. Root `.gitignore` có pattern `lib/` bỏ qua cả thư mục source này; cần sửa rule khi khôi phục các module.

## Chạy

```bash
cd frontend
npm ci
npm run dev
```

Mở [http://localhost:3000](http://localhost:3000).

## Tính năng

- **UploadZone**: Kéo thả / chọn file PDF, progress khi index, hiển thị filename + số chunks, xử lý lỗi.
- **ChatWindow**: Gửi câu hỏi, nhận sự kiện SSE, dùng `appendTextDelta()` để nối nội dung. `parseChatEvents` là tên local của import `streamChatSSEParser` từ API client đang thiếu.
- **SourceCard**: Hiển thị trang, nguồn và điểm liên quan của đoạn được truy xuất.
- **clearMessages()**: Xoá tin nhắn hiển thị; tài liệu đang chọn vẫn giữ nguyên. Chưa có thao tác tạo hội thoại được lưu trên server.
- **Layout**: Responsive, dark mode (Tailwind `dark:`), scroll lịch sử chat, auto-scroll xuống, empty/loading/error.

## Cấu hình sau khi khôi phục module còn thiếu

1. Tạo `.env.local` với `NEXT_PUBLIC_API_URL=http://localhost:8000` (hoặc URL backend).
2. `src/app/chat/page.tsx` tự truyền `mock={!backendUrl}` cho upload/chat; nhánh thật gửi access token cùng request.
3. Kiểm tra với `npx tsc --noEmit --incremental false` và `npm run build`.
