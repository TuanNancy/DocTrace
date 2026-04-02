# Codebase Review and Cleanup (2026-04-02)

## Objective

Review the entire repository, remove unused functionality, reduce documentation drift, and keep only the logic currently used by runtime flow.

## Review Method

1. Traced backend imports and runtime call chain:
   - `app/main.py` -> routers
   - `routers/upload.py` -> processors/providers/storage
   - `routers/chat.py` -> `ai/rag_agent.py`
2. Checked references for legacy modules via repo-wide search.
3. Compared documentation claims with implementation in:
   - `backend/app/core/config.py`
   - `backend/app/providers/factory.py`
   - `backend/app/storage/factory.py`
4. Ran runtime sanity checks:
   - dependency install
   - Milvus connectivity
   - embedding + chat smoke tests
   - end-to-end RAG query

## Current Runtime Truth

- Provider path: OpenRouter only
- Embeddings: OpenRouter `/v1/embeddings`
- Vector DB: Milvus only
- Main flow: upload -> chunk -> embed -> insert -> retrieve -> stream answer

No runtime path uses multi-provider switching, documents legacy wrappers, or deprecated retrieval stubs.

## Cleanup Performed

### Removed unused backend code

- Deleted `backend/app/ai/prompts_rag.py`
  - Not imported anywhere in runtime path.
- Deleted `backend/app/documents/` legacy wrappers
  - `__init__.py`
  - `indexing.py`
  - `retrieval.py`
- Deleted `backend/app/processors/legacy_retrieval.py`
  - Deprecated stubs only, not used.
- Deleted `backend/app/core/utils.py`
  - Empty placeholder.
- Deleted `backend/app/services/__init__.py`
  - Empty placeholder package.

### Code cleanup

- Updated `backend/app/ai/rag_agent.py`
  - Removed unused import `format_response_synthesizer`.

## Documentation Cleanup Performed

### Removed duplicated/outdated root docs

- Deleted `README_NEW_ARCHITECTURE.md`
- Deleted `QUICKSTART.md`
- Deleted `IMPLEMENTATION_SUMMARY.md`
- Deleted `PROJECT_SUMMARY.md`
- Deleted `MIGRATION_GUIDE.md`

These files overlapped heavily and contained stale claims (multi-provider runtime, deprecated paths, old env names).

### Updated retained docs

- Updated `README.md`
  - Corrected stack wording for embeddings via OpenRouter.
  - Updated `.env` examples to current variable names (`RAG_MODEL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`).
  - Clarified dimension alignment with Milvus.
  - Removed outdated test/script section pointing to non-existent files.
- Replaced `ARCHITECTURE.md`
  - Rewritten to match current code and runtime flow only.
- Updated `CODEBASE_OVERVIEW.md`
  - Removed references to deleted docs.
  - Added link to this review file.

## Final Documentation Set

- `README.md` (primary run/use guide)
- `ARCHITECTURE.md` (technical architecture)
- `CODEBASE_OVERVIEW.md` (quick orientation)
- `CODEBASE_REVIEW_2026-04-02.md` (this detailed review)
- `frontend/README.md` (frontend-specific run notes)

## Validation Notes

After cleanup and previous runtime fixes:

- Backend dependencies install successfully.
- Milvus connectivity succeeds.
- Chat model call succeeds.
- Embedding model call succeeds with expected vector dimension.
- End-to-end RAG query returns answer and retrieved chunks.

## Remaining Recommendations (Optional)

1. Add automated tests for:
   - upload pipeline
   - SSE chat stream parser
   - Milvus retrieval thresholds
2. Restrict CORS for production.
3. Add a lightweight docs check in CI to prevent future drift.
4. Add an archive folder if historical docs need long-term retention.
