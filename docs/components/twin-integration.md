# Digital Twin & Integration

Owner: **TBD** (2 people).

## Purpose and scope

Get the supplied CSI vial-line digital twin running in Isaac Sim if feasible, learn which visual parameters can actually be changed, export sample images, and put a thin dashboard/integration skeleton in place.

In scope: inspect twin files, run the provided render script, record capability gaps, optional dashboard.

Out of scope: assuming arbitrary recipe mixing or carryover in the twin; modeling tanks that are not in the asset; choosing Streamlit as a required stack; training on real images.

## Inputs

- Twin root `$DIGITAL_TWIN_ROOT` (package `csi_digital_twin_v1`).
- Isaac Sim install (twin README: tested with **Isaac Sim 6.0**).
- Camera JSON under `cameras/CapSealCam.json` and `cameras/FillCam.json`.
- Provided tools: `tools/render_example.py`, `tools/apply_lens.py`.

Keep the twin folder structure; USD files reference each other relatively.

## Outputs

- Rendered sample images (FillCam and/or CapSealCam) in an ignored `outputs/` directory.
- A short capability note: what changed in the render vs what the docs claim.
- Optional dashboard that can display an image path and, later, CV/recipe JSON. Streamlit is a **candidate**, not required.

Renders used as training images must set `data_origin: digital_twin` and `intended_use: train` in provenance ([interfaces.md](../interfaces.md)).

## Dependencies

- CV: can measure color on twin renders the same way as on real frames.
- Recipe: twin animation is not a recipe engine. Do not block recipe modeling on twin mixing.
- Compute: Isaac Sim on Brev or local GPU; stop Brev instances when idle ([compute guide](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Compute)).

## Verified twin capabilities (docs and files only)

Isaac Sim was **not** run for this documentation pass.

From twin README, USDA/JSON, and Dataset 2:

| Item | Evidence |
| --- | --- |
| Fill station + tray inspection station | Twin README |
| `FillCam` 640×480 pinhole | `cameras/FillCam.json` |
| `CapSealCam` 640×480 after 768×576 render + `apply_lens.py` | README + `CapSealCam.json` |
| Fill animation frames 1–686 at 30 fps | README; `fill_station.usda` visibility samples |
| Animation content: blue liquid, then clear; next cart moves in | Twin README |
| No physics | Twin README |
| Glass/liquid are material approximations | Twin README |
| Tanks not modeled | Dataset 2 page |
| No tank-level camera in the twin | Twin camera table vs dataset's `tank_level` |
| `render_example.py` headless PathTracing render | tool source |
| Synthetic class/instance attributes on some fill parts | Twin README |

`fill_station.usda` only overrides visibility for `Fill_dispensing_stream`, `Fill_liquid`, and a neighbor vial. Geometry and materials live in binary `*.usdc` files and were not inspected as authored color parameters.

## Documented gaps (do not assume)

- Arbitrary recipe volumes or tank colors.
- Carryover in a shared mixing path.
- Physically accurate liquid color.
- A `tank_level` viewpoint.
- Confirmed ability to vary lighting or fill height beyond the authored animation.
- Animation matching real dispense order: real video-5 order is T200 (orange) → T400 (blue) → T100 (clear); the twin README describes blue then clear. Whether orange is present in the animation is unverified.

Dataset 2 starter text says teams "can render new scenes with different fills, colors and lighting." That is organizer intent, not a verified feature of this asset. Treat it as a hypothesis for this workstream to test.

## Observable completion

- One successful FillCam render **or** a recorded failure with the exact command, Isaac Sim version, and error.
- A written list of parameters that were successfully changed vs not supported.
- Dashboard: optional; if started, it must run locally against a sample image path without requiring the twin to be open.

## Current evidence (repo)

No twin runner, dashboard, or synthetic-image exporter is in this Git repository.

## Next bounded milestone

Date: **TBD**.

Open `csi_line.usda` or `stations/fill_station/fill_station.usda` with Isaac Sim 6.0 and run `tools/render_example.py --camera FillCam --frame 686` to an `outputs/` path. Record success or the failure. Do not expand into a dashboard until that result exists.

## Data-use reminder

Twin images are the intended training source. Real line images remain inspect/eval. See [project-context.md](../project-context.md).
