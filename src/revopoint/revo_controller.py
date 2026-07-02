"""
RevoController
==============
Wrapper Python que controla PB-Revo.exe mediante pipes stdin/stdout.

El exe usa stderr para sus logs internos → stdout queda limpio para
el protocolo de texto.

Protocolo
---------
Python  →  C++             C++  →  Python
SET_DIR <ruta>    →        DIR_OK <ruta>
CAPTURE           →        CAPTURING  ...  CAPTURED <ruta.ply>
CAPTURE N         →        (N veces lo anterior)
STATUS            →        READY
QUIT              →        BYE

Cualquier error del lado C++ llega como:   ERROR <motivo>
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time


# ──────────────────────────────────────────────────────────────────────────────
# Excepciones propias
# ──────────────────────────────────────────────────────────────────────────────

class RevoTimeoutError(TimeoutError):
    """Timeout esperando respuesta del proceso C++."""


class RevoError(RuntimeError):
    """El proceso C++ reportó un error."""


# ──────────────────────────────────────────────────────────────────────────────
# Clase principal
# ──────────────────────────────────────────────────────────────────────────────

class RevoController:

    def __init__(
        self,
        exe_path: str,
        dll_dirs: list[str] | None = None,
        stderr_to_console: bool = True,
    ):
        """
        :param exe_path:          Ruta al ejecutable compilado (REVO_CA.exe).
        :param stderr_to_console: Si True, los logs internos del C++ se
                                  imprimen en consola con prefijo [REVO].
                                  Útil durante desarrollo; poner a False
                                  en producción para no ensuciar la salida.
        """
        self._exe_path         = str(exe_path)
        self._dll_dirs = dll_dirs or []
        self._stderr_to_console = stderr_to_console

        self._proc:          subprocess.Popen | None = None
        self._stdout_q:      queue.Queue[str]        = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    # ──────────────────────────────────────────────────────────────────────────
    # Arranque / parada
    # ──────────────────────────────────────────────────────────────────────────

    def start(self, timeout: float = 30.0) -> None:
        """
        Lanza el ejecutable C++ y espera a que emita READY (señal de que
        la cámara se ha inicializado y el loop de comandos está activo).

        :param timeout: Segundos máximos para la inicialización de la cámara.
        :raises FileNotFoundError: Si el exe no existe en la ruta indicada.
        :raises RevoTimeoutError:  Si la cámara no responde en `timeout` s.
        """
        if self._proc is not None:
            raise RuntimeError("RevoController ya está en marcha.")

        if not os.path.isfile(self._exe_path):
            raise FileNotFoundError(
                f"Ejecutable no encontrado: {self._exe_path}"
            )

        env = os.environ.copy()

        if self._dll_dirs:
            env["PATH"] = (
                os.pathsep.join(self._dll_dirs)
                + os.pathsep
                + env["PATH"]
            )

        self._proc = subprocess.Popen(
            [self._exe_path],
            cwd=os.path.dirname(self._exe_path),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        time.sleep(0.5)

        # Hilo lector de stdout (protocolo)
        self._reader_thread = threading.Thread(
            target=self._read_stdout, daemon=True
        )
        self._reader_thread.start()

        # Hilo lector de stderr (logs del C++, opcional en consola)
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, daemon=True
        )
        self._stderr_thread.start()

        time.sleep(0.5)
        self._wait_for("READY", timeout=timeout)

    def stop(self) -> None:
        """Envía QUIT al proceso C++ y espera a que termine limpiamente."""
        if self._proc is None:
            return

        try:
            self._send("QUIT")
            self._wait_for("BYE", timeout=5.0)
        except Exception:
            pass        # si ya está muerto o en timeout, no importa
        finally:
            self._proc.stdin.close()
            self._proc.wait(timeout=5)
            self._proc = None
            print("[RevoController] Proceso detenido.")

    # ──────────────────────────────────────────────────────────────────────────
    # API pública de captura
    # ──────────────────────────────────────────────────────────────────────────

    def set_session_dir(self, path: str, timeout: float = 5.0) -> None:
        """
        Indica al exe C++ la carpeta donde debe guardar los PLY de esta
        sesión. El C++ la crea si no existe.

        :param path:    Ruta absoluta de la carpeta de sesión.
        :param timeout: Segundos máximos para la confirmación.
        :raises RevoError: Si el C++ responde con ERROR.
        """
        self._send(f"SET_DIR {path}")
        line = self._wait_for_prefix("DIR_OK", timeout=timeout)
        confirmed = line.split(" ", 1)[1].strip()
        print(f"[RevoController] Directorio de sesión: {confirmed}")

    def capture(
        self,
        n: int = 1,
        timeout_per_frame: float = 15.0,
    ) -> list[str]:
        """
        Ordena al C++ capturar n frames y espera hasta que todos estén
        guardados en disco.

        :param n:                 Número de frames a capturar.
        :param timeout_per_frame: Timeout por frame en segundos.
        :return:                  Lista de rutas a los PLY guardados,
                                  en el mismo orden de captura.
        :raises RevoError:        Si el C++ reporta un error durante la captura.
        :raises RevoTimeoutError: Si algún frame supera el timeout.
        """
        if self._proc is None:
            raise RuntimeError("RevoController no está iniciado. Llama a start() primero.")

        cmd = "CAPTURE" if n == 1 else f"CAPTURE {n}"
        self._send(cmd)

        paths: list[str] = []
        for i in range(n):
            # Esperar señal de disparo (soft trigger enviado)
            self._wait_for("CAPTURING", timeout=timeout_per_frame)
            # Esperar confirmación de escritura en disco
            line = self._wait_for_prefix("CAPTURED", timeout=timeout_per_frame)
            ply_path = line.split(" ", 1)[1].strip()
            paths.append(ply_path)
            print(f"[RevoController] Frame {i+1}/{n} → {ply_path}")

        return paths

    def status(self, timeout: float = 5.0) -> bool:
        """
        Comprueba si el proceso C++ responde. Devuelve True si está listo,
        False si no responde en `timeout` segundos.
        """
        if self._proc is None:
            return False
        try:
            self._send("STATUS")
            self._wait_for("READY", timeout=timeout)
            return True
        except RevoTimeoutError:
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Comunicación de bajo nivel (interna)
    # ──────────────────────────────────────────────────────────────────────────

    def _send(self, command: str) -> None:
        """Escribe una línea de comando en stdin del proceso C++."""
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Proceso no disponible.")
        self._proc.stdin.write(command + "\n")
        self._proc.stdin.flush()

    def _wait_for(self, expected: str, timeout: float) -> str:
        """
        Bloquea hasta recibir una línea que sea exactamente `expected`.
        Descarta silenciosamente cualquier otra línea que llegue antes.
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RevoTimeoutError(
                    f"Timeout esperando '{expected}' del proceso C++."
                )
            try:
                line = self._stdout_q.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue

            if line == expected:
                return line
            if line.startswith("ERROR"):
                raise RevoError(f"C++ reportó: {line}")
            # cualquier otra línea: ignorar y seguir esperando

    def _wait_for_prefix(self, prefix: str, timeout: float) -> str:
        """
        Bloquea hasta recibir una línea que empiece por `prefix`.
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RevoTimeoutError(
                    f"Timeout esperando prefijo '{prefix}' del proceso C++."
                )
            try:
                line = self._stdout_q.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue

            if line.startswith(prefix):
                return line
            if line.startswith("ERROR"):
                raise RevoError(f"C++ reportó: {line}")

    def _read_stdout(self) -> None:
        """
        Hilo permanente: lee líneas de stdout del proceso C++ y las
        encola en _stdout_q para que los métodos de espera las consuman.
        """
        try:
            for raw_line in self._proc.stdout:
                clean = raw_line.rstrip("\r\n")

                if clean:
                    self._stdout_q.put(clean)

        except Exception as e:
            print("STDOUT THREAD:", e)

    def _read_stderr(self) -> None:
        """
        Hilo permanente: lee stderr del proceso C++ (logs internos).
        Si stderr_to_console=True los imprime con prefijo [REVO].
        """
        try:
            for raw_line in self._proc.stderr:
                if self._stderr_to_console:
                    print(f"[REVO] {raw_line.rstrip()}")
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # Context manager
    # ──────────────────────────────────────────────────────────────────────────

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()
