# Migration Guide: New Architecture

## Overview

This guide helps you migrate from the old architecture to the new DocPixie-inspired architecture. The new architecture provides better separation of concerns, provider-agnostic configuration, and improved extensibility.

## What's Changed

### Key Improvements

1. **Provider-Agnostic Configuration**: Generic configuration that works with multiple LLM providers
2. **Pluggable Storage**: Support for multiple vector database backends
3. **Centralized Prompts**: All AI prompts in one location
4. **Better Models**: Comprehensive data models with Pydantic validation
5. **Factory Pattern**: Easy creation of providers and storage instances
6. **RAG Agent**: Intelligent query orchestration with conversation awareness

### Architecture Changes

```
Old Architecture:
├── config.py (flat configuration)
├── providers/ (direct API calls)
├── documents/ (mixed concerns)
└── routers/ (business logic)

New Architecture:
├── core/config.py (structured configuration)
├── providers/ (BaseProvider interface + implementations)
├── storage/ (BaseStorage interface + implementations)
├── models/ (data models)
├── ai/ (business logic layer)
└── routers/ (thin API layer)
```

## Breaking Changes

### 1. Configuration

**Old:**
```python
from app.config import (
    MILVUS_HOST,
    MILVUS_PORT,
    OPENAI_API_KEY,
    CHUNK_SIZE,
)
```

**New:**
```python
from app.core.config import get_config

config = get_config()
milvus_host = config.milvus_host
milvus_port = config.milvus_port
openai_api_key = config.openai_api_key
chunk_size = config.chunk_size
```

**Migration:** Update all imports to use `get_config()` and access configuration as attributes.

### 2. Provider Usage

**Old:**
```python
from app.providers.openrouter import stream_answer

async for token in stream_answer(messages):
    print(token)
```

**New:**
```python
from app.providers.factory import create_provider

provider = create_provider(provider="openrouter")

async for token in provider.stream_text_messages(messages):
    print(token)
```

**Migration:** Use the provider factory and BaseProvider interface.

### 3. Storage Operations

**Old:**
```python
from app.providers.milvus import insert_chunks_batch, search_chunks

insert_chunks_batch(doc_id, chunks, vectors)
chunks = search_chunks(query, doc_id)
```

**New:**
```python
from app.storage.factory import create_and_connect_storage

storage = await create_and_connect_storage(storage_type="milvus")

await storage.insert_chunks(doc_id, chunks, vectors)
chunks = await storage.search_chunks(query_vector, doc_id)
```

**Migration:** Use storage factory and BaseStorage interface. Note that methods are now async.

### 4. Document Processing

**Old:**
```python
from app.documents.indexing import run_indexing_pipeline_from_upload

result = run_indexing_pipeline_from_upload(file_content, filename)
```

**New:**
```python
from app.routers.upload import run_indexing_pipeline_from_upload

result = await run_indexing_pipeline_from_upload(file_content, filename)
```

**Migration:** The function is now async and returns an `IndexingResult` model.

### 5. Query Processing

**Old:**
```python
from app.documents.retrieval import search_chunks, build_context

chunks = search_chunks(query, doc_id)
context = build_context(chunks)
```

**New:**
```python
from app.ai.rag_agent import create_rag_agent_with_defaults

agent = await create_rag_agent_with_defaults()
result = await agent.process_query(query, doc_id)
answer = result.answer
chunks = result.retrieved_chunks
```

**Migration:** Use the RAG agent for query processing instead of direct retrieval.

## Step-by-Step Migration

### Phase 1: Update Configuration (1-2 hours)

1. **Update environment variables:**

```bash
# Old variables still work for backward compatibility
MILVUS_HOST=localhost
MILVUS_PORT=19530

# New structured variables (recommended)
RAG_PROVIDER=openrouter
RAG_MODEL=openai/gpt-4o-mini
RAG_TEMPERATURE=0.7
STORAGE_TYPE=milvus
```

2. **Update configuration imports:**

```python
# Find and replace
from app.config import X
# With
from app.core.config import get_config
config = get_config()
X = config.x
```

3. **Test configuration:**

```python
from app.core.config import get_config

config = get_config()
errors = config.validate()
if errors:
    print(f"Configuration errors: {errors}")
else:
    print("Configuration is valid!")
```

### Phase 2: Update Providers (2-3 hours)

1. **Identify all provider usage:**

```bash
grep -r "from app.providers" backend/app/
```

2. **Update to use factory:**

```python
# Old
from app.providers.openrouter import stream_answer

# New
from app.providers.factory import create_provider

provider = create_provider(provider="openrouter")
```

3. **Update method calls:**

```python
# Old
stream_answer(messages)

# New
provider.stream_text_messages(messages)
```

### Phase 3: Update Storage (2-3 hours)

1. **Identify all storage usage:**

```bash
grep -r "from app.providers.milvus" backend/app/
grep -r "insert_chunks_batch\|search_chunks" backend/app/
```

2. **Update to use storage factory:**

```python
# Old
from app.providers.milvus import insert_chunks_batch, search_chunks

# New
from app.storage.factory import create_and_connect_storage

storage = await create_and_connect_storage(storage_type="milvus")
```

3. **Update method calls to async:**

```python
# Old
insert_chunks_batch(doc_id, chunks, vectors)
chunks = search_chunks(query, doc_id)

# New
await storage.insert_chunks(doc_id, chunks, vectors)
chunks = await storage.search_chunks(query_vector, doc_id)
```

### Phase 4: Update Models (1-2 hours)

1. **Identify model usage:**

```bash
grep -r "from app.schemas" backend/app/
```

2. **Update to use new models:**

```python
# Old
from app.schemas import UploadResponse

# New
from app.models.document import IndexingResult
```

3. **Update model attributes:**

```python
# Old
response.doc_id
response.chunks_count

# New (same attributes, but with better type hints)
result.doc_id
result.chunks_count
```

### Phase 5: Update Query Processing (2-3 hours)

1. **Identify query processing code:**

```bash
grep -r "search_chunks\|build_context" backend/app/
```

2. **Update to use RAG agent:**

```python
# Old
chunks = search_chunks(query, doc_id)
context = build_context(chunks)
# ... generate response

# New
from app.ai.rag_agent import create_rag_agent_with_defaults

agent = await create_rag_agent_with_defaults()
result = await agent.process_query(query, doc_id)
answer = result.answer
```

### Phase 6: Update API Endpoints (1-2 hours)

1. **Review router changes:**

```python
# Old
@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile) -> UploadResponse:
    result = run_indexing_pipeline_from_upload(...)
    return UploadResponse(...)

# New
@router.post("/upload")
async def upload_pdf(file: UploadFile) -> IndexingResult:
    result = await run_indexing_pipeline_from_upload(...)
    return result
```

2. **Update request/response models:**

```python
# Old
from app.schemas import ChatRequest, UploadResponse

# New
from app.models.document import IndexingResult
# Request is now a dict, not a Pydantic model
```

### Phase 7: Testing (3-4 hours)

1. **Unit tests:**

```python
# Test configuration
from app.core.config import get_config

def test_config():
    config = get_config()
    assert config.provider == "openrouter"
    assert config.storage_type == "milvus"

# Test provider
from app.providers.factory import create_provider

async def test_provider():
    provider = create_provider(provider="openrouter")
    response = await provider.process_text_messages([{"role": "user", "content": "test"}])
    assert response is not None

# Test storage
from app.storage.factory import create_and_connect_storage

async def test_storage():
    storage = await create_and_connect_storage(storage_type="milvus")
    health = await storage.health_check()
    assert health["status"] == "healthy"

# Test RAG agent
from app.ai.rag_agent import create_rag_agent_with_defaults

async def test_rag_agent():
    agent = await create_rag_agent_with_defaults()
    result = await agent.process_query("test query", "test-doc")
    assert result.answer is not None
    await agent.shutdown()
```

2. **Integration tests:**

```python
async def test_full_workflow():
    # Upload document
    # Query document
    # Verify results
    pass
```

3. **Manual testing:**

```bash
# Start services
docker-compose up -d

# Test upload
curl -X POST http://localhost:8000/api/upload \
  -F "file=@test.pdf"

# Test chat
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the main topic?", "doc_id": "..."}'
```

## Code Comparison Examples

### Example 1: Document Upload

**Old:**
```python
from app.documents.indexing import run_indexing_pipeline_from_upload
from app.schemas import UploadResponse

@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile) -> UploadResponse:
    result = run_indexing_pipeline_from_upload(file_content, filename)
    return UploadResponse(
        doc_id=result.doc_id,
        chunks_count=result.chunks_count,
        message="Upload completed"
    )
```

**New:**
```python
from app.routers.upload import run_indexing_pipeline_from_upload
from app.models.document import IndexingResult

@router.post("/upload")
async def upload_pdf(file: UploadFile) -> IndexingResult:
    result = await run_indexing_pipeline_from_upload(file_content, filename)
    return result
```

### Example 2: Query Processing

**Old:**
```python
from app.documents.retrieval import search_chunks, build_context, SYSTEM_PROMPT_VI
from app.providers.openrouter import stream_answer

async def _stream_chat_sse(query: str, doc_id: str):
    chunks = search_chunks(query, doc_id)
    context = build_context(chunks)
    
    messages = [
        {"role": "system", "content": f"{SYSTEM_PROMPT_VI}\n\nContext:\n{context}"},
        {"role": "user", "content": query}
    ]
    
    async for token in stream_answer(messages):
        yield token
```

**New:**
```python
from app.ai.rag_agent import create_rag_agent_with_defaults
from app.models.document import QueryMode

async def _stream_chat_sse(query: str, doc_id: str):
    agent = await create_rag_agent_with_defaults()
    
    try:
        async for token in agent.process_query_stream(
            query=query,
            doc_id=doc_id,
            mode=QueryMode.RAG
        ):
            yield token
    finally:
        await agent.shutdown()
```

### Example 3: Direct Storage Access

**Old:**
```python
from app.providers.milvus import insert_chunks_batch, search_chunks

# Insert
insert_chunks_batch(doc_id, chunks, vectors)

# Search
chunks = search_chunks(query, doc_id, top_k=8)
```

**New:**
```python
from app.storage.factory import create_and_connect_storage

storage = await create_and_connect_storage(storage_type="milvus")

try:
    # Insert
    await storage.insert_chunks(doc_id, chunks, vectors)
    
    # Search
    query_vector = embedder.embed_documents([query])[0]
    chunks = await storage.search_chunks(query_vector, doc_id, top_k=8)
finally:
    await storage.disconnect()
```

## Migration Checklist

- [ ] Update environment variables
- [ ] Update configuration imports
- [ ] Update provider usage
- [ ] Update storage operations
- [ ] Update model imports
- [ ] Update query processing
- [ ] Update API endpoints
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Manual testing
- [ ] Update documentation
- [ ] Train team on new architecture

## Common Issues and Solutions

### Issue 1: Async/Await Errors

**Problem:** `RuntimeError: This function is coroutine but not awaited`

**Solution:** Make sure to await all async methods:

```python
# Wrong
storage.insert_chunks(doc_id, chunks, vectors)

# Correct
await storage.insert_chunks(doc_id, chunks, vectors)
```

### Issue 2: Import Errors

**Problem:** `ModuleNotFoundError: No module named 'app.core'`

**Solution:** Ensure all new modules are created:

```bash
backend/app/core/__init__.py
backend/app/core/config.py
backend/app/storage/__init__.py
backend/app/storage/base.py
backend/app/storage/milvus_storage.py
backend/app/storage/factory.py
```

### Issue 3: Configuration Validation Errors

**Problem:** `ValueError: API key required for provider: openrouter`

**Solution:** Set the required API key:

```bash
export OPENROUTER_API_KEY=sk-...
```

Or use test key for testing:

```python
config = get_config()
config.openrouter_api_key = "test-key"
```

### Issue 4: Storage Connection Errors

**Problem:** `RuntimeError: Milvus connection failed`

**Solution:** Ensure Milvus is running:

```bash
docker-compose up -d milvus
docker-compose ps milvus
```

Check connection:

```python
storage = await create_and_connect_storage()
health = await storage.health_check()
print(health)
```

### Issue 5: Model Attribute Errors

**Problem:** `AttributeError: 'IndexingResult' object has no attribute 'message'`

**Solution:** Update to use new model attributes:

```python
# Old
result.message

# New
result.warnings  # List of warnings
# Or build message manually
message = "Upload completed"
if result.warnings:
    message += " " + " ".join(result.warnings)
```

## Rollback Plan

If issues arise during migration, you can rollback:

1. **Keep old code in version control:**

```bash
git checkout -b old-architecture
git add .
git commit -m "Backup old architecture before migration"
```

2. **Revert changes:**

```bash
git checkout main
git merge old-architecture
```

3. **Restore old files:**

```bash
# Restore old config
git checkout old-architecture -- backend/app/config.py

# Restore old providers
git checkout old-architecture -- backend/app/providers/

# Restore old documents
git checkout old-architecture -- backend/app/documents/

# Restore old routers
git checkout old-architecture -- backend/app/routers/
```

4. **Restart services:**

```bash
docker-compose restart backend
```

## Performance Considerations

### Before Migration

- Monitor current performance metrics
- Record response times
- Note memory usage
- Document API throughput

### After Migration

- Compare performance metrics
- Identify any regressions
- Optimize if needed
- Update performance baselines

### Optimization Tips

1. **Reuse instances:**

```python
# Good - reuse provider and storage
provider = create_provider()
storage = await create_and_connect_storage()

# Use them for multiple requests
for request in requests:
    await process_request(provider, storage)

# Bad - create new instances each time
for request in requests:
    provider = create_provider()
    storage = await create_and_connect_storage()
    await process_request(provider, storage)
```

2. **Use streaming for large responses:**

```python
# Good - streaming
async for token in agent.process_query_stream(query, doc_id):
    yield token

# Bad - load entire response
result = await agent.process_query(query, doc_id)
yield result.answer
```

3. **Batch operations:**

```python
# Good - batch insert
await storage.insert_chunks(doc_id, chunks, vectors, batch_size=64)

# Bad - insert one by one
for chunk, vector in zip(chunks, vectors):
    await storage.insert_chunks(doc_id, [chunk], [vector])
```

## Support and Resources

### Documentation

- [Architecture Overview](./ARCHITECTURE.md)
- [Codebase Overview](./CODEBASE_OVERVIEW.md)
- [API Documentation](http://localhost:8000/docs)

### Getting Help

1. Check this migration guide
2. Review architecture documentation
3. Look at code examples
4. Check test files for usage patterns

### Testing Tools

```bash
# Run tests
pytest backend/app/tests/

# Run with coverage
pytest --cov=backend/app backend/app/tests/

# Run specific test
pytest backend/app/tests/test_rag_agent.py
```

## Next Steps

After completing the migration:

1. **Monitor production:**
   - Watch error logs
   - Monitor performance
   - Track user feedback

2. **Optimize:**
   - Identify bottlenecks
   - Implement caching
   - Optimize queries

3. **Extend:**
   - Add new providers
   - Add new storage backends
   - Implement advanced features

4. **Document:**
   - Update API docs
   - Write guides
   - Create examples

## Conclusion

This migration guide provides a comprehensive path from the old architecture to the new DocPixie-inspired architecture. Take it step by step, test thoroughly, and don't hesitate to rollback if needed.

The new architecture provides better separation of concerns, improved extensibility, and a more maintainable codebase. The investment in migration will pay off in easier development and better long-term maintainability.

Good luck with your migration!