"""
Helm - Security Vitals Monitoring Application

Main entry point that orchestrates:
1. FFmpeg camera streaming (Windows)
2. helm_vitals C++ backend (WSL)  
3. PySide6 GUI (future)
"""

import json
import signal
import sys
from pathlib import Path

from loguru import logger

from lib.startup import HelmBackend, Resolution

# Hardcoded settings
CAMERA_NAME = "Logitech BRIO"
RESOLUTION = Resolution.RES_1080P  # 4K not available via DirectShow on Windows
STREAM_PORT = 5000
VERBOSITY = 1
SHOW_GUI = False


def load_api_key() -> str:
    """Load API key from gui/settings.json."""
    settings_path = Path(__file__).parent / "gui" / "settings.json"
    
    if not settings_path.exists():
        logger.warning(f"Settings file not found: {settings_path}")
        return ""
    
    try:
        with open(settings_path) as f:
            settings = json.load(f)
            return settings.get("api_key", "")
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to load settings: {e}")
        return ""


def handle_message(message: dict):
    """Process incoming messages from helm_vitals backend."""
    msg_type = message.get("type", "unknown")
    
    if msg_type == "status":
        data = message.get("data", {})
        logger.info(f"Status: {data.get('description', 'Unknown')}")
    
    elif msg_type == "core_metrics" or msg_type == "edge_metrics":
        data = message.get("data", {})
        logger.debug(f"Physiology data: {data}")
        # TODO: React to data
    
    elif msg_type == "error":
        logger.error(f"Backend error: {message.get('message', 'Unknown error')}")
    
    elif msg_type == "system":
        data = message.get("data", {})
        logger.info(f"System: {data.get('event', '')} - {data.get('message', '')}")
    
    else:
        logger.warning(f"Unknown message type: {msg_type}")


def main():
    """Main entry point for Helm application."""
    logger.info("Helm - Security Vitals Monitor")
    logger.info("-" * 40)
    
    # Load API key from gui/settings.json
    api_key = load_api_key()
    
    # Create backend with hardcoded settings
    backend = HelmBackend(
        api_key=api_key,
        resolution=RESOLUTION,
        camera_name=CAMERA_NAME,
        stream_port=STREAM_PORT,
        verbosity=VERBOSITY,
        show_gui=SHOW_GUI,
    )
    
    # Register message handler
    backend.register_callback(handle_message)
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        logger.info("\nShutdown requested...")
        backend.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start the backend system
    if not backend.start():
        logger.error("Failed to start Helm backend")
        return 1
    
    # Main loop - process messages until stopped
    try:
        logger.info("Processing vitals... Press Ctrl+C to stop")
        while backend.is_running:
            # Messages are handled by callback, but we could also poll here
            message = backend.get_message(timeout=1.0)
            if message:
                # Additional processing if needed
                pass
    except KeyboardInterrupt:
        pass
    finally:
        backend.stop()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
