"""Tests for the staff-facing lab orchestration CLI."""

import csv
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import staff_lab


def valid_notes_text() -> str:
    return """# Session notes
- Run name: run1
- Original recording filename: run1.mp4
- Packaged recording filename: run1.mp4
- Camera/view confirmed as vial_fill: yes
- Wall-clock start/end, including timezone: 2026-10-30 12:00-12:10 America/Chicago
- Clock mode: dataset
- Run-plan filename: plan.csv
- Number of successful fills: 2
- T-100 contents/color: clear
- T-200 contents/color: orange
- T-400 contents/color: blue
- Operator/staff contact: UWM operator
- Backup location: approved shared drive
"""


def write_run(tmp_path: Path, recipes=(7, 7)):
    lab = tmp_path / "lab"
    vials = tmp_path / "vials"
    extracted = vials / "run1"
    lab.mkdir()
    extracted.mkdir(parents=True)
    plan = tmp_path / "plan.csv"
    staff_lab.make_plan(recipes, plan)

    (lab / "run1.mp4").write_bytes(b"raw-video")
    (lab / "run1_preview.mp4").write_bytes(b"preview-video")
    (lab / "run1_capture.json").write_text(
        json.dumps({"frames": 3, "written_fps": 30.0, "data_origin": "real_line"}),
        encoding="utf-8",
    )
    with (lab / "run1_frames.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame_index", "wall_time", "elapsed_s"])
        for i in range(3):
            writer.writerow([i, f"2026-10-30T12:00:0{i}.000", i / 30])
    live = [{"number": i + 1, "recipe_id": recipe} for i, recipe in enumerate(recipes)]
    (lab / "run1_live.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in live), encoding="utf-8"
    )

    pd.DataFrame(
        {"event_idx": range(len(recipes)), "n_pours": [1] * len(recipes)}
    ).to_csv(extracted / "events.csv", index=False)
    pd.DataFrame({"frame_index": [0], "video_s": [0.0]}).to_csv(
        extracted / "signals.csv", index=False
    )
    pd.DataFrame({"event_idx": range(len(recipes)), "frame_path": ["x"] * len(recipes)}).to_csv(
        extracted / "manifest.csv", index=False
    )
    records = [
        {
            "vial_id": i + 1,
            "recipe_id": recipe,
            "quality": {"ok": True},
            "provenance": {
                "data_origin": "derived",
                "sources": [{"ref": "run1.mp4", "data_origin": "real_line"}],
            },
        }
        for i, recipe in enumerate(recipes)
    ]
    (extracted / "records.json").write_text(json.dumps(records), encoding="utf-8")
    (extracted / "records.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in records), encoding="utf-8"
    )
    (extracted / "extraction.json").write_text(
        json.dumps({
            "data_origin": "real_line",
            "clock_mode": "dataset",
            "source_name": "run1.mp4",
            "run_plan": "plan.csv",
        }),
        encoding="utf-8",
    )
    return plan, lab, vials


def fake_video(path: Path):
    width = 970 if "preview" in path.name else 640
    return staff_lab.VideoInfo(path, width=width, height=480, fps=30.0, frames=3)


def test_make_plan_writes_exact_sequential_csv_and_refuses_overwrite(tmp_path):
    path = tmp_path / "plan.csv"
    table = staff_lab.make_plan([7, 7, 9], path)
    assert path.read_text(encoding="utf-8") == "vial_order,recipe_id\n1,7\n2,7\n3,9\n"
    assert table.to_dict("records") == [
        {"vial_order": 1, "recipe_id": 7},
        {"vial_order": 2, "recipe_id": 7},
        {"vial_order": 3, "recipe_id": 9},
    ]
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        staff_lab.make_plan([10], path)
    with pytest.raises(staff_lab.StaffLabError, match="positive whole number"):
        staff_lab.make_plan([0], tmp_path / "invalid.csv")


def test_verify_accepts_consistent_capture_plan_and_records(tmp_path, monkeypatch):
    plan, lab, vials = write_run(tmp_path)
    monkeypatch.setattr(staff_lab, "inspect_video", fake_video)
    result = staff_lab.verify_run("run1", plan, lab, vials)
    assert result.ok
    assert (result.plan_count, result.detected_count, result.record_count, result.measured_count) == (2, 2, 2, 2)
    assert result.errors == []


def test_verify_rejects_plan_and_detected_count_mismatch(tmp_path, monkeypatch):
    plan, lab, vials = write_run(tmp_path, recipes=(7, 7, 7))
    # Simulate extraction finding only two pours and writing two records.
    extracted = vials / "run1"
    pd.DataFrame({"event_idx": [0, 1], "n_pours": [1, 1]}).to_csv(
        extracted / "events.csv", index=False
    )
    records = [
        {
            "vial_id": i + 1,
            "recipe_id": 7,
            "quality": {"ok": True},
            "provenance": {
                "data_origin": "derived",
                "sources": [{"ref": "run1.mp4", "data_origin": "real_line"}],
            },
        }
        for i in range(2)
    ]
    (extracted / "records.json").write_text(json.dumps(records), encoding="utf-8")
    (extracted / "records.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in records), encoding="utf-8"
    )
    monkeypatch.setattr(staff_lab, "inspect_video", fake_video)
    result = staff_lab.verify_run("run1", plan, lab, vials)
    assert not result.ok
    assert any("plan has 3 vials" in error.lower() for error in result.errors)


def test_package_copies_required_artifacts_hashes_them_and_refuses_overwrite(tmp_path, monkeypatch):
    plan, lab, vials = write_run(tmp_path)
    notes = tmp_path / "notes.txt"
    notes.write_text(valid_notes_text(), encoding="utf-8")
    destination = tmp_path / "handoff" / "run1"
    monkeypatch.setattr(staff_lab, "inspect_video", fake_video)
    monkeypatch.setattr(staff_lab, "_git_revision", lambda: "verified-test-revision")

    result = staff_lab.package_run("run1", plan, notes, destination, lab, vials)
    assert result == destination.resolve()
    assert (result / "raw" / "run1.mp4").read_bytes() == b"raw-video"
    assert (result / "preview" / "run1_preview.mp4").read_bytes() == b"preview-video"
    assert (result / "plan" / "plan.csv").is_file()
    assert (result / "notes" / "notes.txt").is_file()
    assert (result / "metadata" / "source-revision.txt").read_text(encoding="utf-8") == (
        "verified-test-revision\n"
    )

    lines = (result / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 14
    for line in lines:
        expected, relative = line.split("  ", 1)
        assert hashlib.sha256((result / relative).read_bytes()).hexdigest() == expected

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        staff_lab.package_run("run1", plan, notes, destination, lab, vials)


def test_staff_file_verify_and_package_do_not_require_capture_sidecars(tmp_path, monkeypatch):
    plan, lab, vials = write_run(tmp_path)
    notes = tmp_path / "notes.md"
    notes.write_text(valid_notes_text(), encoding="utf-8")
    source = lab / "run1.mp4"
    monkeypatch.setattr(staff_lab, "inspect_video", fake_video)
    monkeypatch.setattr(staff_lab, "_git_revision", lambda: "verified-test-revision")

    result = staff_lab.verify_run("run1", plan, tmp_path / "unused-lab", vials, source)
    assert result.ok
    destination = tmp_path / "staff-file-handoff"
    staff_lab.package_run(
        "run1", plan, notes, destination, tmp_path / "unused-lab", vials, source
    )
    assert (destination / "raw" / "run1.mp4").is_file()
    assert not (destination / "preview").exists()
    assert (destination / "SHA256SUMS.txt").is_file()


def test_package_refuses_dirty_checkout(tmp_path, monkeypatch):
    def fake_check_output(command, **kwargs):
        if "status" in command:
            return " M scripts/staff_lab.py\n"
        return "abc123\n"

    monkeypatch.setattr(staff_lab.subprocess, "check_output", fake_check_output)
    with pytest.raises(staff_lab.StaffLabError, match="dirty checkout"):
        staff_lab._git_revision()


def test_blank_notes_template_is_not_packageable(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("# Session\n- Run name:\n- Clock mode: unknown\n", encoding="utf-8")
    with pytest.raises(staff_lab.StaffLabError, match="blank/missing required fields"):
        staff_lab.validate_notes(notes)


def test_package_rejects_notes_from_another_batch(tmp_path, monkeypatch):
    plan, lab, vials = write_run(tmp_path)
    notes = tmp_path / "notes.md"
    notes.write_text(
        valid_notes_text().replace("- Run name: run1", "- Run name: another-run"),
        encoding="utf-8",
    )
    monkeypatch.setattr(staff_lab, "inspect_video", fake_video)
    monkeypatch.setattr(staff_lab, "_git_revision", lambda: "verified-test-revision")
    with pytest.raises(staff_lab.StaffLabError, match="do not match packaged artifacts"):
        staff_lab.package_run("run1", plan, notes, tmp_path / "handoff", lab, vials)


def test_verify_rejects_non_real_line_record_provenance(tmp_path, monkeypatch):
    plan, lab, vials = write_run(tmp_path)
    path = vials / "run1" / "records.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    records[0]["provenance"]["sources"][0]["data_origin"] = "unknown"
    path.write_text(json.dumps(records), encoding="utf-8")
    (vials / "run1" / "records.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in records), encoding="utf-8"
    )
    monkeypatch.setattr(staff_lab, "inspect_video", fake_video)
    result = staff_lab.verify_run("run1", plan, lab, vials)
    assert not result.ok
    assert any("entirely from real_line" in error for error in result.errors)


def test_geometry_mismatch_requires_explicit_calibration_override(tmp_path, monkeypatch):
    plan, lab, vials = write_run(tmp_path)

    def wide_video(path):
        width = 1610 if "preview" in path.name else 1280
        return staff_lab.VideoInfo(path, width=width, height=720, fps=30.0, frames=3)

    monkeypatch.setattr(staff_lab, "inspect_video", wide_video)
    rejected = staff_lab.verify_run("run1", plan, lab, vials)
    accepted = staff_lab.verify_run(
        "run1", plan, lab, vials, allow_geometry_mismatch=True
    )
    assert not rejected.ok
    assert accepted.ok
    assert any("calibration-only override" in warning for warning in accepted.warnings)


def test_preflight_checks_config_writable_output_and_mp4_codec(tmp_path):
    ok, messages, warnings = staff_lab.run_preflight(tmp_path, dataset_root=tmp_path / "missing")
    assert ok
    assert any("MP4 codec:" in message for message in messages)
    assert any("Exact next commands:" in message for message in messages)
    assert any("does not contain videos.csv" in warning for warning in warnings)
    assert any("No run plan supplied" in warning for warning in warnings)
    assert "extract_vials.py" not in "\n".join(messages)


def test_preflight_rejects_missing_plan_and_secret_url(tmp_path):
    ok, messages, _ = staff_lab.run_preflight(tmp_path / "missing-plan", plan=tmp_path / "no.csv")
    assert not ok
    assert any("FAIL run plan" in message for message in messages)

    secret = "rtsp://user:password@example.invalid/stream?token=secret"
    ok, messages, _ = staff_lab.run_preflight(tmp_path / "secret", source=secret)
    combined = "\n".join(messages)
    assert not ok
    assert "password" not in combined
    assert "token=secret" not in combined
    assert "Credential-bearing" in combined


def test_stream_source_labels_do_not_retain_paths_or_tokens():
    assert staff_lab.safe_source_label("rtsp://camera.example/live/path") == "rtsp://camera.example"
    with pytest.raises(OSError, match="Credential-bearing"):
        staff_lab.validate_source("rtsp://user:password@camera.example/live?token=secret")


def test_staff_video_stems_with_spaces_are_supported_and_paths_are_rejected():
    assert staff_lab._safe_run_name("CSI batch 01") == "CSI batch 01"
    assert staff_lab._safe_run_name("batch.01") == "batch.01"
    with pytest.raises(staff_lab.StaffLabError, match="safe filename stem"):
        staff_lab._safe_run_name("../outside")
    with pytest.raises(staff_lab.StaffLabError, match="safe filename stem"):
        staff_lab._safe_run_name("NUL")
