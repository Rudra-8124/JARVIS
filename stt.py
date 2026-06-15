import io
import logging
from faster_whisper import WhisperModel

logger = logging.getLogger("jarvis")

class SpeechToText:
    """
    Speech-to-text transcription module using the faster-whisper engine.
    Runs on CPU with int8 quantization for high-speed, local inference.
    """
    def __init__(self, model_size="base", device="cpu", compute_type="int8"):
        self.model_size = model_size
        logger.info(f"Initializing Whisper model '{model_size}' on {device} with {compute_type}...")
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
            logger.info("Whisper model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise e

    def transcribe(self, wav_bytes):
        """
        Transcribes the in-memory WAV bytes.
        Returns the combined transcription string (empty if no speech is detected).
        """
        if not wav_bytes:
            return ""
            
        try:
            # Load the raw audio bytes into an in-memory file-like object
            audio_file = io.BytesIO(wav_bytes)
            
            # Perform transcription (beam_size=5 is standard for good accuracy)
            segments, info = self.model.transcribe(audio_file, beam_size=5, language="en")
            
            # Since segments is a generator, we iterate to execute the model and collect results
            text_parts = [segment.text for segment in segments]
            transcription = "".join(text_parts).strip()
            
            logger.info(f"Transcription result: '{transcription}'")
            return transcription
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            return ""
