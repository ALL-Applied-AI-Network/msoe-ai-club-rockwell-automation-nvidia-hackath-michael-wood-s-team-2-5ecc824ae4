"""Detect the measured liquid color and fill level of a vial in one image.

`detect_vial_color()` ties the pieces together: locate the vial (or use a given ROI),
optionally white-balance, segment the liquid against an empty reference or the camera's
empty profile, and summarize color per background zone. It returns a record shaped like
`MeasuredAppearance` in docs/interfaces.md (proposed, not agreed) with extra blocks for
zones, fill, segmentation, and white balance.

This is measured camera appearance, not expected mixture color. On failure the color
fields are null and `quality` says why; no color is guessed.
"""

import numpy as np

from vialcv.colorstats import describe_color
from vialcv.locate import locate_vial
from vialcv.roi import CameraConfig, Roi, crop, load_camera_config, validate_roi
from vialcv.segment import crop_zones, load_empty_profile, segment_liquid
from vialcv.whitebalance import NO_CORRECTION, apply_gains, white_balance

SCHEMA = "processdna.measured_appearance.v0"
GENERATOR = "vialcv.detect.detect_vial_color"

# Headline color comes from the first zone with enough pixels; the backlit zone shows
# the transmitted color best (docs/components/cv-lighting-study.md).
ZONE_PREFERENCE = ("backlit", "bore", "dark_background")
MIN_ZONE_PIXELS = 200

DATA_ORIGINS = ("real_line", "digital_twin", "unknown")
METADATA_KEYS = ("video_id", "frame_index", "timestamp", "video_s", "vial_id", "recipe_id")


def resolve_region(image_bgr: np.ndarray, config: CameraConfig, roi: Roi | None) -> tuple[dict, list[str]]:
    """Decide which pixels are the vial and how the input was interpreted."""
    height, width = image_bgr.shape[:2]
    full_frame = (width, height) == config.image_size_wh
    vial_w, vial_h = config.region("vial")[2:]
    notes = []

    if roi is not None:
        validate_roi(roi, (width, height))
        return {"input": "full_frame" if full_frame else "image", "roi": roi, "roi_source": "argument",
                "frame_coordinates": full_frame, "zones_roi": roi if full_frame else None}, notes

    if full_frame:
        located = locate_vial(image_bgr, config)
        if not located.ok:
            return {"input": "full_frame", "failure": (located.code, located.detail)}, notes
        if located.code:
            notes.append(located.code)
        return {"input": "full_frame", "roi": located.vial_xywh, "roi_source": located.source,
                "frame_coordinates": True, "zones_roi": located.vial_xywh}, notes

    whole = (0, 0, width, height)
    if (width, height) == (vial_w, vial_h):
        notes.append("assumed_config_vial_crop")
        return {"input": "vial_crop", "roi": whole, "roi_source": "whole_image",
                "frame_coordinates": False, "zones_roi": config.region("vial")}, notes

    notes.append("unknown_crop_no_zones")
    return {"input": "image", "roi": whole, "roi_source": "whole_image",
            "frame_coordinates": False, "zones_roi": None}, notes


def legacy_fields(described: dict | None) -> dict:
    """Interface fields from docs/interfaces.md, from the headline zone's mean color."""
    if not described or not described.get("ok"):
        return {"method": "mean_rgb_then_convert", "rgb_0_255": None, "hsv_of_mean_rgb": None,
                "lab_of_mean_rgb": None}
    legacy = described["mean_rgb_then_convert"]
    return {"method": "mean_rgb_then_convert", **legacy}


def empty_reference_colors(reference_corrected: np.ndarray, segmentation, balance) -> dict:
    """Color of the empty vial on the same pixels the liquid was measured on, per zone.

    This is the camera's view of the same spot with no liquid (glass plus whatever is
    behind it). It is a measured white/background reference for a consumer that models
    light passing through the liquid, not a liquid color.
    """
    return {
        "source": "empty_reference",
        "pixels": "same liquid-mask pixels as color.zones, read from the empty reference",
        "white_balance_gains_rgb": list(balance.gains_rgb),
        "zones": {name: describe_color(reference_corrected, mask, MIN_ZONE_PIXELS)
                  for name, mask in segmentation.zone_masks.items()},
        "whole_mask": describe_color(reference_corrected, segmentation.mask),
    }


def detect_vial_color(
    image_bgr: np.ndarray,
    camera_id: str = "vial_fill",
    roi: Roi | None = None,
    white_balance_method: str = "none",
    reference_bgr: np.ndarray | None = None,
    image_ref: str | None = None,
    source_data_origin: str = "unknown",
    metadata: dict | None = None,
    config: CameraConfig | None = None,
) -> dict:
    """Return a measured-appearance record for the vial in `image_bgr` (BGR, as from cv2.imread).

    `reference_bgr` is an optional empty-vial image taken with the same framing (for
    example the frame before the pour). `metadata` may carry video_id, frame_index,
    timestamp, video_s, vial_id, recipe_id; anything not given stays null.
    """
    if source_data_origin not in DATA_ORIGINS:
        raise ValueError(f"source_data_origin must be one of {DATA_ORIGINS}.")
    config = config or load_camera_config(camera_id)
    metadata = metadata or {}

    record = {
        "schema": SCHEMA,
        "image_ref": image_ref,
        "camera_id": camera_id,
        **{key: metadata.get(key) for key in METADATA_KEYS},
        "input": None,
        "roi_xywh": None,
        "roi_source": None,
        "pixel_count": 0,
        **legacy_fields(None),
        "color": None,
        "fill": None,
        "segmentation": None,
        "white_balance": None,
        "quality": {"ok": False, "code": None, "detail": None, "warnings": []},
        "provenance": {
            "data_origin": "derived",
            "intended_use": "inspect",
            "generator": GENERATOR,
            "sources": [{"ref": image_ref, "data_origin": source_data_origin}],
        },
    }
    if reference_bgr is not None:
        record["provenance"]["sources"].append({"ref": "empty_reference", "data_origin": source_data_origin})

    def fail(code, detail):
        record["quality"].update(ok=False, code=code, detail=detail)
        return record

    if image_bgr is None or image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        return fail("unreadable_image", "Expected a BGR color image.")

    try:
        region, notes = resolve_region(image_bgr, config, roi)
    except ValueError as error:
        return fail("invalid_roi", str(error))
    record["input"] = region["input"]
    record["quality"]["warnings"].extend(notes)
    if "failure" in region:
        return fail(*region["failure"])
    record["roi_xywh"] = list(region["roi"])
    record["roi_source"] = region["roi_source"]

    # White balance needs the camera's white patch, so only full frames can be corrected.
    corrected, balance = image_bgr.astype(np.float32), NO_CORRECTION
    if white_balance_method != "none":
        if region["input"] == "full_frame":
            corrected, balance = white_balance(image_bgr, white_balance_method, config)
            if not balance.ok:
                record["quality"]["warnings"].append(balance.code)
        else:
            record["quality"]["warnings"].append("white_balance_needs_full_frame")
    record["white_balance"] = balance.as_dict() if white_balance_method != "none" else NO_CORRECTION.as_dict()

    vial = crop(image_bgr, region["roi"])
    vial_corrected = crop(corrected, region["roi"])
    reference = None
    if reference_bgr is not None:
        if reference_bgr.shape != image_bgr.shape:
            return fail("invalid_reference", "Empty reference must have the same size as the image.")
        reference = crop(reference_bgr, region["roi"])

    zones_roi = region["zones_roi"]
    zones = crop_zones(config, zones_roi) if zones_roi else None
    puck_row = config.lines_y["puck_top"] - zones_roi[1] if zones_roi else None
    # The profile is per row of the configured vial ROI; a shifted ROI would misalign it.
    profile = load_empty_profile(camera_id) if zones_roi and tuple(zones_roi) == config.region("vial") else None
    if zones_roi and profile is None and reference is None:
        record["quality"]["warnings"].append("no_empty_reference_for_this_roi")
    segmentation = segment_liquid(vial, reference, puck_row, profile, zones)

    record["segmentation"] = {
        "ok": segmentation.ok,
        "code": segmentation.code,
        "method": segmentation.method,
        "glare_fraction": round(segmentation.glare_fraction, 4),
        "interior_columns": list(segmentation.interior_columns),
    }

    offset_y = region["roi"][1] if region["frame_coordinates"] else zones_roi[1] if zones_roi else 0
    fill_line_y = None if segmentation.fill_line_row is None else offset_y + segmentation.fill_line_row
    coordinates = "frame" if region["frame_coordinates"] or zones_roi else "image"
    fill = {"state": segmentation.fill_state, "coordinates": coordinates, "fill_line_y_px": None,
            "visible_top_y_px": offset_y, "height_above_puck_top_px": None}
    if segmentation.fill_state == "in_view":
        fill["fill_line_y_px"] = fill_line_y
        if coordinates == "frame":
            fill["height_above_puck_top_px"] = config.lines_y["puck_top"] - fill_line_y
    record["fill"] = fill

    if not segmentation.ok:
        return fail(segmentation.code, segmentation.detail)
    if segmentation.code:
        record["quality"]["warnings"].append(segmentation.code)

    zone_colors = {name: describe_color(vial_corrected, mask, MIN_ZONE_PIXELS)
                   for name, mask in segmentation.zone_masks.items()}
    whole = describe_color(vial_corrected, segmentation.mask)
    primary = next((z for z in ZONE_PREFERENCE if zone_colors.get(z, {}).get("ok")), None)
    if primary is None and not zone_colors:
        primary = "whole_mask"
    if primary is None:
        return fail("no_zone_with_enough_pixels", f"No background zone has {MIN_ZONE_PIXELS}+ liquid pixels.")

    headline = whole if primary == "whole_mask" else zone_colors[primary]
    record["pixel_count"] = headline["pixel_count"]
    record.update(legacy_fields(headline))
    record["color"] = {
        "primary_zone": primary,
        "primary": headline,
        "zones": zone_colors,
        "whole_mask": whole,
        "empty_reference": None,
        "note": "Measured camera appearance. Compare colors only within the same zone.",
    }
    if reference is not None:
        # The reference is from seconds earlier under the same lighting, so it gets the
        # measured frame's gains rather than its own estimate (its patch may be occluded).
        reference_corrected = apply_gains(reference, balance)
        record["color"]["empty_reference"] = empty_reference_colors(reference_corrected, segmentation, balance)
    record["quality"].update(ok=True, code=None, detail=None)
    return record
