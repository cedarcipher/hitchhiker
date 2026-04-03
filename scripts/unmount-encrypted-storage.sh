#!/usr/bin/env bash
# unmount-encrypted-storage.sh — Stop the stack, unmount, and lock the encrypted volume.
#
# This ensures all data is flushed and the LUKS volume is locked. Data on disk
# is unreadable until the volume is unlocked again with the passphrase.
#
# Usage:
#   sudo ./scripts/unmount-encrypted-storage.sh [mount_point]

set -euo pipefail

MOUNT_POINT="${1:-/mnt/hitchhiker}"
VOLUME_NAME="hitchhiker-vault"

if [[ $EUID -ne 0 ]]; then
    echo "Error: this script must be run as root (sudo)." >&2
    exit 1
fi

# Stop Docker containers that use the volumes
echo "Stopping docker compose services..."
docker compose down 2>/dev/null || true

# Unmount
if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    umount "$MOUNT_POINT"
    echo "Unmounted $MOUNT_POINT."
fi

# Close the LUKS volume
if [[ -e "/dev/mapper/$VOLUME_NAME" ]]; then
    cryptsetup close "$VOLUME_NAME"
    echo "LUKS volume locked. Data is encrypted at rest."
fi
