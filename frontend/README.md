# DocTrace frontend

Next.js 15 App Router + React + Tailwind 3, deployed on Vercel. Node.js 22.18+.

## Setup

From `frontend/`, run `npm ci`, create `.env.local` from `.env.example`, then `npm run dev`.

Required public settings:

- `NEXT_PUBLIC_API_URL`: backend origin, without `/api`.
- `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY`: public project credentials, never service-role/S3/OpenRouter keys.
- `NEXT_PUBLIC_SITE_URL`: frontend origin used for email confirmation callbacks.

Typecheck/build require all four variables. Typecheck runs `next typegen` before `tsc` so a clean checkout has generated route types. Production build embeds `NEXT_PUBLIC_*` values; changing them on Vercel requires a rebuild. `NEXT_PUBLIC_DEMO_MODE=true` only enables fake upload/chat in development; Supabase login is still required.

## Verification

```text
npm run lint
npm run typecheck
npm test
npx playwright install chromium
npm run test:e2e
npm run build
```

Playwright owns ports 3005 (Next dev) and 8999 (mock Supabase/API). It tests actual cookie-based Server Actions and browser streaming without cloud credentials. Stop other processes using those ports first. Traces/screenshots for failures are ignored under `test-results/`.

The build uses `next/font/google`, which needs access to Google Fonts on a cold build. `npm start` serves the completed production build.

## Integration notes

- `src/lib/api.ts`: upload uses multipart, chat uses POST fetch + a ReadableStream parser. Both send a bearer token directly to FastAPI.
- `src/lib/{client,server,middleware}.ts`: Supabase browser singleton, per-request server client and session-refresh middleware. The server helper is for cookie-writing Actions/Route Handlers, not read-only Server Components.
- `/auth/callback`: exchanges OAuth/email confirmation codes; redirects remain on the app origin.
- Missing backend URL is an error; it no longer silently switches to demo mode.
- `clearMessages()` clears the displayed transcript; document selection remains. Selecting another document resets the chat. Reload clears document/transcript state but retains auth.
- Branding is bundled from `public/logo1.png`; the root logo is not a runtime dependency.
- `tailwind-merge` stays on 2.6 for Tailwind 3. The PostCSS override selects the patched 8.5 line for Next's transitive dependency; validate with `npm audit` and a production build when updating it.

For Supabase setup, Vercel settings, EC2/Caddy and live smoke tests, see [DEPLOYMENT.md](../DEPLOYMENT.md).
