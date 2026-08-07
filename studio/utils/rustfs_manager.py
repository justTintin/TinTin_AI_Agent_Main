# -*- coding: utf-8 -*-
"""
RustFS 对象存储管理器。

RustFS 完全兼容 S3 协议，官方推荐使用 boto3 SDK（需 s3v4 签名）。
配置从 ai_config.json 读写（rustfs_endpoint / access_key / secret_key / bucket）。

参考: https://docs.rustfs.com/developer/sdk/python.html
"""
import os
import json
import tempfile

from config.paths import AI_CONFIG_FILE
from utils.logger_utils import log

try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import ClientError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


# ─── 配置读写 ─────────────────────────────────────────────────────────────────

def _load_ai_config():
    try:
        with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ai_config(data):
    try:
        with open(AI_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        log.error(f"保存 ai_config 失败: {e}")
        return False


def get_rustfs_config():
    cfg = _load_ai_config()
    return {
        "endpoint":   cfg.get("rustfs_endpoint",   "http://X.X.X.X:9000"),
        "access_key": cfg.get("rustfs_access_key", "rustfsadmin"),
        "secret_key": cfg.get("rustfs_secret_key", "rustfssecret"),
        "bucket":     cfg.get("rustfs_bucket",     "materials"),
    }


def save_rustfs_config(endpoint, access_key, secret_key, bucket):
    cfg = _load_ai_config()
    cfg["rustfs_endpoint"]   = endpoint.strip()
    cfg["rustfs_access_key"] = access_key.strip()
    cfg["rustfs_secret_key"] = secret_key.strip()
    cfg["rustfs_bucket"]     = bucket.strip()
    return _save_ai_config(cfg)


# ─── 客户端工厂 ───────────────────────────────────────────────────────────────

def _build_client(bucket_override: str = None):
    """创建 boto3 S3 客户端（s3v4 签名，兼容 RustFS）。"""
    if not HAS_BOTO3:
        raise ImportError("boto3 库未安装，请执行：pip install boto3")
    cfg = get_rustfs_config()
    client = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},   # 私有部署必须用路径寻址
        ),
        region_name="us-east-1",   # RustFS 不校验 region
    )
    bucket = bucket_override or cfg["bucket"]
    return client, bucket


# ─── 存储桶操作 ───────────────────────────────────────────────────────────────

def test_connection():
    """测试连接，返回 (ok: bool, message: str)。"""
    try:
        client, _ = _build_client()
        resp = client.list_buckets()
        names = [b["Name"] for b in resp.get("Buckets", [])]
        return True, f"连接成功，共 {len(names)} 个存储桶：{', '.join(names) if names else '（无）'}"
    except ImportError as e:
        return False, str(e)
    except Exception as e:
        return False, f"连接失败：{e}"


def list_buckets():
    """列出所有存储桶，返回 (ok, names: list[str] | error_str)。"""
    try:
        client, _ = _build_client()
        resp = client.list_buckets()
        return True, [b["Name"] for b in resp.get("Buckets", [])]
    except Exception as e:
        return False, str(e)


def _ensure_bucket(client, bucket_name):
    """确保存储桶存在，不存在则创建。403 = 桶存在但无 HeadBucket 权，视为已存在。"""
    try:
        client.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket_name)
            log.info(f"已创建存储桶: {bucket_name}")
        elif code in ("403", "AccessDenied"):
            pass  # 桶存在，只是无 HeadBucket 权限
        else:
            raise


# ─── 对象列表 ─────────────────────────────────────────────────────────────────

def list_objects(prefix: str = "", bucket_override: str = None,
                 max_keys: int = 5000):
    """
    列出存储桶对象，使用 V1 API（ListObjects）。
    RustFS 对 ListObjectsV2 的 list-type=2 参数签名校验有兼容问题，V1 无此参数。
    返回 (ok, list[dict]) 或 (False, error_str)。
    每条 dict: {name, size, last_modified, ext}
    """
    try:
        client, bucket = _build_client(bucket_override)
        objs = []
        paginator = client.get_paginator("list_objects")   # V1，无 list-type=2
        kwargs = {"Bucket": bucket, "PaginationConfig": {"MaxItems": max_keys}}
        if prefix:
            kwargs["Prefix"] = prefix
        for page in paginator.paginate(**kwargs):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                ext = os.path.splitext(key)[1].lower()
                objs.append({
                    "name":          key,
                    "size":          obj.get("Size", 0),
                    "last_modified": str(obj.get("LastModified", "")),
                    "ext":           ext,
                })
        return True, objs
    except ClientError as e:
        return False, f"S3 错误：{e.response['Error']['Code']} — {e.response['Error']['Message']}"
    except Exception as e:
        return False, str(e)


# ─── 对象下载 / 预签名 ────────────────────────────────────────────────────────

def download_object(object_key: str, local_path: str = None,
                    bucket_override: str = None) -> tuple[bool, str]:
    """
    下载对象到本地文件。
    若 local_path 为 None，自动写入临时目录。
    返回 (ok, local_path | error_str)。
    """
    try:
        client, bucket = _build_client(bucket_override)
        if local_path is None:
            ext = os.path.splitext(object_key)[1] or ".bin"
            fd, local_path = tempfile.mkstemp(suffix=ext, prefix="rustfs_")
            os.close(fd)
        client.download_file(bucket, object_key, local_path)
        return True, local_path
    except Exception as e:
        return False, str(e)


def generate_presigned_url(object_key: str, expires_in: int = 3600,
                           bucket_override: str = None) -> tuple[bool, str]:
    """
    生成预签名 GET URL（默认 1 小时有效）。
    返回 (ok, url | error_str)。
    """
    try:
        client, bucket = _build_client(bucket_override)
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=expires_in,
        )
        return True, url
    except Exception as e:
        return False, str(e)


# ─── 单文件上传 ───────────────────────────────────────────────────────────────

def upload_file(local_path: str, object_key: str,
                bucket_override: str = None,
                progress_callback=None) -> tuple[bool, str]:
    """
    上传单个文件到对象存储。
    progress_callback(bytes_transferred) — 可选进度回调。
    返回 (ok, message)。
    """
    try:
        client, bucket = _build_client(bucket_override)
        _ensure_bucket(client, bucket)
        if progress_callback:
            size = os.path.getsize(local_path)
            client.upload_file(
                local_path, bucket, object_key,
                Callback=progress_callback,
            )
        else:
            client.upload_file(local_path, bucket, object_key)
        return True, f"上传成功: {object_key}"
    except Exception as e:
        return False, str(e)


# ─── 目录同步 ─────────────────────────────────────────────────────────────────

def sync_directory_to_rustfs(local_dir: str, remote_prefix: str = "",
                              progress_callback=None,
                              bucket_override: str = None,
                              all_files: bool = False):
    """
    将本地目录下的文件同步上传到 RustFS 存储桶。

    all_files=False 仅上传媒体文件（图片/视频/音频）；
    all_files=True  上传目录下所有文件。

    progress_callback(current, total, filename)。
    返回 (ok, message, synced, failed)。
    """
    if not HAS_BOTO3:
        return False, "boto3 库未安装，请执行：pip install boto3", 0, 0
    if not local_dir or not os.path.isdir(local_dir):
        return False, f"目录不存在或无法访问：{local_dir}", 0, 0

    try:
        client, bucket = _build_client(bucket_override)
        _ensure_bucket(client, bucket)
    except Exception as e:
        return False, f"连接对象存储失败：{e}", 0, 0

    if all_files:
        files = []
        for root, _, fnames in os.walk(local_dir):
            for fn in fnames:
                fp = os.path.join(root, fn)
                files.append({"path": fp, "name": fn})
    else:
                files = scan_directory(local_dir, recursive=True)

    total = len(files)
    if total == 0:
        return True, "目录中没有可同步的文件", 0, 0

    synced, failed, errors = 0, 0, []
    for i, f in enumerate(files):
        if progress_callback:
            progress_callback(i, total, f["name"])
        rel = os.path.relpath(f["path"], local_dir).replace("\\", "/")
        key = f"{remote_prefix}/{rel}".lstrip("/") if remote_prefix else rel
        try:
            client.upload_file(f["path"], bucket, key)
            synced += 1
        except Exception as e:
            failed += 1
            errors.append(f"{f['name']}: {e}")
            log.error(f"上传失败 {f['path']}: {e}")

    if progress_callback:
        progress_callback(total, total, "完成")

    msg = f"同步完成：成功 {synced} 个，失败 {failed} 个"
    if errors:
        msg += "\n\n失败详情（前 5 条）：\n" + "\n".join(errors[:5])
    return failed == 0, msg, synced, failed
