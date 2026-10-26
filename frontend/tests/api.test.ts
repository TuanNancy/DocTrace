// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  deleteConversation, getConversation, getUsage, listConversations, listWorkspaces,
  streamChat, uploadPDF,
} from "@/lib/api";

describe("API transport", () => {
  beforeEach(() => vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.test/"));

  it("uploads multipart PDF with Bearer auth, workspace header and a cancellation signal", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ doc_id: "a", chunks_count: 3 }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const file = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    await expect(uploadPDF(file, "test-token", "workspace-a", controller.signal)).resolves.toMatchObject({ doc_id: "a" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/upload");
    expect(init.headers).toEqual({ Authorization: "Bearer test-token", "X-Workspace-Id": "workspace-a" });
    expect(init.body.get("file").name).toBe("a.pdf");
    expect(init.signal).toBe(controller.signal);
  });

  it("posts the backend chat contract with the selected workspace and forwards abort", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { headers: { "Content-Type": "text/event-stream" } }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    await streamChat("Question", "doc-a", "test-token", "workspace-a", "request-a", controller.signal);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/chat");
    expect(JSON.parse(init.body)).toEqual({ query: "Question", doc_id: "doc-a", language: "vi", request_id: "request-a" });
    expect(init.headers.Authorization).toBe("Bearer test-token");
    expect(init.headers["X-Workspace-Id"]).toBe("workspace-a");
    expect(init.signal).toBe(controller.signal);
  });

  it("lists workspace memberships without a tenant header", async () => {
    const workspace = {
      id: "workspace-a", name: "Cá nhân", kind: "personal", role: "owner",
      plan: "free", status: "active", created_at: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ items: [workspace] }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(listWorkspaces("test-token")).resolves.toEqual([workspace]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/workspaces");
    expect(init.headers).toEqual({ Authorization: "Bearer test-token" });
  });

  it("lists conversations with the tenant header and an optional document filter", async () => {
    const item = {
      id: "conversation-a", doc_id: "doc-a", message_count: 2,
      created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:01:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ items: [item] }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(listConversations("test-token", "workspace-a", "doc-a")).resolves.toEqual([item]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/conversations?doc_id=doc-a");
    expect(init.headers).toEqual({
      Authorization: "Bearer test-token", "X-Workspace-Id": "workspace-a",
    });
    expect(init.cache).toBe("no-store");
  });

  it("loads and deletes a transcript through owner-scoped routes", async () => {
    const transcript = {
      id: "conversation-a", workspace_id: "workspace-a", doc_id: "doc-a",
      created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:01:00Z",
      messages: [],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json(transcript))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getConversation("conversation/one", "test-token", "workspace-a"))
      .resolves.toEqual(transcript);
    expect(fetchMock.mock.calls[0][0]).toBe(
      "https://api.example.test/api/conversations/conversation%2Fone",
    );
    await expect(deleteConversation("conversation-a", "test-token", "workspace-a"))
      .resolves.toBeUndefined();
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe("https://api.example.test/api/conversations/conversation-a");
    expect(init.method).toBe("DELETE");
    expect(init.headers["X-Workspace-Id"]).toBe("workspace-a");
  });

  it("fetches workspace usage with the tenant header", async () => {
    const usage = {
      workspace_id: "workspace-a", plan: "free",
      period_start: "2026-10-01T00:00:00Z", reset_at: "2026-11-01T00:00:00Z",
      chat: { used: 2, limit: 10, remaining: 8, metric: "chat_questions_month" },
      documents: { used: 1, limit: 5, remaining: 4, metric: "documents" },
      by_user: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(usage));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getUsage("test-token", "workspace-a")).resolves.toEqual(usage);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/usage");
    expect(init.headers).toEqual({
      Authorization: "Bearer test-token", "X-Workspace-Id": "workspace-a",
    });
  });

  it("supplies the PDF MIME type when the browser leaves it empty", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ doc_id: "a", chunks_count: 0, status: "queued" }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    await uploadPDF(new File(["%PDF-1.4"], "a.pdf"), "token", "workspace-a");
    expect(fetchMock.mock.calls[0][1].body.get("file").type).toBe("application/pdf");
  });

  it("surfaces structured workspace errors with their stable code", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({
      detail: { code: "workspace_not_found", message: "Không tìm thấy workspace." },
    }, { status: 404 })));
    await expect(streamChat("q", "a", "token", "workspace-a", "request-a")).rejects.toMatchObject({
      message: "Không tìm thấy workspace.", status: 404, code: "workspace_not_found",
    });
  });

  it("does not send a workspace-scoped request without a selection", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(streamChat("q", "a", "token", "", "request-a")).rejects.toThrow("Chưa chọn không gian làm việc");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces HTTP auth errors instead of trying to parse SSE", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "Expired session" }, { status: 401 })));
    await expect(streamChat("q", "a", "expired", "workspace-a", "request-a")).rejects.toThrow("Expired session");
  });

  it("retains the HTTP status for proxy HTML errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>Bad Gateway</html>", { status: 502 })));
    await expect(streamChat("q", "a", "token", "workspace-a", "request-a")).rejects.toThrow("502");
  });

  it("rejects a non-SSE response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ status: "ok" })));
    await expect(streamChat("q", "a", "token", "workspace-a", "request-a")).rejects.toThrow("stream chat");
  });

  it("shows the Retry-After wait for fetch without opening SSE", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "Too many requests" }, {
      status: 429, headers: { "Retry-After": "12" },
    })));
    await expect(streamChat("q", "a", "token", "workspace-a", "request-a")).rejects.toThrow("thử lại sau 12 giây");
  });

  it.each([null, "nonsense", "-1", "1.5"])("has a friendly fallback for invalid Retry-After %s", async (value) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", {
      status: 429, headers: value === null ? {} : { "Retry-After": value },
    })));
    await expect(streamChat("q", "a", "token", "workspace-a", "request-a")).rejects.toThrow("Vui lòng thử lại sau.");
  });

  it("does not duplicate a wait message from the API", async () => {
    const detail = "Bạn gửi yêu cầu quá nhanh. Vui lòng thử lại sau 12 giây.";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail }, {
      status: 429, headers: { "Retry-After": "12" },
    })));
    await expect(streamChat("q", "a", "token", "workspace-a", "request-a")).rejects.toThrow(detail);
  });

  it("accepts HTTP-date Retry-After", async () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("Thu, 08 Oct 2026 10:00:00 GMT"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", {
      status: 429, headers: { "Retry-After": "Thu, 08 Oct 2026 10:00:12 GMT" },
    })));
    await expect(streamChat("q", "a", "token", "workspace-a", "request-a")).rejects.toThrow("thử lại sau 12 giây");
  });

  it("shows the quota reset date instead of a long Retry-After wait", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({
      detail: {
        code: "quota_exceeded", message: "Đã hết lượt hỏi trong tháng.",
        metric: "chat_questions_month", limit: 10, used: 10,
        reset_at: "2026-11-01T00:00:00Z", retry_after: 432060,
      },
    }, { status: 429, headers: { "Retry-After": "432060" } })));
    await expect(streamChat("q", "a", "token", "workspace-a", "request-a")).rejects.toMatchObject({
      message: "Đã hết lượt hỏi trong tháng. Hạn mức sẽ được đặt lại vào 01/11/2026.",
      status: 429,
      code: "quota_exceeded",
    });
  });

  it("keeps a document quota message without a monthly reset date", async () => {
    const message = "Đã dùng hết số tài liệu của gói hiện tại.";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({
      detail: { code: "quota_exceeded", message, metric: "documents", limit: 5, used: 5 },
    }, { status: 429 })));
    await expect(streamChat("q", "a", "token", "workspace-a", "request-a")).rejects.toMatchObject({
      message, status: 429, code: "quota_exceeded",
    });
  });

  it("preserves Retry-After and the workspace header for progress uploads through XHR", async () => {
    const xhr = {
      open: vi.fn(), setRequestHeader: vi.fn(), upload: {}, status: 429,
      responseText: JSON.stringify({ detail: "Too many requests" }),
      getResponseHeader: vi.fn((name: string) => name.toLowerCase() === "retry-after" ? "17" : null),
      onload: () => {}, send() { this.onload(); },
    };
    vi.stubGlobal("XMLHttpRequest", vi.fn(() => xhr));
    await expect(uploadPDF(new File(["%PDF"], "a.pdf"), "token", "workspace-a", undefined, vi.fn()))
      .rejects.toThrow("thử lại sau 17 giây");
    expect(xhr.setRequestHeader).toHaveBeenCalledWith("X-Workspace-Id", "workspace-a");
  });
});
