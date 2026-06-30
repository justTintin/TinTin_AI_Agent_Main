# -*- coding: utf-8 -*-
"""
tab_navigation.py
页面标签切换与右侧浮层关闭（所有 Tab 模块共享）。
  - _close_right_drawer(page)
  - _switch_to_tab(page, tab_name)
"""

import asyncio
import os

async def _close_right_drawer(page) -> bool:
    closed = False
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.2)
    except Exception:
        pass

    try:
        closed = bool(await page.evaluate('''() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            };

            const drawers = Array.from(document.querySelectorAll('.ant-drawer, [class*="drawer"]')).filter(isVisible);
            if (!drawers.length) return false;

            for (const drawer of drawers) {
                const applyBtn = Array.from(drawer.querySelectorAll('button,span,div,a')).find(x => isVisible(x) && (x.textContent || '').trim() === '应用');
                if (applyBtn) {
                    applyBtn.click();
                }
                const closeBtn = drawer.querySelector('.ant-drawer-close, button[aria-label="close"], button[aria-label="Close"], .anticon-close, [class*="close"]');
                if (closeBtn && isVisible(closeBtn)) {
                    closeBtn.click();
                    return true;
                }
            }

            const panels = Array.from(document.querySelectorAll('div,section,aside')).filter(isVisible);
            for (const p of panels) {
                const t = (p.textContent || '').trim();
                if (!t) continue;
                if (t.includes('AI素材工具')) {
                    const closeBtn = p.querySelector('.anticon-close, .ant-drawer-close, button[aria-label="close"], button[aria-label="Close"], [class*="close"], svg');
                    if (closeBtn && isVisible(closeBtn)) {
                        closeBtn.click();
                        return true;
                    }
                }
            }

            const masks = Array.from(document.querySelectorAll('.ant-drawer-mask, .ant-modal-mask, [class*="mask"]')).filter(isVisible);
            if (masks.length) {
                masks[0].click();
                return true;
            }

            return false;
        }'''))
    except Exception:
        closed = False

    if closed:
        try:
            await asyncio.sleep(0.5)
        except Exception:
            pass
        return True

    try:
        apply_btn = page.locator('button:has-text("应用"), text=应用').first
        if await apply_btn.count() > 0:
            try:
                await apply_btn.click(timeout=800, force=True)
                await asyncio.sleep(0.2)
            except Exception:
                pass

        btn = page.locator('.ant-drawer-close, .ant-modal-close, button[aria-label="close"], button[aria-label="Close"], .anticon-close, text=关闭, text=返回').first
        if await btn.count() > 0:
            await btn.click(timeout=1500, force=True)
            await asyncio.sleep(0.5)
            return True
    except Exception:
        pass

    return False

async def _switch_to_tab(page, tab_name: str) -> bool:
    """辅助函数：在页面的各个选项卡之间切换"""
    try:
        try:
            await _close_right_drawer(page)
        except Exception:
            pass

        clicked = await page.evaluate(f'''(tabName) => {{
            const els = Array.from(document.querySelectorAll('span, div, label, a'));
            for(let el of els) {{
                if(el.textContent && el.textContent.trim() === tabName) {{
                    const style = window.getComputedStyle(el);
                    if(style.cursor === 'pointer' || el.tagName === 'A' || el.parentElement?.tagName === 'A' || el.closest('.ant-tabs-tab')) {{
                        try {{ el.scrollIntoView({{ block: 'center', inline: 'center' }}); }} catch(e) {{}}
                        el.click();
                        return true;
                    }}
                }}
            }}
            return false;
        }}''', tab_name)
        if clicked:
            print(f"[OK] 已切换到【{tab_name}】标签页")
            await asyncio.sleep(1)
            return True
        else:
            loc = page.locator(f"text={tab_name}").first
            if await loc.count() > 0:
                try:
                    await loc.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                await loc.click(timeout=2000, force=True)
                print(f"[OK] 已切换到【{tab_name}】标签页 (Locator)")
                await asyncio.sleep(1)
                return True
    except Exception as e:
        print(f"[WARN] 切换到【{tab_name}】失败: {e}")
    return False

async def _handle_common_modals(page) -> bool:
    """处理并关闭常见的干扰弹窗（如智能裁剪提示）"""
    handled = False
    try:
        # 针对“智能裁剪”点击“取消”
        crop_modal = page.locator('div:has-text("智能裁剪"), div:has-text("裁剪")').filter(has_text="取消").last
        if await crop_modal.count() > 0:
            btn = crop_modal.locator('button:has-text("取消"), span:has-text("取消")').first
            if await btn.count() > 0:
                await btn.click(timeout=2000, force=True)
                print("[OK] 已取消智能裁剪提示")
                await asyncio.sleep(0.5)
                handled = True
        
        # 针对其他“知道了”或“确定”类通知
        notif = page.locator('button:has-text("知道了"), button:has-text("确定"), button:has-text("确认")').first
        if await notif.count() > 0:
            # 只在它是 modal 内部时点击，避免误触主流程按钮
            is_modal = await notif.evaluate('el => !!el.closest(".ant-modal, .ant-notification, [class*=\\"modal\\"]")')
            if is_modal:
                await notif.click(timeout=1000, force=True)
                print("[OK] 已关闭系统通知弹窗")
                await asyncio.sleep(0.3)
                handled = True
    except Exception:
        pass
    return handled

