const { session } = require('electron');
const path = require('path');
const fs = require('fs');
const { exec } = require('child_process');

let isV2rayRunning = false;

function resolveV2rayPath(customPath) {
  if (customPath && fs.existsSync(customPath)) {
    return customPath;
  }
  const { app } = require('electron');
  return app.isPackaged
    ? path.join(process.resourcesPath, 'bin', 'v2rayN', 'v2rayN.exe')
    : path.join(__dirname, 'bin', 'v2rayN', 'v2rayN.exe');
}

function getV2rayPort(v2rayPath) {
  try {
    if (v2rayPath) {
      const guiConfigPath = path.join(path.dirname(v2rayPath), 'guiConfigs', 'guiNConfig.json');
      if (fs.existsSync(guiConfigPath)) {
        const data = JSON.parse(fs.readFileSync(guiConfigPath, 'utf-8'));
        if (data.Inbound && data.Inbound[0] && data.Inbound[0].LocalPort) {
          return data.Inbound[0].LocalPort;
        }
      }
    }
  } catch (e) {
    console.error('解析 v2rayN 端口配置失败:', e);
  }
  return 10808; // 默认端口
}

function startV2rayProcess(v2rayPath) {
  // 暂时关闭自动启动 v2rayN 进程
  console.log('自动启动 v2rayN 进程已禁用');
}

function stopV2rayProcess() {
  // 暂时关闭自动关闭 v2rayN 进程，避免误杀系统中正在运行的其它代理内核（如 xray.exe）
  console.log('自动关闭 v2rayN 进程已禁用，防止强行杀死系统代理核心');
}

/**
 * 应用代理设置到 Electron 会话，并根据状态控制 v2rayN 进程
 * @param {Object} settings 
 */
function applyProxy(settings) {
  const { useV2rayProxy, v2rayPath: dbV2rayPath } = settings;
  const v2rayPath = resolveV2rayPath(dbV2rayPath);
  const webviewSession = session.fromPartition('persist:tintin-browser');
  const defaultSession = session.defaultSession;

  if (useV2rayProxy) {
    const port = getV2rayPort(v2rayPath);
    // 同时配置 HTTP/HTTPS 代理与 SOCKS 代理。HTTP 代理（端口为 socks 端口 + 1，即 10809）用于解决 Chromium 在 SOCKS5 下本地解析 DNS 导致的域名污染问题。
    const proxyRules = `http=127.0.0.1:${port + 1};https=127.0.0.1:${port + 1};socks=127.0.0.1:${port}`;
    console.log(`启用代理: ${proxyRules}`);
    
    webviewSession.setProxy({ mode: 'fixed_servers', proxyRules });
    defaultSession.setProxy({ mode: 'fixed_servers', proxyRules });
    
    webviewSession.closeAllConnections();
    defaultSession.closeAllConnections();
    
    startV2rayProcess(v2rayPath);
  } else {
    console.log('禁用代理，切换为系统代理模式。');
    webviewSession.setProxy({ mode: 'system' });
    defaultSession.setProxy({ mode: 'system' });
    
    webviewSession.closeAllConnections();
    defaultSession.closeAllConnections();
    
    stopV2rayProcess();
  }
}

/**
 * 获取 yt-dlp 代理命令行参数
 * @param {Object} settings 
 * @returns {string}
 */
function getYtDlpProxyArg(settings) {
  const { useV2rayProxy, v2rayPath: dbV2rayPath } = settings;
  if (useV2rayProxy) {
    const v2rayPath = resolveV2rayPath(dbV2rayPath);
    const port = getV2rayPort(v2rayPath);
    return `--proxy "socks5://127.0.0.1:${port}"`;
  }
  return '';
}

function openV2rayN(customPath) {
  const v2rayPath = resolveV2rayPath(customPath);
  if (!v2rayPath || !fs.existsSync(v2rayPath)) {
    console.warn(`v2rayN 路径不存在: ${v2rayPath}`);
    return false;
  }
  const v2rayDir = path.dirname(v2rayPath);
  exec(`"${v2rayPath}"`, { cwd: v2rayDir }, (err) => {
    if (err) {
      console.error('启动 v2rayN 失败:', err);
    }
  });
  return true;
}

/**
 * 在应用退出时执行清理
 */
function shutdown() {
  stopV2rayProcess();
}

module.exports = {
  applyProxy,
  getYtDlpProxyArg,
  resolveV2rayPath,
  openV2rayN,
  shutdown
};

