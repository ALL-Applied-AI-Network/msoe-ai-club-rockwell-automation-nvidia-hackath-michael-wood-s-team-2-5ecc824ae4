"""Detect a vial's measured liquid color (RGB, HSV, Lab) and fill level from one image.

IMAGE can be a full vial_fill camera frame (the vial is located automatically), a vial
crop the size of the configured vial ROI (as saved by scripts/extract_vials.py), or any
other crop of a vial (measured without background zones).

Exit status: 0 when a color was measured, 1 when quality checks failed (the record
still explains why), 2 for usage errors such as an unreadable image or a --roi outside it.
"""

import os
import sys
import json
import argparse
from pathlib import Path

import cv2
import numpy as np

# Allow running as `python scripts/detect_vial_color.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv.detect import DATA_ORIGINS, detect_vial_color  # noqa: E402
from vialcv.roi import validate_roi  # noqa: E402
from vialcv.whitebalance import METHODS  # noqa: E402


def make_image_ref(path: Path) -> str:
    """Dataset-relative path when inside $DATASET_ROOT, else the bare file name."""
    root = os.environ.get("DATASET_ROOT")
    if root:
        try:
            return path.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def draw_overlay(image: np.ndarray, record: dict, path: Path) -> None:
    canvas = image.copy()
    if record["roi_xywh"]:
        x, y, w, h = record["roi_xywh"]
        cv2.rectangle(canvas, (x, y), (x + w - 1, y + h - 1), (0, 255, 255), 1)
        fill = record.get("fill") or {}
        if fill.get("fill_line_y_px") is not None and fill.get("coordinates") == "frame" \
                and record["input"] == "full_frame":
            fy = fill["fill_line_y_px"]
            cv2.line(canvas, (x - 10, fy), (x + w + 10, fy), (0, 0, 255), 1)
    label = (f"{record['color']['primary_zone']} Lab "
             + " ".join(f"{v:.0f}" for v in record["color"]["primary"]["lab"]["median"].values())
             if record["quality"]["ok"] else f"FAILED: {record['quality']['code']}")
    cv2.putText(canvas, label, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
    cv2.imwrite(str(path), canvas)


def summary(record: dict) -> str:
    quality = record["quality"]
    lines = [f"Image: {record['image_ref']}  (input: {record['input']}, ROI {record['roi_xywh']} "
             f"from {record['roi_source']})"]
    fill = record.get("fill")
    if fill:
        level = f", fill line y={fill['fill_line_y_px']}" if fill["fill_line_y_px"] is not None else ""
        lines.append(f"Fill: {fill['state']}{level}")
    if not quality["ok"]:
        lines.append(f"Quality: FAILED {quality['code']}: {quality['detail']}")
        return "\n".join(lines)

    color = record["color"]
    primary = color["primary"]
    lab, hsv = primary["lab"]["median"], primary["hsv"]
    hue = hsv["h_circular_mean_degrees"]
    lines += [
        f"Zone: {color['primary_zone']}  ({primary['pixel_count']} liquid pixels)",
        "RGB median: " + str([round(v, 1) for v in primary["rgb_0_255"]["median"]]),
        f"HSV: hue {'n/a' if hue is None else f'{hue:.1f}'} deg (circular, resultant {hsv['h_resultant_length']:.2f}), "
        f"s {hsv['s_0_1_median']:.3f}, v {hsv['v_0_1_median']:.3f}",
        f"Lab median: L {lab['L']:.2f}, a {lab['a']:.2f}, b {lab['b']:.2f}",
    ]
    others = [name for name, z in color["zones"].items() if z.get("ok") and name != color["primary_zone"]]
    if others:
        lines.append("Other zones (see --json): " + ", ".join(others))
    if quality["warnings"]:
        lines.append("Warnings: " + ", ".join(quality["warnings"]))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path, help="Path to the vial image")
    parser.add_argument("--camera", default="vial_fill", help="Camera config id (default vial_fill)")
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"),
                        help="Use this vial rectangle instead of locating the vial")
    parser.add_argument("--reference", type=Path, help="Empty-vial image with the same framing")
    parser.add_argument("--white-balance", choices=METHODS, default="none")
    parser.add_argument("--data-origin", choices=DATA_ORIGINS, default="unknown",
                        help="Origin of the input image, recorded in provenance")
    parser.add_argument("--json", action="store_true", help="Print the full record as JSON")
    parser.add_argument("--debug-overlay", type=Path, help="Write an overlay image here")
    args = parser.parse_args()

    image = cv2.imread(str(args.image))
    if image is None:
        parser.error(f"Could not read image: {args.image}")
    if args.roi:
        try:
            validate_roi(tuple(args.roi), (image.shape[1], image.shape[0]))
        except ValueError as error:
            parser.error(str(error))
    reference = None
    if args.reference:
        reference = cv2.imread(str(args.reference))
        if reference is None:
            parser.error(f"Could not read reference image: {args.reference}")

    record = detect_vial_color(
        image,
        camera_id=args.camera,
        roi=tuple(args.roi) if args.roi else None,
        white_balance_method=args.white_balance,
        reference_bgr=reference,
        image_ref=make_image_ref(args.image),
        source_data_origin=args.data_origin,
    )

    if args.debug_overlay:
        draw_overlay(image, record, args.debug_overlay)
    print(json.dumps(record, indent=2, allow_nan=False) if args.json else summary(record))
    sys.exit(0 if record["quality"]["ok"] else 1)


if __name__ == "__main__":
    main()
