# RAG PDF Chatbot — Architecture

## Scope

- Standard text-based RAG flow for PDF
- No OCR/computer vision in the main pipeline
- No multi-agent task planner
- Single LLM provider: OpenRouter (chat + embeddings)
- Single storage backend: Milvus
- Auth: Supabase Auth (JWT)

## Runtime Flow

```
Upload PDF
  → extract text by page (PyPDFLoader)
  → split into chunks (RecursiveCharacterTextSplitter)
  → generate embeddings (OpenRouter /v1/embeddings)
  → insert vectors + metadata into Milvus

Chat query (with doc_id)
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
│   ├── config.py            # RAGConfig dataclass + env loading + singleton
│   └── auth.py              # Supabase JWT verification
│
├── routers/
│   ├── upload.py            # POST /api/upload — PDF upload + indexing
│   └── chat.py              # POST /api/chat — SSE streaming
│
├── processors/
│   └── pdf.py               # PDF loading + chunking (LangChain)
│
├── providers/
│   ├── base.py              # Abstract BaseProvider interface
│   ├── openrouter.py        # OpenRouter implementation (AsyncOpenAI)
│   ├── embeddings.py        # OpenAIEmbedder via OpenRouter
│   └── factory.py           # create_provider() factory
│
├── storage/
│   ├── base.py              # Abstract BaseStorage + dataclasses
│   ├── milvus_storage.py    # Milvus implementation (pymilvus)
│   └── factory.py           # StorageFactory + helpers
│
├── ai/
│   ├── prompts.py           # System prompts (VI + EN)
│   └── rag_agent.py         # RAGAgent: retrieve → context → stream LLM
│
├── models/
│   ├── document.py          # DocumentStatus, QueryMode, RetrievedChunk, IndexingResult
│   └── agent.py             # MessageRole, ConversationMessage, ConversationContext
│
└── services/
    └── supabase_pdf_storage.py  # PDF backup to Supabase S3 (boto3)
```

## Frontend Structure

```
frontend/src/
├── middleware.ts              # Next.js edge middleware (auth redirect)
│
├── types/
│   └── index.ts               # TypeScript types
│
├── lib/
│   ├── api.ts                 # streamChat(), uploadPDF(), SSE parser
│   ├── client.ts              # Supabase browser client
│   ├── server.ts              # Supabase server client
│   ├── middleware.ts          # updateSession() for auth redirect
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

## Key Configuration

Loaded by `backend/app/core/config.py` from repo root `.env` then `backend/.env` (override).

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | API key for OpenRouter |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter endpoint |
| `RAG_MODEL` | `openai/gpt-4o-mini` | LLM model for chat |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `EMBEDDING_DIMENSION` | `1536` | Vector dimension |
| `MILVUS_HOST` | `localhost` | Milvus server |
| `MILVUS_PORT` | `19530` | Milvus gRPC port |
| `MILVUS_COLLECTION` | `pdf_chunks` | Collection name |
| `MILVUS_VECTOR_DIM` | `1536` | Must match EMBEDDING_DIMENSION |
| `RETRIEVAL_TOP_K` | `8` | Number of chunks to retrieve |
| `MIN_RELEVANCE_SCORE` | `0.32` | Min cosine similarity threshold |
| `CHUNK_SIZE` | `1000` | Text chunk size |
| `CHUNK_OVERLAP` | `150` | Chunk overlap |
| `UPLOAD_MAX_SIZE_MB` | `50` | Max PDF upload size |

**Note:** `EMBEDDING_DIMENSION` and `MILVUS_VECTOR_DIM` must match. `OPENAI_API_KEY` is accepted as a legacy alias for OpenRouter key.

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
  - `event: token` — streamed text token
  - `event: error` — error message
  - `event: done` — `[DONE]`

## Design Patterns

| Pattern | Usage |
|---------|-------|
| **Factory** | `create_provider()`, `StorageFactory`, `create_rag_agent_with_defaults()` |
| **Strategy** | `BaseProvider` → `OpenRouterProvider`, `BaseStorage` → `MilvusStorage` |
| **Singleton** | `get_config()`, `get_embedder()` (@lru_cache) |
| **Dependency Injection** | FastAPI `Depends(require_supabase_user)` |
| **Streaming/Generator** | SSE events, LLM token streaming, SSE parser |

## Infra

`docker-compose.yml` provides:

- `etcd` — metadata store
- `minio` — object storage
- `milvus` — vector DB (gRPC: `localhost:19530`)
- `attu` — web UI (`http://localhost:8001`)
