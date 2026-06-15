import os
import json
import asyncio
import logging
import sys
import uuid
from state_manager import StateManager, JarvisState
from config import load_config, setup_logging, HISTORY_PATH
from audio_capture import calibrate_threshold, capture_audio
from stt import SpeechToText
from ai_brain import AIBrain
from tts import TextToSpeech
from wake_word import WakeWordDetector
from tray import SystemTrayManager
from skills import route_intent
from memory_manager import MemoryManager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Initialize the global logging configuration
logger = setup_logging()

class SentenceBuffer:
    """
    Accumulates character/word tokens from the AI stream and yields completed sentences
    based on standard punctuation markers. This minimizes voice output latency.
    """
    def __init__(self):
        self.buffer = ""
        self.endings = {'.', '?', '!'}

    def add_chunk(self, chunk):
        """Adds a chunk of text to the buffer and returns a list of completed sentences."""
        self.buffer += chunk
        sentences = []
        start_idx = 0
        i = 0
        while i < len(self.buffer):
            char = self.buffer[i]
            # Sentence boundary detection
            if char in self.endings:
                # Ensure it is followed by space/newline or is the end of the text
                if (i + 1 == len(self.buffer)) or (self.buffer[i + 1] in (' ', '\n')):
                    sentence = self.buffer[start_idx:i+1].strip()
                    if sentence:
                        sentences.append(sentence)
                    start_idx = i + 1
            elif char == '\n':
                sentence = self.buffer[start_idx:i].strip()
                if sentence:
                    sentences.append(sentence)
                start_idx = i + 1
            i += 1
            
        self.buffer = self.buffer[start_idx:]
        return sentences

    def flush(self):
        """Flushes the remaining content from the buffer as the final sentence."""
        remainder = self.buffer.strip()
        self.buffer = ""
        return remainder if remainder else None

def load_last_session(ai_brain):
    """Loads the last session's conversation history if it exists."""
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                history = json.load(f)
            ai_brain.load_history(history)
            logger.info("Loaded conversation history from last session.")
        except Exception as e:
            logger.error(f"Error loading last session history: {e}")

def save_last_session(ai_brain):
    """Saves the current conversation history to last session json."""
    try:
        history = ai_brain.save_history()
        with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=4)
        logger.info(f"Saved conversation history ({len(history)} messages) to {HISTORY_PATH}")
    except Exception as e:
        logger.error(f"Error saving conversation history: {e}")

async def main():
    logger.info("Starting J.A.R.V.I.S. assistant with wake-word and system tray icon...")
    
    # Cache the primary task so it can be cancelled from the tray thread on Quit
    main_task = asyncio.current_task()
    
    # 1. Load configuration file
    config = load_config()
    websocket_port = config.get("websocket_port", 8765)
    whisper_model_size = config.get("whisper_model_size", "base")
    # Updated default model value to llama3.2:3b
    ollama_model = config.get("ollama_model", "llama3.2:3b")
    tts_voice = config.get("tts_voice", "en_US-lessac-medium")
    history_limit = config.get("conversation_history_limit", 20)
    
    # Get active event loop to share with background threads
    loop = asyncio.get_running_loop()
    
    # Initialize Memory Manager and Session ID
    session_id = str(uuid.uuid4())
    memory_manager = MemoryManager(ollama_url=f"http://localhost:11434/api/generate", embed_model="nomic-embed-text")
    
    # 2. Initialize state manager
    state_manager = StateManager(port=websocket_port)
    
    # Mute and tracking variables
    is_muted = False
    wake_word_event = asyncio.Event()

    # Callback functions to interact from threads to the main asyncio loop
    def on_wake_word():
        """Triggered in background thread when 'Hey Jarvis' is heard."""
        loop.call_soon_threadsafe(wake_word_event.set)

    def on_toggle_mute(muted: bool):
        """Triggered from tray thread when mute state changes."""
        nonlocal is_muted
        is_muted = muted
        if is_muted:
            logger.info("J.A.R.V.I.S. is MUTED.")
            wake_word_detector.set_active(False)
            loop.call_soon_threadsafe(wake_word_event.clear)
        else:
            logger.info("J.A.R.V.I.S. is UNMUTED.")
            wake_word_detector.set_active(True)

    def on_tray_quit():
        """Triggered from tray thread when Quit is selected."""
        logger.info("Quit selected from tray. Triggering main loop shutdown...")
        loop.call_soon_threadsafe(main_task.cancel)

    # 3. Initialize background services
    # Initialize STT (Speech-To-Text)
    try:
        stt = SpeechToText(model_size=whisper_model_size)
    except Exception as e:
        logger.error(f"Failed to initialize Speech-to-Text: {e}")
        return
        
    # Initialize AI Brain
    # Note: ai_brain.py will resolve the endpoint dynamically to /api/generate
    ai_brain = AIBrain(model=ollama_model, history_limit=history_limit)
    load_last_session(ai_brain)
    
    # Initialize TTS (Text-To-Speech)
    try:
        tts = TextToSpeech(state_manager, loop, voice_name=tts_voice)
    except Exception as e:
        logger.error(f"Failed to initialize Text-to-Speech: {e}")
        return

    # Initialize Wake Word Detector
    try:
        wake_word_detector = WakeWordDetector(callback=on_wake_word, score_threshold=0.5)
        wake_word_detector.start()
    except Exception as e:
        logger.error(f"Failed to initialize Wake Word Detector: {e}")
        return

    # Initialize and Start System Tray Icon
    tray_manager = SystemTrayManager(
        on_toggle_mute_callback=on_toggle_mute, 
        on_quit_callback=on_tray_quit
    )
    tray_manager.start()

    # Schedule daily morning briefing
    async def run_morning_briefing():
        logger.info("Executing scheduled morning briefing...")
        briefing = memory_manager.morning_briefing()
        logger.info(f"Morning Briefing: {briefing}")
        tts.speak(briefing)

    scheduler = AsyncIOScheduler()
    briefing_time = config.get("briefing_time", "08:00")
    try:
        hour, minute = map(int, briefing_time.split(":"))
        scheduler.add_job(run_morning_briefing, 'cron', hour=hour, minute=minute)
        scheduler.start()
        logger.info(f"Morning briefing scheduled daily at {briefing_time}")
    except Exception as e:
        logger.error(f"Failed to schedule morning briefing: {e}")

    # 4. Start the WebSocket server
    ws_server = await state_manager.start_server()
    
    # 5. Calibrate microphone threshold
    # Run in a separate thread so it doesn't block the asyncio loop
    threshold = await asyncio.to_thread(calibrate_threshold)
    logger.info(f"Calibrated threshold: {threshold:.4f}")
    
    # Helper callback function to change state to listening from capture thread
    def trigger_listening():
        asyncio.run_coroutine_threadsafe(state_manager.set_state(JarvisState.LISTENING), loop)

    logger.info("J.A.R.V.I.S. is online, wake word active.")
    
    try:
        while True:
            # Load config dynamically at the start of each iteration to capture updates
            config = load_config()
            
            # Hot-reload Ollama model
            ai_brain.model = config.get("ollama_model", "llama3.2:3b")
            
            # Hot-reload TTS voice
            new_tts_voice = config.get("tts_voice", "en_US-lessac-medium")
            if new_tts_voice != tts.voice_name:
                logger.info(f"TTS voice changed from {tts.voice_name} to {new_tts_voice}. Reloading TTS engine...")
                tts.stop()
                try:
                    tts = TextToSpeech(state_manager, loop, voice_name=new_tts_voice)
                except Exception as e:
                    logger.error(f"Failed to reload Text-to-Speech: {e}")
                    
            # Hot-reload Whisper size
            new_whisper_size = config.get("whisper_model_size", "base")
            if new_whisper_size != stt.model_size:
                logger.info(f"Whisper model size changed from {stt.model_size} to {new_whisper_size}. Reloading STT engine...")
                try:
                    stt = SpeechToText(model_size=new_whisper_size)
                except Exception as e:
                    logger.error(f"Failed to reload Speech-to-Text: {e}")

            # Set state to IDLE
            await state_manager.set_state(JarvisState.IDLE)
            
            wake_word_event.clear()
            is_text_command = False
            user_text = ""
            
            if is_muted:
                wake_word_detector.set_active(False)
                logger.info("Standing by (MUTED)... Awaiting commands from HUD.")
                # Wait only for text commands from the HUD since mic is muted
                user_text = await state_manager.get_next_command()
                is_text_command = True
            else:
                wake_word_detector.set_active(True)
                logger.info("Standing by... Say 'Hey Jarvis' or send a command via HUD to activate.")
                
                # Wait for either wake word OR text command from HUD
                wake_word_task = asyncio.create_task(wake_word_event.wait())
                hud_command_task = asyncio.create_task(state_manager.get_next_command())
                
                done, pending = await asyncio.wait(
                    [wake_word_task, hud_command_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # Cancel the other task
                for task in pending:
                    task.cancel()
                    
                if hud_command_task in done:
                    user_text = hud_command_task.result()
                    is_text_command = True
                else:
                    is_text_command = False
            
            # Deactivate wake word engine during processing
            wake_word_detector.set_active(False)
            
            # If triggered via wake word, record and transcribe voice
            if not is_text_command:
                # Skip speech pipeline if the user muted while waiting
                if is_muted:
                    continue
                    
                # Transition state to LISTENING
                await state_manager.set_state(JarvisState.LISTENING)
                
                # Start recording speech command (runs in background thread until silence detected)
                wav_bytes = await asyncio.to_thread(
                    capture_audio, 
                    threshold=threshold, 
                    silence_duration=1.5, 
                    sample_rate=16000, 
                    trigger_listening_callback=trigger_listening
                )
                
                if not wav_bytes:
                    logger.info("No speech command captured.")
                    continue
                    
                # Set state to THINKING
                await state_manager.set_state(JarvisState.THINKING)
                
                # Transcribe audio using Whisper
                user_text = await asyncio.to_thread(stt.transcribe, wav_bytes)
                if user_text.strip():
                    await state_manager.set_state(JarvisState.THINKING, user_text)
            else:
                # Triggered via HUD text: Transition state directly to THINKING
                await state_manager.set_state(JarvisState.THINKING, user_text)
                logger.info(f"Processing HUD text command: '{user_text}'")
            
            if not user_text.strip():
                logger.info("Empty command. Returning to standby.")
                continue
                
            logger.info(f"User command: {user_text}")

            # Extract user facts from text query
            try:
                memory_manager.extract_and_save_facts(user_text)
            except Exception as e:
                logger.error(f"Error extracting facts: {e}")

            # Build memory context from SQLite + ChromaDB
            try:
                mem_context = memory_manager.build_memory_context(user_text)
            except Exception as e:
                logger.error(f"Error building memory context: {e}")
                mem_context = None
            
            # 1. Try to route the intent to a local skill
            try:
                func, params = route_intent(user_text, model=ai_brain.model)
            except Exception as e:
                logger.error(f"Error routing intent: {e}")
                func, params = None, None
                
            if func:
                logger.info(f"Executing skill: {func.__name__} with parameters: {params}")
                try:
                    response_text = func(**params)
                    tts.speak(response_text)
                    await asyncio.to_thread(tts.speak_queue.join)
                    
                    # Add to conversation history so context is preserved
                    ai_brain.add_user_message(user_text)
                    ai_brain.add_assistant_message(response_text)

                    # Save to long-term memory
                    try:
                        memory_manager.save_conversation(user_text, response_text, session_id)
                    except Exception as e:
                        logger.error(f"Error saving conversation to long-term memory: {e}")
                except Exception as e:
                    logger.error(f"Error executing skill {func.__name__}: {e}")
                    tts.speak("I encountered an error executing that request, sir.")
                    await asyncio.to_thread(tts.speak_queue.join)
            else:
                # 2. Fallback to Ollama conversational response
                try:
                    sentence_buf = SentenceBuffer()
                    assistant_response = []
                    async for chunk in ai_brain.generate_response_stream(user_text, mem_context=mem_context):
                        assistant_response.append(chunk)
                        sentences = sentence_buf.add_chunk(chunk)
                        for sentence in sentences:
                            tts.speak(sentence)
                            
                    # Flush final sentence
                    remainder = sentence_buf.flush()
                    if remainder:
                        tts.speak(remainder)
                        
                    # Wait until speech synthesis queue is fully empty and played back
                    await asyncio.to_thread(tts.speak_queue.join)
                    
                    # Save to long-term memory
                    try:
                        assistant_reply = "".join(assistant_response)
                        memory_manager.save_conversation(user_text, assistant_reply, session_id)
                    except Exception as e:
                        logger.error(f"Error saving conversation to long-term memory: {e}")
                    
                except Exception as e:
                    logger.error(f"Error during dialogue handling: {e}")
                    tts.speak(str(e))
                    await asyncio.to_thread(tts.speak_queue.join)
                
    except asyncio.CancelledError:
        logger.info("Main orchestrator task cancelled. Initiating cleanup...")
    finally:
        # Graceful shutdown process
        logger.info("Stopping all J.A.R.V.I.S. services...")
        
        # Stop scheduled jobs
        try:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")
        except Exception as e:
            logger.error(f"Failed to stop scheduler: {e}")
            
        # Stop wake word detector thread
        wake_word_detector.stop()
        
        # Stop tray icon
        tray_manager.stop()
        
        # Stop TTS worker thread
        tts.stop()
        
        # Close WebSocket server
        ws_server.close()
        await ws_server.wait_closed()
        logger.info("WebSocket server closed.")
        
        # Save session history
        save_last_session(ai_brain)
        logger.info("J.A.R.V.I.S. has shut down.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Catch Ctrl+C at the root level for clean termination on Windows
        logger.info("Ctrl+C detected. Exiting application...")
        sys.exit(0)
