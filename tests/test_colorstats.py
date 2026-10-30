"""Tests for robust color statistics."""

import cv2
import numpy as np
import pytest
from skimage.color import rgb2lab

from vialcv.colorstats import (
    circular_hue,
    delta_e_2000,
    describe_color,
    describe_zones,
    masked_rgb,
    rgb_to_hsv_lab,
    robust_summary,
)
from vialcv.measure import convert_mean_rgb


def solid_bgr(bgr, size=(20, 20)) -> np.ndarray:
    image = np.zeros((*size, 3), dtype=np.uint8)
    image[:] = bgr
    return image


def test_masked_rgb_reports_rgb_order():
    image = solid_bgr((10, 20, 30))
    mask = np.zeros(image.shape[:2], dtype=bool)
    mask[:2, :3] = True
    rgb = masked_rgb(image, mask)
    assert rgb.shape == (6, 3)
    assert rgb[0].tolist() == [30.0, 20.0, 10.0]
    with pytest.raises(ValueError):
        masked_rgb(image, np.ones((5, 5), dtype=bool))


def test_robust_summary_resists_outliers():
    values = np.vstack([np.full((95, 3), 100.0), np.full((5, 3), 255.0)])
    summary = robust_summary(values)
    assert summary["median"] == [100.0, 100.0, 100.0]
    assert summary["trimmed_mean"] == [100.0, 100.0, 100.0]
    assert summary["mad_sigma"] == [0.0, 0.0, 0.0]
    assert values.mean(axis=0)[0] > 107  # the plain mean is pulled by glare-like outliers


def test_circular_hue_wraps_around_red():
    result = circular_hue(np.array([350.0, 10.0]))
    assert result["h_circular_mean_degrees"] == pytest.approx(0.0, abs=1e-6) or \
        result["h_circular_mean_degrees"] == pytest.approx(360.0, abs=1e-6)
    assert result["h_resultant_length"] == pytest.approx(np.cos(np.deg2rad(10)))
    assert np.mean([350.0, 10.0]) == 180.0  # what a linear mean would wrongly report


def test_circular_hue_weighting_ignores_gray_pixels():
    hues = np.array([200.0] * 10 + [20.0] * 10)
    saturation = np.array([0.8] * 10 + [0.0] * 10)
    result = circular_hue(hues, weights=saturation)
    assert result["h_circular_mean_degrees"] == pytest.approx(200.0)
    assert result["h_resultant_length"] == pytest.approx(1.0)
    assert result["h_circular_std_degrees"] == pytest.approx(0.0, abs=1e-3)


def test_circular_hue_without_common_direction():
    assert circular_hue(np.array([0.0, 180.0]))["h_circular_mean_degrees"] is None
    assert circular_hue(np.array([90.0]), weights=np.array([0.0]))["h_resultant_length"] == 0.0


def test_delta_e_2000_matches_published_test_pair():
    # Sharma, Wu & Dalal (2005), CIEDE2000 test data, pair 1.
    assert delta_e_2000([50.0, 2.6772, -79.7751], [50.0, 0.0, -82.7485]) == pytest.approx(2.0425, abs=1e-4)
    assert delta_e_2000([40.0, 10.0, -5.0], [40.0, 10.0, -5.0]) == 0.0


def test_opencv_float_lab_agrees_with_skimage():
    rng = np.random.default_rng(0)
    rgb = rng.integers(0, 256, (500, 3)).astype(np.float64)
    _, lab = rgb_to_hsv_lab(rgb)
    reference = rgb2lab((rgb / 255.0).reshape(-1, 1, 3)).reshape(-1, 3)
    differences = [delta_e_2000(a, b) for a, b in zip(lab, reference)]
    assert max(differences) < 0.5


def test_describe_color_on_a_solid_patch():
    image = solid_bgr((200, 120, 30))  # RGB (30, 120, 200), a blue
    result = describe_color(image, np.ones(image.shape[:2], dtype=bool))
    assert result["ok"] and result["pixel_count"] == 400
    assert result["rgb_0_255"]["median"] == [30.0, 120.0, 200.0]

    expected_hsv, expected_lab = convert_mean_rgb([30.0, 120.0, 200.0])
    assert result["hsv"]["h_circular_mean_degrees"] == pytest.approx(expected_hsv[0], abs=1e-3)
    assert result["hsv"]["h_resultant_length"] == pytest.approx(1.0)
    assert result["lab"]["median"]["L"] == pytest.approx(expected_lab[0], abs=1e-3)
    assert result["mean_rgb_then_convert"]["lab_of_mean_rgb"]["b"] == pytest.approx(expected_lab[2], abs=1e-3)


def test_describe_color_median_ignores_glare_but_mean_does_not():
    image = solid_bgr((200, 120, 30))
    image[:2] = 255  # 10% glare
    result = describe_color(image, np.ones(image.shape[:2], dtype=bool))
    assert result["rgb_0_255"]["median"] == [30.0, 120.0, 200.0]
    assert result["mean_rgb_then_convert"]["rgb_0_255"][0] > 50


def test_describe_color_too_few_pixels():
    image = solid_bgr((1, 2, 3))
    mask = np.zeros(image.shape[:2], dtype=bool)
    mask[0, :10] = True
    result = describe_color(image, mask)
    assert not result["ok"] and result["code"] == "too_few_pixels" and result["pixel_count"] == 10


def test_describe_zones():
    image = solid_bgr((200, 120, 30))
    top = np.zeros(image.shape[:2], dtype=bool)
    top[:10] = True
    result = describe_zones(image, {"backlit": top, "bore": np.zeros_like(top)})
    assert result["backlit"]["ok"] and not result["bore"]["ok"]
