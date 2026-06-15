import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wavfile
import io
import time
import logging

logger = logging.getLogger("jarvis")

def calibrate_threshold(sample_rate=16000, duration=0.5):
    """
    Measures ambient noise floor for `duration` seconds and calculates
    a dynamic speech detection threshold (2.5x noise RMS, min floor of 0.015).
    """
    logger.info("Calibrating microphone noise floor... Please remain silent.")
    num_frames = int(sample_rate * duration)
    try:
        audio = sd.rec(num_frames, samplerate=sample_rate, channels=1, dtype='float32')
        sd.wait()
        rms = np.sqrt(np.mean(audio**2))
        threshold = max(rms * 2.5, 0.015)
        logger.info(f"Calibration complete. Noise floor RMS: {rms:.4f}, Threshold set to: {threshold:.4f}")
        return threshold
    except Exception as e:
        logger.warning(f"Calibration failed: {e}. Falling back to default threshold 0.03")
        return 0.03

def capture_audio(threshold=0.03, silence_duration=1.5, sample_rate=16000, trigger_listening_callback=None):
    """
    Listens to the default microphone.
    - Uses pre-rolling (keeps last 0.5s of audio) to avoid cutting off the start of speech.
    - Transitions to LISTENING when volume exceeds threshold.
    - Stops recording when silence (volume below threshold) is detected for `silence_duration` seconds.
    - Returns in-memory WAV bytes (16kHz, mono, 16-bit PCM).
    """
    chunk_size = 1024
    pre_roll_duration = 0.5  # Maintain 0.5s pre-trigger history
    pre_roll_chunks_limit = int((sample_rate * pre_roll_duration) / chunk_size)
    
    pre_roll_buffer = []
    recorded_chunks = []
    is_recording = False
    silence_start_time = None
    
    logger.info("Microphone is active. Listening for speech...")
    
    try:
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype='float32') as stream:
            while True:
                # Read a chunk of audio from the input stream
                chunk, overflowed = stream.read(chunk_size)
                if overflowed:
                    logger.debug("Audio input stream overflowed.")
                
                audio_data = chunk.flatten()
                rms = np.sqrt(np.mean(audio_data**2))
                
                if not is_recording:
                    # Keep rolling pre-roll buffer
                    pre_roll_buffer.append(audio_data)
                    if len(pre_roll_buffer) > pre_roll_chunks_limit:
                        pre_roll_buffer.pop(0)
                    
                    # Trigger voice recording when signal exceeds threshold
                    if rms > threshold:
                        is_recording = True
                        logger.info("Voice detected! Recording speech...")
                        if trigger_listening_callback:
                            trigger_listening_callback()
                        
                        # Build initial buffer from pre-roll
                        recorded_chunks = list(pre_roll_buffer)
                else:
                    recorded_chunks.append(audio_data)
                    
                    if rms < threshold:
                        if silence_start_time is None:
                            silence_start_time = time.time()
                        elif time.time() - silence_start_time >= silence_duration:
                            logger.info("Speech finished. Silence detected.")
                            break
                    else:
                        silence_start_time = None
                        
    except Exception as e:
        logger.error(f"Error reading from microphone: {e}")
        return None
                    
    if not recorded_chunks:
        return None
        
    full_audio = np.concatenate(recorded_chunks)
    duration = len(full_audio) / sample_rate
    
    # Ignore false triggers (less than 0.5 seconds of total recording)
    if duration < 0.5:
        logger.info("Speech duration too short, discarding recording.")
        return None
        
    # Scale float32 [-1.0, 1.0] to signed int16 PCM [-32768, 32767]
    audio_int16 = np.clip(full_audio * 32767.0, -32768.0, 32767.0).astype(np.int16)
    
    # Write WAV to in-memory buffer
    wav_io = io.BytesIO()
    wavfile.write(wav_io, sample_rate, audio_int16)
    wav_io.seek(0)
    
    return wav_io.read()
