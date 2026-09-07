# -*- coding: utf-8 -*-
import re

"""花字卖点提取 + 重叠消解 —— 服务端参考实现（自动生成，勿手改）。

来源：studio/gui/montage/workers/concat_workers.py（脚本原样提取）。
服务端直接拷贝以下常量与函数即可，与客户端 extract_fancy_word /
extract_fancy_words_in_line / extract_fancy_words_from_text /
resolve_fancy_overlaps 保证逐字一致（验收 #7；规则说明见
docs/服务端花字烧制需求.md §2.3）。

重新生成方式：改客户端词表/规则后，运行提取脚本重新生成本文件
（服务端守卫测试会自动发现两侧漂移）。
"""

# ── 常量 ──

_FANCY_PRICE_RE = re.compile(r"(?:仅|只要|低至|到手|券后)?\d+(?:\.\d+)?元")

_FANCY_UNIT = ("小时|分钟|秒钟|毫安时|毫安|mAh|千克|公斤|kg|KG|Kg|千瓦|kW|毫伏|mV|"
               "毫米|厘米|分米|英寸|千米|公里|km|cm|mm|克|瓦|伏|升|毫升|ml|mL|"
               "赫兹|Hz|kHz|分贝|dB|℃|°C|%|％|DPI|dpi|天|周|月|年|米|寸|度|W|V|G|g|L|倍|核|轴|键|帧|级|档|声")

_FANCY_NUM_RE = re.compile(rf"[\u4e00-\u9fa5A-Za-z]{{0,4}}\d+(?:\.\d+)?(?:{_FANCY_UNIT})")

_FANCY_KEYWORDS = (
    "超轻", "超薄", "超长续航", "超静音", "大容量", "快充", "闪充", "无线充电",
    "防水", "防尘", "降噪", "折叠", "便携", "旗舰", "爆款", "新款", "限量",
    "免打孔", "免安装", "持久续航", "高清", "巨幕", "一机多用",
    "电量持久", "电量充足", "放电均衡", "不易漏液", "输出稳定", "经久耐用", "密封性",
    "平价",
)

FANCY_LEAD_SEC = 0.3

FANCY_MAX_LEN = 10     # 花字内容最大字符数（价格/参数串超出截断）

FANCY_MAX_PER_VIDEO = 3  # 每条视频花字数量上限（卖点 2-3 个，不足则有多少用多少）

FANCY_MIN_GAP_SEC = 0.05

FANCY_MIN_DISPLAY_SEC = 0.4

# ── 提取函数 ──

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

# ── 重叠消解（2026-09-07 新增）──

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
