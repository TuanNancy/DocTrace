"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { User } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import { deleteDocument, listConversations, listDocuments, listWorkspaces, retryDocument } from "@/lib/api";
import { isPending } from "@/lib/documents";
import { useChatSession } from "@/lib/use-chat-session";
import { useUpload } from "@/lib/use-upload";
import type { ChatSource, LibraryDocument, Workspace } from "@/types";

function demoWorkspace(userId: string): Workspace {
  return {
    id: userId, name: "Không gian demo", kind: "personal", role: "owner",
    plan: "free", status: "active", created_at: null,
  };
}

/** Keep the current active workspace when it survives a refresh, else pick personal. */
function nextWorkspaceId(workspaces: Workspace[], current: string | null): string | null {
  if (current && workspaces.some((workspace) => workspace.id === current && workspace.status === "active")) {
    return current;
  }
  return workspaces.find((workspace) => workspace.kind === "personal" && workspace.status === "active")?.id
    ?? workspaces.find((workspace) => workspace.status === "active")?.id
    ?? null;
}

function useWorkspaceState() {
  const supabase = useMemo(() => createClient(), []);
  const mock = !process.env.NEXT_PUBLIC_API_URL?.trim();
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspacesLoading, setWorkspacesLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
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
  const workspaceRequest = useRef<AbortController | null>(null);
  const restoreAttempted = useRef<string | null>(null);
  const restoreRequest = useRef<string | null>(null);
  const workspaceIdRef = useRef<string | null>(workspaceId);
  workspaceIdRef.current = workspaceId;
  const userId = user?.id;
  const chat = useChatSession({ docId, workspaceId, mock, accessToken });
  const activeDocument = documents.find((document) => document.doc_id === docId) ?? null;
  const activeWorkspace = workspaces.find((workspace) => workspace.id === workspaceId) ?? null;

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
    workspaceRequest.current?.abort();
    documentRequest.current?.abort();
    setWorkspaces([]); setWorkspaceId(null); setWorkspaceError(null); setWorkspacesLoading(false);
    setDocuments([]); setDocumentsLoading(true); setLibraryError(null); setBusyIds([]);
    setDocId(null); setSource(null); setNotice(null); setSourcesOpen(false);
    return () => {
      workspaceRequest.current?.abort();
      documentRequest.current?.abort();
    };
  }, [userId]);

  const refreshWorkspaces = useCallback(async () => {
    if (!userId) { setWorkspaces([]); setWorkspaceId(null); setWorkspacesLoading(false); return; }
    if (mock) {
      const workspace = demoWorkspace(userId);
      setWorkspaces([workspace]);
      setWorkspaceId((current) => current === workspace.id ? current : workspace.id);
      setWorkspaceError(null);
      setWorkspacesLoading(false);
      return;
    }
    if (!accessToken) return;
    workspaceRequest.current?.abort();
    const controller = new AbortController();
    workspaceRequest.current = controller;
    setWorkspacesLoading(true);
    try {
      const items = await listWorkspaces(accessToken, controller.signal);
      if (controller.signal.aborted) return;
      setWorkspaces(items);
      setWorkspaceError(null);
      setWorkspaceId((current) => nextWorkspaceId(items, current));
    } catch (cause) {
      if (!controller.signal.aborted) {
        setWorkspaces([]);
        setWorkspaceId(null);
        setWorkspaceError(cause instanceof Error ? cause.message : "Không thể tải danh sách workspace.");
      }
    } finally {
      if (!controller.signal.aborted) setWorkspacesLoading(false);
      if (workspaceRequest.current === controller) workspaceRequest.current = null;
    }
  }, [accessToken, mock, userId]);

  useEffect(() => {
    if (!userId) return;
    void refreshWorkspaces();
    return () => { workspaceRequest.current?.abort(); };
  }, [refreshWorkspaces, userId]);

  // A workspace change invalidates every workspace-scoped resource immediately.
  useEffect(() => {
    documentRequest.current?.abort();
    setDocuments([]); setDocumentsLoading(!!workspaceId); setLibraryError(null); setBusyIds([]);
    setDocId(null); setSource(null); setSourcesOpen(false);
    return () => { documentRequest.current?.abort(); };
  }, [workspaceId]);

  const refresh = useCallback(async () => {
    if (mock) { setDocumentsLoading(false); return; }
    if (!accessToken || !userId || !workspaceId) {
      setDocuments([]); setDocumentsLoading(false);
      return;
    }
    documentRequest.current?.abort();
    const controller = new AbortController();
    documentRequest.current = controller;
    try {
      const result = await listDocuments(accessToken, workspaceId, controller.signal);
      if (controller.signal.aborted) return;
      setDocuments(result); setLibraryError(null);
    } catch (cause) {
      if (!controller.signal.aborted) setLibraryError(cause instanceof Error ? cause.message : "Không thể tải thư viện.");
    } finally {
      if (!controller.signal.aborted) setDocumentsLoading(false);
      if (documentRequest.current === controller) documentRequest.current = null;
    }
  }, [accessToken, mock, userId, workspaceId]);

  useEffect(() => {
    if (!workspaceId) return;
    setDocumentsLoading(true);
    void refresh();
    const focus = () => { void refresh(); };
    window.addEventListener("focus", focus);
    return () => { documentRequest.current?.abort(); window.removeEventListener("focus", focus); };
  }, [refresh, workspaceId]);

  const pending = documents.some((document) => isPending(document.status));
  useEffect(() => {
    if (!pending || mock || !workspaceId) return;
    const timer = window.setInterval(() => { if (!document.hidden && !documentRequest.current) void refresh(); }, 2500);
    return () => window.clearInterval(timer);
  }, [pending, mock, refresh, workspaceId]);

  useEffect(() => { setSource(null); }, [docId]);
  useEffect(() => {
    if (documentsLoading || !docId) return;
    if (!documents.some((document) => document.doc_id === docId && document.status === "ready")) {
      setNotice("Tài liệu đang chọn đã bị xóa hoặc chưa sẵn sàng.");
      setDocId(null);
    }
  }, [documents, documentsLoading, docId]);

  // Reload behaviour: if no document is selected yet, restore the latest
  // conversation whose document is still ready in this workspace. This runs
  // once per workspace so "Chat mới" cannot immediately resurrect an old chat.
  useEffect(() => { restoreAttempted.current = null; }, [workspaceId]);
  useEffect(() => {
    if (mock || !accessToken || !userId || !workspaceId) return;
    if (documentsLoading || docId || restoreAttempted.current === workspaceId
        || restoreRequest.current === workspaceId) return;
    const ready = new Set(
      documents.filter((document) => document.status === "ready").map((document) => document.doc_id),
    );
    if (!ready.size) return;
    restoreRequest.current = workspaceId;
    void listConversations(accessToken, workspaceId)
      .then((items) => {
        if (workspaceIdRef.current !== workspaceId) return;
        // "Chat mới" while this initial lookup is in flight must not select a
        // document only to show the transcript the user just dismissed.
        if (restoreAttempted.current === workspaceId) return;
        const latest = items.find((item) => ready.has(item.doc_id));
        if (latest) setDocId((current) => current ?? latest.doc_id);
      })
      .catch(() => { /* A transcript restore failure must not block the library. */ })
      .finally(() => {
        if (workspaceIdRef.current === workspaceId) restoreAttempted.current = workspaceId;
        if (restoreRequest.current === workspaceId) restoreRequest.current = null;
      });
  }, [accessToken, docId, documents, documentsLoading, mock, userId, workspaceId]);

  const uploaded = useCallback((result: LibraryDocument) => {
    if (workspaceId !== workspaceIdRef.current) return;
    documentRequest.current?.abort();
    setDocuments((items) => [result, ...items.filter((item) => item.doc_id !== result.doc_id)]);
    setNotice(mock ? "Đã thêm PDF minh họa. Nội dung chat ở chế độ demo." : "Đã thêm PDF vào thư viện. Trạng thái xử lý được cập nhật tự động.");
    if (!mock) void refresh();
  }, [mock, refresh, workspaceId]);
  const upload = useUpload({ accessToken, workspaceId, mock, onUploadComplete: uploaded });

  const operate = async (document: LibraryDocument, operation: "delete" | "retry") => {
    if (busyIds.includes(document.doc_id)) return;
    const operationWorkspace = workspaceId;
    setBusyIds((ids) => [...ids, document.doc_id]);
    try {
      if (mock) {
        setDocuments((items) => operation === "delete" ? items.filter((item) => item.doc_id !== document.doc_id)
          : items.map((item) => item.doc_id === document.doc_id ? { ...item, status: "ready", error: null } : item));
      } else {
        const result = await (operation === "delete" ? deleteDocument : retryDocument)(
          document.doc_id, accessToken!, operationWorkspace!,
        );
        if (operationWorkspace !== workspaceIdRef.current) return;
        documentRequest.current?.abort();
        setDocuments((items) => items.map((item) => item.doc_id === document.doc_id ? result : item));
      }
      if (operationWorkspace !== workspaceIdRef.current) return;
      if (operation === "delete") {
        setDocId((selected) => selected === document.doc_id ? null : selected);
        setSource((selected) => selected?.doc_id === document.doc_id ? null : selected);
        setNotice(`Đã yêu cầu xóa “${document.name}”.`);
      }
    } catch (cause) {
      if (operationWorkspace !== workspaceIdRef.current) return;
      setNotice(cause instanceof Error ? cause.message : "Thao tác thất bại. Vui lòng thử lại.");
      if (!mock) void refresh(); // A 409 can mean the job changed since the last poll.
    } finally {
      setBusyIds((ids) => ids.filter((id) => id !== document.doc_id));
    }
  };

  const switchWorkspace = (id: string) => {
    if (id === workspaceId) return;
    const target = workspaces.find((workspace) => workspace.id === id);
    if (!target || target.status !== "active") {
      setNotice("Không gian làm việc này không khả dụng.");
      return;
    }
    documentRequest.current?.abort();
    chat.clearMessages();
    setWorkspaceId(id);
    setDocuments([]); setDocumentsLoading(true); setLibraryError(null); setBusyIds([]);
    setDocId(null); setSource(null); setSourcesOpen(false);
    setNotice(`Đã chuyển sang “${target.name}”.`);
  };

  const selectDocument = (document: LibraryDocument) => {
    if (document.status !== "ready") return;
    setDocId(document.doc_id); setSource(null); setSourcesOpen(false); setSidebarOpen(false);
  };
  const selectSource = (selected: ChatSource) => { setSource(selected); setSourcesOpen(true); };
  const newChat = () => {
    restoreAttempted.current = workspaceId;
    void chat.newChat();
    setSource(null);
    setSidebarOpen(false);
  };
  const signOut = async () => {
    const { error } = await supabase.auth.signOut();
    if (error) { setNotice(error.message); return; }
    chat.clearMessages(); setDocuments([]); setDocId(null); setSource(null);
    setWorkspaces([]); setWorkspaceId(null);
    window.location.assign("/auth/login");
  };

  return { user, accessToken, authReady, mock, workspaces, workspacesLoading, workspaceError,
    workspaceId, activeWorkspace, switchWorkspace, refreshWorkspaces,
    documents, documentsLoading, libraryError, refresh,
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
