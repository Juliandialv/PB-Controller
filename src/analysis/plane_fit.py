"""
plane_fit.py — Ajuste de plano y análisis de alineación (Revopoint Inspire 2)
==============================================================================
Replica la lógica de calibración del sistema TrueDepth adaptada al Revopoint.

Diferencias respecto al sistema iPhone:
  · Las nubes llegan como ficheros PLY en disco (no como frames en streaming).
  · El cono de visión del Revopoint tiene su origen desplazado +50 mm en X
    respecto al origen del sensor → se restan 50 mm en X antes de cualquier
    operación.
  · Recorte de ROI cuadrado de 150 mm de lado (±75 mm en X e Y).

Métrica de alineación
---------------------
  cross = ‖ N_plano × N_sensor ‖
  N_sensor = [0, 0, 1]  (eje Z apunta hacia el objeto)
  Mínimo de cross → máxima alineación entre plano y sensor.

Rutina en dos pasadas
---------------------
  1ª pasada (groser):  paso 1°  en rango [theta_centro-5, theta_centro+5]
  2ª pasada (fina):    paso 0.1° en rango [theta_opt-1,   theta_opt+1]

Dependencias: numpy, scipy, open3d, matplotlib
"""

from __future__ import annotations

import copy
import numpy as np
import scipy.linalg
import matplotlib
import matplotlib.pyplot as plt
from pathlib import Path

matplotlib.use("TkAgg")

# ──────────────────────────────────────────────────────────────────────────────
# Constantes físicas del sensor
# ──────────────────────────────────────────────────────────────────────────────

X_OFFSET_MM   =  50.0
ROI_HALF_SIDE =  50.0
N_SENSOR      = np.array([0.0, 0.0, 1.0])


# ──────────────────────────────────────────────────────────────────────────────
# Carga, preprocesado y guardado de ROI
# ──────────────────────────────────────────────────────────────────────────────

def load_and_preprocess(
    ply_path: str | Path,
    phi: float | None = None,
    theta: float | None = None,
) -> np.ndarray:
    """
    Carga un PLY, corrige el offset X del Revopoint, recorta la ROI
    y guarda la nube resultante con la codificación de posición en el nombre:
      <nombre_original>_phiXXX.X_thetaXXX.X_roi.ply

    :param phi:   Ángulo φ de la posición de captura (base), opcional.
    :param theta: Ángulo θ de la posición de captura (brazo), opcional.
    :return:      Array (N, 3) con los puntos dentro de la ROI, en mm.
    """
    try:
        import open3d as o3d
    except ImportError:
        raise ImportError("Instala open3d:  pip install open3d")

    ply_path = Path(ply_path)
    pcd      = o3d.io.read_point_cloud(str(ply_path))
    points   = np.asarray(pcd.points, dtype=float)

    if len(points) == 0:
        raise ValueError(f"Nube vacía: {ply_path}")

    # Corrección del desfase del cono de visión
    points[:, 0] -= X_OFFSET_MM

    # Recorte de ROI cuadrado y Z > 0
    mask = (
        (points[:, 0] > -ROI_HALF_SIDE) & (points[:, 0] < ROI_HALF_SIDE) &
        (points[:, 1] > -ROI_HALF_SIDE) & (points[:, 1] < ROI_HALF_SIDE) &
        (points[:, 2] > 0)
    )
    roi_points = points[mask]

    # Guardar nube ROI corregida junto al PLY original
    pos_tag = ""
    if phi   is not None: pos_tag += f"_phi{phi:06.2f}"
    if theta is not None: pos_tag += f"_theta{theta:06.2f}"
    roi_name = ply_path.stem + pos_tag + "_roi.ply"

    pcd_roi  = o3d.geometry.PointCloud()
    pcd_roi.points = o3d.utility.Vector3dVector(roi_points)
    o3d.io.write_point_cloud(str(ply_path.parent / roi_name), pcd_roi)

    return roi_points


# ──────────────────────────────────────────────────────────────────────────────
# Ajuste de plano y métrica
# ──────────────────────────────────────────────────────────────────────────────

def fit_plane_lstsq(points: np.ndarray):
    """
    Ajusta el plano z = C[0]*x + C[1]*y + C[2] por mínimos cuadrados.
    Devuelve (C, xs, ys, Z) — coeficientes y malla para visualización 3D.
    """
    A = np.c_[points[:, 0], points[:, 1], np.ones(len(points))]
    C, _, _, _ = scipy.linalg.lstsq(A, points[:, 2])

    xs_vec = points[:, 0][::500].reshape(1, -1)
    ys_vec = points[:, 1][::500].reshape(1, -1)
    xs, ys = np.meshgrid(xs_vec, ys_vec)
    Z      = C[0] * xs + C[1] * ys + C[2]

    return C, xs, ys, Z


def plane_normal_and_cross(C: np.ndarray, Z_mean: float) -> tuple[np.ndarray, float]:
    """
    Calcula la normal al plano y el producto vectorial con N_sensor.
    Replica: Nplane = [C[0], C[1], -C[2]/mean(Z)]
    """
    Nplane      = np.array([C[0], C[1], -C[2] / Z_mean])
    Nplane_unit = Nplane / np.linalg.norm(Nplane)
    cross_norm  = float(np.linalg.norm(np.cross(Nplane, N_SENSOR)))
    return Nplane_unit, cross_norm


# ──────────────────────────────────────────────────────────────────────────────
# Plot en tiempo real — redibujado explícito sin plt.show/pause
# ──────────────────────────────────────────────────────────────────────────────

def _update_fig1(fig1, ax1_container: list, Nplane_unit, cross, theta,
                 label_extra: str = "") -> None:
    """Redibuja la figura 1 (vectores YZ) para la posición actual."""
    if ax1_container[0] is not None:
        ax1_container[0].remove()
    ax = fig1.add_subplot(111)
    ax1_container[0] = ax

    ax.grid(True)
    ax.quiver(0, 0, Nplane_unit[1], -Nplane_unit[2],
              color='g', scale=4.35, label='Normal al plano')
    ax.quiver(0, 0, N_SENSOR[1], -N_SENSOR[2],
              color='r', scale=4.35, label='Director sensor')
    ax.set_xlabel('Y', fontweight='bold')
    ax.set_ylabel('Z', fontweight='bold')
    ax.axis('equal'); ax.axis('tight')
    ax.set_xlim(-1.5, 1.5); ax.set_ylim(-1.5, 1.5)
    ax.legend(loc='upper left', fontsize=8)
    ax.text( 0.9, -1.3, f"PROD. VECT: {cross:.5f}",
             fontsize=9, fontweight='bold', ha='center', va='center',
             bbox=dict(facecolor='white', edgecolor='black', boxstyle='round'))
    ax.text(-1.0, -1.3, f"θ = {theta}°{label_extra}",
             fontsize=9, fontweight='bold', ha='center', va='center',
             bbox=dict(facecolor='yellow' if label_extra else 'lightyellow',
                       edgecolor='black', boxstyle='round'))

    # Redibujado explícito — no usa show/pause
    fig1.canvas.draw()
    fig1.canvas.flush_events()


def _update_fig2(fig2, ax2_container: list, xs, ys, Z,
                 title: str = "Plano de mejor ajuste",
                 color: str = "steelblue", alpha: float = 0.2) -> None:
    """Redibuja la figura 2 (superficie 3D del plano ajustado)."""
    if ax2_container[0] is not None:
        ax2_container[0].remove()
    ax = fig2.add_subplot(111, projection='3d')
    ax2_container[0] = ax

    ax.plot_surface(xs, ys, Z, rstride=10, cstride=10, alpha=alpha, color=color)
    ax.set_xlabel('X', fontweight='bold')
    ax.set_ylabel('Y', fontweight='bold')
    ax.set_zlabel('Z', fontweight='bold')
    fig2.suptitle(title, fontweight='bold')

    fig2.canvas.draw()
    fig2.canvas.flush_events()


# ──────────────────────────────────────────────────────────────────────────────
# Análisis de una pasada
# ──────────────────────────────────────────────────────────────────────────────

def run_pass(
    ply_groups: list[list[str | Path]],
    thetas: list[float],
    fig1, ax1_container: list,
    fig2, ax2_container: list,
    pass_name: str,
    phi: float | None = None,
) -> tuple[float, float]:
    """
    Ejecuta una pasada completa de calibración, actualizando los plots
    en tiempo real tras cada posición angular.

    :return: (theta_opt, cross_opt)
    """
    best_cross = np.inf
    best_theta = thetas[0]
    best_xs = best_ys = best_Z = None
    best_normal = np.array([0.0, 0.0, 1.0])

    for i, (theta, group) in enumerate(zip(thetas, ply_groups)):

        fig1.suptitle(f'{pass_name}  |  θ = {theta}°  [{i+1}/{len(thetas)}]',
                      fontweight='bold')

        # Cargar y concatenar nubes de esta posición
        clouds = [load_and_preprocess(p, phi=phi, theta=theta) for p in group]
        points = np.vstack([c for c in clouds if len(c) > 0])

        if len(points) < 10:
            print(f"  [Aviso] θ={theta}°: muy pocos puntos en ROI ({len(points)}), omitida.")
            continue

        C, xs, ys, Z = fit_plane_lstsq(points)
        Nplane_unit, cross = plane_normal_and_cross(C, float(np.mean(Z)))

        is_best = cross < best_cross
        if is_best:
            best_cross  = cross
            best_theta  = theta
            best_normal = Nplane_unit.copy()
            best_xs, best_ys, best_Z = copy.deepcopy(xs), copy.deepcopy(ys), copy.deepcopy(Z)

        # ── Actualizar figuras en tiempo real ─────────────────────────────────
        _update_fig1(fig1, ax1_container, Nplane_unit, cross, theta)
        _update_fig2(fig2, ax2_container, xs, ys, Z,
                     title=f"{pass_name}  |  θ = {theta}°")

        print(f"  [{i+1}/{len(thetas)}] θ={theta}°  cross={cross:.5f}"
              + ("  ← mejor hasta ahora" if is_best else ""))

    # ── Plot resumen de la pasada (posición óptima) ───────────────────────────
    fig1.suptitle(f'{pass_name} — COMPLETADA', fontweight='bold')
    _update_fig1(fig1, ax1_container, best_normal, best_cross, best_theta,
                 label_extra=" ← ÓPTIMO")

    if best_xs is not None:
        _update_fig2(fig2, ax2_container, best_xs, best_ys, best_Z,
                     title=f"Plano óptimo  θ = {best_theta}°",
                     color='green', alpha=0.4)

    print(f"\n  [{pass_name}] θ óptimo = {best_theta}°  |  cross = {best_cross:.5f}")
    return best_theta, best_cross


# ──────────────────────────────────────────────────────────────────────────────
# Función pública principal
# ──────────────────────────────────────────────────────────────────────────────

def analyse_calibration_pass(
    ply_groups: list[list[str | Path]],
    thetas: list[float],
    pass_name: str = "Pasada",
    phi: float | None = None,
    fig1=None, ax1_container: list | None = None,
    fig2=None, ax2_container: list | None = None,
) -> tuple[float, float]:
    """
    Analiza una pasada de calibración con actualización en tiempo real.
    Crea las figuras si no se pasan.

    :return: (theta_opt, cross_opt)
    """
    if fig1 is None:
        plt.style.use('seaborn-v0_8-paper')
        fig1 = plt.figure(1)
        try:
            fig1.canvas.manager.window.wm_geometry("+100+600")
            fig1.canvas.manager.set_window_title("Calibration Info. 1")
        except Exception:
            pass
        ax1_container = [None]

    if fig2 is None:
        fig2 = plt.figure(2)
        try:
            fig2.canvas.manager.window.wm_geometry("+1100+600")
            fig2.canvas.manager.set_window_title("Calibration Info. 2")
        except Exception:
            pass
        ax2_container = [None]

    # Asegurar que las ventanas están visibles antes de empezar
    plt.show(block=False)
    plt.pause(0.1)

    return run_pass(ply_groups, thetas, fig1, ax1_container, fig2, ax2_container, pass_name)
