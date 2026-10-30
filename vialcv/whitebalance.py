"""White-balance and exposure correction for fixed-camera frames.

Methods:
- `none`: no correction (default).
- `white_patch`: per-channel gains that map the median of the camera's white backdrop
  patch to a fixed neutral gray. Corrects both color cast and exposure, so frames from
  different runs or days are on one scale.
- `gray_world`: per-channel gains that make the frame's mean neutral at its own
  brightness. Corrects color cast only.

Correction removes illumination and camera differences only. A real change in liquid
color (for example a different dye in a tank between runs) stays in the corrected pixels.

On videos 1-5 the backdrop patch median lightness was stable within a video (about +/-1
L between the 5th and 95th percentile stills) but differed between recording days
(L ~62 on 2026-09-22, ~69-70 on 2026-09-23). Its spread across the patch was 16-23
gray levels; a passing vial raised it to ~71.
"""

from dataclasses import dataclass

import numpy as np

from vialcv.roi import CameraConfig, Roi, crop

METHODS = ("none", "white_patch", "gray_world")

# Neutral level the white patch is mapped to (0-255); near the patch's raw level.
TARGET_LEVEL = 160.0

# Patch checks: a vial or hand in front raises the spread; clipping or darkness breaks gains.
MAX_PATCH_SPREAD = 35.0
MAX_PATCH_LEVEL = 250.0
MIN_PATCH_LEVEL = 40.0


@dataclass(frozen=True)
class WhiteBalance:
    ok: bool
    code: str | None
    detail: str | None
    method: str
    gains_rgb: tuple[float, float, float]
    reference_rgb_0_255: tuple[float, float, float] | None = None
    target_level: float | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "code": self.code, "detail": self.detail, "method": self.method,
            "gains_rgb": list(self.gains_rgb),
            "reference_rgb_0_255": None if self.reference_rgb_0_255 is None else list(self.reference_rgb_0_255),
            "target_level": self.target_level,
        }


NO_CORRECTION = WhiteBalance(True, None, None, "none", (1.0, 1.0, 1.0))


def estimate_white_patch(image_bgr: np.ndarray, roi: Roi, target_level: float = TARGET_LEVEL) -> WhiteBalance:
    """Return gains mapping the white patch's median to `target_level` in every channel."""
    patch = crop(image_bgr, roi).reshape(-1, 3).astype(np.float64)
    level_rgb = np.median(patch, axis=0)[::-1]
    brightness = patch.mean(axis=1)
    spread = float(np.percentile(brightness, 95) - np.percentile(brightness, 5))

    def failure(code, detail):
        return WhiteBalance(False, code, detail, "white_patch", (1.0, 1.0, 1.0), tuple(level_rgb.tolist()), target_level)

    if spread > MAX_PATCH_SPREAD:
        return failure("white_reference_occluded", f"Patch spread {spread:.0f} > {MAX_PATCH_SPREAD:.0f}; "
                       "something is in front of the backdrop.")
    if level_rgb.max() > MAX_PATCH_LEVEL:
        return failure("white_reference_saturated", "Patch is clipped; gains would be wrong.")
    if level_rgb.min() < MIN_PATCH_LEVEL:
        return failure("white_reference_dark", "Patch is too dark to estimate gains.")

    gains = tuple((target_level / level_rgb).tolist())
    return WhiteBalance(True, None, None, "white_patch", gains, tuple(level_rgb.tolist()), target_level)


def estimate_gray_world(image_bgr: np.ndarray, exclude: list[Roi] | None = None) -> WhiteBalance:
    """Return gains that make the frame's mean color neutral at its own brightness."""
    keep = np.ones(image_bgr.shape[:2], dtype=bool)
    for x, y, w, h in exclude or []:
        keep[y:y + h, x:x + w] = False
    mean_rgb = image_bgr[keep].reshape(-1, 3).astype(np.float64).mean(axis=0)[::-1]
    if mean_rgb.min() < 1.0:
        return WhiteBalance(False, "image_too_dark", "A channel mean is ~0.", "gray_world", (1.0, 1.0, 1.0))
    gains = tuple((mean_rgb.mean() / mean_rgb).tolist())
    return WhiteBalance(True, None, None, "gray_world", gains, tuple(mean_rgb.tolist()), float(mean_rgb.mean()))


def apply_gains(image_bgr: np.ndarray, balance: WhiteBalance) -> np.ndarray:
    """Return a float32 BGR image (0-255) with the gains applied and values clipped."""
    gains_bgr = np.array(balance.gains_rgb[::-1], dtype=np.float32)
    return np.clip(image_bgr.astype(np.float32) * gains_bgr, 0.0, 255.0)


def white_balance(image_bgr: np.ndarray, method: str = "none",
                  config: CameraConfig | None = None) -> tuple[np.ndarray, WhiteBalance]:
    """Estimate and apply a correction; on failure, return the uncorrected image and why."""
    if method not in METHODS:
        raise ValueError(f"Unknown white-balance method {method!r}; expected one of {METHODS}.")
    if method == "none":
        return image_bgr.astype(np.float32), NO_CORRECTION

    if method == "white_patch":
        if config is None or "white_reference" not in config.regions:
            raise ValueError("white_patch needs a camera config with a white_reference region.")
        balance = estimate_white_patch(image_bgr, config.region("white_reference"))
    else:
        exclude = [config.region("timestamp_overlay")] if config and "timestamp_overlay" in config.regions else None
        balance = estimate_gray_world(image_bgr, exclude)

    if not balance.ok:
        return image_bgr.astype(np.float32), balance
    return apply_gains(image_bgr, balance), balance
