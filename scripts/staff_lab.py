"""Small, safe command-line helpers for a ProcessDNA vial-fill lab session.

This script does not implement camera vision or record a camera.  It prepares inputs,
checks the workstation, validates the artifacts written by ``lab_capture.py`` and
``extract_vials.py``, and creates a checksum-protected handoff folder.

Typical use::

    python scripts/staff_lab.py preflight --source 1
    python scripts/staff_lab.py make-plan 7 7 7 8 8 8 --output plan.csv
    python scripts/lab_capture.py --source 1 --name run1 --run-plan plan.csv --save-preview
    python scripts/extract_vials.py --video-file outputs/lab/run1.mp4 --run-plan plan.csv --data-origin real_line
    python scripts/staff_lab.py verify --name run1 --plan plan.csv
    python scripts/staff_lab.py package --name run1 --plan plan.csv --notes notes.txt --destination handoff/run1

All commands are local-only.  Existing plans and handoff directories are never
overwritten.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import pandas as pd
import skimage

# Allow ``python scripts/staff_lab.py`` without installing the repository.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from vialcv.capture import open_source, safe_source_label, validate_source  # noqa: E402
from vialcv.events import load_run_plan  # noqa: E402
from vialcv.roi import CONFIG_DIR, load_camera_config  # noqa: E402


class StaffLabError(RuntimeError):
    """An actionable field-work error, safe to show directly to the operator."""


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: float
    frames: int


@dataclass
class VerificationResult:
    name: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    plan_count: int = 0
    detected_count: int = 0
    record_count: int = 0
    measured_count: int = 0
    raw_video: VideoInfo | None = None
    preview_video: VideoInfo | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def _safe_run_name(name: str) -> str:
    # Extraction keys its output directory to the source video's exact stem.  Accept
    # ordinary staff filenames (including spaces) while still preventing traversal or
    # Windows-special paths when the name is joined below an output directory.
    invalid_chars = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
    base = (name or "").split(".", 1)[0].upper()
    if (
        not name
        or len(name) > 128
        or name in {".", ".."}
        or name.endswith((" ", "."))
        or invalid_chars.search(name)
        or base in reserved
    ):
        raise StaffLabError(
            "Run name must be a single safe filename stem (maximum 128 characters; "
            "no path separators, control characters, trailing space/period, or Windows device name)."
        )
    return name


def _format_command(parts: Iterable[object]) -> str:
    values = [str(value) for value in parts]
    return subprocess.list2cmdline(values) if os.name == "nt" else shlex.join(values)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StaffLabError(f"Could not read JSON {path}: {error}") from error


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise StaffLabError(f"Invalid JSON on {path}:{line_number}: {error}") from error
                if not isinstance(value, dict):
                    raise StaffLabError(f"{path}:{line_number} must contain a JSON object.")
                rows.append(value)
    except OSError as error:
        raise StaffLabError(f"Could not read {path}: {error}") from error
    return rows


def _nonempty_file(path: Path, label: str, errors: list[str]) -> bool:
    if not path.is_file():
        errors.append(f"Missing {label}: {path}")
        return False
    if path.stat().st_size == 0:
        errors.append(f"Empty {label}: {path}")
        return False
    return True


def inspect_video(path: Path) -> VideoInfo:
    """Open a video with the same OpenCV stack used by the lab tools."""
    if not path.is_file() or path.stat().st_size == 0:
        raise StaffLabError(f"Video is missing or empty: {path}")
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise StaffLabError(f"OpenCV could not open video: {path}")
        ok, frame = capture.read()
        if not ok or frame is None:
            raise StaffLabError(f"OpenCV could not read the first frame: {path}")
        height, width = frame.shape[:2]
        return VideoInfo(
            path=path,
            width=int(width),
            height=int(height),
            fps=float(capture.get(cv2.CAP_PROP_FPS)),
            frames=int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
        )
    finally:
        capture.release()


def _test_mp4_codec(output_root: Path, size_wh: tuple[int, int]) -> tuple[bool, str]:
    """Write and read a tiny temporary MP4, deleting it in all cases."""
    output_root.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix="staff_lab_codec_", suffix=".mp4", dir=output_root, delete=False)
    path = Path(handle.name)
    handle.close()
    path.unlink(missing_ok=True)
    width, height = size_wh
    try:
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (width, height))
        if not writer.isOpened():
            return False, "OpenCV could not open an mp4v VideoWriter"
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        for _ in range(3):
            writer.write(frame)
        writer.release()
        try:
            info = inspect_video(path)
        except StaffLabError as error:
            return False, str(error)
        return info.width == width and info.height == height, (
            f"mp4v write/read succeeded ({info.width}x{info.height}, {info.frames} frames)"
        )
    finally:
        path.unlink(missing_ok=True)


def run_preflight(
    output_root: Path,
    source: str | None = None,
    dataset_root: Path | None = None,
    name: str = "run1",
    plan: Path | None = None,
    allow_geometry_mismatch: bool = False,
) -> tuple[bool, list[str], list[str]]:
    """Run local preflight checks and return ``(ok, messages, warnings)``."""
    name = _safe_run_name(name)
    config = load_camera_config("vial_fill")
    messages = [
        f"Python {platform.python_version()} ({sys.executable})",
        f"OpenCV {cv2.__version__}; NumPy {np.__version__}; pandas {pd.__version__}; "
        f"scikit-image {skimage.__version__}",
        f"Camera config: {(CONFIG_DIR / 'vial_fill.json').resolve()} "
        f"expects {config.image_size_wh[0]}x{config.image_size_wh[1]}",
    ]
    warnings = []
    ok = True

    now = datetime.now().astimezone()
    offset_hours = now.utcoffset().total_seconds() / 3600 if now.utcoffset() else 0.0
    messages.append(f"Local clock: {now.isoformat()} ({now.tzname()}, UTC{offset_hours:+g})")
    if offset_hours not in (-6.0, -5.0):
        warnings.append(
            "Workstation timezone is not Central Time (UTC-6/UTC-5). Correct it and verify "
            "clock synchronization before capture."
        )

    if sys.version_info < (3, 12):
        ok = False
        messages.append("FAIL Python 3.12 or newer is required by the pinned dependencies.")

    output_root = output_root.resolve()
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="staff_lab_write_", dir=output_root) as probe:
            probe.write(b"ok")
            probe.flush()
        free_gb = shutil.disk_usage(output_root).free / (1024 ** 3)
        messages.append(f"Output: {output_root} is writable; {free_gb:.1f} GiB free")
        if free_gb < 5:
            ok = False
            messages.append(f"FAIL only {free_gb:.1f} GiB is free; use another destination.")
    except OSError as error:
        ok = False
        messages.append(f"FAIL output {output_root}: {error}")

    if ok:
        codec_ok, detail = _test_mp4_codec(output_root, config.image_size_wh)
        messages.append(("MP4 codec: " if codec_ok else "FAIL MP4 codec: ") + detail)
        ok = ok and codec_ok

    if dataset_root is None:
        value = os.environ.get("DATASET_ROOT")
        dataset_root = Path(value) if value else None
    if dataset_root is None:
        warnings.append("DATASET_ROOT is not set; lab_check will skip the camera-shift comparison.")
    elif not (dataset_root / "videos.csv").is_file():
        warnings.append(f"Dataset root does not contain videos.csv: {dataset_root}")
    else:
        messages.append(f"Dataset root: {dataset_root.resolve()}")

    checked_plan = None
    if plan is None:
        warnings.append(
            "No run plan supplied. Environment checks can pass, but create a plan before "
            "production capture."
        )
    else:
        try:
            checked_plan = load_run_plan(plan)
            expected = list(range(1, len(checked_plan) + 1))
            if checked_plan["vial_order"].tolist() != expected:
                raise ValueError(f"vial_order must be exactly 1..{len(checked_plan)}")
            if (checked_plan["recipe_id"] <= 0).any():
                raise ValueError("recipe_id values must be positive")
            messages.append(f"Run plan: {plan.resolve()} ({len(checked_plan)} vials)")
        except (OSError, ValueError, pd.errors.EmptyDataError) as error:
            ok = False
            messages.append(f"FAIL run plan {plan}: {error}")

    source_safe = True
    if source is not None:
        try:
            validate_source(source)
        except OSError as error:
            source_safe = False
            ok = False
            messages.append(f"FAIL source: {error}")

    if source is not None and source_safe:
        capture = None
        try:
            capture = open_source(source, *config.image_size_wh)
            read_ok, frame = capture.read()
            if not read_ok or frame is None:
                raise OSError(f"source {source} returned no frame")
            height, width = frame.shape[:2]
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            messages.append(
                f"Source {safe_source_label(source)}: readable at {width}x{height}; "
                f"reports {fps:.1f} fps"
            )
            if (width, height) != config.image_size_wh:
                detail = f"source size differs from expected {config.image_size_wh[0]}x{config.image_size_wh[1]}"
                if allow_geometry_mismatch:
                    warnings.append(detail + "; staff-authorized capture is calibration-only.")
                else:
                    ok = False
                    messages.append("FAIL " + detail)
        except OSError as error:
            ok = False
            messages.append(f"FAIL source {safe_source_label(source)}: {error}")
        finally:
            if capture is not None:
                capture.release()

    scripts = REPO_ROOT / "scripts"
    commands = []
    is_file_source = bool(source and source_safe and Path(source).is_file())
    if is_file_source:
        warnings.append(
            "File source detected: preserve it and process it directly. Confirm clock mode; "
            "add --true-rate only when staff confirms true-rate storage."
        )
        if checked_plan is not None:
            file_name = Path(source).stem
            commands.append(_format_command([
                sys.executable, scripts / "extract_vials.py", "--video-file", source,
                "--run-plan", plan, "--data-origin", "real_line", "--out", output_root / "vials",
            ]))
            commands.append(_format_command([
                sys.executable, Path(__file__).resolve(), "verify", "--name", file_name,
                "--source-video", source, "--plan", plan,
                "--vials-dir", output_root / "vials",
            ] + (["--allow-geometry-mismatch"] if allow_geometry_mismatch else [])))
    elif source_safe:
        chosen_source = source or "N"
        check = [sys.executable, scripts / "lab_check.py", "--source", chosen_source,
                 "--out", output_root / "lab_check"]
        if dataset_root is not None:
            check += ["--dataset-root", dataset_root]
        commands.extend([
            _format_command([sys.executable, scripts / "lab_check.py", "--list-cameras",
                             "--out", output_root / "lab_check"]),
            _format_command(check),
            _format_command([sys.executable, scripts / "lab_capture.py", "--source", chosen_source,
                             "--name", f"{name}_test", "--duration", "25", "--save-preview",
                             "--out", output_root / "lab"]),
        ])
        if checked_plan is not None:
            commands.extend([
                _format_command([sys.executable, scripts / "lab_capture.py", "--source", chosen_source,
                                 "--name", name, "--run-plan", plan, "--save-preview",
                                 "--out", output_root / "lab"]),
                _format_command([sys.executable, scripts / "extract_vials.py", "--video-file",
                                 output_root / "lab" / f"{name}.mp4", "--run-plan", plan,
                                 "--data-origin", "real_line", "--out", output_root / "vials"]),
                _format_command([sys.executable, Path(__file__).resolve(), "verify", "--name", name,
                                 "--plan", plan, "--lab-dir", output_root / "lab",
                                 "--vials-dir", output_root / "vials"]
                                + (["--allow-geometry-mismatch"] if allow_geometry_mismatch else [])),
            ])
    messages.append("Exact next commands:\n  " + "\n  ".join(commands))
    return ok, messages, warnings


def make_plan(recipe_ids: Iterable[int], output: Path) -> pd.DataFrame:
    """Write an exact, sequential ``vial_order,recipe_id`` plan without overwriting."""
    recipes = list(recipe_ids)
    if not recipes:
        raise StaffLabError("Give at least one recipe ID.")
    if any(recipe <= 0 for recipe in recipes):
        raise StaffLabError("Every recipe ID must be a positive whole number.")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing run plan: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame({"vial_order": range(1, len(recipes) + 1), "recipe_id": recipes})
    table.to_csv(output, index=False)
    # Reuse the production parser as the final format check.
    checked = load_run_plan(output)
    if checked["vial_order"].tolist() != list(range(1, len(recipes) + 1)):
        raise StaffLabError(f"Internal error: generated plan is not sequential: {output}")
    return checked


def _load_plan_for_verify(path: Path, errors: list[str]) -> pd.DataFrame | None:
    try:
        plan = load_run_plan(path)
    except (OSError, ValueError, pd.errors.EmptyDataError) as error:
        errors.append(f"Invalid run plan {path}: {error}")
        return None
    expected_order = list(range(1, len(plan) + 1))
    if plan["vial_order"].tolist() != expected_order:
        errors.append(
            f"Run plan vial_order must be exactly 1..{len(plan)}; got {plan['vial_order'].tolist()}."
        )
    return plan


REQUIRED_NOTE_FIELDS = (
    "Run name",
    "Original recording filename",
    "Packaged recording filename",
    "Camera/view confirmed as vial_fill",
    "Wall-clock start/end, including timezone",
    "Clock mode",
    "Run-plan filename",
    "Number of successful fills",
    "T-100 contents/color",
    "T-200 contents/color",
    "T-400 contents/color",
    "Operator/staff contact",
    "Backup location",
)


def validate_notes(path: Path) -> dict[str, str]:
    """Require the minimum operational metadata before a run can be packaged."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise StaffLabError(f"Could not read session notes {path}: {error}") from error
    fields = {}
    for line in lines:
        if not line.startswith("- ") or ":" not in line:
            continue
        label, value = line[2:].split(":", 1)
        fields[label.strip()] = value.strip()
    missing = [label for label in REQUIRED_NOTE_FIELDS if not fields.get(label)]
    if missing:
        raise StaffLabError("Session notes have blank/missing required fields: " + ", ".join(missing))
    if fields["Camera/view confirmed as vial_fill"].lower() != "yes":
        raise StaffLabError("Session notes must confirm Camera/view confirmed as vial_fill: yes")
    if fields["Clock mode"].lower() not in {"dataset", "true"}:
        raise StaffLabError("Session notes Clock mode must be dataset or true before packaging.")
    try:
        if int(fields["Number of successful fills"]) <= 0:
            raise ValueError
    except ValueError as error:
        raise StaffLabError("Session notes Number of successful fills must be a positive integer.") from error
    return fields


def verify_run(
    name: str,
    plan_path: Path,
    lab_dir: Path = Path("outputs/lab"),
    vials_dir: Path = Path("outputs/vials"),
    source_video: Path | None = None,
    allow_geometry_mismatch: bool = False,
) -> VerificationResult:
    """Validate one captured and processed run without changing its artifacts."""
    name = _safe_run_name(name)
    result = VerificationResult(name)
    plan = _load_plan_for_verify(plan_path, result.errors)
    if plan is not None:
        result.plan_count = len(plan)

    capture_mode = source_video is None
    raw = lab_dir / f"{name}.mp4" if source_video is None else source_video
    preview = lab_dir / f"{name}_preview.mp4"
    frame_log = lab_dir / f"{name}_frames.csv"
    capture_json = lab_dir / f"{name}_capture.json"
    live_jsonl = lab_dir / f"{name}_live.jsonl"
    extracted = vials_dir / name
    events_csv = extracted / "events.csv"
    signals_csv = extracted / "signals.csv"
    manifest_csv = extracted / "manifest.csv"
    records_json = extracted / "records.json"
    records_jsonl = extracted / "records.jsonl"
    extraction_json = extracted / "extraction.json"

    required_files = [
        (raw, "raw recording" if capture_mode else "staff-provided source video"),
        (events_csv, "extracted events CSV"),
        (signals_csv, "extraction signals CSV"),
        (manifest_csv, "extracted-frame manifest CSV"),
        (records_json, "records JSON"),
        (records_jsonl, "records JSONL"),
        (extraction_json, "extraction metadata JSON"),
    ]
    if capture_mode:
        required_files[1:1] = [
            (preview, "saved preview"),
            (frame_log, "frame clock CSV"),
            (capture_json, "capture metadata JSON"),
            (live_jsonl, "live readout JSONL"),
        ]
    for path, label in required_files:
        _nonempty_file(path, label, result.errors)

    config = load_camera_config("vial_fill")
    if raw.is_file() and raw.stat().st_size:
        try:
            result.raw_video = inspect_video(raw)
            if (result.raw_video.width, result.raw_video.height) != config.image_size_wh:
                detail = (
                    f"Raw video is {result.raw_video.width}x{result.raw_video.height}; "
                    f"expected {config.image_size_wh[0]}x{config.image_size_wh[1]}."
                )
                if allow_geometry_mismatch:
                    result.warnings.append(detail + " Staff-authorized calibration-only override used.")
                else:
                    result.errors.append(detail)
        except StaffLabError as error:
            result.errors.append(str(error))
    if capture_mode and preview.is_file() and preview.stat().st_size:
        try:
            result.preview_video = inspect_video(preview)
            if result.raw_video and (
                result.preview_video.height != result.raw_video.height
                or result.preview_video.width <= result.raw_video.width
            ):
                result.errors.append(
                    "Saved preview does not have the expected readout panel beside the camera frame."
                )
            if result.raw_video and result.preview_video.frames != result.raw_video.frames:
                result.errors.append(
                    f"Preview has {result.preview_video.frames} frames but raw video has "
                    f"{result.raw_video.frames}."
                )
        except StaffLabError as error:
            result.errors.append(str(error))

    capture_meta = None
    if capture_mode and capture_json.is_file() and capture_json.stat().st_size:
        try:
            capture_meta = _read_json(capture_json)
            if not isinstance(capture_meta, dict) or int(capture_meta.get("frames", 0)) <= 0:
                result.errors.append(f"Capture metadata has no positive frame count: {capture_json}")
            if isinstance(capture_meta, dict) and capture_meta.get("data_origin") != "real_line":
                result.warnings.append(
                    f"Capture metadata says data_origin={capture_meta.get('data_origin')!r}; "
                    "document why if this is approved real-line footage."
                )
        except (StaffLabError, TypeError, ValueError) as error:
            result.errors.append(str(error))

    if capture_mode and frame_log.is_file() and frame_log.stat().st_size:
        try:
            with frame_log.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                required = {"frame_index", "wall_time", "elapsed_s"}
                if not required.issubset(reader.fieldnames or []):
                    result.errors.append(f"Frame log lacks columns {sorted(required)}: {frame_log}")
                    frame_rows = []
                else:
                    frame_rows = list(reader)
            if capture_meta and len(frame_rows) != int(capture_meta["frames"]):
                result.errors.append(
                    f"Frame log has {len(frame_rows)} rows but capture metadata says "
                    f"{capture_meta['frames']} frames."
                )
            if result.raw_video and capture_meta and result.raw_video.frames != int(capture_meta["frames"]):
                result.errors.append(
                    f"Raw MP4 reports {result.raw_video.frames} frames but capture metadata says "
                    f"{capture_meta['frames']}."
                )
        except (OSError, KeyError, TypeError, ValueError) as error:
            result.errors.append(f"Could not validate frame log {frame_log}: {error}")

    live_rows = []
    if capture_mode and live_jsonl.is_file() and live_jsonl.stat().st_size:
        try:
            live_rows = _read_jsonl(live_jsonl)
        except StaffLabError as error:
            result.errors.append(str(error))

    if events_csv.is_file() and events_csv.stat().st_size:
        try:
            events = pd.read_csv(events_csv)
            if "n_pours" not in events:
                result.errors.append(f"Events CSV has no n_pours column: {events_csv}")
            else:
                pours = pd.to_numeric(events["n_pours"], errors="coerce")
                if pours.isna().any():
                    result.errors.append(f"Events CSV contains invalid n_pours values: {events_csv}")
                else:
                    result.detected_count = int((pours > 0).sum())
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
            result.errors.append(f"Could not validate events CSV {events_csv}: {error}")

    records = None
    jsonl_records = None
    if records_json.is_file() and records_json.stat().st_size:
        try:
            records = _read_json(records_json)
            if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
                result.errors.append(f"Records JSON must contain a list of objects: {records_json}")
                records = None
        except StaffLabError as error:
            result.errors.append(str(error))
    if records_jsonl.is_file() and records_jsonl.stat().st_size:
        try:
            jsonl_records = _read_jsonl(records_jsonl)
        except StaffLabError as error:
            result.errors.append(str(error))
    if records is not None:
        result.record_count = len(records)
        result.measured_count = sum(bool(row.get("quality", {}).get("ok")) for row in records)
        if jsonl_records is not None and records != jsonl_records:
            result.errors.append("records.json and records.jsonl do not contain the same records.")
        for index, row in enumerate(records, 1):
            provenance = row.get("provenance", {})
            sources = provenance.get("sources", []) if isinstance(provenance, dict) else []
            if provenance.get("data_origin") != "derived" or not sources or any(
                source.get("data_origin") != "real_line"
                for source in sources
                if isinstance(source, dict)
            ) or not all(isinstance(source, dict) for source in sources):
                result.errors.append(
                    f"Record {index} must be derived entirely from real_line sources."
                )

    extraction_meta = None
    if extraction_json.is_file() and extraction_json.stat().st_size:
        try:
            extraction_meta = _read_json(extraction_json)
            if not isinstance(extraction_meta, dict):
                raise StaffLabError(f"Extraction metadata must be a JSON object: {extraction_json}")
            if extraction_meta.get("data_origin") != "real_line":
                result.errors.append(
                    f"Extraction metadata data_origin must be real_line: {extraction_json}"
                )
            if extraction_meta.get("clock_mode") not in {"dataset", "true"}:
                result.errors.append(
                    f"Extraction metadata has unsupported clock_mode: {extraction_meta.get('clock_mode')!r}."
                )
            if extraction_meta.get("source_name") != raw.name:
                result.errors.append(
                    f"Extraction source {extraction_meta.get('source_name')!r} does not match "
                    f"packaged recording {raw.name!r}."
                )
            if plan is not None and extraction_meta.get("run_plan") != plan_path.name:
                result.errors.append(
                    f"Extraction plan {extraction_meta.get('run_plan')!r} does not match "
                    f"verified plan {plan_path.name!r}."
                )
        except StaffLabError as error:
            result.errors.append(str(error))

    if plan is not None and result.detected_count != len(plan):
        result.errors.append(
            f"Run plan has {len(plan)} vials but extraction detected {result.detected_count} pours."
        )
    if records is not None and result.record_count != result.detected_count:
        result.errors.append(
            f"Extraction detected {result.detected_count} pours but wrote {result.record_count} records."
        )
    if plan is not None and records is not None and len(records) == len(plan):
        expected = list(zip(plan["vial_order"].tolist(), plan["recipe_id"].tolist()))
        actual = [(row.get("vial_id"), row.get("recipe_id")) for row in records]
        if actual != expected:
            result.errors.append(f"Record vial/recipe IDs {actual} do not match run plan {expected}.")
    if plan is not None and live_rows and len(live_rows) != len(plan):
        result.warnings.append(
            f"Live readout logged {len(live_rows)} vials for a {len(plan)}-vial plan; "
            "authoritative extraction is used for verification."
        )

    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_revision() -> str:
    """Return the exact repository revision used to create a handoff package."""
    try:
        dirty = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--untracked-files=all"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        if dirty:
            raise StaffLabError(
                "Refusing to package from a dirty checkout. Preserve the run, then use the "
                "verified release/tag or commit and review the source changes first."
            )
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise StaffLabError(f"Could not determine source revision: {error}") from error


def _package_sources(
    name: str,
    plan_path: Path,
    notes_path: Path,
    lab_dir: Path,
    vials_dir: Path,
    source_video: Path | None = None,
) -> dict[Path, Path]:
    extracted = vials_dir / name
    sources = {
        Path("metadata") / "events.csv": extracted / "events.csv",
        Path("metadata") / "manifest.csv": extracted / "manifest.csv",
        Path("metadata") / "signals.csv": extracted / "signals.csv",
        Path("metadata") / "extraction.json": extracted / "extraction.json",
        Path("records") / "records.json": extracted / "records.json",
        Path("records") / "records.jsonl": extracted / "records.jsonl",
        Path("plan") / "plan.csv": plan_path,
        Path("notes") / "notes.txt": notes_path,
    }
    if source_video is not None:
        sources[Path("raw") / source_video.name] = source_video
    else:
        sources.update({
            Path("raw") / f"{name}.mp4": lab_dir / f"{name}.mp4",
            Path("preview") / f"{name}_preview.mp4": lab_dir / f"{name}_preview.mp4",
            Path("metadata") / f"{name}_frames.csv": lab_dir / f"{name}_frames.csv",
            Path("metadata") / f"{name}_capture.json": lab_dir / f"{name}_capture.json",
            Path("metadata") / f"{name}_live.jsonl": lab_dir / f"{name}_live.jsonl",
        })
    return sources


def package_run(
    name: str,
    plan_path: Path,
    notes_path: Path,
    destination: Path,
    lab_dir: Path = Path("outputs/lab"),
    vials_dir: Path = Path("outputs/vials"),
    source_video: Path | None = None,
    allow_geometry_mismatch: bool = False,
) -> Path:
    """Create a new verified handoff directory and a SHA-256 manifest."""
    name = _safe_run_name(name)
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing handoff destination: {destination}")
    fields = validate_notes(notes_path)
    revision = _git_revision()
    result = verify_run(
        name, plan_path, lab_dir, vials_dir, source_video, allow_geometry_mismatch
    )
    if not result.ok:
        raise StaffLabError("Run verification failed:\n- " + "\n- ".join(result.errors))
    raw = source_video if source_video is not None else lab_dir / f"{name}.mp4"
    expected_notes = {
        "Run name": name,
        "Packaged recording filename": raw.name,
        "Run-plan filename": plan_path.name,
        "Number of successful fills": str(result.detected_count),
    }
    mismatches = [
        f"{label} is {fields.get(label)!r}; expected {expected!r}"
        for label, expected in expected_notes.items()
        if fields.get(label) != expected
    ]
    extraction_meta = _read_json(vials_dir / name / "extraction.json")
    if fields.get("Clock mode", "").lower() != extraction_meta.get("clock_mode"):
        mismatches.append(
            f"Clock mode is {fields.get('Clock mode')!r}; extraction used "
            f"{extraction_meta.get('clock_mode')!r}"
        )
    if mismatches:
        raise StaffLabError("Session notes do not match packaged artifacts:\n- " + "\n- ".join(mismatches))
    sources = _package_sources(name, plan_path, notes_path, lab_dir, vials_dir, source_video)
    missing = [f"{label}: {source}" for label, source in sources.items()
               if not source.is_file() or source.stat().st_size == 0]
    if missing:
        raise StaffLabError("Cannot package missing/empty files:\n- " + "\n- ".join(missing))

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        for relative, source in sources.items():
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        revision_path = temporary / "metadata" / "source-revision.txt"
        revision_path.parent.mkdir(parents=True, exist_ok=True)
        revision_path.write_text(revision + "\n", encoding="utf-8")
        lines = []
        packaged_files = sorted(
            (path for path in temporary.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(temporary).as_posix(),
        )
        for path in packaged_files:
            relative = path.relative_to(temporary)
            lines.append(f"{_sha256(path)}  {relative.as_posix()}")
        (temporary / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite existing handoff destination: {destination}")
        for attempt in range(5):
            try:
                temporary.rename(destination)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                # Windows antivirus/indexers can briefly hold a newly copied MP4.
                time.sleep(0.2 * (attempt + 1))
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def _print_verification(result: VerificationResult) -> None:
    verdict = "VERIFY OK" if result.ok else "VERIFY FAILED"
    print(f"{verdict}: {result.name}")
    print(
        f"  plan {result.plan_count}; detected pours {result.detected_count}; "
        f"records {result.record_count}; measured colors {result.measured_count}"
    )
    if result.raw_video:
        raw = result.raw_video
        print(f"  raw {raw.width}x{raw.height}, {raw.frames} frames, {raw.fps:.2f} fps")
    if result.preview_video:
        preview = result.preview_video
        print(f"  preview {preview.width}x{preview.height}, {preview.frames} frames")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight", help="Check local config, output, codec, and optional source")
    preflight.add_argument("--source", help="Optional camera index, URL, or video file to open once")
    preflight.add_argument("--output-root", type=Path, default=Path("outputs"))
    preflight.add_argument("--dataset-root", type=Path, help="Defaults to $DATASET_ROOT")
    preflight.add_argument("--name", default="run1", help="Run name used in the printed command")
    preflight.add_argument("--plan", type=Path, help="Validate this plan and print production commands")
    preflight.add_argument(
        "--allow-geometry-mismatch", action="store_true",
        help="Allow staff-authorized capture at nonconfigured geometry as calibration-only data",
    )

    make = commands.add_parser("make-plan", help="Write vial_order,recipe_id CSV from recipe IDs")
    make.add_argument("recipe_ids", type=int, nargs="+")
    make.add_argument("--output", type=Path, default=Path("plan.csv"))

    verify = commands.add_parser("verify", help="Validate one captured and processed run")
    verify.add_argument("--name", required=True)
    verify.add_argument("--plan", type=Path, required=True)
    verify.add_argument("--lab-dir", type=Path, default=Path("outputs/lab"))
    verify.add_argument("--vials-dir", type=Path, default=Path("outputs/vials"))
    verify.add_argument(
        "--source-video", type=Path,
        help="Verify a preserved staff-provided original instead of lab_capture sidecars",
    )
    verify.add_argument(
        "--allow-geometry-mismatch", action="store_true",
        help="Accept staff-authorized non-640x480 footage as calibration-only",
    )

    package = commands.add_parser("package", help="Create a new checksummed handoff directory")
    package.add_argument("--name", required=True)
    package.add_argument("--plan", type=Path, required=True)
    package.add_argument("--notes", type=Path, required=True)
    package.add_argument("--destination", type=Path, required=True)
    package.add_argument("--lab-dir", type=Path, default=Path("outputs/lab"))
    package.add_argument("--vials-dir", type=Path, default=Path("outputs/vials"))
    package.add_argument(
        "--source-video", type=Path,
        help="Package a preserved staff-provided original instead of lab_capture sidecars",
    )
    package.add_argument(
        "--allow-geometry-mismatch", action="store_true",
        help="Package staff-authorized non-640x480 footage as calibration-only",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            ok, messages, warnings = run_preflight(
                args.output_root, args.source, args.dataset_root, args.name, args.plan,
                args.allow_geometry_mismatch,
            )
            print("PREFLIGHT OK" if ok else "PREFLIGHT FAILED")
            for message in messages:
                print(message)
            for warning in warnings:
                print(f"WARNING: {warning}")
            return 0 if ok else 1
        if args.command == "make-plan":
            plan = make_plan(args.recipe_ids, args.output)
            print(f"Wrote {len(plan)} vials to {args.output}")
            return 0
        if args.command == "verify":
            result = verify_run(
                args.name, args.plan, args.lab_dir, args.vials_dir, args.source_video,
                args.allow_geometry_mismatch,
            )
            _print_verification(result)
            return 0 if result.ok else 1
        if args.command == "package":
            destination = package_run(
                args.name, args.plan, args.notes, args.destination, args.lab_dir,
                args.vials_dir, args.source_video, args.allow_geometry_mismatch,
            )
            print(f"Packaged verified run to {destination}")
            print(f"Checksums: {destination / 'SHA256SUMS.txt'}")
            return 0
    except (StaffLabError, FileExistsError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
