"""Tests for per-camera ROI configuration."""

import json

import numpy as np
import pytest

from vialcv.roi import check_image_size, crop, load_camera_config, validate_roi


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
