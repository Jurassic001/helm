# Helm

<!-- TODO: Overhaul project description -->

A security-focused vitals monitoring application that assesses physiological threat indicators via camera input. Combines a Python GUI frontend with a C++ backend interfacing with the [SmartSpectra SDK](https://docs.physiology.presagetech.com/cpp/annotated.html) for real-time measurements (pulse, breathing, blood pressure, stress indicators).

**Use cases:** Smart doorbells, security cameras, access control systems.

## Setup

### Requirements

* Ubuntu 22.04 on WSL2 <!-- non-negotiable, required for compatibility with SmartSpectra SDK -->
* FFmpeg on your Windows PATH
* SmartSpectra API key from [physiology.presagetech.com](https://physiology.presagetech.com)
* Logitech Brio 4k 60 FPS webcam (support for other models coming soon)
* [uv by astral-sh](https://github.com/astral-sh/uv)

### Configuring WSL

```bash
# Essential build tools
sudo apt update
sudo apt install -y build-essential git lsb-release libcurl4-openssl-dev libssl-dev pkg-config libv4l-dev libgles2-mesa-dev libunwind-dev

# Install latest cmake
sudo apt remove --purge --auto-remove cmake
sudo apt install -y software-properties-common lsb-release wget gnupg
wget -O - https://apt.kitware.com/keys/kitware-archive-latest.asc 2>/dev/null | gpg --dearmor - | sudo tee /etc/apt/trusted.gpg.d/kitware.gpg >/dev/null
echo "deb https://apt.kitware.com/ubuntu/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/kitware.list >/dev/null
sudo apt update
sudo apt install cmake

# Download the GPG key
curl -s "https://presage-security.github.io/PPA/KEY.gpg" | gpg --dearmor | sudo tee /etc/apt/trusted.gpg.d/presage-technologies.gpg >/dev/null
# Copy the PPA list
sudo curl -s --compressed -o /etc/apt/sources.list.d/presage-technologies.list "https://presage-security.github.io/PPA/presage-technologies.list"
# Install/Upgrade the SDK
sudo apt update
sudo apt install libphysiologyedge-dev=2.0.4
sudo apt install libsmartspectra-dev=2.0.4

# At this point you may need to update your drivers, depending on the state of your webcam and stuff like that
```

### Python environment in Windows

```bash
# Install deps and setup venv
uv sync

# Set up API key
cp gui/example-settings.json gui/settings.json
echo "Configure your API key in gui/settings.json!"
```

## Build & Run

### Building the detection layer in WSL

```bash
cd src/build
cmake ..
make
```

### Python runtime

```bash
uv run main.py
```

Press `Ctrl+C` to quit.

## Architecture

```
helm/
├── main.py              # Python entry point (launches C++ backend)
├── gui/app.py           # PySide6 GUI (in development)
└── src/
    ├── main.cpp         # Headless vitals processor (JSON output)
    └── CMakeLists.txt   # Build configuration
```

### JSON Output Format

<!-- TODO: This shouldn't be user-facing -->

```json
// status message structure
{
    "type": "status",
    "timestamp_ms": 1737734400000,
    "data": {
        "code": 0,
        "description": "OK",
        "frame_timestamp": 123456
    }
}

// core_mectrics message structure
{
    "type": "core_metrics",
    "timestamp_ms": 1737734400100,
    "data": {
        "pulse": {
            "heart_rate": {
                "value": 72,
                "stable": true,
                "confidence": 0.95
            }
        },
        "breathing": {
            "respiratory_rate": {
                "value": 16,
                "stable": true
            }
        },
        "blood_pressure": {
            "phasic": {
                "value": 120,
                "stable": false
            }
        },
        "face": {
            "blinking": {
                "detected": false,
                "stable": true
            },
            "talking": {
                "detected": false,
                "stable": true
            }
        }
    }
}

// edge_metrics message structure
{
    "type": "edge_metrics",
    "timestamp_ms": 1737734400050,
    "data": {
        "chest_breathing": {
            "value": 0.42,
            "stable": true
        },
        "eda": {
            "value": 0.15,
            "stable": false
        }
    }
}
```

## License

See [LICENSE](LICENSE) for details.
