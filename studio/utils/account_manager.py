# -*- coding: utf-8 -*-
import json
import os
import time
from utils.logger_utils import log

class AccountManager:
    def __init__(self, base_dir=None):
        if base_dir is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            base_dir = os.path.join(project_root, "accounts")
        self.base_dir = base_dir
        self.config_file = os.path.join(self.base_dir, "accounts.json")
        self.sessions_dir = os.path.join(self.base_dir, "sessions")
        self.accounts = []
        self._ensure_dirs()
        self.load_accounts()

    def _ensure_dirs(self):
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)
        if not os.path.exists(self.sessions_dir):
            os.makedirs(self.sessions_dir)

    def load_accounts(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.accounts = json.load(f)
            except Exception as e:
                log.error(f"Failed to load accounts: {e}")
                self.accounts = []
        else:
            self.accounts = []

    def save_accounts(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.accounts, f, indent=4, ensure_ascii=False)
        except Exception as e:
            log.error(f"Failed to save accounts: {e}")

    def add_account(self, uid, nickname, cookie_str="", avatar_url=None, profile_id=None):
        # Check for duplicates or update
        for acc in self.accounts:
            if acc['uid'] == uid:
                acc['nickname'] = nickname
                if cookie_str: acc['cookie'] = cookie_str
                if avatar_url: acc['avatar'] = avatar_url
                if profile_id: acc['profile_id'] = profile_id
                self.save_accounts()
                return acc
        
        # profile_id is used for the dedicated browser storage path
        if not profile_id:
            profile_id = f"profile_{int(time.time())}"
            
        session_path = os.path.abspath(os.path.join(self.sessions_dir, profile_id))
        new_acc = {
            "uid": uid,
            "nickname": nickname,
            "cookie": cookie_str,
            "avatar": avatar_url,
            "profile_id": profile_id,
            "session_path": session_path,
            "added_time": time.time()
        }
        self.accounts.append(new_acc)
        self.save_accounts()
        return new_acc

    def get_accounts(self):
        return self.accounts

    def remove_account(self, uid):
        self.accounts = [a for a in self.accounts if a['uid'] != uid]
        self.save_accounts()
        # Note: We don't automatically delete the session folder to avoid data loss

    def update_account_info(self, uid, nickname=None, remark=None, douyin_id=None):
        for acc in self.accounts:
            if acc['uid'] == uid:
                if nickname is not None:
                    acc['nickname'] = nickname
                if remark is not None:
                    acc['remark'] = remark
                if douyin_id is not None:
                    acc['douyin_id'] = douyin_id
                self.save_accounts()
                return True
        return False
