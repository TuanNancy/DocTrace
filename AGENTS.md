# Repository Notes

## Runtime boundaries

- Backend paths below are relative to `backend/app/`. See `ARCHITECTURE.md` for lifecycle and recovery details.
- FastAPI starts in `backend/app/main.py`. Upload retains the PDF in Supabase Storage, then commits Redis catalog metadata + RQ enqueue before returning 202. Indexing errors belong to document status. Supabase supplies Auth/Storage; no application SQL migrations or metadata service-role key are required.
- `services/document_repository.py` owns Redis hashes and per-user sorted sets under `doctrace:library:v2`; catalog keys have no TTL. RQ result expiry must not remove ready documents. Every public read/mutation checks the authenticated owner; Milvus queries also filter `user_id`.
- `services/job_queue.py` enqueues inside the repository's WATCH/MULTI transaction. RQ 2.12 `unique=True` ignores a supplied pipeline: do not enable it here. API/worker need the same Redis and queue (`documents-v2`); legacy `documents` jobs have incompatible payloads.
- `app.worker` runs RQ with JSON serialization and scheduler; `jobs/documents.py` creates task clients after fork. Keep the worker's blocking Redis timeout separate from the producer's short timeout. `job_queue.MAX_RETRIES` also controls attempt numbering; retries wait 10/30 seconds. Redis/RQ/boto3/Milvus blocking calls run off-loop.
- Public `doc_id` differs from the Milvus generation: resolve `active_index_id`. A retry registers a fresh generation; only current job/attempt may publish. Reread metadata after an uncertain enqueue/publication before cleanup or failure. Delete/retry rejects live RQ jobs, including scheduled retries; RQ `finished` alone never implies ready.
- `services/pdf_indexing.py` owns extraction/chunking/embedding/insertion and temporary-file cleanup. `load_pdf_pages()` uses pypdf and preserves the original filename and **one-based physical PDF pages** (including blank pages) for `#page=N`.
- Chat retrieves once, bounds ordinary context before citation numbering, and streams using those same chunks. Summaries read all owner-scoped chunks without query embeddings; preserve citation IDs through reduction (`score: null`).
- SSE sources require `citation_id`, `chunk_id`, public `doc_id`, `page`, `source`, `score`; token is a JSON text delta, error is `{message}`, done is the JSON string `"[DONE]"`. Keep `routers/chat.py`, frontend types, `src/lib/sse.ts` and fixtures aligned; EOF without done is an error. Citation lookup checks owner + active generation; request fresh 300-second PDF links when opening.

## Frontend ownership

- `frontend/src/app/(workspace)/layout.tsx` mounts `WorkspaceProvider` for `/chat` and `/documents`. It owns auth/catalog and the chat/upload hooks; `ChatWindow` and `UploadZone` receive required sessions, not their own hook instances. Navigation preserves state; switching PDFs/reloading clears chat. Backend chat is single-turn.
- `frontend/src/lib/api.ts` owns HTTP transport; `sse.ts` validates/decodes events. Preserve hook cancellation and late-response rejection. Markdown citation transforms must leave code/existing links intact and bind only known IDs.
- Supabase helpers live in `frontend/src/lib/supabase/`. Browser singleton is SDK-managed; server clients are per request. Middleware verifies `getUser()` for both workspace routes and preserves refreshed cookies on redirects plus `private, no-store` headers.
- Workspace styling stays light independently of the landing-page theme; Inter via `--font-sans` applies throughout.

## Commands and test boundaries

- CI uses Python 3.12 / Node 22. Commands run in `backend/` or `frontend/`, except Docker/deploy commands at root.
- Backend: `python -m pip install -r requirements-dev.txt` includes runtime + tests. API: `uvicorn app.main:app --reload --port 8000`. Linux worker: `python -m app.worker`. On macOS use root `docker compose --profile jobs up -d --build worker` for Linux RQ fork behavior.
- Backend tests: `python -m pytest`; focused: `python -m pytest tests/test_document_repository.py tests/test_worker.py` or `python -m pytest tests/test_chat.py::test_chat_sse_stream`. `tests/conftest.py` seeds isolated config before app import. Repository tests use fakeredis; external Auth/provider/storage calls are mocked.
- Backend: `python scripts/verify_document_queue.py [--api-image doctrace-api:verify]` uses isolated real Redis + Linux RQ workers and `tests/fixtures/queue_worker.py` for PDF/AI/S3/Milvus. It builds an image when omitted; test dependencies, scripts and fixtures are excluded from the production image. Docker must be running/unpaused.
- Frontend: `npm ci`; CI order: `npm run typecheck`, `npm run lint`, `npm test`, `npm run test:e2e`, `npm run build`. Focused: `npm test -- tests/ChatWindow.test.tsx`. Build needs public Supabase settings (CI has placeholders).
- Install Chromium: `npx playwright install chromium` (`--with-deps` on Linux CI). Playwright owns ports 4310/4311 for Next + fake Auth/API; screenshots go to ignored `test-results/`. Headless shell downloads PDF links; assert the URL/page fragment rather than Chrome's viewer.
- Route moves can leave stale `.next/types`; regenerate ignored Next output rather than changing TypeScript paths. Preserve root `.gitignore` exceptions for `frontend/src/lib/` (Python's `lib/` rule otherwise hides it).
- Proxy checks at root: `docker build -t doctrace-api:verify ./backend`, then `python deploy/tests/verify_nginx.py --api-image doctrace-api:verify`. This uses disposable containers and self-signed TLS, not real cloud/ACME. Certificate orchestration check: use the Docker command in `.github/workflows/verify.yml` (test scripts are mounted, not included in the image).

## Configuration and operations

- `AppConfig(...)` never reads env; `from_env(mapping)` parses settings. `get_config()` loads root `.env`, then `backend/.env` overriding even process env, and caches once. Restart API/worker after edits. Public `NEXT_PUBLIC_*` settings require frontend rebuild; API URL is an origin without `/api`. Empty API URL enables demo upload/chat; Auth still uses Supabase.
- Pass the same config through pipeline/factories/embedder. `RAG_MODEL`/`EMBEDDING_MODEL` are explicit; cached embedder construction makes a real dimension-probe request. Milvus URI mode defaults to AUTOINDEX; preserve request-owned aliases, Strong consistency and cancellation cleanup. `ensure_collection()` rejects incompatibility; only `recreate_collection()` deletes all chunks.
- Redis AOF/volume holds the library and queue; `down -v` loses them (and production certificates). Old PostgreSQL users re-upload; see `DEPLOYMENT.md` cutover. Do not flush Redis, run legacy workers on the new queue, or recreate Milvus to populate metadata; PDF/vector data cannot automatically rebuild the catalog.
- Local Compose starts Redis + Milvus infrastructure; `jobs` adds the worker. Production Compose does **not** run Milvus or frontend: provide a reachable vector endpoint and deploy frontend separately. API and worker share `REDIS_URL=redis://redis:6379/0`; container localhost is not the host.
- Worker shutdown grace is 16m; keep it above job timeouts (index 900s, delete 300s). Bootstrap certificates only initially; later use `docker compose --env-file .env.production -f compose.production.yml up -d --build --wait api worker nginx`.
- Nginx templates render at startup: recreate after template edits. Preserve unbuffered uploads/SSE, renewal validation-before-reload and Compose project/certificate volumes. systemd assumes `/opt/DocTrace`; see `DEPLOYMENT.md`.
- `/health` is process liveness; `get_connection_status()` is local connection state, neither verifies cloud/worker health.
