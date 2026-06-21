#!/usr/bin/env python3
"""
SmartMonitor Linux Driver - Final version
VID:0483 PID:0065 | 3.5" USB LCD stats monitor

Protocol reverse-engineered from original Windows app via Frida hooking.
Field mapping verified through iterative testing with the display.

Requirements: pip install hidapi psutil
Optional GPU:  rocm-smi (AMD) | nvidia-smi or nvidia-ml-py3 (NVIDIA)
"""

import hid
import psutil
import time
import sys
import os

# ── Configuration ──────────────────────────────────────────────────
VID = 0x0483
PID = 0x0065
INTERVAL = 1.0  # update interval in seconds

# ── Field mapping (confirmed via testing) ─────────────────────────
F_CPU_TEMP   = 0x01   # °C
F_CPU_CLOCK  = 0x02   # MHz
F_CPU_USAGE  = 0x03   # %
F_CPU_FAN    = 0x04   # RPM
F_GPU_TEMP   = 0x05   # °C
F_GPU_USAGE  = 0x07   # %
F_GPU_MCLK   = 0x08   # MHz (memory clock)
F_GPU_MUSAGE = 0x09   # % (memory usage)
F_RAM_USED   = 0x0A   # MB (display shows GB)
F_RAM_AVAIL  = 0x0B   # MB (display shows GB)
F_RAM_PCT    = 0x0C   # %
F_DISK_TOTAL = 0x0E   # GB
F_DISK_FREE  = 0x10   # GB
F_DISK_PCT   = 0x11   # %
F_NET_UP     = 0x12   # KB/s
F_NET_DL     = 0x13   # KB/s
F_VOLUME     = 0x14   # %


def build_packet(cpu_temp, cpu_clock, cpu_usage, cpu_fan,
                 gpu_temp, gpu_usage, gpu_mclk, gpu_musage,
                 ram_used_mb, ram_avail_mb, ram_pct,
                 disk_total_gb, disk_free_gb, disk_pct,
                 net_up, net_dl, volume=100):
    """Build the 65-byte HID report (type 0x02)."""
    pkt = bytearray(65)
    pkt[0] = 0x00   # Report ID
    pkt[1] = 0x02   # Command type
    pkt[2] = 0x14   # Field count (20)

    def sf(idx, value):
        """Set field at index with 16-bit big-endian value."""
        value = max(0, min(int(value), 0xFFFF))
        off = 3 + (idx - 1) * 3
        pkt[off] = idx
        pkt[off + 1] = (value >> 8) & 0xFF
        pkt[off + 2] = value & 0xFF

    sf(F_CPU_TEMP,   cpu_temp)
    sf(F_CPU_CLOCK,  cpu_clock)
    sf(F_CPU_USAGE,  cpu_usage)
    sf(F_CPU_FAN,    cpu_fan)
    sf(F_GPU_TEMP,   gpu_temp)
    sf(0x06,         0)              # unused in current theme
    sf(F_GPU_USAGE,  gpu_usage)
    sf(F_GPU_MCLK,   gpu_mclk)
    sf(F_GPU_MUSAGE, gpu_musage)
    sf(F_RAM_USED,   min(ram_used_mb, 32767))
    sf(F_RAM_AVAIL,  min(ram_avail_mb, 32767))
    sf(F_RAM_PCT,    ram_pct)
    sf(0x0D,         0)              # unused
    sf(F_DISK_TOTAL, disk_total_gb)
    sf(0x0F,         0)              # unused
    sf(F_DISK_FREE,  disk_free_gb)
    sf(F_DISK_PCT,   disk_pct)
    sf(F_NET_UP,     net_up)
    sf(F_NET_DL,     net_dl)
    sf(F_VOLUME,     volume)

    return bytes(pkt)


def build_heartbeat(counter):
    """Build the type 0x03 counter/heartbeat packet."""
    pkt = bytearray(65)
    pkt[0] = 0x00
    pkt[1] = 0x03
    pkt[2] = 0x01; pkt[3] = 0x15; pkt[4] = 0x1A
    pkt[5] = 0x06; pkt[6] = 0x15; pkt[7] = 0x0D
    pkt[8] = 0x00; pkt[9] = counter & 0xFF
    pkt[10] = 0x07; pkt[11] = 0x64
    return bytes(pkt)


# ── System stats ──────────────────────────────────────────────────

def get_cpu():
    """Return (temp°C, clock_MHz, usage%, fan_RPM)."""
    usage = int(psutil.cpu_percent(interval=0.1))
    clock = 3600
    try:
        freq = psutil.cpu_freq()
        if freq:
            clock = int(freq.current)
    except:
        pass
    temp = 35
    try:
        for _, entries in psutil.sensors_temperatures().items():
            for e in entries:
                if 'cpu' in e.label.lower() or 'core' in e.label.lower():
                    temp = int(e.current)
                    break
    except:
        pass
    fan = 0
    try:
        for _, entries in psutil.sensors_fans().items():
            if entries:
                fan = int(entries[0].current)
                break
    except:
        pass
    return temp, clock, usage, fan


def get_gpu():
    """Return (temp°C, usage%, mem_clock_MHz, mem_usage%)."""
    import subprocess
    import re

    # ── AMD (rocm-smi) ──────────────────────────────────────────
    try:
        out = subprocess.check_output(
            ['rocm-smi', '--csv', '-t', '-u', '-c', '--showmemuse'],
            timeout=5
        ).decode().strip()
        lines = out.strip().split('\n')
        if len(lines) >= 2:
            headers = lines[0].split(',')
            values = lines[1].split(',')
            data = dict(zip(headers, values))

            temp = int(float(data.get('Temperature (Sensor edge) (C)', '0')))
            usage = int(float(data.get('GPU use (%)', '0')))

            mclk_str = data.get('mclk clock speed:', '(0Mhz)')
            mclk = 0
            m = re.search(r'(\d+)Mhz', mclk_str)
            if m:
                mclk = int(m.group(1))

            mem_usage = int(float(data.get('GPU Memory Allocated (VRAM%)', '0')))
            return (temp, usage, mclk, mem_usage)
    except Exception:
        pass

    # ── NVIDIA (nvidia-smi) ─────────────────────────────────────
    try:
        out = subprocess.check_output(
            ['nvidia-smi',
             '--query-gpu=temperature.gpu,utilization.gpu,clocks.current.memory,utilization.memory',
             '--format=csv,noheader,nounits'],
            timeout=2
        ).decode().strip()
        parts = [p.strip() for p in out.split(',')]
        if len(parts) >= 4:
            return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    except Exception:
        pass

    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        mclk = pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM)
        pynvml.nvmlShutdown()
        return (temp, util.gpu, mclk, util.memory)
    except Exception:
        pass

    return (0, 0, 0, 0)


def get_ram():
    """Return (used_MB, avail_MB, usage%)."""
    mem = psutil.virtual_memory()
    return (
        int(mem.used / (1024 * 1024)),
        int(mem.available / (1024 * 1024)),
        int(mem.percent)
    )


def get_disk():
    """Return (total_GB, free_GB, usage%)."""
    try:
        disk = psutil.disk_usage('/')
        return (
            int(disk.total / (1024 ** 3)),
            int(disk.free / (1024 ** 3)),
            int(disk.percent)
        )
    except:
        return (0, 0, 0)


def get_network(prev_net, prev_time):
    """Return (up_KBps, dl_KBps, new_state)."""
    try:
        net = psutil.net_io_counters()
        now = time.time()
        if prev_time > 0:
            elapsed = max(now - prev_time, 0.001)
            up = int((net.bytes_sent - prev_net[0]) / elapsed / 1024)
            dl = int((net.bytes_recv - prev_net[1]) / elapsed / 1024)
        else:
            up, dl = 0, 0
        return up, dl, ((net.bytes_sent, net.bytes_recv), now)
    except:
        return 0, 0, (prev_net, prev_time)


# ── Main ──────────────────────────────────────────────────────────

def main():
    print("SmartMonitor Linux Driver")
    print(f"VID:{VID:04X} PID:{PID:04X}\n")

    devs = hid.enumerate(VID, PID)
    if not devs:
        print("ERROR: Device not found. Is the USB monitor connected?")
        sys.exit(1)

    path = devs[0]['path']
    print(f"Device: {devs[0].get('product_string', 'Unknown')}")
    print(f"Path:   {str(path)[-60:]}")

    h = hid.device()
    try:
        h.open_path(path)
    except Exception as e:
        print(f"ERROR opening device: {e}")
        print("Try running with sudo or check USB permissions.")
        sys.exit(1)

    print(f"Sending updates every {INTERVAL}s. Ctrl+C to stop.\n")

    counter = 0
    prev_net = (0, 0)
    prev_time = 0

    try:
        while True:
            cpu_temp, cpu_clock, cpu_usage, cpu_fan = get_cpu()
            gpu_temp, gpu_usage, gpu_mclk, gpu_musage = get_gpu()
            ram_used, ram_avail, ram_pct = get_ram()
            disk_total, disk_free, disk_pct = get_disk()
            net_up, net_dl, (prev_net, prev_time) = get_network(prev_net, prev_time)

            pkt = build_packet(
                cpu_temp, cpu_clock, cpu_usage, cpu_fan,
                gpu_temp, gpu_usage, gpu_mclk, gpu_musage,
                ram_used, ram_avail, ram_pct,
                disk_total, disk_free, disk_pct,
                net_up, net_dl
            )
            hb = build_heartbeat(counter)

            h.write(pkt)
            h.write(hb)

            ram_total = ram_used + ram_avail
            print(f"\r[#{counter:03d}] "
                  f"CPU:{cpu_usage:3d}% {cpu_temp:2d}°C {cpu_clock}MHz "
                  f"| GPU:{gpu_usage:3d}% {gpu_temp:2d}°C "
                  f"| RAM:{ram_used//1024}.{ram_used%1024//103}G/"
                  f"{ram_total//1024}.{ram_total%1024//103}G ({ram_pct}%) "
                  f"| Disk:{disk_pct}% "
                  f"| Net:{net_up}/{net_dl} KB/s  ",
                  end='', flush=True)

            counter = (counter + 1) % 256
            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print("\n\nStopped.")
    finally:
        try:
            h.close()
        except:
            pass


if __name__ == '__main__':
    main()
