"""
硬件指纹 + License 许可证系统

- 机器码：MAC + 主机名 + CPU 信息 → SHA256
- License 文件：JSON 格式，RSA 签名防篡改
- 公钥内置在代码中，私钥由开发者保管用于签发
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
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend

# ── 密钥对（仅公钥嵌入代码，私钥由开发者离线保管）────────────────────────────
_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAiycgVREVLbYYuKpuutqg
2yiEb6tKAji6R0FSui+id7gH+P6vMpBnc866Hn/JSFwJwBvvU7XiuH+T93BSvFBd
RDwOjyWGYl6TMIAT92fuPcWCl04sgrM+fYP5LmGHzv493C7eupXs74JCLttlNo7T
SuL46B7AzuGWoq9FDTevQkukJyfWReFuYs4hbqF5circbqpvMT3quy4a3c9AIZJg
22kYLd+OA5OCfBVQi0jPYPUjZe6+IDiBjAPWr22iIOUZZJnoaJ9oTX7ChVHQ8OIE
zcM/B/jJGAEE4Qpp/+EXQvw5EU1psnE7S9EkjTI2p9/ElqZXWZOrjQ7IbzRLU34z
qQIDAQAB
-----END PUBLIC KEY-----"""

# ⚠️ 私钥备份: studio/config/license_private.pem（不要提交到 git）

_LICENSE_FILE = "license.dat"


def generate_keypair() -> tuple[str, str]:
    """生成 RSA 2048 密钥对（开发者一次性操作）。返回 (private_pem, public_pem)。"""
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    return private_pem, public_pem


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


# ── License 签发（开发者用）──────────────────────────────────────────────────

def sign_license(
    private_key_pem: str,
    machine_id: str,
    licensee: str = "",
    expiry_days: int = 365,
    features: list[str] | None = None,
) -> str:
    """用私钥签发 License 文件内容（JSON 字符串）。"""
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None, backend=default_backend()
    )

    issued = datetime.now().isoformat()
    expires = (datetime.now() + timedelta(days=expiry_days)).isoformat()

    payload = {
        "machine_id": machine_id,
        "licensee": licensee,
        "issued": issued,
        "expires": expires,
        "features": features or [],
        "version": "1.0",
    }

    # 签名
    payload_bytes = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    signature = private_key.sign(
        payload_bytes,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )

    license_data = {
        "payload": payload,
        "signature": signature.hex(),
    }

    return json.dumps(license_data, indent=2, ensure_ascii=False)


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
        license_path = Path(__file__).resolve().parent.parent / "config" / _LICENSE_FILE
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


# ── 密钥生成工具（开发者一次性运行）──────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "genkey":
        priv, pub = generate_keypair()
        print("=" * 60)
        print("私钥（妥善保管，用于签发 License）：")
        print(priv)
        print("=" * 60)
        print("公钥（替换代码中的 _PUBLIC_KEY_PEM）：")
        print(pub)
        print("=" * 60)

    elif len(sys.argv) > 1 and sys.argv[1] == "machineid":
        print(f"当前机器码: {get_machine_id()}")

    elif len(sys.argv) > 1 and sys.argv[1] == "sign":
        # 用法: python license.py sign <machine_id> [licensee] [days]
        # 私钥从文件读取
        key_path = os.path.join(os.path.dirname(__file__), "..", "config", "license_private.pem")
        if not os.path.exists(key_path):
            print("错误: 未找到私钥文件 config/license_private.pem")
            sys.exit(1)
        with open(key_path) as f:
            private_key = f.read()
        mid = sys.argv[2] if len(sys.argv) > 2 else get_machine_id()
        name = sys.argv[3] if len(sys.argv) > 3 else ""
        days = int(sys.argv[4]) if len(sys.argv) > 4 else 365
        lic = sign_license(private_key, mid, name, days)
        print(lic)
    else:
        print("用法:")
        print("  python license.py genkey        生成密钥对")
        print("  python license.py machineid     查看机器码")
        print("  python license.py sign <机器码> <客户名> <天数>  签发License")
