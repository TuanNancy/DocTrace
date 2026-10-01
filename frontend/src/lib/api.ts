import type { ChatSource, SSEEvent, UploadResponse } from "@/types";

function apiUrl(path: string) {
  const base = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/+$/, "");
  if (!base) throw new Error("Thiếu NEXT_PUBLIC_API_URL. Hãy cấu hình URL backend.");
  return `${base}${path}`;
}

function authorization(accessToken: string) {
  if (!accessToken) throw new Error("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
  return { Authorization: `Bearer ${accessToken}` };
}

async function checkResponse(response: Response) {
  if (response.ok) return;
  let message = `Yêu cầu thất bại (HTTP ${response.status}).`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail)) {
      message = body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join("; ") || message;
    }
  } catch {
    // A proxy may return HTML. Retain its status rather than displaying HTML.
  }
  throw new Error(message);
}

export async function uploadPDF(
  file: File,
  accessToken: string,
  signal?: AbortSignal
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(apiUrl("/api/upload"), {
    method: "POST",
    headers: authorization(accessToken),
    body: form,
    signal,
  });
  await checkResponse(response);
  return response.json();
}

export async function streamChat(
  query: string,
  docId: string,
  accessToken: string,
  signal?: AbortSignal
): Promise<Response> {
  const response = await fetch(apiUrl("/api/chat"), {
    method: "POST",
    headers: {
      ...authorization(accessToken),
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ query, doc_id: docId, language: "vi" }),
    signal,
  });
  await checkResponse(response);
  if (!response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
    throw new Error("Backend không trả về stream chat hợp lệ.");
  }
  return response;
}

function isSource(value: unknown): value is ChatSource {
  if (!value || typeof value !== "object") return false;
  const source = value as Record<string, unknown>;
  return typeof source.page === "number" && typeof source.source === "string" && typeof source.score === "number";
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
