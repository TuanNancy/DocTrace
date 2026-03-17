# RAG PDF Chatbot - New Architecture

A modern, modular Retrieval-Augmented Generation (RAG) system for PDF document querying, built with FastAPI and following the DocPixie reference architecture (adapted for embeddings/vector databases).

## 🎯 Overview

This project provides a clean, extensible architecture for building PDF document chatbots using RAG. It features:

- **Provider-Agnostic Configuration**: Support for multiple LLM providers (OpenRouter, OpenAI, Anthropic)
- **Pluggable Storage**: Support for multiple vector databases (Milvus, in-memory)
- **Intelligent RAG Agent**: Context-aware query processing with conversation support
- **Streaming Responses**: Real-time token streaming for better UX
- **Centralized Prompts**: All AI prompts in one location for easy maintenance
- **Comprehensive Models**: Rich data models with Pydantic validation
- **Factory Pattern**: Easy creation of providers and storage instances

## 🏗️ Architecture

The architecture follows clear separation of concerns:

```
┌─────────────────────────────────────────────────────────┐
│                    API Layer (Routers)                   │
│  ┌──────────────┐              ┌──────────────┐         │
│  │   Upload     │              │    Chat      │         │
│  └──────────────┘              └──────────────┘         │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│              AI Operations (Business Logic)              │
│  ┌──────────────────────────────────────────────────┐  │
│  │              RAG Agent (Orchestrator)             │  │
│  │  • Query Processing  • Context Management         │  │
│  │  • Vector Search     • Response Synthesis         │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────┐              ┌──────────────┐         │
│  │   Prompts    │              │   Models     │         │
│  └──────────────┘              └──────────────┘         │
└─────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│   Providers      │ │    Storage       │ │   Embeddings     │
│  ┌────────────┐  │ │  ┌────────────┐  │ │  ┌────────────┐  │
│  │ OpenRouter │  │ │  │  Milvus    │  │ │  │   OpenAI   │  │
│  │  OpenAI    │  │ │  │ In-Memory  │  │ │  │ Sentence   │  │
│  │ Anthropic  │  │ │  │            │  │ │  │ Transformers│ │
│  └────────────┘  │ │  └────────────┘  │ │  └────────────┘  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
            │               │               │
            └───────────────┼───────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│                 Core Configuration                        │
│  • Environment Variables  • Validation  • Defaults       │
└─────────────────────────────────────────────────────────┘
```

## 📦 Key Components

### 1. Configuration System (`core/config.py`)
- Provider-agnostic configuration with `RAGConfig` class
- Environment variable loading with sensible defaults
- Configuration validation
- Support for test API keys

### 2. Provider System (`providers/`)
- **BaseProvider**: Abstract interface for LLM providers
- **OpenRouterProvider**: OpenRouter implementation
- **ProviderFactory**: Factory for creating provider instances
- Support for streaming and non-streaming modes

### 3. Storage System (`storage/`)
- **BaseStorage**: Abstract interface for vector databases
- **MilvusStorage**: Milvus vector database implementation
- **StorageFactory**: Factory for creating storage instances
- Async operations throughout

### 4. Data Models (`models/`)
- **Document Models**: Document, chunk, and query models
- **Agent Models**: Conversation and agent task models
- Pydantic validation for API responses
- Factory functions for easy creation

### 5. AI Operations (`ai/`)
- **RAGAgent**: Main orchestrator for query processing
- **Prompts**: Centralized AI prompts (Vietnamese & English)
- Conversation awareness and context management
- Query classification and routing

### 6. API Layer (`routers/`)
- **Upload**: PDF upload and indexing endpoint
- **Chat**: Streaming chat/query endpoint
- Thin API layer with business logic in AI operations

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Docker & Docker Compose
- API Key (OpenRouter, OpenAI, or Anthropic)

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd RAG-PDF-chatbot
```

2. **Set up environment variables**
```bash
# Create .env file
cat > .env << EOF
# LLM Provider
RAG_PROVIDER=openrouter
RAG_MODEL=openai/gpt-4o-mini
OPENROUTER_API_KEY=sk-or-...

# Vector Database
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=pdf_chunks

# Document Processing
CHUNK_SIZE=1000
CHUNK_OVERLAP=150
EOF
```

3. **Install dependencies**
```bash
cd backend
pip install -r requirements.txt
```

4. **Start Milvus**
```bash
docker-compose up -d milvus
```

5. **Start the server**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Usage

**Upload a PDF:**
```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@document.pdf"
```

**Query the document:**
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the main topic?",
    "doc_id": "uuid-1234",
    "language": "vi"
  }'
```

**Python example:**
```python
import asyncio
from app.ai.rag_agent import create_rag_agent_with_defaults

async def query_document():
    agent = await create_rag_agent_with_defaults()
    
    try:
        result = await agent.process_query(
            query="What are the key benefits?",
            doc_id="uuid-1234",
            language="vi"
        )
        
        print(f"Answer: {result.answer}")
        print(f"Sources: {result.get_sources()}")
        print(f"Processing time: {result.processing_time}s")
        
    finally:
        await agent.shutdown()

asyncio.run(query_document())
```

## 📚 Documentation

- **[Architecture Overview](./ARCHITECTURE.md)** - Detailed architecture documentation
- **[Implementation Summary](./IMPLEMENTATION_SUMMARY.md)** - What was implemented
- **[Migration Guide](./MIGRATION_GUIDE.md)** - Step-by-step migration instructions
- **[Quick Start Guide](./QUICKSTART.md)** - Get started in minutes
- **[Codebase Overview](./CODEBASE_OVERVIEW.md)** - Reference architecture

## 🔧 Configuration

### Environment Variables

```bash
# LLM Provider
RAG_PROVIDER=openrouter              # openrouter, openai, anthropic
RAG_MODEL=openai/gpt-4o-mini         # Model to use
RAG_TEMPERATURE=0.7                  # Sampling temperature
RAG_MAX_TOKENS=4096                  # Max tokens to generate

# API Keys
OPENROUTER_API_KEY=sk-or-...         # OpenRouter API key
OPENAI_API_KEY=sk-...                # OpenAI API key
ANTHROPIC_API_KEY=sk-ant-...         # Anthropic API key

# Vector Database (Milvus)
MILVUS_HOST=localhost                # Milvus host
MILVUS_PORT=19530                    # Milvus port
MILVUS_COLLECTION=pdf_chunks         # Collection name
MILVUS_VECTOR_DIM=1536               # Vector dimension

# Document Processing
CHUNK_SIZE=1000                      # Chunk size
CHUNK_OVERLAP=150                    # Chunk overlap
MIN_CHARS_PER_PAGE=50                # Min chars per page

# RAG Settings
RETRIEVAL_TOP_K=8                    # Top-k results
CONTEXT_MAX_CHARS=6000               # Max context chars
MIN_RELEVANCE_SCORE=0.5              # Min relevance score

# Upload Settings
UPLOAD_MAX_SIZE_MB=50                # Max upload size
```

## 🎨 Features

### Document Processing
- ✅ PDF upload and indexing
- ✅ Text extraction and chunking
- ✅ Embedding generation
- ✅ Vector database insertion
- ✅ Document metadata tracking
- ✅ Batch processing support

### Query Processing
- ✅ Vector similarity search
- ✅ Context building from retrieved chunks
- ✅ RAG response generation
- ✅ Streaming support
- ✅ Conversation awareness
- ✅ Query classification
- ✅ Multi-turn conversation support

### Provider Support
- ✅ OpenRouter (fully implemented)
- 🔧 OpenAI (interface ready)
- 🔧 Anthropic (interface ready)
- 🔧 Easy to add new providers

### Storage Support
- ✅ Milvus (fully implemented)
- 🔧 In-memory (interface ready)
- 🔧 Easy to add new backends

### Monitoring
- ✅ Health checks
- ✅ Statistics tracking
- ✅ Logging throughout
- ✅ Performance metrics
- ✅ Cost tracking

## 🔌 Extensibility

### Adding a New LLM Provider

```python
# 1. Create provider class
from app.providers.base import BaseProvider

class CustomProvider(BaseProvider):
    async def process_text_messages(self, messages, max_tokens, temperature):
        # Implement custom API call
        pass

    async def stream_text_messages(self, messages, max_tokens, temperature):
        # Implement streaming
        pass

# 2. Register with factory
from app.providers.factory import ProviderFactory
ProviderFactory.register_provider("custom", CustomProvider)

# 3. Use in configuration
RAG_PROVIDER=custom
```

### Adding a New Storage Backend

```python
# 1. Create storage class
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

# 2. Register with factory
from app.storage.factory import StorageFactory
StorageFactory.register_backend("custom", CustomStorage)

# 3. Use in configuration
STORAGE_TYPE=custom
```

## 🧪 Testing

### Unit Tests
```python
import pytest
from app.ai.rag_agent import create_rag_agent_with_defaults

@pytest.mark.asyncio
async def test_rag_agent_query():
    agent = await create_rag_agent_with_defaults()
    
    try:
        result = await agent.process_query("test query", "test-doc")
        assert result.answer is not None
        assert result.processing_time > 0
    finally:
        await agent.shutdown()
```

### Run Tests
```bash
# Run all tests
pytest backend/app/tests/

# Run with coverage
pytest --cov=backend/app backend/app/tests/

# Run specific test
pytest backend/app/tests/test_rag_agent.py
```

## 📊 API Endpoints

### POST /api/upload
Upload and index a PDF document.

**Request:**
```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@document.pdf"
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

### POST /api/chat
Query a document with streaming response.

**Request:**
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the main topic?",
    "doc_id": "uuid-1234",
    "language": "vi"
  }'
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

## 🛠️ Development

### Project Structure
```
backend/app/
├── core/              # Core configuration
├── providers/         # LLM providers
├── storage/           # Vector database storage
├── models/            # Data models
├── ai/                # AI operations
├── routers/           # API endpoints
├── documents/         # Document processing
└── services/          # Business services
```

### Code Style
- Follow PEP 8 guidelines
- Use type hints
- Write docstrings
- Add unit tests

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 🐛 Troubleshooting

### Milvus Connection Failed
```bash
# Check if Milvus is running
docker-compose ps milvus

# Start Milvus
docker-compose up -d milvus

# Check logs
docker-compose logs milvus
```

### API Key Invalid
```bash
# Set API key in .env file
OPENROUTER_API_KEY=sk-or-...

# Or set via environment variable
export OPENROUTER_API_KEY=sk-or-...
```

### No Chunks Retrieved
```python
# Check if document was indexed
storage = await create_and_connect_storage()
documents = await storage.list_documents()
print(f"Total documents: {len(documents)}")

# Adjust retrieval settings
config = get_config()
config.retrieval_top_k = 20
config.min_relevance_score = 0.3
```

## 🚧 Roadmap

### Phase 1 (Current)
- ✅ Core architecture implementation
- ✅ OpenRouter provider
- ✅ Milvus storage
- ✅ RAG agent
- ✅ Streaming support

### Phase 2 (Next)
- 🔧 OpenAI provider implementation
- 🔧 Anthropic provider implementation
- 🔧 In-memory storage for testing
- 🔧 Advanced RAG features (re-ranking, query expansion)
- 🔧 Response caching

### Phase 3 (Future)
- 🔲 Additional storage backends (Chroma, Qdrant, Pinecone)
- 🔲 Document versioning
- 🔲 Metadata search
- 🔲 Usage analytics
- 🔲 Cost estimation
- 🔲 Multi-language support

## 📝 License

See LICENSE file for details.

## 🤝 Support

- **Documentation**: Check the `docs/` directory
- **Issues**: Report bugs on GitHub
- **Discussions**: Join community discussions

## 🙏 Acknowledgments

- **DocPixie**: Reference architecture inspiration
- **LangChain**: Document processing utilities
- **Milvus**: Vector database
- **OpenRouter**: LLM provider

---

**Built with ❤️ using modern Python practices and clean architecture principles.**