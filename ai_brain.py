import os
import json
import logging
import urllib.parse
from datetime import datetime
from collections import deque
import requests
import traceback

logger = logging.getLogger("jarvis")

def check_ollama(url=None, model="llama3.2:3b"):
    """
    Checks if Ollama is running and if the model is available.
    """
    if url is None:
        url = "http://localhost:11434/api/tags"
    else:
        # Resolve to api/tags
        parsed = urllib.parse.urlparse(url)
        url = f"{parsed.scheme}://{parsed.netloc}/api/tags"
        
    try:
        r = requests.get(url, timeout=3)
        r.raise_for_status()
        data = r.json()
        models = data.get("models", [])
        model_names = [m.get("name", "") for m in models]
        
        target = model.lower()
        for name in model_names:
            if target == name.lower() or name.lower().startswith(target):
                return True
        return False
    except Exception:
        return False

class AIBrain:
    """
    Manages conversation memory (last 6 exchanges) saved to memory.json
    and handles generating responses using Ollama /api/generate.
    """
    def __init__(self, ollama_url="http://localhost:11434/api/generate", model="llama3.2:3b", history_limit=6):
        self.ollama_url = ollama_url
        self.model = model
        self.history_limit = history_limit
        # Limit * 2 because each exchange has a user message and an assistant message
        self.history = deque(maxlen=history_limit * 2)
        
        # Resolve memory file path
        user_home = os.path.expanduser("~")
        self.memory_dir = os.path.join(user_home, ".jarvis")
        os.makedirs(self.memory_dir, exist_ok=True)
        self.memory_file = os.path.join(self.memory_dir, "memory.json")
        
        self.load_history_from_file()
        self.run_startup_check()

    def check_ollama(self):
        return check_ollama(self.ollama_url, self.model)

    def run_startup_check(self):
        """Startup check: calls check_ollama. Speaks/logs if offline."""
        if not self.check_ollama():
            err_msg = "Sir, Ollama is not running. Please open a terminal and type ollama serve"
            logger.error(err_msg)
            print(f"\n[WARNING] {err_msg}\n", flush=True)
            try:
                import win32com.client
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Speak("Sir, Ollama is not running. Please start it.")
            except Exception:
                try:
                    import subprocess
                    cmd = f'powershell -Command "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak(\'Sir, Ollama is not running. Please start it.\')"'
                    subprocess.run(cmd, shell=True, timeout=5)
                except Exception:
                    pass

    def add_user_message(self, text):
        self.history.append({"role": "user", "content": text})
        self.persist_history_to_file()

    def add_assistant_message(self, text):
        self.history.append({"role": "assistant", "content": text})
        self.persist_history_to_file()

    def load_history(self, history_list):
        self.history.clear()
        for msg in history_list[-(self.history_limit * 2):]:
            self.history.append(msg)

    def save_history(self):
        return list(self.history)

    def load_history_from_file(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.load_history(data)
                logger.info(f"Loaded memory from file: {self.memory_file}")
            except Exception as e:
                logger.error(f"Error loading memory JSON: {e}")

    def persist_history_to_file(self):
        try:
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.history), f, indent=4)
        except Exception as e:
            logger.error(f"Error saving memory JSON: {e}")

    def generate(self, user_text, mem_context=None):
        """
        Generates a non-streaming response from Ollama.
        If Ollama is not running or model not found, returns a warning message.
        """
        if not self.check_ollama():
            return "Ollama is offline, sir. Please start it."
            
        # Add user message to history
        self.add_user_message(user_text)
        
        # Construct system prompt
        current_time = datetime.now().strftime("%B %d, %Y, %I:%M %p")
        system_prompt = (
            "You are JARVIS from Iron Man. British accent, dry wit, call user "
            f"'sir', 1-3 sentence answers, never say Certainly or Of course, "
            f"never mention being an AI. Current time: {current_time}"
        )
        if mem_context:
            system_prompt += f"\n\n[Memory Context]\n{mem_context}"
            
        # Build prompt string
        prompt = f"[SYSTEM]\n{system_prompt}\n[/SYSTEM]\n\n"
        
        # Append historical exchanges from history deque (excluding the last user_text we just added)
        history_list = list(self.history)[:-1]
        for i in range(0, len(history_list), 2):
            if i + 1 < len(history_list):
                user_msg = history_list[i]["content"]
                assistant_msg = history_list[i+1]["content"]
                prompt += f"Human: {user_msg}\nJARVIS: {assistant_msg}\n\n"
                
        prompt += f"Human: {user_text}\nJARVIS:"
        
        # Build request payload
        parsed_url = urllib.parse.urlparse(self.ollama_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        generate_url = f"{base_url}/api/generate"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.85,
                "num_predict": 150,
                "stop": ["Human:", "User:", "\nHuman"]
            }
        }
        
        try:
            logger.info(f"Calling Ollama generate endpoint: {generate_url}")
            response = requests.post(generate_url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            response_text = data.get("response", "").strip()
            self.add_assistant_message(response_text)
            return response_text
        except Exception as e:
            logger.error(f"Error calling Ollama generate: {e}", exc_info=True)
            fallback = "I am having trouble reaching my cognitive processors, sir."
            self.add_assistant_message(fallback)
            return fallback

    async def generate_response_stream(self, user_text, mem_context=None):
        """
        Streaming compatibility fallback that behaves like generate but yields chunks.
        """
        response = self.generate(user_text, mem_context)
        yield response
