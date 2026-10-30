"""Mean-color measurement of image regions (the CV baseline)."""

import cv2
import numpy as np


def measure_rgb(image: np.ndarray, roi: tuple[int, int, int, int]) -> list[float]:
    """Return mean RGB values for a rectangular region in a BGR image."""
    x, y, width, height = roi
    image_height, image_width = image.shape[:2]

    if (
        width <= 0
        or height <= 0
        or x < 0
        or y < 0
        or x + width > image_width
        or y + height > image_height
    ):
        raise ValueError("Region must be nonempty and inside the image.")

    patch = image[y:y + height, x:x + width]
    rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
    return rgb.mean(axis=(0, 1)).tolist()


def measure_rgb_masked(image: np.ndarray, mask: np.ndarray) -> list[float]:
    """Return mean RGB values for the pixels selected by a mask in a BGR image."""
    if mask.shape != image.shape[:2]:
        raise ValueError("Mask must have the same height and width as the image.")

    selected = mask.astype(bool)
    if not selected.any():
        raise ValueError("Mask must select at least one pixel.")

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return rgb[selected].mean(axis=0).tolist()


def convert_mean_rgb(mean_rgb: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Return (HSV, LAB) of a mean RGB color, using OpenCV float conversions."""
    # Represent the mean color as one RGB pixel, normalized to 0–1.
    mean_pixel = np.array([[mean_rgb]], dtype=np.float32) / 255.0

    hsv = cv2.cvtColor(mean_pixel, cv2.COLOR_RGB2HSV)[0, 0]
    lab = cv2.cvtColor(mean_pixel, cv2.COLOR_RGB2Lab)[0, 0]
    return hsv, lab
