#!/bin/bash
# Baut die eigenständige macOS-App: dist/ESP32 Flasher.app
# Voraussetzung: pip install pyinstaller  (einmalig)
set -e
cd "$(dirname "$0")"

python3 -m PyInstaller --noconfirm --clean --windowed \
  --name "ESP32 Flasher" \
  --icon assets/icon.icns \
  --osx-bundle-identifier de.rafuelo.esp32flasher \
  --collect-data esptool \
  --hidden-import serial.tools.list_ports \
  flasher.py

# Finder/Dock cachen Icons aggressiv — Zeitstempel anfassen, damit das neue
# Icon sofort erscheint.
touch "dist/ESP32 Flasher.app"

echo ""
echo "Fertig: dist/ESP32 Flasher.app"
echo "Erster Start: Rechtsklick -> Oeffnen (unsignierte App)."
