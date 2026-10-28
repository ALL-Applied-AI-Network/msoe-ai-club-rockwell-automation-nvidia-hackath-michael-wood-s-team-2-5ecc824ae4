"""Fit tank colors in one camera zone from measured vials, then fit the carryover residue.

Input: MeasuredAppearance JSON records from vialcv.detect.detect_vial_color (the
cv/color-measurement branch), with vial_id set, plus the video-5 recipe table.

  python scripts/calibrate_tank_colors.py --measured <dir or .json files> [--zone backlit] \
      [--labels <csv>] --out tank_colors.json

Steps
  1. Clean vials (not first after a recipe change) -> per-channel NNLS fit of tank colors.
  2. Leave-one-recipe-out: refit without each recipe and predict it.
  3. First vials after a change -> residue volume, for both residue hypotheses.

Data-use: calibration on real line data (organizer reply, Oct 21). This is a fit on the same
vials, not independent evaluation; see recipemodel/calibrate.py.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recipemodel import (default_labels_path, fit_residue_ml, fit_tank_colors,  # noqa: E402
                         leave_one_recipe_out, read_vial_recipes, samples_from_measured)


def load_records(paths):
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("**/*.json")) if p.is_dir() else [p]
    records = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d if isinstance(d, list) else [d]:
            if r.get("schema") == "processdna.measured_appearance.v0":
                records.append(r)
    return records


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--measured", nargs="+", required=True)
    ap.add_argument("--labels")
    ap.add_argument("--zone", default="backlit", help="camera background zone to fit in (default backlit)")
    ap.add_argument("--stat", default="median", choices=("median", "trimmed_mean"))
    ap.add_argument("--out", help="write tank colors JSON (input for expected_color.py --tank-colors)")
    ap.add_argument("--report", help="write the full calibration report JSON")
    a = ap.parse_args(argv)

    vials = read_vial_recipes(Path(a.labels) if a.labels else default_labels_path())
    samples, skipped = samples_from_measured(load_records(a.measured), vials, a.zone, a.stat)
    clean = [s for s in samples if not s["first_after_change"] and s["position_in_batch"] > 1]
    firsts = [s for s in samples if s["first_after_change"] and s["previous_volumes_ml"]]
    print(f"{len(samples)} vials measured in zone {a.zone!r}: {len(clean)} clean, {len(firsts)} first-after-change; "
          f"{len(skipped)} records skipped")
    if len(clean) < 3:
        print("error: need at least 3 clean vials covering all tanks", file=sys.stderr)
        return 1

    tc, fit = fit_tank_colors(clean, zone=a.zone)
    tc.provenance.update({"tank_colors_origin": "derived",
                          "sources_data_origin": "real_line",
                          "use_note": "calibration on real line data; not independent evaluation"})
    report = {"zone": a.zone, "tank_fit": fit, "tank_rgb_0_255": {k: [round(c, 1) for c in v] for k, v in tc.rgb.items()},
              "leave_one_recipe_out_de2000": leave_one_recipe_out(clean, a.zone), "skipped": skipped}
    if firsts:
        report["carryover"] = {}
        for src in ("mix", "dye"):
            r_ml, rep = fit_residue_ml(tc, firsts, src)
            report["carryover"][src] = {"residue_ml": r_ml, **rep}
        report["carryover"]["better_fit"] = min(("mix", "dye"),
                                                key=lambda s: report["carryover"][s]["de2000_mean_with_residue"])
    print(json.dumps(report, indent=2, default=str))

    if a.out:
        Path(a.out).write_text(json.dumps(tc.to_json_dict(), indent=2), encoding="utf-8")
        print(f"wrote {a.out}")
    if a.report:
        Path(a.report).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
