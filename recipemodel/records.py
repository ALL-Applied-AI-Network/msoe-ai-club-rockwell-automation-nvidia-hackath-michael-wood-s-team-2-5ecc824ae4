"""Build `processdna.expected_color.v0` records (docs/interfaces.md, proposed).

Additive fields beyond the proposed example (cross-workstream; flagged in
docs/components/recipe-carryover.md): `vial_id`, `camera_zone`, `carryover`
(parameters), `value_lab`, and `hue_degrees`.

A record never contains a guessed color: missing tank colors or incomplete volumes
give value=None and quality.ok=False with a code.
"""
import math

from .carryover import CARRYOVER_MODELS, residue_absorbance
from .colors import srgb_to_lab
from .mixing import MIXING_MODEL, expected_rgb, used_tanks
from .station import TANK_LABELS, TANKS, dispense_order_string, limit_violations

SCHEMA = "processdna.expected_color.v0"
GENERATOR = "recipemodel.records.expected_color_record"


def _quality(ok, code=None, detail=None, warnings=None):
    return {"ok": ok, "code": code, "detail": detail, "warnings": warnings or []}


def _lab_dict(rgb):
    L, a, b = srgb_to_lab(rgb)
    return {"L": round(float(L), 2), "a": round(float(a), 2), "b": round(float(b), 2)}


def _hue(rgb):
    _, a, b = srgb_to_lab(rgb)
    return round(math.degrees(math.atan2(b, a)) % 360, 1)


def expected_color_record(vial, tank_colors=None, residue_ml=0.0, residue_source="mix",
                          tank_colors_ref=None):
    """vial: one dict from labels.read_vial_recipes. tank_colors: TankColors or None."""
    vols = vial["volumes_ml"]
    tanks = used_tanks(vols)
    use_carry = residue_ml > 0 and vial.get("first_after_change") and vial.get("previous_volumes_ml")

    sources = [{"ref": vial.get("source_ref"), "data_origin": "real_line"}]
    if tank_colors is not None:
        tc_origin = tank_colors.provenance.get("tank_colors_origin", "unknown")
        sources.append({"ref": tank_colors_ref, "data_origin": tc_origin})

    rec = {
        "schema": SCHEMA,
        "vial_id": vial.get("vial_id"),
        "recipe_id": vial.get("recipe_id"),
        "previous_recipe_id": vial.get("previous_recipe_id"),
        "volumes_ml": {t: vols.get(t, 0) for t in TANKS},
        "dispense_order": vial.get("dispense_order_label") or dispense_order_string(vols),
        "tank_colors": {t: {"label": TANK_LABELS[t],
                            "note": "from video-5 labels; not a live tank sensor",
                            "rgb_0_255": (list(tank_colors.rgb[t]) if tank_colors and t in tank_colors.rgb else None)}
                        for t in TANKS},
        "camera_zone": tank_colors.zone if tank_colors else None,
        "mixing_model": MIXING_MODEL,
        "carryover_model": CARRYOVER_MODELS[residue_source] if use_carry else "none",
        "carryover": ({"residue_ml": residue_ml, "applies_to": "first vial after a recipe change"}
                      if use_carry else None),
        "space": "srgb_0_255",
        "value": None,
        "value_lab": None,
        "hue_degrees": None,
        "quality": None,
        "provenance": {"data_origin": "derived", "intended_use": "inspect",
                       "generator": GENERATOR, "sources": sources},
    }

    warnings = []
    if vial.get("dispense_order_label") and vial["dispense_order_label"] != dispense_order_string(vols):
        warnings.append(f"label dispense_order {vial['dispense_order_label']!r} differs from "
                        f"T200>T400>T100 rule ({dispense_order_string(vols)!r})")
    violations = limit_violations(vols)
    if violations:
        warnings.append("outside official operating limits: " + "; ".join(violations))
    if residue_ml > 0 and vial.get("first_after_change") and not vial.get("previous_volumes_ml"):
        warnings.append("first after change but previous recipe unknown; no carryover applied")
    if tank_colors is not None and tank_colors.status != "fitted":
        warnings.append(f"tank colors status is {tank_colors.status!r}; value is illustrative only")

    if not vial.get("volumes_complete", True):
        rec["quality"] = _quality(False, "incomplete_volumes",
                                  f"missing volumes for {vial.get('missing_volumes')}", warnings)
        return rec
    if not tanks:
        rec["quality"] = _quality(False, "empty_recipe", "all tank volumes are zero", warnings)
        return rec
    if tank_colors is None or tank_colors.missing(tanks):
        need = tanks if tank_colors is None else tank_colors.missing(tanks)
        rec["quality"] = _quality(False, "missing_tank_color",
                                  f"no tank color for {need}; run scripts/calibrate_tank_colors.py "
                                  f"or pass --tank-colors", warnings)
        return rec
    if use_carry and tank_colors.missing(used_tanks(vial["previous_volumes_ml"])):
        rec["quality"] = _quality(False, "missing_tank_color", "no tank color for previous recipe", warnings)
        return rec

    res_A = residue_absorbance(tank_colors, vial["previous_volumes_ml"], residue_source) if use_carry else None
    rgb = expected_rgb(tank_colors, vols, res_A, residue_ml if use_carry else 0.0)
    rec["value"] = [int(c) for c in rgb]
    rec["value_lab"] = _lab_dict(rgb)
    rec["hue_degrees"] = _hue(rgb)
    rec["quality"] = _quality(True, None, None, warnings)
    return rec
