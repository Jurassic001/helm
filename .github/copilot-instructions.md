# Helm - AI Coding Instructions

## Architecture Overview

Helm is a **dual-environment** security vitals monitoring system:
- **Windows**: Python orchestrator (`main.py`) + FFmpeg camera streaming + PySide6 GUI (WIP)
- **WSL (Ubuntu 22.04)**: C++ backend (`src/main.cpp`) using SmartSpectra SDK for physiological processing

**Data flow**: Camera (Windows) → FFmpeg TCP stream → WSL C++ backend → JSON stdout → Python callbacks → GUI

```
Windows Python          WSL C++
┌──────────────┐       ┌─────────────────┐
│ main.py      │       │ helm_vitals     │
│ HelmBackend  │◄─JSON─┤ (SmartSpectra)  │
│ FFmpegStream │─TCP──►│                 │
└──────────────┘       └─────────────────┘
```

## Critical Build & Run Commands

```bash
# Python (Windows) - uses uv package manager
uv sync                  # Install dependencies
uv run main.py           # Run application

# C++ backend (WSL Ubuntu 22.04 only)
cd src/build && cmake .. && make
```

The C++ binary at `src/build/helm_vitals` is invoked by Python via `wsl -d Ubuntu-22.04`.

## Key Code Patterns

### Python Layer (`lib/startup.py`)
- `HelmBackend`: High-level orchestrator combining `FFmpegStream` + `HelmVitalsBackend`
- `FFmpegStream`: TCP relay server (prevents buffer overflow) - reads FFmpeg stdout, forwards to connected clients
- `HelmVitalsBackend`: WSL process manager parsing JSON from helm_vitals stdout
- **Callbacks**: Register with `backend.register_callback(fn)` to receive parsed JSON messages

### C++ Layer (`src/main.cpp`)
- Uses `absl::GetFlag()` for command-line parsing
- `JsonOutputter`: Thread-safe JSON output class - all stdout goes through `g_outputter`
- Metric extraction functions: `ExtractPulseJson()`, `ExtractBreathingJson()`, etc.
- SmartSpectra container callbacks: `SetOnCoreMetricsOutput()`, `SetOnEdgeMetricsOutput()`, `SetOnStatusChange()`

### JSON Message Types (C++ → Python)
| Type | Description |
|------|-------------|
| `status` | Face positioning/lighting feedback |
| `core_metrics` | Cloud-processed vitals (pulse, breathing, BP) |
| `edge_metrics` | Real-time local metrics (breathing traces, EDA) |
| `system` | Lifecycle events (initialized, shutdown) |
| `error` | Error messages |

## Configuration

- **API Key**: Store in `gui/settings.json` (copy from `gui/example-settings.json`)
- **Resolution**: Hardcoded in `main.py` - 1080p default (4K unavailable via DirectShow)
- **WSL distro**: Hardcoded as `Ubuntu-22.04` in `lib/startup.py` (SDK requirement)

## Dependencies

- **SmartSpectra SDK**: `libsmartspectra-dev=2.0.4` (WSL apt package from Presage PPA)
- **Python**: Exactly 3.12.12 with loguru, opencv-python, pyside6
- **Camera**: Logitech Brio 4K (other cameras not yet supported)

## Development Notes

- GUI in `gui/app.py` is WIP - currently just a placeholder
- The TCP relay pattern in `FFmpegStream` prevents FFmpeg buffer overflow when backend processes frames slower than capture rate
- Always test C++ changes by running the full Python orchestrator, not helm_vitals directly
