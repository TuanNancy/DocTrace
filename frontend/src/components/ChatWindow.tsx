"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChatSSEParser } from "@/lib/api";
import type { ChatMessage, ChatSource } from "@/types";
import { SourceCardList } from "./SourceCardList";
import { StreamingCursor } from "./StreamingCursor";

interface ChatWindowProps {
  docId: string | null;
  /** When true, simulate SSE stream (no backend). */
  mock?: boolean;
  accessToken?: string | null;
}

function genId() {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function ChatWindow({ docId, mock = true, accessToken }: ChatWindowProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const appendToken = useCallback((messageId: string, token: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId ? { ...m, content: m.content + token } : m
      )
    );
  }, []);

  const setSourcesForMessage = useCallback((messageId: string, sources: ChatSource[]) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, sources } : m))
    );
  }, []);

  const finishStreaming = useCallback((messageId: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId ? { ...m, isStreaming: false } : m
      )
    );
  }, []);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const q = input.trim();
      if (!q || loading) return;
      if (!docId && !mock) {
        setError("Vui lòng tải lên một tài liệu trước.");
        return;
      }

      setError(null);
      setInput("");
      const userMsg: ChatMessage = {
        id: genId(),
        role: "user",
        content: q,
      };
      setMessages((prev) => [...prev, userMsg]);

      const assistantId = genId();
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        isStreaming: true,
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setLoading(true);

      if (mock) {
        // Simulate SSE: sources -> tokens -> done
        const mockSources: ChatSource[] = [
          { page: 1, source: "document.pdf", score: 0.92 },
          { page: 2, source: "document.pdf", score: 0.85 },
        ];
        setSourcesForMessage(assistantId, mockSources);
        const mockText =
          "Đây là câu trả lời mẫu dựa trên ngữ cảnh tài liệu (chế độ mock). Khi kết nối backend, câu trả lời sẽ được stream từng token.";
        for (let i = 0; i < mockText.length; i++) {
          await new Promise((r) => setTimeout(r, 20));
          appendToken(assistantId, mockText[i]);
        }
        finishStreaming(assistantId);
        setLoading(false);
        return;
      }

      try {
        const { streamChat } = await import("@/lib/api");
        if (!accessToken) {
          setError("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
          finishStreaming(assistantId);
          setLoading(false);
          return;
        }
        const res = await streamChat(q, docId!, accessToken);
        if (!res || !res.body) {
          setError("Không thể kết nối. Kiểm tra backend.");
          finishStreaming(assistantId);
          setLoading(false);
          return;
        }
        for await (const event of streamChatSSEParser(res.body)) {
          if (event.type === "sources") setSourcesForMessage(assistantId, event.data);
          if (event.type === "token") appendToken(assistantId, event.data);
          if (event.type === "error") setError(event.data.message);
          if (event.type === "done") break;
        }
        finishStreaming(assistantId);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Lỗi khi gửi tin nhắn.");
        finishStreaming(assistantId);
      } finally {
        setLoading(false);
      }
    },
    [
      input,
      loading,
      docId,
      mock,
      accessToken,
      appendToken,
      setSourcesForMessage,
      finishStreaming,
    ]
  );

  const isEmpty = messages.length === 0;
  const hasDoc = !!docId || mock;

  return (
    <div className="flex h-full flex-col rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800/50">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4"
      >
        {isEmpty && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-slate-500 dark:text-slate-400">
            {!hasDoc ? (
              <>
                <p>Chưa có tài liệu nào.</p>
                <p className="text-sm">Tải lên PDF ở trên để bắt đầu hỏi đáp.</p>
              </>
            ) : (
              <>
                <p>Chưa có tin nhắn.</p>
                <p className="text-sm">Nhập câu hỏi và nhấn Gửi.</p>
              </>
            )}
          </div>
        )}

        {!isEmpty && (
          <ul className="space-y-4">
            {messages.map((m) => (
              <li
                key={m.id}
                className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-lg px-3 py-2 ${
                    m.role === "user"
                      ? "bg-blue-600 text-white dark:bg-blue-500"
                      : "bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-200"
                  }`}
                >
                  <div className="whitespace-pre-wrap break-words">
                    {m.content}
                    {m.isStreaming && <StreamingCursor />}
                  </div>
                  {m.role === "assistant" && m.sources && m.sources.length > 0 && (
                    <SourceCardList sources={m.sources} />
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {error && (
          <div className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
            {error}
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="border-t border-slate-200 p-3 dark:border-slate-700">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Nhập câu hỏi..."
            className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 placeholder-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:placeholder-slate-500"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50 dark:bg-blue-500 dark:hover:bg-blue-600"
          >
            {loading ? "Đang gửi..." : "Gửi"}
          </button>
        </div>
      </form>
    </div>
  );
}
