"use client";

import { useState } from "react";
import type { ChatSource } from "@/types";

interface SourceCardProps {
  source: ChatSource;
  /** Optional full text for expanded view (preview when collapsed) */
  previewText?: string;
}

const PREVIEW_LEN = 120;

export function SourceCard({ source, previewText }: SourceCardProps) {
  const [expanded, setExpanded] = useState(false);
  const text = previewText ?? "";
  const showPreview = text.slice(0, PREVIEW_LEN) + (text.length > PREVIEW_LEN ? "…" : "");

  return (
    <div
      className="rounded-lg border border-slate-200 bg-white shadow-sm transition-shadow hover:shadow dark:border-slate-600 dark:bg-slate-800"
      role="button"
      tabIndex={0}
      onClick={() => setExpanded((e) => !e)}
      onKeyDown={(e) => e.key === "Enter" && setExpanded((x) => !x)}
    >
      <div className="flex flex-wrap items-center gap-2 p-3">
        <span className="rounded bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-600 dark:text-slate-200">
          Trang {source.page}
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          Độ liên quan: {(source.score * 100).toFixed(1)}%
        </span>
        {source.source && (
          <span className="truncate text-xs text-slate-500 dark:text-slate-400" title={source.source}>
            {source.source}
          </span>
        )}
        <span className="ml-auto text-xs text-slate-400 dark:text-slate-500">
          {expanded ? "Thu gọn ▲" : "Mở rộng ▼"}
        </span>
      </div>
      {(showPreview || expanded) && (
        <div className="border-t border-slate-100 px-3 py-2 dark:border-slate-700">
          <p className="whitespace-pre-wrap text-sm text-slate-600 dark:text-slate-300">
            {expanded ? text : showPreview}
          </p>
        </div>
      )}
    </div>
  );
}
