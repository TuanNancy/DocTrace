"use client";

import { useState } from "react";
import { Check, CloudUpload, LoaderCircle } from "lucide-react";
import type { UploadSession } from "@/lib/use-upload";

export function UploadZone({ compact = false, session: upload }: {
  compact?: boolean;
  session: UploadSession;
}) {
  const [dragging, setDragging] = useState(false);
  const busy = upload.status === "uploading";
  return <div className={`upload-zone ${dragging ? "upload-zone-dragging" : ""}`}>
    <div onDragOver={(event) => { event.preventDefault(); if (!busy) setDragging(true); }}
      onDragLeave={(event) => { event.preventDefault(); setDragging(false); }}
      onDrop={(event) => { event.preventDefault(); setDragging(false); const file = event.dataTransfer.files[0]; if (file && !busy) void upload.upload(file); }}
      className={`flex flex-col items-center justify-center text-center ${compact ? "px-4 py-6" : "px-6 py-8"}`}>
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl border border-blue-100 bg-white/80 text-blue-500">
        {busy ? <LoaderCircle className="animate-spin" size={20} /> : upload.status === "success" ? <Check size={20} /> : <CloudUpload size={22} strokeWidth={1.6} />}
      </div>
      <p className="text-sm font-medium text-slate-700">{dragging ? "Thả PDF vào đây" : busy ? (upload.progress === 100 ? "Đang lưu PDF…" : `Đang tải lên ${upload.progress}%`) : upload.status === "success" ? "Tải lên thành công" : "Thêm tài liệu của bạn"}</p>
      <p className="mt-1.5 max-w-full truncate text-xs text-slate-400">{busy ? upload.filename : "Kéo thả PDF hoặc chọn tệp để tải lên"}</p>
      {busy && <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-blue-100" role="progressbar" aria-label="Tiến trình tải PDF" aria-valuenow={upload.progress} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-blue-500 transition-[width]" style={{ width: `${upload.progress}%` }} /></div>}
      {upload.error && <p role="alert" className="mt-3 text-xs leading-5 text-red-600">{upload.error}</p>}
      <label className={`secondary-button mt-4 cursor-pointer text-xs ${busy ? "pointer-events-none opacity-50" : ""}`}>
        {upload.status === "success" ? "Chọn file khác" : upload.status === "error" ? "Thử lại" : "Chọn file"}
        <input type="file" accept="application/pdf,.pdf" className="sr-only" disabled={busy} onChange={(event) => {
          const file = event.target.files?.[0]; event.target.value = ""; if (file) void upload.upload(file);
        }} />
      </label>
    </div>
  </div>;
}
