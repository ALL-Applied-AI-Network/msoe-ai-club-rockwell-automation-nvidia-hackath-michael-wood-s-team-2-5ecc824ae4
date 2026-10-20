# ProcessDNA project context

Status of statements in this file:

| Label | Meaning |
| --- | --- |
| **Official** | Organizer requirement or dataset/twin documentation. Cited. |
| **Team** | Confirmed ProcessDNA decision, not yet an organizer rule. |
| **Repo** | Observed in this Git repository. |
| **Proposed** | Design that is not agreed. |
| **Unknown / TBD** | Missing owner, date, roster, or capability. |

If sources conflict, this file records the conflict.

## Problem (team)

ProcessDNA connects camera observations with recipes and recipe sequence to detect fluid-mixing deviations and help explain possible causes, including carryover.

This is team intent. It is aligned with, but not a substitute for, the official Dataset 2 problem statement.

## Official Dataset 2 problem

Source: [Dataset 2: Fluid Mixing Station](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Fluid-Mixing).

Four tanks feed the vial filling station. During supplied data collection, T-300 was out of service. T-100 was labeled clear, T-200 orange, and T-400 blue. A recipe stores milliliters per tank, not the color currently in a tank. Fluids mix upstream of a single nozzle. Residual liquid from the previous recipe can carry into the next fill.

The assigned problem is to detect color or fill problems and, when possible, connect the camera evidence to recipe order, tank state, or carryover. Flagging that a vial looks unexpected is not enough.

Official Dataset 2 process note: when the recipe changes, the first vial of the new batch may be discolored; the second and third vials of a three-vial batch are described as flushing that residue, and the last vial of each recipe is described as a reliable example of that recipe's true color. That is organizer process description, not a measurement this repo has verified.

## Competition constraints (official)

### Dataset choice

This team is using **Dataset 2: Fluid Mixing Station** (also called Fluid Mixing Station 3 in the event README). Organizers recommend focusing on one dataset. That is a recommendation, not a requirement ([event guide](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026)).

### Training versus real line data

Event guide:

> The real data from the line is there to look at, not to train on: teams generate their training data with the digital twins, as a high-mix, low-volume line would have to. Each dataset page explains why.

Dataset 2 page:

> The real images, video, and labels come from the line. Look through them to understand the station, the recipes, and what your generated data needs to match, but avoid training your models on them. The goal of this lab is to generate your training data with the digital twin.

Dataset 2 also says unlabeled real videos and extra camera views can be labeled **to check a model against**, and that organizers may release a held-out real set for testing if there is interest.

Do not treat repeated tuning on real examples as independent evaluation.

**Team constraint:** model-training data comes from the supplied digital twin. Real production data is for inspection and evaluation, not model training.

### Related official wording: synthetic vs real training comparisons

The general [Collect and test your own data](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Data-Collection) guide (verified 2026-10-19) also says:

> When using generated data, keep its source and generation settings. Compare performance on real-only, synthetic-only, and combined training data. A synthetic improvement counts only if it carries over to held-out real examples.

That sentence is official and is not the same instruction as Dataset 2 / the event guide. It does **not** authorize training on Dataset 2's supplied production images. How far it applies to other data (for example newly collected line data) is **not decided here**. Do not treat the two pages as silently reconciled.

ProcessDNA keeps the team constraint above unless organizers give Dataset 2-specific clarification.

### Final submission and hardware demo (official)

Verified from the [event guide](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026) (2026-10-19):

- Final project due **Sun Nov 1, 11:59 PM CT**.
- Each team submits: a video of about five minutes; a one-page project summary; a link to the team repository; references and credits for data, models, code, and tools.
- Under **What judges expect**, the video, summary, and finals presentation should **demonstrate the solution operating on real hardware, either the UWM CSI production line or the FANUC robotic arm**, identify a specific problem, explain impact for other manufacturers, and show measured results against a baseline.
- Dataset 2 uses the vial line, not the standalone FANUC cell.
- Finals: **Thu Nov 5**, MSOE Diercks Hall, 5:00–8:00 PM, including live presentations.
- Detailed judging criteria, category weights, and award categories are still being finalized.

Live-line tests must be scheduled. Teams may not reconfigure cameras, PLCs, recipes, or safety systems without approval ([data collection guide](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Data-Collection)).

### Operating limits on the real station (official Dataset 2)

- Vial total ≤ 80 mL.
- Do not use less than 10 mL of a selected component in practice.
- Do not put more than 50 mL from T-200 in a recipe.
- Do not use T-300.
- Do not change recipes without plant-manager guidance.

## Confirmed team decisions

- Project name: ProcessDNA.
- Dataset: Dataset 2 only, for now.
- Goal: connect measured image color, estimated recipe color, and process context. Broader comparison and carryover explanations come after those pieces work.
- Workstreams: Computer Vision & Data; Recipe Modeling & Carryover; Digital Twin & Integration. See [team-plan.md](team-plan.md).
- A basic dashboard/integration foundation is a Digital Twin & Integration deliverable (sample imagery and component results). Streamlit is a **candidate** framework, not a required dependency. Making the dashboard optional would be a proposed scope change and needs team agreement.
- Shared records in [interfaces.md](interfaces.md) are **proposed**, not agreed.

## Supplied assets

Keep large data and twins **outside git**. Configure local paths privately. Example:

```text
DATASET_ROOT=/path/to/csi-vial-fill-dataset
DIGITAL_TWIN_ROOT=/path/to/csi_digital_twin_v1
```

Official copies:

- Fluid Mixing dataset: <https://drive.google.com/drive/folders/1qwV2BEz3ODX17kwNCr9M15DfkY8U_blQ?usp=sharing>
- Digital twin (datasets 1 and 2): <https://drive.google.com/file/d/1nXRN_VZ_DKGS33jtELwn6z8WR8dbQfKe/view?usp=sharing>
- Parent data folder: <https://drive.google.com/drive/folders/1GWuHV2WUNLztq_Fga6xBH7qFzhxDaac8?usp=sharing>

### Real dataset (from its README and labels)

Package name: `csi-vial-fill-dataset`. Three synchronized cameras at 640×480: `vial_fill`, `tank_level`, `cap_seal`. Five video IDs. Only video 5 / `vial_fill` is labeled (30 vials, recipes 5–14, 3 vials each). T-300 unused. Dispense order is T200 → T400 → T100, skipping unused tanks.

Authoritative per-vial table: `vial_fill/labels/video5_vial_recipes.csv` (and `.json`). Frame mapping: `video5_frame_labels.csv`.

### Digital twin (from its README and Dataset 2)

Package inspected: `csi_digital_twin_v1`. OpenUSD for Isaac Sim (tested with Isaac Sim 6.0). Stations: tray inspection (cap-seal camera) and fill (FillCam plus a pre-recorded fill animation). **No physics.** Glass and liquid materials are approximations. Dataset 2 states **tanks are not modeled**. Official cameras: `CapSealCam` and `FillCam` at 640×480. There is **no tank-level camera** in the supplied twin docs.

Fill animation: time codes 1–686 at 30 fps; twin README describes blue liquid filling, then clear liquid added, while the next cart moves in. That is a fixed authored sequence, not evidence that arbitrary recipes, colors, or carryover can be simulated.

## Implementation status (repo)

`main` currently contains the organizer README only.

Branch `cv/color-baseline` adds `scripts/measure_color.py`, `requirements.txt`, and a `.gitignore`. That script is the **initial CV baseline** (manual or fixed rectangle). It is not workstream completion. No committed automated test suite was found. Details: [components/cv-data.md](components/cv-data.md).

No recipe model, twin runner, synthetic-image exporter, or dashboard code is in the repository. Twin file inspection is documented; Isaac Sim has not been run from this repo. A later failed render would complete a feasibility investigation only, not synthetic-data generation. Details: [components/twin-integration.md](components/twin-integration.md).

## Unknowns

- Full roster size (see [team-plan.md](team-plan.md)).
- Owners other than Corbin on Computer Vision & Data.
- Date for the first integration milestone (previously described as "next week"; **TBD**).
- Whether organizers will release a held-out real test set.
- Which twin parameters (liquid color, fill level, lighting) can actually be changed. Not verified here; Isaac Sim was not run for this documentation pass.

## Sources

| Source | Use |
| --- | --- |
| [Event guide](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026) | Rules, dates, judging expectations, training-data sentence |
| [Dataset 2](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Fluid-Mixing) | Problem, carryover description, data-use, starter ideas |
| [Data collection](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Data-Collection) | CSI visit/test rules; general synthetic vs real training-comparison sentence |
| [Compute](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Compute) | Brev / Spark / CSI workstation |
| [Tools and resources](https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Resources) | Optional tools; not required architecture |
| Dataset `README.md` and label files | Camera layout, recipes, timestamps |
| Twin `README.md`, `cameras/*.json`, `tools/render_example.py` | Verified twin contents |
| Team statements in this documentation effort | ProcessDNA intent and workstreams |
| Git branch `cv/color-baseline` | Current CV baseline |

No original written proposal file was found in the repository. Treat any earlier proposal as an idea document, not proof of implementation.
