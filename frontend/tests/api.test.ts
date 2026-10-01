// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { streamChat, streamChatSSEParser, uploadPDF } from "@/lib/api";

describe("API transport", () => {
  beforeEach(() => vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.test/"));

  it("uploads multipart PDF with Bearer auth and a cancellation signal", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ doc_id: "a", chunks_count: 3 }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const file = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    await expect(uploadPDF(file, "test-token", controller.signal)).resolves.toMatchObject({ doc_id: "a" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/upload");
    expect(init.headers).toEqual({ Authorization: "Bearer test-token" });
    expect(init.body.get("file").name).toBe("a.pdf");
    expect(init.signal).toBe(controller.signal);
  });

  it("posts the backend chat contract and forwards abort", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { headers: { "Content-Type": "text/event-stream" } }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    await streamChat("Question", "doc-a", "test-token", controller.signal);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/chat");
    expect(JSON.parse(init.body)).toEqual({ query: "Question", doc_id: "doc-a", language: "vi" });
    expect(init.headers.Authorization).toBe("Bearer test-token");
    expect(init.signal).toBe(controller.signal);
  });

  it("surfaces HTTP auth errors instead of trying to parse SSE", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "Expired session" }, { status: 401 })));
    await expect(streamChat("q", "a", "expired")).rejects.toThrow("Expired session");
  });

  it("retains the HTTP status for proxy HTML errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>Bad Gateway</html>", { status: 502 })));
    await expect(streamChat("q", "a", "token")).rejects.toThrow("502");
  });

  it("rejects a non-SSE response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ status: "ok" })));
    await expect(streamChat("q", "a", "token")).rejects.toThrow("stream chat");
  });
});

describe("SSE decoding", () => {
  it("handles split UTF-8, CRLF, comments, sources, errors and done", async () => {
    const payload = ': ping\r\nevent: sources\r\ndata: [{"page":1,"source":"a.pdf","score":0.9}]\r\n\r\n'
      + 'event: token\r\ndata: "Tiếng Việt"\r\n\r\n'
      + 'event: error\r\ndata: {"message":"test error"}\r\n\r\n'
      + 'event: done\r\ndata: "[DONE]"\r\n\r\n';
    const bytes = new TextEncoder().encode(payload);
    const cancel = vi.fn();
    let index = 0;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) { controller.enqueue(bytes.slice(index, ++index)); },
      cancel,
    });
    const events = [];
    for await (const event of streamChatSSEParser(body)) events.push(event);
    expect(events).toEqual([
      { type: "sources", data: [{ page: 1, source: "a.pdf", score: 0.9 }] },
      { type: "token", data: "Tiếng Việt" },
      { type: "error", data: { message: "test error" } },
      { type: "done", data: "[DONE]" },
    ]);
    expect(cancel).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
  });

  it("reports truncation when the server closes without done", async () => {
    const body = new Response('event: token\ndata: "partial"\n\n').body!;
    const events = streamChatSSEParser(body);
    expect((await events.next()).value).toEqual({ type: "token", data: "partial" });
    await expect(events.next()).rejects.toThrow("bị ngắt");
    expect(body.locked).toBe(false);
  });

  it("cancels the reader when the consumer stops early", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode('event: token\ndata: "one"\n\n')); },
      cancel,
    });
    for await (const event of streamChatSSEParser(body)) {
      expect(event.type).toBe("token");
      break;
    }
    expect(cancel).toHaveBeenCalledOnce();
  });
});
