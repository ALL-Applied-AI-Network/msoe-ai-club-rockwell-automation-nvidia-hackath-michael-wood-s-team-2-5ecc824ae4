"""Record the vial_fill camera during a lab run, with a live station-state preview.

Measures the frame rate the camera actually delivers and writes the MP4 on the dataset's
clock: at delivered fps * DATASET_TIME_SCALE (30 fps for a camera delivering ~24.7, like
the dataset's capture system), so extract_vials' calibrated time thresholds apply
unchanged. Real wall-clock times go to a per-frame CSV, and the rates to a JSON sidecar.

The preview shows the configured vial region, the live station state, and a per-vial
readout (vialcv.live): each vial is measured as it settles (color swatch, zone, fill
state). With --run-plan, recipes come from the plan by live fill order, and when the
second vial of a recipe settles, the first is flagged if their colors differ by more
than --flag-de00. Live results go to <name>_live.jsonl. They are provisional: the
authoritative per-vial records come from extract_vials.py (--process) on the recording.

Stop with q in the preview window, Ctrl+C, or --duration. With --process, the recording
is passed to extract_vials.py afterwards (with --run-plan if given). The recording is
real line data: inspection and evaluation only, not training data.

Example (PowerShell):
  python scripts/lab_check.py --list-cameras        # find the index N of the line camera
  python scripts/lab_capture.py --source N --name run1 --process --run-plan plan.csv
"""

import sys
import csv
import json
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
from vialcv.dataset import DATASET_TIME_SCALE, dataset_clock_fps  # noqa: E402
from vialcv.detect import detect_vial_color  # noqa: E402
from vialcv.events import SignalTracker, load_run_plan  # noqa: E402
from vialcv.live import DEFAULT_FLAG_DE00, LiveVialReader  # noqa: E402
from vialcv.roi import load_camera_config  # noqa: E402

STATE_COLORS = {"no carrier": (160, 160, 160), "moving": (0, 165, 255), "pouring": (255, 120, 0),
                "parked, waiting": (0, 200, 200), "settling": (255, 200, 0),
                "settled, measured": (0, 200, 0), "settled, no color": (0, 0, 220)}
# The live state is computed on every Nth frame, matching extract_vials' default step.
STATE_STEP = 2
PANEL_W, ROW_H, PANEL_ROWS = 330, 54, 8
FONT = cv2.FONT_HERSHEY_SIMPLEX


def draw_preview(frame: np.ndarray, config, state: str, elapsed_s: float, fps: float) -> np.ndarray:
    preview = frame.copy()
    x, y, w, h = config.region("vial")
    color = STATE_COLORS.get(state, (255, 255, 255))
    cv2.rectangle(preview, (x, y), (x + w - 1, y + h - 1), color, 2)
    cv2.rectangle(preview, (0, 0), (640, 28), (0, 0, 0), -1)
    cv2.putText(preview, f"REC {elapsed_s:6.1f}s  {fps:4.1f} fps  state: {state}", (6, 19),
                FONT, 0.55, color, 2)
    return preview


def draw_panel(vials, height: int, has_plan: bool) -> np.ndarray:
    """Per-vial readout, newest at the bottom: swatch, recipe, zone, fill, comparison, flag."""
    panel = np.full((height, PANEL_W, 3), 30, dtype=np.uint8)
    n_flags = sum(v.flag is not None for v in vials)
    cv2.putText(panel, f"vials filled: {len(vials)}   flagged: {n_flags}", (8, 20), FONT, 0.5, (255, 255, 255), 1)
    if has_plan:
        cv2.putText(panel, "recipes by live fill order (provisional)", (8, 38), FONT, 0.4, (180, 180, 180), 1)
    for row, vial in enumerate(vials[-PANEL_ROWS:]):
        top = 46 + row * ROW_H
        if vial.flag:
            cv2.rectangle(panel, (2, top - 2), (PANEL_W - 3, top + ROW_H - 6), (0, 0, 255), 2)
        swatch = (60, 60, 60)
        if vial.ok:
            rgb = vial.record["color"]["primary"]["rgb_0_255"]["median"]
            swatch = tuple(int(round(c)) for c in rgb[::-1])
        cv2.rectangle(panel, (8, top + 2), (48, top + 42), swatch, -1)
        cv2.rectangle(panel, (8, top + 2), (48, top + 42), (200, 200, 200), 1)

        title = f"#{vial.number}"
        if vial.recipe_id is not None:
            title += f"  recipe {vial.recipe_id} (vial {vial.position_in_recipe})"
        cv2.putText(panel, f"{title}  {vial.status}", (56, top + 14), FONT, 0.45, (255, 255, 255), 1)
        if vial.ok:
            fill = vial.record["fill"]["state"].replace("at_or_above_view_top", "above view").replace("_", " ")
            detail = f"{vial.record['color']['primary_zone']}, fill {fill}"
        elif vial.record is not None:
            detail = f"no color: {vial.record['quality']['code']}"
        else:
            detail = "pouring..."
        cv2.putText(panel, detail, (56, top + 29), FONT, 0.4, (200, 200, 200), 1)
        if vial.flag:
            # The flag comes from the next vial's comparison with this one.
            de00 = vials[vial.number].compare["de00"]
            cv2.putText(panel, f"FLAG: dE00 {de00:.1f} from next vial", (56, top + 44), FONT, 0.42, (0, 0, 255), 1)
        elif vial.compare and vial.compare["de00"] is not None:
            cv2.putText(panel, f"dE00 {vial.compare['de00']:.1f} vs #{vial.compare['to_live_vial']} "
                        f"({vial.compare['zone']})", (56, top + 44), FONT, 0.4, (200, 200, 200), 1)
    return panel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Camera index (e.g. 0), stream URL, or video file")
    parser.add_argument("--name", help="Recording name (default: lab_<date>_<time>)")
    parser.add_argument("--out", type=Path, default=Path("outputs/lab"), help="Folder for recordings")
    parser.add_argument("--duration", type=float, help="Stop after this many seconds")
    parser.add_argument("--fps", type=float,
                        help="The camera's true delivered frame rate (default: measured for 3 s)")
    parser.add_argument("--no-preview", action="store_true", help="Record without a preview window")
    parser.add_argument("--process", action="store_true", help="Run extract_vials.py on the recording afterwards")
    parser.add_argument("--run-plan", type=Path,
                        help="CSV vial_order,recipe_id: live recipe readout, and passed to extract_vials.py")
    parser.add_argument("--vials-out", type=Path, default=Path("outputs/vials"),
                        help="Output folder for extract_vials.py with --process")
    parser.add_argument("--flag-de00", type=float, default=DEFAULT_FLAG_DE00,
                        help="Flag a recipe's first vial when it differs from the second by more than this")
    parser.add_argument("--white-balance", choices=("none", "white_patch", "gray_world"), default="none",
                        help="Correction used for the live measurements")
    parser.add_argument("--data-origin", choices=("real_line", "digital_twin", "unknown"),
                        help="Origin recorded in live records (default: real_line for a camera, unknown for a file)")
    args = parser.parse_args()

    plan = None
    if args.run_plan:
        try:
            plan = load_run_plan(args.run_plan)
        except (OSError, ValueError) as error:
            parser.error(str(error))

    config = load_camera_config("vial_fill")
    name = args.name or datetime.now().strftime("lab_%Y%m%d_%H%M%S")
    args.out.mkdir(parents=True, exist_ok=True)
    video_path = args.out / f"{name}.mp4"
    times_path = args.out / f"{name}_frames.csv"
    live_path = args.out / f"{name}_live.jsonl"
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
    if is_file:
        # A video file is copied on its own clock (dataset videos are already on it).
        true_fps = None
        fps = args.fps or capture.get(cv2.CAP_PROP_FPS) or 30.0
    else:
        if args.fps:
            true_fps = args.fps
        else:
            print("Measuring delivered frame rate for 3 s ...")
            true_fps = measure_fps(capture, 3.0)
            print(f"Camera reports {capture.get(cv2.CAP_PROP_FPS):.1f} fps; delivers {true_fps:.2f} fps.")
        if true_fps <= 0:
            parser.error("Could not determine a frame rate; pass --fps.")
        fps = dataset_clock_fps(true_fps)

    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        parser.error(f"Could not open {video_path} for writing.")
    # The tracker and live reader run on the file's (dataset) clock, like extract_vials.
    tracker = SignalTracker(config, fps / STATE_STEP)
    origin = args.data_origin or ("unknown" if is_file else "real_line")

    def measure(vial_frame, reference, t):
        return detect_vial_color(vial_frame, reference_bgr=reference, white_balance_method=args.white_balance,
                                 image_ref=video_path.name, source_data_origin=origin,
                                 metadata={"video_s": round(t, 3)}, config=config)

    reader = LiveVialReader(measure, fps / STATE_STEP, plan, args.flag_de00)
    live_path.write_text("", encoding="utf-8")

    def log_finished():
        # A first vial's flag is set when the next vial settles, after the first was
        # finished, so the whole log is rewritten each time a vial finishes.
        if reader.pop_finished():
            finished = [v for v in reader.vials if v.status in ("final", "not_measured")]
            live_path.write_text("".join(json.dumps(v.summary(), allow_nan=False) + "\n" for v in finished),
                                 encoding="utf-8")

    clock = (f"{fps:.2f} fps on the dataset clock (delivered {true_fps:.2f} x {DATASET_TIME_SCALE})"
             if true_fps else f"{fps:.2f} fps (source file's own clock)")
    print(f"Recording to {video_path.as_posix()} at {clock}. Press q in the preview (or Ctrl+C) to stop.")
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
                    state = reader.update(frame_index / fps, frame, tracker.update(frame))
                    log_finished()
                if not args.no_preview:
                    preview = draw_preview(frame, config, state, elapsed, true_fps or fps)
                    panel = draw_panel(reader.vials, preview.shape[0], plan is not None)
                    cv2.imshow("lab capture (q to stop)", np.hstack([preview, panel]))
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
            reader.close(frame_index / fps)
            log_finished()
            writer.release()
            capture.release()
            cv2.destroyAllWindows()

    elapsed = time.perf_counter() - start
    print(f"Saved {frame_index + 1} frames ({elapsed:.0f} s wall clock) to {video_path.as_posix()}; "
          f"frame times in {times_path.as_posix()}.")
    measured = sum(v.ok for v in reader.vials)
    print(f"Live readout: {len(reader.vials)} filled vials, {measured} with a color -> {live_path.as_posix()}")
    for vial in reader.vials:
        if vial.flag:
            print(f"  FLAG live vial #{vial.number}: {vial.flag}")
    if plan is not None and len(reader.vials) != len(plan):
        print(f"WARNING: the live count ({len(reader.vials)}) differs from the run plan ({len(plan)}). "
              "If a vial was missed or an extra pour counted, the live recipe IDs after it are wrong; "
              "check extract_vials, which assigns no IDs on a mismatch.")
    delivered = (frame_index + 1) / elapsed if not is_file and elapsed > 0 else None
    sidecar = args.out / f"{name}_capture.json"
    sidecar.write_text(json.dumps({
        "source": args.source, "frames": frame_index + 1, "wall_seconds": round(elapsed, 3),
        "true_fps_before_recording": true_fps, "true_fps_during_recording": delivered,
        "written_fps": fps, "dataset_time_scale": DATASET_TIME_SCALE if true_fps else None,
        "data_origin": "real_line" if not is_file else "unknown",
    }, indent=2) + "\n", encoding="utf-8")
    if delivered and abs(delivered - true_fps) / true_fps > 0.05:
        print(f"WARNING: the camera delivered {delivered:.2f} fps while recording but {true_fps:.2f} fps "
              "when measured, so this file's clock is off by that ratio. Record again with "
              f"--fps {delivered:.2f}.")

    if args.process:
        command = [sys.executable, str(Path(__file__).with_name("extract_vials.py")), "--video-file", str(video_path),
                   "--out", str(args.vials_out)]
        if args.run_plan:
            command += ["--run-plan", str(args.run_plan)]
        print("Running:", " ".join(command), flush=True)
        subprocess.run(command, check=False)


if __name__ == "__main__":
    main()
