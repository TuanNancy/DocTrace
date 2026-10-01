# DocTrace Architecture

## Scope and deployment boundaries

DocTrace is a fixed text-based RAG pipeline: PDF extraction → chunking → embedding → retrieval → generation. There is no OCR or agent planner.

- **Next.js on Vercel:** UI, Supabase Server Actions, OAuth/confirmation callback, cookie refresh middleware.
- **FastAPI behind Caddy on EC2:** authenticated PDF upload/indexing and SSE chat. Browser requests go directly to this origin with a bearer token.
- **Zilliz/Milvus:** vectors, text, citation metadata and owner IDs.
- **Supabase:** user identity and original PDFs in private S3-compatible Storage.
- **OpenRouter:** both chat and embedding requests, despite the OpenAI SDK imports.

S3 + CloudFront static hosting would require replacing the Next.js server-side auth flow. The production target is Vercel; `output: "export"` is not configured.

## Frontend integration

`frontend/src/lib/` contains:

| Module | Responsibility |
|---|---|
| `client.ts` | Supabase browser client; the SSR package manages the browser singleton. |
| `server.ts` | Request-scoped client for cookie-writing Server Actions and Route Handlers. |
| `middleware.ts` | Validate user, refresh request/response cookies, protect `/chat`, retain auth routes as public, mark responses private/no-store. |
| `api.ts` | Multipart upload, POST chat with bearer auth, incremental SSE parser, transport/error handling. |
| `supabase-config.ts` | Validate the public Supabase URL/key configuration. |
| `utils.ts` | `cn()` combines clsx with Tailwind-3-compatible tailwind-merge. |

The browser reads `getSession()` to obtain an access token. Authorization is performed independently by Supabase `getUser()` in middleware and the FastAPI auth dependency. Cookies shared with the browser are managed by Supabase SSR; the app does not manually persist tokens in localStorage.

`ChatWindow` cancels its fetch on unmount/clear. Changing the selected document remounts the chat window to avoid showing previous-document answers. Reload preserves auth, but selected document and transcript are not persisted. Demo upload/chat requires `NEXT_PUBLIC_DEMO_MODE=true` in development.

The logo is bundled from `frontend/public/logo1.png`; deployment does not read the repository-root logo at runtime.

## Upload flow

```text
POST /api/upload
  → require_supabase_user: validate bearer token with Supabase Auth
  → require_upload_slot: reject excess concurrent indexing with 429 + Retry-After
  → validate PDF MIME, extension, bytes and configured maximum size
  → generate doc_id; take user_id from verified identity
  → attempt original-PDF retention at user_id/doc_id/filename
  → index_pdf_bytes(..., user_id=verified_user_id)
      → temporary PDF → extract page text → split chunks
      → enforce maximum chunk count → embed in bounded batches
      → connect vector store → validate schema/dimension → insert owner-scoped chunks
      → disconnect and delete temporary file, including failure paths
```

The router owns auth, HTTP validation, IDs and original-file retention. `services/pdf_indexing.py` owns extraction, chunking, embedding, insertion and cleanup. Retention happens before indexing, so an indexing failure can leave a retained original PDF.

PDF extraction, embedding and Milvus SDK work run in worker threads rather than blocking the event loop. This is not a background job queue: upload still waits for indexing and returns the result in one HTTP response. On the small EC2 target, start with one API worker and `UPLOAD_MAX_CONCURRENT=1`; the admission limit is per process, not distributed.

## Chat flow

```text
POST /api/chat {query, doc_id, language}
  → validate bearer token; reject client-supplied extra fields such as user_id
  → create_initialized_rag_pipeline()
  → retrieve_chunks(query, doc_id, user_id=verified_user_id)
      → embed query → filter user_id AND doc_id → similarity search
  → emit sources
  → no matches: emit fallback token and done; skip completion
  → stream_answer(..., retrieved_chunks_override=chunks)
      → build bounded context with page citations → stream OpenRouter completion
  → emit token events, then done
  → failures: emit error and done
  → shutdown in finally, including partial initialization and disconnects
```

The router retrieves exactly once; `stream_answer()` reuses those chunks. A missing/non-owned document produces no context without revealing whether another user owns it. Search infrastructure failures propagate as errors instead of masquerading as zero matches.

### SSE wire contract

| Event | JSON-decoded data |
|---|---|
| `sources` | `[{page, source, score}]` |
| `token` | Text delta string, possibly multiple model tokens |
| `error` | `{message: "..."}` |
| `done` | String `"[DONE]"` |

All event data uses JSON serialization. `done` is the event name; `[DONE]` is its payload. The frontend handles UTF-8 split across reads, multiple events per read, LF/CRLF separators and truncated streams. Stream failures after headers are sent use HTTP 200 plus an error event. Detailed upstream errors stay in backend logs.

## Vector store invariants

- One adapter supports host/port local Milvus and HTTPS URI/token Zilliz. URI mode defaults to `AUTOINDEX`; local mode defaults to `IVF_FLAT`. IVF-only parameters are omitted for AUTOINDEX.
- Each `MilvusVectorStore` owns a unique PyMilvus connection alias. Every collection operation passes `using=alias`; cleanup removes only that alias.
- Insertion persists `user_id`. Searches require it and JSON-quote filter values; possession of a `doc_id` alone grants no access.
- `ensure_collection()` rejects mismatched/unreadable dimensions and schemas without a VARCHAR `user_id`. It never drops existing data. `recreate_collection()` is explicitly destructive and is not called by upload.
- Deploy into a new collection and re-upload. Existing unowned chunks cannot be assigned owners reliably from their vectors alone.
- Actual embedding output determines the dimension. Config hints do not resize embeddings. Same-dimension models may still use incompatible embedding spaces; model changes require re-indexing.
- Search uses strong consistency so the next request can find a just-uploaded document despite using a separate connection.
- `RetrievedChunk.chunk_id` is the stored primary key. `get_connection_status()` only reports local SDK connection state.

## Configuration and lifecycle

Backend config loads root `.env`, then `backend/.env` with `override=True`. `get_config()` caches settings. Restart after changing them. Docker injects env values but excludes `.env` files from the image, so file-based override does not shadow container settings.

`get_embedder()` caches a synchronous OpenRouter client and probes the embedding endpoint on first construction. That probe is an external request. Chat providers are request-scoped and closed at pipeline shutdown.

`GET /health` is process liveness only, deliberately independent of paid APIs and remote stores. A successful health check does not prove Zilliz, Supabase or OpenRouter are configured correctly.

## Verification layers

- **pytest:** real routing, pipeline, provider and SSE boundaries with external services mocked; adapter tests exercise owner filters, schema preservation, local/cloud config and connection isolation.
- **Vitest:** HTTP/SSE contract, middleware cookie propagation, callback redirects and signup PKCE preservation.
- **Playwright:** actual Next.js Server Actions, browser cookie session, upload and SSE against local HTTP service fixtures. This verifies integration wiring, not live cloud credentials or Google OAuth.
- **Production smoke test:** real sign-in, PDF upload, storage retention, Zilliz search and streaming through Caddy. See `DEPLOYMENT.md`.
