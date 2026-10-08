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

  it("supplies the PDF MIME type when the browser leaves it empty", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ doc_id: "a", chunks_count: 0, status: "queued" }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    await uploadPDF(new File(["%PDF-1.4"], "a.pdf"), "token");
    expect(fetchMock.mock.calls[0][1].body.get("file").type).toBe("application/pdf");
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

  it("shows the Retry-After wait for fetch without opening SSE", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "Too many requests" }, {
      status: 429, headers: { "Retry-After": "12" },
    })));
    await expect(streamChat("q", "a", "token")).rejects.toThrow("thử lại sau 12 giây");
  });

  it.each([null, "nonsense", "-1", "1.5"])("has a friendly fallback for invalid Retry-After %s", async (value) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", {
      status: 429, headers: value === null ? {} : { "Retry-After": value },
    })));
    await expect(streamChat("q", "a", "token")).rejects.toThrow("Vui lòng thử lại sau.");
  });

  it("does not duplicate a wait message from the API", async () => {
    const detail = "Bạn gửi yêu cầu quá nhanh. Vui lòng thử lại sau 12 giây.";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail }, {
      status: 429, headers: { "Retry-After": "12" },
    })));
    await expect(streamChat("q", "a", "token")).rejects.toThrow(new Error(detail));
  });

  it("accepts HTTP-date Retry-After", async () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("Thu, 08 Oct 2026 10:00:00 GMT"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", {
      status: 429, headers: { "Retry-After": "Thu, 08 Oct 2026 10:00:12 GMT" },
    })));
    await expect(streamChat("q", "a", "token")).rejects.toThrow("thử lại sau 12 giây");
  });

  it("preserves Retry-After for progress uploads through XHR", async () => {
    const xhr = {
      open: vi.fn(), setRequestHeader: vi.fn(), upload: {}, status: 429,
      responseText: JSON.stringify({ detail: "Too many requests" }),
      getResponseHeader: vi.fn((name: string) => name.toLowerCase() === "retry-after" ? "17" : null),
      onload: () => {}, send() { this.onload(); },
    };
    vi.stubGlobal("XMLHttpRequest", vi.fn(() => xhr));
    await expect(uploadPDF(new File(["%PDF"], "a.pdf"), "token", undefined, vi.fn()))
      .rejects.toThrow("thử lại sau 17 giây");
  });
});

describe("SSE decoding", () => {
  it("accepts document summary citations without a similarity score", async () => {
    const body = new Response('event: sources\ndata: [{"page":1,"source":"a.pdf","score":null}]\n\n'
      + 'event: done\ndata: "[DONE]"\n\n').body!;
    const events = [];
    for await (const event of streamChatSSEParser(body)) events.push(event);
    expect(events[0]).toEqual({ type: "sources", data: [{ page: 1, source: "a.pdf", score: null }] });
  });

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
