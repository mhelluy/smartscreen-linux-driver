# SmartScreen Monitor

A **Linux driver** for 3.5" USB LCD system stats monitors (VID `0483` / PID `0065`).

These are generic Chinese OEM monitors (sold as "3.5 Inch Sub Display", "SmartMonitor", etc.)
built around an **STM32 MCU** with a 480×320 pixel LCD. The original software is Windows-only
(Qt5 + HIDAPI). This driver replaces it entirely on Linux.

## Features

- **CPU** — temperature, frequency, usage, fan speed
- **GPU** — temperature, usage, memory clock, memory usage (AMD ROCm or NVIDIA)
- **RAM** — used, available, usage percentage
- **Disk** — total, free, usage percentage
- **Network** — upload/download throughput (KB/s)
- **Volume** — placeholder field (customizable)
- **Auto-start** — systemd service installs in one command

## Requirements

| Component | Required | Notes |
|-----------|----------|-------|
| Python 3.10+ | ✓ | |
| `hidapi` | ✓ | `pip install hidapi` |
| `psutil` | ✓ | `pip install psutil` |
| AMD GPU | optional | `rocm-smi` (comes with ROCm) |
| NVIDIA GPU | optional | `nvidia-smi` or `nvidia-ml-py3` |

## Quick start

```bash
# 1. Install dependencies
pip install hidapi psutil

# 2. Run manually (needs root for USB HID access)
sudo python3 smartscreen_driver.py

# 3. Or install as a system service for auto-start
sudo ./install.sh
```

The `install.sh` script will:
- Detect Python and dependencies
- Generate a systemd service with correct paths
- Install, enable, and optionally start the service
- Uninstall cleanly with `--uninstall`

## USB permissions

To run **without sudo**, create a udev rule:

```bash
echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="0065", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-smartscreen.rules
sudo udevadm control --reload-rules
```

## Device compatibility

The driver was tested with a **3.5" SmartMonitor** (480×320, STM32-based HID device).
Other monitors sharing the same VID/PID or protocol should work — open an issue if not.

## Firmware / themes

The monitor stores a firmware/theme bundle in flash (uploaded via YMODEM over HID from
the original Windows app). The **theme persists across power cycles**.

If the screen stays blank or shows garbage:
1. Run the original Windows app once to re-upload the theme
2. The driver only sends live sensor data, not the theme itself

## Files

| File | Purpose |
|------|---------|
| `smartscreen_driver.py` | Main driver — collects stats, builds HID packets |
| `install.sh` | Interactive systemd service installer |
| `smartscreen-monitor.service` | systemd unit template |
