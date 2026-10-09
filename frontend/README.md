# DocTrace frontend

Next.js 14 App Router, React 18, Tailwind, ReactMarkdown/GFM. The authenticated workspace uses a light glass design with responsive navigation and source drawers.

Inter is the shared font across all pages, headings, branding and Markdown. It is loaded with Latin/Vietnamese support through `next/font` and connected to Tailwind's `font-sans` via `--font-sans`.

`BrandMark` pairs a purple document-search icon with the DocTrace wordmark. Login and signup share `AuthShell`, `AuthField` and `Auth.module.css`: light neutral/purple styling, Vietnamese labels, password visibility controls and password-manager autocomplete.

Signup stages Supabase cookie writes until success so failed submissions retain their fields and inline error. Successful signup signs out and redirects from the server to `/auth/login?registered=1`, which shows a persistent confirmation notice.

## Setup

From `frontend/`, run `npm ci`, copy `.env.example` to `.env.local`, then `npm run dev`.

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY` | Public key; legacy `NEXT_PUBLIC_SUPABASE_ANON_KEY` also works |
| `NEXT_PUBLIC_SITE_URL` | Frontend origin, e.g. `http://localhost:3000` |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Google OAuth **Web application** Client ID; same ID as the Supabase Google provider. Empty disables Google login, leaving email/password available. |
| `NEXT_PUBLIC_API_URL` | Backend origin, e.g. `http://localhost:8000`, without `/api` |

Public env is embedded at build time; rebuild after changes. S3 and OpenRouter keys belong in backend env. Empty API URL enables explicitly labelled demo upload/chat; authentication still uses Supabase and demo documents disappear on reload.

Supabase Auth needs Site URL and allowlisted `/auth/login` for the current email-confirmation flow. Backend CORS must allow the frontend origin.

### Google login (Google Identity Services)

`GoogleSignInButton` renders the official Google button through `@react-oauth/google`. Google returns an ID token to the browser callback; `signInWithIdToken` on the shared `@/lib/supabase/client` creates the cookie-based Supabase session, then navigates to `/chat`. The Google SDK loads only on the login page when a Client ID is configured. No automatic One Tap or redirect-based fallback is enabled.

1. **Google Auth Platform → Clients → Web client:** add `https://YOUR-FRONTEND` under **Authorized JavaScript origins** (origin only, no path/trailing slash). For local development add `http://localhost` and `http://localhost:3000`. Register each preview origin separately if testing there.
2. This popup flow needs **no Vercel redirect URI** in Google Console. Keep `https://YOUR-PROJECT.supabase.co/auth/v1/callback` for legacy Supabase OAuth. The app's existing `/auth/callback` exchanges a Supabase PKCE code; it does not accept Google ID tokens or Google's authorization codes directly.
3. **Supabase → Authentication → Providers → Google:** enable Google and configure the same Web Client ID. Keep the existing Client Secret there; never put it in frontend env. Keep **Skip nonce checks** off: the button supplies a SHA-256 nonce to Google and the raw nonce to Supabase.
4. Set `NEXT_PUBLIC_GOOGLE_CLIENT_ID` in `frontend/.env.local` and in Vercel's deployment environment, then restart dev/rebuild and redeploy. The Supabase URL/key remain unchanged.
5. If the Google app audience is **Testing**, add the accounts you intend to use under **Test users**. Test a real Google login on the deployed origin, reload `/chat`, visit `/documents`, then sign out. Google's displayed app/domain depends on its Branding and popup/FedCM UI; automated tests do not establish the exact text Google will display.

The login route sets `Cross-Origin-Opener-Policy: same-origin-allow-popups` for Google's popup. Missing Client ID, SDK load errors, and token exchange errors are shown inline; email login remains available. If Google reports an origin error, check the exact scheme/host/port. An audience mismatch from Supabase usually means the Web Client IDs differ. Changes in Google Console may take time to propagate.

## Workspace

- `src/app/(workspace)/layout.tsx` mounts `WorkspaceProvider` for `/chat` and `/documents`; route changes preserve in-memory chat/upload state. Reload starts a new conversation. There is no localStorage/server chat persistence.
- `/documents` uploads PDF via XHR byte progress and receives the same `LibraryDocument` contract as the library endpoints. Upload progress is local UI state; persisted documents start at queued. `src/lib/documents.ts` shares pending/indexing checks across polling, filters and actions.
- The Redis library and Linux RQ worker described in the root README are required for real processing. Re-upload PDFs when moving from the old PostgreSQL library; no SQL migration is needed. Delete/retry is blocked until the current job ends; a stale UI may receive a 409 and refresh.
- Chat uses only a selected ready PDF. `useChatSession` owns streaming, clear/stop, export and cancellation. Switching PDFs clears messages; navigation between workspace pages preserves them.
- ReactMarkdown/GFM renders assistant output. Source IDs become buttons only when present in the response. The citation panel fetches original text and opens a short-lived PDF URL at the cited page.
- The workspace is light independently of the public landing/auth pages' theme. Sidebar collapses below 1024px, source panel below 1280px; Base UI dialogs provide focus management.
- `src/lib/supabase/` contains browser/server clients, public configuration and session middleware. `src/lib/` has explicit exceptions to the root Python `lib/` ignore rule.
- `src/lib/api.ts` owns HTTP transport; `src/lib/sse.ts` validates and decodes the chat event contract, including required citation IDs and explicit completion.
- `ChatWindow` and `UploadZone` receive sessions from the workspace provider. Their hooks own requests and cancellation; components only render the shared state and dispatch user actions.

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

Build requires public Supabase settings; CI uses placeholders. Browser tests intercept the Google SDK and use local Auth/API fixtures, including ID-token exchange, nonce matching and session-cookie persistence across reloads. Focused Google checks: `npm test -- tests/GoogleSignInButton.test.tsx` and `npm run test:e2e -- tests/e2e/google-auth.spec.ts`. Tests do not call real Google, Supabase, Milvus or OpenRouter. Verify live OAuth/RAG separately when deploying.
