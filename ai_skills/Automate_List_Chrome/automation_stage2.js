async function runStage2({ client, bundle, taskData, sendStatus, checkStop, sleep, findSkuImage }) {
  sendStatus('running', '阶段2: 基础信息/图文信息/价格库存/服务与履约/其他信息/保存草稿');

  const switchToTab = async (tabName) => {
    const ok = await client.evalInPage(`((tabName) => {
      const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };
      const els = Array.from(document.querySelectorAll('span, div, label, a')).filter(isVisible);
      for (const el of els) {
        const t = (el.textContent || '').trim();
        if (t === tabName) {
          const clickable = (style) => style.cursor === 'pointer';
          const style = window.getComputedStyle(el);
          if (clickable(style) || el.tagName === 'A' || (el.parentElement && el.parentElement.tagName === 'A') || el.closest('.ant-tabs-tab')) {
            try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch(e) {}
            el.click();
            return true;
          }
        }
      }
      return false;
    })(${JSON.stringify(tabName)})`).catch(() => false);
    await sleep(ok ? 900 : 300);
    return ok;
  };

  const fillByLabel = async (label, value) => {
    if (!label || !value) return false;
    return await client.evalInPage(`((label, value) => {
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
          }
        }
      }
      if (!bestInput) return false;
      bestInput.focus();
      bestInput.value = '';
      bestInput.dispatchEvent(new Event('input', { bubbles: true }));
      bestInput.value = value;
      bestInput.dispatchEvent(new Event('input', { bubbles: true }));
      bestInput.dispatchEvent(new Event('change', { bubbles: true }));
      bestInput.blur();
      return true;
    })(${JSON.stringify(label)}, ${JSON.stringify(value)})`).catch(() => false);
  };

  if (bundle.brand || bundle.model || bundle.manufacturer) {
    await switchToTab('基础信息');
    await sleep(600);
    if (bundle.brand) {
      await client.evalInPage(`(() => {
        const v = ${JSON.stringify(bundle.brand)};
        if (v === '无品牌') {
          const els = Array.from(document.querySelectorAll('a, span, div'));
          for (const el of els) {
            if ((el.textContent || '').trim() === '无品牌') {
              const style = window.getComputedStyle(el);
              if (style.cursor === 'pointer' || el.tagName === 'A') {
                el.click();
                return true;
              }
            }
          }
        }
        return false;
      })()`).catch(() => false);
    }
    if (bundle.model) await fillByLabel('型号', bundle.model);
    if (bundle.manufacturer) await fillByLabel('生产厂家', bundle.manufacturer);
  }

  await switchToTab('图文信息');
  await sleep(800);
  sendStatus('running', `图文信息: 清理并上传详情图 ${bundle.detailImages.length} 张`);
  await client.evalInPage(`(() => {
    const isVisible = (el) => {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    const deletes = Array.from(document.querySelectorAll('[class*=\"iconDelete\"]')).filter(isVisible);
    for (const d of deletes) {
      try { d.scrollIntoView({ block: 'center' }); } catch(e) {}
      d.click();
    }
    const confirms = Array.from(document.querySelectorAll('button')).filter(isVisible).filter(b => {
      const t = (b.textContent || '').trim();
      return t === '确定' || t === '删除';
    });
    for (const c of confirms) {
      try { c.click(); } catch(e) {}
    }
    return deletes.length;
  })()`).catch(() => 0);
  await sleep(800);

  if (bundle.detailImages.length > 0) {
    await client.evalInPage(`(() => {
      const label = Array.from(document.querySelectorAll('div, span, label')).find(el => {
        const cls = (el.className && el.className.baseVal) ? el.className.baseVal : (el.className || '');
        const c = String(cls);
        return c.includes('decorateImgEditTitle') && !c.includes('Wrapper');
      });
      let node = label;
      for (let i = 0; i < 20; i++) {
        if (!node) break;
        const inp = node.querySelector('input[type=\"file\"]');
        if (inp) {
          inp.setAttribute('data-als-detail', '1');
          return true;
        }
        node = node.parentElement;
      }
      const any = document.querySelector('input[type=\"file\"]');
      if (any) {
        any.setAttribute('data-als-detail', '1');
        return true;
      }
      return false;
    })()`).catch(() => false);

    const { root: root2 } = await client.send('DOM.getDocument', { depth: 0, pierce: true });
    const { nodeId: detailInpNodeId } = await client.send('DOM.querySelector', {
      nodeId: root2.nodeId,
      selector: 'input[data-als-detail=\"1\"]',
    });
    if (detailInpNodeId) {
      await client.send('DOM.setFileInputFiles', { nodeId: detailInpNodeId, files: bundle.detailImages.slice(0, 20) });
      await sleep(2000);
    }
  }

  await switchToTab('价格库存');
  await sleep(800);
  await client.evalInPage(`(() => {
    const els = Array.from(document.querySelectorAll('span, label'));
    for (const el of els) {
      if ((el.textContent || '').trim() === '48小时') {
        el.click();
        return true;
      }
    }
    return false;
  })()`).catch(() => false);
  await sleep(800);

  const skuValues = bundle.skuNames.length ? bundle.skuNames : (bundle.model ? [bundle.model] : []);
  if (skuValues.length > 0) {
    const created = await client.evalInPage(`(() => {
      const inputs = Array.from(document.querySelectorAll('input[placeholder*=\"请输入型号\"]'));
      if (inputs.length > 0) return true;
      const els = Array.from(document.querySelectorAll('span, div, button'));
      const addBtn = els.find(el => (el.textContent || '').trim().includes('添加规格类型'));
      if (!addBtn) return false;
      addBtn.click();
      return true;
    })()`).catch(() => false);
    if (created) {
      await sleep(1200);
      await client.evalInPage(`(() => {
        const inputs = Array.from(document.querySelectorAll('input'));
        const pick = inputs.find(el => (el.placeholder || '').includes('请选择规格类型'));
        if (pick) pick.click();
        return true;
      })()`).catch(() => false);
      await sleep(800);
      await client.evalInPage(`(() => {
        const nodes = Array.from(document.querySelectorAll('span, div, a, p, button, li'));
        const btn = nodes.find(el => (el.textContent || '').includes('创建类型') && (el.textContent || '').trim().length < 20);
        if (!btn) return false;
        btn.click();
        return true;
      })()`).catch(() => false);
      await sleep(600);
      await client.evalInPage(`(() => {
        const inputs = Array.from(document.querySelectorAll('input'));
        const visibles = inputs.filter(el => {
          const s = window.getComputedStyle(el);
          return s.display !== 'none' && s.visibility !== 'hidden' && el.getBoundingClientRect().width > 0;
        });
        for (let i = visibles.length - 1; i >= 0; i--) {
          const el = visibles[i];
          if ((el.placeholder || '') === '请输入' && !el.value) {
            el.focus();
            el.value = '型号';
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.blur();
            return true;
          }
        }
        return false;
      })()`).catch(() => false);
      await sleep(800);
      await client.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
      await client.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
      await sleep(1500);
    }

    for (const val of skuValues) {
      await client.evalInPage(`((val) => {
        const inputs = Array.from(document.querySelectorAll('input[placeholder*=\"请输入型号\"]'));
        let lastEmpty = null;
        for (let i = inputs.length - 1; i >= 0; i--) {
          if (!inputs[i].value) { lastEmpty = inputs[i]; break; }
        }
        if (!lastEmpty && inputs.length) lastEmpty = inputs[inputs.length - 1];
        if (!lastEmpty) return false;
        lastEmpty.focus();
        lastEmpty.value = '';
        lastEmpty.dispatchEvent(new Event('input', { bubbles: true }));
        lastEmpty.value = val;
        lastEmpty.dispatchEvent(new Event('input', { bubbles: true }));
        lastEmpty.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      })(${JSON.stringify(val)})`).catch(() => false);
      await sleep(250);
      await client.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
      await client.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
      await sleep(450);

      const imgPath = findSkuImage(bundle.dataDir, val);
      if (imgPath) {
        await client.evalInPage(`((val) => {
          const inputs = Array.from(document.querySelectorAll('input'));
          const targetInput = inputs.find(inp => (inp.value || '').trim() === val);
          if (!targetInput) return false;
          let container = targetInput.parentElement;
          for (let i = 0; i < 6; i++) {
            if (!container) break;
            const inp = container.querySelector('input[type=\"file\"]');
            if (inp) {
              inp.setAttribute('data-als-skuimg', '1');
              return true;
            }
            container = container.parentElement;
          }
          return false;
        })(${JSON.stringify(val)})`).catch(() => false);
        const { root: root3 } = await client.send('DOM.getDocument', { depth: 0, pierce: true });
        const { nodeId: skuImgNodeId } = await client.send('DOM.querySelector', {
          nodeId: root3.nodeId,
          selector: 'input[data-als-skuimg=\"1\"]',
        });
        if (skuImgNodeId) {
          await client.send('DOM.setFileInputFiles', { nodeId: skuImgNodeId, files: [imgPath] });
          await sleep(1200);
          await client.evalInPage(`(() => {
            const el = document.querySelector('input[data-als-skuimg=\"1\"]');
            if (el) el.removeAttribute('data-als-skuimg');
            return true;
          })()`).catch(() => false);
        }
      }
    }

    await client.evalInPage(`(() => {
      const body = document.querySelector('.ant-table-body');
      if (body) body.scrollLeft = 100000;
      return true;
    })()`).catch(() => false);
    await sleep(400);

    const norm = (s) => String(s || '').replace(/\\s+/g, '').replace(/（/g, '(').replace(/）/g, ')').replace(/[－—–]/g, '-');
    const codeMap = {};
    for (const [k, v] of Object.entries(bundle.skuToMerchantCode || {})) codeMap[norm(k)] = String(v || '').trim();

    for (const val of skuValues) {
      const key = norm(val);
      const merchantCode = codeMap[key] || '';

      const okMarked = await client.evalInPage(`((val) => {
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
        const rows = Array.from(document.querySelectorAll('tr, .ant-table-row'));
        let targetRow = null;
        for (const row of rows) {
          const tds = Array.from(row.querySelectorAll('td'));
          if (tds.length < 3) continue;
          const modelText = (tds[0].innerText || tds[0].textContent || '').trim();
          if (!modelText) continue;
          const a = norm(modelText);
          if (a === target || a.includes(target) || target.includes(a)) {
            const inputs = Array.from(row.querySelectorAll('input')).filter(isVisible);
            if (inputs.length > 0) { targetRow = row; break; }
          }
        }
        if (!targetRow) return false;
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
        return true;
      })(${JSON.stringify(val)})`).catch(() => false);

      if (!okMarked) continue;
      await client.evalInPage(`((price, inv, code) => {
        const fill = (sel, val) => {
          const el = document.querySelector(sel);
          if (!el) return false;
          el.focus();
          el.value = '';
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.value = val;
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
          el.blur();
          return true;
        };
        fill('input[data-als-target=\"price\"]', price);
        fill('input[data-als-target=\"inv\"]', inv);
        if (code) fill('input[data-als-target=\"code\"]', code);
        document.querySelectorAll('[data-als-target]').forEach(el => el.removeAttribute('data-als-target'));
        return true;
      })('999','999',${JSON.stringify(merchantCode)})`).catch(() => false);
      await sleep(350);
    }
  }

  await switchToTab('服务与履约');
  await sleep(800);
  await client.evalInPage(`(() => {
    const labels = Array.from(document.querySelectorAll('.ecom-g-radio-wrapper:not(.ecom-g-radio-wrapper-disabled)'));
    const off = labels.find(el => (el.innerText || '').trim() === '下架' || (el.textContent || '').trim() === '下架');
    if (!off) return false;
    if (off.classList.contains('ecom-g-radio-wrapper-checked') || off.querySelector('input:checked')) return true;
    off.scrollIntoView({ block: 'center' });
    off.click();
    const inp = off.querySelector('input');
    if (inp) inp.click();
    return true;
  })()`).catch(() => false);
  await sleep(800);

  await switchToTab('其他信息');
  await sleep(800);

  sendStatus('running', '保存草稿...');
  await client.evalInPage(`(() => {
    const norm = (s) => (s || '').toString().replace(/\\s+/g,'');
    const isVisible = (el) => {
      const style = window.getComputedStyle(el);
      if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    const btns = Array.from(document.querySelectorAll('button, a, span, div')).filter(isVisible);
    for (const el of btns) {
      const t = norm(el.textContent);
      if (t.includes('保存草稿') || t.includes('保存为草稿')) {
        el.click();
        return true;
      }
    }
    return false;
  })()`).catch(() => false);

  let saved = false;
  let saveErr = '';
  for (let i = 0; i < 30; i++) {
    await sleep(300);
    const errText = await client.evalInPage(`(() => {
      const errorTexts = ['必填', '不能为空', '保存失败', '请输入', '请上传', '校验不通过', '错误'];
      const messages = Array.from(document.querySelectorAll('.ant-message-notice, .arco-message, .arco-toast, .ant-notification-notice'));
      for (const m of messages) {
        const text = (m.textContent || '').trim();
        if (errorTexts.some(e => text.includes(e))) return text;
      }
      const formErrors = Array.from(document.querySelectorAll('.ant-form-item-explain-error, .arco-form-item-message-help-error'));
      for (const err of formErrors) {
        const text = (err.textContent || '').trim();
        if (text && errorTexts.some(e => text.includes(e))) return text;
      }
      return null;
    })()`).catch(() => null);
    if (errText) {
      saveErr = String(errText);
      break;
    }
    const okText = await client.evalInPage(`(() => {
      const successTexts = ['保存成功', '草稿保存成功'];
      const messages = Array.from(document.querySelectorAll('.ant-message-notice, .arco-message, .arco-toast, .ant-notification-notice'));
      for (const m of messages) {
        const text = (m.textContent || '').trim();
        if (successTexts.some(s => text.includes(s))) return true;
      }
      return false;
    })()`).catch(() => false);
    if (okText) {
      saved = true;
      break;
    }
    const curUrl = await client.evalInPage('location.href').catch(() => '');
    if (curUrl && !curUrl.includes('create')) {
      saved = true;
      break;
    }
  }

  if (!saved) throw new Error(saveErr ? `保存草稿失败: ${saveErr}` : '保存草稿未检测到成功提示');
  sendStatus('completed', `任务 [${taskData.taskName}] 已保存草稿成功`);
}

module.exports = { runStage2 };

