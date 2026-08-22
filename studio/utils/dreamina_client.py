import os
import re
import shutil
import subprocess

from config.paths import get_bin

from utils.platform_utils import create_no_window_flag

DREAMINA_EXE = get_bin("dreamina")


def _strip_noise(text):
    lines = [ln for ln in (text or "").splitlines()
             if "版本文件缺失" not in ln and "重新运行curl" not in ln]
    return "\n".join(lines).strip()


def parse_kv(text):
    out = {}
    for ln in (text or "").splitlines():
        m = re.match(r"\s*([A-Za-z_][\w]*)\s*[:：]\s*(.+?)\s*$", ln)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2).strip()
    return out


class DreaminaClient:
    def __init__(self, exe_path=None):
        self.exe = exe_path or self._locate_exe()

    @staticmethod
    def _locate_exe():
        if os.path.isfile(DREAMINA_EXE):
            return DREAMINA_EXE
        found = shutil.which("dreamina")
        if not found:
            found = shutil.which("dreamina.exe")
        return found or DREAMINA_EXE

    def is_installed(self):
        return os.path.isfile(self.exe) or shutil.which(os.path.basename(self.exe)) is not None  # noqa: E501

    def run(self, args, timeout=120):
        if not self.is_installed():
            return -1, f"未找到 dreamina 可执行文件，请先安装到 {DREAMINA_EXE} 或加入 PATH。"
        cmd = [self.exe] + list(args)
        kwargs = {"capture_output": True, "text": True, "encoding": "utf-8",
                      "errors": "replace", "timeout": timeout}
        kwargs["creationflags"] = create_no_window_flag()
        try:
            r = subprocess.run(cmd, **kwargs)
            out = _strip_noise((r.stdout or "") + ("\n" + r.stderr if r.stderr else ""))
            return r.returncode, out
        except subprocess.TimeoutExpired:
            return -1, "命令超时。"
        except (OSError, subprocess.SubprocessError) as e:
            return -1, str(e)

    def login_headless(self, timeout=40):
        code, out = self.run(["login", "--headless"], timeout=timeout)
        kv = parse_kv(out)
        if kv.get("device_code") and kv.get("verification_uri"):
            return True, kv
        return False, out or "发起登录失败。"

    def checklogin(self, device_code, poll=30):
        code, out = self.run(
            ["login", "checklogin", f"--device_code={device_code}", f"--poll={poll}"],
            timeout=poll + 15,
        )
        ok = ("[DREAMINA:LOGIN_SUCCESS]" in out or "[DREAMINA:LOGIN_REUSED]" in out
              or (code == 0 and "登录成功" in out))
        return ok, out

    def is_logged_in(self):
        code, out = self.run(["user_credit"], timeout=30)

        import json as _json
        try:
            data = _json.loads(out)
            if isinstance(data, dict):
                credit_val = data.get("total_credit") or data.get("balance") or data.get("credit")  # noqa: E501
                vip_level = data.get("vip_level")
                if credit_val is not None:
                    credit_str = str(credit_val)
                    if vip_level:
                        credit_str += f" (VIP: {vip_level})"
                    return True, credit_str
        except _json.JSONDecodeError:
            pass

        kv = parse_kv(out)
        credit = kv.get("credit") or kv.get("balance") or ""
        logged = code == 0 and bool(out) and ("登录" not in out or bool(credit)) and "未登录" not in out  # noqa: E501
        if logged:
            return True, credit or out

        code_sess, out_sess = self.run(["session", "list"], timeout=30)
        if code_sess == 0 and out_sess and "未登录" not in out_sess and "login" not in out_sess.lower():  # noqa: E501
            return True, "合作及本地合作权限账号"

        return False, (credit or out)

    def user_credit(self):
        _code, out = self.run(["user_credit"], timeout=30)
        return out

    def logout(self):
        return self.run(["logout"], timeout=20)[1]

    def text2image(self, prompt, ratio="", resolution_type="", model_version="", poll=0, timeout=180):  # noqa: E501
        args = ["text2image", f"--prompt={prompt}"]
        if ratio:
            args.append(f"--ratio={ratio}")
        if resolution_type:
            args.append(f"--resolution_type={resolution_type}")
        if model_version:
            args.append(f"--model_version={model_version}")
        if poll:
            args.append(f"--poll={poll}")
        code, out = self.run(args, timeout=timeout)
        info = parse_kv(out)
        info["raw"] = out
        submit_id = info.get("submit_id", "")
        gen_status = info.get("gen_status", "")
        ok = bool(submit_id) and gen_status in ("querying", "success", "")
        if gen_status == "fail":
            ok = False
        return ok, info

    def query_result(self, submit_id, download_dir=None, timeout=120):
        args = ["query_result", f"--submit_id={submit_id}"]
        if download_dir:
            os.makedirs(download_dir, exist_ok=True)
            args.append(f"--download_dir={download_dir}")
        code, out = self.run(args, timeout=timeout)
        info = parse_kv(out)
        info["raw"] = out
        downloaded = []
        if download_dir and os.path.isdir(download_dir):
            for fn in sorted(os.listdir(download_dir)):
                downloaded.append(os.path.join(download_dir, fn))
        return info, downloaded
