import { createRef } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatWindow, type ChatWindowHandle } from "@/components/ChatWindow";
import { streamChat } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  streamChat: vi.fn(),
}));
const streamMock = vi.mocked(streamChat);
const input = () => screen.getByLabelText("Câu hỏi của bạn");
function send(question = "Question A") {
  fireEvent.change(input(), { target: { value: question } });
  fireEvent.click(screen.getByRole("button", { name: "Gửi" }));
}
const response = () => new Response('event: token\ndata: "Answer A"\n\nevent: done\ndata: "[DONE]"\n\n');

beforeEach(() => { streamMock.mockReset(); });

it("renders summary sources without inventing a similarity percentage", async () => {
  streamMock.mockResolvedValue(new Response(
    'event: sources\ndata: [{"page":1,"source":"a.pdf","score":null}]\n\n'
    + 'event: token\ndata: "Summary A"\n\nevent: done\ndata: "[DONE]"\n\n'
  ));
  render(<ChatWindow docId="a" mock={false} accessToken="token" />);
  send("Tóm tắt PDF này");
  await screen.findByText("Summary A");
  expect(screen.getByText(/Nội dung tài liệu/)).toBeInTheDocument();
  expect(screen.queryByText(/Độ liên quan/)).not.toBeInTheDocument();
});

it("clears messages and draft when the selected document changes", async () => {
  streamMock.mockResolvedValue(response());
  const { rerender } = render(<ChatWindow docId="a" mock={false} accessToken="token" />);
  send();
  await screen.findByText("Answer A");
  await waitFor(() => expect(input()).toBeEnabled());
  fireEvent.change(input(), { target: { value: "Draft about A" } });
  rerender(<ChatWindow docId="b" mock={false} accessToken="token" />);
  expect(screen.queryByText("Answer A")).not.toBeInTheDocument();
  expect(screen.queryByText("Question A")).not.toBeInTheDocument();
  expect(input()).toHaveValue("");
  send("Question B");
  await waitFor(() => expect(streamMock).toHaveBeenLastCalledWith("Question B", "b", "token", expect.any(AbortSignal)));
});

it("clearing aborts the pending request and late results cannot unlock a newer request", async () => {
  let resolveOld!: (response: Response) => void;
  streamMock.mockReturnValueOnce(new Promise((r) => { resolveOld = r; }));
  streamMock.mockReturnValueOnce(new Promise(() => {}));
  const ref = createRef<ChatWindowHandle>();
  render(<ChatWindow ref={ref} docId="a" mock={false} accessToken="token" />);
  send();
  await waitFor(() => expect(streamMock).toHaveBeenCalledOnce());
  const signal = streamMock.mock.calls[0][3];
  act(() => ref.current!.clearMessages());
  expect(signal?.aborted).toBe(true);
  expect(input()).toBeEnabled();
  send("New question");
  await waitFor(() => expect(streamMock).toHaveBeenCalledTimes(2));
  await act(async () => resolveOld(response()));
  expect(screen.queryByText("Answer A")).not.toBeInTheDocument();
  expect(input()).toBeDisabled();
});

it("aborts a pending stream when changing document or unmounting", async () => {
  streamMock.mockReturnValue(new Promise(() => {}));
  const { rerender, unmount } = render(<ChatWindow docId="a" mock={false} accessToken="token" />);
  send();
  await waitFor(() => expect(streamMock).toHaveBeenCalledOnce());
  const firstSignal = streamMock.mock.calls[0][3];
  rerender(<ChatWindow docId="b" mock={false} accessToken="token" />);
  expect(firstSignal?.aborted).toBe(true);
  expect(input()).toBeEnabled();
  send("Question B");
  await waitFor(() => expect(streamMock).toHaveBeenCalledTimes(2));
  const secondSignal = streamMock.mock.calls[1][3];
  unmount();
  expect(secondSignal?.aborted).toBe(true);
});

it("stops demo output when chat is cleared", async () => {
  vi.useFakeTimers();
  try {
    const ref = createRef<ChatWindowHandle>();
    render(<ChatWindow ref={ref} docId={null} mock />);
    send();
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    act(() => ref.current!.clearMessages());
    expect(input()).toBeEnabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.queryByText("Question A")).not.toBeInTheDocument();
    expect(screen.getByText("Bạn muốn tìm hiểu điều gì?")).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});
