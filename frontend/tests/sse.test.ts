// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { streamChatSSEParser } from "@/lib/sse";
import type { ChatSource } from "@/types";

const source: ChatSource = {
  citation_id: 1, chunk_id: "chunk-a", doc_id: "doc-a", page: 1, source: "a.pdf", score: null,
};

describe("SSE decoding", () => {
  it("accepts document summary citations without a similarity score", async () => {
    const body = new Response(`event: sources\ndata: ${JSON.stringify([source])}\n\n`
      + 'event: done\ndata: "[DONE]"\n\n').body!;
    const events = [];
    for await (const event of streamChatSSEParser(body)) events.push(event);
    expect(events[0]).toEqual({ type: "sources", data: [source] });
  });

  it.each([
    { citation_id: undefined },
    { chunk_id: undefined },
    { doc_id: "" },
    { page: 0 },
    { score: "0.9" },
  ])("rejects unusable citation data %j and releases the reader", async (invalid) => {
    const body = new Response(`event: sources\ndata: ${JSON.stringify([{ ...source, ...invalid }])}\n\n`).body!;
    await expect(streamChatSSEParser(body).next()).rejects.toThrow("Dữ liệu SSE không hợp lệ: sources");
    expect(body.locked).toBe(false);
  });

  it("handles split UTF-8, CRLF, comments, sources, errors and done", async () => {
    const scoredSource = { ...source, score: 0.9 };
    const payload = `: ping\r\nevent: sources\r\ndata: ${JSON.stringify([scoredSource])}\r\n\r\n`
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
      { type: "sources", data: [scoredSource] },
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
