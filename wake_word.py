import time
import logging
import threading
import numpy as np
import sounddevice as sd
import openwakeword
from openwakeword.model import Model

logger = logging.getLogger("jarvis")

class WakeWordDetector:
    """
    Background worker that continuously listens to the microphone for the
    'Hey Jarvis' wake word using openWakeWord + ONNX, plays a confirmation chime,
    and calls a callback to wake up the assistant.
    """
    def __init__(self, callback, score_threshold=0.5, sample_rate=16000):
        self.callback = callback
        self.score_threshold = score_threshold
        self.sample_rate = sample_rate
        self.chunk_size = 1280  # Required frame size for openWakeWord (80ms at 16kHz)
        
        # Ensure pre-trained models are downloaded before loading
        try:
            logger.info("Checking openWakeWord models...")
            openwakeword.utils.download_models()
        except Exception as e:
            logger.warning(f"Failed to check/download openWakeWord models: {e}")

        # Initialize the openWakeWord model using ONNX framework
        logger.info("Loading pre-trained 'hey_jarvis' model...")
        try:
            self.model = Model(
                wakeword_models=["hey_jarvis"],
                enable_speex_noise_suppression=False,  # Speex is not supported on Windows
                vad_threshold=0.5,                     # Enable built-in Silero VAD gating
                inference_framework="onnx"
            )
            logger.info("openWakeWord model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load openWakeWord model: {e}")
            raise e

        self.active = False
        self.running = False
        self.thread = None
        self.last_detection_time = 0
        self._lock = threading.Lock()

    def listen(self):
        """
        Blocks until the 'Hey Jarvis' wake word is detected.
        Returns True once detected.
        """
        chunk_size = self.chunk_size
        sample_rate = self.sample_rate
        
        try:
            stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype='int16',
                blocksize=chunk_size
            )
            stream.start()
        except Exception as e:
            logger.error(f"Failed to open microphone for wake word detection: {e}")
            time.sleep(1.0)
            return False

        logger.info("Wake word detector (listen mode) is online. Awaiting wake word...")
        
        try:
            while True:
                chunk, overflowed = stream.read(chunk_size)
                if overflowed:
                    logger.debug("Wake word microphone input overflowed.")

                audio_data = chunk.flatten()
                prediction = self.model.predict(audio_data)
                score = prediction.get("hey_jarvis", 0.0)

                if score > self.score_threshold:
                    now = time.time()
                    if now - self.last_detection_time > 3.0:
                        self.last_detection_time = now
                        logger.info(f"Wake word 'Hey Jarvis' detected via listen()! Score: {score:.3f}")
                        self._play_chime()
                        return True
                time.sleep(0.01)
        except Exception as e:
            logger.error(f"Error in wake word detection loop: {e}")
            return False
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def start(self):
        """Starts the background listening thread."""
        with self._lock:
            if not self.running:
                self.running = True
                self.active = True
                self.thread = threading.Thread(target=self._listen_loop, daemon=True)
                self.thread.start()
                logger.info("Wake word detector background thread started.")

    def stop(self):
        """Stops the background listening thread."""
        with self._lock:
            self.running = False
            self.active = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            logger.info("Wake word detector background thread stopped.")

    def set_active(self, active: bool):
        """Pauses/resumes wake word detection processing."""
        with self._lock:
            self.active = active
            logger.debug(f"Wake word detector active state set to: {active}")

    def _listen_loop(self):
        """Continuous background audio capture and inference loop."""
        try:
            # Open the sounddevice input stream
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype='int16',
                blocksize=self.chunk_size
            )
            stream.start()
        except Exception as e:
            logger.error(f"Failed to open microphone for wake word detection: {e}")
            return

        logger.info("Wake word microphone capture stream is online.")

        while self.running:
            try:
                # Read audio chunk from the device
                chunk, overflowed = stream.read(self.chunk_size)
                if overflowed:
                    logger.debug("Wake word microphone input overflowed.")

                with self._lock:
                    if not self.active:
                        # Sleep briefly to avoid high CPU usage when paused
                        time.sleep(0.05)
                        continue

                # Flatten the 2D chunk to a 1D NumPy array
                audio_data = chunk.flatten()

                # Get prediction scores
                prediction = self.model.predict(audio_data)
                score = prediction.get("hey_jarvis", 0.0)

                if score > self.score_threshold:
                    now = time.time()
                    # 3-second cooldown to avoid duplicate triggers
                    if now - self.last_detection_time > 3.0:
                        self.last_detection_time = now
                        logger.info(f"Wake word 'Hey Jarvis' detected! Score: {score:.3f}")
                        
                        # Play confirmation chime (two-tone sound)
                        self._play_chime()
                        
                        # Trigger target callback
                        if self.callback:
                            self.callback()
                            
            except Exception as e:
                logger.error(f"Error in wake word detection: {e}")
                time.sleep(0.1)

        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        logger.info("Wake word microphone capture stream closed.")

    def _play_chime(self):
        """Plays a high-tech two-tone chime synchronously using sounddevice and numpy."""
        try:
            sample_rate = 22050
            # Tone 1: 880 Hz (A5) for 0.12 seconds
            # Tone 2: 1100 Hz (C#6) for 0.18 seconds
            t1 = np.linspace(0, 0.12, int(sample_rate * 0.12), False)
            t2 = np.linspace(0, 0.18, int(sample_rate * 0.18), False)
            
            tone1 = np.sin(2 * np.pi * 880 * t1)
            tone2 = np.sin(2 * np.pi * 1100 * t2)
            
            # Apply linear envelopes to prevent clicks
            fade_len = int(sample_rate * 0.02)
            fade_in = np.linspace(0, 1, fade_len)
            fade_out = np.linspace(1, 0, fade_len)
            
            tone1[:fade_len] *= fade_in
            tone1[-fade_len:] *= fade_out
            tone2[:fade_len] *= fade_in
            tone2[-fade_len:] *= fade_out
            
            # Combine tones
            chime = np.concatenate([tone1, tone2])
            
            # Scale to safe volume int16 PCM format
            audio_data = (chime * 16384).astype(np.int16)
            
            # Play and block until finished
            sd.play(audio_data, sample_rate)
            sd.wait()
        except Exception as e:
            logger.error(f"Failed to play wake word chime: {e}")
