import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatWindow } from "@/components/ChatWindow";
import { useChatSession } from "@/lib/use-chat-session";
import { ApiError, deleteConversation, getConversation, listConversations, streamChat } from "@/lib/api";
import type { Transcript } from "@/types";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
  listConversations: vi.fn(),
  streamChat: vi.fn(),
}));
const streamMock = vi.mocked(streamChat);
const listMock = vi.mocked(listConversations);
const getMock = vi.mocked(getConversation);
const deleteMock = vi.mocked(deleteConversation);
const input = () => screen.getByLabelText("Câu hỏi của bạn");

function submit(question = "Question A") {
  fireEvent.change(input(), { target: { value: question } });
  fireEvent.click(screen.getByRole("button", { name: "Gửi" }));
}

async function send(question = "Question A") {
  // The transcript restore effect briefly disables the composer.
  await waitFor(() => expect(input()).toBeEnabled());
  submit(question);
}

const response = () => new Response('event: token\ndata: "Answer A"\n\nevent: done\ndata: "[DONE]"\n\n');

// The workspace owns the session; exercise that same ownership in component tests.
function ChatHarness(props: Parameters<typeof useChatSession>[0]) {
  const session = useChatSession(props);
  return <>
    <button onClick={session.clearMessages}>Clear chat</button>
    <button onClick={() => void session.newChat()}>New chat</button>
    <button onClick={() => void session.submit("Direct question")}>Submit directly</button>
    <span data-testid="conversation-id">{session.conversationId}</span>
    <ChatWindow docId={props.docId} mock={props.mock} session={session} onSelectSource={() => undefined} />
  </>;
}

const savedTranscript: Transcript = {
  id: "conversation-a", workspace_id: "workspace-a", doc_id: "a",
  created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:01:00Z",
  messages: [
    {
      id: "message-a", role: "user", content: "Câu hỏi cũ", sources: [],
      index_id: null, status: "complete",
      created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:00:00Z",
    },
    {
      id: "message-b", role: "assistant", content: "Câu trả lời cũ [1]",
      index_id: "old-index", status: "complete",
      created_at: "2026-10-26T00:00:01Z", updated_at: "2026-10-26T00:00:01Z",
      sources: [{
        citation_id: 1, chunk_id: "old-chunk", doc_id: "a", page: 1,
        source: "a.pdf", score: null, stale: true,
      }],
    },
  ],
};

beforeEach(() => {
  streamMock.mockReset();
  listMock.mockReset().mockResolvedValue([]);
  getMock.mockReset();
  deleteMock.mockReset().mockResolvedValue(undefined);
});

it("renders summary sources without inventing a similarity percentage", async () => {
  streamMock.mockResolvedValue(new Response(
    'event: sources\ndata: [{"citation_id":1,"chunk_id":"chunk-a","doc_id":"a","page":1,"source":"a.pdf","score":null}]\n\n'
    + 'event: token\ndata: "Summary A"\n\nevent: done\ndata: "[DONE]"\n\n'
  ));
  render(<ChatHarness docId="a" workspaceId="workspace-a" mock={false} accessToken="token" />);
  await send("Tóm tắt PDF này");
  await screen.findByText("Summary A");
  expect(screen.getByText(/Nội dung tài liệu/)).toBeInTheDocument();
  expect(screen.queryByText(/Độ liên quan/)).not.toBeInTheDocument();
});

it("restores the latest transcript, disables stale citations and deletes it for a new chat", async () => {
  listMock.mockResolvedValue([{
    id: "conversation-a", doc_id: "a", message_count: 2,
    created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:01:00Z",
  }]);
  getMock.mockResolvedValue(savedTranscript);
  render(<ChatHarness docId="a" workspaceId="workspace-a" mock={false} accessToken="token" />);

  await screen.findByText(/Câu trả lời cũ/);
  expect(listMock).toHaveBeenCalledWith("token", "workspace-a", "a", expect.any(AbortSignal));
  expect(getMock).toHaveBeenCalledWith(
    "conversation-a", "token", "workspace-a", expect.any(AbortSignal),
  );
  // A stale generation is never fetched again: the citation renders as plain text
  // and the source card stops being clickable.
  expect(screen.queryByRole("button", { name: "Xem nguồn 1, trang 1" })).not.toBeInTheDocument();
  expect(screen.getByText("a.pdf").closest("button")).toBeDisabled();
  expect(screen.getByText(/Nguồn trích dẫn không còn khả dụng/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(
    "conversation-a", "token", "workspace-a", expect.any(AbortSignal),
  ));
  expect(screen.queryByText(/Câu trả lời cũ/)).not.toBeInTheDocument();
});

it("does not resurrect a deleted transcript after a new chat", async () => {
  listMock.mockResolvedValue([{
    id: "conversation-a", doc_id: "a", message_count: 2,
    created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:01:00Z",
  }]);
  getMock.mockResolvedValue(savedTranscript);
  render(<ChatHarness docId="a" workspaceId="workspace-a" mock={false} accessToken="token" />);
  await screen.findByText(/Câu trả lời cũ/);
  const calls = listMock.mock.calls.length;

  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  await waitFor(() => expect(deleteMock).toHaveBeenCalledOnce());
  expect(listMock).toHaveBeenCalledTimes(calls);
});

it("deletes the latest saved transcript when new chat is clicked during restore", async () => {
  listMock
    .mockReturnValueOnce(new Promise(() => {}))
    .mockResolvedValueOnce([{
      id: "conversation-a", doc_id: "a", message_count: 2,
      created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:01:00Z",
    }]);
  render(<ChatHarness docId="a" workspaceId="workspace-a" mock={false} accessToken="token" />);
  await waitFor(() => expect(listMock).toHaveBeenCalledOnce());

  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(
    "conversation-a", "token", "workspace-a", expect.any(AbortSignal),
  ));
  expect(listMock).toHaveBeenLastCalledWith("token", "workspace-a", "a", expect.any(AbortSignal));
});

it("blocks submissions and duplicate resets until deletion succeeds", async () => {
  listMock.mockResolvedValue([{ ...savedTranscript, message_count: 2 }]);
  getMock.mockResolvedValue(savedTranscript);
  let finish!: () => void;
  deleteMock.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await screen.findByText(/Câu trả lời cũ/);
  fireEvent.change(input(), { target: { value: "Draft" } });
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));

  expect(input()).toBeDisabled();
  expect(screen.getByRole("button", { name: "Gửi" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("Đang xóa hội thoại cũ");
  fireEvent.click(screen.getByRole("button", { name: "Submit directly" }));
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  expect(deleteMock).toHaveBeenCalledOnce();
  expect(streamMock).not.toHaveBeenCalled();
  await act(async () => finish());
  expect(input()).toBeEnabled();
  expect(input()).toHaveValue("");
  expect(screen.queryByText(/Câu trả lời cũ/)).not.toBeInTheDocument();
});

it("keeps the transcript and draft when reset fails and allows a retry", async () => {
  listMock.mockResolvedValue([{ ...savedTranscript, message_count: 2 }]);
  getMock.mockResolvedValue(savedTranscript);
  deleteMock.mockRejectedValueOnce(new Error("Delete unavailable"));
  render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await screen.findByText(/Câu trả lời cũ/);
  fireEvent.change(input(), { target: { value: "Keep my draft" } });
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Delete unavailable");
  expect(screen.getByText(/Câu trả lời cũ/)).toBeInTheDocument();
  expect(input()).toHaveValue("Keep my draft");
  expect(input()).toBeEnabled();
  deleteMock.mockRejectedValueOnce(new ApiError("Already deleted", 404));
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  await waitFor(() => expect(screen.queryByText(/Câu trả lời cũ/)).not.toBeInTheDocument());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("ignores a reset lookup after switching workspace before it resolves", async () => {
  let finish!: (items: Awaited<ReturnType<typeof listConversations>>) => void;
  listMock.mockResolvedValueOnce([]).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
  const { rerender } = render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await waitFor(() => expect(input()).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  const signal = listMock.mock.calls[1][3];
  expect(input()).toBeDisabled();
  rerender(<ChatHarness docId="b" workspaceId="workspace-b" accessToken="token" />);
  await waitFor(() => expect(input()).toBeEnabled());
  expect(signal?.aborted).toBe(true);
  await act(async () => finish([{ ...savedTranscript, message_count: 2 }]));
  expect(deleteMock).not.toHaveBeenCalled();
  expect(screen.getByTestId("conversation-id")).toBeEmptyDOMElement();
});

it.each(["success", "failure"])("ignores a late reset %s after a new selection", async (outcome) => {
  listMock.mockResolvedValueOnce([{ ...savedTranscript, message_count: 2 }]);
  getMock.mockResolvedValueOnce(savedTranscript);
  let finish!: () => void;
  let fail!: (reason: Error) => void;
  deleteMock.mockReturnValueOnce(new Promise((resolve, reject) => { finish = resolve; fail = reject; }));
  const { rerender } = render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await screen.findByText(/Câu trả lời cũ/);
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  const signal = deleteMock.mock.calls[0][3];
  rerender(<ChatHarness docId="b" workspaceId="workspace-b" accessToken="token" />);
  await waitFor(() => expect(input()).toBeEnabled());
  fireEvent.change(input(), { target: { value: "Draft B" } });
  expect(signal?.aborted).toBe(true);
  await act(async () => { if (outcome === "success") finish(); else fail(new Error("Old error")); });
  expect(input()).toHaveValue("Draft B");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("clears messages and draft when the selected document changes", async () => {
  streamMock.mockResolvedValue(response());
  const { rerender } = render(<ChatHarness docId="a" workspaceId="workspace-a" mock={false} accessToken="token" />);
  await send();
  await screen.findByText("Answer A");
  await waitFor(() => expect(input()).toBeEnabled());
  fireEvent.change(input(), { target: { value: "Draft about A" } });
  rerender(<ChatHarness docId="b" workspaceId="workspace-a" mock={false} accessToken="token" />);
  expect(screen.queryByText("Answer A")).not.toBeInTheDocument();
  expect(screen.queryByText("Question A")).not.toBeInTheDocument();
  expect(input()).toHaveValue("");
  await send("Question B");
  await waitFor(() => expect(streamMock).toHaveBeenLastCalledWith("Question B", "b", "token", "workspace-a", expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i), expect.any(AbortSignal)));
});

it("clearing aborts the pending request and late results cannot unlock a newer request", async () => {
  let resolveOld!: (response: Response) => void;
  streamMock.mockReturnValueOnce(new Promise((r) => { resolveOld = r; }));
  streamMock.mockReturnValueOnce(new Promise(() => {}));
  render(<ChatHarness docId="a" workspaceId="workspace-a" mock={false} accessToken="token" />);
  await send();
  await waitFor(() => expect(streamMock).toHaveBeenCalledOnce());
  const signal = streamMock.mock.calls[0][5];
  fireEvent.click(screen.getByRole("button", { name: "Clear chat" }));
  expect(signal?.aborted).toBe(true);
  expect(input()).toBeEnabled();
  await send("New question");
  await waitFor(() => expect(streamMock).toHaveBeenCalledTimes(2));
  await act(async () => resolveOld(new Response(response().body, {
    headers: { "X-Conversation-Id": "old-conversation" },
  })));
  expect(screen.queryByText("Answer A")).not.toBeInTheDocument();
  expect(screen.getByTestId("conversation-id")).toBeEmptyDOMElement();
  expect(input()).toBeDisabled();
});

it("aborts a pending stream when changing document or unmounting", async () => {
  streamMock.mockReturnValue(new Promise(() => {}));
  const { rerender, unmount } = render(<ChatHarness docId="a" workspaceId="workspace-a" mock={false} accessToken="token" />);
  await send();
  await waitFor(() => expect(streamMock).toHaveBeenCalledOnce());
  const firstSignal = streamMock.mock.calls[0][5];
  rerender(<ChatHarness docId="b" workspaceId="workspace-a" mock={false} accessToken="token" />);
  expect(firstSignal?.aborted).toBe(true);
  await send("Question B");
  await waitFor(() => expect(streamMock).toHaveBeenCalledTimes(2));
  const secondSignal = streamMock.mock.calls[1][5];
  unmount();
  expect(secondSignal?.aborted).toBe(true);
});

it("aborts a pending stream when the workspace changes", async () => {
  streamMock.mockReturnValue(new Promise(() => {}));
  const { rerender } = render(<ChatHarness docId="a" workspaceId="workspace-a" mock={false} accessToken="token" />);
  await send();
  await waitFor(() => expect(streamMock).toHaveBeenCalledOnce());
  const signal = streamMock.mock.calls[0][5];
  rerender(<ChatHarness docId="a" workspaceId="workspace-b" mock={false} accessToken="token" />);
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByText("Question A")).not.toBeInTheDocument();
  expect(input()).toHaveValue("");
  await send("Question B");
  await waitFor(() => expect(streamMock).toHaveBeenLastCalledWith(
    "Question B", "a", "token", "workspace-b",
    expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i),
    expect.any(AbortSignal),
  ));
});

it("stops demo output when chat is cleared", async () => {
  vi.useFakeTimers();
  try {
    render(<ChatHarness docId={null} workspaceId="workspace-a" mock />);
    submit();
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    fireEvent.click(screen.getByRole("button", { name: "Clear chat" }));
    expect(input()).toBeEnabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.queryByText("Question A")).not.toBeInTheDocument();
    expect(screen.getByText("Bạn muốn tìm hiểu điều gì?")).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

it("reuses the logical request id after a lost response and restores the completed answer", async () => {
  streamMock.mockRejectedValueOnce(new TypeError("Network unavailable"))
    .mockRejectedValueOnce(new ApiError("Completed", 409, "request_completed", { conversation_id: savedTranscript.id }));
  getMock.mockResolvedValue(savedTranscript);
  render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await send("Câu hỏi cũ");
  await screen.findByRole("alert");
  expect(streamMock).toHaveBeenCalledOnce(); // No automatic retry of uncertain admission.
  fireEvent.click(screen.getByRole("button", { name: "Kiểm tra / thử lại" }));
  await screen.findByText(/Câu trả lời cũ/);
  expect(streamMock.mock.calls[1][4]).toBe(streamMock.mock.calls[0][4]);
  expect(screen.getAllByText("Câu hỏi cũ")).toHaveLength(1);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Kiểm tra / thử lại" })).not.toBeInTheDocument();
});

it("manual resubmission of the same uncertain question keeps the request id", async () => {
  streamMock.mockRejectedValueOnce(new Error("Network failed")).mockResolvedValueOnce(response());
  render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await send();
  await screen.findByRole("alert");
  await send();
  await screen.findByText("Answer A");
  expect(streamMock.mock.calls[1][4]).toBe(streamMock.mock.calls[0][4]);
  expect(screen.getAllByText("Question A")).toHaveLength(1);
});

it("an in-progress duplicate keeps its id and a failed duplicate requires an explicit new charged request", async () => {
  streamMock.mockRejectedValueOnce(new TypeError("Connection lost"))
    .mockRejectedValueOnce(new ApiError("Still running", 409, "request_in_progress", { conversation_id: savedTranscript.id }))
    .mockRejectedValueOnce(new ApiError("Request failed", 409, "request_failed", { retryable: true }))
    .mockResolvedValueOnce(response());
  render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await send();
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Kiểm tra / thử lại" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Still running");
  expect(streamMock.mock.calls[1][4]).toBe(streamMock.mock.calls[0][4]);
  fireEvent.click(screen.getByRole("button", { name: "Kiểm tra / thử lại" }));
  await screen.findByRole("button", { name: "Gửi lại (tính lượt mới)" });
  expect(streamMock.mock.calls[2][4]).toBe(streamMock.mock.calls[0][4]);
  expect(streamMock).toHaveBeenCalledTimes(3);
  fireEvent.click(screen.getByRole("button", { name: "Gửi lại (tính lượt mới)" }));
  await screen.findByText("Answer A");
  expect(streamMock.mock.calls[3][4]).not.toBe(streamMock.mock.calls[0][4]);
});

it("keeps the id when a completed answer cannot yet be restored", async () => {
  streamMock.mockRejectedValue(new ApiError("Completed", 409, "request_completed", { conversation_id: savedTranscript.id }));
  getMock.mockRejectedValueOnce(new Error("Transcript offline")).mockResolvedValueOnce(savedTranscript);
  render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await send();
  expect(await screen.findByRole("alert")).toHaveTextContent("Transcript offline");
  fireEvent.click(screen.getByRole("button", { name: "Kiểm tra / thử lại" }));
  await screen.findByText(/Câu trả lời cũ/);
  expect(streamMock.mock.calls[1][4]).toBe(streamMock.mock.calls[0][4]);
});

it.each(["missing id", "deleted"])("does not resubmit a completed request with a %s transcript", async (kind) => {
  streamMock.mockRejectedValue(new ApiError("Completed", 409, "request_completed",
    kind === "deleted" ? { conversation_id: savedTranscript.id } : {}));
  getMock.mockRejectedValue(new ApiError("Deleted", 404));
  render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await send();
  expect(await screen.findByRole("alert")).toHaveTextContent("hội thoại không còn khả dụng");
  expect(streamMock).toHaveBeenCalledOnce();
  expect(screen.queryByRole("button", { name: "Kiểm tra / thử lại" })).not.toBeInTheDocument();
});

it("rejects recovery for a different document", async () => {
  streamMock.mockRejectedValue(new ApiError("Completed", 409, "request_completed", { conversation_id: savedTranscript.id }));
  getMock.mockResolvedValue({ ...savedTranscript, doc_id: "other" });
  render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await send();
  expect(await screen.findByRole("alert")).toHaveTextContent("không khớp tài liệu");
  expect(screen.queryByText(/Câu trả lời cũ/)).not.toBeInTheDocument();
});

it("discards late recovery after switching workspace and allocates a fresh request there", async () => {
  streamMock.mockRejectedValueOnce(new ApiError("Completed", 409, "request_completed", { conversation_id: savedTranscript.id }))
    .mockResolvedValueOnce(response());
  let finish!: (transcript: Transcript) => void;
  getMock.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
  const { rerender } = render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await send();
  await waitFor(() => expect(getMock).toHaveBeenCalledOnce());
  const signal = getMock.mock.calls[0][3];
  rerender(<ChatHarness docId="b" workspaceId="workspace-b" accessToken="token" />);
  await waitFor(() => expect(input()).toBeEnabled());
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(savedTranscript));
  expect(screen.queryByText(/Câu trả lời cũ/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Kiểm tra / thử lại" })).not.toBeInTheDocument();
  await send();
  await screen.findByText("Answer A");
  expect(streamMock.mock.calls[1][4]).not.toBe(streamMock.mock.calls[0][4]);
});

it("EOF without done keeps the id for recovery, while a successful new question gets a fresh id", async () => {
  streamMock.mockResolvedValueOnce(new Response('event: token\ndata: "Partial"\n\n'))
    .mockRejectedValueOnce(new ApiError("Completed", 409, "request_completed", { conversation_id: savedTranscript.id }))
    .mockResolvedValueOnce(response());
  getMock.mockResolvedValue(savedTranscript);
  render(<ChatHarness docId="a" workspaceId="workspace-a" accessToken="token" />);
  await send();
  expect(await screen.findByRole("alert")).toHaveTextContent("Kết nối chat bị ngắt");
  fireEvent.click(screen.getByRole("button", { name: "Kiểm tra / thử lại" }));
  await screen.findByText(/Câu trả lời cũ/);
  expect(streamMock.mock.calls[1][4]).toBe(streamMock.mock.calls[0][4]);
  await send("Another question");
  await screen.findByText("Answer A");
  expect(streamMock.mock.calls[2][4]).not.toBe(streamMock.mock.calls[0][4]);
});

it("keeps recovery across token renewal but clears it for a different authenticated user", async () => {
  streamMock.mockRejectedValue(new Error("Connection lost"));
  const { rerender } = render(<ChatHarness docId="a" workspaceId="workspace-a" userId="owner" accessToken="token" />);
  await send();
  await screen.findByRole("alert");
  rerender(<ChatHarness docId="a" workspaceId="workspace-a" userId="owner" accessToken="renewed-token" />);
  fireEvent.click(screen.getByRole("button", { name: "Kiểm tra / thử lại" }));
  await waitFor(() => expect(streamMock).toHaveBeenCalledTimes(2));
  expect(streamMock.mock.calls[1][2]).toBe("renewed-token");
  expect(streamMock.mock.calls[1][4]).toBe(streamMock.mock.calls[0][4]);
  rerender(<ChatHarness docId="a" workspaceId="workspace-a" userId="other" accessToken="other-token" />);
  await waitFor(() => expect(input()).toBeEnabled());
  expect(screen.queryByRole("button", { name: "Kiểm tra / thử lại" })).not.toBeInTheDocument();
  expect(screen.queryByText("Question A")).not.toBeInTheDocument();
  await send();
  await screen.findByRole("alert");
  expect(streamMock.mock.calls[2][4]).not.toBe(streamMock.mock.calls[0][4]);
});
