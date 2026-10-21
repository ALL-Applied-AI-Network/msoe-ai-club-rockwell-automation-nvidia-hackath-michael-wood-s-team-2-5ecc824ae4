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
from vialcv.roi import load_camera_config  # noqa: E402

COLORS = [(0, 0, 255), (0, 200, 0), (255, 0, 0), (0, 200, 255), (255, 0, 255), (128, 128, 128)]

# Part of the vial_fill scene that does not move with the vial carriers.
STATIC_REGION_XYWH = (200, 0, 240, 70)


def draw_regions(image: np.ndarray, config) -> np.ndarray:
    canvas = image.copy()
    for color, (name, (x, y, w, h)) in zip(COLORS, config.regions.items()):
        cv2.rectangle(canvas, (x, y), (x + w - 1, y + h - 1), color, 1)
        cv2.putText(canvas, name, (x, max(y - 3, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)
    for name, y in config.lines_y.items():
        cv2.line(canvas, (250, y), (390, y), (255, 255, 255), 1)
    return canvas


def contact_sheet(tiles: list[np.ndarray], columns: int) -> np.ndarray:
    blank = np.zeros_like(tiles[0])
    tiles = tiles + [blank] * (-len(tiles) % columns)
    rows = [np.hstack(tiles[i:i + columns]) for i in range(0, len(tiles), columns)]
    return np.vstack(rows)


def static_median(images: list[np.ndarray]) -> np.ndarray:
    x, y, w, h = STATIC_REGION_XYWH
    gray = [cv2.cvtColor(image[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY) for image in images]
    return np.median(np.stack(gray), axis=0).astype(np.float32)


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

        median = static_median(images)
        if reference is None:
            reference, reference_id = median, video_id
            shift = "reference"
        else:
            (dx, dy), response = cv2.phaseCorrelate(reference, median)
            shift = f"shift vs video {reference_id}: dx={dx:+.2f} px, dy={dy:+.2f} px (response {response:.2f})"
        print(f"video {video_id}: {len(images)} stills, {shift}, sheet {sheet_path.as_posix()}")


if __name__ == "__main__":
    main()
