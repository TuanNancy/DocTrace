import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { WorkspaceProvider, useWorkspace } from "@/components/workspace/WorkspaceProvider";
import {
  deleteConversation, deleteDocument, getConversation, listConversations, listDocuments,
  listWorkspaces, streamChat,
} from "@/lib/api";
import type { ChatSource, LibraryDocument, Transcript, Workspace } from "@/types";

const client = vi.hoisted(() => ({ auth: {
  getUser: vi.fn(), getSession: vi.fn(), onAuthStateChange: vi.fn(),
} }));
vi.mock("@/lib/supabase/client", () => ({ createClient: () => client }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  deleteConversation: vi.fn(), deleteDocument: vi.fn(), getConversation: vi.fn(),
  listConversations: vi.fn(), listDocuments: vi.fn(), listWorkspaces: vi.fn(),
  streamChat: vi.fn(),
}));

const documents: LibraryDocument[] = ["a", "b"].map((id) => ({
  doc_id: id, name: `${id}.pdf`, status: "ready", size_bytes: 100, chunks_count: 1,
  warnings: [], error: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
}));
const workspaces: Workspace[] = [
  { id: "workspace-a", name: "Cá nhân", kind: "personal", role: "owner", plan: "free", status: "active", created_at: null },
  { id: "workspace-b", name: "Nhóm học tập", kind: "team", role: "member", plan: "free", status: "active", created_at: null },
];
const source = (id: string): ChatSource => ({
  doc_id: id, chunk_id: `chunk-${id}`, citation_id: 1, page: 1, source: `${id}.pdf`, score: null,
});
const response = () => new Response('event: token\ndata: "Answer"\n\nevent: done\ndata: "[DONE]"\n\n');
const savedTranscript: Transcript = {
  id: "conversation-b", workspace_id: "workspace-a", doc_id: "b",
  created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:01:00Z",
  messages: [
    {
      id: "message-1", role: "user", content: "Câu hỏi đã lưu", sources: [],
      index_id: null, status: "complete",
      created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:00:00Z",
    },
    {
      id: "message-2", role: "assistant", content: "Câu trả lời đã lưu",
      index_id: "index-b", status: "complete",
      created_at: "2026-10-26T00:00:01Z", updated_at: "2026-10-26T00:00:01Z",
      sources: [{ ...source("b"), stale: false }],
    },
  ],
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.test");
  const user = { id: "owner" };
  client.auth.getUser.mockResolvedValue({ data: { user } });
  client.auth.getSession.mockResolvedValue({ data: { session: { user, access_token: "token" } } });
  client.auth.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } });
  vi.mocked(listWorkspaces).mockResolvedValue(workspaces);
  vi.mocked(listConversations).mockResolvedValue([]);
  vi.mocked(deleteConversation).mockResolvedValue(undefined);
  vi.mocked(listDocuments).mockImplementation(async (_token, workspaceId) =>
    workspaceId === "workspace-a" ? documents : []);
});

async function mountWorkspace() {
  const hook = renderHook(useWorkspace, {
    wrapper: ({ children }: PropsWithChildren) => <WorkspaceProvider>{children}</WorkspaceProvider>,
  });
  await waitFor(() => expect(hook.result.current.workspaceId).toBe("workspace-a"));
  await waitFor(() => expect(hook.result.current.documents).toEqual(documents));
  return hook.result;
}

it("selects the personal workspace and scopes the library request to it", async () => {
  const workspace = await mountWorkspace();
  expect(workspace.current.activeWorkspace?.name).toBe("Cá nhân");
  expect(listWorkspaces).toHaveBeenCalledWith("token", expect.any(AbortSignal));
  expect(listDocuments).toHaveBeenCalledWith("token", "workspace-a", expect.any(AbortSignal));
});

it("restores the latest ready conversation and new chat deletes that transcript", async () => {
  const summary = {
    id: savedTranscript.id, doc_id: savedTranscript.doc_id, message_count: 2,
    created_at: savedTranscript.created_at, updated_at: savedTranscript.updated_at,
  };
  vi.mocked(listConversations).mockResolvedValue([summary]);
  vi.mocked(getConversation).mockResolvedValue(savedTranscript);
  const workspace = await mountWorkspace();

  await waitFor(() => expect(workspace.current.docId).toBe("b"));
  await waitFor(() => expect(workspace.current.chat.messages.map((message) => message.content))
    .toEqual(["Câu hỏi đã lưu", "Câu trả lời đã lưu"]));
  expect(listConversations).toHaveBeenCalledWith("token", "workspace-a");
  expect(listConversations).toHaveBeenCalledWith(
    "token", "workspace-a", "b", expect.any(AbortSignal),
  );
  expect(getConversation).toHaveBeenCalledWith(
    "conversation-b", "token", "workspace-a", expect.any(AbortSignal),
  );

  await act(async () => { await workspace.current.chat.newChat(); });
  expect(deleteConversation).toHaveBeenCalledWith("conversation-b", "token", "workspace-a", expect.any(AbortSignal));
  expect(workspace.current.chat.messages).toEqual([]);
  expect(workspace.current.docId).toBe("b");
  // A deleted transcript must not be restored again for this workspace.
  await act(async () => { await Promise.resolve(); });
  expect(listConversations).toHaveBeenCalledTimes(2);
});

it("keeps the chat empty when new chat is clicked during the initial transcript lookup", async () => {
  let resolveConversations!: (items: Awaited<ReturnType<typeof listConversations>>) => void;
  vi.mocked(listConversations).mockReturnValue(new Promise((resolve) => { resolveConversations = resolve; }));
  const workspace = await mountWorkspace();
  await waitFor(() => expect(listConversations).toHaveBeenCalledWith("token", "workspace-a"));

  act(() => workspace.current.newChat());
  await act(async () => {
    resolveConversations([{
      id: "conversation-b", doc_id: "b", message_count: 2,
      created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:01:00Z",
    }]);
    await Promise.resolve();
  });

  expect(workspace.current.docId).toBeNull();
  expect(workspace.current.chat.messages).toEqual([]);
  expect(deleteConversation).not.toHaveBeenCalled();
});

it("keeps archived workspaces listed but selects an active one by default", async () => {
  vi.mocked(listWorkspaces).mockResolvedValue([
    { ...workspaces[0], status: "archived" },
    workspaces[1],
  ]);
  const hook = renderHook(useWorkspace, {
    wrapper: ({ children }: PropsWithChildren) => <WorkspaceProvider>{children}</WorkspaceProvider>,
  });
  await waitFor(() => expect(hook.result.current.workspaceId).toBe("workspace-b"));
  expect(hook.result.current.workspaces.map((item) => item.status)).toEqual(["archived", "active"]);
});

it("switching workspace clears document, source and chat, then rejects late answers", async () => {
  let finishChat!: (response: Response) => void;
  vi.mocked(streamChat).mockReturnValue(new Promise((resolve) => { finishChat = resolve; }));
  const workspace = await mountWorkspace();
  act(() => workspace.current.selectDocument(documents[0]));
  await waitFor(() => expect(workspace.current.chat.transcriptLoading).toBe(false));
  let chat!: Promise<void>;
  act(() => { chat = workspace.current.chat.submit("Question about A"); });
  act(() => workspace.current.selectSource(source("a")));
  const signal = vi.mocked(streamChat).mock.calls[0][5];

  await act(async () => { workspace.current.switchWorkspace("workspace-b"); });

  expect(workspace.current.workspaceId).toBe("workspace-b");
  expect(workspace.current.docId).toBeNull();
  expect(workspace.current.source).toBeNull();
  expect(workspace.current.chat.messages).toEqual([]);
  expect(workspace.current.chat.loading).toBe(false);
  expect(signal?.aborted).toBe(true);
  await waitFor(() => expect(workspace.current.documents).toEqual([]));
  expect(listDocuments).toHaveBeenCalledWith("token", "workspace-b", expect.any(AbortSignal));

  await act(async () => { finishChat(response()); await chat; });
  expect(workspace.current.chat.messages).toEqual([]);
  expect(workspace.current.documents).toEqual([]);
});

it("ignores a deletion response that arrives after the workspace changed", async () => {
  let finishDelete!: (document: LibraryDocument) => void;
  vi.mocked(deleteDocument).mockReturnValue(new Promise((resolve) => { finishDelete = resolve; }));
  const workspace = await mountWorkspace();
  let deletion!: Promise<void>;
  act(() => { deletion = workspace.current.operate(documents[0], "delete"); });
  await act(async () => { workspace.current.switchWorkspace("workspace-b"); });
  await waitFor(() => expect(workspace.current.documents).toEqual([]));

  await act(async () => { finishDelete({ ...documents[0], status: "deleting" }); await deletion; });
  expect(workspace.current.documents).toEqual([]);
  expect(workspace.current.notice).not.toContain("a.pdf");
});

it("preserves the new selection, source and stream when an older deletion responds", async () => {
  let finishDelete!: (document: LibraryDocument) => void;
  let finishChat!: (response: Response) => void;
  vi.mocked(deleteDocument).mockReturnValue(new Promise((resolve) => { finishDelete = resolve; }));
  vi.mocked(streamChat).mockReturnValue(new Promise((resolve) => { finishChat = resolve; }));
  const workspace = await mountWorkspace();
  act(() => workspace.current.selectDocument(documents[0]));
  await waitFor(() => expect(workspace.current.chat.transcriptLoading).toBe(false));
  let deletion!: Promise<void>;
  act(() => { deletion = workspace.current.operate(documents[0], "delete"); });
  act(() => workspace.current.selectDocument(documents[1]));
  await waitFor(() => expect(workspace.current.chat.transcriptLoading).toBe(false));
  let chat!: Promise<void>;
  act(() => { chat = workspace.current.chat.submit("Question about B"); });
  act(() => workspace.current.selectSource(source("b")));
  const signal = vi.mocked(streamChat).mock.calls[0][5];

  await act(async () => { finishDelete({ ...documents[0], status: "deleting" }); await deletion; });

  expect(workspace.current.docId).toBe("b");
  expect(workspace.current.source).toEqual(source("b"));
  expect(workspace.current.chat.messages[0].content).toBe("Question about B");
  expect(workspace.current.chat.loading).toBe(true);
  expect(signal?.aborted).toBe(false);
  await act(async () => { finishChat(response()); await chat; });
  expect(workspace.current.chat.messages[1].content).toBe("Answer");
});

it("clears the source and cancels chat when the deleted document is still selected", async () => {
  let finishChat!: (response: Response) => void;
  vi.mocked(streamChat).mockReturnValue(new Promise((resolve) => { finishChat = resolve; }));
  vi.mocked(deleteDocument).mockResolvedValue({ ...documents[0], status: "deleting" });
  const workspace = await mountWorkspace();
  act(() => workspace.current.selectDocument(documents[0]));
  await waitFor(() => expect(workspace.current.chat.transcriptLoading).toBe(false));
  let chat!: Promise<void>;
  act(() => { chat = workspace.current.chat.submit("Question about A"); });
  act(() => workspace.current.selectSource(source("a")));
  const signal = vi.mocked(streamChat).mock.calls[0][5];

  await act(async () => { await workspace.current.operate(documents[0], "delete"); });

  expect(workspace.current.docId).toBeNull();
  expect(workspace.current.source).toBeNull();
  expect(workspace.current.chat.messages).toEqual([]);
  expect(workspace.current.chat.loading).toBe(false);
  expect(signal?.aborted).toBe(true);
  await act(async () => { finishChat(response()); await chat; });
  expect(workspace.current.chat.messages).toEqual([]);
});

it("refreshes stale document state after a rejected deletion", async () => {
  const workspace = await mountWorkspace();
  vi.mocked(deleteDocument).mockRejectedValue(new Error("Wait for current job"));
  const refreshed = [{ ...documents[0], status: "processing" as const }, documents[1]];
  vi.mocked(listDocuments).mockResolvedValue(refreshed);
  await act(async () => { await workspace.current.operate(documents[0], "delete"); });
  await waitFor(() => expect(workspace.current.documents).toEqual(refreshed));
  expect(workspace.current.notice).toBe("Wait for current job");
});
