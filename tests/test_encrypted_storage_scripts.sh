#!/usr/bin/env bash
# test_encrypted_storage_scripts.sh — Verify encrypted storage scripts have
# expected safety checks and rootless Docker compatibility.
#
# Usage:
#   ./tests/test_encrypted_storage_scripts.sh
#
# These tests do NOT run the scripts (they require root + cryptsetup). Instead
# they parse the script source to verify that critical patterns are present.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)/scripts"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1" >&2; }

check_pattern() {
    local file="$1" pattern="$2" description="$3"
    if grep -qE "$pattern" "$file"; then
        pass "$description"
    else
        fail "$description"
    fi
}

echo "=== setup-encrypted-storage.sh ==="
SETUP="$SCRIPT_DIR/setup-encrypted-storage.sh"

check_pattern "$SETUP" 'set -euo pipefail' "strict error handling (set -euo pipefail)"
check_pattern "$SETUP" 'EUID -ne 0' "requires root"
check_pattern "$SETUP" 'command -v cryptsetup' "checks for cryptsetup"
check_pattern "$SETUP" 'SUDO_USER' "uses SUDO_USER for rootless Docker compatibility"
check_pattern "$SETUP" 'chown.*REAL_USER' "chowns mount point to real user"
check_pattern "$SETUP" 'chmod 700' "sets restrictive permissions"
check_pattern "$SETUP" 'luksFormat' "formats as LUKS"
check_pattern "$SETUP" 'mkfs\.ext4' "creates ext4 filesystem"

echo ""
echo "=== mount-encrypted-storage.sh ==="
MOUNT="$SCRIPT_DIR/mount-encrypted-storage.sh"

check_pattern "$MOUNT" 'set -euo pipefail' "strict error handling (set -euo pipefail)"
check_pattern "$MOUNT" 'EUID -ne 0' "requires root"
check_pattern "$MOUNT" 'cryptsetup open' "opens LUKS volume"
check_pattern "$MOUNT" 'SUDO_USER' "uses SUDO_USER for rootless Docker compatibility"
check_pattern "$MOUNT" 'chown.*REAL_USER' "chowns mount point to real user"
check_pattern "$MOUNT" 'chmod 700' "sets restrictive permissions after mount"
check_pattern "$MOUNT" 'mkdir -p.*signal.*grist' "creates signal and grist subdirectories"

echo ""
echo "=== unmount-encrypted-storage.sh ==="
UNMOUNT="$SCRIPT_DIR/unmount-encrypted-storage.sh"

check_pattern "$UNMOUNT" 'set -euo pipefail' "strict error handling (set -euo pipefail)"
check_pattern "$UNMOUNT" 'EUID -ne 0' "requires root"
check_pattern "$UNMOUNT" 'docker compose down' "stops Docker services before unmounting"
check_pattern "$UNMOUNT" 'umount' "unmounts the volume"
check_pattern "$UNMOUNT" 'cryptsetup close' "locks the LUKS volume"

echo ""
echo "=== Results ==="
echo "  $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
