"""Duet serial commands manager"""

from __future__ import annotations

import threading
import time
import json
import serial
from serial.tools import list_ports


class DuetTimeoutError(TimeoutError):
    """Timeout en comunicación con la Duet."""


class DuetTransport:

    DUET_VID = 0x1D50

    DUET_PIDS = {
        0x60EE,
        0x60EC,
    }

    def __init__(
        self,
        port: str | None = None,
        baudrate: int = 115200,
        serial_timeout: float = 0.1,
    ):
        self._port = port
        self._baudrate = baudrate
        self._serial_timeout = serial_timeout

        self._serial: serial.Serial | None = None
        self._lock = threading.Lock()

        # 🔥 buffer único de entrada
        self._buffer: list[str] = []

        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # CONNECT
    # ------------------------------------------------------------------

    def connect(self) -> None:

        if self.is_connected:
            return

        if self._port is None:
            self._port = self.find_duet_port()

        self._serial = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            timeout=self._serial_timeout,
        )

        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()

        self._stop_event.clear()

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            daemon=True
        )
        self._reader_thread.start()

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def close(self) -> None:

        self._stop_event.set()

        if self._serial:
            self._serial.close()
            self._serial = None

    # ------------------------------------------------------------------
    # READER (ÚNICO PUNTO DE LECTURA)
    # ------------------------------------------------------------------

    def _reader_loop(self):

        while not self._stop_event.is_set() and self.is_connected:

            try:
                line = self._serial.readline()
            except Exception:
                continue

            if not line:
                continue

            decoded = line.decode("utf-8", errors="ignore").strip()

            with self._lock:
                self._buffer.append(decoded)

    def _get_line(self):

        with self._lock:
            if self._buffer:
                return self._buffer.pop(0)

        return None

    # ------------------------------------------------------------------
    # SEND
    # ------------------------------------------------------------------

    def send_line(self, command: str) -> None:

        if not self.is_connected:
            raise RuntimeError("No conectado")

        if not command.endswith("\n"):
            command += "\n"

        with self._lock:
            self._serial.write(command.encode("utf-8"))
            self._serial.flush()

    # ------------------------------------------------------------------
    # EXECUTE (SYNC POR OK)
    # ------------------------------------------------------------------

    def execute(self, command: str, timeout: float = 50.0):

        if not self.is_connected:
            raise RuntimeError("No conectado")

        if not command.endswith("\n"):
            command += "\n"

        with self._lock:

            # 🔥 limpiar SOLO buffer lógico, NO serial
            self._buffer.clear()

            self._serial.write(command.encode())
            self._serial.flush()

        expected_ok = len([c for c in command.splitlines() if c.strip()])

        return self._wait_for_ok(expected_ok, timeout)

    def _wait_for_ok(self, expected_ok: int, timeout: float):

        start = time.monotonic()
        oks = 0
        lines = []

        while True:

            if time.monotonic() - start > timeout:
                raise DuetTimeoutError("Timeout esperando ok")

            line = self._get_line()

            if line is None:
                time.sleep(0.001)
                continue

            lines.append(line)

            if line == "ok":
                oks += 1
                if oks >= expected_ok:
                    return lines

    # ------------------------------------------------------------------
    # M409 (SIN SERIAL DIRECTO)
    # ------------------------------------------------------------------

    def get_object_model_raw(self, key: str) -> dict:

        if not self.is_connected:
            raise RuntimeError("No conectado")

        with self._lock:

            self._buffer.clear()

            self._serial.write(f'M409 K"{key}"\n'.encode())
            self._serial.flush()

        start = time.monotonic()

        while True:

            if time.monotonic() - start > 5:
                raise TimeoutError("No JSON recibido")

            line = self._get_line()

            if line is None:
                time.sleep(0.001)
                continue

            if line.startswith("{"):
                return json.loads(line)

    def get_object_model(self, key: str):
        return self.get_object_model_raw(key)["result"]

    # ------------------------------------------------------------------
    # IDLE WAIT
    # ------------------------------------------------------------------

    def wait_until_idle(self, timeout=30):

        start = time.monotonic()

        while True:

            if time.monotonic() - start > timeout:
                raise TimeoutError("No se alcanzó idle")

            status = self.get_object_model("state.status")

            if status == "idle":
                return

            time.sleep(0.1)

    # ------------------------------------------------------------------
    # UTIL
    # ------------------------------------------------------------------

    @classmethod
    def find_duet_port(cls) -> str:

        for port in list_ports.comports():

            if port.vid == cls.DUET_VID and port.pid in cls.DUET_PIDS:
                return port.device

            if "duet" in (port.description or "").lower():
                return port.device

        raise RuntimeError("Duet no encontrada")

    # ------------------------------------------------------------------
    # CONTEXT MANAGER
    # ------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
