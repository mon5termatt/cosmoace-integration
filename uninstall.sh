#!/bin/sh
set -eu

ADDON_DIR="/user-resource/ace-addon"
KLIPPER_CONFIG_DIR="/etc/klipper/config"
KLIPPER_USER_MACROS_CFG="/etc/klipper/config/ace-addon.cfg"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root."
    exit 1
fi

# Optional: KEEP_CANVAS=1|0 for non-interactive uninstalls.
KEEP_CANVAS="${KEEP_CANVAS:-}"
if [ -z "$KEEP_CANVAS" ]; then
    if [ -t 0 ]; then
        echo ""
        echo "Canvas toolhead hardware (hotend:PB2 runout, cutter, front cover) can be"
        echo "kept after ACE is removed — useful if the ACE is gone but the Canvas"
        echo "toolhead is still installed."
        printf "Keep toolhead runout sensor and cutter buttons? [y/N] "
        read -r ans || ans=""
        case "$ans" in
            y|Y|yes|YES) KEEP_CANVAS=1 ;;
            *) KEEP_CANVAS=0 ;;
        esac
    else
        echo "Non-interactive uninstall: removing all managed hardware."
        echo "  Set KEEP_CANVAS=1 to leave Canvas toolhead sensors/buttons."
        KEEP_CANVAS=0
    fi
fi

echo "Remounting root as RW..."
mount -o remount,rw / || echo "Warning: Could not remount root as RW."

if [ -f "/etc/init.d/ace-addon" ]; then
    echo "Stopping service..."
    if command -v service >/dev/null 2>&1; then
        service ace-addon stop || true
    fi
    rm -f /etc/init.d/ace-addon
    rm -f /etc/rc*.d/S*ace-addon
    rm -f /etc/rc*.d/K*ace-addon
fi

echo "Removing files..."
rm -f /etc/udev/rules.d/99-ace-keepalive.rules

# Remove ACE-managed config before wiping ADDON_DIR (needs ace-setup.py).
if [ -x "${ADDON_DIR}/ace-setup.py" ]; then
    if [ "$KEEP_CANVAS" = "1" ]; then
        echo "Leaving Canvas toolhead sensors/buttons in canvas.cfg (no ACE)..."
        python3 "${ADDON_DIR}/ace-setup.py" remove_managed \
            --restore-sensor-name HUB --keep-canvas-toolhead || true
    else
        echo "Removing CosmoACE managed hardware config..."
        python3 "${ADDON_DIR}/ace-setup.py" remove_managed --restore-sensor-name HUB || true
        rm -f "${KLIPPER_CONFIG_DIR}/ace-hardware.cfg"
    fi
    echo "Removing ace-addon.cfg include from printer.cfg..."
    python3 "${ADDON_DIR}/ace-setup.py" remove_macros_include || true
else
    if [ "$KEEP_CANVAS" != "1" ]; then
        rm -f "${KLIPPER_CONFIG_DIR}/ace-hardware.cfg"
    fi
fi

# Legacy install path: wipe-prone symlink under klipper-readonly.
rm -f "${KLIPPER_CONFIG_DIR}/klipper-readonly/ace-addon.cfg"
rm -rf "$ADDON_DIR"

MACHINE_CFG="/etc/klipper/config/klipper-readonly/machine.cfg"
MACHINE_BAK="${MACHINE_CFG}.pre-cosmoace.bak"
if [ -f "$MACHINE_BAK" ]; then
    echo "Restoring CosmOS machine.cfg from ${MACHINE_BAK}..."
    cp "$MACHINE_BAK" "$MACHINE_CFG"
fi

if command -v service >/dev/null 2>&1; then
    echo "Restarting Klipper..."
    service klipper restart || true
elif command -v systemctl >/dev/null 2>&1; then
    echo "Restarting Klipper..."
    systemctl restart klipper || true
fi

echo "Remounting root as RO..."
mount -o remount,ro / || echo "Warning: Could not remount root as RO."

echo "ACE add-on uninstalled."
if [ "$KEEP_CANVAS" = "1" ]; then
    echo "Kept Canvas toolhead config at:"
    echo "  ${KLIPPER_CONFIG_DIR}/canvas.cfg"
    echo "  (runout + cutter + front cover; no ACE hooks)"
fi
echo "Preserved editable macro file (manual deletion required if desired):"
echo "  $KLIPPER_USER_MACROS_CFG"
