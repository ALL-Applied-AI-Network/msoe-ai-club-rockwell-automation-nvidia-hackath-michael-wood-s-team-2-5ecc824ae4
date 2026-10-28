"""Fit tank colors (and the residue volume) from measured vial appearance.

Data-use: the organizers' reply to the team plan (shared in Teams, Oct 21) says
"Yes, you can use real data from system runs for calibration." The team constraint
(docs/project-context.md) keeps real data out of model TRAINING. This fits 3 physical
parameters per channel (one color per tank) plus one residue volume; results that use
the same real vials are calibration fit, not independent evaluation. The
leave-one-recipe-out numbers are the closest thing to a held-out check here.

Beer-Lambert is linear in absorbance, so for each clean vial (not first after a change):
    A_vial = sum_i (V_i / V_total) * A_i
which is a non-negative least-squares problem per channel. Fit within ONE camera zone:
appearance depends on the background behind the glass, and a zone's background is
absorbed into the fitted tank colors (concentrations sum to 1).
"""
import numpy as np

from .carryover import residue_absorbance
from .colors import color_distance
from .mixing import TankColors, absorbance_to_rgb, expected_rgb, rgb_to_absorbance
from .station import TANKS


def _nnls(M, y, iters=20000):
    x = np.clip(np.linalg.lstsq(M, y, rcond=None)[0], 0, None)
    step = 1.0 / (np.linalg.norm(M, 2) ** 2 or 1.0)
    for _ in range(iters):
        x = np.clip(x - step * (M.T @ (M @ x - y)), 0, None)
    return x


def fit_tank_colors(samples, zone=None, white_ref=(255, 255, 255), tanks=TANKS):
    """samples: [{"volumes_ml": {...}, "rgb": [r,g,b], "recipe_id": ..}] from CLEAN vials.
    Returns (TankColors, report)."""
    M = np.array([[s["volumes_ml"].get(t, 0) / sum(s["volumes_ml"].values()) for t in tanks]
                  for s in samples], float)
    Y = np.array([rgb_to_absorbance(s["rgb"], white_ref) for s in samples])
    A = np.column_stack([_nnls(M, Y[:, c]) for c in range(3)])
    tc = TankColors(rgb={t: tuple(float(x) for x in absorbance_to_rgb(A[i], white_ref)) for i, t in enumerate(tanks)},
                    white_ref=tuple(white_ref), zone=zone, status="fitted",
                    provenance={"tank_colors_origin": "derived", "fit": "nnls_absorbance_per_channel",
                                "n_samples": len(samples),
                                "recipe_ids": sorted({s.get("recipe_id") for s in samples}, key=str)})
    errs = [color_distance(expected_rgb(tc, s["volumes_ml"]), s["rgb"]) for s in samples]
    report = {"n_samples": len(samples), "identifiable": int(np.linalg.matrix_rank(M)) == len(tanks),
              "fit_de2000_mean": round(float(np.mean(errs)), 2) if errs else None,
              "fit_de2000_max": round(float(np.max(errs)), 2) if errs else None}
    return tc, report


def leave_one_recipe_out(samples, zone=None, white_ref=(255, 255, 255)):
    """Refit without each recipe and predict it. Returns {recipe_id: mean dE2000 or reason}."""
    out = {}
    for rid in sorted({s.get("recipe_id") for s in samples}, key=str):
        train = [s for s in samples if s.get("recipe_id") != rid]
        test = [s for s in samples if s.get("recipe_id") == rid]
        tc, rep = fit_tank_colors(train, zone, white_ref)
        if not rep["identifiable"]:
            out[rid] = "skipped: remaining recipes cannot separate all tanks"
            continue
        out[rid] = round(float(np.mean([color_distance(expected_rgb(tc, s["volumes_ml"]), s["rgb"])
                                        for s in test])), 2)
    return out


def fit_residue_ml(tank_colors, first_samples, source="mix", r_max_ml=30.0, steps=3001):
    """first_samples: [{"volumes_ml", "previous_volumes_ml", "rgb"}] for first-after-change
    vials. Finds one residue volume for all of them. Returns (r_ml, report)."""
    res_A = [residue_absorbance(tank_colors, s["previous_volumes_ml"], source) for s in first_samples]
    best_r, best_err, best_list = 0.0, float("inf"), []
    for r in np.linspace(0.0, r_max_ml, steps):
        errs = [color_distance(expected_rgb(tank_colors, s["volumes_ml"], a, r), s["rgb"])
                for s, a in zip(first_samples, res_A)]
        m = float(np.mean(errs))
        if m < best_err:
            best_r, best_err, best_list = float(r), m, errs
    no_carry = [color_distance(expected_rgb(tank_colors, s["volumes_ml"]), s["rgb"]) for s in first_samples]
    return round(best_r, 2), {"residue_source": source,
                              "de2000_mean_with_residue": round(best_err, 2),
                              "de2000_mean_without_residue": round(float(np.mean(no_carry)), 2),
                              "per_vial_de2000": [round(float(e), 2) for e in best_list]}


def samples_from_measured(records, vials, zone="backlit", stat="median"):
    """Join MeasuredAppearance records (vialcv.detect output) to label vials by vial_id.
    Uses color.zones[zone].rgb_0_255[stat]; records whose zone is not ok are skipped.
    Several frames of one vial are averaged in absorbance space."""
    by_vial = {v["vial_id"]: v for v in vials if v.get("vial_id") is not None}
    grouped, skipped = {}, []
    for r in records:
        vid = r.get("vial_id")
        z = ((r.get("color") or {}).get("zones") or {}).get(zone) or {}
        if vid not in by_vial or not z.get("ok") or not (r.get("quality") or {}).get("ok", True):
            skipped.append({"vial_id": vid, "image_ref": r.get("image_ref"),
                            "reason": "no label match" if vid not in by_vial else f"zone {zone} not ok"})
            continue
        grouped.setdefault(vid, []).append((z["rgb_0_255"][stat], r.get("image_ref")))
    samples = []
    for vid, items in grouped.items():
        A = np.mean([rgb_to_absorbance(rgb) for rgb, _ in items], axis=0)
        v = by_vial[vid]
        samples.append({"vial_id": vid, "recipe_id": v["recipe_id"], "volumes_ml": v["volumes_ml"],
                        "previous_volumes_ml": v["previous_volumes_ml"],
                        "first_after_change": v["first_after_change"],
                        "position_in_batch": v["position_in_batch"],
                        "rgb": [float(c) for c in absorbance_to_rgb(A)],
                        "image_refs": [ref for _, ref in items]})
    return sorted(samples, key=lambda s: s["vial_id"]), skipped
