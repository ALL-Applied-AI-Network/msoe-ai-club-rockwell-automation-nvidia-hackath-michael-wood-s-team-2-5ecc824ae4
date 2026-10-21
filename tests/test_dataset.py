"""Tests for dataset access, using a tiny synthetic dataset layout.

The last test checks the real dataset and runs only when DATASET_ROOT is set.
"""

import os

import cv2
import numpy as np
import pytest

from vialcv import dataset


@pytest.fixture
def fake_root(tmp_path):
    root = tmp_path / "csi-vial-fill-dataset"
    (root / "vial_fill" / "videos").mkdir(parents=True)
    (root / "vial_fill" / "labels").mkdir()
    (root / "cap_seal").mkdir()

    (root / "videos.csv").write_text(
        "video_id,duration_s,cameras,n_vials,labeled,notes\n"
        "5,1698,cap_seal;tank_level;vial_fill,30,vial_fill,the only labeled video\n"
    )
    (root / "cap_seal" / "image_index.csv").write_text(
        "filename,timestamp,video_id\n"
        "cap_seal_20260923_194709_622176.jpg,2026-09-23 19:47:09.622176,5\n"
        "cap_seal_20260922_175155_329384.jpg,2026-09-22 17:51:55.329384,unassigned\n"
    )
    (root / "vial_fill" / "labels" / "video5_frame_labels.csv").write_text(
        "filename,timestamp,video_s,in_fill,vial,recipe_id,type,t100_ml,t200_ml,t400_ml,"
        "total_ml,dispense_order,color_purpose\n"
        "vial_fill_20260923_194709_622176.jpg,2026-09-23 19:47:09.622176,-0.378,0,,,"
        "between_fills,,,,,,\n"
        "vial_fill_20260923_194711_630429.jpg,2026-09-23 19:47:11.630429,1.630,1,1,5,"
        "Triple,10,10,10,30,T200>T400>T100,mixed\n"
    )
    return root


def write_gray_video(path, levels, size=(32, 24)):
    """Write an MJPG video whose frame i is a solid gray of levels[i]."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, size)
    assert writer.isOpened()
    for level in levels:
        writer.write(np.full((size[1], size[0], 3), level, dtype=np.uint8))
    writer.release()


def test_dataset_root_from_env_and_argument(fake_root, monkeypatch):
    monkeypatch.setenv("DATASET_ROOT", str(fake_root))
    assert dataset.dataset_root() == fake_root
    assert dataset.dataset_root(fake_root) == fake_root


def test_dataset_root_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("DATASET_ROOT", raising=False)
    with pytest.raises(RuntimeError):
        dataset.dataset_root()
    with pytest.raises(FileNotFoundError):
        dataset.dataset_root(tmp_path)


def test_image_ref_is_dataset_relative(fake_root, tmp_path):
    path = fake_root / "vial_fill" / "images" / "x.jpg"
    assert dataset.image_ref(path, fake_root) == "vial_fill/images/x.jpg"
    with pytest.raises(ValueError):
        dataset.image_ref(tmp_path / "elsewhere.jpg", fake_root)


def test_video_path(fake_root):
    video = fake_root / "vial_fill" / "videos" / "vial_fill_video_5.mp4"
    video.touch()
    assert dataset.video_path("vial_fill", 5, fake_root) == video
    with pytest.raises(FileNotFoundError):
        dataset.video_path("vial_fill", 4, fake_root)
    with pytest.raises(ValueError):
        dataset.video_path("FillCam", 5, fake_root)


def test_load_image_index_marks_unassigned_as_missing(fake_root):
    index = dataset.load_image_index("cap_seal", fake_root)
    assert index["video_id"].iloc[0] == 5
    assert index["video_id"].isna().iloc[1]
    assert index["timestamp"].iloc[0].microsecond == 622176


def test_load_frame_labels_keeps_unknown_vials_missing(fake_root):
    labels = dataset.load_frame_labels(fake_root)
    assert labels["vial"].isna().iloc[0]
    assert labels["vial"].iloc[1] == 1
    assert labels["recipe_id"].iloc[1] == 5


def test_frame_time_conversion():
    assert dataset.frame_to_seconds(807) == pytest.approx(26.9)
    assert dataset.seconds_to_frame(26.894) == 807
    assert dataset.seconds_to_frame(dataset.frame_to_seconds(1386)) == 1386


def test_iter_frames_start_stop_step(tmp_path):
    path = tmp_path / "gray.avi"
    levels = [10 * i for i in range(20)]
    write_gray_video(path, levels)

    frames = list(dataset.iter_frames(path, start=3, stop=15, step=4))

    assert [index for index, _ in frames] == [3, 7, 11]
    for index, frame in frames:
        assert abs(float(frame.mean()) - levels[index]) < 3


def test_iter_frames_stops_at_end_of_video(tmp_path):
    path = tmp_path / "gray.avi"
    write_gray_video(path, [50] * 5)
    assert [index for index, _ in dataset.iter_frames(path, start=2)] == [2, 3, 4]


def test_iter_frames_rejects_bad_arguments(tmp_path):
    with pytest.raises(ValueError):
        next(dataset.iter_frames(tmp_path / "x.avi", step=0))
    with pytest.raises(OSError):
        next(dataset.iter_frames(tmp_path / "missing.avi"))


@pytest.mark.skipif(not os.environ.get("DATASET_ROOT"), reason="DATASET_ROOT not set")
def test_real_dataset_matches_readme():
    videos = dataset.load_videos()
    assert videos["video_id"].tolist() == [1, 2, 3, 4, 5]

    index = dataset.load_image_index("vial_fill")
    assert index["video_id"].value_counts().to_dict() == {5: 845, 1: 558, 4: 157, 3: 95, 2: 78}

    recipes = dataset.load_vial_recipes()
    assert len(recipes) == 30
    assert (recipes["start_frame"] == recipes["start_s"].map(dataset.seconds_to_frame)).all()

    frame_index, frame = next(dataset.iter_frames(dataset.video_path("vial_fill", 2), start=600))
    assert frame_index == 600
    assert frame.shape == (480, 640, 3)
