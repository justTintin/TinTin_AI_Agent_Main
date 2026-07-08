# -*- coding: utf-8 -*-
import os
import time
import logging
import threading
import queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from utils.material_clip_indexer import MaterialClipIndexer, VIDEO_EXTS, IMAGE_EXTS, to_relative_path

log = logging.getLogger(__name__)

class FolderWatchHandler(FileSystemEventHandler):
    def __init__(self, indexer: MaterialClipIndexer, event_queue: queue.Queue):
        super().__init__()
        self.indexer = indexer
        self.db = indexer._db
        self.event_queue = event_queue
        self.supported_exts = VIDEO_EXTS | IMAGE_EXTS

    def on_created(self, event):
        if event.is_directory:
            return
        ext = os.path.splitext(event.src_path)[1].lower()
        if ext in self.supported_exts:
            log.info(f"FileSystem Watcher [Created]: {event.src_path}")
            self.event_queue.put(("created", event.src_path))

    def on_modified(self, event):
        if event.is_directory:
            return
        ext = os.path.splitext(event.src_path)[1].lower()
        if ext in self.supported_exts:
            log.info(f"FileSystem Watcher [Modified]: {event.src_path}")
            self.event_queue.put(("modified", event.src_path))

    def on_deleted(self, event):
        if event.is_directory:
            return
        ext = os.path.splitext(event.src_path)[1].lower()
        if ext in self.supported_exts:
            log.info(f"FileSystem Watcher [Deleted]: {event.src_path}")
            self.event_queue.put(("deleted", event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return
        ext_src = os.path.splitext(event.src_path)[1].lower()
        ext_dest = os.path.splitext(event.dest_path)[1].lower()
        
        # Handle rename/move of media files
        if ext_src in self.supported_exts or ext_dest in self.supported_exts:
            log.info(f"FileSystem Watcher [Moved/Renamed]: {event.src_path} ➔ {event.dest_path}")
            self.event_queue.put(("moved", (event.src_path, event.dest_path)))


class FolderWatcherService:
    def __init__(self):
        self.observer = None
        self.indexer = None
        self.event_queue = queue.Queue()
        self.running = False
        self.worker_thread = None

    def start(self):
        if self.running:
            return
            
        try:
            self.indexer = MaterialClipIndexer()
        except Exception as e:
            log.error(f"FolderWatcher failed to initialize MaterialClipIndexer: {e}")
            return
            
        cfg = self.indexer.cfg
        # 收集所有要监听的本地路径：NAS 目录（index_directories）+ 本机目录（local_directories）
        watch_paths = []
        for d in cfg.get("index_directories", []):
            local_path = d["local_path"] if isinstance(d, dict) else str(d)
            if local_path:
                watch_paths.append(local_path)
        for d in cfg.get("local_directories", []):
            local_path = str(d)
            if local_path:
                watch_paths.append(local_path)
        if not watch_paths:
            log.warning("No directories configured for FolderWatcher.")
            return

        self.running = True
        self.observer = Observer()
        handler = FolderWatchHandler(self.indexer, self.event_queue)

        watch_count = 0
        for local_path in watch_paths:
            if os.path.isdir(local_path):
                try:
                    self.observer.schedule(handler, local_path, recursive=True)
                    log.info(f"FolderWatcher started watching: {local_path}")
                    watch_count += 1
                except Exception as e:
                    log.error(f"FolderWatcher failed to watch directory {local_path}: {e}")
            else:
                log.warning(f"Watcher configured directory not found: {local_path}")
                
        if watch_count == 0:
            log.warning("No valid directories were scheduled for watching.")
            self.running = False
            return
            
        self.observer.start()
        
        # Start event consumer worker thread
        self.worker_thread = threading.Thread(target=self._consume_events, daemon=True, name="folder-watcher-worker")
        self.worker_thread.start()
        log.info("FolderWatcher service started successfully.")

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.observer:
            self.observer.stop()
            self.observer.join()
        # Wake up worker thread to exit
        self.event_queue.put(("stop", None))
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        log.info("FolderWatcher service stopped.")

    def _consume_events(self):
        debounce_map = {} # path: (action, timestamp)
        
        while self.running:
            try:
                try:
                    action, path_data = self.event_queue.get(timeout=0.5)
                except queue.Empty:
                    action, path_data = None, None
                    
                if action == "stop":
                    break
                    
                now = time.time()
                
                # Check debounced files and execute them if they haven't changed in the last 2 seconds
                paths_to_process = []
                for p, (act, t) in list(debounce_map.items()):
                    if now - t >= 2.0:
                        paths_to_process.append((p, act))
                        del debounce_map[p]
                        
                for p, act in paths_to_process:
                    self._process_single_action(act, p)

                if action:
                    if action in ("created", "modified"):
                        debounce_map[path_data] = (action, now)
                    elif action == "deleted":
                        if path_data in debounce_map:
                            del debounce_map[path_data]
                        self._process_single_action("deleted", path_data)
                    elif action == "moved":
                        src, dest = path_data
                        if src in debounce_map:
                            del debounce_map[src]
                        self._process_single_action("moved", (src, dest))
            except Exception as e:
                log.error(f"Error in FolderWatcher worker thread loop: {e}")

    def _process_single_action(self, action: str, path_data):
        try:
            self.indexer._db._connect()
            
            if action in ("created", "modified"):
                if os.path.isfile(path_data):
                    log.info(f"FolderWatcher processing [{action}]: {path_data}")
                    self.indexer.index_file_meta(path_data, force=True)
                    
            elif action == "deleted":
                log.info(f"FolderWatcher processing [deleted]: {path_data}")
                self.indexer._db.delete_material_by_path(path_data)
                
            elif action == "moved":
                src, dest = path_data
                log.info(f"FolderWatcher processing [moved]: {src} ➔ {dest}")
                
                src_rel = to_relative_path(src, self.indexer.nas_root).replace('\\', '/').strip('/')
                
                file_hash = None
                with self.indexer._db._conn.cursor() as cur:
                    cur.execute("SELECT file_hash FROM materials WHERE path = %s", (src_rel,))
                    row = cur.fetchone()
                    if row:
                        file_hash = row[0]
                        
                if file_hash:
                    ext = os.path.splitext(dest)[1].lower()
                    media_type = "video" if ext in VIDEO_EXTS else "image"
                    
                    try:
                        stat = os.stat(dest)
                        size = stat.st_size
                        mtime = stat.st_mtime
                    except Exception:
                        size = None
                        mtime = None
                        
                    self.indexer._db.upsert_material(
                        file_hash=file_hash, path=dest,
                        media_type=media_type, filename=os.path.basename(dest),
                        duration_s=None, width=0, height=0,
                        file_size=size, mtime=mtime
                    )
                    self.indexer._db.delete_material_by_path(src)
                    log.info(f"FolderWatcher successfully moved database path metadata.")
                else:
                    if os.path.isfile(dest):
                        self.indexer.index_file_meta(dest, force=True)
            self.indexer._db._conn.commit()
        except Exception as e:
            log.error(f"FolderWatcher failed to process {action} for {path_data}: {e}")
            try:
                self.indexer._db._conn.rollback()
            except Exception:
                pass
