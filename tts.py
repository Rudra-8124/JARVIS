import os
import queue
import threading
import logging
import re
import time
import sounddevice as sd
from state_manager import JarvisState
import asyncio

logger = logging.getLogger("jarvis")

class MCIPlayer:
    """
    Native Windows Multimedia Control Interface (MCI) player.
    Provides low-latency, zero-dependency, non-blocking MP3 playback 
    and immediate interruption via winmm.dll.
    """
    def __init__(self):
        self.playing = False
        
    def play(self, filepath, stop_event):
        import ctypes
        try:
            # Close alias if it was left open previously
            ctypes.windll.winmm.mciSendStringW('close jarvis_speech', None, 0, None)
            
            # Open the audio file
            ret = ctypes.windll.winmm.mciSendStringW(f'open "{filepath}" type mpegvideo alias jarvis_speech', None, 0, None)
            if ret != 0:
                logger.error(f"MCI failed to open MP3 file. Code: {ret}")
                return False
                
            # Play in the background
            ctypes.windll.winmm.mciSendStringW('play jarvis_speech', None, 0, None)
            self.playing = True
            
            # Wait for playback completion or interruption
            status_buf = ctypes.create_unicode_buffer(128)
            while self.playing and not stop_event.is_set():
                ctypes.windll.winmm.mciSendStringW('status jarvis_speech mode', status_buf, 128, None)
                mode = status_buf.value.strip()
                if mode != "playing":
                    break
                time.sleep(0.02)
        finally:
            self.stop()
            
    def stop(self):
        import ctypes
        self.playing = False
        ctypes.windll.winmm.mciSendStringW('stop jarvis_speech', None, 0, None)
        ctypes.windll.winmm.mciSendStringW('close jarvis_speech', None, 0, None)


class TextToSpeech:
    """
    Handles speech synthesis using edge-tts (online neural) or piper-tts (offline).
    Includes text normalization (markdown, URLs, number-to-words) and non-blocking queueing.
    """
    def __init__(self, state_manager, loop, voice_name="en_US-lessac-medium", model_dir=None):
        self.state_manager = state_manager
        self.loop = loop
        self.speaking_state = False
        
        # Thread control flags and queues
        self.speak_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.running = True
        
        # Load config parameters
        from config import load_config
        config = load_config()
        self.engine = config.get("tts_engine", "edge").lower()
        self.voice_name = config.get("tts_voice", "en-GB-RyanNeural")
        
        # Resolve Piper model paths (always loaded as an offline fallback)
        self.piper_voice_name = "en_US-lessac-medium"
        user_home = os.path.expanduser("~")
        self.piper_model_dir = os.path.join(user_home, ".jarvis", "piper_models")
        os.makedirs(self.piper_model_dir, exist_ok=True)
        self.piper_model_path = os.path.join(self.piper_model_dir, f"{self.piper_voice_name}.onnx")
        self.piper_config_path = os.path.join(self.piper_model_dir, f"{self.piper_voice_name}.onnx.json")
        
        # Validate and download Piper model files if missing
        self._check_and_download_piper_models()
        
        # Initialize the PiperVoice fallback engine
        try:
            from piper.voice import PiperVoice
            self.piper_voice = PiperVoice.load(self.piper_model_path, config_path=self.piper_config_path)
            self.piper_sample_rate = self.piper_voice.config.sample_rate
            logger.info("Piper voice fallback engine loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Piper voice model: {e}")
            self.piper_voice = None
            
        # Start background synthesis & playback worker thread
        self.worker_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.worker_thread.start()

    def speak(self, text):
        """Public non-blocking interface to queue speech commands."""
        cleaned_text = text.strip()
        if cleaned_text:
            self.speak_queue.put(cleaned_text)

    def stop_speaking(self):
        """Interrupts playback immediately, stops active sound devices, and clears the queue."""
        self.stop_event.set()
        
        # Stop MCI player (used by edge-tts)
        try:
            import ctypes
            ctypes.windll.winmm.mciSendStringW('stop jarvis_speech', None, 0, None)
            ctypes.windll.winmm.mciSendStringW('close jarvis_speech', None, 0, None)
        except Exception:
            pass
            
        # Stop sounddevice streams (used by Piper)
        try:
            sd.stop()
        except Exception:
            pass
            
        # Flush the speak queue
        while not self.speak_queue.empty():
            try:
                self.speak_queue.get_nowait()
                self.speak_queue.task_done()
            except queue.Empty:
                break
                
        self.speaking_state = False
        self._update_state(JarvisState.IDLE)
        logger.info("Speech playback stopped and queue cleared.")

    def stop(self):
        """Gracefully terminates the background worker thread on exit."""
        self.running = False
        self.speak_queue.put(None)  # Sentinel unlock
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)

    def _tts_worker(self):
        """Background loop handling speech processing, synthesis, and audio output."""
        logger.info("TTS background worker thread started.")
        while self.running:
            try:
                text = self.speak_queue.get()
                if text is None:
                    break
                    
                # Reset stop event flag for a new synthesis turn
                self.stop_event.clear()
                self.speaking_state = True
                
                # Normalize and segment response into individual sentences
                processed_text = self._preprocess_text(text)
                sentences = self._split_into_sentences(processed_text)
                
                for sentence in sentences:
                    if self.stop_event.is_set():
                        break
                        
                    # Broadcast active speaking state to the HUD
                    self._update_state(JarvisState.SPEAKING, sentence)
                    
                    # Synthesize and play the sentence
                    success = False
                    if self.engine == "edge":
                        success = self._speak_edge(sentence)
                        if not success:
                            logger.warning("Edge TTS failed or offline. Falling back to offline Piper...")
                            success = self._speak_piper(sentence)
                    else:
                        success = self._speak_piper(sentence)
                        
                    if not success:
                        logger.error(f"Failed to play sentence: '{sentence}'")
                        
                self.speaking_state = False
                self._update_state(JarvisState.IDLE)
                self.speak_queue.task_done()
                
            except Exception as e:
                logger.error(f"Error in TTS background worker: {e}")
                self.speaking_state = False
                self._update_state(JarvisState.IDLE)
        logger.info("TTS background worker thread stopped.")

    def _speak_edge(self, sentence):
        """Synthesizes speech using edge-tts and plays via MCIPlayer."""
        import edge_tts
        import tempfile
        
        # Save temporary MP3 to the Windows temp folder
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, "jarvis_speech.mp3")
        
        # Ensure we pass an online neural voice (fallback to RyanNeural)
        voice = self.voice_name
        if not voice or voice.endswith(".onnx"):
            voice = "en-GB-RyanNeural"
            
        async def run_synthesis():
            communicate = edge_tts.Communicate(sentence, voice)
            await communicate.save(temp_path)
            
        try:
            # Execute the async synthesis synchronously inside the worker thread
            asyncio.run(run_synthesis())
            
            if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
                return False
                
            # Play using MCIPlayer
            player = MCIPlayer()
            player.play(temp_path, self.stop_event)
            
            # Attempt temp cleanup
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return True
            
        except Exception as e:
            logger.warning(f"edge-tts failed to synthesize (network issue?): {e}")
            return False

    def _speak_piper(self, sentence):
        """Synthesizes speech offline using Piper TTS and plays via sounddevice."""
        if not self.piper_voice:
            logger.error("Piper fallback voice is not initialized.")
            return False
            
        try:
            stream = sd.OutputStream(samplerate=self.piper_sample_rate, channels=1, dtype='int16')
            stream.start()
            
            for chunk in self.piper_voice.synthesize(sentence):
                if self.stop_event.is_set():
                    break
                stream.write(chunk.audio_int16_array)
                
            stream.stop()
            stream.close()
            return True
        except Exception as e:
            logger.error(f"Piper voice synthesis failure: {e}")
            return False

    def _preprocess_text(self, text):
        """Sanitizes text by stripping markdown, replacing URLs, and translating numbers > 999."""
        # 1. Strip markdown characters
        text = re.sub(r'[\*\#\`\_\~]', '', text)
        
        # 2. Replace URLs
        text = re.sub(r'https?://\S+', 'the link', text)
        
        # 3. Replace numbers > 999 with spoken form
        def replace_num(match):
            val = int(match.group(0))
            if val > 999:
                return self._convert_number_to_words(val)
            return match.group(0)
            
        text = re.sub(r'\d+', replace_num, text)
        return text

    def _convert_number_to_words(self, n):
        """Converts integer n to a spoken English representation (up to 1 Billion)."""
        if n == 0:
            return "zero"
        
        units = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", 
                 "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
        tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
        
        def helper(num):
            if num < 20:
                return units[num]
            elif num < 100:
                suffix = helper(num % 10)
                return tens[num // 10] + (" " + suffix if suffix else "")
            elif num < 1000:
                suffix = helper(num % 100)
                return units[num // 100] + " hundred" + (" and " + suffix if suffix else "")
            elif num < 1000000:
                suffix = helper(num % 1000)
                return helper(num // 1000) + " thousand" + (" " + suffix if suffix else "")
            elif num < 1000000000:
                suffix = helper(num % 1000000)
                return helper(num // 1000000) + " million" + (" " + suffix if suffix else "")
            else:
                return str(num)
                
        return helper(n).strip()

    def _split_into_sentences(self, text):
        """Segments a continuous response into individual sentences."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _update_state(self, state, text=""):
        """Dispatches active speech state back to the primary asyncio HUD thread."""
        if self.state_manager and self.loop:
            asyncio.run_coroutine_threadsafe(self.state_manager.set_state(state, text), self.loop)

    def _check_and_download_piper_models(self):
        """Downloads Piper voice models dynamically if not cached."""
        base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
        model_url = f"{base_url}/{self.piper_voice_name}.onnx"
        config_url = f"{base_url}/{self.piper_voice_name}.onnx.json"
        
        if not os.path.exists(self.piper_model_path):
            logger.info("Piper fallback model file not found. Downloading...")
            self._download_file(model_url, self.piper_model_path)
            
        if not os.path.exists(self.piper_config_path):
            logger.info("Piper fallback config file not found. Downloading...")
            self._download_file(config_url, self.piper_config_path)

    def _download_file(self, url, dest_path):
        import requests
        try:
            r = requests.get(url, stream=True)
            r.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            logger.info(f"Successfully downloaded fallback asset: {dest_path}")
        except Exception as e:
            logger.error(f"Failed to download Piper model asset: {e}")
