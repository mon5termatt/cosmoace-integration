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

# Install the low-priority protocol watchdog. Real get_status traffic prevents
# the ACE GD32 from dropping USB on its exact 3.584s idle watchdog.
echo "Installing ACE protocol keepalive service..."
cp "${SCRIPT_DIR}/files/ace-addon.init" /etc/init.d/ace-addon
chmod 0755 /etc/init.d/ace-addon
rm -f /etc/rc2.d/S80ace-addon /etc/rc3.d/S80ace-addon /etc/rc4.d/S80ace-addon /etc/rc5.d/S80ace-addon
for level in 2 3 4 5; do
    ln -sfn ../init.d/ace-addon "/etc/rc${level}.d/S98ace-addon" 2>/dev/null || true
done
for level in 0 1 6; do
    ln -sfn ../init.d/ace-addon "/etc/rc${level}.d/K20ace-addon" 2>/dev/null || true
done

# Disable USB autosuspend for ACE Pro (VID 28e9 / PID 018a).
# Match the USB device only — not interfaces (:1.0/:1.1), which reject
# power/control writes ("Permission denied" from udevd).
echo "Securing ACE Pro USB connection (disabling auto-suspend)..."
echo 'ACTION=="add", SUBSYSTEM=="usb", DEVTYPE=="usb_device", ATTR{idVendor}=="28e9", ATTR{idProduct}=="018a", ATTR{power/control}="on"' > /etc/udev/rules.d/99-ace-keepalive.rules
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger || true
fi

if command -v service >/dev/null 2>&1; then
    echo "Restarting Klipper..."
    service klipper restart || true
    echo "Waiting 45s for Klipper load to settle before starting ACE keepalive..."
    sleep 45
    service ace-addon start || true
elif command -v systemctl >/dev/null 2>&1; then
    echo "Restarting Klipper..."
    systemctl restart klipper || true
    echo "Waiting 45s for Klipper load to settle before starting ACE keepalive..."
    sleep 45
    systemctl start ace-addon || true
fi

echo "Remounting root as RO..."
mount -o remount,ro / || echo "Warning: Could not remount root as RO."

echo "ACE add-on installed (CLI + low-priority protocol keepalive)."
echo "Configuration:      $ADDON_DIR/ace-addon.conf"
echo "Editable macros:    $KLIPPER_USER_MACROS_CFG"
echo "USB watch (manual): $ADDON_DIR/ace-usb-watch.sh"
echo "Keepalive service:  service ace-addon status"
