"use client";

import type { ChatSource } from "@/types";

interface SourceCardProps {
  source: ChatSource;
}

export function SourceCard({ source }: SourceCardProps) {
  return (
    <div
      className="rounded-lg border border-slate-200 bg-white shadow-sm transition-shadow hover:shadow dark:border-slate-600 dark:bg-slate-800"
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
      </div>
    </div>
  );
}
