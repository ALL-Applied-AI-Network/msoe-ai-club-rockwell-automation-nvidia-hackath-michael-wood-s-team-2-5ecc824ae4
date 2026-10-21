# Lighting and reflection study (vial_fill camera)

Status: **Repo** findings from `scripts/stability_study.py` on the local Dataset 2 copy. Real line data, used for inspection and evaluation only; nothing here is training data.

Thresholds in `vialcv` (ROI, locator, event detection, segmentation) were set on **videos 1-4**. Video 5 was run once after they were fixed and is reported separately. Re-running the study does not tune anything.

## Reproduce

```text
# bash: export DATASET_ROOT=<path to csi-vial-fill-dataset>
# PowerShell: $env:DATASET_ROOT = "<path to csi-vial-fill-dataset>"
python scripts/extract_vials.py            # settled frames + empty references, outputs/vials/
python scripts/stability_study.py          # tables + plots, outputs/stability/
```

`stability_study.py` prints all tables below and writes `frames.csv`, `event_spreads.csv`, `backdrop.csv`, `recipe_positions.csv`, `static_object.csv`, and two plots.

## Main findings

1. **Short-term frame-to-frame noise is small.** Within one settled vial (5 frames over ~1.5 s), color moves by a median CIEDE2000 of 0.14-0.33 and at most 0.75 (p90) under every measurement setting. Glare masking and white balance do not matter at this timescale.
2. **Background behind the glass dominates.** The same liquid reads very differently against the white backdrop, the dark belt, and the bright puck bore (for example video 5 vial 8: median L 30.8, 12.4, 23.7). Hue is the most stable attribute across zones (within ~3-10 degrees). Compare colors **within one zone**; prefer the backlit zone, which exists only when the liquid reaches the backdrop (60 mL and up in video 5).
3. **Lighting changes between days and sometimes within a run.** The backdrop is about 8 L brighter on 2026-09-23 (videos 3-5) than on 2026-09-22 (videos 1-2). Videos 3 and 4 have repeated dips of 4-6 L lasting tens of seconds (cause not verified; a shadow is possible).
4. **White-patch correction removes those lighting changes on static surfaces.** Where lighting dipped (video 4), a metal rail that is not part of the white reference went from 2.7 to 0.6 L spread across frames. Where lighting was steady, correction changed nothing meaningful. Whether it recovers the *true* liquid color across days is **not verified**: that needs the same liquid on both days, which this dataset does not have.
5. **Same-recipe vials: vials 2 and 3 agree; vial 1 differs.** On video 5, vial 2 vs vial 3 of a recipe differ by a median 0.9 dE00 (0.25-2.4 in the backlit zone), while vial 1 differs from vials 2 and 3 by a median ~11-12 (up to 27). This is consistent with the organizer process note that the first vial after a recipe change may be discolored. It is a measured-appearance difference, not a verified carryover model.

## A. Within-event spread

Max dE00 from any frame's color to the event's median color: median / p90 (n events). Same liquid mask for every setting, taken from the uncorrected frame.

| setting | calibration (videos 1-4) | evaluation (video 5) |
| --- | --- | --- |
| rect_mean (cv/color-baseline method) | 0.25 / 0.41 (n=30) | 0.27 / 0.45 (n=28) |
| segmented_mean (glare included) | 0.14 / 0.34 (n=30) | 0.27 / 0.56 (n=28) |
| segmented_median (glare excluded) | 0.16 / 0.38 (n=30) | 0.18 / 0.46 (n=28) |
| segmented_median_wb | 0.20 / 0.53 (n=30) | 0.24 / 0.51 (n=28) |
| backlit_median | 0.18 / 0.50 (n=29) | 0.33 / 0.75 (n=22) |
| backlit_median_wb | 0.22 / 0.51 (n=29) | 0.26 / 0.73 (n=22) |

Glare masking removed a median 2% of liquid pixels (max 8%).

Low stability numbers for `rect_mean` do **not** make it a good measurement: it is stable because it averages a fixed mix of glass, backdrop, belt, and liquid. Stability is necessary, not sufficient.

## B. Backdrop drift

White backdrop patch lightness L, over each video's stills.

| video | p5 | median | p95 | p95 - p5 |
| --- | --- | --- | --- | --- |
| 1 | 61.4 | 62.3 | 62.8 | 1.4 |
| 2 | 62.1 | 62.2 | 63.7 | 1.6 |
| 3 | 65.7 | 69.4 | 70.6 | 4.9 |
| 4 | 64.7 | 68.6 | 70.7 | 6.0 |
| 5 | 69.3 | 70.1 | 70.7 | 1.4 |

## C. Same-recipe vial positions (video 5)

dE00 between vial positions of one recipe, measured in a background zone both vials share (backlit if both have it, else bore). Median over recipes 5-13 (recipe 14 is too pale to segment; see segmentation notes):

| pair | dE00 raw | dE00 white-balanced |
| --- | --- | --- |
| 1-2 | 11.05 | 10.89 |
| 1-3 | 11.90 | 11.90 |
| 2-3 | 0.87 | 1.23 |

Per recipe, 2-3 is under 2.5 in the backlit zone (recipes 7-13). Recipes 5 and 6 are low fills measured in the bore, where 2-3 is 5-6; the bore zone is noisier. Recipe 9 vial 1 is only ~3 from vials 2-3; recipe 8 before it has a similar hue. Recipe 5 is the first recipe of the run, so its vial 1 follows liquid not described in the labels.

## D. White balance on static surfaces

| video | surface | L p95-p5 raw | L p95-p5 corrected | median dE00 raw | median dE00 corrected |
| --- | --- | --- | --- | --- | --- |
| 1 | left rail | 0.85 | 0.67 | 0.32 | 0.32 |
| 4 | left rail | 2.71 | 0.55 | 0.76 | 0.24 |
| 4 | far backdrop | 5.87 | 0.99 | 1.49 | 0.53 |
| 5 | left rail | 0.62 | 0.61 | 0.29 | 0.35 |

The far backdrop is the same paper as the white reference, so it partly measures the method against itself; the rail is independent. The puck face was tried first and rejected: liquid color reflects off the aluminum and differs per vial. Full table in `static_object.csv` (video 3 has only 10 measurable frames here, none in a dip).

## Recommendations

- Report color per background zone and say which zone; do not average over the whole liquid column.
- Use the backlit zone for comparing vials when it is present; fall back to the same zone for both vials.
- Use `white_patch` correction when comparing across runs or days, and record the gains; it is harmless within steady runs.
- Use the robust median; at this timescale it is no less stable than the mean, and it excludes glare by construction.
- For future collection: put a fixed color reference (for example a printed color card) in view, so cross-day color correction can be checked, not only assumed.

## Limits

- The settled window is short (often under 3 s), so only short-term stability is measured per vial.
- Videos 1-4 are unlabeled and tank colors differ between runs, so cross-run color accuracy cannot be evaluated.
- 6 of 64 vials (4 in video 3, 2 in video 5) are too pale for segmentation and are absent from these tables.
- Per-still labels in `video5_frame_labels.csv` are not used: their `video_s` drifts from video time by ~18% (see [cv-data.md](cv-data.md), "Findings that affect other work").
