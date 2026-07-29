const $ = (id) => document.getElementById(id);
let _activeTab = null;
let _domItems = [];   // 手动嗅探（DOM 扫描）结果
let _netItems = [];   // 网络嗅探（后台 webRequest）结果
let _filter = "all";  // all | image | video（视频含音频流）

// ── 客户端连接状态 ──
function refreshStatus() {
  chrome.runtime.sendMessage({ type: "ping_bridge" }, (resp) => {
    const ok = resp && resp.ok;
    $("dot").className = "dot " + (ok ? "ok" : "err");
    $("status").textContent = ok ? "已连接客户端" : "未连接客户端";
  });
}

// ── 工具 ──
function _fmtSize(bytes) {
  if (!bytes) return "";
  if (bytes > 1048576) return (bytes / 1048576).toFixed(1) + "MB";
  if (bytes > 1024) return (bytes / 1024).toFixed(0) + "KB";
  return bytes + "B";
}

function _shortName(url) {
  try {
    const u = new URL(url);
    const base = u.pathname.split("/").pop() || u.hostname;
    const name = decodeURIComponent(base).slice(0, 36);
    return name || u.hostname;
  } catch (e) {
    return url.slice(0, 36);
  }
}

function _iconOf(t) {
  return t === "video" ? "🎬" : t === "audio" ? "🎵" : "🖼";
}

function _displayName(it) {
  let n = _shortName(it.url);
  // 无扩展名的通用流名（videoplayback/playlist 等）→ 用页面标题区分
  if (!/\.[a-z0-9]{2,5}$/i.test(n) && _activeTab && _activeTab.title) {
    n = _activeTab.title.slice(0, 40);
  }
  return n;
}

function _matchFilter(it) {
  if (_filter === "image") return it.media_type === "image";
  if (_filter === "video") return it.media_type === "video" || it.media_type === "audio";
  return true;
}

function _mergedItems() {
  const merged = [];
  const seen = new Set();
  for (const it of [..._netItems, ..._domItems]) {
    if (!it || !it.url || seen.has(it.url)) continue;
    seen.add(it.url);
    merged.push(it);
  }
  return merged;
}

// ── 列表渲染（DOM + 网络嗅探合并，URL 去重，可按类型过滤）──
function renderList() {
  const allItems = _mergedItems();
  const merged = allItems.filter(_matchFilter);
  const box = $("media-list");
  box.innerHTML = "";

  // 整页智能解析条目始终显示（只要页面有 URL），放在列表最顶部
  if (_activeTab && /^https?:/.test(_activeTab.url)) {
    const fb = {
      url: _activeTab.url,
      media_type: "video",
      page_url: _activeTab.url,
      page_title: _activeTab.title || "",
      _fallback: true,
      has_audio: true,
      width: 0, height: 0, size: 0,
    };
    renderFallbackRow(fb);
  }

  if (!merged.length) {
    if (!(_activeTab && /^https?:/.test(_activeTab.url)))
      box.innerHTML = '<div class="empty">尚未嗅探到媒体内容；播放页面视频后自动出现，或点「手动嗅探」</div>';
    return;
  }
  merged.forEach((it) => {
    const row = document.createElement("div");
    row.className = "m-item";
    const thumb = document.createElement(it.media_type === "image" && it.thumb ? "img" : "div");
    thumb.className = "m-thumb";
    if (thumb.tagName === "IMG") {
      thumb.src = it.thumb;
      thumb.loading = "lazy";
    } else {
      thumb.textContent = _iconOf(it.media_type);
    }
    const name = document.createElement("span");
    name.className = "m-name";
    name.title = it.url;
    name.textContent = _displayName(it);
    // 图片标注分辨率+大小，视频标注大小；itag 用于区分同分辨率的不同流
    const meta = [];
    if (it.width && it.height) meta.push(`${it.width}×${it.height}`);
    if (it.itag) meta.push(`#${it.itag}`);
    const sz = _fmtSize(it.size);
    if (sz) meta.push(sz);
    const size = document.createElement("span");
    size.className = "m-size";
    size.textContent = meta.join(" ");
    // 音轨标注：防止下到无声视频
    const tag = document.createElement("span");
    tag.className = "m-size";
    if (/\.(m4s|ts)(\?|#|$)/i.test(it.url)) {
      tag.textContent = "分片";
      tag.style.color = "#8b5cf6";
      tag.title = "DASH/HLS 分片，点「采集」将自动整页解析合并音轨";
    } else if (it.has_audio === false) {
      tag.textContent = "无声轨";
      tag.style.color = "#f59e0b";
      tag.title = "DASH 纯视频流：点「采集」将自动改用整页解析下载（自动合并音轨）";
    } else if (it.media_type === "audio") {
      tag.textContent = "仅音频";
      tag.style.color = "#3b82f6";
    } else if (it.has_audio === true) {
      tag.textContent = "有声";
      tag.style.color = "#188038";
      tag.title = "音画合一的完整流，可直接下载";
    }
    const btn = document.createElement("button");
    btn.textContent = "下载所选";
    if (it._fallback) { btn.style.background = "#a855f7"; btn.style.borderColor = "#a855f7"; }
    btn.addEventListener("click", () => collectItems([it], btn));
    row.append(thumb, name, tag, size, btn);
    box.appendChild(row);
  });
}

function renderFallbackRow(it) {
  const box = $("media-list");
  box.innerHTML = "";
  const row = document.createElement("div");
  row.className = "m-item";
  row.style.border = "1px dashed #3b82f6";
  row.style.borderRadius = "6px";
  const thumb = document.createElement("div");
  thumb.className = "m-thumb";
  thumb.textContent = "🎬";
  const name = document.createElement("span");
  name.className = "m-name";
  name.textContent = "本页视频（整页智能解析）";
  const tag = document.createElement("span");
  tag.className = "m-size";
  tag.textContent = "智能解析";
  tag.style.color = "#a855f7";
  const meta = document.createElement("span");
  meta.className = "m-size";
  if (it._fallback) {
    if (_activeTab && _activeTab.title) meta.textContent = _activeTab.title.slice(0, 35);
  } else if (it.width && it.height) {
    meta.textContent = `${it.width}×${it.height}`;
  }
  const btn = document.createElement("button");
  btn.textContent = "下载所选";
  btn.style.background = "#a855f7";
  btn.style.borderColor = "#a855f7";
  btn.addEventListener("click", () => collectItems([it], btn));
  row.append(thumb, name, tag, meta, btn);
  box.appendChild(row);
}

// ── 采集 ──
function collectItems(items, btn) {
  const payload = items.map((it) => ({
    url: it.url,
    media_type: it.media_type || "file",
    page_url: (_activeTab && _activeTab.url) || it.page_url || "",
    page_title: (_activeTab && _activeTab.title) || "",
    referer: (_activeTab && _activeTab.url) || "",
    cookies: it.cookies || "",
  }));
  // 点下去立刻创建本地任务，不等桥接响应
  const now = Date.now() / 1000;
  payload.forEach((it, i) => {
    const tid = "local_" + now + "_" + i;
    _localTasks[tid] = {
      id: tid, url: it.url,
      filename: (it.page_title || _shortName(it.url)).slice(0, 40) + ".mp4",
      percent: 0, status: "queued", ts: now,
      speed_str: "", received: 0, total: 0,
    };
  });
  renderTasks(null);

  chrome.runtime.sendMessage({ type: "collect_items", items: payload, tabId: _activeTab && _activeTab.id }, (resp) => {
    const ok = resp && resp.ok;
    if (btn) {
      btn.textContent = ok ? "✓" : "✗";
      btn.disabled = true;
      setTimeout(() => { btn.disabled = false; btn.textContent = "下载所选"; }, 1500);
    }
    if (ok) {
      $("info").textContent = `已发送 ${resp.count} 个素材`;
      // 桥接返回了真实 task_id → 替换本地任务 ID
      const ids = resp.task_ids || [];
      ids.forEach((id, i) => {
        const key = "local_" + now + "_" + i;
        if (_localTasks[key]) {
          _localTasks[id] = _localTasks[key];
          _localTasks[id].id = id;
          delete _localTasks[key];
        }
      });
    } else {
      $("info").textContent = "发送失败：客户端未连接";
    }
  });
}

// ── 手动嗅探：让 content script 扫描页面 DOM ──
async function manualSniff() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  _activeTab = tab || null;
  if (!tab || tab.id == null) return;
  try {
    const resp = await chrome.tabs.sendMessage(tab.id, { type: "scan_media" });
    _domItems = (resp && resp.items) || [];
    $("info").textContent = `手动嗅探完成：页面 ${_domItems.length} 个，网络 ${_netItems.length} 个`;
    renderList();
  } catch (e) {
    $("info").textContent = "当前页面不支持嗅探（浏览器内置页面需刷新后重试）";
  }
}

// ── 网络嗅探（每 2 秒轮询后台）──
async function refreshNet() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  _activeTab = tab || _activeTab;
  if (!tab || tab.id == null) return;
  chrome.runtime.sendMessage({ type: "get_sniffed", tabId: tab.id }, (resp) => {
    const items = (resp && resp.items) || [];
    _netItems = items;
    renderList();
  });
}

$("sniff").addEventListener("click", manualSniff);
document.querySelectorAll(".filter-bar button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll(".filter-bar button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    _filter = b.dataset.f;
    renderList();
  });
});
$("collect-all").addEventListener("click", () => {
  const merged = _mergedItems().filter(_matchFilter);
  if (merged.length) collectItems(merged, null);
});

// ── 手动嗅探（清空当前嗅探结果 + 重新扫描页面 DOM + 网络）──
$("manual-sniff").addEventListener("click", async () => {
  _domItems = [];
  _netItems = [];
  if (_activeTab && _activeTab.id != null) {
    chrome.runtime.sendMessage({ type: "clear_sniffed", tabId: _activeTab.id });
  }
  renderList();
  // 清空后立即手动嗅探
  await manualSniff();
  refreshNet();
});

$("open-dir").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "open_dir" }, (resp) => {
    if (!resp || !resp.ok) $("info").textContent = "打开失败：客户端未连接";
  });
});

// ── 下载任务进度（桥接 /tasks，2 秒轮询）──
const _STATUS_TEXT = {
  queued: "排队中", downloading: "下载中", merging: "合并音视频",
  done: "✅ 完成", fail: "❌ 失败",
};

let _localTasks = {}; // 本地任务缓存（不管桥接 /tasks 是否可用都显示进度）

function renderTasks(tasks) {
  const sec = $("task-sec");
  const box = $("task-list");
  // 合并桥接 /tasks 结果到本地缓存
  if (tasks && tasks.length) {
    tasks.forEach((t) => { _localTasks[t.id] = t; });
  }
  // 清理已完成/失败超过 2 分钟的
  const now = Date.now() / 1000;
  for (const id of Object.keys(_localTasks)) {
    const t = _localTasks[id];
    if ((t.status === "done" || t.status === "fail") && now - t.ts > 120) delete _localTasks[id];
  }
  const list = Object.values(_localTasks);
  if (!list.length) {
    sec.style.display = "none";
    return;
  }
  sec.style.display = "block";
  box.innerHTML = "";
  list.sort((a, b) => b.ts - a.ts);
  list.slice(0, 10).forEach((t) => {
    const item = document.createElement("div");
    item.className = "t-item";
    const name = document.createElement("div");
    name.className = "t-name";
    name.textContent = t.filename || _shortName(t.url);
    name.title = t.url;
    const bar = document.createElement("div");
    bar.className = "t-bar" + (t.status === "done" ? " done" : t.status === "fail" ? " fail" : "");
    const inner = document.createElement("div");
    const pct = t.percent >= 0 ? Math.min(100, t.percent) : (t.status === "done" ? 100 : 8);
    inner.style.width = pct + "%";
    bar.appendChild(inner);
    const stat = document.createElement("div");
    stat.className = "t-stat";
    let text = _STATUS_TEXT[t.status] || t.status;
    if (t.status === "downloading" && t.percent >= 0) text += ` ${t.percent.toFixed(0)}%`;
    if (t.speed_str) text += ` ${t.speed_str}`;
    if (t.received) text += ` (${_fmtSize(t.received)}${t.total ? "/" + _fmtSize(t.total) : ""})`;
    if (t.status === "fail" && t.error) text += ` ${t.error.slice(0, 60)}`;
    stat.appendChild(document.createTextNode(text));
    if (t.status === "queued" || t.status === "downloading" || t.status === "merging") {
      const btn = document.createElement("button");
      btn.textContent = "取消";
      btn.addEventListener("click", () => { chrome.runtime.sendMessage({ type: "cancel_task", taskId: t.id }); });
      stat.appendChild(btn);
    } else if (t.status === "fail") {
      const btn = document.createElement("button");
      btn.textContent = "重试";
      btn.addEventListener("click", () => { chrome.runtime.sendMessage({ type: "retry_task", taskId: t.id }); });
      stat.appendChild(btn);
    }
    item.append(name, bar, stat);
    box.appendChild(item);
  });
}

function refreshTasks() {
  chrome.runtime.sendMessage({ type: "get_tasks" }, (resp) => {
    if (resp && resp.ok) {
      renderTasks(resp.tasks);
    } else {
      renderTasks(null);
    }
  });
}
