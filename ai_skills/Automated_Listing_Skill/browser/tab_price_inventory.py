# -*- coding: utf-8 -*-
"""
tab_price_inventory.py
【价格库存】Tab 相关操作：
  - 发货时间选择（48小时）
  - 商品规格填写与规格图上传
  - 价格与库存表格填写
"""

import asyncio
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR
from .tab_navigation import _switch_to_tab
from .excel_reader import (
    _read_sku_image_names_from_sheet1,
    _read_sheet2_value,
    _read_sku_to_merchant_code_mapping,
    _find_sku_image,
)
from .tab_basic_info import _wait_upload_done

async def _fill_price_and_inventory(page, working_dir: str):
    print(f"\n[PAGE] 准备填写价格库存 -> 现货发货时间、商品规格")
    
    
    # 点击“价格库存” tab
    try:
        switched = await _switch_to_tab(page, "价格库存")
        if not switched:
            print("[WARN] 未能切换到【价格库存】标签页")
            return
    except Exception as e:
        print(f"[WARN] 切换到【价格库存】失败: {e}")
        return

    # 选择“48小时”发货
    try:
        hours_clicked = await page.evaluate('''() => {
            const els = Array.from(document.querySelectorAll('span, label'));
            for(let el of els) {
                if(el.textContent && el.textContent.trim() === '48小时') {
                    const style = window.getComputedStyle(el);
                    if(style.display !== 'none' && style.visibility !== 'hidden') {
                        el.click();
                        return true;
                    }
                }
            }
            return false;
        }''')
        if hours_clicked:
            print("[OK] 已选择现货发货时间：48小时")
        else:
            print("[WARN] 未能找到并选择【48小时】选项")
    except Exception as e:
        print(f"[WARN] 选择发货时间失败: {e}")

    await asyncio.sleep(1)
    
    bundle_names = _read_sku_image_names_from_sheet1(working_dir)
    if not bundle_names:
        model_val = _read_sheet2_value(working_dir, "型号")
        if model_val:
            bundle_names = [model_val]
    if not bundle_names:
        print("[WARN] 未读取到可填写的规格值（sku图片名/型号），跳过规格填写")
        return
    bundle_names = [" ".join(str(v).split()) for v in bundle_names if str(v).strip()]
    bundle_names = list(dict.fromkeys(bundle_names))

    # 打开“添加规格图”开关
    try:
        switch_clicked = await page.evaluate('''() => {
            const els = Array.from(document.querySelectorAll('span, div, label'));
            for(let el of els) {
                if(el.textContent && el.textContent.trim().includes('添加规格图')) {
                    // Try to find the switch button nearby
                    const container = el.parentElement || el.closest('div');
                    if (container) {
                        const switchBtn = container.querySelector('button[role="switch"], .ant-switch');
                        if (switchBtn) {
                            if (switchBtn.getAttribute('aria-checked') === 'false' || !switchBtn.classList.contains('ant-switch-checked')) {
                                switchBtn.click();
                                return true;
                            }
                            return true; // Already checked
                        }
                    }
                    // Fallback to click the label itself
                    el.click();
                    return true;
                }
            }
            return false;
        }''')
        if switch_clicked:
            print("[OK] 尝试打开【添加规格图】开关")
            await asyncio.sleep(1)
        else:
            print("[INFO] 【添加规格图】开关未找到")
    except Exception as e:
        print(f"[WARN] 尝试打开【添加规格图】开关失败: {e}")

    try:
        model_inputs = page.locator('input[placeholder*="请输入型号"]')
        model_inputs_count = await model_inputs.count()
        
        # --- 如果没有型号输入框，先尝试添加规格类型 ---
        if model_inputs_count == 0 or not await model_inputs.first.is_visible():
            print("[INFO] 当前页面未发现现成的规格值输入框，准备尝试新建【规格类型】...")
            await _create_new_spec_type(page)
            # 等待新建完成，重新获取 locator
            await asyncio.sleep(2)
            model_inputs = page.locator('input[placeholder*="请输入型号"]')
            model_inputs_count = await model_inputs.count()

        if model_inputs_count > 0 and await model_inputs.first.is_visible():
            expected_values = bundle_names
            def _canon(s: str) -> str:
                s = (s or "").replace(" ", "")
                s = s.replace("（", "(").replace("）", ")")
                s = s.replace("－", "-").replace("—", "-").replace("–", "-")
                return s

            expected_norm = [_canon(v) for v in expected_values if v and str(v).strip()]
            expected_norm = list(dict.fromkeys(expected_norm))
            norm_to_value = {_canon(v): v for v in expected_values if v and str(v).strip()}

            async def _read_current_norms():
                try:
                    data = await page.evaluate(
                        """() => {
                            const norm = (s) => (s || '').toString().replace(/\\s+/g, '').replace(/（/g,'(').replace(/）/g,')').replace(/[－—–]/g,'-');
                            const inputs = Array.from(document.querySelectorAll('input[placeholder*="请输入型号"]'));
                            const vals = [];
                            let emptyCount = 0;
                            for (const input of inputs) {
                                const v = (input.value || '').toString();
                                const nv = norm(v);
                                if (!nv) emptyCount += 1;
                                else vals.push(nv);
                            }
                            return { values: Array.from(new Set(vals)), total: inputs.length, empty: emptyCount };
                        }""",
                    )
                    values = set([str(x) for x in (data.get("values") or []) if isinstance(x, str) and x.strip()])
                    total = int(data.get("total") or 0)
                    empty = int(data.get("empty") or 0)
                    return values, total, empty
                except Exception:
                    return set(), 0, 0

            async def _get_last_empty_input():
                inputs = page.locator('input[placeholder*="请输入型号"]')
                count = await inputs.count()
                for i in range(count - 1, -1, -1):
                    inp = inputs.nth(i)
                    try:
                        v = (await inp.input_value()).strip()
                        if not v:
                            return inp
                    except Exception:
                        continue
                return inputs.nth(count - 1) if count > 0 else None

            initial_present, _, _ = await _read_current_norms()

            max_rounds = 10
            for _ in range(max_rounds):
                present, _total, _empty = await _read_current_norms()
                missing = [v for v in expected_norm if v not in present]
                if not missing:
                    break

                progress = 0
                for v_norm in missing:
                    val = norm_to_value.get(v_norm, v_norm)
                    target = await _get_last_empty_input()
                    if target is None:
                        break
                    try:
                        await target.click(timeout=5000)
                        await target.fill("")
                        try:
                            await target.type(val, delay=25)
                        except Exception:
                            await target.fill(val)
                        await asyncio.sleep(0.2)
                        try:
                            await target.press("Enter")
                        except Exception:
                            await page.keyboard.press("Enter")

                        ok = False
                        for _w in range(12):
                            await asyncio.sleep(0.25)
                            present_now, _t2, _e2 = await _read_current_norms()
                            if v_norm in present_now:
                                ok = True
                                break
                        if ok:
                            progress += 1
                        else:
                            print(f"[WARN] 规格值写入失败: {val}")
                            try:
                                await page.keyboard.press("Escape")
                            except Exception:
                                pass
                            await asyncio.sleep(0.4)
                    except Exception:
                        continue

                if progress <= 0:
                    break

            final_present, _, _ = await _read_current_norms()
            final_missing = [v for v in expected_norm if v not in final_present]
            if final_missing:
                miss_show = [norm_to_value.get(v, v) for v in final_missing[:10]]
                print(f"[WARN] 仍有未填入规格值数量: {len(final_missing)}; 示例: {miss_show}")
            total_added = len(final_present - initial_present)

            print(f"[OK] 已填写规格值数量: {total_added}")

            # 依次为填写的规格值上传对应的图片
            print("\n[PAGE] 准备上传规格图...")
            for v_norm in expected_norm:
                if v_norm not in final_present:
                    continue
                val = norm_to_value.get(v_norm, v_norm)
                img_path = _find_sku_image(working_dir, val)
                if not img_path:
                    print(f"[WARN] 未找到规格值 '{val}' 对应的图片，跳过上传")
                    continue
                
                try:
                    ok = await page.evaluate('''((val) => {
                        const inputs = Array.from(document.querySelectorAll('input'));
                        let targetInput = null;
                        for (const inp of inputs) {
                            if (inp.value && inp.value.trim() === val) {
                                targetInput = inp;
                                break;
                            }
                        }
                        if (!targetInput) return false;
                        
                        let container = targetInput.parentElement;
                        let uploadBtn = null;
                        for (let i = 0; i < 5; i++) {
                            if (!container) break;
                            uploadBtn = container.querySelector('.ant-upload, [class*="upload"], input[type="file"]');
                            if (uploadBtn) {
                                const style = window.getComputedStyle(uploadBtn);
                                if (style.display !== 'none' || uploadBtn.tagName === 'INPUT') {
                                    break;
                                }
                            }
                            container = container.parentElement;
                        }
                        
                        if (uploadBtn) {
                            if (uploadBtn.tagName !== 'INPUT') {
                                const innerInput = uploadBtn.querySelector('input[type="file"]');
                                if (innerInput) uploadBtn = innerInput;
                            }
                            uploadBtn.setAttribute('data-als-upload-target', 'true');
                            return true;
                        }
                        return false;
                    })''', val)
                    
                    if not ok:
                        print(f"[WARN] 未找到 '{val}' 对应的上传入口")
                        continue

                    target_loc = page.locator('[data-als-upload-target="true"]').first
                    tag_name = await target_loc.evaluate("el => el.tagName")
                    if tag_name == "INPUT":
                        await target_loc.set_input_files(img_path)
                    else:
                        file_input = target_loc.locator('input[type="file"]')
                        if await file_input.count() > 0:
                            await file_input.first.set_input_files(img_path)
                        else:
                            async with page.expect_file_chooser(timeout=3000) as fc_info:
                                await target_loc.click(force=True)
                            fc = await fc_info.value
                            await fc.set_files(img_path)

                    await page.evaluate('''() => {
                        const el = document.querySelector('[data-als-upload-target="true"]');
                        if (el) el.removeAttribute('data-als-upload-target');
                    }''')

                    await asyncio.sleep(1)
                    await _wait_upload_done(page)
                    print(f"[OK] 规格图上传成功: {val} -> {os.path.basename(img_path)}")
                except Exception as e:
                    print(f"[WARN] 规格图上传异常 '{val}': {e}")
                    try:
                        await page.evaluate('''() => {
                            const el = document.querySelector('[data-als-upload-target="true"]');
                            if (el) el.removeAttribute('data-als-upload-target');
                        }''')
                    except Exception:
                        pass

            print("\n[PAGE] 准备填写价格与库存表格...")
            def _norm_text(s: str) -> str:
                if s is None:
                    return ""
                s = str(s)
                s = "".join(s.split())
                s = s.replace("（", "(").replace("）", ")")
                s = s.replace("－", "-").replace("—", "-").replace("–", "-")
                return s

            merchant_code_mapping_raw = _read_sku_to_merchant_code_mapping(working_dir)
            merchant_code_mapping = {_norm_text(k): str(v).strip() for k, v in (merchant_code_mapping_raw or {}).items() if str(k).strip() and str(v).strip()}
            try:
                await page.evaluate('''() => {
                    const el = document.querySelector('.ant-table-body');
                    if (el) el.scrollLeft = 100000;
                }''')
            except Exception:
                pass

            async def _fill_input(inp, text: str) -> bool:
                try:
                    await inp.scroll_into_view_if_needed()
                    await inp.click(timeout=2000)
                    try:
                        await inp.press("Control+A")
                    except Exception:
                        pass
                    await inp.type(str(text), delay=30)
                    try:
                        await inp.press("Enter")
                    except Exception:
                        pass
                    try:
                        await inp.press("Tab")
                    except Exception:
                        pass
                    return True
                except Exception:
                    return False

            for v_norm in expected_norm:
                if v_norm not in final_present:
                    continue
                val = norm_to_value.get(v_norm, v_norm)
                merchant_code = merchant_code_mapping.get(_norm_text(val), "")
                marked = False
                for _try in range(3):
                    try:
                        res = await page.evaluate('''({val}) => {
                            const norm = (s) => (s || '').toString().replace(/\\s+/g,'').replace(/（/g,'(').replace(/）/g,')').replace(/[－—–]/g,'-');
                            const isVisible = (el) => {
                                if (!el) return false;
                                const style = window.getComputedStyle(el);
                                if (!style) return false;
                                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                                const r = el.getBoundingClientRect();
                                return r.width > 0 && r.height > 0;
                            };
                            document.querySelectorAll('[data-als-target]').forEach(el => el.removeAttribute('data-als-target'));

                            const target = norm(val);
                            const rows = Array.from(document.querySelectorAll('tr'));
                            let targetRow = null;
                            for (const row of rows) {
                                const tds = Array.from(row.querySelectorAll('td'));
                                if (tds.length < 3) continue;
                                const modelText = (tds[0].innerText || tds[0].textContent || '').trim();
                                if (!modelText) continue;
                                const a = norm(modelText);
                                if (!a) continue;
                                if (a === target || a.includes(target) || target.includes(a)) {
                                    const inputs = Array.from(row.querySelectorAll('input')).filter(isVisible);
                                    if (inputs.length > 0) {
                                        targetRow = row;
                                        break;
                                    }
                                }
                            }
                            if (!targetRow) return { ok: false, reason: 'row_not_found' };

                            const tds = Array.from(targetRow.querySelectorAll('td'));
                            const cellInputs = tds.map(td => Array.from(td.querySelectorAll('input')).filter(isVisible));
                            let priceInp = (cellInputs[1] && cellInputs[1][0]) ? cellInputs[1][0] : null;
                            let invInp = (cellInputs[2] && cellInputs[2][0]) ? cellInputs[2][0] : null;
                            let codeInp = (cellInputs[4] && cellInputs[4][0]) ? cellInputs[4][0] : null;

                            const inputs = Array.from(targetRow.querySelectorAll('input')).filter(isVisible);
                            if (!codeInp) {
                                codeInp = inputs.find(inp => {
                                    const ph = (inp.getAttribute('placeholder') || inp.placeholder || '').toLowerCase();
                                    return ph.includes('erp') || ph.includes('编码');
                                }) || null;
                            }
                            if (!priceInp) priceInp = inputs[0] || null;
                            if (!invInp) invInp = inputs[1] || null;

                            if (priceInp) priceInp.setAttribute('data-als-target', 'price');
                            if (invInp) invInp.setAttribute('data-als-target', 'inv');
                            if (codeInp) codeInp.setAttribute('data-als-target', 'code');

                            return { ok: true, hasPrice: !!priceInp, hasInv: !!invInp, hasCode: !!codeInp };
                        }''', {"val": val})
                        if isinstance(res, dict) and res.get("ok"):
                            marked = True
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)

                if not marked:
                    print(f"[WARN] 未在价格库存表格中找到型号行: {val}")
                    continue

                price_inp = page.locator('input[data-als-target="price"]').first
                inv_inp = page.locator('input[data-als-target="inv"]').first
                code_inp = page.locator('input[data-als-target="code"]').first

                ok_price = await _fill_input(price_inp, "999")
                ok_inv = await _fill_input(inv_inp, "999")
                ok_code = True
                if merchant_code:
                    if await code_inp.count() > 0:
                        ok_code = await _fill_input(code_inp, merchant_code)
                    else:
                        ok_code = False

                try:
                    await page.evaluate('''() => {
                        document.querySelectorAll('[data-als-target]').forEach(el => el.removeAttribute('data-als-target'));
                    }''')
                except Exception:
                    pass

                if not merchant_code:
                    print(f"[WARN] 已填写表格行 {val}: 价格=999, 库存=999, 但未找到对应的修改后商家编码")
                else:
                    if ok_price and ok_inv and ok_code:
                        print(f"[OK] 已填写表格行 {val}: 价格=999, 库存=999, 商家编码={merchant_code}")
                    else:
                        print(f"[WARN] 表格填写可能未生效: {val} price={ok_price} inv={ok_inv} code={ok_code}")

                try:
                    await asyncio.sleep(0.3)
                except Exception:
                    pass

            print("\n[PAGE] 读取并同步最新的商家编码到 Excel...")
            try:
                actual_codes = await page.evaluate('''() => {
                    const rows = Array.from(document.querySelectorAll('tr, .ant-table-row'));
                    const mapping = {};
                    for (const row of rows) {
                        const rowText = row.textContent || '';
                        const inputs = Array.from(row.querySelectorAll('input'));
                        let codeInp = null;
                        for (const inp of inputs) {
                            if (inp.placeholder && (inp.placeholder.includes('编码') || inp.placeholder.includes('erp'))) {
                                codeInp = inp;
                                break;
                            }
                        }
                        if (!codeInp && inputs.length >= 3) {
                            codeInp = inputs[2]; // fallback
                        }
                        
                        if (codeInp) {
                            const code = codeInp.value.trim();
                            if (code) {
                                mapping[rowText] = code;
                            }
                        }
                    }
                    return mapping;
                }''')
                
                sync_mapping = {}
                for v_norm in expected_norm:
                    val = norm_to_value.get(v_norm, v_norm)
                    for row_text, code in actual_codes.items():
                        if val in row_text:
                            sync_mapping[val] = code
                            break
                
                if sync_mapping:
                    _sync_merchant_code_to_excel(working_dir, sync_mapping)
            except Exception as e:
                print(f"[WARN] 读取并同步商家编码异常: {e}")

            try:
                shot_price = os.path.join(RESULT_DIR, "price_inventory_filled.png")
                await page.screenshot(path=shot_price, full_page=True, timeout=5000)
                print(f"[SHOT] 价格库存填写后截图已保存：{shot_price}")
            except Exception:
                pass
    except Exception as e:
        print(f"[WARN] 填写商品规格/价格表格流程发生异常: {e}")

    try:
        shot_price = os.path.join(RESULT_DIR, "price_inventory_filled.png")
        await page.screenshot(path=shot_price, full_page=True, timeout=5000)
        print(f"[SHOT] 价格库存填写后截图已保存：{shot_price}")
    except Exception:
        pass


async def _create_new_spec_type(page):
    """
    当页面没有任何规格输入框时，点击添加规格类型并输入"型号"
    """
    try:
        # 点击“+ 添加规格类型”
        add_type_clicked = await page.evaluate('''() => {
            const els = Array.from(document.querySelectorAll('span, div, button'));
            for(let el of els) {
                if(el.textContent && el.textContent.trim().includes('添加规格类型')) {
                    el.click();
                    return true;
                }
            }
            return false;
        }''')
        if add_type_clicked:
            print("[OK] 已点击【+ 添加规格类型】")
            await asyncio.sleep(1)
            
            # 点击“请选择规格类型”
            await page.evaluate('''() => {
                const els = Array.from(document.querySelectorAll('input'));
                for(let el of els) {
                    if(el.placeholder && el.placeholder.includes('请选择规格类型')) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }''')
            await asyncio.sleep(1)

            # 点击“创建类型”
            create_type_clicked = await page.evaluate('''() => {
                const els = Array.from(document.querySelectorAll('span, div, a, p, button, li, ul'));
                for(let el of els) {
                    if(el.textContent && el.textContent.includes('创建类型')) {
                        const style = window.getComputedStyle(el);
                        if(style.display !== 'none' && style.visibility !== 'hidden' && el.textContent.length < 20) {
                            el.click();
                            return true;
                        }
                    }
                }
                return false;
            }''')
            
            if not create_type_clicked:
                print("[WARN] 未找到【创建类型】按钮")
                return

            await asyncio.sleep(0.5)
            
            # 填写创建类型的输入框
            filled_type = await page.evaluate('''() => {
                const inputs = Array.from(document.querySelectorAll('input'));
                const visibleInputs = inputs.filter(el => {
                    const s = window.getComputedStyle(el);
                    return s.display !== 'none' && s.visibility !== 'hidden' && el.getBoundingClientRect().width > 0;
                });
                
                let targetInput = null;
                for (let i = visibleInputs.length - 1; i >= 0; i--) {
                    const el = visibleInputs[i];
                    if (el.placeholder === '请输入' && el.value === '') {
                        targetInput = el;
                        break;
                    }
                }
                
                if (targetInput) {
                    targetInput.focus();
                    targetInput.value = '型号';
                    targetInput.dispatchEvent(new Event('input', { bubbles: true }));
                    targetInput.dispatchEvent(new Event('change', { bubbles: true }));
                    targetInput.blur();
                    return true;
                }
                return false;
            }''')
            
            if filled_type:
                print("[OK] 规格类型已填写为：型号")
                await asyncio.sleep(1)
                
                # 回车确认创建类型
                await page.keyboard.press("Enter")
                await asyncio.sleep(1.5)
                
                # 在原来正确的逻辑中，创建完类型后，还需要自动填写第一个规格值，
                # 但在前面的某次重构中，不小心把 _create_new_spec_type 里的“填写第一条规格值”的代码丢掉了。
                # 由于这部分的职责主要是把 DOM 框建出来供主循环填写，
                # 所以我们让创建过程停在这里，把所有的规格值填充交给主函数 _fill_price_and_inventory 里的 model_inputs 去统一输入。
            else:
                print("[WARN] 规格类型输入框未找到，填写失败")
        else:
            print("[WARN] 未找到【+ 添加规格类型】按钮，可能已添加达上限")
    except Exception as e:
        print(f"[WARN] 添加规格类型流程异常: {e}")

