#!/usr/bin/env bash
# mount-encrypted-storage.sh — Unlock and mount the Hitchhiker encrypted volume.
#
# Run this after every reboot, before starting docker compose.
# You will be prompted for the LUKS passphrase.
#
# Usage:
#   sudo ./scripts/mount-encrypted-storage.sh [image_path] [mount_point]

set -euo pipefail

IMAGE_PATH="${1:-./hitchhiker.img}"
MOUNT_POINT="${2:-/mnt/hitchhiker}"
VOLUME_NAME="hitchhiker-vault"

if [[ $EUID -ne 0 ]]; then
    echo "Error: this script must be run as root (sudo)." >&2
    exit 1
fi

if ! [[ -f "$IMAGE_PATH" ]]; then
    echo "Error: $IMAGE_PATH not found. Run setup-encrypted-storage.sh first." >&2
    exit 1
fi

if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Already mounted at $MOUNT_POINT."
    exit 0
fi

# Open the LUKS volume (prompts for passphrase)
if [[ ! -e "/dev/mapper/$VOLUME_NAME" ]]; then
    cryptsetup open "$IMAGE_PATH" "$VOLUME_NAME"
fi

# Mount
mkdir -p "$MOUNT_POINT"
mount "/dev/mapper/$VOLUME_NAME" "$MOUNT_POINT"

# Ensure subdirectories exist and are owned by the real user (rootless Docker compat)
REAL_USER="${SUDO_USER:-$USER}"
REAL_GROUP="$(id -gn "$REAL_USER")"
mkdir -p "$MOUNT_POINT/signal" "$MOUNT_POINT/grist"
chown -R "$REAL_USER:$REAL_GROUP" "$MOUNT_POINT"
chmod 700 "$MOUNT_POINT" "$MOUNT_POINT/signal" "$MOUNT_POINT/grist"

echo "Encrypted volume mounted at $MOUNT_POINT (owned by $REAL_USER)."
echo "You can now start the stack: docker compose up -d"
