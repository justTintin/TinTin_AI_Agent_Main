"""智能混剪 - 拼接/合成阶段 Worker：标准化转码拼接、配音烧字幕、最终混音。"""
import contextlib
import os
import random
import re
import shutil
import subprocess
import traceback

from gui.montage.utils_media import find_ffmpeg, get_media_duration
from PySide6.QtCore import Signal
from utils.base_worker import BaseWorker
from utils.ffmpeg_utils import (
    CREATE_NO_WINDOW,
    CompletedProcess,
    TimeoutExpired,
)
from utils.ffmpeg_utils import (
    run as _run_proc,
)
from utils.hwaccel import get_video_encode_args
from utils.logger_utils import log


class _TranscodeSkip(Exception):  # noqa: N818
    """标准化转码单个镜头时，因文件损坏/不可读/转码失败而需跳过。
    携带的提示文案会原样 emit 到 stage 信号，供 UI 展示。"""


# ── 剪映安全框（safe area）：所有花字/字幕必须落在该区域内，避免被平台 UI
# 遮挡或出框。依据剪映竖屏(9:16)默认安全框：左右各约 8% 宽、顶部约 8% 高、
# 底部约 10% 高（底部更大，避开抖音点赞/评论交互区）。
SAFE_X = 0.08        # 左右安全边距（相对宽度）
SAFE_TOP = 0.08      # 顶部安全边距（相对高度）
SAFE_BOTTOM = 0.10   # 底部安全边距（相对高度）
# 字幕：字号相对高度（再大一号）+ 底边距安全框下沿 2%（整体上移）
SUB_FONT_SCALE = 0.035
SUB_BOTTOM_GAP = 0.02
# 字幕自动折行：单行超过 SUB_MAX_LINE_WEIGHT 等效字（中文=1、ASCII≈0.55）
# 自动折为多行上下堆叠（均衡断点，优先在空格/标点处断开）；行距相对高度
SUB_MAX_LINE_WEIGHT = 13.0
SUB_ASCII_WEIGHT = 0.55
SUB_LINE_GAP = 0.012
_SUB_BREAK_CHARS = set("，。！？、；：,.!?;: \t")

_SAFE_X_EXPR = f"w*{SAFE_X}"
_SAFE_TOP_EXPR = f"h*{SAFE_TOP}"
_SAFE_BOTTOM_EDGE = f"h*(1-{SAFE_BOTTOM})"        # 安全框下沿 y 表达式
_SAFE_BOTTOM_ANCHOR = f"{_SAFE_BOTTOM_EDGE}-text_h-h*{SUB_BOTTOM_GAP}"  # 元素底边贴框

# 花字出现位置 → drawtext x/y 表达式（fontsize=h*0.08，text_w/text_h 为花字自身尺寸）。
# 全部落在剪映安全框内：顶部 y=SAFE_TOP、左右 x=SAFE_X、底部元底边=安全框下沿-1%。
# 与 docs/服务端花字烧制需求.md 保持一致。
FANCY_POSITIONS = {
    "upper_middle": {"label": "中上", "x": "(w-text_w)/2", "y": "h*0.3"},
    "top":          {"label": "顶部居中", "x": "(w-text_w)/2", "y": _SAFE_TOP_EXPR},
    "center":       {"label": "画面正中", "x": "(w-text_w)/2", "y": "(h-text_h)/2"},
    "bottom":       {"label": "底部居中", "x": "(w-text_w)/2", "y": _SAFE_BOTTOM_ANCHOR},
    "top_left":     {"label": "左上角", "x": _SAFE_X_EXPR, "y": _SAFE_TOP_EXPR},
    "top_right":    {"label": "右上角", "x": f"w-text_w-{_SAFE_X_EXPR}", "y": _SAFE_TOP_EXPR},  # noqa: E501
    "bottom_left":  {"label": "左下角", "x": _SAFE_X_EXPR, "y": _SAFE_BOTTOM_ANCHOR},
    "bottom_right": {"label": "右下角", "x": f"w-text_w-{_SAFE_X_EXPR}", "y": _SAFE_BOTTOM_ANCHOR},  # noqa: E501
}

# 花字出现时机：跟随对应字幕行，提前 FANCY_LEAD_SEC 秒出现、该行字幕结束时消失；
# 该行文案无卖点时不出现，等待下一个花字时机。
FANCY_LEAD_SEC = 0.3
FANCY_MAX_LEN = 10     # 花字内容最大字符数（价格/参数串超出截断）
# 花字重叠消解：两个花字时间窗过近会在同一位置重叠渲染——
# FANCY_MIN_GAP_SEC 相邻花字最小间隔；FANCY_MIN_DISPLAY_SEC 压缩前一个
# 结束时间的下限（低于它宁可丢弃后一个），规则见 resolve_fancy_overlaps。
FANCY_MIN_GAP_SEC = 0.05
FANCY_MIN_DISPLAY_SEC = 0.4
FANCY_MAX_PER_VIDEO = 3  # 每条视频花字数量上限（卖点 2-3 个，不足则有多少用多少）

# ── 卖点提取（花字内容自动取自口播文案，不再手动输入）──
# 优先级：价格 > 数字参数 > 关键词。与 docs/服务端花字烧制需求.md 2.3 同步维护。
# 1) 价格：如「只要199元」「低至59.9元」
_FANCY_PRICE_RE = re.compile(r"(?:仅|只要|低至|到手|券后)?\d+(?:\.\d+)?元")
# 2) 数字参数：前置修饰 0-4 字 + 数字 + 已知单位（白名单，长词在前），如「续航70小时」「8000DPI」「仅重59克」
_FANCY_UNIT = ("小时|分钟|秒钟|毫安时|毫安|mAh|千克|公斤|kg|KG|Kg|千瓦|kW|毫伏|mV|"
               "毫米|厘米|分米|英寸|千米|公里|km|cm|mm|克|瓦|伏|升|毫升|ml|mL|"
               "赫兹|Hz|kHz|分贝|dB|℃|°C|%|％|DPI|dpi|天|周|月|年|米|寸|度|W|V|G|g|L|倍|核|轴|键|帧|级|档|声")  # noqa: E501
_FANCY_NUM_RE = re.compile(rf"[\u4e00-\u9fa5A-Za-z]{{0,4}}\d+(?:\.\d+)?(?:{_FANCY_UNIT})")
# 3) 关键词卖点：无数字的强卖点词（按行内首个命中取词）
_FANCY_KEYWORDS = (
    "超轻", "超薄", "超长续航", "超静音", "大容量", "快充", "闪充", "无线充电",
    "防水", "防尘", "降噪", "折叠", "便携", "旗舰", "爆款", "新款", "限量",
    "免打孔", "免安装", "持久续航", "高清", "巨幕", "一机多用",
    "电量持久", "电量充足", "放电均衡", "不易漏液", "输出稳定", "经久耐用", "密封性",
    "平价",
)


def extract_fancy_word(line_text):
    """从单行文案提取一个卖点作为花字内容（价格 > 数字参数 > 关键词）。

    无卖点返回 ""，调用方跳过该行（不产生花字时机）。
    """
    words = extract_fancy_words_in_line(line_text, limit=1)
    return words[0] if words else ""


def extract_fancy_words_in_line(line_text, limit=FANCY_MAX_PER_VIDEO):
    """单行内提取多个卖点（按出现位置排序）：价格×n + 数字参数×n + 关键词。

    口播文案常为一整行（无换行），每行只取 1 个会漏掉大部分卖点；
    这里按正则 finditer 收集行内全部命中，区间重叠去重（价格优先），
    按位置排序后取前 limit 个。"""
    t = (line_text or "")
    if not t.strip():
        return []
    hits = []  # (start, end, word)
    for m in _FANCY_PRICE_RE.finditer(t):
        hits.append((m.start(), m.end(), m.group(0)[:FANCY_MAX_LEN]))
    for m in _FANCY_NUM_RE.finditer(t):
        if any(s <= m.start() < e or s < m.end() <= e for s, e, _ in hits):
            continue  # 与价格区间重叠（如「只要199元」同时命中参数）
        hits.append((m.start(), m.end(), m.group(0)[:FANCY_MAX_LEN]))

    def _occupied(pos):
        return any(s <= pos < e for s, e, _ in hits)

    for kw in _FANCY_KEYWORDS:
        if len(hits) >= limit:
            break  # 已凑够上限，无需再扫关键词
        pos = t.find(kw)
        while pos != -1:
            if not _occupied(pos):
                hits.append((pos, pos + len(kw), kw))
                break
            pos = t.find(kw, pos + 1)
    hits.sort(key=lambda h: h[0])
    words = []
    for _s, _e, w in hits:
        if w and (not words or words[-1] != w):
            words.append(w)
        if len(words) >= limit:
            break
    return words


def extract_fancy_words_from_text(text, max_words=FANCY_MAX_PER_VIDEO):
    """整段文案提取卖点花字：逐行（行内多卖点），保持行序，跨行累计到 max_words。

    供两处使用：① VideoDubbingWorker 烧制时的花字事件；② Step3 UI 的
    「花字预览」（让用户在文案侧看见每个视频将生成哪些花字）。
    """
    words = []
    for line in (text or "").splitlines():
        for w in extract_fancy_words_in_line(line, limit=max_words - len(words)):
            if w and (not words or words[-1] != w):
                words.append(w)
            if len(words) >= max_words:
                return words
    return words


def resolve_fancy_overlaps(events, min_gap=FANCY_MIN_GAP_SEC,
                           min_display=FANCY_MIN_DISPLAY_SEC):
    """消解花字时间窗重叠：按开始时间排序后，优先压缩前一花字的结束时间，

    压不动（会低于最短显示时长）则丢弃后一个。

    重叠来源：① 前一花字随字幕行结束才消失，后一花字提前 FANCY_LEAD_SEC
    出现——字幕行衔接紧密（间隔 < 0.3s）时时间窗交叠；② 行内多卖点均分
    时间窗时最短显示约束 max(s+0.2, e) 使后段越界压到下一段。
    服务端烧制需保持同一规则（见 docs/服务端花字烧制需求.md 2.3）。
    """
    out = []
    for word, s, e in sorted(events, key=lambda ev: (ev[1], ev[2])):
        # 仅严格交叠（s < pe）才算重叠：背靠背（s == pe）是行内多卖点依次
        # 出现的正常形态，between 含端点的 1 帧交叠可忽略
        if out and s < out[-1][2]:
            prev_word, ps, pe = out[-1]
            # 优先压缩前一花字：结束提前到 next.start - gap，但不短于最短显示
            new_pe = max(s - min_gap, ps + min_display)
            if new_pe < pe:
                out[-1] = (prev_word, ps, new_pe)
            if s < out[-1][2] + min_gap:
                continue  # 压不动（或压完仍重叠）→ 丢弃后一个，保先到的
        out.append((word, s, e))
    return out


_SUB_PRON_RE = re.compile(r"(?<=[0-9A-Za-z])\([^\(\)]{1,12}\)")


def _strip_pron_annotation(text):
    """去掉读音标注括号：555(三五)电池 → 555电池。

    读音标注供 TTS 用（voice_workers._preprocess_tts_text 把括号内作为
    读法替换），字幕/花字显示原文；仅当括号前紧贴字母/数字时识别。
    """
    return _SUB_PRON_RE.sub("", text or "")


def _sub_line_weight(text):
    """字幕行等效宽度：中文/全角=1，ASCII/半角≈0.55。"""
    return sum(SUB_ASCII_WEIGHT if ord(c) < 0x2E80 else 1.0 for c in text)


def _is_ascii_alnum(ch):
    return ch.isascii() and ch.isalnum()


# 量词/单位字：数字后紧跟这些字时不可作为字幕分段断点（如 199|元、59|克，
# 数字与单位是一个词，拆开观感割裂）
_SUB_UNIT_CHARS = set("元角分厘克千克吨斤两米寸升瓦伏安时天年月日号度倍颗粒枚张片支盒包瓶罐箱袋页行站次趟遍")  # noqa: E501


def _bad_sub_boundary(chars, i):
    """字幕分段禁断边界：英数连续串中间、数字后紧跟量词单位（199|元）。"""
    a, b = chars[i - 1], chars[i]
    if _is_ascii_alnum(a) and _is_ascii_alnum(b):
        return True
    if a.isdigit() and b in _SUB_UNIT_CHARS:
        return True
    return False


def _snap_break(chars, prefer, lo):
    """断点选择（按优先级）：

    1. prefer±2 内的空格/标点（吸附，断点跳过分隔符）；
    2. prefer±2 内不在英文/数字连续串中间的字符边界（如 中|8000、DPI|调，
       杜绝 8000|DPI 硬切）；
    3. 全行范围内离 prefer 最近的非英文数字内部边界（兑底）；
    纯英文/数字长串（无任何可用边界）返回 None 由调用方硬切。
    """
    best = None
    for i in range(max(lo + 1, prefer - 2), min(len(chars) - 1, prefer + 2) + 1):
        if chars[i] in _SUB_BREAK_CHARS or chars[i - 1] in _SUB_BREAK_CHARS:
            dist = abs(i - prefer)
            if best is None or dist < best[0]:
                best = (dist, i)
    if best is not None:
        i = best[1]
        if chars[i] in _SUB_BREAK_CHARS:
            i += 1  # 断点跳过分隔符
        return i
    # 2) ±3 内的可用边界（不在英数连续串中间、不拆数字+量词，如 9|元）
    for i in range(max(lo + 1, prefer - 3), min(len(chars) - 1, prefer + 3) + 1):
        if not _bad_sub_boundary(chars, i):
            return i
    # 3) 全范围最近的可用边界
    best = None
    for i in range(lo + 1, len(chars)):
        if not _bad_sub_boundary(chars, i):
            dist = abs(i - prefer)
            if best is None or dist < best[0]:
                best = (dist, i)
    return best[1] if best else None


def wrap_subtitle_line(line_text):
    """超长字幕行自动折行（剪映竖屏安全框内单行约容 13 个等效字）。

    - 不超宽：返回 [原行]；
    - 超宽：按等效宽度均衡拆成多行，断点优先吸附到空格/标点（如
      「续航持久伴闯关 GPW3手感真带劲」→「续航持久伴闯关」/「GPW3手感真带劲」，
      不会在 GPW3 中间硬断）；空行返回 []。
    """
    text = (line_text or "").strip()
    if not text:
        return []
    total = _sub_line_weight(text)
    if total <= SUB_MAX_LINE_WEIGHT:
        return [text]
    # 按上限-1 计算段数：断点不能落在英文/数字连续串中间（离散性会让
    # 某段超出均值），留 1 字余量保证吸附/回退后每段仍 ≤ 上限
    n_parts = max(2, int(-(-total // max(1.0, SUB_MAX_LINE_WEIGHT - 1.0))))
    chars = list(text)
    weights = [SUB_ASCII_WEIGHT if ord(c) < 0x2E80 else 1.0 for c in chars]
    # 每个字符之前的累计宽度（断点候选基准）
    cum_before = []
    acc = 0.0
    for w in weights:
        cum_before.append(acc)
        acc += w

    bounds = [0]
    for part in range(1, n_parts):
        target = total * part / n_parts
        lo = bounds[-1] + 1
        if lo >= len(chars):
            break
        # 兑底：任意字符边界里离 target 最近的
        boundary = min(range(lo, len(chars)), key=lambda i: abs(cum_before[i] - target))
        b = boundary
        # 优先：±2 范围内的空格/标点/非英数内部断点（_snap_break）
        snapped = _snap_break(chars, boundary, bounds[-1])
        if snapped is not None and bounds[-1] < snapped < len(chars):
            b = snapped
        # 段宽约束：吸附/回退候选不得让前段超过单行上限（均衡边界天然最接近）
        lo_w = cum_before[bounds[-1]]
        if cum_before[b] - lo_w > SUB_MAX_LINE_WEIGHT + 1e-9 \
                and cum_before[boundary] - lo_w <= SUB_MAX_LINE_WEIGHT + 1e-9:
            b = boundary
        b = min(b, len(chars) - 1)
        bounds.append(b)
    bounds.append(len(chars))

    parts = []
    for b0, b1 in zip(bounds, bounds[1:]):
        seg = "".join(chars[b0:b1]).strip(" ，,、")
        if seg:
            parts.append(seg)
    return parts or [text]


class VideoConcatWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(list)  # Emits list of generated files absolute paths

    def __init__(self, selected_clips, output_dir, layout_mode, recombine_mode, target_clip_count, batch_count, split_descriptions=None, randomness="medium", selected_descriptions_list=None, transition="fade", beat_times=None, music_path="", music_range=None, lut_path=""):  # noqa: E501
        super().__init__()
        self.selected_clips = selected_clips
        self.output_dir = output_dir
        self.layout_mode = layout_mode
        self.recombine_mode = recombine_mode
        self.target_clip_count = target_clip_count
        self.batch_count = batch_count
        self.split_descriptions = split_descriptions or {}
        self.randomness = randomness
        self.selected_descriptions_list = selected_descriptions_list
        self.transition = transition or "fade"
        # 音乐卡点模式参数：beat_times=相对裁剪后音频的节拍点，music_range=[起始,结束]绝对时间
        self.beat_times = list(beat_times or [])
        self.music_path = music_path or ""
        self.music_range = list(music_range or [])
        self.lut_path = (lut_path or "").strip()

    def _probe_resolution(self, clip):
        """用 ffprobe 读取视频显示分辨率（已考虑旋转），失败返回 None。

        手机竖拍视频 stream 存的是横屏像素（如 1920x1080），但带 rotate=90 元数据，
        必须读取旋转角度后交换宽高，才能得到正确的显示分辨率。
        """
        try:
            from utils.platform_utils import find_ffprobe
            ffprobe = find_ffprobe()
            if not os.path.isfile(ffprobe):
                ff = find_ffmpeg()
                ffprobe = ff.replace("ffmpeg", "ffprobe")
            cf = CREATE_NO_WINDOW
            cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
                   "-show_entries", "stream=width,height,side_data_list,tag:rotate",
                   "-of", "json", clip]
            r = _run_proc(cmd, capture_output=True, text=True,
                               creationflags=cf, timeout=15)
            if r.returncode != 0 or not (r.stdout or "").strip():
                return None
            import json as _json
            data = _json.loads(r.stdout)
            streams = data.get("streams", [])
            if not streams:
                return None
            s = streams[0]
            w = int(s.get("width", 0) or 0)
            h = int(s.get("height", 0) or 0)
            if w <= 0 or h <= 0:
                return None
            # 检测旋转角度：优先从 side_data 读，回退到 tag:rotate
            rotation = 0
            for sd in (s.get("side_data_list") or []):
                rot_val = sd.get("rotation")
                if rot_val is not None:
                    try:
                        rotation = int(float(rot_val))
                    except (TypeError, ValueError):
                        pass
                    break
            if rotation == 0:
                tag_rot = s.get("tags", {}).get("rotate")
                if tag_rot:
                    try:
                        rotation = int(float(tag_rot))
                    except (TypeError, ValueError):
                        pass
            # 90/270 度旋转时交换宽高
            if rotation in (90, -90, 270, -270):
                w, h = h, w
            return w, h
        except (OSError, subprocess.SubprocessError) as e:
            log.warning(f"探测原视频分辨率失败: {e}")
        return None

    def _transcode_one(self, i, clip, ffmpeg_path, ffprobe_path, temp_dir, width, height):  # noqa: E501
        """标准化转码单个镜头到 temp_dir/norm_{i:04d}.mp4。

        纯函数式：只读入参，输出独立文件，无实例状态写入，线程安全。
        文件损坏/探测失败/转码失败时抛 _TranscodeSkip（携带提示文案），由调用方决定跳过。
        成功返回 norm_out 绝对路径。
        """
        clip_abspath = os.path.abspath(clip)
        name = os.path.basename(clip)
        # 1) 完整性快检
        if not os.path.isfile(clip_abspath) or os.path.getsize(clip_abspath) < 1024:
            raise _TranscodeSkip(f"注意： 跳过损坏/过小文件: {name}")
        probe_cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", clip_abspath]
        try:
            probe_r = _run_proc(probe_cmd, capture_output=True, text=True, timeout=15,
                                     creationflags=CREATE_NO_WINDOW)
            if probe_r.returncode != 0 or not probe_r.stdout.strip():
                raise _TranscodeSkip(f"注意： 跳过无法读取的文件: {name}")
        except _TranscodeSkip:
            raise
        except (OSError, subprocess.SubprocessError) as e:
            raise _TranscodeSkip(f"注意： 跳过探测失败的文件: {name}") from e

        # 2) 转码：缩放/填充黑边/统一 30fps，强制软编 libx264 superfast crf23
        # 标准化转码阶段必须强制软编，避免 GPU 编码器驱动/并发会话在后台线程中
        # 出现 0% 占用假死；xfade/LUT 阶段已强制软编，此处保持一致。
        norm_out = os.path.join(temp_dir, f"norm_{i:04d}.mp4")
        # format=yuv420p：源素材可能是 10-bit（yuv420p10le/HDR），AMF 等硬件编码器
        # 不支持 10-bit 输入，必须在滤镜链显式转 8-bit，否则转码全部失败。
        vf_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p"  # noqa: E501

        clip_dur = 0.0
        try:
            if probe_r.returncode == 0 and probe_r.stdout.strip():
                clip_dur = float(probe_r.stdout.strip())
        except (TypeError, ValueError):
            pass
        encode_timeout = max(60, int(clip_dur * 10)) if clip_dur > 0 else 300

        cmd = [
            ffmpeg_path, "-y", "-i", clip_abspath,
            "-vf", vf_filter,
            *get_video_encode_args(crf=23, preset="superfast", force_software=True),
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            norm_out
        ]
        try:
            r = _run_proc(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=encode_timeout)  # noqa: E501
        except TimeoutExpired as e:
            log.warning(f"标准化转码单镜头超时({encode_timeout}s): {name}")
            raise _TranscodeSkip(f"注意： 转码超时，跳过: {name}") from e
        if r.returncode != 0:
            log.warning(f"标准化转码单镜头失败，跳过: {clip}\n{r.stderr[-300:]}")
            raise _TranscodeSkip(f"注意： 转码失败，跳过: {name}")
        return norm_out

    # ffmpeg xfade 转场类型映射
    _XFADE_MAP = {
        "fade": "fade",
        "dissolve": "dissolve",
        "slideleft": "slideleft",
        "slideright": "slideright",
        "slideup": "slideup",
        "slidedown": "slidedown",
        "zoomin": "zoomin",
        "zoomout": "zoomout",
    }
    # 单个 xfade filter_complex 中最多同时解码的镜头数。超过此值时拆分为多个
    # chunk 分别做 xfade，再用无损 concat 合并，避免镜头过多导致 filter graph
    # 过大、初始化缓慢甚至 ffmpeg 假死。
    _XFADE_CHUNK_SIZE = 12

    def _simple_concat(self, ffmpeg_path, clips, out_file, temp_dir, batch_idx):
        """无损 concat（无转场）。单镜头直接复制；多镜头走 concat demuxer。
        若启用 LUT，使用 filter_complex 给每个镜头做 lut3d 后 concat（需重编码）。
        """
        if not clips:
            return CompletedProcess(args=[], returncode=1, stderr="no clips")

        lut_path = self.lut_path
        if lut_path and not os.path.isfile(lut_path):
            lut_path = ""

        if len(clips) == 1:
            if lut_path:
                lut_esc = lut_path.replace("\\", "/").replace(":", "\\:")
                vf = f"lut3d='{lut_esc}',format=yuv420p"
                self.stage.emit("单个镜头 LUT 还原（软件编码）...")
                cmd = [ffmpeg_path, "-y", "-i", clips[0], "-vf", vf,
                       *get_video_encode_args(crf=23, preset="superfast", force_software=True),  # noqa: E501
                       "-c:a", "aac", "-ar", "44100", "-ac", "2",
                       "-movflags", "+faststart", out_file]
            else:
                cmd = [ffmpeg_path, "-y", "-i", clips[0], "-c", "copy", out_file]
            return _run_proc(cmd, capture_output=True, text=True,
                                  creationflags=CREATE_NO_WINDOW)

        # 多镜头 + LUT：需要在 filter_complex 里逐个应用 lut3d 后 concat
        if lut_path:
            lut_esc = lut_path.replace("\\", "/").replace(":", "\\:")
            n = len(clips)
            video_parts = [f"[{i}:v]lut3d='{lut_esc}',format=yuv420p[v{i}];" for i in range(n)]  # noqa: E501
            concat_labels = "".join(f"[v{i}]" for i in range(n))
            audio_labels = "".join(f"[{i}:a]" for i in range(n))
            filter_complex = (
                "".join(video_parts) +
                f"{concat_labels}concat=n={n}:v=1:a=0[vout];" +
                f"{audio_labels}concat=n={n}:v=0:a=1[aout]"
            )
            cmd = [ffmpeg_path, "-y"] + [arg for i, clip in enumerate(clips) for arg in ("-i", clip)] + [  # noqa: E501
                "-filter_complex", filter_complex,
                "-map", "[vout]", "-map", "[aout]",
                *get_video_encode_args(crf=23, preset="superfast", force_software=True),
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart",
                out_file
            ]
            return _run_proc(cmd, capture_output=True, text=True,
                                  creationflags=CREATE_NO_WINDOW)

        concat_txt = os.path.join(temp_dir, f"concat_simple_{batch_idx}_{os.getpid()}.txt")  # noqa: E501
        with open(concat_txt, "w", encoding="utf-8") as f:
            for c in clips:
                safe_path = c.replace("\\", "/")
                f.write(f"file '{safe_path}'\n")
        cmd = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", out_file]  # noqa: E501
        return _run_proc(cmd, capture_output=True, text=True,
                              creationflags=CREATE_NO_WINDOW)

    def _run_xfade(self, ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx, lut_path):  # noqa: E501
        """对少量镜头直接构建 xfade 滤镜链拼接。超过 _XFADE_CHUNK_SIZE 的镜头应走
        _run_xfade_chunked 分块处理。
        """
        xfade_type = self._XFADE_MAP.get(self.transition, "fade")
        transition_dur = 0.5

        self.stage.emit(f"正在合成转场视频 ({len(clips)} 个镜头){'，LUT 已启用' if lut_path else ''}...")  # noqa: E501

        durations = []
        for clip in clips:
            dur = 0.0
            try:
                cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                       "-of", "csv=p=0", clip]
                pr = _run_proc(cmd, capture_output=True, text=True, timeout=10,
                                    creationflags=CREATE_NO_WINDOW)
                if pr.returncode == 0 and pr.stdout.strip():
                    dur = float(pr.stdout.strip())
            except (OSError, subprocess.SubprocessError):
                pass
            if dur <= 0:
                dur = 5.0
            durations.append(dur)

        n = len(clips)
        filter_parts = []
        inputs = []
        for clip in clips:
            inputs += ["-i", clip]

        if lut_path:
            lut_esc = lut_path.replace("\\", "/").replace(":", "\\:")
            for i in range(n):
                filter_parts.append(f"[{i}:v]lut3d='{lut_esc}',format=yuv420p[lut{i}];")

        prev_label = "lut0" if lut_path else "0:v"
        accumulated = durations[0]
        for i in range(1, n):
            offset = max(0, accumulated - transition_dur)
            out_label = f"v{i:02d}"
            src_label = f"lut{i}" if lut_path else f"{i}:v"
            filter_parts.append(
                f"[{prev_label}][{src_label}]xfade=transition={xfade_type}:duration={transition_dur}:offset={offset:.3f}[{out_label}]"  # noqa: E501
            )
            prev_label = out_label
            accumulated = offset + transition_dur + (durations[i] - transition_dur)

        audio_filter_parts = []
        for i in range(n):
            audio_filter_parts.append(f"[{i}:a]")
        audio_filter_parts.append(f"concat=n={n}:v=0:a=1[aout]")
        audio_filter = "".join(audio_filter_parts)

        final_vlabel = prev_label
        filter_complex = ";".join(filter_parts) + ";" + audio_filter

        total_dur = sum(durations)
        timeout = max(120, int(total_dur * 3) + n * 20)

        cmd = [ffmpeg_path, "-y"] + inputs + [
            "-filter_complex", filter_complex,
            "-map", f"[{final_vlabel}]",
            "-map", "[aout]",
            *get_video_encode_args(crf=23, preset="superfast", force_software=True),
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            out_file
        ]
        try:
            return _run_proc(cmd, capture_output=True, text=True,
                                  creationflags=CREATE_NO_WINDOW, timeout=timeout)
        except TimeoutExpired:
            log.warning(f"xfade 拼接 {len(clips)} 个镜头超时({timeout}s)，输出文件未生成，准备降级")
            return CompletedProcess(args=cmd, returncode=1,
                                               stderr=f"xfade timeout after {timeout}s")

    def _run_xfade_chunked(self, ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx, lut_path):  # noqa: E501
        """镜头数过多时拆块处理，每块内部做 xfade，最后无损 concat 合并各块。"""
        chunk_size = self._XFADE_CHUNK_SIZE
        chunks = [clips[i:i + chunk_size] for i in range(0, len(clips), chunk_size)]
        chunk_files = []
        for idx, chunk in enumerate(chunks):
            self.stage.emit(f"转场拼接分块 {idx + 1}/{len(chunks)} ({len(chunk)} 个镜头)...")
            chunk_out = os.path.join(temp_dir, f"chunk_{batch_idx}_{idx}_{os.getpid()}.mp4")  # noqa: E501
            r = self._run_xfade(ffmpeg_path, ffprobe_path, chunk, chunk_out, temp_dir,
                                f"{batch_idx}_{idx}", lut_path)
            if r.returncode != 0 or not os.path.isfile(chunk_out):
                log.warning(f"分块 {idx + 1} xfade 失败，该块改用无损 concat: {r.stderr[-200:]}")
                r2 = self._simple_concat(ffmpeg_path, chunk, chunk_out, temp_dir,
                                         f"{batch_idx}_{idx}_fallback")
                if r2.returncode != 0 or not os.path.isfile(chunk_out):
                    return CompletedProcess(args=[], returncode=1,
                        stderr=f"chunk {idx} fallback concat failed: {r2.stderr}")
            chunk_files.append(chunk_out)

        return self._simple_concat(ffmpeg_path, chunk_files, out_file, temp_dir,
                                    f"chunked_{batch_idx}")

    def _concat_with_transition(self, ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx):  # noqa: E501
        """用 ffmpeg xfade 滤镜拼接镜头，实现转场动画。可选 LUT 色彩还原。

        注意：xfade 是复杂 CPU 滤镜，其输出像素格式/帧时序与硬件编码器（AMF/NVENC/QSV）
        配合时容易出现卡顿/假死。因此本阶段统一强制使用 libx264 软编，确保稳定性。
        当 LUT 启用时，也在 lut3d 后显式转 yuv420p，避免 10-bit/HDR 素材格式不兼容。
        为避免镜头数过多时 filter graph 过大导致初始化/编码假死，超过阈值会自动分块；
        若用户选择"无转场"或 xfade 超时/失败，自动降级为无损 concat。
        """
        if not clips:
            return CompletedProcess(args=[], returncode=1, stderr="no clips")

        # 读取 LUT 配置
        lut_path = self.lut_path
        if lut_path and not os.path.isfile(lut_path):
            log.warning(f"[LUT] 文件不存在，跳过: {lut_path}")
            lut_path = ""
        if lut_path:
            log.info(f"[LUT] 应用色彩还原: {os.path.basename(lut_path)}")

        # 无转场 / 单镜头：直接走无损 concat
        if self.transition == "none" or len(clips) <= 1:
            return self._simple_concat(ffmpeg_path, clips, out_file, temp_dir, batch_idx)  # noqa: E501

        # 镜头数在阈值内：直接 xfade；超过阈值：分块 xfade
        if len(clips) <= self._XFADE_CHUNK_SIZE:
            return self._run_xfade(ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx, lut_path)  # noqa: E501
        return self._run_xfade_chunked(ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx, lut_path)  # noqa: E501

    def _compose_beat_video(self, ffmpeg_path, norm_clips, out_file, temp_dir):
        """音乐卡点合成：每个镜头裁剪到对应节拍区间时长，硬切拼接（保证卡点精准），
        再叠加裁剪后的音乐片段（替换原声）。

        beat_times: 相对裁剪后音频的节拍点（第一个为 0），相邻节拍形成一个镜头槽位。
        music_range: [起始秒, 结束秒] 绝对时间，从原音乐裁剪出对应片段。
        """
        beats = self.beat_times
        n_slots = max(0, len(beats) - 1)
        if n_slots <= 0 or not norm_clips:
            raise RuntimeError("卡点合成失败：节拍点或镜头为空")

        # 镜头数与槽位数对齐（不足循环填充，多余截断）
        seq = []
        for i in range(n_slots):
            seq.append(norm_clips[i % len(norm_clips)])

        # 1) 每个镜头裁剪到节拍区间时长（硬切，不加转场以保证卡点精准）
        cut_paths = []
        total_dur = 0.0
        for i in range(n_slots):
            dur = max(0.1, beats[i + 1] - beats[i])
            src = seq[i]
            cut = os.path.join(temp_dir, f"beatcut_{i:04d}.mp4")
            cmd = [ffmpeg_path, "-y", "-i", src,
                   "-t", f"{dur:.3f}",
                   "-an",  # 去除原声，后续统一叠加音乐
                   *get_video_encode_args(crf=20, preset="veryfast"),
                   "-pix_fmt", "yuv420p",
                   cut]
            r = _run_proc(cmd, capture_output=True, text=True,
                               creationflags=CREATE_NO_WINDOW)
            if r.returncode != 0 or not os.path.isfile(cut):
                log.warning(f"卡点裁剪镜头失败: {r.stderr[-200:]}")
                raise RuntimeError(f"卡点裁剪第 {i+1} 个镜头失败")
            cut_paths.append(cut)
            total_dur += dur

        # 2) concat 拼接（硬切）
        concat_txt = os.path.join(temp_dir, "beat_concat.txt")
        with open(concat_txt, "w", encoding="utf-8") as f:
            for c in cut_paths:
                f.write(f"file '{c.replace(chr(92), '/')}'\n")
        noaudio = os.path.join(temp_dir, "beat_noaudio.mp4")
        cmd = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
               "-c", "copy", noaudio]
        r = _run_proc(cmd, capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0 or not os.path.isfile(noaudio):
            raise RuntimeError(f"卡点拼接失败：{(r.stderr or '')[-200:]}")

        # 3) 叠加裁剪后的音乐片段（替换原声）
        if self.music_path and os.path.isfile(self.music_path):
            m_start = float(self.music_range[0]) if len(self.music_range) >= 1 else 0.0
            m_end = float(self.music_range[1]) if len(self.music_range) >= 2 else 0.0
            m_dur = max(0.1, m_end - m_start) if m_end > m_start else total_dur
            cmd = [ffmpeg_path, "-y",
                   "-i", noaudio,
                   "-ss", f"{m_start:.3f}", "-t", f"{m_dur:.3f}", "-i", self.music_path,
                   "-map", "0:v:0", "-map", "1:a:0",
                   "-c:v", "copy", "-c:a", "aac", "-shortest",
                   out_file]
            r = _run_proc(cmd, capture_output=True, text=True,
                               creationflags=CREATE_NO_WINDOW)
            if r.returncode != 0 or not os.path.isfile(out_file):
                log.warning(f"卡点叠加音乐失败，输出无音乐版本: {(r.stderr or '')[-200:]}")
                shutil.copyfile(noaudio, out_file)
        else:
            shutil.copyfile(noaudio, out_file)
        return out_file

    def run(self):
        try:
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path or not os.path.isfile(ffmpeg_path):
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            from utils.platform_utils import find_ffprobe
            ffprobe_path = find_ffprobe()
            if not os.path.isfile(ffprobe_path):
                ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")

            if not self.selected_clips:
                raise RuntimeError("未选择任何镜头素材。")

            self.stage.emit("准备标准化转码工作...")
            self.progress.emit(5)

            # Establish temp working dir inside output_dir
            temp_dir = os.path.join(self.output_dir, ".temp_concat")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            os.makedirs(temp_dir, exist_ok=True)

            if self.layout_mode == "vertical":
                width, height = 1080, 1920
            elif self.layout_mode == "horizontal":
                width, height = 1920, 1080
            else:  # "source": 与原视频一致，取第一个素材的分辨率
                res = self._probe_resolution(self.selected_clips[0])
                if res:
                    width, height = res
                    width -= width % 2      # 保证为偶数，libx264 要求
                    height -= height % 2
                    self.stage.emit(f"输出画幅与原视频一致：{width}x{height}")
                else:
                    width, height = 1080, 1920  # 探测失败回退竖屏

            # Step 1: Transcode all selected candidate clips once to temporary folder
            # 并行转码：每个镜头输出独立文件 (norm_{i:04d}.mp4)，互不冲突；
            # 完成后按 i 排序重组，保证拼接顺序与串行版完全一致。
            normalized_list: list[tuple[int, str]] = []
            norm_to_desc = {}
            skipped_clips = []
            total_clips = len(self.selected_clips)
            # 转码是 ffmpeg 子进程密集型，并发数取 CPU 核心数，上限 8
            # （ffmpeg libx264 自身已多线程，过多并发反而争抢 CPU/磁盘）
            max_workers = max(2, min(8, os.cpu_count() or 4))
            transcode_args = (ffmpeg_path, ffprobe_path, temp_dir, width, height)
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=max_workers,
                                    thread_name_prefix="norm") as pool:
                future_to_meta = {
                    pool.submit(self._transcode_one, i, clip, *transcode_args): (i, clip)  # noqa: E501
                    for i, clip in enumerate(self.selected_clips)
                }
                done_count = 0
                for fut in as_completed(future_to_meta):
                    i, clip = future_to_meta[fut]
                    try:
                        norm_out = fut.result()
                    except _TranscodeSkip as e:
                        skipped_clips.append(clip)
                        self.stage.emit(str(e))
                        norm_out = None
                    except Exception as e:  # 线程池中未预期的错误也按跳过处理
                        # 未预期错误也按跳过处理，避免整个合成失败
                        log.warning(f"标准化转码异常，跳过: {clip}\n{e}", exc_info=True)
                        skipped_clips.append(clip)
                        self.stage.emit(f"注意： 转码失败，跳过: {os.path.basename(clip)}")
                        norm_out = None

                    if norm_out:
                        normalized_list.append((i, norm_out))
                        if self.selected_descriptions_list is not None and i < len(self.selected_descriptions_list):  # noqa: E501
                            norm_to_desc[norm_out] = self.selected_descriptions_list[i]
                        else:
                            norm_to_desc[norm_out] = self.split_descriptions.get(os.path.abspath(clip), "")  # noqa: E501

                    done_count += 1  # noqa: SIM113
                    self.stage.emit(f"标准化转码进度 {done_count}/{total_clips}")
                    prog = 10 + int(done_count / total_clips * 70)
                    self.progress.emit(prog)

            # 按原始下标 i 排序，恢复与串行版一致的拼接顺序
            normalized_list.sort(key=lambda t: t[0])
            clip_paths: list[str] = [p for _, p in normalized_list]

            if not clip_paths:
                raise RuntimeError("所有镜头文件均损坏或转码失败，无法合成视频。请重新进行镜头分割。")
            if skipped_clips:
                self.stage.emit(f"注意： 共跳过 {len(skipped_clips)} 个损坏文件，继续合成剩余 {len(clip_paths)} 个镜头")  # noqa: E501

            # ── 音乐卡点模式：按节拍裁剪镜头 + 叠加音乐片段，生成单个卡点视频 ──
            if self.recombine_mode == "beat" and self.beat_times:
                self.stage.emit(" 正在按音乐节拍合成卡点视频...")
                out_file = os.path.join(
                    self.output_dir, f"montage_beat_{random.randint(1000, 9999)}.mp4")
                self._compose_beat_video(ffmpeg_path, clip_paths, out_file, temp_dir)  # noqa: E501
                # 保存源镜头列表
                try:
                    sources_file = os.path.splitext(out_file)[0] + "_sources.txt"
                    with open(sources_file, "w", encoding="utf-8") as sf:
                        for src in self.selected_clips:
                            sf.write(src + "\n")
                except OSError as e:
                    log.warning(f"保存卡点视频源镜头列表失败: {e}")
                with contextlib.suppress(OSError):
                    shutil.rmtree(temp_dir)
                self.stage.emit(" 音乐卡点视频合成完成！")
                self.progress.emit(100)
                self.finished.emit([out_file])
                return

            # Step 2: Batch generate fast concatenations
            generated_paths = []
            for batch_idx in range(self.batch_count):
                self.stage.emit(f"无损拼接第 {batch_idx+1}/{self.batch_count} 个视频...")

                batch_clips = list(clip_paths)
                if self.recombine_mode == "random":
                    if self.randomness == "high":
                        random.shuffle(batch_clips)
                    elif self.randomness == "medium":
                        # Group consecutive clips with same description
                        groups = []
                        current_group: list[str] = []
                        current_desc = None
                        for n_clip in batch_clips:
                            desc = norm_to_desc.get(n_clip, "").strip()
                            if not current_group:
                                current_group.append(n_clip)
                                current_desc = desc
                            else:
                                if desc == current_desc and desc != "":
                                    current_group.append(n_clip)
                                else:
                                    groups.append(current_group)
                                    current_group = [n_clip]
                                    current_desc = desc
                        if current_group:
                            groups.append(current_group)

                        # Shuffle the groups
                        random.shuffle(groups)
                        # Flatten
                        batch_clips = [c for group in groups for c in group]
                    elif self.randomness == "low":
                        # Low randomness = no shuffling, keep sequential order
                        pass

                if len(batch_clips) > self.target_clip_count:
                    batch_clips = batch_clips[:self.target_clip_count]
                elif len(batch_clips) < self.target_clip_count:
                    extra_needed = self.target_clip_count - len(batch_clips)
                    for _ in range(extra_needed):
                        batch_clips.append(random.choice(clip_paths))

                out_file = os.path.join(self.output_dir, f"montage_concat_{random.randint(1000, 9999)}_{batch_idx+1}.mp4")  # noqa: E501

                # 使用 xfade 滤镜实现转场动画（非 copy 模式，需要重新编码）
                r = self._concat_with_transition(ffmpeg_path, ffprobe_path, batch_clips, out_file, temp_dir, batch_idx)  # noqa: E501
                if r.returncode != 0:
                    # 转场拼接失败，回退到无损 concat
                    log.warning(f"转场拼接失败，回退到普通拼接: {r.stderr[-200:]}")
                    concat_txt = os.path.join(temp_dir, f"concat_{batch_idx}.txt")
                    with open(concat_txt, "w", encoding="utf-8") as f:
                        for n_clip in batch_clips:
                            safe_path = n_clip.replace("\\", "/")
                            f.write(f"file '{safe_path}'\n")
                    cmd = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", out_file]  # noqa: E501
                    r = _run_proc(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)  # noqa: E501
                    if r.returncode != 0:
                        raise RuntimeError(f"拼接第 {batch_idx+1} 个视频失败：\n{r.stderr}")

                # 注：不再在合成视频时把画面描述拼接写入 .txt。
                # 该 .txt 是「口播文案」专属文件，只有用户点「生成口播文案」按钮由 AI 生成后才填充。
                # 画面描述已保存在内存 split_descriptions/split_clips_cache + _sources.txt 中，
                # 生成口播文案时由 _get_video_scene_descriptions 正常读取，不受影响。

                # Save the list of original source clips that make up this generated video  # noqa: E501
                sources_file = os.path.splitext(out_file)[0] + "_sources.txt"
                try:
                    original_sources = []
                    for n_clip in batch_clips:
                        filename = os.path.basename(n_clip)
                        if filename.startswith("norm_") and filename.endswith(".mp4"):
                            try:
                                idx = int(filename.split("_")[1].split(".")[0])
                                if 0 <= idx < len(self.selected_clips):
                                    original_sources.append(self.selected_clips[idx])
                            except (TypeError, ValueError):
                                pass
                    with open(sources_file, "w", encoding="utf-8") as sf:
                        for src in original_sources:
                            sf.write(src + "\n")
                except OSError as e:
                    log.warning(f"保存视频源镜头列表失败: {e}")

                generated_paths.append(out_file)
                self.progress.emit(80 + int((batch_idx + 1) / self.batch_count * 20))

            with contextlib.suppress(OSError):
                shutil.rmtree(temp_dir)

            self.stage.emit(f"批量拼接完成，共生成 {self.batch_count} 个视频！")
            self.progress.emit(100)
            self.finished.emit(generated_paths)

        except Exception:  # 批量拼接合并失败
            log.exception("批量拼接合并失败")
            self.error.emit(traceback.format_exc())



class FinalMixWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(list)  # Returns a list of final video paths

    def __init__(self, tasks, bgm_path, bgm_volume):
        super().__init__()
        self.tasks = tasks  # list of tuples: (video_path, output_path)
        self.bgm_path = bgm_path
        self.bgm_volume = bgm_volume

    def run(self):
        try:
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            creationflags = CREATE_NO_WINDOW
            has_bgm = bool(self.bgm_path and os.path.exists(self.bgm_path))
            bgm_vol = self.bgm_volume / 100.0

            results = []
            total = len(self.tasks)

            for index, (video_path, output_path) in enumerate(self.tasks):
                self.stage.emit(f"正在进行最终合成配乐 ({index + 1}/{total})...")
                self.progress.emit(int(index / total * 100))

                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                if has_bgm:
                    # Check if the input video has an audio stream
                    has_audio = False
                    try:
                        ffprobe_cmd = [
                            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",  # noqa: E501
                            "-of", "csv=p=0", video_path
                        ]
                        p_probe = _run_proc(ffprobe_cmd, capture_output=True, text=True, creationflags=creationflags)  # noqa: E501
                        if "audio" in p_probe.stdout:
                            has_audio = True
                    except (OSError, subprocess.SubprocessError):
                        has_audio = True

                    # BGM 淡入淡出：开头 1s 淡入，结尾 2s 淡出（按视频时长定位）
                    vid_dur = get_media_duration(video_path)
                    fade_out_start = max(0.0, vid_dur - 2.0)
                    bgm_fades = f"afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out_start:.3f}:d=2.0" if vid_dur > 0 else "afade=t=in:st=0:d=1.0"  # noqa: E501

                    if has_audio:
                        # 人声闪避（sidechain ducking）：BGM 在人声出现时自动压低，
                        # 人声停顿时回升；最终 loudnorm 统一响度（EBU R128 -16 LUFS）。
                        filter_complex = (
                            f"[0:a]asplit=2[vo][sc];"
                            f"[1:a]volume={bgm_vol},{bgm_fades}[bg];"
                            f"[bg][sc]sidechaincompress=threshold=0.05:ratio=8:attack=50:release=400[duck];"  # noqa: E501
                            f"[vo][duck]amix=inputs=2:duration=first:normalize=0,"
                            f"loudnorm=I=-16:TP=-1.5:LRA=11[a]"
                        )
                        cmd = [
                            ffmpeg_path, "-y", "-i", video_path,
                            "-stream_loop", "-1", "-i", self.bgm_path,
                            "-filter_complex", filter_complex,
                            "-map", "0:v", "-map", "[a]",
                            "-c:v", "copy", "-c:a", "aac", "-shortest",
                            output_path
                        ]
                    else:
                        cmd = [
                            ffmpeg_path, "-y", "-i", video_path,
                            "-stream_loop", "-1", "-i", self.bgm_path,
                            "-filter_complex", f"[1:a]volume={bgm_vol},{bgm_fades},loudnorm=I=-16:TP=-1.5:LRA=11[bgm]",  # noqa: E501
                            "-map", "0:v", "-map", "[bgm]",
                            "-c:v", "copy", "-c:a", "aac", "-shortest",
                            output_path
                        ]
                else:
                    cmd = [
                        ffmpeg_path, "-y", "-i", video_path,
                        "-c", "copy",
                        output_path
                    ]

                r = _run_proc(cmd, capture_output=True, text=True, creationflags=creationflags)  # noqa: E501
                if r.returncode != 0:
                    raise RuntimeError(f"最后合成视频失败：\n{r.stderr}")

                results.append(output_path)

            self.stage.emit("所有视频及配乐最终合成完成！")
            self.progress.emit(100)
            self.finished.emit(results)

        except Exception:  # 最终合成失败
            log.exception("最终合成失败")
            self.error.emit(traceback.format_exc())



class VideoDubbingWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(dict)  # Outputs a dict mapping: original_video_path -> dubbed_video_path  # noqa: E501

    def __init__(self, tasks, add_subtitles=True, length_modes=None,
                 fancy_text=False, fancy_style="gold", fancy_words=None,
                 subtitle_font="", fancy_position="upper_middle",
                 subtitle_box_opacity=0.5, fancy_template=None):
        super().__init__()
        self.tasks = tasks  # list of tuples: (video_path, voice_wav_path, output_video_path, text)  # noqa: E501
        self.add_subtitles = add_subtitles
        self.length_modes = length_modes or {}  # video_path -> "video" or "audio"
        self.fancy_text = fancy_text
        self.fancy_style = fancy_style
        # 兼容保留：花字内容已改为自动从口播文案提取卖点（见 extract_fancy_word），
        # 该参数不再参与渲染，仅为老调用方兼容保留。
        self.fancy_words = fancy_words or []
        # 字幕字体族名（来自服务端 /config/fonts 的 family）；空=用默认微软雅黑
        self.subtitle_font = (subtitle_font or "").strip()
        # 花字出现位置（见 FANCY_POSITIONS）；未知值回退默认中上
        self.fancy_position = fancy_position if fancy_position in FANCY_POSITIONS else "upper_middle"
        # 花字模板（样式+音效+时机，见 utils/fancy_templates.py）；None=自定义样式
        self.fancy_template = fancy_template if isinstance(fancy_template, dict) else None
        # 字幕背景不透明度（黑色背景，0=无背景框，1=全黑）；异常值回退 0.5（历史默认）
        try:
            self.subtitle_box_opacity = min(1.0, max(0.0, float(subtitle_box_opacity)))
        except (TypeError, ValueError):
            self.subtitle_box_opacity = 0.5

    def _resolve_subtitle_font_path(self):
        """把选定的字体族名解析为 drawtext 可用的字体文件路径（已转义盘符冒号）。

        服务端 /config/fonts 只给元信息（没有字体文件下载端点），因此本地烧制只能按
        「同名且本机已装」近似解析；解析不到则回退微软雅黑。真正按服务端字体烧制
        需服务端支持（见 docs/服务端字幕烧制与字体参数需求.md）。
        """
        family = self.subtitle_font
        if family:
            path = self._lookup_windows_font_file(family)
            if path:
                # drawtext 滤镜里盘符冒号需转义；统一用正斜杠避开反斜杠转义歧义
                return path.replace("\\", "/").replace(":", "\\:")
            log.info(f"[字幕字体] 本机未找到字体族「{family}」对应字体文件，回退微软雅黑")  # noqa: E501
        for cand in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyh.ttf"):
            if os.path.exists(cand):
                return cand.replace(":", "\\:")
        return "msyh"

    @staticmethod
    def _lookup_windows_font_file(family):
        """按字体族名从 Windows 注册表找本机字体文件绝对路径；找不到返回 ""。

        不用 Qt：PySide6 6.6 的 QFontDatabase.font() 返回 QFont（无 stylePath，拿不到
        字体文件），且 families() 里系统字体多以本地化名注册，按英文名匹配不到。

        注册表值名形如 "Microsoft YaHei (TrueType)" → 去括号后的前缀是族名；但系统
        自带字体常注册为**复合族名**（如 "Microsoft YaHei & Microsoft YaHei UI"、
        "SimSun & MS Gothic"），所以要按 " & " 拆分逐段比较，不能只比整个前缀；
        拆分后仍是精确匹配，因此不会误选 "Microsoft YaHei Bold" 这类字重。
        """
        if not family or os.name != "nt":
            return ""
        try:
            import winreg
        except ImportError:
            return ""
        fonts_dir = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Fonts")
        target = family.strip().lower()
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:  # noqa: E501
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        try:
                            name, value, _ = winreg.EnumValue(key, i)
                        except OSError:
                            continue
                        reg_family = name.rsplit(" (", 1)[0].strip()
                        parts = {p.strip().lower() for p in reg_family.split("&") if p.strip()}
                        if target not in parts:
                            continue
                        full = os.path.join(fonts_dir, str(value))
                        if os.path.isfile(full):
                            return full
            except OSError:
                continue
        return ""

    @staticmethod
    def _load_timing_sidecar(voice_wav_path):
        """读取逐句 TTS 生成的句级时间轴（.timing.json）；无效则返回 None。"""
        import json as _json
        p = (voice_wav_path or "") + ".timing.json"
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                timing = _json.load(f)
            if (isinstance(timing, list) and timing
                    and all(isinstance(t, dict) and t.get("text") for t in timing)):
                return timing
        except (OSError, _json.JSONDecodeError):
            pass
        return None

    def run(self):
        try:
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            results = {}
            total = len(self.tasks)

            for index, (video_path, voice_wav_path, output_video_path, text) in enumerate(self.tasks):  # noqa: E501
                self.stage.emit(f"正在进行视频原声替换配音 ({index + 1}/{total})...")
                self.progress.emit(int(index / total * 100))

                os.makedirs(os.path.dirname(output_video_path), exist_ok=True)

                length_mode = self.length_modes.get(video_path, "video")
                video_dur = get_media_duration(video_path)
                audio_dur = get_media_duration(voice_wav_path)
                # 输入视频预检：ffprobe 读不出时长 = 文件不完整/损坏
                #（如服务端成片下载中断导致 moov 缺失）。立即报明确错误，
                # 不带坏文件进 ffmpeg（否则报 moov atom not found 难以定位）。
                if video_dur <= 0:
                    raise RuntimeError(
                        f"输入视频无法读取（文件可能不完整或损坏，常见原因为服务端"
                        f"成片下载中断）：{video_path}\n请重新执行镜头合成后再配音。")
                use_audio_length = (length_mode == "audio" and audio_dur > video_dur > 0)  # noqa: E501
                extra_dur = audio_dur - video_dur if use_audio_length else 0.0
                display_dur = audio_dur if use_audio_length else video_dur

                # Build video filter chain
                video_filters = []
                video_label = "0:v"
                audio_label = "1:a:0"
                need_audio_speed = (not use_audio_length and audio_dur > video_dur > 0)
                sound_specs: list = []      # 花字模板音效 [(路径, 延迟ms)]

                if use_audio_length:
                    # Extend video with last frame clone to match audio length
                    video_filters.append(f"[{video_label}]tpad=stop_mode=clone:stop_duration={extra_dur:.3f}[v_padded]")  # noqa: E501
                    video_label = "v_padded"

                # 逐句时间轴（字幕烧制与花字跟字幕时机共用）：优先使用逐句 TTS 的
                # 真实句级时间轴（字幕与语音精确同步）；无时间轴按字数比例估算（旧行为）
                sub_lines, sub_starts, sub_ends = [], [], []
                if (self.add_subtitles or self.fancy_text) and text:
                    timing = self._load_timing_sidecar(voice_wav_path)
                    if timing:
                        raw_lines = [str(t["text"]).strip() for t in timing]
                        line_starts = [float(t.get("start", 0)) for t in timing]
                        line_ends = [float(t.get("end", 0)) for t in timing]
                        # 本步骤内音频被 atempo 加速对齐视频时 → 时间轴按同比例缩放
                        if need_audio_speed and audio_dur > 0:
                            f_scale = video_dur / audio_dur
                            line_starts = [s * f_scale for s in line_starts]
                            line_ends = [e * f_scale for e in line_ends]
                        if display_dur > 0:
                            line_ends = [min(e, display_dur) for e in line_ends]
                    else:
                        # 回退：无时间轴时按字数比例估算（旧行为）
                        raw_lines = [line.strip() for line in text.strip().split("\n") if line.strip()]  # noqa: E501
                        if not raw_lines:
                            raw_lines = [text.strip()]
                        char_counts = [max(1, len(line)) for line in raw_lines]
                        total_chars = sum(char_counts)
                        cum_t = 0.0
                        line_starts, line_ends = [], []
                        for c in char_counts:
                            t0 = cum_t
                            t1 = cum_t + (display_dur * c / total_chars if display_dur > 0 else 5.0)  # noqa: E501
                            line_starts.append(t0)
                            line_ends.append(t1)
                            cum_t = t1
                    sub_lines = [_strip_pron_annotation(x) for x in raw_lines]
                    sub_starts, sub_ends = line_starts, line_ends

                if self.add_subtitles and text and sub_lines:
                    # 字幕字体：优先用用户在「口播配音」选的服务端字体（同名解析本机字体文件），
                    # 解析不到再回退微软雅黑。
                    font_path = self._resolve_subtitle_font_path()

                    # Build drawtext filters（背景不透明度可配：0=无背景框）
                    # 超长行不再多行堆叠（同屏 2-3 行观感太长）：按配音时间窗把
                    # 长句切成多个短字幕段依次显示——段文本用 wrap_subtitle_line
                    # 的均衡断点（标点/空格优先），段时长按各段等效字数占比切分
                    # 行时间窗（有句级时间戳时即克隆配音的节奏），任意时刻只挂一行。
                    box_str = (f"box=1:boxcolor=black@{self.subtitle_box_opacity:.2f}:boxborderw=6:"
                               if self.subtitle_box_opacity > 0 else "")
                    drawtexts = []
                    y_expr = f"{_SAFE_BOTTOM_EDGE}-text_h-h*{SUB_BOTTOM_GAP}"
                    for i, line_text in enumerate(sub_lines):
                        start_t = sub_starts[i]
                        end_t = max(start_t + 0.2, sub_ends[i])
                        parts = wrap_subtitle_line(line_text)
                        if len(parts) == 1:
                            segs = [(parts[0], start_t, end_t)]
                        else:
                            # 长句拆段：时长按等效字数占比切行时间窗
                            weights = [_sub_line_weight(p) for p in parts]
                            total_w = sum(weights) or float(len(parts))
                            cum = start_t
                            segs = []
                            for k, part in enumerate(parts):
                                seg_end = (end_t if k == len(parts) - 1
                                           else cum + (end_t - start_t) * weights[k] / total_w)  # noqa: E501
                                segs.append((part, cum, seg_end))
                                cum = seg_end
                        for part, seg_start, seg_end in segs:
                            escaped = part.replace('\\', '\\\\').replace("'", "'\\\\''").replace(':', '\\:').replace(',', '\\,')  # noqa: E501
                            dt = (
                                f"drawtext=fontfile='{font_path}':"
                                f"text='{escaped}':"
                                f"fontsize=h*{SUB_FONT_SCALE}:fontcolor=white:"
                                f"{box_str}"
                                f"x=(w-text_w)/2:"
                                f"y={y_expr}:"
                                f"enable='between(t,{seg_start:.3f},{seg_end:.3f})'"
                            )
                            drawtexts.append(dt)
                    video_filters.append(f"[{video_label}]{','.join(drawtexts)}[v]")
                    video_label = "v"

                # 花字叠加（关键信息加重提醒，大号彩色描边特效文字）：
                # 内容自动从口播文案提取卖点（价格>数字参数>关键词，行内多卖点，
                # 规则见 extract_fancy_words_in_line），每条视频最多 FANCY_MAX_PER_VIDEO
                # 个；时机跟随对应字幕行——提前 FANCY_LEAD_SEC 秒出现、该行字幕结束即
                # 消失；行内多个卖点时把该行时间窗均分依次出现；无卖点的行不出现。
                fancy_events = []  # [(花字内容, 开始秒, 结束秒)]
                if self.fancy_text and sub_lines and display_dur > 0:
                    quota = FANCY_MAX_PER_VIDEO
                    for li, line_text in enumerate(sub_lines):
                        if quota <= 0:
                            break
                        words = extract_fancy_words_in_line(line_text, limit=quota)
                        if not words:
                            continue
                        ws = max(0.0, sub_starts[li] - FANCY_LEAD_SEC)
                        we = max(ws + 0.2, min(sub_ends[li], display_dur))
                        if len(words) == 1:
                            fancy_events.append((words[0], ws, we))
                        else:
                            # 行内多卖点：时间窗均分依次出现（首段保持提前量）
                            seg = (we - ws) / len(words)
                            for wi, w in enumerate(words):
                                s = ws if wi == 0 else ws + wi * seg
                                e = ws + (wi + 1) * seg if wi < len(words) - 1 else we
                                fancy_events.append((w, s, max(s + 0.2, e)))
                        quota -= len(words)
                    if fancy_events:
                        # 重叠消解：字幕行衔接紧/行内多卖点时时间窗会交叠，
                        # 同位置同时渲染两个花字会重叠——统一压缩/去重。
                        fancy_events = resolve_fancy_overlaps(fancy_events)
                    if not fancy_events:
                        log.info("[花字] 口播文案中未提取到卖点（价格/数字参数/关键词），本次不叠加花字")  # noqa: E501

                if self.fancy_text and fancy_events:
                    font_path = "C\\:/Windows/Fonts/msyhbd.ttc"
                    if not os.path.exists("C:/Windows/Fonts/msyhbd.ttc"):
                        font_path = "C\\:/Windows/Fonts/msyh.ttc"
                    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
                        font_path = "msyh"

                    # 花字样式预设：fontcolor + borderw + bordercolor + shadow
                    fancy_styles = {
                        "gold":          "fontcolor=0xF0C040:borderw=4:bordercolor=0x6B3000:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",  # noqa: E501
                        "red":           "fontcolor=0xFF4040:borderw=4:bordercolor=0x800000:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",  # noqa: E501
                        "blue":          "fontcolor=0x40A0FF:borderw=4:bordercolor=0x003080:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",  # noqa: E501
                        "purple":        "fontcolor=0xC060FF:borderw=4:bordercolor=0x300060:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",  # noqa: E501
                        "neon_green":    "fontcolor=0x40FF80:borderw=3:bordercolor=0x004020:shadowx=3:shadowy=3:shadowcolor=0x00FF80@0.5",  # noqa: E501
                        "white_outline": "fontcolor=white:borderw=5:bordercolor=black:shadowx=2:shadowy=2:shadowcolor=0x000000@0.6",  # noqa: E501
                        "yellow_red":    "fontcolor=0xFFFF00:borderw=5:bordercolor=0xCC0000:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",  # noqa: E501
                    }
                    style_str = fancy_styles.get(self.fancy_style, fancy_styles["gold"])
                    # 模板优先：选了花字模板时，样式以模板的 drawtext 串为准
                    if self.fancy_template and self.fancy_template.get("style"):
                        style_str = str(self.fancy_template["style"])

                    # 模板音效：每个花字出现时刻把音效混入配音轨（adelay 对齐 + amix）。
                    # 音效文件缺失时静默跳过（模板可先只用样式，音效后补）。
                    from utils.fancy_templates import get_fancy_sound_gain_db, get_fancy_sound_path  # noqa: E501
                    sound_specs: list[tuple[str, int]] = []  # (绝对路径, 延迟ms)
                    if self.fancy_template:
                        _sfx = get_fancy_sound_path(self.fancy_template)
                        if _sfx:
                            _gain = get_fancy_sound_gain_db(self.fancy_template)
                            sound_specs = []  # 下方算出各花字时刻后填充
                    else:
                        _sfx = ""
                        _gain = -6.0

                    # 花字位置：drawtext x/y 表达式（与 docs/服务端花字烧制需求.md 一致）。
                    # 底部两个位置抬高到 h*0.15，避免与底部逐行字幕（y=h-text_h-h*0.06）重叠。
                    pos = FANCY_POSITIONS[self.fancy_position]
                    pos_x, pos_y = pos["x"], pos["y"]

                    fancy_drawtexts = []
                    # 入场动画：模板 jy_intro_anim 映射为本地通用动画
                    # （fade 淡入/rise 上浮/slide 滑入/pop 弹跳），drawtext 用
                    # alpha/x/y 的 t 表达式驱动；未选模板时默认淡入。
                    # 动画时长 0.4s（pop 弹跳衰减稍长），从花字出现时刻起播。
                    # 注意：动画时 x/y 由表达式提供（不能同时给静态 x/y，
                    # 避免 drawtext 同名选项的覆盖行为不可靠）。
                    _anim = "fade"
                    if self.fancy_template:
                        from utils.fancy_templates import get_fancy_anim  # noqa: E501
                        _anim = get_fancy_anim(self.fancy_template)
                    _anim_dur = 0.4
                    for word, ft_start, ft_end in fancy_events:
                        escaped = word.replace('\\', '\\\\').replace("'", "'\\\\''").replace(':', '\\:').replace(',', '\\,')  # noqa: E501
                        # 动画选项：alpha 淡入 + 按类型的 x/y 位移；s=出现时刻。
                        # x/y 必须成对提供（drawtext 默认 x/y=0，缺一个就跑位）
                        anim_parts = []
                        s = f"{ft_start:.3f}"
                        x_expr = y_expr = ""
                        if _anim == "fade":
                            anim_parts.append(
                                f"alpha='if(lt(t,{s}+{_anim_dur}),(t-{s})/{_anim_dur},1)'")
                        elif _anim == "rise":
                            anim_parts.append(
                                f"alpha='if(lt(t,{s}+{_anim_dur}),(t-{s})/{_anim_dur},1)'")
                            y_expr = f"({pos_y})-(1-min((t-{s})/{_anim_dur},1))*h*0.04"
                        elif _anim == "slide":
                            anim_parts.append(
                                f"alpha='if(lt(t,{s}+{_anim_dur}),(t-{s})/{_anim_dur},1)'")
                            x_expr = f"({pos_x})+(1-min((t-{s})/{_anim_dur},1))*w*0.10"
                        elif _anim == "pop":
                            anim_parts.append(
                                f"alpha='if(lt(t,{s}+0.15),(t-{s})/0.15,1)'")
                            y_expr = (f"({pos_y})-abs(sin((t-{s})*14))*h*0.012"
                                      f"*(1-min((t-{s})/0.7,1))")
                        anim_str = (":" + ":".join(anim_parts)) if anim_parts else ""
                        x_str = f"x='{x_expr}'" if x_expr else f"x={pos_x}"
                        y_str = f"y='{y_expr}'" if y_expr else f"y={pos_y}"
                        # 花字：大号字体，按所选位置摆放，带描边和阴影
                        dt = (
                            f"drawtext=fontfile='{font_path}':"
                            f"text='{escaped}':"
                            f"fontsize=h*0.08:{style_str}:"
                            f"{x_str}:{y_str}:"
                            f"enable='between(t,{ft_start:.3f},{ft_end:.3f})'"
                            f"{anim_str}"
                        )
                        fancy_drawtexts.append(dt)
                        if _sfx:
                            sound_specs.append((_sfx, int(ft_start * 1000)))
                    if fancy_drawtexts:
                        video_filters.append(f"[{video_label}]{','.join(fancy_drawtexts)}[vf]")  # noqa: E501
                        video_label = "vf"

                if need_audio_speed:
                    # Speed up audio to match video duration using atempo chain
                    ratio = audio_dur / video_dur
                    atempo_parts = []
                    remaining = ratio
                    while remaining > 2.0:
                        atempo_parts.append("atempo=2.0")
                        remaining /= 2.0
                    if remaining < 0.5:
                        atempo_parts.append("atempo=0.5")
                        remaining /= 0.5
                    if abs(remaining - 1.0) > 0.001:
                        atempo_parts.append(f"atempo={remaining:.4f}")
                    if atempo_parts:
                        if video_filters:
                            video_filters.append(f"[{audio_label}]{','.join(atempo_parts)}[a]")  # noqa: E501
                            audio_label = "a"
                        else:
                            video_filters.append(f"[{audio_label}]{','.join(atempo_parts)}[a]")  # noqa: E501
                            audio_label = "a"
                            # Need a dummy video pass-through so filter_complex can map both  # noqa: E501
                            video_filters.insert(0, f"[{video_label}]null[v]")
                            video_label = "v"

                # 花字模板音效混入：在每个花字出现时刻叠加音效（adelay 对齐时间轴
                # + amix 混入配音，normalize=0 防止人声被拉低）。必须在 atempo 之后
                # 追加，保证延迟基于最终时间轴。
                sound_input_paths: list[str] = []
                if sound_specs:
                    next_idx = 2  # 输入流：0=video, 1=voice，音效从 2 开始
                    amix_in = f"[{audio_label}]"
                    for si, (sfx_path, delay_ms) in enumerate(sound_specs):
                        video_filters.append(
                            f"[{next_idx}:a]adelay={delay_ms}:all=1,"
                            f"volume={_gain:.1f}dB[s{si}]")
                        amix_in += f"[s{si}]"
                        sound_input_paths.append(sfx_path)
                        next_idx += 1
                    video_filters.append(
                        f"{amix_in}amix=inputs={len(sound_specs) + 1}"
                        f":normalize=0:duration=longest[a_mix]")
                    audio_label = "a_mix"

                if video_filters:
                    filter_complex = ";".join(video_filters)
                    # 滤镜输出标签（无冒号）需要 [] 包裹；裸输入流（如 1:a:0）不加
                    audio_map = (f"[{audio_label}]" if ":" not in audio_label
                                 else audio_label)  # noqa: E501
                    cmd = [
                        ffmpeg_path, "-y", "-i", video_path,
                        "-i", voice_wav_path,
                    ]
                    for _sp in sound_input_paths:
                        cmd += ["-i", _sp]
                    cmd += [
                        "-filter_complex", filter_complex,
                        "-map", f"[{video_label}]", "-map", audio_map,
                        *get_video_encode_args(crf=23, preset="superfast"), "-c:a", "aac",  # noqa: E501
                    ]
                    # "以声音为准"时严格裁剪输出到音频时长：
                    #   audio > video → tpad 已把视频延长到 audio_dur，-t 再确认一次（无害）
                    #   audio < video → tpad 未触发，必须靠 -t 裁掉多余的视频
                    if length_mode == "audio" and audio_dur > 0:
                        cmd += ["-t", f"{audio_dur:.3f}"]
                else:
                    cmd = [
                        ffmpeg_path, "-y", "-i", video_path,
                        "-i", voice_wav_path,
                        "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-c:a", "aac", "-shortest",
                    ]
                cmd.append(output_video_path)

                r = _run_proc(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)  # noqa: E501
                if r.returncode != 0:
                    err = r.stderr or r.stdout or "(无输出)"
                    raise RuntimeError(f"视频原声替换配音失败：\n{err}\n命令: {' '.join(cmd)}")

                results[video_path] = output_video_path

            self.stage.emit("所有视频替换配音完成！")
            self.progress.emit(100)
            self.finished.emit(results)

        except Exception:  # 视频替换配音失败
            log.exception("视频替换配音失败")
            self.error.emit(traceback.format_exc())
