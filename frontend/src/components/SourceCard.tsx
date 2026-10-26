"use client";

import type { ChatSource } from "@/types";

export function SourceCard({ source, onSelect }: { source: ChatSource; onSelect?: (source: ChatSource) => void }) {
  const unavailable = !!source.stale;
  const disabled = !onSelect || unavailable;
  return <button type="button" className="source-card" onClick={() => { if (!disabled) onSelect?.(source); }} disabled={disabled}
    aria-disabled={unavailable || undefined}
    title={unavailable ? "Nguồn không còn khả dụng sau khi tài liệu được xử lý lại"
      : `${source.source} · Trang ${source.page}`}>
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-xs font-semibold text-blue-500">{source.citation_id}</span>
    <span className="min-w-0 text-left"><span className="block max-w-[150px] truncate text-[11px] font-medium text-slate-700">{source.source}</span>
      <span className="block text-[10px] text-slate-400">{unavailable ? "Nguồn không còn khả dụng"
        : `Trang ${source.page}${source.score === null ? " · Nội dung tài liệu" : ""}`}</span></span>
  </button>;
}
