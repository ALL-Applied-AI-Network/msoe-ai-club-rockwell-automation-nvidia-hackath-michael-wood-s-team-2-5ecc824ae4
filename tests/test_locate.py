"""Tests for the vial locator on synthetic fill-station scenes."""

import numpy as np
import pytest

from vialcv.locate import detect_vial, locate_vial
from vialcv.roi import load_camera_config

CONFIG = load_camera_config("vial_fill")


def station_scene(dx: int = 0, dy: int = 0, dark_liquid: bool = False) -> np.ndarray:
    """Draw a simplified vial_fill frame with the carrier shifted by (dx, dy)."""
    gray = np.full((480, 640), 150, dtype=np.uint8)  # white backdrop
    gray[275:440] = 64  # belt/rail band behind the vial

    gray[195 + dy:225 + dy, 257 + dx:375 + dx] = 90  # lit collar top face
    gray[225 + dy:265 + dy, 257 + dx:375 + dx] = 25  # dark collar front face
    gray[265 + dy:370 + dy, 290 + dx:340 + dx] = 70  # glass interior
    gray[265 + dy:370 + dy, 289 + dx:291 + dx] = 120  # left wall
    gray[265 + dy:370 + dy, 337 + dx:339 + dx] = 120  # right wall
    gray[370 + dy:430 + dy, 255 + dx:380 + dx] = 150  # aluminum puck
    if dark_liquid:
        gray[265 + dy:420 + dy, 292 + dx:336 + dx] = 30  # dark liquid touching the collar
    return np.dstack([gray] * 3)


def test_detect_vial_finds_parts():
    detection = detect_vial(station_scene())
    assert detection is not None
    assert detection.collar_xywh[0] == 257
    assert detection.collar_xywh[1] + detection.collar_xywh[3] == 265
    assert detection.puck_top_y == pytest.approx(370, abs=2)
    assert detection.wall_left_x == pytest.approx(290, abs=2)
    assert detection.wall_right_x == pytest.approx(338, abs=2)


def test_locate_uses_config_when_detection_agrees():
    result = locate_vial(station_scene(), CONFIG)
    assert result.ok and result.code is None
    assert result.source == "config"
    assert result.vial_xywh == CONFIG.region("vial")


def test_locate_reports_small_drift_with_detected_roi():
    result = locate_vial(station_scene(dx=8), CONFIG)
    assert result.ok and result.code == "roi_drift"
    assert result.source == "detected"
    assert result.offset_xy[0] == 8
    assert result.vial_xywh[0] == pytest.approx(CONFIG.region("vial")[0] + 8, abs=3)


def test_locate_rejects_large_offset_as_off_station():
    result = locate_vial(station_scene(dx=40), CONFIG)
    assert not result.ok and result.code == "vial_off_station"
    assert result.vial_xywh is None


def test_locate_reports_missing_vial():
    empty = np.full((480, 640, 3), 150, dtype=np.uint8)
    result = locate_vial(empty, CONFIG)
    assert not result.ok and result.code == "vial_not_found"
    assert not locate_vial(empty).ok


def test_dark_liquid_touching_collar_does_not_hide_it():
    result = locate_vial(station_scene(dark_liquid=True), CONFIG)
    assert result.ok and result.code is None


def test_locate_without_config_auto_detects():
    result = locate_vial(station_scene(dx=-20))
    assert result.ok and result.code == "roi_auto_detected"
    x, y, w, h = result.vial_xywh
    assert x == pytest.approx(288 - 20, abs=3)
    assert y == 265
    assert w == pytest.approx(52, abs=4)
