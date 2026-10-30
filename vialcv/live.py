"""Live per-vial readout: follow fill cycles frame by frame and measure each vial as it settles.

An online version of the dwell -> pour -> settled logic in vialcv.events, using the same
signals and thresholds, for the lab recorder's preview. It only sees the past, so it is
simpler than detect_events (no departure-tail trim; a trailing instead of a centered
median), and `scripts/extract_vials.py` on the finished recording stays the authoritative
measurement.

Each vial is measured with vialcv.detect.detect_vial_color while it is settled, against
an empty-vial reference frame taken before its first pour, and re-measured every
REMEASURE_S until the carrier leaves; the last measurement is the vial's result.

With a run plan (recipe per vial in fill order), recipes are assigned by the live count
of filled vials. A missed or extra pour shifts that count, so the IDs shown are
provisional. When the second vial of a recipe settles, its color is compared with the
first, and the first is flagged if they differ by more than the flag threshold. This is
a measured-appearance consistency check, not a carryover model or an expected color.
"""

from collections import deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from vialcv.colorstats import delta_e_2000
from vialcv.detect import ZONE_PREFERENCE
from vialcv.events import (
    ARRIVAL_IGNORE_S,
    COLLAR_PRESENT_FRACTION,
    MERGE_GAP_S,
    MIN_POUR_S,
    MIN_REFERENCE_WINDOW_S,
    MIN_SETTLED_S,
    REFERENCE_MARGIN_S,
    STATION_STILL_MOTION,
    STREAM_ON_COLUMN_DEV,
    VIAL_CHANGE_LAG_S,
    VIAL_CHANGE_SMOOTH_S,
    VIAL_POURING_CHANGE,
    VIAL_SETTLED_CHANGE,
)

REMEASURE_S = 1.0
# Pre-pour frames kept for the empty reference: one every REFERENCE_SAMPLE_S, at most this many.
REFERENCE_SAMPLE_S = 0.25
REFERENCE_BUFFER = 60
# On video 5, vials 2 and 3 of a recipe differed by up to ~2.7 dE00 in the backlit zone and
# ~6 in the noisier bore zone; first vials by a median ~11. This default was picked after
# looking at video 5, so a lab recording is the independent check of it.
DEFAULT_FLAG_DE00 = 5.0


@dataclass
class LiveVial:
    number: int
    dwell_start_s: float
    first_pour_s: float
    recipe_id: int | None = None
    position_in_recipe: int | None = None
    record: dict | None = None
    measured_at_s: float | None = None
    status: str = "pouring"  # pouring | settled | final | not_measured
    compare: dict | None = None  # this vial vs the previous vial of the same recipe
    flag: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.record and self.record["quality"]["ok"])

    def summary(self) -> dict:
        """A JSON-ready line for the live log."""
        return {"live_vial": self.number, "recipe_id": self.recipe_id,
                "position_in_recipe": self.position_in_recipe, "status": self.status,
                "dwell_start_s": round(self.dwell_start_s, 3), "first_pour_s": round(self.first_pour_s, 3),
                "measured_at_s": None if self.measured_at_s is None else round(self.measured_at_s, 3),
                "compare_to_previous_same_recipe": self.compare, "flag": self.flag, "notes": self.notes,
                "record": self.record}


def zone_lab(record: dict, zone: str) -> list[float] | None:
    described = (record.get("color") or {}).get("zones", {}).get(zone)
    if not described or not described.get("ok"):
        return None
    return [described["lab"]["median"][k] for k in "Lab"]


def compare_records(a: dict, b: dict) -> dict:
    """CIEDE2000 between two records in the first background zone both measured."""
    for zone in ZONE_PREFERENCE:
        lab_a, lab_b = zone_lab(a, zone), zone_lab(b, zone)
        if lab_a is not None and lab_b is not None:
            return {"zone": zone, "de00": round(delta_e_2000(lab_a, lab_b), 2)}
    return {"zone": None, "de00": None}


class LiveVialReader:
    """Feed one sampled frame at a time with `update()`; finished and current vials are in `vials`.

    `measure(frame_bgr, reference_bgr_or_None, t) -> record` does the measurement (for
    example a detect_vial_color wrapper); it is injected so the logic can be tested
    without images. Times are in dataset-clock seconds, like every threshold here.
    """

    def __init__(self, measure, samples_per_second: float, plan: pd.DataFrame | None = None,
                 flag_de00: float = DEFAULT_FLAG_DE00):
        self.measure = measure
        self.plan = plan
        self.flag_de00 = flag_de00
        self.smooth = max(int(round(VIAL_CHANGE_SMOOTH_S * samples_per_second)), 1)
        self.recent_change: deque[float] = deque(maxlen=self.smooth)
        self.vials: list[LiveVial] = []
        self.finished: list[LiveVial] = []  # vials finalized since the last call to pop_finished()
        self._reset_dwell()
        self.parked_since = None
        self.unparked_since = None

    def _reset_dwell(self):
        self.dwell_start = None
        self.current: LiveVial | None = None
        self.pour_run_start = None
        self.last_pouring = None
        self.last_active = None
        self.reference_frames: deque = deque(maxlen=REFERENCE_BUFFER)
        self.reference = None
        self.last_parked_frame = None
        self.recent_change.clear()

    def pop_finished(self) -> list[LiveVial]:
        finished, self.finished = self.finished, []
        return finished

    def update(self, t: float, frame: np.ndarray, signals: tuple[float, float, float, float]) -> str:
        """Advance by one sample; return a short live state for display."""
        collar_dark, motion, change, stream = signals
        parked = collar_dark >= COLLAR_PRESENT_FRACTION and (np.isnan(motion) or motion <= STATION_STILL_MOTION)

        if parked:
            self.unparked_since = None
            if self.dwell_start is None:
                self.dwell_start = t
            self.last_parked_frame = frame
        elif self.dwell_start is not None:
            # Short breaks are merged into the dwell, like detect_events.
            self.unparked_since = self.unparked_since if self.unparked_since is not None else t
            if t - self.unparked_since > MERGE_GAP_S:
                self._end_dwell(t)
            return "moving" if not np.isnan(motion) and motion > STATION_STILL_MOTION else "no carrier"
        else:
            return "moving" if not np.isnan(motion) and motion > STATION_STILL_MOTION else "no carrier"

        arrived = t >= self.dwell_start + ARRIVAL_IGNORE_S
        # Change compares with a frame VIAL_CHANGE_LAG_S back, so it still sees the arriving
        # carrier for that long after the ignore window. detect_events' centered median
        # absorbs that tail; a trailing median does not, so those samples are skipped.
        if t >= self.dwell_start + ARRIVAL_IGNORE_S + VIAL_CHANGE_LAG_S and not np.isnan(change):
            self.recent_change.append(change)
        smoothed = float(np.median(self.recent_change)) if self.recent_change else np.nan
        pouring = arrived and (stream >= STREAM_ON_COLUMN_DEV or (not np.isnan(smoothed) and smoothed >= VIAL_POURING_CHANGE))
        if pouring:
            if self.pour_run_start is None or t - self.last_pouring > MERGE_GAP_S:
                self.pour_run_start = t
            self.last_pouring = t
        active = pouring or any(not np.isnan(v) and v >= VIAL_SETTLED_CHANGE for v in (change, smoothed))
        if active and arrived:
            self.last_active = t

        if self.current is None:
            if arrived and not pouring and (not self.reference_frames
                                            or t - self.reference_frames[-1][0] >= REFERENCE_SAMPLE_S):
                self.reference_frames.append((t, frame))
            if pouring and t - self.pour_run_start >= MIN_POUR_S:
                self._start_vial(self.pour_run_start)
            return "pouring" if pouring else "parked, waiting"

        vial = self.current
        if self.last_active is not None and t - self.last_active < MIN_SETTLED_S:
            vial.status = "pouring" if pouring else vial.status
            return "pouring" if pouring else "settling"
        if vial.measured_at_s is None or vial.measured_at_s < self.last_active or t - vial.measured_at_s >= REMEASURE_S:
            self._measure(vial, t, frame)
        vial.status = "settled"
        return "settled, measured" if vial.ok else "settled, no color"

    def _start_vial(self, first_pour_s: float):
        vial = LiveVial(len(self.vials) + 1, self.dwell_start, first_pour_s)
        start, end = self.dwell_start + ARRIVAL_IGNORE_S + REFERENCE_MARGIN_S, first_pour_s - REFERENCE_MARGIN_S
        candidates = [(abs(ft - (start + end) / 2), f) for ft, f in self.reference_frames if start <= ft <= end]
        if end - start >= MIN_REFERENCE_WINDOW_S and candidates:
            self.reference = min(candidates, key=lambda c: c[0])[1]
        else:
            vial.notes.append("no empty reference before the first pour")
        self.reference_frames.clear()

        if self.plan is not None:
            if vial.number <= len(self.plan):
                vial.recipe_id = int(self.plan.iloc[vial.number - 1]["recipe_id"])
                previous = self.vials[-1] if self.vials else None
                same = previous is not None and previous.recipe_id == vial.recipe_id
                vial.position_in_recipe = previous.position_in_recipe + 1 if same else 1
            else:
                vial.notes.append(f"beyond the run plan's {len(self.plan)} vials")
        self.vials.append(vial)
        self.current = vial

    def close(self, t: float):
        """Finish a vial still at the station when the stream ends."""
        if self.current is not None:
            self.current.notes.append("stream ended before the carrier left")
            self._end_dwell(t)

    def _measure(self, vial: LiveVial, t: float, frame: np.ndarray):
        vial.record = self.measure(frame, self.reference, t)
        vial.measured_at_s = t
        self._compare(vial)

    def _compare(self, vial: LiveVial):
        if not vial.position_in_recipe or vial.position_in_recipe < 2:
            return
        previous = self.vials[vial.number - 2]
        if not vial.ok:
            # A re-measurement can fail after an earlier one succeeded: drop the stale result.
            vial.compare = None
            if vial.position_in_recipe == 2:
                previous.flag = None
            return
        if not previous.ok:
            vial.compare = {"to_live_vial": previous.number, "zone": None, "de00": None}
            return
        vial.compare = {"to_live_vial": previous.number, **compare_records(previous.record, vial.record)}
        de00 = vial.compare["de00"]
        if vial.position_in_recipe == 2:
            previous.flag = None
            if de00 is not None and de00 > self.flag_de00:
                previous.flag = f"first vial of recipe {vial.recipe_id} differs from the next by dE00 {de00:.1f}"

    def _end_dwell(self, t: float):
        vial = self.current
        if vial is not None:
            if vial.record is None and self.last_parked_frame is not None:
                # Poured until departure: measure the last parked frame, as extract_vials falls back.
                self._measure(vial, t, self.last_parked_frame)
                vial.notes.append("short_settle: measured on the last parked frame")
            vial.status = "final" if vial.record is not None else "not_measured"
            self.finished.append(vial)
        self._reset_dwell()
