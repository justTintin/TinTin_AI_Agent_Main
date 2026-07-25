# -*- coding: utf-8 -*-
import os
import json
import uuid
import time
from utils.logger_utils import log

class JianyingExporter:
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
        """一键导出为剪映工程草稿
        
        :param video_path: 视频绝对路径 (例如: dubbed_xxx.mp4)
        :param bgm_path: 背景音乐绝对路径 (可选)
        :param bgm_volume: BGM 音量 (0-100，默认 50)
        :param srt_path: 字幕 .srt 文件的绝对路径 (可选，若提供则生成剪映原生字幕轨)
        :param draft_name: 草稿项目名称 (可选)
        :return: (bool, str) -> (是否成功, 成功路径或错误信息)
        """
        if not video_path or not os.path.exists(video_path):
            return False, "视频文件不存在"

        try:
            # 1. 准备目录与 UUID
            draft_root = cls.get_default_draft_root()
            os.makedirs(draft_root, exist_ok=True)
            
            project_uuid = str(uuid.uuid4()).upper()
            if not draft_name:
                draft_name = f"螺丝钉智能混剪_{os.path.splitext(os.path.basename(video_path))[0]}"
            
            draft_folder = os.path.join(draft_root, project_uuid)
            os.makedirs(draft_folder, exist_ok=True)

            # 获取视频时长与分辨率 (微秒与像素)
            from utils.platform_utils import find_ffprobe, create_no_window_flag
            import subprocess
            
            creationflags = create_no_window_flag()
            ffprobe_exe = find_ffprobe()
            video_duration_sec = 0.0
            video_width = 1080
            video_height = 1920
            
            if os.path.isfile(ffprobe_exe):
                # 1) 获取时长
                cmd = [ffprobe_exe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video_path]
                r = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    video_duration_sec = float(r.stdout.strip())
                
                # 2) 获取宽度和高度
                cmd_size = [ffprobe_exe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path]
                r_size = subprocess.run(cmd_size, capture_output=True, text=True, creationflags=creationflags, timeout=10)
                if r_size.returncode == 0 and r_size.stdout.strip():
                    # 格式可能是单行 width,height 或者多行
                    sz_lines = [s.strip() for s in r_size.stdout.splitlines() if s.strip()]
                    if sz_lines:
                        sz_parts = sz_lines[0].split(",")
                        if len(sz_parts) >= 2:
                            try:
                                video_width = int(sz_parts[0])
                                video_height = int(sz_parts[1])
                            except Exception:
                                pass
            
            if video_duration_sec <= 0:
                # 备用估算方案
                video_duration_sec = 10.0

            video_duration_us = int(video_duration_sec * 1000000)

            # 2. 构建 draft_meta_info.json
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

            # 3. 构造素材库 (materials)
            video_material_id = str(uuid.uuid4()).upper()
            materials = {
                "videos": [
                    {
                        "id": video_material_id,
                        "local_material_path": video_path.replace("\\", "/"),
                        "duration": video_duration_us,
                        "type": "video",
                        "width": video_width,
                        "height": video_height
                    }
                ],
                "audios": [],
                "texts": []
            }

            # 构造轨道 (tracks)
            video_segment_id = str(uuid.uuid4()).upper()
            video_track = {
                "id": str(uuid.uuid4()).upper(),
                "type": "video",
                "segments": [
                    {
                        "id": video_segment_id,
                        "material_id": video_material_id,
                        "target_timerange": {
                            "start": 0,
                            "duration": video_duration_us
                        },
                        "source_timerange": {
                            "start": 0,
                            "duration": video_duration_us
                        },
                        "speed": 1.0,
                        "volume": 1.0
                    }
                ]
            }

            tracks = [video_track]

            # 4. 插入背景音乐 (BGM)
            if bgm_path and os.path.exists(bgm_path):
                bgm_material_id = str(uuid.uuid4()).upper()
                bgm_segment_id = str(uuid.uuid4()).upper()
                
                # 估算 BGM 时长
                bgm_duration_sec = 0.0
                if os.path.isfile(ffprobe_exe):
                    cmd = [ffprobe_exe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", bgm_path]
                    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags, timeout=5)
                    if r.returncode == 0 and r.stdout.strip():
                        bgm_duration_sec = float(r.stdout.strip())
                if bgm_duration_sec <= 0:
                    bgm_duration_sec = video_duration_sec + 60.0 # 足够长

                bgm_duration_us = int(bgm_duration_sec * 1000000)
                
                materials["audios"].append({
                    "id": bgm_material_id,
                    "local_material_path": bgm_path.replace("\\", "/"),
                    "duration": bgm_duration_us,
                    "type": "audio"
                })

                # 音轨
                vol_db = (bgm_volume / 50.0 - 1.0) * 12.0 # 粗略的分贝转换
                audio_track = {
                    "id": str(uuid.uuid4()).upper(),
                    "type": "audio",
                    "segments": [
                        {
                            "id": bgm_segment_id,
                            "material_id": bgm_material_id,
                            "target_timerange": {
                                "start": 0,
                                "duration": video_duration_us # 仅和视频一样长
                            },
                            "source_timerange": {
                                "start": 0,
                                "duration": video_duration_us
                            },
                            "volume": bgm_volume / 100.0,
                            "volume_db": vol_db
                        }
                    ]
                }
                tracks.append(audio_track)

            # 5. 解析并插入字幕 (SRT)
            if srt_path and os.path.exists(srt_path):
                srt_segments = cls._parse_srt(srt_path)
                if srt_segments:
                    text_track = {
                        "id": str(uuid.uuid4()).upper(),
                        "type": "text",
                        "segments": []
                    }
                    
                    for start_sec, end_sec, text_content in srt_segments:
                        text_material_id = str(uuid.uuid4()).upper()
                        text_seg_id = str(uuid.uuid4()).upper()
                        
                        start_us = int(start_sec * 1000000)
                        dur_us = int((end_sec - start_sec) * 1000000)
                        
                        if dur_us <= 0:
                            continue
                            
                        # 文本素材
                        materials["texts"].append({
                            "id": text_material_id,
                            "content": f"[{{\"text\":\"{text_content}\",\"style\":{{\"bold\":false,\"color\":\"#FFFFFF\",\"font\":\"\"}}}}]",
                            "type": "text"
                        })
                        
                        # 文字段落
                        text_track["segments"].append({
                            "id": text_seg_id,
                            "material_id": text_material_id,
                            "target_timerange": {
                                "start": start_us,
                                "duration": dur_us
                            }
                        })
                        
                    if text_track["segments"]:
                        tracks.append(text_track)

            # 根据宽高动态匹配 canvas_config 的比例
            ratio = "9:16"
            if video_width > video_height:
                ratio = "16:9"
            elif video_width == video_height:
                ratio = "1:1"

            # 6. 保存 draft_content.json
            content_info = {
                "canvas_config": {
                    "width": video_width,
                    "height": video_height,
                    "ratio": ratio
                },
                "materials": materials,
                "tracks": tracks
            }
            
            with open(os.path.join(draft_folder, "draft_content.json"), "w", encoding="utf-8") as f:
                json.dump(content_info, f, ensure_ascii=False, indent=2)

            log.info(f"[Jianying] 草稿导出成功: {draft_folder}")
            return True, draft_folder

        except Exception as e:
            log.exception(f"导出剪映草稿失败: {e}")
            return False, str(e)

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
