# RAG PDF Chatbot Architecture

## Scope

Project implements a standard text-based RAG flow for PDF:

- No OCR/computer vision in the main pipeline
- No multi-agent task planner in runtime flow
- Single LLM provider path: OpenRouter (chat + embeddings)
- Single storage backend path: Milvus

## Runtime Flow

```text
Upload PDF
  -> extract text by page
  -> split into chunks
  -> generate embeddings
  -> insert vectors + metadata into Milvus

Chat query (with doc_id)
  -> embed query
  -> search top-k chunks from Milvus
  -> build bounded context with page citations
  -> call chat model via OpenRouter
  -> stream SSE events: sources -> token -> done
```

## Backend Structure

```text
backend/app/
├── main.py                  # FastAPI app + CORS + router mount
├── core/
│   └── config.py            # Centralized env-based config
├── routers/
│   ├── upload.py            # POST /api/upload
│   └── chat.py              # POST /api/chat (SSE)
├── processors/
│   └── pdf.py               # PDF loading + chunking
├── providers/
│   ├── base.py              # LLM provider interface
│   ├── openrouter.py        # OpenRouter chat provider
│   ├── embeddings.py        # OpenRouter embeddings
│   └── factory.py           # Provider factory
├── storage/
│   ├── base.py              # Storage interface
│   ├── milvus_storage.py    # Milvus implementation
│   └── factory.py           # Storage factory
├── ai/
│   ├── prompts.py           # Prompt templates
│   └── rag_agent.py         # Retrieval + synthesis orchestration
└── models/
    ├── document.py          # Query/indexing models
    └── agent.py             # Conversation context models
```

## Frontend Structure

```text
frontend/src/
├── app/page.tsx             # main screen (upload + chat)
├── components/UploadZone.tsx
├── components/ChatWindow.tsx
├── components/SourceCard*.tsx
└── lib/api.ts               # upload/chat API + SSE parser
```

## Key Configuration

Loaded by `backend/app/core/config.py` from:

1. repo root `.env`
2. `backend/.env` (override)

Important variables:

- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `RAG_MODEL`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIMENSION`
- `MILVUS_HOST`
- `MILVUS_PORT`
- `MILVUS_COLLECTION`
- `MILVUS_VECTOR_DIM`
- `RETRIEVAL_TOP_K`
- `MIN_RELEVANCE_SCORE`
- `CHUNK_SIZE`
- `CHUNK_OVERLAP`

Notes:

- `EMBEDDING_DIMENSION` and `MILVUS_VECTOR_DIM` must match embedding output.
- `STORAGE_TYPE` currently supports only `milvus`.
- `OPENAI_API_KEY` is treated as a legacy alias for OpenRouter key if needed.

## API Contract

### `POST /api/upload`

- Input: `multipart/form-data`, field `file` (PDF)
- Output: indexing result with `doc_id`, `chunks_count`, status metadata

### `POST /api/chat`

- Input JSON:
  - `query`
  - `doc_id`
  - optional `language` (`vi`/`en`)
- Output: `text/event-stream`
  - `event: sources`
  - `event: token`
  - `event: error` (if any)
  - `event: done`

## Infra

`docker-compose.yml` provides:

- `etcd`
- `minio`
- `milvus`
- `attu` (web UI)

Milvus gRPC endpoint: `localhost:19530`.
