# Repository Guidelines

## Project Structure & Module Organization

- `backend/app/`: FastAPI `routers/` handles upload/chat; `processors/` extracts and chunks PDF text; `ai/` orchestrates retrieval/streaming; `providers/`, `storage/`, and `services/` integrate OpenRouter, Milvus, and Supabase. `core/` configures authentication and environment settings.
- PDF indexing lives in `services/pdf_indexing.py:index_pdf_bytes()`. Chat uses `ai/rag_pipeline.py:RAGPipeline`; its public `retrieve_chunks()` supplies sources and `stream_answer()` reuses them. `storage/` is for vector chunks; `services/supabase_pdf_storage.py` retains original PDFs.
- `backend/tests/` contains automated tests; `backend/scripts/` contains manual chunking/retrieval diagnostics.
- `frontend/src/app/` contains Next.js App Router pages/routes; `frontend/src/components/` holds React UI; `frontend/src/types/` defines shared types. Styling uses Tailwind and `app/globals.css`; `logo1.png` supplies branding.
- `docker-compose.yml` defines Milvus, etcd, MinIO, and Attu. Cross-check `README.md` and `ARCHITECTURE.md` against source; some documented modules are absent.

## Build, Test, and Development Commands

- Root: `docker compose up -d` starts database infrastructure, excluding the API/frontend.
- API deployment uses `compose.production.yml` separately. On the Linux host, initialize with `sh deploy/certificates.sh bootstrap`, then `issue`; subsequent deploys use `docker compose --env-file .env.production -f compose.production.yml up -d --build --wait api nginx`. See `DEPLOYMENT.md`.
- Nginx templates are rendered only at startup; recreate its container after template changes. `renew` runs Certbot, `nginx -t`, then reload; the systemd timer expects `/opt/DocTrace`. Preserve the Compose project name and certificate volumes. Bootstrap is only for initial issuance.
- Proxy verification: build `docker build -t doctrace-api:verify ./backend`, then run `python deploy/tests/verify_nginx.py --api-image doctrace-api:verify` from root. It uses isolated Docker resources and self-signed certificates, not real cloud services. `/health` is liveness only.
- `backend/`: use Python 3.10+ (tests verified on 3.12), create/activate a virtual environment, then `pip install -r requirements.txt`.
- `backend/`: `uvicorn app.main:app --reload --port 8000` serves the API and `/docs`.
- `backend/`: `python -m pytest` runs tests selected by `pytest.ini`.
- `frontend/`: `npm ci` installs locked dependencies; `npm run dev` starts development on port 3000 by default.
- `frontend/`: `npm run build` creates production output; `npm start` serves it. `npm run lint` uses `.eslintrc.json`; `npm run typecheck` checks TypeScript; `npm test` runs Vitest.
- `frontend/`: install Chromium with `npx playwright install chromium`, then `npm run test:e2e`. It starts Next dev and loopback Auth/API fixtures on ports 4310/4311 and cleans up afterward. CI uses Node 22 and installs Chromium with OS dependencies.

## Current Checkout Limitations

Frontend `src/lib/` is restored and explicitly unignored. Use `frontend/.env.example` for Supabase public settings and API URL; build-time `NEXT_PUBLIC_*` changes require a rebuild. Milvus supports local host/port and cloud URI/token; URI mode defaults to AUTOINDEX.

## Coding Style & Naming Conventions

Follow existing Python style: four spaces, `snake_case` functions/modules, `PascalCase` classes, and type annotations. TypeScript uses two spaces, double quotes, semicolons, `PascalCase` component filenames, and `camelCase` functions. Strict mode and the `@/*` alias are configured. No Python formatter/linter is configured.

## Testing Guidelines

Use pytest/pytest-asyncio with `test_*.py` files and `test_*` functions. The TestClient fixture bypasses authentication; it does not test real auth. Upload tests mock `app.routers.upload.index_pdf_bytes` and `app.routers.upload.try_upload_pdf`; preserve both boundaries to avoid real external calls. Chat tests exercise the real pipeline/provider/SSE with external services mocked. Focused verification from `backend/`: `python -m pytest tests/test_vector_store.py` or `python -m pytest tests/test_chat.py::test_chat_sse_stream`. Frontend regression tests live in `frontend/tests/`; Vitest mocks service boundaries and Playwright exercises real UI/cookies with fake local services. Neither validates real cloud OAuth or RAG.

## Commit & Pull Request Guidelines

History uses imperative subjects such as `Update`, `Add`, and `Refactor`, without mandatory prefixes. Recommended PR content: purpose, relevant issues, validation results/blockers, and UI screenshots.

## Security & Configuration

- `AppConfig(...)` never reads env; `AppConfig.from_env()` parses environment or an explicit mapping. `get_config()` loads root then backend `.env` once and caches the result; restart after edits. Pass the same config through pipeline/factories/embedder. Models must be configured explicitly when their service is used.
- Retrieval callers must pass `top_k` and `min_score`; the manual retrieval script reads application defaults and accepts `--top-k` / `--min-score`. Vector dimensions come from API results; the old dimension env settings have no effect.
- Tests seed an isolated config before importing the app, avoiding developer `.env` files. Use explicit mappings for environment parsing tests.

Use ignored environment files: root `.env`, overriding `backend/.env`, and `frontend/.env.local`. Never place OpenRouter/S3 secrets in `NEXT_PUBLIC_*`. `MilvusVectorStore.ensure_collection()` rejects dimension mismatches without deleting data; only explicit `recreate_collection()` deletes existing chunks. `get_connection_status()` checks local connection state, not server health.
