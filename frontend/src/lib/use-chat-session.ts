"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError, deleteConversation, getConversation, listConversations, streamChat,
} from "@/lib/api";
import { streamChatSSEParser } from "@/lib/sse";
import type { ChatMessage, ChatSource, TranscriptMessage } from "@/types";

function restoredMessage(message: TranscriptMessage): ChatMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    sources: message.sources,
    interrupted: message.role === "assistant" && message.status !== "complete",
  };
}

export function useChatSession({ docId, workspaceId, mock = false, accessToken }: {
  docId: string | null; workspaceId: string | null; mock?: boolean; accessToken?: string | null;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const transcriptRequest = useRef<AbortController | null>(null);
  const resetRequest = useRef<AbortController | null>(null);
  const restoreEpoch = useRef(0);

  const stop = useCallback(() => {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setLoading(false);
    setMessages((items) => items.map((item) => item.isStreaming ? { ...item, isStreaming: false, interrupted: true } : item));
  }, []);

  /** Clear local state without touching server-side transcripts. */
  const clearMessages = useCallback(() => {
    activeRequest.current?.abort();
    activeRequest.current = null;
    transcriptRequest.current?.abort();
    transcriptRequest.current = null;
    resetRequest.current?.abort();
    resetRequest.current = null;
    restoreEpoch.current += 1;
    setLoading(false);
    setTranscriptLoading(false);
    setResetting(false);
    setMessages([]);
    setConversationId(null);
    setInput("");
    setError(null);
  }, []);

  // Reload the latest transcript for the selected document. The epoch guard
  // prevents a late transcript response from leaking into a newer selection.
  useEffect(() => {
    clearMessages();
    if (mock || !docId || !workspaceId || !accessToken) return;
    const epoch = ++restoreEpoch.current;
    const controller = new AbortController();
    transcriptRequest.current = controller;
    setTranscriptLoading(true);
    void (async () => {
      try {
        const items = await listConversations(accessToken, workspaceId, docId, controller.signal);
        if (controller.signal.aborted || restoreEpoch.current !== epoch) return;
        const latest = items[0];
        if (!latest) return;
        const transcript = await getConversation(
          latest.id, accessToken, workspaceId, controller.signal,
        );
        if (controller.signal.aborted || restoreEpoch.current !== epoch) return;
        setConversationId(transcript.id);
        setMessages(transcript.messages.map(restoredMessage));
      } catch (cause) {
        if (!controller.signal.aborted && restoreEpoch.current === epoch) {
          setError(cause instanceof Error ? cause.message : "Không thể tải hội thoại.");
        }
      } finally {
        if (restoreEpoch.current === epoch && !controller.signal.aborted) {
          setTranscriptLoading(false);
        }
        if (transcriptRequest.current === controller) transcriptRequest.current = null;
      }
    })();
    return () => controller.abort();
  }, [docId, workspaceId, mock, accessToken, clearMessages]);

  useEffect(() => () => {
    activeRequest.current?.abort();
    transcriptRequest.current?.abort();
    resetRequest.current?.abort();
  }, []);

  const submit = useCallback(async (question?: string) => {
    const query = (question ?? input).trim();
    if (!query || activeRequest.current || transcriptLoading || resetRequest.current) return;
    if (!workspaceId && !mock) { setError("Vui lòng chọn không gian làm việc."); return; }
    if (!docId && !mock) { setError("Vui lòng chọn một PDF sẵn sàng trong thư viện."); return; }
    if (!mock && !accessToken) { setError("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."); return; }
    const controller = new AbortController();
    activeRequest.current = controller;
    transcriptRequest.current?.abort();
    transcriptRequest.current = null;
    restoreEpoch.current += 1;
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
        const response = await streamChat(query, docId!, accessToken!, workspaceId!, id, controller.signal);
        if (activeRequest.current !== controller || controller.signal.aborted) {
          await response.body?.cancel();
          return;
        }
        const activeConversation = response.headers.get("X-Conversation-Id");
        if (activeConversation) setConversationId(activeConversation);
        for await (const event of streamChatSSEParser(response.body!)) {
          if (activeRequest.current !== controller || controller.signal.aborted) break;
          if (event.type === "sources") update({ sources: event.data });
          if (event.type === "token") update({}, event.data);
          if (event.type === "error") { setError(event.data.message); interrupted = true; }
        }
      }
    } catch (cause) {
      if (activeRequest.current === controller && !controller.signal.aborted) {
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
  }, [input, docId, workspaceId, mock, accessToken, transcriptLoading]);

  const newChat = useCallback(async () => {
    if (resetRequest.current) return;
    let target = conversationId;
    const currentDoc = docId;
    if (mock || !accessToken || !workspaceId || (!target && !currentDoc)) {
      clearMessages();
      return;
    }
    stop();
    transcriptRequest.current?.abort();
    transcriptRequest.current = null;
    restoreEpoch.current += 1;
    setTranscriptLoading(false);
    const controller = new AbortController();
    resetRequest.current = controller;
    const current = () => resetRequest.current === controller && !controller.signal.aborted;
    setResetting(true);
    setError(null);
    try {
      // The transcript may still be loading (or the page may have been
      // reloaded and the user clicked immediately). Resolve the latest saved
      // conversation for this document before deleting so it cannot reappear.
      if (!target) {
        const items = await listConversations(accessToken, workspaceId, currentDoc!, controller.signal);
        if (!current()) return;
        target = items[0]?.id ?? null;
      }
      if (target) {
        setConversationId(target);
        try {
          await deleteConversation(target, accessToken, workspaceId, controller.signal);
        } catch (cause) {
          // Another tab may already have deleted it; the desired state is met.
          if (!(cause instanceof ApiError && cause.status === 404)) throw cause;
        }
      }
      if (current()) clearMessages();
    } catch (cause) {
      if (current()) setError(cause instanceof Error ? cause.message : "Không thể xóa hội thoại.");
    } finally {
      if (current()) {
        resetRequest.current = null;
        setResetting(false);
      }
    }
  }, [conversationId, docId, mock, accessToken, workspaceId, clearMessages, stop]);

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

  return {
    messages, input, setInput, loading, transcriptLoading, resetting, conversationId,
    error, submit, stop, clearMessages, newChat, exportTranscript,
  };
}

export type ChatSession = ReturnType<typeof useChatSession>;
