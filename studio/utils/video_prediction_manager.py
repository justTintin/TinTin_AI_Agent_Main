"""
视频评价预测数据层：保存每次「视频评价预测」的结果，以及发布后回填的
真实播放量 / 平台评价；这些「预测 vs 实际」对照会反哺下次预测（在 prompt 里做校准）。

存储：data/video_predictions.json（Manager + JSON 模式）。
"""
import json
import os
import time

from config.paths import VIDEO_PREDICTIONS_FILE

from utils.logger_utils import log

# 投放平台（与素材浏览器/热点一致）
PLATFORMS = ["抖音", "小红书", "视频号", "B站", "快手"]

# 预测维度（雷达图，6 维）
DIMENSIONS = ["吸睛力", "画面冲击", "悬念信息", "节奏", "完播预测", "平台适配"]

# 预测表现量级
PLAY_LEVELS = ["爆款", "优质", "普通", "偏弱"]


class VideoPredictionManager:
    def __init__(self, file_path=None):
        self.file_path = file_path or VIDEO_PREDICTIONS_FILE
        self.items = []
        self.load()

    def load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, encoding="utf-8") as f:
                    self.items = json.load(f)
            except Exception as e:
                log.error(f"加载视频预测库失败: {e}")
                self.items = []
        else:
            self.items = []
        return self.items

    def save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.items, f, indent=2, ensure_ascii=False)

    def all_items(self):
        return list(self.items)

    def add_prediction(self, video_path, platform, predicted):
        """新增一条预测记录，返回其 id。predicted 为模型输出 dict。"""
        item = {
            "id": os.urandom(8).hex(),
            "video_path": video_path,
            "video_name": os.path.basename(video_path) if video_path else "",
            "platform": platform,
            "predicted": predicted,
            "actual": None,           # 回填后为 {play_count, platform_eval, at}
            "created_at": int(time.time()),
        }
        self.items.insert(0, item)
        self.save()
        return item["id"]

    def set_feedback(self, item_id, play_count, platform_eval):
        target = next((it for it in self.items if it.get("id") == item_id), None)
        if not target:
            return False
        target["actual"] = {
            "play_count": play_count,
            "platform_eval": (platform_eval or "").strip(),
            "at": int(time.time()),
        }
        self.save()
        return True

    def pending_feedback(self):
        """尚未回填真实数据的记录。"""
        return [it for it in self.items if not it.get("actual")]

    def recent_with_feedback(self, platform=None, limit=12):
        """取最近已回填的「预测 vs 实际」对照，供校准。"""
        out = []
        for it in self.items:
            if not it.get("actual"):
                continue
            if platform and it.get("platform") != platform:
                continue
            out.append(it)
            if len(out) >= limit:
                break
        return out

    def calibration_text(self, platform=None, limit=12):
        """把历史对照拼成校准文本（喂给预测 prompt）。无数据返回空串。"""
        rows = self.recent_with_feedback(platform=platform, limit=limit)
        if not rows:
            return ""
        lines = ["以下是你过往的『预测 vs 实际』对照（同一作者/账号），"
                 "请据此校准本次预测——若历史上你高估/低估，请相应修正："]
        for it in rows:
            p = it.get("predicted") or {}
            a = it.get("actual") or {}
            lines.append(
                f"- [{it.get('platform','')}] 预测综合{p.get('total','?')}分/"
                f"量级{p.get('play_level','?')} → 实际播放{a.get('play_count','?')}、"
                f"平台评价「{a.get('platform_eval','')}」")
        return "\n".join(lines)
