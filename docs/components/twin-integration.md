# Digital Twin & Integration

Owner: **TBD** (2 people).

## Purpose and scope

Get the supplied CSI vial-line digital twin running in Isaac Sim if feasible, learn which visual parameters can actually be changed, export sample images, and put a thin dashboard/integration foundation in place.

In scope: inspect twin files, run the provided render script, record capability gaps, generate sample images when the twin allows it, basic dashboard.

Out of scope: assuming arbitrary recipe mixing or carryover in the twin; modeling tanks that are not in the asset; choosing Streamlit as a required stack; training on real images; extra dashboard product features (alerts, operator workflows, live line control).

## Inputs

- Twin root `$DIGITAL_TWIN_ROOT` (package `csi_digital_twin_v1`).
- Isaac Sim install (twin README: tested with **Isaac Sim 6.0**).
- Camera JSON under `cameras/CapSealCam.json` and `cameras/FillCam.json`.
- Provided tools: `tools/render_example.py`, `tools/apply_lens.py`.

Keep the twin folder structure; USD files reference each other relatively.

## Outputs

- Rendered sample images (FillCam and/or CapSealCam) in an ignored `outputs/` directory, when generation succeeds.
- Provenance on those images (source origin `digital_twin`; see [interfaces.md](../interfaces.md)).
- A capability note: what the twin actually rendered or changed vs what the docs claim, including limitations.
- A basic dashboard that displays sample imagery and component results (CV/recipe JSON when those exist). Streamlit is a **candidate**, not a required framework.

## Dependencies

- CV: can measure color on twin renders the same way as on real frames.
- Recipe: twin animation is not a recipe engine. Do not block recipe modeling on twin mixing.
- Compute: Isaac Sim on Brev or local GPU; stop Brev instances when idle ([compute guide](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Compute)).

## Current achievement (repo)

No twin runner, dashboard, or synthetic-image exporter is in this Git repository.

Isaac Sim was **not** run for this documentation pass. File-level inspection only:

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

## Initial milestone: feasibility investigation

Date: **TBD**.

Open `csi_line.usda` or `stations/fill_station/fill_station.usda` with Isaac Sim 6.0 and run `tools/render_example.py --camera FillCam --frame 686` to an `outputs/` path.

- **Success:** one reproducible FillCam (or CapSealCam) render command is recorded.
- **Blocked:** the same command, Isaac Sim version, and error are recorded.

A documented failed render **completes this feasibility investigation with a blocked outcome**. It does **not** complete synthetic-data generation.

## Remaining workstream deliverables

These remain incomplete until done. A blocked feasibility result does not satisfy them.

- **Successful, reproducible sample generation** from the supplied twin (command, version, output path). If the twin cannot produce usable images, say generation is blocked and list what was tried; do not mark this deliverable complete.
- **Provenance** on generated images (`digital_twin` origin; intended_use does not authorize misuse of real-line sources).
- **Documented capabilities and limitations** from what was actually run, not from unverified README claims alone.
- **Basic dashboard/integration foundation:** display sample imagery and available component results. Not optional. Not a new product surface. Streamlit is a candidate only.

If rendering is blocked, the dashboard can still show local sample imagery (including inspect-only real frames, labeled as such) and later CV/recipe outputs so integration work is not stuck behind Isaac Sim.

## Data-use reminder

Twin images are the intended training source. Real line images remain inspect/eval. See [project-context.md](../project-context.md).
