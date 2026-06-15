import numpy as np
import sounddevice as sd
import webrtcvad
import logging

logger = logging.getLogger("jarvis")

def calibrate_threshold(sample_rate=16000, duration=0.5):
    """
    Legacy calibrator stub to maintain backward-compatibility with main.py calls.
    Returns a default threshold value as VAD handles speech gating.
    """
    logger.info("VAD engine active. Skipping noise-floor calibration.")
    return 0.03

def is_too_quiet(audio_chunk):
    """
    Returns True if the root-mean-square (RMS) energy of the float32 audio
    chunk is below 0.001, filtering out empty background noise.
    """
    rms = np.sqrt(np.mean(audio_chunk**2))
    return rms < 0.001

def capture_audio(threshold=0.03, silence_duration=1.2, sample_rate=16000, trigger_listening_callback=None):
    """
    Captures mono speech audio at 16000Hz using WebRTC VAD.
    
    - VAD aggressiveness level: 3 (most aggressive filtering).
    - Checks RMS energy to skip silent chunks entirely (energy < 0.001).
    - Requires 3 consecutive 30ms speech frames to trigger recording.
    - Automatically stops after 1.2 seconds of consecutive silence.
    - Limits recording to a maximum of 15 seconds.
    - Discards recordings shorter than 0.5 seconds as noise.
    - Returns a numpy float32 array at 16kHz or None.
    """
    vad = webrtcvad.Vad(3)
    
    frame_duration_ms = 30
    frame_samples = int(sample_rate * frame_duration_ms / 1000)  # 480 samples at 16kHz
    
    recorded_frames = []
    is_recording = False
    consecutive_speech = 0
    consecutive_silence = 0
    
    # Pre-roll history buffer of 10 frames (300ms) to avoid clipping start of speech
    pre_roll_limit = 10
    pre_roll_buffer = []
    
    print(" Listening...", flush=True)
    
    try:
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype='float32', blocksize=frame_samples) as stream:
            while True:
                # Read exactly one 30ms block
                frame, overflowed = stream.read(frame_samples)
                if overflowed:
                    logger.debug("Audio input stream overflowed.")
                
                frame_data = frame.flatten()
                
                # Check RMS quietness
                if is_too_quiet(frame_data):
                    is_speech = False
                else:
                    # Convert float32 [-1.0, 1.0] to signed int16 PCM for WebRTC VAD
                    frame_int16 = np.clip(frame_data * 32767.0, -32768.0, 32767.0).astype(np.int16)
                    raw_bytes = frame_int16.tobytes()
                    try:
                        is_speech = vad.is_speech(raw_bytes, sample_rate)
                    except Exception as e:
                        logger.error(f"VAD classification error: {e}")
                        is_speech = False
                
                if not is_recording:
                    # Rolling history buffer
                    pre_roll_buffer.append(frame_data)
                    if len(pre_roll_buffer) > pre_roll_limit:
                        pre_roll_buffer.pop(0)
                    
                    if is_speech:
                        consecutive_speech += 1
                        if consecutive_speech >= 3:
                            is_recording = True
                            print(" Recording...", flush=True)
                            if trigger_listening_callback:
                                trigger_listening_callback()
                            recorded_frames = list(pre_roll_buffer)
                    else:
                        consecutive_speech = 0
                else:
                    recorded_frames.append(frame_data)
                    
                    if not is_speech:
                        consecutive_silence += 1
                        silence_threshold_frames = int(silence_duration / (frame_duration_ms / 1000))
                        if consecutive_silence >= silence_threshold_frames:
                            logger.info("Silence duration exceeded threshold. Stopping capture.")
                            break
                    else:
                        consecutive_silence = 0
                    
                    # Auto-stop after 15 seconds (15 / 0.03 = 500 frames)
                    max_frames = int(15.0 / (frame_duration_ms / 1000))
                    if len(recorded_frames) >= max_frames:
                        logger.info("Maximum recording limit (15s) reached. Stopping capture.")
                        break
                        
    except Exception as e:
        logger.error(f"Error reading from microphone: {e}")
        return None
        
    if not recorded_frames:
        return None
        
    full_audio = np.concatenate(recorded_frames)
    duration = len(full_audio) / sample_rate
    
    # Minimum duration check (0.5 seconds)
    if duration < 0.5:
        logger.info(f"Discarding short audio snippet ({duration:.2f}s).")
        return None
        
    logger.info(f"Successfully captured audio segment: {duration:.2f}s.")
    return full_audio
