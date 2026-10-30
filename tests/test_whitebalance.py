"""Tests for white-balance correction on synthetic frames."""

import numpy as np
import pytest

from vialcv.colorstats import describe_color
from vialcv.roi import load_camera_config
from vialcv.whitebalance import (
    NO_CORRECTION,
    TARGET_LEVEL,
    apply_gains,
    estimate_gray_world,
    estimate_white_patch,
    white_balance,
)

CONFIG = load_camera_config("vial_fill")
PATCH = CONFIG.region("white_reference")


def cast_frame(patch_rgb=(150, 160, 140), liquid_rgb=(30, 80, 120)) -> np.ndarray:
    """A 640x480 frame with a tinted backdrop patch and a liquid square."""
    frame = np.full((480, 640, 3), 90, dtype=np.uint8)
    x, y, w, h = PATCH
    frame[y:y + h, x:x + w] = patch_rgb[::-1]
    frame[300:340, 300:330] = liquid_rgb[::-1]
    return frame


def test_white_patch_maps_patch_to_neutral_target():
    frame = cast_frame()
    balance = estimate_white_patch(frame, PATCH)
    assert balance.ok and balance.reference_rgb_0_255 == (150.0, 160.0, 140.0)
    corrected = apply_gains(frame, balance)
    x, y, w, h = PATCH
    assert np.allclose(corrected[y:y + h, x:x + w], TARGET_LEVEL, atol=1e-3)


def test_same_liquid_under_two_lightings_matches_after_correction():
    # Liquid and patch both dimmer and greener under the second lighting.
    light = np.array([0.85, 0.95, 0.8])
    first = cast_frame()
    second = cast_frame(tuple(np.round(np.array([150, 160, 140]) * light)),
                        tuple(np.round(np.array([30, 80, 120]) * light)))
    mask = np.zeros(first.shape[:2], dtype=bool)
    mask[300:340, 300:330] = True

    medians = []
    for frame in (first, second):
        corrected, balance = white_balance(frame, "white_patch", CONFIG)
        assert balance.ok
        medians.append(describe_color(corrected, mask)["rgb_0_255"]["median"])
    assert np.allclose(medians[0], medians[1], atol=1.5)

    raw = [describe_color(f, mask)["rgb_0_255"]["median"] for f in (first, second)]
    assert not np.allclose(raw[0], raw[1], atol=1.5)


def test_occluded_patch_is_reported_and_not_applied():
    frame = cast_frame()
    x, y, w, h = PATCH
    frame[y:y + h, x:x + w // 2] = 20  # a dark object over half the patch
    corrected, balance = white_balance(frame, "white_patch", CONFIG)
    assert not balance.ok and balance.code == "white_reference_occluded"
    assert np.array_equal(corrected, frame.astype(np.float32))


def test_saturated_and_dark_patches_are_rejected():
    assert estimate_white_patch(cast_frame((255, 255, 255)), PATCH).code == "white_reference_saturated"
    assert estimate_white_patch(cast_frame((20, 25, 20)), PATCH).code == "white_reference_dark"


def test_gray_world_neutralizes_a_uniform_cast():
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    frame[:] = (100, 120, 140)  # BGR, warm cast
    balance = estimate_gray_world(frame)
    corrected = apply_gains(frame, balance)
    assert np.allclose(corrected[0, 0], 120.0, atol=1e-3)
    assert balance.gains_rgb[0] < 1.0 < balance.gains_rgb[2]


def test_none_and_unknown_methods():
    frame = cast_frame()
    corrected, balance = white_balance(frame, "none")
    assert balance is NO_CORRECTION and np.array_equal(corrected, frame.astype(np.float32))
    with pytest.raises(ValueError):
        white_balance(frame, "auto")
    with pytest.raises(ValueError):
        white_balance(frame, "white_patch", None)


def test_gains_are_clipped_to_valid_range():
    frame = cast_frame()
    frame[0, 0] = 250
    balance = estimate_white_patch(frame, PATCH)
    assert apply_gains(frame, balance).max() <= 255.0


def test_as_dict_is_serializable():
    record = estimate_white_patch(cast_frame(), PATCH).as_dict()
    assert record["method"] == "white_patch" and len(record["gains_rgb"]) == 3
