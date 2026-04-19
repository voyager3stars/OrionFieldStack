#!/bin/bash
# =================================================================
# Project:      OrionFieldStack
# Component:    Time Synchronization (GPS & Chrony) Setup
# Author:       voyager3.stars
# Web:          https://voyager3.stars.ne.jp
# Version:      1.0.0
# License:      MIT
# Description:  Automated high-precision time sync for Raspberry Pi.
#               Compatible with Raspberry Pi OS Bookworm.
# =================================================================

set -e

# Fix line endings for files edited on Windows (CRLF to LF)
sed -i 's/\r$//' "$0" || true

echo "--- OrionFieldStack: Starting Time-Sync Setup ---"

# 0. Hardware Configuration (UART)
# Enable UART hardware and disable serial console output to prevent data conflict.
echo "[0/7] Enabling UART hardware and modifying config.txt..."
if ! grep -q "enable_uart=1" /boot/firmware/config.txt; then
    sudo bash -c 'echo "enable_uart=1" >> /boot/firmware/config.txt'
fi

if grep -q "console=serial0" /boot/firmware/cmdline.txt; then
    sudo sed -i 's/console=serial0,[0-9]* //' /boot/firmware/cmdline.txt
fi

# 1. Package Installation
echo "[1/7] Installing gpsd, python3-gps, and chrony..."
sudo apt update
sudo apt install -y gpsd python3-gps chrony

# 2. Free Serial Port
# Disable OS from using the serial port for login shell.
echo "[2/7] Disabling serial getty on ttyAMA0..."
sudo systemctl stop serial-getty@ttyAMA0.service || true
sudo systemctl disable serial-getty@ttyAMA0.service || true
sudo systemctl mask serial-getty@ttyAMA0.service

# 3. GPSD Socket Management
# Mask gpsd.socket to allow the daemon to manage the serial port directly.
echo "[3/7] Masking gpsd.socket to prevent conflicts..."
sudo systemctl stop gpsd.socket || true
sudo systemctl disable gpsd.socket || true
sudo systemctl mask gpsd.socket

# 4. GPSD Configuration
echo "[4/7] Configuring /etc/default/gpsd..."
sudo bash -c 'cat << EOF > /etc/default/gpsd
START_DAEMON="true"
USBAUTO="false"
DEVICES="/dev/ttyAMA0"
GPSD_OPTIONS="-N -n -G -s 9600"
GPSD_SOCKET="/run/gpsd.sock"
EOF'

# 5. GPSD Service Customization
# Optimize service startup for OrionFieldStack requirements.
echo "[5/7] Overwriting gpsd.service for stability..."
sudo bash -c 'cat << EOF > /lib/systemd/system/gpsd.service
[Unit]
Description=GPS Daemon for OrionFieldStack
After=network.target
Conflicts=gpsd.socket

[Service]
Type=simple
EnvironmentFile=-/etc/default/gpsd
ExecStart=/usr/sbin/gpsd \$GPSD_OPTIONS \$DEVICES
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF'

# 6. Chrony Configuration (NTP-GPS Pipeline)
# Connect GPS Shared Memory (SHM 2) to Chrony for microsecond precision.
echo "[6/7] Configuring chrony for GPS (SHM 2) and quick sync..."
if ! grep -q "SHM 2" /etc/chrony/chrony.conf; then
    sudo bash -c 'cat << EOF >> /etc/chrony/chrony.conf

# Added by OrionFieldStack (GPS SHM 2)
refclock SHM 2 refid GPS precision 1e-1 offset 0.128 delay 0.2 poll 4 trust
EOF'
fi

# Enable fast stepping for initial sync
if grep -q "makestep" /etc/chrony/chrony.conf; then
    sudo sed -i 's/^#*makestep.*/makestep 1.0 3/' /etc/chrony/chrony.conf
else
    sudo bash -c 'echo "makestep 1.0 3" >> /etc/chrony/chrony.conf'
fi

# 7. Apply Changes
echo "[7/7] Finalizing: Restarting Services ---"
sudo systemctl daemon-reload
sudo systemctl unmask gpsd.service || true
sudo systemctl enable gpsd
sudo systemctl restart gpsd
sudo systemctl restart chrony

echo "-------------------------------------------------------"
echo " OrionFieldStack Setup Complete! "
echo " [Action Required] Please reboot: sudo reboot"
echo ""
echo " After reboot, use these commands to verify:"
echo " 1. GPS Fix Status:  cgps -s"
echo " 2. Sync Status:     chronyc sources"
echo "-------------------------------------------------------"