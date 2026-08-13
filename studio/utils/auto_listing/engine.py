# -*- coding: utf-8 -*-
"""抖店自动上架浏览器引擎（Playwright + 本地 Chrome CDP）。

设计参考 git 历史中的 ai_skills/Automated_Listing_Skill/browser/*：
- chrome_manager.py：调试 Chrome 启停与端口检测
- batch_publish.py：两阶段编排（主图/标题/类目 → 详情页 Tab 填写）
- tab_*.py：按「基础信息/图文信息/价格库存/服务与履约/其他信息」拆分

本模块使用同步 Playwright，便于在 QThread Worker 中直接执行。
"""
import os
import re
import time

from playwright.sync_api import sync_playwright

from .chrome_manager import ensure_debug_chrome
from .config import DOUYIN_STORES
from .validation import PackageInfo, ValidationError, prepare_package


class ListingError(RuntimeError):
    pass


def _norm(s: str) -> str:
    if s is None:
        return ""
    s = "".join(str(s).split())
    return (s.replace("（", "(").replace("）", ")")
             .replace("－", "-").replace("—", "-").replace("–", "-"))


def _find_sku_image(info: PackageInfo, name: str) -> str:
    target = _norm(name)
    for p in info.sku_images:
        base = _norm(os.path.splitext(os.path.basename(p))[0])
        if base == target or target in base or base in target:
            return p
    return info.sku_images[0] if info.sku_images else ""


class AutoListingEngine:
    def __init__(self, progress=None, should_stop=None):
        self.progress = progress or (lambda stage, msg: None)
        self.should_stop = should_stop or (lambda: False)

    def _emit(self, stage: str, message: str):
        if self.should_stop():
            raise ListingError("任务已停止")
        self.progress(stage, message)

    @staticmethod
    def _wait(ms: int):
        time.sleep(ms / 1000.0)

    @staticmethod
    def _body_text(page) -> str:
        try:
            return (page.locator("body").inner_text(timeout=5000) or "")
        except Exception:
            return ""

    @staticmethod
    def _is_visible_js():
        return """(el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }"""

    def run(self, input_path: str, shop_key: str, config: dict = None,
            publish_after_save: bool = False, prepared_info: PackageInfo = None) -> dict:
        config = config or {}
        if prepared_info is not None:
            info = prepared_info
        else:
            self._emit("校验", f"准备数据包：{input_path}")
            info = prepare_package(input_path, shop_key)
        self._emit("校验", f"校验通过：{info.title or '（未命名商品）'} / {len(info.skus)} 个SKU")

        port = int(config.get("debug_port") or 9222)
        user_data_dir = config.get("user_data_dir") or ""
        chrome_exe = config.get("chrome_exe") or ""
        result_dir = config.get("result_dir") or os.path.join(os.path.dirname(user_data_dir), "results")
        os.makedirs(result_dir, exist_ok=True)

        self._emit("浏览器", f"检查/启动 Chrome 调试端口 {port}")
        ensure_debug_chrome(chrome_exe, port, user_data_dir)

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()

            self._check_login(page)
            self._check_shop(page, info)
            self._open_create_page(page)
            self._stage1(page, info, result_dir)
            self._stage2(page, info, result_dir)

            self._emit("保存草稿", "点击保存草稿并校验页面状态")
            saved = self._save_draft(page)
            if publish_after_save and saved:
                self._emit("上架", "尝试直接上架")
                self._try_publish(page)

            shot = os.path.join(result_dir, "final.png")
            try:
                page.screenshot(path=shot, full_page=True)
            except Exception:
                pass
            return {
                "saved": bool(saved),
                "publish_attempted": bool(publish_after_save and saved),
                "working_dir": info.working_dir,
                "result_dir": result_dir,
                "sku_count": len(info.skus),
            }

    def _check_login(self, page):
        url = (page.url or "").lower()
        if "login" in url or "passport" in url:
            raise ListingError("检测到抖店登录页。请在打开的 Chrome 中扫码登录后重试。")
        text = self._body_text(page)
        if "扫码登录" in text and "商品" not in text:
            raise ListingError("检测到抖店登录页。请在打开的 Chrome 中扫码登录后重试。")

    def _check_shop(self, page, info: PackageInfo):
        text = self._body_text(page)
        target = [info.shop_name] + DOUYIN_STORES.get(info.shop_key, {}).get("aliases", [])
        for key, store in DOUYIN_STORES.items():
            if key == info.shop_key:
                continue
            other_name = store.get("name", "")
            if other_name and other_name in text and not any(a and a in text for a in target):
                raise ListingError(
                    f"当前页面疑似店铺「{store.get('name')}」，与目标店铺「{info.shop_name}」不一致。")

    def _open_create_page(self, page):
        if "create" in page.url and "login" not in page.url.lower():
            return
        urls = [
            "https://fxg.jinritemai.com/ffa/g/create",
            "https://fxg.jinritemai.com/ffa/mshop/homepage/index#/home/product/create",
        ]
        for url in urls:
            try:
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                self._wait(2000)
                if "login" in (page.url or "").lower() or "passport" in (page.url or "").lower():
                    continue
                text = self._body_text(page)
                if any(k in text for k in ("创建商品", "商品创建", "主图上传")):
                    return
            except Exception:
                continue
        raise ListingError("未能打开抖店商品创建页，请确认已登录且有商品创建权限。")

    def _stage1(self, page, info: PackageInfo, result_dir: str):
        self._emit("阶段1", "上传主图 / 填写标题 / 等待类目")
        self._upload_main_images(page, info.main_images)
        self._fill_title(page, info.title)
        self._wait(5000)
        if not self._click_text(page, "下一步"):
            self._emit("阶段1", "未找到「下一步」按钮，继续尝试详情页")
        self._wait(1500)
        self._shot(page, result_dir, "stage1")

    def _stage2(self, page, info: PackageInfo, result_dir: str):
        self._emit("阶段2", "填写基础信息 / 图文信息 / 价格库存 / 服务与履约 / 其他信息")
        self._switch_tab(page, "基础信息")
        self._fill_brand(page, info)
        self._fill_model_and_manufacturer(page, info)
        self._shot(page, result_dir, "basic_info")

        self._switch_tab(page, "图文信息")
        self._upload_detail_images(page, info.detail_images)
        self._shot(page, result_dir, "image_text")

        self._switch_tab(page, "价格库存")
        self._fill_price_inventory(page, info)
        self._shot(page, result_dir, "price_inventory")

        self._switch_tab(page, "服务与履约")
        self._click_text(page, "下架")
        self._shot(page, result_dir, "service")

        self._switch_tab(page, "其他信息")
        self._shot(page, result_dir, "other_info")

    def _shot(self, page, result_dir: str, name: str):
        try:
            page.screenshot(path=os.path.join(result_dir, f"{name}.png"), full_page=True)
        except Exception:
            pass

    def _click_text(self, page, text: str, exact: bool = False, timeout: int = 5000) -> bool:
        try:
            clicked = page.evaluate(
                """({text, exact}) => {
                    const isVisible = (el) => {
                        const style = window.getComputedStyle(el);
                        if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };
                    const els = Array.from(document.querySelectorAll('span,div,label,a,button,[role="button"]'));
                    for (const el of els) {
                        if (!isVisible(el)) continue;
                        const t = (el.textContent || '').trim();
                        const hit = exact ? t === text : t.includes(text);
                        if (!hit || !t) continue;
                        if (t.length > 60) continue;
                        try { el.scrollIntoView({block: 'center'}); } catch (e) {}
                        el.click();
                        return true;
                    }
                    return false;
                }""",
                {"text": text, "exact": exact},
            )
            if clicked:
                return True
            loc = page.get_by_text(text, exact=exact).first
            loc.click(timeout=timeout, force=True)
            return True
        except Exception:
            return False

    def _switch_tab(self, page, tab_name: str) -> bool:
        if self._click_text(page, tab_name, exact=True):
            self._wait(800)
            return True
        try:
            tab = page.locator(f".ant-tabs-tab:has-text('{tab_name}')").first
            tab.click(timeout=3000, force=True)
            self._wait(800)
            return True
        except Exception:
            return False

    def _upload_main_images(self, page, images: list):
        if not images:
            raise ListingError("数据包没有主图")
        try:
            page.wait_for_selector('input[type="file"]', timeout=15000)
        except Exception:
            pass
        marked = page.evaluate(
            """() => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const inputs = Array.from(document.querySelectorAll('input[type="file"]')).filter(isVisible);
                const main = inputs.find(inp => {
                    let node = inp;
                    for (let i = 0; i < 8; i++) {
                        node = node.parentElement;
                        if (!node) break;
                        const t = (node.textContent || '').trim();
                        if (t.includes('主图上传') || t.includes('上传主图')) return true;
                        if (t.includes('商品详情') || t.includes('详情图')) return false;
                    }
                    return false;
                }) || inputs[0];
                if (main) { main.setAttribute('data-als-main', '1'); return true; }
                return false;
            }""",
        )
        if marked:
            target = page.locator('input[data-als-main="1"]').first
            try:
                target.set_input_files(images)
            except Exception:
                target.set_input_files(images[0])
            page.evaluate("""() => {
                const el = document.querySelector('[data-als-main="1"]');
                if (el) el.removeAttribute('data-als-main');
            }""")
        else:
            target = page.locator('input[type="file"]').first
            try:
                target.set_input_files(images)
            except Exception:
                target.set_input_files(images[0])
        self._wait_upload_done(page)

    def _fill_title(self, page, title: str):
        if not title:
            return
        marked = page.evaluate(
            """({title}) => {
                const selectors = [
                    'input[placeholder*="请输入2-60"]',
                    'input[placeholder*="商品标题"]',
                    'input[placeholder*="标题"]',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.offsetWidth > 0) {
                        el.setAttribute('data-als-title', '1');
                        return true;
                    }
                }
                const labels = Array.from(document.querySelectorAll('label,span,div')).filter(el => {
                    return (el.textContent || '').trim() === '商品标题' && el.getBoundingClientRect().width > 0;
                });
                for (const label of labels) {
                    let node = label;
                    for (let i = 0; i < 6; i++) {
                        node = node.parentElement;
                        if (!node) break;
                        const input = node.querySelector('input:not([disabled])');
                        if (input) { input.setAttribute('data-als-title', '1'); return true; }
                    }
                }
                return false;
            }""",
            {"title": title},
        )
        if marked:
            inp = page.locator('input[data-als-title="1"]').first
            inp.fill(title)
            inp.press("Tab")
            page.evaluate("""() => {
                const el = document.querySelector('[data-als-title="1"]');
                if (el) el.removeAttribute('data-als-title');
            }""")
        else:
            try:
                page.locator('input[placeholder*="请输入2-60"]').first.fill(title)
            except Exception:
                pass

    def _fill_text_by_label(self, page, label: str, value: str) -> bool:
        if not label or not value:
            return False
        marker = f"als-{abs(hash((label, value, os.getpid())))}"
        marked = page.evaluate(
            """({label, marker}) => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const labels = Array.from(document.querySelectorAll('label,span,div')).filter(el => {
                    return isVisible(el) && (el.textContent || '').trim() === label;
                });
                const inputs = Array.from(document.querySelectorAll('input:not([disabled])')).filter(isVisible);
                let best = null;
                let bestScore = 10 ** 9;
                for (const lab of labels) {
                    const lr = lab.getBoundingClientRect();
                    for (const input of inputs) {
                        const ir = input.getBoundingClientRect();
                        const dy = ir.top - lr.bottom;
                        if (dy < -20 || dy > 280) continue;
                        const dx = Math.abs(ir.left - lr.left);
                        if (dx > 520) continue;
                        const score = dy * 10 + dx;
                        if (score < bestScore) { bestScore = score; best = input; }
                    }
                }
                if (best) { best.setAttribute('data-als-label-input', marker); return true; }
                return false;
            }""",
            {"label": label, "marker": marker},
        )
        if not marked:
            return False
        try:
            inp = page.locator(f'input[data-als-label-input="{marker}"]').first
            inp.fill(value)
            inp.press("Tab")
            return True
        except Exception:
            return False
        finally:
            try:
                page.evaluate("""(marker) => {
                    const el = document.querySelector(`input[data-als-label-input="${marker}"]`);
                    if (el) el.removeAttribute('data-als-label-input');
                }""", marker)
            except Exception:
                pass

    def _fill_brand(self, page, info: PackageInfo):
        brand = (info.brand or "无品牌").strip()
        if brand == "无品牌":
            self._click_text(page, "无品牌", exact=True)
            return
        if not self._fill_text_by_label(page, "品牌", brand):
            self._emit("基础信息", f"品牌字段填写未命中（目标：{brand}）")

    def _fill_model_and_manufacturer(self, page, info: PackageInfo):
        if info.model:
            self._fill_text_by_label(page, "型号", info.model)
        if info.manufacturer:
            self._fill_text_by_label(page, "生产厂家", info.manufacturer)

    def _upload_detail_images(self, page, images: list):
        if not images:
            return
        marked = page.evaluate(
            """() => {
                const labels = Array.from(document.querySelectorAll('div,span,label')).filter(el => {
                    const cls = (el.className && (el.className.baseVal !== undefined ? el.className.baseVal : el.className)) || '';
                    return String(cls).includes('decorateImgEditTitle') && !String(cls).includes('Wrapper');
                });
                for (const label of labels) {
                    let node = label;
                    for (let i = 0; i < 20; i++) {
                        node = node.parentElement;
                        if (!node) break;
                        const input = node.querySelector('input[type="file"]');
                        if (input) { input.setAttribute('data-als-detail', '1'); return true; }
                    }
                }
                const inputs = Array.from(document.querySelectorAll('input[type="file"]')).filter(el => {
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none' && el.getBoundingClientRect().width > 0;
                });
                for (const input of inputs) {
                    let node = input;
                    for (let i = 0; i < 8; i++) {
                        node = node.parentElement;
                        if (!node) break;
                        const t = (node.textContent || '').trim();
                        if (t.includes('商品详情') || t.includes('详情图')) {
                            input.setAttribute('data-als-detail', '1');
                            return true;
                        }
                        if (t.includes('主图')) break;
                    }
                }
                return false;
            }""",
        )
        if not marked:
            self._emit("图文信息", "未定位到详情图上传控件，跳过详情图上传")
            return
        loc = page.locator('input[data-als-detail="1"]').first
        try:
            multiple = loc.evaluate("el => !!el.multiple")
            if multiple:
                loc.set_input_files(images)
                self._wait_upload_done(page, 300000)
            else:
                for img in images:
                    loc.set_input_files(img)
                    self._wait_upload_done(page, 60000)
        except Exception as e:
            self._emit("图文信息", f"详情图上传异常：{e}")
        page.evaluate("""() => {
            const el = document.querySelector('[data-als-detail="1"]');
            if (el) el.removeAttribute('data-als-detail');
        }""")

    def _fill_price_inventory(self, page, info: PackageInfo):
        self._click_text(page, "48小时", exact=True)
        self._wait(500)
        names = [s.name for s in info.skus]
        if not names:
            return
        self._wait(500)
        inputs = page.locator('input[placeholder*="请输入型号"]')
        if inputs.count() == 0:
            self._create_new_spec_type(page)
            self._wait(1500)
            inputs = page.locator('input[placeholder*="请输入型号"]')
        count = inputs.count()
        for i, name in enumerate(names):
            if i >= count:
                self._click_text(page, "添加规格", exact=False)
                self._wait(400)
                inputs = page.locator('input[placeholder*="请输入型号"]')
                count = inputs.count()
                if i >= count:
                    break
            inp = inputs.nth(i)
            try:
                inp.fill(name)
                inp.press("Enter")
                self._wait(300)
            except Exception:
                pass

        for sku in info.skus:
            img = _find_sku_image(info, sku.name)
            if not img:
                continue
            marked = page.evaluate(
                """({val}) => {
                    const isVisible = (el) => {
                        const style = window.getComputedStyle(el);
                        return style.display !== 'none' && el.getBoundingClientRect().width > 0;
                    };
                    const input = Array.from(document.querySelectorAll('input')).find(el =>
                        isVisible(el) && (el.value || '').trim() === val);
                    if (!input) return false;
                    let node = input;
                    for (let i = 0; i < 8; i++) {
                        node = node.parentElement;
                        if (!node) break;
                        const upload = node.querySelector('input[type="file"], .ant-upload input[type="file"]');
                        if (upload) { upload.setAttribute('data-als-sku-upload', '1'); return true; }
                    }
                    return false;
                }""",
                {"val": sku.name},
            )
            if marked:
                try:
                    page.locator('input[data-als-sku-upload="1"]').first.set_input_files(img)
                    self._wait_upload_done(page, 60000)
                except Exception:
                    pass
                page.evaluate("""() => {
                    const el = document.querySelector('[data-als-sku-upload="1"]');
                    if (el) el.removeAttribute('data-als-sku-upload');
                }""")

        self._fill_price_table(page, info)

    def _fill_price_table(self, page, info: PackageInfo):
        for sku in info.skus:
            marked = page.evaluate(
                """({val}) => {
                    const norm = (s) => (s || '').toString().replace(/\\s+/g,'').replace(/（/g,'(').replace(/）/g,')').replace(/[－—–]/g,'-');
                    const target = norm(val);
                    const rows = Array.from(document.querySelectorAll('tr'));
                    for (const row of rows) {
                        const tds = Array.from(row.querySelectorAll('td'));
                        if (tds.length < 3) continue;
                        const first = norm(tds[0].textContent || '');
                        if (!first || !(first === target || first.includes(target) || target.includes(first))) continue;
                        const inputs = Array.from(row.querySelectorAll('input')).filter(el => {
                            const style = window.getComputedStyle(el);
                            return style.display !== 'none' && el.getBoundingClientRect().width > 0;
                        });
                        if (inputs[0]) inputs[0].setAttribute('data-als-price', '1');
                        if (inputs[1]) inputs[1].setAttribute('data-als-inv', '1');
                        const code = inputs.find(inp => (inp.placeholder || '').includes('编码') || (inp.placeholder || '').includes('erp'));
                        if (code) code.setAttribute('data-als-code', '1');
                        return inputs.length > 0;
                    }
                    return false;
                }""",
                {"val": sku.name},
            )
            if not marked:
                continue
            price = page.locator('input[data-als-price="1"]').first
            inv = page.locator('input[data-als-inv="1"]').first
            code = page.locator('input[data-als-code="1"]').first
            try:
                price.fill("999")
                inv.fill("999")
                if sku.merchant_code and code.count() > 0:
                    code.fill(sku.merchant_code)
            except Exception:
                pass
            page.evaluate("""() => {
                document.querySelectorAll('[data-als-price],[data-als-inv],[data-als-code]').forEach(el => {
                    el.removeAttribute('data-als-price');
                    el.removeAttribute('data-als-inv');
                    el.removeAttribute('data-als-code');
                });
            }""")

    def _create_new_spec_type(self, page):
        self._click_text(page, "添加规格类型")
        self._wait(800)
        page.evaluate("""() => {
            const el = Array.from(document.querySelectorAll('input')).find(inp =>
                (inp.placeholder || '').includes('请选择规格类型'));
            if (el) el.click();
        }""")
        self._wait(600)
        self._click_text(page, "创建类型")
        self._wait(600)
        page.evaluate("""() => {
            const inputs = Array.from(document.querySelectorAll('input')).filter(el => {
                const style = window.getComputedStyle(el);
                return style.display !== 'none' && el.getBoundingClientRect().width > 0;
            });
            const target = inputs[inputs.length - 1];
            if (target) {
                target.focus();
                target.value = '型号';
                target.dispatchEvent(new Event('input', {bubbles: true}));
                target.dispatchEvent(new Event('change', {bubbles: true}));
                target.blur();
            }
        }""")

    def _save_draft(self, page) -> bool:
        self._click_text(page, "保存草稿")
        self._wait(500)
        success = False
        error_msg = ""
        for _ in range(15):
            self._wait(200)
            try:
                state = page.evaluate("""() => {
                    const errorTexts = ['必填', '不能为空', '保存失败', '请输入', '请上传', '校验不通过'];
                    const messages = Array.from(document.querySelectorAll(
                        '.ant-message-notice, .arco-message, .arco-toast, .ant-notification-notice, .ant-form-item-explain-error'));
                    for (const m of messages) {
                        const t = (m.textContent || '').trim();
                        if (errorTexts.some(e => t.includes(e))) return {kind: 'error', text: t};
                    }
                    for (const m of messages) {
                        const t = (m.textContent || '').trim();
                        if (t.includes('保存成功') || t.includes('草稿保存成功')) return {kind: 'success'};
                    }
                    return null;
                }""")
                if state:
                    if state.get("kind") == "error":
                        error_msg = state.get("text", "")
                        break
                    success = True
                    break
                if "create" not in page.url:
                    success = True
                    break
            except Exception:
                pass
        if success:
            self._emit("保存草稿", "草稿保存成功")
        elif error_msg:
            self._emit("保存草稿", f"保存失败：{error_msg}")
        else:
            self._emit("保存草稿", "已点击保存草稿，但未检测到明确成功/失败提示")
        return success

    def _try_publish(self, page):
        self._click_text(page, "上架")
        self._wait(2000)
        self._emit("上架", "已点击上架，请到商品管理中确认最终状态")

    def _wait_upload_done(self, page, timeout_ms: int = 120000):
        try:
            page.locator("text=上传中").first.wait_for(state="detached", timeout=timeout_ms)
        except Exception:
            pass
