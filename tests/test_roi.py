"""Tests for per-camera ROI configuration."""

import json

import cv2
import numpy as np
import pytest

from vialcv.roi import (
    camera_shift,
    check_image_size,
    contact_sheet,
    crop,
    draw_regions,
    load_camera_config,
    static_scene,
    validate_roi,
)


def write_config(directory, **overrides):
    raw = {
        "camera_id": "test_cam",
        "image_size_wh": [100, 80],
        "regions_xywh": {"vial": [10, 20, 30, 40]},
        "lines_y": {"puck_top": 50},
    }
    raw.update(overrides)
    (directory / "test_cam.json").write_text(json.dumps(raw))


def test_committed_vial_fill_config_loads():
    config = load_camera_config("vial_fill")
    assert config.image_size_wh == (640, 480)
    for name in ("vial", "puck_bore", "nozzle_stream", "white_reference"):
        assert len(config.region(name)) == 4
    assert config.lines_y["collar_bottom"] < config.lines_y["puck_top"] < config.lines_y["bore_bottom"]


def test_load_config_from_directory(tmp_path):
    write_config(tmp_path)
    config = load_camera_config("test_cam", tmp_path)
    assert config.region("vial") == (10, 20, 30, 40)
    assert config.lines_y == {"puck_top": 50}
    with pytest.raises(KeyError):
        config.region("missing")


def test_load_config_rejects_bad_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_camera_config("test_cam", tmp_path)

    write_config(tmp_path, camera_id="other")
    with pytest.raises(ValueError):
        load_camera_config("test_cam", tmp_path)

    write_config(tmp_path, regions_xywh={"vial": [90, 0, 20, 10]})
    with pytest.raises(ValueError):
        load_camera_config("test_cam", tmp_path)

    write_config(tmp_path, regions_xywh={"vial": [0, 0, 10]})
    with pytest.raises(ValueError):
        load_camera_config("test_cam", tmp_path)

    write_config(tmp_path, lines_y={"puck_top": 80})
    with pytest.raises(ValueError):
        load_camera_config("test_cam", tmp_path)


@pytest.mark.parametrize("roi", [(0, 0, 0, 5), (-1, 0, 5, 5), (96, 0, 5, 5), (0, 76, 5, 5)])
def test_validate_roi_rejects(roi):
    with pytest.raises(ValueError):
        validate_roi(roi, (100, 80))


def test_crop_and_size_check(tmp_path):
    write_config(tmp_path)
    config = load_camera_config("test_cam", tmp_path)
    image = np.arange(80 * 100, dtype=np.int32).reshape(80, 100)

    patch = crop(image, config.region("vial"))
    assert patch.shape == (40, 30)
    assert patch[0, 0] == image[20, 10]

    check_image_size(np.zeros((80, 100, 3)), config)
    with pytest.raises(ValueError):
        check_image_size(np.zeros((480, 640, 3)), config)


def test_draw_regions_draws_every_region():
    config = load_camera_config("vial_fill")
    assert len(config.regions) > 6  # more regions than the old fixed color list
    canvas = draw_regions(np.zeros((480, 640, 3), dtype=np.uint8), config)
    for x, y, w, h in config.regions.values():
        assert canvas[y, x:x + w].any(), (x, y, w, h)


def test_static_scene_shift_is_measured():
    config = load_camera_config("vial_fill")
    rng = np.random.default_rng(1)
    texture = cv2.GaussianBlur(rng.integers(0, 255, (480, 640)).astype(np.uint8), (0, 0), 2)
    frame = np.dstack([texture] * 3)
    moved = np.roll(frame, shift=(3, -2), axis=(0, 1))
    reference = static_scene([frame], config)
    dx, dy, response = camera_shift(reference, static_scene([moved], config))
    assert dx == pytest.approx(-2, abs=0.3) and dy == pytest.approx(3, abs=0.3)
    assert response > 0.3
    _, _, same = camera_shift(reference, static_scene([frame, frame], config))
    assert same > 0.9


def test_contact_sheet_pads_rows():
    tiles = [np.full((4, 5, 3), i, dtype=np.uint8) for i in range(5)]
    sheet = contact_sheet(tiles, columns=3)
    assert sheet.shape == (8, 15, 3)
    assert not sheet[4:, 10:].any()
