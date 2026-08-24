"""向后兼容桥接：gui.vector_search_page → gui.vector_search

旧代码 `from gui.vector_search_page import VectorSearchPage` 仍可用，
实际实现已拆分到 gui/vector_search/ 包。
"""
from .vector_search import (  # noqa: F401
    VectorSearchPage,
    VideoPreviewDialog,
    _ThumbWorker,
)

__all__ = ["VectorSearchPage", "VideoPreviewDialog", "_ThumbWorker"]
