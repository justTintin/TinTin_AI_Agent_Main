const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  // Database Creators
  getCreators: () => ipcRenderer.invoke('db-get-creators'),
  addCreator: (creator) => ipcRenderer.invoke('db-add-creator', creator),
  deleteCreator: (id, platform) => ipcRenderer.invoke('db-delete-creator', { id, platform }),

  // Database Settings
  getSettings: () => ipcRenderer.invoke('db-get-settings'),
  getDownloadDirs: () => ipcRenderer.invoke('db-get-download-dirs'),
  saveSettings: (settings) => ipcRenderer.invoke('db-save-settings', settings),
  addDownloadDir: (dir) => ipcRenderer.invoke('db-add-download-dir', dir),
  selectDownloadDir: () => ipcRenderer.invoke('select-download-dir'),

  // Database Downloads
  getDownloads: () => ipcRenderer.invoke('db-get-downloads'),
  clearDownloads: () => ipcRenderer.invoke('db-clear-downloads'),

  // File System Helpers
  openFileFolder: (filePath) => ipcRenderer.invoke('open-file-folder', filePath),
  openPath: (dirPath) => ipcRenderer.invoke('open-path', dirPath),
  deleteLocalFiles: (paths) => ipcRenderer.invoke('delete-local-files', paths),
  enqueueMaterialImport: (paths) => ipcRenderer.invoke('enqueue-material-import', paths),

  // studio 集成：读取选题握手（关键词/搜索页/下载目录）
  getHandoff: () => ipcRenderer.invoke('get-handoff'),
  // studio 集成：把同步到的关注/收藏样本追加进「我的知识库」清单
  appendKbManifest: (entry) => ipcRenderer.invoke('append-kb-manifest', entry),
  // 热点追踪：把今日热榜快照写入清单
  appendHotspotManifest: (items) => ipcRenderer.invoke('append-hotspot-manifest', items),
  // 收藏记录持久化
  saveKbItems: (items) => ipcRenderer.invoke('save-kb-items', items),
  loadKbItems: () => ipcRenderer.invoke('load-kb-items'),

  // Downloading
  startDownload: (downloadInfo) => ipcRenderer.invoke('start-download', downloadInfo),
  cancelDownload: (id) => ipcRenderer.invoke('cancel-download', id),
  pauseDownload: (id) => ipcRenderer.invoke('pause-download', id),
  resumeDownload: (id) => ipcRenderer.invoke('resume-download', id),
  cancelDownloadItem: (id) => ipcRenderer.invoke('cancel-download-item', id),
  saveTextFile: (data) => ipcRenderer.invoke('save-text-file', data),
  checkLoginStatus: () => ipcRenderer.invoke('check-login-status'),
  getDailyAssets: () => ipcRenderer.invoke('get-daily-assets'),

  // Receive Download Events
  onDownloadListUpdated: (callback) => {
    ipcRenderer.removeAllListeners('download-list-updated');
    ipcRenderer.on('download-list-updated', (event, list) => callback(list));
  },
  onDownloadProgressUpdate: (callback) => {
    ipcRenderer.removeAllListeners('download-progress-update');
    ipcRenderer.on('download-progress-update', (event, data) => callback(data));
  },
  onDownloadStatusChange: (callback) => {
    ipcRenderer.removeAllListeners('download-status-change');
    ipcRenderer.on('download-status-change', (event, data) => callback(data));
  },
  onWebviewMediaSniffed: (callback) => {
    ipcRenderer.removeAllListeners('webview-media-sniffed');
    ipcRenderer.on('webview-media-sniffed', (event, asset) => callback(asset));
  },
  onWebviewOpenUrl: (callback) => {
    ipcRenderer.removeAllListeners('webview-open-url');
    ipcRenderer.on('webview-open-url', (event, url) => callback(url));
  },

  onHandoffUpdated: (callback) => {
    ipcRenderer.removeAllListeners('handoff-updated');
    ipcRenderer.on('handoff-updated', (event, handoff) => callback(handoff));
  },

  // v2ray 代理
  v2rayParseLink: (link) => ipcRenderer.invoke('v2ray-parse-link', link),
  v2rayFetchSubscription: (subUrl) => ipcRenderer.invoke('v2ray-fetch-subscription', subUrl),
  v2rayStart: (nodes) => ipcRenderer.invoke('v2ray-start', nodes),
  v2rayStop: () => ipcRenderer.invoke('v2ray-stop'),
  v2rayStatus: () => ipcRenderer.invoke('v2ray-status'),
  v2rayTestLatency: (node) => ipcRenderer.invoke('v2ray-test-latency', node),
  checkCookieStatus: () => ipcRenderer.invoke('check-cookie-status'),
  exportCookiesFile: (platform) => ipcRenderer.invoke('export-cookies-file', platform),
  writeDebugLog: (filename, content) => ipcRenderer.invoke('write-debug-log', filename, content),
  douyinDownload: (params) => ipcRenderer.invoke('douyin-download', params),

});
