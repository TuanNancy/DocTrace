/** Single citation source from SSE event "sources" */
export interface ChatSource {
  citation_id?: number;
  chunk_id?: string;
  doc_id?: string;
  page: number;
  source: string;
  /** Similarity score; null for document summaries retrieved without vector search. */
  score: number | null;
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
