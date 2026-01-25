# Helm

A security-focused vitals monitoring application that assesses physiological threat indicators via camera input. Combines a Python GUI frontend with a C++ backend interfacing with the [SmartSpectra SDK](https://docs.physiology.presagetech.com/cpp/annotated.html) for real-time measurements (pulse, breathing, blood pressure, stress indicators).

**Use cases:** Smart doorbells, security cameras, access control systems.

> **Hackathon project** - GUI development is happening on feature branches.

## Requirements

- **Windows** with WSL2 (Ubuntu 22.04)
- SmartSpectra API key from [physiology.presagetech.com](https://physiology.presagetech.com)
- USB webcam (4K recommended for optimal detection)

## Setup

<!-- TODO: Add repo setup stuff as well -->

### 0. Install Ubuntu-22..04 on WSL
```bash
wsl --install Ubuntu-22.04
```

### 1. Install SmartSpectra SDK (WSL)

```bash
# Add Presage PPA
curl -s "https://presage-security.github.io/PPA/KEY.gpg" | gpg --dearmor | sudo tee /etc/apt/trusted.gpg.d/presage-technologies.gpg >/dev/null
sudo curl -s --compressed -o /etc/apt/sources.list.d/presage-technologies.list "https://presage-security.github.io/PPA/presage-technologies.list"

# Install SDK
sudo apt update
sudo apt install libphysiologyedge-dev=2.0.4 libsmartspectra-dev=2.0.4
```

### 2. Install USB Passthrough (Windows)

USB cameras need to be passed through to WSL2:

```powershell
# Run in PowerShell as Administrator
winget install usbipd
```

Restart powershell and attach your camera to WSL:
> You'll need to have WSL open in a seperate terminal before attaching it

```powershell
usbipd list
usbipd bind --busid <BUSID>
usbipd attach --wsl --busid <BUSID>
```

### 3. Install Camera Utilities (WSL)

```bash
sudo apt install -y v4l-utils linux-tools-generic hwdata usbutils
```

### 4. Build C++ Backend (WSL)

```bash
cd src/build
cmake ..
make
```

### 5. Setup Python Environment

```bash
# Uses uv for dependency management
uv sync
```

## Running

### Attach Camera (each session)

**Windows PowerShell:**
```powershell
usbipd list                          # Find your camera's BUSID (e.g., 2-6)
usbipd bind --busid <BUSID>          # First time only
usbipd attach --wsl --busid <BUSID>  # Run each session
```

**WSL:**
```bash
sudo modprobe uvcvideo               # Load camera driver
ls /dev/video*                       # Verify camera available
```

### Run Vitals Monitor

```bash
cd src/build
./helm_vitals --api_key YOUR_API_KEY
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

### Command Line Options (helm_vitals)

| Flag | Default | Description |
|------|---------|-------------|
| `--api_key` | (required) | SmartSpectra API key |
| `--camera_device_index` | 0 | Camera device index |
| `--capture_width_px` | 3840 | Capture width (4K default) |
| `--capture_height_px` | 2160 | Capture height (4K default) |
| `--buffer_duration` | 0.2 | Processing buffer (0.2-1.0s) |
| `--verbosity` | 1 | Log level (0-3) |
| `--enable_phasic_bp` | false | Enable blood pressure (requires model) |
| `--enable_eda` | false | Enable electrodermal activity (requires model) |
| `--enable_edge_metrics` | true | Enable real-time metrics |

## License

See [LICENSE](LICENSE) for details.
