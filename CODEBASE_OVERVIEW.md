# DocPixie Codebase Overview

## Tổng quan

DocPixie là một thư viện RAG (Retrieval-Augmented Generation) đa phương thức nhẹ, sử dụng AI thị giác thay vì embeddings/vector databases. Tài liệu được xử lý dưới dạng hình ảnh và phân tích bằng các mô hình ngôn ngữ thị giác cho cả việc hiểu và chọn trang.

## Phiên bản
- **Phiên bản hiện tại**: 0.1.0
- **Giai đoạn phát triển**: Phase 2 - Adaptive Vision RAG

## Cấu trúc thư mục

```
docpixie/
├── __init__.py                 # API chính và exports
├── docpixie.py                 # DocPixie class - API chính
├── exceptions.py               # Custom exception classes
├── ai/                         # Business logic layer
│   ├── __init__.py
│   ├── agent.py               # PixieRAGAgent - Main orchestrator
│   ├── task_planner.py       # Adaptive task planning
│   ├── page_selector.py      # Vision-based page selection
│   ├── summarizer.py         # Document/page summarization
│   ├── context_processor.py  # Conversation summarization
│   ├── query_reformulator.py # Reference resolution
│   ├── query_classifier.py   # Document need classification
│   ├── synthesizer.py        # Response synthesis
│   └── prompts.py            # Centralized AI prompts
├── providers/                  # Raw API operations layer
│   ├── __init__.py
│   ├── base.py               # BaseProvider interface
│   ├── openai.py             # OpenAI GPT-4V provider
│   ├── anthropic.py          # Anthropic Claude provider
│   ├── openrouter.py         # OpenRouter provider
│   └── factory.py            # Provider creation
├── processors/                # Document-to-image conversion
│   ├── __init__.py
│   ├── base.py               # BaseProcessor interface
│   ├── pdf.py                # PyMuPDF implementation
│   ├── image.py              # Image processor
│   └── factory.py            # Processor auto-detection
├── storage/                   # Pluggable storage backends
│   ├── __init__.py
│   ├── base.py               # BaseStorage interface
│   ├── local.py              # Filesystem storage
│   └── memory.py             # In-memory storage (for testing)
├── models/                    # Core data models
│   ├── __init__.py
│   ├── document.py           # Document, Page, QueryResult models
│   └── agent.py              # Agent task/plan data models
├── core/                      # Core configuration
│   ├── __init__.py
│   ├── config.py             # DocPixieConfig class
│   └── utils.py              # Utility functions
├── cli/                       # Command-line interface
│   ├── __init__.py
│   ├── app.py                # Main CLI application
│   ├── state_manager.py      # CLI state management
│   ├── config.py             # CLI configuration
│   ├── commands.py           # CLI commands
│   ├── docpixie_manager.py   # DocPixie manager for CLI
│   ├── conversation_storage.py # Conversation storage
│   ├── event_handlers.py     # Event handlers
│   ├── legacy.py             # Legacy support
│   ├── task_display.py       # Task display utilities
│   ├── styles.py             # CLI styles
│   ├── widgets/              # CLI widgets
│   │   ├── __init__.py
│   │   ├── model_selector.py
│   │   ├── document_manager.py
│   │   ├── conversation_manager.py
│   │   ├── command_palette.py
│   │   └── chat_area.py
│   └── cli.py                # CLI entry point
└── utils/                     # Utilities
    ├── __init__.py
    └── async_helpers.py      # Async helper functions
```

## Kiến trúc chính

### 1. Provider System (Raw API Operations)

**Đặc điểm chính:**
- Tách biệt hoàn toàn giữa các thao tác API thô và logic kinh doanh
- Mỗi provider chỉ implement hai phương thức:
  - `process_text_messages()`: Xử lý tin nhắn văn bản
  - `process_multimodal_messages()`: Xử lý tin nhắn văn bản + hình ảnh
- Tất cả providers nhận tin nhắn với type `image_path`, sau đó convert sang format riêng

**Các Providers hiện có:**
- **OpenAIProvider** (docpixie/providers/openai.py)
  - Sử dụng OpenAI API (AsyncOpenAI)
  - Model mặc định: gpt-4o
  - Convert `image_path` → `image_url` với data URL

- **AnthropicProvider** (docpixie/providers/anthropic.py)
  - Sử dụng Anthropic API (AsyncAnthropic)
  - Model mặc định: claude-3-opus-20240229
  - Convert `image_path` → base64 với type "image"
  - Xử lý system messages khác biệt (prepend vào user message đầu tiên)

- **OpenRouterProvider** (docpixie/providers/openrouter.py)
  - Sử dụng OpenAI client với `base_url="https://openrouter.ai/api/v1"`
  - Model mặc định: openai/gpt-4o
  - Format tương tự OpenAI

**BaseProvider Interface** (docpixie/providers/base.py):
```python
class BaseProvider(ABC):
    @abstractmethod
    async def process_text_messages(messages, max_tokens, temperature) -> str

    @abstractmethod
    async def process_multimodal_messages(messages, max_tokens, temperature) -> str
```

### 2. AI Operations (Business Logic Layer)

**Đặc điểm chính:**
- Chứa tất cả logic kinh doanh, xây dựng prompts, và điều phối workflow
- Tách biệt khỏi providers - chỉ gọi provider methods
- Có thể dễ dàng mở rộng hoặc thay đổi mà không ảnh hưởng providers

**Các thành phần chính:**

#### PixieRAGAgent (docpixie/ai/agent.py)
- **Vai trò**: Main orchestrator cho vision-based document analysis
- **Features**:
  - Vision-first page selection (phân tích actual page images)
  - Adaptive task planning (có thể modify plan dựa trên findings)
  - Single-mode operation (không có Flash/Pro distinction)
  - Conversation-aware query processing

- **Workflow**:
  1. Context Processing (conversation summarization nếu cần)
  2. Query Reformulation (nếu có conversation context)
  3. Query Classification (xác định xem có cần documents không)
  4. Task Planning + Document Selection (merged)
  5. Execute tasks adaptively
  6. Response Synthesis

#### TaskPlanner (docpixie/ai/task_planner.py)
- **Vai trò**: Adaptive task planning với dynamic updates
- **Features**:
  - Tạo initial plan (2-4 tasks)
  - Update plan adaptively sau mỗi task hoàn thành
  - Assign mỗi task đến chính xác 1 document
  - Có thể add/remove/modify tasks dựa trên findings

- **Methods**:
  - `create_initial_plan(query, documents)`: Tạo plan ban đầu
  - `update_plan(current_plan, latest_result, ...)`: Update plan adaptively

#### VisionPageSelector (docpixie/ai/page_selector.py)
- **Vai trò**: Chọn trang dựa trên visual analysis
- **Features**:
  - Phân tích actual page images bằng vision model
  - Limit số trang per task (configurable)
  - Return relevant pages cho mỗi task

#### ContextProcessor (docpixie/ai/context_processor.py)
- **Vai trò**: Xử lý và summarize conversation
- **Features**:
  - Summarize khi > 8 turns
  - Giữ 3 recent turns đầy đủ
  - Return both processed context và display messages

#### QueryReformulator (docpixie/ai/query_reformulator.py)
- **Vai trò**: Giải quyết references trong conversation
- **Features**:
  - Convert references like "it", "that" thành cụ thể
  - Output JSON format
  - Use processed context từ ContextProcessor

#### QueryClassifier (docpixie/ai/query_classifier.py)
- **Vai trò**: Xác định xem query có cần documents không
- **Features**:
  - Return reasoning và needs_documents flag
  - Direct answer nếu không cần documents

#### ResponseSynthesizer (docpixie/ai/synthesizer.py)
- **Vai trò**: Kết hợp findings từ tất cả tasks
- **Features**:
  - Combine task results thành comprehensive response
  - Cite sources bằng page numbers

#### Prompts (docpixie/ai/prompts.py)
- **Vai trò**: Centralized all AI prompts
- **Contains**:
  - System prompts
  - User prompts
  - Template strings cho AI interactions
  - Task processing prompts
  - Planning prompts
  - Synthesis prompts

#### PageSummarizer (docpixie/ai/summarizer.py)
- **Vai trò**: Summarize documents và pages
- **Features**:
  - Document summary: Tất cả page images trong single vision API call
  - Page summary: Optional individual page summaries
  - Preserve visual context và document structure

### 3. Models (Data Structures)

#### Document Models (docpixie/models/document.py)

**Page**:
```python
@dataclass
class Page:
    page_number: int
    image_path: str
    metadata: Dict[str, Any]
    document_name: Optional[str]
    document_id: Optional[str]
```

**Document**:
```python
@dataclass
class Document:
    id: str
    name: str
    pages: List[Page]
    summary: Optional[str]
    status: DocumentStatus
    metadata: Dict[str, Any]
    created_at: datetime
```

**QueryResult**:
```python
@dataclass
class QueryResult:
    query: str
    answer: str
    selected_pages: List[Page]
    mode: QueryMode
    confidence: float
    processing_time: float
    total_cost: float  # Total cost của tất cả API calls
    metadata: Dict[str, Any]
```

**Enums**:
- `QueryMode`: AUTO (adaptive processing)
- `DocumentStatus`: PENDING, PROCESSING, COMPLETED, FAILED

#### Agent Models (docpixie/models/agent.py)

**ConversationMessage**:
```python
@dataclass
class ConversationMessage:
    role: str  # "user" hoặc "assistant"
    content: str
    timestamp: datetime
    cost: float  # Cost cho message này
```

**AgentTask**:
```python
@dataclass
class AgentTask:
    id: str
    name: str
    description: str
    status: TaskStatus
    document: str  # Single document ID assigned
```

**TaskPlan**:
```python
@dataclass
class TaskPlan:
    initial_query: str
    tasks: List[AgentTask]
    current_iteration: int
```

**TaskResult**:
```python
@dataclass
class TaskResult:
    task: AgentTask
    selected_pages: List[Page]
    analysis: str
    pages_analyzed: int
```

**AgentQueryResult**:
```python
@dataclass
class AgentQueryResult:
    query: str
    answer: str
    selected_pages: List[Page]
    task_results: List[TaskResult]
    total_iterations: int
    processing_time_seconds: float
    total_cost: float  # Total cost của tất cả API calls
```

**Enums**:
- `TaskStatus`: PENDING, IN_PROGRESS, COMPLETED, CANCELLED

### 4. Processors (Document-to-Image Conversion)

**BaseProcessor Interface** (docpixie/processors/base.py):
```python
class BaseProcessor(ABC):
    @abstractmethod
    async def process(file_path, document_id) -> Document
```

**PDFProcessor** (docpixie/processors/pdf.py):
- Sử dụng PyMuPDF để convert PDF → images
- Render scale: 2.0 (configurable)
- Max image size: 1200x1200
- JPEG quality: 90 (configurable)
- Output: List of Page objects với image paths

**ImageProcessor** (docpixie/processors/image.py):
- Xử lý trực tiếp image files
- Copy images vào storage

**ProcessorFactory** (docpixie/processors/factory.py):
- Auto-detection dựa trên file extension
- Returns appropriate processor

### 5. Storage (Pluggable Backends)

**BaseStorage Interface** (docpixie/storage/base.py):
```python
class BaseStorage(ABC):
    @abstractmethod
    async def save_document(document) -> None

    @abstractmethod
    async def get_document(document_id) -> Optional[Document]

    @abstractmethod
    async def get_all_documents() -> List[Document]

    @abstractmethod
    async def delete_document(document_id) -> bool

    @abstractmethod
    async def list_documents(limit) -> List[Dict[str, Any]]

    @abstractmethod
    async def search_documents(query, limit) -> List[Dict[str, Any]]
```

**LocalStorage** (docpixie/storage/local.py):
- Lưu documents và pages vào filesystem
- Path: `./docpixie_data` (configurable)
- Structure:
  ```
  docpixie_data/
  ├── documents.json
  ├── documents/
  │   ├── {doc_id}/
  │   │   ├── page_1.jpg
  │   │   ├── page_2.jpg
  │   │   └── ...
  │   └── ...
  ```

**InMemoryStorage** (docpixie/storage/memory.py):
- In-memory storage cho testing
- Không persist data
- Useful cho unit tests

### 6. Configuration (docpixie/core/config.py)

**DocPixieConfig**:
```python
@dataclass
class DocPixieConfig:
    # Document Processing
    pdf_render_scale: float = 2.0
    pdf_max_image_size: Tuple[int, int] = (1200, 1200)
    jpeg_quality: int = 90
    thumbnail_size: Tuple[int, int] = (256, 256)
    vision_detail: str = "high"

    # Storage
    storage_type: str = "local"  # local, memory
    local_storage_path: str = "./docpixie_data"

    # AI Provider Settings (Provider-agnostic)
    provider: str = "openai"  # openai, anthropic, openrouter
    model: str = "gpt-4o"
    vision_model: str = "gpt-4o"

    # API Keys
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None

    # Agent Settings
    max_agent_iterations: int = 5
    max_pages_per_task: int = 6
    max_tasks_per_plan: int = 4

    # Conversation Processing
    max_conversation_turns: int = 8
    turns_to_summarize: int = 5
    turns_to_keep_full: int = 3

    # Logging
    log_level: str = "INFO"
    log_requests: bool = False
```

**Features**:
- Provider-agnostic configuration với generic model fields
- Automatic provider defaults trong `_set_provider_defaults()`
- API keys loaded từ environment variables:
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`
  - `OPENROUTER_API_KEY`
- Test API key support: Use `"test-key"` để bypass validation
- Environment overrides:
  - `DOCPIXIE_PROVIDER`
  - `DOCPIXIE_STORAGE_PATH`
  - `DOCPIXIE_JPEG_QUALITY`
  - `DOCPIXIE_LOG_LEVEL`

### 7. Main API (docpixie/docpixie.py)

**DocPixie Class**:
```python
class DocPixie:
    def __init__(self, config: Optional[DocPixieConfig] = None,
                 storage: Optional[BaseStorage] = None,
                 api_key: Optional[str] = None)

    # Document Management
    async def add_document(file_path, document_id, document_name) -> Document
    async def get_document(document_id) -> Optional[Document]
    async def list_documents(limit) -> List[Dict[str, Any]]
    async def delete_document(document_id) -> bool
    async def search_documents(query, limit) -> List[Dict[str, Any]]

    # Query Processing
    async def query(question, mode, document_ids, max_pages, stream,
                    conversation_history, task_update_callback) -> QueryResult

    async def query_with_conversation(question, conversation_history, mode) -> QueryResult

    # Convenience Methods
    def supports_file(file_path) -> bool
    def get_supported_extensions() -> Dict[str, str]
    def get_stats() -> Dict[str, Any]

    # Synchronous API (for easier adoption)
    def add_document_sync(...)
    def get_document_sync(...)
    def list_documents_sync(...)
    def delete_document_sync(...)
    def query_sync(...)
    def query_with_conversation_sync(...)
```

**Factory Functions**:
```python
def create_docpixie(provider: str = "openai",
                   api_key: Optional[str] = None,
                   storage_path: Optional[str] = None) -> DocPixie

def create_memory_docpixie(provider: str = "openai",
                           api_key: Optional[str] = None) -> DocPixie
```

### 8. CLI Module (docpixie/cli/)

**Main Components**:
- **app.py**: Main CLI application
- **state_manager.py**: CLI state management
- **docpixie_manager.py**: DocPixie manager cho CLI
- **conversation_storage.py**: Conversation persistence
- **widgets/**: TUI widgets (model_selector, document_manager, conversation_manager, command_palette, chat_area)

**Features**:
- Interactive command-line interface
- Document management (add, list, delete, search)
- Query processing với real-time task display
- Conversation management
- Model selector
- Command palette

## Workflow chính

### 1. Document Processing Workflow

```
1. User calls add_document(file_path)
   ↓
2. ProcessorFactory.get_processor(file_path) → PDFProcessor
   ↓
3. processor.process(file_path, document_id)
   - PyMuPDF converts PDF → images
   - Creates Document object với Page objects
   ↓
4. summarizer.summarize_document(document)
   - Sends ALL page images trong single vision API call
   - Generates document summary
   ↓
5. storage.save_document(document)
   - Saves document metadata
   - Saves page images to filesystem
   ↓
6. Returns Document object với summary
```

### 2. Query Processing Workflow (Adaptive RAG)

```
1. User calls query(question, conversation_history)
   ↓
2. PixieRAGAgent.process_query()
   ↓
3. ContextProcessor.process_conversation_context()
   - If > 8 turns: Summarize conversation
   - Keep 3 recent turns full
   ↓
4. QueryReformulator.reformulate_with_context()
   - Resolve references ("it", "that")
   - Output reformulated query
   ↓
5. QueryClassifier.classify_query()
   - Determine if documents needed
   - If not: Return direct answer
   ↓
6. TaskPlanner.create_initial_plan()
   - Create 2-4 tasks
   - Assign each task to single document
   ↓
7. Execute tasks adaptively (loop)
   a. Get next pending task
   b. VisionPageSelector.select_pages_for_task()
      - Analyze page images
      - Select relevant pages (max per task)
   c. Analyze selected pages
      - Build multimodal message
      - Call vision model
   d. Store task result
   e. TaskPlanner.update_plan()
      - Agent evaluates progress
      - Add/remove/modify tasks if needed
   f. Repeat until no pending tasks hoặc max iterations
   ↓
8. ResponseSynthesizer.synthesize_response()
   - Combine all task findings
   - Cite sources with page numbers
   ↓
9. Return QueryResult với answer và metadata
```

## Các nguyên tắc kiến trúc quan trọng

### 1. Provider-Agnostic Configuration
- Sử dụng generic fields (`model`, `vision_model`) thay vì provider-specific fields
- Automatic provider defaults trong `DocPixieConfig._set_provider_defaults()`
- Dễ dàng switch giữa providers mà không thay đổi config

### 2. Separation of Concerns
- **Providers**: Raw API operations only
- **AI Operations**: Business logic, prompt construction, workflow orchestration
- **Processors**: Document-to-image conversion
- **Storage**: Data persistence
- **Models**: Data structures

### 3. Image-Based Processing
- Tất cả documents converted thành images via PyMuPDF
- Preserve visual information và document structure
- Document summaries: Tất cả page images trong single vision API call

### 4. Adaptive RAG Agent
- Single adaptive mode với dynamic task planning
- Mỗi task assigned đến chính xác 1 document
- Agent có thể modify plan dựa trên findings
- Re-evaluate sau mỗi task completion

### 5. Conversation Awareness
- Context processing khi > 8 turns
- Query reformulation với reference resolution
- Conversation context passed đến task analysis

### 6. Error Handling Philosophy
- Simple và direct error handling
- Raise appropriate custom exceptions từ `exceptions.py`
- No fallback mechanisms (ensures clear failure modes)

### 7. Prompt Management
- All AI prompts centralized trong `ai/prompts.py`
- Never embed prompts directly trong component files

## Environment Variables

```bash
# Required cho respective providers
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
OPENROUTER_API_KEY=your_openrouter_key

# Optional configuration overrides
DOCPIXIE_PROVIDER=openai|anthropic|openrouter
DOCPIXIE_STORAGE_PATH=./docpixie_data
DOCPIXIE_JPEG_QUALITY=90
DOCPIXIE_LOG_LEVEL=INFO
```

## Development Guidelines

### Code Modification Priority
**CRITICAL**: Luôn ưu tiên modify existing code hơn là tạo new files/methods trừ khi absolutely necessary. Điều này duy trì codebase coherence và tránh unnecessary duplication.

### Error Handling
- Raise appropriate custom exceptions từ `docpixie/exceptions.py`
- No fallback mechanisms
- Ensure clear failure modes và easier debugging

### Prompt Management
- All AI prompts phải centralized trong `docpixie/ai/prompts.py`
- Include system prompts, user prompts, và template strings
- Never embed prompts trực tiếp trong component files

### Agent Task Architecture
- Mỗi agent task phải assigned đến chính xác 1 document
- Không assign tasks đến multiple documents
- Simplifies page selection và analysis
- Maintains clear scope boundaries

### Configuration Testing
- Never use test mode flags
- Use test API keys (`"test-key"`) để bypass validation
- Test keys automatically bypass validation logic

## Testing Support

### In-Memory Storage
- `InMemoryStorage` cho unit testing
- No persistence
- Faster test execution

### Test API Keys
- Use `"test-key"` để bypass API validation
- Works với tất cả providers

### Synchronous API
- Synchronous methods available cho easier testing
- `*_sync()` methods wrap async methods

## Supported File Formats

- **PDF**: .pdf (via PyMuPDF)
- **Images**: .jpg, .jpeg, .png, .gif, .bmp, .tiff, .webp

## Key Features Summary

1. **Vision-based RAG** không cần embeddings/vector databases
2. **Adaptive RAG agent** với dynamic task planning
3. **Multiple AI provider support** (OpenAI, Anthropic, OpenRouter)
4. **Pluggable storage backends** (local filesystem, in-memory)
5. **PDF to image conversion** via PyMuPDF
6. **Conversation-aware query processing**
7. **Provider-agnostic configuration**
8. **Centralized prompt management**
9. **Comprehensive CLI** với TUI
10. **Cost tracking** cho tất cả API calls

## Future Enhancements

1. **S3 Storage Backend**: Cloud storage support
2. **Streaming Responses**: Real-time answer generation
3. **Cost Estimation**: Pre-query cost estimation
4. **Batch Processing**: Process multiple documents efficiently
5. **Custom Prompts**: Allow custom prompt overrides
6. **Cache Layer**: Cache API responses
7. **Document Export**: Export findings as PDF/Markdown
8. **Multi-language Support**: Better localization

## Conclusion

DocPixie là một thư viện RAG đa phương thức nhẹ với kiến trúc modular và clean separation of concerns. Key strengths:

- **Simplicity**: Không cần embeddings/vector databases
- **Flexibility**: Multiple providers, storage backends
- **Adaptability**: Agent có thể modify plan dynamically
- **Extensibility**: Modular architecture cho easy extension
- **Maintainability**: Clear separation giữa raw API và business logic

Architecture đảm bảo dễ hiểu, dễ maintain, và dễ mở rộng trong tương lai.
