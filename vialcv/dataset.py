"""Access to the local CSI vial-fill dataset (Dataset 2) without hard-coded paths.

The dataset root comes from an argument or the DATASET_ROOT environment variable and
points at the `csi-vial-fill-dataset` folder. Files are listed through each camera's
`image_index.csv`, which is the dataset's authoritative image list.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

CAMERAS = ("vial_fill", "tank_level", "cap_seal")

# All Dataset 2 videos are 30 fps (dataset README); label frame indices use this rate.
VIDEO_FPS = 30.0


def dataset_root(root: str | Path | None = None) -> Path:
    """Return the dataset root from `root` or $DATASET_ROOT, checking that it exists."""
    if root is None:
        root = os.environ.get("DATASET_ROOT")
        if not root:
            raise RuntimeError(
                "Set DATASET_ROOT to the csi-vial-fill-dataset folder or pass root explicitly."
            )

    path = Path(root)
    if not (path / "videos.csv").is_file():
        raise FileNotFoundError(f"Not a csi-vial-fill-dataset folder (no videos.csv): {path}")
    return path


def check_camera(camera: str) -> None:
    if camera not in CAMERAS:
        raise ValueError(f"Unknown camera {camera!r}; expected one of {CAMERAS}.")


def image_ref(path: str | Path, root: str | Path | None = None) -> str:
    """Return a dataset-relative POSIX path for a file inside the dataset root."""
    base = dataset_root(root).resolve()
    try:
        return Path(path).resolve().relative_to(base).as_posix()
    except ValueError:
        raise ValueError(f"Path is not inside the dataset root: {path}") from None


def video_path(camera: str, video_id: int, root: str | Path | None = None) -> Path:
    """Return the MP4 path for one camera and video ID."""
    check_camera(camera)
    path = dataset_root(root) / camera / "videos" / f"{camera}_video_{video_id}.mp4"
    if not path.is_file():
        raise FileNotFoundError(f"Video not found: {path}")
    return path


def image_path(camera: str, filename: str, root: str | Path | None = None) -> Path:
    """Return the path of a sampled still image."""
    check_camera(camera)
    return dataset_root(root) / camera / "images" / filename


def load_videos(root: str | Path | None = None) -> pd.DataFrame:
    """Load the video manifest (`videos.csv`)."""
    return pd.read_csv(dataset_root(root) / "videos.csv")


def load_image_index(camera: str, root: str | Path | None = None) -> pd.DataFrame:
    """Load a camera's image index with parsed timestamps.

    `video_id` is a nullable integer; rows marked `unassigned` become missing.
    """
    check_camera(camera)
    index = pd.read_csv(dataset_root(root) / camera / "image_index.csv", dtype=str)
    index["timestamp"] = pd.to_datetime(index["timestamp"])
    index["video_id"] = pd.to_numeric(index["video_id"], errors="coerce").astype("Int64")
    return index


def load_vial_recipes(root: str | Path | None = None) -> pd.DataFrame:
    """Load the official per-vial table for video 5 (`video5_vial_recipes.csv`)."""
    return pd.read_csv(dataset_root(root) / "vial_fill" / "labels" / "video5_vial_recipes.csv")


def load_frame_labels(root: str | Path | None = None) -> pd.DataFrame:
    """Load the official per-still labels for video 5 (`video5_frame_labels.csv`).

    `vial` and `recipe_id` are nullable integers; they are missing between fills.
    """
    labels = pd.read_csv(dataset_root(root) / "vial_fill" / "labels" / "video5_frame_labels.csv")
    labels["timestamp"] = pd.to_datetime(labels["timestamp"])
    for column in ("vial", "recipe_id"):
        labels[column] = labels[column].astype("Int64")
    return labels


def frame_to_seconds(frame_index: int, fps: float = VIDEO_FPS) -> float:
    """Return video time in seconds for a frame index (t = 0 at frame 0)."""
    return frame_index / fps


def seconds_to_frame(video_s: float, fps: float = VIDEO_FPS) -> int:
    """Return the nearest frame index for a video time in seconds."""
    return int(round(video_s * fps))


def iter_frames(
    path: str | Path,
    start: int = 0,
    stop: int | None = None,
    step: int = 1,
) -> Iterator[tuple[int, np.ndarray]]:
    """Yield (frame_index, BGR frame) from a video for frames in range(start, stop, step).

    Skipped frames are grabbed but not decoded. Stops early at the end of the video.
    """
    if start < 0 or step < 1 or (stop is not None and stop < start):
        raise ValueError("Need start >= 0, step >= 1, and stop >= start.")

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise OSError(f"Could not open video: {path}")

    try:
        if start:
            capture.set(cv2.CAP_PROP_POS_FRAMES, start)

        frame_index = start
        while stop is None or frame_index < stop:
            if (frame_index - start) % step == 0:
                ok, frame = capture.read()
                if not ok:
                    return
                yield frame_index, frame
            elif not capture.grab():
                return
            frame_index += 1
    finally:
        capture.release()
