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

interface ChatAttempt {
  id: string;
  query: string;
  workspaceId: string | null;
  docId: string | null;
  failed: boolean;
}

export function useChatSession({ docId, workspaceId, userId, mock = false, accessToken }: {
  docId: string | null; workspaceId: string | null; userId?: string | null; mock?: boolean; accessToken?: string | null;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryMode, setRetryMode] = useState<"same" | "new" | null>(null);
  const lastAttempt = useRef<ChatAttempt | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const transcriptRequest = useRef<AbortController | null>(null);
  const resetRequest = useRef<AbortController | null>(null);
  const restoreEpoch = useRef(0);
  const tokenRef = useRef(accessToken);
  tokenRef.current = accessToken;
  const authenticated = !!accessToken;
  // Provider supplies the authenticated identity, so routine token renewal
  // does not discard an uncertain request id or interrupt a valid stream.
  const identity = userId ?? accessToken;

  const stop = useCallback(() => {
    if (activeRequest.current && lastAttempt.current) setRetryMode("same");
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
    lastAttempt.current = null;
    setRetryMode(null);
  }, []);

  // Reload the latest transcript for the selected document. The epoch guard
  // prevents a late transcript response from leaking into a newer selection.
  useEffect(() => {
    clearMessages();
    const token = tokenRef.current;
    if (mock || !docId || !workspaceId || !token || !authenticated || !identity) return;
    const epoch = ++restoreEpoch.current;
    const controller = new AbortController();
    transcriptRequest.current = controller;
    setTranscriptLoading(true);
    void (async () => {
      try {
        const items = await listConversations(token, workspaceId, docId, controller.signal);
        if (controller.signal.aborted || restoreEpoch.current !== epoch) return;
        const latest = items[0];
        if (!latest) return;
        const transcript = await getConversation(
          latest.id, token, workspaceId, controller.signal,
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
  }, [docId, workspaceId, mock, authenticated, identity, clearMessages]);

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
    const previous = lastAttempt.current;
    const reuse = previous && !previous.failed && previous.query === query
      && previous.docId === docId && previous.workspaceId === workspaceId;
    const attempt: ChatAttempt = reuse ? previous : {
      id: crypto.randomUUID(), query, docId, workspaceId, failed: false,
    };
    lastAttempt.current = attempt;
    const { id } = attempt;
    const current = () => activeRequest.current === controller && !controller.signal.aborted;
    setRetryMode(null);
    setError(null);
    setInput("");
    setLoading(true);
    if (reuse) {
      setMessages((items) => items.map((item) => item.id === id ? { ...item, isStreaming: true } : item));
    } else {
      setMessages((items) => [...items, { id: crypto.randomUUID(), role: "user", content: query },
        { id, role: "assistant", content: "", isStreaming: true }]);
    }
    const update = (values: Partial<ChatMessage>, delta?: string) => {
      if (!current()) return;
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
        if (!current()) {
          await response.body?.cancel();
          return;
        }
        const activeConversation = response.headers.get("X-Conversation-Id");
        if (activeConversation) setConversationId(activeConversation);
        for await (const event of streamChatSSEParser(response.body!)) {
          if (!current()) break;
          if (event.type === "sources") update({ sources: event.data });
          if (event.type === "token") update({}, event.data);
          if (event.type === "error") { setError(event.data.message); interrupted = true; attempt.failed = true; }
        }
      }
    } catch (cause) {
      if (current()) {
        interrupted = true;
        const duplicate = cause instanceof ApiError && cause.status === 409 ? cause : null;
        const target = duplicate && typeof duplicate.detail.conversation_id === "string"
          ? duplicate.detail.conversation_id : null;
        if (duplicate?.code === "request_completed") {
          if (!target) {
            lastAttempt.current = null;
            setError("Yêu cầu đã hoàn tất nhưng hội thoại không còn khả dụng.");
          } else {
            try {
              const transcript = await getConversation(target, accessToken!, workspaceId!, controller.signal);
              if (!current()) return;
              if (transcript.workspace_id !== workspaceId || transcript.doc_id !== docId) {
                throw new Error("Hội thoại không khớp tài liệu hiện tại.");
              }
              setConversationId(transcript.id);
              setMessages(transcript.messages.map(restoredMessage));
              interrupted = false;
            } catch (restoreError) {
              if (!current()) return;
              if (restoreError instanceof ApiError && restoreError.status === 404) {
                lastAttempt.current = null;
                setError("Yêu cầu đã hoàn tất nhưng hội thoại không còn khả dụng.");
              } else {
                setError(restoreError instanceof Error ? restoreError.message : "Không thể khôi phục câu trả lời.");
              }
            }
          }
        } else {
          if (duplicate?.code === "request_failed") attempt.failed = true;
          if (target && ["request_failed", "request_in_progress"].includes(duplicate?.code ?? "")) setConversationId(target);
          setError(cause instanceof Error ? cause.message : "Không thể gửi câu hỏi.");
        }
      }
    } finally {
      if (current()) {
        update({ isStreaming: false, interrupted });
        if (!interrupted) lastAttempt.current = null;
        setRetryMode(lastAttempt.current ? (attempt.failed ? "new" : "same") : null);
        activeRequest.current = null;
        setLoading(false);
      }
    }
  }, [input, docId, workspaceId, mock, accessToken, transcriptLoading]);

  const retryLastRequest = useCallback(async () => {
    const attempt = lastAttempt.current;
    if (attempt) await submit(attempt.query);
  }, [submit]);

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
    error, retryMode, retryLastRequest, submit, stop, clearMessages, newChat, exportTranscript,
  };
}

export type ChatSession = ReturnType<typeof useChatSession>;
