import type {
  ChatSource, ConversationSummary, LibraryDocument, SourceExcerpt, Transcript,
  UsageSummary, Workspace,
} from "@/types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code: string | null = null) {
    super(message);
    this.name = "ApiError";
  }
}

function apiUrl(path: string) {
  const base = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/+$/, "");
  if (!base) throw new Error("Thiếu NEXT_PUBLIC_API_URL. Hãy cấu hình URL backend.");
  return `${base}${path}`;
}

function authorization(accessToken: string) {
  if (!accessToken) throw new Error("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
  return { Authorization: `Bearer ${accessToken}` };
}

/** Every workspace-scoped request selects a tenant; the server re-checks membership. */
function workspaceAuthorization(accessToken: string, workspaceId: string) {
  if (!workspaceId) throw new Error("Chưa chọn không gian làm việc. Vui lòng tải lại trang.");
  return { ...authorization(accessToken), "X-Workspace-Id": workspaceId };
}

function retryAfterSeconds(value: string | null): number | null {
  const raw = value?.trim() ?? "";
  const seconds = /^\d+$/.test(raw) ? Number(raw)
    : /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), /.test(raw) ? Math.ceil((Date.parse(raw) - Date.now()) / 1000)
    : NaN;
  return Number.isSafeInteger(seconds) && seconds >= 0 ? Math.max(1, seconds) : null;
}

function errorDetail(body: unknown): { message: string | null; code: string | null } {
  if (!body || typeof body !== "object") return { message: null, code: null };
  const record = body as Record<string, unknown>;
  const detail = record.detail;
  if (typeof detail === "string") {
    return { message: detail, code: typeof record.code === "string" ? record.code : null };
  }
  if (Array.isArray(detail)) {
    const message = detail.map((item) => {
      if (!item || typeof item !== "object") return null;
      const msg = (item as Record<string, unknown>).msg;
      return typeof msg === "string" ? msg : null;
    }).filter(Boolean).join("; ");
    return { message: message || null, code: null };
  }
  if (detail && typeof detail === "object") {
    const value = detail as Record<string, unknown>;
    return {
      message: typeof value.message === "string" ? value.message : null,
      code: typeof value.code === "string" ? value.code : null,
    };
  }
  return { message: null, code: typeof record.code === "string" ? record.code : null };
}

/** Render the UTC quota reset boundary the backend reports, if present and valid. */
function quotaResetDate(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as Record<string, unknown>).detail;
  if (!detail || typeof detail !== "object") return null;
  const value = (detail as Record<string, unknown>).reset_at;
  if (typeof value !== "string") return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const day = String(date.getUTCDate()).padStart(2, "0");
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  return `${day}/${month}/${date.getUTCFullYear()}`;
}

async function checkResponse(response: Response) {
  if (response.ok) return;
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // A proxy may return HTML. Retain its status rather than displaying HTML.
  }
  const { message, code } = errorDetail(body);
  if (response.status === 429) {
    if (code === "quota_exceeded") {
      // Monthly quota is not a burst limit: show when the plan resets rather
      // than a Retry-After wait that could be weeks long.
      const reset = quotaResetDate(body);
      const reason = message ?? "Đã hết hạn mức sử dụng của gói hiện tại.";
      throw new ApiError(
        reset ? `${reason} Hạn mức sẽ được đặt lại vào ${reset}.` : reason,
        response.status, code,
      );
    }
    const wait = retryAfterSeconds(response.headers.get("Retry-After"));
    throw new ApiError(
      `Bạn gửi yêu cầu quá nhanh. Vui lòng thử lại sau${wait === null ? "" : ` ${wait} giây`}.`,
      response.status, code,
    );
  }
  throw new ApiError(message ?? `Yêu cầu thất bại (HTTP ${response.status}).`, response.status, code);
}

export async function listWorkspaces(accessToken: string, signal?: AbortSignal): Promise<Workspace[]> {
  const response = await fetch(apiUrl("/api/workspaces"), {
    headers: authorization(accessToken), signal, cache: "no-store",
  });
  await checkResponse(response);
  const body = await response.json() as { items?: Workspace[] };
  return Array.isArray(body.items) ? body.items : [];
}

export async function uploadPDF(
  file: File,
  accessToken: string,
  workspaceId: string,
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
      const headers = workspaceAuthorization(accessToken, workspaceId);
      xhr.setRequestHeader("Authorization", headers.Authorization);
      xhr.setRequestHeader("X-Workspace-Id", headers["X-Workspace-Id"]);
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
    headers: workspaceAuthorization(accessToken, workspaceId),
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
  workspaceId: string,
  requestId: string,
  signal?: AbortSignal
): Promise<Response> {
  const response = await fetch(apiUrl("/api/chat"), {
    method: "POST",
    headers: {
      ...workspaceAuthorization(accessToken, workspaceId),
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ query, doc_id: docId, language: "vi", request_id: requestId }),
    signal,
  });
  await checkResponse(response);
  if (!response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
    throw new Error("Backend không trả về stream chat hợp lệ.");
  }
  return response;
}

async function workspaceRequest<T>(
  path: string,
  accessToken: string,
  workspaceId: string,
  signal?: AbortSignal,
  method = "GET",
): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method, headers: workspaceAuthorization(accessToken, workspaceId),
    signal, cache: "no-store",
  });
  await checkResponse(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function listConversations(
  accessToken: string,
  workspaceId: string,
  docId?: string,
  signal?: AbortSignal,
): Promise<ConversationSummary[]> {
  const search = docId ? `?doc_id=${encodeURIComponent(docId)}` : "";
  const body = await workspaceRequest<{ items?: ConversationSummary[] }>(
    `/api/conversations${search}`, accessToken, workspaceId, signal,
  );
  return Array.isArray(body.items) ? body.items : [];
}

export const getConversation = (
  id: string,
  accessToken: string,
  workspaceId: string,
  signal?: AbortSignal,
) => workspaceRequest<Transcript>(
  `/api/conversations/${encodeURIComponent(id)}`, accessToken, workspaceId, signal,
);

export const deleteConversation = async (
  id: string,
  accessToken: string,
  workspaceId: string,
  signal?: AbortSignal,
) => {
  await workspaceRequest<undefined>(
    `/api/conversations/${encodeURIComponent(id)}`, accessToken, workspaceId,
    signal, "DELETE",
  );
};

export const getUsage = (accessToken: string, workspaceId: string, signal?: AbortSignal) =>
  workspaceRequest<UsageSummary>("/api/usage", accessToken, workspaceId, signal);

async function libraryRequest<T>(
  path: string,
  accessToken: string,
  workspaceId: string,
  signal?: AbortSignal,
  method = "GET",
): Promise<T> {
  const response = await fetch(apiUrl(`/api/documents${path}`), {
    method, headers: workspaceAuthorization(accessToken, workspaceId), signal, cache: "no-store",
  });
  await checkResponse(response);
  return response.json();
}

export async function listDocuments(
  accessToken: string,
  workspaceId: string,
  signal?: AbortSignal,
): Promise<LibraryDocument[]> {
  const documents: LibraryDocument[] = [];
  let hasMore = true;
  while (hasMore) {
    const page = await libraryRequest<{ items: LibraryDocument[]; has_more: boolean }>(
      `?limit=100&offset=${documents.length}`, accessToken, workspaceId, signal,
    );
    documents.push(...page.items);
    hasMore = page.has_more && page.items.length > 0;
  }
  return Array.from(new Map(documents.map((document) => [document.doc_id, document])).values());
}

export const deleteDocument = (id: string, token: string, workspaceId: string) =>
  libraryRequest<LibraryDocument>(`/${encodeURIComponent(id)}`, token, workspaceId, undefined, "DELETE");

export const retryDocument = (id: string, token: string, workspaceId: string) =>
  libraryRequest<LibraryDocument>(`/${encodeURIComponent(id)}/retry`, token, workspaceId, undefined, "POST");

export const getSourceExcerpt = (
  source: ChatSource,
  token: string,
  workspaceId: string,
  signal?: AbortSignal,
) => libraryRequest<SourceExcerpt>(
  `/${encodeURIComponent(source.doc_id)}/chunks/${encodeURIComponent(source.chunk_id)}`,
  token, workspaceId, signal,
);

const getDocumentFile = (id: string, token: string, workspaceId: string) =>
  libraryRequest<{ url: string; expires_in: number }>(`/${encodeURIComponent(id)}/file`, token, workspaceId);

export async function openDocumentFile(id: string, token: string, workspaceId: string, page = 1) {
  const tab = window.open("about:blank", "_blank");
  if (tab) tab.opener = null;
  try {
    const { url } = await getDocumentFile(id, token, workspaceId);
    if (tab) tab.location.href = `${url}#page=${Math.max(1, page)}`;
    else throw new Error("Hãy cho phép mở cửa sổ mới để xem PDF.");
  } catch (error) {
    tab?.close();
    throw error;
  }
}
