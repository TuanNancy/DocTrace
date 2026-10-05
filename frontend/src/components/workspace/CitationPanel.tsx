"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight, FileText, Quote } from "lucide-react";
import { getSourceExcerpt, openDocumentFile } from "@/lib/api";
import type { SourceExcerpt } from "@/types";
import { useWorkspace } from "./WorkspaceProvider";

export function CitationPanel() {
  const { source, setSource, accessToken, mock } = useWorkspace();
  const [excerpt, setExcerpt] = useState<SourceExcerpt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  useEffect(() => {
    setExcerpt(null); setError(null); setFileError(null);
    if (!source) return;
    if (mock) {
      setExcerpt({ doc_id: source.doc_id, chunk_id: source.chunk_id, source: source.source, page: source.page,
        text: "Đây là đoạn trích minh họa. Khi kết nối API, Baymax hiển thị nguyên văn đoạn PDF đã được dùng làm nguồn cho câu trả lời." });
      return;
    }
    if (!accessToken) { setError("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."); return; }
    const controller = new AbortController();
    void getSourceExcerpt(source, accessToken, controller.signal).then((result) => {
      if (!controller.signal.aborted) setExcerpt(result);
    }).catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Không thể tải đoạn trích."); });
    return () => controller.abort();
  }, [source, accessToken, mock]);
  if (!source) return null;
  return <div className="flex flex-1 flex-col p-5">
    <button className="mb-6 flex items-center gap-2 text-xs text-slate-500 hover:text-blue-600" onClick={() => setSource(null)}><ArrowLeft size={14} /> Thư viện tài liệu</button>
    <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.17em] text-blue-500">Kiểm chứng câu trả lời</p>
    <h2 className="font-sans text-xl font-semibold">Trích dẫn nguồn</h2>
    <div className="mb-6 mt-5 flex items-start gap-3 rounded-2xl border border-slate-100 bg-white/80 p-3">
      <div className="rounded-xl bg-blue-50 p-2.5 text-blue-500"><FileText size={20} strokeWidth={1.5} /></div>
      <div className="min-w-0"><p className="break-words text-xs font-medium leading-5">{source.source}</p>
        <span className="mt-1 inline-block text-[10px] text-slate-400">Nguồn [{source.citation_id}] · Trang {source.page}</span></div>
    </div>
    <div className="relative rounded-2xl border border-blue-100/70 bg-blue-50/45 p-4">
      <Quote size={18} className="mb-3 text-blue-300" />
      {error ? <p role="alert" className="text-xs leading-5 text-red-600">{error}</p>
        : excerpt ? <blockquote className="whitespace-pre-wrap break-words text-[13px] leading-7 text-slate-600">{excerpt.text}</blockquote>
          : <p className="animate-pulse text-xs text-slate-400" role="status">Đang tải đoạn trích gốc…</p>}
    </div>
    <p className="mt-3 text-[10px] leading-5 text-slate-400">{mock ? "Nội dung minh họa trong chế độ demo." : "Đoạn văn được trích từ PDF gốc. Số trang tính từ trang đầu của tệp."}</p>
    {!mock && <button className="secondary-button mt-5 w-full text-xs" disabled={opening || !excerpt} onClick={async () => {
      setOpening(true); setFileError(null);
      try { await openDocumentFile(source.doc_id, accessToken!, source.page); }
      catch (cause) { setFileError(cause instanceof Error ? cause.message : "Không thể mở PDF."); }
      finally { setOpening(false); }
    }}>{opening ? "Đang mở…" : `Mở PDF · trang ${source.page}`}<ArrowUpRight size={14} /></button>}
    {fileError && <p role="alert" className="mt-2 text-xs text-red-600">{fileError}</p>}
  </div>;
}
