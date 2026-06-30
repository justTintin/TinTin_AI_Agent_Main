const { app, BrowserWindow, ipcMain, webContents, dialog } = require('electron');

// 关键：在应用就绪前追加远程调试端口，确保即使被打包为 EXE，Playwright 依然可以通过 9222 端口“附身”操控浏览器
app.commandLine.appendSwitch('remote-debugging-port', '9222');

const path = require('path');
const fs = require('fs');

let mainWindow;
let currentBrowserContext = null;
let activeTask = null;
let isStopping = false;
let activeWebContentsId = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      webviewTag: true
    }
  });

  mainWindow.loadFile('index.html');
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

// 监听所有 webContents 的创建，特别是 webview
app.on('web-contents-created', (event, contents) => {
  if (contents.getType() === 'webview') {
    
    // 拦截弹窗 (在新窗口打开链接)，改为在当前 webview 加载
    contents.setWindowOpenHandler(({ url }) => {
      contents.loadURL(url);
      return { action: 'deny' };
    });

    // 拦截特定协议的跳转 (比如 bytedance://)，防止弹出 "需要新应用打开"
    contents.on('will-navigate', (event, url) => {
      if (url.startsWith('bytedance:')) {
        event.preventDefault();
      }
    });
  }
});

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') app.quit();
});

const { runDouyinAutomation } = require('./automation');

ipcMain.handle('start-task', async (event, taskData) => {
  if (activeTask) {
    return { success: false, message: '已有任务正在运行' };
  }
  
  activeTask = taskData;
  isStopping = false;
  activeWebContentsId = null;

  const sendStatus = (status, message) => {
    if (mainWindow) {
      mainWindow.webContents.send('task-status', { taskName: taskData.taskName, status, message });
    }
  };

  try {
    const webviewId = await mainWindow.webContents.executeJavaScript(`
      new Promise((resolve) => {
        const wv = document.getElementById('wv-${taskData.shopKey}');
        resolve(wv ? wv.getWebContentsId() : null);
      });
    `);

    if (!webviewId) {
      throw new Error(`无法获取目标店铺 [${taskData.shopName}] 的视图容器，请确认界面渲染正常。`);
    }

    const targetWebContents = webContents.fromId(webviewId);
    if (!targetWebContents) {
      throw new Error(`无法找到目标店铺 [${taskData.shopName}] 的底层内容进程。`);
    }
    activeWebContentsId = webviewId;

    await runDouyinAutomation(targetWebContents, taskData, sendStatus, () => isStopping);

    activeTask = null;
    activeWebContentsId = null;
    return { success: true };
  } catch (error) {
    console.error('Error in task:', error);
    activeTask = null;
    activeWebContentsId = null;
    return { success: false, message: error.message };
  }
});

ipcMain.handle('stop-task', async (event) => {
  isStopping = true;
  if (activeWebContentsId) {
    const wc = webContents.fromId(activeWebContentsId);
    if (wc && wc.debugger && wc.debugger.isAttached()) {
      try {
        wc.debugger.detach();
      } catch (e) {}
    }
  }
  activeTask = null;
  activeWebContentsId = null;
  return { success: true };
});

ipcMain.handle('select-directory', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory']
  });
  if (result.canceled) return null;
  return result.filePaths[0];
});

ipcMain.handle('validate-data-dir', async (event, dataDir) => {
  try {
    if (!dataDir || !fs.existsSync(dataDir)) {
      return { success: false, hasSku: false, reason: '目录不存在' };
    }
    const skuPath = path.join(dataDir, 'sku.xlsx');
    return { success: true, hasSku: fs.existsSync(skuPath), skuPath };
  } catch (e) {
    return { success: false, hasSku: false, reason: e.message };
  }
});
