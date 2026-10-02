# DocTrace / Baymax — Architecture

## Boundaries

- `backend/app/main.py` mounts upload, documents and chat routers. Authentication resolves the user through Supabase; clients cannot select another owner.
- `services/document_repository.py` accesses Supabase PostgREST using a backend service-role key. Every user-facing read is owner-scoped. All lifecycle transitions are transactional SQL RPCs in `backend/migrations/001_document_library.sql`.
- `services/supabase_pdf_storage.py` owns original PDF operations. Synchronous boto3 and Milvus calls run in threadpools.
- `services/pdf_indexing.py:index_pdf_bytes()` extracts text, chunks, embeds and inserts into Milvus. Temporary-file and vector-connection cleanup stays here.
- `app.worker` claims durable jobs; the API does not run indexing or deletion in request-local background tasks.
- `frontend/src/app/(workspace)/layout.tsx` owns the shared provider and shell for `/chat` and `/documents`. `WorkspaceProvider` keeps authentication, catalog, upload and transient chat state across client navigation. Reload discards chat; documents remain server-side.

## Upload and indexing

```text
POST /api/upload
  → authenticate, enforce upload capacity, validate MIME/extension/header/size
  → create owner-scoped documents row (uploading)
  → retain original PDF in private Storage
  → queue_document_job(index) → 202, status queued

python -m app.worker
  → claim_document_job: SKIP LOCKED, attempts, lease + unique generation token
  → download PDF → index_pdf_bytes(..., doc_id=generation_token, user_id=owner)
  → finish_document_job: publish active_index_id only if lease is still valid
  → clean obsolete generations
```

The public document UUID and the Milvus generation UUID are different. A retry never writes into another attempt's index. The router resolves `documents.active_index_id` before retrieval; citation payloads retain the public document UUID.

Workers renew leases while processing. Expired jobs are claimable after a restart; three interrupted claims become an actionable error. Failed indexing records a safe error and cleans partial chunks. Stale `uploading` rows become errors after 15 minutes. All generation IDs remain registered for retry/deletion cleanup.

A lost HTTP response from `finish_document_job` can still mean the transaction committed. Cleanup rereads the active generation before deleting an unpublished attempt.

## Deletion

`DELETE /api/documents/{id}` installs `deleting` and clears `active_index_id` immediately. New chat/source reads are rejected. A delete job waits for a live indexing lease, deletes all recorded vector generations and the original PDF, then records `deleted`. A worker finishing an index after deletion was requested cannot publish it.

Cleanup operations are idempotent. Partial failure becomes `delete_error`; retry preserves the deletion intent. Deleted rows are tombstones excluded from library/RLS reads, retaining generation metadata for cleanup rather than erasing the audit of unfinished external operations.

Workers also sweep due tombstones (first after five minutes, then hourly). This catches remote writes that finish after cancellation/lease expiry; Python cannot forcibly stop a synchronous S3/Milvus thread already in flight.

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
- `python scripts/verify_document_queue.py` from `backend/` applies real SQL to disposable PostgreSQL and checks RLS, recovery and fencing.
- Vitest covers transport, cancellation, Markdown and auth. Playwright runs real UI/cookies with loopback Auth/API fixtures; it does not validate real cloud services.
- Root Compose runs vector infrastructure. Production Compose runs API, worker, Nginx and on-demand Certbot; frontend deploys separately. `/health` is API process liveness only. See `DEPLOYMENT.md`.
