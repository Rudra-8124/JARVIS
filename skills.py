import os
import re
import sys
import json
import logging
import datetime
import subprocess
import webbrowser
import urllib.parse
import requests

logger = logging.getLogger("jarvis")

# =====================================================================
# CORE SKILLS IMPLEMENTATIONS
# =====================================================================

def find_executable(app_name):
    """
    Locates the path of the executable for common applications on Windows 11.
    Searches the registry (App Paths), common directories, and PATH fallback.
    """
    import winreg
    
    direct_execs = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "explorer": "explorer.exe",
        "task manager": "taskmgr.exe",
        "taskmgr": "taskmgr.exe",
    }
    
    name_lower = app_name.lower().strip()
    if name_lower in direct_execs:
        return direct_execs[name_lower]
        
    # Paths to query in Windows registry
    paths_to_check = [
        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name_lower}.exe",
        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name_lower}",
    ]
    
    # Check common name variations
    app_mappings = {
        "chrome": "chrome.exe",
        "firefox": "firefox.exe",
        "vscode": "code.exe",
        "spotify": "Spotify.exe",
    }
    
    exe_name = app_mappings.get(name_lower, f"{name_lower}.exe")
    paths_to_check.append(rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}")
    
    # Check registry under HKLM and HKCU
    for path in paths_to_check:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(root, path)
                try:
                    val, _ = winreg.QueryValueEx(key, "")
                except Exception:
                    val = winreg.QueryValue(key, "")
                winreg.CloseKey(key)
                if val and os.path.exists(val):
                    return val
            except FileNotFoundError:
                continue
                
    # Search common system directories
    user_home = os.path.expanduser("~")
    local_app_data = os.environ.get("LOCALAPPDATA", os.path.join(user_home, "AppData", "Local"))
    roaming_app_data = os.environ.get("APPDATA", os.path.join(user_home, "AppData", "Roaming"))
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    
    common_search_paths = {
        "chrome": [
            os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
        ],
        "firefox": [
            os.path.join(program_files, "Mozilla Firefox", "firefox.exe"),
            os.path.join(program_files_x86, "Mozilla Firefox", "firefox.exe"),
        ],
        "vscode": [
            os.path.join(local_app_data, "Programs", "Microsoft VS Code", "Code.exe"),
            os.path.join(program_files, "Microsoft VS Code", "Code.exe"),
        ],
        "spotify": [
            os.path.join(roaming_app_data, "Spotify", "Spotify.exe"),
            os.path.join(local_app_data, "Microsoft", "WindowsApps", "Spotify.exe"),
        ]
    }
    
    if name_lower in common_search_paths:
        for p in common_search_paths[name_lower]:
            if os.path.exists(p):
                return p
                
    # Direct command triggers if registered in Windows path
    if name_lower == "vscode":
        return "code"
    elif name_lower == "spotify":
        return "spotify"
        
    return None

def open_app(name: str):
    """
    1. open_app(name: str)
    Locates and launches the specified application.
    """
    executable = find_executable(name)
    if not executable:
        return f"I could not find the application {name} on your computer, sir."
        
    try:
        subprocess.Popen(executable, shell=True)
        return f"Opening {name}, sir."
    except Exception as e:
        logger.error(f"Error opening application {name}: {e}")
        return f"I encountered an error trying to open {name}, sir."

def set_volume(level: int):
    """
    2. set_volume(level: int)
    Adjusts the master volume of Windows 11.
    Values: -1 (mute), -2 (down 20%), -3 (up 20%), or 0-100 (percentage).
    """
    try:
        from pycaw.pycaw import AudioUtilities
        
        devices = AudioUtilities.GetSpeakers()
        volume = devices.EndpointVolume
        
        if level == -1:  # Mute
            volume.SetMute(1, None)
            return "Volume muted, sir."
            
        # Ensure target is unmuted for normal adjustments
        if volume.GetMute():
            volume.SetMute(0, None)
            
        if level == -3:  # Volume Up 20%
            current = volume.GetMasterVolumeLevelScalar()
            new_level = min(1.0, current + 0.20)
            volume.SetMasterVolumeLevelScalar(new_level, None)
            return f"Volume turned up to {int(new_level * 100)} percent, sir."
            
        if level == -2:  # Volume Down 20%
            current = volume.GetMasterVolumeLevelScalar()
            new_level = max(0.0, current - 0.20)
            volume.SetMasterVolumeLevelScalar(new_level, None)
            return f"Volume turned down to {int(new_level * 100)} percent, sir."
            
        # Absolute volume percent setting
        level = max(0, min(100, level))
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
        return f"Volume set to {level} percent, sir."
    except Exception as e:
        logger.error(f"Error setting volume: {e}")
        return "I could not adjust the volume, sir."

def search_web(query: str):
    """
    3. search_web(query: str)
    Performs a DuckDuckGo instant answer search and returns a 2-sentence summary.
    """
    try:
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
        logger.info(f"Calling DuckDuckGo API: {url}")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        abstract = data.get("AbstractText", "")
        related = data.get("RelatedTopics", [])
        
        if abstract:
            text = abstract
        elif related and isinstance(related, list) and len(related) > 0 and "Text" in related[0]:
            text = related[0]["Text"]
        else:
            text = f"I could not find an instant answer for {query}, sir."
            
        # Split into sentences and keep the first two
        sentences = [s.strip() for s in text.split('.') if s.strip()]
        summary = ". ".join(sentences[:2])
        if len(sentences) > 2:
            summary += "."
            
        return f"Here is what I found, sir: {summary}"
    except Exception as e:
        logger.error(f"Error searching web: {e}")
        return "I had trouble searching the web, sir."

def get_weather(city: str = "auto"):
    """
    4. get_weather(city: str = "auto")
    Queries wttr.in for weather details. Auto-detects location via IP lookup if requested.
    """
    try:
        actual_city = city
        if city.lower() == "auto":
            logger.info("Detecting location automatically via ip-api.com...")
            r = requests.get("http://ip-api.com/json/", timeout=5)
            r.raise_for_status()
            loc_data = r.json()
            actual_city = loc_data.get("city", "London")
            logger.info(f"Auto-detected city: {actual_city}")
            
        url = f"https://wttr.in/{urllib.parse.quote(actual_city)}?format=j1"
        logger.info(f"Calling weather API: {url}")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        current = data["current_condition"][0]
        temp = current["temp_C"]
        condition = current["weatherDesc"][0]["value"]
        
        return f"Currently {temp} degrees Celsius and {condition.lower()} in {actual_city}, sir."
    except Exception as e:
        logger.error(f"Error getting weather: {e}")
        return "I could not retrieve the weather information, sir."

def get_desktop_path():
    """Queries the Windows Registry to get the user's real Desktop path (handles OneDrive redirections)."""
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        )
        val, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        return os.path.expandvars(val)
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Desktop")

def take_screenshot():
    """
    5. take_screenshot()
    Captures the primary monitor and saves it to the Windows Desktop.
    """
    try:
        from PIL import ImageGrab
        
        desktop = get_desktop_path()
        if not os.path.exists(desktop):
            os.makedirs(desktop, exist_ok=True)
            
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"screenshot_{timestamp}.png"
        filepath = os.path.join(desktop, filename)
        
        # Grab screen and save to disk
        screenshot = ImageGrab.grab()
        screenshot.save(filepath)
        return "Screenshot saved to your Desktop, sir."
    except Exception as e:
        logger.error(f"Error taking screenshot: {e}")
        return "I was unable to take a screenshot, sir."

def tell_time():
    """
    6. tell_time()
    Returns the current system time in a 12-hour AM/PM format.
    """
    current_time = datetime.datetime.now().strftime("%I:%M %p")
    if current_time.startswith("0"):
        current_time = current_time[1:]  # Remove leading zero
    return f"It's {current_time}, sir."

def tell_date():
    """
    7. tell_date()
    Returns the current date.
    """
    now = datetime.datetime.now()
    weekday = now.strftime("%A")
    month = now.strftime("%B")
    day = now.strftime("%d")
    if day.startswith("0"):
        day = day[1:]
    year = now.strftime("%Y")
    return f"Today is {weekday}, {month} {day}, {year}, sir."

def set_reminder(text: str, minutes: int):
    """
    8. set_reminder(text: str, minutes: int)
    Creates a scheduled task on Windows using schtasks.exe to execute a
    temporary script that presents a toaster notification after X minutes.
    """
    try:
        from datetime import datetime, timedelta
        
        # Calculate execution time
        run_time = datetime.now() + timedelta(minutes=minutes)
        time_str = run_time.strftime("%H:%M")
        date_str = run_time.strftime("%m/%d/%Y")  # schtasks expects MM/DD/YYYY on Windows US settings
        
        user_home = os.path.expanduser("~")
        reminders_dir = os.path.join(user_home, ".jarvis", "reminders")
        os.makedirs(reminders_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        script_path = os.path.join(reminders_dir, f"reminder_{timestamp}.py")
        
        # Write the trigger script
        script_content = f"""
from win10toast import ToastNotifier
import os

try:
    toaster = ToastNotifier()
    toaster.show_toast("JARVIS Reminder", "{text}", duration=10)
finally:
    try:
        os.remove(__file__)
    except Exception:
        pass
"""
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
            
        # Locate pythonw.exe
        python_exe = sys.executable
        if python_exe.endswith("python.exe"):
            pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
        elif python_exe.endswith("python3.exe"):
            pythonw_exe = python_exe.replace("python3.exe", "pythonw.exe")
        else:
            pythonw_exe = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
            if not os.path.exists(pythonw_exe):
                pythonw_exe = python_exe
                
        # Register the Windows Scheduled Task
        task_name = f"JARVIS_Reminder_{timestamp}"
        task_run_cmd = f'\\"{pythonw_exe}\\" \\"{script_path}\\"'
        
        sch_cmd = f'schtasks /create /tn "{task_name}" /tr "{task_run_cmd}" /sc once /st {time_str} /sd {date_str} /f'
        logger.info(f"Scheduling Windows task: {sch_cmd}")
        
        result = subprocess.run(sch_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(result.stderr)
            
        # Log to structured SQLite memory
        try:
            from memory_manager import MemoryManager
            MemoryManager().add_reminder(text, minutes)
        except Exception as err:
            logger.error(f"Failed to log reminder to structured memory: {err}")
            
        return f"Reminder set for {minutes} minutes from now, sir."
    except Exception as e:
        logger.error(f"Error setting reminder: {e}")
        return "I was unable to schedule the reminder, sir."

def open_website(url: str):
    """
    9. open_website(url: str)
    Opens the default web browser to the requested URL (handles spoken shortcut mappings).
    """
    try:
        url_lower = url.lower().strip()
        spoken_mappings = {
            "youtube": "https://youtube.com",
            "gmail": "https://mail.google.com",
            "google": "https://google.com",
            "github": "https://github.com",
            "facebook": "https://facebook.com",
            "wikipedia": "https://wikipedia.org",
            "reddit": "https://reddit.com",
            "twitter": "https://twitter.com",
            "netflix": "https://netflix.com",
            "spotify": "https://spotify.com",
        }
        
        target_url = spoken_mappings.get(url_lower, url)
        
        # Append protocol if missing
        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = "https://" + target_url
            
        logger.info(f"Opening browser link: {target_url}")
        webbrowser.open(target_url)
        return "Opening website, sir."
    except Exception as e:
        logger.error(f"Error opening website {url}: {e}")
        return "I could not open the website, sir."

def run_command(cmd: str):
    """
    10. run_command(cmd: str)
    Executes a shell command via CMD, returning the first 200 characters of output.
    """
    try:
        logger.info(f"Executing CMD command: {cmd}")
        result = subprocess.run(
            cmd, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        
        stdout_text = result.stdout.strip() if result.stdout else ""
        stderr_text = result.stderr.strip() if result.stderr else ""
        
        combined_output = (stdout_text + "\n" + stderr_text).strip()
        if not combined_output:
            return "Command executed successfully with no output, sir."
            
        summary = combined_output[:200]
        if len(combined_output) > 200:
            summary += "..."
            
        return f"Command executed, sir. Output:\n{summary}"
    except Exception as e:
        logger.error(f"Error executing command: {e}")
        return f"Failed to execute command, sir. Error: {str(e)[:100]}"


def get_news_briefing():
    """
    Fetches the top 5 headlines from the BBC News RSS feed.
    Test: print(get_news_briefing())
    """
    try:
        import feedparser
        url = "http://feeds.bbci.co.uk/news/rss.xml"
        logger.info(f"Fetching RSS feed from {url}")
        feed = feedparser.parse(url)
        if not feed.entries:
            return "I could not retrieve any news entries, sir."
        
        headlines = []
        for i, entry in enumerate(feed.entries[:5], 1):
            title = entry.title
            title = title.strip().replace('\n', ' ')
            headlines.append(f"[{i}] {title}")
            
        headlines_str = " ... ".join(headlines)
        return f"Top news today, sir: {headlines_str}."
    except Exception as e:
        logger.error(f"Error in get_news_briefing: {e}")
        return "I was unable to retrieve the news briefing, sir."

def play_music(query: str):
    """
    Plays music via Spotify, local VLC, or opens YouTube in the default browser.
    Test: print(play_music("stairway to heaven"))
    """
    query = query.strip()
    if not query:
        return "What would you like me to play, sir?"

    # 1. Spotify
    try:
        from config import load_config
        config = load_config()
        client_id = config.get("spotify_client_id")
        client_secret = config.get("spotify_client_secret")
        
        if client_id and client_secret:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth
            redirect_uri = config.get("spotify_redirect_uri", "http://localhost:8888/callback")
            sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope="user-modify-playback-state user-read-playback-state"
            ))
            results = sp.search(q=query, limit=1, type='track')
            if results and results.get('tracks') and results['tracks'].get('items'):
                track = results['tracks']['items'][0]
                track_uri = track['uri']
                song_name = track['name']
                artist_name = track['artists'][0]['name']
                
                devices = sp.devices()
                device_id = None
                if devices and devices.get('devices'):
                    for d in devices['devices']:
                        if d.get('is_active'):
                            device_id = d['id']
                            break
                    if not device_id:
                        device_id = devices['devices'][0]['id']
                
                sp.start_playback(device_id=device_id, uris=[track_uri])
                return f"Playing {song_name} by {artist_name}, sir."
    except Exception as e:
        logger.warning(f"Spotify playback failed or not configured: {e}. Trying VLC...")

    # 2. VLC
    try:
        vlc_path = find_executable("vlc")
        if not vlc_path:
            for p in [
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
            ]:
                if os.path.exists(p):
                    vlc_path = p
                    break
        
        if vlc_path:
            music_dir = os.path.join(os.path.expanduser("~"), "Music")
            matching_file = None
            if os.path.exists(music_dir):
                for root, dirs, files in os.walk(music_dir):
                    for file in files:
                        if file.lower().endswith(('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.wma')):
                            if query.lower() in file.lower():
                                matching_file = os.path.join(root, file)
                                break
                    if matching_file:
                        break
            
            if matching_file:
                subprocess.Popen([vlc_path, matching_file])
                song_name = os.path.splitext(os.path.basename(matching_file))[0]
                if " - " in song_name:
                    parts = song_name.split(" - ", 1)
                    artist = parts[0].strip()
                    song = parts[1].strip()
                    return f"Playing {song} by {artist}, sir."
                else:
                    return f"Playing {song_name}, sir."
    except Exception as e:
        logger.warning(f"VLC playback failed: {e}. Trying YouTube...")

    # 3. YouTube Fallback
    try:
        webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}")
        return f"Playing {query} on YouTube, sir."
    except Exception as e:
        logger.error(f"YouTube playback failed: {e}")
        return "I was unable to play the music, sir."

def read_emails(count: int = 5):
    """
    Fetches the sender and subject of the last {count} unread emails from Gmail IMAP.
    Test: print(read_emails(3))
    """
    try:
        from config import load_config
        import imaplib
        import email
        from email.header import decode_header
        
        config = load_config()
        user = config.get("gmail_user") or config.get("email_user")
        password = config.get("gmail_password") or config.get("email_password")
        
        if not user or not password:
            return "Please configure your Gmail credentials in config.json, sir."
            
        logger.info("Connecting to Gmail IMAP...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(user, password)
        mail.select("inbox")
        
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK":
            return "I could not retrieve your emails, sir."
            
        mail_ids = messages[0].split()
        total_unread = len(mail_ids)
        if total_unread == 0:
            mail.logout()
            return "You have no unread emails, sir."
            
        target_ids = mail_ids[-count:]
        target_ids.reverse()
        
        email_summaries = []
        for m_id in target_ids:
            status, data = mail.fetch(m_id, "(RFC822.HEADER)")
            if status != "OK":
                continue
            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)
            
            subject, encoding = decode_header(msg.get("Subject", "No Subject"))[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or "utf-8", errors="ignore")
                
            sender, encoding = decode_header(msg.get("From", "Unknown Sender"))[0]
            if isinstance(sender, bytes):
                sender = sender.decode(encoding or "utf-8", errors="ignore")
                
            match = re.match(r'^([^<]+)', sender)
            if match:
                sender_name = match.group(1).strip()
                sender_name = sender_name.strip('"\'')
                if sender_name:
                    sender = sender_name
                    
            email_summaries.append(f"{sender} wrote: {subject}")
            
        mail.close()
        mail.logout()
        
        details = ". ".join(email_summaries)
        return f"You have {total_unread} unread emails, sir. {details}."
    except Exception as e:
        logger.error(f"Error reading emails: {e}")
        return "I was unable to check your emails, sir."

def run_python_file(filepath: str):
    """
    Executes a local Python script and returns the first 300 characters of its output.
    Test: print(run_python_file("test_skills.py"))
    """
    try:
        filepath = filepath.strip('"\'')
        if not os.path.exists(filepath):
            return f"I could not find the file at {filepath}, sir."
            
        if not filepath.endswith(".py"):
            return "The file is not a Python script, sir."
            
        python_exe = sys.executable
        logger.info(f"Running script {filepath} with {python_exe}")
        result = subprocess.run(
            [python_exe, filepath],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        stdout_text = result.stdout.strip() if result.stdout else ""
        stderr_text = result.stderr.strip() if result.stderr else ""
        
        output = (stdout_text + "\n" + stderr_text).strip()
        if not output:
            return "Script completed successfully, sir."
            
        summary = output[:300]
        if len(output) > 300:
            summary += "..."
        return f"Script completed, sir. Output: {summary}"
    except subprocess.TimeoutExpired:
        return "The script execution timed out, sir."
    except Exception as e:
        logger.error(f"Error running Python script {filepath}: {e}")
        return "I encountered an error while running the script, sir."

def summarize_file(filepath: str):
    """
    Reads a plain text or PDF file and generates a 3-sentence summary using Ollama.
    Test: print(summarize_file("README.md"))
    """
    try:
        filepath = filepath.strip('"\'')
        if not os.path.exists(filepath):
            return f"I could not find the file at {filepath}, sir."
            
        text = ""
        if filepath.lower().endswith(".pdf"):
            import fitz
            doc = fitz.open(filepath)
            for page in doc:
                text += page.get_text()
            doc.close()
        else:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
                
        text = text.strip()
        if not text:
            return "The file appears to be empty, sir."
            
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[Content truncated]"
            
        from config import load_config
        config = load_config()
        model = config.get("ollama_model", "llama3.2:3b")
        url = "http://localhost:11434/api/generate"
        
        parsed_url = urllib.parse.urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        try:
            requests.get(f"{base_url}/api/tags", timeout=3)
        except Exception:
            return "Ollama is not running, so I cannot summarize the file, sir."
            
        payload = {
            "model": model,
            "prompt": f"Summarize this in 3 sentences:\n\n{text}",
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 150
            }
        }
        
        logger.info(f"Calling Ollama to summarize file {filepath} using {model}")
        r = requests.post(url, json=payload, timeout=40)
        r.raise_for_status()
        summary = r.json().get("response", "").strip()
        
        return summary if summary else "I was unable to generate a summary, sir."
    except Exception as e:
        logger.error(f"Error summarizing file {filepath}: {e}")
        return "I had trouble summarizing the file, sir."

def smart_home(device: str, action: str):
    """
    Triggers a light or switch service call on local Home Assistant.
    Test: print(smart_home("light.living_room", "on"))
    """
    action = action.lower().strip()
    if action not in ["on", "off", "toggle"]:
        action = "on"
        
    from config import load_config
    config = load_config()
    ha_token = config.get("ha_token") or config.get("HA_TOKEN")
    ha_url = config.get("ha_url") or config.get("HA_URL") or "http://localhost:8123"
    
    if not ha_token:
        return "Home Assistant is not configured. Please add HA_TOKEN to your config.json, sir."
        
    device_clean = device.lower().strip()
    if "." in device_clean:
        domain = device_clean.split(".")[0]
        entity_id = device_clean
    else:
        device_slug = device_clean.replace(" ", "_")
        if "switch" in device_clean:
            domain = "switch"
            entity_id = f"switch.{device_slug}"
        else:
            domain = "light"
            entity_id = f"light.{device_slug}"
            
    if domain not in ["light", "switch"]:
        domain = "light"
        
    url = f"{ha_url.rstrip('/')}/api/services/{domain}/turn_{action}"
    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json"
    }
    payload = {"entity_id": entity_id}
    
    try:
        logger.info(f"Sending Home Assistant POST to {url} with entity_id {entity_id}")
        r = requests.post(url, json=payload, headers=headers, timeout=5)
        r.raise_for_status()
        return f"Done, sir. {device} has been turned {action}."
    except requests.exceptions.ConnectionError:
        return "I could not connect to Home Assistant. It seems to be offline or not installed, sir."
    except Exception as e:
        logger.error(f"Error controlling smart home device: {e}")
        return f"Failed to turn {action} the {device}, sir."

def system_report():
    """
    Queries CPU, RAM, disk, process count, and NVIDIA GPU temperature to build a diagnostic statement.
    Test: print(system_report())
    """
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
        
        drive = os.path.splitdrive(os.getcwd())[0] or "C:"
        if not drive.endswith("\\"):
            drive += "\\"
        disk = psutil.disk_usage(drive).percent
        
        proc_count = len(list(psutil.process_iter()))
        
        gpu_info = ""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2,
                shell=True
            )
            if result.returncode == 0 and result.stdout:
                gpu_temp = result.stdout.strip()
                gpu_info = f" GPU temperature is {gpu_temp} degrees Celsius, sir."
        except Exception:
            pass
            
        report = f"System health report, sir: CPU usage is at {cpu} percent, memory usage is at {ram} percent, and disk usage is at {disk} percent. There are currently {proc_count} running processes."
        if gpu_info:
            report += gpu_info
        else:
            report += " No NVIDIA GPU diagnostics are available."
            
        return report
    except Exception as e:
        logger.error(f"Error generating system report: {e}")
        return "I could not retrieve the system diagnostic report, sir."

def set_alarm(time_str: str):
    """
    Schedules a Windows Task that triggers an audio beep alarm and a notification popup at the requested time.
    Test: print(set_alarm("7:30 AM"))
    """
    try:
        import dateparser
        from datetime import datetime, timedelta
        
        alarm_time = dateparser.parse(time_str)
        if not alarm_time:
            return f"I could not understand the alarm time '{time_str}', sir. Please specify a time like 7:30 AM."
            
        now = datetime.now()
        if alarm_time < now:
            alarm_time = alarm_time + timedelta(days=1)
            
        time_str_formatted = alarm_time.strftime("%H:%M")
        date_str_formatted = alarm_time.strftime("%m/%d/%Y")
        
        user_home = os.path.expanduser("~")
        alarms_dir = os.path.join(user_home, ".jarvis", "alarms")
        os.makedirs(alarms_dir, exist_ok=True)
        
        timestamp = alarm_time.strftime("%Y%m%d_%H%M%S")
        script_path = os.path.join(alarms_dir, f"alarm_{timestamp}.py")
        
        script_content = f"""
import os
import time
from win10toast import ToastNotifier

try:
    try:
        import win32api
        for _ in range(5):
            win32api.MessageBeep(-1)
            time.sleep(0.5)
    except Exception:
        import winsound
        for _ in range(5):
            winsound.Beep(1000, 500)
            time.sleep(0.2)
            
    toaster = ToastNotifier()
    toaster.show_toast("JARVIS Alarm", "Wake up, sir! It is {time_str_formatted}.", duration=15)
finally:
    try:
        os.remove(__file__)
    except Exception:
        pass
"""
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
            
        python_exe = sys.executable
        if python_exe.endswith("python.exe"):
            pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
        elif python_exe.endswith("python3.exe"):
            pythonw_exe = python_exe.replace("python3.exe", "pythonw.exe")
        else:
            pythonw_exe = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
            if not os.path.exists(pythonw_exe):
                pythonw_exe = python_exe
                
        task_name = f"JARVIS_Alarm_{timestamp}"
        task_run_cmd = f'\\"{pythonw_exe}\\" \\"{script_path}\\"'
        
        sch_cmd = f'schtasks /create /tn "{task_name}" /tr "{task_run_cmd}" /sc once /st {time_str_formatted} /sd {date_str_formatted} /f'
        logger.info(f"Scheduling Windows alarm task: {sch_cmd}")
        
        result = subprocess.run(sch_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(result.stderr)
            
        return f"Alarm successfully set for {alarm_time.strftime('%I:%M %p')} on {alarm_time.strftime('%A, %B %d')}, sir."
    except Exception as e:
        logger.error(f"Error setting alarm: {e}")
        return "I was unable to schedule the alarm, sir."

# Registry of available functions
SKILL_FUNCTIONS = {
    "open_app": open_app,
    "set_volume": set_volume,
    "search_web": search_web,
    "get_weather": get_weather,
    "take_screenshot": take_screenshot,
    "tell_time": tell_time,
    "tell_date": tell_date,
    "set_reminder": set_reminder,
    "open_website": open_website,
    "run_command": run_command,
    "get_news_briefing": get_news_briefing,
    "play_music": play_music,
    "read_emails": read_emails,
    "run_python_file": run_python_file,
    "summarize_file": summarize_file,
    "smart_home": smart_home,
    "system_report": system_report,
    "set_alarm": set_alarm,
}

# =====================================================================
# INTENT ROUTER IMPLEMENTATIONS
# =====================================================================

def extract_number(text):
    """Utility to pull the first contiguous integer from text."""
    match = re.search(r'\d+', text)
    return int(match.group()) if match else None

def route_intent_keywords(text):
    """
    Checks the user query against simple regex/keyword mappings.
    Returns (skill_name, params) if a match is found, or (None, None).
    """
    text_lower = text.lower().strip()
    
    # 1. tell_time
    if any(k in text_lower for k in ["what time is it", "current time", "tell me the time"]):
        return "tell_time", {}
        
    # 2. tell_date
    if any(k in text_lower for k in ["what day is it", "what is the date", "today's date", "tell me the date"]):
        return "tell_date", {}
        
    # 3. take_screenshot
    if any(k in text_lower for k in ["take screenshot", "take a screenshot", "capture screen"]):
        return "take_screenshot", {}
        
    # 4. set_volume
    if "mute" in text_lower:
        return "set_volume", {"level": -1}
    if any(k in text_lower for k in ["turn it up", "increase volume", "volume up", "louder", "turn up"]):
        return "set_volume", {"level": -3}
    if any(k in text_lower for k in ["turn it down", "decrease volume", "volume down", "quieter", "turn down"]):
        return "set_volume", {"level": -2}
    if "volume" in text_lower:
        num = extract_number(text_lower)
        if num is not None:
            return "set_volume", {"level": num}
            
    # 5. set_reminder
    # "remind me to check the oven in 5 minutes"
    # "set reminder to drink water in 15 minutes"
    reminder_match = re.search(r'(?:remind me to|set a reminder to|set reminder for)\s+(.+?)\s+in\s+(\d+)\s+minute', text_lower)
    if reminder_match:
        rem_text = reminder_match.group(1).strip()
        rem_min = int(reminder_match.group(2))
        return "set_reminder", {"text": rem_text, "minutes": rem_min}

    # 6. get_news_briefing
    if any(k in text_lower for k in ["news briefing", "news today", "top headlines", "bbc news", "latest news"]):
        return "get_news_briefing", {}

    # 7. read_emails
    if any(k in text_lower for k in ["read emails", "check emails", "read my email", "check my email", "unread emails"]):
        num = extract_number(text_lower)
        count = num if num is not None else 5
        return "read_emails", {"count": count}

    # 8. run_python_file
    run_py_match = re.search(r'(?:run python file|execute python file|run python script|run script)\s+(.+)', text_lower)
    if run_py_match:
        filepath = run_py_match.group(1).strip()
        return "run_python_file", {"filepath": filepath}

    # 9. summarize_file
    sum_match = re.search(r'(?:summarize file|summarize pdf|summarize text|summarize)\s+(.+)', text_lower)
    if sum_match:
        filepath = sum_match.group(1).strip()
        return "summarize_file", {"filepath": filepath}

    # 10. smart_home
    smart_match = re.search(r'turn\s+(on|off|toggle)\s+(?:the\s+)?(.+)', text_lower)
    if smart_match:
        action = smart_match.group(1).strip()
        device = smart_match.group(2).strip()
        return "smart_home", {"device": device, "action": action}

    # 11. system_report
    if any(k in text_lower for k in ["system report", "system health", "diagnostics", "system diagnostic", "cpu usage", "ram usage", "gpu temperature"]):
        return "system_report", {}

    # 12. set_alarm
    alarm_match = re.search(r'(?:set alarm for|set an alarm for|alarm for|wake me up at)\s+(.+)', text_lower)
    if alarm_match:
        time_str = alarm_match.group(1).strip()
        return "set_alarm", {"time_str": time_str}

    # 13. play_music
    play_music_match = re.search(r'(?:play music|play song|play)\s+(.+)', text_lower)
    if play_music_match:
        query = play_music_match.group(1).strip()
        return "play_music", {"query": query}
        
    # 14. open_app
    for app in ["chrome", "firefox", "notepad", "calculator", "spotify", "vscode", "explorer", "cmd", "powershell", "task manager"]:
        if f"open {app}" in text_lower or f"launch {app}" in text_lower:
            return "open_app", {"name": app}
            
    # 15. open_website
    website_match = re.search(r'(?:open website|open url|go to)\s+(.+)', text_lower)
    if website_match:
        site = website_match.group(1).strip()
        return "open_website", {"url": site}
    for site in ["youtube", "google", "gmail", "github", "facebook", "wikipedia", "reddit"]:
        if f"open {site}" in text_lower or f"go to {site}" in text_lower:
            return "open_website", {"url": site}
            
    # 16. get_weather
    weather_city_match = re.search(r'weather in\s+([a-zA-Z\s]+)', text_lower)
    if weather_city_match:
        city = weather_city_match.group(1).strip()
        return "get_weather", {"city": city}
    if "weather" in text_lower:
        return "get_weather", {"city": "auto"}
        
    # 17. run_command
    cmd_match = re.search(r'(?:run command|execute command|system command)\s+(.+)', text_lower)
    if cmd_match:
        cmd_str = cmd_match.group(1).strip()
        return "run_command", {"cmd": cmd_str}
        
    # 18. search_web
    search_match = re.search(r'(?:search for|google|search)\s+(.+)', text_lower)
    if search_match:
        query = search_match.group(1).strip()
        return "search_web", {"query": query}
        
    return None, None

def route_intent_ollama(text, model="llama3.2:3b", url="http://localhost:11434/api/generate"):
    """
    Uses the local Ollama LLM to classify the user's intent if keyword matching fails.
    Updated to query the /api/generate endpoint with the llama3.2:3b model and tag verification.
    """
    system_prompt = (
        "You are an intent classifier for a voice assistant. "
        "Classify the user's request into one of these skills:\n"
        "- open_app (params: {'name': string})\n"
        "- set_volume (params: {'level': integer}) [-1 for mute, -2 for down, -3 for up, or 0-100]\n"
        "- search_web (params: {'query': string})\n"
        "- get_weather (params: {'city': string}) [use 'auto' if no city is explicitly specified]\n"
        "- take_screenshot (params: {})\n"
        "- tell_time (params: {})\n"
        "- tell_date (params: {})\n"
        "- set_reminder (params: {'text': string, 'minutes': integer})\n"
        "- open_website (params: {'url': string})\n"
        "- run_command (params: {'cmd': string})\n"
        "- get_news_briefing (params: {})\n"
        "- play_music (params: {'query': string})\n"
        "- read_emails (params: {'count': integer}) [default to 5 if not specified]\n"
        "- run_python_file (params: {'filepath': string})\n"
        "- summarize_file (params: {'filepath': string})\n"
        "- smart_home (params: {'device': string, 'action': string}) [action: 'on', 'off', or 'toggle']\n"
        "- system_report (params: {})\n"
        "- set_alarm (params: {'time_str': string}) [time_str: like '7:30 AM', '8:00 PM', '10:15']\n\n"
        "Return ONLY a valid JSON object in this format:\n"
        "{\"skill\": \"skill_name\", \"params\": {...}}\n"
        "If it fits none, return {\"skill\": \"none\", \"params\": {}}.\n"
        "Do not include any chat formatting, warnings, markdown codeblocks or extra text."
    )
    
    prompt = f"System: {system_prompt}\n\nHuman: Classify this request: {text}\nAssistant:"
    
    parsed_url = urllib.parse.urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    
    # Pre-flight tags ping check
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=3)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Ollama is not running during intent classification: {e}")
        return None, None

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 100
        }
    }
    
    try:
        generate_url = f"{base_url}/api/generate"
        logger.info(f"Calling Ollama intent classifier at: {generate_url}")
        r = requests.post(generate_url, json=payload, timeout=20)
        r.raise_for_status()
        res = r.json()
        content = res.get("response", "").strip()
        
        # Strip markdown json block tags if the model returned them
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        data = json.loads(content)
        return data.get("skill"), data.get("params", {})
    except Exception as e:
        logger.error(f"Error calling Ollama intent classifier: {e}")
        return None, None

def route_intent(text, model="llama3.2:3b", url="http://localhost:11434/api/generate"):
    """
    Main entry point for routing intent.
    Checks keyword maps, falls back to Ollama classification.
    Returns (skill_function, params) if a match is found, or (None, None).
    """
    # 1. Try keyword matching
    skill_name, params = route_intent_keywords(text)
    if skill_name:
        func = SKILL_FUNCTIONS.get(skill_name)
        if func:
            logger.info(f"Intent routed via keywords: '{skill_name}' with parameters {params}")
            return func, params
            
    # 2. Fallback to Ollama LLM classifier
    skill_name, params = route_intent_ollama(text, model, url)
    if skill_name and skill_name != "none":
        func = SKILL_FUNCTIONS.get(skill_name)
        if func:
            logger.info(f"Intent routed via Ollama: '{skill_name}' with parameters {params}")
            return func, params
            
    logger.info("No matching skill found. Treating as standard dialog.")
    return None, None
