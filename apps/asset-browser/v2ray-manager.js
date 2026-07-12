/**
 * v2ray 订阅管理器 — 解析订阅/分享链接 → 生成 xray 配置 → 管理进程。
 *
 * 工作流程：
 * 1. 用户输入订阅 URL 或 vless/vmess/ss/trojan 链接
 * 2. 解析出节点信息，生成 xray JSON 配置（本地 SOCKS5 :10808 + HTTP :10809 入站）
 * 3. 启动 xray.exe 子进程
 * 4. 自动设置代理 URL 到 app settings
 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const https = require('https');
const http = require('http');
const { URL } = require('url');

// ── 路径 ───────────────────────────────────────────────────────
const XRAY_BIN = path.join(__dirname, 'bin', 'v2rayN', 'bin', 'xray', 'xray.exe');
const XRAY_CONFIG = path.join(__dirname, 'bin', 'v2rayN', 'bin', 'xray', 'config_generated.json');

// 本地代理端口
const SOCKS_PORT = 10808;
const HTTP_PORT = 10809;
const LOCAL_PROXY = `http://127.0.0.1:${HTTP_PORT}`;

let xrayProcess = null;

// ── 分享链接解析 ─────────────────────────────────────────────

function parseShareLink(link) {
  try {
    const url = new URL(link);
    if (url.protocol === 'vless:') return parseVless(url);
    if (url.protocol === 'vmess:') return parseVmess(link);
    if (url.protocol === 'trojan:') return parseTrojan(url);
    if (url.protocol === 'ss:') return parseSS(url);
  } catch (e) { /* 非标准链接 */ }

  // 尝试 base64 解码后再解析（部分订阅直接返回 base64 编码的单行）
  try {
    const decoded = Buffer.from(link.trim(), 'base64').toString('utf-8');
    if (decoded.startsWith('vless://') || decoded.startsWith('vmess://') ||
        decoded.startsWith('trojan://') || decoded.startsWith('ss://')) {
      return parseShareLink(decoded.trim());
    }
  } catch (e) {}
  return null;
}

function parseVless(url) {
  const params = Object.fromEntries(url.searchParams.entries());
  const host = url.hostname;
  const port = parseInt(url.port, 10) || 443;
  const uuid = url.username;
  const remark = decodeURIComponent(url.hash.replace(/^#/, '')) || 'vless';
  return {
    protocol: 'vless',
    remark, uuid, host, port,
    encryption: params.encryption || 'none',
    flow: params.flow || '',
    security: params.security || 'none',
    sni: params.sni || params.host || host,
    type: params.type || 'tcp',
    headerType: params.headerType || 'none',
    path: params.path || '',
    serviceName: params.serviceName || '',
  };
}

function parseVmess(link) {
  try {
    // vmess 链接是 base64 编码的 JSON
    const b64 = link.replace(/^vmess:\/\//, '');
    const json = JSON.parse(Buffer.from(b64, 'base64').toString('utf-8'));
    return {
      protocol: 'vmess',
      remark: json.ps || 'vmess',
      uuid: json.id,
      host: json.add || json.host,
      port: parseInt(json.port, 10) || 443,
      security: json.security || 'auto',
      sni: json.sni || json.host || json.add,
      type: json.net || 'tcp',
      path: json.path || '',
      tls: json.tls === 'tls' ? 'tls' : 'none',
      aid: json.aid || 0,
    };
  } catch (e) { return null; }
}

function parseTrojan(url) {
  const params = Object.fromEntries(url.searchParams.entries());
  const host = url.hostname;
  const port = parseInt(url.port, 10) || 443;
  const password = url.username;
  const remark = decodeURIComponent(url.hash.replace(/^#/, '')) || 'trojan';
  return {
    protocol: 'trojan',
    remark, password, host, port,
    sni: params.sni || host,
    type: params.type || 'tcp',
    path: params.path || '',
    security: 'tls',
  };
}

function parseSS(url) {
  // ss:// 格式: ss://base64(method:password)@host:port#remark
  // 或 ss://base64(method:password@host:port)#remark
  const params = Object.fromEntries(url.searchParams.entries());
  const raw = url.username ? `${url.username}:${url.password}@${url.hostname}:${url.port}` : '';
  let method = '', password = '', host = '', port = 0, remark = '';

  if (raw) {
    const [mp, hp] = raw.split('@');
    method = mp.split(':')[0] || 'aes-256-gcm';
    password = mp.split(':').slice(1).join(':') || '';
    host = hp?.split(':')[0] || '';
    port = parseInt(hp?.split(':')[1], 10) || 443;
    remark = decodeURIComponent(url.hash.replace(/^#/, '')) || 'ss';
  } else {
    // 全 base64 格式: ss://base64(method:password@host:port)#remark
    const b64 = link => { try { return Buffer.from(link, 'base64').toString('utf-8'); } catch(e) { return ''; } };
    const rest = url.pathname.replace(/^\//, '');
    const decoded = b64(rest);
    if (decoded) {
      const [mp, hp] = decoded.split('@');
      method = mp.split(':')[0] || 'aes-256-gcm';
      password = mp.split(':').slice(1).join(':') || '';
      host = hp?.split(':')[0] || '';
      port = parseInt(hp?.split(':')[1], 10) || 443;
      remark = decodeURIComponent(url.hash.replace(/^#/, '')) || 'ss';
    }
  }
  return { protocol: 'ss', remark, method, password, host, port, path: params.plugin || '' };
}

// ── 订阅下载 ─────────────────────────────────────────────────

function downloadSubscription(url) {
  return new Promise((resolve, reject) => {
    const protocol = url.startsWith('https') ? https : http;
    const req = protocol.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' }, timeout: 15000 }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        req.destroy();
        downloadSubscription(new URL(res.headers.location, url).toString()).then(resolve).catch(reject);
        return;
      }
      let data = '';
      res.on('data', chunk => data += chunk.toString());
      res.on('end', () => resolve(data));
    });
    req.on('error', reject);
    req.end();
  });
}

function parseSubscription(text) {
  // 订阅响应通常是 base64 编码的分享链接列表（每行一个）
  let decoded = '';
  try {
    decoded = Buffer.from(text.trim(), 'base64').toString('utf-8');
  } catch (e) { decoded = text; }

  // 按行分割，每行是一个分享链接
  const lines = decoded.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  const nodes = [];
  for (const line of lines) {
    const node = parseShareLink(line);
    if (node) nodes.push(node);
  }
  return nodes;
}

// ── 生成 xray 配置 ────────────────────────────────────────────

function generateXrayConfig(nodes) {
  if (!nodes || nodes.length === 0) throw new Error('没有可用节点');

  const outbounds = nodes.map((node, i) => {
    const outbound = {
      tag: `proxy-${i}`,
      protocol: node.protocol,
      settings: {},
      streamSettings: { network: node.type || 'tcp' },
      mux: { enabled: false },
    };

    // 各协议 settings
    if (node.protocol === 'vless') {
      outbound.settings = {
        vnext: [{
          address: node.host, port: node.port,
          users: [{ id: node.uuid, encryption: node.encryption || 'none', flow: node.flow || '' }],
        }],
      };
      if (node.security === 'tls' || node.security === 'reality') {
        outbound.streamSettings.security = node.security;
        outbound.streamSettings.tlsSettings = { serverName: node.sni, allowInsecure: false };
        if (node.flow && node.flow.startsWith('xtls-rprx-')) {
          outbound.streamSettings.tlsSettings = { serverName: node.sni, allowInsecure: false, flow: node.flow };
        }
      }
      // 传输层
      if (node.type === 'ws') {
        outbound.streamSettings.wsSettings = { path: node.path || '/', headers: { Host: node.sni } };
      } else if (node.type === 'grpc') {
        outbound.streamSettings.grpcSettings = { serviceName: node.serviceName || '' };
      } else if (node.type === 'kcp') {
        outbound.streamSettings.kcpSettings = { header: { type: node.headerType || 'none' } };
      }
    } else if (node.protocol === 'vmess') {
      outbound.settings = {
        vnext: [{
          address: node.host, port: node.port,
          users: [{ id: node.uuid, security: node.security || 'auto', alterId: node.aid || 0 }],
        }],
      };
      outbound.streamSettings.security = node.tls === 'tls' ? 'tls' : 'none';
      if (node.tls === 'tls') {
        outbound.streamSettings.tlsSettings = { serverName: node.sni || node.host, allowInsecure: false };
      }
      if (node.type === 'ws') {
        outbound.streamSettings.wsSettings = { path: node.path || '/', headers: { Host: node.sni || node.host } };
      } else if (node.type === 'grpc') {
        outbound.streamSettings.grpcSettings = { serviceName: node.path || '' };
      } else if (node.type === 'kcp') {
        outbound.streamSettings.kcpSettings = { header: { type: (node.headerType || 'none') } };
      }
    } else if (node.protocol === 'trojan') {
      outbound.settings = {
        servers: [{ address: node.host, port: node.port, password: node.password }],
      };
      outbound.streamSettings.security = 'tls';
      outbound.streamSettings.tlsSettings = { serverName: node.sni || node.host, allowInsecure: false };
      if (node.type === 'ws') {
        outbound.streamSettings.wsSettings = { path: node.path || '/', headers: { Host: node.sni || node.host } };
      } else if (node.type === 'grpc') {
        outbound.streamSettings.grpcSettings = { serviceName: node.path || '' };
      }
    } else if (node.protocol === 'ss') {
      outbound.settings = {
        servers: [{ address: node.host, port: node.port, method: node.method, password: node.password }],
      };
      if (node.path) {
        // plugin (e.g., obfs)
        outbound.streamSettings.sockopt = { mark: 0 };
      }
    }

    return outbound;
  });

  // 添加直连出站（freedom）和黑洞（blackhole）
  outbounds.push({
    tag: 'direct', protocol: 'freedom', settings: {},
    streamSettings: { network: 'tcp' },
  });
  outbounds.push({
    tag: 'block', protocol: 'blackhole', settings: {},
    streamSettings: { network: 'tcp' },
  });

  return {
    log: { loglevel: 'warning' },
    inbounds: [
      {
        port: SOCKS_PORT, listen: '127.0.0.1',
        protocol: 'socks', tag: 'socks-in',
        settings: { auth: 'noauth', udp: true },
        sniffing: { enabled: true, destOverride: ['http', 'tls'] },
      },
      {
        port: HTTP_PORT, listen: '127.0.0.1',
        protocol: 'http', tag: 'http-in',
        settings: {},
        sniffing: { enabled: true, destOverride: ['http', 'tls'] },
      },
    ],
    outbounds,
    routing: {
      domainStrategy: 'AsIs',
      rules: [
        // 默认走第一个节点
        { type: 'field', inboundTag: ['socks-in', 'http-in'], outboundTag: 'proxy-0' },
        // 内网直连
        { type: 'field', ip: ['geoip:private'], outboundTag: 'direct' },
        { type: 'field', ip: ['geoip:cn'], outboundTag: 'direct' },
        { type: 'field', domain: ['geosite:cn'], outboundTag: 'direct' },
      ],
    },
  };
}

// ── 进程管理 ─────────────────────────────────────────────────

function isRunning() {
  return xrayProcess !== null && !xrayProcess.killed;
}

function getProxyUrl() {
  return isRunning() ? LOCAL_PROXY : '';
}

function start(nodes) {
  return new Promise((resolve, reject) => {
    if (isRunning()) {
      stop();
    }

    if (!fs.existsSync(XRAY_BIN)) {
      return reject(new Error(`xray 未找到: ${XRAY_BIN}`));
    }

    try {
      const config = generateXrayConfig(nodes);
      fs.writeFileSync(XRAY_CONFIG, JSON.stringify(config, null, 2), 'utf-8');
    } catch (e) {
      return reject(new Error(`生成配置失败: ${e.message}`));
    }

    const child = spawn(XRAY_BIN, ['run', '-c', XRAY_CONFIG], {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

    let started = false;
    const timeout = setTimeout(() => {
      if (!started) {
        child.kill();
        reject(new Error('xray 启动超时'));
      }
    }, 8000);

    child.stderr.on('data', (data) => {
      const text = data.toString();
      // xray 启动成功后会在 stderr 输出 "Xray 26.3.27 started"
      if (text.includes('started') || text.includes('Xray')) {
        started = true;
        clearTimeout(timeout);
        xrayProcess = child;
        resolve(LOCAL_PROXY);
      }
    });

    child.on('close', (code) => {
      clearTimeout(timeout);
      xrayProcess = null;
      if (!started) {
        reject(new Error(`xray 退出 (code=${code})`));
      }
    });

    child.on('error', (e) => {
      clearTimeout(timeout);
      xrayProcess = null;
      reject(e);
    });
  });
}

function stop() {
  if (xrayProcess && !xrayProcess.killed) {
    xrayProcess.kill();
    xrayProcess = null;
    return true;
  }
  return false;
}

// ── 导出 ───────────────────────────────────────────────────────

module.exports = {
  parseShareLink,
  parseSubscription,
  downloadSubscription,
  generateXrayConfig,
  start,
  stop,
  isRunning,
  getProxyUrl,
  SOCKS_PORT,
  HTTP_PORT,
  LOCAL_PROXY,
};
