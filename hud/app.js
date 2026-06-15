// J.A.R.V.I.S. HUD Interface Logic

let socket = null;
let reconnectTimer = null;
let currentConfig = {};
let currentTab = 'hud-tab';

// Configuration parameters
const WS_PORT = 8765;
const WS_URL = `ws://localhost:${WS_PORT}`;

// On page load
document.addEventListener('DOMContentLoaded', () => {
    // Start local clock
    startClock();
    
    // Check URL hash for deep-linked tabs (e.g., #settings)
    handleHashLink();
    
    // Connect to WebSocket server
    connectWebSocket();
    
    // Listen for hash changes
    window.addEventListener('hashchange', handleHashLink);
});

// Resilient WebSocket connection
function connectWebSocket() {
    console.log(`Connecting to JARVIS WebSocket at ${WS_URL}...`);
    updateConnectionStatus('connecting', 'SYS_CONN: SEARCHING...');
    
    try {
        socket = new WebSocket(WS_URL);
        
        socket.onopen = () => {
            console.log('Connected to JARVIS WebSocket server!');
            updateConnectionStatus('connected', 'SYS_CONN: ONLINE');
            clearTimeout(reconnectTimer);
            
            // Request configurations and history logs immediately
            requestConfig();
            requestHistory();
        };
        
        socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleServerMessage(data);
            } catch (e) {
                console.error('Failed to parse incoming WS message:', e);
            }
        };
        
        socket.onclose = () => {
            console.log('Disconnected from JARVIS WebSocket server.');
            updateConnectionStatus('disconnected', 'SYS_CONN: OFFLINE');
            // Try to reconnect in 3 seconds
            clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(connectWebSocket, 3000);
        };
        
        socket.onerror = (error) => {
            console.error('WebSocket Error:', error);
            socket.close();
        };
        
    } catch (e) {
        console.error('Failed to establish WebSocket:', e);
        updateConnectionStatus('disconnected', 'SYS_CONN: ERROR');
        reconnectTimer = setTimeout(connectWebSocket, 3000);
    }
}

// Update UI connection indicator
function updateConnectionStatus(state, label) {
    const dot = document.getElementById('connection-dot');
    const statusLabel = document.getElementById('connection-label font-tech') || document.querySelector('.system-status span:last-child');
    const sysWSLabel = document.getElementById('sys-websocket-status');
    
    if (dot) {
        dot.className = 'status-indicator'; // Reset classes
        dot.classList.add(state);
    }
    
    if (statusLabel) {
        statusLabel.textContent = label;
    }
    
    if (sysWSLabel) {
        if (state === 'connected') {
            sysWSLabel.textContent = 'ONLINE (PORT 8765)';
            sysWSLabel.style.color = '#00ff88';
        } else if (state === 'connecting') {
            sysWSLabel.textContent = 'CONNECTING...';
            sysWSLabel.style.color = '#ffaa00';
        } else {
            sysWSLabel.textContent = 'OFFLINE (RETRYING)';
            sysWSLabel.style.color = '#ff3366';
        }
    }
}

// Handle incoming server messages
function handleServerMessage(data) {
    // 1. Handle State Change events (broadcasted real-time)
    if (data.state) {
        const state = data.state.toLowerCase();
        document.body.dataset.state = state;
        updateStatusDisplay(state, data.text || '');
    }
    
    // 2. Handle configuration data reply
    if (data.type === 'config') {
        currentConfig = data.config;
        populateSettingsForm(data.config);
    }
    
    // 3. Handle configuration update acknowledgment
    if (data.type === 'update_config_success') {
        currentConfig = data.config;
        populateSettingsForm(data.config);
        flashSaveButtonSuccess();
        // Request history refresh as history limits might have changed
        requestHistory();
    }
    
    // 4. Handle history log reply
    if (data.type === 'history') {
        renderHistory(data.history);
    }
}

// Update the reactor status description and text transcripts
function updateStatusDisplay(state, speakingText) {
    const title = document.getElementById('status-title');
    const desc = document.getElementById('status-message');
    const transcriptBox = document.getElementById('transcript-box');
    const transcriptText = document.getElementById('transcript-text');
    
    // Hide transcription box by default unless speaking
    if (transcriptBox) {
        transcriptBox.classList.add('hidden');
    }
    
    switch(state) {
        case 'idle':
            title.textContent = 'STATUS: STANDBY';
            title.style.color = 'var(--color-idle)';
            desc.textContent = "Standing by. Say 'Hey Jarvis' or type a command to trigger.";
            break;
            
        case 'listening':
            title.textContent = 'STATUS: LISTENING';
            title.style.color = 'var(--color-listening)';
            desc.textContent = "Listening to your voice command... Speak now, sir.";
            break;
            
        case 'thinking':
            title.textContent = 'STATUS: COMPUTING';
            title.style.color = 'var(--color-thinking)';
            desc.textContent = "Analyzing command request and executing skills...";
            break;
            
        case 'speaking':
            title.textContent = 'STATUS: COMMUNICATING';
            title.style.color = 'var(--color-speaking)';
            desc.textContent = "Synthesizing voice response output...";
            
            if (transcriptBox && transcriptText && speakingText) {
                transcriptBox.classList.remove('hidden');
                transcriptText.textContent = `"${speakingText}"`;
            }
            break;
            
        default:
            title.textContent = 'STATUS: STANDBY';
            desc.textContent = "Awaiting voice trigger 'Hey Jarvis'...";
    }
}

// Request configuration parameters from Python
function requestConfig() {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'get_config' }));
    }
}

// Request session history from Python
function requestHistory() {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'get_history' }));
    }
}

// Populate config panel fields
function populateSettingsForm(config) {
    document.getElementById('config-ollama-model').value = config.ollama_model || 'llama3.2:3b';
    document.getElementById('config-whisper-size').value = config.whisper_model_size || 'base';
    document.getElementById('config-tts-voice').value = config.tts_voice || 'en_US-lessac-medium';
    
    const portInput = document.getElementById('config-port');
    const limitInput = document.getElementById('config-limit');
    const sysPortLabel = document.getElementById('sys-port');
    
    if (portInput) portInput.value = config.websocket_port || 8765;
    if (limitInput) limitInput.value = config.conversation_history_limit || 20;
    if (sysPortLabel) sysPortLabel.textContent = config.websocket_port || 8765;
}

// Submit setting updates to server
function saveSettings(event) {
    event.preventDefault();
    
    const updatedConfig = {
        ollama_model: document.getElementById('config-ollama-model').value,
        whisper_model_size: document.getElementById('config-whisper-size').value,
        tts_voice: document.getElementById('config-tts-voice').value,
        websocket_port: parseInt(document.getElementById('config-port').value),
        conversation_history_limit: parseInt(document.getElementById('config-limit').value)
    };
    
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            type: 'update_config',
            config: updatedConfig
        }));
        
        const btn = document.getElementById('save-settings-btn');
        btn.textContent = 'APPLYING...';
        btn.disabled = true;
    }
}

// Flash success indicator on apply settings
function flashSaveButtonSuccess() {
    const btn = document.getElementById('save-settings-btn');
    if (btn) {
        btn.textContent = 'SETTINGS_APPLIED';
        btn.style.borderColor = '#00ff88';
        btn.style.color = '#00ff88';
        btn.style.background = 'rgba(0, 255, 136, 0.1)';
        
        setTimeout(() => {
            btn.textContent = 'APPLY_SETTINGS';
            btn.style.borderColor = 'var(--theme-color)';
            btn.style.color = 'var(--theme-color)';
            btn.style.background = '';
            btn.disabled = false;
        }, 1500);
    }
}

// Submit a text query directly to JARVIS
function sendCommand(event) {
    event.preventDefault();
    const input = document.getElementById('terminal-input');
    const text = input.value.trim();
    
    if (!text) return;
    
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            type: 'command',
            text: text
        }));
        console.log(`HUD command sent to server: "${text}"`);
        input.value = '';
        
        // Optimistically show thinking state immediately
        document.body.dataset.state = 'thinking';
        updateStatusDisplay('thinking');
        
        // Auto pull history records shortly after to show new exchanges
        setTimeout(requestHistory, 1500);
    } else {
        alert('J.A.R.V.I.S. is currently offline, sir.');
    }
}

// Render history chat log
function renderHistory(history) {
    const container = document.getElementById('history-log');
    if (!container) return;
    
    container.innerHTML = '';
    
    if (!history || history.length === 0) {
        container.innerHTML = '<div class="empty-history font-tech">NO_RECORDS_AVAILABLE</div>';
        return;
    }
    
    history.forEach(msg => {
        const bubble = document.createElement('div');
        const roleClass = msg.role === 'user' ? 'user' : 'assistant';
        const senderName = msg.role === 'user' ? 'USER_QUERY' : 'JARVIS_SYS';
        
        bubble.className = `chat-bubble ${roleClass}`;
        
        const sender = document.createElement('span');
        sender.className = 'bubble-sender font-tech';
        sender.textContent = senderName;
        
        const textNode = document.createElement('p');
        textNode.textContent = msg.content;
        
        bubble.appendChild(sender);
        bubble.appendChild(textNode);
        container.appendChild(bubble);
    });
    
    // Auto-scroll to bottom of logs
    container.scrollTop = container.scrollHeight;
}

// Manual history refresh
function refreshHistory() {
    requestHistory();
}

// Swap tabs
function switchTab(tabId) {
    currentTab = tabId;
    
    // Remove active state from all tabs and contents
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    
    // Activate clicked tab
    const activeBtn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
    const activeContent = document.getElementById(tabId);
    
    if (activeBtn) activeBtn.classList.add('active');
    if (activeContent) activeContent.classList.add('active');
    
    // Sync URL hash
    if (tabId === 'settings-tab') {
        window.location.hash = 'settings';
        requestConfig(); // Refresh config panel values
    } else if (tabId === 'history-tab') {
        window.location.hash = 'history';
        requestHistory(); // Refresh history panel
    } else {
        window.location.hash = '';
    }
}

// Deep link navigation routing
function handleHashLink() {
    const hash = window.location.hash;
    if (hash === '#settings') {
        switchTab('settings-tab');
    } else if (hash === '#history') {
        switchTab('history-tab');
    } else {
        switchTab('hud-tab');
    }
}

// Clock logic
function startClock() {
    const clockEl = document.getElementById('current-time');
    if (!clockEl) return;
    
    function update() {
        const now = new Date();
        const hrs = String(now.getHours()).padStart(2, '0');
        const mins = String(now.getMinutes()).padStart(2, '0');
        const secs = String(now.getSeconds()).padStart(2, '0');
        clockEl.textContent = `${hrs}:${mins}:${secs} LCL`;
    }
    
    update();
    setInterval(update, 1000);
}
