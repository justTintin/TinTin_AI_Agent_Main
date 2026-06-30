# -*- coding: utf-8 -*-
"""
tab_other_info.py
【其他信息】Tab 相关操作 + 保存草稿：
  - _fill_other_info(page)
  - _save_draft(page)
"""

import asyncio
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR
from .tab_navigation import _switch_to_tab

async def _fill_other_info(page) -> None:
    try:
        switched = await _switch_to_tab(page, "其他信息")
        if not switched:
            print("[WARN] 切换到【其他信息】失败")
            return
    except Exception as e:
        print(f"[WARN] 切换到【其他信息】失败: {e}")
        return

    try:
        shot = os.path.join(RESULT_DIR, "other_info.png")
        await page.screenshot(path=shot, full_page=True, timeout=5000)
        print(f"[SHOT] 其他信息截图已保存：{shot}")
    except Exception:
        pass


async def _save_draft(page) -> bool:
    try:
        # 点击保存草稿按钮
        saved_clicked = await page.evaluate('''() => {
            const norm = (s) => (s || '').toString().replace(/\\s+/g,'');
            const btns = Array.from(document.querySelectorAll('button, a, span, div'));
            for (const el of btns) {
                if (!el.textContent) continue;
                const t = norm(el.textContent);
                if (t.includes('保存草稿') || t.includes('保存为草稿')) {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    el.click();
                    return true;
                }
            }
            return false;
        }''')
        if not saved_clicked:
            loc = page.locator('button:has-text("保存草稿"), button:has-text("保存为草稿"), text=保存草稿, text=保存为草稿').first
            await loc.click(timeout=3000)
        
        print("[WAIT] 已点击保存草稿，等待页面响应...")
        
        # 强校验：轮询检测成功提示或错误提示
        # 抖店一般会在页面顶部或中心弹出 toast 提示（如 .ant-message-notice-content, .arco-toast, .arco-message）
        # 如果漏填，往往会提示“该项为必填”或者“保存失败”
        success = False
        error_msg = ""
        
        for _ in range(15): # 等待最多 3 秒
            await asyncio.sleep(0.2)
            
            # 1. 检查是否存在错误提示文本（页面上的红字或弹窗里的失败提示）
            has_error = await page.evaluate('''() => {
                const errorTexts = ['必填', '不能为空', '保存失败', '请输入', '请上传', '校验不通过', '错误'];
                // 检查 toast/message
                const messages = Array.from(document.querySelectorAll('.ant-message-notice, .arco-message, .arco-toast, .ant-notification-notice'));
                for (const m of messages) {
                    const text = (m.textContent || '').trim();
                    if (errorTexts.some(e => text.includes(e))) return text;
                }
                
                // 检查表单下的红字错误提示 (通常是 .ant-form-item-explain-error 或带有 error 类的红色文本)
                const formErrors = Array.from(document.querySelectorAll('.ant-form-item-explain-error, .arco-form-item-message-help-error, [style*="color: red"], [style*="color: rgb(255,"]'));
                for (const err of formErrors) {
                    const text = (err.textContent || '').trim();
                    if (text && errorTexts.some(e => text.includes(e))) return text;
                }
                
                return null;
            }''')
            
            if has_error:
                error_msg = has_error
                break
                
            # 2. 检查是否存在成功提示
            has_success = await page.evaluate('''() => {
                const successTexts = ['保存成功', '草稿保存成功'];
                const messages = Array.from(document.querySelectorAll('.ant-message-notice, .arco-message, .arco-toast, .ant-notification-notice'));
                for (const m of messages) {
                    const text = (m.textContent || '').trim();
                    if (successTexts.some(s => text.includes(s))) return true;
                }
                return false;
            }''')
            
            if has_success:
                success = True
                break
                
            # 3. 检查页面 URL 是否发生了跳转（有时候保存成功会跳回列表页）
            if "create" not in page.url:
                success = True
                break
        
        if success:
            print("[OK] 草稿保存成功！")
        elif error_msg:
            print(f"[ERROR] 保存失败，检测到页面提示: {error_msg}")
        else:
            print("[WARN] 点击了保存草稿，但未检测到明确的成功或失败提示（可能网络延迟）。")
            
    except Exception as e:
        print(f"[ERROR] 点击保存草稿发生异常: {e}")
        success = False

    try:
        shot = os.path.join(RESULT_DIR, "saved_draft.png")
        await page.screenshot(path=shot, full_page=True, timeout=5000)
        if not success:
            print(f"[SHOT] 保存失败时的现场截图已保存：{shot}")
        else:
            print(f"[SHOT] 保存草稿后截图已保存：{shot}")
    except Exception:
        pass
        
    return success


