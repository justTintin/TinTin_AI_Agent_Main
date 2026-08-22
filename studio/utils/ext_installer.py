"""浏览器扩展持久化安装：打包 .crx + 注册表外部扩展登记（Chrome/Edge）。

流程（等价于 Eagle/Billfish 等桌面软件的本地安装方式）：
1. 用任一 Chromium 浏览器把扩展目录打包成 .crx（私钥固定，扩展 ID 恒定）
2. 由私钥公钥计算 32 位扩展 ID（SHA256(SPKI) 前 16 字节，半字节映射 a-p）
3. 写注册表 HKCU\\Software\\<Vendor>\\Extensions\\<id> 的 path/version
4. 用户下次启动浏览器时以其本人 Profile 持久安装（首次需确认启用）
"""
import contextlib
import hashlib
import json
import os
import subprocess
import winreg

# 浏览器注册表外部扩展路径。
# 注意：Google Chrome（Windows 稳定版）官方禁止启用非商店来源扩展，
# 注册表旁加载会被强制停用且无法手动开启，故仅 Edge 支持持久安装；
# Chrome 及其他浏览器走 --load-extension 开发者模式加载。
_BROWSER_EXT_REG = {
    "Microsoft Edge": r"Software\Microsoft\Edge\Extensions",
}


def supported_browser(browser_name: str) -> bool:
    """该浏览器是否支持注册表持久安装。"""
    return browser_name in _BROWSER_EXT_REG


def pack_crx(ext_dir: str, pem_path: str, packer_exe: str) -> str:
    """用浏览器把扩展目录打包为 .crx，返回 crx 路径。

    首次打包无私钥时浏览器自动生成 <ext_dir>.pem（务必保留，ID 由其决定）。
    """
    ext_dir = os.path.abspath(ext_dir)
    if not os.path.isfile(os.path.join(ext_dir, "manifest.json")):
        raise FileNotFoundError(f"扩展目录缺少 manifest.json: {ext_dir}")
    crx_path = ext_dir.rstrip("\\/") + ".crx"
    cmd = [packer_exe, f"--pack-extension={ext_dir}"]
    if os.path.isfile(pem_path):
        cmd.append(f"--pack-extension-key={pem_path}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if not os.path.isfile(crx_path):
        tail = ((r.stderr or "") + (r.stdout or "")).strip()
        raise RuntimeError(f"打包 crx 失败: {tail[-300:] or '未知错误'}")
    return crx_path


def compute_extension_id(pem_path: str) -> str:
    """由打包私钥的公钥计算 32 位扩展 ID。"""
    from cryptography.hazmat.primitives import serialization

    with open(pem_path, "rb") as f:
        pem = f.read()
    key = serialization.load_pem_private_key(pem, password=None)
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(spki).digest()[:16]
    return "".join(chr(ord("a") + (b >> 4)) + chr(ord("a") + (b & 0x0F)) for b in digest)  # noqa: E501


def read_manifest_version(ext_dir: str) -> str:
    try:
        with open(os.path.join(ext_dir, "manifest.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or "1.0.0")
    except (OSError, json.JSONDecodeError):
        return "1.0.0"


def register_external_extension(browser_name: str, ext_id: str, crx_path: str, version: str):  # noqa: E501
    """写注册表外部扩展项（HKCU），浏览器下次启动时持久安装。"""
    reg_path = _BROWSER_EXT_REG.get(browser_name)
    if not reg_path:
        raise ValueError(f"不支持持久安装的浏览器: {browser_name}")
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{reg_path}\{ext_id}")
    try:
        winreg.SetValueEx(key, "path", 0, winreg.REG_SZ, os.path.abspath(crx_path))
        winreg.SetValueEx(key, "version", 0, winreg.REG_SZ, version)
    finally:
        winreg.CloseKey(key)


def unregister_external_extension(browser_name: str, ext_id: str):
    """删除注册表外部扩展项（卸载）。"""
    reg_path = _BROWSER_EXT_REG.get(browser_name)
    if not reg_path:
        return
    with contextlib.suppress(OSError):
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{reg_path}\{ext_id}")
