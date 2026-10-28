"""Tests for recipemodel (synthetic data only; no dataset needed)."""
import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from recipemodel import (TankColors, color_distance, delta_e2000, dispense_order_string,
                         expected_color_record, expected_rgb, fit_residue_ml, fit_tank_colors,
                         leave_one_recipe_out, limit_violations, read_vial_recipes,
                         residue_absorbance, samples_from_measured, srgb_to_lab)

REPO = Path(__file__).resolve().parents[1]
TRUTH = TankColors(rgb={"t100": (250, 250, 250), "t200": (240, 100, 20), "t400": (15, 125, 205)},
                   status="fitted", zone="backlit", provenance={"tank_colors_origin": "derived"})
# Ten synthetic recipes in the shape of video 5 (ids 5-14). NOT the real volumes.
RECIPES = {5: (10, 10, 10), 6: (30, 10, 0), 7: (20, 0, 50), 8: (20, 20, 20), 9: (40, 0, 20),
           10: (10, 30, 30), 11: (30, 0, 30), 12: (20, 40, 0), 13: (10, 20, 40), 14: (60, 0, 10)}
RESIDUE_ML = 8.0


def write_labels(path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vial", "recipe_id", "type", "t100_ml", "t200_ml", "t400_ml", "total_ml", "dispense_order"])
        vial = 1
        for rid, (t100, t200, t400) in RECIPES.items():
            vols = {"t100": t100, "t200": t200, "t400": t400}
            for _ in range(3):
                w.writerow([vial, rid, "x", t100, t200, t400, t100 + t200 + t400, dispense_order_string(vols)])
                vial += 1
    return path


@pytest.fixture
def labels(tmp_path):
    return write_labels(tmp_path / "video5_vial_recipes.csv")


def measured_records(vials, zone="backlit"):
    """Fake vialcv MeasuredAppearance records generated from TRUTH (+ carryover on first vials)."""
    recs = []
    for v in vials:
        res = (residue_absorbance(TRUTH, v["previous_volumes_ml"]) if v["first_after_change"] else None)
        rgb = expected_rgb(TRUTH, v["volumes_ml"], res, RESIDUE_ML if res is not None else 0.0)
        recs.append({"schema": "processdna.measured_appearance.v0", "vial_id": v["vial_id"],
                     "image_ref": f"fake/{v['vial_id']}.png", "quality": {"ok": True},
                     "color": {"zones": {zone: {"ok": True, "rgb_0_255": {"median": [float(c) for c in rgb]}}}}})
    return recs


# ---------- colors ----------
def test_de2000_reference_pairs():
    # Sharma, Wu & Dalal (2005) published test data
    for l1, l2, want in [((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
                         ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
                         ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644)]:
        assert delta_e2000(l1, l2) == pytest.approx(want, abs=1e-3)


def test_white_is_lab_100():
    assert srgb_to_lab((255, 255, 255))[0] == pytest.approx(100, abs=0.1)


# ---------- station + labels ----------
def test_dispense_order_rule():
    assert dispense_order_string({"t100": 20, "t200": 0, "t400": 50}) == "T400>T100"
    assert dispense_order_string({"t100": 1, "t200": 1, "t400": 1}) == "T200>T400>T100"


@pytest.mark.parametrize("vols, text", [({"t100": 60, "t400": 30}, "> 80"), ({"t200": 5, "t100": 30}, "minimum"),
                                        ({"t200": 55, "t100": 10}, "t200 55")])
def test_limit_violations(vols, text):
    assert any(text in p for p in limit_violations(vols))


def test_read_labels_previous_recipe_and_positions(labels):
    vials = read_vial_recipes(labels)
    assert len(vials) == 30
    assert vials[0]["previous_recipe_id"] is None and vials[0]["position_in_batch"] == 1
    assert not vials[0]["first_after_change"]           # predecessor not in the labels
    v7 = [v for v in vials if v["recipe_id"] == 7]
    assert v7[0]["first_after_change"] and v7[0]["previous_recipe_id"] == 6
    assert [v["position_in_batch"] for v in v7] == [1, 2, 3]
    assert not v7[1]["first_after_change"]


def test_incomplete_volumes_flagged(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("vial,recipe_id,t100_ml,t200_ml,t400_ml\n1,5,10,,10\n")
    rec = expected_color_record(read_vial_recipes(p)[0], TRUTH)
    assert rec["value"] is None and rec["quality"]["code"] == "incomplete_volumes"


# ---------- records ----------
def test_no_tank_colors_gives_null_value_not_a_guess(labels):
    rec = expected_color_record(read_vial_recipes(labels)[0])
    assert rec["schema"] == "processdna.expected_color.v0"
    assert rec["value"] is None and rec["quality"] == {"ok": False, "code": "missing_tank_color",
                                                       "detail": rec["quality"]["detail"], "warnings": []}
    assert rec["mixing_model"] == "beer_lambert_absorbance_srgb"


def test_record_shape_and_provenance(labels):
    rec = expected_color_record(read_vial_recipes(labels)[9], TRUTH, tank_colors_ref="tank_colors.json")
    assert rec["quality"]["ok"] and len(rec["value"]) == 3
    assert set(rec["volumes_ml"]) == {"t100", "t200", "t400"}
    prov = rec["provenance"]
    assert prov["data_origin"] == "derived"
    assert {s["data_origin"] for s in prov["sources"]} == {"real_line", "derived"}
    assert prov["sources"][0]["ref"] == "vial_fill/labels/video5_vial_recipes.csv"


def test_single_tank_returns_its_own_color():
    assert color_distance(expected_rgb(TRUTH, {"t400": 30}), TRUTH.rgb["t400"]) < 0.5


def test_mixing_is_not_rgb_averaging():
    mix = np.array(expected_rgb(TRUTH, {"t200": 30, "t400": 30}))
    avg = (np.array(TRUTH.rgb["t200"]) + np.array(TRUTH.rgb["t400"])) / 2
    assert mix.sum() < avg.sum() - 60               # absorbances stack: darker than the average


def test_carryover_only_on_first_vial_after_change(labels):
    vials = read_vial_recipes(labels)
    recs = [expected_color_record(v, TRUTH, residue_ml=RESIDUE_ML) for v in vials]
    for v, r in zip(vials, recs):
        assert (r["carryover_model"] != "none") == v["first_after_change"]
    first7 = next(r for v, r in zip(vials, recs) if v["recipe_id"] == 7 and v["first_after_change"])
    clean7 = next(r for v, r in zip(vials, recs) if v["recipe_id"] == 7 and v["position_in_batch"] == 3)
    assert first7["carryover"]["residue_ml"] == RESIDUE_ML
    assert color_distance(first7["value"], clean7["value"]) > 2.0


def test_orange_residue_pulls_blue_recipe_toward_green():
    clean = expected_rgb(TRUTH, {"t400": 50, "t100": 20})
    dirty = expected_rgb(TRUTH, {"t400": 50, "t100": 20}, residue_absorbance(TRUTH, {"t200": 10, "t100": 30}, "dye"), 8)
    hue = lambda rgb: np.degrees(np.arctan2(srgb_to_lab(rgb)[2], srgb_to_lab(rgb)[1])) % 360
    assert hue(dirty) < hue(clean)                  # blue (~260 deg) moves toward green (<200 deg)


def test_placeholder_tank_colors_warn(labels):
    tc = TankColors(rgb=TRUTH.rgb, status="placeholder")
    rec = expected_color_record(read_vial_recipes(labels)[3], tc)
    assert any("illustrative" in w for w in rec["quality"]["warnings"])


# ---------- calibration ----------
def test_calibration_recovers_tank_colors_and_residue(labels):
    vials = read_vial_recipes(labels)
    samples, skipped = samples_from_measured(measured_records(vials), vials)
    assert not skipped and len(samples) == 30
    clean = [s for s in samples if not s["first_after_change"] and s["position_in_batch"] > 1]
    tc, rep = fit_tank_colors(clean, zone="backlit")
    assert rep["identifiable"] and rep["fit_de2000_max"] < 1.0
    for t in TRUTH.rgb:
        assert color_distance(tc.rgb[t], TRUTH.rgb[t]) < 1.5
    firsts = [s for s in samples if s["first_after_change"]]
    r_ml, rep2 = fit_residue_ml(tc, firsts, "mix")
    assert r_ml == pytest.approx(RESIDUE_ML, abs=0.5)
    assert rep2["de2000_mean_with_residue"] < rep2["de2000_mean_without_residue"]


def test_leave_one_recipe_out_runs(labels):
    vials = read_vial_recipes(labels)
    samples, _ = samples_from_measured(measured_records(vials), vials)
    clean = [s for s in samples if not s["first_after_change"] and s["position_in_batch"] > 1]
    loro = leave_one_recipe_out(clean)
    assert set(loro) == set(RECIPES)
    assert all(isinstance(v, float) and v < 1.5 for v in loro.values())


def test_measured_zone_not_ok_is_skipped(labels):
    vials = read_vial_recipes(labels)
    recs = measured_records(vials[:2])
    recs[0]["color"]["zones"]["backlit"]["ok"] = False
    samples, skipped = samples_from_measured(recs, vials)
    assert len(samples) == 1 and skipped[0]["reason"] == "zone backlit not ok"


# ---------- CLI ----------
def test_cli_end_to_end(labels, tmp_path):
    vials = read_vial_recipes(labels)
    meas = tmp_path / "measured.json"
    meas.write_text(json.dumps(measured_records(vials)))
    tank_json, out = tmp_path / "tank_colors.json", tmp_path / "expected.json"
    run = lambda *args: subprocess.run([sys.executable, *map(str, args)], cwd=REPO, capture_output=True, text=True)

    r = run("scripts/expected_color.py", "--labels", labels)
    assert r.returncode == 1 and "missing_tank_color" in r.stdout

    r = run("scripts/calibrate_tank_colors.py", "--measured", meas, "--labels", labels, "--out", tank_json)
    assert r.returncode == 0, r.stderr
    assert json.loads(tank_json.read_text())["status"] == "fitted"

    r = run("scripts/expected_color.py", "--labels", labels, "--tank-colors", tank_json,
            "--residue-ml", "8", "--out", out)
    assert r.returncode == 0, r.stderr
    recs = json.loads(out.read_text())
    assert len(recs) == 30 and all(x["quality"]["ok"] for x in recs)
