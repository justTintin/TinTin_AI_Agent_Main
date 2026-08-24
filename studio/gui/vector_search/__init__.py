"""素材检索页面（page 39）— 拆分后的包入口。

向后兼容：保持 `from gui.vector_search_page import ...` 可用，
改为 `from gui.vector_search import ...` 即可。
"""
from .page import VectorSearchPage
from .widgets import VideoPreviewDialog
from .workers import _ThumbWorker

__all__ = ["VectorSearchPage", "VideoPreviewDialog", "_ThumbWorker"]
