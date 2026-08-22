"""
在线更新检查器（骨架）。

【当前状态】地基已铺好，等更新服务器搭好后只需实现 TODO 标注的请求部分。
不实现下载/打补丁——那是 apply_update/download_patch 的职责，待服务器就绪后开发。

服务器端 API 约定（供搭建服务器时参考）：
  GET {update_url}/version.json
    返回: {"version": "x.y.z", "channel": "stable", "manifest_url": "...", "release_notes": "..."}  # noqa: E501
  GET {update_url}/manifest-{version}.json
    返回: {"version": "...", "files": [{"rel", "sha256", "size"}]}
    客户端比对本地 manifest 与服务器 manifest 的文件 sha256，
    只下载变化的文件（文件级增量），删除多余文件，实现更新。

用法：
    from utils.update_checker import check_update
    result = check_update()
    if result["available"]:
        print(f"发现新版本 {result['latest_version']}")
"""
import json
import os
from datetime import datetime

from config.paths import UPDATE_CONFIG_FILE
from version import __version__

from utils.logger_utils import log


def get_local_version() -> str:
    """返回本地程序版本号。"""
    return __version__


def load_update_config() -> dict:
    """读取更新配置。文件不存在时返回默认配置。"""
    defaults = {
        "update_url": "",
        "channel": "stable",
        "check_on_startup": False,
        "last_check": None,
    }
    try:
        if os.path.isfile(UPDATE_CONFIG_FILE):
            with open(UPDATE_CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            defaults.update(cfg)
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


def save_update_config(cfg: dict):
    """保存更新配置到 CONFIG_DIR（frozen 模式下为可写部署目录）。"""
    try:
        os.makedirs(os.path.dirname(UPDATE_CONFIG_FILE), exist_ok=True)
        with open(UPDATE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log.warning(f"保存更新配置失败: {e}")


def _compare_versions(local: str, remote: str) -> int:
    """比较 CalVer 混合版本号（主.次.修订.构建日期）。

    格式：X.Y.Z[.YYYYMMDD]，如 2.1.1.20260709。
    前3段按语义化比较；第4段(构建日期)作同语义版本的构建先后兜底。
    段数不同的版本（如旧的3段 2.1.1）缺日期段视为0。

    返回: 1=remote更新, 0=相同, -1=local更新。
    """
    try:
        def parse(v):
            parts = v.split(".")
            # 前3段：主.次.修订（不足补0）
            sem = [int(parts[i]) if i < len(parts) else 0 for i in range(3)]
            # 第4段：构建日期（缺失=0）
            build = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            return tuple(sem) + (build,)
        lp, rp = parse(local), parse(remote)
        if rp > lp:
            return 1
        if rp < lp:
            return -1
        return 0
    except (ValueError, TypeError):
        return 0


def check_update() -> dict:
    """检查是否有新版本。

    返回 dict:
      - available: bool   是否有可用更新
      - reason: str       不可用时的原因（update_url未配置/已是最新/请求失败）
      - local_version: str
      - latest_version: str|None   有新版本时为远程版本号
      - release_notes: str|None

    服务器未配置（update_url 为空）时，优雅返回 available=False，不报错。
    """
    local_ver = get_local_version()
    cfg = load_update_config()
    update_url = (cfg.get("update_url") or "").strip()

    # 更新最后检查时间
    cfg["last_check"] = datetime.now().isoformat()
    save_update_config(cfg)

    # update_url 未配置 —— 服务器还没搭好，静默返回
    if not update_url:
        return {
            "available": False,
            "reason": "update_url 未配置（更新服务器尚未启用）",
            "local_version": local_ver,
            "latest_version": None,
            "release_notes": None,
        }

    # ── TODO: 服务器就绪后实现以下请求逻辑 ──────────────────────────────
    # try:
    #     import requests
    #     resp = requests.get(f"{update_url}/version.json", timeout=10)
    #     resp.raise_for_status()
    #     info = resp.json()
    #     remote_ver = info.get("version", "")
    #     if _compare_versions(local_ver, remote_ver) == 1:
    #         return {
    #             "available": True,
    #             "reason": "",
    #             "local_version": local_ver,
    #             "latest_version": remote_ver,
    #             "release_notes": info.get("release_notes"),
    #         }
    #     return {
    #         "available": False,
    #         "reason": "已是最新版本",
    #         "local_version": local_ver,
    #         "latest_version": remote_ver,
    #         "release_notes": None,
    #     }
    # except Exception as e:
    #     log.warning(f"检查更新失败: {e}")
    #     return {
    #         "available": False,
    #         "reason": f"请求更新服务器失败: {e}",
    #         "local_version": local_ver,
    #         "latest_version": None,
    #         "release_notes": None,
    #     }
    # ── TODO END ────────────────────────────────────────────────────────

    # 当前（服务器未就绪）的占位返回
    log.info(f"更新检查：update_url={update_url} 已配置，但请求逻辑待服务器就绪后启用")
    return {
        "available": False,
        "reason": "更新服务器已配置但请求逻辑尚未启用（待服务器就绪）",
        "local_version": local_ver,
        "latest_version": None,
        "release_notes": None,
    }
