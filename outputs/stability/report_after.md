
A. Within-event spread, max dE00 to event median: median / p90 (n events)

| setting | calibration (videos 1-4) | evaluation (video 5) |
| --- | --- | --- |
| rect_mean | 0.25 / 0.41 (n=30) | 0.27 / 0.45 (n=28) |
| segmented_mean | 0.14 / 0.34 (n=30) | 0.27 / 0.56 (n=28) |
| segmented_median | 0.16 / 0.38 (n=30) | 0.18 / 0.46 (n=28) |
| segmented_median_wb | 0.20 / 0.53 (n=30) | 0.24 / 0.51 (n=28) |
| backlit_median | 0.18 / 0.50 (n=29) | 0.33 / 0.75 (n=22) |
| backlit_median_wb | 0.22 / 0.51 (n=29) | 0.26 / 0.73 (n=22) |

Glare fraction of liquid pixels:

| split | count | 50% | max |
| --- | --- | --- | --- |
| video 5 | 140.0 | 0.018 | 0.077 |
| videos 1-4 | 150.0 | 0.022 | 0.06 |

B. White backdrop patch lightness L per video (stills):

| video_id | p5 | median | p95 | p95_minus_p5 |
| --- | --- | --- | --- | --- |
| 1 | 61.4 | 62.3 | 62.8 | 1.4 |
| 2 | 62.1 | 62.2 | 63.7 | 1.6 |
| 3 | 65.7 | 69.4 | 70.6 | 4.9 |
| 4 | 64.7 | 68.6 | 70.7 | 6.0 |
| 5 | 69.3 | 70.1 | 70.7 | 1.4 |

C. Video 5 same-recipe dE00 between vial positions (shared zone):

| recipe_id | pair | zone | de00_raw | de00_wb |
| --- | --- | --- | --- | --- |
| 5 | 1-2 | bore | 8.74 | 8.73 |
| 5 | 1-3 | bore | 12.05 | 12.41 |
| 5 | 2-3 | bore | 5.48 | 5.75 |
| 6 | 1-2 | bore | 21.89 | 21.9 |
| 6 | 1-3 | bore | 26.27 | 25.83 |
| 6 | 2-3 | bore | 6.08 | 5.73 |
| 7 | 1-2 | backlit | 23.85 | 23.12 |
| 7 | 1-3 | backlit | 24.35 | 24.17 |
| 7 | 2-3 | backlit | 0.69 | 1.23 |
| 8 | 1-2 | backlit | 11.05 | 10.94 |
| 8 | 1-3 | backlit | 11.9 | 11.9 |
| 8 | 2-3 | backlit | 1.37 | 1.45 |
| 9 | 1-2 | backlit | 2.99 | 2.95 |
| 9 | 1-3 | backlit | 2.83 | 2.51 |
| 9 | 2-3 | backlit | 0.79 | 0.7 |
| 10 | 1-2 | backlit | 11.11 | 10.89 |
| 10 | 1-3 | backlit | 11.06 | 11.06 |
| 10 | 2-3 | backlit | 0.25 | 0.27 |
| 11 | 1-2 | backlit | 9.96 | 9.78 |
| 11 | 1-3 | backlit | 10.76 | 10.88 |
| 11 | 2-3 | backlit | 0.87 | 1.16 |
| 12 | 1-2 | backlit | 26.08 | 25.52 |
| 12 | 1-3 | backlit | 27.47 | 26.8 |
| 12 | 2-3 | backlit | 2.43 | 2.16 |
| 13 | 1-2 | backlit | 10.02 | 10.12 |
| 13 | 1-3 | backlit | 9.95 | 9.82 |
| 13 | 2-3 | backlit | 0.34 | 0.43 |

Median over recipes:

| pair | de00_raw | de00_wb |
| --- | --- | --- |
| 1-2 | 11.05 | 10.89 |
| 1-3 | 11.9 | 11.9 |
| 2-3 | 0.87 | 1.23 |

D. Static surface color across frames, raw vs white-balanced (dE00 to per-video median):

| video_id | surface | n_frames | L_p95_minus_p5_raw | de00_median_raw | L_p95_minus_p5_wb | de00_median_wb |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | left_rail | 95 | 0.85 | 0.32 | 0.67 | 0.32 |
| 1 | far_backdrop | 95 | 1.84 | 0.39 | 0.63 | 0.32 |
| 2 | left_rail | 15 | 0.29 | 0.23 | 0.29 | 0.26 |
| 2 | far_backdrop | 15 | 0.25 | 0.2 | 0.21 | 0.14 |
| 3 | left_rail | 10 | 0.26 | 0.08 | 0.3 | 0.27 |
| 3 | far_backdrop | 10 | 0.6 | 0.17 | 0.39 | 0.43 |
| 4 | left_rail | 30 | 2.71 | 0.76 | 0.55 | 0.24 |
| 4 | far_backdrop | 30 | 5.87 | 1.49 | 0.99 | 0.53 |
| 5 | left_rail | 140 | 0.62 | 0.29 | 0.61 | 0.35 |
| 5 | far_backdrop | 140 | 1.26 | 0.23 | 0.74 | 0.38 |

wrote outputs/stability/ (frames.csv, event_spreads.csv, backdrop.csv, recipe_positions.csv, static_object.csv, event_spreads.png, backdrop_drift.png)
