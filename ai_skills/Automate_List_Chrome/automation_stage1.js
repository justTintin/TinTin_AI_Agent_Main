async function runStage1({ client, bundle, taskData, sendStatus, checkStop, sleep, initialUrl }) {
  const detectIsStage2 = async () => {
    const url = await client.evalInPage('location.href').catch(() => '');
    if (url && url.includes('?') && url.includes('/create')) return true;
    const hasTab = await client
      .evalInPage(`(() => {
        const t = document.body ? document.body.innerText : '';
        return t.includes('图文信息') || t.includes('价格库存') || t.includes('服务与履约') || t.includes('其他信息');
      })()`)
      .catch(() => false);
    return !!hasTab;
  };

  const normalized = (initialUrl || '').replace(/\/+$/, '');
  const isStage1 = !normalized.includes('?') && normalized.endsWith('/create') && !(await detectIsStage2());
  if (!isStage1) {
    const url = await client.evalInPage('location.href').catch(() => '');
    return { ran: false, enteredStage2: await detectIsStage2(), urlAfter: url };
  }

  sendStatus('running', '阶段1: 主图/标题/类目');

  if (bundle.mainImages.length === 0) throw new Error('数据包缺少主图');
  if (!bundle.title) sendStatus('running', '提示: sku.xlsx 第二个工作表未解析到标题，将跳过标题填写');

  sendStatus('running', '等待主图上传区域加载...');
  for (let i = 0; i < 30; i++) {
    if (checkStop()) throw new Error('Task stopped by user');
    const ready = await client
      .evalInPage(`(() => {
        const t = document.body ? (document.body.innerText || '') : '';
        if (t.includes('数据异常请刷新重试')) return 'DATA_ERROR';
        const cnt = document.querySelectorAll('input[type="file"]').length;
        return cnt > 0;
      })()`)
      .catch(() => false);
    if (ready === 'DATA_ERROR') throw new Error('页面提示“数据异常请刷新重试”，请先手动刷新页面后再执行');
    if (ready) break;
    await sleep(500);
  }

  const marked = await client.evalInPage(`(() => {
    const pageText = document.body ? (document.body.innerText || '') : '';
    if (pageText.includes('数据异常请刷新重试')) return 'DATA_ERROR';

    const norm = (s) => (s || '').toString().replace(/\\s+/g,'');
    const allInputs = Array.from(document.querySelectorAll('input[type=\"file\"]'));
    if (!allInputs.length) return false;

    const isVisible = (el) => {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      if (!style) return false;
      if (style.display === 'none' || style.visibility === 'hidden') return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };

    const nodes = Array.from(document.querySelectorAll('span,div,label,a,button')).filter(isVisible);
    const hit = nodes.find(el => {
      const t = norm(el.textContent);
      return t.includes('主图上传') || t.includes('上传主图') || t === '商品主图';
    });

    const scoreInput = (inp) => {
      let s = 0;
      const acc = (inp.getAttribute('accept') || '').toLowerCase();
      if (acc.includes('image')) s += 3;
      if (inp.hasAttribute('multiple')) s += 2;

      let p = inp;
      for (let i = 0; i < 10; i++) {
        if (!p || !p.parentElement) break;
        p = p.parentElement;
        const txt = norm(p.innerText || p.textContent || '');
        if (!txt) continue;
        if (txt.includes('上传主图') || txt.includes('主图上传')) s += 10;
        if (txt.includes('商品主图')) s += 8;
        if (txt.includes('上传辅图')) s -= 4;
        if (txt.includes('详情') && txt.includes('图')) s -= 6;
      }

      if (hit) {
        try {
          const common = inp.closest('.ant-form-item') || inp.closest('form') || inp.parentElement;
          if (common && (common.contains(hit) || hit.contains(common))) s += 6;
          if (hit.closest('.ant-form-item') && inp.closest('.ant-form-item') === hit.closest('.ant-form-item')) s += 6;
        } catch (e) {}
      }

      return s;
    };

    document.querySelectorAll('input[data-als-main=\"1\"]').forEach(el => el.removeAttribute('data-als-main'));
    let best = null;
    let bestScore = -1e9;
    for (const inp of allInputs) {
      const sc = scoreInput(inp);
      if (sc > bestScore) {
        bestScore = sc;
        best = inp;
      }
    }
    if (!best) return false;
    best.setAttribute('data-als-main', '1');
    return true;
  })()`);
  if (marked === 'DATA_ERROR') throw new Error('页面提示“数据异常请刷新重试”，请先手动刷新页面后再执行');
  if (!marked) throw new Error('未找到主图上传控件');

  const { root } = await client.send('DOM.getDocument', { depth: 0, pierce: true });
  const { nodeId: mainInpNodeId } = await client.send('DOM.querySelector', {
    nodeId: root.nodeId,
    selector: 'input[data-als-main="1"]',
  });
  if (!mainInpNodeId) throw new Error('未能定位主图上传 input 节点');

  sendStatus('running', `上传主图: ${bundle.mainImages.length} 张`);
  await client.send('DOM.setFileInputFiles', { nodeId: mainInpNodeId, files: bundle.mainImages.slice(0, 5) });
  await sleep(1200);

  if (bundle.title) {
    sendStatus('running', `填写标题: ${bundle.title}`);
    await client.evalInPage(`(() => {
      const title = ${JSON.stringify(bundle.title)};
      const inputs = Array.from(document.querySelectorAll('input'));
      const target = inputs.find(i => (i.placeholder || '').includes('请输入2-60')) || inputs.find(i => (i.placeholder || '').includes('2-60')) || null;
      if (!target) return false;
      target.focus();
      target.value = title;
      target.dispatchEvent(new Event('input', { bubbles: true }));
      target.dispatchEvent(new Event('change', { bubbles: true }));
      target.blur();
      return true;
    })()`);
    await sleep(500);
  }

  sendStatus('running', '等待类目自动填充...');
  await sleep(5000);

  const categoryValue = await client
    .evalInPage(`(() => {
      const exclude = ${JSON.stringify(bundle.title || '')}.trim();
      const isVisible = (el) => {
        const style = window.getComputedStyle(el);
        if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
        if (style.pointerEvents === 'none') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };
      const els = Array.from(document.querySelectorAll('span,div,a')).filter(isVisible);
      const hits = [];
      for (const el of els) {
        const rect = el.getBoundingClientRect();
        if (rect.top < 180 || rect.top > window.innerHeight - 120) continue;
        if (rect.left < 120 || rect.left > window.innerWidth - 120) continue;
        const t = (el.textContent || '').trim();
        if (!t) continue;
        if (!t.includes('>') && !t.includes('＞')) continue;
        if (t.includes('更多类目') || t.includes('商品标题') || t.includes('下一步')) continue;
        if (exclude && t.includes(exclude)) continue;
        if (t.length < 8 || t.length > 240) continue;
        hits.push({ t, area: rect.width * rect.height });
      }
      hits.sort((a, b) => b.area - a.area);
      return hits.length ? hits[0].t : '';
    })()`)
    .catch(() => '');

  if (categoryValue) {
    sendStatus('running', `类目已填充: ${categoryValue}`);
  } else {
    sendStatus('running', '类目未检测到，尝试推荐类目...');
    await client
      .evalInPage(`(() => {
        const isVisible = (el) => {
          const style = window.getComputedStyle(el);
          if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };
        const label = Array.from(document.querySelectorAll('*')).find(el => isVisible(el) && (el.textContent || '').trim() === '商品类目');
        if (!label) return false;
        const container = label.closest('.ant-form-item') || label.parentElement;
        const sel = container ? container.querySelector('.ant-select-selector, .ant-cascader-picker-label, .ant-select-selection-item, .ant-cascader-selection-item') : null;
        if (sel) {
          sel.click();
          return true;
        }
        return false;
      })()`)
      .catch(() => false);
    await sleep(600);
    await client.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    await client.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    await sleep(800);
  }

  sendStatus('running', '点击下一步...');
  const clickedNext = await client
    .evalInPage(`(() => {
      const isVisible = (el) => {
        const style = window.getComputedStyle(el);
        if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
        if (style.pointerEvents === 'none') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };
      const els = Array.from(document.querySelectorAll('button,[role=\"button\"],a,div,span')).filter(isVisible);
      let best = null;
      let bestScore = -1;
      const bottom = window.innerHeight - 260;
      for (const el of els) {
        const t = (el.textContent || '').trim();
        if (!t.includes('下一步')) continue;
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
    })()`)
    .catch(() => false);
  if (!clickedNext) throw new Error('未能点击下一步');

  let enteredStage2 = false;
  for (let i = 0; i < 30; i++) {
    await sleep(1000);
    if (checkStop()) throw new Error('Task stopped by user');
    const ok = await detectIsStage2();
    if (ok) {
      enteredStage2 = true;
      break;
    }
  }
  const urlAfter = await client.evalInPage('location.href').catch(() => '');
  sendStatus('running', `下一步后URL: ${urlAfter}`);
  return { ran: true, enteredStage2, urlAfter };
}

module.exports = { runStage1 };
