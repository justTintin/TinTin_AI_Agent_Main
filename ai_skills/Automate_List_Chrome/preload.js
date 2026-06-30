const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  startTask: (taskData) => ipcRenderer.invoke('start-task', taskData),
  stopTask: () => ipcRenderer.invoke('stop-task'),
  validateDataDir: (dataDir) => ipcRenderer.invoke('validate-data-dir', dataDir),
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  onTaskStatus: (callback) => ipcRenderer.on('task-status', (event, ...args) => callback(...args)),
});
