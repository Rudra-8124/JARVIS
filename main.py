import os
import sys
import json
import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime

# Local module imports
from state_manager import StateManager, JarvisState
from config import load_config, setup_logging, HISTORY_PATH
from audio_capture import capture_speech
from stt import SpeechToText
from ai_brain import AIBrain, check_ollama
from tts import TextToSpeech
from wake_word import WakeWordDetector
from tray import SystemTrayManager
import skills
from memory_manager import MemoryManager

# Global state manager and tts for callbacks/helper access
state_manager = None
tts_instance = None
ai_brain_instance = None

logger = setup_logging()

JARVIS_LOGO = """
      ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
      ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
      ██║███████║██████╔╝██║   ██║██║███████╗
 ██   ██║██╔══██║██╔══██║╚██╗ ██╔╝██║╚════██║
 ╚█████╔╝██║  ██║██║  ██║  ╚████╔╝ ██║███████║
  ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═══╝  ╚═╝╚══════╝
       - Just A Rather Very Intelligent System -
"""

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

def broadcast_ws(payload):
    """Broadcasts a payload to all connected clients on the ws_loop thread."""
    global state_manager
    if not state_manager:
        return
    ws_loop = getattr(state_manager, "ws_loop", None)
    if not ws_loop or not ws_loop.is_running():
        return
        
    async def do_send():
        if state_manager and state_manager._clients:
            message = json.dumps(payload)
            disconnected = set()
            for client in list(state_manager._clients):
                try:
                    await client.send(message)
                except Exception:
                    disconnected.add(client)
            if disconnected:
                state_manager._clients.difference_update(disconnected)
                
    asyncio.run_coroutine_threadsafe(do_send(), ws_loop)

def run_ws_server(state_manager, port, ws_loop):
    """Runs the websocket server inside a background thread's loop."""
    async def server_task():
        server = await state_manager.start_server()
        await server.wait_closed()
        
    def target():
        asyncio.set_event_loop(ws_loop)
        ws_loop.run_until_complete(server_task())
        
    t = threading.Thread(target=target, name="WebSocketServerThread", daemon=True)
    t.start()
    return t

async def run_orchestrator(stt, tts, wake_word, state_manager, ai_brain, keyboard_queue, memory_manager, session_id):
    """
    Core orchestrator task managing the asyncio concurrent loops:
    - Task 1: Wake word listener
    - Task 2: Keyboard commands consumer
    - Task 3: HUD WebSocket commands consumer
    """
    
    async def execute_and_speak(text):
        if not text or not text.strip():
            return
            
        # Extract user facts and save to long-term memory
        try:
            memory_manager.extract_and_save_facts(text)
        except Exception as e:
            logger.error(f"Error extracting facts: {e}")

        # Build memory context from SQLite + ChromaDB
        try:
            mem_context = memory_manager.build_memory_context(text)
        except Exception as e:
            logger.error(f"Error building memory context: {e}")
            mem_context = None
            
        broadcast_ws({"state": "thinking", "user_text": text})
        print(f"You: {text}")
        
        # Check for skill commands first (fast, local)
        skill_response = skills.route(text)
        if skill_response:
            response = skill_response
        else:
            # AI brain (slower)
            state_manager.set("THINKING")
            response = ai_brain.generate(text, mem_context=mem_context)
            
        # Speak response
        state_manager.set("SPEAKING")
        broadcast_ws({"state": "speaking", "text": response})
        print(f"JARVIS: {response}")
        tts.speak(response)  # non-blocking, runs in thread
        
        # Save to memory
        try:
            memory_manager.save_conversation(text, response, session_id)
        except Exception as e:
            logger.error(f"Error saving conversation to long-term memory: {e}")
            
        # Wait for speech to finish
        while tts.is_speaking():
            await asyncio.sleep(0.1)
            
        state_manager.set("IDLE")
        broadcast_ws({"state": "idle"})
        
    async def process_command(audio):
        state_manager.set("LISTENING")
        text = stt.transcribe(audio)
        if text is None:
            tts.speak("I didn't catch that, sir.")
            state_manager.set("IDLE")
            broadcast_ws({"state": "idle"})
            return
            
        await execute_and_speak(text)

    # Task 1 - Wake word listener
    async def wake_word_listener_loop():
        while True:
            # Run the blocking openwakeword listen in a worker thread
            detected = await asyncio.to_thread(wake_word.listen)
            if detected:
                # Interrupt: if wake word detected while JARVIS is speaking, stop speech immediately
                if tts.is_speaking():
                    tts.stop_speaking()
                    
                state_manager.set("LISTENING")
                broadcast_ws({"state": "listening"})
                
                # Capture VAD-gated speech in a thread
                audio = await asyncio.to_thread(capture_speech)
                if audio is None or len(audio) < 8000:  # too short, ignore
                    state_manager.set("IDLE")
                    broadcast_ws({"state": "idle"})
                    continue
                    
                await process_command(audio)
                
    wake_word_task = asyncio.create_task(wake_word_listener_loop())
    
    # Task 2 - Keyboard commands consumer
    async def keyboard_consumer_loop():
        while True:
            text = await keyboard_queue.get()
            if text:
                if tts.is_speaking():
                    tts.stop_speaking()
                await execute_and_speak(text)
                
    keyboard_consumer_task = asyncio.create_task(keyboard_consumer_loop())
    
    # Task 3 - HUD WebSocket commands consumer
    async def hud_consumer_loop():
        while True:
            text = await state_manager.get_next_command()
            if text:
                if tts.is_speaking():
                    tts.stop_speaking()
                await execute_and_speak(text)
                
    hud_consumer_task = asyncio.create_task(hud_consumer_loop())
    
    # Run all tasks concurrently
    try:
        await asyncio.gather(
            wake_word_task,
            keyboard_consumer_task,
            hud_consumer_task
        )
    finally:
        wake_word_task.cancel()
        keyboard_consumer_task.cancel()
        hud_consumer_task.cancel()

async def shutdown_sequence(tray_manager, wake_word, tts, ai_brain):
    """Graceful shutdown sequence."""
    print("\nShutting down, sir. Goodbye.", flush=True)
    try:
        # Play a local shutdown announcement
        import win32com.client
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        speaker.Speak("Shutting down, sir. Goodbye.")
    except Exception:
        try:
            import subprocess
            cmd = 'powershell -Command "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak(\'Shutting down, sir. Goodbye.\')"'
            subprocess.run(cmd, shell=True, timeout=5)
        except Exception:
            pass
            
    try:
        if ai_brain:
            save_last_session(ai_brain)
    except Exception as e:
        logger.error(f"Error saving session on exit: {e}")
        
    try:
        if tray_manager:
            tray_manager.stop()
    except Exception:
        pass
    try:
        if wake_word:
            wake_word.stop()
    except Exception:
        pass
    try:
        if tts:
            tts.stop()
    except Exception:
        pass
        
    logger.info("J.A.R.V.I.S. cleanly shut down.")
    sys.exit(0)

async def main():
    global state_manager, tts_instance, ai_brain_instance
    
    # 1. Print ASCII art JARVIS logo to terminal
    print(JARVIS_LOGO, flush=True)
    
    # 2. Check Ollama is running
    print("Checking Ollama availability...", flush=True)
    # Perform startup check. Speech output is handled inside check_ollama on error.
    check_ollama()
    
    # 3. Load config from C:/Users/{user}/.jarvis/config.json
    print("Loading config...", flush=True)
    config = load_config()
    
    # 4. Initialize all modules: STT, TTS, wake word, state manager
    print("Initializing J.A.R.V.I.S. core modules...", flush=True)
    state_manager = StateManager(port=config.get("websocket_port", 8765))
    
    whisper_model_size = config.get("whisper_model_size", "base")
    stt = SpeechToText(model_size=whisper_model_size)
    
    ollama_model = config.get("ollama_model", "llama3.2:3b")
    ai_brain = AIBrain(model=ollama_model, history_limit=config.get("conversation_history_limit", 20))
    ai_brain_instance = ai_brain
    load_last_session(ai_brain)
    
    loop = asyncio.get_running_loop()
    tts = TextToSpeech(state_manager, loop, voice_name=config.get("tts_voice", "en-GB-RyanNeural"))
    tts_instance = tts
    
    wake_word = WakeWordDetector(callback=None, score_threshold=0.5)
    
    # Initialize Memory Manager and Session ID
    session_id = str(uuid.uuid4())
    memory_manager = MemoryManager(ollama_url=f"http://localhost:11434/api/generate", embed_model="nomic-embed-text")
    
    # 5. Speak startup message
    startup_msg = "J.A.R.V.I.S. online. All systems nominal, sir."
    print(startup_msg, flush=True)
    tts.speak(startup_msg)
    
    # 6. Start WebSocket server on port 8765 in background thread
    print("Starting background WebSocket server thread...", flush=True)
    ws_loop = asyncio.new_event_loop()
    state_manager.ws_loop = ws_loop
    ws_thread = run_ws_server(state_manager, config.get("websocket_port", 8765), ws_loop)
    
    # 7. Start system tray icon in background thread
    print("Starting background System Tray thread...", flush=True)
    def on_toggle_mute(muted: bool):
        logger.info(f"System Tray: mute toggled to {muted}")
        
    def on_tray_quit():
        logger.info("System Tray: Quit command selected.")
        asyncio.run_coroutine_threadsafe(
            shutdown_sequence(tray_manager, wake_word, tts, ai_brain),
            loop
        )
        
    tray_manager = SystemTrayManager(
        on_toggle_mute_callback=on_toggle_mute,
        on_quit_callback=on_tray_quit
    )
    tray_manager.start()
    
    # Keyboard queue and task initialized once to prevent thread leak on crash recovery
    keyboard_queue = asyncio.Queue()
    async def keyboard_listener_task():
        while True:
            text = await asyncio.to_thread(input, "")
            if text.strip():
                await keyboard_queue.put(text.strip())
                
    asyncio.create_task(keyboard_listener_task())
    
    # 8. Enter main loop
    print("All systems fully operational. Standing by.", flush=True)
    while True:
        try:
            await run_orchestrator(
                stt=stt,
                tts=tts,
                wake_word=wake_word,
                state_manager=state_manager,
                ai_brain=ai_brain,
                keyboard_queue=keyboard_queue,
                memory_manager=memory_manager,
                session_id=session_id
            )
        except asyncio.CancelledError:
            logger.info("Orchestrator loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Crash recovery caught exception in main loop: {e}", exc_info=True)
            print(f"\n[CRASH] J.A.R.V.I.S. encountered a localized system fault: {e}")
            print("Auto-restarting orchestrator array in 2 seconds...\n", flush=True)
            await asyncio.sleep(2)
            
    # Exit gracefully if the infinite loop ends
    await shutdown_sequence(tray_manager, wake_word, tts, ai_brain)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Catch KeyboardInterrupt at root level (Ctrl+C in terminal)
        print("\nCtrl+C detected in main terminal.", flush=True)
        # We can't await inside sync context, so run synchronous cleanup
        print("Shutting down, sir. Goodbye.", flush=True)
        try:
            import win32com.client
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Speak("Shutting down, sir. Goodbye.")
        except Exception:
            try:
                import subprocess
                cmd = 'powershell -Command "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak(\'Shutting down, sir. Goodbye.\')"'
                subprocess.run(cmd, shell=True, timeout=5)
            except Exception:
                pass
                
        if ai_brain_instance:
            try:
                save_last_session(ai_brain_instance)
            except Exception:
                pass
        sys.exit(0)
