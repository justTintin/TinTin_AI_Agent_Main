# -*- coding: utf-8 -*-
"""MainWindow 的账号/登录管理 mixin，从 gui_main 拆出；self 不变、行为一致。"""

import subprocess
import time
import sys
import os
from config.paths import (
    PROJECT_ROOT, RUNTIME_DIR, LOG_DIR, TMP_DIR, COOKIES_DIR,
    ACCOUNTS_DIR, PW_BROWSERS_DIR, WORKSPACE_ROOT
)
import threading
import uuid
import configparser
from ui import gui_styles
from gui.transcription_page import TranscriptionToolPage
from gui.env_config_page import EnvConfigPage, EnvInstallWorker
from gui.subtitle_removal_page import SubtitleRemovalPage
from gui.live_clip_page import LiveClipPage
from gui.voice_clone_page import VoiceClonePage
from gui.voice_samples_page import VoiceSamplesPage
from gui.video_ocr_page import VideoOcrPage
from gui.image_folder_ocr_page import ImageFolderOcrPage
from utils.logger_utils import log, get_last_logs
from utils.account_manager import AccountManager
from core.creator_browser_controller import CreatorBrowserController
from utils.thread_worker import TaskWorker as Worker
from gui.threads import SystemMonitorThread, ComfyWSThread
from utils import comfyui_client as comfy
from gui.dialogs import LoginDialog, StartupSplash, CloseSplash, open_cef_browser, EditAccountDialog
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QLabel, QStackedWidget, 
                                 QFrame, QSizePolicy, QLineEdit, QTableWidget, 
                                 QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
                                 QScrollArea, QTextEdit, QDialog, QListWidget, 
                                 QListWidgetItem, QGridLayout, QFileDialog, 
                                 QProgressBar, QComboBox, QInputDialog, QSplitter,
                                 QAbstractItemView, QButtonGroup, QGroupBox, QListView,
                                 QSpinBox)
from PySide6.QtGui import QIcon, QFont, QPixmap
from PySide6.QtCore import Qt, QSize, QUrl, QThread, Signal, QTimer, QEvent
from PySide6.QtGui import QPalette, QColor
from PySide6.QtGui import QFont


from config.paths import CREATOR_CONTENT_MANAGE_URL


class AccountsMixin:
    def refresh_server_tasks(self):
        def fetch():
            try:
                log.info("Syncing tasks from ComfyUI backend")
                # 1. Fetch Queue（被动解析后端，不自动启动本地）
                q_res = comfy.get_queue(self.ai_config)
                if q_res is None:
                    log.error("Sync failed: 无可用 ComfyUI 后端")
                    return []
                running = q_res.get("queue_running", [])
                pending = q_res.get("queue_pending", [])

                # 2. Fetch History (last 10)
                h_res = comfy.get_history(self.ai_config) or {}

                tasks = []
                # Running
                for t in running:
                     tasks.append({"id": t[1], "status": "正在执行", "progress": 0})
                # Pending
                for t in pending:
                     tasks.append({"id": t[1], "status": "等待中", "progress": 0})
                # History
                hist_raw = list(h_res.items())
                hist_items = hist_raw[-15:] if hist_raw else []
                for pid, h_info in hist_items:
                     # Parse outputs
                     outputs = []
                     if h_info and 'outputs' in h_info:
                         for node_id, node_out in h_info['outputs'].items():
                             if 'images' in node_out:
                                 for img in node_out['images']:
                                     outputs.append({"filename": img['filename'], "type": img.get('type', 'output'), "node": node_id})
                             if 'gifs' in node_out:
                                 for gif in node_out['gifs']:
                                      outputs.append({"filename": gif['filename'], "type": gif.get('type', 'output'), "node": node_id})
                     
                     tasks.append({"id": pid, "status": "已完成", "progress": 100, "outputs": outputs})
                     
                log.info(f"Found {len(tasks)} tasks on server")
                return tasks
            except Exception as e:
                log.error(f"Sync failed: {e}")
                return []

        def on_done(tasks):
            if not tasks: return
            
            # Use a set to track which prompt IDs we've updated in the UI in this batch
            updated_pids = set()
            
            for t in tasks:
                pid = t['id']
                if 'outputs' in t:
                    self.task_outputs[pid] = t['outputs']

                if pid not in self.task_progress_bars:
                    self.add_task_to_list(pid, t['status'])
                
                # Update status/progress
                if pid in self.task_status_items:
                    self.task_status_items[pid].setText(t['status'])
                if pid in self.task_progress_bars:
                    self.task_progress_bars[pid].setValue(t.get('progress', 0))
                    
                # Enable preview/download if finished
                if t['status'] == "已完成":
                    self.update_task_actions(pid)

        self.worker = Worker(fetch)
        self.worker.finished.connect(on_done)
        self.worker.start()

    def update_system_default_login_status(self):
        cookie_path = os.path.join(PROJECT_ROOT, "douyin_cookies.txt")
        if os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0:
            self.lbl_default_login_status.setText("登录状态: ✅ 已登录 (Cookie 已同步并生效)")
            self.lbl_default_login_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #2ecc71;")
        else:
            self.lbl_default_login_status.setText("登录状态: ❌ 未登录 (抓取任务可能会受限)")
            self.lbl_default_login_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #e74c3c;")

    def refresh_accounts_list(self):
        # Clear existing grid
        while self.accounts_grid.count():
            item = self.accounts_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Reset row and column stretches
        for col in range(5):
            self.accounts_grid.setColumnStretch(col, 0)
        for row in range(self.accounts_grid.rowCount()):
            self.accounts_grid.setRowStretch(row, 0)
        
        accounts = self.account_manager.get_accounts()
        if not accounts:
            label = QLabel("暂无已登录账户，请点击右上角添加。")
            label.setStyleSheet("color: #7f8c8d; font-size: 16px;")
            self.accounts_grid.addWidget(label, 0, 0, Qt.AlignCenter)
            return

        for i, acc in enumerate(accounts):
            card = QFrame()
            card.setObjectName("card")
            card.setFixedSize(220, 320)
            card.setStyleSheet("""
                QFrame#card {
                    background-color: white;
                    border: 1px solid #e0e0e0;
                    border-radius: 12px;
                }
                QFrame#card:hover {
                    border: 1.5px solid #3498db;
                }
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 15, 15, 12)
            card_layout.setSpacing(6)
            card_layout.setAlignment(Qt.AlignCenter)
            
            avatar = QLabel()
            avatar.setFixedSize(64, 64)
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setStyleSheet("background-color: #f0f2f5; border-radius: 32px; border: 2px solid #fff;")
            
            if acc.get('avatar'):
                self.set_remote_image(acc['avatar'], avatar)
            else:
                avatar.setText("👤")
                avatar.setStyleSheet("font-size: 32px; color: #3498db; background-color: #f0f2f5; border-radius: 32px;")
            
            card_layout.addWidget(avatar)
            
            # Nickname and edit button row
            name_layout = QHBoxLayout()
            name_layout.setContentsMargins(0, 0, 0, 0)
            name_layout.setSpacing(5)
            name_layout.addStretch()
            
            name_label = QLabel(acc['nickname'])
            name_label.setStyleSheet("font-weight: bold; font-size: 15px; color: #2c3e50;")
            name_label.setWordWrap(True)
            name_label.setAlignment(Qt.AlignCenter)
            name_layout.addWidget(name_label)
            
            btn_edit = QPushButton("✏️")
            btn_edit.setFixedSize(20, 20)
            btn_edit.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    font-size: 11px;
                    color: #3b82f6;
                    padding: 0px;
                }
                QPushButton:hover {
                    color: #2563eb;
                }
            """)
            btn_edit.setCursor(Qt.PointingHandCursor)
            btn_edit.clicked.connect(lambda checked=False, a=acc: self.edit_account_info(a))
            name_layout.addWidget(btn_edit)
            name_layout.addStretch()
            card_layout.addLayout(name_layout)
            
            # UID label
            uid_label = QLabel(f"UID: {acc['uid'][:15]}...")
            uid_label.setStyleSheet("color: #95a5a6; font-size: 11px;")
            uid_label.setToolTip(acc['uid'])
            uid_label.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(uid_label)
            
            # Douyin ID label
            dy_id = acc.get('douyin_id', '')
            dy_id_text = f"抖音号: {dy_id}" if dy_id else "抖音号: 未设置"
            dy_id_label = QLabel(dy_id_text)
            dy_id_label.setStyleSheet("color: #7f8c8d; font-size: 11px;")
            dy_id_label.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(dy_id_label)
            
            # Remark label
            remark = acc.get('remark', '')
            remark_text = f"备注: {remark}" if remark else "备注: 暂无"
            remark_label = QLabel(remark_text)
            remark_label.setStyleSheet("color: #7f8c8d; font-size: 11px;")
            remark_label.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(remark_label)
            
            card_layout.addStretch()
            
            # Button to open independent browser
            btn_open_browser = QPushButton("🌐 打开独立浏览器")
            btn_open_browser.setStyleSheet("""
                QPushButton {
                    background-color: #3498db;
                    color: white;
                    border-radius: 6px;
                    padding: 6px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #2980b9;
                }
            """)
            btn_open_browser.setCursor(Qt.PointingHandCursor)
            btn_open_browser.clicked.connect(lambda checked=False, a=acc: self.open_account_browser(a))
            card_layout.addWidget(btn_open_browser)

            btn_sync_cookie = QPushButton("🍪 同步 Cookie")
            btn_sync_cookie.setStyleSheet("""
                QPushButton {
                    background-color: #f3f4f6;
                    color: #374151;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    padding: 5px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #e5e7eb;
                }
            """)
            btn_sync_cookie.setCursor(Qt.PointingHandCursor)
            btn_sync_cookie.clicked.connect(lambda checked=False, a=acc: self.sync_account_cookie(a))
            card_layout.addWidget(btn_sync_cookie)
            
            # Action buttons row
            actions_layout = QHBoxLayout()

            btn_close_browser = QPushButton("⏹ 关闭浏览器")
            btn_close_browser.setStyleSheet("color: #6b7280; border: none; font-size: 11px; padding: 0px;")
            btn_close_browser.setCursor(Qt.PointingHandCursor)
            btn_close_browser.clicked.connect(lambda checked=False, a=acc: self.close_account_browser(a))
            actions_layout.addWidget(btn_close_browser)
            
            btn_exit = QPushButton("🗑️ 退出登录")
            btn_exit.setStyleSheet("color: #e74c3c; border: none; font-size: 11px; padding: 0px;")
            btn_exit.setCursor(Qt.PointingHandCursor)
            btn_exit.clicked.connect(lambda checked=False, u=acc['uid']: self.remove_account(u))
            actions_layout.addWidget(btn_exit)
            
            card_layout.addLayout(actions_layout)
            
            self.accounts_grid.addWidget(card, i // 4, i % 4)

        # Add a stretch column and row to force left-top alignment
        self.accounts_grid.setColumnStretch(4, 1)
        self.accounts_grid.setRowStretch((len(accounts) - 1) // 4 + 1, 1)

    def edit_account_info(self, acc):
        nickname = acc.get('nickname', '')
        douyin_id = acc.get('douyin_id', '')
        remark = acc.get('remark', '')
        uid = acc.get('uid')
        
        dialog = EditAccountDialog(nickname, douyin_id, remark, self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.account_manager.update_account_info(
                uid=uid,
                nickname=data['nickname'],
                remark=data['remark'],
                douyin_id=data['douyin_id']
            )
            self.refresh_accounts_list()

    def trigger_add_account(self):
        self.login_dialog = LoginDialog(
            playwright_profile_path=self.playwright_profile_path,
            browsers_path=PW_BROWSERS_DIR,
            parent=self
        )
        self.login_dialog.setAttribute(Qt.WA_DeleteOnClose)
        self.login_dialog.login_successful.connect(self.on_login_finished)
        self.login_dialog.exec()

    def close_account_browser(self, account):
        profile_id = account.get("profile_id")
        if not profile_id:
            return
        controller = self.account_pw_controllers.get(profile_id)
        if controller:
            controller.stop()
            self.account_pw_controllers.pop(profile_id, None)

    def sync_account_cookie(self, account):
        profile_id = account.get("profile_id")
        if not profile_id:
            QMessageBox.warning(self, "错误", "该账户缺少 profile_id，无法同步 Cookie。")
            return

        controller = self.account_pw_controllers.get(profile_id)
        if not controller or not controller.is_running():
            QMessageBox.information(self, "提示", "请先打开该账户的独立浏览器并完成登录。")
            return

        cookies = controller.get_cookies()
        if not cookies:
            QMessageBox.warning(self, "提示", "未读取到 Cookie，请确认已在外部浏览器登录成功。")
            return

        jar = {}
        for c in cookies:
            domain = str(c.get("domain", "") or "")
            if "douyin.com" not in domain:
                continue
            name = c.get("name")
            value = c.get("value")
            if not name:
                continue
            if name not in jar:
                jar[name] = value if value is not None else ""

        cookie_str = "; ".join([f"{k}={v}" for k, v in jar.items()])
        if not cookie_str:
            QMessageBox.warning(self, "提示", "未筛选到可用的 douyin.com Cookie。")
            return

        self.account_manager.add_account(
            uid=account.get("uid", ""),
            nickname=account.get("nickname", ""),
            cookie_str=cookie_str,
            avatar_url=account.get("avatar"),
            profile_id=profile_id,
        )
        QMessageBox.information(self, "成功", "Cookie 已同步到该账户。")

    def on_login_finished(self, acc_info):
        try:
            log.info(f"on_login_finished called, acc_info: {acc_info}")
            
            # 1. Determine nickname
            nickname = acc_info.get('nickname')
            if not nickname or nickname.startswith("未命名_"):
                suggested = nickname if (nickname and not nickname.startswith("未命名_")) else ""
                nick, ok = QInputDialog.getText(self, "保存账户分身", "请输入账户备注名 (如: 大怪工作室):", text=suggested)
                if not ok or not nick.strip():
                    log.info("User cancelled account saving (no nickname).")
                    return
                nickname = nick.strip()

            # 2. Handle Staging to Permanent Profile Migration
            final_profile_id = acc_info['profile_id']
            
            if final_profile_id == "staging_new_account":
                import time
                import shutil
                # Generate a unique permanent ID
                new_profile_id = f"profile_{int(time.time())}"
                
                # Close the browser window completely before moving (signal is emitted before close)
                # Note: exec() is blocking, so we are currently in the signal handler 
                # which is called when self.accept() was called in LoginDialog.
                # The dialog is hidden but not yet destroyed.
                
                staging_path = os.path.join(self.playwright_profile_path, "accounts", "staging_new_account")
                final_path = os.path.join(self.playwright_profile_path, "accounts", new_profile_id)
                
                # Move the folder (Wait a bit for files to unlock)
                try:
                    # Clear any existing target just in case
                    if os.path.exists(final_path):
                        shutil.rmtree(final_path)
                    
                    # Try move (may need several attempts if files are still being flushed)
                    for i in range(5):
                        try:
                            if os.path.exists(staging_path):
                                shutil.move(staging_path, final_path)
                                log.info(f"Migrated staging profile to {new_profile_id}")
                                break
                        except Exception as e:
                            log.warning(f"Move attempt {i+1} failed: {e}")
                            time.sleep(0.5)
                    
                    final_profile_id = new_profile_id
                except Exception as e:
                    log.error(f"Critical error moving staging profile: {e}")
                    # If move failed, we'll keep using staging_new_account for this account 
                    # as a fallback, but that's not ideal for the next 'Add'.

            # 3. Update or add account to manager
            self.account_manager.add_account(
                uid=acc_info['uid'], 
                nickname=nickname, 
                profile_id=final_profile_id
            )
            self.refresh_accounts_list()
            QMessageBox.information(self, "成功", f"账户 {nickname} 分身已成功保存。")
        except Exception as e:
            log.error(f"Error in on_login_finished: {e}", exc_info=True)
            QMessageBox.critical(self, "保存失败", f"保存账户信息时发生错误: {e}")

    def remove_account(self, uid):
        reply = QMessageBox.question(self, "确认", "确定要退出该账户登录吗？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            profile_id = None
            try:
                for a in self.account_manager.get_accounts():
                    if a.get("uid") == uid:
                        profile_id = a.get("profile_id")
                        break
            except Exception:
                profile_id = None
            if profile_id and profile_id in self.account_pw_controllers:
                try:
                    self.account_pw_controllers[profile_id].stop()
                except Exception:
                    pass
                self.account_pw_controllers.pop(profile_id, None)
            self.account_manager.remove_account(uid)
            self.refresh_accounts_list()

    def show_account_detail(self, account):
        self.current_selected_account = account
        self.detail_nickname.setText(f"昵称: {account['nickname']}")
        self.detail_uid.setText(f"UID: {account['uid']}")
        
        # Load avatar in detail
        if account.get('avatar'):
            self.set_remote_image(account['avatar'], self.detail_avatar, size=(80, 80))
        else:
            self.detail_avatar.setText("👤")
            self.detail_avatar.setStyleSheet("font-size: 40px; color: #3498db; background-color: #f0f2f5; border-radius: 40px;")
            
        self.switch_page(10) # Account Detail is index 10
        self.refresh_account_videos(account)

    def refresh_account_videos(self, account):
        self.account_videos_table.setRowCount(0)
        log.info(f"正在获取账户 {account['nickname']} ({account['uid']}) 的视频数据...")
        
        from core.douyin_user_downloader import DouyinUserDownloader
        def fetch_videos():
            try:
                # Construct user URL if needed
                url = account.get('uid', '')
                if not url.startswith('http'):
                    url = f"https://www.douyin.com/user/{url}"
                
                log.info(f"Fetching videos for {account.get('nickname')} via {url}...")
                
                from core.douyin_user_downloader import DouyinUserDownloader
                downloader = DouyinUserDownloader(
                    user_url=url,
                    cookie_str=account.get('cookie', '')
                )
                videos = downloader.fetch_all_videos()[:100]
                return videos
            except Exception as e:
                log.error(f"Error in fetch_videos: {e}")
                raise e

        self.start_worker(fetch_videos, self.display_account_videos, self.on_account_refresh_error)

    def on_account_refresh_error(self, err):
        self.detail_refresh_btn.setEnabled(True)
        log.error(f"Refresh error: {err}")
        
        if "过期" in str(err) or "登录" in str(err) or "403" in str(err):
            msg = f"获取数据失败: {err}\n\n该账户可能已过期。建议返回“账户平台”点击该账户卡片下方的“重新登录”。"
            QMessageBox.warning(self, "登录已过期", msg)
        else:
            QMessageBox.warning(self, "获取失败", f"获取视频失败: {err}")

    def trigger_relogin(self, account=None):
        # account is passed when triggered from the grid list
        account = account or self.current_selected_account
        
        # Open login dialog
        dialog = LoginDialog(self)
        dialog.login_successful.connect(self.on_login_finished)
        
        msg = f"正在为账户 {account['nickname']} 重新登录。\n请在弹出的窗口中操作，并确保点击进入一次“个人主页”后再点击“我已完成登录”。"
        QMessageBox.information(self, "重新登录提示", msg)
        dialog.exec()

    def display_account_videos(self, videos):
        # Safety check if we already switched away or object is gone
        if not hasattr(self, 'account_videos_table'):
            return
            
        self.account_videos_table.setRowCount(0)
        self.detail_refresh_btn.setEnabled(True)
        
        account_name = self.current_selected_account.get('nickname', '未知') if hasattr(self, 'current_selected_account') and self.current_selected_account else '未知'
        
        if not videos:
            self.account_videos_table.insertRow(0)
            msg = QTableWidgetItem("未找到视频或获取失败，请检查登录状态是否过期并重新登录。")
            msg.setTextAlignment(Qt.AlignCenter)
            self.account_videos_table.setItem(0, 0, msg)
            self.account_videos_table.setSpan(0, 0, 1, 5)
            log.warning(f"No videos found for account {account_name}")
            return

        for row, v in enumerate(videos):
            self.account_videos_table.insertRow(row)
            self.account_videos_table.setItem(row, 0, QTableWidgetItem(v.get('desc', '无标题')))
            
            ctime = v.get('create_time', 0)
            time_str = time.strftime('%Y-%m-%d', time.localtime(ctime)) if ctime else "--"
            self.account_videos_table.setItem(row, 1, QTableWidgetItem(time_str))
            
            stats = v.get('statistics', {})
            self.account_videos_table.setItem(row, 2, QTableWidgetItem(str(stats.get('play_count', 0))))
            self.account_videos_table.setItem(row, 3, QTableWidgetItem(str(stats.get('digg_count', 0))))
            self.account_videos_table.setItem(row, 4, QTableWidgetItem(str(stats.get('comment_count', 0))))
        
        log.info(f"Account detail table populated with {len(videos)} videos")

    def open_account_browser(self, account):
        if not self.is_playwright_chromium_present():
            QMessageBox.information(self, "提示", "正在准备 Playwright Chromium 内核，请先完成内核安装。")
            self.ensure_playwright_chromium_ready()
            return

        profile_id = account.get("profile_id")
        if not profile_id:
            QMessageBox.warning(self, "错误", "该账户缺少 profile_id，无法打开独立浏览器。")
            return

        user_data_dir = os.path.join(self.playwright_profile_path, "accounts", profile_id)
        os.makedirs(user_data_dir, exist_ok=True)

        controller = self.account_pw_controllers.get(profile_id)
        if controller and self.is_pw_controller_usable(controller):
            controller.goto(CREATOR_CONTENT_MANAGE_URL)
            return
        if controller and not self.is_pw_controller_usable(controller):
            try:
                controller.stop()
            except Exception:
                pass
            self.account_pw_controllers.pop(profile_id, None)

        controller = CreatorBrowserController(
            user_data_dir=user_data_dir,
            browsers_path=PW_BROWSERS_DIR,
            headless=False,
        )
        self.account_pw_controllers[profile_id] = controller
        controller.start()
        QTimer.singleShot(300, lambda: controller.goto(CREATOR_CONTENT_MANAGE_URL))
        QMessageBox.information(self, "提示", f"已为账户「{account.get('nickname','')}」打开独立浏览器分身。\n请在弹出的 Chromium 窗口内扫码登录。\n登录完成后点击「同步 Cookie」。")
