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

Expected color may use a different space. It must name `space` and `mixing_model` explicitly.

## Identifiers

If a value is not known, set it to `null` or omit it. **Do not invent** vial IDs, recipe IDs, timestamps, or camera names.

Useful keys when available:

- `camera_id`: `vial_fill` \| `tank_level` \| `cap_seal` \| `FillCam` \| `CapSealCam`
- `video_id`, `frame_index`, `timestamp`, `video_s`
- `vial_id`, `recipe_id`, `previous_recipe_id`
- `image_ref`: dataset- or twin-relative path, not a machine-specific absolute path

## Provenance (required on shared records)

```json
{
  "data_origin": "real_line | digital_twin | derived | unknown",
  "intended_use": "inspect | evaluate | train | unknown",
  "generator": "optional string, e.g. measure_color.py or twin render command"
}
```

`real_line` + `train` contradicts official Dataset 2 guidance. See [project-context.md](project-context.md).

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
    "data_origin": "real_line",
    "intended_use": "inspect",
    "generator": "scripts/measure_color.py"
  }
}
```

Quality: `ok=false` for unreadable images, empty/out-of-bounds ROI, cancelled selection, or other failures. Include `code` such as `unreadable_image` or `invalid_roi`.

Current `measure_color.py` JSON is a partial implementation of this shape. It currently writes a resolved absolute `image` path and has no provenance or quality object. Aligning it is future work.

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
    "generator": null
  }
}
```

`mixing_model` must name the actual method (for example `volume_weighted_srgb_mean`) if a value is produced. That name does not make the method physically valid.

## Proposed later comparison (not started)

A comparison record would reference one measured appearance and one expected color, plus a delta in a named space, and optional `hypotheses` such as `carryover_from_previous_recipe` with an evidence note. Do not implement this until both producers exist.

## Failure reporting

Every producer should return a structured failure instead of a guessed color. Unavailable identifiers stay unknown. Partial records are allowed.
