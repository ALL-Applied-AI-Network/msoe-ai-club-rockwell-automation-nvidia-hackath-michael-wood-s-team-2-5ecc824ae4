"""Extract settled-vial frames from vial_fill videos.

For each video: compute per-frame signals (cached as signals.csv), detect fill events,
save a few frames from each event's settled window (full frame plus vial crop) and one
empty-vial reference frame from before the first pour, and write events.csv and
manifest.csv. For video 5 only, events are matched to the official
vial labels by time overlap; vial_id stays empty unless the match is unambiguous.

Outputs are derived from real line video: inspection/evaluation only, not training data.
"""

import sys
import argparse
from pathlib import Path

import cv2
import pandas as pd

# Allow running as `python scripts/extract_vials.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv import dataset  # noqa: E402
from vialcv.events import (  # noqa: E402
    compute_signals,
    detect_events,
    match_labels,
    pick_frames,
    reference_frame,
)
from vialcv.locate import locate_vial  # noqa: E402
from vialcv.roi import crop, load_camera_config  # noqa: E402

LABELED_VIDEO_ID = 5


def read_frame(video: Path, frame_index: int):
    for _, frame in dataset.iter_frames(video, start=frame_index, stop=frame_index + 1):
        return frame
    return None


def extract_video(video_id: int, args, config) -> pd.DataFrame:
    video = dataset.video_path("vial_fill", video_id, args.dataset_root)
    video_ref = dataset.image_ref(video, args.dataset_root)
    out_dir = args.out / f"video{video_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    signals_path = out_dir / "signals.csv"
    if args.reuse_signals and signals_path.is_file():
        signals = pd.read_csv(signals_path)
    else:
        signals = compute_signals(video, config, step=args.step)
        signals.to_csv(signals_path, index=False)

    events = detect_events(signals)
    event_table = pd.DataFrame([vars(e) for e in events])
    if event_table.empty:
        print(f"video {video_id}: no carrier dwells found")
        return event_table

    if video_id == LABELED_VIDEO_ID:
        labels = dataset.load_vial_recipes(args.dataset_root)
        event_table = event_table.merge(match_labels(events, labels), on="event_idx")
    event_table.insert(0, "video_id", video_id)
    event_table.to_csv(out_dir / "events.csv", index=False)

    manifest = []
    for event, row in zip(events, event_table.itertuples()):
        reference_path = None
        reference_index = reference_frame(event)
        if reference_index is not None:
            reference = read_frame(video, reference_index)
            if reference is not None:
                reference_path = out_dir / f"event{event.event_idx:03d}_ref_f{reference_index:06d}.png"
                cv2.imwrite(str(reference_path), reference)

        for frame_index in pick_frames(event, args.frames_per_event):
            frame = read_frame(video, frame_index)
            if frame is None:
                continue
            located = locate_vial(frame, config)
            stem = f"event{event.event_idx:03d}_f{frame_index:06d}"
            frame_path = out_dir / f"{stem}.png"
            cv2.imwrite(str(frame_path), frame)
            crop_path = None
            if located.ok:
                crop_path = out_dir / f"{stem}_vial.png"
                cv2.imwrite(str(crop_path), crop(frame, located.vial_xywh))

            manifest.append({
                "video_id": video_id,
                "event_idx": event.event_idx,
                "event_quality": event.quality,
                "frame_index": frame_index,
                "video_s": round(dataset.frame_to_seconds(frame_index), 3),
                "frame_path": frame_path.as_posix(),
                "crop_path": crop_path.as_posix() if crop_path else None,
                "reference_path": reference_path.as_posix() if reference_path else None,
                "roi_xywh": list(located.vial_xywh) if located.vial_xywh else None,
                "locate_ok": located.ok,
                "locate_code": located.code,
                "vial_id": getattr(row, "vial_id", pd.NA),
                "recipe_id": getattr(row, "recipe_id", pd.NA),
                "source_ref": video_ref,
                "source_data_origin": "real_line",
                "data_origin": "derived",
                "intended_use": "inspect",
                "generator": "scripts/extract_vials.py",
            })

    manifest_table = pd.DataFrame(manifest)
    manifest_table.to_csv(out_dir / "manifest.csv", index=False)

    with_pour = event_table[event_table["n_pours"] > 0]
    print(f"video {video_id}: {len(event_table)} dwells, {len(with_pour)} with pours "
          f"(quality: {with_pour['quality'].value_counts().to_dict()}), "
          f"{len(manifest_table)} frames saved to {out_dir.as_posix()}")
    return event_table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--step", type=int, default=2, help="Analyze every Nth frame")
    parser.add_argument("--frames-per-event", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("outputs/vials"))
    parser.add_argument("--reuse-signals", action="store_true", help="Reuse cached signals.csv")
    parser.add_argument("--dataset-root", help="Defaults to $DATASET_ROOT")
    args = parser.parse_args()

    config = load_camera_config("vial_fill")
    expected = dataset.load_videos(args.dataset_root).set_index("video_id")["n_vials"]
    for video_id in args.videos:
        events = extract_video(video_id, args, config)
        if not events.empty:
            print(f"  videos.csv lists {expected.get(video_id)} vials")


if __name__ == "__main__":
    main()
