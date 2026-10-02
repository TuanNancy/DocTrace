"use client";

import { FileText } from "lucide-react";
import type { ChatSource } from "@/types";

export function SourceCard({ source, onSelect }: { source: ChatSource; onSelect?: (source: ChatSource) => void }) {
  return <button type="button" className="source-card" onClick={() => onSelect?.(source)} disabled={!onSelect}
    title={`${source.source} · Trang ${source.page}`}>
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-xs font-semibold text-blue-500">{source.citation_id ?? <FileText size={14} />}</span>
    <span className="min-w-0 text-left"><span className="block max-w-[150px] truncate text-[11px] font-medium text-slate-700">{source.source}</span>
      <span className="block text-[10px] text-slate-400">Trang {source.page}{source.score === null ? " · Nội dung tài liệu" : ""}</span></span>
  </button>;
}
