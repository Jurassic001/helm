# Helm - AI Coding Instructions

## Project Overview
Helm is a security-focused vitals monitoring application combining a **Windows-side Python GUI** with a **WSL2-side C++ backend** that interfaces with the SmartSpectra SDK. The system streams camera video via FFmpeg TCP relay from Windows to WSL for physiological threat assessment.

## Architecture & Data Flow

```
Windows (Python)                    WSL2 (C++)
┌─────────────────┐                ┌─────────────────┐
│ main.py         │                │ helm_vitals     │
│   ↓             │  TCP stream    │   (main.cpp)    │
│ FFmpegStream ───┼───────────────►│   SmartSpectra  │
│   (startup.py)  │                │       ↓         │
│       ↓         │  JSON stdout   │   JSON output   │
│ HelmBackend ────┼◄───────────────┼───────────────┘
│       ↓         │
│ MainWindow      │
│   (app.py)      │
└─────────────────┘
```

- **Entry point**: [main.py](../main.py) - orchestrates backend startup and Qt event loop
- **Backend orchestration**: [lib/startup.py](../lib/startup.py) - FFmpegStream + HelmBackend classes manage Windows↔WSL communication
- **GUI**: [gui/app.py](../gui/app.py) - PySide6 MainWindow with OpenCV/MediaPipe wireframe overlay
- **Threat detection**: [lib/threat_eval.py](../lib/threat_eval.py) - normalizes vitals against population baselines
- **Threat summaries**: [lib/threat_summery.py](../lib/threat_summery.py) - Claude-powered natural language threat assessments
- **C++ backend**: [src/main.cpp](../src/main.cpp) - headless JSON output processor using SmartSpectra SDK

## Critical Setup Requirements

### WSL2 Mirrored Networking (Non-Negotiable)
The TCP streaming architecture **requires** mirrored networking. Without it, Windows cannot reach WSL and vice versa:
```
# C:\Users\<user>\.wslconfig
[wsl2]
networkingMode=mirrored
```

### API Key Configuration
Copy `gui/example-settings.json` → `gui/settings.json` and add your SmartSpectra API key.

## Build & Run Commands

```bash
# Python (Windows) - uses uv package manager
uv sync                      # Install dependencies
uv run main.py               # Run application

# C++ (WSL2)
cd src/build && cmake .. && make    # Build helm_vitals binary
```

## Code Patterns & Conventions

### Message Protocol
All backend↔frontend communication uses JSON messages with this structure:
```python
{"type": "core_metrics"|"edge_metrics"|"status"|"error", "timestamp_ms": ..., "data": {...}}
```
Handle messages in callbacks registered via `HelmBackend.register_callback()`.

### Threat Scoring System
The `ThreatDetector` in [lib/threat_eval.py](../lib/threat_eval.py) uses:
- **Z-score normalization** against population baselines (HR: 70±12 BPM, breathing: 16±4)
- **Time-windowed averaging** (default 0.5s) to smooth noisy vitals
- **Security level thresholds** defined in `MainWindow.THREAT_THRESHOLDS` dict

### AI Threat Summaries
The `ThreatSummaryGenerator` in [lib/threat_summery.py](../lib/threat_summery.py) provides Claude-powered natural language summaries:
- Receives metrics dict with `threat_score`, `heart_rate`, `breathing_rate`, `eda`, `chest_breathing`
- Compares against baselines and formats deviation percentages
- Returns 2-3 sentence professional assessment via Claude API
- Requires Anthropic API key in settings

### Qt/PySide6 Patterns
- UI defined in Qt Designer: [gui/designer2.ui](../gui/designer2.ui)
- Load UI dynamically via `QUiLoader` (not compiled `.py` files)
- Camera frames processed in `QTimer` callback at ~30 FPS
- MediaPipe Holistic used for face/hand/pose wireframe overlay

### C++ SDK Integration
- SmartSpectra SDK callbacks deliver protobuf `MetricsBuffer` objects
- Extract latest values from `RepeatedPtrField` using `*field.rbegin()`
- Thread-safe JSON output via `JsonOutputter` class with mutex

## Key Files to Understand

| File | Purpose |
|------|---------|
| [lib/startup.py](../lib/startup.py) | FFmpeg TCP relay + WSL process management |
| [lib/threat_eval.py](../lib/threat_eval.py) | Vitals normalization and threat scoring |
| [lib/threat_summery.py](../lib/threat_summery.py) | Claude AI threat summary generation |
| [gui/app.py](../gui/app.py) | Qt GUI, camera handling, MediaPipe overlay |
| [src/main.cpp](../src/main.cpp) | C++ SmartSpectra integration, JSON output |

## Testing & Debugging

- Set `VERBOSITY = 3` in [main.py](../main.py) for trace-level logging via loguru
- C++ verbosity: `--verbosity 3` flag shows detailed metrics
- C++ `--show_gui` flag enables SmartSpectra's built-in debug visualization (separate from Python GUI)
- Check `.wslconfig` if TCP streaming fails (verify `networkingMode=mirrored`)
