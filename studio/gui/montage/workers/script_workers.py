"""智能混剪 - 文案/脚本生成 Worker：标点补全、AI 改写、产品文案、场景文案、
脚本生成、批量改写、脚本匹配。"""
import os
from typing import Any

from PySide6.QtCore import Signal
from utils.base_worker import BaseWorker
from utils.llm_output_utils import safe_json_parse
from utils.logger_utils import log


def _make_mock_response(json_data: dict[str, Any], text: str = "") -> Any:
    """构造一个模拟 HTTP 响应的对象，供本地调试使用。"""
    class _MockResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return json_data

        @property
        def text(self) -> str:
            return text

    return _MockResponse()


class PunctuationSRTLLMWorker(BaseWorker):
    finished = Signal(str)

    def __init__(self, model, srt_content):
        super().__init__()
        self.model = model
        self.srt_content = srt_content

    def run(self):
        try:
            from utils.llm_proxy import llm_chat
            system_prompt = (
                "你是一个字幕标点符号恢复专家。给定的内容是一个SRT字幕文件，其中包含时间轴和字幕文本。你的任务是给字幕文本添加合适的中文标点符号（，。！？：等），"  # noqa: E501
                "使阅读更清晰自然。请注意：\n"
                "1. 绝对不要修改时间轴（如 00:00:01,000 --> 00:00:04,500）或行号，必须原样保留。\n"
                "2. 绝对不要修改、增加或删除原字幕文本的任何汉字或英文单词，只能在文本中合理地插入标点符号。\n"
                "3. 直接输出加完标点符号后的完整SRT文件内容，不要用 markdown 包裹，不要有任何解释或废话。"
            )
            log.info(f"PunctuationSRTLLMWorker - 开始恢复字幕标点。模型: {self.model}, 字符数: {len(self.srt_content)}")  # noqa: E501
            content = llm_chat(system_prompt, self.srt_content, model=self.model, timeout=45)  # noqa: E501
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            log.info("PunctuationSRTLLMWorker - 字幕标点优化成功。")
            self.finished.emit(content)
        except Exception as e:
            log.exception("PunctuationSRTLLMWorker 运行异常")
            self.error.emit(str(e))



class AITextRewriteWorker(BaseWorker):
    finished = Signal(str)  # Emits the rewritten text

    def __init__(self, api_url, api_key, model, input_text):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.input_text = input_text

    def run(self):
        try:
            # 走服务端代理
            from utils.llm_proxy import llm_chat
            system_prompt = (
                "你是一个顶尖的短视频脚本与广告文案改写、润色与重构专家。\n"
                "请对用户提供的一段短视频配音文案（每行对应一个画面的旁白/配音）进行整体性的改写和润色，使其更具有爆款短视频的吸引力、更通顺、更有销售力或表现力。\n"  # noqa: E501
                "要求：\n"
                "1. 保持原有的行数，不要合并或删减行，因为每一行将严格对应视频中的一个画面镜头段。\n"
                "2. 针对每一行，输出改写优化后的新文案（控制在10-25字之间）。\n"
                "3. 保持整体文案在逻辑与情感上的连贯性，使其朗朗上口。\n"
                "4. 请直接按行返回改写后的纯文本，不要用 markdown 包裹，千万不要返回任何多余的解释、问候或废话！"
            )

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": self.input_text}
                ],
                "temperature": 0.3
            }

            res_json = llm_chat(payload["messages"][0]["content"], payload["messages"][1]["content"], model=self.model, timeout=45)  # noqa: E501
            res = _make_mock_response({"choices": [{"message": {"content": res_json}}]})
            if res.status_code != 200:
                raise RuntimeError(f"LLM API request failed: HTTP {res.status_code}")

            data = res.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("Empty response from LLM")
            content = choices[0].get("message", {}).get("content", "").strip()

            # Clean up markdown code blocks if any
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            self.finished.emit(content)
        except Exception as e:
            self.error.emit(str(e))



class ProductCopyWorker(BaseWorker):
    """根据品牌/产品/型号，调用大模型生成电商短视频口播文案（纯文本，每行一句）。"""
    finished = Signal(str)  # 生成的口播文案

    def __init__(self, api_url, api_key, model, brand, product, model_name, extra=""):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.brand = brand
        self.product = product
        self.model_name = model_name
        self.extra = extra

    def run(self):
        try:
            # 走服务端代理
            from utils.llm_proxy import llm_chat
            system_prompt = (
                "你是资深电商短视频口播文案撰稿人。用户会给出产品的品牌、品类/产品、型号以及可选卖点。\n"
                "请基于你对该产品的了解，撰写一段用于电商带货短视频的口播文案（旁白）。\n"
                "要求：\n"
                "1. 直接输出口播文案纯文本，每行一句，共 5-7 行，每行约 10-22 字，口语化、有节奏、有卖点和号召力。\n"
                "2. 突出该型号产品的核心卖点/参数/适用场景；若不确定具体参数，用准确的通用描述，切勿编造虚假数字。\n"
                "3. 不要 markdown、不要标题、不要解释说明，只输出文案本身，每句独占一行。"
            )
            user_msg = (
                f"品牌：{self.brand or '未提供'}\n"
                f"产品/品类：{self.product or '未提供'}\n"
                f"型号：{self.model_name or '未提供'}\n"
                f"补充卖点：{self.extra or '无'}\n\n"
                "请按要求生成口播文案。"
            )
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                "temperature": 0.6
            }
            res_json = llm_chat(payload["messages"][0]["content"], payload["messages"][1]["content"], model=self.model, timeout=60)  # noqa: E501
            res = _make_mock_response({"choices": [{"message": {"content": res_json}}]}, res_json)
            if res.status_code != 200:
                raise RuntimeError(f"LLM API 请求失败: HTTP {res.status_code} {res.text[:200]}")  # noqa: E501
            data = res.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("大模型返回为空")
            content = choices[0].get("message", {}).get("content", "").strip()
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            # 去掉空行
            content = "\n".join([ln.strip() for ln in content.splitlines() if ln.strip()])  # noqa: E501
            if not content:
                raise RuntimeError("大模型未生成有效文案")
            self.finished.emit(content)
        except Exception as e:
            self.error.emit(str(e))



class SceneCopyWorker(BaseWorker):
    """根据组合视频的画面镜头描述（按顺序）+ 可选的共同产品背景，调用大模型生成口播文案。

    输出每行对应一个镜头画面，按顺序排列，便于后续逐镜头配音映射。
    """
    finished = Signal(str)  # 生成的口播文案

    def __init__(self, api_url, api_key, model, scene_descriptions,
                 brand="", product="", model_name="", extra="", total_duration=0.0):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.scene_descriptions = scene_descriptions or []
        self.brand = brand
        self.product = product
        self.model_name = model_name
        self.extra = extra
        self.total_duration = total_duration

    def run(self):
        try:
            n = len(self.scene_descriptions)
            if n == 0:
                raise RuntimeError("该视频没有可用的画面镜头描述，无法按画面生成文案。")

            # 走服务端代理
            from utils.llm_proxy import llm_chat

            # 根据总时长估算每行文案的字数上限
            # 正常语速约 3-4 字/秒，按 3.5 字/秒计算
            # 每行文案对应的镜头时长 = 总时长 / n
            if self.total_duration > 0 and n > 0:
                sec_per_shot = self.total_duration / n
                max_chars_per_line = int(sec_per_shot * 3.5)
                # 保底 5 字，上限 40 字
                max_chars_per_line = max(5, min(max_chars_per_line, 40))
                duration_hint = (
                    f"\n本条视频总时长约 {self.total_duration:.1f} 秒，共 {n} 个镜头，"
                    f"平均每个镜头约 {sec_per_shot:.1f} 秒。"
                    f"每行文案请控制在 {max_chars_per_line} 字以内，"
                    f"确保能在对应镜头时长内以正常语速读完。"
                )
            else:
                max_chars_per_line = 22
                duration_hint = ""

            system_prompt = (
                "你是资深电商短视频口播文案撰稿人。用户会给出一个产品的共同背景信息（品牌/品类/型号/卖点），"
                "以及该条组合视频按顺序排列的每一个镜头画面描述。\n"
                "请为这条视频撰写一段用于电商带货的口播文案（旁白），要求：\n"
                f"1. 严格输出 {n} 行，第 i 行对应第 i 个镜头画面，顺序不可打乱。\n"
                f"2. 每行文案贴合对应镜头画面内容（如产品外观、特写、使用场景、价格对比等），"
                f"口语化、有节奏、有卖点和号召力，每行约 5-{max_chars_per_line} 字。{duration_hint}\n"
                "3. 所有行围绕同一款产品（同一型号）展开，整体文案在逻辑与情感上连贯、朗朗上口。\n"
                "4. 若不确定具体参数，用准确的通用描述，切勿编造虚假数字。\n"
                "5. 不要 markdown、不要标题、不要编号、不要解释说明，只输出文案本身，每句独占一行。"
            )
            scenes_str = "\n".join(
                f"{i + 1}. {desc.strip() or '（无画面描述，请根据上下文合理发挥）'}"
                for i, desc in enumerate(self.scene_descriptions)
            )
            user_msg = (
                "产品共同背景：\n"
                f"品牌：{self.brand or '未提供'}\n"
                f"产品/品类：{self.product or '未提供'}\n"
                f"型号：{self.model_name or '未提供'}\n"
                f"补充卖点：{self.extra or '无'}\n\n"
                f"本条视频共有 {n} 个镜头画面，按顺序如下：\n{scenes_str}\n\n"
                f"请按要求生成口播文案，严格输出 {n} 行。"
            )
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                "temperature": 0.6
            }
            res_json = llm_chat(payload["messages"][0]["content"], payload["messages"][1]["content"], model=self.model, timeout=90)  # noqa: E501
            res = _make_mock_response({"choices": [{"message": {"content": res_json}}]}, res_json)
            if res.status_code != 200:
                raise RuntimeError(f"LLM API 请求失败: HTTP {res.status_code} {res.text[:200]}")  # noqa: E501
            data = res.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("大模型返回为空")
            content = choices[0].get("message", {}).get("content", "").strip()
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            # 去掉空行
            lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
            content = "\n".join(lines)
            if not content:
                raise RuntimeError("大模型未生成有效文案")

            # 校验行数是否匹配镜头数
            actual_lines = len(lines)
            if actual_lines != n:
                # 尝试用最后一个镜头"填充"或"合并"来修正行数差异
                if actual_lines < n:
                    # 行数少了：用最后一行补齐
                    last_line = lines[-1] if lines else ""
                    for _ in range(n - actual_lines):
                        content += f"\n{last_line}"
                else:
                    # 行数多了：截断到 N 行
                    content = "\n".join(lines[:n])

            self.finished.emit(content)
        except Exception as e:
            self.error.emit(str(e))



class GenScriptWorker(BaseWorker):
    """根据已勾选的镜头素材描述 + 产品背景 + 时长限制，调用大模型生成口播文案。

    用于「按文案智能匹配」模式：先根据素材生成文案，用户编辑确认后再做镜头匹配。
    输出每行对应一个镜头画面，按顺序排列。
    """
    finished = Signal(str)  # 生成的口播文案（每行一句）

    def __init__(self, api_url, api_key, model, clip_descriptions,
                 brand="", product="", model_name="", extra="", total_duration_sec=30):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.clip_descriptions = clip_descriptions or []
        self.brand = brand
        self.product = product
        self.model_name = model_name
        self.extra = extra
        self.total_duration_sec = total_duration_sec

    def run(self):
        try:
            n = len(self.clip_descriptions)
            if n == 0:
                raise RuntimeError("没有可用的镜头素材描述，无法生成文案。")

            # 走服务端代理
            from utils.llm_proxy import llm_chat

            # 根据总时长估算每行文案的字数上限
            # 正常语速约 3.5 字/秒
            sec_per_shot = self.total_duration_sec / n
            max_chars_per_line = int(sec_per_shot * 3.5)
            max_chars_per_line = max(5, min(max_chars_per_line, 40))
            total_max_chars = max_chars_per_line * n

            duration_hint = (
                f"\n视频总时长限制为 {self.total_duration_sec} 秒，共 {n} 个镜头，"
                f"平均每个镜头约 {sec_per_shot:.1f} 秒。"
                f"每行文案请控制在 {max_chars_per_line} 字以内（总计不超过 {total_max_chars} 字），"
                f"确保能在对应镜头时长内以正常语速（约3.5字/秒）读完。"
            )

            system_prompt = (
                "你是资深电商短视频口播文案撰稿人。用户会给出一个产品的共同背景信息（品牌/品类/型号/卖点），"
                "以及该视频可用的每一个镜头画面描述。\n"
                "请为这条视频撰写一段用于电商带货的口播文案（旁白），要求：\n"
                f"1. 严格输出 {n} 行，第 i 行对应第 i 个镜头画面（按给定顺序），顺序不可打乱。\n"
                f"2. 每行文案贴合对应镜头画面内容（如产品外观、特写、使用场景、价格对比等），"
                f"口语化、有节奏、有卖点和号召力，每行约 5-{max_chars_per_line} 字。{duration_hint}\n"
                "3. 所有行围绕同一款产品（同一型号）展开，整体文案在逻辑与情感上连贯、朗朗上口。\n"
                "4. 若不确定具体参数，用准确的通用描述，切勿编造虚假数字。\n"
                "5. 不要 markdown、不要标题、不要编号、不要解释说明，只输出文案本身，每句独占一行。"
            )
            clips_str = "\n".join(
                f"{i + 1}. {desc.strip() or '（无画面描述，请根据上下文合理发挥）'}"
                for i, desc in enumerate(self.clip_descriptions)
            )
            user_msg = (
                "产品共同背景：\n"
                f"品牌：{self.brand or '未提供'}\n"
                f"产品/品类：{self.product or '未提供'}\n"
                f"型号：{self.model_name or '未提供'}\n"
                f"补充卖点：{self.extra or '无'}\n\n"
                f"本条视频共有 {n} 个镜头画面，按顺序如下：\n{clips_str}\n\n"
                f"请按要求生成口播文案，严格输出 {n} 行。"
            )
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                "temperature": 0.7
            }
            res_json = llm_chat(payload["messages"][0]["content"], payload["messages"][1]["content"], model=self.model, timeout=90)  # noqa: E501
            res = _make_mock_response({"choices": [{"message": {"content": res_json}}]}, res_json)
            if res.status_code != 200:
                raise RuntimeError(f"LLM API 请求失败: HTTP {res.status_code} {res.text[:200]}")  # noqa: E501
            data = res.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("大模型返回为空")
            content = choices[0].get("message", {}).get("content", "").strip()
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            # 去掉空行和编号前缀
            lines = []
            for ln in content.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                # 去掉可能的编号前缀 "1." "1、" "1）"
                import re
                ln = re.sub(r'^\d+[\.、，,）\)]\s*', '', ln).strip()
                if ln:
                    lines.append(ln)
            content = "\n".join(lines)
            if not content:
                raise RuntimeError("大模型未生成有效文案")

            # 校验行数是否匹配镜头数
            actual_lines = len(lines)
            if actual_lines != n:
                if actual_lines < n:
                    last_line = lines[-1] if lines else ""
                    for _ in range(n - actual_lines):
                        content += f"\n{last_line}"
                else:
                    content = "\n".join(lines[:n])

            self.finished.emit(content)
        except Exception as e:
            self.error.emit(str(e))



class BatchAITextRewriteWorker(BaseWorker):
    row_finished = Signal(int, str)  # row_idx, rewritten_text
    progress = Signal(int)           # progress value (0-100)
    finished = Signal()

    def __init__(self, api_url, api_key, model, tasks, temperature=0.5):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.tasks = tasks # list of (row_idx, text)
        self.temperature = temperature

    def run(self):
        try:
            # 走服务端代理
            from utils.llm_proxy import llm_chat

            freedom_pct = int((1.0 - self.temperature) * 100)

            if freedom_pct >= 80:
                rewrite_instruction = (
                    "请对用户提供的文案进行最小幅度的润色，尽量保持原文字词和句式不变，只修正明显的语病或不通顺之处。"
                )
            elif freedom_pct >= 50:
                rewrite_instruction = (
                    "请对用户提供的文案进行较大幅度的改写和润色，可以使用不同的表达方式和词汇，使其更朗朗上口、更生动、更有网感，但必须保留原有的核心意思。"  # noqa: E501
                )
            elif freedom_pct >= 20:
                rewrite_instruction = (
                    "请对用户提供的文案进行大幅改写和重构，显著改变表达方式和句式结构，大胆使用新词汇，大幅提升感染力和传播力，只保留最核心的主题不变。"
                )
            else:
                rewrite_instruction = (
                    "请对用户提供的文案进行彻底的重写和创作，完全抛弃原文的用词和句式，用全新的、极具冲击力的方式表达核心意思，最大化网感和爆款潜力。"
                )

            system_prompt = (
                "你是一个顶尖的短视频脚本与广告文案改写、润色与重构专家。\n"
                + rewrite_instruction + "\n"
                "要求：\n"
                "1. 如果用户提供了多行文案，请对每一行分别进行改写优化，并保持与原行一一对应的行数。\n"
                "2. 每行改写后的文案控制在15-35字之间。\n"
                "3. 请直接返回改写后的纯文本（保持多行格式，每行对应原输入的一行），千万不要返回任何多余的解释、问候、序号或包裹符号（不要有markdown的引文框）！"  # noqa: E501
            )

            total = len(self.tasks)
            for index, (row_idx, input_text) in enumerate(self.tasks):
                content = llm_chat(system_prompt, input_text, model=self.model, timeout=20)  # noqa: E501
                # Clean up markdown code blocks if any
                if content.startswith("```"):
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()

                # strip quotes
                if (content.startswith('"') and content.endswith('"')) or (content.startswith("'") and content.endswith("'")):  # noqa: E501
                    content = content[1:-1].strip()
                if (content.startswith('“') and content.endswith('”')) or (content.startswith('‘') and content.endswith('’')):  # noqa: E501
                    content = content[1:-1].strip()

                self.row_finished.emit(row_idx, content)
                self.progress.emit(int((index + 1) / total * 100))

            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))



class ScriptMatchLLMWorker(BaseWorker):
    finished = Signal(list, list)  # Emits (matched_paths, matched_descriptions)

    def __init__(self, model, rewritten_text, candidate_clips, split_descriptions):
        super().__init__()
        self.model = model
        self.rewritten_text = rewritten_text
        self.candidate_clips = candidate_clips
        self.split_descriptions = split_descriptions

    def run(self):
        try:
            from utils.llm_proxy import llm_chat

            rewritten_lines = [line.strip() for line in self.rewritten_text.split("\n") if line.strip()]  # noqa: E501
            if not rewritten_lines:
                raise ValueError("改写后的文案为空。")

            candidate_list_str = ""
            for idx, clip in enumerate(self.candidate_clips, 1):
                desc = self.split_descriptions.get(clip, "无描述")
                filename = os.path.basename(clip)
                candidate_list_str += f"{idx}. 视频: {filename}, 画面描述: {desc}\n"

            rewritten_list_str = ""
            for idx, line in enumerate(rewritten_lines, 1):
                rewritten_list_str += f"{idx}. {line}\n"

            system_prompt = (
                "你是一个视频智能剪辑匹配专家。你的任务是分析改写后的文案（按行分开），以及待排列的视频镜头候选列表（包含编号、文件名和画面描述）。\n"
                "请为改写后文案的每一行，从待排列候选镜头中找出最匹配的一个镜头。请按顺序匹配，并严格以 JSON 格式返回结果。\n"  # noqa: E501
                "JSON 格式要求如下：一个包含对象的数组，每个对象包含 'line_index'（从1开始的文案行号）和 'best_match_shot_index'（最匹配的候选镜头编号，1到候选总数之间）。\n"  # noqa: E501
                "例如：\n"
                "[{\"line_index\": 1, \"best_match_shot_index\": 3}, {\"line_index\": 2, \"best_match_shot_index\": 1}]\n"  # noqa: E501
                "请只返回 JSON 数据本身，不要用 markdown 包裹，不要有任何其他解释或废话。"
            )
            user_content = (
                f"待排列镜头候选列表：\n{candidate_list_str}\n\n"
                f"改写后的新文案列表：\n{rewritten_list_str}"
            )

            content = llm_chat(system_prompt, user_content, model=self.model, timeout=45)  # noqa: E501

            match_results = safe_json_parse(content)
            if not isinstance(match_results, list):
                raise RuntimeError(
                    f"脚本匹配 LLM 未返回 JSON 数组，原始返回:\n{str(content)[:300]}")

            matched_paths = []
            matched_descs = []
            for item in match_results:
                shot_idx = int(item["best_match_shot_index"]) - 1
                line_idx = int(item["line_index"]) - 1
                desc = rewritten_lines[line_idx] if 0 <= line_idx < len(rewritten_lines) else ""  # noqa: E501

                if 0 <= shot_idx < len(self.candidate_clips):
                    matched_paths.append(self.candidate_clips[shot_idx])
                else:
                    matched_paths.append(self.candidate_clips[0])
                matched_descs.append(desc)

            if not matched_paths:
                raise ValueError("未能匹配到任何有效镜头。")

            self.finished.emit(matched_paths, matched_descs)

        except Exception as e:
            self.error.emit(str(e))
