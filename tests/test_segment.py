"""Tests for liquid segmentation on synthetic vial crops."""

import numpy as np
import pytest

from vialcv.roi import load_camera_config
from vialcv.segment import MENISCUS_ROWS, crop_zones, segment_liquid, to_lab

HEIGHT, WIDTH = 148, 52
ZONES = {"backlit": (0, 28), "dark_background": (44, 98), "bore": (116, 148)}
BLUE = (0.9, 0.45, 0.1)  # BGR transmission of a blue liquid
PALE = (0.72, 0.78, 0.84)
VERY_PALE = (0.93, 0.95, 0.97)


def empty_vial() -> np.ndarray:
    """Backdrop (light), belt (dark), and bore (bright) behind glass with two walls."""
    crop = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float32)
    crop[:30] = 200
    crop[30:98] = 70
    crop[98:] = 170
    crop[:, 1:3] = 120
    crop[:, 49:51] = 120
    return crop.astype(np.uint8)


def filled_vial(top_row: int, transmission=BLUE, glare=True) -> np.ndarray:
    crop = empty_vial().astype(np.float32)
    crop[top_row:, 3:49] *= np.array(transmission, dtype=np.float32)
    if glare:
        crop[120:124, 20:26] = 255
    return crop.clip(0, 255).astype(np.uint8)


def profile_of(crop: np.ndarray) -> np.ndarray:
    return np.median(to_lab(crop)[:, 8:44], axis=1)


def test_fill_line_in_view_with_reference():
    result = segment_liquid(filled_vial(60), empty_vial(), puck_top_row=98, zones=ZONES)
    assert result.ok and result.fill_state == "in_view"
    assert result.fill_line_row == pytest.approx(60, abs=2)
    assert result.method == "delta_e76_vs_empty_reference"
    # Meniscus rows, glare, and rows above the surface are not in the color mask.
    assert not result.mask[:60 + MENISCUS_ROWS].any()
    assert not result.mask[120:124, 20:26].any()
    assert result.glare_mask[120:124, 20:26].all()
    assert result.zone_masks["backlit"].sum() == 0
    assert result.zone_masks["dark_background"].sum() > 0 and result.zone_masks["bore"].sum() > 0


def test_full_column_is_at_or_above_view_top():
    result = segment_liquid(filled_vial(0), empty_vial(), puck_top_row=98, zones=ZONES)
    assert result.ok and result.fill_state == "at_or_above_view_top"
    assert result.fill_line_row == 0
    assert result.zone_masks["backlit"].sum() > 0


def test_walls_are_trimmed():
    result = segment_liquid(filled_vial(0), empty_vial(), puck_top_row=98)
    left, right = result.interior_columns
    assert 4 <= left <= 7 and 44 <= right <= 48
    assert not result.mask[:, :left].any() and not result.mask[:, right:].any()


def test_no_difference_is_not_reported_as_empty():
    # An empty vial and a vial of very pale liquid look the same; neither is called empty.
    for crop in (empty_vial(), filled_vial(0, VERY_PALE, glare=False)):
        result = segment_liquid(crop, empty_vial(), puck_top_row=98)
        assert not result.ok and result.code == "no_liquid_detected"
        assert result.fill_state == "unknown"


def test_pale_liquid_is_low_contrast_not_a_fill_line():
    # Only the bright bore rows pass the pixel threshold, as with video 3's pale vials.
    result = segment_liquid(filled_vial(0, PALE, glare=False), empty_vial(), puck_top_row=98)
    assert not result.ok and result.code == "low_contrast"
    assert result.fill_line_row is None


def test_camera_profile_matches_reference_mode():
    profile = profile_of(empty_vial())
    result = segment_liquid(filled_vial(60), None, puck_top_row=98, empty_profile_lab=profile)
    assert result.ok and result.method == "delta_e76_vs_camera_empty_profile"
    assert result.fill_line_row == pytest.approx(60, abs=2)


def test_profile_of_wrong_length_falls_back_to_chroma():
    result = segment_liquid(filled_vial(60), None, puck_top_row=98, empty_profile_lab=np.zeros((10, 3)))
    assert result.method == "lab_chroma_threshold"


def test_gray_vial_without_reference_is_low_contrast():
    result = segment_liquid(empty_vial(), None, puck_top_row=98)
    assert not result.ok and result.code == "low_contrast"


def test_short_bottom_strip_is_not_a_liquid_column():
    # A few changed rows at the bore floor (reflections, residue) are not a fill.
    result = segment_liquid(filled_vial(140, glare=False), empty_vial(), puck_top_row=98)
    assert not result.ok and result.code == "no_liquid_detected"


def test_reference_shape_must_match():
    with pytest.raises(ValueError):
        segment_liquid(filled_vial(60), empty_vial()[:100], puck_top_row=98)


def test_crop_zones_for_configured_vial_roi():
    config = load_camera_config("vial_fill")
    zones = crop_zones(config, config.region("vial"))
    assert zones == {"backlit": (0, 28), "dark_background": (44, 98), "bore": (116, 148)}
