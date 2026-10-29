"""Draw a camera's configured ROIs on sampled stills and check the camera for drift.

Writes one contact sheet per video to the output folder and prints, per video, the
shift of the static scene (nozzle and background) relative to the first video listed.
"""

import sys
import argparse
from pathlib import Path

import cv2
import numpy as np

# Allow running as `python scripts/roi_overlay.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv import dataset  # noqa: E402
from vialcv.roi import camera_shift, contact_sheet, draw_regions, load_camera_config, static_scene  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", default="vial_fill")
    parser.add_argument("--videos", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--per-video", type=int, default=12, help="Stills per contact sheet")
    parser.add_argument("--out", type=Path, default=Path("outputs/roi_check"))
    parser.add_argument("--dataset-root", help="Defaults to $DATASET_ROOT")
    args = parser.parse_args()

    config = load_camera_config(args.camera)
    index = dataset.load_image_index(args.camera, args.dataset_root)
    args.out.mkdir(parents=True, exist_ok=True)

    reference = None
    for video_id in args.videos:
        rows = index[index["video_id"] == video_id].reset_index(drop=True)
        if rows.empty:
            print(f"video {video_id}: no stills")
            continue

        picks = np.linspace(0, len(rows) - 1, min(args.per_video, len(rows))).round().astype(int)
        images, tiles = [], []
        for pick in picks:
            filename = rows.loc[pick, "filename"]
            image = cv2.imread(str(dataset.image_path(args.camera, filename, args.dataset_root)))
            if image is None:
                print(f"video {video_id}: could not read {filename}")
                continue
            images.append(image)
            tile = draw_regions(image, config)
            cv2.putText(tile, f"v{video_id} {filename}", (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
            tiles.append(tile)

        sheet_path = args.out / f"{args.camera}_video{video_id}.jpg"
        cv2.imwrite(str(sheet_path), contact_sheet(tiles, columns=4))

        median = static_scene(images, config)
        if reference is None:
            reference, reference_id = median, video_id
            shift = "reference"
        else:
            dx, dy, response = camera_shift(reference, median)
            shift = f"shift vs video {reference_id}: dx={dx:+.2f} px, dy={dy:+.2f} px (response {response:.2f})"
        print(f"video {video_id}: {len(images)} stills, {shift}, sheet {sheet_path.as_posix()}")


if __name__ == "__main__":
    main()
