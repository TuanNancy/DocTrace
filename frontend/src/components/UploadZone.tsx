"use client";

import { useCallback, useState } from "react";
import { uploadPDF } from "@/lib/api";
import type { UploadResponse } from "@/types";

type Status = "idle" | "dragging" | "uploading" | "success" | "error";

interface UploadZoneProps {
  onUploadComplete?: (res: UploadResponse) => void;
  /** When true, upload is simulated (no backend). For demo. */
  mock?: boolean;
  accessToken?: string | null;
  compact?: boolean;
}

export function UploadZone({
  onUploadComplete,
  mock = true,
  accessToken,
  compact = false,
}: UploadZoneProps) {
  const [status, setStatus] = useState<Status>("idle");
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setStatus("dragging");
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setStatus("idle");
  }, []);

  const simulateUpload = useCallback(
    (file: File) => {
      setStatus("uploading");
      setError(null);
      setResult(null);
      setFilename(file.name);
      setProgress(0);
      const step = 100 / 20;
      let n = 0;
      const t = setInterval(() => {
        n += 1;
        setProgress(Math.min(n * step, 100));
        if (n >= 20) {
          clearInterval(t);
          const res: UploadResponse = {
            doc_id: `mock-${Date.now()}`,
            chunks_count: Math.max(3, Math.floor(Math.random() * 15)),
            message: "Upload and indexing completed (mock).",
          };
          setResult(res);
          setStatus("success");
          onUploadComplete?.(res);
        }
      }, 120);
    },
    [onUploadComplete]
  );

  const uploadToBackend = useCallback(
    async (file: File) => {
      setStatus("uploading");
      setError(null);
      setResult(null);
      setFilename(file.name);
      setProgress(30);

      try {
        if (!accessToken) {
          throw new Error("Thiếu phiên đăng nhập. Vui lòng đăng nhập lại.");
        }
        const res = await uploadPDF(file, accessToken);
        if (!res) {
          throw new Error(
            "Không thể kết nối backend. Hãy kiểm tra `NEXT_PUBLIC_API_URL`."
          );
        }

        setResult(res);
        setProgress(100);
        setStatus("success");
        onUploadComplete?.(res);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed.");
        setStatus("error");
      }
    },
    [accessToken, onUploadComplete]
  );

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setStatus("idle");
      const file = e.dataTransfer.files?.[0];
      if (!file) return;
      if (file.type !== "application/pdf") {
        setError("Chỉ chấp nhận file PDF.");
        setStatus("error");
        return;
      }
      if (mock) {
        simulateUpload(file);
      } else {
        await uploadToBackend(file);
      }
    },
    [mock, simulateUpload, uploadToBackend]
  );

  const handleFileInput = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      if (file.type !== "application/pdf") {
        setError("Chỉ chấp nhận file PDF.");
        setStatus("error");
        return;
      }
      if (mock) {
        simulateUpload(file);
      } else {
        await uploadToBackend(file);
      }
      e.target.value = "";
    },
    [mock, simulateUpload, uploadToBackend]
  );

  const isActive = status === "dragging" || status === "uploading";

  return (
    <div
      className={`h-full rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 transition-colors dark:border-slate-600 dark:bg-slate-800/50 ${
        compact ? "p-3" : "p-6"
      }`}
    >
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`flex h-full flex-col items-center justify-center gap-2 rounded-lg transition-colors ${
          isActive ? "bg-blue-50 dark:bg-blue-950/30" : ""
        }`}
      >
        {status === "idle" && (
          <>
            <p className="text-center text-slate-600 dark:text-slate-400">
              Kéo thả file PDF vào đây hoặc nhấn để chọn
            </p>
            <label className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600">
              Chọn file
              <input
                type="file"
                accept="application/pdf"
                className="sr-only"
                onChange={handleFileInput}
              />
            </label>
          </>
        )}

        {status === "dragging" && (
          <p className="text-blue-600 dark:text-blue-400">Thả file để tải lên</p>
        )}

        {status === "uploading" && (
          <div className="w-full max-w-xs space-y-2">
            <p className="text-center text-sm text-slate-600 dark:text-slate-400">
              Đang index: {filename}
            </p>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
              <div
                className="h-full rounded-full bg-blue-600 transition-all duration-300 dark:bg-blue-500"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-center text-xs text-slate-500">{progress}%</p>
          </div>
        )}

        {status === "success" && result && (
          <div className="w-full space-y-2 text-center">
            <p className="text-sm font-medium text-green-700 dark:text-green-400">
              Tải lên thành công
            </p>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              File: <span className="font-medium">{filename}</span>
            </p>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Số chunks: <span className="font-medium">{result.chunks_count}</span>
            </p>
            {result.message && (
              <p className="text-xs text-slate-500">{result.message}</p>
            )}
            {result.status && !result.message && (
              <p className="text-xs text-slate-500">
                Trạng thái: <span className="font-medium">{result.status}</span>
              </p>
            )}
            {typeof result.processing_time === "number" && (
              <p className="text-xs text-slate-500">
                Thời gian:{" "}
                <span className="font-medium">{result.processing_time}s</span>
              </p>
            )}
            {result.pdf_storage_key && (
              <p className="text-xs text-green-600 dark:text-green-400">
                ✅ Đã lưu PDF lên Storage: <span className="font-medium">{result.pdf_storage_key}</span>
              </p>
            )}
            {result.warnings && result.warnings.length > 0 && (
              <p className="text-xs text-amber-700 dark:text-amber-300">
                Cảnh báo: {result.warnings[0]}
              </p>
            )}
          </div>
        )}

        {status === "error" && (
          <div className="space-y-2 text-center">
            <p className="text-sm font-medium text-red-600 dark:text-red-400">
              Lỗi
            </p>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {error}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
