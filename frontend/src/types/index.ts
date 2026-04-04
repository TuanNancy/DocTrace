/** Upload response from POST /api/upload */
export interface UploadResponse {
  doc_id: string;
  chunks_count: number;
  name?: string;
  status?: string;
  processing_time?: number;
  created_at?: string;
  warnings?: string[];
  pdf_storage_key?: string | null;
  metadata?: Record<string, any>;
  message?: string;
}

/** Single citation source from SSE event "sources" */
export interface ChatSource {
  page: number;
  source: string;
  score: number;
}

/** Parsed SSE event types for streamChat() */
export type SSEEventType = "sources" | "token" | "error" | "done";

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
}
