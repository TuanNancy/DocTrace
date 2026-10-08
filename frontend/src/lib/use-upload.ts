"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { uploadPDF } from "@/lib/api";
import type { LibraryDocument } from "@/types";

export function useUpload({ accessToken, mock, onUploadComplete }: {
  accessToken?: string | null; mock?: boolean; onUploadComplete?: (result: LibraryDocument) => void;
}) {
  const [status, setStatus] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [filename, setFilename] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    setStatus("idle"); setProgress(0); setError(null); setFilename("");
    return () => { active.current?.abort(); active.current = null; };
  }, [accessToken]);
  const upload = useCallback(async (file: File) => {
    if (active.current) return;
    if (!file.name.toLowerCase().endsWith(".pdf") || (file.type && file.type !== "application/pdf")) {
      setError("Chỉ chấp nhận file PDF."); setStatus("error"); return;
    }
    const controller = new AbortController();
    active.current = controller;
    setStatus("uploading"); setProgress(0); setError(null); setFilename(file.name);
    try {
      let result: LibraryDocument;
      if (mock) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        const now = new Date().toISOString();
        result = {
          doc_id: crypto.randomUUID(), name: file.name, size_bytes: file.size,
          status: "ready", chunks_count: 0, created_at: now, updated_at: now,
          warnings: [], error: null,
        };
      } else {
        result = await uploadPDF(file, accessToken ?? "", controller.signal, (percent) => {
          if (!controller.signal.aborted) setProgress(percent);
        });
      }
      if (controller.signal.aborted) return;
      setProgress(100); setStatus("success");
      onUploadComplete?.(result);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setStatus("error"); setError(cause instanceof Error ? cause.message : "Không thể tải PDF.");
      }
    } finally { if (active.current === controller) active.current = null; }
  }, [accessToken, mock, onUploadComplete]);
  return { status, progress, error, filename, upload };
}

export type UploadSession = ReturnType<typeof useUpload>;
