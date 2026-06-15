import os
import json
import logging

# We define the default logger for JARVIS
logger = logging.getLogger("jarvis")

# Locate the user's home directory dynamically on Windows
USER_HOME = os.path.expanduser("~")
JARVIS_DIR = os.path.join(USER_HOME, ".jarvis")
CONFIG_PATH = os.path.join(JARVIS_DIR, "config.json")
LOG_PATH = os.path.join(JARVIS_DIR, "jarvis.log")
HISTORY_PATH = os.path.join(JARVIS_DIR, "last_session.json")
MODEL_DIR = os.path.join(JARVIS_DIR, "piper_models")

# Default configuration parameters for JARVIS
# Updated default model to llama3.2:3b as requested
DEFAULT_CONFIG = {
    "ollama_model": "llama3.2:3b",
    "whisper_model_size": "base",
    "tts_voice": "en_US-lessac-medium",
    "websocket_port": 8765,
    "conversation_history_limit": 20
}

def init_jarvis_directory():
    """
    Initializes the C:/Users/{username}/.jarvis directory structure.
    Creates subdirectories for voice models and configuration if they do not exist.
    """
    if not os.path.exists(JARVIS_DIR):
        os.makedirs(JARVIS_DIR, exist_ok=True)
    if not os.path.exists(MODEL_DIR):
        os.makedirs(MODEL_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        print(f"Created default config file at: {CONFIG_PATH}")

def load_config():
    """
    Loads configuration from C:/Users/{username}/.jarvis/config.json.
    Merges with default settings to ensure all required fields are present.
    """
    init_jarvis_directory()
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # Ensure all default keys are present in loaded config
            updated = False
            for k, v in DEFAULT_CONFIG.items():
                if k not in config:
                    config[k] = v
                    updated = True
            
            # Automatically migrate old mistral model name to llama3.2:3b
            if config.get("ollama_model") == "mistral":
                config["ollama_model"] = "llama3.2:3b"
                updated = True

            if updated:
                with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=4)
            return config
        else:
            return DEFAULT_CONFIG.copy()
    except Exception as e:
        print(f"Error loading config, falling back to defaults: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(config):
    """
    Saves the configuration dictionary to C:/Users/{username}/.jarvis/config.json.
    """
    init_jarvis_directory()
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        logger.info(f"Configuration saved to: {CONFIG_PATH}")
        return True
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return False

def setup_logging():
    """
    Sets up dual logging: console (INFO level) and log file (DEBUG level)
    at C:/Users/{username}/.jarvis/jarvis.log.
    """
    init_jarvis_directory()
    
    # Configure the logger
    logger.setLevel(logging.DEBUG)
    
    # Prevent duplicate handlers if setup is called multiple times
    if logger.handlers:
        return logger
        
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    # File handler
    try:
        fh = logging.FileHandler(LOG_PATH, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.info(f"Logging file initialized at: {LOG_PATH}")
    except Exception as e:
        print(f"Failed to set up file logger: {e}")
        
    return logger
