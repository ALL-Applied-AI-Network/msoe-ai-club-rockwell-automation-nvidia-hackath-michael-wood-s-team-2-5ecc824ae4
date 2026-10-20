# Team plan

Owners and dates below are **TBD** unless named. This is the team plan for ProcessDNA, not the official organizer team-plan form (due Wed Oct 14).

## Roster (unresolved)

The team was previously described as **eight people**. The workstreams below allocate **six**. Do not assign the remaining seats here.

| Role | People | Named |
| --- | --- | --- |
| Computer Vision & Data | 2 | Corbin; second person TBD |
| Recipe Modeling & Carryover | 2 | TBD |
| Digital Twin & Integration | 2 | TBD |
| Unallocated | unresolved | Do not invent names |

The UWM CSI event page describes teams of 4–5. This MSOE team's actual roster is not confirmed in the repository.

## How the pieces connect (team)

1. CV measures **camera appearance** of liquid in an image.
2. Recipe modeling estimates an **expected color** from recipe volumes, tank-color assumptions, and optionally a carryover term.
3. Twin/integration supplies synthetic images when the twin can, and a basic dashboard that displays sample imagery and component results.

Comparison and cause suggestions are follow-on work after those outputs exist. The proposed records are in [interfaces.md](interfaces.md) and are **not agreed**.

First integration milestone date: **TBD** (an earlier "next week" phrase had no calendar date).

Initial milestones (ROI measurement tool; twin feasibility render) are not the same as workstream completion. Details are in the component docs.

## Workstreams

### 1. Computer Vision & Data — 2 people

Owner: Corbin and TBD.

- Explore Dataset 2 videos and recipe labels (inspect only; see [project-context.md](project-context.md)).
- Extract useful frames and vial/liquid regions.
- Select liquid in the image (Python/OpenCV). A particular segmentation method is not required; a fixed ROI is acceptable if evaluation shows it reliably selects liquid.
- Measure RGB, HSV, and LAB.
- Investigate lighting, reflections, and reliability.

Goal: reusable code that accepts a vial image and returns liquid-color measurements.

Initial milestone: the manual/fixed-ROI tool on `cv/color-baseline`. Workstream completion is broader.

Details: [components/cv-data.md](components/cv-data.md).

### 2. Recipe Modeling & Carryover — 2 people

Owner: TBD.

- Understand tank colors, recipe volumes, and dispensing order from official labels.
- Investigate basic liquid color mixing **without** assuming linear RGB averaging is physically correct.
- Build a simple expected-color baseline from recipe information.
- Investigate previous-recipe residue and, if feasible, simulate carryover amounts.

Goal: recipe-to-estimated-color code, with a basic carryover model if feasible.

Details: [components/recipe-carryover.md](components/recipe-carryover.md).

### 3. Digital Twin & Integration — 2 people

Owner: TBD.

- Inspect the supplied twin and try running Isaac Sim.
- Determine which liquid-color, fill-level, and lighting changes are actually supported.
- Generate and export sample synthetic images when the twin allows it.
- Establish a basic dashboard/integration foundation that displays sample imagery and component results. Streamlit is a candidate only, not a required framework.

Goal: twin running and sample images if generation succeeds, plus a basic dashboard/integration foundation. A documented failed render completes a feasibility investigation with a blocked outcome; it does not complete synthetic-data generation. The dashboard remains a workstream deliverable, not an optional extra.

Details: [components/twin-integration.md](components/twin-integration.md).

## Official dates (not team milestones)

| When | What |
| --- | --- |
| Sun Nov 1, 11:59 PM CT | Final submission |
| Thu Nov 5 | Finals, including real-hardware demonstration |

## Out of scope for this plan

- Dataset 1 (final vial inspection) and Dataset 3 (FANUC grasping) as the primary product.
- Declaring a full architecture, mixing physics engine, or dashboard stack.
- Treating the original proposal, if recovered later, as implemented work.
