"""Locate the vial at the fill station from the image, as a fallback to the fixed ROI.

The detector finds the dark rectangular collar on the vial carrier, the top edge of the
bright aluminum puck below it, and the two glass walls between them. With a camera
config, the configured ROI is kept when the detection agrees with it; otherwise the
detected ROI is returned with a quality code saying why.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from vialcv.roi import CameraConfig, Roi

# Gray levels measured on videos 1-4 stills: collar front face ~22-26, belt behind it ~57.
COLLAR_MAX_GRAY = 45

# The collar's front face is a ~115 px wide dark band. A dark liquid column below it is
# only ~45 px wide, so rows are matched on long horizontal dark runs, not blob shape.
COLLAR_RUN_RANGE = (80, 160)
COLLAR_MIN_ROWS = 8
COLLAR_MAX_ROW_GAP = 2

# With a config, the collar is searched only this close to its configured position.
COLLAR_SEARCH_DX = 60
COLLAR_SEARCH_DY = 40

# Search window below the collar bottom for the puck top edge (pixels).
PUCK_SEARCH_RANGE = (40, 170)
PUCK_MIN_STEP = 25.0

# Glass walls are ~25 px either side of the collar center; the aluminum holder bar
# starts ~50 px right of it, so the search stops short of the bar.
WALL_SEARCH_HALF_WIDTH = 35
WALL_MARGIN = 2

# Default depth of visible liquid below the puck top when no config gives it.
DEFAULT_BORE_DEPTH = 50

# Detections within this many pixels of the config are treated as agreeing with it.
DEFAULT_TOLERANCE_PX = 4

# Larger offsets than this are not drift: on videos 1-4 they were carriers in motion.
DEFAULT_MAX_DRIFT_PX = 12


@dataclass(frozen=True)
class Detection:
    collar_xywh: Roi
    puck_top_y: int
    wall_left_x: int
    wall_right_x: int
    vial_xywh: Roi


@dataclass(frozen=True)
class LocateResult:
    ok: bool
    code: str | None
    detail: str | None
    vial_xywh: Roi | None
    source: str | None
    detection: Detection | None
    offset_xy: tuple[int, int] | None


def longest_run(row: np.ndarray) -> tuple[int, int]:
    """Return (start, length) of the longest run of True values in a 1-D array."""
    padded = np.concatenate(([0], row.astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(padded))
    if len(edges) == 0:
        return 0, 0
    starts, ends = edges[::2], edges[1::2]
    best = int(np.argmax(ends - starts))
    return int(starts[best]), int(ends[best] - starts[best])


def find_collar(gray: np.ndarray, expected: tuple[float, float] | None = None) -> Roi | None:
    """Return (x, y, w, h) of the collar's dark front face.

    `expected` is the configured (center x, bottom y); when given, only a nearby collar
    counts. Otherwise the collar nearest the image's horizontal center is used.
    """
    height, width = gray.shape
    if expected is None:
        center_x, x0, x1, y0, y1 = width / 2, 0, width, 0, height
    else:
        center_x = expected[0]
        x0 = max(int(center_x - COLLAR_SEARCH_DX - COLLAR_RUN_RANGE[1] / 2), 0)
        x1 = min(int(center_x + COLLAR_SEARCH_DX + COLLAR_RUN_RANGE[1] / 2), width)
        y0 = max(int(expected[1] - COLLAR_SEARCH_DY - COLLAR_RUN_RANGE[1]), 0)
        y1 = min(int(expected[1] + COLLAR_SEARCH_DY), height)

    dark = gray[y0:y1, x0:x1] < COLLAR_MAX_GRAY
    # Bridge small glints on the collar face.
    dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((1, 7), np.uint8)).astype(bool)

    rows = []
    for offset, row in enumerate(dark):
        start, length = longest_run(row)
        run_center = x0 + start + length / 2
        if COLLAR_RUN_RANGE[0] <= length <= COLLAR_RUN_RANGE[1] and abs(run_center - center_x) <= COLLAR_SEARCH_DX:
            rows.append((y0 + offset, x0 + start, x0 + start + length))

    # Group matching rows into vertical blocks; each block is a collar candidate.
    blocks, current = [], []
    for row in rows:
        if current and row[0] - current[-1][0] > COLLAR_MAX_ROW_GAP + 1:
            blocks.append(current)
            current = []
        current.append(row)
    if current:
        blocks.append(current)

    best, best_distance = None, None
    for block in blocks:
        if len(block) < COLLAR_MIN_ROWS:
            continue
        top, bottom = block[0][0], block[-1][0] + 1
        left = int(np.median([r[1] for r in block]))
        right = int(np.median([r[2] for r in block]))
        dx = (left + right) / 2 - center_x
        if expected is None:
            distance = abs(dx)
        else:
            dy = bottom - expected[1]
            if abs(dy) > COLLAR_SEARCH_DY:
                continue
            distance = abs(dx) + abs(dy)
        if best is None or distance < best_distance:
            best, best_distance = (left, top, right - left, bottom - top), distance
    return best


def find_puck_top(gray: np.ndarray, collar: Roi) -> int | None:
    """Return the y of the dark-to-bright edge at the top of the puck, left of the glass."""
    x, y, w, h = collar
    collar_bottom = y + h
    top = collar_bottom + PUCK_SEARCH_RANGE[0]
    bottom = min(collar_bottom + PUCK_SEARCH_RANGE[1], gray.shape[0] - 1)
    if bottom - top < 5:
        return None

    # The puck extends left of the glass, where nothing else covers it.
    strip = gray[top:bottom, x + 2:x + 22].astype(np.float32)
    profile = np.convolve(np.median(strip, axis=1), np.ones(3) / 3, mode="same")
    step = profile[3:] - profile[:-3]
    best = int(np.argmax(step))
    if step[best] < PUCK_MIN_STEP:
        return None
    return top + best + 2


def find_walls(gray: np.ndarray, collar: Roi, puck_top_y: int) -> tuple[int, int] | None:
    """Return (left, right) x of the glass walls between the collar and the puck."""
    x, y, w, h = collar
    center = x + w // 2
    left, right = center - WALL_SEARCH_HALF_WIDTH, center + WALL_SEARCH_HALF_WIDTH
    top, bottom = y + h + 5, puck_top_y - 5
    if bottom - top < 10 or left < 0 or right > gray.shape[1]:
        return None

    sobel = np.abs(cv2.Sobel(gray[top:bottom, left:right].astype(np.float32), cv2.CV_32F, 1, 0, ksize=3))
    profile = np.median(sobel, axis=0)
    half = WALL_SEARCH_HALF_WIDTH
    wall_left = left + int(np.argmax(profile[:half]))
    wall_right = left + half + int(np.argmax(profile[half:]))
    return wall_left, wall_right


def detect_vial(image: np.ndarray, expected_collar: tuple[float, float] | None = None,
                bore_depth: int = DEFAULT_BORE_DEPTH) -> Detection | None:
    """Detect the fill-station vial in a BGR frame, or return None.

    `expected_collar` is an optional (center x, bottom y) to search near.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    collar = find_collar(gray, expected_collar)
    if collar is None:
        return None
    puck_top = find_puck_top(gray, collar)
    if puck_top is None:
        return None
    walls = find_walls(gray, collar, puck_top)
    if walls is None:
        return None

    wall_left, wall_right = walls
    x0 = max(wall_left - WALL_MARGIN, 0)
    x1 = min(wall_right + WALL_MARGIN, gray.shape[1])
    y0 = collar[1] + collar[3]
    y1 = min(puck_top + bore_depth, gray.shape[0])
    return Detection(collar, puck_top, wall_left, wall_right, (x0, y0, x1 - x0, y1 - y0))


def locate_vial(image: np.ndarray, config: CameraConfig | None = None,
                tolerance_px: int = DEFAULT_TOLERANCE_PX,
                max_drift_px: int = DEFAULT_MAX_DRIFT_PX) -> LocateResult:
    """Return the vial liquid ROI, preferring the camera config when detection agrees.

    Quality codes: None (config ROI confirmed), `roi_drift` (small offset; detected ROI
    used), `roi_auto_detected` (no config), `vial_off_station` (large offset, usually a
    moving carrier; not ok), `vial_not_found` (not ok).
    """
    if config is None:
        detection = detect_vial(image)
        if detection is None:
            return LocateResult(False, "vial_not_found", "No collar/puck/walls found.", None, None, None, None)
        return LocateResult(True, "roi_auto_detected", "No camera config; using detection.",
                            detection.vial_xywh, "detected", detection, None)

    cx, cy, cw, ch = config.region("collar")
    lines = config.lines_y
    bore_depth = lines.get("bore_bottom", 0) - lines.get("puck_top", 0) or DEFAULT_BORE_DEPTH
    expected_collar = (cx + cw / 2, lines.get("collar_bottom", cy + ch))
    detection = detect_vial(image, expected_collar=expected_collar, bore_depth=bore_depth)
    if detection is None:
        return LocateResult(False, "vial_not_found", "No collar/puck/walls found near the fill station.",
                            None, None, None, None)

    # The collar's side edges and the puck top are high-contrast; the glass walls of an
    # empty vial are faint, so they are not used for the offset.
    dcx, _, dcw, _ = detection.collar_xywh
    dx = int(round(dcx + dcw / 2 - (cx + cw / 2)))
    dy = int(round(detection.puck_top_y - lines.get("puck_top", detection.puck_top_y)))
    if abs(dx) <= tolerance_px and abs(dy) <= tolerance_px:
        return LocateResult(True, None, None, config.region("vial"), "config", detection, (dx, dy))

    detail = f"Detection differs from config by dx={dx}, dy={dy} px."
    if abs(dx) > max_drift_px or abs(dy) > max_drift_px:
        return LocateResult(False, "vial_off_station", detail + " Carrier is probably moving.",
                            None, None, detection, (dx, dy))
    return LocateResult(True, "roi_drift", detail, detection.vial_xywh, "detected", detection, (dx, dy))
