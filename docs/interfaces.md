# Proposed interfaces

**Proposed, not agreed.** Changing these records is a cross-workstream change; say so in the PR or review notes.

The point of the split: a number taken from camera pixels is **not** the same quantity as a number estimated from recipe volumes.

## Two color quantities

| Record | Meaning | Produced by |
| --- | --- | --- |
| `MeasuredAppearance` | What the camera image looks like in a region | CV & Data |
| `ExpectedColor` | Model estimate of mixture color from recipe/process context | Recipe & Carryover |

Do not store them in one undifferentiated `color` field. Do not assume linear averaging of RGB (or of HSV/LAB) models physical mixing.

Synthetic images from the twin are still **measured appearance** once rendered and read back from pixels. They are not expected color.

## Color-space conventions (proposed)

Match the current CV baseline unless a later change is agreed:

- Images are loaded by OpenCV as BGR. Report **RGB** to humans and JSON.
- `rgb_0_255`: mean of the region after BGR→RGB, each channel on a 0–255 scale (float OK).
- Derived HSV/LAB are converted **from that mean RGB**, not averaged per pixel. Method name: `mean_rgb_then_convert`.
- OpenCV float `COLOR_RGB2HSV` after scaling RGB to 0–1: `h_degrees` (0–360), `s_0_1`, `v_0_1`.
- OpenCV float `COLOR_RGB2Lab`: `L`, `a`, `b` as returned by OpenCV.
- Always name the space and the aggregation. If a producer uses another method, change `method` and document it.
- **Proposed addition** (branch `cv/color-measurement`, not agreed): aggregation `per_pixel_robust`. Every pixel is converted with the same OpenCV float conversions, then summarized by median, 10% trimmed mean, and MAD (RGB 0-255, Lab); hue by a saturation-weighted circular mean with resultant length and circular std (degrees). CIEDE2000 comes from scikit-image; OpenCV float Lab agrees with scikit-image sRGB/D65 Lab to within dE00 0.32.

Expected color may use a different space. It must name `space` and `mixing_model` explicitly.

## Identifiers

If a value is not known, set it to `null` or omit it. **Do not invent** vial IDs, recipe IDs, timestamps, or camera names.

Useful keys when available:

- `camera_id`: `vial_fill` \| `tank_level` \| `cap_seal` \| `FillCam` \| `CapSealCam`
- `video_id`, `frame_index`, `timestamp`, `video_s`
- `vial_id`, `recipe_id`, `previous_recipe_id`
- `image_ref`: dataset- or twin-relative path, not a machine-specific absolute path

## Provenance (required on shared records)

**Proposed, not agreed.**

`data_origin` on a source asset is `real_line`, `digital_twin`, or `unknown`. Computed records may use `derived` or `mixed`, but those values **do not replace** source origin: `sources` must keep each input's origin. Setting `data_origin` to `derived` **alone is not allowed**.

```json
{
  "data_origin": "real_line | digital_twin | mixed | derived | unknown",
  "intended_use": "inspect | evaluate | train | unknown",
  "generator": "optional string, e.g. measure_color.py or twin render command",
  "sources": [
    {
      "ref": "dataset- or twin-relative path, or record id",
      "data_origin": "real_line | digital_twin | unknown"
    }
  ]
}
```

Rules:

- Direct real frames or labels: `data_origin: real_line`. Direct twin renders: `digital_twin`.
- Transformed records (measurements, expected-color estimates, comparisons): keep `generator`, and set `data_origin` to `derived` **only if** `sources` lists each input with that input's `data_origin` and a `ref` when known.
- Mixed inputs (for example a comparison of a real-line measurement and a twin render): `data_origin: mixed`, plus the same `sources` list.
- Derived and mixed records **retain the stricter source restriction**. Any `real_line` source stays ineligible for model training. Relabeling a record as `derived` does not make real production data eligible for training.
- `intended_use` describes how the producer **intends** the record to be used. It is **not authorization**. `intended_use: train` does not override Dataset 2 or the team constraint when a source is `real_line`.
- Unknown origin stays `unknown`. Do not invent a twin origin to make training look allowed.

See [project-context.md](project-context.md).

## Proposed `MeasuredAppearance`

```json
{
  "schema": "processdna.measured_appearance.v0",
  "image_ref": "vial_fill/images/vial_fill_YYYYMMDD_HHMMSS_microseconds.jpg",
  "camera_id": "vial_fill",
  "video_id": 5,
  "timestamp": "2026-09-23 19:47:11.630429",
  "video_s": 1.63,
  "vial_id": 1,
  "recipe_id": 5,
  "roi_xywh": [120, 80, 40, 50],
  "pixel_count": 2000,
  "method": "mean_rgb_then_convert",
  "rgb_0_255": [12.3, 45.6, 78.9],
  "hsv_of_mean_rgb": {"h_degrees": 210.1, "s_0_1": 0.84, "v_0_1": 0.31},
  "lab_of_mean_rgb": {"L": 28.4, "a": 8.1, "b": -32.0},
  "quality": {"ok": true, "code": null, "detail": null},
  "provenance": {
    "data_origin": "derived",
    "intended_use": "inspect",
    "generator": "scripts/measure_color.py",
    "sources": [
      {
        "ref": "vial_fill/images/vial_fill_YYYYMMDD_HHMMSS_microseconds.jpg",
        "data_origin": "real_line"
      }
    ]
  }
}
```

Quality: `ok=false` for unreadable images, empty/out-of-bounds ROI, cancelled selection, or other failures. Include `code` such as `unreadable_image` or `invalid_roi`.

Current `measure_color.py` JSON is a partial implementation of this shape. It currently writes a resolved absolute `image` path and has no provenance or quality object. Aligning it is future work.

### Proposed extension (branch `cv/color-measurement`)

**Proposed cross-workstream change, not agreed.** `vialcv.detect.detect_vial_color()` and `scripts/detect_vial_color.py --json` emit the `MeasuredAppearance` fields above plus the blocks below. Consumers that read only the original fields keep working, with two differences noted after the example.

Why: the same liquid looks very different against the white backdrop, the dark belt, and the bright puck bore behind the vial (see [components/cv-lighting-study.md](components/cv-lighting-study.md)), so a single color for the whole vial mixes backgrounds. Colors should be compared within one zone.

```json
{
  "input": "full_frame | vial_crop | image",
  "roi_source": "config | detected | argument | whole_image",
  "pixel_count": 1145,
  "method": "mean_rgb_then_convert",
  "rgb_0_255": [1.0, 79.6, 112.1],
  "color": {
    "primary_zone": "backlit | bore | dark_background | whole_mask",
    "primary": {
      "ok": true,
      "pixel_count": 1145,
      "method": "per_pixel_robust",
      "rgb_0_255": {"median": [0, 80, 114], "trimmed_mean": [0.4, 80.1, 112.8], "mad_sigma": [0, 5.9, 7.4]},
      "hsv": {"h_circular_mean_degrees": 197.6, "h_resultant_length": 1.0, "h_circular_std_degrees": 1.16,
              "h_weighting": "saturation", "s_0_1_median": 1.0, "v_0_1_median": 0.447},
      "lab": {"median": {"L": 31.7, "a": -7.9, "b": -24.7}, "trimmed_mean": {}, "mad_sigma": {}},
      "mean_rgb_then_convert": {"rgb_0_255": [], "hsv_of_mean_rgb": {}, "lab_of_mean_rgb": {}}
    },
    "zones": {"backlit": {}, "dark_background": {}, "bore": {}},
    "whole_mask": {}
  },
  "fill": {"state": "in_view | at_or_above_view_top | unknown", "coordinates": "frame | image",
           "fill_line_y_px": null, "visible_top_y_px": 272, "height_above_puck_top_px": null},
  "segmentation": {"ok": true, "code": null, "method": "delta_e76_vs_empty_reference | delta_e76_vs_camera_empty_profile | lab_chroma_threshold",
                   "glare_fraction": 0.043, "interior_columns": [5, 46]},
  "white_balance": {"ok": true, "method": "none | white_patch | gray_world", "gains_rgb": [1, 1, 1],
                    "reference_rgb_0_255": null, "target_level": null},
  "quality": {"ok": true, "code": null, "detail": null, "warnings": []}
}
```

(Values from `scripts/detect_vial_color.py --json` on a video 5 settled frame of vial 9, abbreviated; `{}` marks blocks with the same shape as `primary`.)

Differences from the original proposal:

- `pixel_count` is the number of **liquid pixels in the primary zone** (after removing glass walls, meniscus, and glare), not the ROI area.
- `method` / `rgb_0_255` / `hsv_of_mean_rgb` / `lab_of_mean_rgb` are the `mean_rgb_then_convert` values **of the primary zone's liquid pixels**, not of the whole ROI.
- `image_ref` is whatever the caller passes (the CLI gives a dataset-relative path under `$DATASET_ROOT`, else the bare file name), never an absolute path.
- Fill is reported in pixels only. `at_or_above_view_top` means the surface is hidden by the collar; it is not a measured level.

Records written by `scripts/extract_vials.py` (`records.jsonl`) also carry an `event` block: `video_name`, `event_idx`, the event `quality`, and an `id_note` explaining how `vial_id`/`recipe_id` were set, or why they weren't. They also list the source video first in `provenance.sources`. These fields are proposed, like the rest of this extension.

Quality codes used: `unreadable_image`, `invalid_roi`, `invalid_reference`, `vial_not_found`, `vial_off_station`, `no_liquid_detected` (empty, clear, or very pale: indistinguishable by color), `low_contrast`, `mask_too_small`, `no_zone_with_enough_pixels`. Warnings (measurement still made): `roi_drift`, `assumed_config_vial_crop`, `unknown_crop_no_zones`, `white_balance_needs_full_frame`, `white_reference_occluded` and other white-balance codes, `glare_fraction_high`, `no_empty_reference_for_this_roi`.

## Proposed `ExpectedColor`

```json
{
  "schema": "processdna.expected_color.v0",
  "recipe_id": 7,
  "previous_recipe_id": 6,
  "volumes_ml": {"t100": 20, "t200": 0, "t400": 50},
  "dispense_order": "T400>T100",
  "tank_colors": {
    "t100": {"label": "clear", "note": "from video-5 labels; not a live tank sensor"},
    "t200": {"label": "orange"},
    "t400": {"label": "blue"}
  },
  "mixing_model": "unspecified",
  "carryover_model": "none",
  "space": "unspecified",
  "value": null,
  "quality": {"ok": false, "code": "not_implemented", "detail": "no recipe model in repo yet"},
  "provenance": {
    "data_origin": "derived",
    "intended_use": "inspect",
    "generator": null,
    "sources": [
      {
        "ref": "vial_fill/labels/video5_vial_recipes.csv",
        "data_origin": "real_line"
      }
    ]
  }
}
```

`mixing_model` must name the actual method (for example `volume_weighted_srgb_mean`) if a value is produced. That name does not make the method physically valid.

## Proposed later comparison (not started)

A comparison record would reference one measured appearance and one expected color, plus a delta in a named space, and optional `hypotheses` such as `carryover_from_previous_recipe` with an evidence note. Its provenance `sources` must include both inputs and their origins (`mixed` if they differ). Do not implement this until both producers exist.

## Failure reporting

Every producer should return a structured failure instead of a guessed color. Unavailable identifiers stay unknown. Partial records are allowed.
