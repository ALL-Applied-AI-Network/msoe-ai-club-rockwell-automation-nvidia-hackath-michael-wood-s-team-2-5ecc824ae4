"""Study how lighting, reflections, and measurement choices move measured vial color.

Uses the settled frames from scripts/extract_vials.py (real line video: inspection and
evaluation only). Thresholds in vialcv were set on videos 1-4; video 5 is reported
separately as evaluation.

A. Frame-to-frame stability per vial event, for each measurement setting:
   rect_mean            mean RGB of the whole configured vial rectangle, then converted
                        (the cv/color-baseline method)
   segmented_mean       mean RGB of the liquid mask with glare pixels included
   segmented_median     per-pixel median Lab of the liquid mask, glare excluded
   segmented_median_wb  as above after white-patch correction
   and, on the backlit zone only, backlit_median and backlit_median_wb.
   The mask comes from the uncorrected frame and is the same for every setting.
   Spread = largest CIEDE2000 from any frame's color to the event's median color.
B. Backdrop drift: white-patch lightness over each video, from the sampled stills.
C. Same-recipe vials (video 5): CIEDE2000 between vial positions 1, 2, 3 of a recipe,
   measured in the same background zone, with and without white balance.
D. White-balance check on static surfaces: a metal rail left of the station (not part
   of the white reference) and a far part of the backdrop paper do not change between
   frames, so their color spread across frames, raw vs corrected, shows whether white
   balance removes lighting changes. (The puck face was tried first and rejected: liquid
   color reflects off the aluminum, so it differs per vial.)
E. Baseline comparison (video 5): the cv/color-baseline rectangle mean vs the zone
   median, on (1) the same-recipe pairs of C (first vial vs later vials, against vial 2
   vs vial 3), (2) the pre-pour empty-vial frames, where a measurement should report no
   liquid rather than a color, and (3) the share of the rectangle that is liquid.

Writes CSVs and plots to outputs/stability/ and prints markdown tables.
"""

import sys
import argparse
from itertools import combinations
from pathlib import Path

import cv2
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Allow running as `python scripts/stability_study.py` without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vialcv import dataset  # noqa: E402
from vialcv.colorstats import delta_e_2000, describe_color, rgb_to_hsv_lab  # noqa: E402
from vialcv.detect import detect_vial_color  # noqa: E402
from vialcv.measure import convert_mean_rgb  # noqa: E402
from vialcv.roi import crop, load_camera_config  # noqa: E402
from vialcv.segment import crop_zones, load_empty_profile, segment_liquid  # noqa: E402
from vialcv.whitebalance import white_balance  # noqa: E402

# Static surfaces (frame coordinates), clear of the station while a vial is settled.
STATIC_REGIONS = {"left_rail": (40, 330, 140, 20), "far_backdrop": (20, 90, 60, 90)}

SETTINGS = ["rect_mean", "segmented_mean", "segmented_median", "segmented_median_wb",
            "backlit_median", "backlit_median_wb"]
ZONE_PREFERENCE = ["backlit", "bore", "dark_background"]
MIN_ZONE_PIXELS = 200


def lab_of_mean(pixels_bgr: np.ndarray) -> list[float]:
    _, lab = convert_mean_rgb(pixels_bgr.reshape(-1, 3).astype(np.float64).mean(axis=0)[::-1].tolist())
    return [float(v) for v in lab]


def median_lab(image_bgr: np.ndarray, mask: np.ndarray) -> list[float] | None:
    described = describe_color(image_bgr, mask, MIN_ZONE_PIXELS)
    if not described["ok"]:
        return None
    return [described["lab"]["median"][k] for k in "Lab"]


def measure_frame(row, config, profile) -> dict | None:
    roi = tuple(int(v) for v in row.roi_xywh.strip("[]").split(","))
    frame = cv2.imread(row.frame_path)
    vial = crop(frame, roi)
    reference = crop(cv2.imread(row.reference_path), roi) if isinstance(row.reference_path, str) else None
    segmentation = segment_liquid(vial, reference, config.lines_y["puck_top"] - roi[1], profile,
                                  crop_zones(config, roi))
    if not segmentation.ok:
        return None

    corrected, balance = white_balance(frame, "white_patch", config)
    vial_wb = crop(corrected, roi)
    with_glare = segmentation.mask | segmentation.glare_mask
    backlit = segmentation.zone_masks["backlit"]

    record = {
        "rect_mean": lab_of_mean(vial),
        "segmented_mean": lab_of_mean(vial[with_glare]),
        "segmented_median": median_lab(vial, segmentation.mask),
        "segmented_median_wb": median_lab(vial_wb, segmentation.mask) if balance.ok else None,
        "backlit_median": median_lab(vial, backlit),
        "backlit_median_wb": median_lab(vial_wb, backlit) if balance.ok else None,
    }
    zone = next((z for z in ZONE_PREFERENCE if segmentation.zone_masks[z].sum() >= MIN_ZONE_PIXELS), None)
    record["zone"] = zone
    if zone:
        record["zone_median"] = median_lab(vial, segmentation.zone_masks[zone])
        record["zone_median_wb"] = median_lab(vial_wb, segmentation.zone_masks[zone]) if balance.ok else None
    record["glare_fraction"] = segmentation.glare_fraction
    record["liquid_fraction_of_rect"] = segmentation.mask_pixel_count / (roi[2] * roi[3])
    record["fill_state"] = segmentation.fill_state
    for name, region in STATIC_REGIONS.items():
        record[f"{name}_lab"] = lab_of_mean(crop(frame, region))
        record[f"{name}_lab_wb"] = lab_of_mean(crop(corrected, region)) if balance.ok else None
    return record


def static_object_spread(frames: pd.DataFrame) -> pd.DataFrame:
    """Per video and static surface: color spread across frames, raw vs white-balanced."""
    rows = []
    for (video_id, group), name in ((g, n) for g in frames.groupby("video_id") for n in STATIC_REGIONS):
        row = {"video_id": video_id, "surface": name, "n_frames": len(group)}
        for suffix, column in (("raw", f"{name}_lab"), ("wb", f"{name}_lab_wb")):
            labs = np.array([v for v in group[column] if v is not None])
            center = np.median(labs, axis=0)
            row[f"L_p95_minus_p5_{suffix}"] = float(np.percentile(labs[:, 0], 95) - np.percentile(labs[:, 0], 5))
            row[f"de00_median_{suffix}"] = float(np.median([delta_e_2000(lab, center) for lab in labs]))
        rows.append(row)
    return pd.DataFrame(rows)


def event_spreads(frames: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (video_id, event_idx), group in frames.groupby(["video_id", "event_idx"]):
        row = {"video_id": video_id, "event_idx": event_idx, "n_frames": len(group)}
        for setting in SETTINGS:
            labs = [v for v in group[setting] if v is not None]
            if len(labs) < 2:
                row[setting] = np.nan
                continue
            center = np.median(np.array(labs), axis=0)
            row[setting] = max(delta_e_2000(lab, center) for lab in labs)
        rows.append(row)
    return pd.DataFrame(rows)


def backdrop_drift(config, root) -> pd.DataFrame:
    index = dataset.load_image_index("vial_fill", root)
    rows = []
    for still in index[index["video_id"].notna()].itertuples():
        image = cv2.imread(str(dataset.image_path("vial_fill", still.filename, root)))
        patch = crop(image, config.region("white_reference")).reshape(-1, 3)
        _, lab = rgb_to_hsv_lab(np.median(patch, axis=0)[::-1][None].astype(np.float64))
        rows.append({"video_id": int(still.video_id), "timestamp": still.timestamp,
                     "L": lab[0, 0], "a": lab[0, 1], "b": lab[0, 2]})
    table = pd.DataFrame(rows)
    table["elapsed_s"] = table.groupby("video_id")["timestamp"].transform(lambda t: (t - t.min()).dt.total_seconds())
    return table


def recipe_positions(frames: pd.DataFrame, root) -> pd.DataFrame:
    """CIEDE2000 between same-recipe vial positions on video 5, in a shared zone."""
    labels = dataset.load_vial_recipes(root).set_index("vial")
    last = frames[frames["video_id"] == 5].sort_values("frame_index").groupby("event_idx").tail(1)
    last = last.dropna(subset=["vial_id"]).copy()
    last["vial_id"] = last["vial_id"].astype(int)
    last["recipe_id"] = last["vial_id"].map(labels["recipe_id"])
    last["position"] = last.groupby("recipe_id")["vial_id"].rank().astype(int)

    rows = []
    for recipe, group in last.groupby("recipe_id"):
        by_position = group.set_index("position")
        for first, second in combinations(sorted(by_position.index), 2):
            a, b = by_position.loc[first], by_position.loc[second]
            zone = next((z for z in ZONE_PREFERENCE if a["zone"] == z and b["zone"] == z), None)
            row = {"recipe_id": recipe, "pair": f"{first}-{second}", "zone": zone}
            for name, key in (("de00_raw", "zone_median"), ("de00_wb", "zone_median_wb")):
                ok = zone is not None and a[key] is not None and b[key] is not None
                row[name] = delta_e_2000(a[key], b[key]) if ok else np.nan
            row["de00_rect"] = delta_e_2000(a["rect_mean"], b["rect_mean"])
            rows.append(row)
    return pd.DataFrame(rows)


def baseline_separation(positions: pd.DataFrame) -> pd.DataFrame:
    """How far each method puts a recipe's first vial from its later vials, vs 2-3 noise."""
    shared = positions.dropna(subset=["de00_raw"])
    rows = []
    for method, column in (("rect_mean (baseline)", "de00_rect"), ("zone median", "de00_raw")):
        first = shared[shared["pair"] != "2-3"]
        later = shared[shared["pair"] == "2-3"].set_index("recipe_id")[column]
        per_recipe = first.groupby("recipe_id")[column].min()
        ratio = (per_recipe / later).dropna()
        rows.append({
            "method": method,
            "recipes": len(ratio),
            "first_vs_later_median": round(float(first[column].median()), 2),
            "vial2_vs_3_median": round(float(later.median()), 2),
            "ratio_median": round(float(ratio.median()), 1),
            "recipes_first_above_2_3": int((ratio > 1).sum()),
        })
    return pd.DataFrame(rows)


def empty_vial_check(manifest: pd.DataFrame, config) -> pd.DataFrame:
    """Measure each pre-pour empty-vial frame: the baseline always returns a color."""
    rows = []
    for path in manifest["reference_path"].dropna().unique():
        frame = cv2.imread(path)
        record = detect_vial_color(frame, config=config)
        rows.append({"reference_path": path, "detect_ok": record["quality"]["ok"],
                     "detect_code": record["quality"]["code"],
                     "rect_mean_lab": lab_of_mean(crop(frame, config.region("vial")))})
    return pd.DataFrame(rows)


def markdown(table: pd.DataFrame) -> str:
    header = "| " + " | ".join(map(str, table.columns)) + " |"
    divider = "| " + " | ".join("---" for _ in table.columns) + " |"
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in table.itertuples(index=False)]
    return "\n".join([header, divider, *body])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--vials-dir", type=Path, default=Path("outputs/vials"))
    parser.add_argument("--out", type=Path, default=Path("outputs/stability"))
    parser.add_argument("--dataset-root", help="Defaults to $DATASET_ROOT")
    args = parser.parse_args()

    config = load_camera_config("vial_fill")
    profile = load_empty_profile("vial_fill")
    args.out.mkdir(parents=True, exist_ok=True)

    records = []
    for video_id in args.videos:
        manifest = pd.read_csv(args.vials_dir / f"video{video_id}" / "manifest.csv")
        for row in manifest[manifest["locate_ok"]].itertuples():
            measured = measure_frame(row, config, profile)
            if measured is None:
                continue
            records.append({"video_id": video_id, "event_idx": row.event_idx, "frame_index": row.frame_index,
                            "vial_id": row.vial_id, "event_quality": row.event_quality, **measured})
    frames = pd.DataFrame(records)
    frames.to_csv(args.out / "frames.csv", index=False)

    # A. Frame-to-frame stability.
    spreads = event_spreads(frames)
    spreads["split"] = np.where(spreads["video_id"] == 5, "evaluation (video 5)", "calibration (videos 1-4)")
    spreads.to_csv(args.out / "event_spreads.csv", index=False)
    summary = (spreads.groupby("split")[SETTINGS]
               .agg(lambda s: f"{s.median():.2f} / {s.quantile(0.9):.2f} (n={s.notna().sum()})")
               .T.reset_index().rename(columns={"index": "setting"}))
    print("\nA. Within-event spread, max dE00 to event median: median / p90 (n events)\n")
    print(markdown(summary))

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.boxplot([spreads[s].dropna() for s in SETTINGS], showfliers=True)
    ax.set_xticks(range(1, len(SETTINGS) + 1), SETTINGS, rotation=20, ha="right")
    ax.set_ylabel("max dE00 to event median")
    ax.set_title("Frame-to-frame color spread within a settled vial (all videos)")
    fig.tight_layout()
    fig.savefig(args.out / "event_spreads.png", dpi=100)
    plt.close(fig)

    glare = frames.groupby(np.where(frames["video_id"] == 5, "video 5", "videos 1-4"))["glare_fraction"].describe()
    print("\nGlare fraction of liquid pixels:\n")
    print(markdown(glare[["count", "50%", "max"]].round(3).reset_index().rename(columns={"index": "split"})))

    # B. Backdrop drift.
    drift = backdrop_drift(config, args.dataset_root)
    drift.to_csv(args.out / "backdrop.csv", index=False)
    per_video = drift.groupby("video_id")["L"].agg(
        p5=lambda s: s.quantile(0.05), median="median", p95=lambda s: s.quantile(0.95)).round(1)
    per_video["p95_minus_p5"] = (per_video["p95"] - per_video["p5"]).round(1)
    print("\nB. White backdrop patch lightness L per video (stills):\n")
    print(markdown(per_video.reset_index()))

    fig, ax = plt.subplots(figsize=(9, 4))
    for video_id, group in drift.groupby("video_id"):
        ax.plot(group["elapsed_s"], group["L"], lw=0.8, label=f"video {video_id}")
    ax.set_xlabel("seconds since first still (wall clock)")
    ax.set_ylabel("backdrop patch L")
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.out / "backdrop_drift.png", dpi=100)
    plt.close(fig)

    # C. Same-recipe vial positions (video 5).
    if 5 in args.videos:
        positions = recipe_positions(frames, args.dataset_root)
        positions.to_csv(args.out / "recipe_positions.csv", index=False)
        print("\nC. Video 5 same-recipe dE00 between vial positions (shared zone):\n")
        print(markdown(positions.round(2)))
        pair_summary = positions.groupby("pair")[["de00_raw", "de00_wb"]].median().round(2).reset_index()
        print("\nMedian over recipes:\n")
        print(markdown(pair_summary))

    # D. Static-object white-balance check.
    static = static_object_spread(frames)
    static.to_csv(args.out / "static_object.csv", index=False)
    print("\nD. Static surface color across frames, raw vs white-balanced (dE00 to per-video median):\n")
    print(markdown(static.round(2)))

    # E. Baseline comparison (video 5).
    if 5 in args.videos:
        print("\nE. Baseline comparison, video 5 same-recipe pairs (recipes with a shared zone; "
              "ratio = smaller first-vial dE00 / vial 2-3 dE00, per recipe):\n")
        print(markdown(baseline_separation(positions)))

        empty = empty_vial_check(pd.read_csv(args.vials_dir / "video5" / "manifest.csv"), config)
        empty.to_csv(args.out / "empty_vial_check.csv", index=False)
        codes = empty["detect_code"].value_counts().to_dict()
        print(f"\nPre-pour empty-vial frames: {len(empty)}. detect_vial_color returned a color for "
              f"{int(empty['detect_ok'].sum())} (codes {codes}); rect_mean returned a color for all {len(empty)}.")

        fraction = frames.loc[frames["video_id"] == 5, "liquid_fraction_of_rect"]
        print(f"Liquid share of the vial rectangle (video 5 frames): median {fraction.median():.2f}, "
              f"min {fraction.min():.2f}, max {fraction.max():.2f}.")

    print(f"\nwrote {args.out.as_posix()}/ (frames.csv, event_spreads.csv, backdrop.csv, "
          "recipe_positions.csv, static_object.csv, empty_vial_check.csv, event_spreads.png, backdrop_drift.png)")


if __name__ == "__main__":
    main()
