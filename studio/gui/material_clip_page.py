# -*- coding: utf-8 -*-
"""
素材向量库页面

左侧：入库面板
  - NAS 根目录 + 资源目录选择
  - 快速入库（仅元数据）/ AI 分析（视觉LLM + Whisper + CLIP）
  - 入库日志 + 进度

右侧：数据库浏览面板
  - 按路径前缀筛选，显示数据库中的素材记录
  - 显示 品牌 / 型号 / 类别 / 置信度 / AI状态
  - 多选行后可触发"重新AI分析"
"""
import os
import json
import sys
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.platform_utils import open_path
from utils.logger_utils import log
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QSplitter, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QProgressBar, QAbstractItemView,
    QCheckBox, QComboBox, QTreeWidget, QTreeWidgetItem, QDialog, QStackedWidget,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.material_clip_indexer import to_local_path
from utils.nas_client import NASClient


# ── Workers ───────────────────────────────────────────────────────────────────

class _IndexMetaWorker(BaseWorker):
    """Phase 1: 仅入库元信息（hash/路径/大小），无 AI，速度极快。"""
    log_line = Signal(str)
    progress = Signal(int, int)        # current, total
    finished = Signal(int, int, int)   # ok, skip, fail

    def __init__(self, directory: str, nas_root: str, force: bool):
        super().__init__()
        self.directory = directory
        self.nas_root  = nas_root
        self.force     = force

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        with MaterialClipIndexer(nas_root=self.nas_root,
                                  progress_cb=self.log_line.emit) as idx:
            ok, skip, fail = idx.index_directory_meta(
                self.directory,
                force=self.force,
                file_progress_cb=self.progress.emit
            )
        self.finished.emit(ok, skip, fail)


class _AnalyzeWorker(BaseWorker):
    """Phase 2: 视觉 LLM + Whisper + CLIP，识别品牌/型号。"""
    log_line = Signal(str)
    finished = Signal(int, int)   # ok, fail

    def __init__(self, directory: str, nas_root: str):
        super().__init__()
        self.directory = directory
        self.nas_root  = nas_root

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        with MaterialClipIndexer(nas_root=self.nas_root,
                                  progress_cb=self.log_line.emit) as idx:
            ok, fail = idx.analyze_directory(self.directory)
        self.finished.emit(ok, fail)


class _StatsLightWorker(BaseWorker):
    """仅从数据库读取统计（不扫磁盘），快速。"""
    finished = Signal(dict)

    def __init__(self, index_directories=None):
        super().__init__()
        self.index_directories = index_directories or []

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        with MaterialClipIndexer() as idx:
            stats = idx.get_stats()
        self.finished.emit(stats)


class _LoadBrandsWorker(BaseWorker):
    """从 PostgreSQL 加载去重品牌列表并归一化。"""
    finished = Signal(list)

    def do_work(self):
        from utils.brand_normalizer import canonical_name
        import json, psycopg2
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "material_index_config.json")
        with open(cfg_path) as f:
            cfg = json.load(f)
        conn = psycopg2.connect(
            host=cfg["db_host"], port=cfg["db_port"], dbname=cfg["db_name"],
            user=cfg["db_user"], password=cfg["db_password"]
        )
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT brand FROM materials WHERE brand IS NOT NULL AND brand != '' AND brand != '—' ORDER BY brand")
        raw_brands = [r[0] for r in cur.fetchall()]
        conn.close()
        seen = set()
        result = []
        for b in raw_brands:
            canon = canonical_name(b)
            if canon and canon not in seen:
                seen.add(canon)
                result.append(canon)
        result.sort(key=lambda x: x.lower())
        self.finished.emit(result)


class _LoadCategoriesWorker(BaseWorker):
    """从 PostgreSQL 加载去重类别列表。"""
    finished = Signal(list)

    def do_work(self):
        import json, psycopg2
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "material_index_config.json")
        with open(cfg_path) as f:
            cfg = json.load(f)
        conn = psycopg2.connect(
            host=cfg["db_host"], port=cfg["db_port"], dbname=cfg["db_name"],
            user=cfg["db_user"], password=cfg["db_password"]
        )
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT product FROM materials WHERE product IS NOT NULL AND product != '' AND product != '—' ORDER BY product")
        cats = [r[0] for r in cur.fetchall()]
        conn.close()
        # category normalization map
        _cat_map = {
            "键盘+鼠标": "键鼠套装", "手机": "手机", "平板电脑": "平板",
            "笔记本电脑": "笔记本", "智能手表": "手表", "软件界面": "软件",
            "游戏界面": "游戏", "服饰": "服饰", "其他": "其他", "未知": "未知",
        }
        seen = set()
        result = []
        for c in cats:
            canon = _cat_map.get(c, c)
            if canon not in seen:
                seen.add(canon)
                result.append(canon)
        result.sort(key=lambda x: x.lower())
        self.finished.emit(result)


class _StatsWorker(BaseWorker):
    """对齐并查询统计数据。"""
    finished = Signal(dict)
    log_line = Signal(str)

    def __init__(self, index_directories=None):
        super().__init__()
        self.index_directories = index_directories or []

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer, VIDEO_EXTS, IMAGE_EXTS
        import os
        
        missing_files = []
        
        with MaterialClipIndexer(progress_cb=self.log_line.emit) as idx:
            # 1. 查询数据库常规统计数据
            stats = idx.get_stats()
            
            # 2. 计算磁盘媒体文件与库内差额
            try:
                idx._db._connect()
                with idx._db._conn.cursor() as cur:
                    cur.execute("SELECT path FROM materials")
                    db_paths = {row[0].replace('\\', '/').strip('/') for row in cur.fetchall() if row[0]}
            except Exception as e:
                self.log_line.emit(f"  ✗ 读取数据库路径失败: {e}")
                db_paths = set()
                
            supported_exts = VIDEO_EXTS | IMAGE_EXTS
            disk_count = 0
            for d in self.index_directories:
                local_path = d.get("local_path")
                nas_folder = d.get("nas_folder", "").strip('/')
                if local_path and os.path.isdir(local_path):
                    self.log_line.emit(f"  ➜ 正在比对磁盘文件差额: {local_path} ...")
                    for root, _, files in os.walk(local_path):
                        for f in files:
                            ext = os.path.splitext(f)[1].lower()
                            if ext in supported_exts:
                                disk_count += 1
                                fp = os.path.normpath(os.path.join(root, f))
                                rel_sub = os.path.relpath(fp, local_path).replace('\\', '/').strip('/')
                                db_style_rel = f"{nas_folder}/{rel_sub}".strip('/')
                                if db_style_rel not in db_paths:
                                    try:
                                        st = os.stat(fp)
                                        missing_files.append({
                                            "local_path": fp,
                                            "relative_path": db_style_rel,
                                            "size": st.st_size,
                                            "mtime": st.st_mtime
                                        })
                                    except Exception:
                                        missing_files.append({
                                            "local_path": fp,
                                            "relative_path": db_style_rel,
                                            "size": 0,
                                            "mtime": 0.0
                                        })
                                    
            stats["disk_count"] = disk_count
            stats["missing_files"] = missing_files
            stats["diff_count"] = len(missing_files)
            
            self.log_line.emit(f"  ✓ 统计刷新完成。磁盘媒体数: {disk_count}, 库内总数: {stats.get('total', 0)}, 未入库差额: {len(missing_files)}")
            self.finished.emit(stats)


class _AlignAndIngestWorker(BaseWorker):
    """扫描目录，将磁盘新文件对齐入库。"""
    log_line = Signal(str)
    finished = Signal(dict)

    def __init__(self, index_directories=None):
        super().__init__()
        self.index_directories = index_directories or []

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        import os

        ok_tot = skip_tot = fail_tot = 0
        with MaterialClipIndexer(progress_cb=self.log_line.emit) as idx:
            for d in self.index_directories:
                local_path = d.get("local_path")
                if local_path and os.path.isdir(local_path):
                    self.log_line.emit(f"  ➜ 对齐入库目录: {local_path} ...")
                    try:
                        ok, skip, fail = idx.index_directory_meta(local_path, force=False)
                        ok_tot += ok; skip_tot += skip; fail_tot += fail
                        self.log_line.emit(f"    ✓ 新入库 {ok}，跳过 {skip}，失败 {fail}")
                    except Exception as e:
                        self.log_line.emit(f"  ✗ 对齐失败 {local_path}: {e}")
            self.log_line.emit(f"  ✓ 对齐入库完成。新增 {ok_tot}，跳过 {skip_tot}，失败 {fail_tot}")
        self.finished.emit({"ok": ok_tot, "skip": skip_tot, "fail": fail_tot})


class _BatchIndexMetaWorker(BaseWorker):
    """批量入库指定的文件列表元信息。"""
    log_line = Signal(str)
    progress = Signal(int, int)        # current, total
    finished = Signal(int, int, int)   # ok, skip, fail

    def __init__(self, file_paths: list[str], force: bool = False):
        super().__init__()
        self.file_paths = file_paths
        self.force      = force

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        ok = skip = fail = 0
        total = len(self.file_paths)
        
        with MaterialClipIndexer(progress_cb=self.log_line.emit) as idx:
            for i, fp in enumerate(self.file_paths):
                self.progress.emit(i + 1, total)
                try:
                    if idx.index_file_meta(fp, force=self.force):
                        ok += 1
                        self.log_line.emit(f"  ✓ 成功入库: {fp}")
                    else:
                        skip += 1
                except Exception as e:
                    fail += 1
                    self.log_line.emit(f"  ✗ 入库异常 {fp}: {e}")
                    
        self.finished.emit(ok, skip, fail)


class _ImportMaterialTasksWorker(BaseWorker):
    """导入素材浏览器写入的 material_import_tasks.json 任务清单。"""
    log_line = Signal(str)
    progress = Signal(int, int)       # current, total
    finished = Signal(dict)           # {ok, skip, fail, missing, total, pending_left, file}

    def __init__(self, tasks_file: str):
        super().__init__()
        self.tasks_file = tasks_file

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer

        if not os.path.isfile(self.tasks_file):
            self.finished.emit({
                "ok": 0, "skip": 0, "fail": 0, "missing": 0,
                "total": 0, "pending_left": 0, "file": self.tasks_file,
            })
            return

        try:
            with open(self.tasks_file, "r", encoding="utf-8") as f:
                tasks = json.load(f)
            if not isinstance(tasks, list):
                tasks = []
        except Exception:
            tasks = []

        pending_idx = [
            i for i, t in enumerate(tasks)
            if isinstance(t, dict) and str(t.get("status", "pending")).lower() == "pending"
        ]
        total = len(pending_idx)
        ok = skip = fail = missing = 0

        if total == 0:
            self.finished.emit({
                "ok": 0, "skip": 0, "fail": 0, "missing": 0,
                "total": 0, "pending_left": 0, "file": self.tasks_file,
            })
            return

        self.log_line.emit(f"开始处理素材导入任务：{total} 条")
        with MaterialClipIndexer(progress_cb=self.log_line.emit) as idx:
            for n, ti in enumerate(pending_idx, start=1):
                self.progress.emit(n, total)
                task = tasks[ti]
                fp = str(task.get("path", "")).strip()
                task["updatedAt"] = datetime.now().isoformat(timespec="seconds")
                if not fp or (not os.path.isfile(fp)):
                    missing += 1
                    task["status"] = "missing"
                    task["error"] = "file_not_found"
                    self.log_line.emit(f"  ⚠ 文件不存在，已标记 missing: {fp}")
                    continue
                try:
                    inserted = idx.index_file_meta(fp, force=False)
                    if inserted:
                        ok += 1
                        task["status"] = "ingested"
                        task["error"] = ""
                        self.log_line.emit(f"  ✓ 入库成功: {fp}")
                    else:
                        skip += 1
                        task["status"] = "skipped"
                        task["error"] = "already_exists"
                except Exception as e:
                    fail += 1
                    task["status"] = "failed"
                    task["error"] = str(e)
                    self.log_line.emit(f"  ✗ 入库失败: {fp} | {e}")

        pending_left = sum(1 for t in tasks if isinstance(t, dict) and str(t.get("status", "")).lower() == "pending")
        try:
            with open(self.tasks_file, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_line.emit(f"  ✗ 回写任务清单失败: {e}")

        self.finished.emit({
            "ok": ok,
            "skip": skip,
            "fail": fail,
            "missing": missing,
            "total": total,
            "pending_left": pending_left,
            "file": self.tasks_file,
        })


class _QueryMaterialsWorker(BaseWorker):
    """从数据库查询素材列表（按路径前缀 + hash 前缀 + AI状态 + 类型筛选，新增品牌、描述、置信度筛选）。"""
    finished = Signal(list)

    def __init__(self, path_prefix: str = "", ai_status_filter: str = "",
                 limit: int = 10000, hash_prefix: str = "", media_type: str = "",
                 brand: str = "", scene_desc: str = "", conf_filter: str = "",
                 product: str = ""):
        super().__init__()
        self.path_prefix      = path_prefix
        self.ai_status_filter = ai_status_filter or None
        self.limit            = limit
        self.hash_prefix      = hash_prefix
        self.media_type       = media_type or None
        self.brand            = brand
        self.scene_desc       = scene_desc
        self.conf_filter      = conf_filter
        self.product          = product

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        with MaterialClipIndexer() as idx:
            rows = idx.list_materials(
                path_prefix=self.path_prefix,
                ai_status=self.ai_status_filter,
                limit=self.limit,
                hash_prefix=self.hash_prefix,
                media_type=self.media_type,
                brand=self.brand,
                scene_desc=self.scene_desc,
                conf_filter=self.conf_filter,
                product=self.product,
            )
        self.finished.emit(rows)


class _ReAnalyzeSelectedWorker(BaseWorker):
    """对选定的素材行（{id, path}）重新执行 AI 分析，支持进度汇报与终止任务。"""
    log_line = Signal(str)
    progress = Signal(int, int)   # done, total
    finished = Signal(int, int)   # ok, fail

    def __init__(self, materials: list, nas_root: str):
        super().__init__()
        self.materials = materials
        self.nas_root  = nas_root
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        ok = fail = 0
        total = len(self.materials)
        if total == 0:
            self.finished.emit(0, 0)
            return

        env_workers = os.environ.get("TINTIN_AI_ANALYZE_WORKERS", "2").strip()
        try:
            max_workers = int(env_workers)
        except Exception:
            max_workers = 2
        max_workers = max(1, min(max_workers, 4, total))

        def _analyze_one(mat: dict):
            if self._is_cancelled:
                return False, None
            try:
                with MaterialClipIndexer(nas_root=self.nas_root, progress_cb=self.log_line.emit) as idx:
                    success = idx.analyze_material(mat["id"], mat["path"])
                return bool(success), None
            except Exception as e:
                import traceback
                return False, traceback.format_exc()

        self.log_line.emit(f"  🚀 AI 分析并发数: {max_workers}")
        done = 0
        future_map = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for mat in self.materials:
                future_map[pool.submit(_analyze_one, mat)] = mat

            for fut in as_completed(future_map):
                mat = future_map[fut]
                if self._is_cancelled:
                    self.log_line.emit("  ⚠️ 用户已终止 AI 分析任务")
                    for f2 in future_map:
                        f2.cancel()
                    break
                success, err = fut.result()
                done += 1
                fname = os.path.basename(mat['path'])
                if success:
                    ok += 1
                    self.log_line.emit(f"  ✓ [{done}/{total}] {fname}: AI 分析完成")
                else:
                    fail += 1
                    err_msg = f": {err}" if err else " (分析失败)"
                    self.log_line.emit(f"  ✗ [{done}/{total}] {fname}{err_msg}")
                self.progress.emit(done, total)

        if not self._is_cancelled:
            self.progress.emit(total, total)
        self.finished.emit(ok, fail)


class _OcrRenameWorker(BaseWorker):
    """对目录下已入库的图片执行 OCR 智能重命名。"""
    log_line = Signal(str)
    finished = Signal(int, int)   # ok, fail

    def __init__(self, directory: str, nas_root: str):
        super().__init__()
        self.directory = directory
        self.nas_root  = nas_root

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        with MaterialClipIndexer(nas_root=self.nas_root,
                                  progress_cb=self.log_line.emit) as idx:
            ok, fail = idx.ocr_rename_directory(self.directory)
        self.finished.emit(ok, fail)


# ── 主页面 ────────────────────────────────────────────────────────────────────

_STATUS_COLOR = {
    "pending":  "#f59e0b",   # 黄
    "analyzed": "#22c55e",   # 绿
    "failed":   "#ef4444",   # 红
}

_CONF_COLOR = {
    "high":   "#22c55e",
    "medium": "#f59e0b",
    "low":    "#ef4444",
}


class MaterialClipPage(BasePage):
    def setup(self):
        self._is_init = True
        self._last_selected_dir = ""
        self._nas_client = None

        # 初始化非模态浮动日志面板
        self.log_dialog = QDialog(self.parent_widget)
        self.log_dialog.setWindowTitle("📜 操作日志")
        self.log_dialog.resize(900, 650)
        self.log_dialog.setWindowFlags(Qt.Window)
        self.log_dialog.setAttribute(Qt.WA_DeleteOnClose, False)
        def _close_event(e):
            self.log_dialog.hide()
            self._on_log_dialog_closed(0)
            e.ignore()
        self.log_dialog.closeEvent = _close_event
        dlg_lay = QVBoxLayout(self.log_dialog)
        dlg_lay.setContentsMargins(8, 8, 8, 8)
        self.log_box_ingest = QTextEdit()
        self.log_box_ingest.setReadOnly(True)
        self.log_box_ingest.setPlaceholderText("入库操作日志…")
        self.log_box_analyze = QTextEdit()
        self.log_box_analyze.setReadOnly(True)
        self.log_box_analyze.setPlaceholderText("分析操作日志…")
        dlg_lay.addWidget(self.log_box_ingest)
        dlg_lay.addWidget(self.log_box_analyze)
        self.log_box_analyze.hide()
        self.log_dialog.finished.connect(self._on_log_dialog_closed)
        self._active_log = "ingest"

        self._finish_setup()

    @property
    def log_box(self):
        return self.log_box_ingest if self._active_log == "ingest" else self.log_box_analyze

    def _log(self, msg):
        self.log_box.append(msg)

    def _log_clear(self):
        self.log_box.clear()

    def _finish_setup(self):
        """rest of setup() — can't be in setup() due to method ordering"""

        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        # 标题
        hdr = QHBoxLayout()
        title = QLabel("🗄️ 素材向量库")
        title.setObjectName("heading")
        hdr.addWidget(title)
        hdr.addStretch()
        root.addLayout(hdr)

        # ── Step Bar ──
        self.step_bar = QFrame()
        self.step_bar.setObjectName("step_bar")
        self.step_bar.setStyleSheet("""
            QFrame#step_bar {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 6px;
                padding: 4px 12px;
            }
        """)
        step_layout = QHBoxLayout(self.step_bar)
        step_layout.setContentsMargins(4, 6, 4, 6)
        step_layout.setSpacing(0)
        self.step_labels = []
        for i, text in enumerate(["📥 素材入库", "🤖 智能分析"]):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.setObjectName("step_label")
            lbl.mousePressEvent = lambda e, idx=i: self._switch_tab(idx)
            if i == 0:
                lbl.setProperty("active", True)
            step_layout.addWidget(lbl, 1)
            self.step_labels.append(lbl)
        root.addWidget(self.step_bar, 0)

        # ── Stacked Content ──
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet("QStackedWidget { background: transparent; }")
        self.ingest_panel = self._build_ingest_panel()
        self.analyze_panel = self._build_analyze_panel()
        self.stacked_widget.addWidget(self.ingest_panel)
        self.stacked_widget.addWidget(self.analyze_panel)
        root.addWidget(self.stacked_widget, 1)

        self._is_init = False

        # 初始加载
        self._reload_dir_config()
        self._refresh_stats_light()
        self._load_brand_list()
        self._load_category_list()

    def _switch_tab(self, index):
        self.stacked_widget.setCurrentIndex(index)
        self._active_log = "ingest" if index == 0 else "analyze"
        self.log_box_ingest.setVisible(index == 0)
        self.log_box_analyze.setVisible(index == 1)
        for i, lbl in enumerate(self.step_labels):
            if i == index:
                lbl.setProperty("active", True)
            else:
                lbl.setProperty("active", False)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    # ── 共享：目录树组件 ──

    def _build_dir_tree_widget(self, parent_layout, tree_attr="dir_tree"):
        """构建 NAS 根目录 + 资源目录树。"""
        nas_row = QHBoxLayout()
        nas_row.addWidget(QLabel("NAS 根目录："))
        nas_lbl = QLabel("（未配置）")
        nas_lbl.setObjectName("nas_root_label")
        nas_row.addWidget(nas_lbl, 1)
        setattr(self, f"lbl_nas_root_{tree_attr}", nas_lbl)
        btn_reload_cfg = QPushButton("↺")
        btn_reload_cfg.setFixedWidth(36)
        btn_reload_cfg.setStyleSheet("padding: 2px; min-width: 28px;")
        btn_reload_cfg.setToolTip("重新读取「环境配置」中的目录设置")
        btn_reload_cfg.setObjectName("secondary_button")
        btn_reload_cfg.clicked.connect(self._reload_dir_config)
        nas_row.addWidget(btn_reload_cfg)
        parent_layout.addLayout(nas_row)

        parent_layout.addWidget(QLabel("资源目录："))
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.itemExpanded.connect(self._on_tree_item_expanded)
        tree.itemSelectionChanged.connect(lambda t=tree: self._on_tree_selection_changed(t))
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(lambda pos, t=tree: self._show_tree_context_menu(pos, t))
        setattr(self, tree_attr, tree)
        self.dir_tree = tree
        parent_layout.addWidget(tree)

    # ── Tab1：文件入库 ──

    def _build_ingest_panel(self):
        panel = QFrame()
        panel.setObjectName("card")
        main_lay = QVBoxLayout(panel)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        # 左：目录树
        left = QFrame()
        left.setObjectName("card")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(14, 14, 14, 14)
        left_lay.setSpacing(8)
        left_lay.addWidget(QLabel("📥 入库"))
        self._build_dir_tree_widget(left_lay, "ingest_tree")

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("separator"); left_lay.addWidget(sep)
        self.btn_toggle_log = QPushButton("▶ 显示操作日志")
        self.btn_toggle_log.setObjectName("secondary_button")
        self.btn_toggle_log.clicked.connect(self._toggle_log_box)
        left_lay.addWidget(self.btn_toggle_log)
        self.idx_stat_ingest = QLabel("")
        self.idx_stat_ingest.setObjectName("muted_text")
        left_lay.addWidget(self.idx_stat_ingest)
        splitter.addWidget(left)

        # 右：数据库表格 + 入库操作
        right = self._build_diff_panel()
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 25)
        splitter.setStretchFactor(1, 75)
        QTimer.singleShot(0, lambda: splitter.setSizes([300, 900]))
        main_lay.addWidget(splitter, 1)
        return panel

    # ── Tab2：智能分析 ──

    def _build_analyze_panel(self):
        panel = QFrame()
        panel.setObjectName("card")
        main_lay = QVBoxLayout(panel)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        # 左：目录树
        left = QFrame()
        left.setObjectName("card")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(14, 14, 14, 14)
        left_lay.setSpacing(8)
        left_lay.addWidget(QLabel("📂 数据库"))
        self._build_dir_tree_widget(left_lay, "analyze_tree")
        
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("separator"); left_lay.addWidget(sep)
        self.btn_toggle_log = QPushButton("▶ 显示操作日志")
        self.btn_toggle_log.setObjectName("secondary_button")
        self.btn_toggle_log.clicked.connect(self._toggle_log_box)
        left_lay.addWidget(self.btn_toggle_log)
        self.idx_stat = QLabel("")
        self.idx_stat.setObjectName("muted_text")
        left_lay.addWidget(self.idx_stat)
        splitter.addWidget(left)

        # 右：数据库表格 + 筛选
        right = self._build_db_panel()
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 25)
        splitter.setStretchFactor(1, 75)
        QTimer.singleShot(0, lambda: splitter.setSizes([300, 900]))
        main_lay.addWidget(splitter, 1)
        return panel

    # ── 右：数据库浏览面板 ────────────────────────────────────────────────────

    def _build_db_panel(self):
        panel = QFrame()
        panel.setObjectName("card")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        # 数据库标题 + 统计同行
        db_hdr_row = QHBoxLayout()
        db_hdr_row.addWidget(QLabel("📊 数据库"))
        db_hdr_row.addStretch()
        self.lbl_stats_analyze = QLabel("—")
        self.lbl_stats_analyze.setObjectName("stats_analyze")
        db_hdr_row.addWidget(self.lbl_stats_analyze)
        lay.addLayout(db_hdr_row)

        # 筛选行：全选 + 品牌 + 类别 + 描述 + 置信度 + 类型 + AI状态 + Hash
        filter_row = QHBoxLayout()
        
        self.chk_select_all = QCheckBox("全选")
        self.chk_select_all.stateChanged.connect(self._on_select_all_changed)
        filter_row.addWidget(self.chk_select_all)
        filter_row.addSpacing(5)
        
        filter_row.addWidget(QLabel("品牌："))
        self.db_brand_filter = QComboBox()
        self.db_brand_filter.addItem("全部", "")
        self.db_brand_filter.setFixedWidth(100)
        self.db_brand_filter.setEditable(True)
        self.db_brand_filter.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.db_brand_filter.currentIndexChanged.connect(self._refresh_db_table)
        filter_row.addWidget(self.db_brand_filter)

        filter_row.addWidget(QLabel("类别："))
        self.db_category_filter = QComboBox()
        self.db_category_filter.addItem("全部", "")
        self.db_category_filter.setFixedWidth(80)
        self.db_category_filter.setEditable(True)
        self.db_category_filter.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.db_category_filter.currentIndexChanged.connect(self._refresh_db_table)
        filter_row.addWidget(self.db_category_filter)

        filter_row.addWidget(QLabel("描述："))
        self.db_desc_filter = QLineEdit()
        self.db_desc_filter.setPlaceholderText("画面描述")
        self.db_desc_filter.setFixedWidth(90)
        self.db_desc_filter.returnPressed.connect(self._refresh_db_table)
        filter_row.addWidget(self.db_desc_filter)

        filter_row.addWidget(QLabel("置信度："))
        self.db_conf_filter = QComboBox()
        self.db_conf_filter.addItem("全部", "")
        self.db_conf_filter.addItem("高 (>=70%)", "high")
        self.db_conf_filter.addItem("中 (40%~70%)", "medium")
        self.db_conf_filter.addItem("低 (<40%)", "low")
        self.db_conf_filter.setFixedWidth(115)
        self.db_conf_filter.currentIndexChanged.connect(self._refresh_db_table)
        filter_row.addWidget(self.db_conf_filter)

        filter_row.addWidget(QLabel("类型："))
        self.db_type_filter = QComboBox()
        self.db_type_filter.addItem("全部", "")
        self.db_type_filter.addItem("视频", "video")
        self.db_type_filter.addItem("图片", "image")
        self.db_type_filter.setFixedWidth(95)
        self.db_type_filter.currentIndexChanged.connect(self._refresh_db_table)
        filter_row.addWidget(self.db_type_filter)

        filter_row.addWidget(QLabel("AI状态："))
        self.db_status_filter = QComboBox()
        self.db_status_filter.addItem("全部", "")
        self.db_status_filter.addItem("待分析", "pending")
        self.db_status_filter.addItem("已分析", "analyzed")
        self.db_status_filter.addItem("失败", "failed")
        self.db_status_filter.setFixedWidth(120)
        self.db_status_filter.currentIndexChanged.connect(self._refresh_db_table)
        filter_row.addWidget(self.db_status_filter)

        filter_row.addWidget(QLabel("Hash："))
        self.db_hash_filter = QLineEdit()
        self.db_hash_filter.setPlaceholderText("hash前缀")
        self.db_hash_filter.setFixedWidth(110)
        self.db_hash_filter.returnPressed.connect(self._refresh_db_table)
        filter_row.addWidget(self.db_hash_filter)
        
        btn_db_refresh = QPushButton("↺ 刷新")
        btn_db_refresh.setObjectName("secondary_button")
        btn_db_refresh.clicked.connect(self._refresh_db_table)
        filter_row.addWidget(btn_db_refresh)
        
        filter_row.addStretch()

        lay.addLayout(filter_row)

        # 数据表
        self.db_table = QTableWidget()
        self.db_table.setColumnCount(13)
        self.db_table.setHorizontalHeaderLabels(
            ["", "文件名", "主要画面描述", "次要画面描述", "类型", "品牌", "型号", "类别", "大小", "时长", "置信度", "AI状态", "Hash"]
        )
        hh = self.db_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.db_table.setColumnWidth(0, 30)
        
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        self.db_table.setColumnWidth(1, 400)
        
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        self.db_table.setColumnWidth(2, 150)
        
        hh.setSectionResizeMode(3, QHeaderView.Interactive)
        self.db_table.setColumnWidth(3, 150)
        
        # 类型、品牌、型号、类别、大小、时长（列 4-9）
        for c in range(4, 10):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
            
        # 置信度、AI状态（列 10-11）
        for c in range(10, 12):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        
        # Hash（列 12）
        hh.setSectionResizeMode(12, QHeaderView.Interactive)
        self.db_table.setColumnWidth(12, 250)
        
        self.db_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.db_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.db_table.setAlternatingRowColors(True)
        self.db_table.doubleClicked.connect(self._open_db_file_dir)
        self.db_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.db_table.customContextMenuRequested.connect(self._show_table_context_menu)
        lay.addWidget(self.db_table, 1)

        # 底部操作行
        bot_row = QHBoxLayout()
        self.db_stat = QLabel("共 0 条")
        self.db_stat.setObjectName("muted_text")
        self.db_stat.setWordWrap(False)
        self.db_stat.setMaximumHeight(24)
        bot_row.addWidget(self.db_stat, 1)

        self.btn_reanalyze = QPushButton("🔍 进行AI分析内容")
        self.btn_reanalyze.setObjectName("secondary_button")
        self.btn_reanalyze.setToolTip("对选中的行执行或重新执行视觉LLM + Whisper + CLIP 分析")
        self.btn_reanalyze.clicked.connect(self._start_reanalyze_selected)
        bot_row.addWidget(self.btn_reanalyze)

        self.btn_stop_reanalyze = QPushButton("⏹ 停止AI分析")
        self.btn_stop_reanalyze.setObjectName("secondary_button")
        self.btn_stop_reanalyze.setProperty("danger", True)
        self.btn_stop_reanalyze.setToolTip("停止当前的 AI 分析任务")
        self.btn_stop_reanalyze.setEnabled(False)
        self.btn_stop_reanalyze.clicked.connect(self._stop_reanalyze)
        bot_row.addWidget(self.btn_stop_reanalyze)

        btn_open = QPushButton("🗂 打开目录")
        btn_open.setObjectName("secondary_button")
        btn_open.clicked.connect(lambda: self._open_db_file_dir(
            self.db_table.currentIndex()
        ))
        bot_row.addWidget(btn_open)
        lay.addLayout(bot_row)

        # AI分析任务进度条和状态标签
        self.lbl_db_pbar_status = QLabel("")
        self.lbl_db_pbar_status.setVisible(False)
        lay.addWidget(self.lbl_db_pbar_status)

        self.db_pbar = QProgressBar()
        self.db_pbar.setVisible(False)
        lay.addWidget(self.db_pbar)

        return panel

    # ── 入库相关事件 ──────────────────────────────────────────────────────────

    def _toggle_log_box(self):
        if self.log_dialog.isVisible():
            self.log_dialog.hide()
            self.btn_toggle_log.setText("▶ 显示操作日志")
        else:
            self.log_dialog.show()
            self.log_dialog.raise_()
            self.log_dialog.activateWindow()
            self.btn_toggle_log.setText("▼ 隐藏操作日志")

    def _on_log_dialog_closed(self, result):
        self.btn_toggle_log.setText("▶ 显示操作日志")

    def _is_nas_path(self, path: str) -> bool:
        """判断路径是否需要通过 SMB 访问。"""
        return self._nas_client is not None and self._nas_client.is_connected()

    def _resolve_path(self, path: str) -> str:
        """将相对路径或 UNC 路径转为完整本地路径。"""
        if self._nas_client and self._nas_client.is_connected():
            return path  # SMB 直接访问
        from utils.material_clip_indexer import to_local_path
        return to_local_path(path, self._nas_root)

    def _list_dir(self, path: str) -> list[dict] | None:
        """列出目录内容（本地 or SMB），返回 [{"name":..., "is_dir":..., "full_path":...}, ...]"""
        if self._is_nas_path(path):
            try:
                return self._nas_client.scandir(path)
            except Exception:
                return None
        full = self._resolve_path(path)
        if not os.path.isdir(full):
            return None
        result = []
        try:
            for entry in os.scandir(full):
                if entry.name.startswith(".") or entry.name == "#recycle":
                    continue
                result.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "full_path": entry.path,
                })
        except Exception:
            return None
        return result

    def _dir_has_subdirs(self, path: str) -> bool:
        """检查目录是否包含子目录。"""
        if self._is_nas_path(path):
            try:
                entries = self._nas_client.scandir(path)
                return any(e["is_dir"] and not e["name"].startswith(".") for e in entries)
            except Exception:
                return False
        full = self._resolve_path(path)
        try:
            for entry in os.scandir(full):
                if entry.is_dir() and not entry.name.startswith(".") and entry.name != "#recycle":
                    return True
        except Exception:
            pass
        return False

    def _reload_dir_config(self):
        import json as _json
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "material_index_config.json"
        )
        self._nas_root = ""
        dirs = []
        cfg = {}
        try:
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = _json.load(f)
                self._nas_root = cfg.get("nas_root", "")
                dirs = cfg.get("index_directories", [])
        except Exception:
            pass

        nas_text = self._nas_root if self._nas_root else "（未配置，请前往「环境配置」设置）"
        for attr in ["lbl_nas_root_ingest_tree", "lbl_nas_root_analyze_tree"]:
            lbl = getattr(self, attr, None)
            if lbl is not None:
                lbl.setText(nas_text)

        # 检测是否为 SMB 路径，建立 NAS 客户端
        if self._nas_root.startswith("//") or self._nas_root.startswith("\\\\"):
            try:
                self._nas_client = NASClient.from_config(cfg)
                self._nas_client.connect()
                log.info(f"NAS 客户端已连接: {self._nas_root}")
            except Exception as e:
                log.warning(f"NAS 客户端连接失败: {e}")
                self._nas_client = None
        else:
            self._nas_client = None

        old_selected = getattr(self, "_last_selected_dir", "")

        for tree_attr in ["ingest_tree", "analyze_tree"]:
            tree = getattr(self, tree_attr, None)
            if tree is not None:
                self._populate_dir_tree(tree, dirs)

        if old_selected and hasattr(self, "analyze_tree"):
            self.analyze_tree.blockSignals(True)
            self._select_path_in_tree(old_selected)
            self.analyze_tree.blockSignals(False)
            self._last_selected_dir = old_selected
            self._refresh_db_table()
        else:
            self._last_selected_dir = ""
            self._refresh_db_table()

    def _populate_dir_tree(self, tree, dirs):
        tree.blockSignals(True)
        tree.clear()
        for d in dirs:
            if isinstance(d, dict):
                local_path = d.get("local_path", "")
                nas_folder = d.get("nas_folder", "")
            else:
                local_path = str(d)
                from utils.material_clip_indexer import to_relative_path
                nas_folder = to_relative_path(local_path, self._nas_root)
                if not nas_folder or nas_folder == local_path:
                    nas_folder = os.path.basename(local_path.rstrip("/\\")) or local_path

            if not local_path:
                continue

            item = QTreeWidgetItem(tree)
            item.setText(0, nas_folder)
            item.setData(0, Qt.UserRole, local_path)
            try:
                has_sub = self._dir_has_subdirs(local_path)
                if has_sub:
                    dummy = QTreeWidgetItem(item)
                    dummy.setText(0, "Loading...")
            except Exception:
                pass
        tree.blockSignals(False)

    def _on_tree_item_expanded(self, item):
        if item.childCount() == 1 and item.child(0).data(0, Qt.UserRole) is None:
            item.takeChild(0)
            path = item.data(0, Qt.UserRole)
            self._load_subdirectories(item, path)

    def _load_subdirectories(self, parent_item, path):
        try:
            entries = self._list_dir(path)
            if entries is None:
                return
            entries.sort(key=lambda e: e["name"].lower())

            for entry in entries:
                if not entry["is_dir"] or entry["name"].startswith(".") or entry["name"] == "#recycle":
                    continue
                child = QTreeWidgetItem(parent_item)
                child.setText(0, entry["name"])
                child.setData(0, Qt.UserRole, entry["full_path"] if "full_path" in entry else entry.get("path", ""))
                try:
                    has_sub = self._dir_has_subdirs(
                        entry["full_path"] if "full_path" in entry else entry.get("path", "")
                    )
                    if has_sub:
                        dummy = QTreeWidgetItem(child)
                        dummy.setText(0, "Loading...")
                except Exception:
                    pass
        except Exception:
            pass

    def _on_tree_selection_changed(self, tree=None):
        if tree is None:
            tree = self.dir_tree
        selected = tree.selectedItems()
        if selected:
            val = selected[0].data(0, Qt.UserRole)
            self._last_selected_dir = str(val) if val is not None else ""
        else:
            self._last_selected_dir = ""
        self._refresh_db_table()

    def _select_path_in_tree(self, target_path):
        tree = self.analyze_tree
        if not target_path or not isinstance(target_path, str):
            return
        target_path = os.path.normpath(target_path).lower()

        root_item = None
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            val = item.data(0, Qt.UserRole)
            if not val:
                continue
            root_path = os.path.normpath(val).lower()
            if target_path == root_path:
                tree.setCurrentItem(item)
                item.setSelected(True)
                return
            prefix = root_path if root_path.endswith(os.sep) else (root_path + os.sep)
            if target_path.startswith(prefix):
                tree.setCurrentItem(item)
                item.setSelected(True)
                tree.expandItem(item)
                # expand children recursively to find the exact match
                child_path = target_path[len(prefix):]
                for part in child_path.split(os.sep):
                    if not part:
                        continue
                    found = False
                    for j in range(item.childCount()):
                        child = item.child(j)
                        child_name = child.text(0).lower()
                        if child_name == part or child_name.startswith(part):
                            item = child
                            tree.setCurrentItem(item)
                            item.setSelected(True)
                            tree.expandItem(item)
                            found = True
                            break
                    if not found:
                        break
                return
            if target_path.startswith(prefix):
                root_item = item
                break

        if not root_item:
            return

        current_item = root_item
        root_path = os.path.normpath(root_item.data(0, Qt.UserRole))
        rel = os.path.relpath(target_path, root_path)
        parts = [p for p in rel.split(os.sep) if p]

        for part in parts:
            current_item.setExpanded(True)
            found_child = None
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                if child.text(0).lower() == part.lower():
                    found_child = child
                    break
            if found_child:
                current_item = found_child
            else:
                break

        tree.setCurrentItem(current_item)
        current_item.setSelected(True)

    def _get_selected_directory(self) -> str:
        return getattr(self, "_last_selected_dir", "")

    def _set_busy(self, busy: bool):
        self.btn_meta.setEnabled(not busy)
        self.btn_ocr_rename.setEnabled(not busy)
        self.btn_reanalyze.setEnabled(not busy)
        if hasattr(self, "btn_import_tasks"):
            self.btn_import_tasks.setEnabled(not busy)

    def _show_tree_context_menu(self, pos, tree=None):
        if tree is None:
            tree = self.dir_tree
        item = tree.itemAt(pos)
        if not item:
            return
        path = item.data(0, Qt.UserRole)
        if not path:
            return

        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction

        menu = QMenu(self.parent_widget)
        act_scan = QAction("🔍 扫描此目录（快速入库）", menu)
        act_scan.triggered.connect(lambda: self._scan_directory(path))
        menu.addAction(act_scan)

        menu.exec_(tree.viewport().mapToGlobal(pos))

    def _scan_directory(self, directory: str):
        if not directory:
            return
        # NAS SMB 相对路径 → 本地挂载路径
        if self._is_nas_path(directory):
            nas_dir = "/mnt/nas/" + directory
            if not os.path.isdir(nas_dir):
                self.show_warning(f"目录不可访问：\n{directory}\n\n请确认 NAS 已挂载到 /mnt/nas/", "目录无效")
                return
            directory = nas_dir
        elif not os.path.isdir(directory):
            self.show_warning(f"目录不可访问：\n{directory}", "目录无效")
            return

        # 自动拉起日志窗口以让用户看到进度
        if not self.log_dialog.isVisible():
            self._toggle_log_box()

        self._set_busy(True)
        self._log_clear()
        self._log(f"快速入库（元数据）：{directory}\n")
        self.idx_stat.setText("")
        
        # 使用共享进度条
        self.db_pbar.setRange(0, 0)
        self.db_pbar.setVisible(True)
        self.lbl_db_pbar_status.setText("正在进行快速入库元数据…")
        self.lbl_db_pbar_status.setVisible(True)

        w = self.track_worker(
            _IndexMetaWorker(directory, self._nas_root, self.chk_force.isChecked())
        )
        w.log_line.connect(lambda m: self.log_box.append(m))
        w.progress.connect(self._on_meta_progress)
        w.finished.connect(self._on_meta_done)
        w.error.connect(self._on_work_err)
        w.start()

    def _on_meta_progress(self, done, total):
        if done == -1:
            self.db_pbar.setRange(0, 0)
            self.lbl_db_pbar_status.setText(f"正在扫描目录并统计文件：已发现 {total} 个媒体文件...")
        else:
            self.db_pbar.setRange(0, total)
            self.db_pbar.setValue(done)
            self.lbl_db_pbar_status.setText(f"正在进行快速入库元数据：已处理 {done} / {total}")

    def _start_meta_index(self):
        directory = self._get_selected_directory()
        if not directory:
            self.show_warning("请先在「环境配置」中添加入库目录。", "未配置目录")
            return
        self._scan_directory(directory)

    def _on_meta_done(self, ok: int, skip: int, fail: int):
        self._set_busy(False)
        self.db_pbar.setVisible(False)
        self.lbl_db_pbar_status.setVisible(False)
        self.idx_stat.setText(f"✅ 元信息入库完成  新增:{ok}  跳过:{skip}  失败:{fail}")
        self._reload_stats()
        self._refresh_db_table()

    def _start_ocr_rename(self):
        directory = self._get_selected_directory()
        if not directory:
            self.show_warning("请先选择或在「环境配置」中添加入库目录。", "未配置目录")
            return
        # NAS SMB 相对路径 → 本地挂载路径
        if self._is_nas_path(directory):
            directory = "/mnt/nas/" + directory
        if not os.path.isdir(directory):
            self.show_warning(f"目录不可访问：\n{directory}", "目录无效")
            return

        # 弹出警告框二次确认
        if not self.confirm("确定要对该目录下所有已入库的图片执行 OCR 智能重命名吗？\n该操作会物理修改文件名与数据库索引路径。", "智能重命名确认"):
            return

        self._set_busy(True)
        self.log_box.clear()
        self.log_box.append(f"智能 OCR 重命名：{directory}\n")
        self.idx_stat.setText("")
        
        # 使用共享进度条
        self.db_pbar.setRange(0, 0)
        self.db_pbar.setVisible(True)
        self.lbl_db_pbar_status.setText("正在进行智能 OCR 重命名…")
        self.lbl_db_pbar_status.setVisible(True)

        w = self.track_worker(_OcrRenameWorker(directory, self._nas_root))
        w.log_line.connect(lambda m: self.log_box.append(m))
        w.finished.connect(self._on_ocr_rename_done)
        w.error.connect(self._on_work_err)
        w.start()

    def _on_ocr_rename_done(self, ok: int, fail: int):
        self._set_busy(False)
        self.db_pbar.setVisible(False)
        self.lbl_db_pbar_status.setVisible(False)
        self.idx_stat.setText(f"✅ 智能重命名完成  成功:{ok}  失败:{fail}")
        # 刷新一下当前表格数据
        self._refresh_db_table()
        # 刷新统计信息
        self._reload_stats()



    def _on_work_err(self, msg: str):
        self._set_busy(False)
        self.db_pbar.setVisible(False)
        self.lbl_db_pbar_status.setVisible(False)
        self.log_box.append(f"\n❌ {msg}")
        self.show_error(f"操作出错：\n{msg}")

    def _get_index_directories(self):
        import json as _json
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "material_index_config.json"
        )
        dirs = []
        try:
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = _json.load(f)
                dirs = cfg.get("index_directories", [])
        except Exception:
            pass
        
        normalized_dirs = []
        for d in dirs:
            if isinstance(d, dict):
                local_path = d.get("local_path", "")
                nas_folder = d.get("nas_folder", "")
            else:
                local_path = str(d)
                nas_folder = ""
            if local_path:
                normalized_dirs.append({
                    "local_path": local_path,
                    "nas_folder": nas_folder or os.path.basename(local_path.rstrip("/\\"))
                })
        return normalized_dirs

    def _reload_stats(self):
        self.lbl_stats_ingest.setText("素材统计：扫描中…")
        dirs = self._get_index_directories()
        
        self.log_box.append("开始对齐所有目录的文件 Hash 并刷新索引统计...\n")
        
        w = self.track_worker(_StatsWorker(dirs))
        w.finished.connect(self._on_stats_done)
        w.error.connect(lambda _: self.lbl_stats_ingest.setText("对齐与统计失败"))
        w.log_line.connect(lambda m: self.log_box.append(m))
        w.start()

    def _refresh_stats_light(self):
        """仅从数据库读取统计数字（不扫磁盘），用于页面初始显示。"""
        dirs = self._get_index_directories()
        w = self.track_worker(_StatsLightWorker(dirs))
        w.finished.connect(self._on_stats_done)
        w.error.connect(lambda _: self.lbl_stats_ingest.setText("统计失败"))
        w.start()

    def _load_brand_list(self):
        """从数据库加载品牌列表到品牌下拉框。"""
        w = self.track_worker(_LoadBrandsWorker())
        w.finished.connect(self._on_brands_loaded)
        w.start()

    def _on_brands_loaded(self, brands: list):
        self.db_brand_filter.blockSignals(True)
        self.db_brand_filter.clear()
        self.db_brand_filter.addItem("全部", "")
        for brand in brands:
            self.db_brand_filter.addItem(brand)
        self.db_brand_filter.blockSignals(False)

    def _load_category_list(self):
        """从数据库加载类别列表到类别下拉框。"""
        w = self.track_worker(_LoadCategoriesWorker())
        w.finished.connect(self._on_categories_loaded)
        w.start()

    def _on_categories_loaded(self, categories: list):
        self.db_category_filter.blockSignals(True)
        self.db_category_filter.clear()
        self.db_category_filter.addItem("全部", "")
        for cat in categories:
            self.db_category_filter.addItem(cat)
        self.db_category_filter.blockSignals(False)

    def _align_and_ingest(self):
        """对齐入库按钮：扫描目录，将新文件 Hash 对齐后批量入库，完成后自动刷新统计。"""
        dirs = self._get_index_directories()
        self.lbl_stats_ingest.setText("对齐入库中…")
        self.log_box.append("开始扫描磁盘目录，对齐文件 Hash 并入库新文件...\n")
        w = self.track_worker(_AlignAndIngestWorker(dirs))
        w.log_line.connect(lambda m: self.log_box.append(m))
        w.finished.connect(lambda _: self._reload_stats())
        w.error.connect(lambda _: self.lbl_stats_ingest.setText("对齐入库失败"))
        w.start()

    def _on_stats_done(self, stats: dict):
        total    = stats.get("total", 0)
        pending  = stats.get("pending", 0)
        analyzed = stats.get("analyzed", 0)
        failed   = stats.get("failed", 0)
        
        disk_total = stats.get("disk_total", 0)
        diff_count = stats.get("diff_count", 0)
        dir_stats  = stats.get("dir_stats", {})
        
        self._missing_files_list = stats.get("missing_files", [])
        
        # 构建数据库统计 + 目录文件统计两块显示
        db_line = (
            f"📊 数据库总计: <span style='color: #ffffff;'>{total}</span> &nbsp;|&nbsp; "
            f"待分析: <span style='color: #f59e0b;'>{pending}</span> &nbsp;"
            f"已分析: <span style='color: #22c55e;'>{analyzed}</span> &nbsp;"
            f"失败: <span style='color: #ef4444;'>{failed}</span>"
        )
        disk_line = (
            f"💿 磁盘媒体: <span style='color: #3b82f6;'>{disk_total}</span> &nbsp;|&nbsp; "
            f"未入库差额: <span style='color: #f43f5e;'>{diff_count}</span>"
        )
        dir_lines = []
        for d, ds in dir_stats.items():
            short = os.path.basename(d.rstrip("/\\"))
            dir_lines.append(
                f"&nbsp;&nbsp;&nbsp;📁 <span style='color: #a78bfa;'>{short}</span>: "
                f"<span style='color: #ffffff;'>{ds['total']}</span> "
                f"(视频 <span style='color: #60a5fa;'>{ds['video']}</span>, "
                f"图片 <span style='color: #34d399;'>{ds['image']}</span>)"
            )
        dir_block = "<br>".join(dir_lines) if dir_lines else ""
        
        # 素材统计（仅磁盘媒体信息）
        disk_line = (
            f"💿 磁盘媒体: <span style='color: #3b82f6;'>{disk_total}</span> &nbsp;|&nbsp; "
            f"未入库差额: <span style='color: #f43f5e;'>{diff_count}</span>"
        )
        ingest_parts = [disk_line]
        if dir_block:
            ingest_parts.append(dir_block)
        self.lbl_stats_ingest.setText("<br>".join(ingest_parts))

        # 智能分析统计（数据库信息）
        self.lbl_stats_analyze.setText(
            f"📊 数据库总计: <span style='color: #ffffff;'>{total}</span> &nbsp;|&nbsp; "
            f"待分析: <span style='color: #f59e0b;'>{pending}</span> &nbsp;"
            f"已分析: <span style='color: #22c55e;'>{analyzed}</span> &nbsp;"
            f"失败: <span style='color: #ef4444;'>{failed}</span>"
        )
        
        if hasattr(self, "diff_table") and self.diff_table:
            self._refresh_diff_table_data()

    def _build_diff_panel(self):
        panel = QFrame()
        panel.setObjectName("card")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        
        # 标题行 + 素材统计
        stats_hdr_row = QHBoxLayout()
        stats_hdr_row.addWidget(QLabel("🔍 磁盘与数据库「未入库差额」文件列表"))
        stats_hdr_row.addStretch()
        stats_hdr_row.addWidget(QLabel("素材统计："))
        self.lbl_stats_ingest = QLabel("—")
        self.lbl_stats_ingest.setObjectName("stats_ingest")
        stats_hdr_row.addWidget(self.lbl_stats_ingest)
        btn_refresh_stats = QPushButton("↺ 刷新")
        btn_refresh_stats.setToolTip("刷新统计（数据库 + 目录文件数），不扫描新文件")
        btn_refresh_stats.setObjectName("btn_refresh_stats")
        btn_refresh_stats.clicked.connect(self._reload_stats)
        stats_hdr_row.addWidget(btn_refresh_stats)
        btn_align = QPushButton("📂 对齐入库")
        btn_align.setToolTip("扫描磁盘目录，将新文件 Hash 对齐后批量入库")
        btn_align.setObjectName("btn_align")
        btn_align.clicked.connect(self._align_and_ingest)
        stats_hdr_row.addWidget(btn_align)
        self.btn_import_tasks = QPushButton("📥 导入浏览器任务")
        self.btn_import_tasks.setToolTip("读取 material_import_tasks.json，将待处理项批量快速入库")
        self.btn_import_tasks.setObjectName("secondary_button")
        self.btn_import_tasks.clicked.connect(self._start_import_material_tasks)
        stats_hdr_row.addWidget(self.btn_import_tasks)
        lay.addLayout(stats_hdr_row)

        ctrl_row = QHBoxLayout()
        
        self.chk_diff_select_all = QCheckBox("全选")
        self.chk_diff_select_all.stateChanged.connect(self._on_diff_select_all_changed)
        ctrl_row.addWidget(self.chk_diff_select_all)

        ctrl_row.addWidget(QLabel("类型："))
        self.diff_type_filter = QComboBox()
        self.diff_type_filter.addItem("全部", "")
        self.diff_type_filter.addItem("视频", "video")
        self.diff_type_filter.addItem("图片", "image")
        self.diff_type_filter.addItem("音频", "audio")
        self.diff_type_filter.setFixedWidth(80)
        self.diff_type_filter.currentIndexChanged.connect(self._refresh_diff_table_from_db)
        ctrl_row.addWidget(self.diff_type_filter)
        
        self.lbl_diff_status = QLabel("（请先在左侧索引统计点击「刷新」开始差分扫描）")
        self.lbl_diff_status.setObjectName("muted_text")
        ctrl_row.addWidget(self.lbl_diff_status, 1)
        
        lay.addLayout(ctrl_row)
        
        self.diff_table = QTableWidget()
        self.diff_table.setColumnCount(6)
        self.diff_table.setHorizontalHeaderLabels(["", "文件路径", "文件名", "类型", "大小", "已入库"])
        
        hh = self.diff_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.diff_table.setColumnWidth(0, 35)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        self.diff_table.setColumnWidth(1, 300)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        self.diff_table.setColumnWidth(2, 200)
        hh.setSectionResizeMode(3, QHeaderView.Interactive)
        self.diff_table.setColumnWidth(3, 60)
        hh.setSectionResizeMode(4, QHeaderView.Interactive)
        self.diff_table.setColumnWidth(4, 80)
        hh.setSectionResizeMode(5, QHeaderView.Interactive)
        self.diff_table.setColumnWidth(5, 60)
        self.diff_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.diff_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.diff_table.setAlternatingRowColors(True)
        self.diff_table.doubleClicked.connect(self._open_diff_file_dir)
        self.diff_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.diff_table.customContextMenuRequested.connect(self._show_diff_table_context_menu)
        
        lay.addWidget(self.diff_table, 1)

        # 底部操作行
        bot_row = QHBoxLayout()
        self.db_stat_ingest = QLabel("请在左侧目录树中选择目录以查看文件。")
        self.db_stat_ingest.setObjectName("muted_text")
        bot_row.addWidget(self.db_stat_ingest, 1)

        self.btn_meta = QPushButton("📂 快速入库（仅元数据）")
        self.btn_meta.setObjectName("primary_button")
        self.btn_meta.setToolTip("只记录 hash/路径/大小，不做 AI 分析，速度极快")
        self.btn_meta.clicked.connect(self._start_meta_index)
        bot_row.addWidget(self.btn_meta)

        self.btn_ocr_rename = QPushButton("🏷️ 智能 OCR 重命名（仅图片）")
        self.btn_ocr_rename.setObjectName("secondary_button")
        self.btn_ocr_rename.setToolTip("对当前目录下已入库的图片执行 OCR 识别文字并重命名物理文件与数据库")
        self.btn_ocr_rename.clicked.connect(self._start_ocr_rename)
        bot_row.addWidget(self.btn_ocr_rename)

        self.chk_force = QCheckBox("强制重新入库")
        self.chk_force.setToolTip("即使文件 hash 已存在也重新入库")
        bot_row.addWidget(self.chk_force)
        lay.addLayout(bot_row)

        return panel

    def _on_diff_select_all_changed(self, state):
        self.diff_table.blockSignals(True)
        is_checked = (state == Qt.Checked.value or state == Qt.Checked)
        for i in range(self.diff_table.rowCount()):
            chk_item = self.diff_table.cellWidget(i, 0)
            if isinstance(chk_item, QCheckBox):
                chk_item.setChecked(is_checked)
        self.diff_table.blockSignals(False)

    def _refresh_diff_table_data(self):
        self.diff_table.setRowCount(0)
        self.chk_diff_select_all.setChecked(False)
        all_files = getattr(self, "_missing_files_list", [])
        sel_dir = self._last_selected_dir
        if sel_dir:
            files = [f for f in all_files if f.get("local_path", "").startswith(sel_dir)]
        else:
            files = all_files
        if not files:
            self.lbl_diff_status.setText("没有发现未入库的文件（磁盘与数据库已完全同步）")
            return
            
        self.lbl_diff_status.setText(f"发现 {len(files)} 个未入库媒体文件")
        self.diff_table.setRowCount(len(files))
        for idx, f in enumerate(files):
            # 0 = checkbox
            chk = QCheckBox()
            chk.setStyleSheet("margin-left: 8px;")
            self.diff_table.setCellWidget(idx, 0, chk)
            
            # 1 = 文件路径
            full_path = f["local_path"]
            path_item = QTableWidgetItem(full_path)
            path_item.setFlags(path_item.flags() & ~Qt.ItemIsEditable)
            path_item.setData(Qt.UserRole, full_path)
            self.diff_table.setItem(idx, 1, path_item)

            # 2 = 文件名
            name_item = QTableWidgetItem(os.path.basename(full_path))
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.diff_table.setItem(idx, 2, name_item)

            # 3 = 类型
            import os as _os
            ext = _os.path.splitext(full_path)[1].lower()
            type_map = {".mp4": "视频", ".mov": "视频", ".avi": "视频", ".mkv": "视频",
                        ".jpg": "图片", ".jpeg": "图片", ".png": "图片", ".webp": "图片",
                        ".mp3": "音频", ".wav": "音频", ".m4a": "音频"}
            type_item = QTableWidgetItem(type_map.get(ext, ext.lstrip(".") if ext else "—"))
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
            self.diff_table.setItem(idx, 3, type_item)
            
            # 4 = 大小
            sz_mb = f["size"] / (1024 * 1024)
            size_item = QTableWidgetItem(f"{sz_mb:.2f} MB")
            size_item.setFlags(size_item.flags() & ~Qt.ItemIsEditable)
            self.diff_table.setItem(idx, 4, size_item)

    def _start_diff_batch_ingest(self):
        checked_paths = []
        for i in range(self.diff_table.rowCount()):
            chk_item = self.diff_table.cellWidget(i, 0)
            if isinstance(chk_item, QCheckBox) and chk_item.isChecked():
                path_item = self.diff_table.item(i, 1)
                if path_item:
                    checked_paths.append(path_item.data(Qt.UserRole) or path_item.text())
                    
        if not checked_paths:
            self.show_error("请先勾选需要入库的文件！")
            return
            
        self.db_pbar.setVisible(True)
        self.db_pbar.setRange(0, len(checked_paths))
        self.db_pbar.setValue(0)
        self.lbl_db_pbar_status.setVisible(True)
        self.lbl_db_pbar_status.setText(f"正在批量入库: 0 / {len(checked_paths)}")
        
        self.log_box.clear()
        self.log_box.append(f"开始对选择的 {len(checked_paths)} 个未入库文件执行快速元数据入库…\n")
        self._toggle_log_box()
        
        w = self.track_worker(_BatchIndexMetaWorker(checked_paths, force=False))
        w.log_line.connect(lambda m: self.log_box.append(m))
        w.progress.connect(self._on_diff_ingest_progress)
        w.finished.connect(self._on_diff_ingest_finished)
        w.error.connect(self._on_diff_ingest_error)
        w.start()

    def _material_import_tasks_file(self) -> str:
        from config.paths import KNOWLEDGE_MATERIALS_DIR
        return os.path.join(KNOWLEDGE_MATERIALS_DIR, "material_import_tasks.json")

    def _start_import_material_tasks(self):
        tasks_file = self._material_import_tasks_file()
        if not os.path.isfile(tasks_file):
            self.show_warning(f"未找到任务清单文件：\n{tasks_file}", "任务不存在")
            return

        self._set_busy(True)
        self.db_pbar.setVisible(True)
        self.db_pbar.setRange(0, 0)
        self.lbl_db_pbar_status.setVisible(True)
        self.lbl_db_pbar_status.setText("正在导入素材浏览器任务…")
        self._active_log = "ingest"
        self.log_box.append(f"开始导入素材浏览器任务清单：{tasks_file}")
        if not self.log_dialog.isVisible():
            self._toggle_log_box()

        w = self.track_worker(_ImportMaterialTasksWorker(tasks_file))
        w.log_line.connect(lambda m: self.log_box.append(m))
        w.progress.connect(self._on_import_material_tasks_progress)
        w.finished.connect(self._on_import_material_tasks_finished)
        w.error.connect(self._on_work_err)
        w.start()

    def _on_import_material_tasks_progress(self, current: int, total: int):
        self.db_pbar.setRange(0, max(1, total))
        self.db_pbar.setValue(current)
        self.lbl_db_pbar_status.setText(f"正在导入素材浏览器任务：{current} / {total}")

    def _on_import_material_tasks_finished(self, result: dict):
        self._set_busy(False)
        self.db_pbar.setVisible(False)
        self.lbl_db_pbar_status.setVisible(False)
        ok = int(result.get("ok", 0))
        skip = int(result.get("skip", 0))
        fail = int(result.get("fail", 0))
        missing = int(result.get("missing", 0))
        total = int(result.get("total", 0))
        pending_left = int(result.get("pending_left", 0))
        tasks_file = result.get("file", "")
        self.log_box.append(
            f"\n✅ 浏览器任务导入完成：总计 {total}，成功 {ok}，跳过 {skip}，失败 {fail}，文件缺失 {missing}"
        )
        if tasks_file:
            self.log_box.append(f"任务清单已回写：{tasks_file}（剩余 pending: {pending_left}）")
        self.show_message(
            f"素材导入任务执行完成！\n总计: {total}\n成功: {ok}\n跳过: {skip}\n失败: {fail}\n文件缺失: {missing}\n剩余待处理: {pending_left}"
        )
        self._reload_stats()
        self._refresh_db_table()

    def _on_diff_ingest_progress(self, current, total):
        self.db_pbar.setValue(current)
        self.lbl_db_pbar_status.setText(f"正在批量入库: {current} / {total}")
        
    def _on_diff_ingest_finished(self, ok, skip, fail):
        self.db_pbar.setVisible(False)
        self.lbl_db_pbar_status.setVisible(False)
        self.log_box.append(f"\n✅ 批量快速入库完成：成功 {ok}，跳过 {skip}，失败 {fail}")
        self.show_message(f"批量快速入库完成！\n成功: {ok}\n跳过: {skip}\n失败: {fail}")
        self._reload_stats()
        self._refresh_db_table()
        
    def _on_diff_ingest_error(self, msg):
        self.db_pbar.setVisible(False)
        self.lbl_db_pbar_status.setVisible(False)
        self.log_box.append(f"\n❌ 批量快速入库出错: {msg}")
        self.show_error(f"批量快速入库异常:\n{msg}")


    # ── 数据库面板事件 ────────────────────────────────────────────────────────

    def _refresh_db_table(self):
        if getattr(self, "_is_init", False):
            return
        path_prefix = self._get_selected_directory()
        is_ingest = self.stacked_widget.currentIndex() == 0
        if not path_prefix:
            msg = "请在左侧目录树中选择目录以查看文件。"
            if is_ingest and hasattr(self, "db_stat_ingest"):
                self.db_stat_ingest.setText(msg)
            else:
                self.db_stat.setText(msg)
            self.db_table.setRowCount(0)
            return

        if hasattr(self, "_query_worker") and self._query_worker:
            if self._query_worker.isRunning():
                self._query_worker.quit()
                self._query_worker.wait(3000)
            try:
                self._query_worker.finished.disconnect()
                self._query_worker.error.disconnect()
            except Exception:
                pass

        self.db_stat.setText("查询中…")
        if hasattr(self, "db_stat_ingest"):
            self.db_stat_ingest.setText("⏳ 查询中…")
        self.db_table.setRowCount(0)
        if hasattr(self, "diff_table") and self.diff_table:
            self.diff_table.setRowCount(0)
            self.diff_table.setEnabled(False)
        status_filter = self.db_status_filter.currentData() or ""
        type_filter   = self.db_type_filter.currentData() or ""
        hash_prefix  = self.db_hash_filter.text().strip()
        brand_filter = self.db_brand_filter.currentText().strip() if self.db_brand_filter.currentIndex() > 0 else ""
        desc_filter  = self.db_desc_filter.text().strip()
        conf_filter  = self.db_conf_filter.currentData() or ""
        cat_filter   = self.db_category_filter.currentText().strip() if self.db_category_filter.currentIndex() > 0 else ""
        
        self._query_worker = self.track_worker(
            _QueryMaterialsWorker(
                path_prefix, status_filter, hash_prefix=hash_prefix, media_type=type_filter,
                brand=brand_filter, scene_desc=desc_filter, conf_filter=conf_filter,
                product=cat_filter
            )
        )
        self._query_worker.finished.connect(self._on_db_loaded)
        self._query_worker.error.connect(lambda m: self.db_stat.setText(f"❌ 查询失败: {m.split(chr(10))[0]}"))
        self._query_worker.start()

    def _on_db_loaded(self, rows: list):
        try:
            self._db_rows = rows
            self.db_table.setUpdatesEnabled(False)
            self.db_table.setRowCount(len(rows))

            if hasattr(self, "chk_select_all"):
                self.chk_select_all.blockSignals(True)
                self.chk_select_all.setChecked(False)
                self.chk_select_all.blockSignals(False)

            for r, row in enumerate(rows):
                fname  = row.get("filename") or os.path.basename(row.get("path", ""))
                desc_p = row.get("scene_desc_primary") or "—"
                desc_s = row.get("scene_desc_secondary") or "—"
                mtype  = row.get("media_type") or "—"
                brand  = row.get("brand")  or "—"
                model  = row.get("model")  or "—"
                cat    = row.get("category") or (row.get("product") or "—")
                fsize  = row.get("file_size")
                conf   = row.get("ai_confidence")
                status = row.get("ai_status") or "pending"
                fhash  = row.get("file_hash") or "—"

                conf_text = f"{conf:.0%}" if conf is not None else "—"
                size_text = f"{fsize / 1048576:.1f} MB" if isinstance(fsize, (int, float)) and fsize > 0 else "—"
                # 时长格式化：秒 → M:SS 或 Ss（图片无时长显示 —）
                dur_val = row.get("duration_s")
                if isinstance(dur_val, (int, float)) and dur_val > 0:
                    mm = int(dur_val // 60)
                    ss = int(dur_val % 60)
                    dur_text = f"{mm}:{ss:02d}" if mm else f"{dur_val:.1f}s"
                else:
                    dur_text = "—"

                chk_item = QTableWidgetItem()
                chk_item.setCheckState(Qt.Unchecked)
                chk_item.setData(Qt.UserRole, row)
                self.db_table.setItem(r, 0, chk_item)

                vals = [fname, desc_p, desc_s, mtype, brand, model, cat, size_text, dur_text, conf_text, status, fhash]
                for c, v in enumerate(vals):
                    cell = QTableWidgetItem(str(v))
                    cell.setData(Qt.UserRole, row)
                    if c == 7:  # 大小右对齐
                        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if c == 8:  # 时长右对齐
                        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if c == 9 and conf is not None:  # 置信度
                        key = "high" if conf >= 0.7 else ("medium" if conf >= 0.4 else "low")
                        cell.setForeground(QColor(_CONF_COLOR[key]))
                    if c == 10:  # AI状态
                        cell.setForeground(QColor(_STATUS_COLOR.get(status, "#9ca3af")))
                    self.db_table.setItem(r, c + 1, cell)
            self.db_table.setUpdatesEnabled(True)
            if hasattr(self, "diff_table") and self.diff_table:
                self.diff_table.setEnabled(True)

            total = len(rows)
            no_brand = sum(1 for r in rows if not r.get("brand"))
            self.db_stat.setText(
                f"共 {total} 条  缺少品牌/型号: {no_brand} 条  双击文件名播放，双击其他单元格打开目录"
            )

            # 填充品牌/类别下拉筛选框
            self._populate_filter_dropdowns(rows)

            # 同步填充素材入库面板的 diff 表（仅在素材入库 tab 激活时）
            if hasattr(self, "diff_table") and self.diff_table and self.stacked_widget.currentIndex() == 0:
                type_filter = self.diff_type_filter.currentData() if hasattr(self, 'diff_type_filter') else ""
                filtered_rows = rows
                if type_filter:
                    filtered_rows = [r for r in rows if r.get("media_type") == type_filter]
                self.diff_table.setRowCount(len(filtered_rows))
                for r, row in enumerate(filtered_rows):
                    chk = QCheckBox()
                    chk.setStyleSheet("margin-left: 8px;")
                    self.diff_table.setCellWidget(r, 0, chk)
                    fpath = row.get("path", "")
                    fname = row.get("filename") or os.path.basename(fpath)
                    mtype = row.get("media_type") or "—"
                    fsize = row.get("file_size")
                    if isinstance(fsize, (int, float)) and fsize > 0:
                        if fsize >= 1048576:
                            size_text = f"{fsize / 1048576:.1f} MB"
                        elif fsize >= 1024:
                            size_text = f"{fsize / 1024:.1f} KB"
                        else:
                            size_text = f"{fsize} B"
                    else:
                        size_text = "—"
                    on_disk = "是"  # 数据来自数据库，已入库
                    # 存 row 数据到文件路径列，供双击播放使用
                    path_cell = QTableWidgetItem(fpath)
                    path_cell.setFlags(path_cell.flags() & ~Qt.ItemIsEditable)
                    path_cell.setData(Qt.UserRole, row)
                    self.diff_table.setItem(r, 1, path_cell)
                    for c, val in enumerate([fname, mtype, size_text, on_disk]):
                        item = QTableWidgetItem(str(val))
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.diff_table.setItem(r, c + 2, item)
                self.db_stat_ingest.setText(f"共 {len(filtered_rows)} 条")
        except Exception as e:
            self.db_stat.setText(f"❌ 渲染表格失败: {e}")
            if hasattr(self, "diff_table") and self.diff_table:
                self.diff_table.setEnabled(True)
            log.error(f"_on_db_loaded 异常: {e}", exc_info=True)

    def _populate_filter_dropdowns(self, rows: list):
        """从查询结果中提取唯一品牌和类别，填充下拉筛选框。"""
        from utils.brand_normalizer import canonical_name
        brands = set()
        categories = set()
        for row in rows:
            b = row.get("brand")
            if b and b.strip():
                brands.add(canonical_name(b) or b.strip())
            c = row.get("category") or row.get("product")
            if c and c.strip():
                categories.add(c.strip())

        # 品牌下拉
        current_brand = self.db_brand_filter.currentText()
        self.db_brand_filter.blockSignals(True)
        self.db_brand_filter.clear()
        self.db_brand_filter.addItem("全部", "")
        for brand_name in sorted(brands):
            self.db_brand_filter.addItem(brand_name)
        idx = self.db_brand_filter.findText(current_brand)
        if idx >= 0:
            self.db_brand_filter.setCurrentIndex(idx)
        self.db_brand_filter.blockSignals(False)

        # 类别下拉
        current_cat = self.db_category_filter.currentText()
        self.db_category_filter.blockSignals(True)
        self.db_category_filter.clear()
        self.db_category_filter.addItem("全部", "")
        for cat_name in sorted(categories):
            self.db_category_filter.addItem(cat_name)
        idx = self.db_category_filter.findText(current_cat)
        if idx >= 0:
            self.db_category_filter.setCurrentIndex(idx)
        self.db_category_filter.blockSignals(False)

    def _start_reanalyze_selected(self):
        if not getattr(self.main_window, "_models_ready", False):
            self.show_error(
                "❌ 视觉大模型尚未就绪（未启动或未加载），请先启动 Ollama 并测试大模型状态！",
                "大模型未就绪"
            )
            return

        # 优先收集已勾选复选框的行
        materials = []
        for r in range(self.db_table.rowCount()):
            item = self.db_table.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                data = item.data(Qt.UserRole)
                if data and data.get("id"):
                    materials.append({"id": data["id"], "path": data.get("path", "")})

        # 如果没有勾选任何行，则回退到通过表格选择的高亮行
        if not materials:
            selected_rows = self.db_table.selectionModel().selectedRows()
            for idx in selected_rows:
                item = self.db_table.item(idx.row(), 0)
                if item:
                    data = item.data(Qt.UserRole)
                    if data and data.get("id"):
                        materials.append({"id": data["id"], "path": data.get("path", "")})

        if not materials:
            self.show_warning("请先勾选或在表格中选中要进行 AI 分析的素材行。", "未选择")
            return

        self._set_busy(True)
        self.log_box.clear()
        self.log_box.append(f"开始进行 AI 分析（共 {len(materials)} 个素材）…\n")
        self.idx_stat.setText("")

        self.db_pbar.setRange(0, len(materials))
        self.db_pbar.setValue(0)
        self.db_pbar.setVisible(True)
        self.lbl_db_pbar_status.setText(f"正在进行 AI 分析：0 / {len(materials)}")
        self.lbl_db_pbar_status.setVisible(True)

        self.reanalyze_worker = self.track_worker(_ReAnalyzeSelectedWorker(materials, self._nas_root))
        self.reanalyze_worker.log_line.connect(lambda m: self.log_box.append(m))
        self.reanalyze_worker.progress.connect(self._on_reanalyze_progress)
        self.reanalyze_worker.finished.connect(self._on_reanalyze_done)
        self.reanalyze_worker.error.connect(self._on_reanalyze_err)
        self.reanalyze_worker.start()
        self.btn_stop_reanalyze.setEnabled(True)

    def _stop_reanalyze(self):
        if hasattr(self, "reanalyze_worker") and self.reanalyze_worker and self.reanalyze_worker.isRunning():
            self.reanalyze_worker.cancel()
            self.log_box.append("\n⏳ 正在发送终止信号，请稍候...")
            self.btn_stop_reanalyze.setEnabled(False)

    def _on_reanalyze_progress(self, done, total):
        self.db_pbar.setValue(done)
        self.lbl_db_pbar_status.setText(f"正在进行 AI 分析，已完成：{done} / {total}")

    def _on_reanalyze_done(self, ok: int, fail: int):
        self._set_busy(False)
        self.db_pbar.setVisible(False)
        self.lbl_db_pbar_status.setVisible(False)
        self.btn_stop_reanalyze.setEnabled(False)
        self.log_box.append(f"\n✅ AI 分析完成  成功:{ok}  失败:{fail}")
        self.idx_stat.setText(f"✅ AI 分析完成  成功:{ok}  失败:{fail}")
        self._refresh_db_table()
        self._reload_stats()

    def _on_reanalyze_err(self, msg: str):
        self._set_busy(False)
        self.db_pbar.setVisible(False)
        self.lbl_db_pbar_status.setVisible(False)
        self.btn_stop_reanalyze.setEnabled(False)
        self.log_box.append(f"\n❌ {msg}")
        self.show_error(f"进行 AI 分析出错：\n{msg}")

    def _open_diff_file_dir(self, index):
        if not index.isValid():
            return
        item = self.diff_table.item(index.row(), 1)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        rel_path = data.get("path", "")
        nas_root = getattr(self, "_nas_root", "")
        full_path = to_local_path(rel_path, nas_root)
        if index.column() == 2:
            self._play_file_by_path(full_path)
        else:
            self._open_dir_by_path(full_path)

    def _refresh_diff_table_from_db(self):
        self._refresh_db_table()

    def _play_file_by_path(self, full_path: str):
        if not os.path.isfile(full_path):
            self.show_warning(f"文件不存在或无法播放：\n{full_path}", "文件不存在")
            return
        try:
            open_path(full_path)
        except Exception as e:
            self.show_error(f"播放文件失败：\n{e}")

    def _open_dir_by_path(self, full_path: str):
        folder = os.path.dirname(full_path)
        if os.path.isdir(folder):
            open_path(folder)
        else:
            self.show_warning(f"目录不可访问：\n{folder}", "无法打开")

    def _parse_unc(self, path: str) -> tuple:
        """\\server\\share\\path → (share, relative_path)."""
        p = path.replace("\\", "/")
        p = p.lstrip("/")
        if p.startswith("192.168.111.17/"):
            p = p[len("192.168.111.17/"):]
        parts = p.split("/", 1)
        return (parts[0], parts[1] if len(parts) > 1 else "")

    def _open_db_file_dir(self, index):
        if not index.isValid():
            return
        item = self.db_table.item(index.row(), 0)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        rel_path = data.get("path", "")
        nas_root = getattr(self, "_nas_root", "")
        full_path = to_local_path(rel_path, nas_root)

        # 双击统一播放文件（避免 checkbox 列干扰 column index）
        self._play_file_by_path(full_path)

    def _on_select_all_changed(self, state):
        chk_state = Qt.Checked if state == Qt.Checked or state == 2 else Qt.Unchecked
        self.db_table.setUpdatesEnabled(False)
        for r in range(self.db_table.rowCount()):
            item = self.db_table.item(r, 0)
            if item:
                item.setCheckState(chk_state)
        self.db_table.setUpdatesEnabled(True)

    def _show_diff_table_context_menu(self, pos):
        item = self.diff_table.itemAt(pos)
        if not item:
            return
        row_idx = item.row()
        path_item = self.diff_table.item(row_idx, 1)
        if not path_item:
            return
        data = path_item.data(Qt.UserRole)
        if not data:
            return

        rel_path = data.get("path", "")
        nas_root = getattr(self, "_nas_root", "")
        full_path = to_local_path(rel_path, nas_root)

        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction, QGuiApplication

        menu = QMenu(self.parent_widget)
        act_play = QAction("▶ 播放文件", menu)
        act_play.triggered.connect(lambda: self._play_file_by_path(full_path))
        menu.addAction(act_play)
        act_open_dir = QAction("🗂 打开文件所在目录", menu)
        act_open_dir.triggered.connect(lambda: self._open_dir_by_path(full_path))
        menu.addAction(act_open_dir)
        menu.addSeparator()

        txt = item.text().strip()
        if txt:
            act_copy_val = QAction(f"📋 复制当前单元格: '{txt[:50]}'", menu)
            act_copy_val.triggered.connect(lambda: QGuiApplication.clipboard().setText(txt))
            menu.addAction(act_copy_val)
        fname = data.get("filename") or os.path.basename(full_path)
        if fname:
            act_copy_name = QAction("📋 复制文件名", menu)
            act_copy_name.triggered.connect(lambda: QGuiApplication.clipboard().setText(fname))
            menu.addAction(act_copy_name)
        if full_path:
            act_copy_path = QAction("📋 复制完整路径", menu)
            act_copy_path.triggered.connect(lambda: QGuiApplication.clipboard().setText(full_path))
            menu.addAction(act_copy_path)
        fhash = data.get("file_hash", "")
        if fhash and fhash != "—":
            act_copy_hash = QAction("📋 复制 Hash 值", menu)
            act_copy_hash.triggered.connect(lambda: QGuiApplication.clipboard().setText(fhash))
            menu.addAction(act_copy_hash)

        material_id = data.get("id")
        if material_id is not None:
            menu.addSeparator()
            act_delete_db = QAction("🗑 从数据库删除该条目", menu)
            act_delete_db.triggered.connect(lambda: self._delete_material_from_db(data))
            menu.addAction(act_delete_db)

        menu.exec_(self.diff_table.viewport().mapToGlobal(pos))

    def _show_table_context_menu(self, pos):
        item = self.db_table.itemAt(pos)
        if not item:
            return
        row_idx = item.row()
        row_item = self.db_table.item(row_idx, 0)
        if not row_item:
            return
        data = row_item.data(Qt.UserRole)
        if not data:
            return

        rel_path = data.get("path", "")
        nas_root = getattr(self, "_nas_root", "")
        full_path = to_local_path(rel_path, nas_root)

        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction, QGuiApplication

        menu = QMenu(self.parent_widget)
        act_play = QAction("▶ 播放文件", menu)
        act_play.triggered.connect(lambda: self._play_file_by_path(full_path))
        menu.addAction(act_play)
        act_open_dir = QAction("🗂 打开文件所在目录", menu)
        act_open_dir.triggered.connect(lambda: self._open_dir_by_path(full_path))
        menu.addAction(act_open_dir)
        menu.addSeparator()

        txt = item.text().strip()
        if txt:
            act_copy_val = QAction(f"📋 复制当前单元格: '{txt}'", menu)
            act_copy_val.triggered.connect(lambda: QGuiApplication.clipboard().setText(txt))
            menu.addAction(act_copy_val)
        fname = data.get("filename") or os.path.basename(full_path)
        if fname:
            act_copy_name = QAction("📋 复制文件名", menu)
            act_copy_name.triggered.connect(lambda: QGuiApplication.clipboard().setText(fname))
            menu.addAction(act_copy_name)
        if full_path:
            act_copy_path = QAction("📋 复制完整绝对路径", menu)
            act_copy_path.triggered.connect(lambda: QGuiApplication.clipboard().setText(full_path))
            menu.addAction(act_copy_path)
        fhash = data.get("file_hash", "")
        if fhash and fhash != "—":
            act_copy_hash = QAction("📋 复制 Hash 值", menu)
            act_copy_hash.triggered.connect(lambda: QGuiApplication.clipboard().setText(fhash))
            menu.addAction(act_copy_hash)

        material_id = data.get("id")
        if material_id is not None:
            menu.addSeparator()
            act_delete_db = QAction("🗑 从数据库删除该条目", menu)
            act_delete_db.triggered.connect(lambda: self._delete_material_from_db(data))
            menu.addAction(act_delete_db)

        menu.exec_(self.db_table.viewport().mapToGlobal(pos))

    def _delete_material_from_db(self, row_data: dict):
        try:
            material_id = int(row_data.get("id"))
        except Exception:
            self.show_warning("未找到素材 ID，无法删除数据库记录。")
            return

        fname = row_data.get("filename") or os.path.basename(row_data.get("path", "")) or f"ID={material_id}"
        if not self.confirm(
            f"确定从数据库删除该素材记录吗？\n\n文件: {fname}\nID: {material_id}\n\n仅删除数据库记录，不删除磁盘文件。",
            "确认删除"
        ):
            return

        try:
            from utils.material_clip_indexer import MaterialClipIndexer
            with MaterialClipIndexer(nas_root=getattr(self, "_nas_root", "")) as idx:
                idx.delete_material_by_id(material_id)
            self.log_box.append(f"🗑 已从数据库删除: {fname} (id={material_id})")
            self._refresh_db_table()
        except Exception as e:
            self.show_error(f"删除数据库记录失败：\n{e}")
