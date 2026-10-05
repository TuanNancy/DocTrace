"use client";

import { useState } from "react";
import type { ChatSource } from "@/types";
import { SourceCard } from "./SourceCard";

export function SourceCardList({ sources, onSelectSource }: { sources: ChatSource[]; onSelectSource?: (source: ChatSource) => void }) {
  const [expanded, setExpanded] = useState(false);
  return <div className="mt-4">
    <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-slate-400">Nguồn tham khảo</p>
    <div className="flex flex-wrap gap-2">{(expanded ? sources : sources.slice(0, 3)).map((source) =>
      <SourceCard key={source.chunk_id} source={source} onSelect={onSelectSource} />)}
      {sources.length > 3 && <button className="suggestion-chip text-[11px]" onClick={() => setExpanded(!expanded)}>{expanded ? "Thu gọn" : `+${sources.length - 3} nguồn`}</button>}
    </div>
  </div>;
}
