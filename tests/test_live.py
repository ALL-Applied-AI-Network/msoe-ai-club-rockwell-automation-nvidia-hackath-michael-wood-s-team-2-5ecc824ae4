"""Tests for the live per-vial reader on synthetic signal sequences (no images needed)."""

import numpy as np
import pandas as pd
import pytest

from vialcv.live import LiveVialReader, compare_records

RATE = 15.0  # samples per second (30 fps, every 2nd frame)

AWAY = (0.0, 0.5, 0.5, 5.0)  # collar_dark, station_motion, vial_change, stream_column_dev
PARKED = (1.0, 0.5, 0.5, 5.0)
POURING = (1.0, 0.5, 3.0, 30.0)


def cycle(parked_s=3.0, pour_s=2.0, settle_s=3.0, away_s=1.5):
    return [(AWAY, away_s), (PARKED, parked_s), (POURING, pour_s), (PARKED, settle_s)]


def backlit_record(L):
    zone = {"ok": True, "lab": {"median": {"L": L, "a": 0.0, "b": -20.0}},
            "rgb_0_255": {"median": [0, 80, 110]}}
    return {"quality": {"ok": True, "code": None}, "fill": {"state": "in_view"},
            "color": {"primary_zone": "backlit", "primary": zone, "zones": {"backlit": zone}}}


def run(segments, lightness, plan=None, end_away=True):
    """Feed segments of (signals, seconds); frames are stamped with their time."""
    calls = []

    def measure(frame, reference, t):
        calls.append({"t": t, "frame_t": float(frame[0, 0]),
                      "reference_t": None if reference is None else float(reference[0, 0])})
        return backlit_record(lightness[len(reader.vials) - 1])

    reader = LiveVialReader(measure, RATE, plan)
    t = 0.0
    states = []
    for signals, seconds in segments + ([(AWAY, 1.5)] if end_away else []):
        for _ in range(int(seconds * RATE)):
            states.append(reader.update(t, np.full((2, 2), t), signals))
            t += 1 / RATE
    reader.close(t)
    return reader, calls, states


def test_one_vial_is_measured_after_settling_with_a_pre_pour_reference():
    reader, calls, states = run(cycle(), [40.0])
    assert len(reader.vials) == 1
    vial = reader.vials[0]
    assert vial.status == "final" and vial.ok
    # First pour at 1.5 (away) + 3.0 (parked) = 4.5 s; reference midway in [2.5+0.5... ] window.
    assert vial.first_pour_s == pytest.approx(4.5, abs=0.1)
    reference_t = calls[0]["reference_t"]
    assert 1.5 + 1.5 <= reference_t <= 4.5 - 0.5
    # Measured only once settled (>= 0.5 s after the pour), and re-measured while settled.
    assert calls[0]["t"] >= 6.5 + 0.5 - 0.1
    assert len(calls) >= 2
    assert "pouring" in states and "settled, measured" in states
    assert reader.pop_finished() == [vial]


def test_dwell_without_pour_is_not_a_vial():
    reader, calls, _ = run([(AWAY, 1.0), (PARKED, 6.0)], [])
    assert reader.vials == [] and calls == []


def test_short_pour_blip_is_ignored():
    reader, _, _ = run([(AWAY, 1.0), (PARKED, 3.0), (POURING, 0.2), (PARKED, 3.0)], [])
    assert reader.vials == []


def test_arriving_carrier_change_is_not_a_pour():
    # The change signal lags, so it stays high just past the arrival-ignore window.
    arriving = (1.0, 0.5, 3.0, 5.0)
    reader, _, _ = run([(AWAY, 1.0), (arriving, 1.4), (PARKED, 4.0)], [])
    assert reader.vials == []


def test_no_reference_when_pour_starts_right_after_arrival():
    reader, calls, _ = run(cycle(parked_s=1.2), [40.0])
    assert calls[0]["reference_t"] is None
    assert "no empty reference before the first pour" in reader.vials[0].notes


def test_pour_until_departure_is_measured_on_last_parked_frame():
    reader, calls, _ = run([(AWAY, 1.0), (PARKED, 3.0), (POURING, 2.0)], [40.0])
    vial = reader.vials[0]
    assert vial.status == "final" and len(calls) == 1
    assert any(note.startswith("short_settle") for note in vial.notes)


def test_run_plan_assigns_recipes_and_flags_an_off_first_vial():
    plan = pd.DataFrame({"vial_order": [1, 2, 3, 4], "recipe_id": [7, 7, 8, 8]})
    # Recipe 7: vials agree. Recipe 8: the first vial is 12 L off the second.
    reader, _, _ = run(cycle() * 4, [40.0, 40.5, 52.0, 40.0], plan)
    vials = reader.vials
    assert [v.recipe_id for v in vials] == [7, 7, 8, 8]
    assert [v.position_in_recipe for v in vials] == [1, 2, 1, 2]
    assert vials[0].flag is None
    assert vials[2].flag is not None and "recipe 8" in vials[2].flag
    assert vials[1].compare["to_live_vial"] == 1 and vials[1].compare["de00"] < 1
    assert vials[3].compare["zone"] == "backlit" and vials[3].compare["de00"] > 5


def test_failed_remeasurement_clears_a_stale_flag():
    plan = pd.DataFrame({"vial_order": [1, 2], "recipe_id": [8, 8]})
    second_vial_calls = []

    def measure(frame, reference, t):
        if len(reader.vials) == 1:
            return backlit_record(52.0)
        second_vial_calls.append(t)  # first measurement differs (flags vial 1), later ones fail
        if len(second_vial_calls) == 1:
            return backlit_record(40.0)
        return {"quality": {"ok": False, "code": "low_contrast"}, "color": None}

    reader = LiveVialReader(measure, RATE, plan)
    t = 0.0
    for signals, seconds in cycle() * 2 + [(AWAY, 1.5)]:
        for _ in range(int(seconds * RATE)):
            reader.update(t, np.zeros((2, 2)), signals)
            t += 1 / RATE
    first, second = reader.vials
    assert len(second_vial_calls) >= 2 and not second.ok
    assert first.flag is None and second.compare is None


def test_vials_beyond_the_plan_have_no_recipe():
    plan = pd.DataFrame({"vial_order": [1], "recipe_id": [7]})
    reader, _, _ = run(cycle() * 2, [40.0, 40.0], plan)
    assert reader.vials[1].recipe_id is None
    assert any("beyond the run plan" in note for note in reader.vials[1].notes)


def test_without_a_plan_nothing_is_compared_or_flagged():
    reader, _, _ = run(cycle() * 2, [40.0, 60.0])
    assert all(v.recipe_id is None and v.compare is None and v.flag is None for v in reader.vials)


def test_stream_end_finishes_the_current_vial():
    reader, _, _ = run(cycle(), [40.0], end_away=False)
    assert reader.vials[0].status == "final"
    assert "stream ended before the carrier left" in reader.vials[0].notes


def test_compare_records_needs_a_shared_zone():
    a, b = backlit_record(40.0), backlit_record(40.0)
    assert compare_records(a, b) == {"zone": "backlit", "de00": 0.0}
    b["color"]["zones"] = {"bore": b["color"]["zones"]["backlit"]}
    assert compare_records(a, b) == {"zone": None, "de00": None}
