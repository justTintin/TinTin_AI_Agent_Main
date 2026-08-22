"""SRT 字幕解析与生成工具。

从 transcription_page.py 和 live_clip_page.py 中统一下沉的 SRT 处理逻辑。
"""
import re
from dataclasses import dataclass, field
from typing import Any

_TIME_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)


@dataclass
class SRTSegment:
    """SRT 字幕片段。"""
    start: float = 0.0
    end: float = 0.0
    text: str = ""
    words: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text, "words": self.words}  # noqa: E501

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SRTSegment":
        return cls(
            start=d.get("start", 0.0),
            end=d.get("end", 0.0),
            text=d.get("text", ""),
            words=d.get("words", []),
        )


def parse_srt_time(t: str) -> float:
    """SRT 时间戳 HH:MM:SS,mmm（兼容 . 分隔）→ 秒。"""
    t = t.strip().replace(".", ",")
    try:
        hms, ms = t.split(",")
        h, m, s = hms.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms[:3]) / 1000.0
    except ValueError:
        return 0.0


def parse_srt(text: str) -> list[dict[str, Any]]:
    """逐行解析字幕文本 → segments [{"start","end","text","words":[]}]。

    同时兼容两种输入：
    - 原始 SRT（序号行+时间轴行+正文）
    - 编辑态视图纯文本（时间轴行内嵌序号）
    """
    segments: list[dict[str, Any]] = []
    cur = None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = _TIME_RE.search(line)
        if m:
            if cur:
                segments.append(cur)
            cur = {
                "start": parse_srt_time(m.group(1)),
                "end": parse_srt_time(m.group(2)),
                "text": "",
                "words": [],
            }
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if cur is not None:
            cur["text"] = (str(cur["text"]) + " " + line).strip()
    if cur:
        segments.append(cur)
    segments = [s for s in segments if s["text"]]
    segments.sort(key=lambda s: s["start"])
    return segments


def segments_to_srt(segments: list[dict[str, Any]]) -> str:
    """segments → SRT 格式化文本。"""
    if not segments:
        return ""
    lines = []
    for i, seg in enumerate(segments):
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        text = str(seg.get("text", "")).strip().replace("\n", " ")
        lines.append(f"{i + 1}")
        lines.append(
            f"{int(start // 3600):02d}:{int(start % 3600 // 60):02d}:{start % 60:06.3f} --> "  # noqa: E501
            f"{int(end // 3600):02d}:{int(end % 3600 // 60):02d}:{end % 60:06.3f}"
        )
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def parse_srt_to_segments(text: str) -> list[SRTSegment]:
    """解析 SRT 文本 → SRTSegment 对象列表（供 live_clip_page 等使用）。"""
    raw = parse_srt(text)
    return [SRTSegment.from_dict(s) for s in raw]
