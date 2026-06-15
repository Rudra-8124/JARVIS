import os
import queue
import threading
import logging
import requests
import sounddevice as sd
from piper.voice import PiperVoice
from state_manager import JarvisState
import asyncio

logger = logging.getLogger("jarvis")

class TextToSpeech:
    """
    Manages text-to-speech synthesis using the local piper-tts library.
    Downloads the model files dynamically if they are missing.
    Synthesizes and plays audio sentence-by-sentence in a background thread to achieve low latency.
    """
    def __init__(self, state_manager, loop, voice_name="en_US-lessac-medium", model_dir=None):
        self.state_manager = state_manager
        self.loop = loop
        self.voice_name = voice_name
        
        # Resolve destination folder for Piper voice models
        if model_dir is None:
            user_home = os.path.expanduser("~")
            model_dir = os.path.join(user_home, ".jarvis", "piper_models")
        
        os.makedirs(model_dir, exist_ok=True)
        self.model_path = os.path.join(model_dir, f"{voice_name}.onnx")
        self.config_path = os.path.join(model_dir, f"{voice_name}.onnx.json")
        
        # Verify presence of model files and download them if missing
        self._check_and_download_models()
        
        # Load the PiperVoice model into memory
        logger.info(f"Loading Piper voice model '{voice_name}'...")
        try:
            self.voice = PiperVoice.load(self.model_path, config_path=self.config_path)
            logger.info("Piper voice model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Piper voice model: {e}")
            raise e
        
        # Extract model-specified audio sample rate (usually 22050Hz for medium models)
        self.sample_rate = self.voice.config.sample_rate
        logger.info(f"Piper audio sample rate: {self.sample_rate} Hz")
        
        # Thread-safe queue for incoming sentences
        self.speak_queue = queue.Queue()
        
        # Worker control flags
        self.running = True
        
        # Start worker thread for speech synthesis and playback
        self.worker_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.worker_thread.start()

    def _check_and_download_models(self):
        """Validates local model file availability and initiates download if needed."""
        base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
        model_url = f"{base_url}/{self.voice_name}.onnx"
        config_url = f"{base_url}/{self.voice_name}.onnx.json"
        
        if not os.path.exists(self.model_path):
            logger.info(f"Model file {self.model_path} not found. Downloading...")
            self._download_file(model_url, self.model_path)
            
        if not os.path.exists(self.config_path):
            logger.info(f"Config file {self.config_path} not found. Downloading...")
            self._download_file(config_url, self.config_path)

    def _download_file(self, url, dest_path):
        """Downloads a resource file from url to dest_path with download progress logs."""
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        bytes_downloaded = 0
        
        logger.info(f"Downloading: {url}")
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    if total_size > 0:
                        percent = (bytes_downloaded / total_size) * 100
                        # Log status updates on roughly 20% milestones to keep log size reasonable
                        if int(percent) % 20 == 0:
                            logger.info(f"Download progress: {percent:.1f}%")
        logger.info(f"Successfully downloaded to: {dest_path}")

    def speak(self, text):
        """Queues a sentence/phrase for speech synthesis."""
        cleaned_text = text.strip()
        if cleaned_text:
            self.speak_queue.put(cleaned_text)

    def stop(self):
        """Shuts down the background worker thread."""
        self.running = False
        self.speak_queue.put(None)  # Sentinel to unlock the worker queue
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)

    def _tts_worker(self):
        """
        Background synthesis loop.
        Retrieves text from the queue, performs synthesis, and plays audio through sounddevice.
        """
        try:
            # Open sounddevice output stream configured with the voice model parameters
            stream = sd.OutputStream(samplerate=self.sample_rate, channels=1, dtype='int16')
            stream.start()
        except Exception as e:
            logger.error(f"Failed to initialize sounddevice output stream: {e}")
            return

        logger.info("TTS background worker thread started.")
        
        while self.running:
            try:
                # Retrieve next speaking item (blocks if queue is empty)
                text = self.speak_queue.get()
                if text is None:
                    # Shutdown signal received
                    break
                
                # Update status variable and broadcast SPEAKING state via WebSocket
                self._update_state(JarvisState.SPEAKING, text)
                logger.info(f"Synthesizing speech for: '{text}'")
                
                # Synthesize text and stream chunks to the output stream
                for chunk in self.voice.synthesize(text):
                    if not self.running:
                        break
                    # Write NumPy int16 array to sounddevice output buffer (blocking write)
                    stream.write(chunk.audio_int16_array)
                
                self.speak_queue.task_done()
                
                # Transition back to IDLE when the queue is empty
                if self.speak_queue.empty():
                    self._update_state(JarvisState.IDLE)
                    
            except Exception as e:
                logger.error(f"Error occurred in TTS playback: {e}")
                self._update_state(JarvisState.IDLE)
                
        # Graceful stream closure
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        logger.info("TTS background worker thread stopped.")

    def _update_state(self, state, text=""):
        """Dispatches state updates back to the primary asyncio event loop."""
        asyncio.run_coroutine_threadsafe(self.state_manager.set_state(state, text), self.loop)
