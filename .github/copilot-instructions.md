# Copilot Instructions for Helm

## Project Overview

Helm is a **security-focused vitals monitoring application** with a cross-platform architecture:
- **Python frontend** (Windows) - GUI and orchestration via PySide6
- **C++ backend** (WSL/Linux) - Real-time processing using SmartSpectra SDK
- **FFmpeg streaming** bridges Windows camera → WSL via TCP

## Architecture & Data Flow

```
Windows                          WSL (Ubuntu 22.04)
┌─────────────┐    TCP:5000     ┌─────────────────┐
│ FFmpeg      │ ───MJPEG────→   │ helm_vitals     │
│ (DirectShow)│                 │ (SmartSpectra)  │
└─────────────┘                 └────────┬────────┘
                                         │ JSON stdout
┌─────────────┐                          │
│ main.py     │ ←────────────────────────┘
│ (Python)    │ subprocess + line parsing
└─────────────┘
```

### Key Components
- [main.py](../main.py) - Entry point, loads API key from `gui/settings.json`, starts `HelmBackend`
- [lib/startup.py](../lib/startup.py) - Orchestrates `FFmpegStream` (Windows) + `HelmVitalsBackend` (WSL)
- [src/main.cpp](../src/main.cpp) - Headless C++ processor, outputs JSON to stdout for Python consumption

## Build & Run Commands

```bash
# C++ backend (run in WSL)
cd src/build && cmake .. && make

# Python app (run in Windows)
uv run main.py
```

## Critical Conventions

### JSON IPC Protocol
The C++ backend communicates via structured JSON lines to stdout:
```json
{"type": "status|core_metrics|edge_metrics|error", "timestamp_ms": ..., "data": {...}}
```
- Handle message types: `status`, `core_metrics`, `edge_metrics`, `error`, `system`
- See `handle_message()` in [main.py](../main.py#L42-L57) for parsing pattern

### Resolution Constraints
- WSL USB passthrough limits to **1080p max** (DirectShow limitation)
- 4K requires FFmpeg streaming from Windows (current architecture)
- Use `Resolution` enum in [lib/startup.py](../lib/startup.py#L33-L41)

### Configuration
- API key stored in `gui/settings.json` (gitignored) - copy from `gui/example-settings.json`
- Hardcoded settings in `main.py` (camera name, resolution, port)
- C++ flags defined via `ABSL_FLAG` macros in [src/main.cpp](../src/main.cpp#L42-L66)

### Cross-Platform Paths
- C++ binary path in WSL: `/mnt/c/Users/mhabe/Documents/VSCode/helm/src/build/helm_vitals`
- Windows host IP detection: `get_windows_host_ip()` in [lib/startup.py](../lib/startup.py#L68-L81)

## Dependencies

**Python (Windows):** `uv` for package management, PySide6, loguru, opencv-python
**C++ (WSL):** SmartSpectra SDK 2.0.4, OpenCV, abseil-cpp, glog, protobuf

## Development Notes

- GUI in [gui/app.py](../gui/app.py) is empty/in development - PySide6 planned
- `FFmpegStream` uses relay architecture to prevent buffer overflow (see class docstring)
- Thread-safe JSON output via `JsonOutputter` class with mutex in C++
- Graceful shutdown: handle SIGINT, call `backend.stop()` to clean up subprocesses
