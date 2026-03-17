# Quick Start Guide

Get started with the RAG PDF Chatbot in minutes!

## Prerequisites

- **Python 3.9+**
- **Docker & Docker Compose** (for Milvus vector database)
- **API Keys**: OpenRouter, OpenAI, or Anthropic

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd RAG-PDF-chatbot
```

### 2. Set Up Environment Variables

Create a `.env` file in the project root:

```bash
# LLM Provider (choose one)
RAG_PROVIDER=openrouter
RAG_MODEL=openai/gpt-4o-mini

# API Keys
OPENROUTER_API_KEY=sk-or-...
# or
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...

# Vector Database (Milvus)
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=pdf_chunks
MILVUS_VECTOR_DIM=1536

# Document Processing
CHUNK_SIZE=1000
CHUNK_OVERLAP=150

# RAG Settings
RETRIEVAL_TOP_K=8
CONTEXT_MAX_CHARS=6000
```

### 3. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Start Milvus (Vector Database)

```bash
docker-compose up -d milvus
```

Verify Milvus is running:

```bash
docker-compose ps milvus
```

### 5. Start the Backend Server

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## Quick Test

### 1. Upload a PDF

```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@test.pdf"
```

**Response:**
```json
{
  "doc_id": "uuid-1234",
  "name": "test.pdf",
  "chunks_count": 42,
  "status": "completed",
  "processing_time": 2.345,
  "created_at": "2024-01-15T10:30:00",
  "warnings": []
}
```

### 2. Query the Document

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the main topic?",
    "doc_id": "uuid-1234",
    "language": "vi"
  }'
```

**Response (Streaming):**
```
event: token
data: "The"

event: token
data: " main"

event: token
data: " topic"

event: sources
data: [{"page": 1, "source": "test.pdf", "score": 0.95}]

event: done
data: "[DONE]"
```

## Usage Examples

### Python Example: Basic Query

```python
import asyncio
from app.ai.rag_agent import create_rag_agent_with_defaults

async def query_document():
    # Create agent
    agent = await create_rag_agent_with_defaults()
    
    try:
        # Process query
        result = await agent.process_query(
            query="What are the key benefits?",
            doc_id="uuid-1234",
            language="vi"
        )
        
        # Print results
        print(f"Answer: {result.answer}")
        print(f"Sources: {result.get_sources()}")
        print(f"Pages: {result.get_pages()}")
        print(f"Processing time: {result.processing_time}s")
        
    finally:
        await agent.shutdown()

# Run
asyncio.run(query_document())
```

### Python Example: Streaming Response

```python
import asyncio
from app.ai.rag_agent import create_rag_agent_with_defaults

async def stream_query():
    agent = await create_rag_agent_with_defaults()
    
    try:
        print("Answer: ", end="", flush=True)
        
        async for token in agent.process_query_stream(
            query="Explain the main concept",
            doc_id="uuid-1234",
            language="vi"
        ):
            print(token, end="", flush=True)
        
        print()  # New line
        
    finally:
        await agent.shutdown()

asyncio.run(stream_query())
```

### Python Example: Multi-turn Conversation

```python
import asyncio
from app.ai.rag_agent import create_rag_agent_with_defaults

async def conversation():
    agent = await create_rag_agent_with_defaults()
    
    try:
        # First query
        result1 = await agent.process_query(
            query="What is the main topic?",
            doc_id="uuid-1234"
        )
        print(f"Q1: {result1.answer}")
        
        # Follow-up query (uses conversation context)
        result2 = await agent.process_query(
            query="Can you explain more about that?",
            doc_id="uuid-1234"
        )
        print(f"Q2: {result2.answer}")
        
        # Check conversation
        context = await agent.get_conversation_context()
        print(f"Conversation length: {context.total_message_count}")
        
    finally:
        await agent.shutdown()

asyncio.run(conversation())
```

### Python Example: Direct Storage Operations

```python
import asyncio
from app.storage.factory import create_and_connect_storage
from app.providers.embeddings import get_embedder

async def search_documents():
    storage = await create_and_connect_storage()
    embedder = get_embedder()
    
    try:
        # Search chunks
        query_vector = embedder.embed_documents(["search query"])[0]
        chunks = await storage.search_chunks(
            query_vector=query_vector,
            doc_id="uuid-1234",
            top_k=5
        )
        
        for chunk in chunks:
            print(f"Page {chunk.page}: {chunk.text[:100]}...")
            print(f"Score: {chunk.score}")
        
        # Get document metadata
        metadata = await storage.get_document_metadata("uuid-1234")
        print(f"Document: {metadata.name}")
        print(f"Chunks: {metadata.chunks_count}")
        
        # List all documents
        documents = await storage.list_documents(limit=10)
        for doc in documents:
            print(f"{doc.doc_id}: {doc.name}")
        
    finally:
        await storage.disconnect()

asyncio.run(search_documents())
```

## Common Tasks

### Upload and Index a PDF

```python
import asyncio
from app.routers.upload import run_indexing_pipeline_from_upload

async def upload_pdf():
    with open("document.pdf", "rb") as f:
        file_content = f.read()
    
    result = await run_indexing_pipeline_from_upload(
        file_content=file_content,
        filename="document.pdf"
    )
    
    print(f"Document ID: {result.doc_id}")
    print(f"Chunks created: {result.chunks_count}")
    print(f"Status: {result.status}")
    
    if result.warnings:
        print(f"Warnings: {result.warnings}")

asyncio.run(upload_pdf())
```

### Query with Custom Provider

```python
import asyncio
from app.providers.openrouter import OpenRouterProvider
from app.storage.factory import create_and_connect_storage
from app.ai.rag_agent import RAGAgent

async def custom_provider_query():
    # Create custom provider
    provider = OpenRouterProvider(
        api_key="sk-or-...",
        model="anthropic/claude-3-opus",
        base_url="https://openrouter.ai/api/v1"
    )
    
    # Create storage
    storage = await create_and_connect_storage()
    
    # Create agent
    agent = RAGAgent(provider=provider, storage=storage)
    await agent.initialize()
    
    try:
        result = await agent.process_query(
            query="What is the main topic?",
            doc_id="uuid-1234"
        )
        print(result.answer)
        
    finally:
        await agent.shutdown()

asyncio.run(custom_provider_query())
```

### Get Agent Statistics

```python
import asyncio
from app.ai.rag_agent import create_rag_agent_with_defaults

async def get_stats():
    agent = await create_rag_agent_with_defaults()
    
    try:
        # Process some queries
        await agent.process_query("Query 1", "doc-123")
        await agent.process_query("Query 2", "doc-123")
        
        # Get statistics
        stats = agent.get_stats()
        print(f"Total queries: {stats['total_queries']}")
        print(f"Total cost: ${stats['total_cost']:.6f}")
        print(f"Conversation length: {stats['conversation_length']}")
        
        # Health check
        health = await agent.health_check()
        print(f"Health status: {health['status']}")
        
    finally:
        await agent.shutdown()

asyncio.run(get_stats())
```

## Configuration Options

### LLM Provider Settings

```bash
# Provider selection
RAG_PROVIDER=openrouter  # openrouter, openai, anthropic

# Model selection
RAG_MODEL=openai/gpt-4o-mini

# Generation parameters
RAG_TEMPERATURE=0.7
RAG_MAX_TOKENS=4096
```

### Vector Database Settings

```bash
# Milvus connection
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=pdf_chunks
MILVUS_VECTOR_DIM=1536

# Index settings
MILVUS_INDEX_TYPE=IVF_FLAT
MILVUS_METRIC_TYPE=COSINE
MILVUS_NLIST=128
MILVUS_NPROBE=32
```

### Document Processing Settings

```bash
# Chunking
CHUNK_SIZE=1000
CHUNK_OVERLAP=150
MIN_CHARS_PER_PAGE=50

# Upload limits
UPLOAD_MAX_SIZE_MB=50
```

### RAG Settings

```bash
# Retrieval
RETRIEVAL_TOP_K=8
CONTEXT_MAX_CHARS=6000
MIN_RELEVANCE_SCORE=0.5

# Conversation
MAX_CONVERSATION_TURNS=8
TURNS_TO_SUMMARIZE=5
TURNS_TO_KEEP_FULL=3
```

## API Documentation

Once the server is running, visit:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

Interactive API documentation with examples and testing capabilities.

## Troubleshooting

### Milvus Connection Failed

**Problem:** `RuntimeError: Milvus connection failed`

**Solution:**
```bash
# Check if Milvus is running
docker-compose ps milvus

# Start Milvus
docker-compose up -d milvus

# Check logs
docker-compose logs milvus
```

### API Key Invalid

**Problem:** `ValueError: API key required for provider: openrouter`

**Solution:**
```bash
# Set API key in .env file
OPENROUTER_API_KEY=sk-or-...

# Or set via environment variable
export OPENROUTER_API_KEY=sk-or-...
```

### No Chunks Retrieved

**Problem:** Query returns no results

**Solution:**
```python
# Check if document was indexed
storage = await create_and_connect_storage()
documents = await storage.list_documents()
print(f"Total documents: {len(documents)}")

# Check document chunks
metadata = await storage.get_document_metadata("doc-123")
print(f"Document chunks: {metadata.chunks_count}")

# Adjust retrieval settings
config = get_config()
config.retrieval_top_k = 20  # Increase top_k
config.min_relevance_score = 0.3  # Lower threshold
```

### Memory Issues

**Problem:** Out of memory errors

**Solution:**
```bash
# Reduce chunk size
CHUNK_SIZE=500

# Reduce batch size in code
await storage.insert_chunks(doc_id, chunks, vectors, batch_size=32)

# Use streaming instead of loading all results
async for token in agent.process_query_stream(query, doc_id):
    # Process token by token
```

## Next Steps

1. **Explore the Architecture**: Read [ARCHITECTURE.md](./ARCHITECTURE.md)
2. **Learn More**: Check [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md)
3. **Migrate Existing Code**: Follow [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md)
4. **Build Features**: Extend with custom providers and storage backends
5. **Deploy**: Set up production environment with proper monitoring

## Support

- **Documentation**: Check the `docs/` directory
- **Examples**: Look at `examples/` directory
- **Issues**: Report bugs on GitHub
- **Discussions**: Join community discussions

## License

See LICENSE file for details.

---

**Happy Building! 🚀**