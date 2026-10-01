// Local HTTP contract fixtures, used only by Playwright. No cloud calls or real keys.
import { createServer } from "node:http";
import { createHmac } from "node:crypto";

const user = {
  id: "00000000-0000-0000-0000-000000000001", aud: "authenticated", role: "authenticated",
  email: "demo@example.com", email_confirmed_at: new Date().toISOString(),
  app_metadata: { provider: "email", providers: ["email"] },
  user_metadata: { full_name: "Demo Tester" }, created_at: new Date().toISOString(),
};
const expiresAt = Math.floor(Date.now() / 1000) + 3600;
const encode = (data) => Buffer.from(JSON.stringify(data)).toString("base64url");
const unsigned = `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: user.id, aud: "authenticated", exp: expiresAt, role: "authenticated", email: user.email })}`;
const token = `${unsigned}.${createHmac("sha256", "e2e-only-not-a-real-key").update(unsigned).digest("base64url")}`;
const session = { access_token: token, token_type: "bearer", refresh_token: "e2e-refresh", expires_in: 3600, expires_at: expiresAt, user };

createServer(async (request, response) => {
  response.setHeader("Access-Control-Allow-Origin", "http://127.0.0.1:3005");
  response.setHeader("Access-Control-Allow-Headers", "authorization, apikey, content-type, x-client-info, x-supabase-api-version");
  response.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  if (request.method === "OPTIONS") { response.writeHead(204).end(); return; }
  const url = new URL(request.url, "http://127.0.0.1:8999");
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const body = Buffer.concat(chunks).toString();
  const json = (status, value) => {
    response.writeHead(status, { "Content-Type": "application/json" });
    response.end(JSON.stringify(value));
  };
  if (url.pathname === "/health") return json(200, { status: "ok" });
  if (url.pathname === "/auth/v1/token") {
    const credentials = JSON.parse(body || "{}");
    if (url.searchParams.get("grant_type") === "refresh_token" || credentials.password === "correct-password") return json(200, session);
    return json(400, { error_code: "invalid_credentials", msg: "Invalid login credentials" });
  }
  if (url.pathname === "/auth/v1/user") {
    return request.headers.authorization === `Bearer ${token}`
      ? json(200, user) : json(401, { msg: "Invalid JWT" });
  }
  if (url.pathname === "/auth/v1/logout") { response.writeHead(204).end(); return; }
  if (url.pathname === "/auth/v1/signup") return json(200, user);
  if (request.headers.authorization !== `Bearer ${token}`) return json(401, { detail: "Missing valid bearer token" });
  if (url.pathname === "/api/upload") {
    if (!request.headers["content-type"]?.includes("multipart/form-data; boundary=") || !body.includes('filename="policy.pdf"')) {
      return json(400, { detail: "Expected multipart PDF upload" });
    }
    return json(200, { doc_id: "test-document", name: "policy.pdf", chunks_count: 3, status: "completed" });
  }
  if (url.pathname === "/api/chat") {
    const payload = JSON.parse(body);
    if (payload.doc_id !== "test-document") return json(422, { detail: "Wrong document" });
    response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
    const event = (name, data) => response.write(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
    event("sources", [{ page: 2, source: "policy.pdf", score: 0.9 }]);
    event("token", "Mười hai ");
    setTimeout(() => {
      if (payload.query !== "disconnect") { event("token", "ngày nghỉ phép."); event("done", "[DONE]"); }
      response.end();
    }, 100);
    return;
  }
  json(404, { detail: "Unknown fixture endpoint" });
}).listen(8999, "127.0.0.1");
