# DocTrace / Baymax — Architecture

## Boundaries

- `backend/app/main.py` mounts upload, documents, chat, conversations, workspace and usage routers. Authentication resolves the user through Supabase; `core/workspace.py` then validates `X-Workspace-Id` and `services/workspaces.py` re-checks active membership in Postgres. The header selects a tenant; it never grants access.
- `services/workspaces.py` owns the workspace control plane in schema `doctrace`: personal/team workspaces, memberships and roles, archive/restore, plan workspace limits, and the member-has-documents guard. `routers/workspaces.py` selects a workspace from the path, not from `X-Workspace-Id`.
- Documents stay private to their owner. Every read/mutation requires matching `workspace_id` and `owner_user_id`; same-workspace members cannot read each other's PDFs, chunks or chat. Cross-workspace, cross-owner and admin content requests return `404`.
- `services/document_repository.py` stores metadata in Redis hashes under `doctrace:library:v2:document:{doc_id}`. Workspace/user, workspace and global sorted sets provide the private library, workspace counts and admin metadata index. These keys have no TTL and are separate from RQ job/result keys. The legacy per-user index is still written during the P1 rollout for rollback compatibility.
- `services/supabase_pdf_storage.py` owns original PDF operations. Synchronous boto3 and Milvus calls run in threadpools.
- `services/pdf_indexing.py:index_pdf_bytes()` extracts text, chunks, embeds and inserts into Milvus. Temporary-file and vector-connection cleanup stays here. Milvus still stores the owner id; no schema change in P1.
- The API enqueues directly through `services/job_queue.py`. `app.worker` starts standard RQ workers with JSON serialization and the retry scheduler. `jobs/documents.py` contains task functions; Redis/storage clients are created after fork. Redis/RQ calls from async code run in threadpools.
- `frontend/src/app/(workspace)/layout.tsx` owns the shared provider and shell for `/chat`, `/documents` and `/usage`. `WorkspaceProvider` keeps authentication, workspace membership, catalog, upload and chat state across client navigation. Switching workspace aborts in-flight work and clears document/chat/source state. Reload restores the latest ready conversation for the workspace; “Chat mới” deletes the current transcript.

## Upload and indexing

```text
POST /api/upload
  → authenticate, require X-Workspace-Id + active membership
  → enforce upload capacity, validate MIME/extension/header/size
  → check Redis availability
  → retain original PDF in private Storage
  → WATCH/MULTI: catalog record (workspace_id, owner_user_id)
       + workspace/user, workspace, global and legacy indexes + RQ job → EXEC → 202

python -m app.worker (RQ + scheduler)
  → verify current job/attempt, register a fresh generation
  → remove registered partial indexes from earlier failed attempts
  → download PDF → index_pdf_bytes(..., doc_id=attempt_id, user_id=owner)
  → publish active_index_id only if job/attempt still matches
```

Create/delete invariants update the user, workspace and global sets in the same transaction as the hash and enqueue. A pre-P1 record without `workspace_id`/`owner_user_id` is normalized on read to the owner's personal workspace (`workspace_id = user_id`); `scripts/backfill_workspaces.py` optionally persists that metadata and rebuilds every index idempotently. It never flushes Redis or touches Milvus.

The public document UUID and the Milvus generation UUID are different. A retry never writes into another attempt's index. The router resolves Redis metadata's `active_index_id` before retrieval; citation payloads retain the public document UUID.

RQ owns execution heartbeats, timeouts, abandoned-job maintenance and `Retry(max=2, interval=[10,30])`. The task derives its attempt number from RQ's remaining retries; repeated entry for the same attempt is a no-op. A manual retry gets a new job ID. Redis WATCH protects concurrent updates and enqueue; RQ 2.12's `unique=True` must not be used here because it ignores the supplied pipeline.

`InvalidPDFError` records a terminal business error without more embedding retries. Transient errors are raised for RQ to retry; final failure persists `error` or `delete_error`. On library reads, pending documents are reconciled against RQ: scheduled jobs stay queued, failed/stopped/missing jobs become errors. This also covers failure before task entry and process termination without callbacks. Business outcomes survive RQ result expiration; RQ `finished` alone never implies `ready`.

`202` acknowledges retained PDF bytes and confirmed Redis metadata/enqueue. Redis outages cause `503`; connection errors never look like missing documents/jobs. If enqueue's reply is lost, the API rereads metadata. It removes the PDF only when no enqueue was committed; uncertain outcomes retain the PDF. A lost publication reply is also reread before recording failure.

### Recovery limits

Redis is the sole source of library/queue state. AOF `everysec` and a persistent volume survive ordinary restarts but may lose recent writes on a crash; loss of the volume loses the library. PDFs/vectors do not rebuild it automatically. A dead worker's job waits for RQ heartbeat/registry maintenance before retry/failure; this is not immediate. Missing job keys allow manual retry from the library. There is no independent outbox, renewable SQL lease or periodic tombstone sweep. A process dying between Storage upload and Redis commit can leave an unlisted PDF; remote writes completing after a killed task can leave unused vectors requiring manual cleanup. Re-upload is the chosen cutover for the old PostgreSQL library.

If the killed worker also owned the retry scheduler, its lock must expire before another scheduler takes over (about 61 seconds with RQ defaults). An idle worker can block on dequeue for 405 seconds before checking maintenance again, even though the configured maintenance interval is 30 seconds. Retry recovery after a hard kill can therefore take several minutes.

## Deletion

`DELETE /api/documents/{id}` accepts ready/error/delete_error documents only after their RQ job is terminal or missing. Queued/started/scheduled/deferred jobs return `409`; the UI disables deletion while indexing. Acceptance atomically clears `active_index_id`, marks `deleting` and enqueues deletion. Chat/source reads are then rejected. The task removes every registered generation and the original PDF.

Cleanup is idempotent. Partial failures use RQ retry, then `delete_error`; manual retry continues deletion. On success, the document leaves every user/workspace/global index and becomes a hidden tombstone so lost success responses can be reconciled. Registered generations remain available through all retries. The frontend disables selection during deletion and switching workspace drops the deleted document's pending responses. The document router also hides that document's transcripts before queueing deletion.

## RAG and citation contract

1. Validate `X-Workspace-Id` membership, then the document is ready, belongs to that workspace and is owned by the current user; resolve its published index.
2. Reject a repeated client `request_id` before spending a burst token or quota question, then apply the Redis burst limiter and atomically admit the request in Postgres (`chat_requests` insert + monthly `usage_counters` increment + conversation/user message/assistant placeholder). A quota denial returns JSON before SSE starts and leaves no transcript row.
3. `RAGPipeline.retrieve_chunks()` uses owner-scoped vector search for specific questions. Summaries use every document chunk in original page/chunk order, bypassing query embeddings and similarity thresholds.
4. Ordinary retrieval is trimmed to the context budget **before** assigning citation numbers. The router emits the same numbered chunks that `stream_answer()` receives.
5. Context labels include stable `[n]` IDs and page numbers. Long summaries preserve those IDs through bounded reduction steps.
6. Emit `sources`, streamed `token`, optional `error`, then `done` with the JSON string `"[DONE]"`.
7. Finalize the assistant message and `chat_requests` as `completed`, `failed` or `interrupted` in the same shielded scope that flushes provider usage, so a disconnected browser cannot leave the request or transcript in `streaming`. The response also carries additive `X-Conversation-Id`.

Source payload: `{citation_id, chunk_id, doc_id, page, source, score}`. Summary scores are `null`, not a confidence percentage. Original text is fetched on demand from `/api/documents/{id}/chunks/{chunk_id}` using workspace, owner and active-generation filters. `/file` returns a 300-second signed URL; the UI adds `#page=N`.

`load_pdf_pages()` reads text directly with pypdf, numbers physical PDF pages from one (including blank pages), and retains the original filename. Recursive text splitting preserves those values. Indexing returns chunk counts/warnings; Redis owns document status and timestamps.

ReactMarkdown + GFM render assistant messages without raw HTML. The citation plugin transforms text nodes, leaving code and existing links intact, and makes only known IDs interactive. Clear/document changes cancel streams; stopping retains a partial answer. Backend queries remain single-turn.

## Transcripts and retention

- `services/transcripts.py` owns conversation admission helpers, owner-scoped reads/deletion, streaming finalization, stale-citation marking and retention. `conversations` and `messages` already exist in migration `0001`; P3 adds no migration.
- A conversation is unique per active `(workspace_id, user_id, doc_id)` via `ux_conversations_active_document`. Every query filters both workspace and the authenticated user, so a workspace owner cannot read a member's transcript. `GET /api/conversations` returns summaries (optionally filtered by `doc_id`); `GET /api/conversations/{id}` returns messages and sources; `DELETE` physically removes the current user's conversation and cascades messages.
- Admission inserts the user message and a `pending` assistant placeholder in the quota transaction and links `chat_requests.conversation_id`. Streaming marks `streaming`, then `complete`/`error`/`interrupted` with partial content and the final source snapshot. Repeating a finalize is a no-op.
- Assistant messages keep the `index_id` used for retrieval. Reads compare it with the document's current status/`active_index_id`; a missing, non-ready or re-indexed document marks the message and every source `stale`. The frontend renders stale citations as plain text, disables their source cards and does not fetch an old chunk from the new generation.
- Accepting document deletion hides its transcripts immediately. `TRANSCRIPT_DELETE_MODE=cascade` deletes them at once; the default `retain_30d` sets `document_deleted_at` and `purge_after = now() + TRANSCRIPT_RETENTION_DAYS`. `python -m app.purge_transcripts` deletes expired conversations; `provider_calls` accounting rows intentionally survive without transcript content. A failed deletion stays hidden and can be retried.

## Quota and idempotency

- `services/quotas.py` owns workspace plan limits, monthly chat admission, the document limit lookup and the usage aggregate. Limits come from `doctrace.plan_limits` (free `10/5/1`, pro `100/50/10` for questions/documents/workspaces) and are evaluated per workspace.
- Chat admission is one Postgres transaction: insert `chat_requests` with `ON CONFLICT DO NOTHING`, ensure the current UTC-month `usage_counters` row, then `UPDATE ... SET used = used + 1 WHERE used < :limit RETURNING used`. A missing updated row rolls back the request insert and returns `429 quota_exceeded` with `reset_at`; concurrent requests therefore cannot overshoot. The frontend sends `request_id`; a duplicate returns `409 request_completed`, `request_in_progress` or `request_failed` without reserving again.
- `_stream_chat_sse` marks the request `streaming` and finalizes it, the assistant message and provider usage under a shielded scope, so cancellation still records state. Quota counts admitted questions even if the stream later fails.
- Upload checks `ZCARD workspace:{wid}:documents` before Storage and `DocumentRepository.create(..., limit=...)` re-checks it after `WATCH` inside the catalog/enqueue transaction. If the atomic re-check rejects the upload, the router deletes the already-retained PDF. Deleted documents free a slot only after reaching `deleted`; `error`/`delete_error` records still count.
- `GET /api/usage` merges the Postgres counters/costs with the Redis document count. Owners receive a per-user breakdown; members receive only their own rows. `provider_calls` costs remain integer micro-USD and keep `unknown` call counts visible.
- Redis burst windows in `services/rate_limiter.py` are separate from monthly quotas. Both return 429, but burst denials use `code: "rate_limited"` and a short `Retry-After`; quota denials use `code: "quota_exceeded"` and `reset_at`.

## Provider usage and cost

- `providers/usage.py` models one logical metered call (`query_embedding`, `index_embedding`, `summary`, `answer`). A `ProviderCall` keeps token counts, generation id, latency and integer micro-USD cost. Missing cost stays `None`/`unknown`; if any embedding batch omits cost, the aggregate stays unknown rather than under-reporting.
- `providers/openrouter.py` captures non-streaming usage/id and the final streaming usage chunk even when `choices` is empty. It requests `stream_options.include_usage`, disables SDK retries so one logical call maps to one HTTP attempt, marks cancellation/errors, and exposes `fetch_generation()` for `GET /generation`.
- `providers/embeddings.py` accumulates batch token/cost usage into one `ProviderCall`; the dimension probe is excluded as infrastructure overhead. Embedding responses are not chat generations and are never reconciled through `/generation`.
- `services/provider_calls.py` persists rows into `doctrace.provider_calls` (already created by migration `0001`). `UsageAttribution` carries workspace/user/document/job/request ids; malformed UUIDs become `NULL`. Tracking is disabled without `DATABASE_URL` and is best effort: reconciliation or database failures never fail chat or indexing.
- Chat creates one collector per request and flushes it under a shielded scope after the stream, so a browser disconnect still records costs. The worker uses one collector per index attempt and flushes it in `finally`; delete jobs record nothing. A repeated generation id upserts the existing row, never a duplicate.
- `SUMMARY_MAX_CALLS` (default 8) caps summary/reduction calls before the answer call. An oversized overview is rejected before spending, or stops after earlier completed calls, whose rows still flush. Costs never appear in SSE events.
- Rows contain identifiers, token counts, status, latency and raw provider usage only; no prompt or document text. Deleting a workspace nulls the workspace FK while retaining accounting rows.

## Configuration and storage invariants

- `services/rate_limiter.py` gates valid authenticated upload/chat/index-retry attempts using Redis-time sliding windows: 5/600s, 10/60s and 3/600s per owner by default. `RATE_LIMIT_*` settings are shared by all API instances; `RATE_LIMIT_ENABLED=false` bypasses quota checks. Changing models does not change these quotas.
- Lua atomically prunes/counts/adds unique admissions in `doctrace:ratelimit:v1` sorted sets with TTL. Denials neither add events nor renew expiry. Admitted attempts are not refunded after downstream errors, and uncertain Redis replies are not retried. Burst exhaustion is HTTP 429 with `code=rate_limited` and `Retry-After`; Redis failure is 503. These windows only bound short bursts; monthly plan quota is enforced separately in Postgres. Check before Storage/enqueue and before SSE starts; delete retries and library reads are exempt. The existing upload capacity limiter remains per-process, not a worker limit.
- API CORS exposes `Retry-After` and `X-Conversation-Id`; both fetch and XHR preserve `Retry-After` for the frontend's wait message. The UI treats `quota_exceeded` as a plan/reset message and `rate_limited` as a wait. User quotas do not bound provider calls per indexing job or IP traffic before multipart parsing/Auth.

- `AppConfig(...)` is environment-independent. `from_env()` parses a mapping/environment. `get_config()` loads root `.env`, then overriding `backend/.env`, once per process.
- `RAG_MODEL` and `EMBEDDING_MODEL` have no implicit model fallback. Embedding dimensions come from API vectors; constructing an embedder also probes the API.
- Milvus supports host/port and URI/token. URI defaults to AUTOINDEX. Requests own their connection alias; reads use Strong consistency so newly published uploads are immediately queryable.
- `ensure_collection()` rejects incompatible dimensions/owner schemas. Only explicit `recreate_collection()` deletes a collection.
- Supabase provides Auth and private PDF Storage; Postgres holds the `doctrace` control plane. Redis is server-only; application workspace + owner checks protect every library operation, and Milvus queries also filter by owner. S3/LLM credentials belong only in backend env.
- Upload, documents, files/chunks, chat, conversations and usage require `X-Workspace-Id`. Missing header is `400 workspace_required`; malformed UUID is `400 workspace_invalid`; valid but archived/non-member is `404 workspace_not_found`. Authentication runs before header validation.
- A demo personal workspace uses the owner's user id, so a free user has one active workspace until an admin upgrades the plan. Workspace removal is blocked while its member still has catalogued documents; removing a member never transfers or deletes their PDFs.
- Frontend middleware protects `/chat`, `/documents` and `/usage`. API URL is an origin without `/api`; no API URL means demo upload/chat, while Auth still uses Supabase.

## Verification and deployment

- pytest uses isolated fakeredis for repository/RQ serialization, and mocks Storage/provider boundaries. Chat tests exercise the real pipeline/provider/SSE. TestClient overrides Auth, the workspace dependency, repository, rate limiter, quota and transcript services; dedicated tests cover header validation, workspace routes, private catalog scope, workspace counts, legacy normalization and idempotent backfill, streaming usage, embedding aggregation, summary caps, provider-call persistence, duplicate admissions, status transitions and transcript routes. Postgres workspace/quota/transcript tests use testcontainers and skip without Docker.
- Router tests also override `get_rate_limiter`; `python scripts/verify_rate_limits.py` verifies the actual Lua against disposable Docker Redis, including cross-process quota, concurrent admission, expiry and outage behavior. `tests/test_quotas_pg.py` checks the free and pro concurrency limits, duplicate ids, period rollover and owner/member usage breakdown. `tests/test_transcripts_pg.py` checks admission ordering, owner/workspace scoping, both retention modes, purge and stale generations.
- `python scripts/verify_document_queue.py` uses real Redis and two Linux RQ workers to exercise transactions, owner scope, restart/outage, retry/timeout, kill and deletion. Only PDF/embedding/S3/Milvus boundaries are faked. It builds a disposable image unless `--api-image` is supplied. The container-kill case targets the scheduler owner, advances abandoned-job registry time, and waits for the killed scheduler's lease to expire before restarting it.
- Vitest covers transport (including `X-Workspace-Id`, `request_id`, conversation/usage routes and structured errors), cancellation, transcript restore, stale citations, workspace switching, Markdown, usage and auth. Playwright runs real UI/cookies with loopback Auth/API fixtures, verifies workspace isolation, transcript restore after reload/new chat, usage rendering, and does not validate real cloud services.
- Root Compose runs Redis and vector infrastructure; profile `jobs` runs the Linux worker. Production Compose runs API, Redis, RQ worker, Nginx and on-demand Certbot. `/health` is API process liveness only. See `DEPLOYMENT.md`.
