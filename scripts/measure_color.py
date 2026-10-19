"""Measure the average RGB color of a manually selected image region."""

import argparse
from pathlib import Path

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="Path to the vial image")
    args = parser.parse_args()

    image = cv2.imread(str(args.image))
    if image is None:
        parser.error(f"Could not read image: {args.image}")

    try:
        roi = cv2.selectROI(
            "Select liquid, then press Enter",
            image,
            showCrosshair=True,
            fromCenter=False,
        )
    finally:
        cv2.destroyAllWindows()

    if roi[2] == 0 or roi[3] == 0:
        print("Selection cancelled.")
        return

    mean_rgb = measure_rgb(image, roi)

    # Represent the mean color as one RGB pixel, normalized to 0–1.
    mean_pixel = np.array([[mean_rgb]], dtype=np.float32) / 255.0

    hsv = cv2.cvtColor(mean_pixel, cv2.COLOR_RGB2HSV)[0, 0]
    lab = cv2.cvtColor(mean_pixel, cv2.COLOR_RGB2Lab)[0, 0]

    print(f"Region (x, y, width, height): {roi}")
    print("Mean RGB:", [round(value, 1) for value in mean_rgb])
    print("HSV of mean RGB:", [round(float(value), 3) for value in hsv])
    print("LAB of mean RGB:", [round(float(value), 3) for value in lab])


if __name__ == "__main__":
    main()