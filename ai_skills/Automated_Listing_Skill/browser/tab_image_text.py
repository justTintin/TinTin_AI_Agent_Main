# -*- coding: utf-8 -*-
"""
tab_image_text.py
【图文信息】Tab 相关操作：
  - 商品详情图上传（_fill_image_text_info）

DOM 结构说明（抖店商品创建页 - 实测确认）：
  - 商详图片区域容器: class 含 "goods-publish-highlight-item"
  - 图片标题 label:   class 含 "decorateImgEditTitle"（不含 "Wrapper"）
  - 每张图片包裹:     class 含 "imgWrapper"
  - 删除按钮:         i[class*="iconDelete"]  ← 无需 hover，直接可见可点击
  - 上传控件:         input[type="file"] 在同一容器内
"""

import asyncio
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR
from .tab_navigation import _switch_to_tab, _close_right_drawer, _handle_common_modals
from .tab_basic_info import _wait_upload_done


# ---------------------------------------------------------------------------
# 内部辅助：删除商详图片区域内的所有现有图片
# ---------------------------------------------------------------------------

async def _delete_detail_images_js(page) -> int:
    """
    通过 JavaScript 直接点击 [class*='iconDelete'] 按钮，
    删除商详图片区域内的所有图片。
    返回实际删除张数。
    """
    try:
        # 截图记录删除前状态
        try:
            await page.screenshot(path=os.path.join(RESULT_DIR, "before_delete.png"))
        except Exception:
            pass

        # 获取当前商详图片数量（通过 iconDelete 个数）
        initial_count = await page.evaluate("""() => {
            return document.querySelectorAll('[class*="iconDelete"]').length;
        }""")
        print(f"[INFO] 商详图片当前数量: {initial_count}")

        if initial_count <= 0:
            print("[INFO] 商详区域无图片，跳过删除")
            return 0

        removed = 0
        for _ in range(initial_count + 5):  # 留余量防止意外
            remaining = await page.evaluate("""() => {
                return document.querySelectorAll('[class*="iconDelete"]').length;
            }""")
            if remaining == 0:
                break

            # JS 直接点击第一个删除图标
            clicked = await page.evaluate("""() => {
                const btn = document.querySelector('[class*="iconDelete"]');
                if (!btn) return false;
                btn.scrollIntoView({block: 'center'});
                btn.click();
                return true;
            }""")
            if not clicked:
                break

            await asyncio.sleep(0.3)

            # 处理可能出现的确认弹窗（popover / modal）
            confirm = page.locator(
                '.ant-popover button:has-text("确定"), .ant-modal button:has-text("确定"), '
                '.ant-popover button:has-text("删除"), .ant-modal button:has-text("删除")'
            ).first
            if await confirm.count() > 0:
                try:
                    await confirm.click(timeout=2000, force=True)
                    await asyncio.sleep(0.2)
                except Exception:
                    pass

            await asyncio.sleep(0.3)
            removed += 1
            if removed % 5 == 0:
                print(f"[INFO] 已删除 {removed} 张商详图片...")

        print(f"[OK] 商详图片清理完成，共删除 {removed} 张")
        return removed

    except Exception as e:
        print(f"[WARN] 删除商详图片时出错: {e}")
        return 0


# ---------------------------------------------------------------------------
# 内部辅助：向商详图片区域上传本地图片
# ---------------------------------------------------------------------------

async def _upload_detail_images_js(page, detail_images: list) -> bool:
    """
    在 goods-publish-highlight-item + decorateImgEditTitle 限定的容器内
    找到 input[type='file'] 并上传商详图片。
    策略优先级：
      1. JS 定位 input element_handle → set_input_files (最快)
      2. Playwright locator 定位容器内 input → 批量或逐张
      3. 点击 "上传图片" 按钮触发 file chooser
    """
    try:
        print(f"[INFO] 开始上传 {len(detail_images)} 张商详图片...")

        # --- 策略 1：JS 直接找商详区域内的 input[type="file"] ---
        file_input_handle = await page.evaluate_handle("""() => {
            // 找到商详图片标题元素（class 含 decorateImgEditTitle 且不含 Wrapper）
            const label = Array.from(document.querySelectorAll('div, span, label')).find(el => {
                const cls = (el.className?.baseVal || el.className || '').toString();
                return cls.includes('decorateImgEditTitle') && !cls.includes('Wrapper');
            });
            if (!label) return null;
            // 向上查找包含 input[type="file"] 的祖先容器
            let node = label;
            for (let i = 0; i < 20; i++) {
                node = node.parentElement;
                if (!node) return null;
                const inp = node.querySelector('input[type="file"]');
                if (inp) return inp;
            }
            return null;
        }""")

        element = file_input_handle.as_element() if file_input_handle else None
        if element:
            print("[INFO] 使用 element_handle 直接上传...")
            await element.set_input_files(detail_images)
            await _wait_upload_done(page, timeout_ms=300000)
            await _handle_common_modals(page)
            print("[OK] 商详图片上传完成")
            return True

        # --- 策略 2：Playwright locator 在商详容器内找 input ---
        section_loc = page.locator('[class*="goods-publish-highlight-item"]').filter(
            has=page.locator('[class*="decorateImgEditTitle"]')
        ).last

        if await section_loc.count() > 0:
            file_inp = section_loc.locator('input[type="file"]').first
            if await file_inp.count() > 0:
                is_multiple = await file_inp.evaluate("el => !!el.multiple")
                if is_multiple:
                    print("[INFO] 批量上传模式...")
                    await file_inp.set_input_files(detail_images)
                    await _wait_upload_done(page, timeout_ms=300000)
                    await _handle_common_modals(page)
                else:
                    print("[INFO] 逐张上传模式...")
                    for i, img in enumerate(detail_images):
                        await _handle_common_modals(page)
                        cur_input = section_loc.locator('input[type="file"]').first
                        await cur_input.set_input_files(img)
                        await _wait_upload_done(page, timeout_ms=60000)
                        await _handle_common_modals(page)
                        await asyncio.sleep(0.3)
                        if (i + 1) % 5 == 0:
                            print(f"[INFO] 已上传 {i + 1}/{len(detail_images)} 张...")
                print("[OK] 商详图片上传完成")
                return True

            # --- 策略 3：点击 "上传图片" 按钮触发 file chooser ---
            upload_btn = section_loc.locator('button:has-text("上传图片")').first
            if await upload_btn.count() > 0:
                print("[INFO] 通过按钮逐张上传...")
                for i, img in enumerate(detail_images):
                    await _close_right_drawer(page)
                    await _handle_common_modals(page)
                    async with page.expect_file_chooser(timeout=10000) as fc_info:
                        await upload_btn.click(timeout=5000, force=True)
                    fc = await fc_info.value
                    await fc.set_files(img)
                    await _wait_upload_done(page, timeout_ms=60000)
                    await _handle_common_modals(page)
                    await asyncio.sleep(0.3)
                    if (i + 1) % 5 == 0:
                        print(f"[INFO] 已上传 {i + 1}/{len(detail_images)} 张...")
                print("[OK] 商详图片上传完成")
                return True

        print("[WARN] 未找到商详图片上传控件，跳过上传")
        return False

    except Exception as e:
        print(f"[ERROR] 上传商详图片时出错: {e}")
        return False


# ---------------------------------------------------------------------------
# 公开入口：由 batch_publish.py 调用
# ---------------------------------------------------------------------------

async def _fill_image_text_info(page, working_dir: str):
    """
    【图文信息】Tab 入口：
      1. 切换到图文信息 Tab
      2. 删除商详图片区域内的默认图片
      3. 从本地 working_dir 下的 详情/详情页 目录上传图片
    注意：不处理主图，主图由调用方在进入此页面前已完成。
    """
    print("\n[PAGE] 准备填写图文信息 -> 商品详情")

    # --- 切换到图文信息 Tab ---
    if not await _switch_to_tab(page, "图文信息"):
        print("[WARN] 未能切换到【图文信息】标签页")
        return

    try:
        await _close_right_drawer(page)
        await _handle_common_modals(page)
    except Exception:
        pass

    # --- 收集本地详情图（来自 详情/ 或 详情页/ 子目录）---
    detail_images = []
    if working_dir and os.path.isdir(working_dir):
        for root, _dirs, files in os.walk(working_dir):
            if "详情" in root or "详情页" in root:
                for f in sorted(files):
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        detail_images.append(os.path.join(root, f))
                break  # 只取第一个匹配目录

    if not detail_images:
        print(f"[WARN] 未找到详情图目录或无可上传图片，working_dir={working_dir}")
        return

    print(f"[OK] 找到 {len(detail_images)} 张本地详情图")

    # --- 滚动到商详图片区域 ---
    try:
        scrolled = await page.evaluate("""() => {
            const label = Array.from(document.querySelectorAll('div, span, label')).find(el => {
                const cls = (el.className?.baseVal || el.className || '').toString();
                return cls.includes('decorateImgEditTitle') && !cls.includes('Wrapper');
            });
            if (!label) return false;
            label.scrollIntoView({block: 'center'});
            return true;
        }""")
        await asyncio.sleep(0.8 if scrolled else 0.3)
        if not scrolled:
            await page.evaluate("window.scrollBy(0, window.innerHeight * 0.5)")
            await asyncio.sleep(0.5)
    except Exception:
        pass

    # --- 删除现有商详图片 ---
    await _delete_detail_images_js(page)
    await asyncio.sleep(0.5)

    # --- 上传本地详情图 ---
    success = await _upload_detail_images_js(page, detail_images)

    # --- 结果截图 ---
    if success:
        try:
            shot = os.path.join(RESULT_DIR, "detail_images_final.png")
            await page.screenshot(path=shot, full_page=True)
            print(f"[SHOT] 结果截图已保存：{shot}")
        except Exception:
            pass
    else:
        print("[WARN] 详情图上传未成功完成，请检查页面状态")
