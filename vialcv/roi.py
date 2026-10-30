"""Per-camera region-of-interest configuration for fixed cameras."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs" / "cameras"

Roi = tuple[int, int, int, int]


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    image_size_wh: tuple[int, int]
    regions: dict[str, Roi]
    lines_y: dict[str, int] = field(default_factory=dict)

    def region(self, name: str) -> Roi:
        if name not in self.regions:
            raise KeyError(f"Camera {self.camera_id!r} has no region {name!r}.")
        return self.regions[name]


def validate_roi(roi: Roi, image_size_wh: tuple[int, int]) -> None:
    """Raise ValueError unless roi is a nonempty (x, y, width, height) inside the image."""
    x, y, width, height = roi
    image_width, image_height = image_size_wh
    if (
        width <= 0
        or height <= 0
        or x < 0
        or y < 0
        or x + width > image_width
        or y + height > image_height
    ):
        raise ValueError(f"Region {roi} must be nonempty and inside a {image_width}x{image_height} image.")


def load_camera_config(camera_id: str, config_dir: str | Path | None = None) -> CameraConfig:
    """Load and validate `<config_dir>/<camera_id>.json`."""
    path = Path(config_dir or CONFIG_DIR) / f"{camera_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"No ROI config for camera {camera_id!r}: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("camera_id") != camera_id:
        raise ValueError(f"{path} declares camera_id {raw.get('camera_id')!r}, expected {camera_id!r}.")

    image_size_wh = tuple(raw["image_size_wh"])
    regions = {name: tuple(int(v) for v in roi) for name, roi in raw["regions_xywh"].items()}
    for name, roi in regions.items():
        if len(roi) != 4:
            raise ValueError(f"Region {name!r} in {path} must have 4 values (x, y, width, height).")
        validate_roi(roi, image_size_wh)

    lines_y = {name: int(y) for name, y in raw.get("lines_y", {}).items()}
    for name, y in lines_y.items():
        if not 0 <= y < image_size_wh[1]:
            raise ValueError(f"Line {name!r}={y} in {path} is outside the image.")

    return CameraConfig(camera_id, image_size_wh, regions, lines_y)


def crop(image: np.ndarray, roi: Roi) -> np.ndarray:
    """Return the roi of an image (a view, not a copy)."""
    height, width = image.shape[:2]
    validate_roi(roi, (width, height))
    x, y, w, h = roi
    return image[y:y + h, x:x + w]


REGION_COLORS = [(0, 0, 255), (0, 200, 0), (255, 0, 0), (0, 200, 255), (255, 0, 255), (128, 128, 128),
                 (0, 128, 255), (255, 255, 0), (128, 0, 255)]


def draw_regions(image: np.ndarray, config: CameraConfig) -> np.ndarray:
    """Return a copy of a BGR image with the camera's regions and reference lines drawn."""
    canvas = image.copy()
    for i, (name, (x, y, w, h)) in enumerate(config.regions.items()):
        color = REGION_COLORS[i % len(REGION_COLORS)]
        cv2.rectangle(canvas, (x, y), (x + w - 1, y + h - 1), color, 1)
        cv2.putText(canvas, name, (x, max(y - 3, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)
    for y in config.lines_y.values():
        cv2.line(canvas, (250, y), (390, y), (255, 255, 255), 1)
    return canvas


def contact_sheet(tiles: list[np.ndarray], columns: int) -> np.ndarray:
    """Tile same-size images into rows of `columns`, padding with black."""
    blank = np.zeros_like(tiles[0])
    tiles = tiles + [blank] * (-len(tiles) % columns)
    return np.vstack([np.hstack(tiles[i:i + columns]) for i in range(0, len(tiles), columns)])


def static_scene(images: list[np.ndarray], config: CameraConfig) -> np.ndarray:
    """Return the median grayscale `static_scene` region over images, for shift checks."""
    x, y, w, h = config.region("static_scene")
    gray = [cv2.cvtColor(image[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY) for image in images]
    return np.median(np.stack(gray), axis=0).astype(np.float32)


def camera_shift(reference: np.ndarray, current: np.ndarray) -> tuple[float, float, float]:
    """Return (dx, dy, response) of `current` relative to `reference` static scenes."""
    # A Hanning window keeps the crop edges from biasing the estimate toward zero.
    window = cv2.createHanningWindow(reference.shape[::-1], cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(reference, current, window)
    return float(dx), float(dy), float(response)


def check_image_size(image: np.ndarray, config: CameraConfig) -> None:
    """Raise ValueError if an image does not match the camera's configured size."""
    height, width = image.shape[:2]
    if (width, height) != config.image_size_wh:
        raise ValueError(
            f"Image is {width}x{height}; camera {config.camera_id!r} config expects "
            f"{config.image_size_wh[0]}x{config.image_size_wh[1]}."
        )
