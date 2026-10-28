"""Explicit, testable carryover term for the first vial after a recipe change.

Official Dataset 2 description: residue from the previous recipe in the shared mixing
path flushes into the first vial of a new batch; vials 2 and 3 come out clean.
The residue volume is NOT measured in the supplied tables, so it is a parameter.

Two residue hypotheses (which one fits the real first vials is itself a finding):
  previous_mix_v0 : the residue looks like the previous vial's whole mixture
  previous_dye_v0 : the residue is the previous recipe's colored tanks only (t100 excluded)

    A_first = (V * A_recipe + r * A_residue) / (V + r)       r = residue_ml

Applied only to vials with first_after_change=True and a known previous recipe.
"""
from .mixing import mixture_absorbance

CARRYOVER_MODELS = {"mix": "previous_mix_v0", "dye": "previous_dye_v0"}


def residue_absorbance(tank_colors, previous_volumes_ml, source="mix", diluent="t100"):
    if source == "dye":
        dyes = {t: v for t, v in previous_volumes_ml.items() if t != diluent and (v or 0) > 0}
        if dyes:
            return mixture_absorbance(tank_colors, dyes)[0]
    return mixture_absorbance(tank_colors, previous_volumes_ml)[0]
