/** Single citation source from SSE event "sources" */
export interface ChatSource {
  citation_id: number;
  chunk_id: string;
  doc_id: string;
  page: number;
  source: string;
  /** Similarity score; null for document summaries retrieved without vector search. */
  score: number | null;
  /** True when the document was re-indexed or deleted after this answer. */
  stale?: boolean;
}

/** Parsed SSE event types for streamChat() */
export type SSEEvent =
  | { type: "sources"; data: ChatSource[] }
  | { type: "token"; data: string }
  | { type: "error"; data: { message: string } }
  | { type: "done"; data: "[DONE]" };

/** One message in chat history */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
  isStreaming?: boolean;
  interrupted?: boolean;
}

export type DocumentStatus = "queued" | "processing" | "ready" | "error" | "deleting" | "delete_error" | "deleted";

/** Public document returned by upload and library endpoints. */
export interface LibraryDocument {
  doc_id: string;
  name: string;
  size_bytes: number;
  status: DocumentStatus;
  chunks_count: number;
  warnings: string[];
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceExcerpt {
  doc_id: string;
  chunk_id: string;
  source: string;
  page: number;
  text: string;
}

/** Membership returned by GET /api/workspaces. */
export interface Workspace {
  id: string;
  name: string;
  kind: "personal" | "team";
  role: "owner" | "member";
  plan: "free" | "pro";
  status: "active" | "archived" | "purging";
  created_at: string | null;
}

/** One persisted message returned by GET /api/conversations/{id}. */
export interface TranscriptMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: ChatSource[];
  index_id: string | null;
  status: "pending" | "streaming" | "complete" | "interrupted" | "error";
  created_at: string;
  updated_at: string;
}

/** Latest active conversation summary for the current user and document. */
export interface ConversationSummary {
  id: string;
  doc_id: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Transcript {
  id: string;
  workspace_id: string;
  doc_id: string;
  created_at: string;
  updated_at: string;
  messages: TranscriptMessage[];
}

export interface UsageMetric {
  used: number;
  limit: number;
  /** Shared remaining quota is private to workspace owners. */
  remaining: number | null;
  metric: string;
}

export interface UsageUser {
  user_id: string;
  chat_questions: number;
  cost_micros: number;
  cost_unknown_calls: number;
}

/** GET /api/usage: plan limits, monthly counters and owner-scoped costs. */
export interface UsageSummary {
  workspace_id: string;
  scope: "workspace" | "self";
  plan: "free" | "pro";
  period_start: string;
  reset_at: string;
  chat: UsageMetric;
  documents: UsageMetric;
  by_user: UsageUser[];
  costs: { known_micros: number; unknown_calls: number };
}
