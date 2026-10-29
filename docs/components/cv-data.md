# Computer Vision & Data

Owner: Corbin; second person **TBD**.

## Purpose and scope

Turn vial images into reusable liquid-color measurements, and characterize when those measurements are unreliable.

In scope: Dataset 2 image/video exploration, liquid-region selection, OpenCV color measurement, lighting/reflection notes, metadata and quality reporting.

Out of scope: training models on real line images; automatic defect classification; recipe mixing physics; running Isaac Sim.

Liquid-region selection is required. A particular segmentation technique is **not**. A fixed ROI is acceptable if evaluation shows it reliably selects liquid under the intended operating conditions.

## Inputs

- A vial image: a full `vial_fill` camera frame (640x480), a crop of the configured vial ROI, or another vial crop. Real inspect/eval images or twin renders.
- Optional: a fixed ROI `X Y WIDTH HEIGHT`; an empty-vial reference image with the same framing; a white-balance method.
- Optional metadata if known: camera, video id, frame, timestamp, vial, recipe. Unknown stays unknown.

Local data lives outside git. Use `$DATASET_ROOT`, not machine-specific paths.

## Outputs

- `scripts/measure_color.py` (baseline): mean RGB of a rectangle, HSV/LAB of that mean, optional JSON.
- `scripts/detect_vial_color.py` / `vialcv.detect.detect_vial_color()`: a `MeasuredAppearance`-shaped record ([interfaces.md](../interfaces.md), proposed) with robust RGB, circular-hue HSV, and Lab per background zone, the zone used for the headline color, fill state and fill line, white-balance gains, quality codes, and provenance. Color fields are null on failure.

## Dependencies

- Recipe workstream: none for measurement. Needed later for comparison.
- Twin workstream: synthetic images if/when available. Measurements taken from an image are derived records: keep that image's origin in `sources` ([interfaces.md](../interfaces.md)). `detect_vial_color` geometry is configured for the real `vial_fill` camera; twin `FillCam` renders would need their own camera config.
- Official labels: `video5_vial_recipes.*` and `video5_frame_labels.csv` for inspect/eval context only. See the label-timing finding below before using `video5_frame_labels.csv`.

## Current achievement (repo)

### Baseline (`cv/color-baseline`)

- `scripts/measure_color.py`: image path; `--roi X Y WIDTH HEIGHT` or `cv2.selectROI`; mean RGB; HSV/LAB of that mean; optional JSON; rejects invalid rectangles.

### Color measurement (`cv/color-measurement`, PR into `cv/color-baseline`)

Package `vialcv/` with scripts and tests. `measure_color.py` keeps its CLI and output (verified identical on 9 ROIs x 3 frames) and now imports from `vialcv.measure`.

| Piece | File | What it does |
| --- | --- | --- |
| Dataset access | `vialcv/dataset.py` | `$DATASET_ROOT`, indexes, labels, video frames, frame/time conversion |
| Camera config | `configs/cameras/vial_fill.json`, `vialcv/roi.py` | Fixed regions and reference lines for the `vial_fill` camera |
| Vial locator | `vialcv/locate.py` | Confirms the configured ROI from the collar, puck, and walls; detected ROI on drift; codes for off-station/not found |
| Fill events | `vialcv/events.py`, `scripts/extract_vials.py` | Finds carrier dwells, pours, and the settled window in video; saves settled frames and a pre-pour empty reference per vial |
| Segmentation | `vialcv/segment.py` | Liquid vs empty reference or camera empty profile; walls, meniscus, glare excluded; fill state; background zones |
| Color statistics | `vialcv/colorstats.py` | Per-pixel median/trimmed mean/MAD (RGB, Lab), saturation-weighted circular hue, CIEDE2000 |
| White balance | `vialcv/whitebalance.py` | `white_patch` (backdrop to neutral), `gray_world`, `none` |
| Detection | `vialcv/detect.py`, `scripts/detect_vial_color.py` | One image in, measured-appearance record out |
| Calibration/evaluation | `scripts/roi_overlay.py`, `evaluate_locate.py`, `calibrate_empty_profile.py`, `segment_vials.py`, `stability_study.py` | Reproduce every number below |

Tests: `pytest` (85 tests, synthetic images; one real-data smoke test runs only when `DATASET_ROOT` is set). Dev install: `pip install -r requirements-dev.txt`. `requirements.txt` pins `numpy==2.5.4`, which needs Python 3.12+.

Calibration and evaluation split: all thresholds and config values were set on **videos 1-4**; video 5 was run once after they were fixed. `configs/cameras/vial_fill_empty_profile.json` holds per-row numbers derived from 33 empty-vial frames of videos 1-4 (`data_origin: real_line`, no images).

### Usage

PowerShell (bash: `export DATASET_ROOT=...`):

```text
$env:DATASET_ROOT = "<path to csi-vial-fill-dataset>"

# One image -> color and fill level (add --json for the full record)
python scripts/detect_vial_color.py <frame.png|.jpg> [--reference <empty frame>] [--white-balance white_patch] [--data-origin real_line] [--debug-overlay out.png]

# Settled frames and empty references from the videos -> outputs/vials/
python scripts/extract_vials.py [--videos 1 2 3 4 5] [--reuse-signals]

# Studies and checks -> outputs/
python scripts/roi_overlay.py
python scripts/evaluate_locate.py [--videos 5]
python scripts/segment_vials.py
python scripts/stability_study.py
```

`detect_vial_color.py` exits 0 when a color was measured, 1 on a quality failure (the record says why), 2 on usage errors.

Lab runs: `scripts/lab_check.py` (camera view vs config, READY / NOT READY), `scripts/lab_capture.py` (record a camera with a live state preview, then extract), and `extract_vials.py --video-file <recording> --run-plan plan.csv` (any recording; times use the file's frame rate; writes `records.jsonl`, one record per vial). Step-by-step: [cv-lab-runbook.md](cv-lab-runbook.md).

### Results

| Check | Calibration (videos 1-4) | Evaluation (video 5) |
| --- | --- | --- |
| Camera drift between videos (static scene) | < 0.15 px | < 0.15 px |
| Locator confirms configured ROI on stills | 873 / 888 (rest: moving carriers, small drift) | 808 / 845 (rest: 16 empty station, ~13 moving, ~1-3 misses) |
| Fill events vs `videos.csv` vial counts | 19 / 3 / 6 / 6, all match | 30 / 30; all matched to label vials; pour end median 0.8 s before label end |
| Segmentation (last settled frame per vial) | 30 measured, 4 pale/clear not measurable | 28 measured (1 via camera profile, no pre-pour frame), 2 pale not measurable |
| Fill state vs labeled volume | n/a (unlabeled) | 30 mL in view (y 325-332), 40 mL in view (y 293-300), 60-80 mL at or above view top |

Details: [cv-lighting-study.md](cv-lighting-study.md) (stability, background zones, white balance, same-recipe vials).

### Findings that affect other work

- **Per-still label timing.** In all five videos the burned-in clock advances ~1.21-1.22 s per video second (frames captured at ~24.7 fps, encoded at 30 fps). `video5_vial_recipes.*` start/end times match video time (event detection agreed within ~1-2 s). `video5_frame_labels.csv` computes each still's `video_s` from wall-clock time, so it drifts from video time by ~18% (~290 s by the end of video 5) and its per-still `in_fill`/`vial` labels are unreliable. The stills also stop ~17% before the end of each video's clock span.
- **Background zones.** The same liquid reads very differently against the white backdrop, the dark belt, and the bright puck bore (for example L 31 / 12 / 24). Compare colors within one zone; hue is the most stable attribute across zones.
- **Visible fill range.** The visible column resolves fills up to about 45 mL (~10 mL per 32 px); 60-80 mL fills reach the top of the view.
- **Tank colors differ by run.** Videos 1-4 show blue, orange, green, cyan, and pale liquids; recipe 5 in video 5 looks green although the README names T-200 orange and T-400 blue.
- **First vial of a recipe.** On video 5, vials 2 and 3 of a recipe differ by median 0.9 dE00; vial 1 differs from them by ~11-12. Consistent with the organizer process note; measured appearance only.
- **Dataset copy.** The official zip contains three byte-identical `(1).jpg` duplicates not in `image_index.csv`; loading through the index ignores them.

### Limitations

- Pale and clear liquids (video 3; video 5 recipe 14) are reported as `low_contrast` or `no_liquid_detected`, not measured. Detecting them needs a surface-edge method.
- Fill level is in pixels; no mL calibration. Above ~45 mL the level is hidden by the collar.
- Crops that are not the configured vial ROI have no background zones, no camera profile, and no white patch; they only work for strongly colored liquid.
- White balance removes lighting changes on static surfaces (video 4 rail: L spread 2.7 -> 0.6); recovering true color across days is not verified, because no liquid appears on both days.
- The settled window before a carrier leaves is short (often under 3 s); one video-5 vial poured until departure and is marked `short_settle`.
- Geometry is specific to the real `vial_fill` camera; other cameras and twin renders need their own config.

## Initial baseline milestone

A teammate can run the measurement tool on an image they provide, get RGB/HSV/LAB for a chosen region, or a clear error for an invalid region.

The `cv/color-baseline` script is this milestone's implementation. Lighting robustness, metadata completeness, and liquid-region reliability across conditions are **not** part of this milestone.

## Workstream completion

All of the following, with usage notes a teammate can follow. Status is the author's assessment for review, not a team sign-off:

| Requirement | Status on `cv/color-measurement` |
| --- | --- |
| **Reliable liquid-region selection** in the intended operating conditions | Evidence for colored liquids (locator and segmentation results above); pale/clear liquids not covered |
| **RGB, HSV, and LAB** with the aggregation method named | Done (`method`, `per_pixel_robust`, `primary_zone`) |
| **Relevant metadata** when known; unknown stays unknown | Record fields present; extraction fills video, frame, and video-5 vial/recipe where unambiguous |
| **Explicit failure/quality reporting**; no guessed color | Done (`quality.code`, null color on failure) |
| **Evaluation across multiple images and conditions** without tuning on the evaluation set | Calibration on videos 1-4, single evaluation run on video 5; see results and lighting study |
| **Reproducible usage instructions** | Usage section above |

## Next bounded milestone

Date: **TBD**.

The previous milestone (fixed ROI stays on liquid; how lighting and reflections move color) is addressed by the results above and [cv-lighting-study.md](cv-lighting-study.md).

**Proposed**, not agreed:

- Re-map stills to video time using the measured clock rate, so per-still labels can be corrected.
- Surface-edge detection for pale/clear liquids.
- A camera config for twin `FillCam` renders once twin images exist.

## Data-use reminder

Look at real frames to understand the station. Do not train on them. See [project-context.md](../project-context.md).
