"""Bench's main mechanical parameters"""

# ── Stepper motors ───────────────────────────────────────────────────────────
D_POLEA = 15.92
STEPS_REV = 200
I_BASE = 4
I_BRAZO = 3.6
MSTEPPING_BASE = 16
MSTEPPING_BRAZO = 8
STEPS_BASE_MM = (STEPS_REV * MSTEPPING_BASE)/D_POLEA
STEPS_BRAZO_MM = (STEPS_REV * MSTEPPING_BRAZO)/D_POLEA
