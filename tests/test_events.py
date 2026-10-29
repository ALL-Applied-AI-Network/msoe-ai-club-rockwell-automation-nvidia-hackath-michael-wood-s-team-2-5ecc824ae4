"""Tests for fill-event detection on synthetic signal tables."""

import numpy as np
import pandas as pd
import pytest

from vialcv.events import (
    SIGNAL_COLUMNS,
    FillEvent,
    assign_run_plan,
    detect_events,
    load_run_plan,
    match_labels,
    pick_frames,
    station_state,
    stream_column_dev,
)

FPS = 30
STEP = 2


def make_signals(duration_s, dwells, streams=(), pours=(), keyframe_steps=()):
    """Build a signal table sampled every STEP frames.

    dwells: (start_s, end_s) carrier parked; motion spikes at each end.
    streams: (start_s, end_s) visible stream in the nozzle window.
    pours: (start_s, end_s) liquid change in the vial (with or without a visible stream).
    keyframe_steps: times of 0.5 s change plateaus like those seen at encoder keyframes.
    """
    frames = np.arange(0, int(duration_s * FPS), STEP)
    t = frames / FPS
    collar = np.zeros_like(t)
    motion = np.full_like(t, 0.3)
    change = np.full_like(t, 0.3)
    stream = np.full_like(t, 4.0)

    for start, end in dwells:
        collar[(t >= start) & (t <= end)] = 0.95
        for edge in (start, end):
            near = np.abs(t - edge) < 0.6
            motion[near] = 20.0
            change[near] = 30.0
        # The carrier starts moving a few frames before motion crosses its threshold.
        change[(t > end - 0.25) & (t <= end)] = 5.0
    for start, end in streams:
        stream[(t >= start) & (t <= end)] = 80.0
    for start, end in pours:
        change[(t >= start) & (t <= end)] = 4.0
    for at in keyframe_steps:
        change[(t >= at) & (t < at + 0.5)] = 1.6

    return pd.DataFrame(dict(zip(SIGNAL_COLUMNS, [frames, t, collar, motion, change, stream])))


def test_detects_dwells_pours_and_settled_window():
    signals = make_signals(
        100,
        dwells=[(2, 45), (48, 95)],
        streams=[(10, 20), (25, 30)],
        pours=[(10, 21), (25, 31), (60, 70)],
        keyframe_steps=[38],
    )
    events = detect_events(signals)

    assert len(events) == 2
    first, second = events
    assert first.n_pours == 2 and first.quality == "ok"
    assert first.pour_start_s == pytest.approx(10, abs=0.6)
    assert first.pour_end_s == pytest.approx(31, abs=0.6)
    assert 31 < first.settled_start_s < 33
    assert first.settled_end_s < 45

    # A clear pour shows only as liquid change; it still counts.
    assert second.n_pours == 1 and second.quality == "ok"
    assert second.pour_end_s == pytest.approx(70, abs=0.6)


def test_pour_until_departure_is_short_settle():
    signals = make_signals(50, dwells=[(2, 45)], pours=[(10, 44.6)])
    (event,) = detect_events(signals)
    assert event.quality == "short_settle"


def test_short_settle_still_picks_frames_before_departure():
    # Settled window ended before the last pour did (seen on video 5, vial 3).
    event = FillEvent(2, 75.7, 121.0, 3, 91.9, 119.7, None, 119.5, "short_settle", None)
    frames = pick_frames(event, n=5)
    assert frames
    assert all(round(119.7 * FPS) <= f <= round(120.8 * FPS) for f in frames)


def test_dwell_without_pour():
    signals = make_signals(50, dwells=[(2, 45)])
    (event,) = detect_events(signals)
    assert event.n_pours == 0 and event.quality == "no_pour_detected"
    assert pick_frames(event) == []


def test_dwell_at_video_end_is_noted():
    signals = make_signals(40, dwells=[(2, 45)], pours=[(10, 20)])
    (event,) = detect_events(signals)
    assert "video end" in event.detail


def test_pick_frames_stay_inside_settled_window():
    event = FillEvent(0, 2.0, 45.0, 1, 10.0, 31.0, 31.5, 44.8, "ok", None)
    frames = pick_frames(event, n=5)
    assert len(frames) == 5
    assert all(round(43.3 * FPS) <= f <= round(44.8 * FPS) for f in frames)


def test_match_labels():
    labels = pd.DataFrame({"vial": [1, 2], "recipe_id": [5, 5], "start_s": [0.0, 46.0], "end_s": [27.0, 73.0]})
    events = [
        FillEvent(0, 0, 28, 3, 1.0, 26.5, 27, 27.8, "ok", None),
        FillEvent(1, 29, 74, 3, 45.8, 72.2, 72.5, 74.3, "ok", None),
        FillEvent(2, 80, 120, 2, 90.0, 110.0, 111, 119, "ok", None),
        FillEvent(3, 121, 130, 0, None, None, None, None, "no_pour_detected", None),
    ]
    table = match_labels(events, labels).set_index("event_idx")

    assert table.loc[0, "vial_id"] == 1 and table.loc[1, "vial_id"] == 2
    assert table.loc[0, "start_offset_s"] == pytest.approx(1.0)
    assert table.loc[1, "end_offset_s"] == pytest.approx(-0.8)
    assert pd.isna(table.loc[2, "vial_id"]) and table.loc[2, "match_note"] == "no overlapping label window"
    assert pd.isna(table.loc[3, "vial_id"]) and table.loc[3, "match_note"] == "no pour"


def test_match_labels_refuses_a_vial_claimed_twice():
    labels = pd.DataFrame({"vial": [1], "recipe_id": [5], "start_s": [0.0], "end_s": [30.0]})
    events = [
        FillEvent(0, 0, 14, 1, 1.0, 10.0, 11, 13, "ok", None),
        FillEvent(1, 15, 30, 1, 16.0, 25.0, 26, 29, "ok", None),
    ]
    table = match_labels(events, labels)
    assert table["vial_id"].isna().all()
    assert (table["match_note"] == "several events overlap this vial's label window").all()


def test_stream_column_dev_sees_a_thin_stream():
    window = np.full((57, 35, 3), 160, dtype=np.uint8)
    assert stream_column_dev(window) < 1
    window[:, 17:19] = (200, 120, 20)
    assert stream_column_dev(window) > 20
    window[:] = 90  # uniform brightness change, no stream
    assert stream_column_dev(window) < 1


def poured(idx, n_pours=1):
    return FillEvent(idx, idx * 50.0, idx * 50.0 + 40, n_pours, idx * 50.0 + 10 if n_pours else None,
                     idx * 50.0 + 30 if n_pours else None, None, None, "ok" if n_pours else "no_pour_detected", None)


def test_load_run_plan_validates(tmp_path):
    good = tmp_path / "plan.csv"
    good.write_text("vial_order,recipe_id\n2,7\n1,5\n")
    plan = load_run_plan(good)
    assert plan["vial_order"].tolist() == [1, 2] and plan["recipe_id"].tolist() == [5, 7]

    for text in ("vial_order\n1\n", "vial_order,recipe_id\n1,\n", "vial_order,recipe_id\n1,5\n1,6\n",
                 "vial_order,recipe_id\n1,5.5\n"):
        bad = tmp_path / "bad.csv"
        bad.write_text(text)
        with pytest.raises(ValueError):
            load_run_plan(bad)


def test_assign_run_plan_by_fill_order_when_counts_match():
    plan = pd.DataFrame({"vial_order": [1, 2], "recipe_id": [5, 7]})
    table = assign_run_plan([poured(0), poured(1, n_pours=0), poured(2)], plan).set_index("event_idx")
    assert table.loc[0, "vial_id"] == 1 and table.loc[0, "recipe_id"] == 5
    assert table.loc[2, "vial_id"] == 2 and table.loc[2, "recipe_id"] == 7
    assert pd.isna(table.loc[1, "vial_id"]) and table.loc[1, "match_note"] == "no pour"


def test_assign_run_plan_refuses_to_shift_ids_on_a_missed_pour():
    # Four vials ran, but the pale second one was not detected: assigning by order would
    # label physical vials 3 and 4 as vials 2 and 3.
    plan = pd.DataFrame({"vial_order": [1, 2, 3, 4], "recipe_id": [5, 14, 6, 7]})
    table = assign_run_plan([poured(0), poured(1, n_pours=0), poured(2), poured(3)], plan)
    assert table["vial_id"].isna().all() and table["recipe_id"].isna().all()
    filled = table[table["event_idx"] != 1]
    assert filled["match_note"].str.contains("IDs not assigned").all()


def test_station_state():
    assert station_state(0.95, 10.0, 0.3, 4.0) == "moving"
    assert station_state(0.1, 0.2, 0.3, 4.0) == "no carrier"
    assert station_state(0.95, 0.2, 0.3, 80.0) == "pouring"
    assert station_state(0.95, 0.2, 4.0, 4.0) == "pouring"
    assert station_state(0.95, np.nan, np.nan, 4.0) == "parked, still"
