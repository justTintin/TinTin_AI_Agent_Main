#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电商智能体矩阵 · License 签发/验证工具

独立可拷贝，不依赖工程路径。给开发者用于生成客户激活码。

用法:
    python license_tool.py machineid                   查看本机机器码
    python license_tool.py sign <机器码> [客户名] [天数]  签发激活码
    python license_tool.py verify <激活码.json>          验证激活码
    python license_tool.py genkey                       生成新密钥对

示例:
    python license_tool.py sign 4fc34c57c40fa096 "客户A" 365
"""

import sys
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

# ═══════════════════════════════════════════════════════════
# 密钥（与主程序 license.py 相同）
# ═══════════════════════════════════════════════════════════

_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAiycgVREVLbYYuKpuutqg
2yiEb6tKAji6R0FSui+id7gH+P6vMpBnc866Hn/JSFwJwBvvU7XiuH+T93BSvFBd
RDwOjyWGYl6TMIAT92fuPcWCl04sgrM+fYP5LmGHzv493C7eupXs74JCLttlNo7T
SuL46B7AzuGWoq9FDTevQkukJyfWReFuYs4hbqF5circbqpvMT3quy4a3c9AIZJg
22kYLd+OA5OCfBVQi0jPYPUjZe6+IDiBjAPWr22iIOUZZJnoaJ9oTX7ChVHQ8OIE
zcM/B/jJGAEE4Qpp/+EXQvw5EU1psnE7S9EkjTI2p9/ElqZXWZOrjQ7IbzRLU34z
qQIDAQAB
-----END PUBLIC KEY-----"""

# 私钥在首次运行 sign 时从同目录下的 license_private.pem 读取，也支持直接硬编码

_PRIVATE_KEY_PATH = Path(__file__).parent / "license_private.pem"


# ═══════════════════════════════════════════════════════════
# 功能
# ═══════════════════════════════════════════════════════════

def get_machine_id() -> str:
    """生成唯一机器码（与主程序一致）。"""
    parts = []
    mac = uuid.getnode()
    parts.append(f"mac:{mac:012x}")
    parts.append(f"host:{socket.gethostname()}")
    parts.append(f"cpu:{platform.processor() or ''}")
    try:
        result = subprocess.run(
            ["dmidecode", "-s", "system-uuid"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append(f"uuid:{result.stdout.strip()}")
    except Exception:
        pass
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_private_key() -> str:
    """加载私钥。优先从同目录文件读取，失败时提示。"""
    if _PRIVATE_KEY_PATH.exists():
        return _PRIVATE_KEY_PATH.read_text(encoding="utf-8")
    print(f"⚠️  未找到私钥文件: {_PRIVATE_KEY_PATH}")
    print(f"   请将 license_private.pem 放置到本脚本同目录下，或先运行 genkey 生成。")
    sys.exit(1)


def generate_keypair():
    """生成 RSA 2048 密钥对。"""
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    public_key = private_key.public_key()
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv_pem, pub_pem


def sign_license(private_key_pem: str, machine_id: str,
                 licensee: str = "", expiry_days: int = 365) -> str:
    """签发 License 激活码。"""
    priv_key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None, backend=default_backend()
    )
    issued = datetime.now().isoformat()
    expires = (datetime.now() + timedelta(days=expiry_days)).isoformat()
    payload = {
        "machine_id": machine_id,
        "licensee": licensee,
        "issued": issued,
        "expires": expires,
        "features": [],
        "version": "1.0",
    }
    payload_bytes = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    signature = priv_key.sign(
        payload_bytes,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return json.dumps({
        "payload": payload,
        "signature": signature.hex(),
    }, indent=2, ensure_ascii=False)


def verify_license(license_json_str: str):
    """验证 License 激活码。成功返回 LicenseInfo，失败抛异常。"""
    data = json.loads(license_json_str)
    payload_data = data.get("payload")
    signature_hex = data.get("signature")
    if not payload_data or not signature_hex:
        raise ValueError("激活码格式不完整")

    pub_key = serialization.load_pem_public_key(
        _PUBLIC_KEY_PEM.encode(), backend=default_backend()
    )
    payload_bytes = json.dumps(payload_data, sort_keys=True, ensure_ascii=False).encode()
    signature = bytes.fromhex(signature_hex)
    try:
        pub_key.verify(
            signature, payload_bytes,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
    except Exception:
        raise ValueError("签名校验失败（激活码无效或已被篡改）")

    expires = datetime.fromisoformat(payload_data["expires"])
    days_left = (expires - datetime.now()).days
    if days_left <= 0:
        raise ValueError(f"激活码已过期（{abs(days_left)} 天前）")

    return payload_data, days_left


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def print_usage():
    print(__doc__)


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "machineid":
        print(get_machine_id())

    elif cmd == "genkey":
        priv, pub = generate_keypair()
        priv_path = _PRIVATE_KEY_PATH
        priv_path.write_text(priv, encoding="utf-8")
        print(f"✅ 私钥已保存: {priv_path}")
        print()
        print("=" * 60)
        print("公钥（替换主程序 license.py 中的 _PUBLIC_KEY_PEM）：")
        print(pub)
        print("=" * 60)
        print()
        print(f"⚠️  请将以上公钥同步更新到 studio/utils/license.py 的 _PUBLIC_KEY_PEM")
        print()

    elif cmd == "sign":
        if len(sys.argv) < 3:
            print("用法: python license_tool.py sign <机器码> [客户名] [天数]")
            sys.exit(1)
        machine_id = sys.argv[2]
        licensee = sys.argv[3] if len(sys.argv) > 3 else ""
        days = int(sys.argv[4]) if len(sys.argv) > 4 else 365
        priv_pem = load_private_key()
        result = sign_license(priv_pem, machine_id, licensee, days)
        print(result)

    elif cmd == "verify":
        if len(sys.argv) < 3:
            print("用法: python license_tool.py verify <激活码.json文件>")
            sys.exit(1)
        path = sys.argv[2]
        code = Path(path).read_text(encoding="utf-8") if Path(path).exists() else sys.argv[2]
        try:
            info, days = verify_license(code)
            print(f"✅ 激活码有效")
            print(f"   客户: {info.get('licensee', '未命名')}")
            print(f"   机器码: {info.get('machine_id', '')}")
            print(f"   有效期至: {info.get('expires', '')}")
            print(f"   剩余: {days} 天")
        except Exception as e:
            print(f"❌ 验证失败: {e}")
            sys.exit(1)

    else:
        print(f"未知命令: {cmd}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
