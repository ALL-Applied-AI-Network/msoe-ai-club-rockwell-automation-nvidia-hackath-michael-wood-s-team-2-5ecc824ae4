"""Segment liquid in extracted settled-vial frames and draw debug overlays.

Reads outputs/vials/video<N>/manifest.csv from scripts/extract_vials.py. For each frame,
segments the vial crop against its event's empty reference (when one was saved) and
against the camera's empty profile, writes segments.csv, and saves a contact sheet per
video: green = color mask, magenta = glare, red line = fill line, yellow = wall trim,
cyan ticks = background zone limits.
"""

import sys
import argparse
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

# Allow running as `python scripts/segment_vials.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv.roi import crop, load_camera_config  # noqa: E402
from vialcv.segment import crop_zones, load_empty_profile, segment_liquid  # noqa: E402

SCALE = 3


def overlay(vial_crop: np.ndarray, result, zones: dict[str, tuple[int, int]]) -> np.ndarray:
    canvas = vial_crop.copy()
    if result.glare_mask is not None:
        canvas[result.glare_mask] = (255, 0, 255)
    if result.mask is not None:
        canvas[result.mask] = (0.5 * canvas[result.mask] + (0, 127, 0)).astype(np.uint8)
    canvas = cv2.resize(canvas, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_NEAREST)
    left, right = result.interior_columns
    for column in (left, right):
        cv2.line(canvas, (column * SCALE, 0), (column * SCALE, canvas.shape[0]), (0, 255, 255), 1)
    for first, last in zones.values():
        for row in (first, last):
            cv2.line(canvas, (0, row * SCALE), (6, row * SCALE), (255, 255, 0), 1)
    if result.fill_line_row is not None:
        y = result.fill_line_row * SCALE
        cv2.line(canvas, (0, y), (canvas.shape[1], y), (0, 0, 255), 2)
    label = result.fill_state if result.ok else str(result.code)
    cv2.putText(canvas, label[:13], (2, canvas.shape[0] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 255), 1)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--vials-dir", type=Path, default=Path("outputs/vials"))
    parser.add_argument("--frame", choices=["last", "all"], default="last",
                        help="Segment only each event's last settled frame, or all of them")
    args = parser.parse_args()

    config = load_camera_config("vial_fill")
    puck_top = config.lines_y["puck_top"]
    empty_profile = load_empty_profile("vial_fill")
    if empty_profile is None:
        print("No camera empty profile; the no-reference column falls back to chroma. "
              "Run scripts/calibrate_empty_profile.py to create one.")

    for video_id in args.videos:
        manifest = pd.read_csv(args.vials_dir / f"video{video_id}" / "manifest.csv")
        manifest = manifest[manifest["locate_ok"]]
        if args.frame == "last":
            manifest = manifest.groupby("event_idx").tail(1)

        rows, tiles = [], []
        for row in manifest.itertuples():
            roi = tuple(int(v) for v in row.roi_xywh.strip("[]").split(","))
            vial_crop = crop(cv2.imread(row.frame_path), roi)
            reference = None
            if isinstance(row.reference_path, str):
                reference = crop(cv2.imread(row.reference_path), roi)

            puck_row = puck_top - roi[1]
            zones = crop_zones(config, roi)
            results = {
                "ref": segment_liquid(vial_crop, reference, puck_row, zones=zones) if reference is not None else None,
                # The profile only lines up with the configured ROI, not a drifted one.
                "profile": segment_liquid(vial_crop, None, puck_row,
                                          empty_profile if roi == config.region("vial") else None, zones),
            }
            record = {"video_id": video_id, "event_idx": row.event_idx, "frame_index": row.frame_index,
                      "vial_id": row.vial_id, "roi_y": roi[1]}
            for name, result in results.items():
                if result is None:
                    record[f"{name}_code"] = "no_reference"
                    continue
                record.update({
                    f"{name}_ok": result.ok,
                    f"{name}_code": result.code,
                    f"{name}_fill_state": result.fill_state,
                    f"{name}_fill_line_y": None if result.fill_line_row is None else roi[1] + result.fill_line_row,
                    f"{name}_mask_pixels": result.mask_pixel_count,
                    f"{name}_glare_fraction": round(result.glare_fraction, 3),
                    f"{name}_method": result.method,
                    **{f"{name}_{zone}_pixels": int(m.sum()) for zone, m in result.zone_masks.items()},
                })
            rows.append(record)

            panels = [cv2.resize(vial_crop, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_NEAREST)]
            panels += [overlay(vial_crop, r, zones) for r in results.values() if r is not None]
            tile = np.hstack(panels)
            cv2.putText(tile, f"v{video_id} e{row.event_idx}", (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
            tiles.append(tile)

        out_dir = args.vials_dir / f"video{video_id}"
        table = pd.DataFrame(rows)
        table.to_csv(out_dir / "segments.csv", index=False)
        # Drifted (detected) ROIs can differ in size from the configured one.
        height, width = max(t.shape[0] for t in tiles), max(t.shape[1] for t in tiles)
        tiles = [np.pad(t, ((0, height - t.shape[0]), (0, width - t.shape[1]), (0, 0))) for t in tiles]
        tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % 6)
        sheet = np.vstack([np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)])
        cv2.imwrite(str(out_dir / "segments.jpg"), sheet)

        for name in results:
            if f"{name}_ok" in table:
                states = table[f"{name}_fill_state"].where(table[f"{name}_ok"] == True, table[f"{name}_code"])  # noqa: E712
                print(f"video {video_id} [{name}]: {states.value_counts().to_dict()}")
        print(f"  wrote {(out_dir / 'segments.csv').as_posix()} and segments.jpg")


if __name__ == "__main__":
    main()
