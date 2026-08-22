"""
风格化提炼：把「我的知识库」里从素材浏览器采集来的「风格参考样本」
按多维度提炼为「风格化」条目——即 HOW to write（写法风格），而非 WHAT（内容知识点）。

四个维度：
  - account      账号风格：特定创作者/账号的写作风格画像
  - content_type 内容类型：科技类/科普类/剧情类/玩梗类/硬核类 的风格套路
  - product_cat  产品品类：笔电/鼠标类/键盘类/外设类/台机类/苹果类/AI类 的内容风格
  - industry     行业垂类：科技类/财经类/电商行业类 的内容风格

流程：
  ① 给每条样本打标（content_type / product_cat / industry，账号来自 source.creator）
  ② 按四维度分组
  ③ 每组 LLM 提炼「风格画像」（钩子/口吻/节奏/句式/收尾/禁忌）
  ④ 写回 manager，类型固定为 STYLIZATION_TYPE="风格化"

LLM 复用 ai_config 的 llm_api_url/llm_api_key/llm_model。
"""
import json
import re
from typing import Any

from utils.logger_utils import log
from utils.my_knowledge_manager import (
    CONTENT_TYPE_OPTIONS,
    INDUSTRY_OPTIONS,
    PRODUCT_CAT_OPTIONS,
    REFERENCE_TYPE,
    STYLE_DIMS,
    STYLIZATION_TYPE,
    MyKnowledgeManager,
)

TAG_BATCH = 12          # 每批打标样本数
MAX_GROUP_SAMPLES = 25  # 每组参与提炼的样本上限
MIN_GROUP_SAMPLES = 2   # 少于此数不单独提炼（账号维度放宽到 1）
SAMPLE_TEXT_CAP = 280   # 单条样本文本截断


def _chat(cfg, system, user, temperature=0.4, timeout=120):
    """通过服务端代理调用 LLM（不再直连 API）。"""
    from utils.llm_proxy import llm_chat
    model = cfg.get("model", "deepseek-v4-flash")
    return llm_chat(system, user, model=model, temperature=temperature, timeout=timeout)


def _parse_json(text):
    """从 LLM 输出里抠出 JSON（容忍 ```json 包裹 / 前后多余文字）。"""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"(\[.*\]|\{.*\})", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                return None
    return None


def _sample_text(it):
    c = (it.get("content") or "").strip().replace("\n", " ")
    return c[:SAMPLE_TEXT_CAP]


# ──────────────────── 打标 ────────────────────

def _tag_batch(cfg, batch):
    """给一批样本打 content_type / product_cat / industry 标签，账号维度来自 source.creator。
    返回 list[{content_type:[], product_cat:[], industry:[]}]（与 batch 对齐）。"""
    ct_opts = "/".join(CONTENT_TYPE_OPTIONS)
    pc_opts = "/".join(PRODUCT_CAT_OPTIONS)
    ind_opts = "/".join(INDUSTRY_OPTIONS)
    system = (
        "你是短视频内容类型分析助手。给定若干条视频/图文(标题+文案)，为每条提取：\n"
        f"- content_type: 内容风格类型，只从[{ct_opts}]中选，可多个，没有则空数组\n"
        f"- product_cat: 产品品类，只从[{pc_opts}]中选，可多个，没有则空数组\n"
        f"- industry: 行业垂类，只从[{ind_opts}]中选，可多个，没有则空数组\n"
        '只输出JSON数组，每元素形如 {"i":序号,"content_type":[],"product_cat":[],"industry":[]}，不要任何多余文字。'  # noqa: E501
    )
    lines = [f"[{i}] {_sample_text(it)}" for i, it in enumerate(batch)]
    out = _chat(cfg, system, "\n".join(lines), temperature=0.2)
    parsed = _parse_json(out) or []
    by_i = {}
    if isinstance(parsed, list):
        for el in parsed:
            if isinstance(el, dict) and "i" in el:
                by_i[int(el["i"])] = el
    res = []
    for i in range(len(batch)):
        el = by_i.get(i, {})
        def _clean(key, allowed, _el=el):
            return [str(v).strip() for v in (_el.get(key) or [])
                    if str(v).strip() in allowed]
        res.append({
            "content_type": _clean("content_type", set(CONTENT_TYPE_OPTIONS)),
            "product_cat":  _clean("product_cat",  set(PRODUCT_CAT_OPTIONS)),
            "industry":     _clean("industry",      set(INDUSTRY_OPTIONS)),
        })
    return res


# ──────────────────── 风格提炼 ────────────────────

def _extract_style(cfg, dim, dim_value, samples):
    """对一组样本，提炼「风格画像」——HOW to write，不是 WHAT。
    返回结构化文本（分点，六个维度：钩子/口吻/节奏/句式/收尾/禁忌）。"""
    dim_label = STYLE_DIMS.get(dim, dim)
    system = (
        f"你是资深短视频/电商内容风格提炼专家。\n"
        f"分析「{dim_label}：{dim_value}」的真实视频/图文样本，"
        "**只提炼写作风格特征——怎么写(HOW)，不是写什么内容(WHAT)**。\n"
        "输出结构化风格画像，要具体可操作（可直接套用于脚本改写）：\n"
        "① 开头钩子：用什么方式开头（数字冲击/疑问句/痛点场景/玩梗/反常识…）\n"
        "② 语气口吻：说话方式、人称（你/我/咱）、情绪温度（理性/激情/毒舌/友好…）\n"
        "③ 内容节奏：信息密度、转折节点、起承转合节拍\n"
        "④ 常用句式：高频句型模板（可含XXX占位符，如「XXX是个_____但_____」）\n"
        "⑤ 结尾方式：收尾套路（悬念/结论/互动引导/CTA…）\n"
        "⑥ 风格禁忌：这种风格里不该有的表达方式\n"
        "分点输出，每点2-3句简洁可执行的规则，不要泛泛而谈。"
    )
    texts = [f"- {_sample_text(it)}" for it in samples[:MAX_GROUP_SAMPLES]]
    user = f"共 {len(samples)} 条样本，节选如下：\n" + "\n".join(texts)
    return _chat(cfg, system, user, temperature=0.5).strip()


# ──────────────────── 热点归纳（保持原逻辑） ────────────────────

def distill_hotspots(hotspot_mgr, my_knowledge_mgr, cfg, progress_cb=None):
    """
    把热点趋势库按 科技/数码/AI 分类，用 LLM 归纳成「选题方向」知识写入「我的知识库」。
    返回 (created, updated, msg)。
    """
    import os as _os
    import time as _t

    def emit(m):
        if progress_cb:
            progress_cb(m)
        log.info(f"[hotspot-distill] {m}")

    if not cfg.get("model"):
        return 0, 0, "未配置 LLM 模型。"
    cats = ["AI", "数码", "科技"]
    existing = {(it.get("dim"), it.get("dim_value")): it
                for it in my_knowledge_mgr.items if it.get("distilled")}
    created = updated = 0
    for cat in cats:
        topics = hotspot_mgr.query(category=cat)
        if not topics:
            continue
        emit(f"归纳【热点·{cat}】（{len(topics)} 个话题）…")
        lines = []
        for t in topics[:40]:
            trend = f"上榜{t.get('days_on_board',1)}天/最新排名{t.get('latest_rank')}"
            lines.append(f"- [{t.get('platform')}] {t.get('title')}（{trend}）")
        system = (f"你是资深科技/数码内容选题策划。下面是近期 {cat} 相关的平台热榜话题(含上榜天数与排名趋势)。"
                  "请归纳：当前最值得做的选题方向、正在升温的趋势、可切入的内容角度，"
                  "提炼成可直接用于选题决策的要点(分点，标注哪些是持续上榜的强趋势)。")
        try:
            content = _chat(cfg, system, "\n".join(lines), temperature=0.5).strip()
        except Exception as e:  # _chat 外部 LLM API 调用
            log.error(f"热点归纳失败({cat}): {e}")
            continue
        if not content:
            continue
        name = f"【热点选题】{cat}"
        key = ("hotspot", cat)
        if key in existing:
            existing[key].update({"name": name, "type": "选题方向", "content": content,
                                  "source_count": len(topics)})
            updated += 1
        else:
            my_knowledge_mgr.items.append({
                "id": _os.urandom(8).hex(), "name": name, "type": "选题方向",
                "content": content, "distilled": True, "dim": "hotspot", "dim_value": cat,  # noqa: E501
                "source_count": len(topics),
                "created_at": int(_t.time()), "updated_at": int(_t.time()),
            })
            created += 1
    my_knowledge_mgr.save()
    return created, updated, f"热点蒸馏完成：新增 {created}、更新 {updated} 条选题方向。"


# ──────────────────── 主流程 ────────────────────

def run_distillation(manager, cfg, progress_cb=None):
    """
    对 manager 里的「风格参考样本」做打标+四维度风格提炼，写回「风格化」条目。
    cfg = {"api_url","api_key","model"}。返回 (created, updated, msg)。

    四个维度：
      account      = 来自 source.creator（无需打标）
      content_type = LLM 打标，从 CONTENT_TYPE_OPTIONS 选
      product_cat  = LLM 打标，从 PRODUCT_CAT_OPTIONS 选
      industry     = LLM 打标，从 INDUSTRY_OPTIONS 选
    """
    def emit(m):
        if progress_cb:
            progress_cb(m)
        log.info(f"[stylize] {m}")

    if not cfg.get("model"):
        return 0, 0, "未配置 LLM 模型。"

    samples = [it for it in manager.all_items()
               if it.get("type") == REFERENCE_TYPE and (it.get("content") or "").strip()]  # noqa: E501
    if not samples:
        return 0, 0, "没有可提炼的「风格参考样本」。请先在素材浏览器同步收藏/点赞并导入。"

    # ① 打标（按批）：给每条样本打 content_type / product_cat / industry
    emit(f"开始为 {len(samples)} 条样本打标（内容类型/产品品类/行业垂类）…")
    for start in range(0, len(samples), TAG_BATCH):
        batch = samples[start:start + TAG_BATCH]
        try:
            tags = _tag_batch(cfg, batch)
        except Exception as e:  # _tag_batch 含外部 LLM API 调用
            log.error(f"打标失败(批 {start}): {e}")
            tags = [{"content_type": [], "product_cat": [], "industry": []} for _ in batch]  # noqa: E501
        for it, tg in zip(batch, tags, strict=False):
            it["_style_tags"] = tg
        emit(f"打标进度 {min(start + TAG_BATCH, len(samples))}/{len(samples)}")
    manager.save()

    # ② 按四维度分组
    groups: dict[str, Any] = {"account": {}, "content_type": {}, "product_cat": {}, "industry": {}}
    for it in samples:
        # 账号维度：来自 source.creator
        creator = (it.get("source") or {}).get("creator", "").strip()
        if creator:
            groups["account"].setdefault(creator, []).append(it)
        # 其余维度：来自打标
        tg = it.get("_style_tags") or {}
        for ct in tg.get("content_type", []):
            groups["content_type"].setdefault(ct, []).append(it)
        for pc in tg.get("product_cat", []):
            groups["product_cat"].setdefault(pc, []).append(it)
        for ind in tg.get("industry", []):
            groups["industry"].setdefault(ind, []).append(it)

    # 已有的风格化条目（按 维度+取值 去重更新）
    existing = {(it.get("dim"), it.get("dim_value")): it
                for it in manager.items
                if it.get("distilled") and it.get("type") == STYLIZATION_TYPE}

    created = updated = 0
    for dim, mapping in groups.items():
        floor = 1 if dim == "account" else MIN_GROUP_SAMPLES
        for value, items in mapping.items():
            if len(items) < floor:
                continue
            dim_label = STYLE_DIMS.get(dim, dim)
            emit(f"提炼【{dim_label}：{value}】风格化（{len(items)} 条样本）…")
            try:
                content = _extract_style(cfg, dim, value, items)
            except Exception as e:  # _extract_style 外部 LLM API 调用
                log.error(f"风格提炼失败({dim}:{value}): {e}")
                continue
            if not content:
                continue
            name = f"【{dim_label}】{value}"
            key = (dim, value)
            srcs = [(it.get("source") or {}).get("url", "") for it in items]
            init_score = MyKnowledgeManager.initial_score(len(items))
            if key in existing:
                ex = existing[key]
                ex.update({
                    "name": name, "type": STYLIZATION_TYPE, "content": content,
                    "source_count": len(items), "source_urls": srcs,
                })
                # 重新提炼时按新样本量重算初始分，但保留用户反馈累积的差值
                old_base = MyKnowledgeManager.initial_score(ex.get("source_count", len(items)))  # noqa: E501
                feedback_delta = round(ex.get("score", old_base) - old_base, 1)
                ex["score"] = round(min(max(init_score + feedback_delta, 0.0), 10.0), 1)
                updated += 1
            else:
                import os
                import time
                manager.items.append({
                    "id": os.urandom(8).hex(), "name": name,
                    "type": STYLIZATION_TYPE,
                    "content": content, "distilled": True,
                    "dim": dim, "dim_value": value,
                    "source_count": len(items), "source_urls": srcs,
                    "score": init_score,
                    "like_count": 0, "dislike_count": 0,
                    "created_at": int(time.time()), "updated_at": int(time.time()),
                })
                created += 1
    manager.save()
    n_acc = len(groups["account"])
    n_ct  = len(groups["content_type"])
    n_pc  = len(groups["product_cat"])
    n_ind = len(groups["industry"])
    msg = (f"风格化提炼完成：新增 {created} 条、更新 {updated} 条「风格化」"
           f"（账号 {n_acc} / 内容类型 {n_ct} / 产品品类 {n_pc} / 行业 {n_ind} 个分组）。")
    emit(msg)
    return created, updated, msg
