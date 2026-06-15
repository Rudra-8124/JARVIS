# J.A.R.V.I.S. (Just A Rather Very Intelligent System)

J.A.R.V.I.S. is a local voice assistant and HUD (Heads-Up Display) desktop interface for Windows 11, inspired by Iron Man's helmet overlay interface. It operates with local speech-to-text, offline text-to-speech, local LLM-based intent routing, a two-layer memory architecture, and 18 advanced helper skills.

---

## 🚀 Key Features

*   **Iron Man HUD UI**: Frameless, transparent Windows overlay, always-on-top, technical/futuristic typography, and dynamic animated SVG visual states (Idle, Listening, Thinking, Speaking).
*   **Offline Voice Stack**:
    *   **Wake Word Detection**: `openWakeWord` checking for "Hey Jarvis".
    *   **STT (Speech-to-Text)**: Faster Whisper running locally.
    *   **TTS (Text-to-Speech)**: Local Piper engine using `en_US-lessac-medium` model.
*   **Two-Layer Memory System**:
    *   **Layer 1 (Structured)**: SQLite database tracking conversations, user facts (key-value profiles), habit counts, and reminders.
    *   **Layer 2 (Semantic)**: Local ChromaDB vector database storing all turns embedded via Ollama (`nomic-embed-text`).
*   **Local Intent Classifier**: Uses a local Ollama model (`llama3.2:3b`) for classifying complex user queries when regex/keyword matching fails.

---

## 🛠️ Architecture Overview

The system consists of two primary modules:
1.  **Python Backend**: The central engine (`main.py`) handles wake-word loops, audio processing, memory, skill execution (`skills.py`), and hosts a WebSocket server on port `8765`.
2.  **Electron HUD Frontend**: A floating desktop widget overlaying the screen, connecting to the Python server via WebSockets to animate dynamically and output logs.

---

## ⚡ Integrated Skills

J.A.R.V.I.S. registers and routes queries to 18 distinct skills:

### Core Skills
1.  **`open_app`**: Locates and launches local Windows applications (Notepad, VS Code, Chrome, etc.) via Registry lookup.
2.  **`set_volume`**: Adjusts Windows master volume (mute, relative adjustments, or absolute percentage).
3.  **`search_web`**: Queries DuckDuckGo Instant Answer API for a concise 2-sentence summary.
4.  **`get_weather`**: Fetches weather statistics from `wttr.in` (auto-detects city using IP lookup or target name).
5.  **`take_screenshot`**: Captures screen and saves file to the user's Desktop.
6.  **`tell_time`**: Speaks the current system time in a 12-hour format.
7.  **`tell_date`**: Speaks the current day, month, date, and year.
8.  **`set_reminder`**: Creates a Windows Scheduled Task executing a background toaster notification.
9.  **`open_website`**: Opens default browser to specified URLs or mapped shortcuts.
10. **`run_command`**: Runs safe shell commands via Command Prompt, returning stdout summaries.

### Advanced Skills
11. **`get_news_briefing`**: Parses the BBC News RSS feed and reads the top 5 headlines aloud.
12. **`play_music`**: Searches and plays requested tracks on Spotify (via spotipy client credentials) or local Music folder matching files (via VLC), falling back to YouTube.
13. **`read_emails`**: Connects to Gmail IMAP, securely reading only senders and subjects of unread messages.
14. **`run_python_file`**: Executes a local `.py` script and returns the first 300 characters of output.
15. **`summarize_file`**: Reads plain text or `.pdf` (using PyMuPDF) and summarizes contents in 3 sentences using local Ollama models.
16. **`smart_home`**: POSTs service controls to local Home Assistant REST endpoints (`/api/services/light` or `switch`).
17. **`system_report`**: Reports CPU%, RAM%, Disk%, process counts, and NVIDIA GPU temperature (via `nvidia-smi`).
18. **`set_alarm`**: Parses time using `dateparser` and schedules a Windows Task executing a beep pattern and alert dialog.

---

## ⚙️ Configuration Setup

Configure credentials and API tokens inside the global configuration file located at `C:\Users\<Username>\.jarvis\config.json`:

```json
{
    "ollama_model": "llama3.2:3b",
    "whisper_model_size": "base",
    "tts_voice": "en_US-lessac-medium",
    "websocket_port": 8765,
    "conversation_history_limit": 20,
    "spotify_client_id": "YOUR_SPOTIFY_CLIENT_ID",
    "spotify_client_secret": "YOUR_SPOTIFY_CLIENT_SECRET",
    "spotify_redirect_uri": "http://localhost:8888/callback",
    "gmail_user": "your_email@gmail.com",
    "gmail_password": "your_app_password",
    "ha_token": "YOUR_HOME_ASSISTANT_LONG_LIVED_TOKEN",
    "ha_url": "http://localhost:8123"
}
```

---

## 🏃 Getting Started

### 1. Requirements & Dependencies
Ensure you have Python 3.10+ installed and install all dependencies:
```bash
pip install -r requirements.txt
```

### 2. Ollama Setup
Install [Ollama](https://ollama.com) and pull models:
```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### 3. Run JARVIS Backend
Start the central Python backend:
```bash
python main.py
```

### 4. Run Electron HUD
In a separate terminal, navigate to the `hud-desktop` directory, install node modules, and start the HUD overlay:
```bash
cd hud-desktop
npm install
npm start
```

---

## 🧪 Testing & Verification

A diagnostic verification test suite is included to validate skills, parameters, error boundaries, and intent router routing:

```bash
python test_skills.py
```