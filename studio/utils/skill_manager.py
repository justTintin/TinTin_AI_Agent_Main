# -*- coding: utf-8 -*-
"""本地技能安装/管理。

技能 = 一个包含 SKILL.md 的目录或 zip 包，安装到 data/skills/<skill_id>/。
SKILL.md 支持 YAML 风格 frontmatter：

---
name: 文案风格改写
description: 按给定品牌风格改写商品文案
version: 1.0.0
author: TinTin
tags: [文案, 改写]
---
技能正文（LLM 指令，唤起时随消息发给智能体）。
"""
import json
import os
import re
import shutil
import tempfile
import zipfile

from config.paths import DATA_DIR

SKILLS_DIR = os.path.join(DATA_DIR, "skills")
SKILLS_INDEX_FILE = os.path.join(DATA_DIR, "skills_index.json")


def _machine_id() -> str:

    """当前机器码（技能登记归属，与服务端会话多租户隔离一致）。"""

    try:

        from utils.license import get_machine_id

        return get_machine_id() or ""

    except Exception:

        return ""





def _server_url() -> str:

    """服务端统一地址（与编排客户端一致）。"""

    from utils.scheduled_task_client import _server_url as _u

    return _u()





def register_skill(entry, timeout=8):

    """POST /skills → 登记客户端技能（executor=client_tool，服务端不执行，仅多端可见/编排可引用）。



    entry 为技能条目 dict（含 id/name/description/instruction/version）。

    成功返回 True；失败仅告警不抛出（本地技能不受服务端影响）。

    """

    try:

        from utils.http_client import http_post

        body = {

            "skill_id": (entry or {}).get("id"),

            "name": (entry or {}).get("name"),

            "description": (entry or {}).get("description"),

            "instruction": (entry or {}).get("instruction"),

            "machine_id": _machine_id(),

            "version": (entry or {}).get("version"),

        }

        r = http_post(f"{_server_url()}/skills", json=body, timeout=timeout)

        if r.status_code == 200:

            return True

        _log_warn(f"[技能] register_skill HTTP {r.status_code}: {r.text[:120]}")

    except Exception as e:

        _log_warn(f"[技能] register_skill 失败: {e}")

    return False





def unregister_skill(skill_id, timeout=8):

    """DELETE /skills/{skill_id} → 取消服务端登记。失败仅告警。"""

    try:

        from utils.http_client import http_delete

        r = http_delete(f"{_server_url()}/skills/{skill_id}", timeout=timeout)

        return r.status_code == 200

    except Exception as e:

        _log_warn(f"[技能] unregister_skill({skill_id}) 失败: {e}")

    return False





def server_skills(timeout=8):

    """GET /skills → 服务端已登记技能清单 [{skill_id, name, description, instruction, machine_id, version}]。



    失败/超时返回 None（调用方回退本地扫描）。

    """

    try:

        from utils.http_client import http_get

        r = http_get(f"{_server_url()}/skills", timeout=timeout)

        if r.status_code == 200:

            data = r.json()

            if isinstance(data, list):

                return data

            if isinstance(data, dict):

                return data.get("skills") or data.get("items") or []

    except Exception as e:

        _log_warn(f"[技能] server_skills 失败: {e}")

    return None





def _log_warn(msg):

    try:

        from utils.logger_utils import log

        log.warning(msg)

    except Exception:

        pass





def ensure_builtin_skills():

    """确保内置技能（studio/assets/skills/*）已安装并登记服务端。



    工作台加载时调用；每个内置技能目录含 SKILL.md，未安装则 install + register。

    """

    import glob

    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),

                        "assets", "skills")

    for md in sorted(glob.glob(os.path.join(base, "*", "SKILL.md"))):

        src_dir = os.path.dirname(md)

        try:

            meta = _parse_skill_dir(src_dir)

        except Exception as e:

            _log_warn(f"[技能] 内置技能解析失败 {src_dir}: {e}")

            continue

        sid = meta.get("id")

        installed = os.path.isdir(os.path.join(SKILLS_DIR, sid)) if sid else False

        if not installed:

            try:

                entry = install_skill(src_dir, overwrite=False)

            except Exception as e:

                _log_warn(f"[技能] 内置技能安装失败 {sid}: {e}")

                continue

            register_skill(entry)

        else:

            # 已安装：保证服务端登记存在（幂等）

            register_skill(meta)





def _slugify(text):
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", str(text or "").strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "skill"


def _split_frontmatter(raw):
    """返回 (meta_dict, body_text)。frontmatter 缺失时 meta 为空、body 为全文。"""
    text = (raw or "").lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text.strip()
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text.strip()
    meta = {}
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        if not key or not val:
            continue
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        elif val.lower() == "true":
            val = True
        elif val.lower() == "false":
            val = False
        meta[key] = val
    return meta, text[end + 4:].strip()


def _parse_skill_dir(skill_dir):
    """读取技能目录里的 SKILL.md，返回规范化技能条目。"""
    md_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(md_path):
        raise FileNotFoundError(f"技能目录缺少 SKILL.md: {skill_dir}")
    with open(md_path, "r", encoding="utf-8-sig") as f:
        raw = f.read()
    meta, body = _split_frontmatter(raw)
    name = str(meta.get("name") or os.path.basename(skill_dir.rstrip("\\/"))).strip()
    desc = str(meta.get("description") or "").strip()
    if not desc and body:
        desc = body.splitlines()[0].lstrip("#").strip()
    entry = {
        "id": str(meta.get("id") or _slugify(name)),
        "name": name,
        "description": desc,
        "version": str(meta.get("version") or "1.0.0"),
        "author": str(meta.get("author") or ""),
        "tags": meta.get("tags") or [],
        "instruction": body or raw.strip(),
        "path": os.path.abspath(skill_dir),
    }
    return entry


def _index_path():
    return SKILLS_INDEX_FILE


def _read_index():
    try:
        if os.path.isfile(_index_path()):
            with open(_index_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_index(index):
    os.makedirs(SKILLS_DIR, exist_ok=True)
    p = _index_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _safe_extract_zip(zip_path, dest):
    dest_abs = os.path.abspath(dest)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = os.path.abspath(os.path.join(dest_abs, info.filename))
            if not (target == dest_abs or target.startswith(dest_abs + os.sep)):
                raise RuntimeError("技能包包含非法路径，已拒绝安装")
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _find_skill_dir(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        if "SKILL.md" in filenames:
            return dirpath
    return None


def _copy_skill_dir(src, meta, overwrite):
    os.makedirs(SKILLS_DIR, exist_ok=True)
    skills_abs = os.path.abspath(SKILLS_DIR)
    dest_abs = os.path.abspath(os.path.join(SKILLS_DIR, meta["id"]))
    if not (dest_abs == skills_abs or dest_abs.startswith(skills_abs + os.sep)):
        raise RuntimeError("技能 id 非法，已拒绝安装")
    src_abs = os.path.abspath(src)
    if src_abs == dest_abs:
        return meta
    if os.path.exists(dest_abs):
        if not overwrite:
            raise FileExistsError(f"技能已存在: {meta['id']}")
        if os.path.isdir(dest_abs):
            shutil.rmtree(dest_abs)
        else:
            os.remove(dest_abs)
    shutil.copytree(src_abs, dest_abs)
    meta["path"] = dest_abs
    index = _read_index()
    index[meta["id"]] = meta
    _write_index(index)
    return meta


def _copy_skill_file(src, overwrite):
    """把单个 .md 文件安装为技能（内部仍落为 <skill_id>/SKILL.md）。"""
    with open(src, "r", encoding="utf-8-sig") as f:
        raw = f.read()
    meta, body = _split_frontmatter(raw)
    name = str(meta.get("name") or os.path.splitext(os.path.basename(src))[0]).strip()
    desc = str(meta.get("description") or "").strip()
    if not desc and body:
        desc = body.splitlines()[0].lstrip("#").strip()
    entry = {
        "id": str(meta.get("id") or _slugify(name)),
        "name": name,
        "description": desc,
        "version": str(meta.get("version") or "1.0.0"),
        "author": str(meta.get("author") or ""),
        "tags": meta.get("tags") or [],
        "instruction": body or raw.strip(),
        "path": "",
    }
    os.makedirs(SKILLS_DIR, exist_ok=True)
    skills_abs = os.path.abspath(SKILLS_DIR)
    dest_abs = os.path.abspath(os.path.join(SKILLS_DIR, entry["id"]))
    if not (dest_abs == skills_abs or dest_abs.startswith(skills_abs + os.sep)):
        raise RuntimeError("技能 id 非法，已拒绝安装")
    if os.path.exists(dest_abs):
        if not overwrite:
            raise FileExistsError(f"技能已存在: {entry['id']}")
        if os.path.isdir(dest_abs):
            shutil.rmtree(dest_abs)
        else:
            os.remove(dest_abs)
    os.makedirs(dest_abs)
    with open(os.path.join(dest_abs, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(raw)
    entry["path"] = dest_abs
    index = _read_index()
    index[entry["id"]] = entry
    _write_index(index)
    return entry


def install_skill(src, overwrite=True):
    """安装技能并返回技能条目 dict。

    src 支持：单个 .md 文件；含 SKILL.md（或唯一 .md）的目录；
    zip 包（包内任意层级含 SKILL.md 或唯一 .md）。
    """
    src = os.path.abspath(src)
    if not os.path.exists(src):
        raise FileNotFoundError(f"技能来源不存在: {src}")
    if os.path.isdir(src):
        md = os.path.join(src, "SKILL.md")
        if os.path.isfile(md):
            meta = _parse_skill_dir(src)
            return _copy_skill_dir(src, meta, overwrite)
        md_files = [f for f in os.listdir(src)
                    if f.lower().endswith((".md", ".markdown"))]
        if len(md_files) == 1:
            return _copy_skill_file(os.path.join(src, md_files[0]), overwrite)
        if not md_files:
            raise FileNotFoundError(
                f"技能目录缺少 SKILL.md 或 .md 文件: {src}")
        raise ValueError(
            f"技能目录存在多个 .md 文件（{len(md_files)} 个），"
            "请选择单个 .md 文件或保留 SKILL.md")
    low = src.lower()
    if low.endswith((".md", ".markdown")):
        return _copy_skill_file(src, overwrite)
    if not low.endswith(".zip"):
        raise ValueError("技能来源必须是 .md 文件、含 SKILL.md 的目录或 .zip 包")
    tmp = tempfile.mkdtemp(prefix="tinntin_skill_")
    try:
        _safe_extract_zip(src, tmp)
        skill_dir = _find_skill_dir(tmp)
        if skill_dir:
            meta = _parse_skill_dir(skill_dir)
            return _copy_skill_dir(skill_dir, meta, overwrite)
        md_files = [os.path.join(root, f)
                    for root, _dirs, files in os.walk(tmp)
                    for f in files if f.lower().endswith((".md", ".markdown"))]
        if len(md_files) == 1:
            return _copy_skill_file(md_files[0], overwrite)
        raise FileNotFoundError("技能包内未找到 SKILL.md 或唯一 .md 文件")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def list_skills():
    """列出已安装技能（自动扫描 data/skills 自愈索引）。"""
    index = _read_index()
    entries = []
    if os.path.isdir(SKILLS_DIR):
        for name in sorted(os.listdir(SKILLS_DIR)):
            d = os.path.join(SKILLS_DIR, name)
            if not (os.path.isdir(d) and os.path.isfile(os.path.join(d, "SKILL.md"))):
                continue
            try:
                entry = _parse_skill_dir(d)
            except Exception:
                continue
            entries.append(entry)
            index[entry["id"]] = entry
    _write_index(index)
    return sorted(entries, key=lambda e: (e.get("name") or "").lower())


def skill_entries():
    """供工作台使用：优先服务端已登记技能（GET /skills），失败回退本地扫描。

    技能管理在服务端：本地导入的技能登记后由服务端接口统一返回。
    返回与智能体同构的条目（id/name/desc/instruction/source="skill"）。
    """
    srv = server_skills(timeout=6)
    if srv:
        out = []
        for s in srv:
            if not isinstance(s, dict):
                continue
            out.append({
                "id": s.get("skill_id") or s.get("id") or "",
                "name": s.get("name") or s.get("skill_id") or "",
                "desc": s.get("description") or "",
                "instruction": s.get("instruction") or "",
                "source": "skill",
            })
        return out
    return [{
        "id": s["id"],
        "name": s["name"],
        "desc": s["description"],
        "instruction": s["instruction"],
        "source": "skill",
    } for s in list_skills()]


def remove_skill(skill_id):
    """卸载技能；技能目录不在 data/skills 内时拒绝删除。"""
    skill_id = (skill_id or "").strip()
    if not skill_id:
        return False
    skills_abs = os.path.abspath(SKILLS_DIR)
    target_abs = os.path.abspath(os.path.join(SKILLS_DIR, skill_id))
    if not target_abs.startswith(skills_abs + os.sep):
        raise RuntimeError("技能 id 非法，已拒绝卸载")
    if os.path.isdir(target_abs):
        shutil.rmtree(target_abs)
    index = _read_index()
    removed = index.pop(skill_id, None) is not None or not os.path.isdir(target_abs)
    _write_index(index)
    # 同步取消服务端登记（失败不影响本地删除）
    unregister_skill(skill_id)
    return removed
