export interface AdminPage<T> { items: T[]; next_offset: number | null }
export interface CostGroup { key: string | null; calls: number; known_micros: number; unknown_calls: number }
export interface AdminOverview {
  since: string; documents: number; workspaces: { status: string; count: number }[];
  costs: { cost_status: string; calls: number; known_micros: number }[];
  by: Record<"day" | "model" | "workspace" | "kind", CostGroup[]>;
  chat: { requests: number; failed: number; interrupted: number; cache_hits: number; latency_p50_ms: number | null;
    latency_p95_ms: number | null; first_token_p50_ms: number | null; first_token_p95_ms: number | null };
}
export interface AdminWorkspace {
  id: string; name: string; kind: string; plan: "free" | "pro"; status: "active" | "archived" | "purging";
  created_by: string; created_at: string; documents: number; members: number;
}
export interface AdminDocument {
  doc_id: string; workspace_id: string; owner_user_id: string; status: string; chunks_count: number;
  size_bytes: number; created_at: string; updated_at: string; error_code: string | null;
  job_id: string | null; request_id: string | null; attempt_number: number; queue_state: string | null;
}
export interface AdminFailure {
  id: string; workspace_id: string; owner_user_id: string; doc_id: string; job_id: string;
  attempt: number; kind: string; error_code: string; message: string; request_id: string | null; created_at: string;
}
export interface AdminAudit {
  id: string; actor_user_id: string; workspace_id: string | null; action: string; target_type: string;
  target_id: string | null; metadata: Record<string, string | number>; request_id: string | null; created_at: string;
}
export interface AdminPurge {
  workspace_id: string; status: "running" | "completed"; started_at: string; updated_at: string;
  completed_at: string | null; total: number; deleted: number; failed: number; deleting: number;
}
export interface AdminHealth {
  status: string;
  checks: Record<string, { status: string; latency_ms?: number; error_code?: string;
    workers?: number; queued?: number; started?: number; scheduled?: number; failed?: number;
    oldest_queued_seconds?: number | null; collection_exists?: boolean }>;
}
