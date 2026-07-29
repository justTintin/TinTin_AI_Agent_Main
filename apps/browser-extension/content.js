(() => {
  if (window.__lsdCollectLoaded) return;
  window.__lsdCollectLoaded = true;

  const MEDIA_EXTS = /\.(jpg|jpeg|png|gif|webp|bmp|svg|mp4|webm|mov|mkv|avi|m3u8|mp3|wav)(\?|#|$)/i;

  function absUrl(u) {
    try {
      return new URL(u, location.href).href;
    } catch (e) {
      return "";
    }
  }

  function scanMedia() {
    const found = new Map();
    const add = (url, type, thumb, width, height) => {
      url = absUrl(url);
      if (!url || /^(data:|blob:|chrome|about:)/.test(url)) return;
      if (!found.has(url)) {
        found.set(url, { url, media_type: type, thumb: thumb || url,
                         width: width || 0, height: height || 0 });
      }
    };

    document.querySelectorAll("img").forEach((img) => {
      const w = img.naturalWidth || img.width || 0;
      const h = img.naturalHeight || img.height || 0;
      if (w > 0 && w < 60 && h > 0 && h < 60) return;
      add(img.currentSrc || img.src, "image", img.currentSrc || img.src, w, h);
      const srcset = img.getAttribute("srcset");
      if (srcset) {
        const first = srcset.split(",")[0].trim().split(/\s+/)[0];
        if (first) add(first, "image", img.currentSrc || img.src, w, h);
      }
    });

    document.querySelectorAll("video").forEach((v) => {
      if (v.src) add(v.src, "video", v.poster || "", v.videoWidth, v.videoHeight);
      v.querySelectorAll("source").forEach((s) => {
        if (s.src) add(s.src, "video", v.poster || "", v.videoWidth, v.videoHeight);
      });
    });

    document.querySelectorAll("a[href]").forEach((a) => {
      const href = a.getAttribute("href") || "";
      if (MEDIA_EXTS.test(href)) {
        const isVideo = /\.(mp4|webm|mov|mkv|avi|m3u8)(\?|#|$)/i.test(href);
        add(href, isVideo ? "video" : "image", "");
      }
    });

    return Array.from(found.values());
  }

  // Alt + 点击图片：快速采集
  document.addEventListener(
    "click",
    (e) => {
      if (!e.altKey) return;
      const img = e.target && e.target.closest ? e.target.closest("img") : null;
      if (!img) return;
      const url = img.currentSrc || img.src;
      if (!url || /^(data:|blob:)/.test(url)) return;
      e.preventDefault();
      e.stopPropagation();
      chrome.runtime.sendMessage({
        type: "collect_items",
        items: [{ url, media_type: "image", thumb: url }],
      });
    },
    true
  );

  // ── 批量采集面板（Shadow DOM 隔离样式）────────────────────────
  let panelHost = null;

  function closePanel() {
    if (panelHost) {
      panelHost.remove();
      panelHost = null;
    }
  }

  function showPanel(items) {
    closePanel();
    panelHost = document.createElement("div");
    panelHost.id = "__lsd_collect_panel__";
    const shadow = panelHost.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = `
      .mask{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:2147483646;}
      .panel{position:fixed;top:5%;left:50%;transform:translateX(-50%);width:min(860px,92vw);
        max-height:86vh;background:#1e1f24;color:#eee;border-radius:12px;z-index:2147483647;
        display:flex;flex-direction:column;font:13px/1.5 -apple-system,"Microsoft YaHei",sans-serif;
        box-shadow:0 12px 48px rgba(0,0,0,.5);}
      .head{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #333;}
      .head .title{font-size:15px;font-weight:600;flex:1;}
      .head button{background:#2d2f36;color:#ddd;border:1px solid #444;border-radius:6px;
        padding:5px 12px;cursor:pointer;font-size:13px;}
      .head button.primary{background:#3b82f6;border-color:#3b82f6;color:#fff;}
      .head button:hover{filter:brightness(1.15);}
      .grid{overflow-y:auto;padding:12px 16px;display:grid;
        grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;}
      .cell{position:relative;border:2px solid transparent;border-radius:8px;overflow:hidden;
        background:#141519;cursor:pointer;aspect-ratio:1;display:flex;align-items:center;justify-content:center;}
      .cell.sel{border-color:#3b82f6;}
      .cell img{width:100%;height:100%;object-fit:cover;}
      .cell .vt{font-size:34px;color:#888;}
      .cell .cb{position:absolute;top:6px;right:6px;width:18px;height:18px;accent-color:#3b82f6;}
      .empty{padding:40px;text-align:center;color:#999;}
      .toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#188038;color:#fff;
        padding:8px 18px;border-radius:20px;z-index:2147483647;font-size:13px;}
    `;
    shadow.appendChild(style);

    const mask = document.createElement("div");
    mask.className = "mask";
    shadow.appendChild(mask);

    const panel = document.createElement("div");
    panel.className = "panel";
    shadow.appendChild(panel);

    const head = document.createElement("div");
    head.className = "head";
    head.innerHTML = `<span class="title">批量采集素材（共 ${items.length} 个）</span>`;
    const btnAll = document.createElement("button");
    btnAll.textContent = "全选";
    const btnNone = document.createElement("button");
    btnNone.textContent = "清空";
    const btnGo = document.createElement("button");
    btnGo.className = "primary";
    btnGo.textContent = "采集选中";
    const btnClose = document.createElement("button");
    btnClose.textContent = "关闭";
    head.append(btnAll, btnNone, btnGo, btnClose);
    panel.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "grid";
    panel.appendChild(grid);

    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "本页未发现可采集的图片/视频素材";
      grid.appendChild(empty);
    }

    const cells = [];
    items.forEach((it, idx) => {
      const cell = document.createElement("div");
      cell.className = "cell sel";
      if (it.media_type === "image") {
        const im = document.createElement("img");
        im.src = it.thumb || it.url;
        im.loading = "lazy";
        cell.appendChild(im);
      } else {
        const sp = document.createElement("span");
        sp.className = "vt";
        sp.textContent = it.media_type === "video" ? "🎬" : it.media_type === "audio" ? "🎵" : "📄";
        cell.appendChild(sp);
      }
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "cb";
      cb.checked = true;
      cell.appendChild(cb);
      cell.addEventListener("click", (e) => {
        if (e.target !== cb) cb.checked = !cb.checked;
        cell.classList.toggle("sel", cb.checked);
      });
      cb.addEventListener("change", () => cell.classList.toggle("sel", cb.checked));
      grid.appendChild(cell);
      cells.push({ cb, idx });
    });

    function toast(text, ok) {
      const t = document.createElement("div");
      t.className = "toast";
      if (!ok) t.style.background = "#d93025";
      t.textContent = text;
      shadow.appendChild(t);
      setTimeout(() => t.remove(), 2500);
    }

    btnAll.onclick = () => cells.forEach((c) => { c.cb.checked = true; c.cb.dispatchEvent(new Event("change")); });
    btnNone.onclick = () => cells.forEach((c) => { c.cb.checked = false; c.cb.dispatchEvent(new Event("change")); });
    btnClose.onclick = closePanel;
    mask.onclick = closePanel;
    btnGo.onclick = () => {
      const picked = cells.filter((c) => c.cb.checked).map((c) => {
        const it = items[c.idx];
        return {
          url: it.url,
          media_type: it.media_type,
          page_url: location.href,
          page_title: document.title,
          referer: location.href,
        };
      });
      if (!picked.length) {
        toast("请先勾选要采集的素材", false);
        return;
      }
      btnGo.disabled = true;
      chrome.runtime.sendMessage({ type: "collect_items", items: picked }, (resp) => {
        btnGo.disabled = false;
        if (resp && resp.ok) {
          toast(`已发送 ${resp.count} 个素材`, true);
          setTimeout(closePanel, 800);
        } else {
          toast("发送失败：请确认螺丝钉客户端已启动", false);
        }
      });
    };

    document.documentElement.appendChild(panelHost);
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "get_youtube_token") {
      try {
        const ytcfg = window.ytcfg || window.ytcfg_;
        if (ytcfg && ytcfg.data_ && ytcfg.data_.PO_TOKEN) {
          sendResponse({ poToken: ytcfg.data_.PO_TOKEN });
          return false;
        }
      } catch (e) { /* ignore */ }
      sendResponse({ poToken: null });
      return false;
    }
    if (msg && msg.type === "scan_media") {
      // 手动嗅探：返回页面 DOM 中的图片/视频（不弹面板）
      sendResponse({ ok: true, items: scanMedia() });
      return false;
    }
    if (msg && msg.type === "scan_and_show") {
      const items = scanMedia();
      // 合并后台嗅探到的网络视频/音频（DOM 里没有的也列出来）
      chrome.runtime.sendMessage({ type: "get_sniffed" }, (resp) => {
        const extra = (resp && resp.items) || [];
        const have = new Set(items.map((i) => i.url));
        extra.forEach((e) => {
          if (e && e.url && !have.has(e.url)) {
            items.push({ url: e.url, media_type: e.media_type || "video", thumb: "" });
          }
        });
        showPanel(items);
      });
      sendResponse({ ok: true });
      return false;
    }
    return false;
  });
})();
