import logging
from faster_whisper import WhisperModel

logger = logging.getLogger("jarvis")

class SpeechToText:
    """
    Speech-to-text transcription module using the faster-whisper base.en engine.
    Runs on CPU with int8 quantization for high-speed, local inference.
    """
    def __init__(self, model_size="base.en", device="cpu", compute_type="int8"):
        # Map generic 'base' size requests to 'base.en' for faster/more accurate English transcription
        if model_size == "base":
            model_size = "base.en"
            
        self.model_size = model_size
        logger.info(f"Initializing Whisper model '{model_size}' on {device} with {compute_type}...")
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
            logger.info("Whisper model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise e

    def transcribe(self, audio_numpy):
        """
        Transcribes a 1D float32 numpy array at 16kHz.
        Applies confidence thresholds and filters out common Whisper hallucinations.
        Returns the clean transcribed string or None.
        """
        if audio_numpy is None or len(audio_numpy) == 0:
            return None
            
        try:
            # Transcribe with specific arguments for higher accuracy and hallucination reduction
            segments, info = self.model.transcribe(
                audio_numpy,
                beam_size=5,
                best_of=5,
                temperature=0.0,
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.4,
                language="en"
            )
            
            segments = list(segments)
            if not segments:
                return None
                
            # Log transcription confidence metrics
            first_segment = segments[0]
            avg_logprob = first_segment.avg_logprob
            logger.info(f"Whisper segment avg_logprob: {avg_logprob:.4f}")
            print(f" Whisper confidence (avg_logprob): {avg_logprob:.4f}")
            
            # Discard low-confidence transcriptions (avg_logprob < -1.0)
            if avg_logprob < -1.0:
                logger.info(f"Transcription confidence below threshold ({avg_logprob:.4f} < -1.0). Discarding.")
                return None
                
            text = " ".join(segment.text for segment in segments).strip()
            if not text:
                return None
                
            # Clean text and verify length/hallucinations
            cleaned_phrase = text.lower().strip(" .,!?")
            
            # Common faster-whisper hallucinations list
            hallucinations = [
                "thank you", "thanks for watching", "you", ".", " ", 
                "bye", "goodbye", "see you next time", "please subscribe"
            ]
            
            if cleaned_phrase in hallucinations or not cleaned_phrase:
                logger.info(f"Discarding common Whisper hallucination/filler: '{text}'")
                return None
                
            if len(text.strip()) < 3:
                logger.info(f"Discarding short noise fragment: '{text}'")
                return None
                
            # Strip leading/trailing whitespace and punctuation
            final_text = text.strip(" .,!?")
            return final_text
            
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            return None
