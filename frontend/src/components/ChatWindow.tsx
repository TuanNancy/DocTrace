"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { streamChatSSEParser } from "@/lib/api";
import type { ChatMessage, ChatSource } from "@/types";
import { SourceCardList } from "./SourceCardList";
import { StreamingCursor } from "./StreamingCursor";

export type ChatWindowHandle = {
  clear: () => void;
  exportTranscript: () => void;
};

interface ChatWindowProps {
  docId: string | null;
  /** When true, simulate SSE stream (no backend). */
  mock?: boolean;
  accessToken?: string | null;
}

function genId() {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export const ChatWindow = forwardRef<ChatWindowHandle, ChatWindowProps>(
  function ChatWindow(
    { docId, mock = true, accessToken },
    ref
  ) {
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const scrollRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }, [messages]);

    useImperativeHandle(
      ref,
      () => ({
        clear: () => {
          setMessages([]);
          setError(null);
        },
        exportTranscript: () => {
          const lines: string[] = ["=== LỊCH SỬ CHAT ===", ""];
          messages.forEach((m) => {
            const who = m.role === "user" ? "Bạn" : "AI";
            lines.push(`[${who}]`, m.content, "");
          });
          const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `chat-${new Date().toISOString().split("T")[0]}.txt`;
          a.click();
          URL.revokeObjectURL(url);
        },
      }),
      [messages]
    );

    const appendToken = useCallback((messageId: string, token: string) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, content: m.content + token } : m))
      );
    }, []);

    const setSourcesForMessage = useCallback((messageId: string, sources: ChatSource[]) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, sources } : m))
      );
    }, []);

    const finishStreaming = useCallback((messageId: string) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, isStreaming: false } : m))
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

    const userBubble =
      "bg-[#B22222] text-white dark:bg-[#B22222] dark:text-white";
    const sendBtn =
      "bg-[#B22222] hover:bg-[#9a1d1d] dark:bg-[#B22222] dark:hover:bg-[#9a1d1d]";

    const shellInputWrap =
      "border-slate-200 bg-[#f7f7f4] focus-within:border-[#B22222]/50 focus-within:ring-2 focus-within:ring-[#B22222]/15";

    return (
      <div className="flex h-full min-h-0 flex-col bg-white">
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6">
          {isEmpty && (
            <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-2 text-center text-slate-500 dark:text-slate-400">
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
                    className={`max-w-[85%] rounded-2xl px-4 py-2 shadow-sm ${
                      m.role === "user"
                        ? userBubble
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

        <form
          onSubmit={handleSubmit}
          className="shrink-0 border-t border-slate-200 bg-white p-4 dark:border-slate-700 md:px-6"
        >
          <div className={`flex gap-3 rounded-2xl border p-3 ${shellInputWrap}`}>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (!loading && input.trim()) {
                    e.currentTarget.form?.requestSubmit();
                  }
                }
              }}
              placeholder="Nhập tin nhắn của bạn..."
              rows={1}
              className="max-h-36 min-h-[44px] flex-1 resize-none border-0 bg-transparent px-2 py-2 text-slate-900 placeholder-slate-400 focus:outline-none dark:text-slate-100"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-white disabled:opacity-40 ${sendBtn}`}
              aria-label="Gửi"
            >
              {loading ? "…" : "➤"}
            </button>
          </div>
        </form>
      </div>
    );
  }
);

ChatWindow.displayName = "ChatWindow";
