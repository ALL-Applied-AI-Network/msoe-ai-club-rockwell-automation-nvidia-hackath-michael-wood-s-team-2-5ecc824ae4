"""Check that a vial_fill camera view still matches our camera config before a lab run.

Give it frame images, or --source to grab frames from a camera (index such as 0, or a
URL). For each frame it checks:
- size: must match the config (640x480);
- camera shift: static scene vs the dataset's video 5 stills (needs $DATASET_ROOT);
- vial location: a parked vial must be found where the config expects it;
- white patch: the backdrop reference must be unoccluded and unclipped.

Prints READY, READY (camera shift NOT checked), or NOT READY, and writes overlays to
--out. Run --list-cameras first: it saves a snapshot per camera index, so you can see which
one is the line camera (a laptop's own webcam is usually 0). Frames grabbed from the line
are real line data: inspection and calibration only.
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# Allow running as `python scripts/lab_check.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv import dataset  # noqa: E402
from vialcv.capture import grab_frames, list_cameras, open_source  # noqa: E402
from vialcv.colorstats import rgb_to_hsv_lab  # noqa: E402
from vialcv.locate import locate_vial  # noqa: E402
from vialcv.roi import camera_shift, contact_sheet, draw_regions, load_camera_config, static_scene  # noqa: E402
from vialcv.whitebalance import estimate_white_patch  # noqa: E402

# Camera shift limits (px). Dataset videos differed by < 0.15 px; the locator tolerates 4.
SHIFT_OK_PX = 2.0
SHIFT_FAIL_PX = 8.0
# Phase-correlation response between dataset videos was 0.62-0.91; far lower means a different view.
MIN_RESPONSE = 0.3
# Backdrop patch lightness on the dataset recording days.
DATASET_PATCH_L = (61.0, 71.0)
REFERENCE_VIDEO = 5
REFERENCE_STILLS = 20


def dataset_reference(config, root):
    index = dataset.load_image_index("vial_fill", root)
    rows = index[index["video_id"] == REFERENCE_VIDEO].reset_index(drop=True)
    picks = np.linspace(0, len(rows) - 1, REFERENCE_STILLS).round().astype(int)
    images = [cv2.imread(str(dataset.image_path("vial_fill", rows.loc[i, "filename"], root))) for i in picks]
    images = [im for im in images if im is not None]
    if not images:
        raise ValueError(f"no readable video {REFERENCE_VIDEO} stills under the dataset root")
    return static_scene(images, config)


def check_frame(image, config, reference) -> tuple[dict, list[str]]:
    lines, result = [], {"size_ok": False, "shift_ok": None, "vial_ok": False, "patch_ok": False}
    height, width = image.shape[:2]
    if (width, height) != config.image_size_wh:
        lines.append(f"FAIL size {width}x{height}; config expects {config.image_size_wh[0]}x"
                     f"{config.image_size_wh[1]}. Set the camera resolution, then re-check.")
        return result, lines
    result["size_ok"] = True

    if reference is not None:
        dx, dy, response = camera_shift(reference, static_scene([image], config))
        magnitude = float(np.hypot(dx, dy))
        if response < MIN_RESPONSE or magnitude > SHIFT_FAIL_PX:
            lines.append(f"FAIL camera shift dx={dx:+.1f} dy={dy:+.1f} px (response {response:.2f}): "
                         "view differs from the dataset; config regions will not line up.")
            result["shift_ok"] = False
        elif magnitude > SHIFT_OK_PX:
            lines.append(f"WARN camera shift dx={dx:+.1f} dy={dy:+.1f} px (response {response:.2f}): "
                         "small move; check the overlay and the vial result below.")
            result["shift_ok"] = True
        else:
            lines.append(f"ok   camera shift dx={dx:+.1f} dy={dy:+.1f} px (response {response:.2f})")
            result["shift_ok"] = True

    located = locate_vial(image, config)
    if located.ok and located.code is None:
        lines.append(f"ok   vial at station matches config (offset {located.offset_xy})")
        result["vial_ok"] = True
    elif located.ok:
        lines.append(f"WARN vial found with {located.code}: {located.detail}")
        result["vial_ok"] = True
    else:
        lines.append(f"info no parked vial usable in this frame ({located.code}); fine if a carrier "
                     "was moving or the station was empty")

    balance = estimate_white_patch(image, config.region("white_reference"))
    level = balance.reference_rgb_0_255
    _, lab = rgb_to_hsv_lab(np.array([level], dtype=np.float64))
    patch_l = float(lab[0, 0])
    if balance.ok:
        note = "" if DATASET_PATCH_L[0] <= patch_l <= DATASET_PATCH_L[1] else \
            f" (dataset days were L {DATASET_PATCH_L[0]:.0f}-{DATASET_PATCH_L[1]:.0f}; use --white-balance white_patch)"
        lines.append(f"ok   white patch L={patch_l:.1f}{note}")
        result["patch_ok"] = True
    else:
        lines.append(f"WARN white patch {balance.code}: {balance.detail}")
    return result, lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("images", type=Path, nargs="*", help="Frame images to check")
    parser.add_argument("--source", help="Grab frames from this camera index or URL instead")
    parser.add_argument("--frames", type=int, default=5, help="Frames to grab with --source")
    parser.add_argument("--list-cameras", action="store_true", help="List camera indexes and exit")
    parser.add_argument("--out", type=Path, default=Path("outputs/lab_check"))
    parser.add_argument("--dataset-root", help="Defaults to $DATASET_ROOT; enables the camera-shift check")
    args = parser.parse_args()

    if args.list_cameras:
        args.out.mkdir(parents=True, exist_ok=True)
        cameras = list_cameras()
        for camera in cameras:
            path = args.out / f"camera_{camera['index']}.png"
            cv2.imwrite(str(path), camera["frame"])
            print(f"camera {camera['index']}: {camera['width']}x{camera['height']}, "
                  f"reports {camera['reported_fps']:.1f} fps, snapshot {path.as_posix()}")
        if cameras:
            print("Open the snapshots and use the index that shows the vial_fill station.")
        else:
            print("No cameras returned a frame.")
        return

    config = load_camera_config("vial_fill")
    args.out.mkdir(parents=True, exist_ok=True)

    frames = []
    if args.source is not None:
        try:
            capture = open_source(args.source, *config.image_size_wh)
        except OSError as error:
            parser.error(str(error))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for i, frame in enumerate(grab_frames(capture, args.frames, interval_s=0.5)):
            path = args.out / f"snapshot_{stamp}_{i}.png"
            cv2.imwrite(str(path), frame)
            frames.append((path.name, frame))
        capture.release()
        if not frames:
            parser.error(f"Source {args.source} returned no frames.")
    for path in args.images:
        image = cv2.imread(str(path))
        if image is None:
            parser.error(f"Could not read image: {path}")
        frames.append((path.name, image))
    if not frames:
        parser.error("Give frame images or --source.")

    reference, no_shift_reason = None, None
    try:
        reference = dataset_reference(config, args.dataset_root)
    except RuntimeError:
        no_shift_reason = "DATASET_ROOT is not set"
    except (OSError, ValueError, KeyError) as error:
        no_shift_reason = f"dataset reference unavailable ({error})"
    if no_shift_reason:
        print(f"note: {no_shift_reason}; the camera-shift check is skipped.")

    results, tiles = [], []
    for name, image in frames:
        result, lines = check_frame(image, config, reference)
        results.append(result)
        print(f"\n{name}")
        for line in lines:
            print(f"  {line}")
        if result["size_ok"]:
            tile = draw_regions(image, config)
            cv2.putText(tile, name[:40], (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
            tiles.append(tile)

    if tiles:
        sheet = args.out / "lab_check_overlay.jpg"
        cv2.imwrite(str(sheet), contact_sheet(tiles, columns=min(len(tiles), 3)))
        print(f"\noverlay: {sheet.as_posix()}")

    size_ok = all(r["size_ok"] for r in results)
    shift_ok = all(r["shift_ok"] is not False for r in results)
    vial_seen = any(r["vial_ok"] for r in results)
    ready = size_ok and shift_ok and vial_seen
    if not size_ok or reference is None:
        shift_text = "not checked"
    else:
        shift_text = "ok" if shift_ok else "FAIL"
    if not ready:
        verdict = "NOT READY"
    elif reference is None:
        verdict = f"READY (camera shift NOT checked: {no_shift_reason}; compare the overlay by eye)"
    else:
        verdict = "READY"
    print(f"\n{verdict}: size {'ok' if size_ok else 'FAIL'}, camera shift {shift_text}, "
          f"parked vial located {'yes' if vial_seen else 'no - grab frames while a vial is parked'}")
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
