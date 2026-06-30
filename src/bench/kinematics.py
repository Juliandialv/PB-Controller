"""Bench's kinematics functions"""

import src.bench.config as c

def angle_to_mm(angle_deg, axis):
    """
    Función que pasa de un ángulo en grados a distancia en mm
    para construir el gcode a enviar a la impresora.

    :param angle_deg: Angulo a convertir, tipo float.
    :param axis: Eje sobre el que se trabaja, tipo string.
    :return: Valor convertido a mm, tipo float.
    """

    if axis == 'base':
        d_mm = angle_deg * c.I_BASE * (1 / 360) * \
            c.STEPS_REV * c.MSTEPPING_BASE / c.STEPS_BASE_MM
    elif axis == 'brazo':
        d_mm = angle_deg * c.I_BRAZO * (1 / 360) * \
            c.STEPS_REV * c.MSTEPPING_BRAZO / c.STEPS_BRAZO_MM
    else:
        d_mm = False

    return d_mm


def mm_to_angle(d_mm, axis):
    """
    Función que pasa de un distancia en mm a un ángulo en grados

    :param d_mm: Distancia a convertir, tipo float.
    :param axis: Eje sobre el que se trabaja, tipo string.
    :return: Valor convertido a grados, tipo float.
    """

    if axis == 'base':
        angle_deg = d_mm * 1/(c.I_BASE * (1 / 360) * \
            c.STEPS_REV * c.MSTEPPING_BASE / c.STEPS_BASE_MM)
    elif axis == 'brazo':
        angle_deg = d_mm * 1/(c.I_BRAZO * (1 / 360) * \
            c.STEPS_REV * c.MSTEPPING_BRAZO / c.STEPS_BRAZO_MM)
    else:
        angle_deg = False

    return angle_deg
