# Baymax frontend

Next.js 14 App Router, React 18, Tailwind, ReactMarkdown/GFM. The authenticated workspace uses a light glass design with responsive navigation and source drawers.

Inter is the shared font across all pages, headings, branding and Markdown. It is loaded with Latin/Vietnamese support through `next/font` and connected to Tailwind's `font-sans` via `--font-sans`.

## Setup

From `frontend/`, run `npm ci`, copy `.env.example` to `.env.local`, then `npm run dev`.

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY` | Public key; legacy `NEXT_PUBLIC_SUPABASE_ANON_KEY` also works |
| `NEXT_PUBLIC_SITE_URL` | Frontend origin, e.g. `http://localhost:3000` |
| `NEXT_PUBLIC_API_URL` | Backend origin, e.g. `http://localhost:8000`, without `/api` |

Public env is embedded at build time; rebuild after changes. S3 and OpenRouter keys belong in backend env. Empty API URL enables explicitly labelled demo upload/chat; authentication still uses Supabase and demo documents disappear on reload.

Supabase Auth needs Site URL and allowlisted `/auth/callback` for OAuth and `/auth/login` for the current email-confirmation flow. Enable Google provider for Google login. Backend CORS must allow the frontend origin.

## Workspace

- `src/app/(workspace)/layout.tsx` mounts `WorkspaceProvider` for `/chat` and `/documents`; route changes preserve in-memory chat/upload state. Reload starts a new conversation. There is no localStorage/server chat persistence.
- `/documents` uploads PDF via XHR byte progress and receives `202 queued`. Metadata comes from the owner-scoped library API. Polling follows queued/processing/deleting documents; reload retrieves persisted status.
- The Redis library and Linux RQ worker described in the root README are required for real processing. Re-upload PDFs when moving from the old PostgreSQL library; no SQL migration is needed. Delete/retry is blocked until the current job ends; a stale UI may receive a 409 and refresh.
- Chat uses only a selected ready PDF. `useChatSession` owns streaming, clear/stop, export and cancellation. Switching PDFs clears messages; navigation between workspace pages preserves them.
- ReactMarkdown/GFM renders assistant output. Source IDs become buttons only when present in the response. The citation panel fetches original text and opens a short-lived PDF URL at the cited page.
- The workspace is light independently of the public landing/auth pages' theme. Sidebar collapses below 1024px, source panel below 1280px; Base UI dialogs provide focus management.
- `src/lib/middleware.ts` protects both workspace routes using verified Auth and refreshed cookies. `src/lib/` has explicit exceptions to the root Python `lib/` ignore rule.

## Verification

```sh
npm run typecheck
npm run lint
npm test
npx playwright install chromium
npm run test:e2e
npm run build
```

Focused unit test: `npm test -- tests/ChatWindow.test.tsx`.

Playwright owns `localhost:4310` (Next) and `127.0.0.1:4311` (Auth/API fixtures); keep them free. Tests cover desktop/mobile library lifecycle, retry/filtering, streaming/stop, citation navigation, transient chat and logout. Screenshots go to ignored `test-results/`.

Build requires public Supabase settings; CI uses placeholders. Browser and unit tests do not call real Supabase, Milvus or OpenRouter. Verify live OAuth/RAG separately when deploying.
