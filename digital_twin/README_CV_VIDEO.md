# ProcessDNA: Isaac Sim + MAIC CV presentation render

This script should live on the **`feature/digital-twin` branch of `MAIC`**, under `digital_twin/tools/render_cv_demo.py`. It renders the existing CSI FillCam USD animation on the GB10 and **runs `vialcv.detect.detect_vial_color()` directly on each captured camera frame**, then composites the camera and real CV results in a 1920×1080 video frame. It also writes the per-frame structured inspection record. It **does not** use a finished video as its detection input.

Requirements: GB10 `~/csi_digital_twin_v1` with `~/isaacsim`; and the MAIC repository's **merged/approved** `vialcv` code on GB10 at `~/MAIC/vialcv`, plus any needed `configs/` and Python dependencies. Until MAIC actually contains `vialcv`, its integration cannot be claimed complete. The script will fail visibly instead of drawing a fake detection.

## Copy code to GB10 (Windows PowerShell)

```powershell
scp "$env:USERPROFILE\MAIC\digital_twin\tools\render_cv_demo.py" hackathon18@spark8.ai.msoe.edu:~/csi_digital_twin_v1/tools/
ssh hackathon18@spark8.ai.msoe.edu "mkdir -p ~/MAIC"
scp -r "$env:USERPROFILE\MAIC\vialcv" hackathon18@spark8.ai.msoe.edu:~/MAIC/
# Only when MAIC/configs exists:
scp -r "$env:USERPROFILE\MAIC\configs" hackathon18@spark8.ai.msoe.edu:~/MAIC/
```

## Validate the existing detector on one frame (GB10)

```bash
cd ~/csi_digital_twin_v1
python3 -m py_compile tools/render_cv_demo.py
~/isaacsim/python.sh tools/render_cv_demo.py --cv-root ~/MAIC \
  --offline-frame outputs/clean_final_frames/frame_0350.png \
  --out-dir outputs/CV_preview_check
```

Automatic detection is attempted by default. If it fails, ask the CV owner to validate a FillCam-specific camera config. For a manual-ROI **CV color measurement** test (not automatic localization):

```bash
~/isaacsim/python.sh tools/render_cv_demo.py --cv-root ~/MAIC \
  --offline-frame outputs/clean_final_frames/frame_0350.png \
  --roi 290 290 35 55 --out-dir outputs/CV_roi_preview
```

`cv_preview.png` will be in the chosen output folder.

## Render the video at full HD

Only after successful CV preview:

```bash
cd ~/csi_digital_twin_v1
nohup ~/isaacsim/python.sh tools/render_cv_demo.py \
  --cv-root ~/MAIC --start 1 --end 686 --fps 30 \
  --subframes 8 --render-width 1280 --render-height 960 \
  --save-camera-frames \
  --out-dir outputs/ProcessDNA_Integrated_CV_30 \
  > outputs/ProcessDNA_CV_run.log 2>&1 < /dev/null &
disown
```

For 60 FPS at original simulation duration, change `--fps 30` to `--fps 60` **and choose a different `--out-dir`**. At a 30 timecodes/s stage, this samples 1371 intermediate times, rather than playing 686 frames twice as fast.

```bash
tail -n 10 outputs/ProcessDNA_CV_run.log
find outputs/ProcessDNA_Integrated_CV_30/presentation_frames -name '*.png' | wc -l
```

`DONE` confirms that all frames have been written. The script saves `ProcessDNA_CV_Preview.avi` (MJPEG working video), lossless `presentation_frames/` (1920×1080, suitable for final encode), optional raw `camera_frames/`, `inspections.jsonl`, and `manifest.json`.

## Make the presentation MP4 (Windows PowerShell)

Download the MJPEG master AVI:

```powershell
scp hackathon18@spark8.ai.msoe.edu:~/csi_digital_twin_v1/outputs/ProcessDNA_Integrated_CV_30/ProcessDNA_CV_Preview.avi "$env:USERPROFILE\Downloads\"
cd "$env:USERPROFILE\Downloads"
ffmpeg -i ProcessDNA_CV_Preview.avi -c:v libx264 -crf 17 -preset slow -pix_fmt yuv420p -movflags +faststart ProcessDNA_CV_Final_1080p.mp4
```

If exact per-pixel quality matters, get the original `presentation_frames/` PNGs and encode with `ffmpeg -framerate 30 -i frame_%05d.png -c:v libx264 -crf 16 -preset slow -pix_fmt yuv420p ProcessDNA_CV_Final_1080p.mp4` instead. The source images, not 640x480 MP4 upscaling, should drive the final export.

## Accuracy limitations

- The camera frame **is rendered from Isaac Sim during execution**; the detector runs immediately on its pixels. The sidebar is an output composite, not 3D geometry in the USD stage.
- `ROI MEASURED` explicitly distinguishes manual ROI measurement from automatically localized `VIAL LOCATED`.
- When the detector fails it reports `INSPECTION FAILED` and never invents a measurement or factory PASS/FAIL outcome.
- Simulated pixels and their CV measurements do **not** imply physically validated fluid carryover or recipe correctness. The current CSI asset uses a prerecorded animation and approximate liquid appearance.
- `data_origin: digital_twin` is preserved in the inspection records.
- Keep PNG/video datasets and CSI USD assets outside Git. Commit code and documentation only.
