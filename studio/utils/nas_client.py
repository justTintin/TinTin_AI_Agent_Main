"""
NAS SMB 客户端 — 通过 SMB 协议直接访问 NAS 文件系统。

用法:
    from utils.nas_client import NASClient
    client = NASClient("//192.168.111.17", username="x", password="y")
    for e in client.scandir("Photos"):
        print(e["name"], e["is_dir"])
"""

# smbprotocol 为可选重依赖（NAS 访问），缺失时不应阻断主程序启动。
# 这里不顶层 import，改在 _load_smb() 首次需要时延迟加载。
# 见 studio/gui/material_clip_page.py —— import 本模块不再触发 import smbprotocol。


def _load_smb():
    """延迟导入 smbprotocol 全部符号。缺失时抛 ModuleNotFoundError（含中文提示）。"""
    try:
        from smbprotocol.connection import Connection
        from smbprotocol.session import Session
        from smbprotocol.tree import TreeConnect
        from smbprotocol.open import (
            Open, ImpersonationLevel, FileAttributes, ShareAccess,
            CreateDisposition, CreateOptions, FilePipePrinterAccessMask,
        )
        from smbprotocol.file_info import FileInformationClass
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "缺少 NAS 访问依赖 smbprotocol，NAS 相关功能不可用。"
            "安装：pip install smbprotocol"
        ) from e
    return (Connection, Session, TreeConnect, Open, ImpersonationLevel,
            FileAttributes, ShareAccess, CreateDisposition, CreateOptions,
            FilePipePrinterAccessMask, FileInformationClass)


class NASClient:
    def __init__(self, server: str = "", username: str = "", password: str = ""):
        self._server = server.lstrip("\\/")
        self._username = username
        self._password = password
        self._conn = None   # smbprotocol.Connection | None（延迟导入）
        self._session = None  # smbprotocol.Session | None
        # 延迟加载的符号缓存
        self._smb = None

    @classmethod
    def from_config(cls, cfg: dict) -> "NASClient":
        nas_root = cfg.get("nas_root", "")
        if not nas_root:
            return cls()
        return cls(
            server=nas_root.lstrip("\\/"),
            username=cfg.get("nas_user", ""),
            password=cfg.get("nas_password", ""),
        )

    def is_connected(self) -> bool:
        return self._conn is not None

    def connect(self, timeout: float = 5.0):
        """连接 NAS，超时秒数内未连上则放弃（避免连不上时阻塞几十秒）。

        smbprotocol 的 Connection.connect()/Session.connect() 默认无超时，
        目标主机不可达时会阻塞 30-60 秒（SMB 重试）。这里用线程 + join(timeout)
        包装，保证调用方不会被长时间卡住。
        """
        if self.is_connected():
            return
        import threading
        # 首次连接时才加载 smbprotocol
        (Connection, Session, _TreeConnect, _Open, _Imp, _FA, _SA, _CD, _CO,
         _FPAM, _FIC) = self._ensure_smb()
        err: list = []
        def _do():
            try:
                conn = Connection(None, server_name=self._server, port=445)
                conn.connect()
                if self._username:
                    sess = Session(conn, username=self._username, password=self._password)
                else:
                    sess = Session(conn, username="guest", password="", require_encryption=False)
                sess.connect()
                self._conn = conn
                self._session = sess
            except Exception as e:
                err.append(e)
        t = threading.Thread(target=_do, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            # 超时：连接仍在后台跑，放弃这次连接
            raise TimeoutError(f"NAS 连接超时（{timeout}s），请检查 NAS 地址 {self._server} 是否可达")
        if err:
            raise err[0]
        if not self.is_connected():
            raise ConnectionError(f"NAS 连接失败：{self._server}")

    def _ensure_smb(self):
        """延迟加载并缓存 smbprotocol 符号，所有用到 SMB 的方法开头调用。"""
        if self._smb is None:
            self._smb = _load_smb()
        return self._smb

    def disconnect(self):
        try:
            if self._session:
                self._session.disconnect()
        except Exception:
            pass
        try:
            if self._conn:
                self._conn.disconnect()
        except Exception:
            pass
        self._conn = None
        self._session = None

    @staticmethod
    def _parse_path(path: str) -> tuple[str, str]:
        """'share/sub/dir' → ('share', 'sub/dir')"""
        path = path.replace("\\", "/").lstrip("/")
        if "/" in path:
            idx = path.index("/")
            return path[:idx], path[idx + 1:]
        return path, ""

    @staticmethod
    def _field_val(field):
        """Extract value from an SMB field object (BytesField/IntField/FlagField)."""
        return field.value if hasattr(field, "value") else field

    @staticmethod
    def _decode_name(raw) -> str:
        """Decode UTF-16LE filename bytes from SMB response."""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, bytes):
            try:
                return raw.decode("utf-16-le", errors="replace").rstrip("\x00")
            except Exception:
                return raw.hex()
        return str(raw)

    def scandir(self, path: str) -> list[dict]:
        self.connect()
        (_Connection, _Session, TreeConnect, Open, ImpersonationLevel,
         FileAttributes, _ShareAccess, _CreateDisposition, _CreateOptions,
         FilePipePrinterAccessMask, FileInformationClass) = self._ensure_smb()
        share, subdir = self._parse_path(path)

        tree = TreeConnect(self._session, f"\\\\{self._server}\\{share}")
        tree.connect()

        entries = []
        try:
            op = Open(tree, subdir or "")
            op.create(
                ImpersonationLevel.Impersonation,
                FilePipePrinterAccessMask.GENERIC_READ,
                FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
                ShareAccess.FILE_SHARE_READ,
                CreateDisposition.FILE_OPEN,
                CreateOptions.FILE_DIRECTORY_FILE,
            )

            try:
                results = op.query_directory(
                    "*", FileInformationClass.FILE_DIRECTORY_INFORMATION
                )
                for info in results:
                    name = self._decode_name(self._field_val(info["file_name"]))
                    if name in (".", ".."):
                        continue
                    attrs = self._field_val(info["file_attributes"])
                    is_dir = bool(attrs & FileAttributes.FILE_ATTRIBUTE_DIRECTORY)
                    sub = f"{subdir}/{name}".lstrip("/") if subdir else name
                    entries.append({
                        "name": name,
                        "is_dir": is_dir,
                        "size": self._field_val(info["end_of_file"]),
                        "mtime": self._field_val(info["last_write_time"]),
                        "full_path": f"{share}/{sub}",
                    })
            finally:
                try:
                    op.close(False)
                except Exception:
                    pass
        finally:
            tree.disconnect()

        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return entries

    def isdir(self, path: str) -> bool:
        self.connect()
        (_Connection, _Session, TreeConnect, Open, ImpersonationLevel,
         FileAttributes, ShareAccess, CreateDisposition, CreateOptions,
         FilePipePrinterAccessMask, _FIC) = self._ensure_smb()
        share, subdir = self._parse_path(path)
        tree = TreeConnect(self._session, f"\\\\{self._server}\\{share}")
        tree.connect()
        try:
            op = Open(tree, subdir or "")
            op.create(
                ImpersonationLevel.Impersonation,
                FilePipePrinterAccessMask.GENERIC_READ,
                FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
                ShareAccess.FILE_SHARE_READ,
                CreateDisposition.FILE_OPEN,
                CreateOptions.FILE_DIRECTORY_FILE,
            )
            try:
                op.close(False)
            except Exception:
                pass
            return True
        except Exception:
            return False
        finally:
            tree.disconnect()

    def open_file(self, path: str):
        """以只读方式打开 NAS 文件，返回类文件对象。"""
        self.connect()
        (_Connection, _Session, TreeConnect, Open, ImpersonationLevel,
         FileAttributes, ShareAccess, CreateDisposition, CreateOptions,
         FilePipePrinterAccessMask, _FIC) = self._ensure_smb()
        share, subdir = self._parse_path(path)
        tree = TreeConnect(self._session, f"\\\\{self._server}\\{share}")
        tree.connect()

        op = Open(tree, subdir)
        op.create(
            ImpersonationLevel.Impersonation,
            FilePipePrinterAccessMask.GENERIC_READ,
            FileAttributes.FILE_ATTRIBUTE_NORMAL,
            ShareAccess.FILE_SHARE_READ,
            CreateDisposition.FILE_OPEN,
            CreateOptions.FILE_NON_DIRECTORY_FILE,
        )

        file_size = op.end_of_file

        class _SMBFile:
            def __init__(self, o, t, s):
                self._o = o
                self._t = t
                self._offset = 0
                self._size = s

            def read(self, size=-1):
                if size < 0:
                    size = self._size - self._offset
                data = self._o.read(self._offset, size)
                self._offset += len(data)
                return data

            def seek(self, offset, whence=0):
                if whence == 0:
                    self._offset = offset
                elif whence == 1:
                    self._offset += offset
                elif whence == 2:
                    self._offset = self._size + offset

            def tell(self):
                return self._offset

            def close(self):
                try:
                    self._o.close(False)
                except Exception:
                    pass
                try:
                    self._t.disconnect()
                except Exception:
                    pass

        return _SMBFile(op, tree, file_size)

    def stat(self, path: str) -> dict | None:
        self.connect()
        (_Connection, _Session, TreeConnect, Open, ImpersonationLevel,
         FileAttributes, ShareAccess, CreateDisposition, CreateOptions,
         FilePipePrinterAccessMask, _FIC) = self._ensure_smb()
        share, subdir = self._parse_path(path)
        tree = TreeConnect(self._session, f"\\\\{self._server}\\{share}")
        tree.connect()
        try:
            op = Open(tree, subdir or "")
            op.create(
                ImpersonationLevel.Impersonation,
                FilePipePrinterAccessMask.GENERIC_READ,
                FileAttributes.FILE_ATTRIBUTE_NORMAL,
                ShareAccess.FILE_SHARE_READ,
                CreateDisposition.FILE_OPEN,
                CreateOptions.FILE_NON_DIRECTORY_FILE,
            )
            result = {
                "size": op.end_of_file,
                "mtime": op.last_write_time,
            }
            try:
                op.close(False)
            except Exception:
                pass
            return result
        except Exception:
            return None
        finally:
            tree.disconnect()

    def download_file(self, share: str, remote_path: str, local_path: str):
        """通过 SMB 下载文件到本地。"""
        self.connect()
        (_Connection, _Session, TreeConnect, Open, ImpersonationLevel,
         FileAttributes, ShareAccess, CreateDisposition, CreateOptions,
         FilePipePrinterAccessMask, _FIC) = self._ensure_smb()
        tree = TreeConnect(self._session, f"\\\\{self._server}\\{share}")
        tree.connect()
        try:
            op = Open(tree, remote_path)
            op.create(
                ImpersonationLevel.Impersonation,
                FilePipePrinterAccessMask.GENERIC_READ,
                FileAttributes.FILE_ATTRIBUTE_NORMAL,
                ShareAccess.FILE_SHARE_READ,
                CreateDisposition.FILE_OPEN,
                CreateOptions.FILE_NON_DIRECTORY_FILE,
            )
            try:
                offset = 0
                with open(local_path, "wb") as f:
                    while True:
                        data = op.read(offset, 1048576)  # 1MB chunks
                        if not data:
                            break
                        f.write(data)
                        offset += len(data)
            finally:
                try:
                    op.close(False)
                except Exception:
                    pass
        finally:
            tree.disconnect()
