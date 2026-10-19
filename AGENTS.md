# Agent instructions (ProcessDNA)

This repository is the MSOE team project **ProcessDNA** for the Fall 2026 Rockwell Automation × NVIDIA Innovation Lab, Dataset 2: Fluid Mixing Station.

These instructions do not guarantee compliance. Teammate review is still required.

## Read first

1. This file.
2. [docs/project-context.md](docs/project-context.md) for official requirements, team decisions, source conflicts, and data-use rules.
3. Only the documents that match the assigned task:

| Task | Also read |
| --- | --- |
| Team planning, owners, milestones | [docs/team-plan.md](docs/team-plan.md) |
| Connecting workstreams or changing shared records | [docs/interfaces.md](docs/interfaces.md) |
| Images, color measurement, dataset exploration | [docs/components/cv-data.md](docs/components/cv-data.md) |
| Recipes, expected color, carryover | [docs/components/recipe-carryover.md](docs/components/recipe-carryover.md) |
| Isaac Sim, synthetic images, dashboard/integration | [docs/components/twin-integration.md](docs/components/twin-integration.md) |

Do not load every component document for a narrow change.

## Before editing

- Inspect existing code, docs, and nearby files. The CV baseline lives on `cv/color-baseline` (`scripts/measure_color.py`); it may not be on the current branch.
- Identify the assigned task and its completion condition from the user and the relevant component doc.
- Stay inside that task. Do not start another workstream when the assigned work is done.
- Keep machine-specific absolute paths out of shared files. Use placeholders such as `$DATASET_ROOT`.

## Data-use constraints

Follow [docs/project-context.md](docs/project-context.md). In short:

- Official Dataset 2 guidance: look at real line images, video, and labels to understand the station; **do not train models on them**. Generate training data from the supplied digital twin.
- Real data may be used for inspection and evaluation. Do not describe repeated tuning on real examples as independent evaluation.
- If official pages conflict, record the conflict instead of silently picking a side.
- Do not invent extra organizer restrictions.

## Working rules

- Surface unsupported assumptions instead of treating them as fact.
- Call out any change that affects another workstream or the proposed interface in [docs/interfaces.md](docs/interfaces.md). Do not silently treat that interface as agreed.
- Distinguish **measured camera appearance** from **expected mixture color**. Do not assume linear RGB averaging models liquid mixing.
- Do not assume the twin supports arbitrary mixing, carryover, tank rendering, or physically accurate liquid color. Verify against twin docs and observed behavior.
- Run verification appropriate to the change. Report what was actually run and the result. Do not claim a committed test suite unless one exists in the repository.
- Update the relevant docs when agreed scope or behavior changes.
- Do not commit datasets, model weights, secrets, or API keys.

## Git

- Do not run destructive Git operations (`reset --hard`, `push --force`, history rewrites) unless the user explicitly asks.
- Do not commit, push, or merge unless the user explicitly asks.
- Do not switch branches if that would discard or disrupt uncommitted work.
- Do not copy implementation from another branch into a documentation-only change, or documentation into an unrelated implementation change, unless asked.

## Stop

Stop after the assigned task. Leave remaining workstreams and follow-on cleanups for a later request.
