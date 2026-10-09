# Repository Notes

## Commands and verification

- CI uses Ubuntu 24.04, Python 3.12 / Node 22; Actions run on Node 24. Run Python/npm commands in `backend/`/`frontend/`; Docker/deploy commands run at root.
- Backend setup: `python -m pip install -r requirements-dev.txt` includes runtime + tests. API: `uvicorn app.main:app --reload --port 8000`. Linux worker: `python -m app.worker`; on macOS use `docker compose --profile jobs up -d --build worker` for Linux RQ fork behavior.
- Backend tests: `python -m pytest`; focused: `python -m pytest tests/test_document_repository.py tests/test_worker.py` or `python -m pytest tests/test_chat.py::test_chat_sse_stream`. `tests/conftest.py` seeds isolated config before app import. Repository tests use fakeredis; router tests override Auth, repository and `get_rate_limiter` to avoid developer services.
- Redis integration: `python scripts/verify_rate_limits.py` checks real Lua/TTL/concurrency; `python scripts/verify_document_queue.py` checks transactions and Linux RQ workers with PDF/AI/S3/Milvus fixtures. Both need running Docker and use disposable Redis. Queue verification builds an image unless given `--api-image doctrace-api:verify`.
- Frontend: `npm ci`; CI order: `npm run typecheck`, `npm run lint`, `npm test`, `npm run test:e2e`, `npm run build`. Focused: `npm test -- tests/ChatWindow.test.tsx`. Build needs public Supabase settings; `.github/workflows/verify.yml` supplies placeholders.
- Before E2E: `npx playwright install chromium` (`--with-deps` on Linux CI). Playwright builds then starts Next in production mode with fixture env for both steps; keep ports 4310/4311 free for Next + fake Auth/API. E2E replaces `.next`; rebuild with deployment env before normal `npm start`/deployment. Screenshots go to ignored `test-results/`. Headless shell downloads PDFs; assert the URL/page fragment rather than Chrome's viewer.
- Validate production Compose with fixture env: `BACKEND_ENV_FILE=./deploy/tests/api.env docker compose --env-file .env.production.example -f compose.production.yml config --quiet`.
- Proxy verification: `docker build -t doctrace-api:verify ./backend`, then `python deploy/tests/verify_nginx.py --api-image doctrace-api:verify`. It uses disposable containers/self-signed TLS. Use the certificate-test Docker command in `.github/workflows/verify.yml`; the production image excludes test dependencies, scripts and fixtures, so deploy tests are mounted.

## Runtime boundaries

- Paths in this section are relative to `backend/app/`. See `ARCHITECTURE.md` for lifecycle and recovery details.
- FastAPI starts in `main.py`. Upload retains the PDF in Supabase Storage, then commits Redis metadata + RQ enqueue before returning 202. Indexing errors belong to document status. Supabase supplies Auth/Storage; no application SQL migrations or metadata service-role key are required.
- `services/document_repository.py` owns Redis hashes and per-user sorted sets under `doctrace:library:v2`; catalog keys have no TTL. RQ result expiry must not remove ready documents. Every public read/mutation checks the authenticated owner; Milvus queries also filter `user_id`.
- `services/rate_limiter.py` uses atomic Redis-time windows under `doctrace:ratelimit:v1` with TTL. Validate user/document before quota; check quota before Storage/enqueue/SSE. Never refund admissions or retry uncertain quota replies. Redis failure is 503; exhaustion is 429 + `Retry-After`, which CORS and fetch/XHR must preserve. Deletion retries are exempt.
- `services/job_queue.py` enqueues inside the repository's WATCH/MULTI transaction. RQ 2.12 `unique=True` ignores a supplied pipeline: do not enable it here. API/worker need the same Redis and queue (`documents-v2`); legacy `documents` jobs have incompatible payloads.
- `worker.py` uses JSON serialization and the retry scheduler; `jobs/documents.py` creates clients after fork. Keep worker blocking Redis timeouts separate from producer timeouts. `job_queue.MAX_RETRIES` also controls attempt numbering. Redis/RQ/boto3/Milvus blocking calls run off-loop.
- Public `doc_id` differs from the Milvus generation: resolve `active_index_id`. A retry registers a fresh generation; only current job/attempt may publish. Reread metadata after an uncertain enqueue/publication before cleanup or failure. Delete/retry rejects live RQ jobs, including scheduled retries; RQ `finished` alone never implies ready.
- `services/pdf_indexing.py` owns indexing and temporary-file cleanup. `processors/pdf.py:load_pdf_pages()` preserves the original filename and **one-based physical PDF pages**, including blanks, for `#page=N`.
- Chat retrieves once, bounds ordinary context before citation numbering, and streams using those same chunks. Summaries read all owner-scoped chunks without query embeddings; preserve citation IDs through reduction (`score: null`).
- SSE sources require `citation_id`, `chunk_id`, public `doc_id`, `page`, `source`, `score`; token is a JSON text delta, error is `{message}`, done is the JSON string `"[DONE]"`. Keep `routers/chat.py`, frontend types/parser and fixtures aligned; EOF without done is an error. Citation lookup checks owner + active generation; request fresh 300-second PDF links when opening.

## Frontend ownership

- `frontend/src/app/(workspace)/layout.tsx` mounts `WorkspaceProvider` for `/chat` and `/documents`. It owns auth/catalog and the chat/upload hooks; `ChatWindow` and `UploadZone` receive required sessions, not their own hook instances. Navigation preserves state; switching PDFs/reloading clears chat. Backend chat is single-turn.
- `frontend/src/lib/api.ts` owns HTTP transport; `sse.ts` validates/decodes events. Preserve hook cancellation and late-response rejection. Markdown citation transforms must leave code/existing links intact and bind only known IDs.
- Supabase helpers live in `frontend/src/lib/supabase/`. Browser singleton is SDK-managed; server clients are per request. Middleware verifies `getUser()` for both workspace routes and preserves refreshed cookies on redirects plus `private, no-store` headers.
- Google login uses GIS `GoogleLogin` → `signInWithIdToken` on that shared SSR browser client; a plain supabase-js client loses middleware-visible cookies. `NEXT_PUBLIC_GOOGLE_CLIENT_ID` must match the Supabase provider; authorize frontend origins in Google. `/auth/callback` handles legacy Supabase PKCE, not Google credentials. GIS receives a hashed nonce, Supabase the raw nonce; Playwright intercepts GIS locally (see `frontend/README.md`).
- `NEXT_PUBLIC_*` changes require rebuild. API URL is an origin without `/api`; empty enables demo upload/chat while Auth still uses Supabase.
- Workspace styling stays light independently of the landing-page theme; Inter via `--font-sans` applies throughout. `@fontsource-variable/inter` bundles font files locally; builds must not fetch Google Fonts.
- Route moves can leave stale `.next/types`; regenerate ignored Next output rather than changing TypeScript paths. Preserve root `.gitignore` exceptions for `frontend/src/lib/` (Python's `lib/` rule otherwise hides it).

## Configuration and operations

- `AppConfig(...)` never reads env; `from_env(mapping)` parses settings. `get_config()` precedence is `backend/.env` > process env > root `.env`, cached once. Restart API/worker after edits; exporting a variable cannot override `backend/.env`.
- Pass the same config through pipeline/factories/embedder. `RAG_MODEL`/`EMBEDDING_MODEL` are explicit; cached embedder construction makes a real dimension-probe request. Milvus URI mode defaults to AUTOINDEX; preserve request-owned aliases, Strong consistency and cancellation cleanup. `ensure_collection()` rejects incompatibility; only `recreate_collection()` deletes all chunks.
- Redis AOF/volume holds the library and queue; `down -v` loses them and production certificates. PDF/vector data cannot rebuild the catalog: do not flush Redis or recreate Milvus to populate metadata. Old PostgreSQL users re-upload; see `DEPLOYMENT.md` cutover.
- Use `compose.production.yml` for VPS API/Redis/worker/Nginx; Vercel builds `frontend/`. Plain root Compose starts local vector infrastructure. API/worker share `REDIS_URL=redis://redis:6379/0` inside Docker.
- Keep worker shutdown grace (16m) above job timeouts (index 900s, delete 300s). Follow `DEPLOYMENT.md` for updates/certificates; bootstrap only initially. Recreate Nginx after template edits; preserve unbuffered uploads/SSE, validation-before-reload and Compose project/volumes. systemd assumes `/opt/DocTrace`.
- `/health` is process liveness; `get_connection_status()` is local connection state, neither verifies cloud/worker health.
