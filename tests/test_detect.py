"""End-to-end tests for detect_vial_color on synthetic vial_fill frames."""

import json

import numpy as np
import pytest

from vialcv.detect import SCHEMA, detect_vial_color

BLUE = np.array([0.9, 0.45, 0.1], dtype=np.float32)  # BGR transmission


def station_frame(fill_top_y: int | None = None) -> np.ndarray:
    """A simplified vial_fill frame matching the committed camera config geometry."""
    gray = np.full((480, 640), 150, dtype=np.float32)  # white backdrop
    gray[304:440] = 64  # dark belt behind the lower vial
    gray[90:180, 160:240] = 185  # white reference patch area
    gray[195:225, 257:375] = 90  # lit collar top
    gray[225:265, 257:375] = 25  # dark collar face
    gray[265:370, 289:291] = 120  # glass walls
    gray[265:370, 337:339] = 120
    gray[370:430, 255:380] = 150  # aluminum puck
    gray[388:420, 290:338] = 170  # bright bore
    frame = np.dstack([gray] * 3)
    if fill_top_y is not None:
        frame[fill_top_y:420, 291:337] *= BLUE
    return frame.clip(0, 255).astype(np.uint8)


def test_full_frame_with_reference():
    record = detect_vial_color(station_frame(330), reference_bgr=station_frame(), image_ref="frame.png",
                               source_data_origin="digital_twin", metadata={"video_id": 9})
    assert record["schema"] == SCHEMA
    assert record["quality"]["ok"], record["quality"]
    assert record["input"] == "full_frame" and record["roi_source"] == "config"
    assert record["fill"]["state"] == "in_view"
    assert record["fill"]["fill_line_y_px"] == pytest.approx(330, abs=2)
    assert record["fill"]["height_above_puck_top_px"] == pytest.approx(40, abs=2)

    # Liquid starts below the backdrop, so the headline color comes from the bore.
    assert record["color"]["primary_zone"] == "bore"
    assert not record["color"]["zones"]["backlit"]["ok"]
    assert record["method"] == "mean_rgb_then_convert" and len(record["rgb_0_255"]) == 3
    assert record["rgb_0_255"][2] > record["rgb_0_255"][0]  # blue

    assert record["video_id"] == 9 and record["vial_id"] is None
    origins = {s["data_origin"] for s in record["provenance"]["sources"]}
    assert record["provenance"]["data_origin"] == "derived" and origins == {"digital_twin"}
    json.dumps(record, allow_nan=False)


def test_empty_reference_color_is_read_on_the_liquid_pixels():
    record = detect_vial_color(station_frame(265), reference_bgr=station_frame())
    empty = record["color"]["empty_reference"]
    assert empty["source"] == "empty_reference"
    assert empty["zones"].keys() == record["color"]["zones"].keys()
    backlit = empty["zones"]["backlit"]
    assert backlit["pixel_count"] == record["color"]["zones"]["backlit"]["pixel_count"]
    assert backlit["rgb_0_255"]["median"] == pytest.approx([150, 150, 150], abs=1)  # bare backdrop
    assert empty["zones"]["bore"]["rgb_0_255"]["median"] == pytest.approx([170, 170, 170], abs=1)
    json.dumps(record, allow_nan=False)


def test_empty_reference_gets_the_measured_frames_white_balance():
    record = detect_vial_color(station_frame(265), reference_bgr=station_frame(), white_balance_method="white_patch")
    empty = record["color"]["empty_reference"]
    assert empty["white_balance_gains_rgb"] == record["white_balance"]["gains_rgb"]
    assert empty["zones"]["backlit"]["rgb_0_255"]["median"] == pytest.approx([150 * 160 / 185] * 3, abs=1)


def test_no_empty_reference_block_without_a_reference():
    record = detect_vial_color(station_frame(265))
    assert record["quality"]["ok"]
    assert record["color"]["empty_reference"] is None


def test_full_column_uses_backlit_zone():
    record = detect_vial_color(station_frame(265), reference_bgr=station_frame())
    assert record["quality"]["ok"]
    assert record["fill"]["state"] == "at_or_above_view_top"
    assert record["fill"]["fill_line_y_px"] is None
    assert record["color"]["primary_zone"] == "backlit"


def test_empty_vial_is_a_failure_without_color():
    record = detect_vial_color(station_frame(), reference_bgr=station_frame())
    assert not record["quality"]["ok"] and record["quality"]["code"] == "no_liquid_detected"
    assert record["color"] is None and record["rgb_0_255"] is None and record["lab_of_mean_rgb"] is None


def test_no_vial_at_station():
    record = detect_vial_color(np.full((480, 640, 3), 150, dtype=np.uint8))
    assert not record["quality"]["ok"] and record["quality"]["code"] == "vial_not_found"


def test_invalid_roi_and_bad_inputs():
    frame = station_frame(330)
    assert detect_vial_color(frame, roi=(600, 400, 100, 100))["quality"]["code"] == "invalid_roi"
    assert detect_vial_color(np.zeros((10, 10), dtype=np.uint8))["quality"]["code"] == "unreadable_image"
    assert detect_vial_color(frame, reference_bgr=frame[:100])["quality"]["code"] == "invalid_reference"
    with pytest.raises(ValueError):
        detect_vial_color(frame, source_data_origin="synthetic")


def test_arbitrary_crop_measures_whole_mask_without_zones():
    crop = np.full((120, 60, 3), 200, dtype=np.uint8)
    crop[:, 2:4] = 120
    crop[:, 56:58] = 120
    crop[40:, 4:56] = (200, 90, 20)  # strongly colored liquid, BGR
    record = detect_vial_color(crop, white_balance_method="white_patch")
    assert record["quality"]["ok"], record["quality"]
    assert record["input"] == "image" and record["color"]["primary_zone"] == "whole_mask"
    assert record["fill"]["coordinates"] == "image"
    assert "unknown_crop_no_zones" in record["quality"]["warnings"]
    assert "white_balance_needs_full_frame" in record["quality"]["warnings"]


def test_white_patch_correction_is_reported():
    record = detect_vial_color(station_frame(265), reference_bgr=station_frame(), white_balance_method="white_patch")
    assert record["quality"]["ok"]
    balance = record["white_balance"]
    assert balance["method"] == "white_patch" and balance["ok"]
    assert balance["gains_rgb"] == pytest.approx([160 / 185] * 3, abs=1e-3)
