"""
硬件指纹 + License 许可证系统（仅验证）

- 机器码：MAC + 主机名 + CPU 信息 → SHA256
- License 文件：JSON 格式，RSA 签名防篡改
- 公钥内置在代码中用于验证；私钥由开发者离线保管，不在此工程内

注意： 本模块只做"验证"，不做"签发"。签发逻辑已移至工程外的独立工具
   TinTin_License_Signer/sign_license.py（含私钥），严禁随客户端分发。
"""

import os
import json
import hashlib
import uuid
import socket
import platform
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

# config 目录由 paths.py 统一管理（支持源码模式与 frozen 打包模式）
from config.paths import CONFIG_DIR

# ── 公钥（嵌入代码用于验证；私钥由开发者离线保管，不在此工程内）──────────────
_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtGAXKhTWuqV6MT9CjrDB
bN5I9PMxX1NgInK0DG5MKANlA5rpGGijFL6COzqoHY/nh/Xi7vltb5cB1cQQGddd
2PVQPl8+Eo9V9LKKDoLTg0qntt6tpTW1OnC/bpLlO70X7hKpJCAF0fheBXPnUddd
jqzob37F8A/WC58x/OINN/ls2pw8+E4Kg5zN/riZvkbG87s5E+D5RWu/bcw5FboX
At+22itv+r8RPSmnJxtQL145hBv6qkD8iEDAN48VUMedr2OENjtoX6WRR7SZDHp7
PpThSj+jtINBajnPq+BxwE/uBDHJvXoMBb9vByZLwtZGZx9Yt1sklvvYcJYIEtIQ
hwIDAQAB
-----END PUBLIC KEY-----"""

_LICENSE_FILE = "license.dat"


# ── 机器码 ───────────────────────────────────────────────────────────────────

def get_machine_id() -> str:
    """生成唯一机器码（MAC + 主机名 + CPU + 主板）。"""
    parts = []

    # MAC 地址
    mac = uuid.getnode()
    parts.append(f"mac:{mac:012x}")

    # 主机名
    parts.append(f"host:{socket.gethostname()}")

    # CPU 信息
    cpu = platform.processor() or ""
    parts.append(f"cpu:{cpu}")

    # Linux: 主板序列号
    try:
        result = subprocess.run(
            ["dmidecode", "-s", "system-uuid"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append(f"uuid:{result.stdout.strip()}")
    except Exception:
        pass

    # 综合哈希
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── License 验证（运行时）─────────────────────────────────────────────────────

class LicenseError(Exception):
    pass


class LicenseInfo:
    def __init__(self, data: dict):
        self.machine_id: str = data.get("machine_id", "")
        self.licensee: str = data.get("licensee", "")
        self.issued: str = data.get("issued", "")
        self.expires: str = data.get("expires", "")
        self.features: list[str] = data.get("features", [])
        self.days_left: int = 0

    @property
    def is_expired(self) -> bool:
        return self.days_left <= 0

    @property
    def is_valid(self) -> bool:
        return not self.is_expired


def verify_license(license_json: str | None = None) -> LicenseInfo:
    """验证 License 文件，校验签名 + 机器码 + 有效期。失败抛 LicenseError。"""
    # 读取 License 文件
    if license_json is None:
        license_path = Path(CONFIG_DIR) / _LICENSE_FILE
        if not license_path.exists():
            raise LicenseError("未找到许可证文件，请将 license.dat 放入 studio/config/ 目录")

        try:
            license_json = license_path.read_text(encoding="utf-8")
        except Exception:
            raise LicenseError("许可证文件读取失败")

    # 解析 License
    try:
        license_data = json.loads(license_json)
    except json.JSONDecodeError:
        raise LicenseError("许可证文件格式错误")

    payload_data = license_data.get("payload")
    signature_hex = license_data.get("signature")

    if not payload_data or not signature_hex:
        raise LicenseError("许可证文件内容不完整")

    # 校验签名
    public_key = serialization.load_pem_public_key(
        _PUBLIC_KEY_PEM.encode(), backend=default_backend()
    )

    payload_bytes = json.dumps(payload_data, sort_keys=True, ensure_ascii=False).encode()
    signature = bytes.fromhex(signature_hex)

    try:
        public_key.verify(
            signature,
            payload_bytes,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
    except Exception:
        raise LicenseError("许可证签名校验失败（文件已被篡改）")

    # 校验机器码
    current_machine = get_machine_id()
    licensed_machine = payload_data.get("machine_id", "")

    if licensed_machine != current_machine:
        raise LicenseError(
            f"许可证机器码不匹配\n当前机器: {current_machine}\n授权机器: {licensed_machine}"
        )

    # 校验有效期
    try:
        expires = datetime.fromisoformat(payload_data.get("expires", ""))
        days_left = (expires - datetime.now()).days
    except (ValueError, TypeError):
        raise LicenseError("许可证有效期格式错误")

    if days_left <= 0:
        raise LicenseError(f"许可证已过期（{abs(days_left)} 天前）")

    # 构建返回信息
    info = LicenseInfo(payload_data)
    info.days_left = days_left
    return info


# ── 试用白名单 ────────────────────────────────────────────────────────────────

_TRIAL_WHITELIST_FILE = "trial_whitelist.json"
_ACTIVATION_CACHE_FILE = ".activation_cache"


def _get_whitelist_path() -> str:
    return os.path.join(CONFIG_DIR, _TRIAL_WHITELIST_FILE)


def check_trial_whitelist(machine_id: str | None = None) -> bool:
    """检查当前机器是否在试用白名单中。"""
    if machine_id is None:
        machine_id = get_machine_id()
    whitelist_path = _get_whitelist_path()
    try:
        if os.path.isfile(whitelist_path):
            with open(whitelist_path, encoding="utf-8") as f:
                data = json.load(f)
            allowed = set(data.get("machine_ids", []))
            return machine_id in allowed
    except Exception:
        pass
    return False


def verify_activation_code(code_text_raw: str) -> LicenseInfo | None:
    """验证用户输入的激活码（粘贴的 License JSON 字符串）。

    激活码由工程外的独立工具 TinTin_License_Signer/sign_license.py 签发，
    与 license.dat 格式一致。
    返回 LicenseInfo 表示验证通过，None 表示失败。
    """
    try:
        return verify_license(code_text_raw.strip())
    except LicenseError:
        return None


def save_activation_cache(info: LicenseInfo):
    """将激活信息缓存到本地文件，下次启动直接读取。"""
    cache_path = os.path.join(CONFIG_DIR, _ACTIVATION_CACHE_FILE)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({
                "machine_id": info.machine_id,
                "licensee": info.licensee,
                "expires": info.expires,
                "activated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_activation_cache() -> LicenseInfo | None:
    """读取本地的激活缓存。"""
    cache_path = os.path.join(CONFIG_DIR, _ACTIVATION_CACHE_FILE)
    try:
        if os.path.isfile(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            # 验证缓存中的机器码是否匹配当前设备
            current = get_machine_id()
            if data.get("machine_id") != current:
                return None
            # 检查有效期
            expires = datetime.fromisoformat(data["expires"])
            if expires <= datetime.now():
                return None
            return LicenseInfo({
                "machine_id": data["machine_id"],
                "licensee": data.get("licensee", ""),
                "expires": data["expires"],
                "features": [],
            })
    except Exception:
        pass
    return None


# ── CLI（仅查询机器码；签发已移至工程外工具 TinTin_License_Signer）──────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "machineid":
        print(f"当前机器码: {get_machine_id()}")
    else:
        print("用法:")
        print("  python license.py machineid     查看本机机器码")
        print()
        print("激活码签发请使用工程外的独立工具:")
        print("  D:\\Project\\TinTin_License_Signer\\sign_license.py")
