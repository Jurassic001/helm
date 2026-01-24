# Helm - AI Coding Instructions

## Project Overview

Helm is a vitals monitoring application combining a Python GUI frontend with a C++ backend that interfaces with the [SmartSpectra SDK](https://docs.physiology.presagetech.com/cpp/annotated.html) for real-time physiological measurements (pulse, breathing rate) via camera input.

> **Hackathon project** - GUI development is happening on feature branches.

## Architecture

```
helm/
├── main.py          # Python entry point - orchestrates GUI and backend
├── gui/app.py       # PySide6 GUI (in development on feature branches)
└── src/             # C++ backend using SmartSpectra SDK
    ├── hello_vitals.cpp   # Core vitals processing with OpenCV
    └── CMakeLists.txt     # CMake build configuration
```

### Component Responsibilities
- **Python layer**: GUI built with PySide6, logging via Loguru, OpenCV for image handling
- **C++ layer**: Real-time vitals extraction using SmartSpectra's `CpuContinuousRestForegroundContainer`
- **Python-C++ bridge**: TBD (integration approach not yet finalized)

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

## Key Conventions

### C++ Backend Patterns
- Uses SmartSpectra's callback-based async model for metrics/video/status updates
- All callbacks must complete within **75ms** to avoid blocking incoming data
- Error handling uses `absl::Status` - always check `.ok()` before proceeding
- API key passed via CLI argument or `SMARTSPECTRA_API_KEY` environment variable

### SmartSpectra SDK Usage (see [hello_vitals.cpp](../src/hello_vitals.cpp))
```cpp
// Settings template: OperationMode::Continuous + IntegrationMode::Rest
container::settings::Settings<
    container::settings::OperationMode::Continuous,
    container::settings::IntegrationMode::Rest
> settings;

// Critical callbacks to implement:
container->SetOnCoreMetricsOutput(...)  // Pulse/breathing data
container->SetOnVideoOutput(...)         // Frame rendering
container->SetOnStatusChange(...)        // Processing status
```

### Python Conventions
- Python 3.12.12 required (pinned in pyproject.toml)
- Use `loguru` for logging, not stdlib logging
- GUI uses PySide6 (Qt6 bindings)

## Build & Run

### C++ Build (in WSL)
```bash
cd src/build
cmake ..
make
./hello_vitals YOUR_API_KEY
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
| C++ | OpenCV | Video capture and HUD rendering |
| C++ | glog | Logging infrastructure |
| Python | PySide6 | Cross-platform GUI |
| Python | opencv-python | Image processing |

## Development Notes

- Camera defaults: 1280x720 @ MJPG codec, device index 0
- If changing resolution, the HUD positioning must also be updated
- Press 's' to start/stop recording, 'q' or ESC to quit in C++ app
- C++ backend must be built/run in WSL (Ubuntu 22.04)
