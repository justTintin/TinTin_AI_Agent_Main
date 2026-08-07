# -*- coding: utf-8 -*-
import os
import json
import uuid
import time
from utils.logger_utils import log


class JianyingExporter:
    """剪映专业版草稿（DRT）导出器。

    支持：
    - 单视频导出（兼容旧入口 export_to_draft）
    - 多片段时间轴导出：多个视频按顺序排成一条视频轨，片段之间可加剪映原生转场，
      每个片段可携带各自的 .srt 字幕（自动按时间轴偏移）
    - BGM 音频轨、音量
    """

    # UI 转场 key -> (剪映转场名, resource_id, effect_id, is_overlap, 默认时长(微秒))
    # 资源 ID 来自剪映内置转场元数据（pyJianYingDraft，2024 版剪映专业版）
    TRANSITION_MAP = {
        "fade":       ("模糊",     "6911569618171597320", "4212596", True,  500000),
        "dissolve":   ("叠化",     "6724845717472416269", "322577",  True,  500000),
        "slideleft":  ("向左擦除", "6724849999336706573", "2917283", True,  500000),
        "slideright": ("向右擦除", "6724849898857959950", "2917284", True,  500000),
        "slideup":    ("向上擦除", "6724849456891564557", "2917281", True,  500000),
        "slidedown":  ("向下擦除", "6724849752921346573", "2917282", True,  500000),
        "zoomin":     ("推近",     "6724226861666144779", "359359",  False, 1000000),
        "zoomout":    ("拉远",     "6724226338418332167", "359365",  False, 1000000),
    }

    @staticmethod
    def get_default_draft_root():
        """获取 Windows 默认的剪映专业版草稿根目录"""
        appdata = os.environ.get("LOCALAPPDATA")
        if not appdata:
            appdata = os.path.expandvars(r"%USERPROFILE%\AppData\Local")
        path = os.path.join(appdata, "JianyingPro", "User Data", "Projects", "com.lveditor.draft")
        return os.path.normpath(path)

    @classmethod
    def export_to_draft(cls, video_path, bgm_path=None, bgm_volume=50, srt_path=None, draft_name=None):
        """一键导出单个视频为剪映工程草稿（兼容旧入口，内部走多片段时间轴导出）。

        :param video_path: 视频绝对路径 (例如: dubbed_xxx.mp4)
        :param bgm_path: 背景音乐绝对路径 (可选)
        :param bgm_volume: BGM 音量 (0-100，默认 50)
        :param srt_path: 字幕 .srt 文件的绝对路径 (可选，若提供则生成剪映原生字幕轨)
        :param draft_name: 草稿项目名称 (可选)
        :return: (bool, str) -> (是否成功, 成功路径或错误信息)
        """
        if not video_path or not os.path.exists(video_path):
            return False, "视频文件不存在"
        if not draft_name:
            draft_name = f"螺丝钉智能混剪_{os.path.splitext(os.path.basename(video_path))[0]}"
        return cls.export_multi_to_draft(
            video_paths=[video_path],
            transitions=None,
            bgm_path=bgm_path,
            bgm_volume=bgm_volume,
            srt_paths=[srt_path] if srt_path else None,
            draft_name=draft_name,
        )

    @classmethod
    def export_multi_to_draft(cls, video_paths, transitions=None, bgm_path=None, bgm_volume=50,
                              srt_paths=None, draft_name=None):
        """将多个视频按顺序导出为一条剪映时间轴（可带转场 + 各自字幕 + BGM）。

        :param video_paths: 有序的视频绝对路径列表（时间轴顺序）
        :param transitions: 转场配置，可为：
            - None：默认使用 "fade"（模糊）连接每个片段
            - str：一个转场 key（如 "dissolve"），应用到所有衔接处
            - list：长度 = 片段数-1 的转场 key 列表；None/""/"none" 表示该处不加转场
        :param bgm_path: 背景音乐绝对路径 (可选)
        :param bgm_volume: BGM 音量 (0-100，默认 50)
        :param srt_paths: 与 video_paths 等长的字幕 .srt 列表（可选），每个片段的字幕
            会自动按其在时间轴上的起始时间偏移
        :param draft_name: 草稿项目名称 (可选)
        :return: (bool, str) -> (是否成功, 成功路径或错误信息)
        """
        video_paths = [p for p in (video_paths or []) if p]
        if not video_paths:
            return False, "没有可导出的视频"
        for p in video_paths:
            if not os.path.exists(p):
                return False, f"视频文件不存在: {p}"

        try:
            from utils.platform_utils import find_ffprobe, create_no_window_flag
            import subprocess
            creationflags = create_no_window_flag()
            ffprobe_exe = find_ffprobe()

            # 1. 探测每个视频的时长与分辨率
            clips = []
            total_duration_us = 0
            for p in video_paths:
                duration_us, width, height = cls._probe_video(p, ffprobe_exe, creationflags)
                if duration_us <= 0:
                    duration_us = 10_000_000  # 兜底 10s
                clips.append({
                    "path": p,
                    "duration_us": duration_us,
                    "width": width or 1080,
                    "height": height or 1920,
                })
                total_duration_us += duration_us

            canvas_width = clips[0]["width"]
            canvas_height = clips[0]["height"]

            # 2. 准备草稿目录与 UUID
            draft_root = cls.get_default_draft_root()
            os.makedirs(draft_root, exist_ok=True)
            project_uuid = str(uuid.uuid4()).upper()
            if not draft_name:
                if len(clips) == 1:
                    draft_name = f"螺丝钉智能混剪_{os.path.splitext(os.path.basename(clips[0]['path']))[0]}"
                else:
                    draft_name = "螺丝钉智能混剪_多片段时间轴"
            draft_folder = os.path.join(draft_root, project_uuid)
            os.makedirs(draft_folder, exist_ok=True)

            # 3. draft_meta_info.json
            now_ms = int(time.time() * 1000)
            meta_info = {
                "id": project_uuid,
                "draft_name": draft_name,
                "draft_foldpath": draft_folder.replace("\\", "/"),
                "draft_type": "face",
                "create_time": now_ms,
                "update_time": now_ms,
                "tm_draft_modified": now_ms,
                "draft_rootpath": draft_root.replace("\\", "/"),
                "platform": "windows"
            }
            with open(os.path.join(draft_folder, "draft_meta_info.json"), "w", encoding="utf-8") as f:
                json.dump(meta_info, f, ensure_ascii=False, indent=2)

            # 4. 素材库 + 轨道
            materials = {
                "videos": [],
                "audios": [],
                "texts": [],
                "transitions": [],
            }
            video_track = {
                "id": str(uuid.uuid4()).upper(),
                "type": "video",
                "segments": [],
            }
            tracks = [video_track]

            # 转场规格归一化：长度 = 片段数-1
            transition_specs = cls._normalize_transitions(transitions, len(clips) - 1)

            cursor_us = 0
            for i, clip in enumerate(clips):
                video_material_id = str(uuid.uuid4()).upper()
                materials["videos"].append({
                    "id": video_material_id,
                    "local_material_path": clip["path"].replace("\\", "/"),
                    "duration": clip["duration_us"],
                    "type": "video",
                    "width": clip["width"],
                    "height": clip["height"],
                })

                segment = {
                    "id": str(uuid.uuid4()).upper(),
                    "material_id": video_material_id,
                    "target_timerange": {
                        "start": cursor_us,
                        "duration": clip["duration_us"],
                    },
                    "source_timerange": {
                        "start": 0,
                        "duration": clip["duration_us"],
                    },
                    "speed": 1.0,
                    "volume": 1.0,
                    "extra_material_refs": [],
                }
                video_track["segments"].append(segment)

                # 转场挂在「前一个」片段上（剪映约定），衔接 i-1 与 i
                if i > 0:
                    spec = transition_specs[i - 1]
                    if spec:
                        trans_id = cls._build_transition_material(materials, spec)
                        video_track["segments"][-2]["extra_material_refs"].append(trans_id)

                # 该片段的字幕按时间轴偏移
                if srt_paths and i < len(srt_paths) and srt_paths[i] and os.path.exists(srt_paths[i]):
                    cls._append_subtitle_track(
                        tracks, materials, srt_paths[i], offset_us=cursor_us,
                        limit_end_us=cursor_us + clip["duration_us"],
                    )

                cursor_us += clip["duration_us"]

            # 5. BGM（覆盖整条时间轴）
            if bgm_path and os.path.exists(bgm_path):
                cls._append_bgm_track(tracks, materials, bgm_path, bgm_volume,
                                      total_duration_us, ffprobe_exe, creationflags)

            # 6. canvas_config
            ratio = "9:16"
            if canvas_width > canvas_height:
                ratio = "16:9"
            elif canvas_width == canvas_height:
                ratio = "1:1"

            content_info = {
                "canvas_config": {
                    "width": canvas_width,
                    "height": canvas_height,
                    "ratio": ratio,
                },
                "materials": materials,
                "tracks": tracks,
            }
            with open(os.path.join(draft_folder, "draft_content.json"), "w", encoding="utf-8") as f:
                json.dump(content_info, f, ensure_ascii=False, indent=2)

            log.info(f"[Jianying] 草稿导出成功: {draft_folder}（{len(clips)} 个片段）")
            return True, draft_folder

        except Exception as e:
            log.exception(f"导出剪映草稿失败: {e}")
            return False, str(e)

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #

    @staticmethod
    def _probe_video(video_path, ffprobe_exe, creationflags):
        """返回 (时长微秒, 宽度, 高度)；失败时时长返回 0，尺寸返回默认值"""
        import subprocess
        duration_sec = 0.0
        width, height = 1080, 1920
        if os.path.isfile(ffprobe_exe):
            try:
                cmd = [ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
                       "-of", "csv=p=0", video_path]
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   creationflags=creationflags, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    duration_sec = float(r.stdout.strip())
            except Exception:
                pass
            try:
                cmd_size = [ffprobe_exe, "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path]
                r_size = subprocess.run(cmd_size, capture_output=True, text=True,
                                        creationflags=creationflags, timeout=10)
                if r_size.returncode == 0 and r_size.stdout.strip():
                    sz_lines = [s.strip() for s in r_size.stdout.splitlines() if s.strip()]
                    if sz_lines:
                        parts = sz_lines[0].split(",")
                        if len(parts) >= 2:
                            width = int(float(parts[0]))
                            height = int(float(parts[1]))
            except Exception:
                pass
        return int(duration_sec * 1000000), width, height

    @classmethod
    def _normalize_transitions(cls, transitions, count):
        """将转场参数归一化为长度 count 的列表，每项为 spec dict 或 None（无转场）"""
        if transitions is None:
            transitions = []
        elif isinstance(transitions, (str, dict)):
            transitions = [transitions]
        result = []
        for i in range(count):
            spec = transitions[i] if i < len(transitions) else "fade"
            result.append(cls._normalize_one_transition(spec))
        return result

    @classmethod
    def _normalize_one_transition(cls, spec):
        """单个转场规格 -> dict（name/resource_id/effect_id/is_overlap/duration）或 None"""
        if spec is None:
            return None
        if isinstance(spec, str):
            key = spec.strip().lower()
            if key in ("", "none", "无", "null"):
                return None
            name, resource_id, effect_id, is_overlap, duration_us = cls.TRANSITION_MAP.get(
                key, cls.TRANSITION_MAP["fade"])
            return {
                "name": name,
                "resource_id": resource_id,
                "effect_id": effect_id,
                "is_overlap": is_overlap,
                "duration": duration_us,
            }
        if isinstance(spec, dict):
            # 支持外部直接传完整 spec（便于以后扩展自定义转场）
            if not spec.get("resource_id"):
                return None
            return {
                "name": spec.get("name", "模糊"),
                "resource_id": str(spec["resource_id"]),
                "effect_id": str(spec.get("effect_id", "")),
                "is_overlap": bool(spec.get("is_overlap", True)),
                "duration": int(spec.get("duration", 500000)),
            }
        return None

    @staticmethod
    def _build_transition_material(materials, spec):
        """把转场写入 materials.transitions，返回转场素材 id"""
        trans_id = str(uuid.uuid4()).upper()
        materials["transitions"].append({
            "category_id": "",
            "category_name": "",
            "duration": spec["duration"],
            "effect_id": spec["effect_id"],
            "id": trans_id,
            "is_overlap": spec["is_overlap"],
            "name": spec["name"],
            "platform": "all",
            "resource_id": spec["resource_id"],
            "type": "transition",
        })
        return trans_id

    @staticmethod
    def _append_subtitle_track(tracks, materials, srt_path, offset_us=0, limit_end_us=None):
        """把一个 .srt 解析后写入字幕轨道（若不存在则新建），时间整体偏移 offset_us"""
        srt_segments = JianyingExporter._parse_srt(srt_path)
        if not srt_segments:
            return
        text_track = None
        for t in tracks:
            if t["type"] == "text":
                text_track = t
                break
        if text_track is None:
            text_track = {"id": str(uuid.uuid4()).upper(), "type": "text", "segments": []}
            tracks.append(text_track)

        for start_sec, end_sec, text_content in srt_segments:
            start_us = int(start_sec * 1000000) + offset_us
            dur_us = int((end_sec - start_sec) * 1000000)
            if dur_us <= 0:
                continue
            if limit_end_us is not None and start_us + dur_us > limit_end_us:
                dur_us = max(0, limit_end_us - start_us)
            if dur_us <= 0:
                continue

            text_material_id = str(uuid.uuid4()).upper()
            text_seg_id = str(uuid.uuid4()).upper()
            # 转义字幕文本中的引号/反斜杠，避免破坏 content 的 JSON 结构
            safe_text = text_content.replace("\\", "\\\\").replace('"', '\\"')
            materials["texts"].append({
                "id": text_material_id,
                "content": f'[{{"text":"{safe_text}","style":{{"bold":false,"color":"#FFFFFF","font":""}}}}]',
                "type": "text",
            })
            text_track["segments"].append({
                "id": text_seg_id,
                "material_id": text_material_id,
                "target_timerange": {"start": start_us, "duration": dur_us},
            })

    @staticmethod
    def _append_bgm_track(tracks, materials, bgm_path, bgm_volume, total_duration_us,
                          ffprobe_exe, creationflags):
        """追加一条 BGM 音频轨，覆盖整条时间轴长度"""
        import subprocess
        bgm_material_id = str(uuid.uuid4()).upper()
        bgm_segment_id = str(uuid.uuid4()).upper()

        bgm_duration_sec = 0.0
        if os.path.isfile(ffprobe_exe):
            try:
                cmd = [ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
                       "-of", "csv=p=0", bgm_path]
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   creationflags=creationflags, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    bgm_duration_sec = float(r.stdout.strip())
            except Exception:
                pass
        if bgm_duration_sec <= 0:
            bgm_duration_sec = total_duration_us / 1000000.0 + 60.0  # 足够长

        bgm_duration_us = int(bgm_duration_sec * 1000000)
        materials["audios"].append({
            "id": bgm_material_id,
            "local_material_path": bgm_path.replace("\\", "/"),
            "duration": bgm_duration_us,
            "type": "audio",
        })

        vol_db = (bgm_volume / 50.0 - 1.0) * 12.0  # 粗略的分贝转换
        audio_track = {
            "id": str(uuid.uuid4()).upper(),
            "type": "audio",
            "segments": [
                {
                    "id": bgm_segment_id,
                    "material_id": bgm_material_id,
                    "target_timerange": {
                        "start": 0,
                        "duration": total_duration_us,
                    },
                    "source_timerange": {
                        "start": 0,
                        "duration": total_duration_us,
                    },
                    "volume": bgm_volume / 100.0,
                    "volume_db": vol_db,
                }
            ],
        }
        tracks.append(audio_track)

    @staticmethod
    def _parse_srt(srt_path):
        """解析 srt 格式为时间轴片段元组列表: (start_sec, end_sec, text)"""
        segments = []
        try:
            with open(srt_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            idx = 0
            while idx < len(lines):
                line = lines[idx].strip()
                if not line:
                    idx += 1
                    continue
                # Skip numeric index line
                if line.isdigit():
                    idx += 1
                    if idx >= len(lines):
                        break
                    line = lines[idx].strip()

                # Check for timestamp arrow -->
                if "-->" in line:
                    parts = line.split("-->")
                    start_sec = JianyingExporter._timestamp_to_sec(parts[0].strip())
                    end_sec = JianyingExporter._timestamp_to_sec(parts[1].strip())

                    # Gather subtitle text (possibly multi-line)
                    idx += 1
                    text_lines = []
                    while idx < len(lines) and lines[idx].strip():
                        text_lines.append(lines[idx].strip())
                        idx += 1

                    text = " ".join(text_lines)
                    segments.append((start_sec, end_sec, text))
                idx += 1
        except Exception as e:
            log.warning(f"解析字幕文件失败: {e}")
        return segments

    @staticmethod
    def _timestamp_to_sec(ts):
        """转换 00:00:02,120 格式为秒"""
        try:
            ts = ts.replace(",", ".")
            parts = ts.split(":")
            h = int(parts[0])
            m = int(parts[1])
            s = float(parts[2])
            return h * 3600 + m * 60 + s
        except Exception:
            return 0.0