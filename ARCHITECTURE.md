# DocTrace / Baymax — Architecture

## Boundaries

- `backend/app/main.py` mounts upload, documents and chat routers. Authentication resolves the user through Supabase; clients cannot select another owner.
- `services/document_repository.py` stores owner-scoped metadata in Redis hashes under `doctrace:library:v2`; per-user sorted sets provide library pagination. These keys have no TTL and are separate from RQ job/result keys.
- `services/supabase_pdf_storage.py` owns original PDF operations. Synchronous boto3 and Milvus calls run in threadpools.
- `services/pdf_indexing.py:index_pdf_bytes()` extracts text, chunks, embeds and inserts into Milvus. Temporary-file and vector-connection cleanup stays here.
- The API enqueues directly through `services/job_queue.py`. `app.worker` starts standard RQ workers with JSON serialization and the retry scheduler. `jobs/documents.py` contains task functions; Redis/storage clients are created after fork. Redis/RQ calls from async code run in threadpools.
- `frontend/src/app/(workspace)/layout.tsx` owns the shared provider and shell for `/chat` and `/documents`. `WorkspaceProvider` keeps authentication, catalog, upload and transient chat state across client navigation. Reload discards chat; documents remain server-side.

## Upload and indexing

```text
POST /api/upload
  → authenticate, enforce upload capacity, validate MIME/extension/header/size
  → check Redis availability
  → retain original PDF in private Storage
  → WATCH/MULTI: catalog record + user index + RQ job → EXEC → 202

python -m app.worker (RQ + scheduler)
  → verify current job/attempt, register a fresh generation
  → remove registered partial indexes from earlier failed attempts
  → download PDF → index_pdf_bytes(..., doc_id=attempt_id, user_id=owner)
  → publish active_index_id only if job/attempt still matches
```

The public document UUID and the Milvus generation UUID are different. A retry never writes into another attempt's index. The router resolves Redis metadata's `active_index_id` before retrieval; citation payloads retain the public document UUID.

RQ owns execution heartbeats, timeouts, abandoned-job maintenance and `Retry(max=2, interval=[10,30])`. The task derives its attempt number from RQ's remaining retries; repeated entry for the same attempt is a no-op. A manual retry gets a new job ID. Redis WATCH protects concurrent updates and enqueue; RQ 2.12's `unique=True` must not be used here because it ignores the supplied pipeline.

`InvalidPDFError` records a terminal business error without more embedding retries. Transient errors are raised for RQ to retry; final failure persists `error` or `delete_error`. On library reads, pending documents are reconciled against RQ: scheduled jobs stay queued, failed/stopped/missing jobs become errors. This also covers failure before task entry and process termination without callbacks. Business outcomes survive RQ result expiration; RQ `finished` alone never implies `ready`.

`202` acknowledges retained PDF bytes and confirmed Redis metadata/enqueue. Redis outages cause `503`; connection errors never look like missing documents/jobs. If enqueue's reply is lost, the API rereads metadata. It removes the PDF only when no enqueue was committed; uncertain outcomes retain the PDF. A lost publication reply is also reread before recording failure.

### Recovery limits

Redis is the sole source of library/queue state. AOF `everysec` and a persistent volume survive ordinary restarts but may lose recent writes on a crash; loss of the volume loses the library. PDFs/vectors do not rebuild it automatically. A dead worker's job waits for RQ heartbeat/registry maintenance before retry/failure; this is not immediate. Missing job keys allow manual retry from the library. There is no independent outbox, renewable SQL lease or periodic tombstone sweep. A process dying between Storage upload and Redis commit can leave an unlisted PDF; remote writes completing after a killed task can leave unused vectors requiring manual cleanup. Re-upload is the chosen cutover for the old PostgreSQL library.

If the killed worker also owned the retry scheduler, its lock must expire before another scheduler takes over (about 61 seconds with RQ defaults). An idle worker can block on dequeue for 405 seconds before checking maintenance again, even though the configured maintenance interval is 30 seconds. Retry recovery after a hard kill can therefore take several minutes.

## Deletion

`DELETE /api/documents/{id}` accepts ready/error/delete_error documents only after their RQ job is terminal or missing. Queued/started/scheduled/deferred jobs return `409`; the UI disables deletion while indexing. Acceptance atomically clears `active_index_id`, marks `deleting` and enqueues deletion. Chat/source reads are then rejected. The task removes every registered generation and the original PDF.

Cleanup is idempotent. Partial failures use RQ retry, then `delete_error`; manual retry continues deletion. On success, the document leaves the user's sorted set and becomes a hidden tombstone so lost success responses can be reconciled. Registered generations remain available through all retries.

## RAG and citation contract

1. Validate the owned document is ready and resolve its published index.
2. `RAGPipeline.retrieve_chunks()` uses owner-scoped vector search for specific questions. Summaries use every document chunk in original page/chunk order, bypassing query embeddings and similarity thresholds.
3. Ordinary retrieval is trimmed to the context budget **before** assigning citation numbers. The router emits the same numbered chunks that `stream_answer()` receives.
4. Context labels include stable `[n]` IDs and page numbers. Long summaries preserve those IDs through bounded reduction steps.
5. Emit `sources`, streamed `token`, optional `error`, then `done` with the JSON string `"[DONE]"`.

Source payload: `{citation_id, chunk_id, doc_id, page, source, score}`. Summary scores are `null`, not a confidence percentage. Original text is fetched on demand from `/api/documents/{id}/chunks/{chunk_id}` using both owner and active-generation filters. `/file` returns a 300-second signed URL; the UI adds `#page=N`.

`load_pdf_pages()` reads text directly with pypdf, numbers physical PDF pages from one (including blank pages), and retains the original filename. Recursive text splitting preserves those values. Indexing returns chunk counts/warnings; Redis owns document status and timestamps.

ReactMarkdown + GFM render assistant messages without raw HTML. The citation plugin transforms text nodes, leaving code and existing links intact, and makes only known IDs interactive. Clear/document changes cancel streams; stopping retains a partial answer. Backend queries remain single-turn.

## Configuration and storage invariants

- `services/rate_limiter.py` gates valid authenticated upload/chat/index-retry attempts using Redis-time sliding windows: 5/600s, 10/60s and 3/600s per owner by default. `RATE_LIMIT_*` settings are shared by all API instances; `RATE_LIMIT_ENABLED=false` bypasses quota checks. Changing models does not change these quotas.
- Lua atomically prunes/counts/adds unique admissions in `doctrace:ratelimit:v1` sorted sets with TTL. Denials neither add events nor renew expiry. Admitted attempts are not refunded after downstream errors, and uncertain Redis replies are not retried. Quota exhaustion is HTTP 429 with `Retry-After`; Redis failure is 503. Check before Storage/enqueue and before SSE starts; delete retries and library reads are exempt. The existing upload capacity limiter remains per-process, not a worker limit.
- API CORS exposes `Retry-After`; both fetch and XHR preserve it for the frontend's wait message. User quotas do not bound provider calls per indexing job or IP traffic before multipart parsing/Auth.

- `AppConfig(...)` is environment-independent. `from_env()` parses a mapping/environment. `get_config()` loads root `.env`, then overriding `backend/.env`, once per process.
- `RAG_MODEL` and `EMBEDDING_MODEL` have no implicit model fallback. Embedding dimensions come from API vectors; constructing an embedder also probes the API.
- Milvus supports host/port and URI/token. URI defaults to AUTOINDEX. Requests own their connection alias; reads use Strong consistency so newly published uploads are immediately queryable.
- `ensure_collection()` rejects incompatible dimensions/owner schemas. Only explicit `recreate_collection()` deletes a collection.
- Supabase provides Auth and private PDF Storage. Redis is server-only; application owner checks protect every library operation, and Milvus queries also filter by owner. S3/LLM credentials belong only in backend env.
- Frontend middleware protects both `/chat` and `/documents`. API URL is an origin without `/api`; no API URL means demo upload/chat, while Auth still uses Supabase.

## Verification and deployment

- pytest uses isolated fakeredis for repository/RQ serialization, and mocks Storage/provider boundaries. Chat tests exercise the real pipeline/provider/SSE. TestClient overrides Auth; dedicated auth tests mock its upstream HTTP.
- Router tests also override `get_rate_limiter`; `python scripts/verify_rate_limits.py` verifies the actual Lua against disposable Docker Redis, including cross-process quota, concurrent admission, expiry and outage behavior.
- `python scripts/verify_document_queue.py` uses real Redis and two Linux RQ workers to exercise transactions, owner scope, restart/outage, retry/timeout, kill and deletion. Only PDF/embedding/S3/Milvus boundaries are faked. It builds a disposable image unless `--api-image` is supplied. The container-kill case targets the scheduler owner, advances abandoned-job registry time, and waits for the killed scheduler's lease to expire before restarting it.
- Vitest covers transport, cancellation, Markdown and auth. Playwright runs real UI/cookies with loopback Auth/API fixtures; it does not validate real cloud services.
- Root Compose runs Redis and vector infrastructure; profile `jobs` runs the Linux worker. Production Compose runs API, Redis, RQ worker, Nginx and on-demand Certbot. `/health` is API process liveness only. See `DEPLOYMENT.md`.
