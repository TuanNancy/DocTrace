# DocTrace — Architecture

## Scope

- Standard text-based RAG flow for PDF
- No OCR/computer vision in the main pipeline
- No multi-agent task planner
- Single LLM provider: OpenRouter (chat + embeddings)
- Vector store: Milvus; original PDF storage: Supabase S3
- Auth: Supabase Auth (JWT)

## Runtime Flow

```
Upload PDF
  → validate request and retain original PDF in Supabase Storage (upload router)
  → index_pdf_bytes() (PDF indexing service)
  → extract text by page (PyPDFLoader)
  → split into chunks (RecursiveCharacterTextSplitter)
  → generate embeddings (OpenRouter /v1/embeddings)
  → insert vectors + metadata into Milvus

Chat query (with doc_id)
  → create_initialized_rag_pipeline()
  → embed query (OpenRouter)
  → search top-k chunks from Milvus (COSINE, filter by doc_id)
  → build bounded context with page citations
  → call chat model via OpenRouter (stream)
  → stream SSE events: sources → token → done
```

## Backend Structure

```
backend/app/
├── main.py                  # FastAPI app + CORS + mount routers
├── schemas.py               # Pydantic request models (ChatRequest)
│
├── core/
│   ├── config.py            # AppConfig: AI, auth, upload, and storage settings
│   └── auth.py              # Supabase JWT verification
│
├── routers/
│   ├── upload.py            # POST /api/upload — validation + indexing service call
│   └── chat.py              # POST /api/chat — SSE streaming
│
├── processors/
│   └── pdf.py               # PDF loading + chunking (LangChain)
│
├── providers/
│   ├── base.py              # Abstract ChatProvider interface
│   ├── openrouter.py        # OpenRouterChatProvider (AsyncOpenAI SDK)
│   ├── embeddings.py        # OpenRouterEmbedder
│   └── factory.py           # create_chat_provider()
│
├── storage/
│   ├── base.py              # VectorStore + RetrievedChunk/InsertResult
│   ├── milvus_vector_store.py # MilvusVectorStore (pymilvus)
│   └── factory.py           # VectorStoreFactory + connection helpers
│
├── ai/
│   ├── prompts.py           # System prompts (VI + EN)
│   └── rag_pipeline.py      # RAGPipeline: retrieve → context → stream answer
│
├── models/
│   └── document.py          # DocumentStatus, IndexingResult
│
└── services/
    ├── pdf_indexing.py      # index_pdf_bytes(): extract → chunk → embed → insert
    └── supabase_pdf_storage.py  # PDF backup to Supabase S3 (boto3)
```

## Responsibilities and Naming

| Component | Responsibility |
|-----------|----------------|
| `RAGPipeline` | Fixed retrieval/context/generation flow. `retrieve_chunks()` is public because the router also needs sources; `stream_answer()` can reuse those chunks to avoid a second search. |
| `ChatProvider` | `generate_completion()` returns complete text; `stream_completion()` yields text deltas. `generate_with_context()` and `stream_with_context()` construct messages with retrieved context. |
| `OpenRouterEmbedder` | Embeddings use the OpenAI-compatible SDK but are sent to OpenRouter. `_probe_embedding_dimension()` makes an API call when the cached embedder is first created. |
| `VectorStore` | Stores chunk text/vectors/metadata; `RetrievedChunk.chunk_id` is the persisted primary key returned by search. |
| `index_pdf_bytes()` | Handles temporary PDF files, extraction, chunking, embedding, insertion, and cleanup. The router owns auth, HTTP validation, and original-PDF retention. |
| `AppConfig` | Application-wide settings, including auth and PDF storage as well as RAG. |

- `create_vector_store()` constructs an object; `create_connected_vector_store()` also connects it. Its caller must disconnect it.
- `create_initialized_rag_pipeline()` constructs and initializes the pipeline. The chat router calls `shutdown()` in `finally`.
- `has_api_key()` checks local key presence only. `get_connection_status()` reports local connection state only; neither verifies remote service health.
- `ensure_collection()` creates/loads a compatible collection and rejects mismatched or unreadable dimensions. Only `recreate_collection()` explicitly deletes existing chunks.

## Frontend Structure

The shared `lib/` modules are tracked via an exception to the root Python `lib/` ignore rule. Frontend verification includes typecheck, ESLint, Vitest and a Chromium journey with loopback Auth/API fixtures.

```
frontend/src/
├── middleware.ts              # Next.js edge middleware (auth redirect)
│
├── types/
│   └── index.ts               # TypeScript types
│
├── lib/                       # Shared API and auth adapters
│   ├── api.ts                 # streamChat(), uploadPDF(), SSE parser
│   ├── client.ts              # Supabase browser client
│   ├── server.ts              # Supabase server client
│   ├── middleware.ts          # updateSession() for auth redirect
│   ├── supabase-config.ts     # Public project URL and key validation
│   └── utils.ts               # cn() — clsx + tailwind-merge
│
├── app/
│   ├── layout.tsx             # Root layout (Inter font, metadata)
│   ├── globals.css            # Tailwind + CSS variables
│   ├── page.tsx               # Landing page
│   │
│   ├── chat/
│   │   └── page.tsx           # Main chat page (sidebar + upload + chat)
│   │
│   └── auth/
│       ├── actions.ts         # Server actions: loginAction, signupAction
│       ├── login/page.tsx
│       ├── signup/page.tsx
│       ├── callback/route.ts  # OAuth callback
│       └── auth-code-error/page.tsx
│
└── components/
    ├── BrandMark.tsx
    ├── ThemeToggle.tsx
    ├── UploadZone.tsx
    ├── ChatWindow.tsx
    ├── SourceCard.tsx
    ├── SourceCardList.tsx
    ├── StreamingCursor.tsx
    └── auth/
        ├── LoginForms.tsx
        ├── SignupForm.tsx
        └── AuthSubmitButton.tsx
```

`ChatWindow` uses `createMessageId()`, `appendTextDelta()`, and the local parser alias `parseChatEvents` (imported as `streamChatSSEParser`). The wire event name remains `token`. `clearMessages()` aborts the request, clears transcript/draft/error and unlocks input without changing the selected document. Changing documents resets chat and aborts old requests. `UploadZone` serializes uploads and ignores late results after unmount. API requests forward Supabase Bearer tokens and AbortSignals.

Password login redirects from the server action after session cookies are written. Middleware validates with `getUser()`, propagates refreshed cookies to both request and response, and disables shared caching. Auth actions use `normalizeOriginValue()` for the selected env/header URL value.

## Key Configuration

Loaded by `backend/app/core/config.py` from repo root `.env` then `backend/.env` (override).

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | API key for OpenRouter |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter endpoint |
| `RAG_MODEL` | `openai/gpt-4o-mini` | LLM model for chat |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `EMBEDDING_DIMENSION` | `1536` | Configured hint; actual embedding response determines indexing dimension |
| `MILVUS_HOST` | `localhost` | Milvus server |
| `MILVUS_PORT` | `19530` | Milvus gRPC port |
| `MILVUS_COLLECTION` | `pdf_chunks` | Collection name |
| `MILVUS_VECTOR_DIM` | `1536` | Configured hint; collection schema must match actual vectors |
| `RETRIEVAL_TOP_K` | `8` | Number of chunks to retrieve |
| `MIN_RELEVANCE_SCORE` | `0.32` | Min cosine similarity threshold |
| `CHUNK_SIZE` | `1000` | Text chunk size |
| `CHUNK_OVERLAP` | `150` | Chunk overlap |
| `UPLOAD_MAX_SIZE_MB` | `50` | Max PDF upload size |

**Note:** Upload indexing uses `len(vectors[0])` to validate the collection schema. A dimension mismatch raises an error instead of recreating the collection. Changing these environment hints does not resize model output. `OPENAI_API_KEY` is accepted as a legacy alias for OpenRouter key.

## API Contract

### `POST /api/upload`

- **Input**: `multipart/form-data`, field `file` (PDF)
- **Auth**: `Authorization: Bearer <supabase_token>`
- **Output**: JSON with `doc_id`, `chunks_count`, `status`, `warnings`

### `POST /api/chat`

- **Input**: JSON `{ query, doc_id, language? }`
- **Auth**: `Authorization: Bearer <supabase_token>`
- **Output**: `text/event-stream`
  - `event: sources` — `[{page, source, score}]`
  - `event: token` — JSON-encoded text delta (not necessarily one model token)
  - `event: error` — JSON object `{"message": "..."}`
  - `event: done` — JSON string `"[DONE]"`

## Design Patterns

| Pattern | Usage |
|---------|-------|
| **Factory** | `create_chat_provider()`, `VectorStoreFactory`, `create_initialized_rag_pipeline()` |
| **Strategy** | `ChatProvider` → `OpenRouterChatProvider`, `VectorStore` → `MilvusVectorStore` |
| **Singleton** | `get_config()`, `get_embedder()` (@lru_cache) |
| **Dependency Injection** | FastAPI `Depends(require_supabase_user)` |
| **Streaming/Generator** | SSE events, LLM token streaming, SSE parser |

## Infra

`docker-compose.yml` provides:

- `etcd` — metadata store
- `minio` — object storage
- `milvus` — vector DB (gRPC: `localhost:19530`)
- `attu` — web UI (`http://localhost:8001`)

API deployment uses a separate `compose.production.yml`:

- `api` — non-root FastAPI image built from `backend/`; port 8000 is internal.
- `nginx` — HTTPS reverse proxy, unbuffered SSE and streaming uploads. Docker DNS re-resolves `api` after container replacement.
- `certbot` — on-demand webroot issuance/renewal using shared certificate/ACME volumes. The host systemd timer runs renewal, validates config and reloads Nginx.

Bootstrap HTTP serves only ACME and proxy liveness. HTTPS starts only after a certificate exists; the API's `/health` reports process liveness, not external service health. See `DEPLOYMENT.md` for commands and the current application prerequisites.
