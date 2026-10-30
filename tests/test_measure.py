"""Tests for the baseline mean-color measurement, using synthetic images only."""

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from vialcv.measure import convert_mean_rgb, measure_rgb, measure_rgb_masked

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_color.py"


def solid_bgr(blue: int, green: int, red: int, height: int = 20, width: int = 30) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:] = (blue, green, red)
    return image


def test_measure_rgb_reports_rgb_order():
    image = solid_bgr(10, 20, 30)
    assert measure_rgb(image, (0, 0, 30, 20)) == [30.0, 20.0, 10.0]


def test_measure_rgb_averages_only_the_region():
    image = solid_bgr(0, 0, 0)
    image[:, 10:] = (0, 0, 200)
    assert measure_rgb(image, (10, 0, 20, 20)) == [200.0, 0.0, 0.0]
    assert measure_rgb(image, (0, 0, 20, 20)) == [100.0, 0.0, 0.0]


@pytest.mark.parametrize(
    "roi",
    [
        (0, 0, 0, 10),
        (0, 0, 10, 0),
        (-1, 0, 5, 5),
        (0, -1, 5, 5),
        (26, 0, 5, 5),
        (0, 16, 5, 5),
    ],
)
def test_measure_rgb_rejects_empty_or_out_of_bounds(roi):
    with pytest.raises(ValueError):
        measure_rgb(solid_bgr(1, 2, 3), roi)


def test_measure_rgb_masked_uses_selected_pixels():
    image = solid_bgr(0, 0, 0)
    image[5:10, 5:10] = (40, 80, 120)
    mask = np.zeros(image.shape[:2], dtype=bool)
    mask[5:10, 5:10] = True
    assert measure_rgb_masked(image, mask) == [120.0, 80.0, 40.0]


def test_measure_rgb_masked_rejects_empty_or_mismatched_mask():
    image = solid_bgr(1, 2, 3)
    with pytest.raises(ValueError):
        measure_rgb_masked(image, np.zeros(image.shape[:2], dtype=bool))
    with pytest.raises(ValueError):
        measure_rgb_masked(image, np.ones((5, 5), dtype=bool))


def test_convert_mean_rgb_known_colors():
    hsv, lab = convert_mean_rgb([255.0, 0.0, 0.0])
    assert hsv == pytest.approx([0.0, 1.0, 1.0], abs=1e-4)

    hsv, lab = convert_mean_rgb([255.0, 255.0, 255.0])
    assert hsv[1:] == pytest.approx([0.0, 1.0], abs=1e-4)
    assert lab == pytest.approx([100.0, 0.0, 0.0], abs=0.1)


def test_cli_json_with_fixed_roi(tmp_path):
    image_path = tmp_path / "solid.png"
    cv2.imwrite(str(image_path), solid_bgr(10, 20, 30))

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(image_path), "--roi", "0", "0", "30", "20", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(completed.stdout)

    assert result["roi_xywh"] == [0, 0, 30, 20]
    assert result["pixel_count"] == 600
    assert result["method"] == "mean_rgb_then_convert"
    assert result["rgb_0_255"] == [30.0, 20.0, 10.0]


def test_cli_rejects_out_of_bounds_roi(tmp_path):
    image_path = tmp_path / "solid.png"
    cv2.imwrite(str(image_path), solid_bgr(10, 20, 30))

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(image_path), "--roi", "25", "0", "10", "10"],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "Region must be nonempty and inside the image." in completed.stderr
