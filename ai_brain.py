import os
import json
import logging
import urllib.parse
from datetime import datetime
from collections import deque
import requests
import threading
import asyncio
import traceback

logger = logging.getLogger("jarvis")

class AIBrain:
    """
    Manages the conversation history memory (retains last 8 exchanges in a deque, 
    persisted to conversation_history.json) and handles generating responses using 
    the local Ollama /api/generate endpoint.
    Runs a health check on startup and speaks/logs warnings if Ollama is not configured.
    """
    def __init__(self, ollama_url="http://localhost:11434/api/generate", model="llama3.2:3b", history_limit=8):
        # Normalize the endpoint URL to /api/generate
        if "/api/chat" in ollama_url:
            self.ollama_url = ollama_url.replace("/api/chat", "/api/generate")
        else:
            self.ollama_url = ollama_url
            
        self.model = model
        self.history_limit = history_limit
        # Limit * 2 because each exchange has a user message and an assistant message
        self.history = deque(maxlen=history_limit * 2)
        
        # Resolve history persistence paths
        self.history_dir = os.path.join(os.path.expanduser("~"), ".jarvis")
        os.makedirs(self.history_dir, exist_ok=True)
        self.history_file = os.path.join(self.history_dir, "conversation_history.json")
        
        # Fallback rotation configurations
        self.fallback_index = 0
        self.FALLBACK_MESSAGES = [
            "I am having trouble reaching the main network array, sir. Let me try that again.",
            "The connection to my processing core seems unstable at the moment, sir.",
            "An unexpected disruption occurred during synthesis. My apologies, sir.",
            "My processing arrays are currently experiencing high latency, sir.",
            "I encountered a localized system fault, sir. I am correcting it now."
        ]
        
        # Load persistent history and run tags validation on initialization
        self.load_history_from_file()
        self.run_startup_check()

    def add_user_message(self, text):
        """Adds a user message to conversation history and persists it."""
        self.history.append({"role": "user", "content": text})
        self.persist_history_to_file()

    def add_assistant_message(self, text):
        """Adds an assistant message to conversation history and persists it."""
        self.history.append({"role": "assistant", "content": text})
        self.persist_history_to_file()

    def get_system_prompt(self):
        """Returns the base system prompt blueprint for J.A.R.V.I.S."""
        return (
            "You are J.A.R.V.I.S. — Just A Rather Very Intelligent System.\n"
            "Tony Stark's personal AI. You speak with British sophistication and dry wit.\n"
            "You address the user as 'sir'. Keep answers concise (2-3 sentences) unless\n"
            "asked for detail. You are confident, precise, and occasionally make sharp\n"
            "observations. Never say you are an AI or mention Ollama or LLaMA.\n"
            "Current date and time: {datetime}"
        )

    def load_history(self, history_list):
        """Loads a raw list of history dicts into memory deque (maintains maximum bounds)."""
        self.history.clear()
        for msg in history_list[-16:]:
            self.history.append(msg)
        logger.info(f"Loaded {len(self.history)} messages into conversation history memory.")

    def save_history(self):
        """Returns the conversation history deque as a list."""
        return list(self.history)

    def load_history_from_file(self):
        """Loads persistent conversation history from local json file."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.load_history(data)
                logger.info(f"Persistent history file loaded successfully: {self.history_file}")
            except Exception as e:
                logger.error(f"Error loading persistent history from JSON: {e}")

    def persist_history_to_file(self):
        """Saves current memory queue state to local json file."""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.history), f, indent=4)
        except Exception as e:
            logger.error(f"Error saving conversation history to JSON: {e}")

    def get_fallback_message(self):
        """Rotates and returns one of 5 fallback messages on generation errors."""
        msg = self.FALLBACK_MESSAGES[self.fallback_index]
        self.fallback_index = (self.fallback_index + 1) % len(self.FALLBACK_MESSAGES)
        return msg

    def run_startup_check(self):
        """
        Performs a startup tags check. Speaks and prints diagnostic details
        if Ollama is not running or the model is missing.
        """
        parsed_url = urllib.parse.urlparse(self.ollama_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        tags_url = f"{base_url}/api/tags"
        
        logger.info(f"Running Ollama startup check: {tags_url}")
        try:
            r = requests.get(tags_url, timeout=5)
            r.raise_for_status()
            data = r.json()
            models = data.get("models", [])
            model_names = [m.get("name", "") for m in models]
            
            target = self.model.lower()
            found = False
            for name in model_names:
                if target == name.lower() or name.lower().startswith(target):
                    found = True
                    break
                    
            if not found:
                available = ", ".join(model_names) if model_names else "None"
                err_text = (
                    f"[ERROR] Model '{self.model}' not found in Ollama.\n"
                    f"Available models: {available}\n"
                    f"Please run: ollama pull {self.model}"
                )
                print(f"\n{err_text}\n", flush=True)
                logger.error(err_text)
        except requests.exceptions.ConnectionError:
            err_msg = "Sir, Ollama is not running. Please open a terminal and type ollama serve"
            print(f"\n[ERROR] {err_msg}\n", flush=True)
            logger.error(err_msg)
            # Synchronously speak the alert using native Windows SpVoice
            try:
                import win32com.client
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Speak(err_msg)
            except Exception:
                try:
                    import subprocess
                    cmd = f'powershell -Command "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak(\'{err_msg}\')"'
                    subprocess.run(cmd, shell=True, timeout=5)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Ollama startup tag validation failed: {e}")

    def _stream_ollama(self, system_prompt, queue, loop):
        """
        Worker function run in a background thread.
        Constructs the prompt, queries /api/generate with streaming enabled,
        and pushes tokens back to the main event loop queue.
        """
        parsed_url = urllib.parse.urlparse(self.ollama_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        generate_url = f"{base_url}/api/generate"
        
        # Build manual prompt structure
        prompt = f"{system_prompt}\n\n"
        for msg in self.history:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                prompt += f"Human: {content}\n"
            elif role == "assistant":
                prompt += f"Assistant: {content}\n"
        if not prompt.endswith("Assistant:"):
            prompt += "Assistant:"
            
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": 0.85,
                "top_p": 0.9,
                "num_predict": 250,
                "stop": ["Human:", "User:", "\nHuman", "\nUser"]
            }
        }
        
        try:
            logger.info(f"Calling Ollama stream endpoint: {generate_url}")
            response = requests.post(generate_url, json=payload, timeout=60, stream=True)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line.decode('utf-8'))
                    chunk_text = data.get("response", "")
                    if chunk_text:
                        loop.call_soon_threadsafe(queue.put_nowait, chunk_text)
                    if data.get("done", False):
                        break
                except Exception as je:
                    logger.warning(f"Error parsing json chunk: {je}")
                    
            # Complete the queue stream
            loop.call_soon_threadsafe(queue.put_nowait, None)
            
        except requests.exceptions.Timeout as te:
            logger.warning(f"Ollama request timed out: {te}")
            loop.call_soon_threadsafe(queue.put_nowait, "timeout_error")
        except Exception as e:
            # Log full exception traceback to file
            try:
                err_file = os.path.join(self.history_dir, "errors.log")
                with open(err_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n--- Error at {datetime.now()} ---\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass
            logger.error(f"Error calling Ollama generate stream: {e}", exc_info=True)
            loop.call_soon_threadsafe(queue.put_nowait, e)

    async def generate_response_stream(self, user_text, mem_context=None):
        """
        Asynchronous generator yielding response tokens from Ollama.
        Commits assistant's response to history deque upon completion.
        """
        self.add_user_message(user_text)
        
        current_time = datetime.now().strftime("%B %d, %Y, %I:%M %p")
        system_prompt = self.get_system_prompt().format(datetime=current_time)
        if mem_context:
            system_prompt += f"\n\n[Memory Context]\n{mem_context}"
            
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        
        # Run blocking network call in background thread
        thread = threading.Thread(target=self._stream_ollama, args=(system_prompt, queue, loop))
        thread.start()
        
        full_response = []
        while True:
            item = await queue.get()
            if item is None:
                break
            elif item == "timeout_error":
                timeout_msg = "Processing your request, sir. One moment."
                yield timeout_msg
                full_response.append(timeout_msg)
                break
            elif isinstance(item, Exception):
                fallback_msg = self.get_fallback_message()
                yield fallback_msg
                full_response.append(fallback_msg)
                break
            else:
                yield item
                full_response.append(item)
                
        assistant_reply = "".join(full_response)
        self.add_assistant_message(assistant_reply)
