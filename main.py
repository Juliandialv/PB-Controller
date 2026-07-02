"""
main.py — Rutina de calibración de alineación (dos pasadas)
============================================================
Pasada groser:  paso 1°   en [theta_centro-5, theta_centro+5]
Pasada fina:    paso 0.1° en [theta_opt-1,    theta_opt+1]
"""

import datetime
import matplotlib.pyplot as plt
from pathlib import Path

from src.bench.bench_controller    import BenchController
from src.revopoint.revo_controller import RevoController
from src.analysis.plane_fit        import analyse_calibration_pass

# ──────────────────────────────────────────────────────────────────────────────
# RUTAS
# ──────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent

REVO_EXE = (
    ROOT.parent
    / "PB-Revo"
    / "build"
    / "Desktop_Qt_6_11_0_MSVC2022_64bit-Release"
    / "release"
    / "PB-Revo.exe"
)

QT_DLLS      = r"C:\Qt\6.11.0\msvc2022_64\bin"
SDK_3DCAMERA = r"D:\Proyectos\Revopoint\00_LIBS\3DCameraSDK-v3.2.229.20251110\lib\3dcamera\windows\x64\Release"
SDK_HANDEYE  = r"D:\Proyectos\Revopoint\00_LIBS\3DCameraSDK-v3.2.229.20251110\lib\handEye\windows\x64\Release"
SDK_DLLS     = [QT_DLLS, SDK_3DCAMERA, SDK_HANDEYE]

DATA_DIR = ROOT / "data"

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

EXPERIMENTO    = "CALIB_ALINEACION"
STANDOFF_MM    = 300
N_CAPTURAS     = 1          # frames por posición (se promedian puntos)

PHI_FIJO       = 90
THETA_CENTRO   = 130.0      # estimación inicial del ángulo óptimo

PASO_GRUESO    = 1.0
RANGO_GRUESO   = 2.0        # ± grados alrededor de THETA_CENTRO

PASO_FINO      = 0.1
RANGO_FINO     = 0.5        # ± grados alrededor del óptimo grueso

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def make_session_dir(tag: str) -> Path:
    ts   = datetime.datetime.now().strftime("%d%m%Y_%H%M%S")
    name = f"{EXPERIMENTO}_d{STANDOFF_MM:03d}mm_{ts}_{tag}"
    path = DATA_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def angular_range(centro: float, rango: float, paso: float) -> list[float]:
    ini, fin = centro - rango, centro + rango
    values, v = [], ini
    while v <= fin + 1e-9:
        values.append(round(v, 6))
        v = round(v + paso, 6)
    return values


# ──────────────────────────────────────────────────────────────────────────────
# BARRIDO: captura + análisis de una pasada
# ──────────────────────────────────────────────────────────────────────────────

def barrido(
    bench: BenchController,
    revo:  RevoController,
    thetas: list[float],
    session_tag: str,
    pass_name: str,
    fig1, ax1_container: list,
    fig2, ax2_container: list,
) -> tuple[float, float]:
    """
    Mueve el banco por cada theta, captura N_CAPTURAS PLY y analiza en caliente.

    :return: (theta_opt, cross_opt)
    """
    session_dir = make_session_dir(session_tag)
    print(f"\n[{pass_name}] Directorio: {session_dir.name}")
    print(f"[{pass_name}] φ={PHI_FIJO}°  |  θ: {thetas[0]}° → {thetas[-1]}°  |  {N_CAPTURAS} cap/pos\n")
    revo.set_session_dir(str(session_dir))

    # Mover a la posición inicial
    bench.go_to(PHI_FIJO, thetas[0])

    ply_groups: list[list[str]] = []

    for i, theta in enumerate(thetas):
        if i > 0:
            bench.go_to(PHI_FIJO, theta)

        print(f"  [{i+1}/{len(thetas)}] θ = {theta}°  →  capturando {N_CAPTURAS} frames...")
        rutas = revo.capture(n=N_CAPTURAS)
        ply_groups.append(rutas)

    # Análisis con plot en tiempo real
    theta_opt, cross_opt = analyse_calibration_pass(
        ply_groups, thetas, pass_name,
        phi=PHI_FIJO,
        fig1=fig1, ax1_container=ax1_container,
        fig2=fig2, ax2_container=ax2_container,
    )

    return theta_opt, cross_opt


# ──────────────────────────────────────────────────────────────────────────────
# RUTINA PRINCIPAL (dos pasadas)
# ──────────────────────────────────────────────────────────────────────────────

def rutina_calibracion(bench: BenchController, revo: RevoController) -> None:

    # Crear figuras una sola vez — se reutilizan en ambas pasadas
    plt.style.use('seaborn-v0_8-paper')
    fig1 = plt.figure(1)
    fig1.canvas.manager.window.wm_geometry("+100+600")
    fig1.canvas.manager.set_window_title("Calibration Info. 1")
    ax1_container = [None]

    fig2 = plt.figure(2)
    fig2.canvas.manager.window.wm_geometry("+1100+600")
    fig2.canvas.manager.set_window_title("Calibration Info. 2")
    ax2_container = [None]

    bench.home_axis()

    # ── Pasada groser ─────────────────────────────────────────────────────────
    thetas_grueso = angular_range(THETA_CENTRO, RANGO_GRUESO, PASO_GRUESO)
    theta_opt_1, cross_opt_1 = barrido(
        bench, revo, thetas_grueso,
        session_tag   = "grueso",
        pass_name     = "Pasada groser",
        fig1=fig1, ax1_container=ax1_container,
        fig2=fig2, ax2_container=ax2_container,
    )
    print(f"\n[Pasada grosera] Resultado:  θ = {theta_opt_1}°  |  cross = {cross_opt_1:.5f}")

    # ── Pasada fina ───────────────────────────────────────────────────────────
    thetas_fino = angular_range(theta_opt_1, RANGO_FINO, PASO_FINO)

    # Resetear ejes para la segunda pasada
    if ax1_container[0] is not None:
        ax1_container[0].remove()
        ax1_container[0] = None
    if ax2_container[0] is not None:
        ax2_container[0].remove()
        ax2_container[0] = None

    theta_opt_2, cross_opt_2 = barrido(
        bench, revo, thetas_fino,
        session_tag   = "fino",
        pass_name     = "Pasada fina",
        fig1=fig1, ax1_container=ax1_container,
        fig2=fig2, ax2_container=ax2_container,
    )

    bench.home_axis()

    # ── Resultado final ───────────────────────────────────────────────────────
    print("\n" + "═" * 52)
    print(f"  CALIBRACIÓN FINALIZADA")
    print(f"  φ = {PHI_FIJO}°   θ = {theta_opt_2}°")
    print(f"  Producto vectorial: {cross_opt_2:.5f}")
    print("═" * 52)

    plt.show(block=True)   # mantener las figuras abiertas al terminar


# ──────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    bench = BenchController()
    #revo  = RevoController(str(REVO_EXE), dll_dirs=SDK_DLLS, stderr_to_console=True)

    try:
        #revo.start(timeout=120)
        #rutina_calibracion(bench, revo)
        bench.home_axis()
        #bench.go_to(90, 128.8)

    finally:
        #revo.stop()
        bench.close()
