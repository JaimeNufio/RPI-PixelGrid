#!/bin/bash
# One-time root setup for the RGB matrix. Run from the repo root: sudo bash deploy/setup_root.sh
set -e
apt-get update
apt-get install -y python3-dev cython3 cmake build-essential

# Onboard audio shares the PWM timer the matrix driver uses; turn it off.
CFG=/boot/firmware/config.txt
if grep -q '^dtparam=audio=on' "$CFG"; then
    sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$CFG"
    echo "Disabled onboard audio in $CFG (takes effect after reboot)."
fi
echo "blacklist snd_bcm2835" > /etc/modprobe.d/blacklist-rgb-matrix.conf
modprobe -r snd_bcm2835 2>/dev/null && echo "Unloaded snd_bcm2835 for this boot." || echo "Could not unload snd_bcm2835 now; reboot to apply."
echo "Root setup done."
