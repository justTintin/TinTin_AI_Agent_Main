const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 51233;

async function getBridge() {
  const cfg = await chrome.storage.sync.get(["host", "port"]);
  return {
    host: (cfg.host || "127.0.0.1").trim(),
    port: Number(cfg.port) || 51233,
  };
}

async function pingHost(host, port) {
  try {
    const r = await fetch(`http://${host}:${port}/ping`, { signal: AbortSignal.timeout(3000) });
    if (r.ok) return { host, port };
  } catch (e) { /* ignore */ }
  return null;
}

async function discoverBridge() {
  // 尝试存储的端口 → 默认端口 → 4096-65535 范围随机走？ → 先试默认范围
  const cfg = await chrome.storage.sync.get(["host", "port"]);
  const host = (cfg.host || "127.0.0.1").trim();
  const candidates = [Number(cfg.port) || 51233, 51233, 49337, 54321, 51000];
  for (const port of [...new Set(candidates)]) {
    const r = await pingHost(host, port);
    if (r) {
      await chrome.storage.sync.set({ host: r.host, port: r.port });
      return r;
    }
  }
  return null;
}

async function postToBridge(path, body) {
  const cfg = await chrome.storage.sync.get(["host", "port"]);
  const host = (cfg.host || "127.0.0.1").trim();
  const port = Number(cfg.port) || 51233;
  try {
    const resp = await fetch(`http://${host}:${port}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) return resp.json();
  } catch (e) { /* try discovery */ }
  // 首次失败 → 自动发现桥接（端口改了的情况）
  const b = await discoverBridge();
  if (b) {
    const resp = await fetch(`http://${b.host}:${b.port}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) return resp.json();
  }
  throw new Error("bridge_unreachable");
}

// 导出指定 URL 的 cookies（Netscape 格式），供桥接 yt-dlp 使用
async function getCookiesText(url) {
  try {
    let all = await chrome.cookies.getAll({ url });
    try {
      const parts = new URL(url).hostname.split(".");
      if (parts.length > 2) {
        const root = "." + parts.slice(-2).join(".");
        const more = await chrome.cookies.getAll({ domain: root });
        const seen = new Set(all.map((c) => c.name + c.domain + c.path));
        more.forEach((c) => {
          if (!seen.has(c.name + c.domain + c.path)) all.push(c);
        });
      }
    } catch (e) { /* ignore */ }
    if (!all.length) return "";
    const lines = ["# Netscape HTTP Cookie File"];
    all.forEach((c) => {
      lines.push([
        c.domain, c.domain.startsWith(".") ? "TRUE" : "FALSE",
        c.path, c.secure ? "TRUE" : "FALSE",
        Math.floor(c.expirationDate || 0), c.name, c.value,
      ].join("\t"));
    });
    return lines.join("\n");
  } catch (e) {
    return "";
  }
}

function notify(title, message, isErr) {
  try {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
      title,
      message,
    });
  } catch (e) { /* notifications 不可用时忽略 */ }
  chrome.action.setBadgeBackgroundColor({ color: isErr ? "#d93025" : "#188038" });
  chrome.action.setBadgeText({ text: isErr ? "ERR" : "OK" });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 3000);
}

function makeItem(rawUrl, mediaType, info, tab) {
  return {
    url: rawUrl,
    media_type: mediaType,
    page_url: (tab && tab.url) || (info && info.pageUrl) || "",
    page_title: (tab && tab.title) || "",
    referer: (tab && tab.url) || "",
  };
}

async function collectSingle(rawUrl, mediaType, info, tab) {
  if (!rawUrl || /^(data:|blob:|chrome|about:)/.test(rawUrl)) return;
  try {
    await postToBridge("/collect", makeItem(rawUrl, mediaType, info, tab));
    notify("素材采集", "已发送 1 个素材到客户端", false);
  } catch (e) {
    notify("素材采集失败", "无法连接螺丝钉客户端，请确认客户端已启动桥接服务", true);
  }
}

// ── 媒体嗅探（对齐素材浏览器：按 Content-Type/扩展名/CDN 模式抓视频音频请求）──
const sniffed = new Map(); // tabId -> Map(streamKey -> item)
const MEDIA_URL_RE = /(\.(mp4|m3u8|mpd|m3s|m4s|mp3|webm|mov|flv|m4a|wav)(\?|#|$))|videoplayback|[?&]mime=(video|audio)|\/video\/playback/i;
const FRAG_RE = /\.(ts|m4v|f4v)(\?|#|$)/i; // HLS 分片，不入列；.m4s 保留供嗅探（B站等 DASH 流的基础片段）

// 常见 YouTube itag → 分辨率
const ITAG_RES = {
  "18": "640x360", "22": "1280x720", "37": "1920x1080",
  "133": "426x240", "134": "640x360", "135": "854x480", "136": "1280x720", "137": "1920x1080",
  "160": "256x144", "242": "426x240", "243": "640x360", "244": "854x480",
  "247": "1280x720", "248": "1920x1080", "278": "256x144",
  "298": "1280x720", "299": "1920x1080", "302": "1280x720", "303": "1920x1080",
  "308": "2560x1440", "271": "2560x1440", "313": "3840x2160", "315": "3840x2160",
  "394": "256x144", "395": "426x240", "396": "854x480", "397": "1280x720",
  "398": "1920x1080", "399": "1920x1080", "400": "2560x1440", "401": "3840x2160",
};

// 流归组：DASH 会把一条流切成大量 range/sq 分片请求，去掉片段参数后视为同一条流
function streamKeyOf(u) {
  try {
    const x = new URL(u);
    ["range", "sq", "rn", "nrn", "rbuf"].forEach((p) => x.searchParams.delete(p));
    return x.toString();
  } catch (e) {
    return u;
  }
}

// YouTube 音频流 itag（纯音频轨）；ITAG_RES 表内的为纯视频轨（无声）
const AUDIO_ITAGS = new Set(["139", "140", "141", "171", "249", "250", "251", "256", "258", "325", "328"]);
// 音画合一的 progressive 流 itag（完整 MP4，直接下就有声画面）
const PROGRESSIVE_ITAGS = new Set(["18", "22", "37", "38", "82", "83", "84", "85"]);

function parseVideoMeta(url) {
  const meta = { width: 0, height: 0, cleanUrl: url, itag: "", mime: "" };
  try {
    const u = new URL(url);
    ["range", "sq", "rn", "nrn", "rbuf"].forEach((p) => u.searchParams.delete(p));
    meta.cleanUrl = u.toString(); // 无 range 的整流地址，可直接整段下载
    meta.itag = u.searchParams.get("itag") || "";
    const mime = u.searchParams.get("mime") || ""; // video%2Fmp4 / audio%2Fmp4
    meta.mime = decodeURIComponent(mime).split("/")[0];
    const size = u.searchParams.get("size"); // 如 "1920x1080"
    if (size && /^\d+x\d+$/.test(size)) {
      const [w, h] = size.split("x").map(Number);
      meta.width = w; meta.height = h;
    } else if (meta.itag && ITAG_RES[meta.itag]) {
      const [w, h] = ITAG_RES[meta.itag].split("x").map(Number);
      meta.width = w; meta.height = h;
    }
  } catch (e) { /* ignore */ }
  return meta;
}

function addSniffed(tabId, item) {
  if (!sniffed.has(tabId)) sniffed.set(tabId, new Map());
  const m = sniffed.get(tabId);
  const key = streamKeyOf(item.url);
  const old = m.get(key);
  if (old) {
    // 同一条流的后续分片：补充/更新大小、分辨率信息
    let changed = false;
    if ((item.size || 0) > (old.size || 0)) { old.size = item.size; changed = true; }
    if (!old.width && item.width) { old.width = item.width; old.height = item.height; changed = true; }
    if (!changed) return;
  } else {
    if (m.size >= 100) m.delete(m.keys().next().value);
    m.set(key, item);
  }
  try {
    chrome.action.setBadgeBackgroundColor({ tabId, color: "#3b82f6" });
    chrome.action.setBadgeText({ tabId, text: String(m.size) });
  } catch (e) { /* ignore */ }
}

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.tabId < 0 || details.type === "main_frame") return;
    const url = details.url || "";
    let ct = "";
    let size = 0;
    for (const h of details.responseHeaders || []) {
      const name = h.name.toLowerCase();
      if (name === "content-type") ct = (h.value || "").toLowerCase();
      else if (name === "content-length") size = Number(h.value) || 0;
      else if (name === "content-range") {
        // bytes 0-1/71303168 → 整流大小
        const m = (h.value || "").match(/\/(\d+)\s*$/);
        if (m) size = Math.max(size, Number(m[1]) || 0);
      }
    }
    const isMediaCt = ct.startsWith("video/") || ct.startsWith("audio/") || ct.includes("mpegurl");
    const isMediaUrl = MEDIA_URL_RE.test(url);
    if (!isMediaCt && !isMediaUrl) return;
    if (FRAG_RE.test(url)) return; // 跳过分片文件
    // 噪音过滤：网站 UI 音效/静态资源（gstatic、youtube.com/s/、100KB 以下音频）
    try {
      const u = new URL(url);
      if (u.hostname.endsWith("gstatic.com")) return;
      if (u.hostname.endsWith("youtube.com") && u.pathname.startsWith("/s/")) return;
    } catch (e) { /* ignore */ }
    const meta = parseVideoMeta(url);
    // 音轨判断：progressive(音画合一) → mime 参数 → itag 表 → null(未知)
    let hasAudio = null;
    if (PROGRESSIVE_ITAGS.has(meta.itag)) hasAudio = true;
    else if (meta.mime === "audio") hasAudio = true;
    else if (meta.mime === "video") hasAudio = false;
    else if (meta.itag) {
      if (AUDIO_ITAGS.has(meta.itag)) hasAudio = true;
      else if (ITAG_RES[meta.itag]) hasAudio = false;
    }
    const mediaType = (ct.startsWith("audio/") || AUDIO_ITAGS.has(meta.itag)) ? "audio" : "video";
    if (mediaType === "audio" && size > 0 && size < 100 * 1024) return; // UI 提示音
    addSniffed(details.tabId, {
      url: meta.cleanUrl,
      media_type: mediaType,
      has_audio: hasAudio,
      itag: meta.itag,
      width: meta.width,
      height: meta.height,
      content_type: ct,
      size,
      page_url: details.initiator || "",
    });
  },
  { urls: ["http://*/*", "https://*/*"] },
  ["responseHeaders"]
);

chrome.tabs.onRemoved.addListener((tabId) => sniffed.delete(tabId));
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading" && changeInfo.url) {
    sniffed.delete(tabId);
    try { chrome.action.setBadgeText({ tabId, text: "" }); } catch (e) { /* ignore */ }
  }
});

chrome.runtime.onInstalled.addListener(() => {
  // 点击工具栏图标 → 打开侧边栏嗅探面板
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  }
  chrome.contextMenus.create({
    id: "collect_image",
    title: "采集图片到素材库",
    contexts: ["image"],
  });
  chrome.contextMenus.create({
    id: "collect_video",
    title: "采集视频到素材库",
    contexts: ["video"],
  });
  chrome.contextMenus.create({
    id: "collect_link",
    title: "采集链接素材到素材库",
    contexts: ["link"],
  });
  chrome.contextMenus.create({
    id: "collect_page",
    title: "批量采集本页素材",
    contexts: ["page"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "collect_image") {
    await collectSingle(info.srcUrl, "image", info, tab);
  } else if (info.menuItemId === "collect_video") {
    await collectSingle(info.srcUrl, "video", info, tab);
  } else if (info.menuItemId === "collect_link") {
    await collectSingle(info.linkUrl, "file", info, tab);
  } else if (info.menuItemId === "collect_page" && tab && tab.id != null) {
    try {
      await chrome.tabs.sendMessage(tab.id, { type: "scan_and_show" });
    } catch (e) {
      notify("素材采集", "当前页面不支持采集（浏览器内置页面）", true);
    }
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return false;

  if (msg.type === "collect_items") {
    const items = (msg.items || []).filter(
      (it) => it && it.url && !/^(data:|blob:)/.test(it.url)
    );
    if (!items.length) {
      sendResponse({ ok: false, error: "empty" });
      return false;
    }
    (async () => {
      let poToken = "";
      // 从 YouTube 页面获取 PO Token（替换 --cookies-from-browser，不受锁库限制）
      if (msg.tabId != null && items.some((it) => /youtube\.com|youtu\.be/i.test(it.url || it.page_url || ""))) {
        try {
          const [r] = await chrome.scripting.executeScript({
            target: { tabId: msg.tabId },
            func: () => {
              const yt = window.ytcfg || window.ytcfg_;
              return (yt && yt.data_ && yt.data_.PO_TOKEN) || null;
            },
          });
          poToken = (r && r.result) || "";
        } catch (e) { /* ignore */ }
      }
      const enriched = [];
      for (const it of items) {
        let target = { ...it };
        if (/\.(m4s|ts)(\?|#|$)/i.test(it.url) && it.page_url && /^https?:/.test(it.page_url)) {
          target = { ...it, url: it.page_url, stream_url: it.url };
        }
        if (it.media_type === "video" && it.has_audio === false && it.page_url && /^https?:/.test(it.page_url)) {
          target = { ...it, url: it.page_url, stream_url: it.url };
        }
        if ((target.media_type === "video" || target.media_type === "audio") && !target.cookies) {
          target.cookies = await getCookiesText(target.page_url || target.url);
        }
        if (poToken) target.po_token = poToken;
        enriched.push(target);
      }
      return postToBridge("/collect_batch", { items: enriched });
    })()
      .then((data) => {
        notify("素材采集", `已发送 ${items.length} 个素材到客户端`, false);
        sendResponse({ ok: true, count: items.length, task_ids: (data && data.task_ids) || [] });
      })
      .catch(() => {
        notify("素材采集失败", "无法连接螺丝钉客户端，请确认客户端已启动桥接服务", true);
        sendResponse({ ok: false, error: "bridge_unreachable" });
      });
    return true;
  }

  if (msg.type === "ping_bridge") {
    discoverBridge()
      .then((r) => sendResponse({ ok: !!r, data: r }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (msg.type === "bridge_status") {
    (async () => {
      const b = await discoverBridge();
      if (b) {
        try {
          const r = await fetch(`http://${b.host}:${b.port}/status`);
          if (r.ok) { sendResponse({ ok: true, data: await r.json() }); return; }
        } catch (e) { /* ignore */ }
      }
      sendResponse({ ok: false });
    })();
    return true;
  }

  if (msg.type === "get_sniffed") {
    const tabId = msg.tabId != null ? msg.tabId : (sender.tab && sender.tab.id);
    const m = sniffed.get(tabId);
    sendResponse({ ok: true, items: m ? Array.from(m.values()) : [] });
    return false;
  }

  if (msg.type === "clear_sniffed") {
    const tabId = msg.tabId != null ? msg.tabId : (sender.tab && sender.tab.id);
    sniffed.delete(tabId);
    try { chrome.action.setBadgeText({ tabId, text: "" }); } catch (e) { /* ignore */ }
    sendResponse({ ok: true });
    return false;
  }

  if (msg.type === "open_dir") {
    postToBridge("/open_dir", {})
      .then(() => sendResponse({ ok: true }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (msg.type === "cancel_task") {
    postToBridge(`/task/${msg.taskId}/cancel`, {})
      .then(() => sendResponse({ ok: true }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (msg.type === "retry_task") {
    postToBridge(`/task/${msg.taskId}/retry`, {})
      .then(() => sendResponse({ ok: true }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (msg.type === "get_tasks") {
    (async () => {
      const b = await discoverBridge();
      if (b) {
        try {
          const r = await fetch(`http://${b.host}:${b.port}/tasks`);
          if (r.ok) { sendResponse({ ok: true, tasks: (await r.json()).tasks || [] }); return; }
        } catch (e) { /* ignore */ }
      }
      sendResponse({ ok: false, tasks: [] });
    })();
    return true;
  }

  // 导出页面 cookies（Netscape 格式）→ 桥接 yt-dlp 用
  if (msg.type === "get_cookies") {
    (async () => {
      const text = await getCookiesText(msg.url || "");
      const count = text ? text.split("\n").length - 1 : 0;
      sendResponse({ ok: !!text, text, count });
    })();
    return true;
  }

  return false;
});

// 内容脚本消息转发：获取 YouTube 页面的 PO Token（在 ytcfg.data_.PO_TOKEN 中）
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "get_youtube_token" && sender.tab && sender.tab.id != null) {
    chrome.tabs.sendMessage(sender.tab.id, { type: "get_youtube_token" }, (resp) => {
      sendResponse({ poToken: (resp && resp.poToken) || null });
    });
    return true;
  }
  return false;
});
