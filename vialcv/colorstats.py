"""Robust per-pixel color statistics for a masked image region.

Every pixel in the mask is converted to RGB, HSV, and Lab, and each space is summarized
with robust statistics instead of a plain mean:

- RGB and Lab: per-channel median, trimmed mean, and MAD (scaled to a normal sigma).
- HSV hue is an angle, so it is averaged as a vector: circular mean, resultant length
  (1 = all hues equal, 0 = no common hue), and circular standard deviation. Hue of
  near-gray pixels is meaningless, so the vector mean is weighted by saturation.

Conversions follow docs/interfaces.md: OpenCV float conversions from sRGB scaled to 0-1
(HSV h in degrees, s and v 0-1; Lab L 0-100). OpenCV float Lab agrees with scikit-image's
sRGB/D65 Lab to within dE00 0.32, so CIEDE2000 comes from scikit-image.

The baseline's mean-RGB-then-convert values are kept alongside for comparison.
"""

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000

from vialcv.measure import convert_mean_rgb

TRIM_FRACTION = 0.1
MAD_TO_SIGMA = 1.4826
MIN_PIXELS = 50

METHOD = "per_pixel_robust"


def masked_rgb(image_bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Return the masked pixels as an (N, 3) float RGB array on a 0-255 scale."""
    if mask.shape != image_bgr.shape[:2]:
        raise ValueError("Mask must have the same height and width as the image.")
    return image_bgr[mask.astype(bool)][:, ::-1].astype(np.float64)


def rgb_to_hsv_lab(rgb_0_255: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Convert (N, 3) RGB 0-255 to OpenCV float HSV (h degrees, s/v 0-1) and Lab."""
    pixels = (rgb_0_255 / 255.0).astype(np.float32).reshape(-1, 1, 3)
    hsv = cv2.cvtColor(pixels, cv2.COLOR_RGB2HSV).reshape(-1, 3)
    lab = cv2.cvtColor(pixels, cv2.COLOR_RGB2Lab).reshape(-1, 3)
    return hsv.astype(np.float64), lab.astype(np.float64)


def trimmed_mean(values: np.ndarray, fraction: float = TRIM_FRACTION) -> np.ndarray:
    """Per-column mean after dropping `fraction` of values from each end."""
    ordered = np.sort(values, axis=0)
    cut = int(len(ordered) * fraction)
    return ordered[cut:len(ordered) - cut].mean(axis=0)


def robust_summary(values: np.ndarray) -> dict[str, list[float]]:
    median = np.median(values, axis=0)
    mad = np.median(np.abs(values - median), axis=0) * MAD_TO_SIGMA
    return {
        "median": median.tolist(),
        "trimmed_mean": trimmed_mean(values).tolist(),
        "mad_sigma": mad.tolist(),
    }


def circular_hue(h_degrees: np.ndarray, weights: np.ndarray | None = None) -> dict[str, float | None]:
    """Return the circular mean, resultant length, and circular std of hues in degrees."""
    angles = np.deg2rad(h_degrees)
    weights = np.ones_like(angles) if weights is None else np.asarray(weights, dtype=np.float64)
    total = weights.sum()
    if total <= 0:
        return {"h_circular_mean_degrees": None, "h_resultant_length": 0.0, "h_circular_std_degrees": None}

    x = float((weights * np.cos(angles)).sum() / total)
    y = float((weights * np.sin(angles)).sum() / total)
    length = float(np.hypot(x, y))
    if length < 1e-9:
        return {"h_circular_mean_degrees": None, "h_resultant_length": 0.0, "h_circular_std_degrees": None}
    return {
        "h_circular_mean_degrees": float(np.rad2deg(np.arctan2(y, x)) % 360.0),
        "h_resultant_length": length,
        "h_circular_std_degrees": float(np.rad2deg(np.sqrt(-2.0 * np.log(min(length, 1.0))))),
    }


def delta_e_2000(lab_1, lab_2) -> float:
    """Return CIEDE2000 between two Lab colors (L 0-100)."""
    return float(deltaE_ciede2000(np.asarray(lab_1, dtype=np.float64), np.asarray(lab_2, dtype=np.float64)))


def lab_dict(values) -> dict[str, float]:
    return {"L": float(values[0]), "a": float(values[1]), "b": float(values[2])}


def describe_color(image_bgr: np.ndarray, mask: np.ndarray, min_pixels: int = MIN_PIXELS) -> dict:
    """Return robust RGB/HSV/Lab statistics of the masked pixels, or a structured failure."""
    rgb = masked_rgb(image_bgr, mask)
    if len(rgb) < min_pixels:
        return {"ok": False, "code": "too_few_pixels", "pixel_count": int(len(rgb)),
                "detail": f"{len(rgb)} pixels; at least {min_pixels} needed."}

    hsv, lab = rgb_to_hsv_lab(rgb)
    rgb_stats = robust_summary(rgb)
    lab_stats = robust_summary(lab)

    mean_rgb = rgb.mean(axis=0).tolist()
    mean_hsv, mean_lab = convert_mean_rgb(mean_rgb)

    return {
        "ok": True,
        "pixel_count": int(len(rgb)),
        "method": METHOD,
        "rgb_0_255": rgb_stats,
        "hsv": {
            **circular_hue(hsv[:, 0], weights=hsv[:, 1]),
            "h_weighting": "saturation",
            "s_0_1_median": float(np.median(hsv[:, 1])),
            "v_0_1_median": float(np.median(hsv[:, 2])),
        },
        "lab": {
            "median": lab_dict(lab_stats["median"]),
            "trimmed_mean": lab_dict(lab_stats["trimmed_mean"]),
            "mad_sigma": lab_dict(lab_stats["mad_sigma"]),
        },
        "mean_rgb_then_convert": {
            "rgb_0_255": mean_rgb,
            "hsv_of_mean_rgb": {"h_degrees": float(mean_hsv[0]), "s_0_1": float(mean_hsv[1]),
                                "v_0_1": float(mean_hsv[2])},
            "lab_of_mean_rgb": lab_dict(mean_lab),
        },
    }


def describe_zones(image_bgr: np.ndarray, zone_masks: dict[str, np.ndarray],
                   min_pixels: int = MIN_PIXELS) -> dict[str, dict]:
    """Return describe_color for each background zone mask."""
    return {name: describe_color(image_bgr, mask, min_pixels) for name, mask in zone_masks.items()}
