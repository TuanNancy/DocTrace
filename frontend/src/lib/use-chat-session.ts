"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat } from "@/lib/api";
import { streamChatSSEParser } from "@/lib/sse";
import type { ChatMessage, ChatSource } from "@/types";

export function useChatSession({ docId, mock = false, accessToken }: {
  docId: string | null; mock?: boolean; accessToken?: string | null;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setLoading(false);
    setMessages((items) => items.map((item) => item.isStreaming ? { ...item, isStreaming: false, interrupted: true } : item));
  }, []);

  const clearMessages = useCallback(() => {
    stop();
    setMessages([]);
    setInput("");
    setError(null);
  }, [stop]);

  useEffect(() => {
    clearMessages();
    return () => { activeRequest.current?.abort(); activeRequest.current = null; };
  }, [docId, clearMessages]);

  const submit = useCallback(async (question?: string) => {
    const query = (question ?? input).trim();
    if (!query || activeRequest.current) return;
    if (!docId && !mock) { setError("Vui lòng chọn một PDF sẵn sàng trong thư viện."); return; }
    if (!mock && !accessToken) { setError("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."); return; }
    const controller = new AbortController();
    activeRequest.current = controller;
    const id = crypto.randomUUID();
    setError(null);
    setInput("");
    setLoading(true);
    setMessages((items) => [...items, { id: crypto.randomUUID(), role: "user", content: query },
      { id, role: "assistant", content: "", isStreaming: true }]);
    const update = (values: Partial<ChatMessage>, delta?: string) => {
      if (activeRequest.current !== controller || controller.signal.aborted) return;
      setMessages((items) => items.map((item) => item.id === id
        ? { ...item, ...values, content: delta === undefined ? item.content : item.content + delta } : item));
    };
    let interrupted = false;
    try {
      if (mock) {
        const sources: ChatSource[] = [{ citation_id: 1, doc_id: docId ?? "demo", chunk_id: "demo-chunk", page: 1, source: "Tài liệu mẫu.pdf", score: null }];
        update({ sources });
        const text = "## Câu trả lời minh họa\n\nDocTrace giúp bạn **tìm hiểu tài liệu** và kiểm tra nguồn ngay trong cuộc trò chuyện. [1]\n\n- Hỏi về các ý chính\n- Đối chiếu đoạn trích gốc\n\n*Đây là nội dung demo, chưa phân tích PDF của bạn.*";
        for (const part of text.match(/.{1,8}|\n/g) ?? []) {
          await new Promise((resolve) => setTimeout(resolve, 25));
          if (controller.signal.aborted) return;
          update({}, part);
        }
      } else {
        const response = await streamChat(query, docId!, accessToken!, controller.signal);
        if (controller.signal.aborted) { await response.body?.cancel(); return; }
        for await (const event of streamChatSSEParser(response.body!)) {
          if (controller.signal.aborted) break;
          if (event.type === "sources") update({ sources: event.data });
          if (event.type === "token") update({}, event.data);
          if (event.type === "error") { setError(event.data.message); interrupted = true; }
        }
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        interrupted = true;
        setError(cause instanceof Error ? cause.message : "Không thể gửi câu hỏi.");
      }
    } finally {
      if (activeRequest.current === controller && !controller.signal.aborted) {
        update({ isStreaming: false, interrupted });
        activeRequest.current = null;
        setLoading(false);
      }
    }
  }, [input, docId, mock, accessToken]);

  const exportTranscript = useCallback(() => {
    const text = messages.map((message) => `${message.role === "user" ? "Bạn" : "DocTrace"}\n${message.content}\n${
      (message.sources ?? []).map((source) => `[${source.citation_id}] ${source.source} — trang ${source.page}`).join("\n")
    }`).join("\n\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `doctrace-${new Date().toISOString().slice(0, 10)}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }, [messages]);

  return { messages, input, setInput, loading, error, submit, stop, clearMessages, exportTranscript };
}

export type ChatSession = ReturnType<typeof useChatSession>;
