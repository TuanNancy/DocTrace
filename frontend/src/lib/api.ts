import type { ChatSource, LibraryDocument, SourceExcerpt } from "@/types";

function apiUrl(path: string) {
  const base = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/+$/, "");
  if (!base) throw new Error("Thiếu NEXT_PUBLIC_API_URL. Hãy cấu hình URL backend.");
  return `${base}${path}`;
}

function authorization(accessToken: string) {
  if (!accessToken) throw new Error("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
  return { Authorization: `Bearer ${accessToken}` };
}

function retryAfterSeconds(value: string | null): number | null {
  const raw = value?.trim() ?? "";
  const seconds = /^\d+$/.test(raw) ? Number(raw)
    : /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), /.test(raw) ? Math.ceil((Date.parse(raw) - Date.now()) / 1000)
    : NaN;
  return Number.isSafeInteger(seconds) && seconds >= 0 ? Math.max(1, seconds) : null;
}

async function checkResponse(response: Response) {
  if (response.ok) return;
  if (response.status === 429) {
    const wait = retryAfterSeconds(response.headers.get("Retry-After"));
    throw new Error(`Bạn gửi yêu cầu quá nhanh. Vui lòng thử lại sau${wait === null ? "" : ` ${wait} giây`}.`);
  }
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
  signal?: AbortSignal,
  onProgress?: (percent: number) => void
): Promise<LibraryDocument> {
  const form = new FormData();
  form.append("file", file.type ? file : new File([file], file.name, { type: "application/pdf" }));
  if (onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const abort = () => xhr.abort();
      const cleanup = () => signal?.removeEventListener("abort", abort);
      xhr.open("POST", apiUrl("/api/upload"));
      xhr.setRequestHeader("Authorization", authorization(accessToken).Authorization);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(Math.round(event.loaded * 100 / event.total));
      };
      xhr.onload = async () => {
        cleanup();
        try {
          const headers = new Headers();
          const retryAfter = xhr.getResponseHeader("Retry-After");
          if (retryAfter) headers.set("Retry-After", retryAfter);
          const response = new Response(xhr.responseText, { status: xhr.status, headers });
          await checkResponse(response);
          resolve(await response.json());
        } catch (error) { reject(error); }
      };
      xhr.onerror = () => { cleanup(); reject(new Error("Không thể tải PDF. Kiểm tra kết nối và thử lại.")); };
      xhr.onabort = () => { cleanup(); reject(new DOMException("Upload aborted", "AbortError")); };
      if (signal?.aborted) { reject(new DOMException("Upload aborted", "AbortError")); return; }
      signal?.addEventListener("abort", abort, { once: true });
      xhr.send(form);
    });
  }
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

async function libraryRequest<T>(path: string, accessToken: string, signal?: AbortSignal, method = "GET"): Promise<T> {
  const response = await fetch(apiUrl(`/api/documents${path}`), {
    method, headers: authorization(accessToken), signal, cache: "no-store",
  });
  await checkResponse(response);
  return response.json();
}

export async function listDocuments(accessToken: string, signal?: AbortSignal): Promise<LibraryDocument[]> {
  const documents: LibraryDocument[] = [];
  let hasMore = true;
  while (hasMore) {
    const page = await libraryRequest<{ items: LibraryDocument[]; has_more: boolean }>(
      `?limit=100&offset=${documents.length}`, accessToken, signal
    );
    documents.push(...page.items);
    hasMore = page.has_more && page.items.length > 0;
  }
  return Array.from(new Map(documents.map((document) => [document.doc_id, document])).values());
}

export const deleteDocument = (id: string, token: string) =>
  libraryRequest<LibraryDocument>(`/${encodeURIComponent(id)}`, token, undefined, "DELETE");

export const retryDocument = (id: string, token: string) =>
  libraryRequest<LibraryDocument>(`/${encodeURIComponent(id)}/retry`, token, undefined, "POST");

export const getSourceExcerpt = (source: ChatSource, token: string, signal?: AbortSignal) =>
  libraryRequest<SourceExcerpt>(`/${encodeURIComponent(source.doc_id)}/chunks/${encodeURIComponent(source.chunk_id)}`, token, signal);

const getDocumentFile = (id: string, token: string) =>
  libraryRequest<{ url: string; expires_in: number }>(`/${encodeURIComponent(id)}/file`, token);

export async function openDocumentFile(id: string, token: string, page = 1) {
  const tab = window.open("about:blank", "_blank");
  if (tab) tab.opener = null;
  try {
    const { url } = await getDocumentFile(id, token);
    if (tab) tab.location.href = `${url}#page=${Math.max(1, page)}`;
    else throw new Error("Hãy cho phép mở cửa sổ mới để xem PDF.");
  } catch (error) {
    tab?.close();
    throw error;
  }
}
