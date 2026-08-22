const $ = (id) => document.getElementById(id);
let _activeTab = null;
let _sniffedItems = [];

async function loadCfg() {
  const cfg = await chrome.storage.sync.get(["host", "port"]);
  $("host").value = cfg.host || "127.0.0.1";
  $("port").value = cfg.port || 51233;
}

function setStatus(ok, text) {
  $("dot").className = "dot " + (ok ? "ok" : "err");
  $("status").textContent = text;
}

function refreshStatus() {
  let done = false;
  // 超时兜底：service worker 休眠未唤醒时回调可能不触发，5 秒后强制提示
  const timer = setTimeout(() => {
    if (done) return;
    done = true;
    setStatus(false, "未连接客户端（插件后台未就绪，请刷新页面重试）");
  }, 5000);
  chrome.runtime.sendMessage({ type: "ping_bridge" }, (resp) => {
    if (done) return;
    done = true;
    clearTimeout(timer);
    if (chrome.runtime.lastError || !resp || !resp.ok) {
      setStatus(false, "未连接客户端（请先启动螺丝钉客户端）");
      $("info").textContent = "";
      return;
    }
    setStatus(true, "已连接客户端");
    chrome.runtime.sendMessage({ type: "bridge_status" }, (r2) => {
      if (r2 && r2.ok && r2.data) {
        $("info").textContent =
          `保存目录：${r2.data.save_dir || "-"}\n已采集：${r2.data.collected || 0} 个`;
      }
    });
  });
}

$("save").addEventListener("click", async () => {
  await chrome.storage.sync.set({
    host: $("host").value.trim() || "127.0.0.1",
    port: Number($("port").value) || 51233,
  });
  refreshStatus();
});

$("batch").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || tab.id == null) return;
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "scan_and_show" });
    window.close();
  } catch (e) {
    $("info").textContent = "当前页面不支持采集（浏览器内置页面需刷新后重试）";
  }
});

// ── 媒体嗅探列表 ──

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
    return decodeURIComponent(base).slice(0, 40) || u.hostname;
  } catch (e) {
    return url.slice(0, 40);
  }
}

function renderMediaList() {
  const box = $("media-list");
  box.innerHTML = "";
  if (!_sniffedItems.length) {
    box.innerHTML = '<div class="empty">暂无（播放页面视频后自动出现）</div>';
    return;
  }
  _sniffedItems.forEach((it, i) => {
    const row = document.createElement("div");
    row.className = "m-item";
    const icon = it.media_type === "audio" ? "🎵" : "🎬";
    const name = document.createElement("span");
    name.className = "m-name";
    name.title = it.url;
    name.textContent = `${icon} ${_shortName(it.url)}`;
    const size = document.createElement("span");
    size.className = "m-size";
    size.textContent = it.has_audio === false ? "无声轨 " + _fmtSize(it.size)
      : (it.media_type === "audio" ? "仅音频 " : "") + _fmtSize(it.size);
    if (it.has_audio === false) size.style.color = "#f59e0b";
    const btn = document.createElement("button");
    btn.textContent = "采集";
    btn.addEventListener("click", () => collectItems([it], btn));
    row.append(name, size, btn);
    box.appendChild(row);
  });
}

function collectItems(items, btn) {
  const payload = items.map((it) => ({
    url: it.url,
    media_type: it.media_type,
    page_url: (_activeTab && _activeTab.url) || it.page_url || "",
    page_title: (_activeTab && _activeTab.title) || "",
    referer: (_activeTab && _activeTab.url) || "",
  }));
  chrome.runtime.sendMessage({ type: "collect_items", items: payload }, (resp) => {
    const ok = resp && resp.ok;
    $("info").textContent = ok ? `已发送 ${resp.count} 个素材` : "发送失败：客户端未连接";
    if (btn) {
      btn.textContent = ok ? "✓" : "✗";
      setTimeout(() => { btn.textContent = "采集"; }, 1500);
    }
  });
}

async function refreshSniffed() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  _activeTab = tab || null;
  if (!tab || tab.id == null) return;
  chrome.runtime.sendMessage({ type: "get_sniffed", tabId: tab.id }, (resp) => {
    _sniffedItems = (resp && resp.items) || [];
    renderMediaList();
  });
}

$("clear-sniffed").addEventListener("click", async () => {
  if (!_activeTab || _activeTab.id == null) return;
  chrome.runtime.sendMessage({ type: "clear_sniffed", tabId: _activeTab.id }, () => {
    _sniffedItems = [];
    renderMediaList();
  });
});

$("collect-all").addEventListener("click", () => {
  if (_sniffedItems.length) collectItems(_sniffedItems, null);
});

loadCfg().then(() => {
  refreshStatus();
  refreshSniffed();
});
