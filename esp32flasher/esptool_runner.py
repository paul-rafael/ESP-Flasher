"""esptool ausführen und seine Ausgabe zeilenweise weiterreichen.

In-process statt subprocess, weil es in der fertigen PyInstaller-App weder
python3 noch ein esptool-Skript gibt. Dafür muss sys.stdout getauscht werden,
und das ist prozessweit — daher das Lock in run().
"""

import sys
import threading

try:
    import esptool
except ImportError:
    esptool = None

_stdout_lock = threading.Lock()


def parse_percent(line):
    """Prozentwert aus Zeilen wie "Writing at 0x10000... (37 %)"."""
    if "%" not in line:
        return None
    try:
        fragment = line.split("(")[-1].split("%")[0].strip()
    except IndexError:
        return None
    try:
        return max(0, min(100, int(fragment)))
    except ValueError:
        return None


class QueueWriter:
    """esptool beendet Fortschrittszeilen mit CR statt LF — hier zählt beides
    als Zeilenende."""

    def __init__(self, on_line):
        self._on_line = on_line
        self._buffer = ""

    def write(self, text):
        self._buffer += text
        while True:
            index = min((i for i in (self._buffer.find("\r"), self._buffer.find("\n"))
                         if i >= 0), default=-1)
            if index < 0:
                break
            line, self._buffer = self._buffer[:index], self._buffer[index + 1:]
            if line.strip():
                self._on_line(line)
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False

    def close(self):
        if self._buffer.strip():
            self._on_line(self._buffer)
        self._buffer = ""


def run(args, on_line):
    """esptool ausführen, jede Ausgabezeile an on_line. -> Rückgabecode.

    Wirft nie: Fehler landen als Logzeile und ergeben Code 1.
    """
    if esptool is None:
        on_line("esptool ist nicht installiert.")
        return 1

    writer = QueueWriter(on_line)
    with _stdout_lock:
        original_out, original_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = writer
        try:
            esptool.main(args)
            return 0
        except SystemExit as exit_signal:
            code = exit_signal.code
            if code is None:
                return 0
            return code if isinstance(code, int) else 1
        except Exception as error:  # noqa: BLE001 - jeder Fehler gehört ins Log
            on_line(f"Fehler: {error}")
            return 1
        finally:
            writer.close()
            sys.stdout, sys.stderr = original_out, original_err
