# UWM staff-agent runbook: `vial_fill` capture and return

This runbook is for a UWM staff member or a coding agent operating on their behalf during an authorized CSI vial-line session. Its goal is to return an untouched `vial_fill` recording, the exact run context, and reproducible per-vial records without changing the production line or losing provenance.

Use this together with [cv-lab-runbook.md](cv-lab-runbook.md). The commands below use PowerShell and Windows paths because the capture code selects the Windows DirectShow camera backend. The Python scripts also run on Linux when OpenCV can open the source.

## Completion conditions

A session is complete only when all of the following are true:

1. The source revision and command history are recorded.
2. Every batch has an exact recipe plan and wall-clock start/end notes.
3. The original recording is retained unchanged.
4. Detected-pour count is compared with the number of vials that actually ran.
5. `records.jsonl` exists, or the processing failure and raw recording are returned together.
6. The return package contains SHA-256 checksums and has a second copy on approved storage.

Do not delay or endanger line operations to make the detector pass. A preserved raw recording with good metadata is more valuable than an on-site threshold change.

## Safety and data boundaries

- Run only during a scheduled, staff-authorized line session. The plant manager/operator controls the equipment.
- Do not modify cameras, PLCs, recipes, network settings, safety systems, guards, lighting, or the backdrop without explicit staff approval. Ask staff to make any approved equipment change.
- Dataset 2 operating limits are: total vial volume at most 80 mL; at least 10 mL of every selected component; at most 50 mL from T-200; do not use T-300. Recipe changes require plant-manager guidance.
- The repository code captures and analyzes camera frames. It must not be connected to a PLC or used to control the line.
- Real-line video and derived records are for inspection, calibration, evaluation, and demonstration under the team's current constraint. Do not use them for model training.
- Keep recordings, images, notes containing operational details, credentials, and checksums out of Git. The repository ignores `outputs/`; keep all session files there.
- A red first-vial flag means that two measured camera appearances differ. It is not proof of carryover or a root-cause diagnosis.
- Stop when staff asks, when a safety procedure requires it, or when storage/power is at risk. Preserve partial recordings rather than attempting a risky recovery.

## 1. Obtain the correct branch from the team repository

The GitHub fork or clone may contain only `main`. The verified staff package lives on the upstream release branch and immutable tag below. Do not run an arbitrary development branch during the lab.

```text
release branch: release/uwm-lab-2026-10-30
verified tag:   uwm-lab-2026-10-30-v1
```

Team upstream:

```text
https://github.com/ALL-Applied-AI-Network/msoe-ai-club-rockwell-automation-nvidia-hackath-michael-wood-s-team-2-5ecc824ae4.git
```

From a fresh clone of the staff fork:

```powershell
git clone <staff-fork-url> processdna-lab
Set-Location processdna-lab
git remote -v
git remote add upstream https://github.com/ALL-Applied-AI-Network/msoe-ai-club-rockwell-automation-nvidia-hackath-michael-wood-s-team-2-5ecc824ae4.git
git fetch --prune --tags upstream
git switch --create staff/uwm-lab --track upstream/release/uwm-lab-2026-10-30
```

If `upstream` already exists, verify its URL instead of adding it again:

```powershell
git remote get-url upstream
git fetch --prune --tags upstream
```

If `staff/uwm-lab` already exists and has no local work to preserve:

```powershell
git switch staff/uwm-lab
git merge --ff-only upstream/release/uwm-lab-2026-10-30
```

If the existing checkout is dirty, do not reset it. Create a separate worktree:

```powershell
git fetch --prune --tags upstream
git worktree add --detach ..\processdna-uwm-lab uwm-lab-2026-10-30-v1
Set-Location ..\processdna-uwm-lab
```

Record and verify the exact source before setup:

```powershell
git status --short --branch
git rev-parse HEAD
git rev-list -n 1 uwm-lab-2026-10-30-v1
git log -1 --date=iso-strict --format="%H %ad %an %s"
Test-Path scripts\lab_check.py
Test-Path scripts\lab_capture.py
Test-Path scripts\extract_vials.py
Test-Path scripts\staff_lab.py
```

All four `Test-Path` commands must print `True`. The two revision commands must print the same SHA. If they differ, switch to the verified tag or stop and contact the team. Do not merge another branch, rewrite history, or copy files from an old worktree during the lab.

If the branch cannot be fetched, stop Git troubleshooting after confirming the URL and access. Ask the team for repository access or a verified archive containing the source revision. Do not reconstruct the capture scripts by hand.

## 2. Create and verify the Python environment

Python 3.12 or newer is required by the pinned dependencies.

```powershell
py -3.12 -m venv .venv
$py = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements-dev.txt
& $py --version
& $py -c "import cv2, numpy, pandas, skimage; print('OpenCV', cv2.__version__)"
& $py -m pytest -q
& $py scripts\staff_lab.py --help
& $py scripts\staff_lab.py preflight --output-root outputs --name uwm_20261030_batch01
```

Require zero test failures and `PREFLIGHT OK`. The preflight checks the bundled camera configuration, output permissions, free storage, and MP4 write/read support without controlling line equipment. Record the test count and source revision in the session notes.

This explicit interpreter path works even when PowerShell execution policy blocks `Activate.ps1`. Later commands use `python` for readability: either activate this same `.venv`, or replace `python` with `& $py` in every command. Never continue with an unverified system Python.

Verify wall-clock provenance before capture:

```powershell
Get-Date -Format o
Get-TimeZone
w32tm /query /status
```

The workstation must show Central Time (`UTC-6` or `UTC-5` depending on daylight saving) and a synchronized clock. If Windows Time status is unavailable, compare against a staff-approved synchronized clock and record that comparison in the notes.

The supplied dataset is optional for recording but enables the camera-shift comparison. When an approved local copy is present:

```powershell
$env:DATASET_ROOT = '<path-to-csi-vial-fill-dataset>'
Test-Path (Join-Path $env:DATASET_ROOT 'videos.csv')
```

The final command must print `True`. Do not copy the dataset into the repository.

Before connecting to the line, plug into AC power, confirm at least 5 GB of free space, disable automatic sleep for the duration of the authorized session, and confirm that Windows camera privacy settings permit the Python process to use the camera. Restore normal power settings after the session.

## 3. Create one run plan and notes file per batch

Ask the operator, before the batch starts:

- Which recipes will run, in exact vial fill order?
- What is currently in T-100, T-200, and T-400, and what color does each tank appear?
- Were there aborted fills, carriers with no pour, extra vials, or recipe changes?
- Has the `vial_fill` camera, lighting, or backdrop changed since the supplied recordings?
- May the team film the physical line and tank view for the demonstration?

Use a unique session and batch name containing the local date, for example `uwm_20261030_batch01`. Create the notes from the committed template, then generate the plan from the operator-confirmed recipe sequence:

```powershell
New-Item -ItemType Directory -Force outputs\lab | Out-Null
Copy-Item configs\lab\staff_session.template.md outputs\lab\uwm_20261030_batch01_notes.md
python scripts\staff_lab.py make-plan 7 7 7 8 8 8 `
  --output outputs\lab\uwm_20261030_batch01_plan.csv
```

The recipe IDs above are an example only. Replace them with the complete physical fill order. `staff_lab.py` refuses to overwrite an existing plan.

The plan stays under ignored output storage:

```text
outputs/lab/uwm_20261030_batch01_plan.csv
```

The CSV has exactly two columns. `vial_order` is one-based physical fill order, not a frame number:

```csv
vial_order,recipe_id
1,7
2,7
3,7
4,8
5,8
6,8
```

Requirements:

- Use one row per vial that is planned to receive a fill in this batch.
- Use whole-number recipe IDs supplied by the operator.
- Use unique, contiguous `vial_order` values from 1 through N.
- Do not reuse a plan for a batch with a different sequence.
- Record aborted/no-pour carriers and unexpected extra fills separately in the notes.

Create `outputs/lab/uwm_20261030_batch01_notes.md` and record at minimum:

- operator/staff contact;
- source revision (`git rev-parse HEAD`);
- wall-clock start/end with `America/Chicago` / CT noted;
- camera/source identifier and resolution;
- planned and actual vial counts;
- exact recipe sequence and any mid-run change;
- current tank contents/colors;
- camera, lighting, and backdrop observations;
- warnings, interruptions, dropped frames, or unusual line behavior;
- phone/demo footage names;
- original recording name, exact packaged/working-copy filename, backup location, and later checksum.

## 4. Select the source correctly

`scripts/lab_check.py` and `scripts/lab_capture.py` accept these source forms:

- USB/local camera: a numeric index such as `0`, `1`, or `2`;
- network camera/approved stream: its URL;
- existing video: a file path.

The tools reject stream URLs containing user-info credentials, query tokens, or fragments because the source is referenced in logs and metadata. Use a credential-free local alias or camera index supplied by staff. Do not work around this guard by embedding a secret in a path.

For a live camera, enumerate indexes 0 through 5:

```powershell
python scripts\lab_check.py --list-cameras
```

Open `outputs/lab_check/camera_<N>.png`. The laptop webcam is often index 0; use the numeric index that actually shows the `vial_fill` station. If the approved camera uses a higher index, try it directly with `--source <number>` because enumeration stops at 5.

For a staff-provided recording, do not pass it through `lab_capture.py`; that would create an unnecessary re-encoded copy. Preserve and process the original directly as described in [Staff-provided file intake](#staff-provided-file-intake).

## 5. Preflight a live camera or stream

With a vial parked at the station:

```powershell
python scripts\staff_lab.py preflight `
  --source <camera-index-or-stream-url> `
  --output-root outputs `
  --name uwm_20261030_batch01 `
  --plan outputs\lab\uwm_20261030_batch01_plan.csv

python scripts\lab_check.py --source <camera-index-or-stream-url> --frames 5
```

Require `PREFLIGHT OK` before the production run. The command validates the run plan and prints the exact check, test-capture, production-capture, extraction, and verification commands for the selected source.

If the only hard failure is non-640x480 geometry and staff explicitly authorizes recording unchanged, rerun with `--allow-geometry-mismatch`, record the warning, and classify the run as calibration-only. The detector is not expected to measure correctly until a matching camera configuration is created.

Expected geometry is 640 x 480. Interpret the verdict carefully:

- `READY`: size, camera alignment, and a parked vial passed.
- `READY (camera shift NOT checked)`: `DATASET_ROOT` was unavailable; inspect the saved overlay manually.
- `NOT READY` with no parked vial: rerun while a vial is stationary. An empty or moving station is not automatically a camera failure.
- Size or camera-shift failure: record anyway if staff approves. Note that the recording is calibration material; use a separate run for evaluation after geometry is repaired.

Make a 25-second codec and throughput test using a unique name:

```powershell
python scripts\lab_capture.py `
  --source <camera-index-or-stream-url> `
  --name uwm_20261030_test01 `
  --duration 25 `
  --save-preview
```

Camera mode measures delivered FPS for about three seconds before writing. Ask the operator to wait until the console prints `Recording to ...` before starting any meaningful motion.

Verify all of the following before the production run:

- `outputs/lab/uwm_20261030_test01.mp4` opens;
- `outputs/lab/uwm_20261030_test01_preview.mp4` opens and contains the readout panel;
- `_frames.csv`, `_capture.json`, and `_live.jsonl` exist;
- the console does not report a write failure;
- any delivered-rate warning is understood and recorded.

## 6. Record the production batch

For back-to-back batches, prioritize raw capture and process afterward. Start this command before the operator starts the line:

```powershell
python scripts\lab_capture.py `
  --source <camera-index-or-stream-url> `
  --name uwm_20261030_batch01 `
  --run-plan outputs/lab/uwm_20261030_batch01_plan.csv `
  --save-preview
```

Wait for `Recording to ...`, then tell the operator recording is active. Stop with `q` in the preview window or `Ctrl+C`. Do not close the terminal or unplug the camera until the script reports that files were saved.

The command writes:

```text
outputs/lab/uwm_20261030_batch01.mp4
outputs/lab/uwm_20261030_batch01_preview.mp4
outputs/lab/uwm_20261030_batch01_frames.csv
outputs/lab/uwm_20261030_batch01_capture.json
outputs/lab/uwm_20261030_batch01_live.jsonl
```

The raw recording is written on the dataset clock for the existing event thresholds. The preview is written at real speed for the demonstration. Capture sidecars retain wall-clock timing and measured rates.

The live readout is provisional. It assigns recipes by detected live fill order, so a missed pale pour can shift later display IDs. Do not treat live IDs or flags as authoritative until offline counts match.

If there is guaranteed idle time after the batch, `--process` may be added to the recording command. However, post-processing blocks the recorder, and `lab_capture.py` does not propagate `--white-balance` into offline extraction. The safer field workflow is to record first and run the explicit processing command below.

If filming the physical line, clap once in view at the beginning and record the phone filename in the notes. Do not obstruct the camera or enter a restricted area for synchronization.

## 7. Process and verify a captured batch

Recordings made by `lab_capture.py` are already on the dataset clock. Do not add `--true-rate`:

```powershell
python scripts\extract_vials.py `
  --video-file outputs/lab/uwm_20261030_batch01.mp4 `
  --run-plan outputs/lab/uwm_20261030_batch01_plan.csv `
  --data-origin real_line
```

If `lab_check` showed that lighting differed from the dataset days, create the authoritative records with white-patch correction:

```powershell
python scripts\extract_vials.py `
  --video-file outputs/lab/uwm_20261030_batch01.mp4 `
  --run-plan outputs/lab/uwm_20261030_batch01_plan.csv `
  --data-origin real_line `
  --white-balance white_patch `
  --reuse-signals
```

The output directory is based on the video stem:

```text
outputs/vials/uwm_20261030_batch01/
```

Verify:

```powershell
python scripts\staff_lab.py verify `
  --name uwm_20261030_batch01 `
  --plan outputs\lab\uwm_20261030_batch01_plan.csv

Test-Path outputs/vials/uwm_20261030_batch01/records.jsonl
(Get-Content outputs/vials/uwm_20261030_batch01/records.jsonl | Measure-Object -Line).Lines
Import-Csv outputs/vials/uwm_20261030_batch01/events.csv |
  Select-Object event_idx,n_pours,quality,vial_id,recipe_id,match_note
```

Require `VERIFY OK` before building the automated return package. If verification fails, preserve and return the raw files plus error output; do not change thresholds on the evaluation run.

The console's `N with pours` must equal the number of actual successful fills represented in the plan before vial/recipe IDs are trusted. Also record `N/N vials measured`; pale or clear liquid may produce a structured `low_contrast` or `no_liquid_detected` result without losing the event.

If counts differ, leave IDs unassigned unless the video and operator notes identify the exact missed or extra vial. Never delete an arbitrary plan row merely to make counts match: a missed vial in the middle would shift every later recipe ID.

## Staff-provided file intake

Prefer the original, untrimmed, non-transcoded `vial_fill` file. Copy it; do not move, rename, or overwrite the only original. Use a globally unique working-copy stem because processing outputs are keyed only by `video.stem`. Spaces and periods in a source stem are supported; path separators, control characters, trailing spaces/periods, and Windows device names are rejected.

Record:

- original filename and SHA-256;
- capture/export system and whether it trimmed or transcoded the file;
- camera ID and resolution;
- stored/encoded FPS and actual delivered camera FPS, if known;
- constant versus variable frame rate and any known dropped frames;
- wall-clock start/end;
- whether playback is real-time or on the Dataset 2 accelerated clock.

The stored FPS alone cannot determine clock mode. A 30 fps file may be either real-time or dataset-clock. For a continuous recording:

```text
encoded duration = frame count / stored FPS
wall duration / encoded duration ~= 1.0   -> true-rate file
wall duration / encoded duration ~= 1.215 -> Dataset 2 clock
```

A burned-in clock provides another check: approximately 73 seconds of clock advance during 60 playback seconds indicates the Dataset 2 clock; approximately 60 indicates true rate. If the mode remains unknown, return the untouched file and mark any processed result provisional. Do not select the mode that merely produces a more convenient vial count.

Inspect basic file properties without rewriting it:

```powershell
python -c "import cv2,sys; p=sys.argv[1]; c=cv2.VideoCapture(p); n=int(c.get(cv2.CAP_PROP_FRAME_COUNT)); f=c.get(cv2.CAP_PROP_FPS); w=int(c.get(cv2.CAP_PROP_FRAME_WIDTH)); h=int(c.get(cv2.CAP_PROP_FRAME_HEIGHT)); print(dict(path=p,width=w,height=h,frames=n,stored_fps=f,encoded_seconds=(n/f if f else None)))" '<working-copy-path>'
```

Process one staff file at a time. A file exported by the same CSI system in the same format as Dataset 2 is already on the dataset clock:

```powershell
python scripts\extract_vials.py `
  --video-file '<working-copy-path>' `
  --run-plan '<batch-plan-path>' `
  --data-origin real_line
```

For a file explicitly confirmed to play at its true delivered rate, add `--true-rate`:

```powershell
python scripts\extract_vials.py `
  --video-file '<working-copy-path>' `
  --run-plan '<batch-plan-path>' `
  --data-origin real_line `
  --true-rate
```

`--true-rate` applies the fixed 1.215 Dataset 2 normalization. Current extraction is frame-index based and does not support arbitrary clock ratios or variable-frame-rate timestamps. Return such a source unchanged with its metadata rather than silently treating it as supported.

The generated records retain the source basename and `real_line` origin. `extraction.json` also records the selected clock mode, stored/analysis FPS, run plan, processing options, and counts. It does not embed the original SHA-256, wall times, delivered FPS, or transcode history; keep those facts in the session notes next to the records.

After processing, the helper supports a staff-file mode that does not require `lab_capture` preview/timing sidecars. Use the working copy's stem as `--name`:

```powershell
python scripts\staff_lab.py verify `
  --name <unique-working-copy-stem> `
  --source-video '<working-copy-path>' `
  --plan '<batch-plan-path>'

python scripts\staff_lab.py package `
  --name <unique-working-copy-stem> `
  --source-video '<working-copy-path>' `
  --plan '<batch-plan-path>' `
  --notes '<completed-batch-notes-path>' `
  --destination 'outputs\handoff\<unique-working-copy-stem>'
```

The source video is copied byte-for-byte into the package and included in `SHA256SUMS.txt`. Packaging refuses blank required notes, a dirty source checkout, missing artifacts, count/ID mismatches, or an existing destination.

If staff explicitly accepted non-640x480 footage as calibration-only during preflight, add `--allow-geometry-mismatch` to both `verify` and `package`. This only permits a checksummed calibration handoff; it does not claim that the configured detector geometry is valid.

## 8. Build a checksummed return package

Do not commit the package. Use approved encrypted/removable storage or an approved shared folder.

Complete every required field in the per-batch notes, then confirm the release checkout is unchanged. Packaging cross-checks the run name, packaged recording filename, plan filename, successful-fill count, and clock mode against the verified artifacts and `extraction.json`:

```powershell
git status --porcelain --untracked-files=all
```

This must print nothing (ignored `.venv/` and `outputs/` are not reported). Use the staff helper; it runs verification first, refuses dirty source or an existing destination, copies atomically, records the exact Git revision, and hashes every packaged file:

```powershell
python scripts\staff_lab.py package `
  --name uwm_20261030_batch01 `
  --plan outputs\lab\uwm_20261030_batch01_plan.csv `
  --notes outputs\lab\uwm_20261030_batch01_notes.md `
  --destination outputs\handoff\uwm_20261030_batch01
```

The resulting structure is:

```text
uwm_20261030_batch01/
  raw/             untouched lab_capture recording
  preview/         readout-panel MP4
  metadata/        frame/capture/live/event/signal/manifest/extraction files and source revision
  records/         records.json and records.jsonl
  plan/            exact run plan
  notes/           operator/session notes
  SHA256SUMS.txt
```

Copy rather than move source files. For every staff-provided original, retain its original filename and checksum in the notes even when the working copy has a unique name.

The manual checksum command below is a fallback for an additional staff-provided original or sidecar that is not part of the automated capture package:

```powershell
$package = (Resolve-Path '<path-to-uwm_20261030_return>').Path
$files = Get-ChildItem -LiteralPath $package -File -Recurse |
  Where-Object Name -ne 'SHA256SUMS.txt' |
  Sort-Object FullName
$lines = foreach ($file in $files) {
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $relative = $file.FullName.Substring($package.Length + 1).Replace('\', '/')
    "$hash  $relative"
}
$lines | Set-Content -LiteralPath (Join-Path $package 'SHA256SUMS.txt') -Encoding utf8
```

Verify the copied package on the destination, not only the source laptop:

```powershell
$package = (Resolve-Path '<destination-package-path>').Path
$failures = foreach ($line in Get-Content (Join-Path $package 'SHA256SUMS.txt')) {
    if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') { "Malformed checksum line: $line"; continue }
    $expected = $Matches[1]
    $path = Join-Path $package $Matches[2]
    if (-not (Test-Path -LiteralPath $path)) { "Missing: $($Matches[2])"; continue }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($actual -ne $expected) { "Hash mismatch: $($Matches[2])" }
}
if ($failures) { $failures; throw 'Return package verification failed.' }
'Return package verification passed.'
```

Do not delete the laptop copy until the team confirms the destination package and checksum verification.

## 9. Fallback and error handling

| Situation | Safe response |
| --- | --- |
| Direct camera access denied | Ask staff for the original `vial_fill` recording and the clock/capture metadata above. Do not spend the slot bypassing permissions. |
| Camera not enumerated | Confirm Windows privacy access and that no other application owns it. Try the staff-provided stream or direct numeric index. Fall back to staff capture. |
| Resolution is not 640 x 480 | Ask staff whether the approved capture can use 640 x 480. Otherwise record unchanged, note the resolution, and treat the run as calibration data. |
| Camera-shift check fails | Record unchanged and preserve the overlay. Recalibrate later; do not tune and then call the same run independent evaluation. |
| Recorder warns delivered FPS changed | Preserve the first recording. If time and staff permit, repeat with `--fps <reported-delivered-rate>` and a new name. |
| MP4 writer cannot open | Preserve console output and use the staff capture system. Do not install random codecs or transcode the only source during the slot. |
| Preview stays `no carrier` | Record raw video and note it. A moved view or collar may need later geometry calibration. |
| Pale/clear vial is not measured | Preserve the event and structured failure. Do not lower thresholds during the evaluation run. |
| Plan and detected count differ | Keep IDs unassigned. Use video plus operator notes to identify the exact discrepancy before reprocessing. |
| Processing crashes or produces no `records.jsonl` | Keep raw video, plan, notes, console error, source revision, and checksum. Retry off-line; capture success does not depend on same-day extraction. |
| Clock mode is unknown or file is variable-rate | Preserve original and metadata; mark output provisional. Current code cannot infer or faithfully normalize arbitrary/VFR timing. |
| Power or disk becomes unsafe | Stop capture with `q`/`Ctrl+C`, wait for file close, and back up completed/partial artifacts. Do not hard-power-off during a write. |

## Agent handoff summary

An agent receiving the package should first verify `SHA256SUMS.txt`, read the plan and notes, confirm the source revision, and determine the clock mode before reprocessing. It must preserve `real_line` provenance, keep the material out of training, and leave recipe IDs null when event-to-plan alignment is uncertain. Any camera-geometry or threshold change made from a run converts that run into calibration evidence; evaluate the change on a different run.
