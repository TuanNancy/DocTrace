# RAG PDF Chatbot — Frontend

Next.js 15 (App Router) + Tailwind CSS. **Chưa kết nối backend** — chạy ở chế độ mock.

## Chạy

```bash
cd frontend
npm install
npm run dev
```

Mở [http://localhost:3000](http://localhost:3000).

## Tính năng

- **UploadZone**: Kéo thả / chọn file PDF, progress khi index, hiển thị filename + số chunks, xử lý lỗi.
- **ChatWindow**: Input câu hỏi, stream câu trả lời (mock), con trỏ nhấp nháy khi đang nhận token, parser SSE trong `src/lib/api.ts` (split `\n\n`, parse JSON).
- **SourceCard**: Trích dẫn dạng thẻ thu gọn/mở rộng, badge trang, điểm liên quan, preview text.
- **Layout**: Responsive, dark mode (Tailwind `dark:`), scroll lịch sử chat, auto-scroll xuống, empty/loading/error.

## Kết nối backend sau

1. Tạo `.env.local` với `NEXT_PUBLIC_API_URL=http://localhost:8000` (hoặc URL backend).
2. Trong `page.tsx` / `UploadZone`: bỏ `mock` hoặc gọi `uploadPDF(file)` từ `@/lib/api` khi có `NEXT_PUBLIC_API_URL`.
3. Trong `ChatWindow`: bỏ `mock` để dùng `streamChat()` + `streamChatSSEParser(res.body)`.
