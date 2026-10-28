"""Recipe Modeling & Carryover (ProcessDNA workstream 2).

Recipe volumes -> named expected-color estimate (`processdna.expected_color.v0`),
with an optional explicit carryover term for the first vial after a recipe change.
"""
from .calibrate import fit_residue_ml, fit_tank_colors, leave_one_recipe_out, samples_from_measured
from .carryover import CARRYOVER_MODELS, residue_absorbance
from .colors import color_distance, delta_e2000, srgb_to_lab
from .labels import default_labels_path, read_vial_recipes
from .mixing import MIXING_MODEL, TankColors, expected_rgb, mixture_absorbance
from .records import SCHEMA, expected_color_record
from .station import DISPENSE_ORDER, TANKS, dispense_order_string, limit_violations

__all__ = [
    "CARRYOVER_MODELS", "DISPENSE_ORDER", "MIXING_MODEL", "SCHEMA", "TANKS", "TankColors",
    "color_distance", "default_labels_path", "delta_e2000", "dispense_order_string",
    "expected_color_record", "expected_rgb", "fit_residue_ml", "fit_tank_colors",
    "leave_one_recipe_out", "limit_violations", "mixture_absorbance", "read_vial_recipes",
    "residue_absorbance", "samples_from_measured", "srgb_to_lab",
]
