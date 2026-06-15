import threading
import logging
from PIL import Image, ImageDraw
import pystray

logger = logging.getLogger("jarvis")

class SystemTrayManager:
    """
    Manages the Windows system tray icon using pystray and Pillow.
    Operates on a background thread and communicates state updates
    (such as muting or quitting) back to the main application loop.
    """
    def __init__(self, on_toggle_mute_callback, on_quit_callback):
        self.on_toggle_mute_callback = on_toggle_mute_callback
        self.on_quit_callback = on_quit_callback
        
        self.is_muted = False
        
        # Draw tray icon images programmatically
        self.active_image = self._create_active_image()
        self.muted_image = self._create_muted_image()
        
        # Configure right-click menu
        # Marking "Mute" / "Unmute" as default=True links it to left-click actions
        self.menu = pystray.Menu(
            pystray.MenuItem("Open HUD", self._on_open_hud),
            pystray.MenuItem(
                lambda item: "Unmute" if self.is_muted else "Mute", 
                self._handle_mute_toggle, 
                default=True
            ),
            pystray.MenuItem("Settings", self._on_settings),
            pystray.MenuItem("Quit JARVIS", self._handle_quit)
        )
        
        # Initialize the tray icon
        self.icon = pystray.Icon(
            "JARVIS", 
            self.active_image, 
            "J.A.R.V.I.S. Assistant", 
            self.menu
        )
        self.thread = None

    def start(self):
        """Launches the system tray icon loop in a background daemon thread."""
        self.thread = threading.Thread(target=self.icon.run, daemon=True)
        self.thread.start()
        logger.info("System tray icon thread started.")

    def stop(self):
        """Stops the system tray icon loop."""
        if self.icon:
            self.icon.stop()
            logger.info("System tray icon stopped.")

    def set_mute_state(self, is_muted: bool):
        """Updates the local mute state, switching the tray icon image dynamically."""
        self.is_muted = is_muted
        self.icon.icon = self.muted_image if is_muted else self.active_image
        # Redraw the menu labels
        self.icon.update_menu()
        logger.info(f"System tray icon updated: is_muted={is_muted}")

    def _create_active_image(self, width=64, height=64):
        """Draws a glowing blue circle representing active status."""
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        dc = ImageDraw.Draw(image)
        # Outer glow ring (semi-transparent blue)
        dc.ellipse([4, 4, width - 4, height - 4], fill=(0, 191, 255, 100))
        # Inner solid circle (glowing cyan)
        dc.ellipse([12, 12, width - 12, height - 12], fill=(0, 230, 255, 255))
        return image

    def _create_muted_image(self, width=64, height=64):
        """Draws a grayed circle with a red diagonal line representing muted status."""
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        dc = ImageDraw.Draw(image)
        # Outer gray ring
        dc.ellipse([4, 4, width - 4, height - 4], fill=(128, 128, 128, 100))
        # Inner gray circle
        dc.ellipse([12, 12, width - 12, height - 12], fill=(160, 160, 160, 255))
        # Red diagonal line to represent mute
        dc.line([16, 16, width - 16, height - 16], fill=(220, 20, 60, 255), width=6)
        return image

    def _handle_mute_toggle(self, icon, item):
        """Toggles local mute state and invokes the master toggle callback."""
        self.is_muted = not self.is_muted
        self.set_mute_state(self.is_muted)
        
        # Fire external toggle callback
        if self.on_toggle_mute_callback:
            self.on_toggle_mute_callback(self.is_muted)

    def _handle_quit(self, icon, item):
        """Handles the Quit command by stopping the tray loop and triggering app shutdown."""
        logger.info("Quit command selected from system tray.")
        self.stop()
        if self.on_quit_callback:
            self.on_quit_callback()

    def _on_open_hud(self, icon, item):
        """Callback for 'Open HUD' right-click menu item."""
        import webbrowser
        import os
        hud_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "hud", "index.html"))
        if os.path.exists(hud_path):
            webbrowser.open(f"file:///{hud_path}")
            logger.info("Opened HUD Display in web browser.")
        else:
            logger.error(f"HUD file not found at: {hud_path}")

    def _on_settings(self, icon, item):
        """Callback for 'Settings' right-click menu item."""
        import webbrowser
        import os
        hud_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "hud", "index.html"))
        if os.path.exists(hud_path):
            webbrowser.open(f"file:///{hud_path}#settings")
            logger.info("Opened Settings Panel in web browser.")
        else:
            logger.error(f"Settings panel file not found at: {hud_path}")
