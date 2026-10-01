# Deploy portfolio demo: Vercel + EC2/Caddy + Zilliz + Supabase

## 1. Prepare cloud services

### Supabase

1. Create a project; copy the Project URL and publishable key.
2. Set **Authentication → URL Configuration → Site URL** to your Vercel/custom frontend origin.
3. Add allowed redirect URLs:
   - `http://localhost:3000/auth/callback`
   - `https://YOUR-FRONTEND/auth/callback`
4. For Google login, enable the provider and configure its credentials in Supabase. The Google console callback points to Supabase's callback URL shown in the dashboard, not directly to Next.js.
5. For email signup, configure a working email provider/SMTP for intended testers; the default email service has recipient/rate restrictions. Confirmation links use the PKCE callback; open them in the browser where signup began.
6. Create a **private** Storage bucket (`pdfs`) and obtain S3 credentials, endpoint and region. These credentials stay on the backend. Upload keys are `user_id/doc_id/filename`.

Set frontend `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY`, and backend `SUPABASE_URL` / `SUPABASE_PUBLISHABLE_KEY` to the same project.

### Zilliz

1. Create a Free cluster where available, preferably near the API/Supabase region.
2. Copy the public HTTPS endpoint to `MILVUS_URI` and an API key/token to `MILVUS_TOKEN` in `backend/.env`.
3. Set `MILVUS_COLLECTION=pdf_chunks_owned_v1` (or another new name). The first upload creates the schema/index. The new schema contains `user_id`.
4. Re-upload PDFs. Existing local data is not migrated or deleted automatically.

URI mode defaults to `AUTOINDEX` + `COSINE`; leave `MILVUS_INDEX_TYPE` unset. Confirm the account's free storage/compute limits in its dashboard.

### OpenRouter

Set `OPENROUTER_API_KEY`, `RAG_MODEL` and `EMBEDDING_MODEL` in `backend/.env`. Chat and embeddings are separate billable operations; selecting a free chat model does not make embeddings free. Use a per-key spending limit and choose a model available to your account.

Choose the embedding model before loading PDFs. If it changes, use a new collection and re-index, even if the dimension remains identical. The first embedder construction probes the API, so a new process can incur a small initial embedding request.

## 2. EC2 and API domain

Start with one Linux `t3.small` for this low-traffic demo. Install Docker Engine and the Compose plugin. The API image uses Python 3.12 and one Uvicorn worker.

- Assign a stable public address and point `api.YOUR-DOMAIN` to it.
- Allow inbound TCP 80/443 so Caddy can obtain certificates and serve HTTPS. Limit SSH to your administrative access path.
- API port 8000 is internal to Docker; production Compose does not publish it.
- Choose EBS capacity for the image and rotated logs. Originals live in Supabase, not EBS.

Cost consists of **EC2 runtime + EBS + public IPv4 + any billable traffic/CPU credits**. Region and account credits determine the actual bill; the VM hourly rate alone is not the total. Vercel Hobby is intended for personal non-commercial projects. Check the current free-tier quotas for Supabase/Zilliz before sharing the demo broadly.

## 3. Configure and start the backend

On EC2, from the repository root:

```sh
cp backend/.env.example backend/.env
cp .env.production.example .env.production
```

Edit `backend/.env` with real backend credentials and:

```dotenv
CORS_ALLOW_ORIGINS=https://YOUR-FRONTEND
MILVUS_URI=https://YOUR-ZILLIZ-ENDPOINT
MILVUS_TOKEN=YOUR-ZILLIZ-TOKEN
MILVUS_COLLECTION=pdf_chunks_owned_v1
UPLOAD_MAX_CONCURRENT=1
```

Edit `.env.production`:

```dotenv
API_DOMAIN=api.YOUR-DOMAIN
ACME_EMAIL=YOUR-EMAIL
```

Use the separate production Compose file explicitly:

```sh
docker compose --env-file .env.production -f compose.production.yml config --quiet
docker compose --env-file .env.production -f compose.production.yml up -d --build
docker compose --env-file .env.production -f compose.production.yml ps
docker compose --env-file .env.production -f compose.production.yml logs --tail=100 api caddy
curl --fail https://api.YOUR-DOMAIN/health
```

The root `docker-compose.yml` is the **local Milvus infrastructure**, not this production app. Production starts only API + Caddy, with managed vector/storage services elsewhere.

Secrets are injected via `env_file` and excluded from the image. Caddy stores certificate state in its named volumes. Keep these volumes across updates. The API root filesystem is read-only with a 256 MiB temporary filesystem; its 1400 MiB container memory limit leaves headroom on a 2 GiB host.

`/health` proves only that the API is alive. It deliberately makes no OpenRouter/Supabase/Zilliz calls. Container health does not validate credentials.

## 4. Deploy frontend to Vercel

Import the Git repository and configure:

| Setting | Value |
|---|---|
| Framework | Next.js |
| Root Directory | `frontend` |
| Node.js | 22.x |
| Install Command | `npm ci` |
| Build Command | `npm run build` |

Set all four public environment variables **before building**:

```dotenv
NEXT_PUBLIC_API_URL=https://api.YOUR-DOMAIN
NEXT_PUBLIC_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY=YOUR-PUBLISHABLE-KEY
NEXT_PUBLIC_SITE_URL=https://YOUR-FRONTEND
```

`NEXT_PUBLIC_API_URL` is an origin without `/api`. Frontend values are baked into the client bundle; rebuild after changes. OpenRouter, Zilliz tokens and Supabase S3 keys belong only on EC2.

Use a stable Vercel/custom URL for the demo. Preview deployments need their own site URL, Supabase redirect allowlist entry and backend CORS origin if you want auth/upload to work there. Recheck CORS and Supabase configuration after assigning the final domain.

PDF upload and SSE go directly from the browser to the HTTPS API. Next.js handles auth pages/actions/callbacks; no Next API proxy handles the PDF or chat stream.

Caddy automatically flushes `text/event-stream` responses immediately. Keep the default flush configuration: forcing `flush_interval -1` would keep the upstream request running even after the browser disconnects.

## 5. Live smoke test

1. Open the deployed site; verify the logo, public landing and login page.
2. Sign in, reload `/chat`, and confirm the session remains valid.
3. Upload a small text PDF; verify chunks count, private Supabase object and Zilliz rows with the signed-in `user_id`.
4. Ask a document-specific question. In browser Network tools, verify `/api/chat` streams `sources`, `token` and `done` incrementally rather than buffering until completion.
5. Using a second account, submit the first account's `doc_id`. It must produce no sources/document context. Adding `user_id` to the body must be rejected with 422.
6. Logout and reopen `/chat`; it must return to login. Verify an unauthenticated API request returns 401.

These are live checks with real credentials, distinct from the isolated pytest/Vitest/Playwright suites.

## 6. Updates and rollback

Before an update, record the current Git SHA and keep the previous API image ID (`docker compose --env-file .env.production -f compose.production.yml images`). Deploy a tested revision with the same Compose command. If needed, check out the recorded revision and rebuild/restart it; Vercel can promote the previous successful deployment.

Code rollback does not roll back data. Collection/schema/model changes should use a new collection name so the previous deployment can still read its compatible collection. Do not drop collections as an automatic deployment step.

The GitHub workflow verifies tests, frontend build, API container liveness and Caddy config. It performs no cloud deployment or credential provisioning.

## Troubleshooting

| Symptom | Check |
|---|---|
| Frontend build says missing env | Set the four public variables in the Vercel environment and rebuild. |
| Auth works locally but not deployed | Supabase Site URL/redirect allowlist, `NEXT_PUBLIC_SITE_URL`, and matching Supabase project keys. |
| Email confirmation fails on another browser | PKCE verifier is in the signup browser; retry there or use the login flow after verification as appropriate. |
| Upload/chat blocked by CORS | Exact HTTPS frontend origin in `CORS_ALLOW_ORIGINS`, then recreate the API container. |
| Indexing fails on schema/dimension | Inspect API logs; use a fresh owner-scoped collection and a fixed embedding model. |
| Sources are empty | Confirm ownership, selected doc_id, and relevance threshold. Service errors are reported separately. |
| Upload returns 429 | Another upload occupies the per-process slot; honor `Retry-After`. |
| Large PDF rejected | File size, 2000-chunk default cap, and container memory; split PDFs for this demo. |
| Original PDF missing but indexing succeeds | Retention is skipped without full S3 configuration; failures appear in warnings/logs. |
| Demo disappears after inactivity | Check free-tier service pause/quota state in Supabase/Zilliz dashboards. |
