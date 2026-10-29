"""Find fill events in vial_fill video and the settled frames after the last pour.

A fill cycle on this station is: a carrier parks at the station (dwell), one or more
dispense streams pour into the vial, the liquid settles for a few seconds, and the
carrier leaves. Per-frame signals are computed from fixed regions of the camera config;
event detection works on that signal table only, so it can be tuned and tested without
decoding video.

Thresholds were set on videos 1-4 (calibration); video 5 is used for evaluation.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from vialcv.dataset import VIDEO_FPS, iter_frames, video_fps
from vialcv.roi import CameraConfig, crop

# A carrier is parked when most of the collar face is dark and the station is still.
COLLAR_DARK_GRAY = 45
COLLAR_PRESENT_FRACTION = 0.8
STATION_STILL_MOTION = 3.0

# A pour is a thin vertical stream: one column of the nozzle window deviates from the rest.
STREAM_ON_COLUMN_DEV = 20.0

# Liquid change is measured over this lag; below the settled level the liquid is still.
# Clear or pale streams barely show in the nozzle window (video 3), so a pour is also
# recognized from sustained liquid change in the vial.
VIAL_CHANGE_LAG_S = 0.5
VIAL_SETTLED_CHANGE = 1.2
VIAL_POURING_CHANGE = 2.0
# The change lag still sees the arriving carrier at the start of a dwell.
ARRIVAL_IGNORE_S = 1.0
# A one-frame encoder quality step shows as a change plateau as long as the lag, so the
# change signal is median-filtered over a longer window than that.
VIAL_CHANGE_SMOOTH_S = 1.1

MIN_DWELL_S = 5.0
MIN_POUR_S = 0.5
MERGE_GAP_S = 0.5
MIN_SETTLED_S = 0.5

# The empty-vial reference frame is taken this far from the arrival and the first pour.
REFERENCE_MARGIN_S = 0.5
MIN_REFERENCE_WINDOW_S = 0.3

# Settled frames are picked from this long a window before the carrier leaves.
PICK_WINDOW_S = 1.5
DEPARTURE_MARGIN_S = 0.2

SIGNAL_COLUMNS = ["frame_index", "video_s", "collar_dark", "station_motion", "vial_change", "stream_column_dev"]


@dataclass(frozen=True)
class FillEvent:
    """One carrier dwell. `n_pours` counts pouring runs separated by more than
    MERGE_GAP_S; it is not a count of tanks dispensed."""

    event_idx: int
    dwell_start_s: float
    dwell_end_s: float
    n_pours: int
    pour_start_s: float | None
    pour_end_s: float | None
    settled_start_s: float | None
    settled_end_s: float | None
    quality: str
    detail: str | None


def stream_column_dev(window_bgr: np.ndarray) -> float:
    """Return how far the most deviant columns of a window differ from the median column."""
    columns = window_bgr.astype(np.float32).mean(axis=0)
    deviation = np.abs(columns - np.median(columns, axis=0)).sum(axis=1)
    return float(np.sort(deviation)[-3:].mean())


def compute_signals(video: str | Path, config: CameraConfig, step: int = 2,
                    fps: float | None = None) -> pd.DataFrame:
    """Return one row of signals per sampled frame of a vial_fill video.

    `fps` defaults to the rate stored in the file (30 for the dataset videos); video_s
    and all time thresholds use it, so recordings at other rates are timed correctly.
    """
    fps = fps or video_fps(video)
    lag = max(int(round(VIAL_CHANGE_LAG_S * fps / step)), 1)
    recent_vials: list[np.ndarray] = []
    previous_station = None
    rows = []

    for frame_index, frame in iter_frames(video, step=step):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        collar_dark = float((crop(gray, config.region("collar_face")) < COLLAR_DARK_GRAY).mean())

        station = cv2.resize(crop(gray, config.region("station")), None, fx=0.25, fy=0.25,
                             interpolation=cv2.INTER_AREA).astype(np.float32)
        motion = np.nan if previous_station is None else float(np.abs(station - previous_station).mean())
        previous_station = station

        vial = crop(gray, config.region("vial")).astype(np.float32)
        recent_vials.append(vial)
        change = float(np.abs(vial - recent_vials[0]).mean()) if len(recent_vials) > lag else np.nan
        if len(recent_vials) > lag:
            recent_vials.pop(0)

        rows.append((frame_index, frame_index / fps, collar_dark, motion, change,
                     stream_column_dev(crop(frame, config.region("nozzle_stream")))))

    return pd.DataFrame(rows, columns=SIGNAL_COLUMNS)


def runs(mask: np.ndarray, times: np.ndarray, merge_gap_s: float, min_length_s: float) -> list[tuple[int, int]]:
    """Return (first, last) row indices of True runs, merging short gaps and dropping short runs."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    spans = [(int(s), int(e) - 1) for s, e in zip(edges[::2], edges[1::2])]

    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and times[start] - times[merged[-1][1]] <= merge_gap_s:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return [(s, e) for s, e in merged if times[e] - times[s] >= min_length_s]


def detect_events(signals: pd.DataFrame) -> list[FillEvent]:
    """Return one FillEvent per carrier dwell at the station."""
    times = signals["video_s"].to_numpy()
    if len(times) < 2:
        return []
    sample_s = float(np.median(np.diff(times)))

    parked = (signals["collar_dark"].to_numpy() >= COLLAR_PRESENT_FRACTION) & (
        signals["station_motion"].fillna(0).to_numpy() <= STATION_STILL_MOTION)
    stream_on = signals["stream_column_dev"].to_numpy() >= STREAM_ON_COLUMN_DEV
    smooth = max(int(round(VIAL_CHANGE_SMOOTH_S / sample_s)) | 1, 1)
    change = signals["vial_change"].rolling(smooth, center=True, min_periods=1).median().to_numpy()

    events = []
    for dwell_start, dwell_end in runs(parked, times, MERGE_GAP_S, MIN_DWELL_S):
        notes = []
        if dwell_start == 0:
            notes.append("dwell starts at video start")
        if dwell_end == len(times) - 1:
            notes.append("dwell ends at video end; departure not seen")

        dwell = slice(dwell_start, dwell_end + 1)
        pouring = stream_on[dwell] | (change[dwell] >= VIAL_POURING_CHANGE)
        pouring &= times[dwell] >= times[dwell_start] + ARRIVAL_IGNORE_S
        pours = runs(pouring, times[dwell], MERGE_GAP_S, MIN_POUR_S)
        if not pours:
            events.append(FillEvent(len(events), times[dwell_start], times[dwell_end], 0,
                                    None, None, None, None, "no_pour_detected", "; ".join(notes) or None))
            continue

        pour_start = dwell_start + pours[0][0]
        pour_end = dwell_start + pours[-1][1]

        # The carrier starts moving a few frames before station motion crosses its
        # threshold; drop that rising tail so it is not mistaken for unsettled liquid.
        last_still = dwell_end
        while last_still > pour_end and change[last_still] >= VIAL_SETTLED_CHANGE:
            last_still -= 1
        settled_end_s = times[last_still] - DEPARTURE_MARGIN_S

        # The settled window is the stretch after the last activity before departure.
        active = np.flatnonzero(change[pour_end:last_still + 1] >= VIAL_SETTLED_CHANGE)
        settled_start = pour_end + int(active[-1]) + 1 if len(active) else pour_end + 1
        if settled_start > last_still:
            settled_start = None

        if settled_start is None or settled_end_s - times[settled_start] < MIN_SETTLED_S:
            quality = "short_settle"
            notes.append("liquid not still for long before departure")
            settled_start_s = times[settled_start] if settled_start is not None else None
        else:
            quality = "ok"
            settled_start_s = times[settled_start]

        events.append(FillEvent(len(events), times[dwell_start], times[dwell_end], len(pours),
                                times[pour_start], times[pour_end], settled_start_s, settled_end_s,
                                quality, "; ".join(notes) or None))
    return events


def pick_frames(event: FillEvent, n: int = 5, fps: float = VIDEO_FPS) -> list[int]:
    """Return up to n frame indices spread over the settled window just before departure.

    Events without a settled window fall back to the frames just before departure.
    """
    if event.pour_end_s is None:
        return []
    end_s = event.settled_end_s if event.settled_end_s is not None else event.dwell_end_s
    if end_s <= event.pour_end_s:
        # Poured until the departure trim: use whatever is left before the carrier moves.
        end_s = event.dwell_end_s - DEPARTURE_MARGIN_S
    start_s = max(end_s - PICK_WINDOW_S, event.pour_end_s)
    if event.settled_start_s is not None:
        start_s = max(start_s, event.settled_start_s)
    first, last = int(round(start_s * fps)), int(round(end_s * fps))
    if last < first:
        return []
    return sorted(set(np.linspace(first, last, min(n, last - first + 1)).round().astype(int).tolist()))


def reference_frame(event: FillEvent, fps: float = VIDEO_FPS) -> int | None:
    """Return a frame index showing the parked vial before its first pour, if there is one.

    The frame is midway between the end of the carrier's arrival and shortly before the
    first pour; None when that window is too short.
    """
    if event.pour_start_s is None:
        return None
    start_s = event.dwell_start_s + ARRIVAL_IGNORE_S + REFERENCE_MARGIN_S
    end_s = event.pour_start_s - REFERENCE_MARGIN_S
    if end_s - start_s < MIN_REFERENCE_WINDOW_S:
        return None
    return int(round((start_s + end_s) / 2 * fps))


def match_labels(events: list[FillEvent], vial_labels: pd.DataFrame) -> pd.DataFrame:
    """Match events with pours to labeled vials by overlap of pour time and label window.

    A vial is assigned only when the event overlaps exactly one label window and no other
    event claims the same vial; otherwise vial_id stays missing and `match_note` says why.
    """
    rows = []
    for event in events:
        row = {"event_idx": event.event_idx, "vial_id": pd.NA, "recipe_id": pd.NA,
               "overlap_s": 0.0, "start_offset_s": np.nan, "end_offset_s": np.nan, "match_note": None}
        if event.pour_start_s is None:
            row["match_note"] = "no pour"
            rows.append(row)
            continue
        overlap = (np.minimum(vial_labels["end_s"], event.pour_end_s)
                   - np.maximum(vial_labels["start_s"], event.pour_start_s)).clip(lower=0)
        hits = np.flatnonzero(overlap.to_numpy() > 0)
        if len(hits) == 1:
            label = vial_labels.iloc[hits[0]]
            row.update(vial_id=int(label["vial"]), recipe_id=int(label["recipe_id"]),
                       overlap_s=float(overlap.iloc[hits[0]]),
                       start_offset_s=event.pour_start_s - float(label["start_s"]),
                       end_offset_s=event.pour_end_s - float(label["end_s"]))
        else:
            row["match_note"] = "no overlapping label window" if len(hits) == 0 else "overlaps several label windows"
        rows.append(row)

    table = pd.DataFrame(rows)
    claimed = table["vial_id"].dropna()
    for vial in claimed[claimed.duplicated()].unique():
        duplicate = table["vial_id"] == vial
        table.loc[duplicate, ["vial_id", "recipe_id"]] = pd.NA
        table.loc[duplicate, "match_note"] = "several events overlap this vial's label window"
    table["vial_id"] = table["vial_id"].astype("Int64")
    table["recipe_id"] = table["recipe_id"].astype("Int64")
    return table
