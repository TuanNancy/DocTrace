# DocTrace / Baymax — Architecture

## Boundaries

- `backend/app/main.py` mounts upload, documents and chat routers. Authentication resolves the user through Supabase; clients cannot select another owner.
- `services/document_repository.py` accesses Supabase PostgREST using a backend service-role key. Every user-facing read is owner-scoped. Apply migration 001 then 002; lifecycle transitions and the transactional outbox live in `002_rq_document_jobs.sql`.
- `services/supabase_pdf_storage.py` owns original PDF operations. Synchronous boto3 and Milvus calls run in threadpools.
- `services/pdf_indexing.py:index_pdf_bytes()` extracts text, chunks, embeds and inserts into Milvus. Temporary-file and vector-connection cleanup stays here.
- `app.dispatcher` delivers PostgreSQL outbox operations to Redis using `services/job_queue.py`. `app.worker` starts standard RQ workers with JSON serialization and the retry scheduler. `jobs/documents.py` contains importable task functions; clients/connections are created in the work horse, after fork.
- `frontend/src/app/(workspace)/layout.tsx` owns the shared provider and shell for `/chat` and `/documents`. `WorkspaceProvider` keeps authentication, catalog, upload and transient chat state across client navigation. Reload discards chat; documents remain server-side.

## Upload and indexing

```text
POST /api/upload
  → authenticate, enforce upload capacity, validate MIME/extension/header/size
  → create owner-scoped documents row (uploading)
  → retain original PDF in private Storage
  → request_document_operation(index): atomically update metadata + insert outbox → 202

python -m app.dispatcher
  → enqueue unique operation_id-delivery in Redis, with timeout and Retry(max=2, interval=[10,30])

python -m app.worker (RQ + scheduler)
  → begin_document_attempt: verify current operation/delivery, register a new generation
  → download PDF → index_pdf_bytes(..., doc_id=attempt_id, user_id=owner)
  → finish_document_attempt: atomically publish only the current, unexpired attempt
```

The public document UUID and the Milvus generation UUID are different. A retry never writes into another attempt's index. The router resolves `documents.active_index_id` before retrieval; citation payloads retain the public document UUID.

RQ owns execution heartbeats, timeout enforcement, failed-job registries and scheduled retries. PostgreSQL has no renewable worker lease. A fixed publication deadline (job timeout + 60 seconds) bounds the authority of an attempt even if Redis is lost. `operation_id` tracks user intent; `delivery` fences replaced Redis deliveries; `attempt_id` is a fresh generation UUID per execution. All lifecycle RPCs lock document before operation.

Each operation has a durable budget of three actual attempts, including crash recovery. Ordinary failures release the attempt and leave a 10/30-second backoff; `InvalidPDFError` is a terminal business failure. The dispatcher respects healthy RQ queued/started/scheduled states. For lost or terminal jobs it uses compare-and-swap recovery, waiting for any outstanding publication deadline before replacement. An expired publication deadline permits recovery even if a stale Redis started key remains without its registry entry. An RQ retry arriving while an interrupted SQL attempt is still outstanding does no work; after the deadline the dispatcher creates a new delivery. Recovery latency includes this deadline, RQ maintenance and dispatch polling.

`202` acknowledges retained bytes plus durable intent, not necessarily successful Redis delivery. Redis outages leave outbox operations pending. `unique=True` deduplicates enqueue retries; database guards also protect against duplicate execution. A Redis connection error is never interpreted as a missing job. Redis AOF `everysec` reduces loss but is not the source of durability for user intent.

A lost HTTP response from publication can mean the transaction committed. Tasks reread metadata before reporting failure. Cleanup is independent: it only deletes registered generations past their cleanup deadline, excluding published/live-attempt generations. Postgres remains the source of document status even when RQ result keys expire. A finished RQ job may have reported an invalid PDF or ignored a superseded operation; it does not necessarily mean the document is ready.

## Deletion

`DELETE /api/documents/{id}` installs a new delete operation, marks pending index intent superseded and clears `active_index_id` immediately. New chat/source reads are rejected. Queued stale index tasks become no-ops; an already running index may finish, but cannot publish. Deletion waits for outstanding index attempts to acknowledge completion or reach their fixed deadlines, then removes all recorded generations and the original PDF.

Cleanup operations are idempotent. Partial failure becomes `delete_error`; retry preserves the deletion intent. Deleted rows are tombstones excluded from library/RLS reads, retaining generation metadata for cleanup rather than erasing the audit of unfinished external operations.

Every 30 seconds the dispatcher schedules due cleanup jobs and recovers `uploading` rows older than 15 minutes. Cleanup first becomes due one minute after publication/deletion and repeats hourly; unfinished generations are eligible after their attempt deadline plus 60 seconds. This catches remote writes finishing after process termination. Cleanup tasks have independent RQ retry and result expiry, and failed cleanup is scheduled again. Generation registrations and tombstones are retained for repeated physical cleanup.

## RAG and citation contract

1. Validate the owned document is ready and resolve its published index.
2. `RAGPipeline.retrieve_chunks()` uses owner-scoped vector search for specific questions. Summaries use every document chunk in original page/chunk order, bypassing query embeddings and similarity thresholds.
3. Ordinary retrieval is trimmed to the context budget **before** assigning citation numbers. The router emits the same numbered chunks that `stream_answer()` receives.
4. Context labels include stable `[n]` IDs and page numbers. Long summaries preserve those IDs through bounded reduction steps.
5. Emit `sources`, streamed `token`, optional `error`, then `done` with the JSON string `"[DONE]"`.

Source payload: `{citation_id, chunk_id, doc_id, page, source, score}`. Summary scores are `null`, not a confidence percentage. Original text is fetched on demand from `/api/documents/{id}/chunks/{chunk_id}` using both owner and active-generation filters. `/file` returns a 300-second signed URL; the UI adds `#page=N`.

`load_pdf_pages()` converts PyPDFLoader's zero-based page index to a one-based physical PDF page and replaces its temporary source path with the original filename. Downstream chunking preserves those values.

ReactMarkdown + GFM render assistant messages without raw HTML. The citation plugin transforms text nodes, leaving code and existing links intact, and makes only known IDs interactive. Clear/document changes cancel streams; stopping retains a partial answer. Backend queries remain single-turn.

## Configuration and storage invariants

- `AppConfig(...)` is environment-independent. `from_env()` parses a mapping/environment. `get_config()` loads root `.env`, then overriding `backend/.env`, once per process.
- `RAG_MODEL` and `EMBEDDING_MODEL` have no implicit model fallback. Embedding dimensions come from API vectors; constructing an embedder also probes the API.
- Milvus supports host/port and URI/token. URI defaults to AUTOINDEX. Requests own their connection alias; reads use Strong consistency so newly published uploads are immediately queryable.
- `ensure_collection()` rejects incompatible dimensions/owner schemas. Only explicit `recreate_collection()` deletes a collection.
- Postgres RLS allows authenticated users to read their own live documents. Mutations and job RPCs are service-role-only. No service-role/S3/LLM secret belongs in frontend env.
- Frontend middleware protects both `/chat` and `/documents`. API URL is an origin without `/api`; no API URL means demo upload/chat, while Auth still uses Supabase.

## Verification and deployment

- pytest mocks database/storage/provider boundaries; chat tests exercise the real pipeline/provider/SSE. TestClient overrides Auth, while dedicated tests exercise the real auth dependency with mocked HTTP.
- `python scripts/verify_document_queue.py` applies 001→002 to disposable PostgreSQL, checks RLS/concurrent fencing, then uses real PostgREST, Redis and two Linux RQ workers to exercise delivery, restart, retry, kill and deletion. Only PDF/embedding/S3/Milvus boundaries are faked. It builds a disposable backend image unless `--api-image` is supplied.
- Vitest covers transport, cancellation, Markdown and auth. Playwright runs real UI/cookies with loopback Auth/API fixtures; it does not validate real cloud services.
- Root Compose runs Redis and vector infrastructure; profile `jobs` runs Linux worker/dispatcher containers. Production Compose runs API, Redis, dispatcher, RQ worker, Nginx and on-demand Certbot. `/health` is API process liveness only. See `DEPLOYMENT.md`.
