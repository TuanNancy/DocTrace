# Repository Guidelines

## Project Structure & Module Organization

- `backend/app/`: FastAPI `routers/` handles upload/chat; `processors/` extracts and chunks PDF text; `ai/` orchestrates retrieval/streaming; `providers/`, `storage/`, and `services/` integrate OpenRouter, Milvus, and Supabase. `core/` configures authentication and environment settings.
- `backend/tests/` contains automated tests; `backend/scripts/` contains manual chunking/retrieval diagnostics.
- `frontend/src/app/` contains Next.js App Router pages/routes; `frontend/src/components/` holds React UI; `frontend/src/types/` defines shared types. Styling uses Tailwind and `app/globals.css`; `logo1.png` supplies branding.
- `docker-compose.yml` defines Milvus, etcd, MinIO, and Attu. Cross-check `README.md` and `ARCHITECTURE.md` against source; some documented modules are absent.

## Build, Test, and Development Commands

- Root: `docker compose up -d` starts database infrastructure, excluding the API/frontend.
- `backend/`: create/activate a virtual environment, then `pip install -r requirements.txt`.
- `backend/`: `uvicorn app.main:app --reload --port 8000` serves the API and `/docs`.
- `backend/`: `python -m pytest` runs tests selected by `pytest.ini`.
- `frontend/`: `npm ci` installs locked dependencies; `npm run dev` starts development on port 3000 by default.
- `frontend/`: `npm run build` creates production output; `npm start` serves it. `npm run lint` invokes Next.js ESLint, but no ESLint configuration is checked in.

## Current Checkout Limitations

Frontend imports require missing `frontend/src/lib/{api,client,server,middleware,utils}.ts` modules, blocking builds. The root `.gitignore` pattern `lib/` also ignores this directory; address it when restoring modules.

## Coding Style & Naming Conventions

Follow existing Python style: four spaces, `snake_case` functions/modules, `PascalCase` classes, and type annotations. TypeScript uses two spaces, double quotes, semicolons, `PascalCase` component filenames, and `camelCase` functions. Strict mode and the `@/*` alias are configured. No Python formatter/linter is configured.

## Testing Guidelines

Use pytest/pytest-asyncio with `test_*.py` files and `test_*` functions. The TestClient fixture bypasses authentication; it does not test real auth. Mock external calls, including `app.routers.upload.try_upload_pdf`: existing upload tests leave S3 unmocked and may upload with configured credentials. Cover validation, success, and SSE/error paths. No coverage threshold or frontend test runner exists; manually verify UI changes.

## Commit & Pull Request Guidelines

History uses imperative subjects such as `Update`, `Add`, and `Refactor`, without mandatory prefixes. Recommended PR content: purpose, relevant issues, validation results/blockers, and UI screenshots.

## Security & Configuration

Use ignored environment files: root `.env`, overriding `backend/.env`, and `frontend/.env.local`. Never place OpenRouter/S3 secrets in `NEXT_PUBLIC_*`. Changing embedding dimensions can drop/recreate the Milvus collection; preserve data before changing models.
