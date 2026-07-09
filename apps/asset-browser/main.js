const { app, BrowserWindow, ipcMain, dialog, shell, session } = require('electron');
const path = require('path');
const fs = require('fs');
const https = require('https');
const http = require('http');
const { URL } = require('url');
const { exec } = require('child_process');
const proxyManager = require('./proxy-manager');

// 捕获未捕获的异常，防止因为 Electron/Chromium 内部的 WebFrameMain 销毁竞争等底层问题弹出 JavaScript 错误弹窗
process.on('uncaughtException', (err) => {
  console.error('主进程未捕获异常:', err);
});

function formatBytes(bytes, decimals = 2) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

let mainWindow;
const dbPath = path.join(app.getPath('userData'), 'database.json');

// ── 素材目录：支持用户通过 knowledge_dir.json 映射到外置盘/网络盘 ──
const _STUDIO_ROOT = path.join(__dirname, '..', '..', 'studio');
const _KB_DIR_CFG = path.join(_STUDIO_ROOT, 'data', 'knowledge_dir.json');
let KNOWLEDGE_DIR = path.join(_STUDIO_ROOT, 'outputs', 'materials', 'knowledge');
try {
  if (fs.existsSync(_KB_DIR_CFG)) {
    const _kd = JSON.parse(fs.readFileSync(_KB_DIR_CFG, 'utf-8'));
    if (_kd && _kd.materials_dir && fs.existsSync(_kd.materials_dir)) {
      KNOWLEDGE_DIR = _kd.materials_dir;
    }
  }
} catch (e) { console.warn('knowledge_dir.json read failed', e); }

// Initialize database
function initDatabase() {
  const defaultSettings = {
    downloadPath: KNOWLEDGE_DIR,
  };

  if (!fs.existsSync(dbPath)) {
    const defaultDb = {
      settings: defaultSettings,
      creators: [],
      downloads: []
    };
    // Ensure dir exists
    const dir = path.dirname(dbPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(dbPath, JSON.stringify(defaultDb, null, 2), 'utf-8');
  } else {
    // Read and ensure fields exist
    try {
      const db = JSON.parse(fs.readFileSync(dbPath, 'utf-8'));
      let modified = false;
      if (!db.settings) { db.settings = defaultSettings; modified = true; }
      // 始终与 Studio 配置的素材目录同步（knowledge_dir.json 优先）
      if (db.settings.downloadPath !== KNOWLEDGE_DIR) { db.settings.downloadPath = KNOWLEDGE_DIR; modified = true; }
      if (!db.creators) { db.creators = []; modified = true; }
      if (!db.downloads) { db.downloads = []; modified = true; }
      if (!Array.isArray(db.downloadDirs)) {
        db.downloadDirs = db.settings.downloadPath ? [db.settings.downloadPath] : [];
        modified = true;
      }
      if (modified) {
        fs.writeFileSync(dbPath, JSON.stringify(db, null, 2), 'utf-8');
      }
    } catch (e) {
      console.error('Database parse error, resetting', e);
      const defaultDb = {
        settings: defaultSettings,
        creators: [],
        downloads: []
      };
      fs.writeFileSync(dbPath, JSON.stringify(defaultDb, null, 2), 'utf-8');
    }
  }
}

function getDatabase() {
  try {
    const data = fs.readFileSync(dbPath, 'utf-8');
    return JSON.parse(data);
  } catch (err) {
    console.error('Failed to read database', err);
    return {
      settings: { downloadPath: path.join(app.getPath('home'), 'Downloads', 'BrowserAssets') },
      creators: [],
      downloads: []
    };
  }
}

function saveDatabase(db) {
  try {
    fs.writeFileSync(dbPath, JSON.stringify(db, null, 2), 'utf-8');
  } catch (err) {
    console.error('Failed to save database', err);
  }
}


// ── studio 集成：握手文件（选题关键词 → 搜索页 + 下载目录）──
let pendingHandoff = null;
const HANDOFF_FILE = path.join(__dirname, 'handoff.json');

function buildSearchUrl(platform, keyword) {
  const kw = encodeURIComponent(keyword || '');
  switch ((platform || 'douyin').toLowerCase()) {
    case 'bilibili':    return `https://search.bilibili.com/all?keyword=${kw}`;
    case 'tiktok':      return `https://www.tiktok.com/search?q=${kw}`;
    case 'youtube':     return `https://www.youtube.com/results?search_query=${kw}`;
    case 'xiaohongshu': return `https://www.xiaohongshu.com/search_result?keyword=${kw}`;
    case 'douyin':
    default:            return `https://www.douyin.com/search/${kw}`;
  }
}

function readHandoff() {
  try {
    if (fs.existsSync(HANDOFF_FILE)) {
      const raw = fs.readFileSync(HANDOFF_FILE, 'utf-8');
      try { fs.unlinkSync(HANDOFF_FILE); } catch (e) {} // 消费一次即删除
      const h = JSON.parse(raw);
      if (h && h.keyword && !h.searchUrl) h.searchUrl = buildSearchUrl(h.platform, h.keyword);
      return h;
    }
  } catch (e) { console.error('readHandoff failed', e); }
  return null;
}

ipcMain.handle('get-handoff', () => pendingHandoff);

// ── studio 集成：把同步到的关注/收藏样本写入 studio「我的知识库」可读的清单 ──
// KNOWLEDGE_DIR 已在上方初始化（支持 knowledge_dir.json 自定义映射）
const KB_MANIFEST = path.join(KNOWLEDGE_DIR, 'kb_sync.json');
const MATERIAL_IMPORT_TASKS = path.join(KNOWLEDGE_DIR, 'material_import_tasks.json');

// 热点追踪：把每天采集到的热榜快照写入 studio 可读的清单（含日期，供趋势合并）
const HOTSPOT_DIR = path.join(__dirname, '..', '..', 'studio', 'outputs', 'materials', 'hotspots');
const HOTSPOT_MANIFEST = path.join(HOTSPOT_DIR, 'hotspots_sync.json');

ipcMain.handle('append-hotspot-manifest', (event, items) => {
  try {
    if (!Array.isArray(items) || items.length === 0) return { ok: true, count: 0 };
    fs.mkdirSync(HOTSPOT_DIR, { recursive: true });
    let arr = [];
    if (fs.existsSync(HOTSPOT_MANIFEST)) {
      try { arr = JSON.parse(fs.readFileSync(HOTSPOT_MANIFEST, 'utf-8')); } catch (e) { arr = []; }
      if (!Array.isArray(arr)) arr = [];
    }
    const date = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
    for (const it of items) arr.push({ ...it, date });
    fs.writeFileSync(HOTSPOT_MANIFEST, JSON.stringify(arr, null, 2), 'utf-8');
    return { ok: true, count: items.length, date };
  } catch (e) {
    console.error('append-hotspot-manifest failed', e);
    return { ok: false, error: String(e) };
  }
});

// 收藏记录持久化：把内存里的收藏/点赞样本表存进 database.json，重启可恢复
ipcMain.handle('save-kb-items', (event, items) => {
  try {
    const db = getDatabase();
    db.kbItems = Array.isArray(items) ? items : [];
    saveDatabase(db);
    // 同步镜像到 studio 可读的共享目录，供「导入收藏记录」功能使用
    try {
      fs.mkdirSync(KNOWLEDGE_DIR, { recursive: true });
      fs.writeFileSync(
        path.join(KNOWLEDGE_DIR, 'kb_items.json'),
        JSON.stringify(db.kbItems, null, 2), 'utf-8'
      );
    } catch (e) { console.error('write kb_items.json failed', e); }
    return { ok: true, count: db.kbItems.length };
  } catch (e) {
    console.error('save-kb-items failed', e);
    return { ok: false, error: String(e) };
  }
});
ipcMain.handle('load-kb-items', () => {
  try {
    const db = getDatabase();
    const items = db.kbItems || [];
    // 每次加载时同步镜像，确保 studio 端总能看到最新数据（即使上次未调用 save-kb-items）
    if (items.length > 0) {
      try {
        fs.mkdirSync(KNOWLEDGE_DIR, { recursive: true });
        fs.writeFileSync(
          path.join(KNOWLEDGE_DIR, 'kb_items.json'),
          JSON.stringify(items, null, 2), 'utf-8'
        );
      } catch (e) { console.error('load-kb-items mirror failed', e); }
    }
    return items;
  } catch (e) { return []; }
});

ipcMain.handle('append-kb-manifest', (event, entry) => {
  try {
    fs.mkdirSync(KNOWLEDGE_DIR, { recursive: true });
    let arr = [];
    if (fs.existsSync(KB_MANIFEST)) {
      try { arr = JSON.parse(fs.readFileSync(KB_MANIFEST, 'utf-8')); } catch (e) { arr = []; }
      if (!Array.isArray(arr)) arr = [];
    }
    entry.syncedAt = new Date().toISOString();
    arr.push(entry);
    fs.writeFileSync(KB_MANIFEST, JSON.stringify(arr, null, 2), 'utf-8');
    return { ok: true, count: arr.length };
  } catch (e) {
    console.error('append-kb-manifest failed', e);
    return { ok: false, error: String(e) };
  }
});

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      webviewTag: true, // Enable <webview> tag
      preload: path.join(__dirname, 'preload-app.js') // Preload for the main UI
    },
    frame: true,
    show: false,
    title: '螺丝钉-电商智能体矩阵 素材浏览器'
  });

  // Load the frontend main interface
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// 防止重复启动：若已有实例在运行，将焦点转移到已有窗口后退出当前进程
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
}
app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
    // 重新读取握手文件，让已有窗口响应新的选题/搜索跳转
    const newHandoff = readHandoff();
    if (newHandoff) {
      pendingHandoff = newHandoff;
      mainWindow.webContents.send('handoff-updated', newHandoff);
    }
  }
});

app.whenReady().then(() => {
  initDatabase();

  // 启动时把数据库中已有的 kbItems 镜像到 studio 共享目录
  // 解决「旧数据存在 database.json 但 kb_items.json 从未写过」的问题
  try {
    const dbInit = getDatabase();
    const existingItems = dbInit.kbItems || [];
    if (existingItems.length > 0) {
      fs.mkdirSync(KNOWLEDGE_DIR, { recursive: true });
      fs.writeFileSync(
        path.join(KNOWLEDGE_DIR, 'kb_items.json'),
        JSON.stringify(existingItems, null, 2), 'utf-8'
      );
      console.log(`[startup] 已镜像 ${existingItems.length} 条收藏记录到 studio 共享目录`);
    }
  } catch (e) {
    console.error('[startup] kb_items.json mirror failed:', e);
  }

  // studio 集成：读取握手文件，设定本次下载目录（选题专属）
  pendingHandoff = readHandoff();
  if (pendingHandoff && pendingHandoff.downloadDir) {
    const db0 = getDatabase();
    const newDir = pendingHandoff.downloadDir;
    db0.settings.downloadPath = newDir;
    if (!Array.isArray(db0.downloadDirs)) db0.downloadDirs = [];
    if (!db0.downloadDirs.includes(newDir)) db0.downloadDirs.push(newDir);
    saveDatabase(db0);
  }

  createWindow();

  // 应用初始代理设置
  const db = getDatabase();
  proxyManager.applyProxy(db.settings);

  // 获取 Webview 使用的独立分区 Session，必须在此 Session 上挂载网络拦截器
  const webviewSession = session.fromPartition('persist:tintin-browser');

  // 1. 拦截并取消 Webview 内的所有外部 App 唤醒请求（例如 bytedance://, snssdk://, tbopen:// 等），彻底解决任务栏唤醒外部应用弹窗的问题。
  // 允许放行 ws:, wss: (用于登录检查和长连接) 以及 data: (用于图片和 SVG) 等标准 Web 协议，防止登录和保存卡死。
  webviewSession.webRequest.onBeforeRequest((details, callback) => {
    const url = details.url;
    try {
      const parsedUrl = new URL(url);
      const allowedProtocols = ['http:', 'https:', 'file:', 'ws:', 'wss:', 'data:', 'blob:', 'about:', 'chrome-extension:', 'devtools:'];
      if (!allowedProtocols.includes(parsedUrl.protocol)) {
        callback({ cancel: true }); // 阻止请求，阻止系统呼叫外部 App
        return;
      }
    } catch (e) {
      callback({ cancel: true });
      return;
    }
    callback({ cancel: false });
  });

  // 2. NeatDownloadManager 风格的网络请求响应头监听器 (在 Webview Session 上实时嗅探视频与音频流)
  webviewSession.webRequest.onHeadersReceived({ urls: ['http://*/*', 'https://*/*'] }, (details, callback) => {
    const responseHeaders = details.responseHeaders || {};
    // 忽略大小写寻找 Content-Type 响应头
    const contentTypeKey = Object.keys(responseHeaders).find(k => k.toLowerCase() === 'content-type');
    const contentType = contentTypeKey ? responseHeaders[contentTypeKey][0] : '';
    const url = details.url;

    let isMedia = false;
    let mediaType = '';

    const checkAudioUrlFeatures = (urlStr) => {
      const lower = urlStr.toLowerCase();
      return lower.includes('.mp3') || lower.includes('mime=audio') || lower.includes('media-audio') ||
             lower.includes('-30216') || lower.includes('-30232') || lower.includes('-30280') ||
             lower.includes('-30250') || lower.includes('audio');
    };

    if (contentType) {
      const ct = contentType.toLowerCase();
      if (ct.startsWith('video/') || ct.startsWith('audio/')) {
        isMedia = true;
        mediaType = ct.startsWith('audio/') ? 'audio' : 'video';
        // 修正：如果 Content-Type 是 video/mp4，但是 URL 包含音频特征，应修正为 audio
        if (mediaType === 'video' && checkAudioUrlFeatures(url)) {
          mediaType = 'audio';
        }
      } else if (ct.includes('application/vnd.apple.mpegurl') || ct.includes('application/x-mpegurl') || ct.includes('application/octet-stream')) {
        // 部分视频平台返回的是二进制流或 M3U8 分片，进一步校验 URL 关键字
        const lowerUrl = url.toLowerCase();
        if (lowerUrl.includes('.m3u8') || lowerUrl.includes('.ts') || lowerUrl.includes('.mp4') || lowerUrl.includes('.mp3') || lowerUrl.includes('.m4s') || lowerUrl.includes('videoplayback')) {
          isMedia = true;
          mediaType = checkAudioUrlFeatures(url) ? 'audio' : 'video';
        }
      }
    }

    // 备用机制：通过 URL 后缀或特征码识别
    if (!isMedia) {
      const lowerUrl = url.toLowerCase();
      if (lowerUrl.includes('.mp4') || lowerUrl.includes('.m3u8') || lowerUrl.includes('.mp3') || lowerUrl.includes('.webm') || lowerUrl.includes('.m4s') || lowerUrl.includes('.flv') || lowerUrl.includes('videoplayback')) {
        isMedia = true;
        mediaType = checkAudioUrlFeatures(url) ? 'audio' : 'video';
      }
    }

    // 过滤掉开发环境 localhost 和内部文件协议
    if (isMedia && !url.includes('127.0.0.1') && !url.includes('localhost') && !url.startsWith('file:')) {
      if (mainWindow && !mainWindow.isDestroyed()) {
        let filename = '媒体素材';
        try {
          const parsed = new URL(url);
          filename = path.basename(parsed.pathname) || '媒体素材';
        } catch (e) {}

        // 去掉 URL 参数
        filename = filename.split('?')[0];

        // 针对 YouTube/字节等特征无后缀链接进行重命名
        if (url.includes('videoplayback')) {
          filename = 'youtube_video_' + Math.random().toString(36).substring(2, 7);
        } else if (url.includes('video/tos') || url.includes('video_')) {
          filename = 'douyin_video_' + Math.random().toString(36).substring(2, 7);
        }

        const fileExt = mediaType === 'audio' ? '.mp3' : '.mp4';
        if (!filename.includes('.')) {
          filename += fileExt;
        }

        // 提取文件大小信息 (Content-Range 或 Content-Length)
        let totalSize = 0;
        const contentRangeKey = Object.keys(responseHeaders).find(k => k.toLowerCase() === 'content-range');
        if (contentRangeKey && responseHeaders[contentRangeKey][0]) {
          const contentRange = responseHeaders[contentRangeKey][0];
          const match = contentRange.match(/\/(\d+)$/);
          if (match) {
            totalSize = parseInt(match[1], 10);
          }
        }
        if (!totalSize) {
          const contentLengthKey = Object.keys(responseHeaders).find(k => k.toLowerCase() === 'content-length');
          if (contentLengthKey && responseHeaders[contentLengthKey][0]) {
            totalSize = parseInt(responseHeaders[contentLengthKey][0], 10);
          }
        }

        mainWindow.webContents.send('webview-media-sniffed', {
          url,
          type: mediaType,
          name: filename,
          size: totalSize,
          sizeText: totalSize > 0 ? formatBytes(totalSize) : '网络流自动嗅探'
        });
      }
    }

    callback({ cancel: false });
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});



app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// 应用程序退出时，关闭代理进程
app.on('will-quit', () => {
  proxyManager.shutdown();
});

// 拦截非 http/https 协议（例如 bytedance://, snssdk://, tbopen:// 等原生客户端跳转链接），防止 Windows 弹出“寻找关联应用”的系统对话框
app.on('web-contents-created', (event, contents) => {
  const allowedNavProtocols = ['http:', 'https:', 'file:', 'about:', 'data:', 'blob:'];

  // 转发控制台日志到主进程终端，方便调试
  contents.on('console-message', (event, level, message, line, sourceId) => {
    const type = contents.getType();
    console.log(`[Console][${type}] ${message} (at ${path.basename(sourceId || '')}:${line})`);
  });

  // 拦截主框架导航
  contents.on('will-navigate', (event, navigationUrl) => {
    try {
      const parsedUrl = new URL(navigationUrl);
      if (!allowedNavProtocols.includes(parsedUrl.protocol)) {
        event.preventDefault();
      }
    } catch (e) {
      event.preventDefault();
    }
  });

  // 拦截子框架 (iframe) 导航（抖音等网页通常在子 iframe 内跳转 bytedance:// 唤起外部 App）
  contents.on('will-frame-navigate', (event, navigationUrl) => {
    try {
      const parsedUrl = new URL(navigationUrl);
      if (!allowedNavProtocols.includes(parsedUrl.protocol)) {
        event.preventDefault(); // 阻止跳转，彻底拦截弹窗
      }
    } catch (e) {
      event.preventDefault();
    }
  });

  // 拦截重定向
  contents.on('will-redirect', (event, navigationUrl) => {
    try {
      const parsedUrl = new URL(navigationUrl);
      if (!allowedNavProtocols.includes(parsedUrl.protocol)) {
        event.preventDefault();
      }
    } catch (e) {
      event.preventDefault();
    }
  });

  contents.setWindowOpenHandler((details) => {
    try {
      const parsedUrl = new URL(details.url);
      if (!allowedNavProtocols.includes(parsedUrl.protocol)) {
        return { action: 'deny' };
      }
      
      // 如果是 webview 内触发的窗口打开（如 B站视频点击），拦截它并在当前的 webview 中加载，防止跳转到新窗口导致嗅探失效
      if (contents.getType() === 'webview') {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('webview-open-url', { url: details.url, senderId: contents.id });
        }
        return { action: 'deny' };
      }
    } catch (e) {
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });
});


// --- IPC Communication Handlers ---

// DB Creators
ipcMain.handle('db-get-creators', () => {
  const db = getDatabase();
  return db.creators;
});

ipcMain.handle('db-add-creator', (event, creator) => {
  const db = getDatabase();
  // Check duplicate
  const exists = db.creators.find(c => c.id === creator.id && c.platform === creator.platform);
  if (!exists) {
    db.creators.push(creator);
    saveDatabase(db);
  }
  return db.creators;
});

ipcMain.handle('db-delete-creator', (event, { id, platform }) => {
  const db = getDatabase();
  db.creators = db.creators.filter(c => !(c.id === id && c.platform === platform));
  saveDatabase(db);
  return db.creators;
});

// DB Settings
ipcMain.handle('db-get-settings', () => {
  const db = getDatabase();
  return db.settings;
});

ipcMain.handle('db-get-download-dirs', () => {
  const db = getDatabase();
  const dirs = new Set();
  if (db.settings.downloadPath) dirs.add(db.settings.downloadPath);
  if (Array.isArray(db.downloadDirs)) db.downloadDirs.forEach(d => dirs.add(d));
  return [...dirs];
});

ipcMain.handle('db-add-download-dir', (event, dir) => {
  if (!dir) return;
  const db = getDatabase();
  if (!Array.isArray(db.downloadDirs)) db.downloadDirs = [];
  if (!db.downloadDirs.includes(dir)) {
    db.downloadDirs.push(dir);
    saveDatabase(db);
  }
});

ipcMain.handle('db-save-settings', (event, settings) => {
  const db = getDatabase();
  db.settings = { ...db.settings, ...settings };
  if (settings.downloadPath) {
    if (!Array.isArray(db.downloadDirs)) db.downloadDirs = [];
    if (!db.downloadDirs.includes(settings.downloadPath)) {
      db.downloadDirs.push(settings.downloadPath);
    }
  }
  saveDatabase(db);
  // 动态应用更新后的代理设置
  proxyManager.applyProxy(db.settings);
  return db.settings;
});

// Select Directory Dialog
ipcMain.handle('select-download-dir', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory']
  });
  if (!result.canceled && result.filePaths.length > 0) {
    return result.filePaths[0];
  }
  return null;
});

// DB Downloads
ipcMain.handle('db-get-downloads', () => {
  const db = getDatabase();
  return db.downloads;
});

ipcMain.handle('db-clear-downloads', () => {
  const db = getDatabase();
  db.downloads = [];
  saveDatabase(db);
  return db.downloads;
});

// File System Helper
ipcMain.handle('open-file-folder', async (event, filePath) => {
  if (fs.existsSync(filePath)) {
    shell.showItemInFolder(filePath);
    return true;
  }
  return false;
});

ipcMain.handle('open-path', async (event, dirPath) => {
  if (fs.existsSync(dirPath)) {
    shell.openPath(dirPath);
    return true;
  }
  return false;
});

function _normalizePathLower(p) {
  return path.resolve(String(p || '')).replace(/[\\/]+$/, '').toLowerCase();
}

function _isPathInRoots(filePath, roots) {
  const fp = _normalizePathLower(filePath);
  return roots.some((r) => {
    const root = _normalizePathLower(r);
    return fp === root || fp.startsWith(root + path.sep);
  });
}

function _classifyFileType(name) {
  const ext = path.extname(String(name || '')).toLowerCase();
  const VIDEO_EXT = new Set(['.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v']);
  const IMAGE_EXT = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']);
  const TEXT_EXT = new Set(['.txt', '.html', '.md', '.json']);
  if (VIDEO_EXT.has(ext)) return 'video';
  if (IMAGE_EXT.has(ext)) return 'image';
  if (TEXT_EXT.has(ext)) return 'text';
  return 'file';
}

ipcMain.handle('delete-local-files', async (event, paths) => {
  try {
    const arr = Array.isArray(paths) ? paths : [];
    const unique = Array.from(new Set(arr.filter(Boolean).map((p) => path.resolve(String(p)))));
    const db = getDatabase();
    const allowedRoots = new Set();
    if (db.settings && db.settings.downloadPath) allowedRoots.add(db.settings.downloadPath);
    if (Array.isArray(db.downloadDirs)) db.downloadDirs.forEach((d) => allowedRoots.add(d));

    let deleted = 0;
    let failed = 0;
    let skipped = 0;
    const errors = [];

    for (const p of unique) {
      try {
        if (!_isPathInRoots(p, Array.from(allowedRoots))) {
          skipped += 1;
          continue;
        }
        if (!fs.existsSync(p)) {
          skipped += 1;
          continue;
        }
        const stat = fs.statSync(p);
        if (!stat.isFile()) {
          skipped += 1;
          continue;
        }
        fs.unlinkSync(p);
        deleted += 1;
      } catch (e) {
        failed += 1;
        if (errors.length < 20) {
          errors.push({ path: p, error: String(e && e.message ? e.message : e) });
        }
      }
    }

    return { ok: true, deleted, failed, skipped, errors };
  } catch (e) {
    console.error('delete-local-files failed', e);
    return { ok: false, deleted: 0, failed: 0, skipped: 0, error: String(e) };
  }
});

ipcMain.handle('enqueue-material-import', async (event, paths) => {
  try {
    const arr = Array.isArray(paths) ? paths : [];
    const unique = Array.from(new Set(arr.filter(Boolean).map((p) => path.resolve(String(p)))));
    fs.mkdirSync(KNOWLEDGE_DIR, { recursive: true });

    let existing = [];
    if (fs.existsSync(MATERIAL_IMPORT_TASKS)) {
      try {
        existing = JSON.parse(fs.readFileSync(MATERIAL_IMPORT_TASKS, 'utf-8'));
      } catch (e) {
        existing = [];
      }
      if (!Array.isArray(existing)) existing = [];
    }

    const existingSet = new Set(existing.map((it) => String(it.path || '').toLowerCase()).filter(Boolean));
    const now = new Date().toISOString();
    let added = 0;

    for (const p of unique) {
      if (!fs.existsSync(p)) continue;
      let stat;
      try {
        stat = fs.statSync(p);
      } catch (e) {
        continue;
      }
      if (!stat.isFile()) continue;
      const key = String(p).toLowerCase();
      if (existingSet.has(key)) continue;
      existing.push({
        path: p,
        name: path.basename(p),
        size: stat.size,
        type: _classifyFileType(p),
        status: 'pending',
        source: 'asset-browser',
        enqueuedAt: now
      });
      existingSet.add(key);
      added += 1;
    }

    fs.writeFileSync(MATERIAL_IMPORT_TASKS, JSON.stringify(existing, null, 2), 'utf-8');
    return { ok: true, count: added, total: existing.length, file: MATERIAL_IMPORT_TASKS };
  } catch (e) {
    console.error('enqueue-material-import failed', e);
    return { ok: false, count: 0, error: String(e) };
  }
});

// IPC 处理器：扫描所有曾用过的下载目录，按日期分组返回文件列表
ipcMain.handle('get-daily-assets', async () => {
  const db = getDatabase();

  // 合并当前目录与历史目录，去重
  const dirsToScan = new Set();
  if (db.settings.downloadPath) dirsToScan.add(db.settings.downloadPath);
  if (Array.isArray(db.downloadDirs)) db.downloadDirs.forEach(d => dirsToScan.add(d));

  // dateKey → { files: [], dirs: Set<string> }  (dirs 用于跨目录去重同路径文件)
  const dateGroups = {};

  const VIDEO_EXT = new Set(['.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v']);
  const IMAGE_EXT = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']);
  const TEXT_EXT  = new Set(['.txt', '.html', '.md', '.json']);

  for (const baseDir of dirsToScan) {
    if (!baseDir || !fs.existsSync(baseDir)) continue;
    try {
      for (const name of fs.readdirSync(baseDir)) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(name)) continue;
        const datePath = path.join(baseDir, name);
        try {
          if (!fs.statSync(datePath).isDirectory()) continue;
        } catch (e) { continue; }

        if (!dateGroups[name]) dateGroups[name] = { files: [], seen: new Set() };
        const group = dateGroups[name];

        for (const f of fs.readdirSync(datePath)) {
          if (f.endsWith('.tmp') || f.endsWith('.cookies.txt')) continue;
          const fp = path.join(datePath, f);
          try {
            if (!fs.statSync(fp).isFile()) continue;
          } catch (e) { continue; }
          if (group.seen.has(fp)) continue;
          group.seen.add(fp);
          const ext = path.extname(f).toLowerCase();
          let type = 'file';
          if (VIDEO_EXT.has(ext)) type = 'video';
          else if (IMAGE_EXT.has(ext)) type = 'image';
          else if (TEXT_EXT.has(ext)) type = 'text';
          group.files.push({ name: f, path: fp, size: (() => { try { return fs.statSync(fp).size; } catch(e){ return 0; } })(), type });
        }
      }
    } catch (err) {
      console.error('扫描下载目录失败:', baseDir, err);
    }
  }

  return Object.keys(dateGroups)
    .sort().reverse()
    .map(date => ({ date, files: dateGroups[date].files }));
});


// --- Injected Referrer & Cookie Downloader ---

// Active download tasks
const activeDownloads = new Map();

// 通用网络流下载辅助函数，支持 Referer、Cookie 注入和 302 重定向
function downloadStream(id, url, destPath, referer, onProgress) {
  return new Promise(async (resolve, reject) => {
    let cookieString = '';
    try {
      const cookies = await session.fromPartition('persist:tintin-browser').cookies.get({ url });
      cookieString = cookies.map(c => `${c.name}=${c.value}`).join('; ');
    } catch (err) {}

    const headers = {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': '*/*',
      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
    };
    if (referer) headers['Referer'] = referer;
    if (cookieString) headers['Cookie'] = cookieString;

    let req = null;
    let fileStream = null;
    let isRequestDestroyed = false;

    const cleanupFile = () => {
      activeDownloads.delete(id);
      if (fileStream) {
        fileStream.close();
        fileStream = null;
      }
      try {
        if (fs.existsSync(destPath)) {
          fs.unlinkSync(destPath);
        }
      } catch (e) {}
    };

    const makeRequest = (requestUrl) => {
      try {
        const parsed = new URL(requestUrl);
        const httpModule = parsed.protocol === 'https:' ? https : http;

        req = httpModule.get(requestUrl, { method: 'GET', headers, timeout: 45000 }, (res) => {
          if (isRequestDestroyed) return;

          // 处理重定向
          if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
            const redirectUrl = new URL(res.headers.location, requestUrl).toString();
            makeRequest(redirectUrl);
            return;
          }

          // YouTube 使用 range=0-99999999999 时，服务器会返回 206 Partial Content
          if (res.statusCode !== 200 && res.statusCode !== 206) {
            reject(new Error(`HTTP 状态码错误: ${res.statusCode}`));
            return;
          }

          // 仅在 HTTP 请求成功且返回 200/206 时，才创建文件流，避免重定向过程中对流进行关闭 and 重建报错
          try {
            fileStream = fs.createWriteStream(destPath);
            fileStream.on('error', (err) => {
              cleanupFile();
              reject(err);
            });
          } catch (err) {
            reject(err);
            return;
          }

          const totalBytes = parseInt(res.headers['content-length'], 10) || 0;
          let receivedBytes = 0;

          res.on('data', (chunk) => {
            if (isRequestDestroyed) return;
            receivedBytes += chunk.length;
            if (fileStream) {
              fileStream.write(chunk);
            }
            if (onProgress) {
              onProgress(receivedBytes, totalBytes);
            }
          });

          res.on('end', () => {
            if (isRequestDestroyed) return;
            activeDownloads.delete(id);
            if (fileStream) {
              fileStream.end(() => {
                resolve({ totalBytes });
              });
            } else {
              resolve({ totalBytes });
            }
          });
        });

        // 注册当前活动请求以便可中途取消
        activeDownloads.set(id, req);

        req.on('error', (err) => {
          if (isRequestDestroyed) return;
          cleanupFile();
          reject(err);
        });

        req.on('timeout', () => {
          if (isRequestDestroyed) return;
          isRequestDestroyed = true;
          req.destroy();
          cleanupFile();
          reject(new Error('网络连接超时'));
        });
      } catch (err) {
        cleanupFile();
        reject(err);
      }
    };

    makeRequest(url);
  });
}

function cleanMediaUrlForDownload(urlStr) {
  if (!urlStr) return urlStr;
  try {
    const parsed = new URL(urlStr);
    if (parsed.hostname.includes('googlevideo.com') || parsed.hostname.includes('youtube.com')) {
      // YouTube 要求必须有 range 参数，否则直接返回 403。
      // 我们将其设置为超大范围，从而实现一个链接下载完整音频/视频文件。
      parsed.searchParams.set('range', '0-99999999999');
    } else {
      parsed.searchParams.delete('range');
    }
    parsed.searchParams.delete('rn');
    parsed.searchParams.delete('obuf');
    parsed.searchParams.delete('start');
    parsed.searchParams.delete('end');
    return parsed.toString();
  } catch (e) {
    return urlStr;
  }
}

// 辅助函数：导出指定域名的 Cookie 给 yt-dlp 使用
async function exportCookiesForDomain(domain, destPath) {
  try {
    const cookies = await session.fromPartition('persist:tintin-browser').cookies.get({ domain });
    let cookieText = "# Netscape HTTP Cookie File\n";
    for (const c of cookies) {
      const d = c.domain;
      const flag = d.startsWith('.') ? 'TRUE' : 'FALSE';
      const path = c.path;
      const secure = c.secure ? 'TRUE' : 'FALSE';
      const expiration = c.expirationDate ? Math.round(c.expirationDate) : Math.round(Date.now() / 1000 + 86400 * 30);
      cookieText += `${d}\t${flag}\t${path}\t${secure}\t${expiration}\t${c.name}\t${c.value}\n`;
    }
    fs.writeFileSync(destPath, cookieText, 'utf-8');
    return true;
  } catch (err) {
    console.warn(`导出域名 ${domain} 的 Cookie 失败:`, err);
    return false;
  }
}

// IPC 处理器：检查登录状态
ipcMain.handle('check-login-status', async () => {
  const sess = session.fromPartition('persist:tintin-browser');
  try {
    const allCookies = await sess.cookies.get({});
    const hasCookie = (domainPart, namePart) => {
      return allCookies.some(c => 
        c.domain.toLowerCase().includes(domainPart.toLowerCase()) && 
        c.name.toLowerCase().includes(namePart.toLowerCase())
      );
    };
    const status = {
      bilibili: hasCookie('bilibili.com', 'SESSDATA'),
      xiaohongshu: hasCookie('xiaohongshu.com', 'web_session') || hasCookie('xiaohongshu.com', 'webId'),
      douyin: hasCookie('douyin.com', 'sessionid'),
      youtube: hasCookie('youtube.com', 'LOGIN_INFO') || hasCookie('youtube.com', 'SID'),
      zhihu: hasCookie('zhihu.com', 'z_c0'),
      tiktok: hasCookie('tiktok.com', 'sessionid') || hasCookie('tiktok.com', 'sid_tt')
    };
    return status;
  } catch (err) {
    console.error('获取 Cookies 失败:', err);
    return { bilibili: false, xiaohongshu: false, douyin: false, youtube: false, zhihu: false, tiktok: false };
  }
});

// IPC 处理器：将文本或 HTML 写入文件并生成一条下载记录
ipcMain.handle('save-text-file', async (event, { filename, content, subDir }) => {
  const db = getDatabase();
  let downloadDir = db.settings.downloadPath;
  if (subDir) {
    downloadDir = path.join(downloadDir, subDir);
  }
  if (!fs.existsSync(downloadDir)) {
    fs.mkdirSync(downloadDir, { recursive: true });
  }
  
  let safeFilename = filename.replace(/[\\/:*?"<>|]/g, '_');
  const finalPath = path.join(downloadDir, safeFilename);
  
  fs.writeFileSync(finalPath, content, 'utf-8');
  
  // 生成一条已完成的本地下载历史记录
  const id = 'dl-text-' + Date.now() + '-' + Math.random().toString(36).substring(2, 7);
  const newTask = {
    id,
    url: '',
    filename: safeFilename,
    path: finalPath,
    status: 'completed',
    progress: 100,
    size: fs.statSync(finalPath).size,
    date: new Date().toLocaleString()
  };
  db.downloads.unshift(newTask);
  saveDatabase(db);
  mainWindow.webContents.send('download-list-updated', db.downloads);
  
  return { success: true, path: finalPath };
});

function isValidVideoPageUrl(url) {
  if (!url) return false;
  const lower = url.toLowerCase();
  if (lower.includes('youtube.com/watch') || lower.includes('youtu.be/') || lower.includes('youtube.com/shorts/')) {
    return true;
  }
  if (lower.includes('bilibili.com/video/') || lower.includes('bilibili.com/bangumi/play/')) {
    return true;
  }
  if (lower.includes('douyin.com/video/') || lower.includes('douyin.com/note/')) {
    return true;
  }
  if (lower.includes('zhihu.com/zvideo/')) {
    return true;
  }
  return false;
}

ipcMain.handle('start-download', async (event, { id, url: fileUrl, audioUrl, filename, referer, subDir, useYtdlp }) => {
  const db = getDatabase();
  let downloadDir = db.settings.downloadPath;
  if (subDir) {
    downloadDir = path.join(downloadDir, subDir);
  }

  // 确保下载目录存在
  if (!fs.existsSync(downloadDir)) {
    fs.mkdirSync(downloadDir, { recursive: true });
  }

  // 生成安全文件名
  let safeFilename = filename.replace(/[\\/:*?"<>|]/g, '_');
  let finalPath = path.join(downloadDir, safeFilename);

  // 文件重名处理
  let counter = 1;
  const ext = path.extname(safeFilename);
  const base = path.basename(safeFilename, ext);
  while (fs.existsSync(finalPath)) {
    safeFilename = `${base}_${counter}${ext}`;
    finalPath = path.join(downloadDir, safeFilename);
    counter++;
  }

  // 新建下载记录并保存
  const newTask = {
    id,
    url: fileUrl,
    audioUrl: audioUrl || null,
    filename: safeFilename,
    path: finalPath,
    status: 'downloading',
    progress: 0,
    size: 0,
    date: new Date().toLocaleString()
  };

  db.downloads.unshift(newTask);
  saveDatabase(db);
  mainWindow.webContents.send('download-list-updated', db.downloads);

  // 判断是否应该使用 yt-dlp 进行页面整包下载（若明确指定，或者 URL/referer 指向主要视频站视频详情页且非直接静态流链接）
  const isVideoPage = useYtdlp || (referer && isValidVideoPageUrl(referer));

  if (isVideoPage) {
    updateTaskProgress(id, 5, '正在通过 yt-dlp 解析视频...', 0);

    const urlToDownload = isVideoPage ? (referer || fileUrl) : fileUrl;
    
    // 根据域名判断需要导出的 Cookie，实现登录视频下载
    let cookieDomain = '';
    if (urlToDownload.includes('youtube.com') || urlToDownload.includes('youtu.be')) {
      cookieDomain = '.youtube.com';
    } else if (urlToDownload.includes('bilibili.com')) {
      cookieDomain = '.bilibili.com';
    } else if (urlToDownload.includes('douyin.com')) {
      cookieDomain = '.douyin.com';
    } else if (urlToDownload.includes('zhihu.com')) {
      cookieDomain = '.zhihu.com';
    }

    const cookieTempPath = finalPath + '.cookies.txt';
    if (cookieDomain) {
      await exportCookiesForDomain(cookieDomain, cookieTempPath);
    }

    const localYtdlpPath = app.isPackaged
      ? path.join(process.resourcesPath, 'bin', 'yt-dlp.exe')
      : path.join(__dirname, 'bin', 'yt-dlp.exe');
      
    const ytdlpBin = fs.existsSync(localYtdlpPath) ? `"${localYtdlpPath}"` : 'yt-dlp';

    const cookieArg = fs.existsSync(cookieTempPath) ? `--cookies "${cookieTempPath}"` : '';
    const proxyArg = proxyManager.getYtDlpProxyArg(db.settings);

    // 调用 yt-dlp，指定合并格式为 mp4 并指定保存文件名路径
    const cmd = `${ytdlpBin} ${cookieArg} ${proxyArg} --no-warnings -f "bv+ba/b" --merge-output-format mp4 -o "${finalPath}" "${urlToDownload}"`;

    const child = exec(cmd, (err, stdout, stderr) => {
      // 销毁时清理 Cookie 临时文件
      try { if (fs.existsSync(cookieTempPath)) fs.unlinkSync(cookieTempPath); } catch(e){}
      activeDownloads.delete(id);

      if (err) {
        // 即使 exit code 非零，若文件已成功生成则视为成功（yt-dlp 警告信息可能触发非零退出）
        let fileCreated = false;
        try { fileCreated = fs.existsSync(finalPath) && fs.statSync(finalPath).size > 0; } catch(e) {}
        if (fileCreated) {
          const finalSize = fs.statSync(finalPath).size;
          updateTaskSize(id, finalSize);
          updateTaskStatus(id, 'completed', 100, finalSize);
        } else {
          console.error('yt-dlp 下载失败:', err, stderr);
          const errLines = (stderr || '').split('\n').filter(l => l.trim() && !l.startsWith('WARNING:'));
          const errMsg = errLines.join('\n').trim() || err.message;
          updateTaskStatus(id, 'failed', 0, 0, '下载失败: ' + errMsg);
        }
      } else {
        let finalSize = 0;
        try {
          if (fs.existsSync(finalPath)) {
            finalSize = fs.statSync(finalPath).size;
          }
        } catch (e) {}
        updateTaskSize(id, finalSize);
        updateTaskStatus(id, 'completed', 100, finalSize);
      }
    });

    // 解析 stdout 得到进度和速度
    if (child.stdout) {
      child.stdout.on('data', (data) => {
        const str = data.toString();
        // 匹配进度: [download]  12.5% of  15.20MiB at  2.11MiB/s ETA 00:06
        const match = str.match(/\[download\]\s+(\d+\.\d+)%\s+of\s+([^\s]+)\s+at\s+([^\s]+)/);
        if (match) {
          const progress = Math.round(parseFloat(match[1]));
          const speed = match[3];
          updateTaskProgress(id, progress, `下载中 ${speed}`, 0);
        }
      });
    }

    activeDownloads.set(id, child);
    return { success: true };
  }

  // 清理 URL 的 range 和分段请求参数，下载完整流数据
  const cleanVideoUrl = cleanMediaUrlForDownload(fileUrl);
  const cleanAudioUrl = cleanMediaUrlForDownload(audioUrl);

  // 执行下载
  if (audioUrl) {
    // ----------------------------------------------------
    // 情况 A：音视频分离下载模式（B站/抖音DASH流）
    // ----------------------------------------------------
    const videoTempPath = finalPath + '.video.tmp';
    const audioTempPath = finalPath + '.audio.tmp';

    let videoBytes = { received: 0, total: 0 };
    let audioBytes = { received: 0, total: 0 };
    let lastTime = Date.now();
    let lastBytes = 0;
    let speed = '0 B/s';

    const updateOverallProgress = () => {
      const total = videoBytes.total + audioBytes.total;
      const received = videoBytes.received + audioBytes.received;
      
      const now = Date.now();
      const elapsed = now - lastTime;
      if (elapsed >= 500 || received === total) {
        const progress = total > 0 ? Math.round((received / total) * 100) : 0;
        
        // 速度计算
        const bytesDiff = received - lastBytes;
        const speedBps = (bytesDiff / elapsed) * 1000;
        if (speedBps > 1024 * 1024) {
          speed = `${(speedBps / (1024 * 1024)).toFixed(1)} MB/s`;
        } else if (speedBps > 1024) {
          speed = `${(speedBps / 1024).toFixed(1)} KB/s`;
        } else {
          speed = `${Math.round(speedBps)} B/s`;
        }

        updateTaskProgress(id, progress, `下载中 (音视频合并模式) ${speed}`, received);
        lastTime = now;
        lastBytes = received;
      }
    };

    const videoPromise = downloadStream(id + '_video', cleanVideoUrl, videoTempPath, referer, (received, total) => {
      videoBytes.received = received;
      videoBytes.total = total;
      updateOverallProgress();
    });

    const audioPromise = downloadStream(id + '_audio', cleanAudioUrl, audioTempPath, referer, (received, total) => {
      audioBytes.received = received;
      audioBytes.total = total;
      updateOverallProgress();
    });

    Promise.all([videoPromise, audioPromise])
      .then(async ([videoRes, audioRes]) => {
        const totalSize = videoRes.totalBytes + audioRes.totalBytes;
        updateTaskSize(id, totalSize);
        updateTaskProgress(id, 99, '正在使用 FFmpeg 完美合并音视频...', totalSize);

        // 优先使用内置的 ffmpeg 二进制文件，若不存在则回退至系统全局命令
        const localFfmpegPath = app.isPackaged
          ? path.join(process.resourcesPath, 'bin', 'ffmpeg.exe')
          : path.join(__dirname, 'bin', 'ffmpeg.exe');
        
        const ffmpegBin = fs.existsSync(localFfmpegPath) ? `"${localFfmpegPath}"` : 'ffmpeg';

        const cmd = `${ffmpegBin} -y -i "${videoTempPath}" -i "${audioTempPath}" -c:v copy -c:a aac -strict experimental "${finalPath}"`;
        exec(cmd, (err) => {
          // 清理临时文件
          try { fs.unlinkSync(videoTempPath); } catch(e){}
          try { fs.unlinkSync(audioTempPath); } catch(e){}

          if (err) {
            console.error('FFmpeg 合并失败，回退仅视频文件:', err);
            // 回退：如果 FFmpeg 合并报错，重命名视频临时文件为最终文件，供用户起码能看无声画面
            try {
              fs.renameSync(videoTempPath, finalPath);
              updateTaskStatus(id, 'completed', 100, videoRes.totalBytes, 'FFmpeg 合并失败，仅保存无声视频');
            } catch(renameErr) {
              updateTaskStatus(id, 'failed', 0, 0, 'FFmpeg 合并失败: ' + err.message);
            }
          } else {
            updateTaskStatus(id, 'completed', 100, totalSize);
          }
        });
      })
      .catch((err) => {
        try { fs.unlinkSync(videoTempPath); } catch(e){}
        try { fs.unlinkSync(audioTempPath); } catch(e){}
        updateTaskStatus(id, 'failed', 0, 0, '音视频下载失败: ' + err.message);
      });

  } else {
    // ----------------------------------------------------
    // 情况 B：常规单文件下载模式（小红书大图/单视频）
    // ----------------------------------------------------
    let lastTime = Date.now();
    let lastBytes = 0;
    let speed = '0 B/s';

    downloadStream(id, cleanVideoUrl, finalPath, referer, (received, total) => {
      const now = Date.now();
      const elapsed = now - lastTime;
      if (elapsed >= 500 || received === total) {
        const progress = total > 0 ? Math.round((received / total) * 100) : 0;
        
        // 速度计算
        const bytesDiff = received - lastBytes;
        const speedBps = (bytesDiff / elapsed) * 1000;
        if (speedBps > 1024 * 1024) {
          speed = `${(speedBps / (1024 * 1024)).toFixed(1)} MB/s`;
        } else if (speedBps > 1024) {
          speed = `${(speedBps / 1024).toFixed(1)} KB/s`;
        } else {
          speed = `${Math.round(speedBps)} B/s`;
        }

        updateTaskProgress(id, progress, speed, received);
        lastTime = now;
        lastBytes = received;
      }
    })
    .then(({ totalBytes }) => {
      updateTaskSize(id, totalBytes);
      updateTaskStatus(id, 'completed', 100, totalBytes);
    })
    .catch((err) => {
      updateTaskStatus(id, 'failed', 0, 0, err.message);
    });
  }

  return { success: true };
});

ipcMain.handle('cancel-download', (event, id) => {
  let cancelled = false;

  // 1. 取消单个任务句柄 (yt-dlp child process or single download req)
  if (activeDownloads.has(id)) {
    const task = activeDownloads.get(id);
    if (task.kill) {
      task.kill(); // child process
    } else if (task.destroy) {
      task.destroy(); // http request
    }
    activeDownloads.delete(id);
    cancelled = true;
  }

  // 2. 取消音视频分离下载的子请求 (video 与 audio 任务)
  const videoId = id + '_video';
  const audioId = id + '_audio';
  if (activeDownloads.has(videoId)) {
    const task = activeDownloads.get(videoId);
    if (task.destroy) task.destroy();
    activeDownloads.delete(videoId);
    cancelled = true;
  }
  if (activeDownloads.has(audioId)) {
    const task = activeDownloads.get(audioId);
    if (task.destroy) task.destroy();
    activeDownloads.delete(audioId);
    cancelled = true;
  }

  if (cancelled) {
    updateTaskStatus(id, 'failed', 0, 0, '已取消');
    return true;
  }
  return false;
});

// Task database helper functions
function updateTaskSize(id, size) {
  const db = getDatabase();
  const task = db.downloads.find(t => t.id === id);
  if (task) {
    task.size = size;
    saveDatabase(db);
    mainWindow.webContents.send('download-list-updated', db.downloads);
  }
}

function updateTaskProgress(id, progress, speed, receivedBytes) {
  // We send direct ipc message to frontend for real-time progress without rewriting database file every 500ms
  if (mainWindow) {
    mainWindow.webContents.send('download-progress-update', { id, progress, speed, receivedBytes });
  }
}

function updateTaskStatus(id, status, progress, size, errorMsg = '') {
  const db = getDatabase();
  const task = db.downloads.find(t => t.id === id);
  if (task) {
    task.status = status;
    task.progress = progress;
    if (size > 0) task.size = size;
    if (errorMsg) task.error = errorMsg;
    saveDatabase(db);
    if (mainWindow) {
      mainWindow.webContents.send('download-list-updated', db.downloads);
      mainWindow.webContents.send('download-status-change', { id, status, errorMsg });
    }
  }
}
