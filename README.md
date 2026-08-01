# ESP32 Flasher

Firmware auf ESP32-Boards schreiben, ohne esptool-Kommandozeilen zu tippen.
Projektordner auswählen — der Scanner findet selbst heraus, welche Dateien an
welche Flash-Adressen gehören. Alternativ direkt eine `.bin` wählen.

Läuft auf macOS und Windows. Hell- und Dunkelmodus folgen der
Systemeinstellung, umschaltbar oben rechts.

## Starten

```bash
pip install -r requirements.txt
python3 flasher.py
```

## Eigenständige App bauen

macOS — Ergebnis `dist/ESP32 Flasher.app`, läuft ohne Python-Installation:

```bash
pip install pyinstaller && ./build_app.sh
```

Beim ersten Start Rechtsklick → „Öffnen" (unsignierte App).

Windows — Ergebnis `dist\ESP32 Flasher\ESP32 Flasher.exe`:

```bash
pip install pyinstaller -r requirements.txt && pyinstaller --noconfirm --clean --windowed --name "ESP32 Flasher" --icon assets\icon.ico --collect-data esptool --hidden-import serial.tools.list_ports flasher.py
```

## Was der Scanner erkennt

Der beste Kandidat wird vorgeschlagen, alle anderen stehen im Dropdown.

| Prio | Quelle | Adresse |
|---|---|---|
| 1 | `flasher.json` im Projekt | laut Manifest |
| 2 | `factory.bin` / `*merged*.bin` | `0x0` |
| 3 | Build-Ordner (PlatformIO, Arduino, ESP-IDF) | Bootloader, Partitionen, App |
| 4 | einzelne `.bin` | `0x10000` |

Ein Manifest ist nur nötig, wenn ein Projekt mehrere Varianten hat oder ein
Dateisystem-Image dazugehört:

```json
{
  "name": "Mein Projekt",
  "chip": "esp32",
  "flash_size": "4MB",
  "parts": [
    { "offset": "0x1000",  "file": ".pio/build/esp32dev/bootloader.bin" },
    { "offset": "0x8000",  "file": ".pio/build/esp32dev/partitions.bin" },
    { "offset": "0x10000", "file": ".pio/build/esp32dev/firmware.bin" }
  ]
}
```

Pfade sind relativ zum Manifest und dürfen den Projektordner nicht verlassen.

## Bedienelemente

| | |
|---|---|
| **Firmware flashen** | schreibt den gewählten Kandidaten bzw. die `.bin` |
| **Flash löschen** | kompletter Chip-Erase, mit Rückfrage |
| **Gerät prüfen** | Chip, MAC und Flash-Größe auslesen |
| **Boot-Check** | 15 s mithören und den Bootzustand einordnen |
| **Reset** | Reset-Puls über DTR/RTS |
| **Exportieren** | Kandidat zu einer `factory.bin` ab `0x0` zusammenführen |
| **Port freigeben** | Prozess beenden, der den seriellen Port blockiert |

**Ohne Auto-Reset** ankreuzen bei Boards wie dem WT32-ETH01, die keinen
Auto-Reset haben: IO0 auf GND brücken, Reset auslösen, Brücke während des
Uploads stecken lassen. Hilft der Boot-Check nicht weiter, liegt es meist an
der Stromversorgung oder an vertauschtem TX/RX.

## Kommandozeile

```bash
python3 flasher.py --scan /pfad/zum/projekt
```

Zeigt, was der Scanner finden würde — praktisch zum Prüfen eines Manifests.

## Aufbau

```
flasher.py          Einstiegspunkt
esp32flasher/       scanner, ports, esptool_runner, settings, theme
esp32flasher/ui/    widgets, app
```

Kern und Oberfläche sind getrennt: `scanner`, `ports`, `esptool_runner` und
`settings` kennen kein Tkinter.

## Lizenz

MIT
