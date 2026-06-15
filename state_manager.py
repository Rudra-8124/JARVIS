import asyncio
import json
import logging
from enum import Enum

logger = logging.getLogger("jarvis")

class JarvisState(Enum):
    """Enumeration representing the possible states of the JARVIS assistant."""
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"

class StateManager:
    """
    Manages the JARVIS state machine and coordinates the WebSocket server
    to broadcast real-time state changes to all connected clients.
    """
    def __init__(self, port=8765):
        self._state = JarvisState.IDLE
        self._speaking_text = ""
        self._port = port
        self._clients = set()
        self._lock = asyncio.Lock()
        self.command_queue = asyncio.Queue()

    async def get_next_command(self):
        """Blocks until a text command is received from a WebSocket client."""
        return await self.command_queue.get()
        
    def submit_command(self, text: str):
        """Submits a command text to the queue (thread-safe/async-safe)."""
        self.command_queue.put_nowait(text)

    def get_state(self):
        """
        Getter function to access the current state name (string)
        usable by other modules in a simple way.
        """
        return self._state.value

    def get_speaking_text(self):
        """Returns the current text being spoken by the assistant."""
        return self._speaking_text

    async def set_state(self, state: JarvisState, text: str = ""):
        """
        Sets the state and broadcasts it to all connected websocket clients.
        If the state is SPEAKING or THINKING, text is included.
        """
        async with self._lock:
            self._state = state
            self._speaking_text = text if state in (JarvisState.SPEAKING, JarvisState.THINKING) else ""
            logger.info(f"State changed to: {self._state.value}" + (f" - '{text}'" if text else ""))
        
        await self._broadcast_state()

    async def _broadcast_state(self):
        """Helper to broadcast the current state as JSON to all connected clients."""
        if not self._clients:
            return
            
        payload = {"state": self._state.value}
        if self._state == JarvisState.SPEAKING:
            payload["text"] = self._speaking_text
        elif self._state == JarvisState.THINKING and self._speaking_text:
            payload["user_text"] = self._speaking_text

        message = json.dumps(payload)
        
        # Gather all clients and send state updates
        disconnected_clients = set()
        for client in self._clients:
            try:
                await client.send(message)
            except Exception as e:
                logger.debug(f"Error sending message to client: {e}")
                disconnected_clients.add(client)
        
        if disconnected_clients:
            self._clients.difference_update(disconnected_clients)

    async def register_client(self, websocket):
        """Registers a new WebSocket connection and sends the current state immediately."""
        self._clients.add(websocket)
        logger.debug(f"WebSocket client connected. Total clients: {len(self._clients)}")
        # Send current state upon connection
        payload = {"state": self._state.value}
        if self._state == JarvisState.SPEAKING:
            payload["text"] = self._speaking_text
        try:
            await websocket.send(json.dumps(payload))
        except Exception:
            self._clients.discard(websocket)

    def unregister_client(self, websocket):
        """Unregisters a WebSocket client when connection is closed."""
        self._clients.discard(websocket)
        logger.debug(f"WebSocket client disconnected. Total clients: {len(self._clients)}")

    async def start_server(self):
        """
        Starts the WebSocket server on port 8765 (or as configured).
        Returns the websockets server object.
        """
        import websockets
        async def handler(websocket):
            await self.register_client(websocket)
            try:
                # Listen for messages from connection
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        
                        if msg_type == "command":
                            text = data.get("text", "").strip()
                            if text:
                                logger.info(f"Received text command from HUD: {text}")
                                self.command_queue.put_nowait(text)
                                
                        elif msg_type == "get_config":
                            from config import load_config
                            config = load_config()
                            await websocket.send(json.dumps({
                                "type": "config",
                                "config": config
                            }))
                            
                        elif msg_type == "update_config":
                            from config import save_config, load_config
                            new_config = data.get("config", {})
                            if new_config:
                                current_config = load_config()
                                current_config.update(new_config)
                                save_config(current_config)
                                logger.info(f"Configuration updated from HUD: {new_config}")
                                
                                # Acknowledge the update
                                await websocket.send(json.dumps({
                                    "type": "update_config_success",
                                    "config": current_config
                                }))
                                
                        elif msg_type == "get_history":
                            from config import HISTORY_PATH
                            import os
                            history = []
                            if os.path.exists(HISTORY_PATH):
                                try:
                                    with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                                        history = json.load(f)
                                except Exception as e:
                                    logger.error(f"Error loading history for HUD: {e}")
                            await websocket.send(json.dumps({
                                "type": "history",
                                "history": history
                            }))
                    except Exception as e:
                        logger.error(f"Error handling WebSocket message: {e}")
            except websockets.exceptions.ConnectionClosed:
                pass
            finally:
                self.unregister_client(websocket)

        logger.info(f"Starting WebSocket server on localhost:{self._port}...")
        server = await websockets.serve(handler, "localhost", self._port)
        return server
