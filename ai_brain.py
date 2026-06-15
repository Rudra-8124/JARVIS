import requests
import json
import logging
import urllib.parse
from datetime import datetime
from collections import deque
import threading
import asyncio

logger = logging.getLogger("jarvis")

class AIBrain:
    """
    Manages the conversation history memory (retains last 20 exchanges in a deque)
    and handles generating responses using the local Ollama /api/generate endpoint.
    Checks Ollama availability and model tags before execution.
    """
    def __init__(self, ollama_url="http://localhost:11434/api/generate", model="llama3.2:3b", history_limit=20):
        # We ensure the URL points to /api/generate as required
        if "/api/chat" in ollama_url:
            self.ollama_url = ollama_url.replace("/api/chat", "/api/generate")
        else:
            self.ollama_url = ollama_url
            
        self.model = model
        self.history_limit = history_limit
        # Limit * 2 because each exchange has a user message and an assistant message
        self.history = deque(maxlen=history_limit * 2)

    def add_user_message(self, text):
        """Adds a user message to the conversation history deque."""
        self.history.append({"role": "user", "content": text})

    def add_assistant_message(self, text):
        """Adds an assistant message to the conversation history deque."""
        self.history.append({"role": "assistant", "content": text})

    def get_system_prompt(self):
        """
        Dynamically generates the system prompt containing the current local date
        formatted for Tony Stark's J.A.R.V.I.S. persona.
        """
        current_date = datetime.now().strftime("%B %d, %Y")
        return (
            "You are J.A.R.V.I.S., Tony Stark's AI assistant. British accent, dry wit, "
            "calls user 'sir', highly intelligent, concise answers (2-3 sentences max "
            "unless asked for more), occasionally makes sharp observations about the situation. "
            f"Current date: {current_date}. You have access to the user's computer and can help with tasks."
        )

    def load_history(self, history_list):
        """Loads a list of raw history messages into the memory deque."""
        self.history.clear()
        for msg in history_list:
            self.history.append(msg)
        logger.info(f"Loaded {len(self.history)} messages into conversation history memory.")

    def save_history(self):
        """Returns the conversation history deque as a standard list of message dicts."""
        return list(self.history)

    def _verify_ollama(self, base_url):
        """
        Queries http://localhost:11434/api/tags to confirm Ollama is running
        and that the target model is loaded.
        """
        tags_url = f"{base_url}/api/tags"
        try:
            logger.info(f"Verifying Ollama and model presence via: {tags_url}")
            r = requests.get(tags_url, timeout=5)
            r.raise_for_status()
            data = r.json()
            
            models = data.get("models", [])
            target_model = self.model.lower()
            model_names = [m.get("name", "").lower() for m in models]
            
            # Substring comparison to accommodate model tagging (like llama3.2:3b vs llama3.2:3b-instruct)
            model_found = False
            for name in model_names:
                if target_model in name or name in target_model:
                    model_found = True
                    break
                    
            if not model_found:
                raise Exception(f"The model {self.model} is not downloaded in Ollama, sir. Please run 'ollama pull {self.model}'.")
                
        except requests.exceptions.ConnectionError:
            raise Exception("Ollama is not running sir, please start it")
        except requests.exceptions.HTTPError as he:
            raise Exception(f"Ollama returned HTTP error {he.response.status_code}, sir.")

    def _stream_ollama(self, system_prompt, queue, loop):
        """
        Worker function run in a background thread.
        Constructs the full prompt string manually, queries /api/generate,
        and pushes the result back to the event loop queue.
        """
        parsed_url = urllib.parse.urlparse(self.ollama_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        try:
            # 1. Perform health-check ping
            self._verify_ollama(base_url)
            
            # 2. Build the manual conversation prompt string
            prompt = f"System: {system_prompt}\n\n"
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
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 200
                }
            }
            
            # 3. Call generate endpoint
            generate_url = f"{base_url}/api/generate"
            logger.info(f"Calling Ollama generate endpoint: {generate_url}")
            
            response = requests.post(generate_url, json=payload, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            content = data.get("response", "")
            
            if content:
                # Put the full response into the queue
                loop.call_soon_threadsafe(queue.put_nowait, content)
            
            # Send None to signal the end of the generator
            loop.call_soon_threadsafe(queue.put_nowait, None)
            
        except requests.exceptions.ConnectionError:
            err = Exception("Ollama is not running sir, please start it")
            loop.call_soon_threadsafe(queue.put_nowait, err)
        except requests.exceptions.HTTPError as he:
            err = Exception(f"Ollama returned HTTP error {he.response.status_code}, sir.")
            loop.call_soon_threadsafe(queue.put_nowait, err)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, e)

    async def generate_response_stream(self, user_text, mem_context=None):
        """
        Asynchronous generator that yields response tokens from Ollama.
        Updates conversation memory with the complete exchange upon completion.
        """
        self.add_user_message(user_text)
        system_prompt = self.get_system_prompt()
        if mem_context:
            system_prompt += f"\n\n[Memory Context]\n{mem_context}"
        
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        
        # Run the blocking network request in a dedicated background thread
        thread = threading.Thread(target=self._stream_ollama, args=(system_prompt, queue, loop))
        thread.start()
        
        full_response = []
        while True:
            item = await queue.get()
            if item is None:
                # End of stream reached
                break
            elif isinstance(item, Exception):
                # Propagation of thread exception to async loop
                raise item
            else:
                full_response.append(item)
                yield item
                
        # Commit assistant's response to history deque
        assistant_reply = "".join(full_response)
        self.add_assistant_message(assistant_reply)
