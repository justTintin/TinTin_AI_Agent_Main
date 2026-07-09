const { session } = require('electron');
const path = require('path');
const fs = require('fs');
const { exec } = require('child_process');

let isV2rayRunning = false;

function resolveV2rayPath(customPath) {
  return ''; // v2rayN 已移除
}

function getV2rayPort(v2rayPath) {
  return 0; // v2rayN 已移除
}

function startV2rayProcess(v2rayPath) {
  // v2rayN 已移除
}

function stopV2rayProcess() {
  // v2rayN 已移除
}

/**
 * 应用代理设置到 Electron 会话 —— v2rayN 已移除，代理功能已禁用
 */
function applyProxy(settings) {
  // v2rayN 已移除，不做任何代理设置
  console.log('代理功能已禁用（v2rayN 已移除）');
}

/**
 * 获取 yt-dlp 代理命令行参数
 */
function getYtDlpProxyArg(settings) {
  return ''; // v2rayN 已移除，不使用代理
}

function openV2rayN(customPath) {
  console.warn('v2rayN 已移除，无法打开');
  return false;
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

