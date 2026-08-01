"""ESP32 Flasher — Kern und Oberfläche.

scanner          Projektordner nach flashbaren Images durchsuchen
ports            serielle Ports finden, Adapter erkennen, Port freigeben
esptool_runner   esptool in-process ausführen, Ausgabe umleiten
settings         Einstellungen laden/speichern (validiert)
theme            Farbpaletten und Systemmodus
ui.widgets       themefähige Bausteine
ui.app           das Fenster
"""

__version__ = "1.0.0"
