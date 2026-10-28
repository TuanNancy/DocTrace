// Loopback-only Auth/API fixture. Never used by application code or production.
import { createServer } from "node:http";
import { createHash, randomUUID } from "node:crypto";
import { adminFixture } from "./admin.mjs";

const admin = adminFixture();

const user = {
  id: "11111111-1111-4111-8111-111111111111",
  aud: "authenticated",
  role: "authenticated",
  email: "student@example.test",
  app_metadata: { provider: "email", providers: ["email"] },
  user_metadata: { full_name: "Test Student" },
  created_at: "2026-01-01T00:00:00Z",
};
const expiresAt = Math.floor(Date.now() / 1000) + 3600;
const encode = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
const token = `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: user.id, aud: user.aud, role: user.role, exp: expiresAt })}.${encode("fixture-signature")}`;
const personalWorkspace = {
  id: user.id, name: "Cá nhân", kind: "personal", role: "owner",
  plan: "free", status: "active", created_at: "2026-01-01T00:00:00Z",
};
const teamWorkspace = {
  id: "33333333-3333-4333-8333-333333333333", name: "Nhóm học tập", kind: "team", role: "member",
  plan: "free", status: "active", created_at: "2026-01-02T00:00:00Z",
};
const workspaces = [personalWorkspace, teamWorkspace];
let uploads = 0;
let cancelledStreams = 0;
const questionsByWorkspace = new Map();
const chatRequests = new Map();
const documents = new Map();
const conversations = new Map();
const chunkId = "22222222-2222-4222-8222-222222222222";
const excerpt = "Baymax giúp bạn tra cứu nội dung tài liệu. Mỗi câu trả lời có trích dẫn để đối chiếu với văn bản gốc.";

function publicDocument(document) {
  const { workspace_id, ...item } = document;
  return item;
}

function publicConversation(conversation) {
  return {
    id: conversation.id, workspace_id: conversation.workspace_id,
    doc_id: conversation.doc_id, created_at: conversation.created_at,
    updated_at: conversation.updated_at, messages: conversation.messages,
  };
}

function conversationSummary(conversation) {
  return {
    id: conversation.id, doc_id: conversation.doc_id,
    created_at: conversation.created_at, updated_at: conversation.updated_at,
    message_count: conversation.messages.length,
  };
}

function findConversation(workspaceId, docId) {
  return [...conversations.values()].find((conversation) => conversation.workspace_id === workspaceId
    && conversation.doc_id === docId && !conversation.hidden_at);
}

function hideConversations(workspaceId, docId) {
  for (const conversation of conversations.values()) {
    if (conversation.workspace_id === workspaceId && conversation.doc_id === docId) {
      conversation.hidden_at = new Date().toISOString();
    }
  }
}

function workspaceFor(request) {
  const workspaceId = request.headers["x-workspace-id"];
  if (!workspaceId) {
    return { error: [400, { detail: { code: "workspace_required", message: "Thiếu header X-Workspace-Id." } }] };
  }
  if (!workspaces.some((workspace) => workspace.id === workspaceId && workspace.status === "active")) {
    return { error: [404, { detail: { code: "workspace_not_found", message: "Không tìm thấy workspace." } }] };
  }
  return { workspaceId };
}

function fixturePDF() {
  const stream = "BT /F1 16 Tf 50 740 Td (Baymax original source fixture) Tj ET";
  const objects = ["<</Type/Catalog/Pages 2 0 R>>", "<</Type/Pages/Kids[3 0 R]/Count 1>>",
    "<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
    "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>", `<</Length ${stream.length}>>\nstream\n${stream}\nendstream`];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => { offsets.push(pdf.length); pdf += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = pdf.length;
  pdf += `xref\n0 ${offsets.length}\n0000000000 65535 f \n`;
  pdf += offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  return `${pdf}trailer<</Size ${offsets.length}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF`;
}

function processDocument(document, fail = false) {
  document.status = "queued";
  document.error = null;
  setTimeout(() => { if (document.status === "queued") document.status = "processing"; }, 300);
  setTimeout(() => {
    if (document.status !== "processing") return;
    document.status = fail ? "error" : "ready";
    document.error = fail ? "Không thể đọc văn bản PDF. Vui lòng thử lại." : null;
    document.chunks_count = fail ? 0 : 2;
  }, document.name === "slow.pdf" ? 7000 : 1000);
}

function json(response, status, body) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
}

createServer(async (request, response) => {
  response.setHeader("Access-Control-Allow-Origin", "http://localhost:4310");
  response.setHeader("Access-Control-Allow-Headers", "authorization, apikey, content-type, x-client-info, x-supabase-api-version, x-workspace-id");
  response.setHeader("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS");
  response.setHeader("Access-Control-Expose-Headers", "Retry-After, X-Conversation-Id");
  if (request.method === "OPTIONS") {
    response.writeHead(204).end();
    return;
  }
  const url = new URL(request.url, "http://127.0.0.1:4311");
  if (url.pathname === "/health") return json(response, 200, { status: "ok" });
  if (url.pathname === "/test/status") return json(response, 200, { uploads, cancelledStreams });
  if (url.pathname === "/test/reset") {
    documents.clear(); conversations.clear(); questionsByWorkspace.clear(); chatRequests.clear(); uploads = 0; cancelledStreams = 0;
    admin.reset();
    return json(response, 200, {});
  }
  if (url.pathname === "/fixture.pdf" && url.searchParams.get("signature") === "fixture") {
    response.writeHead(200, { "Content-Type": "application/pdf", "Content-Disposition": "inline" });
    return response.end(fixturePDF());
  }

  const parts = [];
  for await (const part of request) parts.push(part);
  const body = Buffer.concat(parts).toString();
  if (url.pathname === "/test/admin") {
    admin.setAllowed(JSON.parse(body).allowed);
    return json(response, 200, {});
  }
  if (url.pathname === "/auth/v1/signup") {
    const credentials = JSON.parse(body);
    if (credentials.email !== user.email || credentials.password !== "fixture-password" || credentials.data?.full_name !== "Test Student") {
      return json(response, 400, { code: "validation_failed", message: "Không thể tạo tài khoản với thông tin này." });
    }
    return json(response, 200, { user });
  }
  if (url.pathname === "/auth/v1/token") {
    const credentials = JSON.parse(body);
    const google = url.searchParams.get("grant_type") === "id_token";
    const valid = google
      ? credentials.provider === "google" && typeof credentials.nonce === "string"
        && /^[a-f0-9]{64}$/.test(credentials.nonce)
        && credentials.id_token === `fixture-google:${createHash("sha256").update(credentials.nonce).digest("hex")}`
      : credentials.email === user.email && credentials.password === "fixture-password";
    if (!valid) {
      return json(response, 400, { error: "invalid_grant", error_description: "Invalid login credentials" });
    }
    return json(response, 200, {
      access_token: token,
      refresh_token: "fixture-refresh-token",
      token_type: "bearer",
      expires_in: 3600,
      expires_at: expiresAt,
      user,
    });
  }
  if (request.headers.authorization !== `Bearer ${token}`) {
    return json(response, 401, { detail: "Missing or invalid Bearer token", message: "Invalid session" });
  }
  if (url.pathname === "/auth/v1/user") return json(response, 200, user);
  if (url.pathname === "/auth/v1/logout") return response.writeHead(204).end();
  if (url.pathname.startsWith("/api/admin/")) return json(response, ...admin.handle(url, request.method, body));
  if (url.pathname === "/api/workspaces") return json(response, 200, { items: workspaces });
  if (url.pathname === "/api/upload") {
    const scope = workspaceFor(request);
    if (scope.error) return json(response, ...scope.error);
    if (!request.headers["content-type"]?.includes("multipart/form-data") || !body.includes('%PDF')) {
      return json(response, 400, { detail: "Expected multipart PDF" });
    }
    uploads += 1;
    const document = { doc_id: randomUUID(), workspace_id: scope.workspaceId,
      name: /filename="([^"]+)"/.exec(body)?.[1] ?? "fixture.pdf",
      size_bytes: 1024, chunks_count: 0, warnings: [], error: null,
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(), status: "queued" };
    documents.set(document.doc_id, document);
    processDocument(document, document.name === "error.pdf");
    return json(response, 202, publicDocument(document));
  }
  if (url.pathname === "/api/documents") {
    const scope = workspaceFor(request);
    if (scope.error) return json(response, ...scope.error);
    const items = [...documents.values()]
      .filter((document) => document.workspace_id === scope.workspaceId)
      .reverse().map(publicDocument);
    return json(response, 200, { items, has_more: false });
  }
  const documentRoute = url.pathname.match(/^\/api\/documents\/([^/]+)(.*)$/);
  if (documentRoute) {
    const scope = workspaceFor(request);
    if (scope.error) return json(response, ...scope.error);
    const document = documents.get(documentRoute[1]);
    if (!document || document.workspace_id !== scope.workspaceId) {
      return json(response, 404, { detail: { code: "document_not_found", message: "Không tìm thấy tài liệu." } });
    }
    const action = documentRoute[2];
    if (request.method === "DELETE") {
      if (["queued", "processing", "deleting"].includes(document.status)) {
        return json(response, 409, { detail: "Chờ xử lý hoàn tất trước khi xóa." });
      }
      document.status = "deleting";
      hideConversations(scope.workspaceId, document.doc_id);
      setTimeout(() => documents.delete(document.doc_id), 500);
      return json(response, 202, publicDocument(document));
    }
    if (action === "/retry") {
      if (!["error", "delete_error"].includes(document.status)) return json(response, 409, { detail: "Tài liệu chưa thể thử lại." });
      processDocument(document); return json(response, 202, publicDocument(document));
    }
    if (action === "/file") return json(response, 200, { url: "http://127.0.0.1:4311/fixture.pdf?signature=fixture", expires_in: 300 });
    if (action === `/chunks/${chunkId}`) return json(response, 200, { doc_id: document.doc_id, chunk_id: chunkId, source: document.name, page: 1, text: excerpt });
    return json(response, 200, publicDocument(document));
  }
  if (url.pathname === "/api/conversations") {
    const scope = workspaceFor(request);
    if (scope.error) return json(response, ...scope.error);
    const docId = url.searchParams.get("doc_id");
    const items = [...conversations.values()]
      .filter((conversation) => conversation.workspace_id === scope.workspaceId
        && !conversation.hidden_at && (!docId || conversation.doc_id === docId))
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at)
        || right.created_at.localeCompare(left.created_at))
      .slice(0, 20)
      .map(conversationSummary);
    return json(response, 200, { items });
  }
  const conversationRoute = url.pathname.match(/^\/api\/conversations\/([^/]+)$/);
  if (conversationRoute) {
    const scope = workspaceFor(request);
    if (scope.error) return json(response, ...scope.error);
    const conversation = conversations.get(conversationRoute[1]);
    if (!conversation || conversation.workspace_id !== scope.workspaceId || conversation.hidden_at) {
      return json(response, 404, { detail: { code: "conversation_not_found", message: "Không tìm thấy hội thoại." } });
    }
    if (request.method === "DELETE") {
      conversations.delete(conversation.id);
      response.writeHead(204).end();
      return;
    }
    const document = documents.get(conversation.doc_id);
    const activeIndex = document?.status === "ready" ? document.doc_id : null;
    return json(response, 200, {
      ...publicConversation(conversation),
      messages: conversation.messages.map((message) => {
        const stale = message.role === "assistant"
          ? !activeIndex || message.index_id !== activeIndex
          : undefined;
        return {
          ...message,
          ...(message.role === "assistant" ? { stale } : {}),
          sources: (message.sources ?? []).map((source) => ({ ...source, stale: !!stale })),
        };
      }),
    });
  }
  if (url.pathname === "/api/usage") {
    const scope = workspaceFor(request);
    if (scope.error) return json(response, ...scope.error);
    const now = new Date();
    const owner = workspaces.find((workspace) => workspace.id === scope.workspaceId).role === "owner";
    const chatQuestions = questionsByWorkspace.get(scope.workspaceId) ?? 0;
    const documentCount = [...documents.values()]
      .filter((document) => document.workspace_id === scope.workspaceId).length;
    return json(response, 200, {
      workspace_id: scope.workspaceId, scope: owner ? "workspace" : "self", plan: "free",
      period_start: new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString(),
      reset_at: new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1)).toISOString(),
      chat: { used: chatQuestions, limit: 10, remaining: owner ? Math.max(0, 10 - chatQuestions) : null, metric: "chat_questions_month" },
      documents: { used: documentCount, limit: 5, remaining: owner ? Math.max(0, 5 - documentCount) : null, metric: "documents" },
      costs: { known_micros: chatQuestions * 250000, unknown_calls: 0 },
      by_user: chatQuestions ? [{
        user_id: user.id, chat_questions: chatQuestions,
        cost_micros: chatQuestions * 250000, cost_unknown_calls: 0,
      }] : [],
    });
  }
  if (url.pathname === "/api/chat") {
    const scope = workspaceFor(request);
    if (scope.error) return json(response, ...scope.error);
    const chat = JSON.parse(body);
    if (!chat.doc_id || !chat.query) return json(response, 422, { detail: "Missing chat fields" });
    if (typeof chat.request_id !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(chat.request_id)) {
      return json(response, 422, { detail: "Missing chat request id" });
    }
    const document = documents.get(chat.doc_id);
    if (!document || document.workspace_id !== scope.workspaceId || document.status !== "ready") {
      return json(response, 409, { detail: "Tài liệu chưa sẵn sàng." });
    }
    const requestKey = `${scope.workspaceId}:${chat.request_id}`;
    const previous = chatRequests.get(requestKey);
    if (previous) {
      const code = previous.status === "completed" ? "request_completed"
        : previous.status === "streaming" ? "request_in_progress" : "request_failed";
      return json(response, 409, { detail: { code, message: "Yêu cầu đã được tiếp nhận.",
        conversation_id: previous.conversation_id, retryable: code === "request_failed" } });
    }

    const now = new Date().toISOString();
    let conversation = findConversation(scope.workspaceId, document.doc_id);
    if (!conversation) {
      conversation = {
        id: randomUUID(), workspace_id: scope.workspaceId, doc_id: document.doc_id,
        created_at: now, updated_at: now, messages: [],
      };
      conversations.set(conversation.id, conversation);
    }
    const source = {
      citation_id: 1, doc_id: document.doc_id, chunk_id: chunkId, page: 1,
      source: document.name, score: 0.95,
    };
    const userMessage = {
      id: randomUUID(), role: "user", content: chat.query, sources: [], index_id: null,
      status: "complete", created_at: now, updated_at: now,
    };
    const assistantMessage = {
      id: randomUUID(), role: "assistant", content: "", sources: [source],
      index_id: document.doc_id, status: "streaming", created_at: now, updated_at: now,
    };
    conversation.messages.push(userMessage, assistantMessage);
    const admission = { conversation_id: conversation.id, status: "streaming" };
    chatRequests.set(requestKey, admission);
    conversation.updated_at = now;
    questionsByWorkspace.set(scope.workspaceId, (questionsByWorkspace.get(scope.workspaceId) ?? 0) + 1);

    response.writeHead(200, {
      "Content-Type": "text/event-stream", "Cache-Control": "no-cache",
      "X-Conversation-Id": conversation.id,
    });
    const event = (type, data) => response.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    const first = "## Kết quả\n\nĐang đọc tài liệu";
    const second = ": **nội dung kiểm thử**. [1]\n\n| Nội dung | Kết quả |\n|---|---|\n| Kiểm tra | Thành công |\n";
    event("sources", [source]);
    event("token", first);
    assistantMessage.content = first;
    let finished = false;
    const timer = setTimeout(() => {
      event("token", second);
      assistantMessage.content += second;
      assistantMessage.status = "complete";
      admission.status = "completed";
      assistantMessage.updated_at = new Date().toISOString();
      conversation.updated_at = assistantMessage.updated_at;
      event("done", "[DONE]");
      finished = true;
      response.end();
    }, 2000);
    response.on("close", () => {
      clearTimeout(timer);
      if (finished) return;
      cancelledStreams += 1;
      assistantMessage.status = "interrupted";
      admission.status = "interrupted";
      assistantMessage.updated_at = new Date().toISOString();
      conversation.updated_at = assistantMessage.updated_at;
    });
    return;
  }
  json(response, 404, { message: "Unknown fixture endpoint" });
}).listen(4311, "127.0.0.1");
