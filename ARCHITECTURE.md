# RAG PDF Chatbot Architecture

## Overview

This project implements a Retrieval-Augmented Generation (RAG) system for PDF document querying. The architecture follows the **DocPixie** reference architecture but is adapted for **embeddings/vector databases** instead of vision AI.

### Key Design Principles

1. **Provider-Agnostic Configuration**: Generic configuration that works with multiple LLM providers (OpenRouter, OpenAI, Anthropic)
2. **Separation of Concerns**: Clear boundaries between providers, storage, AI operations, and models
3. **Vector-Based Processing**: Uses embeddings and vector databases for semantic search instead of vision models
4. **Adaptive RAG Agent**: Intelligent query processing with context awareness
5. **Conversation Awareness**: Maintains conversation history for multi-turn interactions
6. **Pluggable Storage**: Support for multiple vector database backends (Milvus, in-memory)
7. **Centralized Prompt Management**: All AI prompts in one location for easy maintenance

## Architecture Comparison

### DocPixie (Vision-Based)
```
PDF → Images → Vision Model → Page Selection → Analysis → Response
```

### RAG PDF Chatbot (Embedding-Based)
```
PDF → Text → Chunking → Embeddings → Vector Search → Context → LLM → Response
```

## Directory Structure

```
backend/app/
├── __init__.py                 # Package initialization
├── main.py                     # FastAPI application entry point
├── config.py                   # Backward compatibility config wrapper
│
├── core/                       # Core configuration and utilities
│   ├── __init__.py
│   ├── config.py              # Main configuration class (RAGConfig)
│   └── utils.py               # Utility functions
│
├── providers/                  # LLM and embedding providers
│   ├── __init__.py
│   ├── base.py                # BaseProvider interface
│   ├── openrouter.py          # OpenRouter provider implementation
│   ├── embeddings.py          # Embedding provider (OpenAI, sentence-transformers)
│   └── factory.py             # Provider factory for creating instances
│
├── storage/                    # Vector database storage backends
│   ├── __init__.py
│   ├── base.py                # BaseStorage interface
│   ├── milvus_storage.py      # Milvus implementation
│   └── factory.py             # Storage factory for creating instances
│
├── models/                     # Data models
│   ├── __init__.py
│   ├── document.py            # Document, chunk, and query models
│   └── agent.py               # Conversation and agent task models
│
├── ai/                         # AI operations and business logic
│   ├── __init__.py
│   ├── rag_agent.py           # Main RAG agent orchestrator
│   └── prompts.py             # Centralized AI prompts
│
├── documents/                  # Document processing (legacy, being refactored)
│   ├── __init__.py
│   ├── indexing.py            # PDF indexing pipeline
│   └── retrieval.py           # Vector search retrieval
│
├── routers/                    # API endpoints
│   ├── __init__.py
│   ├── upload.py              # PDF upload endpoint
│   └── chat.py                # Chat/query endpoint
│
├── services/                   # Business services (future expansion)
│   └── __init__.py
│
└── schemas.py                  # Pydantic schemas for API
```

## Core Components

### 1. Configuration System (`core/config.py`)

The `RAGConfig` class provides provider-agnostic configuration:

```python
from app.core.config import get_config

config = get_config()

# Access configuration
print(config.provider)           # "openrouter", "openai", "anthropic"
print(config.model)              # "openai/gpt-4o-mini"
print(config.milvus_host)        # "localhost"
print(config.chunk_size)         # 1000
```

**Key Features:**
- Environment variable loading with sensible defaults
- Provider-specific defaults
- Configuration validation
- Support for test API keys

**Environment Variables:**

```bash
# LLM Provider
RAG_PROVIDER=openrouter
RAG_MODEL=openai/gpt-4o-mini
RAG_TEMPERATURE=0.7
RAG_MAX_TOKENS=4096

# API Keys
OPENROUTER_API_KEY=sk-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-...

# Vector Database (Milvus)
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=pdf_chunks
MILVUS_VECTOR_DIM=1536

# Document Processing
CHUNK_SIZE=1000
CHUNK_OVERLAP=150
MIN_CHARS_PER_PAGE=50

# Upload
UPLOAD_MAX_SIZE_MB=50

# RAG Settings
RETRIEVAL_TOP_K=8
CONTEXT_MAX_CHARS=6000
MIN_RELEVANCE_SCORE=0.5
```

### 2. Provider System (`providers/`)

The provider system abstracts LLM API interactions behind a common interface.

#### BaseProvider Interface

```python
from app.providers.base import BaseProvider

class BaseProvider(ABC):
    @abstractmethod
    async def process_text_messages(messages, max_tokens, temperature) -> str:
        """Process text messages and return complete response."""
        pass

    @abstractmethod
    async def stream_text_messages(messages, max_tokens, temperature) -> AsyncIterator[str]:
        """Stream text messages and yield tokens."""
        pass

    async def process_with_context(query, context, system_prompt) -> str:
        """Convenience method for RAG with document context."""
        pass
```

#### OpenRouter Provider

```python
from app.providers.openrouter import OpenRouterProvider

provider = OpenRouterProvider(
    api_key="sk-...",
    model="openai/gpt-4o-mini",
    base_url="https://openrouter.ai/api/v1"
)

# Process messages
response = await provider.process_text_messages(
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=1000
)

# Stream response
async for token in provider.stream_text_messages(
    messages=[{"role": "user", "content": "Hello"}]
):
    print(token, end="")
```

#### Provider Factory

```python
from app.providers.factory import create_provider

# Create provider from config
provider = create_provider(
    provider="openrouter",
    model="openai/gpt-4o-mini"
)

# Get default provider from global config
provider = get_default_provider()
```

### 3. Storage System (`storage/`)

The storage system abstracts vector database operations behind a common interface.

#### BaseStorage Interface

```python
from app.storage.base import BaseStorage

class BaseStorage(ABC):
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to storage backend."""
        pass

    @abstractmethod
    async def insert_chunks(doc_id, chunks, vectors) -> InsertResult:
        """Insert document chunks with embeddings."""
        pass

    @abstractmethod
    async def search_chunks(query_vector, doc_id, top_k) -> List[RetrievedChunk]:
        """Search for similar chunks using vector similarity."""
        pass

    @abstractmethod
    async def delete_document(doc_id) -> bool:
        """Delete a document and all its chunks."""
        pass
```

#### Milvus Storage

```python
from app.storage.milvus_storage import MilvusStorage

storage = MilvusStorage(config={
    "host": "localhost",
    "port": 19530,
    "collection": "pdf_chunks",
    "vector_dim": 1536
})

await storage.connect()

# Insert chunks
result = await storage.insert_chunks(
    doc_id="doc-123",
    chunks=[{"text": "...", "page": 1, "source": "doc.pdf"}],
    vectors=[[0.1, 0.2, ...]]
)

# Search chunks
chunks = await storage.search_chunks(
    query_vector=[0.1, 0.2, ...],
    doc_id="doc-123",
    top_k=8
)

await storage.disconnect()
```

#### Storage Factory

```python
from app.storage.factory import create_storage, create_and_connect_storage

# Create storage
storage = create_storage(storage_type="milvus")

# Create and connect in one call
storage = await create_and_connect_storage(storage_type="milvus")
```

### 4. Data Models (`models/`)

#### Document Models

```python
from app.models.document import (
    Document,
    DocumentChunk,
    RetrievedChunk,
    QueryResult,
    DocumentStatus,
    QueryMode
)

# Create a document
document = Document(
    doc_id="doc-123",
    name="document.pdf",
    source="/path/to/document.pdf",
    chunks_count=42,
    status=DocumentStatus.COMPLETED,
    created_at=datetime.utcnow()
)

# Create a query result
result = QueryResult(
    query="What is the main topic?",
    answer="The main topic is...",
    retrieved_chunks=[...],
    mode=QueryMode.RAG,
    processing_time=1.234
)
```

#### Agent Models

```python
from app.models.agent import (
    ConversationMessage,
    AgentTask,
    TaskPlan,
    TaskResult,
    MessageRole,
    TaskType
)

# Create a conversation message
message = ConversationMessage(
    role=MessageRole.USER,
    content="What is the main topic?",
    timestamp=datetime.utcnow(),
    message_id="msg-123"
)

# Create a task
task = AgentTask(
    task_id="task-456",
    task_type=TaskType.RETRIEVAL,
    name="Retrieve relevant chunks",
    description="Search for chunks related to the query",
    status=TaskStatus.PENDING
)
```

### 5. RAG Agent (`ai/rag_agent.py`)

The RAG agent orchestrates the complete query processing workflow.

```python
from app.ai.rag_agent import create_rag_agent_with_defaults

# Create and initialize agent
agent = await create_rag_agent_with_defaults()

# Process a query
result = await agent.process_query(
    query="What is the main topic?",
    doc_id="doc-123",
    mode=QueryMode.AUTO,
    language="vi"
)

print(result.answer)
print(f"Retrieved {len(result.retrieved_chunks)} chunks")
print(f"Processing time: {result.processing_time}s")

# Stream a query
async for token in agent.process_query_stream(
    query="What is the main topic?",
    doc_id="doc-123"
):
    print(token, end="")

# Get conversation context
context = await agent.get_conversation_context()
print(f"Conversation length: {context.total_message_count}")

# Cleanup
await agent.shutdown()
```

**RAG Workflow:**

1. **Query Classification**: Determine if retrieval is needed
2. **Context Processing**: Manage conversation history
3. **Vector Search**: Retrieve relevant chunks using embeddings
4. **Context Building**: Format retrieved chunks for LLM
5. **Response Generation**: Generate answer with citations
6. **Conversation Update**: Add interaction to history

### 6. AI Prompts (`ai/prompts.py`)

All AI prompts are centralized in one location for easy maintenance.

```python
from app.ai.prompts import PromptTemplates, format_response_synthesizer

# Get system prompt
system_prompt = PromptTemplates.get_system_prompt(language="vi")

# Format prompt with context
formatted_prompt = format_response_synthesizer(
    query="What is the main topic?",
    search_results="[Trang 1] (độ liên quan: 0.95)\nContent...",
    language="vi"
)
```

**Available Prompts:**
- System prompts (Vietnamese and English)
- Context summarizer
- Query reformulator
- Query classifier
- Response synthesizer
- Task planner
- Document summarizer
- Chunk analyzer

## API Endpoints

### Upload PDF

```bash
POST /api/upload
Content-Type: multipart/form-data

file: <PDF file>
```

**Response:**

```json
{
  "doc_id": "uuid-1234",
  "name": "document.pdf",
  "chunks_count": 42,
  "status": "completed",
  "processing_time": 2.345,
  "created_at": "2024-01-15T10:30:00",
  "warnings": []
}
```

### Chat/Query

```bash
POST /api/chat
Content-Type: application/json

{
  "query": "What is the main topic?",
  "doc_id": "uuid-1234",
  "language": "vi"
}
```

**Response (SSE Stream):**

```
event: token
data: "The"

event: token
data: " main"

event: token
data: " topic"

event: sources
data: [{"page": 1, "source": "document.pdf", "score": 0.95}]

event: done
data: "[DONE]"
```

## Usage Examples

### Example 1: Basic RAG Query

```python
from app.ai.rag_agent import create_rag_agent_with_defaults
from app.models.document import QueryMode

async def basic_rag_query():
    # Create agent
    agent = await create_rag_agent_with_defaults()
    
    try:
        # Process query
        result = await agent.process_query(
            query="What are the key benefits?",
            doc_id="doc-123",
            mode=QueryMode.RAG,
            language="vi"
        )
        
        # Print results
        print(f"Answer: {result.answer}")
        print(f"Sources: {result.get_sources()}")
        print(f"Pages: {result.get_pages()}")
        print(f"Processing time: {result.processing_time}s")
        
    finally:
        await agent.shutdown()
```

### Example 2: Streaming Response

```python
from app.ai.rag_agent import create_rag_agent_with_defaults

async def streaming_query():
    agent = await create_rag_agent_with_defaults()
    
    try:
        print("Answer: ", end="", flush=True)
        
        async for token in agent.process_query_stream(
            query="Explain the main concept",
            doc_id="doc-123",
            language="vi"
        ):
            print(token, end="", flush=True)
        
        print()  # New line
        
    finally:
        await agent.shutdown()
```

### Example 3: Multi-turn Conversation

```python
from app.ai.rag_agent import create_rag_agent_with_defaults

async def multi_turn_conversation():
    agent = await create_rag_agent_with_defaults()
    
    try:
        # First query
        result1 = await agent.process_query(
            query="What is the main topic?",
            doc_id="doc-123"
        )
        print(f"Q1: {result1.answer}")
        
        # Follow-up query (uses conversation context)
        result2 = await agent.process_query(
            query="Can you explain more about that?",
            doc_id="doc-123"
        )
        print(f"Q2: {result2.answer}")
        
        # Check conversation
        context = await agent.get_conversation_context()
        print(f"Conversation length: {context.total_message_count}")
        
    finally:
        await agent.shutdown()
```

### Example 4: Custom Provider

```python
from app.providers.openrouter import OpenRouterProvider
from app.storage.factory import create_and_connect_storage
from app.ai.rag_agent import RAGAgent

async def custom_provider_query():
    # Create custom provider
    provider = OpenRouterProvider(
        api_key="sk-...",
        model="anthropic/claude-3-opus",
        base_url="https://openrouter.ai/api/v1"
    )
    
    # Create storage
    storage = await create_and_connect_storage(storage_type="milvus")
    
    # Create agent with custom provider
    agent = RAGAgent(provider=provider, storage=storage)
    await agent.initialize()
    
    try:
        result = await agent.process_query(
            query="What is the main topic?",
            doc_id="doc-123"
        )
        print(result.answer)
        
    finally:
        await agent.shutdown()
```

### Example 5: Direct Storage Operations

```python
from app.storage.factory import create_and_connect_storage
from app.providers.embeddings import get_embedder

async def direct_storage_operations():
    storage = await create_and_connect_storage(storage_type="milvus")
    embedder = get_embedder()
    
    try:
        # Search chunks
        query_vector = embedder.embed_documents(["search query"])[0]
        chunks = await storage.search_chunks(
            query_vector=query_vector,
            doc_id="doc-123",
            top_k=5
        )
        
        for chunk in chunks:
            print(f"Page {chunk.page}: {chunk.text[:100]}...")
            print(f"Score: {chunk.score}")
        
        # Get document metadata
        metadata = await storage.get_document_metadata("doc-123")
        print(f"Document: {metadata.name}")
        print(f"Chunks: {metadata.chunks_count}")
        
        # List all documents
        documents = await storage.list_documents(limit=10)
        for doc in documents:
            print(f"{doc.doc_id}: {doc.name}")
        
    finally:
        await storage.disconnect()
```

## Extensibility

### Adding a New LLM Provider

1. Create provider class implementing `BaseProvider`:

```python
# app/providers/custom_provider.py
from app.providers.base import BaseProvider

class CustomProvider(BaseProvider):
    async def process_text_messages(self, messages, max_tokens, temperature):
        # Implement custom API call
        pass

    async def stream_text_messages(self, messages, max_tokens, temperature):
        # Implement streaming
        pass
```

2. Register with factory:

```python
# app/providers/factory.py
from app.providers.custom_provider import CustomProvider

ProviderFactory.register_provider("custom", CustomProvider)
```

3. Use in configuration:

```bash
RAG_PROVIDER=custom
RAG_MODEL=custom-model-name
CUSTOM_API_KEY=sk-...
```

### Adding a New Storage Backend

1. Create storage class implementing `BaseStorage`:

```python
# app/storage/custom_storage.py
from app.storage.base import BaseStorage

class CustomStorage(BaseStorage):
    async def connect(self):
        # Implement connection
        pass

    async def insert_chunks(self, doc_id, chunks, vectors):
        # Implement insertion
        pass

    async def search_chunks(self, query_vector, doc_id, top_k):
        # Implement search
        pass
```

2. Register with factory:

```python
# app/storage/factory.py
from app.storage.custom_storage import CustomStorage

StorageFactory.register_backend("custom", CustomStorage)
```

3. Use in configuration:

```bash
STORAGE_TYPE=custom
CUSTOM_HOST=localhost
CUSTOM_PORT=1234
```

## Testing

### Unit Tests

```python
import pytest
from app.ai.rag_agent import create_rag_agent_with_defaults

@pytest.mark.asyncio
async def test_rag_agent_query():
    agent = await create_rag_agent_with_defaults()
    
    try:
        result = await agent.process_query(
            query="test query",
            doc_id="test-doc"
        )
        
        assert result.answer is not None
        assert result.processing_time > 0
        
    finally:
        await agent.shutdown()
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_full_workflow():
    # Upload document
    # Query document
    # Verify results
    pass
```

## Performance Considerations

### Embedding Caching

Embeddings are cached using `lru_cache` to avoid redundant API calls:

```python
from app.providers.embeddings import get_embedder

embedder = get_embedder()
# Subsequent calls with same text use cached embeddings
```

### Batch Processing

Storage operations support batch processing for efficiency:

```python
await storage.insert_chunks(
    doc_id="doc-123",
    chunks=chunks,
    vectors=vectors,
    batch_size=64  # Process 64 chunks at a time
)
```

### Connection Pooling

Providers and storage backends manage connections efficiently:

```python
# Connections are reused across requests
provider = create_provider()
storage = await create_and_connect_storage()
```

## Troubleshooting

### Common Issues

1. **Milvus Connection Failed**
   - Ensure Milvus is running: `docker-compose up -d milvus`
   - Check host and port in configuration

2. **API Key Invalid**
   - Verify API key in environment variables
   - Check provider-specific key format

3. **No Chunks Retrieved**
   - Verify document was indexed successfully
   - Check retrieval settings (top_k, min_score)
   - Ensure query is relevant to document content

4. **Memory Issues**
   - Reduce chunk size or batch size
   - Use streaming instead of loading all results

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Or via environment variable:

```bash
LOG_LEVEL=DEBUG
LOG_REQUESTS=true
```

## Future Enhancements

1. **Additional Providers**: OpenAI, Anthropic, local models
2. **More Storage Backends**: Chroma, Qdrant, Pinecone
3. **Advanced RAG**: Hybrid search, re-ranking, query expansion
4. **Document Management**: Versioning, metadata search
5. **Caching Layer**: Response caching, embedding caching
6. **Analytics**: Usage tracking, cost estimation
7. **Multi-language**: Better localization support
8. **Batch Operations**: Process multiple documents efficiently

## References

- [DocPixie Architecture](./CODEBASE_OVERVIEW.md) - Reference architecture
- [Milvus Documentation](https://milvus.io/docs) - Vector database
- [OpenRouter API](https://openrouter.ai/docs) - LLM provider
- [LangChain](https://python.langchain.com) - Document processing

## License

See LICENSE file for details.