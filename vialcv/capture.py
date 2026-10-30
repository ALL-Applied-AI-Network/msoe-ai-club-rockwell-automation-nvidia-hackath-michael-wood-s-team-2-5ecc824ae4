"""Open a camera or video source for lab capture.

A source is a camera index ("0", "1", ...), a stream URL, or a video file. On Windows,
USB cameras open through DirectShow, which reliably honors the requested resolution.
"""

import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import cv2
import numpy as np


def validate_source(source: str) -> None:
    """Reject stream URLs whose credentials or tokens would leak into logs/metadata."""
    if "://" not in source:
        return
    parsed = urlsplit(source)
    try:
        parsed.port
    except ValueError as error:
        raise OSError("Stream URL has an invalid port.") from error
    if not parsed.scheme or not parsed.hostname:
        raise OSError("Stream URL must include a scheme and host.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OSError(
            "Credential-bearing or tokenized stream URLs are not accepted. "
            "Ask staff for a credential-free local alias or camera index."
        )


def safe_source_label(source: str) -> str:
    """Return a non-secret label suitable for console output and capture metadata."""
    if source.isdigit():
        return source
    if "://" in source:
        parsed = urlsplit(source)
        host = parsed.hostname or "stream"
        try:
            port = parsed.port
        except ValueError:
            port = None
        if port:
            host += f":{port}"
        return urlunsplit((parsed.scheme, host, "", "", ""))
    return Path(source).name or "video-file"


def open_source(source: str, width: int = 640, height: int = 480) -> cv2.VideoCapture:
    """Open a camera index, URL, or file; raise OSError if it cannot be opened."""
    validate_source(source)
    if source.isdigit():
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        capture = cv2.VideoCapture(int(source), backend)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    else:
        capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise OSError(f"Could not open video source {safe_source_label(source)!r}.")
    return capture


def list_cameras(max_index: int = 6, warmup: int = 10) -> list[dict]:
    """Probe camera indexes 0..max_index-1; return the ones that give a frame, with that frame.

    A laptop's built-in webcam is usually index 0, so look at the frames to find the line camera.
    """
    found = []
    for index in range(max_index):
        try:
            capture = open_source(str(index))
        except OSError:
            continue
        frames = grab_frames(capture, 1, warmup=warmup)
        if frames:
            frame = frames[0]
            found.append({"index": index, "width": frame.shape[1], "height": frame.shape[0],
                          "reported_fps": capture.get(cv2.CAP_PROP_FPS), "frame": frame})
        capture.release()
    return found


def grab_frames(capture: cv2.VideoCapture, count: int, warmup: int = 10,
                interval_s: float = 0.0) -> list[np.ndarray]:
    """Read `count` frames after discarding `warmup` (auto-exposure settles in the first ones)."""
    for _ in range(warmup):
        capture.read()
    frames = []
    while len(frames) < count:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
        if interval_s:
            time.sleep(interval_s)
    return frames


def measure_fps(capture: cv2.VideoCapture, seconds: float = 3.0) -> float:
    """Return the frame rate actually delivered, measured over `seconds` of reads."""
    start, frames = time.perf_counter(), 0
    while time.perf_counter() - start < seconds:
        ok, _ = capture.read()
        if not ok:
            break
        frames += 1
    elapsed = time.perf_counter() - start
    return frames / elapsed if elapsed > 0 else 0.0
