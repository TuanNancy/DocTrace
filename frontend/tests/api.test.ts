import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { streamChat, streamChatSSEParser, uploadPDF } from "../src/lib/api";

function byteStream(text: string, chunkSize = 1) {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < bytes.length; i += chunkSize) controller.enqueue(bytes.slice(i, i + chunkSize));
      controller.close();
    },
  });
}

async function collect(text: string, chunkSize?: number) {
  const events = [];
  for await (const event of streamChatSSEParser(byteStream(text, chunkSize))) events.push(event);
  return events;
}

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("SSE wire contract", () => {
  it.each([1, 7, 4096])("decodes split UTF-8 and multiple events with chunk size %i", async (chunkSize) => {
    const text = ': heartbeat\r\n\r\nevent: sources\r\ndata: [{"page":2,"source":"policy.pdf","score":0.9}]\r\n\r\n' +
      'event: token\r\ndata: "Tiếng Việt\\n😀"\r\n\r\nevent: done\r\ndata: "[DONE]"\r\n\r\n';
    expect(await collect(text, chunkSize)).toEqual([
      { type: "sources", data: [{ page: 2, source: "policy.pdf", score: 0.9 }] },
      { type: "token", data: "Tiếng Việt\n😀" },
      { type: "done", data: "[DONE]" },
    ]);
  });

  it("joins multiline JSON data, ignores unknown events, and forwards error events", async () => {
    expect(await collect('event: ping\ndata: not-json\n\nevent: error\ndata: {\ndata: "message": "Unavailable"}\n\nevent: done\ndata: "[DONE]"\n\n')).toEqual([
      { type: "error", data: { message: "Unavailable" } }, { type: "done", data: "[DONE]" },
    ]);
  });

  it.each(['event: token\ndata: 42\n\n', 'event: sources\ndata: [{"page":1}]\n\n', 'event: done\ndata: [DONE]\n\n'])("rejects malformed payload %s", async (payload) => {
    await expect(collect(payload)).rejects.toThrow();
  });

  it("reports truncated streams instead of silently completing", async () => {
    await expect(collect('event: token\ndata: "partial"\n\n')).rejects.toThrow("bị ngắt");
  });

  it("cancels and unlocks the stream when the consumer stops early", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode('event: token\ndata: "first"\n\n')); },
      cancel,
    });
    for await (const event of streamChatSSEParser(stream)) { expect(event.type).toBe("token"); break; }
    expect(cancel).toHaveBeenCalledOnce();
    expect(stream.locked).toBe(false);
  });
});

describe("HTTP client", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com/");
  });

  it("uploads multipart PDF with bearer auth and browser-generated boundary", async () => {
    fetchMock.mockResolvedValue(Response.json({ doc_id: "doc-1", chunks_count: 2 }));
    const file = new File(["pdf"], "test.pdf", { type: "application/pdf" });
    expect((await uploadPDF(file, "access-token")).doc_id).toBe("doc-1");
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.com/api/upload");
    expect(options.headers).toEqual({ Authorization: "Bearer access-token" });
    expect(options.body.get("file").name).toBe("test.pdf");
  });

  it("posts the chat contract with a cancellation signal", async () => {
    const response = new Response("stream", { headers: { "Content-Type": "text/event-stream; charset=utf-8" } });
    fetchMock.mockResolvedValue(response);
    const controller = new AbortController();
    expect(await streamChat("Câu hỏi?", "doc-1", "token", controller.signal)).toBe(response);
    expect(fetchMock).toHaveBeenCalledWith("https://api.example.com/api/chat", expect.objectContaining({
      method: "POST", signal: controller.signal,
      body: JSON.stringify({ query: "Câu hỏi?", doc_id: "doc-1", language: "vi" }),
      headers: expect.objectContaining({ Authorization: "Bearer token" }),
    }));
  });

  it.each([
    [Response.json({ detail: "Expired token" }, { status: 401 }), "Expired token"],
    [Response.json({ detail: [{ msg: "Required document" }] }, { status: 422 }), "Required document"],
    [new Response("<html>Proxy error</html>", { status: 502 }), "HTTP 502"],
  ])("surfaces backend and proxy errors", async (response, message) => {
    fetchMock.mockResolvedValue(response);
    await expect(streamChat("question", "doc", "token")).rejects.toThrow(message);
  });

  it("rejects a non-SSE successful response", async () => {
    fetchMock.mockResolvedValue(Response.json({ detail: "not a stream" }));
    await expect(streamChat("question", "doc", "token")).rejects.toThrow("stream chat");
  });

  it("fails before requesting if URL or access token is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "");
    await expect(streamChat("q", "doc", "token")).rejects.toThrow("NEXT_PUBLIC_API_URL");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com");
    await expect(streamChat("q", "doc", "")).rejects.toThrow("đăng nhập");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
