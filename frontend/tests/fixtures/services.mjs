// Loopback-only Auth/API fixture. Never used by application code or production.
import { createServer } from "node:http";

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

function json(response, status, body) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
}

createServer(async (request, response) => {
  response.setHeader("Access-Control-Allow-Origin", "http://localhost:4310");
  response.setHeader("Access-Control-Allow-Headers", "authorization, apikey, content-type, x-client-info, x-supabase-api-version");
  response.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  if (request.method === "OPTIONS") {
    response.writeHead(204).end();
    return;
  }
  const url = new URL(request.url, "http://127.0.0.1:4311");
  if (url.pathname === "/health") return json(response, 200, { status: "ok" });
  if (url.pathname === "/test/status") return json(response, 200, { uploads, cancelledStreams });

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
    return json(response, 200, { doc_id: `document-${uploads}`, chunks_count: 2 });
  }
  if (url.pathname === "/api/chat") {
    const chat = JSON.parse(body);
    if (!chat.doc_id || !chat.query) return json(response, 422, { detail: "Missing chat fields" });
    response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
    const event = (type, data) => response.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    event("sources", [{ page: 1, source: "fixture.pdf", score: 0.95 }]);
    event("token", "Đang đọc tài liệu");
    let finished = false;
    const timer = setTimeout(() => {
      event("token", ": nội dung kiểm thử.");
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
