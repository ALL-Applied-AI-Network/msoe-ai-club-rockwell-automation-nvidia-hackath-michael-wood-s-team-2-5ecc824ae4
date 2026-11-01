# CV results (snapshot for the final submission)

Selected outputs of the CV & Data pipeline, copied from `outputs/` (which stays out of git) for the presentation and for teammates. Generated on branch `cv/color-measurement`, Nov 1 2026.

**Data use.** Everything here is derived from Dataset 2 real line video (`data_origin: real_line`). It is for inspection and evaluation only, **not training data** ([docs/project-context.md](../docs/project-context.md)). Frames and videos from the dataset itself are not included, except the example images and the demo clip below.

| Folder | What | Made by |
| --- | --- | --- |
| `study/` | Lighting and baseline study: `report.md` (all tables, sections A-E), CSVs, and two plots. Explained in [docs/components/cv-lighting-study.md](../docs/components/cv-lighting-study.md). | `python scripts/stability_study.py` |
| `locate/` | Vial locator evaluation on the stills, videos 1-4 (calibration) and video 5 (evaluation). | `python scripts/evaluate_locate.py` |
| `vials/videoN/` | One measured-appearance record per filled vial (`records.json`, same as `records.jsonl`), plus `events.csv` (fill events) and `manifest.csv` (frames used). Record format: [docs/interfaces.md](../docs/interfaces.md) (proposed, not agreed). Frame paths in them point into `outputs/` and are not committed. | `python scripts/extract_vials.py` |
| `images/` | Slide images: `recipe7_first_vial_vs_next.png` (video 5, recipe 7: the first vial after the recipe change next to vials 2 and 3), `live_readout_flags.png` (the live panel with three first vials flagged), `detection_example.png` (vial region in yellow, detected fill line in red). | see below |
| `demo/` | `video5_demo_preview.mp4`: the first 6 min 20 s of video 5 replayed through the lab recorder, with the live readout panel (real speed; flags on vials 1, 4, and 7). `video5_demo_live.jsonl`: its live per-vial log. | see below |

Reproduce the demo clip (needs `$DATASET_ROOT` and a run plan made from `vial_fill/labels/video5_vial_recipes.csv`, columns `vial_order,recipe_id`):

```text
python scripts/lab_capture.py --source $DATASET_ROOT/vial_fill/videos/vial_fill_video_5.mp4 --name video5_demo --duration 380 --no-preview --save-preview --run-plan plan5.csv --data-origin real_line
```

Headline results in plain words (details in the study doc):

- Empty vials: the baseline (average color of a fixed rectangle) reported a color for 29 of 29 empty vials; our measurement said "no liquid" for all 29.
- Off-color first vials stand out about 35% more with our measurement than with the baseline, at the same vial-to-vial noise.
- Replaying video 5 live: all 30 vials found, 28 measured (2 too pale), and the first vial of 8 of 10 recipes flagged.
