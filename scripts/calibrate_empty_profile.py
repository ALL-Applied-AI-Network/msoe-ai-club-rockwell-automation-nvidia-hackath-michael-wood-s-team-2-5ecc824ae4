"""Build the camera-level empty-vial profile used when no per-event reference exists.

Takes the empty-vial reference frames saved by scripts/extract_vials.py for the given
(calibration) videos, crops the configured vial ROI, and stores the per-row median Lab
over the glass interior. Writes configs/cameras/<camera>_empty_profile.json: numbers only,
with the source videos and frame count recorded.
"""

import sys
import json
import argparse
from pathlib import Path

import cv2
import numpy as np

# Allow running as `python scripts/calibrate_empty_profile.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv.roi import CONFIG_DIR, crop, load_camera_config  # noqa: E402
from vialcv.segment import find_interior, to_lab  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos", type=int, nargs="+", default=[1, 2, 3, 4])
    parser.add_argument("--vials-dir", type=Path, default=Path("outputs/vials"))
    parser.add_argument("--camera", default="vial_fill")
    args = parser.parse_args()

    config = load_camera_config(args.camera)
    roi = config.region("vial")
    puck_row = config.lines_y["puck_top"] - roi[1]

    profiles = []
    for video_id in args.videos:
        for path in sorted((args.vials_dir / f"video{video_id}").glob("*_ref_*.png")):
            vial = crop(cv2.imread(str(path)), roi)
            left, right = find_interior(vial, puck_row)
            profiles.append(np.median(to_lab(vial)[:, left:right], axis=1))
    if not profiles:
        raise SystemExit("No reference frames found; run scripts/extract_vials.py first.")

    stack = np.stack(profiles).astype(np.float64)
    rows_lab = np.round(np.median(stack, axis=0), 2)
    spread = np.round(np.subtract(*np.percentile(stack, [75, 25], axis=0)), 2)
    header = {
        "camera_id": args.camera,
        "roi_xywh": list(roi),
        "space": "opencv_float_lab",
        "calibration": {
            "source": f"empty-vial reference frames from vial_fill videos {args.videos}",
            "n_frames": len(profiles),
            "data_origin": "real_line",
            "generator": "scripts/calibrate_empty_profile.py",
        },
    }

    # One profile row per line keeps the file reviewable in diffs.
    def rows(values):
        return "[\n" + ",\n".join("  " + json.dumps(row.tolist()) for row in values) + "\n ]"

    text = json.dumps(header, indent=1)[:-2]
    text += f',\n "rows_lab": {rows(rows_lab)},\n "rows_lab_spread_iqr": {rows(spread)}\n}}\n'
    json.loads(text)  # fail loudly rather than write a broken config
    out = CONFIG_DIR / f"{args.camera}_empty_profile.json"
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out.relative_to(CONFIG_DIR.parents[1]).as_posix()} from {len(profiles)} frames; "
          f"median row IQR in L: {np.median(spread, axis=0)[0]:.1f}")


if __name__ == "__main__":
    main()
