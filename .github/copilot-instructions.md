# Helm - AI Coding Instructions

## Project Overview

Helm is a security-focused vitals monitoring application that assesses physiological threat indicators via camera input. Combines a Python GUI frontend with a C++ backend interfacing with the [SmartSpectra SDK](https://docs.physiology.presagetech.com/cpp/annotated.html) for real-time measurements.

**Use cases:** Smart doorbells, security cameras, access control systems.

> **Hackathon project** - GUI development is happening on feature branches.

## Architecture

```
helm/
├── main.py          # Python entry point - spawns C++ backend subprocess
├── gui/app.py       # PySide6 GUI (in development on feature branches)
└── src/             # C++ backend using SmartSpectra SDK
    ├── main.cpp           # Headless vitals processor (JSON output to stdout)
    └── CMakeLists.txt     # CMake build configuration
```

### Component Responsibilities
- **Python layer**: GUI built with PySide6, spawns `helm_vitals` subprocess, parses JSON output
- **C++ layer**: Real-time vitals extraction using SmartSpectra's `CpuContinuousRestForegroundContainer`
- **Python-C++ bridge**: Subprocess with JSON over stdout (line-delimited)

## Environment Setup

### Requirements
- **Ubuntu 22.04** (via WSL on Windows)
- SmartSpectra SDK v2.0.4

### SmartSpectra SDK Installation
```bash
# Add Presage PPA and install SDK (run in WSL/Ubuntu 22.04)
curl -s "https://presage-security.github.io/PPA/KEY.gpg" | gpg --dearmor | sudo tee /etc/apt/trusted.gpg.d/presage-technologies.gpg >/dev/null
sudo curl -s --compressed -o /etc/apt/sources.list.d/presage-technologies.list "https://presage-security.github.io/PPA/presage-technologies.list"
sudo apt update
sudo apt install libphysiologyedge-dev=2.0.4 libsmartspectra-dev=2.0.4
```

### WSL Camera Setup (Windows)
USB cameras require passthrough from Windows to WSL2 using `usbipd-win`.

#### One-time setup (Windows PowerShell as Admin)
```powershell
# Install usbipd-win
winget install usbipd
```

#### One-time setup (WSL)
```bash
sudo apt install -y v4l-utils linux-tools-generic hwdata usbutils
```

#### Each session (before running helm_vitals)
1. **Windows**: Attach camera to WSL
   ```powershell
   usbipd list                        # Find your camera's BUSID
   usbipd bind --busid <BUSID>        # First time only
   usbipd attach --wsl --busid <BUSID>
   ```

2. **WSL**: Load the camera driver
   ```bash
   sudo modprobe uvcvideo
   ls /dev/video*                     # Verify camera is available
   ```

## Key Conventions

### C++ Backend Patterns
- Uses SmartSpectra's callback-based async model for metrics/video/status updates
- All callbacks must complete within **75ms** to avoid blocking incoming data
- Error handling uses `absl::Status` - always check `.ok()` before proceeding
- API key passed via CLI argument or `SMARTSPECTRA_API_KEY` environment variable

### SmartSpectra SDK Usage

See [main.cpp](../src/main.cpp):
```cpp
// Settings template: OperationMode::Continuous + IntegrationMode::Rest
settings::Settings<settings::OperationMode::Continuous, settings::IntegrationMode::Rest> settings{
    // headless=true for JSON output
};

// Critical callbacks:
container.SetOnStatusChange(...)       // Face positioning, lighting feedback
container.SetOnCoreMetricsOutput(...)  // Cloud-processed metrics (pulse, breathing, BP)
container.SetOnEdgeMetricsOutput(...)  // Real-time local metrics (traces, EDA)
```

### JSON Output Schema (helm_vitals)

All output is line-delimited JSON with structure:
```json
{"type":"<type>","timestamp_ms":<ms>,"data":{...}}
```

| Type | Description | Data Fields |
|------|-------------|-------------|
| `status` | Face/lighting feedback | `code`, `description`, `frame_timestamp` |
| `core_metrics` | Cloud vitals | `pulse`, `breathing`, `blood_pressure`, `face` |
| `edge_metrics` | Real-time local | `chest_breathing`, `eda`, `micromotion_*` |
| `error` | Errors | `message` |
| `system` | Events | `event`, `message` |

### Measurement Stability

Every measurement includes a `stable` boolean:
- **`stable: true`** — Measurement is reliable
- **`stable: false`** — Measurement may be unreliable (subject moving, poor lighting, etc.)

Always check `stable` before using values in threat assessment.

### Python Conventions
- Python 3.12.12 required (pinned in pyproject.toml)
- Use `loguru` for logging, not stdlib logging
- GUI uses PySide6 (Qt6 bindings)

## Build & Run

#### Entering WSL (REQUIRED for C++ build/run)
```bash
# in project root
wsl -d Ubuntu-22.04
```

### C++ Build (in WSL)
```bash
cd src/build
cmake ..
make
```

### Running

```bash
./helm_vitals --api_key <YOUR_API_KEY>
# Output: JSON to stdout
```

### Python Environment
```bash
# Uses uv for dependency management (see pyproject.toml)
uv sync
python main.py
```

## External Dependencies

| Component | Dependency | Purpose |
|-----------|------------|---------|
| C++ | [SmartSpectra SDK](https://docs.physiology.presagetech.com/cpp/annotated.html) | Vitals extraction from camera |
| C++ | OpenCV | Video capture |
| C++ | glog | Logging infrastructure |
| Python | PySide6 | Cross-platform GUI |
| Python | opencv-python | Image processing |

## Development Notes

- **helm_vitals**: 4K default (3840x2160), headless, JSON output, auto-start recording
- Press `Ctrl+C` to quit
- C++ backend must be built/run in WSL (Ubuntu 22.04)
