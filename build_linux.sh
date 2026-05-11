#!/usr/bin/env bash
# Build VaultPass as a single-file Linux executable using PyInstaller.
#
# Requirements (install once):
#   sudo apt install python3 python3-pip python3-tk xdotool
#
# Then run:
#   chmod +x build_linux.sh
#   ./build_linux.sh
#
# Output: dist/VaultPass  (standalone binary, no Python required)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Installing Python dependencies..."
pip3 install -r requirements.txt pyinstaller --quiet

echo "==> Building VaultPass..."
python3 -m PyInstaller \
    --onefile \
    --noconsole \
    --name VaultPass \
    --clean \
    main.py

echo ""
echo "Done! Binary is at: dist/VaultPass"
echo ""
echo "To run:"
echo "  ./dist/VaultPass"
echo ""
echo "NOTE: The vault file (!vault.vpm) will be created next to the binary."
echo "NOTE: Autofill (▶ Fill) requires xdotool:  sudo apt install xdotool"
