import os
import subprocess
import time
import threading
import requests
from utils.logger_utils import log
from config.paths import PROJECT_ROOT, OLLAMA_BIN, get_bin
from utils.platform_utils import IS_WIN, create_no_window_flag

OLLAMA_MODELS  = os.path.join(PROJECT_ROOT, "assets", "ollama_models")
OLLAMA_HOST    = "127.0.0.1:11434"
OLLAMA_API     = f"http://{OLLAMA_HOST}"


def _read_ai_config() -> dict:
    """读取 ai_config.json；读不到返回空字典。"""
    try:
        from config.paths import AI_CONFIG_FILE
        import json
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def read_ollama_mode() -> str:
    """当前 Ollama 来源模式：'local'(内置进程) 或 'remote'(外部已运行)。默认 local。"""
    return (_read_ai_config().get("ollama_mode") or "local").strip()


def _read_ollama_api() -> str:
    """返回当前模式应使用的 Ollama API 基地址。

    - local: 固定 http://127.0.0.1:11434（内置进程）
    - remote: 读 ai_config['llm_vision_api_url']，缺省回退本地
    """
    if read_ollama_mode() == "remote":
        url = (_read_ai_config().get("llm_vision_api_url") or "").strip()
        if not url:
            return OLLAMA_API
        # 自动补 http:// 前缀
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url
        return url.rstrip("/")
    return OLLAMA_API


class OllamaManager:
    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def is_binary_present(self) -> bool:
        return os.path.isfile(OLLAMA_BIN)

    def is_running(self) -> bool:
        try:
            r = requests.get(f"{_read_ollama_api()}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def list_local_models(self) -> list[str]:
        try:
            r = requests.get(f"{_read_ollama_api()}/api/tags", timeout=5)
            if r.status_code == 200:
                return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
        return []

    def start(self) -> tuple[bool, str]:
        if not self.is_binary_present():
            return False, f"未找到 ollama 可执行文件，请将其放置到：\n{OLLAMA_BIN}"

        if self.is_running():
            log.info("Ollama 已在运行，跳过启动。")
            return True, "已在运行"

        log.info("正在初始化并后台启动内置 GPU 优化版 Ollama...")

        os.makedirs(OLLAMA_MODELS, exist_ok=True)

        ollama_log_path = os.path.join(PROJECT_ROOT, "ollama_run.log")

        env = os.environ.copy()
        env["OLLAMA_MODELS"]      = OLLAMA_MODELS
        env["OLLAMA_HOST"]        = OLLAMA_HOST

        runners_dir = os.path.join(os.path.dirname(OLLAMA_BIN), "lib", "ollama")
        env["OLLAMA_RUNNERS_DIR"] = runners_dir

        try:
            cuda_ver = 0.0
            out = subprocess.check_output(
                ["nvidia-smi"],
                stderr=subprocess.DEVNULL,
                creationflags=create_no_window_flag()
            ).decode(errors="ignore")
            import re
            m = re.search(r"CUDA.*Version:\s*(\d+\.\d+)", out)
            if m:
                cuda_ver = float(m.group(1))
                log.info(f"检测到系统 CUDA 版本: {cuda_ver}")
            else:
                log.info("未从 nvidia-smi 匹配到 CUDA Version 字段")

            if cuda_ver > 0.0:
                if cuda_ver >= 13.0 and os.path.isdir(os.path.join(runners_dir, "cuda_v13")):
                    env["OLLAMA_LLM_LIBRARY"] = "cuda_v13"
                    log.info("已强制设置 OLLAMA_LLM_LIBRARY = cuda_v13")
                elif cuda_ver >= 12.0 and os.path.isdir(os.path.join(runners_dir, "cuda_v12")):
                    env["OLLAMA_LLM_LIBRARY"] = "cuda_v12"
                    log.info("已强制设置 OLLAMA_LLM_LIBRARY = cuda_v12")
                else:
                    if os.path.isdir(os.path.join(runners_dir, "cuda_v13")):
                        env["OLLAMA_LLM_LIBRARY"] = "cuda_v13"
                        log.info("检测到 CUDA 但版本未完全匹配，降级强制设置 OLLAMA_LLM_LIBRARY = cuda_v13")
                    elif os.path.isdir(os.path.join(runners_dir, "cuda_v12")):
                        env["OLLAMA_LLM_LIBRARY"] = "cuda_v12"
                        log.info("检测到 CUDA 但版本未完全匹配，降级强制设置 OLLAMA_LLM_LIBRARY = cuda_v12")
        except Exception as e:
            log.warning(f"CUDA 检测与指定失败: {e}")

        num_parallel = 4
        try:
            from config.paths import AI_CONFIG_FILE
            import json
            if os.path.isfile(AI_CONFIG_FILE):
                with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                    ai_cfg = json.load(f)
                num_parallel = int(ai_cfg.get("ollama_num_parallel", 4))
        except Exception:
            pass
        env["OLLAMA_NUM_PARALLEL"] = str(num_parallel)
        env["OLLAMA_CONTEXT_LENGTH"] = "4096"
        env["OLLAMA_KEEP_ALIVE"] = "2m"   # 2 分钟空闲后自动卸载模型释放显存

        with self._lock:
            try:
                ollama_log = open(ollama_log_path, "w")
                self._proc = subprocess.Popen(
                    [OLLAMA_BIN, "serve"],
                    env=env,
                    stdout=ollama_log,
                    stderr=subprocess.STDOUT,
                    creationflags=create_no_window_flag(),
                )
                log.info(f"Ollama 进程已启动 PID={self._proc.pid}")
            except Exception as e:
                return False, f"启动失败: {e}"

        for i in range(120):
            if self.is_running():
                log.info("Ollama API 就绪")
                return True, "Ollama 启动成功"
            if i > 0 and i % 20 == 0:
                log.info(f"等待 Ollama API 就绪... 已等待 {i * 0.5:.0f} 秒")
            time.sleep(0.5)
        return False, f"Ollama 启动超时（60秒），请检查 {OLLAMA_BIN} 是否正常"

    def get_configured_model(self) -> str:
        """从 ai_config.json 读取当前配置的视觉模型名；读不到返回空串。"""
        try:
            from config.paths import AI_CONFIG_FILE
            import json
            if os.path.isfile(AI_CONFIG_FILE):
                with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                    ai_cfg = json.load(f)
                return str(ai_cfg.get("llm_vision_model", "") or "").strip()
        except Exception as e:
            log.warning(f"读取配置的视觉模型失败: {e}")
        return ""

    def warmup_model(self, model_name: str = "", timeout: int = 180) -> tuple[bool, str]:
        """把指定模型预加载进显存（触发冷加载），避免后续推理请求读超时。

        - model_name 为空时自动用 get_configured_model()；仍为空则跳过。
        - 用 Ollama 原生 /api/generate 接口（predict=1, 不流式）触发模型加载。
        - 长超时（默认 180s），可被后台线程调用；本方法不抛异常，返回 (ok, msg)。
        """
        if not model_name:
            model_name = self.get_configured_model()
        if not model_name:
            return False, "未配置视觉模型，跳过预热"

        if not self.is_running():
            return False, "Ollama 未运行，跳过预热"

        log.info(f"开始预热视觉模型「{model_name}」(timeout={timeout}s)...")
        try:
            res = requests.post(
                f"{_read_ollama_api()}/api/generate",
                json={"model": model_name, "prompt": "", "stream": False, "predict": 1},
                timeout=timeout,
            )
            if res.status_code == 200:
                log.info(f"视觉模型「{model_name}」预热完成")
                return True, "预热完成"
            else:
                msg = f"HTTP {res.status_code}"
                log.warning(f"视觉模型「{model_name}」预热返回非 200: {msg}")
                return False, msg
        except Exception as e:
            log.warning(f"视觉模型「{model_name}」预热失败: {e}")
            return False, str(e)[:80]

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None

        # 清理可能残留的 ollama 进程（仅在旧进程已正常终止时）
        if IS_WIN:
            for img in ["ollama.exe", "llama-server.exe"]:
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/IM", img],
                                   capture_output=True, timeout=10,
                                   creationflags=create_no_window_flag())
                except Exception:
                    pass
        else:
            try:
                subprocess.run(["pkill", "-x", "ollama"],
                               capture_output=True, timeout=2)
            except Exception:
                pass

        # 等待 GPU 显存释放（最多等 10 秒）
        try:
            import time as _time
            for _ in range(10):
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=create_no_window_flag())
                if r.returncode == 0 and r.stdout.strip().isdigit():
                    used_mb = int(r.stdout.strip())
                    # 显存使用降到 3GB 以下认为已释放（桌面 GUI 约占 1-2GB）
                    if used_mb < 3072:
                        break
                _time.sleep(1)
        except Exception:
            pass

        log.info("Ollama 进程已停止")

    def pull_model(self, model_name: str, progress_cb=None) -> tuple[bool, str]:
        if not self.is_running():
            ok, msg = self.start()
            if not ok:
                return False, msg

        try:
            import json
            resp = requests.post(
                f"{OLLAMA_API}/api/pull",
                json={"name": model_name, "stream": True},
                stream=True,
                timeout=600,
            )
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                status  = data.get("status", "")
                total   = data.get("total",   0)
                completed = data.get("completed", 0)
                pct = int(completed * 100 / total) if total > 0 else None
                if progress_cb:
                    progress_cb(status, pct)
                if data.get("error"):
                    return False, data["error"]
            return True, f"{model_name} 下载完成"
        except Exception as e:
            return False, str(e)

    def delete_model(self, model_name: str) -> tuple[bool, str]:
        try:
            r = requests.delete(
                f"{OLLAMA_API}/api/delete",
                json={"name": model_name},
                timeout=10,
            )
            if r.status_code in (200, 204):
                return True, f"{model_name} 已删除"
            return False, f"删除失败: HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    def get_version(self) -> str:
        try:
            out = subprocess.check_output(
                [OLLAMA_BIN, "--version"],
                stderr=subprocess.DEVNULL,
                creationflags=create_no_window_flag(),
                timeout=5,
            ).decode(errors="ignore")
            import re
            m = re.search(r"(\d+\.\d+[\.\d]*)", out)
            return m.group(1) if m else "unknown"
        except Exception:
            return "unknown"

    def runners_ok(self) -> bool:
        bin_dir = os.path.dirname(OLLAMA_BIN)
        suffix = ".exe" if IS_WIN else ""
        candidates = [
            os.path.join(bin_dir, f"llama-server{suffix}"),
            os.path.join(bin_dir, "lib", "ollama", f"llama-server{suffix}"),
        ]
        runners_root = os.path.join(bin_dir, "lib", "ollama")
        if os.path.isdir(runners_root):
            for sub in os.listdir(runners_root):
                if sub.startswith("cuda_") or sub == "vulkan":
                    candidates.append(
                        os.path.join(runners_root, sub, f"llama-server{suffix}")
                    )
        return any(os.path.isfile(p) for p in candidates)

    def download_runners(self, progress_cb=None) -> tuple[bool, str]:
        import tarfile, shutil

        version = self.get_version()
        if version == "unknown":
            return False, "无法读取 Ollama 版本，请确认二进制文件正常"

        bin_dir  = os.path.dirname(OLLAMA_BIN)

        # Linux: 新版用 tar.zst，旧版用 zip；Windows: 始终 zip
        formats = [("tar.zst", "tar.zst")] if not IS_WIN else []
        formats.append(("zip", "zip"))

        last_error = None
        for fmt_key, fmt_ext in formats:
            url = (
                "https://github.com/ollama/ollama/releases/download/"
                f"v{version}/ollama-{'windows' if IS_WIN else 'linux'}-amd64.{fmt_ext}"
            )
            log.info(f"尝试下载 Ollama 运行库 ({fmt_key}): {url}")
            if progress_cb:
                progress_cb(0, 0, f"连接中 ({fmt_key})…  v{version}")

            try:
                head = requests.head(url, timeout=(10, 10), allow_redirects=True)
                if head.status_code != 200:
                    last_error = f"{fmt_key}: HTTP {head.status_code}"
                    continue
                total = int(head.headers.get("content-length", 0))
            except Exception as e:
                last_error = f"{fmt_key}: {e}"
                continue

            pkg_path = os.path.join(bin_dir, f"_ollama_pkg.{fmt_ext}")
            CHUNK = 131072
            MAX_RETRIES = 5
            STALL_TIMEOUT = 30
            downloaded = 0
            retries    = 0

            try:
                with open(pkg_path, "ab") as f:
                    downloaded = os.path.getsize(pkg_path)
                    if downloaded > 0 and total and downloaded >= total:
                        pass
                    else:
                        while retries <= MAX_RETRIES:
                            headers = {}
                            if downloaded > 0:
                                headers["Range"] = f"bytes={downloaded}-"
                            try:
                                resp = requests.get(
                                    url, stream=True,
                                    headers=headers,
                                    timeout=(15, STALL_TIMEOUT),
                                    allow_redirects=True,
                                )
                                if resp.status_code not in (200, 206):
                                    last_error = f"{fmt_key}: HTTP {resp.status_code}"
                                    break
                                if not total:
                                    total = int(resp.headers.get("content-length", 0))
                                for chunk in resp.iter_content(chunk_size=CHUNK):
                                    if not chunk:
                                        continue
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if progress_cb:
                                        mb = downloaded / 1048576
                                        tb = total / 1048576 if total else 0
                                        label = (f"下载中… {mb:.1f} / {tb:.1f} MB"
                                                  if tb else f"下载中… {mb:.1f} MB")
                                        progress_cb(downloaded, total, label)
                                break
                            except (requests.exceptions.ReadTimeout,
                                    requests.exceptions.ChunkedEncodingError,
                                    requests.exceptions.ConnectionError) as e:
                                retries += 1
                                log.warning(f"下载中断 ({retries}/{MAX_RETRIES}): {e}")
                                if progress_cb:
                                    progress_cb(downloaded, total,
                                                f"连接中断，重试 {retries}/{MAX_RETRIES}…")
                                if retries > MAX_RETRIES:
                                    last_error = f"{fmt_key}: 多次中断"
                                    return False, f"下载多次中断，已保存 {downloaded//1048576} MB，可重新点击继续。"
                                time.sleep(2)
            except Exception as e:
                last_error = f"{fmt_key}: {e}"
                continue

            if not os.path.isfile(pkg_path) or os.path.getsize(pkg_path) < 1024:
                last_error = f"{fmt_key}: 文件不完整"
                continue

            if progress_cb:
                progress_cb(downloaded, total, "解压中…")
            try:
                extracted = 0
                if fmt_key == "zip":
                    import zipfile
                    with zipfile.ZipFile(pkg_path) as zf:
                        for name in zf.namelist():
                            if name.startswith("lib/") or name.startswith("lib\\"):
                                dest = os.path.join(bin_dir, name.replace("/", os.sep).replace("\\", os.sep))
                                if name.endswith("/"):
                                    os.makedirs(dest, exist_ok=True)
                                else:
                                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                                    with zf.open(name) as src, open(dest, "wb") as dst:
                                        shutil.copyfileobj(src, dst)
                                    extracted += 1
                else:
                    import zstandard as zstd
                    tar_path = pkg_path + ".tar"
                    try:
                        with open(pkg_path, "rb") as zst_f:
                            dctx = zstd.ZstdDecompressor()
                            with dctx.stream_reader(zst_f) as reader, open(tar_path, "wb") as tar_f:
                                shutil.copyfileobj(reader, tar_f)
                        with tarfile.open(tar_path, "r") as tf:
                            for member in tf.getmembers():
                                if member.name.startswith("lib/"):
                                    tf.extract(member, bin_dir, filter="data")
                                    extracted += 1
                    finally:
                        try:
                            os.remove(tar_path)
                        except Exception:
                            pass
            except Exception as e:
                last_error = f"{fmt_key} 解压: {e}"
                continue

            try:
                os.remove(pkg_path)
            except Exception:
                pass

            log.info(f"Ollama 运行库安装完成 ({fmt_key})，{extracted} 个文件 → {bin_dir}")
            if progress_cb:
                progress_cb(downloaded, total, "完成")
            return True, ""

        return False, (
            f"下载失败。\n"
            f"请手动下载 ollama-{'windows' if IS_WIN else 'linux'}-amd64.{{tar.zst|zip}} (v{version}) "
            f"并将其中 lib/ 目录解压到 studio/bin/{'win' if IS_WIN else 'linux'}/ 下。\n"
            f"({last_error})"
        )

        log.info(f"Ollama 运行库安装完成，{extracted} 个文件 → {bin_dir}")
        if progress_cb:
            progress_cb(downloaded, total, "完成")
        return True, f"运行库安装成功（{extracted} 个文件），Ollama 重启中…"
