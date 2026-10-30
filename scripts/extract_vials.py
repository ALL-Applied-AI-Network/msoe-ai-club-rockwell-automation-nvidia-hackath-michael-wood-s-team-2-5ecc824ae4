"""Extract settled-vial frames from vial_fill videos and measure each vial.

For each video (dataset video IDs, or any recording via --video-file): compute per-frame
signals (cached as signals.csv), detect fill events, save a few frames from each event's
settled window (full frame plus vial crop) and one empty-vial reference frame from before
the first pour, and write events.csv, manifest.csv, and records.jsonl (one measured-
appearance record per vial from vialcv.detect, on its last settled frame; records.json
holds the same records as one JSON list).

Vial and recipe IDs: for dataset video 5, events are matched to the official labels by
time overlap and IDs are set only when unambiguous. For a recording, --run-plan gives
the recipe of each vial in fill order (CSV with columns vial_order,recipe_id). IDs are
assigned only if the number of filled vials detected equals the plan's rows; otherwise
none are, and each record's id_note says why.

Times use the frame rate stored in each file, which must be on the dataset's clock
(dataset videos and scripts/lab_capture.py recordings are). For a recording written at
its true capture rate by another tool, pass --true-rate. Outputs from real line video are
for inspection and evaluation only, not training data.
"""

import sys
import json
import argparse
from pathlib import Path

import cv2
import pandas as pd

# Allow running as `python scripts/extract_vials.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv import dataset  # noqa: E402
from vialcv.detect import detect_vial_color  # noqa: E402
from vialcv.events import (  # noqa: E402
    assign_run_plan,
    compute_signals,
    detect_events,
    load_run_plan,
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


def optional_int(value):
    return None if pd.isna(value) else int(value)


def extract_video(video: Path, name: str, video_ref: str, args, config,
                  video_id: int | None = None, plan: pd.DataFrame | None = None) -> pd.DataFrame:
    fps = dataset.video_fps(video)
    if args.true_rate:
        fps = dataset.dataset_clock_fps(fps)
    out_dir = args.out / name
    out_dir.mkdir(parents=True, exist_ok=True)

    signals_path = out_dir / "signals.csv"
    if args.reuse_signals and signals_path.is_file():
        signals = pd.read_csv(signals_path)
    else:
        signals = compute_signals(video, config, step=args.step, fps=fps)
        signals.to_csv(signals_path, index=False)

    events = detect_events(signals)
    event_table = pd.DataFrame([vars(e) for e in events])
    if event_table.empty:
        print(f"{name}: no carrier dwells found ({fps:.2f} fps)")
        return event_table

    if video_id == LABELED_VIDEO_ID:
        labels = dataset.load_vial_recipes(args.dataset_root)
        event_table = event_table.merge(match_labels(events, labels), on="event_idx")
    elif plan is not None:
        event_table = event_table.merge(assign_run_plan(events, plan), on="event_idx")
        poured = int((event_table["n_pours"] > 0).sum())
        if poured != len(plan):
            print(f"  WARNING: {poured} filled vials detected but the run plan has {len(plan)}; "
                  "no vial/recipe IDs assigned. Compare with the vials actually run.")
    event_table.insert(0, "video_id", video_id)
    event_table.insert(1, "video_name", name)
    event_table.to_csv(out_dir / "events.csv", index=False)

    manifest, records = [], []
    for event, row in zip(events, event_table.itertuples()):
        reference_path, reference = None, None
        reference_index = reference_frame(event, fps)
        if reference_index is not None:
            reference = read_frame(video, reference_index)
            if reference is not None:
                reference_path = out_dir / f"event{event.event_idx:03d}_ref_f{reference_index:06d}.png"
                cv2.imwrite(str(reference_path), reference)

        last_frame, last_index = None, None
        for frame_index in pick_frames(event, args.frames_per_event, fps):
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
            last_frame, last_index, last_path = frame, frame_index, frame_path

            manifest.append({
                "video_id": video_id,
                "video_name": name,
                "event_idx": event.event_idx,
                "event_quality": event.quality,
                "frame_index": frame_index,
                "video_s": round(dataset.frame_to_seconds(frame_index, fps), 3),
                "frame_path": frame_path.as_posix(),
                "crop_path": crop_path.as_posix() if crop_path else None,
                "reference_path": reference_path.as_posix() if reference_path else None,
                "roi_xywh": list(located.vial_xywh) if located.vial_xywh else None,
                "locate_ok": located.ok,
                "locate_code": located.code,
                "vial_id": getattr(row, "vial_id", pd.NA),
                "recipe_id": getattr(row, "recipe_id", pd.NA),
                "source_ref": video_ref,
                "source_data_origin": args.data_origin,
                "data_origin": "derived",
                "intended_use": "inspect",
                "generator": "scripts/extract_vials.py",
            })

        if last_frame is not None:
            record = detect_vial_color(
                last_frame,
                reference_bgr=reference,
                white_balance_method=args.white_balance,
                image_ref=last_path.as_posix(),
                source_data_origin=args.data_origin,
                metadata={
                    "video_id": video_id,
                    "frame_index": last_index,
                    "video_s": round(dataset.frame_to_seconds(last_index, fps), 3),
                    "vial_id": optional_int(getattr(row, "vial_id", pd.NA)),
                    "recipe_id": optional_int(getattr(row, "recipe_id", pd.NA)),
                },
                config=config,
            )
            record["provenance"]["sources"].insert(0, {"ref": video_ref, "data_origin": args.data_origin})
            record["event"] = {"video_name": name, "event_idx": event.event_idx, "quality": event.quality,
                               "id_note": getattr(row, "match_note", None)}
            records.append(record)

    manifest_table = pd.DataFrame(manifest)
    manifest_table.to_csv(out_dir / "manifest.csv", index=False)
    with open(out_dir / "records.jsonl", "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, allow_nan=False) + "\n")
    # The same records as one JSON list, for consumers that read *.json files.
    (out_dir / "records.json").write_text(json.dumps(records, allow_nan=False, indent=1) + "\n", encoding="utf-8")

    with_pour = event_table[event_table["n_pours"] > 0]
    measured = sum(r["quality"]["ok"] for r in records)
    print(f"{name}: {fps:.2f} fps, {len(event_table)} dwells, {len(with_pour)} with pours "
          f"(quality: {with_pour['quality'].value_counts().to_dict()}), {len(manifest_table)} frames, "
          f"{measured}/{len(records)} vials measured -> {out_dir.as_posix()}")
    return event_table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--videos", type=int, nargs="+", default=[1, 2, 3, 4, 5],
                        help="Dataset video IDs (ignored when --video-file is given)")
    parser.add_argument("--video-file", type=Path, nargs="+", help="Process these recordings instead")
    parser.add_argument("--run-plan", type=Path, help="CSV vial_order,recipe_id for --video-file runs")
    parser.add_argument("--true-rate", action="store_true",
                        help="The file's frame rate is its true capture rate (not the dataset clock); "
                             "convert it. Not needed for dataset videos or lab_capture.py recordings.")
    parser.add_argument("--data-origin", choices=("real_line", "digital_twin", "unknown"), default="real_line",
                        help="Origin of the input video (default real_line)")
    parser.add_argument("--white-balance", choices=("none", "white_patch", "gray_world"), default="none",
                        help="Correction used for the per-vial records")
    parser.add_argument("--step", type=int, default=2, help="Analyze every Nth frame")
    parser.add_argument("--frames-per-event", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("outputs/vials"))
    parser.add_argument("--reuse-signals", action="store_true", help="Reuse cached signals.csv")
    parser.add_argument("--dataset-root", help="Defaults to $DATASET_ROOT")
    args = parser.parse_args()

    config = load_camera_config("vial_fill")

    if args.video_file:
        plan = None
        if args.run_plan:
            try:
                plan = load_run_plan(args.run_plan)
            except (OSError, ValueError) as error:
                parser.error(str(error))
        for video in args.video_file:
            if not video.is_file():
                parser.error(f"Video not found: {video}")
            extract_video(video, video.stem, video.name, args, config, plan=plan)
        return

    expected = dataset.load_videos(args.dataset_root).set_index("video_id")["n_vials"]
    for video_id in args.videos:
        video = dataset.video_path("vial_fill", video_id, args.dataset_root)
        events = extract_video(video, f"video{video_id}", dataset.image_ref(video, args.dataset_root),
                               args, config, video_id=video_id)
        if not events.empty:
            print(f"  videos.csv lists {expected.get(video_id)} vials")


if __name__ == "__main__":
    main()
