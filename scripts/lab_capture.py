"""Record the vial_fill camera during a lab run, with a live station-state preview.

Measures the frame rate the camera actually delivers, then writes an MP4 at that rate
plus a CSV of per-frame wall-clock times. The preview shows the configured vial region
and a coarse live state (no carrier / moving / pouring / parked, still) computed with
the same signals and thresholds as scripts/extract_vials.py.

Stop with q in the preview window, Ctrl+C, or --duration. With --process, the recording
is passed to extract_vials.py afterwards (with --run-plan if given). The recording is
real line data: inspection and evaluation only, not training data.

Example (PowerShell):
  python scripts/lab_capture.py --source 0 --name run1 --process --run-plan plan.csv
"""

import sys
import csv
import time
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# Allow running as `python scripts/lab_capture.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv.capture import measure_fps, open_source  # noqa: E402
from vialcv.events import SignalTracker, station_state  # noqa: E402
from vialcv.roi import load_camera_config  # noqa: E402

STATE_COLORS = {"no carrier": (160, 160, 160), "moving": (0, 165, 255), "pouring": (255, 120, 0),
                "parked, still": (0, 200, 0)}
# The live state is computed on every Nth frame, matching extract_vials' default step.
STATE_STEP = 2


def draw_preview(frame: np.ndarray, config, state: str, elapsed_s: float, fps: float) -> np.ndarray:
    preview = frame.copy()
    x, y, w, h = config.region("vial")
    color = STATE_COLORS.get(state, (255, 255, 255))
    cv2.rectangle(preview, (x, y), (x + w - 1, y + h - 1), color, 2)
    cv2.rectangle(preview, (0, 0), (640, 28), (0, 0, 0), -1)
    cv2.putText(preview, f"REC {elapsed_s:6.1f}s  {fps:4.1f} fps  state: {state}", (6, 19),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    return preview


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Camera index (e.g. 0), stream URL, or video file")
    parser.add_argument("--name", help="Recording name (default: lab_<date>_<time>)")
    parser.add_argument("--out", type=Path, default=Path("outputs/lab"), help="Folder for recordings")
    parser.add_argument("--duration", type=float, help="Stop after this many seconds")
    parser.add_argument("--fps", type=float, help="Frame rate to record at (default: measured)")
    parser.add_argument("--no-preview", action="store_true", help="Record without a preview window")
    parser.add_argument("--process", action="store_true", help="Run extract_vials.py on the recording afterwards")
    parser.add_argument("--run-plan", type=Path, help="Passed to extract_vials.py with --process")
    args = parser.parse_args()

    config = load_camera_config("vial_fill")
    name = args.name or datetime.now().strftime("lab_%Y%m%d_%H%M%S")
    args.out.mkdir(parents=True, exist_ok=True)
    video_path = args.out / f"{name}.mp4"
    times_path = args.out / f"{name}_frames.csv"
    if video_path.exists():
        parser.error(f"{video_path} exists; choose another --name.")

    try:
        capture = open_source(args.source, *config.image_size_wh)
    except OSError as error:
        parser.error(str(error))

    ok, frame = capture.read()
    if not ok:
        parser.error(f"Source {args.source} returned no frame.")
    height, width = frame.shape[:2]
    if (width, height) != config.image_size_wh:
        print(f"WARNING: frames are {width}x{height}, config expects {config.image_size_wh}; "
              "measurements will fail until the resolution matches.")

    is_file = not args.source.isdigit() and Path(args.source).is_file()
    if args.fps:
        fps = args.fps
    elif is_file:
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    else:
        print("Measuring delivered frame rate for 3 s ...")
        fps = measure_fps(capture, 3.0)
        print(f"Camera reports {capture.get(cv2.CAP_PROP_FPS):.1f} fps; delivers {fps:.2f} fps.")
    if fps <= 0:
        parser.error("Could not determine a frame rate; pass --fps.")

    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        parser.error(f"Could not open {video_path} for writing.")
    tracker = SignalTracker(config, fps / STATE_STEP)

    print(f"Recording to {video_path.as_posix()} at {fps:.2f} fps. Press q in the preview (or Ctrl+C) to stop.")
    start = time.perf_counter()
    frame_index, state = 0, "starting"
    with open(times_path, "w", newline="", encoding="utf-8") as handle:
        log = csv.writer(handle)
        log.writerow(["frame_index", "wall_time", "elapsed_s"])
        try:
            while True:
                writer.write(frame)
                # A file is read faster than real time, so its clock is the video's own.
                elapsed = frame_index / fps if is_file else time.perf_counter() - start
                log.writerow([frame_index, datetime.now().isoformat(timespec="milliseconds"), f"{elapsed:.3f}"])
                if frame_index % STATE_STEP == 0 and (width, height) == config.image_size_wh:
                    state = station_state(*tracker.update(frame))
                if not args.no_preview:
                    cv2.imshow("lab capture (q to stop)", draw_preview(frame, config, state, elapsed, fps))
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                if args.duration and elapsed >= args.duration:
                    break
                ok, frame = capture.read()
                if not ok:
                    print("Source ended.")
                    break
                frame_index += 1
        except KeyboardInterrupt:
            print("Stopped.")
        finally:
            writer.release()
            capture.release()
            cv2.destroyAllWindows()

    elapsed = time.perf_counter() - start
    print(f"Saved {frame_index + 1} frames ({elapsed:.0f} s wall clock) to {video_path.as_posix()}; "
          f"frame times in {times_path.as_posix()}.")
    if not is_file and elapsed > 0:
        delivered = (frame_index + 1) / elapsed
        if abs(delivered - fps) / fps > 0.05:
            print(f"WARNING: delivered {delivered:.2f} fps during recording vs {fps:.2f} fps written; "
                  "durations in the MP4 are scaled by that ratio. Use the frames CSV for wall-clock "
                  "times, or record again with --fps set to the delivered rate.")

    if args.process:
        command = [sys.executable, str(Path(__file__).with_name("extract_vials.py")), "--video-file", str(video_path)]
        if args.run_plan:
            command += ["--run-plan", str(args.run_plan)]
        print("Running:", " ".join(command), flush=True)
        subprocess.run(command, check=False)


if __name__ == "__main__":
    main()
