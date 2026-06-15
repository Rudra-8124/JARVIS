const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
    // Subscriptions
    onTelemetryUpdate: (callback) => {
        ipcRenderer.on('telemetry-update', (event, data) => callback(data));
    },
    onAlwaysOnTopChanged: (callback) => {
        ipcRenderer.on('always-on-top-changed', (event, state) => callback(state));
    },
    
    // Commands
    minimizeToTray: () => {
        ipcRenderer.send('window-minimize-to-tray');
    },
    showContextMenu: () => {
        ipcRenderer.send('show-context-menu');
    }
});
