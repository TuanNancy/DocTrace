# Repository Notes

## Architecture and Boundaries

- API entrypoint: `backend/app/main.py`; routes: upload, documents, chat. `frontend/src/app/(workspace)/layout.tsx` shares auth/catalog/upload/chat state between `/chat` and `/documents`. Chat stays in memory across navigation; reload clears it. Persistent chat history is deferred.
- `POST /api/upload` validates/retains the PDF and returns **202 queued**. `python -m app.worker` performs indexing/deletion. Indexing errors belong to document status, not the completed upload response.
- Apply `backend/migrations/001_document_library.sql` once in Supabase before running the library. It creates metadata/jobs, RLS and transactional queue RPCs. API/worker require server-only `SUPABASE_SERVICE_ROLE_KEY` and private S3 storage. Old uploads lack catalog rows and need re-uploading; do not recreate their collection to populate the library.
- Public `doc_id` is not the Milvus index ID: resolve `documents.active_index_id`. Each worker lease indexes a fresh generation; only a valid lease may publish it. Preserve fencing, heartbeat, retry/deletion intent and periodic tombstone cleanup. A lost finish-RPC response may have committed; reread metadata before deleting that generation.
- `services/pdf_indexing.py:index_pdf_bytes()` owns extraction/chunking/embedding/insertion and temporary-file cleanup. The upload router owns original-PDF retention; `services/supabase_pdf_storage.py` owns S3 operations. Run synchronous boto3/Milvus work in threadpools.
- `load_pdf_pages()` converts PyPDFLoader's zero-based page index to **one-based physical PDF pages** and replaces temporary paths with the original filename. Preserve this for `#page=N` navigation.
- Chat retrieves once, bounds ordinary context before numbering sources, and passes the same chunks to `stream_answer()`. Summaries read all owner-scoped chunks without query embeddings/similarity filtering; preserve original citation IDs through summary reduction. Summary `score` is `null`.
- SSE sources contain `citation_id`, `chunk_id`, public `doc_id`, `page`, `source`, `score`; `token` is a JSON text delta, `error` is `{message}`, `done` is the JSON string `"[DONE]"`. Keep backend, frontend types/parser and fixtures aligned; EOF without `done` is an error.
- Citation text is loaded on demand under owner + active-generation filters. PDF links expire after 300 seconds; generate fresh links when opening. Markdown citation transforms must leave code/links intact and only activate known source IDs.
- Preserve clear/stop/document-change cancellation and rejection of late responses. Middleware in `frontend/src/lib/middleware.ts` protects both workspace routes. The workspace uses light styling independently of landing/auth theme preferences.
- Use Inter throughout the UI, including headings, branding and Markdown. Root `next/font` loads Latin/Vietnamese into `--font-sans`; Tailwind's `font-sans` must resolve that variable. Avoid page-specific serif overrides.

## Commands and Test Boundaries

- CI uses Python 3.12 and Node 22. Backend/frontend commands run from their respective directories.
- `backend/`: `python -m pip install -r requirements.txt`; API: `uvicorn app.main:app --reload --port 8000`; separate worker terminal: `python -m app.worker`.
- `backend/`: `python -m pytest`; focused: `python -m pytest tests/test_documents.py tests/test_worker.py` or `python -m pytest tests/test_chat.py::test_chat_sse_stream`.
- `backend/`: `python scripts/verify_document_queue.py` uses disposable Docker PostgreSQL to exercise the real migration, RLS, leases, stale-worker fencing and delete/retry. It does not touch the configured cloud project.
- `tests/conftest.py` seeds isolated config before app import. TestClient overrides Auth and `get_document_repository`. Upload tests mock S3 retention; worker tests mock download/index/delete. Chat tests keep the real pipeline/provider/SSE while mocking external services. These tests do not prove cloud integration.
- Manual retrieval uses real services: `python scripts/test_retrieval.py <user_id> <doc_id> "question" [--top-k 8 --min-score 0.32]`. It resolves the public document to its active generation. `scripts/` is outside pytest's test paths.
- `frontend/`: `npm ci`, `npm run dev`. CI order: `npm run typecheck`, `npm run lint`, `npm test`, `npm run test:e2e`, `npm run build`. Focused test: `npm test -- tests/ChatWindow.test.tsx`.
- Install Chromium with `npx playwright install chromium` (`--with-deps` on Linux CI). Playwright owns ports 4310/4311 for Next + fake Auth/API, and writes ignored screenshots to `test-results/`. Headless shell downloads PDF links instead of mounting Chrome's viewer; tests assert the download URL/page fragment.
- Builds need public Supabase settings; see `frontend/.env.example` and CI placeholders. Route moves can leave stale `.next/types`; regenerate the ignored Next output rather than altering TypeScript paths to accommodate old routes.

## Configuration and Data Invariants

- `AppConfig(...)` never reads env; `from_env(mapping)` parses explicit settings. `get_config()` loads root `.env`, then `backend/.env` with override enabled (including process env), and caches once. Restart API/worker after changes. Config tests use explicit mappings.
- Pass the same config through pipeline/factories/embedder. `RAG_MODEL` and `EMBEDDING_MODEL` are explicit; constructing the cached embedder makes a real dimension-probe request. Dimensions come from API vectors, not removed dimension env settings.
- Milvus supports host/port or URI/token; URI mode defaults to AUTOINDEX. `ensure_collection()` rejects incompatible dimensions/owner schemas; only `recreate_collection()` deletes all chunks. Preserve `user_id` filters, request-owned connection aliases, Strong read consistency and cancellation cleanup.
- `NEXT_PUBLIC_API_URL` is an origin without `/api`. Empty means demo upload/chat; Auth still requires Supabase. Public env is build-time; service-role/S3/OpenRouter secrets stay in backend env.
- Root `.gitignore` ignores Python `lib/`; preserve exceptions for `frontend/src/lib/`.

## Deployment

- Root `docker compose up -d` starts Milvus/etcd/MinIO/Attu only. Production uses `compose.production.yml` for API + worker + Nginx; frontend deploys separately.
- Initial Linux setup: `sh deploy/certificates.sh bootstrap`, then `sh deploy/certificates.sh issue`. Later: `docker compose --env-file .env.production -f compose.production.yml up -d --build --wait api worker nginx`. See `DEPLOYMENT.md` for migration/env prerequisites and memory limits.
- Nginx templates render only at startup; recreate its container after template edits. Preserve unbuffered SSE/uploads. Renewal validates before reload; systemd assumes `/opt/DocTrace`. Preserve Compose project name/certificate volumes; `down -v` deletes certificate state. Bootstrap is initial-only.
- Proxy verification from root: `docker build -t doctrace-api:verify ./backend`, then `python deploy/tests/verify_nginx.py --api-image doctrace-api:verify`. It uses isolated Docker resources, fake services and self-signed certificates.
- `/health` is API process liveness; it does not verify worker/cloud health. `get_connection_status()` is local connection state, not a remote health probe.
