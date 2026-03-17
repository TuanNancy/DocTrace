"""
Centralized AI prompts module.

All AI prompts for the RAG PDF Chatbot are centralized here.
This includes system prompts, user prompts, and template strings
for various AI operations.
"""

# ==================== System Prompts ====================

SYSTEM_PROMPT_VI = """Bạn là trợ lý trả lời câu hỏi dựa trên nội dung tài liệu PDF được cung cấp.

Hãy trả lời ngắn gọn, chính xác và chỉ dựa vào ngữ cảnh tài liệu bên dưới. Khi trích dẫn thông tin, luôn ghi rõ số trang nguồn (ví dụ: (trang 3), (trang 5-6)).

Nếu ngữ cảnh không chứa thông tin để trả lời, hãy nói rõ rằng tài liệu không có thông tin về câu hỏi đó và không bịa đặt.

Nguyên tắc:
- Chỉ sử dụng thông tin từ ngữ cảnh được cung cấp
- Trích dẫn rõ nguồn trang cho mọi thông tin
- Nếu không tìm thấy thông tin, hãy nói thẳng là không có
- Tránh suy diễn hoặc thêm thông tin không có trong tài liệu
- Giữ câu trả lời ngắn gọn và đi thẳng vào vấn đề
"""

SYSTEM_PROMPT_EN = """You are a helpful assistant that answers questions based on the provided PDF document content.

Please provide concise, accurate answers based only on the document context below. When citing information, always include the source page number (e.g., (page 3), (pages 5-6)).

If the context does not contain information to answer the question, clearly state that the document does not have information about that question and do not make up information.

Principles:
- Use only information from the provided context
- Cite source pages for all information
- If information is not found, state clearly that it's not available
- Avoid speculation or adding information not in the document
- Keep answers concise and to the point
"""

# ==================== Context Processing Prompts ====================

CONTEXT_SUMMARIZER_PROMPT_VI = """Tóm tắt cuộc hội thoại sau đây một cách ngắn gọn, tập trung vào các điểm chính và thông tin quan trọng.

Cuộc hội thoại:
{conversation}

Hãy cung cấp tóm tắt bao gồm:
1. Chủ đề chính của cuộc hội thoại
2. Các câu hỏi quan trọng đã được hỏi
3. Các thông tin quan trọng đã được thảo luận
4. Bối cảnh hiện tại cần được giữ lại

Tóm tắt nên đủ ngắn gọn để có thể được sử dụng làm ngữ cảnh cho các câu hỏi tiếp theo."""

CONTEXT_SUMMARIZER_PROMPT_EN = """Summarize the following conversation concisely, focusing on key points and important information.

Conversation:
{conversation}

Please provide a summary including:
1. The main topic of the conversation
2. Important questions that were asked
3. Key information that was discussed
4. Current context that needs to be retained

The summary should be concise enough to be used as context for follow-up questions."""

# ==================== Query Reformulation Prompts ====================

QUERY_REFORMULATOR_PROMPT_VI = """Dựa vào ngữ cảnh hội thoại trước đó, hãy viết lại câu hỏi hiện tại để giải quyết các tham chiếu (như "nó", "đó", "cái này") và làm rõ ý định.

Ngữ cảnh hội thoại:
{conversation}

Câu hỏi hiện tại: "{current_query}"

Hãy viết lại câu hỏi để:
1. Giải quyết các tham chiếu bằng các từ cụ thể
2. Làm rõ ý định của người dùng
3. Giữ nguyên ý nghĩa gốc
4. Đảm bảo câu hỏi có thể hiểu được độc lập

Trả về chỉ câu hỏi đã viết lại, không có giải thích."""

QUERY_REFORMULATOR_PROMPT_EN = """Based on the previous conversation context, rewrite the current question to resolve references (like "it", "that", "this") and clarify the intent.

Conversation context:
{conversation}

Current question: "{current_query}"

Rewrite the question to:
1. Resolve references with specific terms
2. Clarify the user's intent
3. Maintain the original meaning
4. Ensure the question can be understood independently

Return only the rewritten question, without explanation."""

# ==================== Query Classification Prompts ====================

QUERY_CLASSIFIER_PROMPT_VI = """Phân tích câu hỏi sau đây và xác định xem nó có cần truy xuất thông tin từ tài liệu hay không.

Câu hỏi: "{query}"

Hãy trả lời theo định dạng JSON:
{{
    "needs_documents": true/false,
    "reasoning": "lý do cho quyết định",
    "direct_answer": "câu trả lời trực tiếp nếu không cần tài liệu, hoặc null"
}}

Nếu câu hỏi là về thông tin chung, chào hỏi, hoặc không liên quan đến nội dung tài liệu cụ thể, hãy đặt needs_documents là false và cung cấp câu trả lời trực tiếp."""

QUERY_CLASSIFIER_PROMPT_EN = """Analyze the following question and determine if it needs to retrieve information from documents.

Question: "{query}"

Please respond in JSON format:
{{
    "needs_documents": true/false,
    "reasoning": "reason for the decision",
    "direct_answer": "direct answer if documents are not needed, or null"
}}

If the question is about general information, greetings, or not related to specific document content, set needs_documents to false and provide a direct answer."""

# ==================== Response Synthesis Prompts ====================

RESPONSE_SYNTHESIZER_PROMPT_VI = """Dựa trên các kết quả tìm kiếm từ tài liệu, hãy tổng hợp một câu trả lời toàn diện cho câu hỏi.

Câu hỏi: "{query}"

Kết quả tìm kiếm:
{search_results}

Hãy:
1. Tổng hợp thông tin từ tất cả các kết quả
2. Trích dẫn rõ nguồn trang cho từng thông tin
3. Sắp xếp câu trả lời một cách logic
4. Giữ câu trả lời ngắn gọn nhưng đầy đủ
5. Nếu có thông tin mâu thuẫn, hãy ghi rõ

Trả về câu trả lời đã tổng hợp."""

RESPONSE_SYNTHESIZER_PROMPT_EN = """Based on the search results from the document, synthesize a comprehensive answer to the question.

Question: "{query}"

Search results:
{search_results}

Please:
1. Synthesize information from all results
2. Cite source pages clearly for each piece of information
3. Organize the answer logically
4. Keep the answer concise but complete
5. If there is conflicting information, note it clearly

Return the synthesized answer."""

# ==================== Task Planning Prompts ====================

TASK_PLANNER_PROMPT_VI = """Tạo kế hoạch thực hiện các nhiệm vụ để trả lời câu hỏi sau đây một cách hiệu quả.

Câu hỏi: "{query}"

Tài liệu có sẵn:
{documents}

Hãy tạo kế hoạch với 2-4 nhiệm vụ, mỗi nhiệm vụ được gán cho một tài liệu cụ thể.

Trả về theo định dạng JSON:
{{
    "tasks": [
        {{
            "name": "tên nhiệm vụ",
            "description": "mô tả chi tiết nhiệm vụ",
            "document_id": "id tài liệu",
            "task_type": "retrieval|analysis|synthesis"
        }}
    ]
}}

Mỗi nhiệm vụ nên:
- Tập trung vào một khía cạnh cụ thể của câu hỏi
- Được gán cho đúng một tài liệu
- Có mô tả rõ ràng về những gì cần làm"""

TASK_PLANNER_PROMPT_EN = """Create a task execution plan to answer the following question effectively.

Question: "{query}"

Available documents:
{documents}

Please create a plan with 2-4 tasks, each task assigned to a specific document.

Return in JSON format:
{{
    "tasks": [
        {{
            "name": "task name",
            "description": "detailed task description",
            "document_id": "document id",
            "task_type": "retrieval|analysis|synthesis"
        }}
    ]
}}

Each task should:
- Focus on a specific aspect of the question
- Be assigned to exactly one document
- Have a clear description of what needs to be done"""

# ==================== Document Summarization Prompts ====================

DOCUMENT_SUMMARIZER_PROMPT_VI = """Tóm tắt tài liệu sau đây một cách ngắn gọn nhưng đầy đủ các thông tin quan trọng.

Nội dung tài liệu:
{content}

Hãy cung cấp tóm tắt bao gồm:
1. Chủ đề chính của tài liệu
2. Các điểm quan trọng
3. Cấu trúc hoặc tổ chức nội dung
4. Bất kỳ thông tin đặc biệt hoặc đáng chú ý

Tóm tắt nên:
- Ngắn gọn (khoảng 200-300 từ)
- Bắt được tinh thần của tài liệu
- Hữu ích cho việc tìm kiếm và truy xuất"""

DOCUMENT_SUMMARIZER_PROMPT_EN = """Summarize the following document concisely but with all important information.

Document content:
{content}

Please provide a summary including:
1. The main topic of the document
2. Key points
3. Structure or organization of content
4. Any special or notable information

The summary should:
- Be concise (around 200-300 words)
- Capture the essence of the document
- Be useful for search and retrieval"""

# ==================== Chunk Analysis Prompts ====================

CHUNK_ANALYZER_PROMPT_VI = """Phân tích đoạn văn bản sau đây để xác định mức độ liên quan của nó với câu hỏi.

Câu hỏi: "{query}"

Đoạn văn bản:
{chunk_text}

Hãy trả lời theo định dạng JSON:
{{
    "relevant": true/false,
    "relevance_score": 0.0-1.0,
    "reasoning": "lý do cho đánh giá",
    "key_information": "thông tin chính từ đoạn nếu có liên quan"
}}

Đánh giá dựa trên:
- Mức độ đoạn văn trả lời câu hỏi
- Chất lượng và tính chính xác của thông tin
- Tính liên quan trực tiếp với câu hỏi"""

CHUNK_ANALYZER_PROMPT_EN = """Analyze the following text chunk to determine its relevance to the question.

Question: "{query}"

Text chunk:
{chunk_text}

Please respond in JSON format:
{{
    "relevant": true/false,
    "relevance_score": 0.0-1.0,
    "reasoning": "reason for the evaluation",
    "key_information": "key information from the chunk if relevant"
}}

Evaluate based on:
- How well the chunk answers the question
- Quality and accuracy of information
- Direct relevance to the question"""

# ==================== Prompt Templates ====================

class PromptTemplates:
    """Collection of prompt templates for various AI operations."""

    # System prompts
    SYSTEM_PROMPT_VI = SYSTEM_PROMPT_VI
    SYSTEM_PROMPT_EN = SYSTEM_PROMPT_EN

    # Context processing
    CONTEXT_SUMMARIZER_VI = CONTEXT_SUMMARIZER_PROMPT_VI
    CONTEXT_SUMMARIZER_EN = CONTEXT_SUMMARIZER_PROMPT_EN

    # Query reformulation
    QUERY_REFORMULATOR_VI = QUERY_REFORMULATOR_PROMPT_VI
    QUERY_REFORMULATOR_EN = QUERY_REFORMULATOR_PROMPT_EN

    # Query classification
    QUERY_CLASSIFIER_VI = QUERY_CLASSIFIER_PROMPT_VI
    QUERY_CLASSIFIER_EN = QUERY_CLASSIFIER_PROMPT_EN

    # Response synthesis
    RESPONSE_SYNTHESIZER_VI = RESPONSE_SYNTHESIZER_PROMPT_VI
    RESPONSE_SYNTHESIZER_EN = RESPONSE_SYNTHESIZER_PROMPT_EN

    # Task planning
    TASK_PLANNER_VI = TASK_PLANNER_PROMPT_VI
    TASK_PLANNER_EN = TASK_PLANNER_PROMPT_EN

    # Document summarization
    DOCUMENT_SUMMARIZER_VI = DOCUMENT_SUMMARIZER_PROMPT_VI
    DOCUMENT_SUMMARIZER_EN = DOCUMENT_SUMMARIZER_PROMPT_EN

    # Chunk analysis
    CHUNK_ANALYZER_VI = CHUNK_ANALYZER_PROMPT_VI
    CHUNK_ANALYZER_EN = CHUNK_ANALYZER_PROMPT_EN

    @classmethod
    def get_system_prompt(cls, language: str = "vi") -> str:
        """Get system prompt for specified language."""
        return cls.SYSTEM_PROMPT_VI if language == "vi" else cls.SYSTEM_PROMPT_EN

    @classmethod
    def get_context_summarizer(cls, language: str = "vi") -> str:
        """Get context summarizer prompt for specified language."""
        return cls.CONTEXT_SUMMARIZER_VI if language == "vi" else cls.CONTEXT_SUMMARIZER_EN

    @classmethod
    def get_query_reformulator(cls, language: str = "vi") -> str:
        """Get query reformulator prompt for specified language."""
        return cls.QUERY_REFORMULATOR_VI if language == "vi" else cls.QUERY_REFORMULATOR_EN

    @classmethod
    def get_query_classifier(cls, language: str = "vi") -> str:
        """Get query classifier prompt for specified language."""
        return cls.QUERY_CLASSIFIER_VI if language == "vi" else cls.QUERY_CLASSIFIER_EN

    @classmethod
    def get_response_synthesizer(cls, language: str = "vi") -> str:
        """Get response synthesizer prompt for specified language."""
        return cls.RESPONSE_SYNTHESIZER_VI if language == "vi" else cls.RESPONSE_SYNTHESIZER_EN

    @classmethod
    def get_task_planner(cls, language: str = "vi") -> str:
        """Get task planner prompt for specified language."""
        return cls.TASK_PLANNER_VI if language == "vi" else cls.TASK_PLANNER_EN

    @classmethod
    def get_document_summarizer(cls, language: str = "vi") -> str:
        """Get document summarizer prompt for specified language."""
        return cls.DOCUMENT_SUMMARIZER_VI if language == "vi" else cls.DOCUMENT_SUMMARIZER_EN

    @classmethod
    def get_chunk_analyzer(cls, language: str = "vi") -> str:
        """Get chunk analyzer prompt for specified language."""
        return cls.CHUNK_ANALYZER_VI if language == "vi" else cls.CHUNK_ANALYZER_EN


# ==================== Utility Functions ====================

def format_context_summarizer(conversation: str, language: str = "vi") -> str:
    """Format context summarizer prompt with conversation."""
    template = PromptTemplates.get_context_summarizer(language)
    return template.format(conversation=conversation)


def format_query_reformulator(conversation: str, current_query: str, language: str = "vi") -> str:
    """Format query reformulator prompt with context and query."""
    template = PromptTemplates.get_query_reformulator(language)
    return template.format(conversation=conversation, current_query=current_query)


def format_query_classifier(query: str, language: str = "vi") -> str:
    """Format query classifier prompt with query."""
    template = PromptTemplates.get_query_classifier(language)
    return template.format(query=query)


def format_response_synthesizer(query: str, search_results: str, language: str = "vi") -> str:
    """Format response synthesizer prompt with query and results."""
    template = PromptTemplates.get_response_synthesizer(language)
    return template.format(query=query, search_results=search_results)


def format_task_planner(query: str, documents: str, language: str = "vi") -> str:
    """Format task planner prompt with query and documents."""
    template = PromptTemplates.get_task_planner(language)
    return template.format(query=query, documents=documents)


def format_document_summarizer(content: str, language: str = "vi") -> str:
    """Format document summarizer prompt with content."""
    template = PromptTemplates.get_document_summarizer(language)
    return template.format(content=content)


def format_chunk_analyzer(query: str, chunk_text: str, language: str = "vi") -> str:
    """Format chunk analyzer prompt with query and chunk."""
    template = PromptTemplates.get_chunk_analyzer(language)
    return template.format(query=query, chunk_text=chunk_text)


# ==================== Default Prompts ====================

# Default to Vietnamese prompts
DEFAULT_SYSTEM_PROMPT = SYSTEM_PROMPT_VI
DEFAULT_CONTEXT_SUMMARIZER = CONTEXT_SUMMARIZER_PROMPT_VI
DEFAULT_QUERY_REFORMULATOR = QUERY_REFORMULATOR_PROMPT_VI
DEFAULT_QUERY_CLASSIFIER = QUERY_CLASSIFIER_PROMPT_VI
DEFAULT_RESPONSE_SYNTHESIZER = RESPONSE_SYNTHESIZER_PROMPT_VI
DEFAULT_TASK_PLANNER = TASK_PLANNER_PROMPT_VI
DEFAULT_DOCUMENT_SUMMARIZER = DOCUMENT_SUMMARIZER_PROMPT_VI
DEFAULT_CHUNK_ANALYZER = CHUNK_ANALYZER_PROMPT_VI
