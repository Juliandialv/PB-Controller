"""Bench Controller Class definition with useful methods"""

from src.bench.duet_transport import DuetTransport
from src.bench.kinematics import (angle_to_mm, mm_to_angle)
import time

class BenchController:
    # Constructor
    def __init__(self):

        self.duet = DuetTransport()
        self.duet.connect()

        self.board_name = self.duet.get_object_model("boards[0].name")
        self.unique_id = self.duet.get_object_model("boards[0].uniqueId")

        time.sleep(0.2)

        print(
            f"[DUET3d] Successfully connected to "
            f"{self.board_name} - {self.unique_id}"
        )

    def go_to(self, phi_deg: float, theta_deg: float):
        """
        Función que envía a la Duet las posiciones deseadas para cada uno de 
        los dos ejes y espera a que esta responda onforme se han alcanzado.

        :param self: clase con la que se trabaja
        :param phi_deg: Ángulo en grados deseado para la base.
        :param theta_deg: Ángulo en grados deseado para el brazo.
        """

        print("[DUET3d] Moving...")

        x = angle_to_mm(phi_deg, "base")
        y = angle_to_mm(theta_deg, "brazo")

        command = (
            f"G1 X{x:.3f} Y{y:.3f}\n"
            "G4 P1000\n"
            "M400"
        )

        self.duet.execute(command)
        print(f"[DUET3d] Position ({phi_deg}, {theta_deg}) reached")

    def home_axis(self):
        """Homing test bench axis"""
        print("[DUET3d] Homing axis...")
        self.duet.execute('G28 XYZ G4 P1000')
        self.duet.wait_until_idle()
        print("[DUET3D] Axis homed successfully")

    def close(self):
        """Closing communication with Duet board"""
        self.duet.close()
