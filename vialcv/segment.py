"""Segment the liquid inside a vial crop and find its fill line.

Works on a crop of the camera's vial ROI (glass column from the collar bottom down
through the visible puck bore). Liquid pixels are found, in order of preference:

1. against an empty-vial reference crop of the same vial (the frame before the pour);
2. against the camera's per-row empty-vial profile (configs/cameras/<id>_empty_profile.json);
3. by Lab chroma alone, which cannot see clear liquid or dark liquid on a dark background.

The background behind the glass changes down the column (white backdrop, dark belt,
bright puck bore), and it changes how the same liquid looks. The color mask is therefore
also split by background zone. The bright band at the liquid surface and specular glare
are excluded from the color mask.

Thresholds were set on videos 1-4 (calibration).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from vialcv.roi import CONFIG_DIR, CameraConfig, Roi

# Glass walls are the strongest vertical edges near each side of the crop.
WALL_SEARCH_COLUMNS = 15
WALL_INSET = 4

# CIE76 difference from the empty reference or profile that counts as liquid.
REFERENCE_DELTA_E = 12.0
# Last resort without any reference: Lab chroma that counts as colored liquid.
NO_REFERENCE_CHROMA = 18.0

# With a reference or profile, the detected column must differ from empty by at least
# this median CIE76; pale and clear liquids (video 3: 9-16) fall below it and would
# otherwise give a wrong fill line. Correct columns on videos 1-4 were 26-40.
MIN_COLUMN_DELTA_E = 20.0

# A row is liquid when at least this fraction of its interior pixels are.
ROW_LIQUID_FRACTION = 0.5
# The liquid column must reach within this many rows of the bottom of the crop.
BOTTOM_SLACK_ROWS = 25
# A fill line within this many rows of the top means the surface is at or above the view.
TOP_SLACK_ROWS = 2

# Rows below the fill line that hold the bright meniscus band.
MENISCUS_ROWS = 7

# Glare: much brighter than the liquid's median lightness, or near-white and colorless.
GLARE_DELTA_L = 20.0
GLARE_MIN_L = 85.0
GLARE_MAX_CHROMA = 15.0

MIN_MASK_PIXELS = 150
MAX_GLARE_FRACTION = 0.3

# Rows just below backdrop_bottom are skipped: liquid lensing moves the backdrop edge down.
BACKDROP_EDGE_SKIP = 16


@dataclass(frozen=True)
class Segmentation:
    ok: bool
    code: str | None
    detail: str | None
    method: str
    fill_state: str
    fill_line_row: int | None
    interior_columns: tuple[int, int]
    mask: np.ndarray | None
    glare_mask: np.ndarray | None
    mask_pixel_count: int
    glare_fraction: float
    zone_masks: dict[str, np.ndarray] = field(default_factory=dict)


def to_lab(crop_bgr: np.ndarray) -> np.ndarray:
    """Return float Lab (L 0-100) using OpenCV's float sRGB conversion."""
    return cv2.cvtColor(crop_bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)


def load_empty_profile(camera_id: str, config_dir: str | Path | None = None) -> np.ndarray | None:
    """Return the camera's per-row empty-vial Lab profile, or None if not calibrated."""
    path = Path(config_dir or CONFIG_DIR) / f"{camera_id}_empty_profile.json"
    if not path.is_file():
        return None
    return np.asarray(json.loads(path.read_text(encoding="utf-8"))["rows_lab"], dtype=np.float32)


def crop_zones(config: CameraConfig, roi: Roi) -> dict[str, tuple[int, int]]:
    """Return background zones as [first, last) crop rows for a crop of `roi`."""
    lines, y0, height = config.lines_y, roi[1], roi[3]

    def rows(top, bottom):
        return max(top - y0, 0), min(max(bottom - y0, 0), height)

    return {
        "backlit": rows(lines["collar_bottom"], lines["backdrop_bottom"]),
        "dark_background": rows(lines["backdrop_bottom"] + BACKDROP_EDGE_SKIP, lines["puck_top"]),
        "bore": rows(lines["bore_view_top"], lines["bore_bottom"]),
    }


def find_interior(crop_bgr: np.ndarray, bottom_row: int | None = None) -> tuple[int, int]:
    """Return [left, right) columns inside the glass walls of a vial crop."""
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    rows = gray[: bottom_row or gray.shape[0]]
    width = gray.shape[1]
    search = min(WALL_SEARCH_COLUMNS, width // 3)
    profile = np.median(np.abs(cv2.Sobel(rows, cv2.CV_32F, 1, 0, ksize=3)), axis=0)
    left = int(np.argmax(profile[:search]))
    right = width - search + int(np.argmax(profile[width - search:]))
    left, right = left + WALL_INSET, right - WALL_INSET + 1
    if right - left < 5:
        left, right = WALL_INSET, width - WALL_INSET
    return left, right


def liquid_block(row_fraction: np.ndarray) -> tuple[int, int] | None:
    """Return (top, bottom) rows of the liquid column that rises from the crop bottom."""
    liquid = row_fraction >= ROW_LIQUID_FRACTION
    rows = np.flatnonzero(liquid)
    if len(rows) == 0:
        return None
    bottom = int(rows[-1])
    if bottom < len(row_fraction) - BOTTOM_SLACK_ROWS:
        return None
    top = bottom
    while top > 0 and liquid[top - 1]:
        top -= 1
    return top, bottom


def segment_liquid(crop_bgr: np.ndarray, reference_bgr: np.ndarray | None = None,
                   puck_top_row: int | None = None, empty_profile_lab: np.ndarray | None = None,
                   zones: dict[str, tuple[int, int]] | None = None) -> Segmentation:
    """Segment liquid in a vial crop.

    `reference_bgr` is an empty-vial crop of the same vial and shape; `empty_profile_lab`
    is a per-row Lab profile with one row per crop row. `puck_top_row` limits the wall
    search to the glass above the puck. `zones` maps zone names to [first, last) rows.
    """
    interior = find_interior(crop_bgr, puck_top_row)
    lab = to_lab(crop_bgr)
    chroma = np.hypot(lab[..., 1], lab[..., 2])

    delta = None
    if reference_bgr is not None:
        if reference_bgr.shape != crop_bgr.shape:
            raise ValueError("Reference crop must have the same shape as the vial crop.")
        delta = np.linalg.norm(lab - to_lab(reference_bgr), axis=2)
        method = "delta_e76_vs_empty_reference"
    elif empty_profile_lab is not None and len(empty_profile_lab) == crop_bgr.shape[0]:
        delta = np.linalg.norm(lab - empty_profile_lab[:, None, :], axis=2)
        method = "delta_e76_vs_camera_empty_profile"
    else:
        method = "lab_chroma_threshold"
    liquid_px = delta > REFERENCE_DELTA_E if delta is not None else chroma > NO_REFERENCE_CHROMA

    left, right = interior
    fraction = liquid_px[:, left:right].mean(axis=1).astype(np.float32).reshape(-1, 1)
    block = liquid_block(cv2.medianBlur(fraction, 5).ravel())

    def failure(code, detail, fill_state="unknown"):
        return Segmentation(False, code, detail, method, fill_state, None, interior, None, None, 0, 0.0)

    if block is None:
        if method == "lab_chroma_threshold":
            return failure("low_contrast", "No colored liquid column found; clear or dark liquid "
                           "cannot be seen without an empty reference.")
        return failure("no_liquid_detected", "No liquid column differs from the empty reference; "
                       "the vial is empty or holds clear or very pale liquid.")

    top, bottom = block
    if delta is not None:
        column_delta = float(np.median(delta[top:bottom + 1, left:right]))
        if column_delta < MIN_COLUMN_DELTA_E:
            return failure("low_contrast", f"Liquid differs from empty by median dE76 {column_delta:.0f} "
                           f"(< {MIN_COLUMN_DELTA_E:.0f}); pale or clear liquid, fill line not reliable.")
    fill_state = "at_or_above_view_top" if top <= TOP_SLACK_ROWS else "in_view"

    region = np.zeros(liquid_px.shape, dtype=bool)
    region[top:bottom + 1, left:right] = True
    if fill_state == "in_view":
        region[top:top + MENISCUS_ROWS] = False
    region &= liquid_px

    lightness = lab[..., 0]
    glare = np.zeros_like(region)
    if region.any():
        median_l = float(np.median(lightness[region]))
        glare = region & ((lightness > median_l + GLARE_DELTA_L)
                          | ((lightness > GLARE_MIN_L) & (chroma < GLARE_MAX_CHROMA)))
    mask = region & ~glare
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)

    zone_masks = {}
    for name, (first, last) in (zones or {}).items():
        zone = np.zeros_like(mask)
        zone[first:last] = mask[first:last]
        zone_masks[name] = zone

    glare_fraction = float(glare.sum() / max(region.sum(), 1))
    count = int(mask.sum())
    ok, code, detail = True, None, None
    if count < MIN_MASK_PIXELS:
        ok, code, detail = False, "mask_too_small", f"Only {count} liquid pixels after masking."
    elif glare_fraction > MAX_GLARE_FRACTION:
        code, detail = "glare_fraction_high", f"{glare_fraction:.0%} of liquid pixels masked as glare."

    return Segmentation(ok, code, detail, method, fill_state, top, interior,
                        mask if ok else None, glare, count, glare_fraction, zone_masks if ok else {})
