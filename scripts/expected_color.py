"""Recipe table -> one `processdna.expected_color.v0` record per vial.

  python scripts/expected_color.py                                # value=null, quality says why
  python scripts/expected_color.py --tank-colors tank_colors.json  # named Beer-Lambert estimate
  python scripts/expected_color.py --tank-colors tank_colors.json --residue-ml 8 --residue dye
  python scripts/expected_color.py --labels <csv> --out expected.json

--labels defaults to $DATASET_ROOT/vial_fill/labels/video5_vial_recipes.csv.
Exit code: 0 if every record has a value, 1 if any record has quality.ok=false, 2 on usage errors.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recipemodel import TankColors, default_labels_path, expected_color_record, read_vial_recipes  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--labels", help="video5_vial_recipes.csv (default: under $DATASET_ROOT)")
    ap.add_argument("--tank-colors", help="tank colors JSON (scripts/calibrate_tank_colors.py output)")
    ap.add_argument("--residue-ml", type=float, default=0.0,
                    help="residue volume added to the first vial after a recipe change (default 0 = no carryover)")
    ap.add_argument("--residue", choices=("mix", "dye"), default="mix",
                    help="residue looks like the previous whole mix, or the previous dye only")
    ap.add_argument("--out", help="write records as a JSON list here")
    a = ap.parse_args(argv)

    try:
        labels = Path(a.labels) if a.labels else default_labels_path()
        vials = read_vial_recipes(labels)
        tc = TankColors.from_json(a.tank_colors) if a.tank_colors else None
    except (RuntimeError, FileNotFoundError, KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    records = [expected_color_record(v, tc, a.residue_ml, a.residue,
                                     tank_colors_ref=Path(a.tank_colors).name if a.tank_colors else None)
               for v in vials]
    for r in records:
        q = r["quality"]
        val = r["value"] if q["ok"] else f"null ({q['code']})"
        carry = f"  carryover {r['carryover']['residue_ml']} mL" if r["carryover"] else ""
        print(f"vial {r['vial_id']!s:>3}  recipe {r['recipe_id']!s:>3} (prev {r['previous_recipe_id']!s:>4})  "
              f"{r['dispense_order']:<16} -> {val}{carry}")
        for w in q["warnings"]:
            print(f"      warning: {w}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        print(f"wrote {len(records)} records to {a.out}")
    return 0 if all(r["quality"]["ok"] for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
