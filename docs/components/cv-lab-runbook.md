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
| 0-10 | Find the camera and check the view | `python scripts\lab_check.py --list-cameras` saves `outputs\lab_check\camera_<N>.png` for each camera. Open them and pick the index **N** that shows the vial_fill station (a laptop's own webcam is usually 0). Then `python scripts\lab_check.py --source N` with a vial parked. Want **READY**. "READY (camera shift NOT checked)" means `DATASET_ROOT` is missing or wrong: fix it, or compare the overlay by eye. |
| 10-15 | Test recording (20-30 s) | `python scripts\lab_capture.py --source N --name test --duration 25`. Check that the preview shows the station and that no frame-rate warning appears at the end. Optional backup: `python scripts\lab_check.py --source N --frames 5` while an empty vial is parked (extraction already saves one empty reference per vial). |
| 15-50 | Record the run(s); one recording per batch | `python scripts\lab_capture.py --source N --name run1 --process --run-plan plan.csv`. Watch the preview: states should cycle no carrier → moving → parked, waiting → pouring → settling → settled, measured → moving. The right-hand panel adds one row per filled vial (color swatch, zone, fill); check its "vials filled" count against the vials that actually ran. |
| 50-55 | Check results | The extract summary's "N with pours" must equal the number of vials that ran; if it doesn't, no IDs are assigned (see below). `outputs\vials\run1\records.jsonl` has one line per detected filled vial, and the summary shows "N/N vials measured". |
| 55-60 | Back up | Copy `outputs\lab\` and `outputs\vials\run*` to the drive. Note anything unusual (lighting, people in view, recipe changes). |

Write down the wall-clock start and end of each recording, how many vials ran, and any recipe changes the operator makes.

### Live per-vial readout

The preview panel measures each vial while it is settled (re-measured every second until the carrier leaves) and logs it to `outputs\lab\<name>_live.jsonl`.
- With `--run-plan`, each vial shows its recipe and its position within the recipe, taken from the plan by **live fill order**. A missed pour (pale liquid) shifts every later ID, so treat the IDs as provisional and check the "vials filled" count.
- When the second vial of a recipe settles, the panel compares it with the first. If they differ by more than `--flag-de00` (default 5), the first vial gets a red **FLAG** box. The flag appears when vial 2 settles, not when vial 1 does.
- What a flag means: the first vial of a recipe looks different from the next one. It is a measured-appearance check, not a carryover model or an expected color. The default threshold was chosen after looking at video 5, so the lab recording is its first independent test.
- The authoritative per-vial records still come from `extract_vials.py` (`--process`).
- Replaying video 5 (`--source <vial_fill_video_5.mp4> --run-plan <plan from the labels>`) gave 30/30 vials, live colors within a median 0.06 dE00 of `extract_vials`, and flags on the first vial of 8 of 10 recipes. Recipe 9's first vial is ~3 dE00 off, under the threshold; recipe 14 is too pale to measure.

Recordings are written on the **dataset clock**: frame rate × 1.215, so 30 fps for a camera delivering ~24.7. Every time threshold was calibrated on Dataset 2 videos, which were captured at ~24.7 fps but saved at 30. The MP4 therefore plays slightly fast. Real times are in `<name>_frames.csv`, and the rates in `<name>_capture.json`.

## If something goes wrong

| Symptom | Meaning | What to do |
| --- | --- | --- |
| `--list-cameras` finds nothing, or no direct access | Camera not available to us | Ask for recordings from their system; the system that recorded Dataset 2 already writes on the dataset clock. Process them later with `python scripts\extract_vials.py --video-file <file> --run-plan plan.csv`. For a video saved at its true frame rate by some other tool, add `--true-rate`. |
| `lab_check` FAIL size | Camera not at 640x480 | Ask staff whether the resolution can be set back; otherwise record anyway and note it. |
| `lab_check` FAIL camera shift | View moved since the dataset | **Record anyway.** The config can be re-measured from the recording afterwards; that recording is then calibration data, so evaluate on a different run. |
| `lab_check` WARN roi_drift | Small move (≤ 12 px) | Fine; the detector uses the detected ROI and says so. |
| Preview stays "no carrier" with a vial parked | Collar not where the config expects | Same as camera shift: record anyway. |
| Preview never shows "pouring" for a vial | Clear or very pale liquid | That vial may not be detected at all, and then it gets no record. If its pour was detected, it reports `low_contrast` / `no_liquid_detected`. Note which vial it was. |
| "WARNING: N filled vials detected but the run plan has M" | A pour was missed (pale vial) or an extra one was detected | No IDs are assigned, rather than shifting them onto the wrong vials. Edit `plan.csv` to list only the detected vials in order, then re-run `python scripts\extract_vials.py --video-file outputs\lab\run1.mp4 --run-plan plan.csv --reuse-signals`. |
| Recorder warns that the delivered rate changed while recording | The camera's rate changed after it was measured | The file's clock is off by that ratio. Record again with `--fps <rate printed in the warning>`. |
| White patch L outside 61-71 | Lighting differs from the dataset days | Fine; measurements can use `--white-balance white_patch`. |

## After the lab

- Re-run extraction with white balance if lighting differed: `python scripts\extract_vials.py --video-file outputs\lab\run1.mp4 --run-plan plan.csv --white-balance white_patch`.
- Spot-check a few vials: `python scripts\detect_vial_color.py <settled frame> --reference <ref frame> --debug-overlay check.png`.
- Share `records.jsonl` with Digital Twin & Integration for the dashboard. It uses the proposed (not agreed) `MeasuredAppearance` shape in [interfaces.md](../interfaces.md), plus an `event` block added by extraction. Say so when handing it over.
- Record what happened (camera access, shift, how many vials measured) in [cv-data.md](cv-data.md).
