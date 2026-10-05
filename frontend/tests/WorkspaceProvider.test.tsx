import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { WorkspaceProvider, useWorkspace } from "@/components/workspace/WorkspaceProvider";
import { deleteDocument, listDocuments, streamChat } from "@/lib/api";
import type { ChatSource, LibraryDocument } from "@/types";

const client = vi.hoisted(() => ({ auth: {
  getUser: vi.fn(), getSession: vi.fn(), onAuthStateChange: vi.fn(),
} }));
vi.mock("@/lib/supabase/client", () => ({ createClient: () => client }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  deleteDocument: vi.fn(), listDocuments: vi.fn(), streamChat: vi.fn(),
}));

const documents: LibraryDocument[] = ["a", "b"].map((id) => ({
  doc_id: id, name: `${id}.pdf`, status: "ready", size_bytes: 100, chunks_count: 1,
  warnings: [], error: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
}));
const source = (id: string): ChatSource => ({
  doc_id: id, chunk_id: `chunk-${id}`, citation_id: 1, page: 1, source: `${id}.pdf`, score: null,
});
const response = () => new Response('event: token\ndata: "Answer"\n\nevent: done\ndata: "[DONE]"\n\n');

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.test");
  const user = { id: "owner" };
  client.auth.getUser.mockResolvedValue({ data: { user } });
  client.auth.getSession.mockResolvedValue({ data: { session: { user, access_token: "token" } } });
  client.auth.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } });
  vi.mocked(listDocuments).mockResolvedValue(documents);
});

async function mountWorkspace() {
  const hook = renderHook(useWorkspace, {
    wrapper: ({ children }: PropsWithChildren) => <WorkspaceProvider>{children}</WorkspaceProvider>,
  });
  await waitFor(() => expect(hook.result.current.documents).toEqual(documents));
  return hook.result;
}

it("preserves the new selection, source and stream when an older deletion responds", async () => {
  let finishDelete!: (document: LibraryDocument) => void;
  let finishChat!: (response: Response) => void;
  vi.mocked(deleteDocument).mockReturnValue(new Promise((resolve) => { finishDelete = resolve; }));
  vi.mocked(streamChat).mockReturnValue(new Promise((resolve) => { finishChat = resolve; }));
  const workspace = await mountWorkspace();
  act(() => workspace.current.selectDocument(documents[0]));
  let deletion!: Promise<void>;
  act(() => { deletion = workspace.current.operate(documents[0], "delete"); });
  act(() => workspace.current.selectDocument(documents[1]));
  let chat!: Promise<void>;
  act(() => { chat = workspace.current.chat.submit("Question about B"); });
  act(() => workspace.current.selectSource(source("b")));
  const signal = vi.mocked(streamChat).mock.calls[0][3];

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
  let chat!: Promise<void>;
  act(() => { chat = workspace.current.chat.submit("Question about A"); });
  act(() => workspace.current.selectSource(source("a")));
  const signal = vi.mocked(streamChat).mock.calls[0][3];

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
