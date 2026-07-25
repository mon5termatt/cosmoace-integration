#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ADDON_DIR="/user-resource/ace-addon"
KLIPPER_CONFIG_DIR="/etc/klipper/config"
KLIPPER_READONLY_DIR="${KLIPPER_CONFIG_DIR}/klipper-readonly"
KLIPPER_USER_MACROS_CFG="${KLIPPER_CONFIG_DIR}/ace-addon.cfg"
KLIPPER_ADDON_CFG="${KLIPPER_READONLY_DIR}/ace-addon.cfg"

required_files="files/ace-addon.py files/ace-addon.conf files/ace-command.sh files/ace_macros.cfg files/ace-addon.init files/ace-usb-watch.sh"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root."
    exit 1
fi

for file in $required_files; do
    if [ ! -f "${SCRIPT_DIR}/${file}" ]; then
        echo "Missing ${file} in add-on directory."
        exit 1
    fi
done

echo "Remounting root as RW..."
mount -o remount,rw / || echo "Warning: Could not remount root as RW. Proceeding anyway..."

if command -v service >/dev/null 2>&1; then
    service ace-addon stop 2>/dev/null || true
elif [ -f /etc/init.d/ace-addon ]; then
    /etc/init.d/ace-addon stop 2>/dev/null || true
fi

mkdir -p "$ADDON_DIR"
mkdir -p "$KLIPPER_READONLY_DIR"

echo "Copying files..."
cp "${SCRIPT_DIR}/files/ace-addon.py" "${ADDON_DIR}/ace-addon.py"
cp "${SCRIPT_DIR}/files/ace-command.sh" "${ADDON_DIR}/ace-command.sh"
cp "${SCRIPT_DIR}/files/ace-usb-watch.sh" "${ADDON_DIR}/ace-usb-watch.sh"
cp "${SCRIPT_DIR}/files/ace_macros.cfg" "${ADDON_DIR}/ace_macros.default.cfg"
chmod 0755 "${ADDON_DIR}/ace-addon.py" "${ADDON_DIR}/ace-command.sh" "${ADDON_DIR}/ace-usb-watch.sh"
chmod 0644 "${ADDON_DIR}/ace_macros.default.cfg"

if [ ! -f "${KLIPPER_USER_MACROS_CFG}" ]; then
    echo "Installing default macro config..."
    cp "${SCRIPT_DIR}/files/ace_macros.cfg" "${KLIPPER_USER_MACROS_CFG}"
else
    echo "Preserving existing macro config at ${KLIPPER_USER_MACROS_CFG}"
fi

chmod 0644 "${KLIPPER_USER_MACROS_CFG}"
ln -sfn "${KLIPPER_USER_MACROS_CFG}" "${KLIPPER_ADDON_CFG}"

if [ ! -f "${ADDON_DIR}/ace-addon.conf" ]; then
    cp "${SCRIPT_DIR}/files/ace-addon.conf" "${ADDON_DIR}/ace-addon.conf"
fi
chmod 0644 "${ADDON_DIR}/ace-addon.conf"

# Install init script for optional manual heartbeat, but do NOT enable at boot.
# CosmOS (~112MB RAM) cannot afford an always-on Python poller.
echo "Installing ace-addon init script (boot autostart disabled)..."
cp "${SCRIPT_DIR}/files/ace-addon.init" /etc/init.d/ace-addon
chmod 0755 /etc/init.d/ace-addon
rm -f /etc/rc2.d/S80ace-addon /etc/rc3.d/S80ace-addon /etc/rc4.d/S80ace-addon /etc/rc5.d/S80ace-addon
for level in 0 1 6; do
    ln -sfn ../init.d/ace-addon "/etc/rc${level}.d/K20ace-addon" 2>/dev/null || true
done
if command -v update-rc.d >/dev/null 2>&1; then
    update-rc.d -f ace-addon remove >/dev/null 2>&1 || true
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

echo "ACE add-on installed (CLI; heartbeat OFF by default)."
echo "Configuration:      $ADDON_DIR/ace-addon.conf"
echo "Editable macros:    $KLIPPER_USER_MACROS_CFG"
echo "USB watch (manual): $ADDON_DIR/ace-usb-watch.sh"
echo "Optional heartbeat: service ace-addon start  # only if keepalive_enabled=true"
