# -*- coding: utf-8 -*-
"""智能混剪 - 画面描述生成 Worker：批量镜头描述、本地视觉描述。"""
import base64
from PySide6.QtCore import Signal
from utils.base_worker import BaseWorker
from utils.logger_utils import log
from gui.montage.utils_media import extract_keyframes



class BatchGenerateDescriptionsWorker(BaseWorker):
    finished = Signal(str)  # JSON string: {"1": "desc1", "2": "desc2", ...}

    def __init__(self, api_url, api_key, model, srt_text, scenes, split_video_paths):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.srt_text = srt_text
        self.scenes = scenes # list of (start_sec, end_sec)
        self.split_video_paths = split_video_paths

    def run(self):
        try:
            import requests
            import json
            import re

            log.info(f"BatchGenerateDescriptionsWorker - 启动整体镜头描述分析。视频分段数: {len(self.scenes)}")
            
            desc_dict = {}
            # 有字幕时走文本模型（默认），无字幕时走服务端自选的视觉模型
            is_vision = not self.srt_text.strip()
            
            # 1. Prepare scenes info
            scenes_info = []
            for idx, (scene_start, scene_end) in enumerate(self.scenes, 1):
                scenes_info.append(f"镜头 {idx} 时间段: {scene_start:.2f}秒 --> {scene_end:.2f}秒")
            scenes_text = "\n".join(scenes_info)
            
            # 2. Build system and user prompt
            if self.srt_text.strip():
                # We have subtitles, perform global text alignment and optimization
                system_prompt = (
                    "你是一个优秀的视频剪辑文案配合分析与生成专家。\n"
                    "给你一段视频的原始字幕文案作为背景，以及该视频被分割出的所有镜头的时间段列表。\n"
                    "请将这段字幕文案合理、自然地拆分、分配并润色到各个对应的时间段镜头中，让每个镜头都有一句通顺、且有营销卖点的画面描述文案。\n"
                    "请注意：\n"
                    "1. 必须为【每个】镜头生成一句画面描述（控制在10-25字之间）。\n"
                    "2. 如果某些时间段视频里没有说话声音（比如是背景镜头），请根据整体视频卖点设计一句合适的画面描述（如：产品细节特写、模特手持特写、大字提示卖点等）。\n"
                    "3. 保持镜头描述在语意上的连贯性和整体性。\n"
                    "请严格以 JSON 格式输出，不得包含 markdown 标记或任何解释文字，格式如下：\n"
                    "[\n"
                    "  {\"index\": 1, \"description\": \"第一镜头的描述文案\"},\n"
                    "  {\"index\": 2, \"description\": \"第二镜头的描述文案\"}\n"
                    "]"
                )
                user_content = (
                    f"视频字幕背景内容：\n{self.srt_text}\n\n"
                    f"镜头时间段列表：\n{scenes_text}\n\n"
                    "请直接输出分配好后的 JSON 数组。"
                )
            else:
                # Silent video, we must generate description from visual keyframes
                system_prompt = (
                    "你是一个视频画面描述专家。给定一个无声视频被分割出的所有镜头时间段，以及每个镜头的关键帧图片。\n"
                    "请为每一个镜头设计一句简短的画面描述文案（字数控制在10-25字之间，用以说明该镜头展示了什么内容或概念，如：产品外观展示、运动特写、价格对比等）。\n"
                    "请注意镜头之间的衔接和整体文案的吸引力。\n"
                    "请严格以 JSON 格式输出，不得包含 markdown 标记或任何解释文字，格式如下：\n"
                    "[\n"
                    "  {\"index\": 1, \"description\": \"第一镜头的描述文案\"},\n"
                    "  {\"index\": 2, \"description\": \"第二镜头的描述文案\"}\n"
                    "]"
                )
                
                # Extract keyframes for all scenes
                user_content = []
                user_content.append({"type": "text", "text": "以下是视频中所有分割镜头的关键帧图片：\n\n"})
                for idx, (scene_start, scene_end) in enumerate(self.scenes, 1):
                    clip_path = ""
                    if idx - 1 < len(self.split_video_paths):
                        clip_path = self.split_video_paths[idx - 1]
                    
                    keyframes = []
                    if clip_path:
                        try:
                            keyframes = extract_keyframes(clip_path)
                            log.info(f"BatchGenerateDescriptionsWorker - 镜头 {idx} 成功抽帧 {len(keyframes)} 张关键图片。")
                        except Exception as e:
                            log.warning(f"提取视频关键帧失败: {clip_path}, 错误: {e}")
                    
                    user_content.append({"type": "text", "text": f"镜头 {idx} ({scene_start:.2f}s --> {scene_end:.2f}s):\n"})
                    if keyframes and is_vision:
                        for kf_b64 in keyframes:
                            user_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{kf_b64}"
                                }
                            })
                    user_content.append({"type": "text", "text": "\n\n"})
                
            # Call LLM API
            # 走服务端代理
            from utils.llm_proxy import llm_chat
            
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.2
            }
            
            log.info("BatchGenerateDescriptionsWorker - 正在请求大模型 API，以整体方式生成镜头描述。")
            res_json = llm_chat(payload["messages"][0]["content"], payload["messages"][1]["content"], model=(None if is_vision else ""), timeout=60)
            class _R:
                status_code = 200
            res = _R()
            res.json = lambda: {"choices": [{"message": {"content": res_json}}]}
            if res.status_code != 200:
                raise RuntimeError(f"LLM API request failed: HTTP {res.status_code}, Response: {res.text}")
            
            data = res.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            log.info(f"BatchGenerateDescriptionsWorker - 大模型返回内容:\n{content}")
            
            # Clean markdown codeblocks
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            
            # Extract JSON array
            if not content.startswith("["):
                start_idx = content.find("[")
                end_idx = content.rfind("]")
                if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                    content = content[start_idx:end_idx+1]
            
            results = json.loads(content)
            for item in results:
                desc_dict[int(item["index"])] = item["description"]
            
            # Fill missing indices with default
            for idx in range(1, len(self.scenes) + 1):
                if idx not in desc_dict:
                    desc_dict[idx] = f"镜头片段 {idx}"
                    
            log.info(f"BatchGenerateDescriptionsWorker - 整体文案对齐生成成功，共 {len(desc_dict)} 个镜头描述。")
            self.finished.emit(json.dumps({str(k): v for k, v in desc_dict.items()}, ensure_ascii=False))
            
        except Exception as e:
            log.exception("BatchGenerateDescriptionsWorker 运行发生异常")
            self.error.emit(str(e))



class LocalVisionDescWorker(BaseWorker):
    """调用服务端 /llm/chat/completions 视觉模型（模型名由服务端自动选择）分析每个分割镜头的画面内容，生成画面描述文案；客户端本地仅抽帧。

    有字幕时：结合字幕文案 + 画面截图，生成带营销感的描述。
    无字幕时：纯画面视觉分析。
    """

    finished = Signal(str)  # JSON string: {"1": "desc1", "2": "desc2", ...}

    def __init__(self, split_video_paths, scenes,
                 srt_text="", srt_segments=None):
        super().__init__()
        self.split_video_paths = split_video_paths
        self.scenes = scenes
        self.srt_text = srt_text
        self.srt_segments = srt_segments or []  # list of (start_sec, end_sec, text)

    def _find_subtitle_for_shot(self, shot_start, shot_end):
        """找到与该镜头时间重叠的字幕文本。"""
        matched_texts = []
        for seg_start, seg_end, text in self.srt_segments:
            # 有重叠即匹配
            if seg_start < shot_end and seg_end > shot_start:
                text = text.strip()
                if text:
                    matched_texts.append(text)
        return " ".join(matched_texts) if matched_texts else ""

    def _extract_mid_frame(self, video_path):
        """从视频中间位置抽取一帧，返回 base64 jpg。"""
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return None
        mid = total_frames // 2
        cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        # Resize to max 512px for token efficiency
        h, w = frame.shape[:2]
        max_size = 512
        if h > max_size or w > max_size:
            if h > w:
                new_h, new_w = max_size, int(w * max_size / h)
            else:
                new_h, new_w = int(h * max_size / w), max_size
            frame = cv2.resize(frame, (new_w, new_h))
        ret_jpg, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ret_jpg:
            return None
        return base64.b64encode(buffer).decode("utf-8")

    def run(self):
        try:
            import json as _json
            desc_dict = {}
            total = len(self.split_video_paths)
            has_subtitles = bool(self.srt_segments)

            system_prompt_vision_only = (
                "你是一个视频画面描述专家。请仔细观察这张视频截图，用一句简短的中文（10-25字）"
                "描述画面中的核心视觉内容，包括：主体对象、动作/姿态、场景/环境。"
                "只输出描述文字，不要编号、不要引号、不要任何额外解释。"
            )
            system_prompt_with_srt = (
                "你是一个短视频营销文案专家。请结合下方提供的【口播字幕文案】和这张【视频截图】，"
                "生成一句简短有营销感的中文画面描述（10-25字）。"
                "描述应提炼画面中的视觉卖点，并与字幕内容呼应。"
                "只输出描述文字，不要编号、不要引号、不要任何额外解释。"
            )

            for idx, clip_path in enumerate(self.split_video_paths, 1):
                try:
                    frame_b64 = self._extract_mid_frame(clip_path)
                    if not frame_b64:
                        desc_dict[idx] = f"镜头片段 {idx}"
                        continue

                    # Check for subtitle text aligned to this shot
                    shot_start, shot_end = (0.0, 0.0)
                    if idx - 1 < len(self.scenes):
                        shot_start, shot_end = self.scenes[idx - 1]
                    sub_text = self._find_subtitle_for_shot(shot_start, shot_end)

                    if sub_text:
                        system_prompt = system_prompt_with_srt
                        user_text = f"【口播字幕文案】{sub_text}\n\n请结合截图生成画面描述。"
                    else:
                        system_prompt = system_prompt_vision_only
                        user_text = "请描述这张截图的画面内容。"

                    from utils.llm_proxy import llm_chat_messages
                    text = llm_chat_messages(
                        [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": [
                             {"type": "text", "text": user_text},
                             {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"}},
                         ]}],
                        model=None, temperature=0.2, max_tokens=60, timeout=60)
                    content = text.strip().strip("'\"\"'").split("\n")[0].strip()
                    if content:
                        desc_dict[idx] = content[:30]
                    else:
                        desc_dict[idx] = f"镜头片段 {idx}"
                except Exception as e:
                    log.warning(f"Vision analysis failed for clip {idx}: {e}")
                    desc_dict[idx] = f"镜头片段 {idx}"

            log.info(f"LocalVisionDescWorker - 完成 {len(desc_dict)}/{total} 个镜头画面分析"
                     + ("（结合字幕）" if has_subtitles else "（纯画面）"))
            self.finished.emit(_json.dumps({str(k): v for k, v in desc_dict.items()}, ensure_ascii=False))
        except Exception as e:
            log.exception("LocalVisionDescWorker 运行发生异常")
            self.error.emit(str(e))


class ServerDescribeWorker(BaseWorker):
    """调用服务端 /material/score_clip 接口生成镜头画面描述文案。"""

    finished = Signal(object)

    def __init__(self, clip_paths):
        super().__init__()
        self.clip_paths = clip_paths

    def run(self):
        try:
            from utils.montage_client import describe_shots
            log.info(f"ServerDescribeWorker - 请求服务端分析: {len(self.clip_paths)} 个镜头")
            result = describe_shots(self.clip_paths)
            self.finished.emit(result)
        except Exception as e:
            log.exception("ServerDescribeWorker 运行发生异常")
            self.error.emit(str(e))
