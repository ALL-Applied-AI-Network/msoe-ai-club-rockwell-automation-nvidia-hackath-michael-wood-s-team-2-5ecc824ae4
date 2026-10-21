"""Measure the average RGB color of a manually selected image region."""

import sys
import json
import argparse
from pathlib import Path

import cv2

# Allow running as `python scripts/measure_color.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv.measure import convert_mean_rgb, measure_rgb  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="Path to the vial image")

    parser.add_argument(
        "--roi",
        type=int,
        nargs=4,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        help="Use a fixed rectangle instead of selecting one manually",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the measurement as JSON",
    )
    args = parser.parse_args()

    image = cv2.imread(str(args.image))
    if image is None:
        parser.error(f"Could not read image: {args.image}")

    if args.roi is not None:
        roi = tuple(args.roi)
    else:
        try:
            roi = cv2.selectROI(
                "Select liquid, then press Enter",
                image,
                showCrosshair=True,
                fromCenter=False,
            )
        finally:
            cv2.destroyAllWindows()

    if args.roi is None and (roi[2] == 0 or roi[3] == 0):
        print("Selection cancelled.")
        return

    try:
        mean_rgb = measure_rgb(image, roi)
    except ValueError as error:
        parser.error(str(error))

    hsv, lab = convert_mean_rgb(mean_rgb)

    if args.json:
        result = {
            "image": str(args.image.resolve()),
            "roi_xywh": list(roi),
            "pixel_count": roi[2] * roi[3],
            "method": "mean_rgb_then_convert",
            "rgb_0_255": mean_rgb,
            "hsv_of_mean_rgb": {
                "h_degrees": float(hsv[0]),
                "s_0_1": float(hsv[1]),
                "v_0_1": float(hsv[2]),
            },
            "lab_of_mean_rgb": {
                "L": float(lab[0]),
                "a": float(lab[1]),
                "b": float(lab[2]),
            },
        }
        print(json.dumps(result, indent=2, allow_nan=False))
    else:
        print(f"Region (x, y, width, height): {roi}")
        print("Mean RGB:", [round(value, 1) for value in mean_rgb])
        print("HSV of mean RGB:", [round(float(value), 3) for value in hsv])
        print("LAB of mean RGB:", [round(float(value), 3) for value in lab])


if __name__ == "__main__":
    main()