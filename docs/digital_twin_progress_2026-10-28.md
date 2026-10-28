# Digital Twin Progress Report

**Project:** ProcessDNA for Fluid Mixing  
**Date:** October 28, 2026  
**Workstream:** Digital Twin — Rendering, Synthetic Data, and Usability Testing  
**Platform:** NVIDIA GB10 / Isaac Sim 6.0  
**Status:** Initial synthetic-data generation complete; temporal scenario generation and validation handoff in progress.

## 1. Project Objective and Connection to ProcessDNA

Generate reproducible synthetic camera data from the CSI vial-filling digital twin to support the team's recipe-conditioned process monitoring, anomaly detection, and evidence-backed diagnosis.

The broader ProcessDNA concept goes **beyond checking final vial color**: it seeks to compare time-ordered visual observations with an expected recipe/process trajectory, identify when a deviation starts, and report supported explanations or **unknown** when evidence is insufficient.

The digital twin workstream provides **images/sequences, controllable simulation scenarios, and traceable metadata**. The CV and ProcessDNA teams own the measurement, detection, temporal modeling, and diagnostic algorithms.

## 2. Completed Work

### Isaac Sim setup and camera rendering

- Installed/configured Isaac Sim 6.0 on the MSOE NVIDIA GB10 server.
- Successfully ran the CSI digital twin headlessly via SSH.
- Loaded the supplied CSI filling-station USD scene and rendered using FillCam.
- Produced representative PNGs, including `fillcam_686.png` and `green_vial.png`.
- Generated an MP4 demonstration of the animated filling station.
- Developed a multi-frame rendering script, `render_video.py`.

### Synthetic color dataset — 8 images

- Developed `generate_dataset.py` to vary liquid shader appearance within one Isaac Sim session.
- Generated **8** distinct liquid-color variants: blue, dark blue, light blue, teal, green, red, purple, and yellow.
- Exported image files and a `metadata.csv` recording generator/scenario parameters.

### Preliminary color-measurement sanity check

- Ran the team's `measure_color.py` against **all 8** color variants using a **manually selected ROI**.
- All 8 produced numeric RGB measurements, and the reported values differed by color.
- This confirms the images can support a basic manual-ROI measurement workflow. It does **not** validate automatic vial detection, recipe conformance, defect classification, or root-cause diagnosis.
- Earlier detector trials encountered image-quality/detection statuses including `low_contrast` and `vial_off_station`; these still require systematic follow-up by the validation owner.

### Carryover visual-proxy dataset — 15 images

- Developed `generate_carryover_dataset.py`.
- Generated **15 PNGs** covering blue→green, green→red, and red→blue transitions at nominal **0%, 1%, 5%, 10%, and 20%** shader interpolation.
- Verified all 15 outputs were generated; recorded parameters in `metadata.csv`.
- Explicitly marked physical mixing validation and factory defect labels as unavailable/not validated in the metadata.

### Repository preparation (not yet confirmed published)

- Created clean `feature/digital-twin` branch from `origin/main`.
- Created `digital_twin/tools/`, `digital_twin/examples/`, and `digital_twin/data/` in the local `MAIC` checkout.
- Prepared a digital twin README and this progress report.
- **Seven files were confirmed staged locally**: the README, three scripts, two example PNGs, and the progress report.
- Two metadata CSVs exist in `digital_twin/data/` but **were not shown in the staged file list**; inspect ignore rules and include intentionally if appropriate.
- No Git commit/push confirmation has been provided yet; therefore **do not describe these files as already uploaded to GitHub**.

## 3. Current Files and Artifacts

### Staged locally (as last verified)

- `digital_twin/README.md`
- `digital_twin/tools/generate_dataset.py`
- `digital_twin/tools/generate_carryover_dataset.py`
- `digital_twin/tools/render_video.py`
- `digital_twin/examples/fillcam_686.png`
- `digital_twin/examples/green_vial.png`
- `docs/digital_twin_progress_2026-10-28.md`

### Present locally, Git staging still to confirm

- `digital_twin/data/synthetic_metadata.csv`
- `digital_twin/data/carryover_metadata.csv`

### Generated on the GB10 / outside the committed sample

- Eight synthetic color PNGs plus metadata.
- Fifteen carryover-proxy PNGs plus metadata.
- Filling-station MP4 demonstration.
- CSI USD scenes and supplied camera configurations (source assets; sharing permissions to be checked).

## 4. Important Limitations

1. **Shader proxy, not fluid physics.** Nominal carryover percentages interpolate material colors; they are not calibrated measurements of actual liquid residue.
2. **Shared material scope.** The current material edit may recolor multiple vials rather than one first post-change vial.
3. **Static variants are not temporal histories.** The eight colors and fifteen carryover-proxy images do not yet establish labeled normal/abnormal process trajectories with deviation onset.
4. **Measurement is not validation.** Manual-ROI RGB results do not show that automated CV reliably detects the vial or correctly returns recipe PASS/FLAG decisions.
5. **No physically validated ground truth.** No real-factory defect labels, root-cause diagnosis accuracy, or real-hardware evaluation have been established by this workstream.
6. **Simulation-to-real gap remains.** Camera framing, reflections, exposure, actual liquid appearance, and synchronization need comparison with permitted CSI test footage.

## 5. Division of Work

**Rendering / generator owner**

- Maintain GB10 and Isaac Sim environment.
- Create and improve scripts, render images and videos, and generate requested scenarios.
- Export simulator-derived parameters, frame timestamps, and known synthetic change points.

**Digital twin validation owner (friend)**

- Create the 20-case test matrix and organize the dataset.
- Check image suitability and run available CV scripts.
- Record `low_contrast`, `vial_off_station`, measured colors, and blocked scenarios separately from valid defect outcomes.
- Report which additional scenes/renders are needed.

**Other team workstreams**

- Own expected-recipe comparisons, automatic anomaly detection, temporal models, and RecipeTrace diagnosis.

## 6. Remaining Milestones — Priority Order

- [ ] **GitHub handoff:** Review `.gitignore`, include intended metadata CSVs, review staged files, commit and push `feature/digital-twin`.
- [ ] **Reproduction:** Check README commands, required CSI USD scenes/camera JSONs, permissions, and dataset storage strategy.
- [ ] **Scenario validation:** Friend prepares T01–T20 with generated/pending/blocked status and results.
- [ ] **Temporal normal run:** Render one timestamped normal process sequence with recipe/phase metadata.
- [ ] **Temporal abnormal run:** Render a comparable sequence with a documented observable deviation and onset frame.
- [ ] **Traceable labels:** Export run ID, recipe/phase, time/frame, condition, camera, and proxy/ground-truth status.
- [ ] **Real-camera comparison:** Compare synthetic framing, lighting, liquid visibility, and fill-level appearance against approved lab footage.
- [ ] **Optional fidelity improvements:** Independent first-vial material changes and more physically grounded carryover, only if technically feasible and supported by data.
- [ ] **Handoff:** Give the CV/ProcessDNA team representative data, run-level metadata, quality-test results, and explicitly documented limitations.

See `digital_twin_task_checklist.md` for owner-by-owner checkboxes and handoff detail.

## 7. Current Status Summary

**Verified:** Headless CSI FillCam rendering; PNG/MP4 output; 8 synthetic shader-color images; 15 carryover-proxy images; CSV metadata generation; manual-ROI RGB measurements on 8/8 color images; local feature branch and seven staged files.

**Not yet verified as complete:** Metadata CSV staging, GitHub push, systematic validation matrix, normal/abnormal recipe-labeled temporal sequences, first-vial-only carryover, physically validated mixing, and real-hardware validation.

**Bottom line:** The digital twin image-generation foundation works. The next highest-value contribution to the original ProcessDNA proposal is **reproducible, time-ordered, labeled synthetic runs**, followed by documented usability testing and a reliable handoff to the modeling team.
