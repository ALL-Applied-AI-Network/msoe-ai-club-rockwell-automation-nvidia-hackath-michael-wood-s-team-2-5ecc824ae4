# Recipe Modeling & Carryover

Owner: **Zayd**; second person TBD.

## Purpose and scope

Estimate an expected vial color from recipe information, and optionally add a simple previous-recipe carryover term.

In scope: tank IDs and labeled colors, volumes, dispense order, a named mixing baseline, a bounded carryover experiment if feasible.

Out of scope: claiming the estimate equals camera appearance; training on real images; assuming the twin can mix arbitrary recipes; a full fluid-dynamics model.

## Inputs

From Dataset 2 labels (`$DATASET_ROOT/vial_fill/labels/`):

- Per vial: `recipe_id`, `t100_ml`, `t200_ml`, `t400_ml`, `total_ml`, `dispense_order`, fill times.
- Sequence: vials 1–30 on video 5 run recipes 5–14 in order, three vials each.
- Labeled tank colors for this collection: T-100 clear, T-200 orange, T-400 blue. T-300 unused.
- Official Dataset 2 note: first vial after a recipe change may show carryover; last vial of a recipe is described as the cleaner example of that recipe.

Tank colors can change in general. Labels are not live tank sensors.

## Outputs

Proposed `ExpectedColor` record in [interfaces.md](../interfaces.md): volumes, order, tank-color assumptions, named `mixing_model`, optional `carryover_model`, named color `space` and `value`, plus quality/failure.

If carryover is included, name `previous_recipe_id` only when known.

## Dependencies

- CV: later comparison needs `MeasuredAppearance`. This workstream should not wait on workstream-complete liquid-region selection to parse recipes.
- Twin: do not require the twin to produce physically mixed colors. Official twin docs do not model tanks.
- Data-use: recipe tables may be used to build the baseline. Pixel training still follows [project-context.md](../project-context.md).

## Observable completion

- Code reads the video-5 recipe table and emits a structured expected-color record per recipe or vial.
- Mixing method is named. Linear RGB averaging, if used, is labeled as a naive baseline, not as physical mixing.
- Missing tank color or incomplete volumes produce `quality.ok=false` rather than a guessed color.

A carryover term is success only if it is explicit and testable; skipping it is allowed.

## Current evidence (repo)

Branch `recipe/expected-color` adds package `recipemodel/`, two scripts, and `tests/test_recipemodel.py`.

| Piece | File | What it does |
| --- | --- | --- |
| Station facts | `recipemodel/station.py` | Tanks t100/t200/t400, dispense order T200>T400>T100, official operating limits |
| Labels | `recipemodel/labels.py` | Reads `video5_vial_recipes.csv`; per vial: volumes, order, `previous_recipe_id`, first-after-change, position in batch. Unknown stays `null` (vial 1's predecessor is not in the labels) |
| Mixing model | `recipemodel/mixing.py` | Named `beer_lambert_absorbance_srgb`: per-channel absorbance `-log10(T)`, volume-weighted sum, back to sRGB. **Not** linear RGB averaging |
| Carryover | `recipemodel/carryover.py` | Explicit term for the first vial after a recipe change: `A = (V*A_recipe + r*A_residue)/(V + r)`. Two hypotheses: `previous_mix_v0` (residue = previous whole mix) and `previous_dye_v0` (previous colored tanks only) |
| Records | `recipemodel/records.py`, `scripts/expected_color.py` | One `ExpectedColor` record per vial. No tank colors or incomplete volumes -> `value: null`, `quality.ok: false` with a code |
| Calibration | `recipemodel/calibrate.py`, `scripts/calibrate_tank_colors.py` | Fits tank colors in one camera zone from `MeasuredAppearance` records of clean vials (NNLS on absorbance), leave-one-recipe-out check, then fits the residue volume on first-after-change vials for both hypotheses |

Verification run: the 19 tests in `tests/test_recipemodel.py` (synthetic labels and synthetic measurements only) passed, including an end-to-end CLI run. On synthetic data the calibration recovers tank colors within dE00 1.5 and the residue volume within 0.5 mL. **Not yet run on real Dataset 2 data** (no real numbers in this doc).

Usage (dataset outside git):

```text
$env:DATASET_ROOT = "<path to csi-vial-fill-dataset>"

# Recipe table only -> records with value=null and quality code missing_tank_color
python scripts/expected_color.py

# Fit tank colors in the backlit zone from Group 1 measurements (cv/color-measurement output)
python scripts/calibrate_tank_colors.py --measured <folder of detect_vial_color --json outputs> --zone backlit --out tank_colors.json

# Expected color per vial, optionally with carryover on first-after-change vials
python scripts/expected_color.py --tank-colors tank_colors.json [--residue-ml 8 --residue mix|dye] --out expected.json

python -m pytest tests/test_recipemodel.py
```

Dependencies: numpy (and pytest for tests). No pandas or OpenCV needed in `recipemodel/`.

### Interface notes (cross-workstream, proposed)

`ExpectedColor` records from this branch follow the proposed shape in [interfaces.md](../interfaces.md) and **add** these fields, which are not agreed yet: `vial_id`, `camera_zone` (zone the tank colors were fitted in), `carryover` (`{"residue_ml", "applies_to"}`), `value_lab`, `hue_degrees`, and `quality.warnings`. `space` is `srgb_0_255`. `value_lab` uses a D65 CIELAB conversion in `recipemodel/colors.py`, which is not guaranteed to match OpenCV's float Lab exactly; compare colors with one converter.

Calibration consumes `MeasuredAppearance.color.zones[<zone>].rgb_0_255.median` and requires `vial_id` on each record.

### Data-use for calibration

Organizer reply to the team plan (posted in the team chat on Oct 21): *"Yes, you can use real data from system runs for calibration. You will want to expand the scope of the color ranges to fully calibrate your solution."* This fits physical parameters (one color per tank, one residue volume). It is not model training on images, and a fit on the same vials is not independent evaluation. The team constraint in [project-context.md](../project-context.md) is unchanged; the team should confirm it is comfortable with this reading.

## Limitations and cautions

- Do not treat `color_purpose` notes as ground-truth spectrophotometer readings.
- Volume-weighted RGB is not a verified mixing model. Beer-Lambert on 3 sRGB channels is also an approximation of a spectral process.
- Instant, complete mixing is assumed; the model predicts the settled vial, not the pour.
- Carryover amount in the shared path is not measured in the supplied tables.

## Next bounded milestone

Date: **TBD**.

Done on this branch: parse `video5_vial_recipes.csv` into per-vial records and emit named `ExpectedColor` records.

Next: run `calibrate_tank_colors.py` on real video-5 measurements from Group 1 (backlit zone) and report the fit, leave-one-recipe-out, and which residue hypothesis fits the first vials better. Recipe 14 is too pale to segment and recipes 5-6 have no backlit zone (cv-lighting-study), so expect fewer than 30 usable vials.

## Out of scope

- Recommending live recipe changes on the CSI line.
- Using T-300 or >50 mL from T-200 in any requested live test (official station limits).
