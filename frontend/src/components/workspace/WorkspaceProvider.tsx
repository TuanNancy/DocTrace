"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { User } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import { deleteDocument, listDocuments, retryDocument } from "@/lib/api";
import { isPending } from "@/lib/documents";
import { useChatSession } from "@/lib/use-chat-session";
import { useUpload } from "@/lib/use-upload";
import type { ChatSource, LibraryDocument } from "@/types";

function useWorkspaceState() {
  const supabase = useMemo(() => createClient(), []);
  const mock = !process.env.NEXT_PUBLIC_API_URL?.trim();
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [documents, setDocuments] = useState<LibraryDocument[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [docId, setDocId] = useState<string | null>(null);
  const [source, setSource] = useState<ChatSource | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [busyIds, setBusyIds] = useState<string[]>([]);
  const documentRequest = useRef<AbortController | null>(null);
  const userId = user?.id;
  const chat = useChatSession({ docId, mock, accessToken });
  const activeDocument = documents.find((document) => document.doc_id === docId) ?? null;

  useEffect(() => {
    let mounted = true;
    const bootstrap = async () => {
      try {
        const [{ data: verified }, { data: session }] = await Promise.all([supabase.auth.getUser(), supabase.auth.getSession()]);
        if (mounted) {
          setUser(verified.user ?? session.session?.user ?? null);
          setAccessToken(session.session?.access_token ?? null);
        }
      } catch { if (mounted) setNotice("Không thể kiểm tra phiên đăng nhập. Hãy tải lại trang."); }
      finally { if (mounted) setAuthReady(true); }
    };
    void bootstrap();
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null); setAccessToken(session?.access_token ?? null); setAuthReady(true);
    });
    return () => { mounted = false; subscription.unsubscribe(); };
  }, [supabase]);

  useEffect(() => {
    setDocuments([]); setDocId(null); setSource(null);
    return () => { documentRequest.current?.abort(); };
  }, [userId]);

  const refresh = useCallback(async () => {
    if (mock) { setDocumentsLoading(false); return; }
    if (!accessToken || !userId) return;
    documentRequest.current?.abort();
    const controller = new AbortController();
    documentRequest.current = controller;
    try {
      const result = await listDocuments(accessToken, controller.signal);
      if (controller.signal.aborted) return;
      setDocuments(result); setLibraryError(null);
    } catch (cause) {
      if (!controller.signal.aborted) setLibraryError(cause instanceof Error ? cause.message : "Không thể tải thư viện.");
    } finally {
      if (!controller.signal.aborted) setDocumentsLoading(false);
      if (documentRequest.current === controller) documentRequest.current = null;
    }
  }, [accessToken, mock, userId]);

  useEffect(() => {
    setDocumentsLoading(true);
    void refresh();
    const focus = () => { void refresh(); };
    window.addEventListener("focus", focus);
    return () => { documentRequest.current?.abort(); window.removeEventListener("focus", focus); };
  }, [refresh]);

  const pending = documents.some((document) => isPending(document.status));
  useEffect(() => {
    if (!pending || mock) return;
    const timer = window.setInterval(() => { if (!document.hidden && !documentRequest.current) void refresh(); }, 2500);
    return () => window.clearInterval(timer);
  }, [pending, mock, refresh]);

  useEffect(() => { setSource(null); }, [docId]);
  useEffect(() => {
    if (documentsLoading || !docId) return;
    if (!documents.some((document) => document.doc_id === docId && document.status === "ready")) {
      setNotice("Tài liệu đang chọn đã bị xóa hoặc chưa sẵn sàng.");
      setDocId(null);
    }
  }, [documents, documentsLoading, docId]);

  const uploaded = useCallback((result: LibraryDocument) => {
    documentRequest.current?.abort();
    setDocuments((items) => [result, ...items.filter((item) => item.doc_id !== result.doc_id)]);
    setNotice(mock ? "Đã thêm PDF minh họa. Nội dung chat ở chế độ demo." : "Đã thêm PDF vào thư viện. Trạng thái xử lý được cập nhật tự động.");
    if (!mock) void refresh();
  }, [mock, refresh]);
  const upload = useUpload({ accessToken, mock, onUploadComplete: uploaded });

  const operate = async (document: LibraryDocument, operation: "delete" | "retry") => {
    if (busyIds.includes(document.doc_id)) return;
    setBusyIds((ids) => [...ids, document.doc_id]);
    try {
      if (mock) {
        setDocuments((items) => operation === "delete" ? items.filter((item) => item.doc_id !== document.doc_id)
          : items.map((item) => item.doc_id === document.doc_id ? { ...item, status: "ready", error: null } : item));
      } else {
        const result = await (operation === "delete" ? deleteDocument : retryDocument)(document.doc_id, accessToken!);
        documentRequest.current?.abort();
        setDocuments((items) => items.map((item) => item.doc_id === document.doc_id ? result : item));
      }
      if (operation === "delete") {
        setDocId((selected) => selected === document.doc_id ? null : selected);
        setSource((selected) => selected?.doc_id === document.doc_id ? null : selected);
        setNotice(`Đã yêu cầu xóa “${document.name}”.`);
      }
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : "Thao tác thất bại. Vui lòng thử lại.");
      if (!mock) void refresh(); // A 409 can mean the job changed since the last poll.
    }
    finally { setBusyIds((ids) => ids.filter((id) => id !== document.doc_id)); }
  };

  const selectDocument = (document: LibraryDocument) => {
    if (document.status !== "ready") return;
    setDocId(document.doc_id); setSource(null); setSourcesOpen(false); setSidebarOpen(false);
  };
  const selectSource = (selected: ChatSource) => { setSource(selected); setSourcesOpen(true); };
  const newChat = () => { chat.clearMessages(); setSource(null); setSidebarOpen(false); };
  const signOut = async () => {
    const { error } = await supabase.auth.signOut();
    if (error) { setNotice(error.message); return; }
    chat.clearMessages(); setDocuments([]); setDocId(null);
    window.location.assign("/auth/login");
  };

  return { user, accessToken, authReady, mock, documents, documentsLoading, libraryError, refresh,
    notice, setNotice, docId, activeDocument, selectDocument, source, setSource, selectSource,
    sidebarOpen, setSidebarOpen, sourcesOpen, setSourcesOpen, busyIds, operate, chat, upload, newChat, signOut };
}

type WorkspaceState = ReturnType<typeof useWorkspaceState>;
const WorkspaceContext = createContext<WorkspaceState | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const value = useWorkspaceState();
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("WorkspaceProvider is required");
  return value;
}
