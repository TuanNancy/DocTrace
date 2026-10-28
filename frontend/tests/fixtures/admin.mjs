// Browser contract fixture only. Real authorization/lifecycle is tested in pytest.
export const adminWorkspaceId = "44444444-4444-4444-8444-444444444444";
export const adminDocumentId = "55555555-5555-4555-8555-555555555555";

export function adminFixture() {
  let allowed, workspace, document, purge, audit;
  const timestamp = "2026-10-29T00:00:00Z";
  const reset = () => {
    allowed = false; purge = null; audit = [];
    workspace = { id: adminWorkspaceId, name: "Admin fixture team", kind: "team", plan: "free", status: "active",
      created_by: "66666666-6666-4666-8666-666666666666", created_at: timestamp, members: 2, documents: 1 };
    document = { doc_id: adminDocumentId, workspace_id: workspace.id, owner_user_id: workspace.created_by,
      status: "error", chunks_count: 0, size_bytes: 1024, created_at: timestamp, updated_at: timestamp,
      error_code: "invalid_pdf", job_id: "index-fixture", request_id: "upload-fixture", attempt_number: 1, queue_state: "finished" };
  };
  reset();
  const page = (items) => ({ items, next_offset: null });
  const record = (action, target, metadata = {}) => audit.push({ id: `audit-${audit.length}`, action,
    actor_user_id: "11111111-1111-4111-8111-111111111111", workspace_id: adminWorkspaceId,
    target_id: target, target_type: action.startsWith("document") ? "document" : "workspace",
    request_id: "admin-request", created_at: timestamp, metadata });
  return {
    reset,
    setAllowed(value) { allowed = value === true; },
    handle(url, method, raw) {
      if (!allowed) return [403, { detail: { code: "admin_required", message: "Chỉ platform admin được sử dụng chức năng này." } }];
      const path = url.pathname.replace("/api/admin", "");
      if (path === "/access") return [200, { admin: true }];
      if (path === "/overview") return [200, { since: timestamp, documents: document ? 1 : 0,
        workspaces: workspace ? [{ status: workspace.status, count: 1 }] : [],
        costs: [{ cost_status: "reported", calls: 1, known_micros: 250000 }, { cost_status: "unknown", calls: 2, known_micros: 0 }],
        chat: { requests: 1, failed: 0, interrupted: 0, latency_p50_ms: 100, latency_p95_ms: 200, first_token_p50_ms: 25, first_token_p95_ms: 50 },
        by: { day: [], model: [], workspace: [], kind: [] } }];
      if (path === "/health") return [200, { status: "ok", checks: {
        postgres: { status: "ok", latency_ms: 2 }, redis: { status: "ok", latency_ms: 1 }, milvus: { status: "ok", collection_exists: true },
        queue: { status: "ok", workers: 1, queued: 0, started: 0, scheduled: 0, failed: 0, oldest_queued_seconds: null },
      } }];
      if (path === "/workspaces") return [200, page(workspace ? [workspace] : [])];
      if (path === "/documents") return [200, page(document
        && (!url.searchParams.get("status") || document.status === url.searchParams.get("status"))
        && (!url.searchParams.get("workspace_id") || document.workspace_id === url.searchParams.get("workspace_id")) ? [document] : [])];
      if (path === "/purges") return [200, page(purge ? [purge] : [])];
      if (path === "/audit") return [200, page(audit)];
      if (path === "/failures") return [200, page([{ id: "failure-1", doc_id: adminDocumentId, workspace_id: adminWorkspaceId,
        owner_user_id: "66666666-6666-4666-8666-666666666666", job_id: "index-fixture", attempt: 1, kind: "index",
        error_code: "invalid_pdf", message: "PDF cannot be indexed.", request_id: "upload-fixture", created_at: timestamp }])];
      if (path === `/documents/${adminDocumentId}/retry` && method === "POST" && document?.status === "error") {
        record("document.retry_requested", adminDocumentId, { kind: "index" });
        document = { ...document, status: "ready", error_code: null, job_id: "index-retry", request_id: "admin-request" };
        record("document.retry_accepted", adminDocumentId, { kind: "index", job_id: "index-retry" });
        return [202, document];
      }
      if (path === `/workspaces/${adminWorkspaceId}/plan` && method === "PATCH") {
        const plan = JSON.parse(raw).plan;
        record("workspace.plan_changed", adminWorkspaceId, { from_plan: workspace.plan, to_plan: plan });
        workspace.plan = plan;
        return [200, { id: workspace.id, plan }];
      }
      if (path === `/workspaces/${adminWorkspaceId}/archive` && method === "POST") {
        workspace.status = "archived"; record("workspace.archived", adminWorkspaceId);
        return [200, workspace];
      }
      if (path === `/workspaces/${adminWorkspaceId}/restore` && method === "POST") {
        workspace.status = "active"; record("workspace.restored", adminWorkspaceId);
        return [200, workspace];
      }
      if (path === `/workspaces/${adminWorkspaceId}/purge` && method === "POST" && workspace.status === "archived"
        && JSON.parse(raw).confirm_workspace_id === adminWorkspaceId) {
        workspace.status = "purging";
        purge = { workspace_id: adminWorkspaceId, status: "running", started_at: timestamp, updated_at: timestamp,
          completed_at: null, total: 1, deleted: 0, failed: 0, deleting: 1 };
        record("workspace.purge_started", adminWorkspaceId, { documents: 1 });
        return [202, purge];
      }
      return [409, { detail: { code: "operation_rejected", message: "Thao tác không hợp lệ." } }];
    },
  };
}
