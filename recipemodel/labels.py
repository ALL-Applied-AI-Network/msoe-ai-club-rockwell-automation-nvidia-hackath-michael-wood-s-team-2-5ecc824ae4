"""Read the official per-vial recipe table (video 5) into plain per-vial dicts.

Source: $DATASET_ROOT/vial_fill/labels/video5_vial_recipes.csv (outside git).
Columns used: a vial id (`vial` or `vial_id`), `recipe_id`, `t100_ml`, `t200_ml`,
`t400_ml`; optional `total_ml`, `dispense_order`. Other columns are kept as-is.

`previous_recipe_id` is the recipe of the preceding vial in the table, and only
when that vial exists; the first vial of the run gets None (its predecessor is not
described in the labels). Unknown values stay None; nothing is invented.
"""
import csv
import os
from pathlib import Path

from .station import TANKS

LABELS_RELPATH = Path("vial_fill") / "labels" / "video5_vial_recipes.csv"


def default_labels_path(root=None):
    root = root or os.environ.get("DATASET_ROOT")
    if not root:
        raise RuntimeError("Set DATASET_ROOT to the csi-vial-fill-dataset folder or pass --labels.")
    return Path(root) / LABELS_RELPATH


def _num(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        f = float(value)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def read_vial_recipes(path):
    """Return a list of per-vial dicts in table order."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    vials = []
    for i, row in enumerate(rows):
        vial_id = _num(row.get("vial", row.get("vial_id")))
        volumes = {t: _num(row.get(f"{t}_ml")) for t in TANKS}
        missing = [t for t, v in volumes.items() if v is None]
        vials.append({
            "vial_id": vial_id,
            "recipe_id": _num(row.get("recipe_id")),
            "volumes_ml": {t: (v or 0) for t, v in volumes.items()},
            "volumes_complete": not missing,
            "missing_volumes": missing,
            "total_ml": _num(row.get("total_ml")),
            "dispense_order_label": (row.get("dispense_order") or None),
            "row_index": i,
            "source_ref": LABELS_RELPATH.as_posix(),
        })
    for i, v in enumerate(vials):
        prev = vials[i - 1] if i > 0 else None
        v["previous_recipe_id"] = prev["recipe_id"] if prev else None
        v["previous_volumes_ml"] = prev["volumes_ml"] if prev else None
        v["first_after_change"] = bool(prev and prev["recipe_id"] != v["recipe_id"])
        v["position_in_batch"] = 1 if (prev is None or v["first_after_change"]) else \
            vials[i - 1]["position_in_batch"] + 1
    return vials
