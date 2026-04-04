"use client";

import { SourceCard } from "./SourceCard";
import type { ChatSource } from "@/types";

interface SourceCardListProps {
  sources: ChatSource[];
}

export function SourceCardList({ sources }: SourceCardListProps) {
  return (
    <div className="mt-2 space-y-2">
      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
        Nguồn trích dẫn
      </p>
      <div className="flex flex-col gap-2">
        {sources.map((s, i) => (
          <SourceCard
            key={`${s.page}-${s.source}-${i}`}
            source={s}
          />
        ))}
      </div>
    </div>
  );
}
