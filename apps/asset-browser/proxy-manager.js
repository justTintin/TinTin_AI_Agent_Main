/**
 * 代理管理器（代理功能已移除）。
 *
 * 保留空操作接口供 main.js 调用，避免引用断裂。
 * 如需恢复代理支持，在此重新实现。
 */

function applyProxy(_settings) {
  // 代理功能已移除，不做任何设置
}

function getYtDlpProxyArg(_settings) {
  return '';
}

function shutdown() {
  // 无需清理
}

module.exports = {
  applyProxy,
  getYtDlpProxyArg,
  shutdown,
};
