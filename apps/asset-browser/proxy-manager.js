/**
 * 代理管理器 — 为 yt-dlp 提供代理配置。
 *
 * 代理来源（优先级从高到低）：
 * 1. settings.proxyUrl（用户通过 UI 配置）
 * 2. 环境变量 HTTPS_PROXY / HTTP_PROXY / ALL_PROXY
 */

function getProxyUrl(settings) {
  // 1. 用户配置
  if (settings && settings.proxyUrl) {
    const url = settings.proxyUrl.trim();
    if (url) return url;
  }
  // 2. 环境变量
  const env = process.env;
  return env.HTTPS_PROXY || env.https_proxy ||
         env.HTTP_PROXY  || env.http_proxy  ||
         env.ALL_PROXY   || env.all_proxy   || '';
}

function applyProxy(settings) {
  const url = getProxyUrl(settings);
  if (url) {
    // 设置环境变量供子进程（如 yt-dlp）继承
    if (!process.env.HTTPS_PROXY) process.env.HTTPS_PROXY = url;
    if (!process.env.HTTP_PROXY)  process.env.HTTP_PROXY  = url;
  }
}

// 返回 --proxy "url" 字符串（兼容 exec 调用）
function getYtDlpProxyArg(settings) {
  const url = getProxyUrl(settings);
  if (url) return `--proxy "${url}"`;
  return '';
}

// 返回 ['--proxy', 'url'] 数组（供 spawn 使用，避免引号转义）
function getYtDlpProxyArgv(settings) {
  const url = getProxyUrl(settings);
  if (url) return ['--proxy', url];
  return [];
}

function shutdown() {
  // 无需清理
}

module.exports = {
  applyProxy,
  getYtDlpProxyArg,
  getYtDlpProxyArgv,
  shutdown,
};
