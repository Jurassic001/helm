"""
Helm Startup Module

Orchestrates the startup sequence:
1. Launch FFmpeg camera stream (Windows -> TCP)
2. Start helm_vitals C++ backend in WSL
3. Provide JSON output stream to the GUI

"""

import json
import os
import queue
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator

from loguru import logger


class Resolution(Enum):
    """Supported camera resolutions."""

    RES_4K = ("4k", 3840, 2160, 30)
    RES_1080P = ("1080p", 1920, 1080, 30)
    RES_720P = ("720p", 1280, 720, 60)

    def __init__(self, name: str, width: int, height: int, fps: int):
        self._name = name
        self.width = width
        self.height = height
        self.fps = fps


@dataclass
class StreamConfig:
    """Configuration for the FFmpeg camera stream."""

    camera_name: str = "Logitech BRIO"
    resolution: Resolution = Resolution.RES_4K
    host: str = "0.0.0.0"
    port: int = 5000
    quality: int = 3  # MJPEG quality (1-31, lower is better)


@dataclass
class BackendConfig:
    """Configuration for the helm_vitals C++ backend."""

    api_key: str = ""
    wsl_distro: str = "Ubuntu-22.04"
    binary_path: str = "/mnt/c/Users/mhabe/Documents/VSCode/helm/src/build/helm_vitals"
    video_url: str = "localhost:5000"  # Will be set dynamically with Windows host IP
    verbosity: int = 1
    enable_edge_metrics: bool = True
    show_gui: bool = False
    extra_args: list[str] = field(default_factory=list)


def wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    """Wait for a TCP port to be listening."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                result = sock.connect_ex((host, port))
                if result == 0:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def verify_wslconfig() -> bool:
    """
    Verify that .wslconfig in the user's home directory contains
    [wsl2] section with networkingMode=mirrored.

    Returns True if valid, False otherwise.
    """
    wslconfig_path = Path.home() / ".wslconfig"

    if not wslconfig_path.exists():
        logger.error(
            f".wslconfig not found at {wslconfig_path}\n"
            "Required for WSL2 mirrored networking mode.\n"
            "Please create the file with:\n"
            "[wsl2]\n"
            "networkingMode=mirrored"
        )
        return False

    try:
        content = wslconfig_path.read_text()

        # Simple check for [wsl2] section and networkingMode=mirrored
        has_wsl2_section = "[wsl2]" in content
        has_mirrored_mode = "networkingMode=mirrored" in content or "networkingMode = mirrored" in content

        if not has_wsl2_section:
            logger.error(
                f".wslconfig at {wslconfig_path} missing [wsl2] section.\nPlease add:\n[wsl2]\nnetworkingMode=mirrored"
            )
            return False

        if not has_mirrored_mode:
            logger.error(
                f".wslconfig at {wslconfig_path} missing networkingMode=mirrored.\n"
                "Please add to [wsl2] section:\n"
                "networkingMode=mirrored"
            )
            return False

        logger.info("✓ WSL config verified: mirrored networking enabled")
        return True

    except Exception as e:
        logger.error(f"Failed to read .wslconfig: {e}")
        return False


class FFmpegStream:
    """
    Manages the FFmpeg camera streaming process on Windows.

    Uses a relay architecture to prevent buffer overflow:
    - FFmpeg outputs MJPEG to stdout (pipe)
    - Python TCP server accepts client connections
    - Data flows from FFmpeg -> Python -> TCP client

    This ensures frames are consumed immediately and only forwarded
    when a client is connected.
    """

    def __init__(self, config: StreamConfig):
        self.config = config
        self._ffmpeg_process: subprocess.Popen | None = None
        self._server_socket: socket.socket | None = None
        self._client_socket: socket.socket | None = None
        self._relay_thread: threading.Thread | None = None
        self._running = False
        self._client_connected = threading.Event()

    @property
    def stream_url(self) -> str:
        """Get the TCP stream URL for consumers."""
        return f"tcp://localhost:{self.config.port}"

    def _relay_data(self):
        """
        Relay data from FFmpeg stdout to the connected TCP client.

        Uses JPEG frame boundary detection (SOI/EOI markers) and pacing
        to ensure frames arrive at consistent intervals, preventing the
        SmartSpectra SDK's one_euro_filter from receiving duplicate timestamps.
        """
        if not self._ffmpeg_process or not self._ffmpeg_process.stdout:
            return

        # JPEG markers for frame boundary detection
        JPEG_SOI = b"\xff\xd8"  # Start of Image
        JPEG_EOI = b"\xff\xd9"  # End of Image

        # Target frame interval based on camera FPS
        target_interval = 1.0 / self.config.resolution.fps
        buffer = b""
        last_frame_time = time.monotonic()

        try:
            while self._running:
                # Read a chunk from FFmpeg
                data = self._ffmpeg_process.stdout.read(65536)  # 64KB chunks
                if not data:
                    break

                buffer += data

                # Extract and send complete JPEG frames with pacing
                while True:
                    # Find start of JPEG frame
                    soi_pos = buffer.find(JPEG_SOI)
                    if soi_pos == -1:
                        # No frame start found, keep minimal buffer
                        buffer = b""
                        break

                    # Discard any data before the SOI marker
                    if soi_pos > 0:
                        buffer = buffer[soi_pos:]

                    # Find end of JPEG frame
                    eoi_pos = buffer.find(JPEG_EOI, 2)  # Start search after SOI
                    if eoi_pos == -1:
                        # Incomplete frame, wait for more data
                        break

                    # Extract complete frame (including EOI marker)
                    frame = buffer[: eoi_pos + 2]
                    buffer = buffer[eoi_pos + 2 :]

                    # If client is connected, send with pacing
                    if self._client_socket:
                        # Pace frame delivery to prevent timestamp collisions
                        now = time.monotonic()
                        elapsed = now - last_frame_time
                        if elapsed < target_interval:
                            time.sleep(target_interval - elapsed)

                        try:
                            self._client_socket.sendall(frame)
                            last_frame_time = time.monotonic()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            logger.warning("Client disconnected")
                            self._client_socket = None
                    # If no client, frame is discarded (prevents buffer buildup)

        except Exception as e:
            if self._running:
                logger.error(f"Relay error: {e}")
        finally:
            logger.debug("Relay thread ending")

    def _accept_client(self):
        """Accept a single client connection."""
        if not self._server_socket:
            return

        try:
            self._server_socket.settimeout(1.0)
            while self._running and not self._client_socket:
                try:
                    client, addr = self._server_socket.accept()
                    logger.info(f"Client connected from {addr}")
                    self._client_socket = client
                    self._client_connected.set()
                except socket.timeout:
                    continue
        except Exception as e:
            if self._running:
                logger.error(f"Accept error: {e}")

    def start(self) -> bool:
        """Start the FFmpeg streaming process with TCP relay."""
        if self._running:
            logger.warning("FFmpeg stream already running")
            return True

        res = self.config.resolution

        # Step 1: Create TCP server socket
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind((self.config.host, self.config.port))
            self._server_socket.listen(1)
            logger.info(f"TCP server listening on port {self.config.port}")
        except Exception as e:
            logger.error(f"Failed to create TCP server: {e}")
            return False

        # Step 2: Start FFmpeg outputting to stdout (pipe)
        # Note: -use_wallclock_as_timestamps ensures monotonic timestamps for SDK
        cmd = [
            "ffmpeg",
            "-use_wallclock_as_timestamps",
            "1",  # Use real-time clock for timestamps
            "-f",
            "dshow",
            "-video_size",
            f"{res.width}x{res.height}",
            "-framerate",
            str(res.fps),
            "-i",
            f"video={self.config.camera_name}",
            "-c:v",
            "mjpeg",
            "-q:v",
            str(self.config.quality),
            "-f",
            "mjpeg",
            "pipe:1",  # Output to stdout
        ]

        logger.info(f"Starting FFmpeg stream: {res._name} @ {res.fps}fps")
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")

        try:
            self._ffmpeg_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # Suppress FFmpeg's verbose output
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            self._running = True

            # Give FFmpeg time to initialize
            time.sleep(0.5)

            if self._ffmpeg_process.poll() is not None:
                logger.error("FFmpeg failed to start")
                self._cleanup()
                return False

            # Step 3: Start relay thread (reads FFmpeg, writes to client)
            self._relay_thread = threading.Thread(target=self._relay_data, daemon=True)
            self._relay_thread.start()

            # Step 4: Start client accept thread
            self._accept_thread = threading.Thread(target=self._accept_client, daemon=True)
            self._accept_thread.start()

            logger.info(f"FFmpeg stream ready on {self.stream_url}")
            return True

        except FileNotFoundError:
            logger.error("FFmpeg not found. Please install FFmpeg and add it to PATH.")
            self._cleanup()
            return False
        except Exception as e:
            logger.error(f"Failed to start FFmpeg: {e}")
            self._cleanup()
            return False

    def wait_for_client(self, timeout: float = 30.0) -> bool:
        """Wait for a client to connect."""
        return self._client_connected.wait(timeout=timeout)

    def _cleanup(self):
        """Clean up all resources."""
        self._running = False
        if self._client_socket:
            try:
                self._client_socket.close()
            except Exception:
                pass
            self._client_socket = None
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

    def stop(self):
        """Stop the FFmpeg streaming process."""
        if self._running:
            logger.info("Stopping FFmpeg stream...")
            self._running = False

            # Stop FFmpeg
            if self._ffmpeg_process:
                try:
                    if os.name == "nt":
                        self._ffmpeg_process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        self._ffmpeg_process.terminate()
                    self._ffmpeg_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning("FFmpeg didn't stop gracefully, killing...")
                    self._ffmpeg_process.kill()
                except Exception as e:
                    logger.error(f"Error stopping FFmpeg: {e}")
                finally:
                    self._ffmpeg_process = None

            self._cleanup()

    @property
    def is_running(self) -> bool:
        """Check if FFmpeg is still running."""
        if self._ffmpeg_process is None:
            return False
        return self._ffmpeg_process.poll() is None


class HelmVitalsBackend:
    """
    Manages the helm_vitals C++ backend running in WSL.
    Parses JSON output and provides it to consumers.
    """

    def __init__(self, config: BackendConfig):
        self.config = config
        self._process: subprocess.Popen | None = None
        self._running = False
        self._message_queue: queue.Queue[dict] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._callbacks: list[Callable[[dict], None]] = []

    def start(self) -> bool:
        """Start the helm_vitals backend in WSL."""
        if self._running:
            logger.warning("Helm backend already running")
            return True

        # Verify WSL config before starting
        if not verify_wslconfig():
            logger.error("WSL configuration check failed. Cannot proceed.")
            return False

        if not self.config.api_key:
            # Try environment variable
            self.config.api_key = os.environ.get("SMARTSPECTRA_API_KEY", "")
            if not self.config.api_key:
                logger.error("API key required. Set api_key or SMARTSPECTRA_API_KEY environment variable.")
                return False

        # Build the WSL command - quote the binary path for paths with spaces
        backend_cmd_parts = [
            f"'{self.config.binary_path}'",  # Quote the path
            "--api_key",
            self.config.api_key,
            "--video_url",
            self.config.video_url,
            "--verbosity",
            str(self.config.verbosity),
            "--enable_micromotion",
        ]

        if self.config.enable_edge_metrics:
            backend_cmd_parts.append("--enable_edge_metrics")

        if self.config.show_gui:
            backend_cmd_parts.append("--show_gui")

        backend_cmd_parts.extend(self.config.extra_args)

        # Join into a bash command string
        # Prepend GLOG_minloglevel=2 to suppress SDK internal warnings (one_euro_filter timestamp warnings)
        # glog levels: 0=INFO, 1=WARNING, 2=ERROR, 3=FATAL
        bash_cmd = "GLOG_minloglevel=2 " + " ".join(backend_cmd_parts)

        # Wrap in WSL
        cmd = ["wsl", "-d", self.config.wsl_distro, "-e", "bash", "-c", bash_cmd]

        logger.info(f"Starting helm_vitals backend in WSL ({self.config.wsl_distro})")
        logger.debug(f"Backend command: {bash_cmd}")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )
            self._running = True

            # Start reader thread
            self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
            self._reader_thread.start()

            # Wait briefly and check if process started successfully
            time.sleep(0.5)
            if self._process.poll() is not None:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                logger.error(f"helm_vitals failed to start: {stderr}")
                self._running = False
                return False

            logger.success("helm_vitals backend started successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to start helm_vitals: {e}")
            return False

    def _read_output(self):
        """Background thread to read JSON output from helm_vitals."""
        if not self._process or not self._process.stdout:
            return

        # Also start reading stderr in a separate thread
        def read_stderr():
            if self._process and self._process.stderr:
                for line in self._process.stderr:
                    line = line.strip()
                    if line:
                        # Filter out one_euro_filter timestamp warnings from MediaPipe
                        # These are triggered ~468 times per frame (once per facial landmark)
                        # and cannot be suppressed at the SDK level
                        if "one_euro_filter.cc" in line and "timestamp is equal or less" in line:
                            continue
                        logger.warning(f"helm_vitals stderr: {line}")

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
                self._message_queue.put(message)

                # Call registered callbacks
                for callback in self._callbacks:
                    try:
                        callback(message)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")

            except json.JSONDecodeError:
                logger.warning(f"Non-JSON output from backend: {line}")

        self._running = False
        logger.info("helm_vitals output stream ended")

    def register_callback(self, callback: Callable[[dict], None]):
        """Register a callback to be called for each message."""
        self._callbacks.append(callback)

    def read_messages(self, timeout: float = 0.1) -> Iterator[dict]:
        """
        Generator that yields messages from the backend.
        Non-blocking with optional timeout.
        """
        while self._running or not self._message_queue.empty():
            try:
                message = self._message_queue.get(timeout=timeout)
                yield message
            except queue.Empty:
                continue

    def get_message(self, timeout: float = 1.0) -> dict | None:
        """Get a single message, or None if timeout."""
        try:
            return self._message_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        """Stop the helm_vitals backend."""
        if self._process and self._running:
            logger.info("Stopping helm_vitals backend...")
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("helm_vitals didn't stop gracefully, killing...")
                self._process.kill()
            except Exception as e:
                logger.error(f"Error stopping helm_vitals: {e}")
            finally:
                self._running = False
                self._process = None

    @property
    def is_running(self) -> bool:
        """Check if the backend is still running."""
        if self._process is None:
            return False
        return self._process.poll() is None


# Hardcoded WSL distribution - cannot be changed
WSL_DISTRO = "Ubuntu-22.04"


class HelmBackend:
    """
    High-level orchestrator for the Helm backend system.
    Manages both FFmpeg streaming and helm_vitals processing.
    """

    def __init__(
        self,
        api_key: str = "",
        resolution: Resolution = Resolution.RES_4K,
        camera_name: str = "Logitech BRIO",
        stream_port: int = 5000,
        show_gui: bool = False,
        verbosity: int = 1,
    ):
        self.stream_config = StreamConfig(
            camera_name=camera_name,
            resolution=resolution,
            port=stream_port,
        )

        self.backend_config = BackendConfig(
            api_key=api_key,
            wsl_distro=WSL_DISTRO,
            video_url=f"tcp://localhost:{stream_port}",
            show_gui=show_gui,
            verbosity=verbosity,
        )

        self._ffmpeg = FFmpegStream(self.stream_config)
        self._backend = HelmVitalsBackend(self.backend_config)

    def start(self) -> bool:
        """
        Start the complete Helm backend system.

        1. Starts FFmpeg camera stream (with TCP relay server)
        2. Starts helm_vitals in WSL (connects to the TCP server)
        3. Waits for client connection to be established

        Returns True if both started successfully.
        """
        logger.info("=" * 50)
        logger.info("Starting Helm Backend System")
        logger.info("=" * 50)

        # Step 1: Start FFmpeg stream (creates TCP server and starts capturing)
        logger.info("Step 1/2: Starting camera stream...")
        if not self._ffmpeg.start():
            logger.error("Failed to start camera stream")
            return False

        # Step 2: Start helm_vitals backend (will connect to TCP server)
        logger.info("Step 2/2: Starting vitals processing backend...")
        if not self._backend.start():
            logger.error("Failed to start vitals backend")
            self._ffmpeg.stop()  # Clean up
            return False

        # Step 3: Wait for the backend to connect to the stream
        logger.info("Waiting for backend to connect to stream...")
        if not self._ffmpeg.wait_for_client(timeout=30.0):
            logger.error("Backend did not connect to stream within 30 seconds")
            self._backend.stop()
            self._ffmpeg.stop()
            return False

        logger.info("=" * 50)
        logger.info("Helm Backend System started successfully!")
        logger.info(f"  Camera: {self.stream_config.camera_name}")
        logger.info(f"  Resolution: {self.stream_config.resolution._name}")
        logger.info(f"  Stream: {self._ffmpeg.stream_url}")
        logger.info("=" * 50)

        return True

    def stop(self):
        """Stop the complete Helm backend system."""
        logger.info("Shutting down Helm Backend System...")
        self._backend.stop()
        self._ffmpeg.stop()
        logger.info("Helm Backend System stopped")

    def register_callback(self, callback: Callable[[dict], None]):
        """Register a callback for backend messages."""
        self._backend.register_callback(callback)

    def read_messages(self, timeout: float = 0.1) -> Iterator[dict]:
        """Generator that yields messages from the backend."""
        return self._backend.read_messages(timeout)

    def get_message(self, timeout: float = 1.0) -> dict | None:
        """Get a single message from the backend."""
        return self._backend.get_message(timeout)

    @property
    def is_running(self) -> bool:
        """Check if both FFmpeg and backend are running."""
        return self._ffmpeg.is_running and self._backend.is_running

    def __enter__(self):
        """Context manager support."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup."""
        self.stop()
        logger.warning("HelmBackend exited from context manager. Press Ctrl+C again to exit everything.")
        return False
