# Recipe Modeling & Carryover

Owner: **TBD** (2 people).

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

No recipe or mixing code is in the repository.

Label files exist only in the external dataset package, not in git.

Official Dataset 2 example (organizer description, not a repo result): Recipe 6 (orange) followed by Recipe 7 (blue) produced a green first vial, attributed to leftover orange in the shared path.

## Limitations and cautions

- Do not treat `color_purpose` notes as ground-truth spectrophotometer readings.
- Volume-weighted RGB is not a verified mixing model.
- Carryover amount in the shared path is not measured in the supplied tables.

## Next bounded milestone

Date: **TBD**.

Parse `video5_vial_recipes.csv` into per-vial records with volumes, order, and previous recipe id. Emit `ExpectedColor` with `mixing_model: unspecified` and `value: null` until a named baseline exists.

## Out of scope

- Recommending live recipe changes on the CSI line.
- Using T-300 or >50 mL from T-200 in any requested live test (official station limits).
