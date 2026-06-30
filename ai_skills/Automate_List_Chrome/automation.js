const fs = require('fs');
const path = require('path');
const xlsx = require('xlsx');

const { runStage1 } = require('./automation_stage1');
const { runStage2 } = require('./automation_stage2');

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function safeToString(v) {
  if (v === null || v === undefined) return '';
  return String(v);
}

function normalizeSkuKey(s) {
  return safeToString(s)
    .trim()
    .replace(/\s+/g, '')
    .replace(/（/g, '(')
    .replace(/）/g, ')')
    .replace(/[－—–]/g, '-')
    .toLowerCase();
}

function isImageFile(name) {
  const ext = path.extname(name).toLowerCase();
  return ext === '.png' || ext === '.jpg' || ext === '.jpeg' || ext === '.webp';
}

function findFirstDirByName(rootDir, dirName) {
  try {
    const direct = path.join(rootDir, dirName);
    if (fs.existsSync(direct) && fs.statSync(direct).isDirectory()) return direct;
  } catch (e) {}

  const queue = [rootDir];
  let guard = 0;
  while (queue.length && guard < 2000) {
    guard += 1;
    const cur = queue.shift();
    let entries = [];
    try {
      entries = fs.readdirSync(cur, { withFileTypes: true });
    } catch (e) {
      continue;
    }
    for (const ent of entries) {
      if (!ent.isDirectory()) continue;
      if (ent.name === dirName) {
        return path.join(cur, ent.name);
      }
      if (ent.name === 'node_modules' || ent.name === '.git' || ent.name === 'dist') continue;
      queue.push(path.join(cur, ent.name));
    }
  }
  return '';
}

function parseNumericIndex(filename) {
  const base = path.basename(filename, path.extname(filename));
  const m = base.match(/(?:主图[_-]?)?(\d+)/);
  if (!m) return Number.MAX_SAFE_INTEGER;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : Number.MAX_SAFE_INTEGER;
}

function collectImagesSorted(dirPath, preferIndexSort) {
  if (!dirPath) return [];
  if (!fs.existsSync(dirPath)) return [];
  let items = [];
  try {
    items = fs.readdirSync(dirPath, { withFileTypes: true });
  } catch (e) {
    return [];
  }
  const files = items
    .filter((d) => d.isFile() && isImageFile(d.name))
    .map((d) => path.join(dirPath, d.name));

  files.sort((a, b) => {
    if (preferIndexSort) {
      const ia = parseNumericIndex(a);
      const ib = parseNumericIndex(b);
      if (ia !== ib) return ia - ib;
    }
    return path.basename(a).toLowerCase().localeCompare(path.basename(b).toLowerCase());
  });
  return files;
}

function readSkuNewCodesJson(workingDir) {
  const candidates = [];
  const direct = path.join(workingDir, 'sku_new_codes.json');
  candidates.push(direct);

  const runsDir = path.join(workingDir, '_runs');
  if (fs.existsSync(runsDir) && fs.statSync(runsDir).isDirectory()) {
    const stack = [runsDir];
    while (stack.length) {
      const cur = stack.pop();
      let entries = [];
      try {
        entries = fs.readdirSync(cur, { withFileTypes: true });
      } catch (e) {
        continue;
      }
      for (const ent of entries) {
        const p = path.join(cur, ent.name);
        if (ent.isDirectory()) stack.push(p);
        if (ent.isFile() && ent.name === 'sku_new_codes.json') candidates.push(p);
      }
    }
  }

  let bestPath = '';
  let bestMtime = -1;
  for (const p of candidates) {
    try {
      if (!fs.existsSync(p) || !fs.statSync(p).isFile()) continue;
      const mtime = fs.statSync(p).mtimeMs || 0;
      if (mtime > bestMtime) {
        bestMtime = mtime;
        bestPath = p;
      }
    } catch (e) {}
  }

  if (!bestPath) return {};

  try {
    const raw = fs.readFileSync(bestPath, 'utf-8');
    const json = JSON.parse(raw);
    const details = json && typeof json === 'object' ? json['明细'] : null;
    if (!Array.isArray(details)) return {};
    const out = {};
    for (const item of details) {
      if (!item || typeof item !== 'object') continue;
      const newCode = safeToString(item['新编码']).trim();
      const full = item['完整数据'] && typeof item['完整数据'] === 'object' ? item['完整数据'] : {};
      const skuName = safeToString(full['sku图片名'] || full['组合装名称']).trim();
      if (!newCode || !skuName) continue;
      out[skuName] = newCode;
    }
    return out;
  } catch (e) {
    return {};
  }
}

function parseSkuExcel(workingDir) {
  const skuPath = path.join(workingDir, 'sku.xlsx');
  if (!fs.existsSync(skuPath)) {
    throw new Error(`未找到 sku.xlsx: ${skuPath}`);
  }

  const wb = xlsx.readFile(skuPath);
  const sheet1Name = wb.SheetNames[0];
  const sheet2Name = wb.SheetNames[1];

  const sheet1 = sheet1Name ? wb.Sheets[sheet1Name] : null;
  const sheet2 = sheet2Name ? wb.Sheets[sheet2Name] : null;

  const sheet1Rows = sheet1 ? xlsx.utils.sheet_to_json(sheet1, { header: 1, defval: '' }) : [];
  const sheet2Rows = sheet2 ? xlsx.utils.sheet_to_json(sheet2, { header: 1, defval: '' }) : [];

  const s1Header = Array.isArray(sheet1Rows[0]) ? sheet1Rows[0].map((v) => safeToString(v).trim()) : [];
  const s2Header = Array.isArray(sheet2Rows[0]) ? sheet2Rows[0].map((v) => safeToString(v).trim()) : [];

  const findHeaderIndex = (headers, candidates) => {
    for (const c of candidates) {
      const idx = headers.findIndex((h) => h === c);
      if (idx >= 0) return idx;
    }
    for (const c of candidates) {
      const idx = headers.findIndex((h) => h && h.includes(c));
      if (idx >= 0) return idx;
    }
    return -1;
  };

  const brandIdx = findHeaderIndex(s1Header, ['品牌']);
  const skuIdx =
    findHeaderIndex(s1Header, ['sku图片名', 'sku 图片名', 'SKU图片名', 'sku', 'SKU', '组合装名称']) >= 0
      ? findHeaderIndex(s1Header, ['sku图片名', 'SKU图片名', 'sku', 'SKU', '组合装名称'])
      : -1;

  let codeIdx = findHeaderIndex(s1Header, ['修改后的商品编码', '同步后的商家编码']);
  if (codeIdx < 0) codeIdx = findHeaderIndex(s1Header, ['编码', 'erp', 'ERP']);
  if (codeIdx < 0 && s1Header.length) codeIdx = s1Header.length - 1;

  const skuNames = [];
  const seenSku = new Set();
  const skuToMerchantCode = {};
  let brand = '';

  for (let r = 1; r < sheet1Rows.length; r++) {
    const row = sheet1Rows[r] || [];
    if (!brand && brandIdx >= 0) {
      const b = safeToString(row[brandIdx]).trim();
      if (b && b.toLowerCase() !== 'nan') brand = b;
    }

    if (skuIdx >= 0) {
      const rawSku = safeToString(row[skuIdx]).trim();
      const sku = rawSku ? rawSku.replace(/\s+/g, ' ').trim() : '';
      if (sku && sku.toLowerCase() !== 'nan' && !seenSku.has(sku)) {
        seenSku.add(sku);
        skuNames.push(sku);
      }

      if (sku && codeIdx >= 0) {
        const code = safeToString(row[codeIdx]).trim();
        if (code && code.toLowerCase() !== 'nan') skuToMerchantCode[sku] = code;
      }
    }
  }

  const fallbackMap = readSkuNewCodesJson(workingDir);
  for (const [k, v] of Object.entries(fallbackMap)) {
    if (!skuToMerchantCode[k]) skuToMerchantCode[k] = v;
  }

  const title = s2Header.length >= 2 ? safeToString(s2Header[1]).trim() : '';
  const normalizedTitle = title && !title.toLowerCase().startsWith('unnamed:') ? title : '';

  const getSheet2Value = (key) => {
    if (!key) return '';
    for (let r = 1; r < sheet2Rows.length; r++) {
      const row = sheet2Rows[r] || [];
      const k = safeToString(row[0]).trim();
      if (k === String(key).trim()) {
        const v = safeToString(row[1]).trim();
        if (!v || v.toLowerCase() === 'nan') return '';
        return v;
      }
    }
    return '';
  };

  const model = getSheet2Value('型号');
  const manufacturer = getSheet2Value('生产厂家');

  return { title: normalizedTitle, brand, model, manufacturer, skuNames, skuToMerchantCode };
}

function getDataBundleInfo(dataDir) {
  if (!dataDir || !fs.existsSync(dataDir)) throw new Error('数据包目录不存在');

  const mainDir = findFirstDirByName(dataDir, '主图');
  const detailDir = findFirstDirByName(dataDir, '详情页');
  const skuDir = findFirstDirByName(dataDir, 'sku图');

  const mainImages = collectImagesSorted(mainDir, true);
  const detailImages = collectImagesSorted(detailDir, false);
  const skuImages = collectImagesSorted(skuDir, false);

  const excel = parseSkuExcel(dataDir);

  return {
    dataDir,
    skuPath: path.join(dataDir, 'sku.xlsx'),
    mainDir,
    detailDir,
    skuDir,
    mainImages,
    detailImages,
    skuImages,
    title: excel.title,
    brand: excel.brand,
    model: excel.model,
    manufacturer: excel.manufacturer,
    skuNames: excel.skuNames,
    skuToMerchantCode: excel.skuToMerchantCode,
  };
}

function findSkuImage(dataDir, skuName) {
  const skuDir = findFirstDirByName(dataDir, 'sku图');
  if (!skuDir) return '';
  const candidates = collectImagesSorted(skuDir, false);
  if (!candidates.length) return '';

  const target = normalizeSkuKey(skuName);
  if (!target) return '';

  let best = '';
  let bestScore = -1;
  for (const p of candidates) {
    const base = path.basename(p, path.extname(p));
    const key = normalizeSkuKey(base);
    if (!key) continue;
    const hit = key.includes(target) || target.includes(key);
    if (!hit) continue;
    const score = Math.min(key.length, target.length);
    if (score > bestScore) {
      bestScore = score;
      best = p;
    }
  }
  return best;
}

function createDebuggerClient(targetWebContents) {
  if (!targetWebContents) throw new Error('targetWebContents is required');
  const dbg = targetWebContents.debugger;
  if (!dbg) throw new Error('webContents.debugger not available');

  const attach = async () => {
    if (!dbg.isAttached()) {
      dbg.attach('1.3');
    }
    await dbg.sendCommand('Runtime.enable');
    await dbg.sendCommand('DOM.enable');
    await dbg.sendCommand('Page.enable');
  };

  const detach = () => {
    if (dbg.isAttached()) {
      try {
        dbg.detach();
      } catch (e) {}
    }
  };

  const send = async (method, params) => {
    try {
      return await dbg.sendCommand(method, params || {});
    } catch (e) {
      throw new Error(`${method} failed: ${e && e.message ? e.message : String(e)}`);
    }
  };

  const evalInPage = async (expression) => {
    const res = await send('Runtime.evaluate', {
      expression: String(expression),
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    return res && res.result ? res.result.value : undefined;
  };

  return { attach, detach, send, evalInPage };
}

async function runDouyinAutomation(targetWebContents, taskData, sendStatus, checkStop) {
  const dataDir = taskData && taskData.dataDir ? String(taskData.dataDir) : '';
  const client = createDebuggerClient(targetWebContents);

  try {
    sendStatus('running', '准备任务数据...');
    if (!dataDir || !fs.existsSync(dataDir)) throw new Error('数据包目录不存在');
    const skuPath = path.join(dataDir, 'sku.xlsx');
    if (!fs.existsSync(skuPath)) throw new Error('数据包目录缺少 sku.xlsx');

    const bundle = getDataBundleInfo(dataDir);
    if (!bundle.mainDir || bundle.mainImages.length === 0) throw new Error('数据包缺少主图文件夹或无可上传图片');
    if (!bundle.detailDir || bundle.detailImages.length === 0) sendStatus('running', '提示: 未发现详情页图片，将跳过详情图上传');

    await client.attach();

    let initialUrl = await client.evalInPage('location.href').catch(() => '');
    if (checkStop && checkStop()) throw new Error('Task stopped by user');

    // 起始页不是 create 流程时，先强制跳到第一阶段页面
    if (!initialUrl.includes('/ffa/g/create')) {
      const stage1Url = 'https://fxg.jinritemai.com/ffa/g/create';
      sendStatus('running', `当前页不是创建页，跳转到第一阶段: ${stage1Url}`);
      await client.send('Page.navigate', { url: stage1Url });
      for (let i = 0; i < 40; i++) {
        await sleep(500);
        if (checkStop && checkStop()) throw new Error('Task stopped by user');
        const u = await client.evalInPage('location.href').catch(() => '');
        if (u && u.includes('/ffa/g/create')) {
          initialUrl = u;
          break;
        }
      }
      if (!initialUrl.includes('/ffa/g/create')) {
        throw new Error(`跳转第一阶段页面失败，当前URL=${initialUrl || '(empty)'}`);
      }
    }

    const r1 = await runStage1({ client, bundle, taskData, sendStatus, checkStop, sleep, initialUrl });
    let currentUrl = (r1 && r1.urlAfter) || (await client.evalInPage('location.href').catch(() => '')) || initialUrl || '';
    if (r1 && r1.ran && !r1.enteredStage2) {
      sendStatus('running', '阶段1已完成，等待进入阶段2页面...');
      let entered = false;
      for (let i = 0; i < 180; i++) {
        await sleep(1000);
        if (checkStop && checkStop()) throw new Error('Task stopped by user');
        const url = await client.evalInPage('location.href').catch(() => '');
        currentUrl = url || currentUrl;
        if (currentUrl.includes('?') && currentUrl.includes('/create')) {
          entered = true;
          break;
        }
      }
      if (!entered) {
        throw new Error(`阶段1完成后等待进入阶段2超时，URL=${currentUrl || '(empty)'}`);
      }
    }

    const isStage2 = currentUrl.includes('?') && currentUrl.includes('/create');
    if (!isStage2) {
      throw new Error(`当前页面不符合阶段2条件，URL=${currentUrl || '(empty)'}`);
    }

    await runStage2({ client, bundle, taskData, sendStatus, checkStop, sleep, findSkuImage });
  } finally {
    client.detach();
  }
}

module.exports = { runDouyinAutomation, getDataBundleInfo, findSkuImage, createDebuggerClient };
