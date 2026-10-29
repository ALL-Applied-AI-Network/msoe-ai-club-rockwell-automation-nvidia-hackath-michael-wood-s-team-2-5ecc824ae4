# CV lab runbook (vial_fill camera, one-hour slot)

For the CV team during a scheduled lab test on the CSI vial line. Goal: leave with clean recordings of the vial_fill camera (with the recipes that were run) and a first set of per-vial measurements.

**Rules (official; see [project-context.md](../project-context.md)):** do not reconfigure cameras, PLCs, recipes, or safety systems without approval. Recipe changes need plant-manager guidance. Station limits: vial total ≤ 80 mL, ≥ 10 mL of any component used, ≤ 50 mL from T-200, no T-300. Recordings are **real line data**: inspection, calibration, and evaluation only, never training data. Keep them out of git (`outputs/` is ignored).

## Before you go

- [ ] Laptop charged; repo on `cv/color-measurement`; `.venv\Scripts\python -m pytest -q` passes.
- [ ] `$env:DATASET_ROOT` set to the dataset copy (enables the camera-shift check).
- [ ] USB cable/adapter for the camera, if staff allow a direct connection; an external drive or cloud folder to copy recordings to.
- [ ] Run plan written down with staff (recipes and order), then saved as `plan.csv`:

  ```text
  vial_order,recipe_id
  1,7
  2,7
  3,7
  ```

## Questions to ask staff first

1. Can we connect our laptop to the vial_fill camera, or should we get recordings from your capture system?
2. Which recipes will run, in what order, and what color is in each tank today?
3. Has the vial_fill camera, lighting, or backdrop changed since the Dataset 2 recordings?
4. May we photograph the tanks (or record the tank_level camera) to note tank colors?

## Timeline

| Minutes | Do | Command / check |
| --- | --- | --- |
| 0-10 | Find the camera and check the view | `python scripts\lab_check.py --list-cameras`, then `python scripts\lab_check.py --source 0` with a vial parked. Want **READY**. |
| 10-15 | Optional backup: grab empty-vial frames (a parked carrier before its pour). Extraction already saves one per vial from the recording. | `python scripts\lab_check.py --source 0 --frames 5` while an empty vial is parked. Snapshots go to `outputs\lab_check\`. |
| 15-50 | Record the run(s); one recording per batch | `python scripts\lab_capture.py --source 0 --name run1 --process --run-plan plan.csv`. Watch the preview: states should cycle no carrier → moving → parked → pouring → parked → moving. |
| 50-55 | Check results | `outputs\vials\run1\records.jsonl` has one line per filled vial; the extract summary shows "N/N vials measured". |
| 55-60 | Back up | Copy `outputs\lab\` and `outputs\vials\run*` to the drive. Note anything unusual (lighting, people in view, recipe changes). |

Write down the wall-clock start and end of each recording and any recipe changes the operator makes.

## If something goes wrong

| Symptom | Meaning | What to do |
| --- | --- | --- |
| `--list-cameras` finds nothing, or no direct access | Camera not available to us | Ask for recordings from their system; process later with `python scripts\extract_vials.py --video-file <file> --run-plan plan.csv`. |
| `lab_check` FAIL size | Camera not at 640x480 | Ask staff whether the resolution can be set back; otherwise record anyway and note it. |
| `lab_check` FAIL camera shift | View moved since the dataset | **Record anyway.** The config can be re-measured from the recording afterwards; that recording is then calibration data, so evaluate on a different run. |
| `lab_check` WARN roi_drift | Small move (≤ 12 px) | Fine; the detector uses the detected ROI and says so. |
| Preview stays "no carrier" with a vial parked | Collar not where the config expects | Same as camera shift: record anyway. |
| Preview never shows "pouring" | Clear or very pale liquid | Expected for pale recipes; those vials will report `low_contrast` / `no_liquid_detected`. |
| Recorder warns about delivered fps | Camera delivers a different rate than written | Stop and restart with `--fps <delivered rate>`. |
| White patch L outside 61-71 | Lighting differs from the dataset days | Fine; measurements can use `--white-balance white_patch`. |

## After the lab

- Re-run extraction with white balance if lighting differed: `python scripts\extract_vials.py --video-file outputs\lab\run1.mp4 --run-plan plan.csv --white-balance white_patch`.
- Spot-check a few vials: `python scripts\detect_vial_color.py <settled frame> --reference <ref frame> --debug-overlay check.png`.
- Share `records.jsonl` with Digital Twin & Integration for the dashboard; it uses the `MeasuredAppearance` shape in [interfaces.md](../interfaces.md).
- Record what happened (camera access, shift, how many vials measured) in [cv-data.md](cv-data.md).
