# type: ignore
"""MainWindow 的本地服务管理 mixin（VoxCPM / Ollama），从 gui_main 拆出；self 不变、行为一致。"""

from PySide6.QtWidgets import QMessageBox
from utils.logger_utils import log


class ServicesMixin:
    def load_voxcpm_config(self):
        # 纯远程模式：只从 ai_config 读取远程 TTS 配置回填到输入框
        if hasattr(self, 'ai_config'):
            self.vox_api_url_input.setText(self.ai_config.get("vox_api_url", "http://127.0.0.1:7861/v1/tts"))  # noqa: E501
            self.vox_timesteps_spin.setValue(self.ai_config.get("vox_timesteps", 20))
            self.vox_cfg_spin.setValue(self.ai_config.get("vox_cfg", 2.0))

    def _save_voxcpm_config_silent(self):
        try:
            if hasattr(self, "ai_config"):
                # 关键：先从所有 UI 收集最新值，避免保存时用过期内存值覆盖其它字段
                # （否则会把它Tab的旧地址写回文件，例如 comfyui_addr 被重置为旧值）
                if hasattr(self, "_collect_all_config_from_ui"):
                    self._collect_all_config_from_ui()
                else:
                    self.ai_config["vox_api_url"] = self.vox_api_url_input.text().strip()  # noqa: E501
                    self.ai_config["vox_source"] = "remote"  # 纯远程
                    self.ai_config["vox_mode"] = "api"       # 纯 API 调用
                    self.ai_config["vox_timesteps"] = self.vox_timesteps_spin.value()
                    self.ai_config["vox_cfg"] = self.vox_cfg_spin.value()
                try:
                    from utils import config_manager as _cm
                    _cm.save_ai_config(self.ai_config)
                except OSError as e:
                    log.error(f"保存声音克隆参数到 ai_config 失败: {e}")
            return True
        except Exception as e:  # 配置保存涉及文件 I/O 等多类异常
            log.error(f"静默保存 VoxCPM 配置失败: {e}")
            return False

    def save_voxcpm_config(self):
        if self._save_voxcpm_config_silent():
            QMessageBox.information(self, "提示", "VoxCPM 配置参数保存成功！")
            self.refresh_llm_page_status()
        else:
            QMessageBox.critical(self, "错误", "保存 VoxCPM 配置失败，请检查文件权限。")

    def _ollama_refresh_status(self):
        from utils.thread_worker import TaskWorker as Worker
        # 后台线程探测（resilient_get 自带 3 次重试 + 指数退避，
        # 服务端异常时可能耗时数十秒，绝不能阻塞 GUI 线程）
        if getattr(self, "_ollama_probe_worker", None) and self._ollama_probe_worker.isRunning():  # noqa: E501
            return

        def _probe():
            from utils.ollama_manager import OllamaManager
            mgr = OllamaManager.get()
            running = mgr.is_running()
            models = mgr.list_local_models() if running else []
            return running, models

        def _done(result):
            try:
                running, models = result or (False, [])
                if running:
                    self.ollama_status_lbl.setText("● 已连接（远程）")
                    self._set_ollama_status_state("green")
                else:
                    self.ollama_status_lbl.setText("● 连接失败")
                    self._set_ollama_status_state("red")
                    self.ollama_models_lbl.setText("请检查远程地址及网络")
            except Exception as e:  # 外部API调用（Ollama 状态探测）
                log.warning(f"[Ollama] 状态刷新失败: {e}")

        w = Worker(_probe)
        w.finished.connect(_done)
        self._ollama_probe_worker = w
        w.start()

    def _set_ollama_status_state(self, state):
        self.ollama_status_lbl.setProperty("state", state)
        self.ollama_status_lbl.style().unpolish(self.ollama_status_lbl)
        self.ollama_status_lbl.style().polish(self.ollama_status_lbl)
