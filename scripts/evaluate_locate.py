"""Run the vial locator on every indexed still of chosen videos and summarize the results.

Writes one CSV row per still (quality code, offsets, detected parts) and prints counts
per video and offset percentiles. For video 5 it also cross-tabulates codes against the
official `in_fill` label. Videos 1-4 set the locator thresholds; video 5 is evaluation.
"""

import sys
import argparse
from pathlib import Path

import cv2
import pandas as pd

# Allow running as `python scripts/evaluate_locate.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv import dataset  # noqa: E402
from vialcv.locate import locate_vial  # noqa: E402
from vialcv.roi import load_camera_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos", type=int, nargs="+", default=[1, 2, 3, 4])
    parser.add_argument("--out", type=Path, default=Path("outputs/locate/locate_eval.csv"))
    parser.add_argument("--dataset-root", help="Defaults to $DATASET_ROOT")
    args = parser.parse_args()

    config = load_camera_config("vial_fill")
    index = dataset.load_image_index("vial_fill", args.dataset_root)

    rows = []
    for still in index[index["video_id"].isin(args.videos)].itertuples():
        path = dataset.image_path("vial_fill", still.filename, args.dataset_root)
        image = cv2.imread(str(path))
        if image is None:
            rows.append({"filename": still.filename, "video_id": still.video_id, "code": "unreadable_image"})
            continue

        result = locate_vial(image, config)
        row = {
            "filename": still.filename,
            "video_id": still.video_id,
            "code": result.code or "config_confirmed",
            "ok": result.ok,
            "dx": result.offset_xy[0] if result.offset_xy else None,
            "dy": result.offset_xy[1] if result.offset_xy else None,
        }
        if result.detection:
            x, y, w, h = result.detection.collar_xywh
            row.update(collar_x=x, collar_bottom_y=y + h, puck_top_y=result.detection.puck_top_y,
                       wall_left_x=result.detection.wall_left_x, wall_right_x=result.detection.wall_right_x)
        rows.append(row)

    table = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)

    print(table.groupby("video_id")["code"].value_counts().unstack(fill_value=0).to_string())
    for column in ("dx", "dy"):
        values = table[column].dropna()
        print(f"{column}: median {values.median():.0f}, p1 {values.quantile(0.01):.0f}, "
              f"p99 {values.quantile(0.99):.0f}")

    if 5 in args.videos:
        labels = dataset.load_frame_labels(args.dataset_root)[["filename", "in_fill"]]
        labeled = table.merge(labels, on="filename")
        print(pd.crosstab(labeled["code"], labeled["in_fill"].map({1: "in_fill", 0: "between_fills"})).to_string())
    print(f"wrote {args.out.as_posix()}")


if __name__ == "__main__":
    main()
