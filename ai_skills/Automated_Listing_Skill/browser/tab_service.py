# -*- coding: utf-8 -*-
"""
tab_service.py
【服务与履约】Tab 相关操作：
  - 商品状态设为下架（_fill_service_and_fulfillment）

DOM 结构说明（实测确认）：
  - 商品状态 radio 组容器: .ecom-g-radio-group.ecom-g-radio-group-outline
  - 每个选项:             label.ecom-g-radio-wrapper  (innerText 含 "上架" 或 "下架")
  - 目标:                 label.ecom-g-radio-wrapper 且 innerText === "下架"
"""

import asyncio
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR
from .tab_navigation import _switch_to_tab


async def _fill_service_and_fulfillment(page) -> None:
    # --- 切换到【服务与履约】Tab ---
    try:
        switched = await _switch_to_tab(page, "服务与履约")
        if not switched:
            print("[WARN] 切换到【服务与履约】失败")
            return
    except Exception as e:
        print(f"[WARN] 切换到【服务与履约】失败: {e}")
        return

    await asyncio.sleep(0.8)

    # --- 将商品状态设为"下架" ---
    try:
        # 使用我们在诊断中确认的精准选择器
        offsale_loc = page.locator('.ecom-g-radio-wrapper:not(.ecom-g-radio-wrapper-disabled)').filter(
            has_text="下架"
        ).first

        if await offsale_loc.count() > 0:
            # 检查是否已选中
            is_checked = await offsale_loc.evaluate("el => el.classList.contains('ecom-g-radio-wrapper-checked') || !!el.querySelector('input:checked')")
            
            if is_checked:
                print("[OK] 商品状态已经是【下架】，无需重复点击")
            else:
                await offsale_loc.scroll_into_view_if_needed(timeout=5000)
                await asyncio.sleep(0.3)
                # 使用 Playwright 的原生点击（模拟真实鼠标），触发 React/Vue 状态同步更稳健
                await offsale_loc.click(timeout=5000)
                await asyncio.sleep(0.8)
                print("[OK] 已成功点击选择：下架")
        else:
            # 最后的 JS 保底逻辑
            print("[WARN] 未找到'下架'选项，尝试 JS 强制查找...")
            result = await page.evaluate("""() => {
                const labels = Array.from(document.querySelectorAll('label, .ecom-g-radio-wrapper'));
                const target = labels.find(el => el.innerText?.trim() === '下架' && el.getBoundingClientRect().width > 0);
                if (target) {
                    target.scrollIntoView({block: 'center'});
                    target.click();
                    const inp = target.querySelector('input');
                    if (inp) inp.click();
                    return true;
                }
                return false;
            }""")
            if result:
                print("[OK] 已通过 JS 强制点击：下架")
            else:
                print("[WARN] 最终未能找到'下架'选择按钮，请检查页面结构")

    except Exception as e:
        print(f"[WARN] 设置商品状态为下架失败: {e}")

    # --- 截图留档 ---
    try:
        shot = os.path.join(RESULT_DIR, "service_offsale.png")
        await page.screenshot(path=shot, full_page=True, timeout=5000)
        print(f"[SHOT] 服务与履约（下架）截图已保存：{shot}")
    except Exception:
        pass
