"""
Models package for DocTrace.
"""

from app.models.document import (
    DocumentStatus,
    IndexingResult,
    create_indexing_result,
)

__all__ = [
    "DocumentStatus",
    "IndexingResult",
    "create_indexing_result",
]
