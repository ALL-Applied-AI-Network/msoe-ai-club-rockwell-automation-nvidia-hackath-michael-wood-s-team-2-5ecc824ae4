# ProcessDNA — Digital Twin Task Checklist

**Project:** ProcessDNA for Fluid Mixing (CSI Station 3)  
**Date prepared:** October 28, 2026  
**Scope:** Digital Twin only — simulation, synthetic data, metadata, and data usability testing  
**Goal:** Give the CV/ProcessDNA team reproducible **recipe-labeled, time-ordered normal and abnormal synthetic runs** with honest ground truth and known limitations.

> **Checklist legend:** `[x]` = completed and verified; `[ ]` = remaining or not yet verified.  
> **Ownership:** **Rendering owner** = Isaac Sim and generator development; **Validation owner** = your friend (test scenarios, image usability, documentation); **Both** = handoff/integration. The CV/modeling team owns the actual detector, anomaly model, and RecipeTrace logic.

## 1. Completed — Rendering and Generators (Rendering owner)

- [x] Install and run Isaac Sim 6.0 headlessly on the MSOE GB10 through SSH.
- [x] Load the supplied CSI filling-station USD scene and use FillCam.
- [x] Generate representative PNG renders (`fillcam_686.png`, `green_vial.png`).
- [x] Render an MP4 demonstration of the animated filling station.
- [x] Create `generate_dataset.py` and render **8** shader-color variants: blue, dark blue, light blue, teal, green, red, purple, yellow.
- [x] Produce a metadata CSV for the eight-color dataset.
- [x] Create `generate_carryover_dataset.py` and render **15** carryover-*proxy* images: blue→green, green→red, red→blue at 0%, 1%, 5%, 10%, and 20% shader interpolation.
- [x] Produce carryover metadata that distinguishes proxy parameters from physical residue measurements.
- [x] Use the team's `measure_color.py` with a **manual ROI** on all eight color variants; all returned numeric RGB measurements. This is a generator sanity check, **not** full CV validation.

## 2. GitHub and Reproduction (Rendering owner; Both review)

- [x] Create clean `feature/digital-twin` branch from `origin/main`.
- [x] Create `digital_twin/` with tools, examples, and data directories.
- [x] Stage the three scripts, two example images, README, and progress report (**7 files confirmed staged**).
- [ ] Check why `digital_twin/data/synthetic_metadata.csv` and `digital_twin/data/carryover_metadata.csv` were not staged; review `.gitignore`, then add the two intended CSVs if allowed.
- [ ] Inspect `git diff --cached --stat` and `git diff --cached --name-only` (expect **9 files** if both CSVs are included).
- [ ] Commit the branch and push `feature/digital-twin` to the team's GitHub repository.
- [ ] Verify files are visible on GitHub; do **not** assume staged files have been uploaded.
- [ ] Review README reproduction instructions against the actual script arguments, paths, Isaac Sim version, camera config, and USD asset requirements.
- [ ] Confirm what CSI-provided assets are permitted to be committed/shared; do not publish restricted source assets or credentials.
- [ ] Decide how the full image/video datasets will be shared (repository, approved shared storage, or archives) without committing unnecessary bulk output.

## 3. Test Design and Data Usability (Validation owner / friend)

- [ ] Prepare the **20 proposed cases T01–T20** covering correct recipes, carryover, mixing errors, camera/lighting variation, fill level, obstruction, missing vial, and low contrast.
- [ ] Mark each case **GENERATED**, **NOT YET GENERATED**, or **BLOCKED**; do not imply that an unsupported scenario was tested.
- [ ] Organize generated images using stable filenames and a scenario/test-case mapping.
- [ ] Inspect camera framing, vial visibility, liquid contrast, reflections, and fill-level visibility for each supplied image.
- [ ] Run the existing CV scripts on the images; record outputs, errors, and whether the color measurement was valid.
- [ ] Track `low_contrast`, `vial_off_station`, and other image-quality failures **separately** from valid color mismatch decisions.
- [ ] Document actual RGB/Lab results, quality outcomes, and test blockers in a results sheet.
- [ ] Request additional renders or simulation modifications needed for blocked cases.
- [ ] Evaluate normal/abnormal PASS/FLAG behavior only when recipe targets and defensible labels exist; do not fabricate physical defect ground truth.

## 4. Temporal Data — Biggest Remaining Digital Twin Gap (Rendering owner + Validation owner)

- [ ] Define the **run-level schema**: run ID, recipe/phase, camera, frame, timestamp, simulation condition, expected visual event, event onset, and whether the label is synthetic/proxy.
- [ ] Verify what the provided USD animation actually changes over time (filling motion versus real mixing/color dynamics).
- [ ] Export **one reproducible normal time-ordered run** from a known recipe/condition.
- [ ] Export **one controlled abnormal time-ordered run** with a clearly documented visual perturbation and onset frame/time.
- [ ] Keep the normal and abnormal runs comparable (same camera, framing, baseline lighting, and relevant recipe context).
- [ ] Where feasible, create an abnormal run with similar final appearance but different observable history — the original ProcessDNA hypothesis. Treat this as a **goal, not a completed result**.
- [ ] Supply sequence-level metadata and expected change points to the CV/ProcessDNA team.
- [ ] Keep evaluation splits at the **run level**, not by randomly splitting neighboring frames.

## 5. Physical Lab and Simulation-to-Real Comparison (Both, with authorized testbed access)

- [ ] Confirm rules on real footage: synthetic data for training; only permitted uses of real data for inspection/evaluation/calibration.
- [ ] Confirm camera views, timestamps, recipe IDs, and whether synchronized camera footage is available.
- [ ] Capture or inspect approved known-good real FillCam examples for comparison (do not assume permissions for training).
- [ ] Compare synthetic versus real camera framing, vial ROI, reflections, exposure, background, apparent color, and fill-level visibility.
- [ ] Verify whether recipe changes and first-vial effects are visible and safely reproducible on the real equipment.
- [ ] Document sim-to-real differences and prioritize the synthetic scenarios needed to reduce them.

## 6. Modeling Boundaries and Scientific Honesty (Both)

- [ ] Keep **shader-color interpolation** labeled as a carryover *visual proxy*, **not** a physically validated residue/mixing model.
- [ ] Do not claim contamination affects only the first vial until the simulator represents vials independently and this behavior is demonstrated.
- [ ] Do not assign a physically meaningful PASS/FLAG outcome without recipe and fault ground truth.
- [ ] Treat `low_contrast` or `vial_off_station` as **quality/detection failures**, not proof of incorrect liquid.
- [ ] Separate your deliverables (rendered data, labels, reproducible generation, validation observations) from the CV/ProcessDNA team's detector, anomaly model, and RecipeTrace diagnosis.

## 7. Minimum Handoff for the Team (Both)

- [ ] Working generator scripts, README, and permitted source-asset instructions.
- [ ] A sample of generated PNGs/MP4 and the associated metadata CSVs.
- [ ] One normal and one controlled abnormal **time-ordered** synthetic run, with traceable onset/condition labels if feasible.
- [ ] A 20-case scenario matrix with generated/blocked/pending statuses.
- [ ] Recorded CV image-usability results and clear failure logs from the validation owner.
- [ ] Documented limitations and specific requests for the CV/ProcessDNA team.
- [ ] Update the progress report with only outcomes actually verified.

## Suggested priority order

1. **Finish the GitHub handoff**: include ignored metadata CSVs, review, commit, and push.
2. **Produce a normal/abnormal temporal pair** and frame-level metadata.
3. **Have your friend run the validation matrix** on available data, logging blocked tests.
4. **Compare against permitted real camera footage** and document realism gaps.
5. Improve first-vial-specific carryover/physics only if the assets and time support it.

**Reference:** Original ProcessDNA proposal emphasizes recipe-conditioned temporal monitoring, deviation onset, and evidence-qualified diagnosis. The digital twin supplies data and ground truth; other workstreams build the model and demonstration.
