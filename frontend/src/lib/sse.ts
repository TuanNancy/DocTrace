import type { ChatSource, SSEEvent } from "@/types";

function isSource(value: unknown): value is ChatSource {
  if (!value || typeof value !== "object") return false;
  const source = value as Record<string, unknown>;
  return Number.isInteger(source.page) && Number(source.page) > 0
    && typeof source.source === "string"
    && (source.score === null || (typeof source.score === "number" && Number.isFinite(source.score)))
    && Number.isInteger(source.citation_id) && Number(source.citation_id) > 0
    && typeof source.chunk_id === "string" && source.chunk_id.length > 0
    && typeof source.doc_id === "string" && source.doc_id.length > 0;
}

function parseEvent(block: string): SSEEvent | null {
  let type = "message";
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") type = value;
    if (field === "data") dataLines.push(value);
  }
  if (!["sources", "token", "error", "done"].includes(type)) return null;
  const data: unknown = JSON.parse(dataLines.join("\n"));
  if (type === "token" && typeof data === "string") return { type, data };
  if (type === "done" && data === "[DONE]") return { type, data };
  if (type === "sources" && Array.isArray(data) && data.every(isSource)) return { type, data };
  if (type === "error" && data && typeof data === "object" && "message" in data && typeof data.message === "string") {
    return { type, data: { message: data.message } };
  }
  throw new Error(`Dữ liệu SSE không hợp lệ: ${type}.`);
}

/** Decode complete events across arbitrary network/UTF-8 boundaries; require explicit completion. */
export async function* streamChatSSEParser(body: ReadableStream<Uint8Array>): AsyncGenerator<SSEEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary: RegExpExecArray | null;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const block = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const event = parseEvent(block);
        if (!event) continue;
        yield event;
        if (event.type === "done") return;
      }
      if (buffer.length > 1024 * 1024) throw new Error("Sự kiện SSE quá lớn.");
      if (done) throw new Error("Kết nối chat bị ngắt trước khi hoàn tất. Vui lòng thử lại.");
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
