#!/usr/bin/env bash
# setup-encrypted-storage.sh — Create a LUKS-encrypted volume for Hitchhiker data.
#
# This script creates a file-backed LUKS volume that stores Signal key material
# and Grist database files. The encrypted volume is scoped to Docker volumes only —
# application code, configuration, and Docker images are NOT encrypted by this.
#
# What gets encrypted:
#   - Signal keys, session data, and PII (phone numbers, contacts, groups)
#   - Grist documents (SQLite files, including action/undo history)
#
# Usage:
#   sudo ./scripts/setup-encrypted-storage.sh [size_mb] [image_path] [mount_point]
#
# Defaults:
#   size_mb     = 512        (512 MB — adjust for your data size)
#   image_path  = ./hitchhiker.img
#   mount_point = /mnt/hitchhiker
#
# After setup, start the stack:
#   docker compose up -d --build
#
# On reboot, unlock and mount first:
#   sudo ./scripts/mount-encrypted-storage.sh

set -euo pipefail

SIZE_MB="${1:-512}"
IMAGE_PATH="${2:-./hitchhiker.img}"
MOUNT_POINT="${3:-/mnt/hitchhiker}"
VOLUME_NAME="hitchhiker-vault"

# --- Preflight checks ---

if [[ $EUID -ne 0 ]]; then
    echo "Error: this script must be run as root (sudo)." >&2
    exit 1
fi

if ! command -v cryptsetup &>/dev/null; then
    echo "Error: cryptsetup is not installed." >&2
    echo "Install it with: apt install cryptsetup  (Debian/Ubuntu)" >&2
    echo "                  dnf install cryptsetup  (Fedora/RHEL)" >&2
    exit 1
fi

if [[ -f "$IMAGE_PATH" ]]; then
    echo "Error: $IMAGE_PATH already exists. Remove it first or choose a different path." >&2
    exit 1
fi

if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Error: $MOUNT_POINT is already a mount point." >&2
    exit 1
fi

# --- Create the encrypted volume ---

echo "Creating ${SIZE_MB} MB encrypted volume at ${IMAGE_PATH}..."

# Allocate the image file (fallocate is faster than dd)
if command -v fallocate &>/dev/null; then
    fallocate -l "${SIZE_MB}M" "$IMAGE_PATH"
else
    dd if=/dev/zero of="$IMAGE_PATH" bs=1M count="$SIZE_MB" status=progress
fi
chmod 600 "$IMAGE_PATH"

# Format as LUKS
echo ""
echo "You will be prompted to set a passphrase for the encrypted volume."
echo "Choose a strong passphrase and store it securely — losing it means losing all data."
echo ""
cryptsetup luksFormat --type luks2 "$IMAGE_PATH"

# Open the LUKS volume
cryptsetup open "$IMAGE_PATH" "$VOLUME_NAME"

# Create a filesystem
mkfs.ext4 -q "/dev/mapper/$VOLUME_NAME"

# Mount it
mkdir -p "$MOUNT_POINT"
mount "/dev/mapper/$VOLUME_NAME" "$MOUNT_POINT"

# Create subdirectories for Docker volumes
mkdir -p "$MOUNT_POINT/signal" "$MOUNT_POINT/grist"

# Set ownership for rootless Docker compatibility.
# When run via sudo, SUDO_USER is the real (non-root) user. Rootless Docker
# runs as that user and needs to own these directories to bind-mount them.
REAL_USER="${SUDO_USER:-$USER}"
REAL_GROUP="$(id -gn "$REAL_USER")"
chown -R "$REAL_USER:$REAL_GROUP" "$MOUNT_POINT"
chmod 700 "$MOUNT_POINT" "$MOUNT_POINT/signal" "$MOUNT_POINT/grist"

echo ""
echo "Encrypted storage is ready."
echo ""
echo "  Image:       $IMAGE_PATH"
echo "  Mount point:  $MOUNT_POINT"
echo "  LUKS name:    $VOLUME_NAME"
echo ""
echo "  Signal data:  $MOUNT_POINT/signal"
echo "  Grist data:   $MOUNT_POINT/grist"
echo ""
echo "Docker Compose will use these directories as volume backing stores."
echo ""
echo "Next steps:"
echo "  1. docker compose up -d --build"
echo "  2. After reboot: sudo ./scripts/mount-encrypted-storage.sh"
echo ""
echo "To change the default mount point, set HITCHHIKER_ENCRYPTED_MOUNT in .env:"
echo "  echo 'HITCHHIKER_ENCRYPTED_MOUNT=$MOUNT_POINT' >> .env"
