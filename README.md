# Helm

A vitals monitoring application combining a Python GUI frontend with a C++ backend that interfaces with the [SmartSpectra SDK](https://docs.physiology.presagetech.com/cpp/annotated.html) for real-time physiological measurements (pulse, breathing rate) via camera input.

> **Hackathon project** - GUI development is happening on feature branches.

## Requirements

- **Windows** with WSL2 (Ubuntu 22.04)
- SmartSpectra API key from [physiology.presagetech.com](https://physiology.presagetech.com)
- USB webcam

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
./hello_vitals YOUR_API_KEY
# Or use environment variable:
export SMARTSPECTRA_API_KEY=YOUR_API_KEY
./hello_vitals
```

**Controls:**
- `s` - Start/stop recording
- `q` or `ESC` - Quit

## Architecture

```
helm/
├── main.py              # Python entry point
├── gui/app.py           # PySide6 GUI (in development)
└── src/
    ├── hello_vitals.cpp # C++ vitals processing
    └── CMakeLists.txt   # Build configuration
```

## License

See [LICENSE](LICENSE) for details.
