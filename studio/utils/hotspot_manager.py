"""
热点趋势库：把素材浏览器每天采集的各平台热榜快照（hotspots_sync.json）
合并成**持久 + 带历史**的趋势库（data/hotspots.json），并按 科技/数码/AI 分类。

趋势：同一话题（平台+标题）每天上榜就往 history 追加 {date,rank,hot}，
据此得到 上榜天数 / 最佳排名 / 最新排名 / 首末出现日期。
"""
import json
import os
import re
import time

from config.paths import HOTSPOTS_FILE, HOTSPOTS_MATERIALS_DIR

from utils.logger_utils import log

# 科技/数码/AI 关键词（命中即归类；可多类）
CATEGORY_KEYWORDS = {
    "AI": ["ai", "人工智能", "大模型", "gpt", "claude", "gemini", "agent", "智能体",
           "机器学习", "深度学习", "llm", "算法", "生成式", "aigc", "chatgpt", "deepseek"],
    "数码": ["手机", "电脑", "笔记本", "平板", "耳机", "相机", "鼠标", "键盘", "显卡",
            "芯片", "处理器", "ssd", "显示器", "数码", "智能手表", "充电", "续航", "屏幕",
            "iphone", "华为", "小米", "苹果", "安卓", "骁龙", "英伟达", "amd", "intel"],
    "科技": ["科技", "互联网", "软件", "编程", "开发", "发布会", "新品", "黑科技", "机器人",
            "卫星", "半导体", "新能源", "汽车", "特斯拉", "量子", "航天", "数据", "云计算"],
}


def classify(title):
    """返回命中的分类列表（科技/数码/AI），无命中返回 []。"""
    t = (title or "").lower()
    hits = []
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in t for k in kws):
            hits.append(cat)
    return hits


def _norm(title):
    return re.sub(r"\s+", "", (title or "")).strip().lower()


class HotspotManager:
    def __init__(self, file_path=None):
        self.file_path = file_path or HOTSPOTS_FILE
        self.topics = []
        self.load()

    def load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, encoding="utf-8") as f:
                    self.topics = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                log.error(f"加载热点库失败: {e}")
                self.topics = []
        else:
            self.topics = []
        return self.topics

    def save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.topics, f, indent=2, ensure_ascii=False)

    def all_topics(self):
        return list(self.topics)

    def import_snapshots(self, manifest_path=None):
        """
        合并采集清单到趋势库（按 平台+标题 去重，按日期追加 history）。
        返回 (new_topics, updated_topics, snapshots, msg)。幂等：同(话题,日期)不重复记。
        """
        path = manifest_path or os.path.join(HOTSPOTS_MATERIALS_DIR, "hotspots_sync.json")  # noqa: E501
        if not os.path.exists(path):
            return 0, 0, 0, f"未找到采集清单：{path}\n请先在素材浏览器点「 抓取今日热点」。"
        try:
            with open(path, encoding="utf-8") as f:
                snaps = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return 0, 0, 0, f"读取采集清单失败：{e}"
        if not isinstance(snaps, list):
            return 0, 0, 0, "采集清单格式异常（应为数组）。"

        index = {(t.get("platform"), _norm(t.get("title"))): t for t in self.topics}
        new_n = upd_n = 0
        dates = set()
        for s in snaps:
            platform = s.get("platform", "")
            title = (s.get("title") or "").strip()
            if not title:
                continue
            date = s.get("date", "")
            dates.add(date)
            rank = s.get("rank")
            hot = s.get("hot", "")
            key = (platform, _norm(title))
            topic = index.get(key)
            if not topic:
                topic = {
                    "id": os.urandom(8).hex(),
                    "platform": platform,
                    "title": title,
                    "url": s.get("url", ""),
                    "categories": classify(title),
                    "first_seen": date,
                    "last_seen": date,
                    "history": [],
                    "created_at": int(time.time()),
                }
                self.topics.append(topic)
                index[key] = topic
                new_n += 1
            # 追加历史（同日期不重复）
            if not any(h.get("date") == date for h in topic["history"]):
                topic["history"].append({"date": date, "rank": rank, "hot": hot})
                topic["last_seen"] = max(topic.get("last_seen", date), date)
                topic["first_seen"] = min(topic.get("first_seen", date), date)
                if s.get("url") and not topic.get("url"):
                    topic["url"] = s["url"]
                if not topic.get("categories"):
                    topic["categories"] = classify(title)
                upd_n += 1
            # 维护派生字段
            ranks = [h["rank"] for h in topic["history"] if isinstance(h.get("rank"), int)]  # noqa: E501
            topic["days_on_board"] = len({h["date"] for h in topic["history"] if h.get("date")})  # noqa: E501
            topic["best_rank"] = min(ranks) if ranks else None
            topic["latest_rank"] = topic["history"][-1].get("rank") if topic["history"] else None  # noqa: E501
        self.save()
        msg = f"导入完成：新增话题 {new_n}，更新 {upd_n}（{len(dates)} 个日期快照）。"
        return new_n, upd_n, len(dates), msg

    def query(self, category=None, platform=None, keyword=None, tech_only=False):
        """筛选话题。category in {科技,数码,AI}；tech_only=只看有任一分类命中的。"""
        out = []
        kw = (keyword or "").strip().lower()
        for t in self.topics:
            cats = t.get("categories") or []
            if tech_only and not cats:
                continue
            if category and category not in cats:
                continue
            if platform and t.get("platform") != platform:
                continue
            if kw and kw not in (t.get("title", "").lower()):
                continue
            out.append(t)
        # 排序：上榜天数降序、最新排名升序
        out.sort(key=lambda t: (-(t.get("days_on_board") or 0),
                                t.get("latest_rank") if isinstance(t.get("latest_rank"), int) else 9999))  # noqa: E501
        return out
