# Computer Vision & Data

Owner: Corbin; second person **TBD**.

## Purpose and scope

Turn vial images into reusable liquid-color measurements, and characterize when those measurements are unreliable.

In scope: Dataset 2 image/video exploration, liquid-region selection, OpenCV color measurement, lighting/reflection notes, metadata and quality reporting.

Out of scope: training models on real line images; automatic defect classification; recipe mixing physics; running Isaac Sim.

Liquid-region selection is required. A particular segmentation technique is **not**. A fixed ROI is acceptable if evaluation shows it reliably selects liquid under the intended operating conditions.

## Inputs

- A vial image path (real inspect/eval images or twin renders).
- Optional fixed ROI `X Y WIDTH HEIGHT`, else interactive selection in the current baseline.
- Optional metadata if known: camera, video id, timestamp, vial, recipe. Unknown stays unknown.

Local data lives outside git. Use `$DATASET_ROOT`, not machine-specific paths.

## Outputs

- Mean RGB of the selected region, plus HSV and LAB derived from that mean (see [interfaces.md](../interfaces.md)).
- JSON when requested: image ref, ROI, pixel count, method, values.
- Failure when the image cannot be read or the rectangle is empty/out of bounds.

## Dependencies

- Recipe workstream: none for measurement. Needed later for comparison.
- Twin workstream: synthetic images if/when available. Measurements taken from an image are derived records: keep that image's origin in `sources` ([interfaces.md](../interfaces.md)).
- Official labels: `video5_vial_recipes.*` and `video5_frame_labels.csv` for inspect/eval context only.

## Current achievement (repo)

On branch `cv/color-baseline` (not claimed present on every branch):

- `scripts/measure_color.py`: image path; `--roi X Y WIDTH HEIGHT` or `cv2.selectROI`; mean RGB; HSV/LAB of that mean; optional JSON; rejects invalid rectangles.
- `requirements.txt` pins `numpy==2.5.4` and `opencv-python==5.0.0.93`.
- No committed automated test suite.

Reported interactive checks (not in git): a known synthetic BGR image matched RGB order and mean; an out-of-bounds rectangle was rejected; a fixed ROI reproduced an earlier measurement exactly.

Local environment observed while documenting (not a repo pin): Python 3.12.7; `numpy 2.5.4`; `cv2.__version__` reports `5.0.0` for the pinned `opencv-python==5.0.0.93` wheel.

Limitations of this achievement:

- Manual/fixed rectangle. Reliability of that rectangle as a liquid region is not yet evaluated across images or conditions.
- Mean includes every pixel in the ROI (glare, glass, background).
- JSON `image` is an absolute filesystem path.
- No provenance/`intended_use` fields yet.

Unimplemented: multi-image evaluation, quality objects, usage docs in-repo, and any automatic segmentation. Do not treat those as present.

## Initial baseline milestone

A teammate can run the measurement tool on an image they provide, get RGB/HSV/LAB for a chosen region, or a clear error for an invalid region.

The `cv/color-baseline` script is this milestone's implementation. Lighting robustness, metadata completeness, and liquid-region reliability across conditions are **not** part of this milestone.

## Workstream completion

All of the following, with usage notes a teammate can follow:

- **Reliable liquid-region selection** in the intended operating conditions. Method is open: evaluated fixed ROI, interactive ROI with recorded coordinates, or another selector. Reliability must be shown, not assumed.
- **RGB, HSV, and LAB** measurements of that region, with the aggregation method named.
- **Relevant metadata** when known (image ref, camera, time, vial/recipe); unknown stays unknown.
- **Explicit failure/quality reporting** (unreadable image, invalid region, and similar cases). Do not emit a guessed color.
- **Evaluation across multiple images and conditions** (for example lighting or reflections) on inspect/eval data, without treating repeated real-example tuning as independent evaluation.
- **Reproducible usage instructions**.

## Next bounded milestone

Date: **TBD**.

Keep the existing ROI measurement. On a small inspect-only set of real frames, record whether a fixed (or recorded) ROI stays on liquid and how lighting and reflections move the mean RGB. Do not train on those frames.

## Data-use reminder

Look at real frames to understand the station. Do not train on them. See [project-context.md](../project-context.md).
