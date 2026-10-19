# Computer Vision & Data

Owner: Corbin; second person **TBD**.

## Purpose and scope

Turn vial images into reusable liquid-color measurements, and characterize when those measurements are unreliable.

In scope: Dataset 2 image/video exploration, region extraction, OpenCV color measurement, lighting/reflection notes.

Out of scope: training models on real line images; automatic defect classification; recipe mixing physics; running Isaac Sim.

## Inputs

- A vial image path (real inspect/eval images or twin renders).
- Optional fixed ROI `X Y WIDTH HEIGHT`, else interactive selection in the current baseline.
- Optional metadata if known: camera, video id, timestamp, vial, recipe. Unknown stays unknown.

Local data lives outside git. Use `$DATASET_ROOT`, not machine-specific paths.

## Outputs

- Mean RGB of the selected region, plus HSV and LAB derived from that mean (see [interfaces.md](../interfaces.md)).
- JSON when requested: image ref, ROI, pixel count, method, values.
- Failure when the image cannot be read or the rectangle is empty/out of bounds.

Goal (team): code that accepts a vial image and returns liquid-color measurements. Automatic liquid segmentation is part of the workstream goal, not of the current baseline.

## Dependencies

- Recipe workstream: none for measurement. Needed later for comparison.
- Twin workstream: synthetic images if/when available. CV must label `data_origin` correctly.
- Official labels: `video5_vial_recipes.*` and `video5_frame_labels.csv` for inspect/eval context only.

## Observable completion

A teammate can run the measurement tool on an image they provide, get RGB/HSV/LAB for a chosen region, or a clear error for an invalid region.

Automatic liquid detection, lighting robustness, and interface-aligned JSON are **not** required to call the current baseline complete.

## Current evidence (repo)

On branch `cv/color-baseline`:

- `scripts/measure_color.py`: image path; `--roi X Y WIDTH HEIGHT` or `cv2.selectROI`; mean RGB; HSV/LAB of that mean; optional JSON; rejects invalid rectangles.
- `requirements.txt` pins `numpy==2.5.4` and `opencv-python==5.0.0.93`.
- No committed automated test suite.

Reported interactive checks (not in git): a known synthetic BGR image matched RGB order and mean; an out-of-bounds rectangle was rejected; a fixed ROI reproduced an earlier measurement exactly.

Local environment observed while documenting (not a repo pin): Python 3.12.7; `numpy 2.5.4`; `cv2.__version__` reports `5.0.0` for the pinned `opencv-python==5.0.0.93` wheel.

Limitations:

- Manual/fixed rectangle, not liquid detection.
- Mean includes every pixel in the ROI (glare, glass, background).
- JSON `image` is an absolute filesystem path.
- No provenance/`intended_use` fields yet.

## Next bounded milestone

Date: **TBD**.

Keep the existing ROI measurement. On a small inspect-only set of real frames, record how lighting and reflections move the mean RGB, without training and without claiming automatic vial finding.

## Data-use reminder

Look at real frames to understand the station. Do not train on them. See [project-context.md](../project-context.md).
