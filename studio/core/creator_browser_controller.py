import os
import re
import threading
import queue
from config.paths import PW_BROWSERS_DIR

_active_controllers = []
_active_controllers_lock = threading.Lock()


def close_all_active_browsers():
    with _active_controllers_lock:
        for controller in list(_active_controllers):
            try:
                if controller.is_running():
                    controller.stop()
            except Exception:
                pass
        _active_controllers.clear()


class CreatorBrowserController:
    def __init__(self, user_data_dir, browsers_path=None, headless=False):
        self.user_data_dir = user_data_dir
        self.browsers_path = browsers_path or PW_BROWSERS_DIR
        self.headless = headless

        self._stop_event = threading.Event()
        self._thread = None
        self._cmd_q = queue.Queue()
        self._resp_q = queue.Queue()

        self._lock = threading.Lock()
        self._status = "未启动"
        self._current_video_url = ""
        self._last_error = ""

        self._page = None
        self._context = None
        self._playwright = None

        with _active_controllers_lock:
            if self not in _active_controllers:
                _active_controllers.append(self)

    def start(self):
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        try:
            self._cmd_q.put_nowait(("stop",))
        except Exception:
            pass

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def goto(self, url):
        self._cmd_q.put(("goto", url))

    def click_category(self, category):
        self._cmd_q.put(("category", category))

    def get_cookies(self, timeout_ms=8000):
        token = os.urandom(8).hex()
        self._cmd_q.put(("get_cookies", token))
        try:
            kind, got_token, cookies = self._resp_q.get(timeout=timeout_ms / 1000.0)
            if kind == "get_cookies" and got_token == token:
                return cookies
        except Exception:
            return None
        return None

    def evaluate(self, js_code, timeout_ms=8000):
        token = os.urandom(8).hex()
        self._cmd_q.put(("evaluate", token, js_code))
        try:
            kind, got_token, result = self._resp_q.get(timeout=timeout_ms / 1000.0)
            if kind == "evaluate" and got_token == token:
                return result
        except Exception:
            return None
        return None


    def get_status(self):
        with self._lock:
            return self._status, self._current_video_url, self._last_error

    def _set_state(self, status=None, current_video_url=None, last_error=None):
        with self._lock:
            if status is not None:
                self._status = status
            if current_video_url is not None:
                self._current_video_url = current_video_url
            if last_error is not None:
                self._last_error = last_error

    def _extract_video_url(self, text):
        if not text:
            return ""
        m = re.search(r"/video/(\d+)", text)
        if m:
            return f"https://www.douyin.com/video/{m.group(1)}"
        for key in ["modal_id", "aweme_id", "video_id", "item_id"]:
            m = re.search(rf"[?&]{key}=(\d+)", text)
            if m:
                return f"https://www.douyin.com/video/{m.group(1)}"
        return ""

    def _maybe_update_from_text(self, text):
        url = self._extract_video_url(text)
        if not url:
            return
        _, cur, _ = self.get_status()
        if url != cur:
            self._set_state(current_video_url=url, status="已识别视频，可加入下载队列")

    def _run(self):
        os.makedirs(self.user_data_dir, exist_ok=True)
        os.makedirs(self.browsers_path, exist_ok=True)
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", self.browsers_path)

        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            self._set_state(status="启动失败：缺少 Playwright 依赖", last_error=str(e))
            return

        try:
            self._set_state(status="启动中...")
            with sync_playwright() as p:
                self._playwright = p
                self._context = p.chromium.launch_persistent_context(
                    self.user_data_dir,
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    locale="zh-CN",
                    viewport={"width": 1400, "height": 900},
                )
                pages = list(self._context.pages)
                self._page = pages[0] if pages else self._context.new_page()

                def on_close(_):
                    try:
                        self._set_state(status="浏览器窗口已关闭")
                    except Exception:
                        pass
                    try:
                        self._stop_event.set()
                    except Exception:
                        pass

                def on_request(req):
                    try:
                        self._maybe_update_from_text(req.url)
                    except Exception:
                        pass

                def on_nav(frame):
                    try:
                        self._maybe_update_from_text(frame.url)
                    except Exception:
                        pass

                self._page.on("request", on_request)
                self._page.on("framenavigated", on_nav)
                self._page.on("close", on_close)
                self._set_state(status="已启动（Playwright Chromium）")

                while not self._stop_event.is_set():
                    try:
                        if self._page and hasattr(self._page, "is_closed") and self._page.is_closed():
                            self._set_state(status="浏览器窗口已关闭")
                            break
                    except Exception:
                        pass

                    try:
                        cmd = self._cmd_q.get_nowait()
                    except queue.Empty:
                        cmd = None

                    if cmd:
                        if cmd[0] == "stop":
                            break
                        if cmd[0] == "goto":
                            url = cmd[1]
                            try:
                                self._set_state(status=f"打开页面：{url}")
                                self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
                                self._maybe_update_from_text(self._page.url)
                            except Exception as e:
                                self._set_state(status="打开页面失败", last_error=str(e))
                        if cmd[0] == "category":
                            category = cmd[1]
                            try:
                                self._set_state(status=f"切换分类：{category}")
                                self._page.evaluate(
                                    """(text) => {
                                        const nodes = Array.from(document.querySelectorAll('a,button,div,span'));
                                        const hit = nodes.find(n => (n.textContent || '').trim() === text);
                                        if (hit) { hit.click(); return true; }
                                        return false;
                                    }""",
                                    category,
                                )
                            except Exception as e:
                                self._set_state(status="切换分类失败", last_error=str(e))
                        if cmd[0] == "get_cookies":
                            token = cmd[1]
                            try:
                                cookies = self._context.cookies() if self._context else []
                                self._resp_q.put(("get_cookies", token, cookies))
                            except Exception as e:
                                self._resp_q.put(("get_cookies", token, []))
                                self._set_state(last_error=str(e))
                        if cmd[0] == "evaluate":
                            token = cmd[1]
                            js_code = cmd[2]
                            try:
                                result = self._page.evaluate(js_code) if self._page else None
                                self._resp_q.put(("evaluate", token, result))
                            except Exception as e:
                                self._resp_q.put(("evaluate", token, None))
                                self._set_state(last_error=str(e))


                    try:
                        self._page.wait_for_timeout(250)
                    except Exception as e:
                        self._set_state(status="浏览器窗口已关闭", last_error=str(e))
                        break

        except Exception as e:
            self._set_state(status="启动失败", last_error=str(e))
        finally:
            try:
                if self._context:
                    self._context.close()
            except Exception:
                pass
            self._set_state(status="已停止")
