"""Recipe -> expected color with a Beer-Lambert absorbance model.

Dyed water is transparent: each dye absorbs part of the light and absorbances add.
Seen sideways through the vial (fixed path length), the mixture's absorbance per
channel is the concentration-weighted sum of each tank's absorbance:

    T_i   = linear_rgb(tank_i) / linear_rgb(white_ref)
    A_i   = -log10(T_i)
    A_mix = sum(V_i * A_i) / sum(V_i)          (+ residue term, see carryover.py)
    rgb   = white_ref * 10^(-A_mix)

Named `beer_lambert_absorbance_srgb`. It is a model, not a measurement: RGB is a
3-number summary of a spectrum, and camera appearance also depends on the background
behind the glass (see docs/components/cv-lighting-study.md on cv/color-measurement).
Tank colors are therefore fitted per camera zone (calibrate.py) before comparing.
Linear RGB averaging is NOT used.
"""
from dataclasses import dataclass, field
import json

import numpy as np

from .colors import linear_to_srgb, srgb_to_linear
from .station import TANKS

MIXING_MODEL = "beer_lambert_absorbance_srgb"
EPS = 1e-4


@dataclass
class TankColors:
    """Apparent color of each tank's liquid (sRGB 0-255) through a full vial, plus the
    white reference those colors are relative to. `zone` names the camera background
    the colors were fitted in (None if not camera-calibrated)."""
    rgb: dict
    white_ref: tuple = (255.0, 255.0, 255.0)
    zone: str = None
    status: str = "unverified"          # unverified | placeholder | fitted
    provenance: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return cls(rgb={k: tuple(v) for k, v in d["tank_rgb_0_255"].items()},
                   white_ref=tuple(d.get("white_ref_rgb_0_255", (255, 255, 255))),
                   zone=d.get("camera_zone"), status=d.get("status", "unverified"),
                   provenance=d.get("provenance", {}))

    def to_json_dict(self):
        return {"schema": "processdna.tank_colors.v0", "camera_zone": self.zone, "status": self.status,
                "white_ref_rgb_0_255": list(self.white_ref),
                "tank_rgb_0_255": {k: [round(float(c), 2) for c in v] for k, v in self.rgb.items()},
                "provenance": self.provenance}

    def missing(self, tanks):
        return [t for t in tanks if t not in self.rgb]

    def absorbance(self, tank):
        return rgb_to_absorbance(self.rgb[tank], self.white_ref)


def rgb_to_absorbance(rgb, white_ref=(255, 255, 255)):
    T = srgb_to_linear(rgb) / np.maximum(srgb_to_linear(white_ref), EPS)
    return -np.log10(np.clip(T, EPS, 1.0))


def absorbance_to_rgb(A, white_ref=(255, 255, 255)):
    lin = 10 ** (-np.asarray(A, float)) * srgb_to_linear(white_ref)
    return linear_to_srgb(lin)


def mixture_absorbance(tank_colors, volumes_ml, residue_A=None, residue_ml=0.0):
    """Volume-weighted absorbance of the recipe, plus an optional residue volume.
    Returns (A, total_ml). Raises ValueError for an empty recipe."""
    used = {t: float(v) for t, v in volumes_ml.items() if (v or 0) > 0}
    total = sum(used.values())
    if total <= 0:
        raise ValueError("recipe has zero total volume")
    num = sum(v * tank_colors.absorbance(t) for t, v in used.items())
    if residue_A is not None and residue_ml > 0:
        num = num + residue_ml * np.asarray(residue_A, float)
        total += residue_ml
    return num / total, total


def expected_rgb(tank_colors, volumes_ml, residue_A=None, residue_ml=0.0):
    A, _ = mixture_absorbance(tank_colors, volumes_ml, residue_A, residue_ml)
    return absorbance_to_rgb(A, tank_colors.white_ref)


def used_tanks(volumes_ml):
    return [t for t in TANKS if (volumes_ml.get(t) or 0) > 0]
