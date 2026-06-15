const { app, BrowserWindow, Tray, Menu, ipcMain, screen, nativeImage } = require('electron');
const path = require('path');
const os = require('os');
const fs = require('fs');
const pidusage = require('pidusage');
const AutoLaunch = require('auto-launch');

let mainWindow = null;
let tray = null;
const startTime = Date.now();

// Calculate CPU Usage Ticks
let lastCpuTicks = getCPUTicks();

function getCPUTicks() {
    const cpus = os.cpus();
    let idle = 0;
    let total = 0;
    for (const cpu of cpus) {
        for (const type in cpu.times) {
            total += cpu.times[type];
        }
        idle += cpu.times.idle;
    }
    return { idle, total };
}

function getSystemCPU() {
    const currentTicks = getCPUTicks();
    const idleDifference = currentTicks.idle - lastCpuTicks.idle;
    const totalDifference = currentTicks.total - lastCpuTicks.total;
    lastCpuTicks = currentTicks;

    if (totalDifference === 0) return 0;
    return Math.round((1 - idleDifference / totalDifference) * 100);
}

// Read Ollama Config
function getOllamaModel() {
    try {
        const configPath = path.join(os.homedir(), '.jarvis', 'config.json');
        if (fs.existsSync(configPath)) {
            const configData = JSON.parse(fs.readFileSync(configPath, 'utf8'));
            return configData.ollama_model || 'llama3.2:3b';
        }
    } catch (e) {
        console.error('Error reading JARVIS config:', e);
    }
    return 'llama3.2:3b';
}

// Format Uptime Duration
function formatDuration(ms) {
    const totalSecs = Math.floor(ms / 1000);
    const hrs = String(Math.floor(totalSecs / 3600)).padStart(2, '0');
    const mins = String(Math.floor((totalSecs % 3600) / 60)).padStart(2, '0');
    const secs = String(totalSecs % 60).padStart(2, '0');
    return `${hrs}:${mins}:${secs}`;
}

// Create base64 blue circle tray icon
function createTrayIcon() {
    const base64Icon = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAAZ0lEQVQ4T2NkoDJgpFL5j0r1M5KoGKTBYDHIg8FigAeDxQAPBpYFjD9g/IFlASPjDxj/wLKAgfEHkH9gWcA4fAHjDywLGL9jxYk0i/+pZAHjDzT/jSTFIKpiqE0/qJQgqZSDqFJMlQoAk+w8L5Fv/pMAAAAASUVORK5CYII=';
    return nativeImage.createFromDataURL(base64Icon);
}

function resetWindowPosition() {
    if (!mainWindow) return;
    const primaryDisplay = screen.getPrimaryDisplay();
    const { width, height } = primaryDisplay.workAreaSize;
    const windowWidth = 480;
    const windowHeight = 640;
    const x = width - windowWidth - 20;
    const y = height - windowHeight - 20;
    mainWindow.setBounds({ x, y, width: windowWidth, height: windowHeight });
}

function createWindow() {
    const primaryDisplay = screen.getPrimaryDisplay();
    const { width, height } = primaryDisplay.workAreaSize;
    
    const windowWidth = 480;
    const windowHeight = 640;
    
    // Position bottom-right by default
    const x = width - windowWidth - 20;
    const y = height - windowHeight - 20;

    mainWindow = new BrowserWindow({
        width: windowWidth,
        height: windowHeight,
        x: x,
        y: y,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        resizable: false,
        maximizable: false,
        skipTaskbar: false,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false
        }
    });

    mainWindow.loadFile('renderer.html');

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

function createTray() {
    tray = new Tray(createTrayIcon());
    const contextMenu = Menu.buildFromTemplate([
        {
            label: 'Open HUD',
            click: () => {
                if (mainWindow) {
                    mainWindow.show();
                } else {
                    createWindow();
                }
            }
        },
        {
            label: 'Always on Top',
            type: 'checkbox',
            checked: true,
            click: (item) => {
                if (mainWindow) {
                    mainWindow.setAlwaysOnTop(item.checked);
                    mainWindow.webContents.send('always-on-top-changed', item.checked);
                }
            }
        },
        {
            label: 'Reset Position',
            click: () => {
                resetWindowPosition();
            }
        },
        { type: 'separator' },
        {
            label: 'Quit J.A.R.V.I.S. HUD',
            click: () => {
                app.isQuiting = true;
                app.quit();
            }
        }
    ]);
    
    tray.setToolTip('J.A.R.V.I.S. Desktop HUD');
    tray.setContextMenu(contextMenu);
    
    tray.on('double-click', () => {
        if (mainWindow) {
            mainWindow.show();
        }
    });
}

// Auto-Launch Setup
function setupAutoLaunch() {
    if (app.isPackaged) {
        const jarvisAutoLaunch = new AutoLaunch({
            name: 'JarvisHUD',
            path: app.getPath('exe'),
        });
        jarvisAutoLaunch.isEnabled().then((isEnabled) => {
            if (!isEnabled) {
                jarvisAutoLaunch.enable().catch(err => console.error('AutoLaunch error:', err));
            }
        });
    }
}

app.whenReady().then(() => {
    createWindow();
    createTray();
    setupAutoLaunch();

    // Stats loop (2 seconds)
    setInterval(async () => {
        if (!mainWindow) return;
        
        try {
            // Memory stats
            const totalMem = os.totalmem();
            const freeMem = os.freemem();
            const systemRam = Math.round(((totalMem - freeMem) / totalMem) * 100);

            // CPU stats
            const systemCpu = getSystemCPU();

            // Ollama settings
            const ollamaModel = getOllamaModel();

            // Uptime
            const appUptime = formatDuration(Date.now() - startTime);

            // Send telemetry package
            mainWindow.webContents.send('telemetry-update', {
                cpu: systemCpu,
                ram: systemRam,
                model: ollamaModel,
                uptime: appUptime
            });
        } catch (err) {
            console.error('Telemetry gather error:', err);
        }
    }, 2000);

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

// Context Menu Trigger from Renderer
ipcMain.on('show-context-menu', (event) => {
    const template = [
        {
            label: 'Always on Top',
            type: 'checkbox',
            checked: mainWindow.isAlwaysOnTop(),
            click: (item) => {
                mainWindow.setAlwaysOnTop(item.checked);
                event.sender.send('always-on-top-changed', item.checked);
            }
        },
        {
            label: 'Reset Position',
            click: () => {
                resetWindowPosition();
            }
        },
        { type: 'separator' },
        {
            label: 'Minimize to Tray',
            click: () => {
                mainWindow.hide();
            }
        },
        {
            label: 'Quit',
            click: () => {
                app.isQuiting = true;
                app.quit();
            }
        }
    ];
    const menu = Menu.buildFromTemplate(template);
    menu.popup(BrowserWindow.fromWebContents(event.sender));
});

// Window Control actions
ipcMain.on('window-minimize-to-tray', () => {
    if (mainWindow) {
        mainWindow.hide();
    }
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});
