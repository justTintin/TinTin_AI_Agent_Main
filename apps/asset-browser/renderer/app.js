// Global State
let sniffedAssets = [];
let hotspotItems = [];   // 本次采集累计的热榜条
let selectedSniffUrls = new Set();   // 已勾选的嗅探素材，跨重渲染保持选中状态
let _lastSniffSig = '';              // 嗅探列表签名，内容不变时跳过重建（避免勾选被清掉）
let downloadTasks = [];
let currentSettings = {};

// Sniffer State
let blobToMediaUrlsMap = new Map(); // blobUrl/directUrl -> { videoUrl, audioUrl, title }
let activeVideoSrc = null;          // Active playing video src (blob: or http:)
let activeVideoTitle = '';          // Active playing video title
let lastSniffedAssetsFallback = []; // Fallback for pages without active video play event

// Knowledge Base State
let allKnowledgeItems = [];
let activeLoginStatus = {};

// Local Materials State
let allDailyMaterials = [];
let selectedMaterialPaths = new Set();

// DOM Elements
const webview = document.getElementById('browser-webview');
const addressInput = document.getElementById('address-input');
const btnBack = document.getElementById('btn-back');
const btnForward = document.getElementById('btn-forward');
const btnRefresh = document.getElementById('btn-refresh');
const tabBtns = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');
const activeDownloadBadge = document.getElementById('download-active-count');

// Sniffer DOMs
const snifferGrid = document.getElementById('sniffer-grid');
const snifferEmpty = document.getElementById('sniffer-empty');
const sniffedCountDisplay = document.getElementById('sniffed-count');
const selectAllSniffedCheckbox = document.getElementById('select-all-sniffed');
const btnClearSniffed = document.getElementById('btn-clear-sniffed');
const btnDownloadSelected = document.getElementById('btn-download-selected');
const btnManualSniff = document.getElementById('btn-manual-sniff');

// Downloads DOMs
const downloadList = document.getElementById('download-list');
const downloadsEmpty = document.getElementById('downloads-empty');
const btnClearDownloads = document.getElementById('btn-clear-downloads');
const btnOpenDir = document.getElementById('btn-open-dir');
const downloadPathDisplay = document.getElementById('download-path-display');
const btnChangePath = document.getElementById('btn-change-path');
const proxyUrlInput = document.getElementById('proxy-url-input');
const btnSaveProxy = document.getElementById('btn-save-proxy');

// ── 代理配置弹窗 ──
const proxyOverlay = document.getElementById('proxy-config-overlay');
const btnProxyConfig = document.getElementById('btn-proxy-config');
const btnProxyClose = document.getElementById('btn-proxy-close');
const proxyStatusDot = document.getElementById('proxy-status-dot');
const proxyInputField = document.getElementById('proxy-input-field');
const btnProxyParse = document.getElementById('btn-proxy-parse');
const proxyNodeList = document.getElementById('proxy-node-list');
const proxyNodeCount = document.getElementById('proxy-node-count');
const btnProxyStart = document.getElementById('btn-proxy-start');
const btnProxyStop = document.getElementById('btn-proxy-stop');
const btnProxyUpdateSub = document.getElementById('btn-proxy-update-sub');
const btnProxyCopyLog = document.getElementById('btn-proxy-copy-log');
const proxyPanelStatus = document.getElementById('proxy-panel-status');
const proxyInputTabs = document.querySelectorAll('.proxy-input-tab');

let proxyNodes = [];       // 当前解析到的节点列表
let proxyRunning = false;  // 代理是否运行中

// 显示可复制的错误信息（取代 alert）
function showProxyError(msg) {
  const box = document.getElementById('proxy-error-box');
  if (!box) return;
  box.textContent = msg;
  box.style.display = 'block';
  // 自动选中方便复制
  setTimeout(() => {
    const range = document.createRange();
    range.selectNodeContents(box);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }, 100);
}
function clearProxyError() {
  const box = document.getElementById('proxy-error-box');
  if (box) { box.style.display = 'none'; box.textContent = ''; }
}

// Knowledge Base DOMs
const browserView = document.getElementById('browser-view');
const knowledgeBaseView = document.getElementById('knowledge-base-view');
const materialsView = document.getElementById('materials-view');
const btnModeBrowser = document.getElementById('btn-mode-browser');
const btnModeKnowledge = document.getElementById('btn-mode-knowledge');
const btnModeMaterials = document.getElementById('btn-mode-materials');
const btnRefreshMaterials = document.getElementById('btn-refresh-materials');
const materialsContainer = document.getElementById('materials-container');
const materialsSearchInput = document.getElementById('materials-search-input');
const materialsTypeFilter = document.getElementById('materials-type-filter');
const materialsDateFilter = document.getElementById('materials-date-filter');
const materialsSort = document.getElementById('materials-sort');
const materialsSelectedCount = document.getElementById('materials-selected-count');
const btnMaterialsSelectVisible = document.getElementById('btn-materials-select-visible');
const btnMaterialsClearSelected = document.getElementById('btn-materials-clear-selected');
const btnMaterialsCopyPaths = document.getElementById('btn-materials-copy-paths');
const btnMaterialsImportSelected = document.getElementById('btn-materials-import-selected');
const btnMaterialsDeleteSelected = document.getElementById('btn-materials-delete-selected');
const btnMaterialsOpenSelected = document.getElementById('btn-materials-open-selected');
const btnSyncKnowledge = document.getElementById('btn-sync-knowledge');
const loginStatusContainer = document.getElementById('login-status-container');
const kbSearchInput = document.getElementById('kb-search-input');
const kbPlatformFilter = document.getElementById('kb-platform-filter');
const kbTypeFilter = document.getElementById('kb-type-filter');
const kbCreatorFilter = document.getElementById('kb-creator-filter');
const kbSort = document.getElementById('kb-sort');
const kbPagination = document.getElementById('kb-pagination');
const kbPrevBtn = document.getElementById('kb-prev');
const kbNextBtn = document.getElementById('kb-next');
const kbPageInfo = document.getElementById('kb-page-info');
let kbPage = 1;
const KB_PAGE_SIZE = 50;
const kbSelectedCount = document.getElementById('kb-selected-count');
const kbTotalCount = document.getElementById('kb-total-count');
const btnKbDownloadSelected = document.getElementById('btn-kb-download-selected');
const kbLoadingOverlay = document.getElementById('kb-loading-overlay');
const kbLoadingText = document.getElementById('kb-loading-text');
const kbSyncProgressBar = document.getElementById('kb-sync-progress-bar');
const kbListContainer = document.getElementById('kb-list-container');
const kbEmptyState = document.getElementById('kb-empty-state');
const kbTable = document.getElementById('kb-table');
const kbTableBody = document.getElementById('kb-table-body');
const kbSelectAll = document.getElementById('kb-select-all');
const scraperWebview = document.getElementById('scraper-webview');
const btnCollectCreatorAll = document.getElementById('btn-collect-creator-all');

// --- Initialization ---
async function init() {
  // 事件绑定最先执行，确保不论异步初始化是否成功，界面按钮始终可点击
  setupEventListeners();
  setupWebviewListeners();

  try { await loadSettings(); } catch (e) { console.error('loadSettings failed:', e); }
  try { await loadDownloads(); } catch (e) { console.error('loadDownloads failed:', e); }
  // 恢复持久化的收藏记录（重启后不丢失）
  try {
    const saved = await window.api.loadKbItems();
    if (Array.isArray(saved) && saved.length) allKnowledgeItems = saved;
  } catch (e) {}

  // Set initial address input value
  addressInput.value = webview.src;

  // studio 集成：根据握手自动进入对应模式
  try {
    const h = await window.api.getHandoff();
    if (h && h.mode === 'hotspot') {
      // 定时/一键热点采集：自动跑一轮，autoQuit 时跑完关闭窗口（供每日定时任务）
      setTimeout(async () => {
        await captureHotspots(null);
        if (h.autoQuit) { try { window.close(); } catch (e) {} }
      }, 1500);
    } else if (h && h.mode === 'knowledge') {
      // 直接进入「关注同步（我的知识库）」模式
      try { btnModeKnowledge.click(); } catch (e) {}
    } else if (h && h.searchUrl) {
      webview.src = h.searchUrl;
      addressInput.value = h.searchUrl;
      if (h.topic) {
	        document.title = `选题：${h.topic} — 螺丝钉-电商智能体矩阵 素材浏览器`;
      }
      // 将选题专属下载目录设为本次会话的下载路径，并记录到历史目录列表
      if (h.downloadDir) {
        try {
          await window.api.saveSettings({ downloadPath: h.downloadDir });
          await window.api.addDownloadDir(h.downloadDir);
          currentSettings = await window.api.getSettings();
          if (downloadPathDisplay) downloadPathDisplay.textContent = currentSettings.downloadPath;
        } catch (e) { console.warn('设置选题下载目录失败', e); }
      }
    }
  } catch (e) { console.error('getHandoff failed', e); }
}

// Load Settings
async function loadSettings() {
  currentSettings = await window.api.getSettings();
  downloadPathDisplay.textContent = currentSettings.downloadPath || '未选择';
  if (proxyUrlInput && currentSettings.proxyUrl) {
    proxyUrlInput.value = currentSettings.proxyUrl;
  }
}

// Load and render downloads
async function loadDownloads() {
  downloadTasks = await window.api.getDownloads();
  renderDownloads();
  updateActiveDownloadCount();
}

function renderDownloads() {
  if (downloadTasks.length === 0) {
    downloadsEmpty.style.display = 'flex';
    downloadList.style.display = 'none';
    return;
  }
  
  downloadsEmpty.style.display = 'none';
  downloadList.style.display = 'flex';
  
  downloadList.innerHTML = '';
  downloadTasks.forEach(task => {
    const card = document.createElement('div');
    card.className = 'download-card';
    card.dataset.id = task.id;
    card.id = `dl-${task.id}`;
    
    let statusText = '等待';
    let badgeClass = 'downloading';
    let sizeText = task.size > 0 ? formatBytes(task.size) : '计算';
    let progressVal = task.progress || 0;
    
    if (task.status === 'completed') {
      statusText = '已完成';
      badgeClass = 'completed';
      progressVal = 100;
    } else if (task.status === 'failed') {
      statusText = (task.error || '失败').slice(0, 20) + ((task.error || '').length > 20 ? '...' : '');
      badgeClass = 'failed';
    } else if (task.status === 'downloading') {
      statusText = `下载中(${progressVal}%)`;
    } else if (task.status === 'paused') {
      statusText = '已暂停';
      badgeClass = 'paused';
    }
    
    let actionHtml = '';
    if (task.status === 'downloading') {
      actionHtml = `<button class="download-action-btn pause" onclick="pauseDownload('${task.id}')">⏸ 暂停</button>`;
    } else if (task.status === 'paused') {
      actionHtml = `<button class="download-action-btn resume" onclick="resumeDownload('${task.id}')">↻ 重新下载</button>`;
    } else {
      // 失败时显示日志按钮 + 打开文件
      const openBtn = `<button class="download-action-btn" onclick="openFileFolder('${task.path.replace(/\\/g, '\\\\')}')">打开文件</button>`;
      const logBtn = task.status === 'failed' && task.log
        ? `<button class="download-action-btn log" onclick="showDownloadLog('${task.id}')">📋 日志</button>`
        : '';
      actionHtml = logBtn + openBtn;
    }
    
    card.innerHTML = `
      <div class="download-header">
        <span class="download-title" title="${task.filename}">${task.filename}</span>
        <span class="download-status-badge ${badgeClass}" id="dl-status-${task.id}">${statusText}</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" id="dl-bar-${task.id}" style="width: ${progressVal}%"></div>
      </div>
      <div class="download-footer">
        <span id="dl-meta-${task.id}">
          ${task.status === 'downloading' ? '<span id="dl-speed-' + task.id + '">0 KB/s</span>' : sizeText}
        </span>
        <div class="download-actions" id="dl-actions-${task.id}">
          ${actionHtml}
        </div>
      </div>
    `;
    
    // 双击失败项弹出详细日志
    if (task.status === 'failed' && task.log) {
      card.style.cursor = 'pointer';
      card.addEventListener('dblclick', () => showDownloadLog(task.id));
    }
    
    // 右键菜单：取消任务
    card.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      showDownloadContextMenu(e.clientX, e.clientY, task);
    });
    
    downloadList.appendChild(card);
  });
}

// 右键下载项上下文菜单
function showDownloadContextMenu(x, y, task) {
  // 移除已有菜单
  const old = document.getElementById('download-context-menu');
  if (old) old.remove();

  const menu = document.createElement('div');
  menu.id = 'download-context-menu';
  menu.style.cssText = `
    position: fixed; left: ${x}px; top: ${y}px; z-index: 9999;
    background: #2a2a2a; border: 1px solid #444; border-radius: 6px;
    padding: 4px 0; min-width: 120px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  `;

  const cancelItem = document.createElement('div');
  cancelItem.textContent = '🗑 取消下载';
  cancelItem.style.cssText = `
    padding: 8px 16px; cursor: pointer; color: #ef4444; font-size: 0.8rem;
    display: flex; align-items: center; gap: 6px;
  `;
  cancelItem.addEventListener('mouseenter', () => { cancelItem.style.background = '#333'; });
  cancelItem.addEventListener('mouseleave', () => { cancelItem.style.background = 'transparent'; });
  cancelItem.addEventListener('click', () => {
    cancelDownloadItem(task.id);
    menu.remove();
  });
  menu.appendChild(cancelItem);

  document.body.appendChild(menu);

  // 点击其他地方关闭菜单
  const closeMenu = (e) => {
    if (!menu.contains(e.target)) {
      menu.remove();
      document.removeEventListener('click', closeMenu);
      document.removeEventListener('contextmenu', closeMenu);
    }
  };
  setTimeout(() => {
    document.addEventListener('click', closeMenu);
    document.addEventListener('contextmenu', closeMenu);
  }, 0);
}

// 显示下载详情日志弹窗
function showDownloadLog(id) {
  const task = downloadTasks.find(t => t.id === id);
  if (!task || !task.log) return;

  // 移除已有弹窗
  const old = document.getElementById('download-log-modal');
  if (old) old.remove();

  const overlay = document.createElement('div');
  overlay.id = 'download-log-modal';
  overlay.style.cssText = `
    position: fixed; inset: 0; z-index: 10000;
    background: rgba(0,0,0,0.6); display: flex;
    align-items: center; justify-content: center;
  `;

  const panel = document.createElement('div');
  panel.style.cssText = `
    background: #1a1a2e; border: 1px solid #444; border-radius: 10px;
    width: 80%; max-width: 800px; max-height: 80vh;
    display: flex; flex-direction: column;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  `;

  const header = document.createElement('div');
  header.style.cssText = `
    display: flex; justify-content: space-between; align-items: center;
    padding: 14px 18px; border-bottom: 1px solid #333;
  `;
  header.innerHTML = `<span style="font-weight:700;color:#fca5a5;">📋 下载日志 - ${task.filename}</span>
    <span style="cursor:pointer;color:#888;font-size:1.2rem;" id="dl-log-close">✕</span>`;

  const body = document.createElement('pre');
  body.style.cssText = `
    margin: 0; padding: 16px 18px; overflow: auto; flex: 1;
    font-family: 'Consolas', 'Courier New', monospace; font-size: 0.75rem;
    color: #d1d5db; line-height: 1.5; white-space: pre-wrap; word-break: break-all;
  `;
  body.textContent = task.log;

  panel.appendChild(header);
  panel.appendChild(body);
  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  header.querySelector('#dl-log-close').onclick = close;
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
}

// 暂停下载
async function pauseDownload(id) {
  await window.api.pauseDownload(id);
}

// 重新下载
async function resumeDownload(id) {
  await window.api.resumeDownload(id);
}

// 取消并删除任务
async function cancelDownloadItem(id) {
  await window.api.cancelDownloadItem(id);
}

function updateActiveDownloadCount() {
  const active = downloadTasks.filter(t => t.status === 'downloading').length;
  if (active > 0) {
    activeDownloadBadge.textContent = active;
    activeDownloadBadge.style.display = 'inline-block';
  } else {
    activeDownloadBadge.style.display = 'none';
  }
}

// Cancel Download
async function cancelDownload(id) {
  await window.api.cancelDownload(id);
}

// Open Containing Folder
async function openFileFolder(filePath) {
  const success = await window.api.openFileFolder(filePath);
  if (!success) {
    alert('文件不存在，可能已被移动或删除');
  }
}

// --- Event Listeners Setup ---
function setupEventListeners() {
  // Navigation
  btnBack.addEventListener('click', () => { if (webview.canGoBack()) webview.goBack(); });
  btnForward.addEventListener('click', () => { if (webview.canGoForward()) webview.goForward(); });
  btnRefresh.addEventListener('click', () => webview.reload());

  const btnAutoScroll = document.getElementById('btn-auto-scroll');
  if (btnAutoScroll) {
    btnAutoScroll.addEventListener('click', () => autoScrollToBottom(btnAutoScroll));
  }
  const btnHotspot = document.getElementById('btn-capture-hotspot');
  if (btnHotspot) {
    btnHotspot.addEventListener('click', () => captureHotspots(btnHotspot));
  }
  
  addressInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      let val = addressInput.value.trim();
      if (!val.startsWith('http://') && !val.startsWith('https://')) {
        // 像网址就直接访问，否则'Google 搜索（通用浏览器）
        if (val.includes('.') && !val.includes(' ')) {
          val = 'https://' + val;
        } else {
          val = 'https://www.google.com/search?q=' + encodeURIComponent(val);
        }
      }
      webview.src = val;
      addressInput.blur();
    }
  });

  // Platform navigation
  document.querySelectorAll('.platform-btn[data-url]').forEach(btn => {
    btn.addEventListener('click', () => {
      const url = btn.dataset.url;
      webview.src = url;
      addressInput.value = url;
      // 自动切换回网页浏览器模式
      btnModeBrowser.click();
    });
  });

  // Mode switching
  btnModeBrowser.addEventListener('click', () => {
    btnModeBrowser.classList.add('active');
    btnModeKnowledge.classList.remove('active');
    btnModeMaterials.classList.remove('active');
    browserView.style.display = 'flex';
    knowledgeBaseView.style.display = 'none';
    materialsView.style.display = 'none';
    // Navigate to Pinterest by default
    if (!webview.src || webview.src === 'about:blank') {
      webview.src = 'https://www.pinterest.com/';
    }
  });

  btnModeKnowledge.addEventListener('click', () => {
    btnModeKnowledge.classList.add('active');
    btnModeBrowser.classList.remove('active');
    btnModeMaterials.classList.remove('active');
    browserView.style.display = 'none';
    knowledgeBaseView.style.display = 'flex';
    materialsView.style.display = 'none';
    
    // Auto check login status when switching to Knowledge Base
    checkLoginStatus();
    // 显示已持久化/已嗅探的收藏记录（不为空时直接渲染，避免空白
    if (allKnowledgeItems.length > 0) {
      kbEmptyState.style.display = 'none';
      renderKnowledgeBaseTable();
    }
  });

  btnModeMaterials.addEventListener('click', () => {
    btnModeMaterials.classList.add('active');
    btnModeBrowser.classList.remove('active');
    btnModeKnowledge.classList.remove('active');
    browserView.style.display = 'none';
    knowledgeBaseView.style.display = 'none';
    materialsView.style.display = 'flex';
    
    // Load local daily materials
    loadDailyMaterials();
  });

  btnRefreshMaterials.addEventListener('click', () => {
    loadDailyMaterials();
  });

  if (materialsSearchInput) {
    let _materialsSearchTimer = null;
    materialsSearchInput.addEventListener('input', () => {
      clearTimeout(_materialsSearchTimer);
      _materialsSearchTimer = setTimeout(() => renderDailyMaterials(), 220);
    });
  }
  if (materialsTypeFilter) materialsTypeFilter.addEventListener('change', () => renderDailyMaterials());
  if (materialsDateFilter) materialsDateFilter.addEventListener('change', () => renderDailyMaterials());
  if (materialsSort) materialsSort.addEventListener('change', () => renderDailyMaterials());

  if (btnMaterialsSelectVisible) {
    btnMaterialsSelectVisible.addEventListener('click', () => {
      const visibleCards = Array.from(document.querySelectorAll('.material-file-card'));
      visibleCards.forEach((card) => {
        const p = card.dataset.path;
        if (p) selectedMaterialPaths.add(p);
        const cb = card.querySelector('.material-item-check');
        if (cb) cb.checked = true;
        card.classList.add('selected');
      });
      updateMaterialsSelectedCount();
    });
  }

  if (btnMaterialsClearSelected) {
    btnMaterialsClearSelected.addEventListener('click', () => {
      selectedMaterialPaths.clear();
      updateMaterialsSelectionUI();
    });
  }

  if (btnMaterialsCopyPaths) {
    btnMaterialsCopyPaths.addEventListener('click', async () => {
      const paths = Array.from(selectedMaterialPaths);
      if (paths.length === 0) {
        alert('请先勾选要复制的素材项');
        return;
      }
      try {
        await navigator.clipboard.writeText(paths.join('\n'));
        alert(`已复制 ${paths.length} 条路径`);
      } catch (e) {
        alert('复制失败，请检查系统剪贴板权限');
      }
    });
  }

  if (btnMaterialsOpenSelected) {
    btnMaterialsOpenSelected.addEventListener('click', async () => {
      const paths = Array.from(selectedMaterialPaths);
      if (paths.length === 0) {
        alert('请先勾选要打开目录的素材项');
        return;
      }
      for (const p of paths) {
        await window.api.openFileFolder(p);
      }
    });
  }

  if (btnMaterialsImportSelected) {
    btnMaterialsImportSelected.addEventListener('click', async () => {
      const paths = Array.from(selectedMaterialPaths);
      if (paths.length === 0) {
        alert('请先勾选要导入的素材项');
        return;
      }
      try {
        const res = await window.api.enqueueMaterialImport(paths);
        if (res && res.ok) {
          alert(`已写入素材导入任务：${res.count} 条\n任务文件：${res.file}`);
        } else {
          alert('写入素材导入任务失败');
        }
      } catch (e) {
        alert('写入素材导入任务失败：' + (e && e.message ? e.message : e));
      }
    });
  }

  if (btnMaterialsDeleteSelected) {
    btnMaterialsDeleteSelected.addEventListener('click', async () => {
      const paths = Array.from(selectedMaterialPaths);
      if (paths.length === 0) {
        alert('请先勾选要删除的素材项');
        return;
      }
      const ok = confirm(`确认删除已选 ${paths.length} 个本地文件？\n该操作不可撤销。`);
      if (!ok) return;
      try {
        const res = await window.api.deleteLocalFiles(paths);
        if (res && res.ok) {
          selectedMaterialPaths.clear();
          alert(`删除完成：成功 ${res.deleted}，失败 ${res.failed}`);
          await loadDailyMaterials();
        } else {
          alert('删除失败');
        }
      } catch (e) {
        alert('删除失败：' + (e && e.message ? e.message : e));
      }
    });
  }

  // Knowledge Base Sync
  btnSyncKnowledge.addEventListener('click', () => {
    syncKnowledgeBase();
  });

  // Knowledge Base Select All Checkbox
  kbSelectAll.addEventListener('change', () => {
    const checked = kbSelectAll.checked;
    document.querySelectorAll('.kb-item-check').forEach(cb => {
      cb.checked = checked;
    });
    updateKbSelectedCount();
  });

  // Knowledge Base Filters
  // 筛选/排序变化时回到第 1 页
  const _kbReset = () => { kbPage = 1; renderKnowledgeBaseTable(); };
  // 搜索防抖：避免每敲一个字就全表重建（卡顿主因）
  let _kbSearchTimer = null;
  kbSearchInput.addEventListener('input', () => {
    clearTimeout(_kbSearchTimer);
    _kbSearchTimer = setTimeout(_kbReset, 300);
  });
  kbPlatformFilter.addEventListener('change', () => { _syncCreatorFilterOptions(); _kbReset(); });
  kbTypeFilter.addEventListener('change', _kbReset);
  if (kbCreatorFilter) kbCreatorFilter.addEventListener('change', () => {
    _kbReset();
    // 选定具体创作者时显示「收藏全部」按钮
    if (btnCollectCreatorAll) {
      btnCollectCreatorAll.style.display = kbCreatorFilter.value !== 'all' ? 'inline-block' : 'none';
    }
  });
  if (btnCollectCreatorAll) btnCollectCreatorAll.addEventListener('click', () => collectAllFromCreator());
  if (kbSort) kbSort.addEventListener('change', _kbReset);
  if (kbPrevBtn) kbPrevBtn.addEventListener('click', () => { if (kbPage > 1) { kbPage--; renderKnowledgeBaseTable(); } });
  if (kbNextBtn) kbNextBtn.addEventListener('click', () => { kbPage++; renderKnowledgeBaseTable(); });

  // Knowledge Base Download Selected
  btnKbDownloadSelected.addEventListener('click', async () => {
    const checkedBoxes = document.querySelectorAll('.kb-item-check:checked');
    if (checkedBoxes.length === 0) {
      alert('请先勾选需要下载的收藏记录');
      return;
    }
    
    // Get daily subdirectory name YYYY-MM-DD
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    const subDir = `${yyyy}-${mm}-${dd}`;
    
    // Switch to Downloads tab to display progress
    document.querySelector('.tab-btn[data-tab="tab-downloads"]').click();
    
    // Disable download button and show message
    btnKbDownloadSelected.disabled = true;
    btnKbDownloadSelected.textContent = '下载..';
    
    try {
      for (const cb of checkedBoxes) {
        const item = cb._itemData;
        if (item) {
          await downloadKnowledgeBaseItem(item, subDir);
        }
      }
      alert(`已开始在后台为您下载选中的项目，请切换到“下载管理”标签查看进度！\n所有资源与元数据都存入今日目录'{subDir}/`);
    } catch(err) {
      console.error(err);
      alert('批量下载执行中遇到了问题，详情查看控制台');
    } finally {
      btnKbDownloadSelected.disabled = false;
      btnKbDownloadSelected.textContent = '批量下载';
    }
  });

  // Tab switching
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      tabPanes.forEach(p => p.classList.remove('active'));
      
      btn.classList.add('active');
      const tabId = btn.dataset.tab;
      document.getElementById(tabId).classList.add('active');
    });
  });

  // Sniffer Panel Actions
  selectAllSniffedCheckbox.addEventListener('change', () => {
    const checked = selectAllSniffedCheckbox.checked;
    document.querySelectorAll('.sniffed-item-check').forEach(cb => {
      cb.checked = checked;
    });
    selectedSniffUrls.clear();
    if (checked) sniffedAssets.forEach(a => selectedSniffUrls.add(a.url));
  });

  btnManualSniff.addEventListener('click', () => {
    try {
      webview.send('trigger-manual-sniff');
      
      // Visual feedback
      btnManualSniff.textContent = '嗅探..';
      btnManualSniff.disabled = true;
      setTimeout(() => {
        btnManualSniff.textContent = '手动嗅探';
        btnManualSniff.disabled = false;
      }, 1000);
    } catch (e) {
      console.error('Failed to send trigger-manual-sniff:', e);
    }
  });

  btnClearSniffed.addEventListener('click', () => {
    sniffedAssets = [];
    selectedSniffUrls.clear();
    blobToMediaUrlsMap.clear();
    lastSniffedAssetsFallback = [];
    activeVideoSrc = null;
    activeVideoTitle = '';
    renderSniffedAssets();
  });

  btnDownloadSelected.addEventListener('click', async () => {
    const checkedBoxes = document.querySelectorAll('.sniffed-item-check:checked');
    if (checkedBoxes.length === 0) {
      alert('请先勾选需要下载的素材');
      return;
    }
    
    // Switch to Downloads tab so user can see progress
    document.querySelector('.tab-btn[data-tab="tab-downloads"]').click();

    for (let cb of checkedBoxes) {
      const idx = parseInt(cb.dataset.index, 10);
      const asset = sniffedAssets[idx];
      if (asset) {
        const id = 'dl-' + Date.now() + '-' + Math.random().toString(36).substring(2, 7);
        await window.api.startDownload({
          id,
          url: asset.url,
          audioUrl: asset.type === 'combined' ? asset.audioUrl : null,
          filename: asset.name,
          referer: webview.src
        });
      }
    }
  });

  // Downloads Panel Actions
  btnClearDownloads.addEventListener('click', async () => {
    downloadTasks = await window.api.clearDownloads();
    renderDownloads();
    updateActiveDownloadCount();
  });

  btnOpenDir.addEventListener('click', async () => {
    if (currentSettings.downloadPath) {
      await window.api.openPath(currentSettings.downloadPath);
    }
  });

  btnChangePath.addEventListener('click', async () => {
    const newPath = await window.api.selectDownloadDir();
    if (newPath) {
      currentSettings = await window.api.saveSettings({ downloadPath: newPath });
      downloadPathDisplay.textContent = currentSettings.downloadPath;
    }
  });

  btnSaveProxy.addEventListener('click', async () => {
    const proxyUrl = proxyUrlInput.value.trim();
    currentSettings = await window.api.saveSettings({ proxyUrl });
    proxyUrlInput.style.borderColor = proxyUrl ? 'var(--color-primary)' : 'var(--border-color)';
    setTimeout(() => { proxyUrlInput.style.borderColor = 'var(--border-color)'; }, 1500);
  });

  // ── 代理配置弹窗 ──

  // 更新状态指示（左侧按钮小圆点 + 弹窗底部文字）
  async function refreshProxyStatus() {
    const st = await window.api.v2rayStatus();
    proxyRunning = st.running;
    if (st.running) {
      proxyStatusDot.style.background = '#34d399';
      proxyPanelStatus.textContent = `▶️ 运行中 (${st.proxyUrl})`;
      proxyPanelStatus.style.color = '#34d399';
      btnProxyStop.style.display = '';
      btnProxyStart.textContent = '▶ 重启代理';
      // 自动填入代理地址到手动代理设置
      if (!proxyUrlInput.value.trim()) {
        proxyUrlInput.value = st.proxyUrl;
        await window.api.saveSettings({ proxyUrl: st.proxyUrl });
      }
    } else {
      proxyStatusDot.style.background = '#6b7280';
      proxyPanelStatus.textContent = '⏹ 未启动';
      proxyPanelStatus.style.color = 'var(--text-muted)';
      btnProxyStop.style.display = 'none';
      btnProxyStart.textContent = '▶ 启动代理';
    }
  }

  // 打开/关闭弹窗
  btnProxyConfig.addEventListener('click', () => {
    proxyOverlay.style.display = 'flex';
    refreshProxyStatus();
    // 从 sessionStorage 恢复节点（刷新页面后不丢失）
    if (proxyNodes.length === 0) {
      try { const saved = sessionStorage.getItem('proxyNodes'); if (saved) proxyNodes = JSON.parse(saved); } catch(e){}
    }
    renderProxyNodes();
  });
  btnProxyClose.addEventListener('click', () => { proxyOverlay.style.display = 'none'; });
  proxyOverlay.addEventListener('click', (e) => { if (e.target === proxyOverlay) proxyOverlay.style.display = 'none'; });

  // 协议标签切换
  proxyInputTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      proxyInputTabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const proto = tab.dataset.proto;
      if (proto === 'sub') {
        proxyInputField.placeholder = '粘贴订阅地址...';
      } else {
        proxyInputField.placeholder = `粘贴 ${proto}:// 链接...`;
      }
    });
  });

  // 渲染节点列表
  function renderProxyNodes() {
    proxyNodeList.innerHTML = '';
    proxyNodeCount.textContent = `${proxyNodes.length} 个节点`;

    if (proxyNodes.length === 0) {
      proxyNodeList.innerHTML = '<div style="color:var(--text-muted);font-size:0.75rem;text-align:center;padding:20px 0;">请先输入订阅地址或分享链接</div>';
      return;
    }

    let selectedIdx = -1;
    proxyNodes.forEach((node, i) => {
      const div = document.createElement('div');
      div.className = 'proxy-node-item';
      const proto = node.protocol || '?';
      const name = node.remark || node.host || `节点 ${i+1}`;
      div.innerHTML = `
        <span style="font-weight:600;color:var(--color-primary);font-size:0.7rem;min-width:32px;">${proto}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${name}</span>
        <span class="node-latency" id="nlat-${i}">—</span>
      `;
      div.addEventListener('click', async () => {
        // 选中样式
        document.querySelectorAll('.proxy-node-item').forEach(el => el.classList.remove('selected'));
        div.classList.add('selected');
        selectedIdx = i;
        // TCP 测速（不启动 xray，不占端口）
        const latSpan = document.getElementById(`nlat-${i}`);
        latSpan.textContent = '测试中...';
        latSpan.className = 'node-latency testing';
        const result = await window.api.v2rayTestLatency(node);
        if (result.ok && result.latency >= 0) {
          latSpan.textContent = `${result.latency}ms`;
          latSpan.className = `node-latency ${result.latency < 500 ? 'good' : 'bad'}`;
        } else {
          latSpan.textContent = '超时';
          latSpan.className = 'node-latency bad';
        }
      });
      proxyNodeList.appendChild(div);
	    });
	  }

	  // 自动测试所有节点延迟（逐条，间隔 300ms 避免并发）
	  async function testAllNodesLatency() {
	    for (let i = 0; i < proxyNodes.length; i++) {
	      const latSpan = document.getElementById(`nlat-${i}`);
	      if (!latSpan) continue;
	      latSpan.textContent = '测试中...';
	      latSpan.className = 'node-latency testing';
	      const result = await window.api.v2rayTestLatency(proxyNodes[i]);
	      if (result.ok && result.latency >= 0) {
	        latSpan.textContent = `${result.latency}ms`;
	        latSpan.className = `node-latency ${result.latency < 500 ? 'good' : 'bad'}`;
	      } else {
	        latSpan.textContent = '不通';
	        latSpan.className = 'node-latency bad';
	      }
	      await new Promise(r => setTimeout(r, 300));
	    }
	  }

	  // 解析按钮
  btnProxyParse.addEventListener('click', async () => {
    clearProxyError();
    const input = proxyInputField.value.trim();
    if (!input) return;

    btnProxyParse.textContent = '解析中...';
    btnProxyParse.disabled = true;

    try {
      // 判断当前激活的协议标签
      const activeTab = document.querySelector('.proxy-input-tab.active');
      const proto = activeTab ? activeTab.dataset.proto : 'sub';

      if (proto === 'sub' || input.startsWith('http://') || input.startsWith('https://')) {
        // 订阅地址
        const result = await window.api.v2rayFetchSubscription(input);
        if (!result.ok) throw new Error(result.error);
        if (!result.nodes || result.nodes.length === 0) throw new Error('订阅返回 0 个有效节点');
        proxyNodes = result.nodes;
      } else {
        // 分享链接
        const node = await window.api.v2rayParseLink(input);
        if (!node) throw new Error('无法解析该链接');
        proxyNodes = [node];
      }

      // 保存到 sessionStorage，刷新页面后恢复
      try { sessionStorage.setItem('proxyNodes', JSON.stringify(proxyNodes)); } catch(e){}
      renderProxyNodes();
      // 自动测试所有节点的延迟
      testAllNodesLatency();
    } catch (e) {
      showProxyError('解析失败:\n' + e.message);
    }

    btnProxyParse.textContent = '解析';
    btnProxyParse.disabled = false;
  });

  // 启动代理
  btnProxyStart.addEventListener('click', async () => {
    clearProxyError();
    if (proxyNodes.length === 0) { showProxyError('请先解析节点'); return; }
    // 获取选中的节点（如果有），否则用全部
    const selected = document.querySelector('.proxy-node-item.selected');
    const nodesToUse = selected ? [proxyNodes[Array.from(proxyNodeList.children).indexOf(selected)]] : proxyNodes;

    btnProxyStart.textContent = '启动中...';
    btnProxyStart.disabled = true;

    try {
      const result = await window.api.v2rayStart(nodesToUse);
      if (!result.ok) throw new Error(result.error);
      await refreshProxyStatus();
    } catch (e) {
      showProxyError('启动失败:\n' + e.message);
    }

    btnProxyStart.textContent = '▶ 重启代理';
    btnProxyStart.disabled = false;
  });

  // 停止代理
  btnProxyStop.addEventListener('click', async () => {
    clearProxyError();
    await window.api.v2rayStop();
    await refreshProxyStatus();
  });

  // 复制日志到剪贴板
  btnProxyCopyLog.addEventListener('click', () => {
    const box = document.getElementById('proxy-error-box');
    const status = document.getElementById('proxy-panel-status');
    const text = [
      status ? status.textContent : '',
      box && box.style.display !== 'none' ? '\n' + box.textContent : '',
      '\n节点列表:',
      ...proxyNodes.map(n => `  ${n.protocol}://${n.host}:${n.port}  # ${n.remark || ''}`),
    ].join('\n').trim();
    if (text) {
      navigator.clipboard.writeText(text).then(() => {
        btnProxyCopyLog.textContent = '✅ 已复制';
        setTimeout(() => { btnProxyCopyLog.textContent = '📋 复制日志'; }, 2000);
      });
    }
  });

  // 更新订阅
  btnProxyUpdateSub.addEventListener('click', async () => {
    clearProxyError();
    const subUrl = proxyInputField.value.trim();
    if (!subUrl.startsWith('http')) { showProxyError('请在输入框中粘贴有效的订阅地址'); return; }

    btnProxyUpdateSub.textContent = '更新中...';
    btnProxyUpdateSub.disabled = true;

    try {
      const result = await window.api.v2rayFetchSubscription(subUrl);
      if (!result.ok) throw new Error(result.error);
      if (!result.nodes || result.nodes.length === 0) throw new Error('订阅返回 0 个有效节点');
      proxyNodes = result.nodes;
      renderProxyNodes();
      testAllNodesLatency();
    } catch (e) {
      showProxyError('更新订阅失败:\n' + e.message);
    }

    btnProxyUpdateSub.textContent = '🔄 更新订阅';
    btnProxyUpdateSub.disabled = false;
  });

  // 初始化状态
  setTimeout(refreshProxyStatus, 1000);

  // --- IPC Listeners (Download Events) ---
  window.api.onDownloadListUpdated((list) => {
    downloadTasks = list;
    renderDownloads();
    updateActiveDownloadCount();
  });

  window.api.onDownloadProgressUpdate(({ id, progress, speed, receivedBytes }) => {
    const bar = document.getElementById(`dl-bar-${id}`);
    const speedLabel = document.getElementById(`dl-speed-${id}`);
    const statusLabel = document.getElementById(`dl-status-${id}`);
    
    if (bar) bar.style.width = `${progress}%`;
    if (speedLabel) speedLabel.textContent = speed;
    if (statusLabel) statusLabel.textContent = `下载'(${progress}%)`;
  });

  window.api.onDownloadStatusChange(({ id, status, errorMsg }) => {
    loadDownloads(); // Re-fetch all and redraw when a status completes/fails
  });

  // --- NeatDownloadManager 风格的网络底层请求嗅探监'---
  window.api.onWebviewMediaSniffed((asset) => {
    addSniffedAssets([asset]);
  });

  // --- Studio 重新激活时，应用新的握手跳转 ---
  window.api.onHandoffUpdated((h) => {
    if (h && h.searchUrl) {
      webview.src = h.searchUrl;
      addressInput.value = h.searchUrl;
      btnModeBrowser.click();
    }
  });

  // --- 新窗口打开重定向监听 ---
  window.api.onWebviewOpenUrl((data) => {
    const url = typeof data === 'string' ? data : data.url;
    const senderId = typeof data === 'string' ? null : data.senderId;
    let isMain = true;
    if (senderId) {
      try {
        isMain = (senderId === webview.getWebContentsId());
      } catch(e) {
        isMain = true;
      }
    }
    if (isMain) {
      webview.src = url;
      addressInput.value = url;
    }
  });
}

// --- Webview Listeners Setup ---
function setupWebviewListeners() {
  webview.addEventListener('did-start-loading', () => {
    btnRefresh.classList.add('loading');
  });

  webview.addEventListener('did-stop-loading', () => {
    btnRefresh.classList.remove('loading');
    addressInput.value = webview.getURL();
  });

  // Clear sniffed results of the previous screen when navigation starts or SPA navigation happens
  webview.addEventListener('did-start-navigation', () => {
    activeVideoSrc = null;
    activeVideoTitle = '';
    lastSniffedAssetsFallback = [];
    sniffedAssets = [];
    renderSniffedAssets();
  });

  webview.addEventListener('did-navigate-in-page', () => {
    activeVideoSrc = null;
    activeVideoTitle = '';
    lastSniffedAssetsFallback = [];
    sniffedAssets = [];
    renderSniffedAssets();
  });

  // 处理内嵌网页进程崩溃，进行自动重新加载
  webview.addEventListener('render-process-gone', (event) => {
    console.warn('网页渲染进程失效:', event.reason);
    if (event.reason === 'crashed' || event.reason === 'killed' || event.reason === 'oom') {
      console.log('正在重新加载网页视图...');
      webview.reload();
    }
  });

  // 处理新窗口打开事件：拦截自定义协议弹窗，并将普通网页新窗口跳转重定向在当前 Webview 中打开
  webview.addEventListener('new-window', (e) => {
    const url = e.url;
    if (!url.startsWith('http://') && !url.startsWith('https://') && !url.startsWith('file:')) {
      e.preventDefault();
      return;
    }
    e.preventDefault();
    webview.src = url;
    addressInput.value = url;
  });


  // Capture messages sent by preload-webview.js
  webview.addEventListener('ipc-message', (event) => {
    const { channel, args } = event;
    const payload = args[0];

    if (channel === 'dom-assets-scanned' || channel === 'network-media-sniffed') {
      addSniffedAssets(payload);
    }
    
    else if (channel === 'mse-segment-appended') {
      const { url, type, blobUrl } = payload;
      if (!blobToMediaUrlsMap.has(blobUrl)) {
        blobToMediaUrlsMap.set(blobUrl, { videoUrl: null, audioUrl: null, title: '' });
      }
      const entry = blobToMediaUrlsMap.get(blobUrl);
      if (type === 'video') {
        entry.videoUrl = url;
      } else if (type === 'audio') {
        entry.audioUrl = url;
      }
      
      // Limit cache size to 20 to prevent memory leak
      if (blobToMediaUrlsMap.size > 20) {
        const firstKey = blobToMediaUrlsMap.keys().next().value;
        blobToMediaUrlsMap.delete(firstKey);
      }

      if (blobUrl === activeVideoSrc) {
        updateActiveSnifferDisplay();
      }
    }
    
    else if (channel === 'video-active-changed') {
      const { src, title, currentUrl } = payload;
      activeVideoSrc = src;
      activeVideoTitle = title;
      
      if (src) {
        if (!blobToMediaUrlsMap.has(src)) {
          blobToMediaUrlsMap.set(src, { videoUrl: null, audioUrl: null, title: title });
        } else {
          blobToMediaUrlsMap.get(src).title = title;
        }
        
        // For direct HTTP playback, set the src as the videoUrl directly
        if (src.startsWith('http')) {
          blobToMediaUrlsMap.get(src).videoUrl = src;
        }
      }
      
      updateActiveSnifferDisplay();
    }
    
    else if (channel === 'kb-collect-items-synced') {
      _ingestKbCollect(payload);
    }

    else if (channel === 'hotspot-items-synced') {
      _ingestHotspot(payload);
    }
  });

  // Scraper Webview listener：采集在隐藏 webview 进行，收'热点拦截也走这里
  scraperWebview.addEventListener('ipc-message', (event) => {
    const { channel, args } = event;
    const payload = args[0];
    if (channel === 'xhs-user-posted-intercepted' ||
        channel === 'douyin-user-posted-intercepted' ||
        channel === 'zhihu-user-posted-intercepted' ||
        channel === 'bilibili-user-posted-intercepted' ||
        channel === 'youtube-user-posted-intercepted' ||
        channel === 'tiktok-user-posted-intercepted') {
      lastInterceptedNotes = payload;
    } else if (channel === 'kb-collect-items-synced') {
      _ingestKbCollect(payload);
    } else if (channel === 'hotspot-items-synced') {
      _ingestHotspot(payload);
    }
  });
}

// 收藏/点赞拦截结果入库（主 webview 与隐藏 scraperWebview 共用）
function _ingestKbCollect(payload) {
  if (!Array.isArray(payload) || payload.length === 0) return;
  let addedCount = 0;
  payload.forEach(item => {
    if (item && item.url && !allKnowledgeItems.some(e => e.url === item.url)) {
      allKnowledgeItems.push(item);
      addedCount++;
    }
  });
  if (addedCount > 0) {
    // 全局 URL 去重，防止跨批次/跨平台标签页带来的重复
    allKnowledgeItems = Array.from(new Map(allKnowledgeItems.map(i => [i.url, i])).values());
    console.log(`从拦截中同步'${addedCount} 条新收藏样本（去重后共 ${allKnowledgeItems.length} 条）`);
    renderKnowledgeBaseTable();
    try { window.api.saveKbItems(allKnowledgeItems); } catch (e) {}
  }
}

// 热点拦截结果累计
function _ingestHotspot(payload) {
  if (!Array.isArray(payload)) return;
  payload.forEach(it => {
    const key = it.platform + '|' + it.title;
    if (it.title && !hotspotItems.some(x => (x.platform + '|' + x.title) === key)) {
      hotspotItems.push(it);
    }
  });
  console.log(`热点拦截累计 ${hotspotItems.length} 条`);
}

// 收藏/点赞页：自动滚动到底，反复触发分页加载，让嗅探器收齐全部历史
let autoScrolling = false;
async function autoScrollToBottom(btn) {
  if (autoScrolling) { autoScrolling = false; return; }   // 再次点击 = 停止
  autoScrolling = true;
  const origHtml = btn ? btn.innerHTML : '';
  if (btn) btn.innerHTML = '<span>停止加载</span>';
  let lastH = 0, stable = 0, i = 0;
  const MAX = 80;        // 轮数上限（~2 分钟兜底
  const STEP_MS = 1500;  // 每轮等待加载
  try {
    while (autoScrolling && i < MAX && stable < 3) {
      const h = await webview.executeJavaScript(`(() => {
        let target = document.scrollingElement || document.documentElement;
        let maxh = target ? target.scrollHeight : 0;
        const els = document.querySelectorAll('div, main, section, ul');
        for (const e of els) {
          if (e.scrollHeight > e.clientHeight + 300 && e.scrollHeight > maxh) { maxh = e.scrollHeight; target = e; }
        }
        try { if (target && target !== document.scrollingElement) target.scrollTop = target.scrollHeight; } catch(e){}
        window.scrollTo(0, document.body.scrollHeight);
        return maxh;
      })()`).catch(() => 0);
      if (h <= lastH) stable++; else { stable = 0; lastH = h; }
      i++;
      await new Promise(r => setTimeout(r, STEP_MS));
    }
  } catch (e) { console.error('autoScroll failed', e); }
  const reachedBottom = stable >= 3;
  autoScrolling = false;
  if (btn) btn.innerHTML = origHtml;
  alert((reachedBottom ? '已加载到底部' : '已停止滚动') +
        '。\n收藏/点赞内容已尽量加载完，切到「收藏记录」模式即可查看并批量下载');
}

// 热点追踪：依次打开各平台热榜页采集，再把快照写入清单（'studio 趋势库）
const HOTSPOT_PAGES = [
  { platform: 'douyin', url: 'https://www.douyin.com/hot' },
  // { platform: 'zhihu', url: 'https://www.zhihu.com/hot' },        # 暂时隐藏
  { platform: 'xiaohongshu', url: 'https://www.xiaohongshu.com/explore' },
  { platform: 'bilibili', url: 'https://www.bilibili.com/v/popular/rank/all' },
];

function _waitWebviewLoad(timeoutMs = 9000, settleMs = 3500, wv = webview) {
  return new Promise((resolve) => {
    let done = false;
    const onStop = () => {
      if (done) return; done = true;
      wv.removeEventListener('did-stop-loading', onStop);
      setTimeout(resolve, settleMs);
    };
    wv.addEventListener('did-stop-loading', onStop);
    setTimeout(() => { if (!done) { done = true; wv.removeEventListener('did-stop-loading', onStop); resolve(); } }, timeoutMs);
  });
}

function _hotspotDomScript(platform) {
  if (platform === 'zhihu') {
    return `(() => { const out=[]; const seen=new Set();
      const push=(t,u)=>{t=(t||'').trim().replace(/^\\d+\\s*/,''); if(t&&t.length>4&&!seen.has(t)){seen.add(t); out.push({title:t,url:u||''});}};
      document.querySelectorAll('section.HotItem, .HotItem, .HotList-item, [class*="HotItem"]').forEach(el=>{
        const t=el.querySelector('.HotItem-title')||el.querySelector('h2')||el.querySelector('a');
        const a=el.querySelector('a'); if(t) push(t.textContent, a?a.href:'');
      });
      if(out.length===0){
        document.querySelectorAll('a[href*="/question/"], a[href*="/zvideo/"]').forEach(a=>push(a.textContent, a.href));
      }
      return out.slice(0,60); })()`;
  }
  if (platform === 'xiaohongshu') {
    return `(() => { const out=[]; const seen=new Set();
      document.querySelectorAll('a[href*="/explore/"], a[href*="/search_result"], .note-item').forEach(el=>{
        const t=el.querySelector('.title')||el.querySelector('span')||el;
        const title=(t.textContent||'').trim();
        const a=el.tagName==='A'?el:el.querySelector('a');
        if(title && title.length>3 && !seen.has(title)){seen.add(title); out.push({title, url:a?a.href:''});}
      });
      return out.slice(0,40); })()`;
  }
  return 'null';
}

async function captureHotspots(btn) {
  hotspotItems = [];
  const origHtml = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = '<span>采集中</span>'; }
  try {
    for (let i = 0; i < HOTSPOT_PAGES.length; i++) {
      const p = HOTSPOT_PAGES[i];
      if (btn) btn.innerHTML = `<span>采集 ${p.platform} (${i + 1}/${HOTSPOT_PAGES.length})'/span>`;
      // 用隐藏的 scraperWebview 采集，不打扰用户的「网页浏览器」
      scraperWebview.src = p.url;
      await _waitWebviewLoad(9000, 3500, scraperWebview);
      // 轻滚一下，触发懒加载的热榜接口
      try { await scraperWebview.executeJavaScript('window.scrollTo(0, 1200); true'); } catch (e) {}
      await new Promise(r => setTimeout(r, 1500));
      // API 没抓到该平台 'DOM 兜底
      const have = hotspotItems.filter(x => x.platform === p.platform).length;
      if (have === 0) {
        try {
          const domItems = await scraperWebview.executeJavaScript(_hotspotDomScript(p.platform));
          if (Array.isArray(domItems)) {
            domItems.forEach((it, idx) => {
              const key = p.platform + '|' + it.title;
              if (it.title && !hotspotItems.some(x => (x.platform + '|' + x.title) === key)) {
                hotspotItems.push({ platform: p.platform, title: it.title, rank: idx + 1, hot: '', url: it.url || '' });
              }
            });
          }
        } catch (e) {}
      }
    }
    let res = { count: 0 };
    if (hotspotItems.length > 0) {
      res = await window.api.appendHotspotManifest(hotspotItems);
    }
    if (btn) {
      btn.disabled = false; btn.innerHTML = origHtml;
      alert(`'今日热点采集完成：共 ${hotspotItems.length} 条（已写入清单）。\n` +
            `'studio「'热点追踪」点「导入最新」即可更新趋势库。\n` +
            `如某平台'0，多为该平台热榜接口结构需按真实响应微调。`);
    }
    return res;
  } catch (e) {
    if (btn) { btn.disabled = false; btn.innerHTML = origHtml; alert('热点采集出错' + e); }
    console.error('captureHotspots failed', e);
  }
}

// 「同步数据」自动打开各已登录平台的「我的收藏/点赞」页采集（被动嗅探的自动化版）
// 注：抖音/YouTube 的自身页地址较稳定；B站/小红书/知乎多需用户手动进自己的收藏页
const FAV_PAGES = {
  douyin: ['https://www.douyin.com/user/self?showTab=favorite_collection',
           'https://www.douyin.com/user/self?showTab=like'],
  youtube: ['https://www.youtube.com/playlist?list=LL',
            'https://www.youtube.com/playlist?list=WL'],
  // bilibili 需要自己的 mid，运行时解析（见下）
};

// 滚动到底加载全部分页（非交互版，供采集用
async function _loadAllByScroll(maxRounds = 30, stepMs = 1200, wv = webview) {
  let lastH = 0, stable = 0, i = 0;
  while (i < maxRounds && stable < 3) {
    let h = 0;
    try {
      h = await wv.executeJavaScript(`(() => {
        let t = document.scrollingElement || document.documentElement;
        let m = t ? t.scrollHeight : 0;
        document.querySelectorAll('div, main, section, ul').forEach(e => {
          if (e.scrollHeight > e.clientHeight + 300 && e.scrollHeight > m) { m = e.scrollHeight; t = e; }
        });
        try { if (t && t !== document.scrollingElement) t.scrollTop = t.scrollHeight; } catch (e) {}
        window.scrollTo(0, document.body.scrollHeight);
        return m;
      })()`);
    } catch (e) {}
    if (h <= lastH) stable++; else { stable = 0; lastH = h; }
    i++;
    await new Promise(r => setTimeout(r, stepMs));
  }
}

async function captureFavorites(onPhase) {
  // 用隐藏的 scraperWebview 采集，避免篡改用户正在用的「网页浏览器」
  const wv = scraperWebview;
  const wait = () => _waitWebviewLoad(9000, 3500, wv);
  const scrollAll = () => _loadAllByScroll(30, 1200, wv);

  // 组装本次要采集的页面；B站收藏夹地址需先取自己'mid
  const pages = { ...FAV_PAGES };
  if (activeLoginStatus.bilibili) {
    try {
      wv.src = 'https://www.bilibili.com';
      await wait();
      const mid = await wv.executeJavaScript(
        `fetch('https://api.bilibili.com/x/web-interface/nav',{credentials:'include'})
           .then(r=>r.json()).then(d=>(d&&d.data&&d.data.mid)?String(d.data.mid):'').catch(()=>'')`);
      if (mid) pages.bilibili = [`https://space.bilibili.com/${mid}/favlist`];
    } catch (e) { console.error('resolve bilibili mid failed', e); }
  }
  for (const [plat, urls] of Object.entries(pages)) {
    if (!activeLoginStatus[plat]) continue;
    for (const u of urls) {
      if (onPhase) onPhase(`正在采集 ${plat} 收藏/点赞（滚动加载全部）…`);
      wv.src = u;
      await wait();
      await scrollAll();   // 滚动到底，加载全部分
    }
  }

  // 知乎：收藏是「收藏夹 '夹内条目」两层。先取自己的 token '打开收藏夹列''  // 逐个进入收藏夹页（其 contents 接口会被嗅探拦截）
  if (activeLoginStatus.zhihu) {
    try {
      if (onPhase) onPhase('正在采集 知乎 收藏夹');
      wv.src = 'https://www.zhihu.com';
      await wait();
      const token = await wv.executeJavaScript(
        `fetch('https://www.zhihu.com/api/v4/me',{credentials:'include'})
           .then(r=>r.json()).then(d=>(d&&(d.url_token||d.id))?(d.url_token||d.id):'').catch(()=>'')`);
      if (token) {
        wv.src = `https://www.zhihu.com/people/${token}/collections`;
        await wait();
        await scrollAll();
        const colIds = await wv.executeJavaScript(
          `Array.from(new Set(Array.from(document.querySelectorAll('a[href*="/collection/"]'))
             .map(a => { const m = (a.getAttribute('href')||'').match(/\\/collection\\/(\\d+)/); return m ? m[1] : ''; })
             .filter(Boolean)))`);
        for (const cid of (colIds || []).slice(0, 15)) {
          if (onPhase) onPhase(`正在采集 知乎 收藏夹内容（${cid}）…`);
          wv.src = `https://www.zhihu.com/collection/${cid}`;
          await wait();
          await scrollAll();
        }
      }
    } catch (e) { console.error('zhihu capture failed', e); }
  }
}

// ── 一键收藏某个达人的全部作品 ──
// 思路：从已有条目中找到该创作者的主页 URL，切到浏览器模式后自动滚动采集。
// 浏览器里的嗅探拦截 (preload-webview.js) 会把新内容追加到 allKnowledgeItems。
async function collectAllFromCreator() {
  const creatorName = kbCreatorFilter ? kbCreatorFilter.value : 'all';
  if (!creatorName || creatorName === 'all') {
    alert('请先在「创作者筛选」中选定一个创作者。');
    return;
  }

  // 优先从已有条目里取 creatorHomepageUrl；否则尝试从视频 URL 反推主页
  const creatorItems = allKnowledgeItems.filter(it => it.creatorName === creatorName);
  let profileUrl = null;
  for (const it of creatorItems) {
    if (it.creatorHomepageUrl) { profileUrl = it.creatorHomepageUrl; break; }
  }
  // 若无主页 URL，按平台从视频 URL 推导
  if (!profileUrl && creatorItems.length > 0) {
    const sample = creatorItems[0];
    const u = sample.url || '';
    const plat = sample.platform || '';
    if (plat === 'bilibili' || u.includes('bilibili.com/video/')) {
      // B站：视频页 URL 中无法直接得到 mid，先进 UP 主的空间页搜索
      profileUrl = `https://search.bilibili.com/upuser?keyword=${encodeURIComponent(creatorName)}`;
    } else if (plat === 'douyin' || u.includes('douyin.com')) {
      profileUrl = `https://www.douyin.com/search/${encodeURIComponent(creatorName)}?type=user`;
    } else if (plat === 'xiaohongshu' || u.includes('xiaohongshu.com')) {
      profileUrl = `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(creatorName)}&source=web_search_result_notes&type=user`;
    } else if (plat === 'zhihu' || u.includes('zhihu.com')) {
      profileUrl = `https://www.zhihu.com/search?type=people&q=${encodeURIComponent(creatorName)}`;
    } else if (plat === 'youtube' || u.includes('youtube.com')) {
      profileUrl = `https://www.youtube.com/results?search_query=${encodeURIComponent(creatorName)}&sp=EgIQAg%3D%3D`;
    } else {
      profileUrl = `https://www.douyin.com/search/${encodeURIComponent(creatorName)}?type=user`;
    }
  }

  if (!profileUrl) {
    alert(`未能确定「${creatorName}」的主页地址。请手动在浏览器中打开其主页后，点工具栏「⬇️ 自动加载到底」。`);
    return;
  }

  const confirmed = confirm(
    `即将前往「${creatorName}」主页：\n${profileUrl}\n\n打开后会自动滚动到底加载全部内容。` +
    `\n如果跳转到搜索页，请手动点击该创作者的主页后再点「⬇️ 自动加载到底」。\n\n确认前往？`
  );
  if (!confirmed) return;

  // 切换到浏览器模式，导航到达人主页
  btnModeBrowser.click();
  webview.src = profileUrl;
  addressInput.value = profileUrl;

  // 等页面加载后自动滚动
  const btnAutoScroll = document.getElementById('btn-auto-scroll');
  await _waitWebviewLoad(10000, 4000);
  autoScrollToBottom(btnAutoScroll);
}

// Add scanned assets with duplicate checks (NeatDownloadManager style)
function addSniffedAssets(assets) {
  let added = false;
  const pageUrl = webview.getURL() || '';

  assets.forEach(asset => {
    const cleanUrl = getCleanUrlForComparison(asset.url);
    
    // Check if this URL is already in our map
    let associated = false;
    for (let [key, entry] of blobToMediaUrlsMap.entries()) {
      if (entry.videoUrl && getCleanUrlForComparison(entry.videoUrl) === cleanUrl) {
        associated = true;
        // Merge size if not already present
        if (asset.size > 0 && !entry.videoSize) {
          entry.videoSize = asset.size;
          added = true;
        }
        break;
      }
      if (entry.audioUrl && getCleanUrlForComparison(entry.audioUrl) === cleanUrl) {
        associated = true;
        // Merge size if not already present
        if (asset.size > 0 && !entry.audioSize) {
          entry.audioSize = asset.size;
          added = true;
        }
        break;
      }
    }
    
    // If not associated with any video blob, we can associate it with the active video if the active video is missing that track!
    if (!associated && activeVideoSrc) {
      if (!blobToMediaUrlsMap.has(activeVideoSrc)) {
        blobToMediaUrlsMap.set(activeVideoSrc, { videoUrl: null, audioUrl: null, title: activeVideoTitle });
      }
      const entry = blobToMediaUrlsMap.get(activeVideoSrc);
      if (asset.type === 'video' && !entry.videoUrl) {
        entry.videoUrl = asset.url;
        entry.videoSize = asset.size || 0;
        associated = true;
        added = true;
      } else if (asset.type === 'audio' && !entry.audioUrl) {
        entry.audioUrl = asset.url;
        entry.audioSize = asset.size || 0;
        associated = true;
        added = true;
      }
    }
    
    // Also add to fallback list, merging size updates if needed
    const existingIdx = lastSniffedAssetsFallback.findIndex(a => getCleanUrlForComparison(a.url) === cleanUrl);
    if (existingIdx !== -1) {
      const existingAsset = lastSniffedAssetsFallback[existingIdx];
      if (asset.size > 0 && !existingAsset.size) {
        existingAsset.size = asset.size;
        existingAsset.sizeText = asset.sizeText;
        added = true;
      }
    } else {
      asset.pageUrl = pageUrl;
      lastSniffedAssetsFallback.push(asset);
      added = true;
    }
  });
  
  if (added) {
    updateActiveSnifferDisplay();
  }
}

function updateActiveSnifferDisplay() {
  if (activeVideoSrc && blobToMediaUrlsMap.has(activeVideoSrc)) {
    const entry = blobToMediaUrlsMap.get(activeVideoSrc);
    if (entry.videoUrl || entry.audioUrl) {
      const assets = [];
      const title = entry.title || activeVideoTitle || '视频素材';
      
      if (entry.videoUrl && entry.audioUrl) {
        const totalSize = (entry.videoSize || 0) + (entry.audioSize || 0);
        assets.push({
          url: entry.videoUrl,
          videoUrl: entry.videoUrl,
          audioUrl: entry.audioUrl,
          type: 'combined',
          name: `${title}.mp4`,
          sizeText: totalSize > 0 ? `${formatBytes(totalSize)}` : '视频 + 音频底层合并',
          size: totalSize
        });
      } else if (entry.videoUrl) {
        assets.push({
          url: entry.videoUrl,
          videoUrl: entry.videoUrl,
          type: 'video',
          name: `${title}.mp4`,
          sizeText: entry.videoSize > 0 ? `${formatBytes(entry.videoSize)}` : '仅视',
          size: entry.videoSize || 0
        });
      } else if (entry.audioUrl) {
        assets.push({
          url: entry.audioUrl,
          audioUrl: entry.audioUrl,
          type: 'audio',
          name: `${title}.mp3`,
          sizeText: entry.audioSize > 0 ? `${formatBytes(entry.audioSize)}` : '仅音',
          size: entry.audioSize || 0
        });
      }
      
      sniffedAssets = assets;
      renderSniffedAssets();
      return;
    }
  }
  
  // Fallback: render the fallback list (only if we don't have active video streams)
  const pageUrl = webview.getURL() || '';
  const filteredFallback = lastSniffedAssetsFallback.filter(a => a.pageUrl === pageUrl);
  
  // Group audio and video in the fallback list
  const grouped = [];
  const m4sStreams = [];
  
  filteredFallback.forEach(asset => {
    if (asset.type === 'video' || asset.type === 'audio') {
      let paired = false;
      for (let i = 0; i < grouped.length; i++) {
        let existing = grouped[i];
        if (asset.type === 'video' && existing.type === 'audio') {
          existing.type = 'combined';
          existing.videoUrl = asset.url;
          existing.audioUrl = existing.url;
          existing.url = asset.url;
          existing.name = asset.name;
          const totalSize = (asset.size || 0) + (existing.size || 0);
          existing.sizeText = totalSize > 0 ? `${formatBytes(totalSize)}` : '视频 + 音频底层合并';
          existing.size = totalSize;
          paired = true;
          break;
        } else if (asset.type === 'audio' && existing.type === 'video') {
          existing.type = 'combined';
          existing.videoUrl = existing.url;
          existing.audioUrl = asset.url;
          const totalSize = (existing.size || 0) + (asset.size || 0);
          existing.sizeText = totalSize > 0 ? `${formatBytes(totalSize)}` : '视频 + 音频底层合并';
          existing.size = totalSize;
          paired = true;
          break;
        }
      }
      if (!paired) {
        if (asset.url.toLowerCase().includes('.m4s') || asset.name.toLowerCase().includes('.m4s') || asset.url.toLowerCase().includes('videoplayback') || asset.url.toLowerCase().includes('video/tos') || asset.url.toLowerCase().includes('video_')) {
          m4sStreams.push(asset);
        } else {
          if (asset.type === 'video') asset.videoUrl = asset.url;
          if (asset.type === 'audio') asset.audioUrl = asset.url;
          asset.sizeText = asset.size > 0 ? `${formatBytes(asset.size)}` : (asset.type === 'video' ? '仅视' : '仅音');
          grouped.push(asset);
        }
      }
    } else {
      asset.sizeText = asset.sizeText || (asset.size > 0 ? `${formatBytes(asset.size)}` : '未知大小');
      grouped.push(asset);
    }
  });

  // If we have remaining unpaired m4s/DASH streams, and we have exactly two, pair them!
  if (m4sStreams.length === 2) {
    const asset1 = m4sStreams[0];
    const asset2 = m4sStreams[1];
    const title = activeVideoTitle || '视频素材';
    const totalSize = (asset1.size || 0) + (asset2.size || 0);
    
    grouped.push({
      url: asset1.url,
      videoUrl: asset1.url,
      audioUrl: asset2.url,
      type: 'combined',
      name: `${title}.mp4`,
      sizeText: totalSize > 0 ? `${formatBytes(totalSize)}` : '视频 + 音频自动合并 (流探测)',
      size: totalSize
    });
  } else {
    m4sStreams.forEach(asset => {
      if (asset.type === 'video') asset.videoUrl = asset.url;
      if (asset.type === 'audio') asset.audioUrl = asset.url;
      asset.sizeText = asset.size > 0 ? `${formatBytes(asset.size)}` : (asset.type === 'video' ? '仅视' : '仅音');
      grouped.push(asset);
    });
  }
  
  sniffedAssets = grouped;
  renderSniffedAssets();
}

// 移除分片参数（如 range, rn 等），用于提取媒体唯一标识防重
function getCleanUrlForComparison(url) {
  try {
    const parsed = new URL(url);
    parsed.searchParams.delete('range');
    parsed.searchParams.delete('rn');
    parsed.searchParams.delete('obuf');
    parsed.searchParams.delete('start');
    parsed.searchParams.delete('end');
    parsed.searchParams.delete('deadline');
    return parsed.origin + parsed.pathname;
  } catch (e) {
    return url;
  }
}

function renderSniffedAssets() {
  sniffedCountDisplay.textContent = sniffedAssets.length;

  if (sniffedAssets.length === 0) {
    _lastSniffSig = '';
    snifferEmpty.style.display = 'flex';
    snifferGrid.style.display = 'none';
    snifferGrid.innerHTML = '';
    return;
  }

  // 列表内容未变化则不重建（嗅探'1-2 秒触发一次，重建会清掉勾选）
  const sig = sniffedAssets.length + '|' + sniffedAssets.map(a => a.url).join(',');
  if (sig === _lastSniffSig && snifferGrid.children.length) {
    return;
  }
  _lastSniffSig = sig;

  snifferEmpty.style.display = 'none';
  snifferGrid.style.display = 'grid';

  snifferGrid.innerHTML = '';
  sniffedAssets.forEach((asset, idx) => {
    const card = document.createElement('div');
    card.className = 'sniffed-card';
    
    // Double click to download immediately
    card.addEventListener('dblclick', async () => {
      const id = 'dl-' + Date.now() + '-' + Math.random().toString(36).substring(2, 7);
      document.querySelector('.tab-btn[data-tab="tab-downloads"]').click();
      await window.api.startDownload({
        id,
        url: asset.url,
        audioUrl: asset.type === 'combined' ? asset.audioUrl : null,
        filename: asset.name,
        referer: webview.src
      });
    });

    let previewHtml = '';
    if (asset.type === 'image') {
      previewHtml = `<img class="sniffed-preview" src="${asset.url}" loading="lazy" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22%23475569%22><path d=%22M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z%22/></svg>'">`;
    } else {
      // Video/Audio placeholder icon
      previewHtml = `
        <div class="sniffed-preview" style="display:flex;align-items:center;justify-content:center;background:#1e293b;">
          <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--color-primary);"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
        </div>
      `;
    }

    let typeIconHtml = '';
    if (asset.type === 'video') {
      typeIconHtml = `
        <div class="sniffed-video-icon">
          <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
        </div>
      `;
    }

    card.innerHTML = `
      <div class="sniffed-checkbox-wrap">
        <input type="checkbox" class="sniffed-item-check" data-index="${idx}">
      </div>
      ${previewHtml}
      ${typeIconHtml}
      <div class="sniffed-info">
        <div class="sniffed-title" title="${asset.name}">${asset.name}</div>
        <div class="sniffed-size">${asset.sizeText}</div>
      </div>
    `;

    // 勾选状态跨重渲染保留：selectedSniffUrls 恢复，change 时同步
    const cb = card.querySelector('.sniffed-item-check');
    if (cb) {
      cb.checked = selectedSniffUrls.has(asset.url);
      cb.addEventListener('change', () => {
        if (cb.checked) selectedSniffUrls.add(asset.url);
        else selectedSniffUrls.delete(asset.url);
      });
      // 点击整行复选框区域更易点中
      const wrap = card.querySelector('.sniffed-checkbox-wrap');
      if (wrap) wrap.addEventListener('click', (e) => {
        if (e.target !== cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
      });
    }
    snifferGrid.appendChild(card);
  });
}

// Helper formats
function formatBytes(bytes, decimals = 2) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// ----------------------------------------------------
// 以下为知识库相关核心功能与逻辑
// ----------------------------------------------------

// 保存上次拦截到的创作者动
let lastInterceptedNotes = null;

// 检查最近两天发布的辅助函数
function isWithinTwoDays(dateStr, timestamp) {
  // 如果有原生时间戳，优先使用时间戳判断，防 locale/系统格式引起的解析失
  if (timestamp) {
    const ms = timestamp < 10000000000 ? timestamp * 1000 : timestamp;
    const diffHours = (Date.now() - ms) / (1000 * 60 * 60);
    return diffHours <= 60; // 48小时 + 12小时缓冲
  }

  if (!dateStr) return false;
  dateStr = dateStr.trim().toLowerCase();
  
  // 相对时间直接放行
  if (/刚刚|秒前|分钟|小时|hour|minute|second|just now/.test(dateStr)) {
    return true;
  }
  if (/昨天|yesterday|1 day/.test(dateStr)) {
    return true;
  }
  if (/前天|2 days/.test(dateStr)) {
    return true;
  }
  if (/最近/.test(dateStr)) {
    return true;
  }
  if (/天前/.test(dateStr)) {
    const dayMatch = dateStr.match(/(\d+)\s*天前/);
    if (dayMatch) {
      const days = parseInt(dayMatch[1], 10);
      return days <= 2;
    }
  }

  // 绝对日期解析
  dateStr = dateStr.replace(/发布于|编辑于|发表/g, '').trim();
  
  // 部分日期只有'6-10 15:30”，补齐年份
  let hasYear = /\d{4}/.test(dateStr);
  let parseStr = dateStr;
  if (!hasYear) {
    const currentYear = new Date().getFullYear();
    parseStr = `${currentYear}-${dateStr}`;
  }
  
  // "-" 换成 "/" 保证在各系统 Date.parse() 下解析的兼容性
  const parsedMs = Date.parse(parseStr.replace(/-/g, '/'));
  if (isNaN(parsedMs)) {
    return false;
  }
  
  const now = Date.now();
  const diffHours = (now - parsedMs) / (1000 * 60 * 60);
  return diffHours <= 60; // 48小时 + 12小时时区缓冲
}

// 检查已登录频道
async function checkLoginStatus() {
  try {
    activeLoginStatus = await window.api.checkLoginStatus();
    renderLoginStatusBadges();
  } catch (err) {
    console.error('更新登录状态失败', err);
  }
}

// 渲染登录徽章列表
function renderLoginStatusBadges() {
  loginStatusContainer.innerHTML = '';
  const platforms = [
    { id: 'bilibili', name: 'B站' },
    { id: 'xiaohongshu', name: '小红书' },
    { id: 'douyin', name: '抖音' },
    { id: 'youtube', name: 'YouTube' },
    // { id: 'zhihu', name: '知乎' },          # 暂时隐藏
    { id: 'tiktok', name: 'TikTok' },
  ];
  
  platforms.forEach(p => {
    const loggedIn = !!activeLoginStatus[p.id];
    const badge = document.createElement('span');
    badge.style.padding = '3px 8px';
    badge.style.borderRadius = '12px';
    badge.style.fontSize = '0.72rem';
    badge.style.fontWeight = '600';
    badge.style.border = '1px solid';
    
    if (loggedIn) {
      badge.style.backgroundColor = 'rgba(16, 185, 129, 0.1)';
      badge.style.borderColor = 'rgba(16, 185, 129, 0.3)';
      badge.style.color = '#34d399';
      badge.textContent = `${p.name}: 已登录`;
    } else {
      badge.style.backgroundColor = 'rgba(239, 68, 68, 0.05)';
      badge.style.borderColor = 'rgba(239, 68, 68, 0.15)';
      badge.style.color = '#f87171';
      badge.textContent = `${p.name}: 未登录`;
    }
    loginStatusContainer.appendChild(badge);
  });
}

// 知识库创作者更新同步主任务
async function syncKnowledgeBase() {
  kbLoadingOverlay.style.display = 'flex';
  kbEmptyState.style.display = 'none';
  kbTable.style.display = 'none';
  kbSyncProgressBar.style.width = '0%';
  kbLoadingText.textContent = '正在检测已登录频道...';
  
  // 只保留已有的收藏样本，清除之前同步到的创作者更新内'  allKnowledgeItems = allKnowledgeItems.filter(item => !!item.isCollected);
  
  await checkLoginStatus();

  try {
    await captureFavorites((m) => { kbLoadingText.textContent = m; });
    // 保存前去重
    allKnowledgeItems = Array.from(new Map(allKnowledgeItems.map(i => [i.url, i])).values());
    try { window.api.saveKbItems(allKnowledgeItems); } catch (e) {}
  } catch (e) { console.error('captureFavorites failed', e); }

  kbSyncProgressBar.style.width = '100%';
  setTimeout(() => {
    kbLoadingOverlay.style.display = 'none';
    if (allKnowledgeItems.length > 0) {
      kbEmptyState.style.display = 'none';
      renderKnowledgeBaseTable();
    } else {
      kbEmptyState.style.display = 'flex';
      const pn = { bilibili: 'B站', xiaohongshu: '小红书', douyin: '抖音', tiktok: 'TikTok' };
      const loggedIn = Object.keys(activeLoginStatus || {}).filter(k => activeLoginStatus[k]).map(k => pn[k] || k);
      const loginLine = loggedIn.length
        ? `<p style="color:#34d399;font-weight:bold;">✅ 已登录：${loggedIn.join('、')}</p>`
        : `<p style="color:#f87171;font-weight:bold;">⚠️ 未检测到任何已登录平台，请先在左侧平台登录。</p>`;
      kbEmptyState.innerHTML = `
        <div style="text-align: left; padding: 10px 20px; line-height: 1.6;">
          ${loginLine}
          <p style="color: var(--text-secondary);">进入你的「我的收藏 / 点赞」页，点工具栏「⬇️ 自动加载到底」，样本会自动出现在这里，可直接批量下载。</p>
        </div>
      `;
    }
    // 再次去重后保存（保险）
    allKnowledgeItems = Array.from(new Map(allKnowledgeItems.map(i => [i.url, i])).values());
    try { window.api.saveKbItems(allKnowledgeItems); } catch (e) {}
  }, 500);
}


// 把 "1.2万赞" / "8000" 解析成数字（排序回退用）
function _parseCount(s) {
  if (typeof s === 'number') return s;
  if (!s) return 0;
  const m = String(s).match(/([\d.]+)\s*(万|w|亿|k|千)?/i);
  if (!m) return 0;
  let n = parseFloat(m[1]) || 0;
  const u = (m[2] || '').toLowerCase();
  if (u === '万' || u === 'w') n *= 10000;
  else if (u === '亿') n *= 1e8;
  else if (u === '千' || u === 'k') n *= 1000;
  return n;
}

// 取某条的排序指标（发布时间/点赞/播放/评论/收藏/转发）
function _metric(item, key) {
  if (key === 'date') return item.timestamp || 0;
  const st = item.stats || {};
  if (st[key] != null) return Number(st[key]) || 0;
  if (key === 'like' || key === 'play') return _parseCount(item.heat);
  return 0;
}

// 按当前平台刷新下拉选项（保留已选）
function _syncCreatorFilterOptions() {
  if (!kbCreatorFilter) return;
  const platformVal = kbPlatformFilter.value;
  const cur = kbCreatorFilter.value;
  const names = Array.from(new Set(allKnowledgeItems
    .filter(it => platformVal === 'all' || it.platform === platformVal)
    .map(it => it.creatorName).filter(Boolean))).sort();
  kbCreatorFilter.innerHTML = '<option value="all">所有创作者</option>' +
    names.map(n => `<option value="${n.replace(/"/g, '&quot;')}">${n}</option>`).join('');
  if (cur && names.includes(cur)) kbCreatorFilter.value = cur;
}

// 过滤和渲染表
function renderKnowledgeBaseTable() {
  _syncCreatorFilterOptions();
  kbTableBody.innerHTML = '';
  kbSelectAll.checked = false;

  const searchVal = kbSearchInput.value.trim().toLowerCase();
  const platformVal = kbPlatformFilter.value;
  const typeVal = kbTypeFilter.value;
  const creatorVal = kbCreatorFilter ? kbCreatorFilter.value : 'all';
  const sortKey = kbSort ? kbSort.value : 'date';

  // 唯一排重（根据链接判断）
  const uniqueItems = Array.from(new Map(allKnowledgeItems.map(item => [item.url, item])).values());

  let filtered = uniqueItems.filter(item => {
    const matchSearch = !searchVal ||
      (item.title || '').toLowerCase().includes(searchVal) ||
      (item.creatorName || '').toLowerCase().includes(searchVal);

    const matchPlatform = platformVal === 'all' || item.platform === platformVal;
    const matchType = typeVal === 'all' || item.type === typeVal;
    const matchCreator = creatorVal === 'all' || item.creatorName === creatorVal;

    return matchSearch && matchPlatform && matchType && matchCreator;
  });
  // 排序（降序）
  filtered.sort((a, b) => _metric(b, sortKey) - _metric(a, sortKey));

  const total = filtered.length;
  kbTotalCount.textContent = total;

  // 分页（每 KB_PAGE_SIZE 条，避免一次性插入过多行 + 提供翻页）
  const totalPages = Math.max(1, Math.ceil(total / KB_PAGE_SIZE));
  if (kbPage > totalPages) kbPage = totalPages;
  if (kbPage < 1) kbPage = 1;
  const pageStart = (kbPage - 1) * KB_PAGE_SIZE;
  filtered = filtered.slice(pageStart, pageStart + KB_PAGE_SIZE);
  if (kbPagination) {
    kbPagination.style.display = total > KB_PAGE_SIZE ? 'flex' : 'none';
    if (kbPageInfo) kbPageInfo.textContent = `'${kbPage} / ${totalPages} 页（'${total} 条）`;
    if (kbPrevBtn) kbPrevBtn.disabled = kbPage <= 1;
    if (kbNextBtn) kbNextBtn.disabled = kbPage >= totalPages;
  }
  updateKbSelectedCount();
  
  if (filtered.length === 0) {
    kbEmptyState.style.display = 'flex';
    kbEmptyState.textContent = '暂无满足条件的更新内';
    kbTable.style.display = 'none';
    return;
  }
  
  kbEmptyState.style.display = 'none';
  kbTable.style.display = 'table';
  
  filtered.forEach((item, idx) => {
    const tr = document.createElement('tr');
    tr.className = 'kb-row';
    
    let platformLabel = '其它';
    if (item.platform === 'bilibili') platformLabel = 'B';
    else if (item.platform === 'xiaohongshu') platformLabel = '小红';
    else if (item.platform === 'douyin') platformLabel = '抖音';
    else if (item.platform === 'youtube') platformLabel = 'YouTube';
    else if (item.platform === 'zhihu') platformLabel = '知乎';
    
    const typeLabel = item.type === 'video' ? '视频' : '文章/图片';
    const typeClass = item.type === 'video' ? 'video' : 'image';
    const collectBadge = item.isLiked
      ? `<span class="kb-badge collect">点赞</span>`
      : (item.isCollected ? `<span class="kb-badge collect">收藏</span>` : '');
    
    tr.innerHTML = `
      <td style="text-align: center;"><input type="checkbox" class="kb-item-check" data-index="${idx}" style="cursor: pointer;"></td>
      <td>
        <img class="kb-cover-img" loading="lazy" decoding="async" src="${item.cover || 'avatar-placeholder.png'}" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22%231e293b%22><rect width=%22100%25%22 height=%22100%25%22/><path d=%22M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z%22 fill=%22%23475569%22/></svg>'">
      </td>
      <td>
        <div class="kb-creator-wrap">
          <img class="kb-creator-avatar" loading="lazy" decoding="async" src="${item.creatorAvatar || ''}" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22%2364748b%22><circle cx=%2212%22 cy=%228%22 r=%224%22/><path d=%22M12 14c-6.1 0-8 4-8 4v2h16v-2s-1.9-4-8-4z%22/></svg>'">
          <div style="display:flex; flex-direction:column; gap:3px; overflow:hidden;">
            <span class="kb-creator-name" title="${item.creatorName}">${item.creatorName}</span>
            <span class="kb-badge-platform ${item.platform}">${platformLabel}</span>
          </div>
        </div>
      </td>
      <td>
        <a class="kb-title-link" title="${item.title}">${item.title}</a>
        <span class="kb-post-url" title="${item.url}">${item.url}</span>
      </td>
      <td style="text-align: center;">
        <span class="kb-badge ${typeClass}">${typeLabel}</span>
        ${collectBadge}
      </td>
      <td style="text-align: center; color: var(--text-secondary); font-weight: 600;">
        ${item.heat || '--'}
      </td>
      <td style="text-align: center; color: var(--text-muted);">
        ${item.date}
      </td>
    `;
    
    // 点击链接切换回浏览器加载
    const titleLink = tr.querySelector('.kb-title-link');
    titleLink.addEventListener('click', () => {
      btnModeBrowser.click();
      webview.src = item.url;
      addressInput.value = item.url;
    });
    
    const checkbox = tr.querySelector('.kb-item-check');
    checkbox.addEventListener('change', updateKbSelectedCount);
    checkbox._itemData = item;
    
    kbTableBody.appendChild(tr);
  });
}

// 更新已选计
function updateKbSelectedCount() {
  const checked = document.querySelectorAll('.kb-item-check:checked').length;
  kbSelectedCount.textContent = checked;
  
  const allCheckBoxes = document.querySelectorAll('.kb-item-check');
  if (allCheckBoxes.length > 0) {
    kbSelectAll.checked = checked === allCheckBoxes.length;
  } else {
    kbSelectAll.checked = false;
  }
}

// 核心：单条知识库项目的归档下载与详情解析写入
async function downloadKnowledgeBaseItem(item, subDir) {
  const cleanTitle = item.title.replace(/[\\/:*?"<>|\r\n\t]/g, '_').trim();
  let platformPrefix = '';
  if (item.platform === 'bilibili') platformPrefix = 'B';
  else if (item.platform === 'xiaohongshu') platformPrefix = '小红';
  else if (item.platform === 'douyin') platformPrefix = '抖音';
  else if (item.platform === 'youtube') platformPrefix = 'YouTube';
  else if (item.platform === 'zhihu') platformPrefix = '知乎';
  else if (item.platform === 'tiktok') platformPrefix = 'TikTok';
  
  const filePrefix = `[${platformPrefix}] [${item.creatorName}] ${cleanTitle}`;
  
  // 1. 视频类型：下载视频 + 封面图片 + 详情元数据
  // 知乎平台始终使用图文归档方式（知乎主要为图文/文章内容）
  if (item.type === 'video' && item.platform !== 'zhihu') {
    const dlId = 'dl-kb-' + Date.now() + '-' + Math.random().toString(36).substring(2, 7);
    await window.api.startDownload({
      id: dlId,
      url: item.url,
      filename: `${filePrefix}.mp4`,
      referer: item.url,
      subDir: subDir,
      useYtdlp: true
    });
    
    if (item.cover) {
      const coverId = 'dl-kb-cover-' + Date.now() + '-' + Math.random().toString(36).substring(2, 7);
      await window.api.startDownload({
        id: coverId,
        url: item.cover,
        filename: `${filePrefix}_cover.jpg`,
        referer: item.url,
        subDir: subDir
      });
    }
    
    const metaText = `标题: ${item.title}\n作' ${item.creatorName}\n平台: ${platformPrefix}\n链接: ${item.url}\n发布时间: ${item.date}\n数据热度: ${item.heat || ''}\n下载时间: ${new Date().toLocaleString()}\n`;
    await window.api.saveTextFile({
      filename: `${filePrefix}_info.txt`,
      content: metaText,
      subDir: subDir
    });

    // studio 集成：写入「我的知识库」样本清单（视频
    try {
      const base = currentSettings && currentSettings.downloadPath ? currentSettings.downloadPath : '';
      await window.api.appendKbManifest({
        platform: item.platform, platformName: platformPrefix,
        creatorName: item.creatorName, title: item.title, caption: '',
        url: item.url, date: item.date, heat: item.heat || '',
        type: 'video',
        mediaPath: base ? `${base}/${subDir}/${filePrefix}.mp4` : '',
        isCollected: !!item.isCollected,
        isLiked: !!item.isLiked
      });
    } catch (e) { console.error('appendKbManifest(video) failed', e); }

    return;
  }
  
  // 2. 图文/文章类型：静默解析图文详（知乎统一走此路径）
  if (item.type === 'image' || item.platform === 'zhihu') {
    try {
      scraperWebview.src = item.url;
      
      // 等待详情页面完全加载渲染
      await new Promise((resolve) => {
        let resolved = false;
        const onStopLoading = () => {
          if (!resolved) {
            resolved = true;
            scraperWebview.removeEventListener('did-stop-loading', onStopLoading);
            setTimeout(resolve, 3500); // 留出 3.5 秒渲
          }
        };
        scraperWebview.addEventListener('did-stop-loading', onStopLoading);
        
        setTimeout(() => {
          if (!resolved) {
            resolved = true;
            scraperWebview.removeEventListener('did-stop-loading', onStopLoading);
            resolve();
          }
        }, 7500);
      });
      
      let detailScript = '';
      if (item.platform === 'xiaohongshu') {
        detailScript = `(() => {
          const imgUrls = [];
          document.querySelectorAll('.media-container img, .image-container img, .slider-item img, .note-container img, .slide-item img').forEach(img => {
            if (img.src && !img.src.startsWith('data:') && !img.src.startsWith('blob:')) {
              imgUrls.push(img.src);
            }
          });
          if (imgUrls.length === 0) {
            document.querySelectorAll('meta[property="og:image"]').forEach(meta => {
              if (meta.content) imgUrls.push(meta.content);
            });
          }
          const uniqueImgs = Array.from(new Set(imgUrls));
          
          const titleEl = document.querySelector('.title') || document.querySelector('h1') || document.querySelector('.note-container .title');
          const descEl = document.querySelector('.desc') || document.querySelector('.note-container .desc') || document.querySelector('.note-text');
          return {
            images: uniqueImgs,
            title: titleEl ? titleEl.textContent.trim() : '',
            desc: descEl ? descEl.textContent.trim() : ''
          };
        })()`;
      } else if (item.platform === 'zhihu') {
        detailScript = `(() => {
          const titleEl = document.querySelector('.Post-title') || document.querySelector('.QuestionHeader-title') || document.querySelector('h1');
          const contentEl = document.querySelector('.Post-RichText') || document.querySelector('.AnswerCard .RichText') || document.querySelector('.ContentItem-richText');
          return {
            title: titleEl ? titleEl.textContent.trim() : '',
            html: contentEl ? contentEl.innerHTML : '',
            text: contentEl ? contentEl.textContent.trim() : ''
          };
        })()`;
      }
      
      let captionText = '';
      if (detailScript) {
        const details = await scraperWebview.executeJavaScript(detailScript);
        if (item.platform === 'xiaohongshu') {
          // 保存小红书正文描述文
          const noteDesc = `标题: ${item.title}\n作' ${item.creatorName}\n发布时间: ${item.date}\n点赞数据: ${item.heat || ''}\n链接: ${item.url}\n\n内容详情描述:\n${details.desc || ''}\n`;
          await window.api.saveTextFile({
            filename: `${filePrefix}.txt`,
            content: noteDesc,
            subDir: subDir
          });
          captionText = details.desc || '';

          // 批量下载所有配
          if (details.images && details.images.length > 0) {
            details.images.forEach((imgUrl, idx) => {
              const dlId = 'dl-xhs-img-' + Date.now() + '-' + Math.random().toString(36).substring(2, 7);
              window.api.startDownload({
                id: dlId,
                url: imgUrl,
                filename: `${filePrefix}_${idx + 1}.jpg`,
                referer: item.url,
                subDir: subDir
              });
            });
          }
        } else if (item.platform === 'zhihu') {
          // 将知乎正文包装为精美模板并存储为离线 HTML
          const articleHtml = `
          <!DOCTYPE html>
          <html>
          <head>
            <meta charset="utf-8">
            <title>${cleanTitle}</title>
            <style>
              body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #f8fafc; background-color: #0b0f19; }
              h1 { border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 12px; font-size: 1.8em; }
              .meta { color: #94a3b8; font-size: 0.9em; margin-bottom: 20px; }
              .meta a { color: #6366f1; text-decoration: none; }
              .content { font-size: 1.05em; line-height: 1.8; }
              img { max-width: 100%; height: auto; display: block; margin: 20px 0; border-radius: 6px; border: 1px solid rgba(255,255,255,0.08); }
              blockquote { border-left: 4px solid #6366f1; padding-left: 16px; color: #94a3b8; margin: 20px 0; }
              pre { background-color: #121826; padding: 15px; border-radius: 6px; overflow-x: auto; border: 1px solid rgba(255,255,255,0.08); }
            </style>
          </head>
          <body>
            <h1>${item.title}</h1>
            <div class="meta">作' ${item.creatorName} | 平台: 知乎 | 来源: <a href="${item.url}" target="_blank">${item.url}</a> | 发布时间: ${item.date} | 获赞: ${item.heat || ''}</div>
            <div class="content">${details.html || ''}</div>
          </body>
          </html>
          `;
          
          await window.api.saveTextFile({
            filename: `${filePrefix}.html`,
            content: articleHtml,
            subDir: subDir
          });
          captionText = details.text || '';
        }
      }

      // studio 集成：写入「我的知识库」样本清单（图文/文章
      try {
        await window.api.appendKbManifest({
          platform: item.platform, platformName: platformPrefix,
          creatorName: item.creatorName, title: item.title, caption: captionText,
          url: item.url, date: item.date, heat: item.heat || '',
          type: 'image', mediaPath: '',
          isCollected: !!item.isCollected,
          isLiked: !!item.isLiked
        });
      } catch (e) { console.error('appendKbManifest(article) failed', e); }
    } catch (scrapeErr) {
      console.error(`归档详情提取遇到问题 ${item.url}:`, scrapeErr);
    }
  }
}

// ----------------------------------------------------
// 以下为本地素材浏览器相关核心功能与逻辑
// ----------------------------------------------------

function updateMaterialsSelectedCount() {
  if (materialsSelectedCount) {
    materialsSelectedCount.textContent = String(selectedMaterialPaths.size);
  }
}

function updateMaterialsSelectionUI() {
  document.querySelectorAll('.material-file-card').forEach((card) => {
    const p = card.dataset.path;
    const checked = !!p && selectedMaterialPaths.has(p);
    card.classList.toggle('selected', checked);
    const cb = card.querySelector('.material-item-check');
    if (cb) cb.checked = checked;
  });
  updateMaterialsSelectedCount();
}

function getFilteredDailyMaterials() {
  const query = (materialsSearchInput?.value || '').trim().toLowerCase();
  const typeVal = materialsTypeFilter?.value || 'all';
  const dateVal = materialsDateFilter?.value || 'all';
  const sortVal = materialsSort?.value || 'date_desc';

  const out = [];
  allDailyMaterials.forEach((group) => {
    if (dateVal !== 'all' && group.date !== dateVal) return;
    const files = (group.files || []).filter((file) => {
      if (typeVal !== 'all' && file.type !== typeVal) return false;
      if (!query) return true;
      const name = (file.name || '').toLowerCase();
      const p = (file.path || '').toLowerCase();
      return name.includes(query) || p.includes(query);
    });

    files.sort((a, b) => {
      const aName = (a.name || '').toLowerCase();
      const bName = (b.name || '').toLowerCase();
      if (sortVal === 'size_desc') return (b.size || 0) - (a.size || 0) || aName.localeCompare(bName);
      if (sortVal === 'size_asc') return (a.size || 0) - (b.size || 0) || aName.localeCompare(bName);
      if (sortVal === 'name_desc') return bName.localeCompare(aName);
      if (sortVal === 'name_asc') return aName.localeCompare(bName);
      if (sortVal === 'type_asc') {
        const byType = (a.type || '').localeCompare(b.type || '');
        return byType !== 0 ? byType : aName.localeCompare(bName);
      }
      return aName.localeCompare(bName);
    });

    if (files.length > 0) out.push({ date: group.date, files });
  });

  out.sort((a, b) => {
    if (sortVal === 'date_asc') return (a.date || '').localeCompare(b.date || '');
    return (b.date || '').localeCompare(a.date || '');
  });
  return out;
}

function _buildMaterialPreviewHtml(file, groupFiles) {
  if (file.type === 'image') {
    const safePath = 'file:///' + file.path.replace(/\\/g, '/');
    return `<img src="${safePath}" alt="${file.name}" loading="lazy">`;
  }
  if (file.type === 'video') {
    const dot = file.name.lastIndexOf('.');
    const baseName = dot > 0 ? file.name.substring(0, dot) : file.name;
    const coverFile = groupFiles.find((f) => f.type === 'image' && f.name.startsWith(baseName) && f.name.includes('cover'));
    if (coverFile) {
      const safeCoverPath = 'file:///' + coverFile.path.replace(/\\/g, '/');
      return `
        <img src="${safeCoverPath}" alt="${file.name}" loading="lazy">
        <div class="video-play-overlay">
          <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
        </div>
      `;
    }
    return `<svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--color-primary);"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>`;
  }
  if (file.type === 'text') {
    return `<svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--color-accent);"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`;
  }
  return `<svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--text-muted);"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>`;
}

function renderDailyMaterials() {
  const data = getFilteredDailyMaterials();
  materialsContainer.innerHTML = '';

  if (!data || data.length === 0) {
    const emptyEl = document.createElement('div');
    emptyEl.className = 'empty-state';
    emptyEl.style.cssText = 'padding:80px 20px;text-align:center;color:var(--text-muted);font-size:0.82rem;line-height:1.6;';
    emptyEl.innerHTML = '暂无符合筛选条件的素材';
    materialsContainer.appendChild(emptyEl);
    updateMaterialsSelectedCount();
    return;
  }

  data.forEach((group) => {
    const groupEl = document.createElement('div');
    groupEl.className = 'materials-group';

    const headerEl = document.createElement('div');
    headerEl.className = 'materials-date-header';
    headerEl.innerHTML = `
      <span>📅 ${group.date}</span>
      <span class="materials-group-count">${group.files.length} 个文件</span>
    `;
    groupEl.appendChild(headerEl);

    const gridEl = document.createElement('div');
    gridEl.className = 'materials-grid';

    group.files.forEach((file) => {
      const cardEl = document.createElement('div');
      cardEl.className = 'material-file-card';
      cardEl.dataset.path = file.path || '';
      cardEl.title = `单击定位文件\n双击打开文件：${file.name}`;
      cardEl.draggable = true;

      let badgeText = '文件';
      let badgeClass = 'file';
      if (file.type === 'video') { badgeText = '视频'; badgeClass = 'video'; }
      else if (file.type === 'image') { badgeText = '图片'; badgeClass = 'image'; }
      else if (file.type === 'text') { badgeText = '图文'; badgeClass = 'text'; }

      const previewHtml = _buildMaterialPreviewHtml(file, group.files);
      const checked = selectedMaterialPaths.has(file.path);
      if (checked) cardEl.classList.add('selected');

      cardEl.innerHTML = `
        <span class="material-badge ${badgeClass}">${badgeText}</span>
        <label class="material-select-wrap" title="勾选用于批量操作">
          <input type="checkbox" class="material-item-check" ${checked ? 'checked' : ''}>
        </label>
        <div class="material-preview-box">${previewHtml}</div>
        <div class="material-info-box">
          <div class="material-name" title="${file.name}">${file.name}</div>
          <div class="material-size">${formatBytes(file.size || 0)}</div>
        </div>
      `;

      const check = cardEl.querySelector('.material-item-check');
      if (check) {
        check.addEventListener('click', (e) => e.stopPropagation());
        check.addEventListener('change', (e) => {
          if (e.target.checked) selectedMaterialPaths.add(file.path);
          else selectedMaterialPaths.delete(file.path);
          cardEl.classList.toggle('selected', e.target.checked);
          updateMaterialsSelectedCount();
        });
      }

      cardEl.addEventListener('click', (e) => {
        e.stopPropagation();
        window.api.openFileFolder(file.path);
      });

      cardEl.addEventListener('dblclick', (e) => {
        e.stopPropagation();
        window.api.openPath(file.path);
      });

      cardEl.addEventListener('dragstart', (e) => {
        try {
          const uri = 'file:///' + String(file.path || '').replace(/\\/g, '/');
          e.dataTransfer.setData('text/plain', file.path || '');
          e.dataTransfer.setData('text/uri-list', uri);
          e.dataTransfer.effectAllowed = 'copy';
        } catch (_) {}
      });

      gridEl.appendChild(cardEl);
    });

    groupEl.appendChild(gridEl);
    materialsContainer.appendChild(groupEl);
  });

  updateMaterialsSelectionUI();
}

function refreshMaterialsDateFilter() {
  if (!materialsDateFilter) return;
  const prev = materialsDateFilter.value;
  const dates = (allDailyMaterials || []).map((g) => g.date).filter(Boolean);
  materialsDateFilter.innerHTML = '<option value="all">全部日期</option>' +
    dates.map((d) => `<option value="${d}">${d}</option>`).join('');
  if (prev && dates.includes(prev)) materialsDateFilter.value = prev;
}

async function loadDailyMaterials() {
  materialsContainer.innerHTML = `
    <div style="padding:50px 20px;text-align:center;color:var(--text-secondary);display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px;">
      <div class="loader" style="border:2px solid var(--border-color);border-top:2px solid var(--color-primary);border-radius:50%;width:20px;height:20px;animation:spin 0.8s linear infinite;"></div>
      <span>正在加载本地素材...</span>
    </div>
  `;

  try {
    const data = await window.api.getDailyAssets();
    allDailyMaterials = Array.isArray(data) ? data : [];
    refreshMaterialsDateFilter();
    renderDailyMaterials();
  } catch (err) {
    console.error('加载本地素材失败:', err);
    materialsContainer.innerHTML = `
      <div class="empty-state" style="padding:100px 20px;text-align:center;color:var(--color-danger);font-size:0.82rem;line-height:1.6;">
        加载本地素材失败，请检查控制台错误信息，或点击右上角“刷新列表”重试
      </div>
    `;
  }
}

// Launch
init();
