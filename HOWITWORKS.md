# How it works

## Overview

The program is a **HID device driver** that collects system metrics via `psutil` and
sends them to a USB LCD monitor as structured 65-byte reports.

```
┌────────────┐     psutil / rocm-smi     ┌──────────────────┐
│  psutil    │ ────────────────────────→  │                  │
│  sensors   │                            │  smartscreen_    │
│  disk/io   │                            │  driver.py       │
│  network   │                            │                  │
│  rocm-smi  │ ────────────────────────→  │  (HID device)    │
└────────────┘                            └──────────────────┘
                                                  │
                                          65-byte HID reports
                                                  │
                                                  ▼
                                         ┌──────────────────┐
                                         │  3.5" USB LCD    │
                                         │  STM32 + 480×320 │
                                         └──────────────────┘
```

## Protocol

The protocol was discovered through **Frida hooking** of the original Windows application.
The function `hid_write` was instrumented to capture every HID report sent to the device
in real time. The raw byte sequences were then decoded by correlating changing byte values
with the live system metrics displayed on the screen.

### HID report format

Every report is **65 bytes**:

```
Byte  0: 0x00        (HID Report ID — always 0)
Byte  1: type        (0x02 = sensor data, 0x03 = heartbeat)
Byte  2: field_count (0x14 = 20 fields for type 0x02)
Bytes 3–64: payload  (triplets: [id, high_byte, low_byte])
```

### Packet type 0x02 — Sensor data

Sent every second. Contains 20 field triplets starting at offset 3.

Each triplet:
```
[field_id: 1 byte] [value_high: 1 byte] [value_low: 1 byte]
```

Values are **16-bit big-endian**: `(high_byte << 8) | low_byte`.

#### Field map

| ID | Widget | Unit | Source |
|----|--------|------|--------|
| `0x01` | CPU Temperature | °C | `psutil.sensors_temperatures()` |
| `0x02` | CPU Frequency | MHz | `psutil.cpu_freq()` |
| `0x03` | CPU Usage | % | `psutil.cpu_percent()` |
| `0x04` | CPU Fan | RPM | `psutil.sensors_fans()` |
| `0x05` | GPU Temperature | °C | `rocm-smi` / `nvidia-smi` / `pynvml` |
| `0x06` | *(unused)* | | |
| `0x07` | GPU Usage | % | GPU backend |
| `0x08` | GPU MemClock | MHz | GPU backend |
| `0x09` | GPU MemUsage | % | GPU backend |
| `0x0A` | RAM Used | MB | `psutil.virtual_memory()` |
| `0x0B` | RAM Available | MB | `psutil.virtual_memory()` |
| `0x0C` | RAM Usage | % | `psutil.virtual_memory()` |
| `0x0D` | *(unused)* | | |
| `0x0E` | Disk Total | GB | `psutil.disk_usage('/')` |
| `0x0F` | *(unused)* | | |
| `0x10` | Disk Free | GB | `psutil.disk_usage('/')` |
| `0x11` | Disk Usage | % | `psutil.disk_usage('/')` |
| `0x12` | Net Upload | KB/s | `psutil.net_io_counters()` (delta) |
| `0x13` | Net Download | KB/s | `psutil.net_io_counters()` (delta) |
| `0x14` | Volume | % | Hardcoded |

The field map was verified iteratively: each field ID was set to a unique known value,
and the display was inspected to see which widget changed. The process was repeated
until every visible widget on every theme was accounted for.

### Packet type 0x03 — Heartbeat

Sent after every type 0x02 packet. Keeps the display alive and tracks update count.

```
00 03 01 15 1a 06 15 0d 00 <counter> 07 64 ...
```

The counter increments from 0 to 255 and wraps around. The display uses it to detect
stale data — if the heartbeat stops, the screen freezes on the last frame.

## GPU backends

The driver probes GPU sources in order:

1. **AMD** — `rocm-smi --csv` parses CSV output for temperature, usage, memory clock, VRAM%
2. **NVIDIA** — `nvidia-smi --query-gpu=...` (fallback)
3. **NVIDIA (py)** — `pynvml` Python bindings (last resort)
4. **None** — returns zeros if no GPU tool is found

## Firmware / theme upload

The monitor firmware and theme data are bundled in `img.dat` (≈3.8 MB), uploaded via
**YMODEM over HID** when the device is first initialized. This contains:

- STM32 firmware
- Background images
- Font files (HelveticaNeue, LiquidCrystal, etc.)
- Qt `.ui` widget layout definitions

This upload **only happens from the original Windows app**. Once uploaded, the theme
persists in flash. The Linux driver assumes a pre-loaded theme and only sends live
sensor data.

## Performance

- Update rate: **1 Hz** (configurable via `INTERVAL` in the script)
- Each cycle: 1× type 0x02 packet + 1× type 0x03 packet = **2 HID writes/second**
- CPU overhead: negligible (<0.1% on modern hardware)
- RAM usage: ~15 MB

## Why 65 bytes?

HID reports are sized by the device's report descriptor. This device uses a **64-byte
input/output report** with a separate **1-byte Report ID**. The python `hidapi` library
prepends the Report ID automatically, so the application layer sends 65 bytes
(1 ID + 64 payload), but the USB transfer itself is 64 bytes (the ID is stripped
by the HID driver).
