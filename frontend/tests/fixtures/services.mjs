// Loopback-only Auth/API fixture. Never used by application code or production.
import { createServer } from "node:http";
import { randomUUID } from "node:crypto";

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
let uploads = 0;
let cancelledStreams = 0;
const documents = new Map();
const chunkId = "22222222-2222-4222-8222-222222222222";
const excerpt = "Baymax giúp bạn tra cứu nội dung tài liệu. Mỗi câu trả lời có trích dẫn để đối chiếu với văn bản gốc.";

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
  response.setHeader("Access-Control-Allow-Headers", "authorization, apikey, content-type, x-client-info, x-supabase-api-version");
  response.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  if (request.method === "OPTIONS") {
    response.writeHead(204).end();
    return;
  }
  const url = new URL(request.url, "http://127.0.0.1:4311");
  if (url.pathname === "/health") return json(response, 200, { status: "ok" });
  if (url.pathname === "/test/status") return json(response, 200, { uploads, cancelledStreams });
  if (url.pathname === "/test/reset") { documents.clear(); uploads = 0; cancelledStreams = 0; return json(response, 200, {}); }
  if (url.pathname === "/fixture.pdf" && url.searchParams.get("signature") === "fixture") {
    response.writeHead(200, { "Content-Type": "application/pdf", "Content-Disposition": "inline" });
    return response.end(fixturePDF());
  }

  const parts = [];
  for await (const part of request) parts.push(part);
  const body = Buffer.concat(parts).toString();
  if (url.pathname === "/auth/v1/token") {
    const credentials = JSON.parse(body);
    if (credentials.email !== user.email || credentials.password !== "fixture-password") {
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
  if (url.pathname === "/api/upload") {
    if (!request.headers["content-type"]?.includes("multipart/form-data") || !body.includes('%PDF')) {
      return json(response, 400, { detail: "Expected multipart PDF" });
    }
    uploads += 1;
    const document = { doc_id: randomUUID(), name: /filename="([^"]+)"/.exec(body)?.[1] ?? "fixture.pdf",
      size_bytes: 1024, chunks_count: 0, warnings: [], error: null,
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(), status: "queued" };
    documents.set(document.doc_id, document);
    processDocument(document, document.name === "error.pdf");
    return json(response, 202, document);
  }
  if (url.pathname === "/api/documents") return json(response, 200, { items: [...documents.values()].reverse(), has_more: false });
  const documentRoute = url.pathname.match(/^\/api\/documents\/([^/]+)(.*)$/);
  if (documentRoute) {
    const document = documents.get(documentRoute[1]);
    if (!document) return json(response, 404, { detail: "Không tìm thấy tài liệu." });
    const action = documentRoute[2];
    if (request.method === "DELETE") {
      if (["queued", "processing", "deleting"].includes(document.status)) {
        return json(response, 409, { detail: "Chờ xử lý hoàn tất trước khi xóa." });
      }
      document.status = "deleting";
      setTimeout(() => documents.delete(document.doc_id), 500);
      return json(response, 202, document);
    }
    if (action === "/retry") {
      if (!["error", "delete_error"].includes(document.status)) return json(response, 409, { detail: "Tài liệu chưa thể thử lại." });
      processDocument(document); return json(response, 202, document);
    }
    if (action === "/file") return json(response, 200, { url: "http://127.0.0.1:4311/fixture.pdf?signature=fixture", expires_in: 300 });
    if (action === `/chunks/${chunkId}`) return json(response, 200, { doc_id: document.doc_id, chunk_id: chunkId, source: document.name, page: 1, text: excerpt });
    return json(response, 200, document);
  }
  if (url.pathname === "/api/chat") {
    const chat = JSON.parse(body);
    if (!chat.doc_id || !chat.query) return json(response, 422, { detail: "Missing chat fields" });
    const document = documents.get(chat.doc_id);
    if (document?.status !== "ready") return json(response, 409, { detail: "Tài liệu chưa sẵn sàng." });
    response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
    const event = (type, data) => response.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    event("sources", [{ citation_id: 1, doc_id: document.doc_id, chunk_id: chunkId, page: 1, source: document.name, score: 0.95 }]);
    event("token", "## Kết quả\n\nĐang đọc tài liệu");
    let finished = false;
    const timer = setTimeout(() => {
      event("token", ": **nội dung kiểm thử**. [1]\n\n| Nội dung | Kết quả |\n|---|---|\n| Kiểm tra | Thành công |\n");
      event("done", "[DONE]");
      finished = true;
      response.end();
    }, 2000);
    response.on("close", () => {
      clearTimeout(timer);
      if (!finished) cancelledStreams += 1;
    });
    return;
  }
  json(response, 404, { message: "Unknown fixture endpoint" });
}).listen(4311, "127.0.0.1");
