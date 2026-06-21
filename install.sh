#!/usr/bin/env bash
# =============================================================================
# SmartScreen Monitor — systemd install script
# =============================================================================
# Installs smartscreen-monitor.service to run the USB LCD driver
# automatically at boot as root.
#
# Usage:
#   sudo ./install.sh                 # Interactive mode
#   sudo ./install.sh --yes           # Non-interactive, accept all
#   sudo ./install.sh --dry-run       # Check without installing
#   sudo ./install.sh --uninstall     # Remove the service
#
# =============================================================================

set -euo pipefail

# ── Colors ─────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

msg()   { echo -e "  ${1}"; }
ok()    { echo -e " ${GREEN}✓${NC} ${1}"; }
warn()  { echo -e " ${YELLOW}⚠${NC} ${1}"; }
err()   { echo -e " ${RED}✗${NC} ${1}"; }
info()  { echo -e " ${CYAN}ℹ${NC} ${1}"; }
header(){ echo -e "\n${BOLD}── ${1}${NC}"; }

# ── Argument parsing ──────────────────────────────────────────────
YES=false
DRY_RUN=false
UNINSTALL=false

for arg in "$@"; do
    case "$arg" in
        --yes|-y)     YES=true ;;
        --dry-run|-n) DRY_RUN=true ;;
        --uninstall|-u) UNINSTALL=true ;;
        --help|-h)
            echo "Usage: sudo ./install.sh [--yes|-y] [--dry-run|-n] [--uninstall|-u]"
            exit 0 ;;
        *) err "Unknown option: $arg"; exit 1 ;;
    esac
done

# ── Root permission check ─────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "This script must be run with sudo or as root."
    echo "  sudo $0 $*"
    exit 1
fi

# ── Path detection ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_TEMPLATE="${SCRIPT_DIR}/smartscreen-monitor.service"
DRIVER_SCRIPT="${SCRIPT_DIR}/smartscreen_driver.py"
SERVICE_NAME="smartscreen-monitor"
SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}.service"

# Look for the venv Python
PYTHON_BIN=""
for candidate in \
    "${SCRIPT_DIR}/.venv/bin/python3" \
    "/home/$(logname 2>/dev/null || echo 'unknown')/.venv/bin/python3" \
    "$(which python3 2>/dev/null || true)"; do
    if [[ -x "$candidate" ]]; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    err "Python 3 not found. Check your virtual environment."
    exit 1
fi

# ── Uninstall ──────────────────────────────────────────────────────
if $UNINSTALL; then
    header "Service removal"

    if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
        msg "Stopping service..."
        systemctl stop "${SERVICE_NAME}"
        ok "Service stopped."
    fi

    if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
        msg "Disabling auto-start..."
        systemctl disable "${SERVICE_NAME}"
        ok "Auto-start disabled."
    fi

    if [[ -f "$SERVICE_DEST" ]]; then
        rm -f "$SERVICE_DEST"
        systemctl daemon-reload
        ok "Service file removed: ${SERVICE_DEST}"
    fi

    msg ""
    ok "Uninstall complete."
    exit 0
fi

# ── Pre-flight checks ─────────────────────────────────────────────
header "SmartScreen Monitor — systemd Installation"
msg ""

info "Install directory: ${SCRIPT_DIR}"
info "Python detected:   ${PYTHON_BIN}"
info "Driver script:     ${DRIVER_SCRIPT}"
msg ""

# Check driver exists
if [[ ! -f "$DRIVER_SCRIPT" ]]; then
    err "Driver script not found: ${DRIVER_SCRIPT}"
    exit 1
fi
ok "Driver script found."

# Check service template exists
if [[ ! -f "$SERVICE_TEMPLATE" ]]; then
    err "Systemd template not found: ${SERVICE_TEMPLATE}"
    exit 1
fi
ok "Service template found."

# Check Python dependencies
header "Python dependency check"

DEPS_OK=true
for mod in hid psutil; do
    if "$PYTHON_BIN" -c "import ${mod}" 2>/dev/null; then
        ok "Module ${mod}"
    else
        err "Module ${mod} missing — install with: pip install ${mod}"
        DEPS_OK=false
    fi
done

if ! $DEPS_OK; then
    err "Missing dependencies. Installation aborted."
    exit 1
fi

# Check GPU tools
GPU_BACKEND="none"
if command -v rocm-smi &>/dev/null; then
    GPU_BACKEND="rocm-smi (AMD)"
elif command -v nvidia-smi &>/dev/null; then
    GPU_BACKEND="nvidia-smi (NVIDIA)"
else
    warn "Neither rocm-smi nor nvidia-smi detected. GPU metrics will be unavailable."
fi
if [[ -n "$GPU_BACKEND" ]]; then
    ok "GPU backend: ${GPU_BACKEND}"
fi

# ── Interactive confirmation ──────────────────────────────────────
if ! $YES && ! $DRY_RUN; then
    echo ""
    read -rp "  Install and enable the service at boot? [Y/n] " confirm
    confirm="${confirm:-y}"
    if [[ ! "$confirm" =~ ^[OoYy] ]]; then
        msg "Installation cancelled."
        exit 0
    fi
fi

# ── Service file generation ───────────────────────────────────────
header "Generating service file"

TMP_SERVICE="$(mktemp /tmp/smartscreen-monitor.service.XXXXXX)"

sed \
    -e "s|__WORKDIR__|${SCRIPT_DIR}|g" \
    -e "s|__PYTHON__|${PYTHON_BIN}|g" \
    -e "s|__SCRIPT__|${DRIVER_SCRIPT}|g" \
    "$SERVICE_TEMPLATE" > "$TMP_SERVICE"

ok "Service file generated."

# Show a preview
info "Service contents:"
echo "  ──────────────────────────────────────────"
sed -n '/^\[Service\]/,/^\[Install\]/p' "$TMP_SERVICE" | while IFS= read -r line; do
    echo "  $line"
done
echo "  ──────────────────────────────────────────"

# ── Installation ──────────────────────────────────────────────────
if $DRY_RUN; then
    msg ""
    ok "Dry-run complete. No changes made."
    rm -f "$TMP_SERVICE"
    exit 0
fi

header "Installing service"

# Copy service
cp "$TMP_SERVICE" "$SERVICE_DEST"
rm -f "$TMP_SERVICE"
ok "Service copied to ${SERVICE_DEST}"

# Reload systemd
systemctl daemon-reload
ok "systemd reloaded."

# Enable at boot
systemctl enable "${SERVICE_NAME}" 2>/dev/null
ok "Service enabled at boot."

# ── Start ──────────────────────────────────────────────────────────
if ! $YES; then
    echo ""
    read -rp "  Start the service now? [Y/n] " start_now
    start_now="${start_now:-y}"
else
    start_now="y"
fi

if [[ "$start_now" =~ ^[OoYy] ]]; then
    msg "Starting service..."
    if systemctl start "${SERVICE_NAME}"; then
        sleep 1
        if systemctl is-active --quiet "${SERVICE_NAME}"; then
            ok "Service started successfully."
        else
            warn "Service does not appear active. Check with:"
            echo "  sudo journalctl -u ${SERVICE_NAME} -f"
        fi
    else
        warn "Failed to start. Check logs:"
        echo "  sudo journalctl -u ${SERVICE_NAME} -xe"
    fi
fi

# ── Summary ────────────────────────────────────────────────────────
echo ""
header "Summary"
echo ""
echo "  Service    : ${SERVICE_NAME}"
echo "  Status     : $(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || echo 'inactive')"
echo "  Boot       : $(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || echo 'disabled')"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status ${SERVICE_NAME}    # Check status"
echo "    sudo journalctl -u ${SERVICE_NAME} -f    # Live logs"
echo "    sudo systemctl restart ${SERVICE_NAME}   # Restart"
echo "    sudo ./install.sh --uninstall            # Remove service"
echo ""
ok "Installation complete."
