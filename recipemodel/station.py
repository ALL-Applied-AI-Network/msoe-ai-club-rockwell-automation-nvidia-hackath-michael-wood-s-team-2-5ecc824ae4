"""Station 3 facts used by the recipe model (official Dataset 2 page and video-5 labels).

* Tanks in the labeled collection: t100 clear, t200 orange, t400 blue. t300 unused.
  Tank colors can change in general; labels are not live tank sensors.
* Dispense order is T200 > T400 > T100, skipping unused tanks.
* Operating limits: total <= 80 mL, each used component >= 10 mL, t200 <= 50 mL, no t300.
"""

TANKS = ("t100", "t200", "t400")
DISPENSE_ORDER = ("t200", "t400", "t100")
TANK_LABELS = {"t100": "clear", "t200": "orange", "t400": "blue"}

MAX_TOTAL_ML = 80.0
MIN_COMPONENT_ML = 10.0
MAX_T200_ML = 50.0


def dispense_order(volumes_ml):
    """Tanks actually used, in dispense order, e.g. ['t400', 't100']."""
    return [t for t in DISPENSE_ORDER if (volumes_ml.get(t) or 0) > 0]


def dispense_order_string(volumes_ml):
    """Label-file style string, e.g. 'T400>T100'."""
    return ">".join(t.upper() for t in dispense_order(volumes_ml))


def limit_violations(volumes_ml, t300_ml=0.0):
    """Official operating-limit violations for a recipe (empty list = within limits)."""
    used = {t: v for t, v in volumes_ml.items() if (v or 0) > 0}
    problems = []
    if t300_ml and t300_ml > 0:
        problems.append("t300 must not be used")
    total = sum(used.values())
    if total > MAX_TOTAL_ML:
        problems.append(f"total {total:g} mL > {MAX_TOTAL_ML:g} mL")
    for t, v in used.items():
        if v < MIN_COMPONENT_ML:
            problems.append(f"{t} {v:g} mL < {MIN_COMPONENT_ML:g} mL minimum")
    if (volumes_ml.get("t200") or 0) > MAX_T200_ML:
        problems.append(f"t200 {volumes_ml['t200']:g} mL > {MAX_T200_ML:g} mL")
    return problems
