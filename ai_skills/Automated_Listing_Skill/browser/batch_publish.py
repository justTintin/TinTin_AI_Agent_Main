# -*- coding: utf-8 -*-
"""
batch_publish.py  ——  协调层（Orchestrator）
抖店商品创建全流程调度，约 120 行。
具体 Tab 操作已拆分为独立子模块：
  - chrome_manager.py   Chrome 启动/连接
  - excel_reader.py     sku.xlsx 读取
  - tab_navigation.py   Tab 切换/抽屉关闭
  - tab_basic_info.py   【基础信息】Tab
  - tab_image_text.py   【图文信息】Tab
  - tab_price_inventory.py  【价格库存】Tab
  - tab_service.py      【服务与履约】Tab
  - tab_other_info.py   【其他信息】Tab + 保存草稿
"""

import asyncio
import os
import sys
import io
import traceback
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import (
    CHROME_DEBUG_PORT, CHROME_USER_DATA, RESULT_DIR,
    DOUYIN_STORES, ensure_dirs,
)
ensure_dirs()

# sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
# sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

# ── 子模块导入 ──────────────────────────────────────────────────────────────
from browser.chrome_manager import ensure_debug_chrome
from browser.excel_reader import (
    _resolve_working_dir,
    _find_latest_batch_dir,
    _collect_main_images,
    _read_title_from_sheet2,
)
from browser.tab_basic_info import (
    _detect_current_store_name,
    _goto_product_create,
    _upload_main_images,
    _detect_category_auto_filled,
    _try_select_recommended_category,
    _click_next_step,
    _fill_brand,
    _fill_model_and_manufacturer,
)
from browser.tab_image_text import _fill_image_text_info
from browser.tab_price_inventory import _fill_price_and_inventory
from browser.tab_service import _fill_service_and_fulfillment
from browser.tab_other_info import _fill_other_info, _save_draft


async def auto_create_product() -> int:
    """
    抖店商品创建全流程编排。
    检测当前活动 Tab，从对应阶段恢复——支持断点续跑。
    退出码：0=成功，2=未登录，3=异常，4=店铺不匹配，5=无法打开创建页
    """
    shop_key = os.environ.get("ALS_SHOP_KEY", "")
    shop_name = os.environ.get("ALS_SHOP_NAME", "")
    shop_homepage_url = os.environ.get("ALS_SHOP_HOMEPAGE_URL", "")
    input_dir = (
        os.environ.get("ALS_UPLOAD_DIR")
        or os.environ.get("ALS_INPUT_DIR")
        or os.environ.get("ALS_WORKING_DIR")
        or ""
    ).strip()

    async with async_playwright() as p:
        try:
            print("=" * 50)
            print("抖店商品创建脚本")
            print("=" * 50)

            ensure_debug_chrome(CHROME_DEBUG_PORT, CHROME_USER_DATA)
            print(f"\n[1/4] 正在连接到本地 Chrome（端口 {CHROME_DEBUG_PORT}）...")
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CHROME_DEBUG_PORT}")

            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()

            title = await page.title()
            print(f"[OK] 连接成功！当前页面：{title}")
            print(f"     URL: {page.url}")

            if "login" in page.url.lower() or "passport" in page.url.lower():
                print("[ERROR] 未登录状态，请先在浏览器中登录抖店")
                return 2
            print("[OK] 已确认登录状态")

            # ── 店铺校验 ────────────────────────────────────────────────────
            target_keywords = _build_target_keywords(shop_key, shop_name)
            if shop_name:
                print(f"[SHOP] 目标店铺: {shop_name}")
                if shop_homepage_url and "fxg.jinritemai.com/ffa/" not in page.url:
                    await page.goto(shop_homepage_url)
                    await asyncio.sleep(2)
                all_keywords = _build_all_keywords()
                current_store = await _detect_current_store_name(page, target_keywords + all_keywords)
                if current_store:
                    print(f"[SHOP] 当前页面店铺识别：{current_store}")
                    if not any(k and (k in current_store or current_store in k) for k in target_keywords):
                        print(f"[ERROR] 当前页面店铺与目标店铺不一致，期望：{shop_name}")
                        return 4
                else:
                    page_text = await page.locator("body").inner_text()
                    if not any(k and k in page_text for k in target_keywords):
                        print("[WARN] 未能可靠识别当前店铺，请人工确认右上角店铺后再继续")
                print("[OK] 店铺校验通过")

            # ── 打开商品创建页 ────────────────────────────────────────────
            print("\n[2/4] 正在打开“商品创建”页面...")
            if not await _goto_product_create(page):
                print("[ERROR] 未能打开“商品创建”页面")
                return 5

            shot = os.path.join(RESULT_DIR, "product_create_page.png")
            try:
                await page.screenshot(path=shot, full_page=True, timeout=5000)
            except Exception:
                pass
            print(f"[SHOT] 已保存页面截图：{shot}")
            print(f"[PAGE] 当前页面标题：{await page.title()}")
            print(f"[PAGE] 当前页面URL：{page.url}")

            # ── 解析工作目录 ─────────────────────────────────────────────
            resolved_input_dir = input_dir or _find_latest_batch_dir(target_keywords)
            working_dir = _resolve_working_dir(resolved_input_dir)

            # ── 检测当前活跃 Tab，实现断点续跑 ──────────────────────────
            current_tab = await _detect_active_tab(page)
            is_step2 = await _detect_is_step2(page)
            is_step_price = await _detect_is_price_step(page)

            if current_tab == "其他信息":
                print("\n[INFO] 断点恢复：从【其他信息】继续")
                await _fill_other_info(page)
                await _save_draft(page)
                return 0

            if current_tab == "服务与履约":
                print("\n[INFO] 断点恢复：从【服务与履约】继续")
                await _fill_service_and_fulfillment(page)
                await _fill_other_info(page)
                await _save_draft(page)
                return 0

            if current_tab == "价格库存" or is_step_price:
                print("\n[INFO] 断点恢复：从【价格库存】继续")
                await _fill_price_and_inventory(page, working_dir)
                await _fill_service_and_fulfillment(page)
                await _fill_other_info(page)
                await _save_draft(page)
                return 0

            if current_tab == "图文信息":
                print("\n[INFO] 断点恢复：从【图文信息】继续")
                await _fill_image_text_info(page, working_dir)
                await _fill_price_and_inventory(page, working_dir)
                await _fill_service_and_fulfillment(page)
                await _fill_other_info(page)
                await _save_draft(page)
                return 0

            if current_tab == "基础信息" or is_step2:
                print("\n[INFO] 断点恢复：从【基础信息】继续")
                await _fill_brand(page, working_dir)
                await _fill_model_and_manufacturer(page, working_dir)
                await _fill_image_text_info(page, working_dir)
                await _fill_price_and_inventory(page, working_dir)
                await _fill_service_and_fulfillment(page)
                await _fill_other_info(page)
                await _save_draft(page)
                return 0

            # ── 区分页面执行逻辑 (通过 URL 是否包含 '?' 判断) ─────────────────────────
            current_url = page.url
            if "?" not in current_url and current_url.rstrip("/").endswith("create"):
                print("\n[INFO] 当前在第一阶段（无参数的 create 页面），开始处理 主图/标题/类目...")
                
                print("\n[STEP] 主图上传")
                main_images = _collect_main_images(working_dir)
                if not main_images:
                    print(f"[WARN] 未找到主图目录或无可上传图片，working_dir={working_dir}")
                else:
                    print(f"[OK] 主图数量: {len(main_images)}")
                    ok_upload = await _upload_main_images(page, main_images)
                    if ok_upload:
                        shot2 = os.path.join(RESULT_DIR, "main_images_uploaded.png")
                        await page.screenshot(path=shot2, full_page=True)
                        print(f"[SHOT] 主图上传后截图已保存：{shot2}")
                    else:
                        print("[WARN] 主图上传未完成，请检查页面是否存在可用的上传控件")

                print("\n[STEP] 填写商品标题")
                title_text = ""
                title_from_sheet2 = _read_title_from_sheet2(working_dir) if working_dir else ""
                if title_from_sheet2:
                    title_text = title_from_sheet2.strip()[:60]
                    try:
                        title_input = page.locator('input[placeholder*="请输入2-60"]').first
                        await title_input.wait_for(timeout=15000)
                        await title_input.fill(title_text)
                        await asyncio.sleep(0.3)
                        await page.keyboard.press("Tab")
                        await asyncio.sleep(0.5)
                        shot_t = os.path.join(RESULT_DIR, "title_filled.png")
                        await page.screenshot(path=shot_t, full_page=True)
                        print(f"[OK] 商品标题已填写: {title_text}")
                    except Exception:
                        print("[WARN] 未找到商品标题输入框或填写失败")
                else:
                    print("[WARN] 未从 sku.xlsx 的第二个工作表解析到标题")

                print("\n[STEP] 自动填充类目")
                print("[WAIT] 等待 5 秒用于类目自动填充...")
                await asyncio.sleep(5)
                try:
                    await page.screenshot(path=os.path.join(RESULT_DIR, "category_wait.png"), full_page=True)
                except Exception:
                    pass

                category_value = await _detect_category_auto_filled(page, title_text)
                if not category_value:
                    if await _try_select_recommended_category(page):
                        await asyncio.sleep(1.2)
                        category_value = await _detect_category_auto_filled(page, title_text)
                        try:
                            if await _click_next_step(page):
                                await asyncio.sleep(2)
                                await page.screenshot(path=os.path.join(RESULT_DIR, "after_next_2.png"), full_page=True)
                        except Exception:
                            pass
                if not category_value:
                    try:
                        if await page.locator("text=类目推荐").count() > 0:
                            category_value = "类目推荐"
                    except Exception:
                        pass
                if category_value:
                    print(f"[OK] 检测到类目已自动填充: {category_value}")
                    try:
                        if await _click_next_step(page):
                            await asyncio.sleep(2)
                            await page.screenshot(path=os.path.join(RESULT_DIR, "after_next.png"), full_page=True)
                            print("[OK] 已点击下一步")
                    except Exception:
                        print("[WARN] 类目已填充，但点击下一步失败")
                else:
                    print("[WARN] 未检测到类目自动填充")

                print("\n[INFO] 第一阶段执行完毕。请确认页面已进入下一步 (带参数的 create? 页面)，如果需要继续，请再次执行。")
                return 0
                
            else:
                # 如果包含 /create? 或者进入了第二阶段
                print("\n[INFO] 当前在第二阶段（带参数的 create? 页面），执行后续 Tab 流程...")

                print("\n[STEP] 基础信息")
                await _fill_brand(page, working_dir)
                await _fill_model_and_manufacturer(page, working_dir)

                print("\n[STEP] 图文信息")
                await _fill_image_text_info(page, working_dir)

                print("\n[STEP] 价格库存")
                await _fill_price_and_inventory(page, working_dir)

                print("\n[STEP] 服务与履约")
                await _fill_service_and_fulfillment(page)

                print("\n[STEP] 其他信息")
                await _fill_other_info(page)

                print("\n[STEP] 保存草稿")
                is_saved = await _save_draft(page)

                print("\n" + "=" * 50)
                if is_saved:
                    print("[DONE] 全流程完成并保存成功")
                    return 0
                else:
                    print("[FAILED] 保存草稿失败，可能由于必填项未通过校验。")
                    return 4

        except Exception as e:
            print(f"\n[ERROR] 操作失败：{e}")
            traceback.print_exc()
            print(f"\n请确认：")
            print(f"1. Chrome 已使用 --remote-debugging-port={CHROME_DEBUG_PORT} 启动")
            print(f"2. 可在浏览器访问 http://127.0.0.1:{CHROME_DEBUG_PORT}/json 验证端口")
            print("3. 已登录抖店后台")
            return 3

        finally:
            print("\n脚本执行完毕（浏览器保持打开）")


# ── 私有辅助 ─────────────────────────────────────────────────────────────────

def _build_target_keywords(shop_key: str, shop_name: str) -> list:
    target = [shop_name or shop_key]
    for _k, info in (DOUYIN_STORES or {}).items():
        if _k == shop_key:
            target = [info.get("name", "")] + (info.get("aliases", []) or [])
            break
    return [k for k in target if isinstance(k, str) and k.strip()]


def _build_all_keywords() -> list:
    out = []
    for _k, info in (DOUYIN_STORES or {}).items():
        out.append(info.get("name", ""))
        out.extend(info.get("aliases", []) or [])
    out = [k for k in out if isinstance(k, str) and k.strip()]
    out.sort(key=len, reverse=True)
    return out


async def _detect_active_tab(page) -> str:
    try:
        val = await page.evaluate(
            "() => { const a = document.querySelector('.ant-tabs-tab-active'); return a ? a.textContent.trim() : ''; }"
        )
        return val or "未知"
    except Exception:
        return "未知"


async def _detect_is_step2(page) -> bool:
    try:
        return (
            await page.locator("text=类目属性").count() > 0
            and await page.locator("text=基础信息").count() > 0
        )
    except Exception:
        return False


async def _detect_is_price_step(page) -> bool:
    try:
        return (
            await page.locator("text=价格库存").count() > 0
            and await page.locator("text=商品规格").count() > 0
            and await page.locator('input[placeholder*="请输入型号"]').count() > 0
        )
    except Exception:
        return False


async def batch_publish_products() -> int:
    return await auto_create_product()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(auto_create_product()))
