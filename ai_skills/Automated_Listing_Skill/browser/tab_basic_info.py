# -*- coding: utf-8 -*-
"""
tab_basic_info.py
【基础信息】Tab 相关操作：
  - 类目自动填充检测（_detect_category_auto_filled）
  - 推荐类目选择（_try_select_recommended_category）
  - 下一步点击（_click_next_step）
  - 主图上传（_upload_main_images / _wait_upload_done）
  - 品牌填写（_fill_brand）
  - 标签输入通用（_fill_text_input_by_label）
  - 型号/生产厂家填写（_fill_model_and_manufacturer）
"""

import asyncio
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR
from .excel_reader import _read_brand_from_sku, _read_sheet2_value

async def _detect_category_auto_filled(page, exclude_text: str = "") -> str:
    try:
        v = (await page.evaluate(
            """(excludeText) => {
                const exclude = (excludeText || "").trim();
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                    if (style.pointerEvents === 'none') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const els = Array.from(document.querySelectorAll("span,div,a"));
                const hits = [];
                for (const el of els) {
                    if (!isVisible(el)) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.top < 180 || rect.top > window.innerHeight - 120) continue;
                    if (rect.left < 120 || rect.left > window.innerWidth - 120) continue;
                    const t = (el.textContent || '').trim();
                    if (!t) continue;
                    if (!t.includes('>') && !t.includes('＞')) continue;
                    if (t.includes('返回商家后台') || t.includes('商品发布')) continue;
                    if (t.includes('更多类目') || t.includes('商品标题') || t.includes('下一步')) continue;
                    if (exclude && t.includes(exclude)) continue;
                    if (t.length < 8 || t.length > 240) continue;
                    hits.push({ t, area: rect.width * rect.height, y: rect.y });
                }
                hits.sort((a, b) => b.area - a.area);
                return hits.length ? hits[0].t : '';
            }""",
            exclude_text,
        ) or "").strip()
        if v:
            return v
    except Exception:
        pass

    try:
        label = page.locator("text=商品类目").first
        if await label.count() <= 0:
            label = page.locator("text=类目").first

        if await label.count() > 0:
            container = label.locator('xpath=ancestor::*[contains(@class,"ant-form-item")][1]')
            if await container.count() > 0:
                cand = [
                    container.locator(".ant-cascader-picker-label"),
                    container.locator(".ant-cascader-selection-item"),
                    container.locator(".ant-select-selection-item"),
                    container.locator(".ant-select-selector"),
                ]
                for loc in cand:
                    if await loc.count() > 0:
                        v = (await loc.first.text_content() or "").strip()
                        if v and "请选择" not in v and "类目" not in v and "更多类目" not in v and (">" in v or "＞" in v) and (not exclude_text or exclude_text not in v):
                            return v

                inputs = container.locator("input")
                if await inputs.count() > 0:
                    v = (await inputs.first.input_value() or "").strip()
                    if v and "请选择" not in v and "更多类目" not in v and (">" in v or "＞" in v) and (not exclude_text or exclude_text not in v):
                        return v
    except Exception:
        pass

    try:
        return (await page.evaluate(
            """(excludeText) => {
                const labelTexts = ["商品类目", "类目"];
                const nodes = Array.from(document.querySelectorAll("span,div,label"));
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === "hidden" || style.display === "none") return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const exclude = (excludeText || "").trim();
                for (const n of nodes) {
                    if (!isVisible(n)) continue;
                    const t = (n.textContent || "").trim();
                    if (!t) continue;
                    if (!labelTexts.some(k => t.includes(k))) continue;
                    const container = n.closest(".ant-form-item") || n.parentElement || document.body;
                    const candidates = [];
                    const sel = container.querySelectorAll(".ant-select-selection-item, .ant-cascader-picker-label, .ant-cascader-selection-item, .ant-select-selector, input");
                    for (const el of sel) {
                        if (!isVisible(el)) continue;
                        if (el.tagName === "INPUT") {
                            const v = (el.value || "").trim();
                            if (v) candidates.push(v);
                        } else {
                            const v = (el.textContent || "").trim();
                            if (v) candidates.push(v);
                        }
                    }
                    for (const v of candidates) {
                        if (!v) continue;
                        if (v.includes("请选择")) continue;
                        if (labelTexts.some(k => v.includes(k))) continue;
                        if (exclude && v.includes(exclude)) continue;
                        return v;
                    }
                }
                const label = nodes.find(el => isVisible(el) && (el.textContent || "").trim().includes("商品类目"));
                if (label) {
                    const labelRect = label.getBoundingClientRect();
                    const els = Array.from(document.querySelectorAll("span,div,a,button"));
                    const hits = [];
                    for (const el of els) {
                        if (!isVisible(el)) continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.top < labelRect.bottom - 10) continue;
                        if (rect.top > labelRect.bottom + 260) continue;
                        if (rect.left < labelRect.left - 10) continue;
                        if (rect.left > labelRect.left + 900) continue;
                        const v = (el.textContent || "").trim();
                        if (!v) continue;
                        if (v.length < 3 || v.length > 240) continue;
                        if (v.includes("请选择")) continue;
                        if (v.includes("商品类目")) continue;
                        if (v.includes("更多类目")) continue;
                        if (v.includes("下一步")) continue;
                        if (v.includes("商品标题")) continue;
                        if (exclude && v.includes(exclude)) continue;
                        hits.push({ v, area: rect.width * rect.height });
                    }
                    hits.sort((a, b) => b.area - a.area);
                    if (hits.length) return hits[0].v;
                }
                return "";
            }"""
            ,
            exclude_text,
        ) or "").strip()
    except Exception:
        return ""


async def _try_select_recommended_category(page) -> bool:
    try:
        label = page.locator("text=商品类目").first
        if await label.count() <= 0:
            return False

        container = label.locator('xpath=ancestor::*[contains(@class,"ant-form-item")][1]')
        if await container.count() <= 0:
            return False

        sel = container.locator(".ant-select-selector, .ant-cascader-picker-label, .ant-select-selection-item, .ant-cascader-selection-item").first
        if await sel.count() > 0:
            await sel.click(timeout=1500, force=True)
            await asyncio.sleep(0.6)
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.8)
            return True
    except Exception:
        return False
    return False


async def _click_next_step(page) -> bool:
    try:
        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        pass
    await asyncio.sleep(0.5)

    try:
        cands = page.locator('text=下一步')
        count = await cands.count()
        best_idx = -1
        best_score = -1
        for i in range(count):
            el = cands.nth(i)
            try:
                if not await el.is_visible():
                    continue
                box = await el.bounding_box()
                if not box:
                    continue
                score = int(box.get("y", 0) * 10 + box.get("width", 0))
                if score > best_score:
                    best_score = score
                    best_idx = i
            except Exception:
                continue
        if best_idx >= 0:
            await cands.nth(best_idx).click(timeout=8000, force=True)
            return True
    except Exception:
        pass

    try:
        clicked = await page.evaluate(
            """() => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                    if (style.pointerEvents === 'none') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const els = Array.from(document.querySelectorAll('button,[role="button"],a,div,span'));
                let best = null;
                let bestScore = -1;
                const bottom = window.innerHeight - 260;
                for (const el of els) {
                    if (!isVisible(el)) continue;
                    const t = (el.textContent || '').trim();
                    if (!t || !t.includes('下一步')) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.top < bottom) continue;
                    const score = rect.y * 10 + rect.width;
                    if (score > bestScore) {
                        bestScore = score;
                        best = el;
                    }
                }
                if (best) {
                    best.click();
                    return true;
                }
                return false;
            }"""
        )
        return bool(clicked)
    except Exception:
        return False


async def _wait_upload_done(page, timeout_ms: int = 120000) -> None:
    try:
        await page.locator("text=上传中").first.wait_for(state="detached", timeout=timeout_ms)
    except Exception:
        return


async def _upload_main_images(page, image_paths) -> bool:
    images = [p for p in (image_paths or []) if isinstance(p, str) and p and os.path.isfile(p)]
    if not images:
        return False

    await asyncio.sleep(1)
    try:
        await page.locator("text=主图上传").first.wait_for(timeout=10000)
    except Exception:
        pass

    upload_main = page.locator("text=上传主图").first
    upload_aux = page.locator("text=上传辅图")
    aux_count = await upload_aux.count()
    ant_slots = page.locator(".ant-upload-select, .ant-upload")
    ant_count = await ant_slots.count()

    try:
        if await upload_main.count() > 0:
            async with page.expect_file_chooser(timeout=3000) as fc_info:
                await upload_main.click(timeout=3000, force=True)
            fc = await fc_info.value
            await fc.set_files(images[0])
            await asyncio.sleep(1)
            await _wait_upload_done(page)
        elif ant_count > 0:
            async with page.expect_file_chooser(timeout=3000) as fc_info:
                await ant_slots.first.click(timeout=3000, force=True)
            fc = await fc_info.value
            await fc.set_files(images[0])
            await asyncio.sleep(1)
            await _wait_upload_done(page)
        else:
            raise RuntimeError("未找到“上传主图”入口")

        for i in range(1, len(images)):
            target = None
            if aux_count > 0:
                idx = i - 1
                if idx >= aux_count:
                    idx = aux_count - 1
                target = upload_aux.nth(idx)
            if target is None and ant_count > 0:
                idx = i
                if idx >= ant_count:
                    idx = ant_count - 1
                target = ant_slots.nth(idx)
            if target is None:
                target = upload_main

            async with page.expect_file_chooser(timeout=3000) as fc_info:
                await target.click(timeout=3000, force=True)
            fc = await fc_info.value
            await fc.set_files(images[i])
            await asyncio.sleep(1)
            await _wait_upload_done(page)
        return True
    except Exception:
        file_inputs = page.locator('input[type="file"]')
        count = await file_inputs.count()
        if count <= 0:
            return False

        if count == 1:
            await file_inputs.first.set_input_files(images)
            await _wait_upload_done(page)
            return True

        limit = min(len(images), count)
        for i in range(limit):
            await file_inputs.nth(i).set_input_files(images[i])
            await asyncio.sleep(0.8)
            await _wait_upload_done(page)
        return True


async def _fill_brand(page, working_dir: str):
    brand_val = _read_brand_from_sku(working_dir)
    if not brand_val:
        brand_val = "无品牌"
    
    print(f"[PAGE] 准备填写品牌，目标值: {brand_val}")
    
    try:
        await page.wait_for_selector("text=类目属性", timeout=15000)
        await asyncio.sleep(1)
    except Exception:
        print("[WARN] 未检测到 类目属性 区域，可能页面加载较慢")
    
    if brand_val == "无品牌":
        try:
            clicked = await page.evaluate('''() => {
                const els = Array.from(document.querySelectorAll('a, span, div'));
                for(let el of els) {
                    if(el.textContent && el.textContent.trim() === '无品牌') {
                        const style = window.getComputedStyle(el);
                        if(style.cursor === 'pointer' || el.tagName === 'A' || el.classList.contains('link') || el.style.color.includes('rgb')) {
                            el.click();
                            return true;
                        }
                    }
                }
                return false;
            }''')
            if clicked:
                print("[OK] 已通过快捷链接选中【无品牌】")
                shot_brand = os.path.join(RESULT_DIR, "brand_filled.png")
                await asyncio.sleep(1)
                await page.screenshot(path=shot_brand, full_page=True)
                print(f"[SHOT] 品牌填写后截图已保存：{shot_brand}")
                return
        except Exception as e:
            print(f"[DEBUG] 点击无品牌链接失败: {e}")
            pass

    print(f"[WARN] 快捷无品牌点击失败或非无品牌，将通过下拉框搜索/选择：{brand_val} (该逻辑可继续扩展)")
    shot_brand = os.path.join(RESULT_DIR, "brand_filled.png")
    await page.screenshot(path=shot_brand, full_page=True)


async def _fill_text_input_by_label(page, label: str, value: str) -> bool:
    if not label or not value:
        return False

    try:
        # 新版抖店的表单结构可能变了，先尝试用 label 精确匹配
        # 这里用 Playwright 的 locator 更稳定
        input_loc = page.locator(f"//label[contains(text(), '{label}')]/ancestor::div[contains(@class, 'ant-row')]//input[not(@disabled)]").first
        
        count = await input_loc.count()
        if count > 0:
            await input_loc.scroll_into_view_if_needed()
            await input_loc.click(timeout=2000)
            # 选中并清空现有内容
            await input_loc.press("Control+A")
            await input_loc.press("Backspace")
            await input_loc.fill(value)
            await asyncio.sleep(0.3)
            await page.keyboard.press("Enter") # 触发可能存在的校验或搜索
            await asyncio.sleep(0.3)
            await page.keyboard.press("Escape") # 关掉可能弹出的下拉框
            return True
            
        # 如果 XPath 没找到，使用原来的坐标/结构查找逻辑作为兜底
        marker = f"als-{abs(hash((label, os.getpid())))}"
        ok = await page.evaluate(
            """(payload) => {
                const label = (payload && payload.label) ? String(payload.label) : '';
                const marker = (payload && payload.marker) ? String(payload.marker) : '';
                if (!label || !marker) return false;

                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                    if (style.pointerEvents === 'none') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };

                const nodes = Array.from(document.querySelectorAll('span,div,label')).filter(isVisible);
                const inputs = Array.from(document.querySelectorAll('input')).filter(isVisible);

                let bestInput = null;
                let bestScore = Infinity;
                let bestLabel = null;

                for (const n of nodes) {
                    const t = (n.textContent || '').trim();
                    if (t !== label) continue;
                    const lr = n.getBoundingClientRect();
                    for (const input of inputs) {
                        if (input.disabled) continue;
                        const ir = input.getBoundingClientRect();
                        const dy = ir.top - lr.bottom;
                        if (dy < -20 || dy > 220) continue;
                        const dx = Math.abs(ir.left - lr.left);
                        if (dx > 420) continue;
                        const score = dy * 10 + dx;
                        if (score < bestScore) {
                            bestScore = score;
                            bestInput = input;
                            bestLabel = n;
                        }
                    }
                }

                if (!bestInput) return false;

                bestInput.setAttribute('data-als-target', marker);
                if (bestLabel) bestLabel.scrollIntoView({ block: 'center' });
                return true;
            }""",
            {"label": label, "marker": marker},
        )
        if not ok:
            return False

        target = page.locator(f'input[data-als-target="{marker}"]').first
        await target.wait_for(timeout=5000)
        await target.click(timeout=5000)
        await target.fill(value)
        try:
            await page.keyboard.press("Tab")
        except Exception:
            pass
        await asyncio.sleep(0.2)
        current = (await target.input_value()).strip()
        try:
            await page.evaluate(
                """(marker) => {
                    const el = document.querySelector(`input[data-als-target="${marker}"]`);
                    if (el) el.removeAttribute("data-als-target");
                }""",
                marker,
            )
        except Exception:
            pass
        return current == value.strip() or (value.strip() in current)
    except Exception:
        return False


async def _fill_model_and_manufacturer(page, working_dir: str) -> None:
    from excel_reader import _read_sheet2_value  # 确保导入成功
    
    model = _read_sheet2_value(working_dir, "型号")
    manufacturer = _read_sheet2_value(working_dir, "生产厂家")

    if not model and not manufacturer:
        print("[WARN] sku.xlsx 第二个工作表未找到 型号/生产厂家")
        return

    if model:
        ok = await _fill_text_input_by_label(page, "型号", model)
        print(f"[OK] 型号填写{'成功' if ok else '失败'}: {model}")
    if manufacturer:
        ok = await _fill_text_input_by_label(page, "生产厂家", manufacturer)
        print(f"[OK] 生产厂家填写{'成功' if ok else '失败'}: {manufacturer}")

    try:
        shot = os.path.join(RESULT_DIR, "model_manufacturer_filled.png")
        await asyncio.sleep(0.8)
        await page.screenshot(path=shot, full_page=True)
        print(f"[SHOT] 型号/生产厂家填写后截图已保存：{shot}")
    except Exception:
        pass



async def _detect_current_store_name(page, store_keywords) -> str:
    try:
        keywords = [k for k in (store_keywords or []) if isinstance(k, str) and k.strip()]
        if not keywords:
            return ""

        found = await page.evaluate(
            """(keywords) => {
                const maxTop = 260;
                const minRight = window.innerWidth - 620;
                const nodes = document.querySelectorAll('a,span,div');
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                for (const el of nodes) {
                    if (!isVisible(el)) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.top < 0 || rect.bottom > maxTop) continue;
                    if (rect.right < minRight) continue;
                    const text = (el.textContent || '').trim();
                    if (!text) continue;
                    for (const kw of keywords) {
                        if (text.includes(kw)) return kw;
                    }
                }
                const bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
                for (const kw of keywords) {
                    if (bodyText.includes(kw)) return kw;
                }
                return '';
            }""",
            keywords,
        )
        return (found or "").strip()
    except Exception:
        return ""
    return ""


async def _goto_product_create(page) -> bool:
    if "fxg.jinritemai.com/ffa/g/create" in page.url:
        return True

    candidates = [
        "https://fxg.jinritemai.com/ffa/g/create",
        "https://fxg.jinritemai.com/ffa/mshop/homepage/index#/home/product/create",
    ]

    for url in candidates:
        try:
            await page.goto(url)
            await asyncio.sleep(2)
            if "login" in page.url.lower() or "passport" in page.url.lower():
                return False
            title = await page.title()
            if any(k in title for k in ("创建商品", "商品创建")):
                return True
            body_text = await page.locator("body").inner_text()
            if any(k in body_text for k in ("创建商品", "商品创建", "主图上传")):
                return True
        except Exception:
            continue

    try:
        await page.locator('text="商品"').first.click(timeout=1500)
        await asyncio.sleep(0.5)
    except Exception:
        pass

    try:
        await page.locator("text=商品创建").first.click(timeout=2500)
        await asyncio.sleep(2)
        if "login" in page.url.lower() or "passport" in page.url.lower():
            return False
        title = await page.title()
        if any(k in title for k in ("创建商品", "商品创建")):
            return True
        body_text = await page.locator("body").inner_text()
        return any(k in body_text for k in ("创建商品", "商品创建", "主图上传"))
    except Exception:
        return False
