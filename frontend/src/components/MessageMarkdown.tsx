"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatSource } from "@/types";

type MarkdownNode = { type: string; value?: string; url?: string; children?: MarkdownNode[] };

// Transform text nodes only: code blocks, inline code and existing links stay intact.
function remarkCitations() {
  return (tree: MarkdownNode) => {
    function walk(node: MarkdownNode) {
      if (!node.children || node.type === "link" || node.type === "linkReference") return;
      node.children = node.children.flatMap((child) => {
        if (child.type !== "text" || !child.value) { walk(child); return [child]; }
        const parts: MarkdownNode[] = [];
        let cursor = 0;
        for (const match of child.value.matchAll(/\[(\d+)\]/g)) {
          if (match.index! > cursor) parts.push({ type: "text", value: child.value.slice(cursor, match.index) });
          parts.push({ type: "link", url: `#citation-${match[1]}`, children: [{ type: "text", value: match[0] }] });
          cursor = match.index! + match[0].length;
        }
        if (!parts.length) return [child];
        if (cursor < child.value.length) parts.push({ type: "text", value: child.value.slice(cursor) });
        return parts;
      });
    }
    walk(tree);
  };
}

export function MessageMarkdown({ content, sources = [], onSelectSource }: {
  content: string; sources?: ChatSource[]; onSelectSource?: (source: ChatSource) => void;
}) {
  return <div className="message-markdown"><ReactMarkdown remarkPlugins={[remarkGfm, remarkCitations]} skipHtml components={{
    a: ({ href, children }) => {
      const match = href?.match(/^#citation-(\d+)$/);
      if (match) {
        const source = sources.find((item) => item.citation_id === Number(match[1]));
        return source && onSelectSource
          ? <button type="button" className="citation-link" onClick={() => onSelectSource(source)} aria-label={`Xem nguồn ${match[1]}, trang ${source.page}`}>{children}</button>
          : <span>{children}</span>;
      }
      return <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>;
    },
    table: ({ children }) => <div className="overflow-x-auto"><table>{children}</table></div>,
  }}>{content}</ReactMarkdown></div>;
}
