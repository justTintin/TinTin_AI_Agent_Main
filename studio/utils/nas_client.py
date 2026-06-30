"""
NAS SMB 客户端 — 通过 SMB 协议直接访问 NAS 文件系统。

用法:
    from utils.nas_client import NASClient
    client = NASClient("//192.168.111.17", username="x", password="y")
    for e in client.scandir("Photos"):
        print(e["name"], e["is_dir"])
"""

from smbprotocol.connection import Connection
from smbprotocol.session import Session
from smbprotocol.tree import TreeConnect
from smbprotocol.open import (
    Open, ImpersonationLevel, FileAttributes, ShareAccess,
    CreateDisposition, CreateOptions, FilePipePrinterAccessMask,
)
from smbprotocol.file_info import FileInformationClass


class NASClient:
    def __init__(self, server: str = "", username: str = "", password: str = ""):
        self._server = server.lstrip("\\/")
        self._username = username
        self._password = password
        self._conn: Connection | None = None
        self._session: Session | None = None

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

    def connect(self):
        if self.is_connected():
            return
        self._conn = Connection(None, server_name=self._server, port=445)
        self._conn.connect()

        if self._username:
            self._session = Session(
                self._conn, username=self._username, password=self._password
            )
        else:
            self._session = Session(
                self._conn, username="guest", password="", require_encryption=False
            )
        self._session.connect()

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
