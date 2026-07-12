const { app, BrowserWindow, ipcMain, dialog, shell, session } = require('electron');
const path = require('path');
const fs = require('fs');
const https = require('https');
const http = require('http');
const { URL } = require('url');
const { exec, spawn } = require('child_process');
const proxyManager = require('./proxy-manager');
const v2rayManager = require('./v2ray-manager');

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


// ── yt-dlp 启动参数：优先使用独立版 exe（不依赖 Python）──
function getYtdlpSpawnArgs() {
  // 返回 { cmd, args } 供 spawn() 使用
  // 1) 优先用 bin/yt-dlp.exe（独立版，不依赖外部 Python）
  const localBin = path.join(__dirname, 'bin', 'yt-dlp.exe');
  if (fs.existsSync(localBin)) {
    return { cmd: localBin, args: [] };
  }
  // 2) 回退到 python_embeded 的 python -m yt_dlp
  const pyPath = path.join(__dirname, '..', '..', 'python_embeded', 'python.exe');
  if (fs.existsSync(pyPath)) {
    return { cmd: pyPath, args: ['-m', 'yt_dlp'] };
  }
  // 3) 最后回退到系统命令
  return { cmd: 'yt-dlp', args: [] };
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
    // 按 URL 去重后保存，防止累积重复
    const arr = Array.isArray(items) ? items : [];
    const uniqueItems = Array.from(new Map(arr.map(i => [i.url, i])).values());
    db.kbItems = uniqueItems;
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

  // 启动时检查 yt-dlp 环境
  const ytArgs = getYtdlpSpawnArgs();
  console.log('yt-dlp 启动参数:', ytArgs.cmd, ytArgs.args.join(' '));

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

  // F12 打开开发者工具
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F12') { mainWindow.webContents.toggleDevTools(); }
  });

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
      parsed.searchParams.set('range', '0-99999999999');
      parsed.searchParams.delete('rn');
      parsed.searchParams.delete('obuf');
      parsed.searchParams.delete('start');
      parsed.searchParams.delete('end');
    }
    // 其他 CDN（抖音、B站等）保留原始参数，range/start/end 是分段下载的关键参数
    return parsed.toString();
  } catch (e) {
    return urlStr;
  }
}

// 辅助函数：导出指定域名的 Cookie 给 yt-dlp 使用
// 用 url 参数更精确，且能获取 httpOnly/secure 等完整 cookie
async function exportCookiesForDomain(domain, destPath) {
  try {
    const sess = session.fromPartition('persist:tintin-browser');
    // 先用 domain 查，再尝试用具体 URL 查
    let cookies = await sess.cookies.get({ domain });
    if (cookies.length === 0 && domain.startsWith('.')) {
      // 去掉前导点再查一次
      cookies = await sess.cookies.get({ domain: domain.slice(1) });
    }
    if (cookies.length === 0) {
      console.log(`[cookie] ${domain}: 无 cookie`);
      return false;
    }
    console.log(`[cookie] ${domain}: ${cookies.length} 条 (${cookies.map(c=>c.name).join(', ')})`);

    // 文件不存在时写头，存在时追加
    const isNew = !fs.existsSync(destPath);
    // 写入 Netscape HTTP Cookie File 格式
    let cookieText = isNew ? "# Netscape HTTP Cookie File\n# This file is generated by TinTin Asset Browser\n" : "";
    for (const c of cookies) {
      // yt-dlp 需要: domain flag path secure expiration name value
      const d = c.domain.startsWith('.') ? c.domain : '.' + c.domain;
      const flag = 'TRUE'; // domain 通配
      const path = c.path || '/';
      const secure = c.secure ? 'TRUE' : 'FALSE';
      const exp = c.expirationDate ? Math.round(c.expirationDate) : Math.round(Date.now() / 1000 + 86400 * 30);
      cookieText += `${d}\t${flag}\t${path}\t${secure}\t${exp}\t${c.name}\t${c.value}\n`;
    }
    fs.writeFileSync(destPath, cookieText, { flag: isNew ? 'w' : 'a', encoding: 'utf-8' });
    return true;
  } catch (err) {
    console.warn(`[cookie] 导出 ${domain} 失败:`, err.message);
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

  // 判断是否应该使用 yt-dlp
  // useYtdlp=true 强制用，false 强制不用，undefined/null 按 referer 自动判断
  const isVideoPage = useYtdlp === true || (useYtdlp !== false && referer && isValidVideoPageUrl(referer));

  if (isVideoPage) {
    updateTaskProgress(id, 5, '正在通过 yt-dlp 解析视频...', 0);

    const urlToDownload = isVideoPage ? (referer || fileUrl) : fileUrl;
    
    // 根据域名判断需要导出的 Cookie，实现登录视频下载
	    let cookieDomains = [];
	    if (urlToDownload.includes('youtube.com') || urlToDownload.includes('youtu.be')) {
	      cookieDomains = ['.youtube.com', '.google.com', 'accounts.google.com'];
	    } else if (urlToDownload.includes('bilibili.com')) {
	      cookieDomains = ['.bilibili.com'];
	    } else if (urlToDownload.includes('douyin.com')) {
	      cookieDomains = ['.douyin.com', 'www.douyin.com'];
	    } else if (urlToDownload.includes('zhihu.com')) {
	      cookieDomains = ['.zhihu.com'];
	    }

    const cookieTempPath = finalPath + '.cookies.txt';
    if (cookieDomains.length > 0) {
      for (const d of cookieDomains) {
        await exportCookiesForDomain(d, cookieTempPath);
      }
      // 用完整 URL 再查一次（某些 cookie 绑定具体路径）
      if (urlToDownload.includes('youtube.com')) {
        try {
          const sess = session.fromPartition('persist:tintin-browser');
          const urlCookies = await sess.cookies.get({ url: 'https://www.youtube.com' });
          if (urlCookies.length > 0) {
            const ctext = urlCookies.map(c =>
              `${c.domain.startsWith('.')?c.domain:'.'+c.domain}\tTRUE\t${c.path||'/'}\t${c.secure?'TRUE':'FALSE'}\t${Math.round(c.expirationDate||Date.now()/1000+86400*30)}\t${c.name}\t${c.value}`
            ).join('\n');
            fs.writeFileSync(cookieTempPath,
              "# Netscape HTTP Cookie File\n# Generated from Electron session\n" + ctext, 'utf-8');
            console.log(`[cookie] YouTube URL 查询到 ${urlCookies.length} 条 cookie`);
          }
        } catch(e) { console.warn('[cookie] URL 查询失败:', e.message); }
      }
      // 抖音也查完整 URL
      if (urlToDownload.includes('douyin.com')) {
        try {
          const sess = session.fromPartition('persist:tintin-browser');
          const urlCookies = await sess.cookies.get({ url: 'https://www.douyin.com' });
          if (urlCookies.length > 0) {
            const ctext = urlCookies.map(c =>
              `${c.domain.startsWith('.')?c.domain:'.'+c.domain}\tTRUE\t${c.path||'/'}\t${c.secure?'TRUE':'FALSE'}\t${Math.round(c.expirationDate||Date.now()/1000+86400*30)}\t${c.name}\t${c.value}`
            ).join('\n');
            fs.writeFileSync(cookieTempPath,
              "# Netscape HTTP Cookie File\n# Generated from Electron session\n" + ctext, 'utf-8');
            console.log(`[cookie] 抖音 URL 查询到 ${urlCookies.length} 条 cookie`);
          }
        } catch(e) { console.warn('[cookie] URL 查询失败:', e.message); }
      }
      // 空 cookie 文件不传给 yt-dlp
      if (fs.existsSync(cookieTempPath)) {
        const content = fs.readFileSync(cookieTempPath, 'utf-8');
        const lines = content.split('\n').filter(l => l.trim() && !l.startsWith('#'));
        if (lines.length === 0) fs.unlinkSync(cookieTempPath);
      }
    }

    // 获取 yt-dlp 启动参数（YouTube/抖音 强制用 pip 版，支持解密 Chrome cookie）
    const needsPip = urlToDownload.includes('youtube.com') || urlToDownload.includes('douyin.com');
    let ytdlpBin, ytdlpBaseArgs;
    if (needsPip) {
      const pipPy = path.join(__dirname, '..', '..', 'python_embeded', 'python.exe');
      if (fs.existsSync(pipPy)) {
        ytdlpBin = pipPy; ytdlpBaseArgs = ['-m', 'yt_dlp'];
      } else {
        const r = getYtdlpSpawnArgs(); ytdlpBin = r.cmd; ytdlpBaseArgs = r.args;
      }
    } else {
      const r = getYtdlpSpawnArgs(); ytdlpBin = r.cmd; ytdlpBaseArgs = r.args;
    }
    // cookie 参数：有文件就传，YouTube/抖音 兜底用浏览器 cookie
    let cookieArg = fs.existsSync(cookieTempPath) ? ['--cookies', cookieTempPath] : [];
    if (cookieArg.length === 0 && (urlToDownload.includes('youtube.com') || urlToDownload.includes('douyin.com'))) {
      cookieArg = ['--cookies-from-browser', 'chrome'];
    }
    const proxyArgArr = proxyManager.getYtDlpProxyArgv(db.settings);

	    // 尝试多种格式，依次降级
	    const formatList = ['bv+ba/b', 'best', 'bestvideo+bestaudio/best', 'worst'];
    let lastError = '', lastLog = '';

    for (const fmt of formatList) {
      if (activeDownloads.has(id) && activeDownloads.get(id) === 'cancelled') break;
      updateTaskProgress(id, 5, `正在通过 yt-dlp 下载 (格式: ${fmt})...`, 0);

      // 用 spawn 避免 cmd.exe 引号转义问题（尤其 Windows 路径含空格/特殊字符时）
      const allArgs = [
        ...ytdlpBaseArgs,
        ...cookieArg,
        ...proxyArgArr,
        '--no-warnings',
        '--extractor-retries', '3',
        '--retries', '5',
        // YouTube 防机器人检测：模拟 TV 客户端（反爬最宽松）
        ...(urlToDownload.includes('youtube.com') ? [
          '--extractor-args', 'youtube:player_client=tv_embedded',
          '--user-agent', 'Mozilla/5.0 (PlayStation; PlayStation 5/2.00) AppleWebKit/609.1 (KHTML, like Gecko) Version/16.0 Safari/609.1',
          '--sleep-requests', '2',
        ] : []),
        '-f', fmt,
        '--merge-output-format', 'mp4',
        '-o', finalPath,
        urlToDownload,
      ];

      const result = await new Promise((resolve) => {
        let stderrBuf = '';
        let stdoutBuf = '';
        const child = spawn(ytdlpBin, allArgs, {
          stdio: ['ignore', 'pipe', 'pipe'],
          windowsHide: true,
        });

        const parseProgress = (text) => {
          const match = text.match(/\[download\]\s+(\d+\.\d+)%\s+of\s+([^\s]+)\s+at\s+([^\s]+)/);
          if (match) {
            updateTaskProgress(id, Math.round(parseFloat(match[1])), `下载中 ${match[3]}`, 0);
          }
        };

        child.stdout.on('data', (data) => {
          const s = data.toString();
          stdoutBuf += s;
          parseProgress(s);
        });

        child.stderr.on('data', (data) => {
          const s = data.toString();
          stderrBuf += s;
          parseProgress(s); // yt-dlp 进度输出到 stderr
        });

        child.on('close', (code) => {
          // 清理 Cookie 临时文件
          try { if (fs.existsSync(cookieTempPath)) fs.unlinkSync(cookieTempPath); } catch(e){}

          if (code === 0) {
            let finalSize = 0;
            try { if (fs.existsSync(finalPath)) finalSize = fs.statSync(finalPath).size; } catch(e) {}
            resolve({ success: true, size: finalSize });
          } else {
            // exit code 非零，但文件已成功生成则视为成功（yt-dlp 警告可能触发非零退出）
            let fileCreated = false;
            try { fileCreated = fs.existsSync(finalPath) && fs.statSync(finalPath).size > 0; } catch(e) {}
            if (fileCreated) {
              resolve({ success: true, size: fs.statSync(finalPath).size });
            } else {
              const errLines = (stderrBuf || '').split('\n').filter(l => l.trim() && !l.startsWith('WARNING:'));
              const fullOutput = (stderrBuf + '\n--- stdout ---\n' + stdoutBuf).trim();
              const errMsg = errLines.join('\n').trim() || `exit code ${code}`;
              lastError = errMsg;
              lastLog = fullOutput;
              console.error(`yt-dlp 格式 ${fmt} 下载失败 (exit ${code}):`, fullOutput.slice(0, 1000));
              resolve({ success: false, error: errMsg, log: fullOutput });
            }
          }
        });

        child.on('error', (e) => {
          lastError = e.message;
          resolve({ success: false, error: e.message });
        });

        activeDownloads.set(id, child);
      });

      if (result.success) {
        activeDownloads.delete(id);
        updateTaskSize(id, result.size);
        updateTaskStatus(id, 'completed', 100, result.size);
        return { success: true };
      }
    }

    // 所有格式均失败
    activeDownloads.delete(id);
    console.error('yt-dlp 所有格式尝试均失败:', lastError);
    updateTaskStatus(id, 'failed', 0, 0, '下载失败: ' + lastError, lastLog);
    return { success: false, error: lastError };
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

// 通用：杀掉活跃下载进程（返回是否成功）
function killActiveTask(id) {
  let killed = false;
  if (activeDownloads.has(id)) {
    const t = activeDownloads.get(id);
    if (t.kill) t.kill();
    else if (t.destroy) t.destroy();
    activeDownloads.delete(id);
    killed = true;
  }
  const vid = id + '_video', aid = id + '_audio';
  if (activeDownloads.has(vid)) { try { activeDownloads.get(vid).destroy?.(); } catch{} activeDownloads.delete(vid); killed = true; }
  if (activeDownloads.has(aid)) { try { activeDownloads.get(aid).destroy?.(); } catch{} activeDownloads.delete(aid); killed = true; }
  return killed;
}

ipcMain.handle('cancel-download', (event, id) => {
  // 旧版取消（保留向后兼容，转换为暂停）
  if (killActiveTask(id)) {
    updateTaskStatus(id, 'paused', 0, 0, '已暂停');
    return true;
  }
  return false;
});

// 暂停下载：杀掉进程，保留部分文件，标记为 paused
ipcMain.handle('pause-download', (event, id) => {
  if (killActiveTask(id)) {
    updateTaskStatus(id, 'paused', 0, 0, '已暂停');
    return true;
  }
  return false;
});

// 重新下载：从已保存的任务参数重新启动下载
ipcMain.handle('resume-download', (event, id) => {
  const db = getDatabase();
  const task = db.downloads.find(t => t.id === id);
  if (!task) return false;

  // 重置状态为 downloading
  task.status = 'downloading';
  task.progress = 0;
  task.error = '';
  saveDatabase(db);
  mainWindow.webContents.send('download-list-updated', db.downloads);

  // 构造下载参数并重新启动
  const referer = task.url || '';
  const fileUrl = task.url || '';
  const audioUrl = task.audioUrl || null;

  // 判断是否走 yt-dlp
  const isVideoPage = isValidVideoPageUrl(referer);

  if (isVideoPage) {
    // yt-dlp 路径（YouTube/抖音 强制用 pip 版以支持 Chrome cookie 解密）
    const needsPip = referer.includes('youtube.com') || referer.includes('douyin.com');
    let ytdlpBin, ytdlpBaseArgs;
    if (needsPip) {
      const pipPy = path.join(__dirname, '..', '..', 'python_embeded', 'python.exe');
      if (fs.existsSync(pipPy)) { ytdlpBin = pipPy; ytdlpBaseArgs = ['-m', 'yt_dlp']; }
      else { const r = getYtdlpSpawnArgs(); ytdlpBin = r.cmd; ytdlpBaseArgs = r.args; }
    } else {
      const r = getYtdlpSpawnArgs(); ytdlpBin = r.cmd; ytdlpBaseArgs = r.args;
    }
    const formatList = ['bv+ba/b', 'best', 'bestvideo+bestaudio/best', 'worst'];

    // 导出 Cookie
    let cookieDomains = [];
    if (referer.includes('youtube.com') || referer.includes('youtu.be')) cookieDomains = ['.youtube.com', '.google.com', 'accounts.google.com'];
    else if (referer.includes('bilibili.com')) cookieDomains = ['.bilibili.com'];
    else if (referer.includes('douyin.com')) cookieDomains = ['.douyin.com', 'www.douyin.com'];

    (async () => {
      const cookieTempPath = task.path + '.cookies.txt';
      for (const d of cookieDomains) await exportCookiesForDomain(d, cookieTempPath);
      // 用完整 URL 查 cookie
      if (referer.includes('youtube.com')) {
        try {
          const sess = session.fromPartition('persist:tintin-browser');
          const urlCookies = await sess.cookies.get({ url: 'https://www.youtube.com' });
          if (urlCookies.length > 0) {
            const ctext = urlCookies.map(c =>
              `${c.domain.startsWith('.')?c.domain:'.'+c.domain}\tTRUE\t${c.path||'/'}\t${c.secure?'TRUE':'FALSE'}\t${Math.round(c.expirationDate||Date.now()/1000+86400*30)}\t${c.name}\t${c.value}`
            ).join('\n');
            fs.writeFileSync(cookieTempPath,
              "# Netscape HTTP Cookie File\n# Generated from Electron session\n" + ctext, 'utf-8');
          }
        } catch(e) {}
      }
      if (referer.includes('douyin.com')) {
        try {
          const sess = session.fromPartition('persist:tintin-browser');
          const urlCookies = await sess.cookies.get({ url: 'https://www.douyin.com' });
          if (urlCookies.length > 0) {
            const ctext = urlCookies.map(c =>
              `${c.domain.startsWith('.')?c.domain:'.'+c.domain}\tTRUE\t${c.path||'/'}\t${c.secure?'TRUE':'FALSE'}\t${Math.round(c.expirationDate||Date.now()/1000+86400*30)}\t${c.name}\t${c.value}`
            ).join('\n');
            fs.writeFileSync(cookieTempPath,
              "# Netscape HTTP Cookie File\n# Generated from Electron session\n" + ctext, 'utf-8');
          }
        } catch(e) {}
      }
      if (fs.existsSync(cookieTempPath)) {
        const c = fs.readFileSync(cookieTempPath, 'utf-8');
        if (c.split('\n').filter(l => l.trim() && !l.startsWith('#')).length === 0) fs.unlinkSync(cookieTempPath);
      }
      let cookieArg = fs.existsSync(cookieTempPath) ? ['--cookies', cookieTempPath] : [];
      if (cookieArg.length === 0 && (referer.includes('youtube.com') || referer.includes('douyin.com'))) {
        cookieArg = ['--cookies-from-browser', 'chrome'];
      }
      const proxyArgArr = proxyManager.getYtDlpProxyArgv(db.settings);

      let lastLog = '';
      for (const fmt of formatList) {
        if (activeDownloads.has(id) && activeDownloads.get(id) === 'cancelled') break;
        updateTaskProgress(id, 5, `正在重新下载 (格式: ${fmt})...`, 0);

	        const allArgs = [
	          ...ytdlpBaseArgs, ...cookieArg, ...proxyArgArr,
	          '--no-warnings', '--extractor-retries', '3', '--retries', '5',
          ...(referer.includes('youtube.com') ? [
            '--extractor-args', 'youtube:player_client=tv_embedded',
            '--user-agent', 'Mozilla/5.0 (PlayStation; PlayStation 5/2.00) AppleWebKit/609.1 (KHTML, like Gecko) Version/16.0 Safari/609.1',
            '--sleep-requests', '2',
          ] : []),
	          '-f', fmt, '--merge-output-format', 'mp4',
	          '-o', task.path, referer,
	        ];

        const result = await new Promise((resolve) => {
          const child = spawn(ytdlpBin, allArgs, { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
          let stderrBuf = '', stdoutBuf = '';
          const parseProgress = (text) => {
            const m = text.match(/\[download\]\s+(\d+\.\d+)%\s+of\s+([^\s]+)\s+at\s+([^\s]+)/);
            if (m) updateTaskProgress(id, Math.round(parseFloat(m[1])), `下载中 ${m[3]}`, 0);
          };
          child.stdout.on('data', (d) => { const s = d.toString(); stdoutBuf += s; parseProgress(s); });
          child.stderr.on('data', (d) => { const s = d.toString(); stderrBuf += s; parseProgress(s); });
          child.on('close', (code) => {
            try { if (fs.existsSync(cookieTempPath)) fs.unlinkSync(cookieTempPath); } catch{}
            if (code === 0) {
              let s = 0; try { if (fs.existsSync(task.path)) s = fs.statSync(task.path).size; } catch{}
              resolve({ success: true, size: s });
            } else {
              let created = false; try { created = fs.existsSync(task.path) && fs.statSync(task.path).size > 0; } catch{}
              if (created) { resolve({ success: true, size: fs.statSync(task.path).size }); }
              else {
                const fullLog = (stderrBuf + '\n--- stdout ---\n' + stdoutBuf).trim();
                lastLog = fullLog;
                resolve({ success: false, error: (stderrBuf || '').split('\n').filter(l => l.trim() && !l.startsWith('WARNING:')).join('\n').trim() || `exit ${code}`, log: fullLog });
              }
            }
          });
          child.on('error', (e) => resolve({ success: false, error: e.message }));
          activeDownloads.set(id, child);
        });

        if (result.success) {
          activeDownloads.delete(id);
          updateTaskSize(id, result.size);
          updateTaskStatus(id, 'completed', 100, result.size);
          return;
        }
      }
      activeDownloads.delete(id);
      updateTaskStatus(id, 'failed', 0, 0, '重新下载失败', lastLog);
    })();
    return true;
  } else {
    // 非 yt-dlp 路径：重新走 HTTP 下载
    // 简化处理：对于音视频分离或单文件，重新发起 start-download 逻辑
    updateTaskStatus(id, 'failed', 0, 0, '该任务不支持重新下载');
    return false;
  }
});

// 取消并删除任务：杀掉进程、删除部分文件、标记已取消
ipcMain.handle('cancel-download-item', (event, id) => {
  killActiveTask(id);
  const db = getDatabase();
  const task = db.downloads.find(t => t.id === id);
  if (task) {
    // 删除部分下载的文件
    try { if (fs.existsSync(task.path)) fs.unlinkSync(task.path); } catch{}
    try { if (fs.existsSync(task.path + '.video.tmp')) fs.unlinkSync(task.path + '.video.tmp'); } catch{}
    try { if (fs.existsSync(task.path + '.audio.tmp')) fs.unlinkSync(task.path + '.audio.tmp'); } catch{}
    try { if (fs.existsSync(task.path + '.cookies.txt')) fs.unlinkSync(task.path + '.cookies.txt'); } catch{}
    // 从下载列表中移除
    db.downloads = db.downloads.filter(t => t.id !== id);
    saveDatabase(db);
    mainWindow.webContents.send('download-list-updated', db.downloads);
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

function updateTaskStatus(id, status, progress, size, errorMsg = '', log = '') {
  const db = getDatabase();
  const task = db.downloads.find(t => t.id === id);
  if (task) {
    task.status = status;
    task.progress = progress;
    if (size > 0) task.size = size;
    if (errorMsg) task.error = errorMsg;
    if (log) task.log = log;
    saveDatabase(db);
    if (mainWindow) {
      mainWindow.webContents.send('download-list-updated', db.downloads);
      mainWindow.webContents.send('download-status-change', { id, status, errorMsg });
    }
  }
}

// ═══════════════════════════════════════════════════════════════
//  v2ray 代理 IPC
// ═══════════════════════════════════════════════════════════════

// 设置 Electron 浏览器 webview 的代理（让浏览器走 v2ray）
async function setWebviewProxy(proxyUrl) {
  try {
    const sess = session.fromPartition('persist:tintin-browser');
    if (proxyUrl) {
      // 把 http://127.0.0.1:10809 转为 proxyRules 格式
      const url = new URL(proxyUrl);
      const rules = `http=${url.protocol}//${url.host};https=${url.protocol}//${url.host}`;
      await sess.setProxy({ proxyRules: rules, proxyBypassRules: '<local>' });
      console.log('webview 代理已设置为:', rules);
    } else {
      await sess.setProxy({ proxyRules: 'direct://' });
      console.log('webview 代理已清除');
    }
  } catch (e) {
    console.warn('设置 webview 代理失败:', e.message);
  }
}

// 解析分享链接（用于 UI 预览）
ipcMain.handle('v2ray-parse-link', (event, link) => {
  return v2rayManager.parseShareLink(link);
});

// 下载订阅并解析节点列表
ipcMain.handle('v2ray-fetch-subscription', async (event, subUrl) => {
  try {
    const text = await v2rayManager.downloadSubscription(subUrl);
    const nodes = v2rayManager.parseSubscription(text);
    return { ok: true, nodes };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

// 启动 v2ray（传入节点列表）
ipcMain.handle('v2ray-start', async (event, nodes) => {
  try {
    const proxyUrl = await v2rayManager.start(nodes);
    // 启动后自动设置代理（yt-dlp + webview）
    const db = getDatabase();
    db.settings = { ...db.settings, proxyUrl };
    saveDatabase(db);
    proxyManager.applyProxy(db.settings);
    await setWebviewProxy(proxyUrl);  // webview 也走代理
    return { ok: true, proxyUrl };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

// 停止 v2ray
ipcMain.handle('v2ray-stop', async () => {
  const stopped = v2rayManager.stop();
  // 清除代理设置
  const db = getDatabase();
  if (db.settings && db.settings.proxyUrl && db.settings.proxyUrl.includes('127.0.0.1')) {
    delete db.settings.proxyUrl;
    saveDatabase(db);
    proxyManager.applyProxy(db.settings);
  }
  await setWebviewProxy('');  // 清除 webview 代理
  return { ok: true, stopped };
});

// 检查 v2ray 运行状态
ipcMain.handle('v2ray-status', () => {
  return {
    running: v2rayManager.isRunning(),
    proxyUrl: v2rayManager.getProxyUrl(),
  };
});

// 测试节点延迟（TCP ping，不启动 xray）
ipcMain.handle('v2ray-test-latency', async (event, node) => {
  try {
    const ms = await v2rayManager.testLatency(node);
    return { ok: true, latency: ms };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

// 检查各平台 cookie 状态 + 强制同步
ipcMain.handle('check-cookie-status', async () => {
  const checks = {
    youtube: { domains: ['.youtube.com', '.google.com'], urls: ['https://www.youtube.com'] },
    bilibili: { domains: ['.bilibili.com'], urls: [] },
    douyin: { domains: ['.douyin.com', 'www.douyin.com'], urls: ['https://www.douyin.com'] },
  };
  const result = {};
  const sess = session.fromPartition('persist:tintin-browser');
  for (const [name, cfg] of Object.entries(checks)) {
    try {
      let allCookies = [];
      for (const d of cfg.domains) {
        const c = await sess.cookies.get({ domain: d });
        allCookies = allCookies.concat(c);
      }
      for (const u of cfg.urls) {
        const c = await sess.cookies.get({ url: u });
        allCookies = allCookies.concat(c);
      }
      // 去重
      const unique = Array.from(new Map(allCookies.map(c => [c.name, c])).values());
      result[name] = { count: unique.length, names: unique.map(c => c.name).slice(0, 15) };
    } catch (e) {
      result[name] = { count: 0, error: e.message };
    }
  }
  return result;
});

// 写入调试日志到桌面（方便用户反馈问题）
ipcMain.handle('write-debug-log', (event, filename, content) => {
  try {
    const desktop = path.join(require('os').homedir(), 'Desktop');
    const filePath = path.join(desktop, filename);
    fs.writeFileSync(filePath, content, 'utf-8');
    return { ok: true, path: filePath };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

// 强制导出指定域名 cookie 到文件（供调试/手动同步）
ipcMain.handle('export-cookies-file', async (event, platform) => {
  const domainMap = {
    youtube: ['.youtube.com', '.google.com', 'accounts.google.com'],
    bilibili: ['.bilibili.com'],
    douyin: ['.douyin.com'],
  };
  const domains = domainMap[platform] || [];
  if (domains.length === 0) return { ok: false, error: '未知平台' };
  const destPath = path.join(app.getPath('desktop'), `cookies_${platform}.txt`);
  for (const d of domains) {
    await exportCookiesForDomain(d, destPath);
  }
  return { ok: true, path: destPath };
});
